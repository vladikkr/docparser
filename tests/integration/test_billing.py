from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


class TestBilling:
    @pytest.mark.asyncio
    async def test_get_plans(self, client: AsyncClient):
        response = await client.get("/api/v1/billing/plans")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 4  # free, starter, pro, business

        tiers = {p["tier"] for p in data}
        assert tiers == {"free", "starter", "pro", "business"}

        free_plan = next(p for p in data if p["tier"] == "free")
        assert free_plan["price_monthly_rub"] == 0
        assert free_plan["documents_per_month"] == 50

    @pytest.mark.asyncio
    async def test_get_subscription_free(self, client: AsyncClient, auth_headers: dict):
        response = await client.get("/api/v1/billing/subscription", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["tier"] == "pro"  # test_user is PRO
        assert data["status"] == "active"

    @pytest.mark.asyncio
    async def test_get_usage_stats(self, client: AsyncClient, auth_headers: dict):
        response = await client.get("/api/v1/billing/usage", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "documents_used" in data
        assert "documents_limit" in data
        assert "api_calls_today" in data

    @pytest.mark.asyncio
    async def test_create_checkout_session(self, client: AsyncClient, auth_headers: dict):
        with patch("stripe.checkout.Session.create") as mock_create, \
             patch("stripe.Customer.create") as mock_customer_create:
            mock_create.return_value = AsyncMock(
                url="https://checkout.stripe.com/pay/xxx",
                id="cs_test_xxx",
            )
            mock_customer_create.return_value = AsyncMock(id="cus_test_xxx")

            response = await client.post(
                "/api/v1/billing/checkout",
                headers=auth_headers,
                json={
                    "price_id": "price_starter_monthly",
                    "success_url": "https://app.com/success",
                    "cancel_url": "https://app.com/cancel",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert "checkout_url" in data
            assert data["checkout_url"].startswith("https://checkout.stripe.com")

    @pytest.mark.asyncio
    async def test_create_customer_portal(self, client: AsyncClient, auth_headers: dict, test_user, db_session):
        # Set up test user with Stripe customer ID
        test_user.stripe_customer_id = "cus_test_xxx"
        await db_session.commit()

        with patch("stripe.billing_portal.Session.create") as mock_create:
            mock_create.return_value = AsyncMock(url="https://billing.stripe.com/portal/xxx")

            response = await client.post(
                "/api/v1/billing/portal",
                headers=auth_headers,
                json={"return_url": "https://app.com/settings"},
            )
            assert response.status_code == 200
            data = response.json()
            assert "portal_url" in data

    @pytest.mark.asyncio
    async def test_list_invoices(self, client: AsyncClient, auth_headers: dict):
        with patch("stripe.Invoice.list") as mock_list:
            mock_list.return_value = AsyncMock(data=[])

            response = await client.get("/api/v1/billing/invoices", headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
