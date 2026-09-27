import pytest
from httpx import AsyncClient

from app.models import User


class TestAuth:
    @pytest.mark.asyncio
    async def test_register(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "newuser@test.com",
                "password": "password123",
                "full_name": "New User",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@test.com"
        assert data["full_name"] == "New User"
        assert data["tier"] == "free"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, client: AsyncClient, test_user: User):
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": test_user.email,
                "password": "password123",
            },
        )
        assert response.status_code == 400
        assert "already registered" in response.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient, test_user: User):
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": test_user.email,
                "password": "testpassword123",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client: AsyncClient, test_user: User):
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": test_user.email,
                "password": "wrongpassword",
            },
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "nonexistent@test.com",
                "password": "password123",
            },
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_token(self, client: AsyncClient, test_user: User):
        # Login first
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={
                "email": test_user.email,
                "password": "testpassword123",
            },
        )
        refresh_token = login_resp.json()["refresh_token"]

        # Refresh
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data

    @pytest.mark.asyncio
    async def test_get_me(self, client: AsyncClient, auth_headers: dict):
        response = await client.get("/api/v1/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "test@docparser.ru"

    @pytest.mark.asyncio
    async def test_create_api_key(self, client: AsyncClient, auth_headers: dict):
        response = await client.post(
            "/api/v1/auth/api-keys",
            headers=auth_headers,
            json={"name": "Test Key", "expires_in_days": 30},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Key"
        assert "key" in data  # Full key returned only once
        assert data["key"].startswith("dp_")

    @pytest.mark.asyncio
    async def test_list_api_keys(self, client: AsyncClient, auth_headers: dict, test_api_key):
        # Create one first
        await client.post(
            "/api/v1/auth/api-keys",
            headers=auth_headers,
            json={"name": "Key 1"},
        )

        response = await client.get("/api/v1/auth/api-keys", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert len(data["api_keys"]) >= 1

    @pytest.mark.asyncio
    async def test_delete_api_key(self, client: AsyncClient, auth_headers: dict):
        # Create
        create_resp = await client.post(
            "/api/v1/auth/api-keys",
            headers=auth_headers,
            json={"name": "To Delete"},
        )
        key_id = create_resp.json()["id"]

        # Delete
        response = await client.delete(f"/api/v1/auth/api-keys/{key_id}", headers=auth_headers)
        assert response.status_code == 204

        # Verify deleted
        list_resp = await client.get("/api/v1/auth/api-keys", headers=auth_headers)
        assert not any(k["id"] == key_id for k in list_resp.json()["api_keys"])
