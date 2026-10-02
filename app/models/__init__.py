import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class UserTier(str, enum.Enum):
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    BUSINESS = "business"


class DocumentType(str, enum.Enum):
    RECEIPT_KKT = "receipt_kkt"
    UPD = "upd"
    UKD = "ukd"
    INVOICE = "invoice"
    INVOICE_CORRECTION = "invoice_correction"
    ACT = "act"
    TORG12 = "torg12"
    TTN = "ttn"
    SELFEMPLOYED = "selfemployed"
    UNKNOWN = "unknown"


class DocumentStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255))
    company_name = Column(String(255))
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    tier = Column(Enum(UserTier), default=UserTier.FREE, nullable=False)
    stripe_customer_id = Column(String(255), unique=True, index=True)
    stripe_subscription_id = Column(String(255), unique=True, index=True)
    current_period_end = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    api_keys = relationship("APIKey", back_populates="user", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="user", cascade="all, delete-orphan")
    usage_logs = relationship("UsageLog", back_populates="user", cascade="all, delete-orphan")


class APIKey(Base):
    __tablename__ = "api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    key_hash = Column(String(255), nullable=False, unique=True, index=True)
    key_prefix = Column(String(20), nullable=False)
    name = Column(String(255))
    is_active = Column(Boolean, default=True)
    last_used_at = Column(DateTime)
    expires_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="api_keys")


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    api_key_id = Column(UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="SET NULL"), index=True)

    filename = Column(String(500))
    mime_type = Column(String(100))
    file_size = Column(BigInteger)
    storage_path = Column(String(500))

    document_type = Column(Enum(DocumentType), default=DocumentType.UNKNOWN, nullable=False)
    status = Column(Enum(DocumentStatus), default=DocumentStatus.PENDING, nullable=False)

    parsed_data = Column(Text)  # JSON
    error_message = Column(Text)
    processing_time_ms = Column(Integer)

    webhook_url = Column(String(500))
    webhook_status = Column(String(50))
    webhook_attempts = Column(Integer, default=0)
    webhook_last_attempt = Column(DateTime)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime)

    user = relationship("User", back_populates="documents")


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    api_key_id = Column(UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="SET NULL"), index=True)

    endpoint = Column(String(100), nullable=False)
    document_type = Column(Enum(DocumentType), nullable=True)
    status_code = Column(Integer)
    response_time_ms = Column(Integer)
    request_size_bytes = Column(BigInteger)
    response_size_bytes = Column(BigInteger)

    ip_address = Column(String(45))
    user_agent = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", back_populates="usage_logs")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)

    stripe_subscription_id = Column(String(255), unique=True, index=True)
    stripe_price_id = Column(String(255))
    stripe_current_period_start = Column(DateTime)
    stripe_current_period_end = Column(DateTime)
    stripe_cancel_at_period_end = Column(Boolean, default=False)
    status = Column(String(50))

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
