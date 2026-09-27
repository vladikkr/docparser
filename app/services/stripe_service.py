from datetime import datetime

import stripe
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Subscription, User, UserTier

logger = structlog.get_logger()

stripe.api_key = settings.STRIPE_SECRET_KEY
stripe.api_version = settings.STRIPE_API_VERSION


TIER_BY_PRICE = {
    settings.STRIPE_PRICE_STARTER: UserTier.STARTER,
    settings.STRIPE_PRICE_PRO: UserTier.PRO,
    settings.STRIPE_PRICE_BUSINESS: UserTier.BUSINESS,
}


async def handle_stripe_event(event: dict, db: AsyncSession) -> None:
    """Handle incoming Stripe webhook events"""
    event_type = event.get("type")
    data = event.get("data", {}).get("object", {})

    logger.info("stripe_event", event_type=event_type, event_id=event.get("id"))

    try:
        if event_type == "customer.subscription.created":
            await handle_subscription_created(data, db)
        elif event_type == "customer.subscription.updated":
            await handle_subscription_updated(data, db)
        elif event_type == "customer.subscription.deleted":
            await handle_subscription_deleted(data, db)
        elif event_type == "invoice.payment_succeeded":
            await handle_payment_succeeded(data, db)
        elif event_type == "invoice.payment_failed":
            await handle_payment_failed(data, db)
        elif event_type == "customer.created":
            await handle_customer_created(data, db)
        else:
            logger.debug("unhandled_stripe_event", event_type=event_type)
    except Exception as e:
        logger.exception("stripe_event_handling_failed", event_type=event_type, error=str(e))
        raise


async def handle_subscription_created(data: dict, db: AsyncSession) -> None:
    subscription_id = data.get("id")
    customer_id = data.get("customer")
    price_id = data.get("items", {}).get("data", [{}])[0].get("price", {}).get("id")
    status = data.get("status")
    current_period_start = datetime.fromtimestamp(data.get("current_period_start", 0))
    current_period_end = datetime.fromtimestamp(data.get("current_period_end", 0))
    cancel_at_period_end = data.get("cancel_at_period_end", False)

    # Find user by Stripe customer ID
    result = await db.execute(select(User).where(User.stripe_customer_id == customer_id))
    user = result.scalar_one_or_none()

    if not user:
        logger.warning("user_not_found_for_stripe_customer", customer_id=customer_id)
        return

    tier = TIER_BY_PRICE.get(price_id, UserTier.FREE)

    # Update user
    user.tier = tier
    user.stripe_subscription_id = subscription_id
    user.current_period_end = current_period_end

    # Create/update subscription record
    result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    subscription = result.scalar_one_or_none()

    if subscription:
        subscription.stripe_subscription_id = subscription_id
        subscription.stripe_price_id = price_id
        subscription.stripe_current_period_start = current_period_start
        subscription.stripe_current_period_end = current_period_end
        subscription.stripe_cancel_at_period_end = cancel_at_period_end
        subscription.status = status
    else:
        subscription = Subscription(
            user_id=user.id,
            stripe_subscription_id=subscription_id,
            stripe_price_id=price_id,
            stripe_current_period_start=current_period_start,
            stripe_current_period_end=current_period_end,
            stripe_cancel_at_period_end=cancel_at_period_end,
            status=status,
        )
        db.add(subscription)

    await db.commit()
    logger.info("subscription_created", user_id=str(user.id), tier=tier.value)


async def handle_subscription_updated(data: dict, db: AsyncSession) -> None:
    subscription_id = data.get("id")
    price_id = data.get("items", {}).get("data", [{}])[0].get("price", {}).get("id")
    status = data.get("status")
    current_period_start = datetime.fromtimestamp(data.get("current_period_start", 0))
    current_period_end = datetime.fromtimestamp(data.get("current_period_end", 0))
    cancel_at_period_end = data.get("cancel_at_period_end", False)

    result = await db.execute(select(Subscription).where(Subscription.stripe_subscription_id == subscription_id))
    subscription = result.scalar_one_or_none()

    if not subscription:
        logger.warning("subscription_not_found", stripe_subscription_id=subscription_id)
        return

    tier = TIER_BY_PRICE.get(price_id, UserTier.FREE)

    subscription.stripe_price_id = price_id
    subscription.stripe_current_period_start = current_period_start
    subscription.stripe_current_period_end = current_period_end
    subscription.stripe_cancel_at_period_end = cancel_at_period_end
    subscription.status = status

    # Update user tier
    result = await db.execute(select(User).where(User.id == subscription.user_id))
    user = result.scalar_one_or_none()
    if user:
        user.tier = tier
        user.current_period_end = current_period_end

    await db.commit()
    logger.info("subscription_updated", subscription_id=subscription_id, tier=tier.value)


async def handle_subscription_deleted(data: dict, db: AsyncSession) -> None:
    subscription_id = data.get("id")

    result = await db.execute(select(Subscription).where(Subscription.stripe_subscription_id == subscription_id))
    subscription = result.scalar_one_or_none()

    if not subscription:
        return

    subscription.status = "canceled"

    # Downgrade user to free
    result = await db.execute(select(User).where(User.id == subscription.user_id))
    user = result.scalar_one_or_none()
    if user:
        user.tier = UserTier.FREE
        user.stripe_subscription_id = None
        user.current_period_end = None

    await db.commit()
    logger.info("subscription_deleted", subscription_id=subscription_id)


async def handle_payment_succeeded(data: dict, db: AsyncSession) -> None:
    """Handle successful payment - could trigger receipt generation"""
    logger.info("payment_succeeded", invoice_id=data.get("id"))


async def handle_payment_failed(data: dict, db: AsyncSession) -> None:
    """Handle failed payment"""
    logger.warning("payment_failed", invoice_id=data.get("id"))


async def handle_customer_created(data: dict, db: AsyncSession) -> None:
    """Handle new customer creation"""
    logger.info("customer_created", customer_id=data.get("id"))


async def create_stripe_customer(user: User, db: AsyncSession) -> str:
    """Create Stripe customer for user"""
    if user.stripe_customer_id:
        return user.stripe_customer_id

    customer = stripe.Customer.create(
        email=user.email,
        name=user.full_name or user.email,
        metadata={"user_id": str(user.id)},
    )
    user.stripe_customer_id = customer.id
    await db.commit()
    return customer.id


async def cancel_subscription(user: User, db: AsyncSession) -> bool:
    """Cancel user's subscription at period end"""
    if not user.stripe_subscription_id:
        return False

    stripe.Subscription.modify(
        user.stripe_subscription_id,
        cancel_at_period_end=True,
    )
    return True


async def resume_subscription(user: User, db: AsyncSession) -> bool:
    """Resume canceled subscription"""
    if not user.stripe_subscription_id:
        return False

    stripe.Subscription.modify(
        user.stripe_subscription_id,
        cancel_at_period_end=False,
    )
    return True
