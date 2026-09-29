# DocParser

Разбор первичных документов в структурированные данные: чеки ККТ России и
Беларуси, УПД и УКД, счета-фактуры и корректировочные, ТОРГ-12, акты
выполненных работ, электронные транспортные накладные и чеки самозанятых.

Клиент обычно не пользуется API напрямую: он пишет Telegram-боту и получает
разбор в том же чате. API остаётся для интеграций с 1С.

## Что работает

| Документ | Источник | Статус |
|---|---|---|
| Чек ККТ Беларуси | фото | работает, итог сверяется с позициями |
| Чек ККТ России | фото + ФНС | работает, если ФНС доступен |
| УПД, УКД | XML, приказ ЕД-7-26/970@ | работает, формат 5.03 |
| Счёт-фактура, корректировочная | XML, приказ ЕД-7-26/970@ | работает |
| ТОРГ-12 | XML, приказ ММВ-7-10/551@ | работает |
| Акт выполненных работ | XML, приказ ММВ-7-10/552@ | работает |
| Электронная транспортная накладная | XML, приказ ЕД-7-26/1065@ | частично, нужны оба титула |
| Чек самозанятого | фото или скриншот «Мой налог» | работает, проверяет арифметику НПД |

Каждый статус подтверждён проверкой, а не обещанием:
`python scripts/validate_all.py` разбирает все XML-форматы и проверяет поля,
арифметику и КНД, а `python scripts/check_selfemployed.py` прогоняет чек
самозанятого сквозным путём на сгенерированной картинке.

## Стек

| Компонент | Технология |
|-----------|------------|
| API | FastAPI 0.109+ (Python 3.12 в контейнере) |
| Бот | python-telegram-bot 22, long polling |
| DB | PostgreSQL (Supabase) + SQLAlchemy 2.0 |
| Cache/Queue | Redis (Upstash) + Celery |
| OCR | Tesseract 5 (rus + eng) + OpenCV, pyzbar для QR |
| PDF | pdf2image + poppler |
| Оплата | ручная: Stripe не работает с резидентами Беларуси |
| Хостинг | Render: web service для API, background worker для бота |
| Monitoring | Sentry + UptimeRobot |
| CI/CD | GitHub Actions |

## Быстрый старт

### Предварительные требования

- Docker Desktop
- Python 3.11+ (для локальной разработки без Docker)
- Учетные записи: Supabase, Upstash Redis, Stripe

### Локальный запуск (Docker)

```bash
# Клонировать репозиторий
git clone https://github.com/yourname/docparser-ru.git
cd docparser-ru

# Создать .env из примера
cp .env.example .env
# Отредактировать .env - заполнить ключи

# Запустить инфраструктуру и миграции
./scripts/dev.sh
```

### Локальный запуск (Poetry)

```bash
# Установить зависимости
poetry install

# Запустить инфраструктуру
docker-compose -f docker/docker-compose.yml up -d postgres redis minio

# Миграции
poetry run alembic upgrade head

# Сид данные
poetry run python scripts/seed.py

# Запуск API
poetry run uvicorn app.main:app --reload

# В отдельном терминале - Worker
poetry run celery -A app.tasks.celery_app worker --loglevel=info
```

## Структура проекта

```
docparser-ru/
├── app/
│   ├── api/v1/           # REST эндпоинты
│   ├── core/             # Security, Rate limiting, Exceptions, Logging
│   ├── models/           # SQLAlchemy модели
│   ├── schemas/          # Pydantic схемы (API contracts)
│   ├── services/         # Бизнес-логика
│   │   ├── ocr.py              # Tesseract: распознавание, повороты, тайлы
│   │   ├── qr.py               # декодирование QR чеков
│   │   ├── fn_api.py           # ФНС API клиент
│   │   ├── parsers/            # Парсеры по типам документов
│   │   ├── stripe_service.py   # Stripe Billing
│   │   └── webhook_dispatcher  # Клиентские вебхуки
│   ├── bot/               # Telegram-бот: определение типа, разбор, выдача доступа
│   ├── tasks/            # Celery задачи
│   └── utils/            # Утилиты
├── alembic/              # Миграции БД
├── docker/               # Docker файлы
├── scripts/              # Утилиты (dev, migrate, seed)
├── tests/                # Unit + Integration тесты
└── render.yaml           # Render.com Blueprint
```

## API Документация

После запуска доступна по адресу: `http://localhost:8000/docs` (Swagger UI)

### Основные эндпоинты

