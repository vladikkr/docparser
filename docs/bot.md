# Telegram-бот

Клиент шлёт фото в чат и получает разобранные данные там же. Ничего пересылать
вручную не нужно.

## Запуск

Обычный способ — для разработки, видно логи:

```powershell
python -m app.bot
```

Рабочий способ — фоновый процесс без окна:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\bot_service.ps1 start
powershell -ExecutionPolicy Bypass -File scripts\bot_service.ps1 status
powershell -ExecutionPolicy Bypass -File scripts\bot_service.ps1 stop
```

Чтобы бот поднимался сам при каждом входе в Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\bot_service.ps1 install
```

Отменить: `... uninstall`.

## Настройка

В `.env`:

| Переменная | Что это |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен от @BotFather |
| `TELEGRAM_ADMIN_ID` | Ваш числовой Telegram ID — только этому аккаунту приходят кнопки одобрения |
| `TELEGRAM_TRIAL_LIMIT` | Сколько документов бесплатно до запроса оплаты (по умолчанию 3) |
| `TELEGRAM_STATE_FILE` | Где хранится состояние клиентов |

Токен вводится скрытым вводом в терминале, чтобы не попасть в историю чата:

```powershell
python scripts/set_bot_token.py
```

## Как это работает

1. Клиент жмёт Start и присылает фото или файл.
2. Бот определяет тип документа: QR-код → кассовый чек, XML → УПД/СФ/ТОРГ-12,
   текст с НПД → чек самозанятого.
3. Парсер разбирает документ и сверяет арифметику.
4. Клиент получает ответ в том же чате.

Когда пробные документы закончились, бот пишет «напишите @vladikskr» и
администратору приходит уведомление с кнопками «Выдать доступ» и «Отказать».

## Что важно знать

- **Один токен — один процесс.** Второй получит от Telegram 409 и оба
  перестанут отвечать. `bot_service.ps1` проверяет это перед стартом.
- **Пока компьютер выключен, бот не работает.** Клиенты не смогут ничего
  прислать. Это главное ограничение до появления хостинга.
- **Бот не выдумывает цифры.** Если формат не поддержан или суммы не сходятся,
  он так и пишет, а не подставляет правдоподобные значения.

## Проверки

```powershell
python -m pytest tests/test_bot.py tests/test_selfemployed.py   # 40 тестов
python scripts/check_selfemployed.py                          # сквозной путь на картинке
python scripts/validate_all.py                                 # УПД, СФ, ТОРГ-12, акт, ЭТрН
```
