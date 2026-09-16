# AnonchatMgn

Анонимный Telegram-чат для Магнитогорска на Python, aiogram 3 и SQLite.

Пользователь выбирает возраст 13–20 лет, получает случайный ник и может найти собеседника из общей очереди. Возраст и пол не используются как фильтр. По желанию можно искать только в своём районе.

## Что умеет бот

- короткий мобильный интерфейс с восемью готовыми изображениями из `assets/menu`;
- анонимный чат без показа Telegram ID, username, имени, аватарки и телефона;
- блокировка бывшего собеседника и защита от повторной пары в течение 24 часов;
- фильтр ссылок, username, телефонов и email;
- запрет пересылки location, venue, contact и документов;
- жалобы с последними 10 текстовыми сообщениями из оперативной памяти;
- одна жалоба участника на один диалог, авто-мут только по уникальным жалобщикам;
- профиль, достижимые уровни, топ-5, районы и админ-панель;
- добровольная поддержка проекта через счёт Telegram Stars;
- удаление профиля без снятия действующего бана или мута.

## Команды

`/start` — начать · `/connect` — поиск · `/next` — следующий · `/stop` — выйти · `/report` — жалоба · `/profile` — профиль · `/settings` — настройки · `/support` — поддержать проект звёздами · `/help` — помощь · `/forget` — удалить данные.

Админ-панель открывается командой `/admin`. Telegram ID администраторов задаются только через `ADMIN_IDS`.

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
BOT_TOKEN=токен_от_BotFather
ADMIN_IDS=123456789
DB_PATH=data/anonchat_mgn.db
CITY_NAME=Магнитогорск
CITY_SHORT=МГН
AUTO_MUTE_REPORTS=3
AUTO_MUTE_MINUTES=60
```

Если `ADMIN_IDS` пуст, бот запускается без администраторов и пишет об этом в лог. `AUTO_MUTE_REPORTS=0` полностью отключает авто-мут.

## Проверка

```bash
python -m tests.core
python -m tests.flow
```

Тесты проверяют онбординг, возраст, общую очередь, блок-лист, недавние пары, защиту жалоб, `/forget`, очистку FSM, фильтр контактов и опасных типов сообщений, повтор после `RetryAfter` и отсутствие Telegram-данных в публичных карточках.

## Docker

```bash
docker build -t anonchat-mgn .
docker run -d --name anonchat-mgn --env-file .env \
  -v "$PWD/data:/app/data" --restart unless-stopped anonchat-mgn
```

Или: `docker compose up -d`.

База обновляется при старте без удаления старых данных. Добавлены таблица `blocks`, возраст профиля и поля жалобы `dialog_key`/`context`.
