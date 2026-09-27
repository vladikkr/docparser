import pytest
from httpx import AsyncClient


class TestDocuments:
    @pytest.mark.asyncio
    async def test_upload_document_jwt(self, client: AsyncClient, auth_headers: dict, sample_receipt_bytes: bytes, mock_celery_task):
        response = await client.post(
            "/api/v1/documents/upload",
            headers=auth_headers,
            files={"file": ("receipt.jpg", sample_receipt_bytes, "image/jpeg")},
            data={"document_type": "receipt_kkt"},
        )
        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["status"] == "pending"
        assert data["document_type"] == "receipt_kkt"

    @pytest.mark.asyncio
    async def test_upload_document_invalid_type(self, client: AsyncClient, auth_headers: dict):
        response = await client.post(
            "/api/v1/documents/upload",
            headers=auth_headers,
            files={"file": ("test.txt", b"text content", "text/plain")},
        )
        assert response.status_code == 400
        assert "unsupported file type" in response.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_upload_document_too_large(self, client: AsyncClient, auth_headers: dict):
        # Create file larger than 20MB
        large_file = b"x" * (21 * 1024 * 1024)
        response = await client.post(
            "/api/v1/documents/upload",
            headers=auth_headers,
            files={"file": ("large.jpg", large_file, "image/jpeg")},
        )
        assert response.status_code == 400
        assert "too large" in response.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_parse_document_sync(self, client: AsyncClient, api_key_headers: dict, sample_receipt_bytes: bytes, mock_celery_task):
        response = await client.post(
            "/api/v1/documents/parse",
            headers=api_key_headers,
            files={"file": ("receipt.jpg", sample_receipt_bytes, "image/jpeg")},
            data={"document_type": "receipt_kkt"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "document_id" in data
        # /parse returns the result inline, so it finishes within the request
        assert data["status"] in ["completed", "failed"]
        assert data["document_type"] == "receipt_kkt"
        assert data["processing_time_ms"] >= 0

    @pytest.mark.asyncio
    async def test_list_documents(self, client: AsyncClient, auth_headers: dict):
        response = await client.get("/api/v1/documents", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "documents" in data
        assert "total" in data
        assert "page" in data

    @pytest.mark.asyncio
    async def test_list_documents_with_filters(self, client: AsyncClient, auth_headers: dict):
        response = await client.get(
            "/api/v1/documents",
            headers=auth_headers,
            params={"status": "completed", "type": "receipt_kkt", "page": 1, "page_size": 10},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_document(self, client: AsyncClient, auth_headers: dict, sample_receipt_bytes: bytes, mock_celery_task):
        # Upload first
        upload_resp = await client.post(
            "/api/v1/documents/upload",
            headers=auth_headers,
            files={"file": ("receipt.jpg", sample_receipt_bytes, "image/jpeg")},
        )
        doc_id = upload_resp.json()["id"]

        # Get
        response = await client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == doc_id

    @pytest.mark.asyncio
    async def test_get_nonexistent_document(self, client: AsyncClient, auth_headers: dict):
        response = await client.get("/api/v1/documents/00000000-0000-0000-0000-000000000000", headers=auth_headers)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_document(self, client: AsyncClient, auth_headers: dict, sample_receipt_bytes: bytes, mock_celery_task):
        upload_resp = await client.post(
            "/api/v1/documents/upload",
            headers=auth_headers,
            files={"file": ("receipt.jpg", sample_receipt_bytes, "image/jpeg")},
        )
        doc_id = upload_resp.json()["id"]

        response = await client.delete(f"/api/v1/documents/{doc_id}", headers=auth_headers)
        assert response.status_code == 204

        # Verify deleted
        get_resp = await client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers)
        assert get_resp.status_code == 404
