# VPN Bot

Telegram-бот для VPN-сервиса на базе Remnawave.

## Быстрый старт

### 1. Клонируй и настрой конфиги

```bash
git clone ...
cd vpn_bot
```

Отредактируй файлы в папке `config/`:

- **`config/config.yaml`** — токен бота, API Remnawave, платёжные системы, ID админов
- **`config/prices.yaml`** — цены, устройства, периоды подписок  
- **`config/messages.yaml`** — все тексты и кнопки бота
- **`assets/README.md`** - Всё про изображения в сообщениях

### 2. Запуск через Docker (рекомендуется)

```bash
# SQLite (простой вариант)
# В config.yaml оставь: url: "sqlite+aiosqlite:///./data/bot.db"
docker compose up -d bot  # без PostgreSQL

# С PostgreSQL
# В config.yaml измени: url: "postgresql+asyncpg://vpnbot:changeme@db/vpnbot"
docker compose up -d
```

### 3. Запуск без Docker

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

## Структура проекта

```
vpn_bot/
├── bot.py                    # Точка входа
├── config/
│   ├── config.yaml           # Основной конфиг
│   ├── prices.yaml           # Цены и планы
│   ├── messages.yaml         # Все тексты
│   ├── loader.py             # Загрузчик конфигов
│   └── logger.py             # Настройка логирования
├── app/
│   ├── bot/
│   │   ├── handlers/         # Обработчики команд и колбэков
│   │   ├── keyboards/        # Клавиатуры
│   │   ├── filters/          # Фильтры (AdminFilter)
│   │   └── middlewares/      # DatabaseMiddleware
│   ├── database/
│   │   ├── models.py         # SQLAlchemy модели
│   │   ├── engine.py         # Движок БД
│   │   └── repository.py     # Репозитории (вся работа с БД)
│   ├── services/
│   │   ├── remnawave.py      # Клиент Remnawave API
│   │   ├── yukassa.py        # ЮKassa
│   │   ├── cryptobot.py      # CryptoBot
│   │   ├── subscription.py   # Логика активации подписок
│   │   └── payment_processor.py  # Обработка оплат
│   └── scheduler.py          # Планировщик: напоминания, автоудаление, бэкапы
```

## Настройка Remnawave

1. В панели Remnawave создай API-токен
2. Опционально: создай сквады и укажи их UUID в `prices.yaml` → `squads`
3. Пользователи создаются в формате `TG_<telegram_id>`

## Платёжные системы

### ЮKassa
1. Зарегистрируйся на yookassa.ru
2. Получи `shop_id` и `secret_key`
3. Впиши в `config.yaml`

### CryptoBot
1. Напиши @CryptoBot → создай приложение
2. Получи API-токен
3. Впиши в `config.yaml`

## Бэкапы

Бэкапы создаются автоматически каждые N часов (настраивается в `config.yaml`).
- SQLite: файл `.db` в папке `backups/`
- PostgreSQL: дамп `.sql` через `pg_dump`

Хранится последних N бэкапов (по умолчанию 7).

## Логи

Логи пишутся в `logs/bot.log` с ротацией (10MB × 5 файлов).