```
POST   /api/v1/auth/register          # Регистрация
POST   /api/v1/auth/login             # Логин (JWT)
POST   /api/v1/auth/api-keys          # Создать API Key
GET    /api/v1/auth/api-keys          # Список API Keys

POST   /api/v1/documents/upload       # Загрузить документ (JWT)
POST   /api/v1/documents/parse        # Синхронный парсинг (API Key)
GET    /api/v1/documents              # Список документов
GET    /api/v1/documents/{id}         # Получить результат

GET    /api/v1/billing/plans          # Тарифы
GET    /api/v1/billing/subscription   # Текущая подписка
POST   /api/v1/billing/checkout       # Создать Stripe Checkout
POST   /api/v1/billing/portal         # Stripe Customer Portal
GET    /api/v1/billing/usage          # Статистика использования
GET    /api/v1/billing/invoices       # История счетов

POST   /api/v1/webhooks/stripe        # Stripe вебхуки
```

## Пример использования

### Python (requests)

```python
import requests

API_KEY = "dp_xxxxxxxxxxxxxxxxxxxxxxxx"
BASE_URL = "https://api.docparser.ru/api/v1"

# Загрузить чек
with open("receipt.jpg", "rb") as f:
    response = requests.post(
        f"{BASE_URL}/documents/parse",
        headers={"X-API-Key": API_KEY},
        files={"file": f},
        data={"document_type": "receipt_kkt"}
    )

document_id = response.json()["document_id"]

# Получить результат (попробовать несколько раз с интервалом)
import time
while True:
    result = requests.get(
        f"{BASE_URL}/documents/{document_id}",
        headers={"X-API-Key": API_KEY}
    ).json()
    
    if result["status"] == "completed":
        print(result["parsed_data"])
        break
    elif result["status"] == "failed":
        print("Error:", result["error_message"])
        break
    
    time.sleep(2)
```

### 1С:Предприятие (HTTP запрос)

```bsl
// Пример для 1С
HTTPКлиент = Новый HTTPКлиент(
    Новый ЗащищенноеСоединениеOpenSSL(),
    ,
    ,
    ,
    30
);

Заголовки = Новый Соответствие();
Заголовки.Вставить("X-API-Key", "dp_xxxxxxxxxxxxxxxxxxxxxxxx");
Заголовки.Вставить("Content-Type", "multipart/form-data");

// Формируем multipart тело...
// Отправляем POST на /api/v1/documents/parse
// Получаем document_id
// Опрашиваем GET /api/v1/documents/{id} до status=completed
// Парсим JSON в parsed_data
```

## Тарифы

Цены в BYN и те же, что на лендинге. Оплата пока ручная: Stripe не работает с
резидентами Беларуси, поэтому списание идёт переводом, а доступ выдаётся
вручную.

| Тариф | BYN/мес | Документов | API Keys | Rate Limit | Особенности |
|-------|----------|------------|----------|------------|-------------|
| Free | 0 | 50 | 1 | 10/min | Базовый парсинг |
| Starter | 9 | 1 000 | 3 | 100/min | Все типы, вебхуки |
| Pro | 29 | 10 000 | 10 | 500/min | SLA 99.9%, батчи, 1С/МойСклад |
| Business | 89 | 50 000 | ∞ | 2000/min | Dedicated, кастом, on-premise |

В боте первые 3 документа бесплатны, дальше он просит написать владельцу.

## Деплой на Render.com

1. Подключить GitHub репозиторий к Render
2. Render автоматически определит `render.yaml` (Blueprint)
3. Добавить секреты в Render Dashboard:
   - `STRIPE_SECRET_KEY`
   - `STRIPE_WEBHOOK_SECRET`
   - `STRIPE_PRICE_*`
   - `SENTRY_DSN` (опционально)
4. Настроить Stripe Webhook URL: `https://your-app.onrender.com/api/v1/webhooks/stripe`
5. Деплой произойдет автоматически при push в `main`

## Тестирование

```bash
# Unit тесты
poetry run pytest tests/unit -v

# Integration тесты (требуют запущенных сервисов)
poetry run pytest tests/integration -v

# Все тесты с покрытием
poetry run pytest --cov=app --cov-report=html
```

## Разработка

### Добавление нового типа документа

1. Добавить enum в `app/models/__init__.py` (`DocumentType`)
2. Создать схему в `app/schemas/{type}.py`
3. Создать парсер в `app/services/parsers/{type}.py` (наследуется от `BaseParser`)
4. Зарегистрировать в `app/services/parsers/__init__.py`
5. Добавить тесты в `tests/unit/test_parsers.py`

### Миграции БД

```bash
# Создать миграцию после изменения моделей
poetry run alembic revision --autogenerate -m "description"

# Применить
poetry run alembic upgrade head
```

## Мониторинг

- **Health check**: `GET /health` — статус API, БД, Redis
- **Readiness**: `GET /ready` — готовность к трафику
- **Sentry**: ошибки и производительность
- **Flower**: `http://localhost:5555` — мониторинг Celery задач

## Лицензия

MIT License — свободное использование, модификация и распространение.

## Поддержка

- 📧 Email: support@docparser.ru
- 🐛 Issues: GitHub Issues
- 📖 Docs: `/docs` (после запуска)