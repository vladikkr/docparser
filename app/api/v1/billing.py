from datetime import datetime

import stripe
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.core.exceptions import ValidationError
from app.database import get_db
from app.models import Subscription, User
from app.schemas import (
    BillingPlan,
    CheckoutSessionRequest,
    CheckoutSessionResponse,
    CustomerPortalRequest,
    CustomerPortalResponse,
    InvoiceResponse,
    PlanType,
    SubscriptionResponse,
    UsageStats,
)

logger = structlog.get_logger()

if settings.STRIPE_SECRET_KEY:
    stripe.api_key = settings.STRIPE_SECRET_KEY
    stripe.api_version = settings.STRIPE_API_VERSION

router = APIRouter(prefix="/billing", tags=["billing"])


def _require_stripe() -> None:
    if not settings.stripe_configured:
        raise HTTPException(
            status_code=503,
            detail="Billing is not configured on this deployment",
        )


PLANS = {
    PlanType.FREE: BillingPlan(
        id="free",
        name="Free",
        tier=PlanType.FREE,
        price_monthly_rub=0,
        price_yearly_rub=0,
        documents_per_month=50,
        api_keys_limit=1,
        rate_limit_per_minute=settings.RATE_LIMIT_FREE,
        features=["Basic parsing", "50 docs/month", "1 API key", "Email support"],
        stripe_price_id_monthly=None,
        stripe_price_id_yearly=None,
        is_active=True,
    ),
    PlanType.STARTER: BillingPlan(
        id="starter",
        name="Starter",
        tier=PlanType.STARTER,
        price_monthly_rub=2900,
        price_yearly_rub=29000,
        documents_per_month=1000,
        api_keys_limit=3,
        rate_limit_per_minute=settings.RATE_LIMIT_STARTER,
        features=["All document types", "1000 docs/month", "3 API keys", "Webhooks", "Priority queue"],
        stripe_price_id_monthly=settings.STRIPE_PRICE_STARTER,
        stripe_price_id_yearly=None,
        is_active=True,
    ),
    PlanType.PRO: BillingPlan(
        id="pro",
        name="Pro",
        tier=PlanType.PRO,
        price_monthly_rub=9900,
        price_yearly_rub=99000,
        documents_per_month=10000,
        api_keys_limit=10,
        rate_limit_per_minute=settings.RATE_LIMIT_PRO,
        features=["All Starter features", "10000 docs/month", "10 API keys", "SLA 99.9%", "Batch upload", "1C/MoySklad webhooks"],
        stripe_price_id_monthly=settings.STRIPE_PRICE_PRO,
        stripe_price_id_yearly=None,
        is_active=True,
    ),
    PlanType.BUSINESS: BillingPlan(
        id="business",
        name="Business",
        tier=PlanType.BUSINESS,
        price_monthly_rub=29900,
        price_yearly_rub=299000,
        documents_per_month=50000,
        api_keys_limit=100,
        rate_limit_per_minute=settings.RATE_LIMIT_BUSINESS,
        features=["All Pro features", "50000 docs/month", "Unlimited API keys", "Dedicated queue", "Custom fields", "Manager", "On-premise option"],
        stripe_price_id_monthly=settings.STRIPE_PRICE_BUSINESS,
        stripe_price_id_yearly=None,
        is_active=True,
    ),
}


@router.get("/plans", response_model=list[BillingPlan])
async def get_plans():
    return list(PLANS.values())


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    subscription = result.scalar_one_or_none()

    if not subscription:
        # Return free tier info
        plan = PLANS[PlanType.FREE]
        return SubscriptionResponse(
            id=user.id,
            tier=user.tier,
            status="active",
            current_period_start=datetime.utcnow(),
            current_period_end=datetime.utcnow(),
            cancel_at_period_end=False,
            documents_used=0,
            documents_limit=plan.documents_per_month,
            stripe_subscription_id=None,
        )

    # Count documents this period
    from sqlalchemy import func

    from app.models import Document, DocumentStatus
    count_result = await db.execute(
        select(func.count(Document.id))
        .where(
            Document.user_id == user.id,
            Document.status == DocumentStatus.COMPLETED,
            Document.created_at >= subscription.stripe_current_period_start,
        )
    )
    docs_used = count_result.scalar() or 0

    plan = PLANS.get(PlanType(subscription.stripe_price_id.split("_")[-1]) if subscription.stripe_price_id else user.tier, PLANS[PlanType.FREE])

    return SubscriptionResponse(
        id=subscription.id,
        tier=user.tier,
        status=subscription.status,
        current_period_start=subscription.stripe_current_period_start,
        current_period_end=subscription.stripe_current_period_end,
        cancel_at_period_end=subscription.stripe_cancel_at_period_end,
        documents_used=docs_used,
        documents_limit=plan.documents_per_month,
        stripe_subscription_id=subscription.stripe_subscription_id,
    )


