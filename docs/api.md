# DocParser.ru API Documentation

## Base URL
- Development: `http://localhost:8000/api/v1`
- Production: `https://api.docparser.ru/api/v1`

## Authentication

### JWT (User-facing)
```
Authorization: Bearer <access_token>
```

### API Key (Server-to-server)
```
X-API-Key: dp_xxxxxxxxxxxxxxxxxxxxxxxx
```

## Endpoints

### Authentication

#### Register
```http
POST /auth/register
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "securepassword123",
  "full_name": "Ivan Ivanov",
  "company_name": "OOO Romashka"
}
```

#### Login
```http
POST /auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "securepassword123"
}
```

Response:
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

#### Create API Key
```http
POST /auth/api-keys
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "Production Server",
  "expires_in_days": 365
}
```

Response (key shown only once):
```json
{
  "id": "uuid",
  "key_prefix": "dp_",
  "key": "dp_xxxxxxxxxxxxxxxxxxxxxxxx",
  "name": "Production Server",
  "is_active": true,
  "created_at": "2024-01-01T00:00:00Z"
}
```

### Documents

#### Upload Document (async, JWT)
```http
POST /documents/upload
Authorization: Bearer <token>
Content-Type: multipart/form-data

file: <binary>
document_type: receipt_kkt (optional)
webhook_url: https://your-app.com/webhook (optional)
```

#### Parse Document (sync, API Key)
```http
POST /documents/parse
X-API-Key: dp_xxxxxxxxxxxxxxxxxxxxxxxx
Content-Type: multipart/form-data

file: <binary>
document_type: receipt_kkt (optional)
return_raw_text: false
```

#### List Documents
```http
GET /documents?page=1&page_size=20&status=completed&type=receipt_kkt
Authorization: Bearer <token>
```

#### Get Document Result
```http
GET /documents/{document_id}
Authorization: Bearer <token>
```

Response:
```json
{
  "id": "uuid",
  "filename": "receipt.jpg",
  "mime_type": "image/jpeg",
  "file_size": 102400,
  "document_type": "receipt_kkt",
  "status": "completed",
  "parsed_data": {
    "fiscal_number": "9280440300007971",
    "fiscal_document_number": "141637",
    "fiscal_sign": "4087570038",
    "date_time": "2024-01-01T12:00:00",
    "total_sum": "1000.00",
    "seller": {
      "name": "ИП Иванов И.И.",
      "inn": "7701234567",
      "address": "г. Москва, ул. Ленина, д. 1"
    },
    "items": [
      {
        "name": "Товар 1",
        "price": "100.00",
        "quantity": "2",
        "sum": "200.00",
        "vat_rate": "20",
        "vat_sum": "33.33"
      }
    ],
    "is_validated_fns": true
  },
  "processing_time_ms": 1500,
  "created_at": "2024-01-01T00:00:00Z",
  "completed_at": "2024-01-01T00:00:02Z"
}
```

### Billing

#### Get Plans
```http
GET /billing/plans
```

#### Get Current Subscription
```http
GET /billing/subscription
Authorization: Bearer <token>
```

#### Create Checkout Session
```http
POST /billing/checkout
Authorization: Bearer <token>
Content-Type: application/json

{
  "price_id": "price_starter_monthly",
  "success_url": "https://yourapp.com/success",
  "cancel_url": "https://yourapp.com/cancel"
}
```

#### Customer Portal
```http
POST /billing/portal
Authorization: Bearer <token>
Content-Type: application/json

{
  "return_url": "https://yourapp.com/settings"
}
```

#### Usage Statistics
```http
GET /billing/usage
Authorization: Bearer <token>
```

### Webhooks

#### Stripe Webhook (configured in Stripe Dashboard)
```http
POST /webhooks/stripe
Stripe-Signature: sig_xxx
Content-Type: application/json

{...stripe event...}
```

#### Client Webhook Registration
```http
POST /webhooks/client
Authorization: Bearer <token>
Content-Type: application/json

{
  "document_id": "uuid",
  "webhook_url": "https://your-app.com/docparser-webhook"
}
```

Client receives:
```http
POST https://your-app.com/docparser-webhook
Content-Type: application/json
X-DocParser-Event: document.parsed
X-DocParser-Document-ID: uuid
X-DocParser-Signature: sha256=...

{
  "event": "document.parsed",
  "timestamp": "2024-01-01T00:00:00Z",
  "document": {
    "id": "uuid",
    "filename": "receipt.jpg",
    "document_type": "receipt_kkt",
    "status": "completed",
    "parsed_data": {...},
    "processing_time_ms": 1500
  }
}
```

## Error Responses

```json
{
  "error": "validation_error",
  "message": "Request validation failed",
  "details": [
    {"loc": ["body", "email"], "msg": "invalid email", "type": "value_error.email"}
  ]
}
```

```json
{
  "error": "authentication_error",
  "message": "Invalid or expired token"
}
```

```json
{
  "error": "rate_limit_exceeded",
  "message": "Rate limit exceeded",
  "details": {"retry_after": 60}
}
```

## Rate Limits

| Tier | Requests/minute |
|------|-----------------|
| Free | 10 |
| Starter | 100 |
| Pro | 500 |
| Business | 2000 |

Headers:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 45
```

## Document Types

| Type | Description |
|------|-------------|
| `receipt_kkt` | Чек ККТ (ФЗ-54) |
| `upd` | УПД |
| `ukd` | УКД |
| `invoice` | Счёт-фактура |
| `invoice_correction` | ИСФ |
| `act` | Акт выполненных работ |
| `torg12` | ТОРГ-12 |
| `ttn` | ТТН |
| `selfemployed` | Чек самозанятого |