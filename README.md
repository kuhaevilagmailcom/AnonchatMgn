# АНОН МГН

Telegram-чат для Магнитогорска на Python, aiogram 3 и SQLite. Возраст и район необязательны и не разделяют общую очередь без явно включённого фильтра района.

## Возможности

- поиск случайного собеседника; повтор запрещается только явной блокировкой пользователя;
- публичный анонимный ник и очки; Telegram username и ID скрыты от обычных пользователей;
- модерация может использовать Telegram-данные при жалобах и нарушениях;
- жалобы с последними 10 сообщениями, блокировка и сброс скрытых собеседников;
- пересылка обычных сообщений, включая `@username`, ссылки `t.me/...`, телефоны и Telegram-контакты;
- фиксированный набор custom emoji и кеширование Telegram `file_id` экранов;
- реферальная ссылка `/ref` с начислением 50 очков;
- добровольная поддержка Stars: любая сумма от 1 ⭐ навсегда добавляет к нику 💎;
- администраторы с отдельными правами на жалобы, пользователей, мут, бан, рассылку и очки;
- удаление профиля без снятия действующего бана или мута.

## Команды

`/start` — меню · `/connect` — поиск · `/next` — следующий · `/stop` — выйти · `/report` — жалоба · `/profile` — профиль и реферальная ссылка · `/settings` — настройки · `/ref` — реферальная ссылка · `/support` — поддержать проект · `/help` — помощь · `/forget` — удалить профиль.

Владельцы задаются через `ADMIN_IDS`. Они имеют все права и назначают остальных:

```text
/adminadd 123456 reports,users,mute
/adminperms 123456 all
/admindel 123456
/adminlist
/points 123456 +50
/points 123456 -50
```

Доступные права: `stats`, `reports`, `queue`, `users`, `broadcast`, `mute`, `ban`, `points`. Интерфейс скрывает недоступные разделы, а каждый обработчик повторно проверяет право на сервере.

Владелец из `ADMIN_IDS` может включить и выключить получение копий сообщений активных диалогов кнопкой «Чаты» в панели. В копии видны username, анонимный ник и ID обоих собеседников; назначенным администраторам эта функция недоступна.

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

```

`AUTO_MUTE_REPORTS=0` выключает авто-мут. Путь `DATABASE_PATH` обязан быть доступен для записи: при ошибке бот завершает запуск и не переходит на временную базу.

## База данных

SQLite обновляется при старте без удаления существующих данных. Основные таблицы: `users`, `admins`, `matches`, `reports`, `blocks`, `referrals`, `payments`, `kv`. `telegram_payment_charge_id` уникален, поэтому один платёж не обрабатывается повторно. Контекст закрытых жалоб очищается после срока `REPORT_CONTEXT_RETENTION_DAYS`.

## Telegram Stars

`/support` создаёт счёт на выбранное пользователем количество Stars. После первого подтверждённого платежа к публичному нику добавляется 💎; сумма поддержки хранится в профиле и защищена от повторной обработки одного charge ID.

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
