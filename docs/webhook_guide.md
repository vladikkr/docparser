# Настройка клиентских вебхуков

## Обзор

DocParser.ru отправляет HTTP POST запрос на ваш URL когда парсинг документа завершен (успешно или с ошибкой). Это позволяет вашему приложению получать результаты асинхронно без поллинга.

## Регистрация вебхука

### При загрузке документа (один раз)

```http
POST /api/v1/documents/upload
Authorization: Bearer <token>
Content-Type: multipart/form-data

file: <binary>
webhook_url: https://your-app.com/docparser-webhook
```

### Через API ключ (sync parse)

```http
POST /api/v1/documents/parse
X-API-Key: dp_xxxxxxxxxxxxxxxxxxxxxxxx
Content-Type: multipart/form-data

file: <binary>
webhook_url: https://your-app.com/docparser-webhook
```

### Отдельный эндпоинт для регистрации

```http
POST /api/v1/webhooks/client
Authorization: Bearer <token>
Content-Type: application/json

{
  "document_id": "uuid",
  "webhook_url": "https://your-app.com/docparser-webhook"
}
```

## Формат вебхука

### Headers
```
Content-Type: application/json
User-Agent: DocParser.ru Webhook/1.0
X-DocParser-Event: document.parsed
X-DocParser-Document-ID: <document_uuid>
X-DocParser-Signature: sha256=<hex_signature>
```

### Body (успешный парсинг)
```json
{
  "event": "document.parsed",
  "timestamp": "2024-01-01T12:00:00.123456Z",
  "document": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "filename": "receipt.jpg",
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
          "name": "Хлеб Бородинский",
          "price": "50.00",
          "quantity": "2",
          "sum": "100.00",
          "vat_rate": "20",
          "vat_sum": "16.67"
        }
      ],
      "is_validated_fns": true
    },
    "processing_time_ms": 1500,
    "created_at": "2024-01-01T11:59:58Z",
    "completed_at": "2024-01-01T12:00:00Z"
  }
}
```

### Body (ошибка парсинга)
```json
{
  "event": "document.parsed",
  "timestamp": "2024-01-01T12:00:00.123456Z",
  "document": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "filename": "receipt.jpg",
    "document_type": "receipt_kkt",
    "status": "failed",
    "parsed_data": null,
    "error_message": "OCR failed: unable to detect text",
    "processing_time_ms": 500,
    "created_at": "2024-01-01T11:59:58Z",
    "completed_at": "2024-01-01T12:00:00Z"
  }
}
```

## Верификация подписи

Подпись `X-DocParser-Signature` позволяет убедиться, что вебхук пришел от DocParser, а не от злоумышленника.

### Алгоритм

```python
import hmac
import hashlib
import json

WEBHOOK_SECRET = "your-webhook-secret"  # Настроить в DocParser или использовать STRIPE_WEBHOOK_SECRET

def verify_webhook(payload: bytes, signature: str) -> bool:
    """
    payload: raw request body (bytes)
    signature: value of X-DocParser-Signature header (e.g., "sha256=abc123...")
    """
    if not signature.startswith("sha256="):
        return False
    
    expected_signature = signature[7:]  # remove "sha256="
    
    # HMAC-SHA256 of payload with secret
    computed = hmac.new(
        WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    # Constant-time comparison
    return hmac.compare_digest(computed, expected_signature)


# Пример использования в FastAPI
from fastapi import Request, HTTPException, Header

async def webhook_handler(
    request: Request,
    x_docparser_signature: str = Header(None, alias="X-DocParser-Signature")
):
    payload = await request.body()
    
    if not verify_webhook(payload, x_docparser_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    data = json.loads(payload)
    # Обработать data...
    return {"status": "ok"}
```

## Retry Policy

Если ваш сервер недоступен или вернул ошибку (не 2xx), DocParser повторно отправит вебхук:

| Попытка | Задержка | Накопленное время |
|---------|----------|-------------------|
| 1 | сразу | 0с |
| 2 | 60 сек | 1 мин |
| 3 | 300 сек | 6 мин |
| 4 | 900 сек | 21 мин |

Максимум 4 попытки (1 исходная + 3 повтора).

После неудачи вебхук помечается как `failed` в базе. Можно повторно отправить вручную через админку.

## Требования к вашему эндпоинту

| Параметр | Значение |
|----------|----------|
| Метод | POST |
| Content-Type | application/json |
| Timeout | 10 секунд |
| Response | 2xx в течение 10с |
| Идемпотентность | Обязательно (используйте `document.id`) |

## Best Practices

### 1. Быстрый ACK, долгая обработка в фоне
```python
async def webhook_handler(request):
    payload = await request.body()
    verify(payload, signature)
    
    # Сразу ставим в очередь
    await queue.put(json.loads(payload))
    
    return {"status": "accepted"}  # 200 OK сразу

# Воркер обрабатывает из очереди
async def worker():
    while True:
        data = await queue.get()
        await process_document(data)
```

### 2. Идемпотентность
```python
processed_ids = set()  # или Redis с TTL

async def process(data):
    doc_id = data["document"]["id"]
    if doc_id in processed_ids:
        return  # Уже обрабатывали
    
    await do_work(data)
    processed_ids.add(doc_id)
```

### 3. Логирование
```python
import structlog
logger = structlog.get_logger()

async def webhook_handler(request):
    doc_id = request.headers.get("X-DocParser-Document-ID")
    event = request.headers.get("X-DocParser-Event")
    
    logger.info("webhook_received", document_id=doc_id, event=event)
    # ...
```

## Тестирование вебхуков

### Локально (ngrok)
```bash
# Запустить туннель
ngrok http 8000

# Использовать https://xxx.ngrok.io/docparser-webhook
```

### Тестовый эндпоинт (webhook.site)
1. Открыть https://webhook.site
2. Скопировать уникальный URL
3. Использовать как `webhook_url` в DocParser
4. Посмотреть полученные запросы в браузере

### Unit тест
```python
import pytest
from app.services.webhook_dispatcher import _generate_signature

def test_webhook_signature():
    payload = {"event": "test", "data": "value"}
    secret = "test-secret"
    
    signature = _generate_signature(payload)
    assert signature.startswith("sha256=")
    
    # Verify
    import hmac, hashlib
    computed = hmac.new(secret.encode(), json.dumps(payload, sort_keys=True).encode(), hashlib.sha256).hexdigest()
    assert hmac.compare_digest(computed, signature[7:])
```

## Мониторинг

В админке DocParser (планируется) будет доступно:
- Статус доставки каждого вебхука
- Количество попыток
- Время ответа вашего сервера
- Коды ошибок

Пока можно отслеживать через логи:
```bash
# Render logs
render logs --service docparser-api --tail 100 | grep webhook
```

## Безопасность

1. **Всегда проверяйте подпись** — это единственный способ подтвердить подлинность
2. **Используйте HTTPS** — вебхуки не отправляются на HTTP URL в production
3. **Ограничьте IP** (опционально) — DocParser отправляет с известных IP (Render IPs)
4. **Не логируйте полные payloads** с чувствительными данными в production