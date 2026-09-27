from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, HttpUrl


class PlanType(str, Enum):
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    BUSINESS = "business"


class BillingPlan(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    tier: PlanType
    price_monthly_rub: int
    price_yearly_rub: int | None
    documents_per_month: int
    api_keys_limit: int
    rate_limit_per_minute: int
    features: list[str]
    stripe_price_id_monthly: str | None
    stripe_price_id_yearly: str | None
    is_active: bool


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    UNPAID = "unpaid"
    TRIALING = "trialing"
    INCOMPLETE = "incomplete"


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tier: PlanType
    status: SubscriptionStatus
    current_period_start: datetime
    current_period_end: datetime
    cancel_at_period_end: bool
    documents_used: int
    documents_limit: int
    stripe_subscription_id: str | None


class CheckoutSessionRequest(BaseModel):
    price_id: str
    success_url: HttpUrl
    cancel_url: HttpUrl
    promotion_code: str | None = None


class CheckoutSessionResponse(BaseModel):
    checkout_url: str
    session_id: str


class CustomerPortalRequest(BaseModel):
    return_url: HttpUrl


class CustomerPortalResponse(BaseModel):
    portal_url: str


class UsageStats(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    current_period_start: datetime
    current_period_end: datetime
    documents_used: int
    documents_limit: int
    api_calls_today: int
    api_calls_this_month: int
    top_document_types: list[dict]
    average_processing_time_ms: float


class InvoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    amount_due: Decimal
    amount_paid: Decimal
    currency: str
    status: str
    invoice_pdf: str | None
    hosted_invoice_url: str | None
    created_at: datetime
    period_start: datetime
    period_end: datetime
