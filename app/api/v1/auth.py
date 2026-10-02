from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.core.exceptions import AuthenticationError, NotFoundError, ValidationError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_api_key,
    get_password_hash,
    verify_password,
)
from app.database import get_db
from app.models import APIKey, User, UserTier
from app.schemas import (
    APIKeyCreate,
    APIKeyList,
    APIKeyResponse,
    RefreshTokenRequest,
    Token,
    UserLogin,
    UserRegister,
    UserResponse,
)
from app.utils.helpers import utcnow

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserRegister, db: AsyncSession = Depends(get_db)):
    # Check if email exists
    result = await db.execute(select(User).where(User.email == user_data.email))
    if result.scalar_one_or_none():
        raise ValidationError("Email already registered")

    # Create user
    user = User(
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
        full_name=user_data.full_name,
        company_name=user_data.company_name,
        tier=UserTier.FREE,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return user


@router.post("/login", response_model=Token)
async def login(credentials: UserLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == credentials.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(credentials.password, user.hashed_password):
        raise AuthenticationError("Invalid email or password")

    if not user.is_active:
        raise AuthenticationError("Account is disabled")

    access_token = create_access_token({"sub": str(user.id), "email": user.email})
    refresh_token = create_refresh_token({"sub": str(user.id), "email": user.email})

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/refresh", response_model=Token)
async def refresh_token(request: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(request.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise AuthenticationError("Invalid refresh token")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise AuthenticationError("User not found or inactive")

    access_token = create_access_token({"sub": str(user.id), "email": user.email})
    new_refresh_token = create_refresh_token({"sub": str(user.id), "email": user.email})

    return Token(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    return user


# API Keys management
@router.post("/api-keys", response_model=APIKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    key_data: APIKeyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    full_key, prefix, key_hash = generate_api_key()

    expires_at = None
    if key_data.expires_in_days:
        expires_at = utcnow() + timedelta(days=key_data.expires_in_days)

    api_key = APIKey(
        user_id=user.id,
        key_hash=key_hash,
        key_prefix=prefix,
        name=key_data.name,
        expires_at=expires_at,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    # Return full key only once
    response = APIKeyResponse.model_validate(api_key)
    response.key = full_key
    return response


@router.get("/api-keys", response_model=APIKeyList)
async def list_api_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(APIKey)
        .where(APIKey.user_id == user.id)
        .order_by(APIKey.created_at.desc())
    )
    api_keys = result.scalars().all()
    return APIKeyList(api_keys=api_keys, total=len(api_keys))


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    key_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(APIKey).where(APIKey.id == key_id, APIKey.user_id == user.id)
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise NotFoundError("API Key", str(key_id))

    await db.delete(api_key)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