@router.post("/checkout", response_model=CheckoutSessionResponse)
async def create_checkout_session(
    request: CheckoutSessionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_stripe()
    if user.tier == PlanType.FREE and request.price_id == settings.STRIPE_PRICE_FREE:
        raise ValidationError("Already on free plan")

    # Create or get Stripe customer
    if not user.stripe_customer_id:
        customer = stripe.Customer.create(
            email=user.email,
            name=user.full_name or user.email,
            metadata={"user_id": str(user.id)},
        )
        user.stripe_customer_id = customer.id
        await db.commit()

    session = stripe.checkout.Session.create(
        customer=user.stripe_customer_id,
        payment_method_types=["card"],
        line_items=[{"price": request.price_id, "quantity": 1}],
        mode="subscription",
        success_url=str(request.success_url),
        cancel_url=str(request.cancel_url),
        subscription_data={
            "metadata": {"user_id": str(user.id)},
        },
        allow_promotion_codes=True,
    )

    return CheckoutSessionResponse(checkout_url=session.url, session_id=session.id)


@router.post("/portal", response_model=CustomerPortalResponse)
async def create_portal_session(
    request: CustomerPortalRequest,
    user: User = Depends(get_current_user),
):
    _require_stripe()
    if not user.stripe_customer_id:
        raise ValidationError("No billing account found")

    session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=str(request.return_url),
    )

    return CustomerPortalResponse(portal_url=session.url)


@router.get("/usage", response_model=UsageStats)
async def get_usage_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func

    from app.models import Document, DocumentStatus, UsageLog

    # Current period from subscription or default to month start
    period_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    period_end = datetime.utcnow()

    # Documents used
    docs_result = await db.execute(
        select(func.count(Document.id)).where(
            Document.user_id == user.id,
            Document.status == DocumentStatus.COMPLETED,
            Document.created_at >= period_start,
        )
    )
    docs_used = docs_result.scalar() or 0

    # API calls today
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    calls_today = await db.execute(
        select(func.count(UsageLog.id)).where(
            UsageLog.user_id == user.id,
            UsageLog.created_at >= today_start,
        )
    )

    # API calls this month
    calls_month = await db.execute(
        select(func.count(UsageLog.id)).where(
            UsageLog.user_id == user.id,
            UsageLog.created_at >= period_start,
        )
    )

    # Top document types
    types_result = await db.execute(
        select(Document.document_type, func.count(Document.id))
        .where(
            Document.user_id == user.id,
            Document.created_at >= period_start,
        )
        .group_by(Document.document_type)
        .order_by(func.count(Document.id).desc())
        .limit(5)
    )
    top_types = [{"type": t.value, "count": c} for t, c in types_result.all()]

    # Average processing time
    avg_time_result = await db.execute(
        select(func.avg(Document.processing_time_ms)).where(
            Document.user_id == user.id,
            Document.status == DocumentStatus.COMPLETED,
            Document.processing_time_ms.isnot(None),
        )
    )
    avg_time = avg_time_result.scalar() or 0

    plan = PLANS.get(user.tier, PLANS[PlanType.FREE])

    return UsageStats(
        current_period_start=period_start,
        current_period_end=period_end,
        documents_used=docs_used,
        documents_limit=plan.documents_per_month,
        api_calls_today=calls_today.scalar() or 0,
        api_calls_this_month=calls_month.scalar() or 0,
        top_document_types=top_types,
        average_processing_time_ms=float(avg_time),
    )


@router.get("/invoices", response_model=list[InvoiceResponse])
async def list_invoices(
    user: User = Depends(get_current_user),
    limit: int = 10,
):
    _require_stripe()
    if not user.stripe_customer_id:
        return []

    invoices = stripe.Invoice.list(
        customer=user.stripe_customer_id,
        limit=limit,
    )

    return [
        InvoiceResponse(
            id=inv.id,
            amount_due=inv.amount_due / 100,
            amount_paid=inv.amount_paid / 100,
            currency=inv.currency,
            status=inv.status,
            invoice_pdf=inv.invoice_pdf,
            hosted_invoice_url=inv.hosted_invoice_url,
            created_at=datetime.fromtimestamp(inv.created),
            period_start=datetime.fromtimestamp(inv.period_start),
            period_end=datetime.fromtimestamp(inv.period_end),
        )
        for inv in invoices.data
    ]
