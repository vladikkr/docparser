# Интеграция с МойСклад

## Обзор

МойСклад — популярная облачная система управления торговлей. DocParser.ru позволяет автоматически создавать документы в МойСклад из распознанных первичных документов.

## Архитектура интеграции

```
[Фото/PDF] → DocParser API → [JSON] → Ваш сервер/1С → МойСклад API → [Документ в МойСклад]
```

## Варианты реализации

### 1. Прямая интеграция (через ваш бэкенд)

Ваш сервер получает вебхук от DocParser, преобразует данные и создает документы в МойСклад.

### 2. Через 1С (если 1С уже интегрирована с МойСклад)

DocParser → 1С → МойСклад (через стандартный обмен)

### 3. Нетт-код (Make/Zapier/n8n)

Использовать вебхуки DocParser для запуска сценариев в Make/Zapier, которые создают документы в МойСклад.

## Пример: Создание "Приходной накладной" в МойСклад (Python)

```python
import requests
import json
from datetime import datetime

MOYSKLAD_TOKEN = "your-moysklad-api-token"
MOYSKLAD_BASE = "https://api.moysklad.ru/api/remap/1.2"

headers = {
    "Authorization": f"Bearer {MOYSKLAD_TOKEN}",
    "Content-Type": "application/json",
}

def find_or_create_counterparty(inn: str, name: str, kpp: str = None):
    """Найти или создать контрагента в МойСклад"""
    # Поиск по ИНН
    search_url = f"{MOYSKLAD_BASE}/entity/counterparty"
    params = {"filter": f"inn={inn}"}
    resp = requests.get(search_url, headers=headers, params=params)
    resp.raise_for_status()
    data = resp.json()
    
    if data["rows"]:
        return data["rows"][0]["meta"]["href"]
    
    # Создать нового
    payload = {
        "name": name,
        "inn": inn,
        "companyType": "legal" if len(inn) == 10 else "individual",
    }
    if kpp:
        payload["kpp"] = kpp
    
    resp = requests.post(search_url, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()["meta"]["href"]

def find_or_create_product(name: str, uom_href: str = None):
    """Найти или создать товар/услугу"""
    search_url = f"{MOYSKLAD_BASE}/entity/product"
    params = {"filter": f"name={name}"}
    resp = requests.get(search_url, headers=headers, params=params)
    data = resp.json()
    
    if data["rows"]:
        return data["rows"][0]["meta"]["href"]
    
    # Создать
    payload = {
        "name": name,
        "salePrices": [{"value": 0, "priceType": "DEFAULT"}],
    }
    if uom_href:
        payload["uom"] = {"meta": {"href": uom_href}}
    
    resp = requests.post(search_url, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()["meta"]["href"]

def create_purchase_order(docparser_data: dict):
    """Создать заказ поставщику (Приходная накладная) из данных DocParser"""
    
    supplier = docparser_data.get("seller", {})
    items = docparser_data.get("items", [])
    date = docparser_data.get("date_time", datetime.now().isoformat())
    
    # Контрагент
    counterparty_href = find_or_create_counterparty(
        inn=supplier.get("inn", ""),
        name=supplier.get("name", "Unknown Supplier"),
        kpp=supplier.get("kpp"),
    )
    
    # Позиции
    positions = []
    for item in items:
        product_href = find_or_create_product(item["name"])
        positions.append({
            "quantity": float(item["quantity"]),
            "price": int(float(item["price"]) * 100),  # в копейках
            "assortment": {"meta": {"href": product_href, "type": "product"}},
            "vat": int(float(item.get("vat_rate", "20")) * 1000000),  # 20% = 20000000
        })
    
    # Создать заказ поставщику
    payload = {
        "moment": date,
        "organization": {"meta": {"href": f"{MOYSKLAD_BASE}/entity/organization/{YOUR_ORG_ID}"}},
        "agent": {"meta": {"href": counterparty_href, "type": "counterparty"}},
        "positions": positions,
        "applicable": True,  # провести сразу
    }
    
    resp = requests.post(f"{MOYSKLAD_BASE}/entity/purchaseorder", headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()
```

## Пример для Make (Integromat)

### Сценарий: DocParser Webhook → МойСклад

1. **Модуль 1: Webhook** (Custom webhook)
   - URL: `https://hook.eu1.make.com/xxx`
   - Метод: POST

2. **Модуль 2: Router** (проверка типа документа)
   - Route 1: `receipt_kkt` → Создать "Приходный заказ"
   - Route 2: `upd` → Создать "Приходная накладная"
   - Route 3: `invoice` → Создать "Счет на оплату"

3. **Модуль 3: HTTP Request** (МойСклад API)
   - Настроить запросы к endpoints МойСклад
   - Использовать функции `map()`, `get()` для преобразования JSON

### Маппинг полей (Receipt KKТ → МойСклад)

| DocParser поле | МойСклад поле | Примечание |
|----------------|---------------|------------|
| `seller.name` | `agent.name` | Наименование контрагента |
| `seller.inn` | `agent.inn` | ИНН (ключ поиска) |
| `seller.kpp` | `agent.kpp` | КПП |
| `date_time` | `moment` | Дата документа |
| `items[].name` | `positions[].assortment.name` | Номенклатура |
| `items[].quantity` | `positions[].quantity` | Количество |
| `items[].price` | `positions[].price` | Цена (в копейках) |
| `items[].vat_rate` | `positions[].vat` | НДС (20% = 20000000) |
| `fiscal_number` | `attributes[]` | Доп. поле: ФН |
| `fiscal_document_number` | `attributes[]` | Доп. поле: ФД |

## Вебхук от DocParser к Make

В DocParser при загрузке документа укажите:
```
webhook_url: https://hook.eu1.make.com/your-webhook-id
```

DocParser отправит:
```json
{
  "event": "document.parsed",
  "timestamp": "2024-01-01T12:00:00Z",
  "document": {
    "id": "uuid",
    "document_type": "receipt_kkt",
    "status": "completed",
    "parsed_data": { ... },
    "processing_time_ms": 1500
  }
}
```

## Настройка в МойСклад

1. Создать API токен: Настройки → API → Создать токен (права: Полный доступ)
2. Получить ID организации: `GET /entity/organization`
3. Настроить единицы измерения (ед.изм.) для товаров
4. Настроить ставки НДС (обычно уже есть: 20%, 10%, 0%, без НДС)

## Обработка ошибок

| Ошибка | Решение |
|--------|---------|
| 401 Unauthorized | Проверить токен, срок действия |
| 404 Not Found | Организация/контрагент не найдены |
| 400 Bad Request | Неверный формат данных (проверить обязательные поля) |
| 429 Too Many Requests | Rate limit МойСклад (100 req/s), добавить задержки |

## Тестирование

Используйте песочницу МойСклад:
- `https://api.moysklad.ru/api/remap/1.2` (работает с тестовым токеном)
- Создайте тестовую организацию для разработки

## Поддержка

- Документация МойСклад API: https://dev.moysklad.ru/doc/api/remap/1.2/
- Поддержка DocParser: support@docparser.ru