# АНОН МГН

Анонимный Telegram-чат для Магнитогорска на Python, aiogram 3 и SQLite. Возраст 13–20 хранится в профиле, но не разделяет общую очередь.

## Возможности

- поиск случайного собеседника и защита от недавней повторной пары;
- публичный анонимный ник без показа собеседнику Telegram ID, имени и username;
- модерация может использовать Telegram-данные при жалобах и нарушениях;
- жалобы с последними 10 сообщениями, блокировка и сброс скрытых собеседников;
- передача только `@username`, `t.me/...` и `telegram.me/...` через `/send` с подтверждением;
- фиксированный набор premium emoji и кеширование Telegram `file_id` экранов;
- реферальная ссылка `/ref` с начислением опыта;
- добровольная поддержка Stars и АНОН+ на 30 дней через Telegram Stars;
- удаление профиля без снятия действующего бана или мута.

АНОН+ добавляет значок `✦`, статус и дополнительную статистику. Он не влияет на поиск, блокировки, жалобы, муты или баны.

## Команды

`/start` — меню · `/connect` — поиск · `/next` — следующий · `/stop` — выйти · `/report` — жалоба · `/send @username` — поделиться контактом · `/profile` — профиль · `/settings` — настройки · `/ref` — реферальная ссылка · `/support` — поддержать проект · `/premium` — АНОН+ · `/help` — помощь · `/forget` — удалить профиль.

Админ-панель: `/admin`. ID администраторов задаются только через `ADMIN_IDS`.

## Запуск

```bash
git clone https://github.com/kuhaevilagmailcom/AnonchatMgn.git
cd AnonchatMgn
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

Основные переменные `.env`:

```dotenv
BOT_TOKEN=
ADMIN_IDS=
DATABASE_PATH=data/anonchat_mgn.db

CITY_NAME=Магнитогорск
CITY_SHORT=МГН

AUTO_MUTE_REPORTS=3
AUTO_MUTE_MINUTES=60
REPORT_CONTEXT_RETENTION_DAYS=7

DROP_PENDING_UPDATES=false
MESSAGE_RATE_LIMIT=30
MENU_RATE_LIMIT=12

PREMIUM_PRICE_STARS=129
PREMIUM_DAYS=30
```

`AUTO_MUTE_REPORTS=0` выключает авто-мут. Путь `DATABASE_PATH` обязан быть доступен для записи: при ошибке бот завершает запуск и не переходит на временную базу.

## База данных

SQLite обновляется при старте без удаления существующих данных. Основные таблицы: `users`, `matches`, `reports`, `blocks`, `referrals`, `payments`, `kv`. `telegram_payment_charge_id` уникален, поэтому один платёж не обрабатывается повторно. Контекст закрытых жалоб очищается после срока `REPORT_CONTEXT_RETENTION_DAYS`.

## Telegram Stars

`/support` создаёт счёт на выбранное пользователем количество Stars. АНОН+ использует фиксированную цену и срок из `PREMIUM_PRICE_STARS` и `PREMIUM_DAYS`. Продление начинается от `max(текущее время, premium_until)`.

## Тесты

```bash
python -m tests.core
python -m tests.flow
python -m compileall .
```

## Docker

```bash
docker compose up -d --build
```

Каталог `data` подключается как volume, а `.env` передаётся контейнеру через `env_file`.
