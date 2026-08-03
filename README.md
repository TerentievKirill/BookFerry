# BookFerry

BookFerry — сервер для поиска и доставки электронных книг на PocketBook и другие устройства по электронной почте.

Проект предоставляет REST API, которое:

- ищет книги через OPDS-каталог;
- скачивает EPUB;
- отправляет книгу по e-mail;
- работает в Docker.

---

# Возможности

- Поиск книг по названию
- Поддержка OPDS-каталогов
- Отправка EPUB по SMTP
- REST API на FastAPI
- Docker и Docker Compose
- Swagger UI

---

# Стек

- Python 3.12
- FastAPI
- Pydantic
- Requests
- lxml
- Docker
- Docker Compose

---

# Структура проекта

```text
bookferry/
│
├── app/
│   ├── api.py
│   ├── config.py
│   ├── models.py
│   └── services/
│       ├── opds.py
│       ├── download.py
│       ├── mail.py
│       └── book_delivery.py
│
├── main.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env
```

---

# Настройка

Создайте файл `.env`.

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_LOGIN=your@gmail.com
SMTP_PASSWORD=your_app_password

DEFAULT_OPDS_URL=https://flibusta.is/opds/
```

Для Gmail необходимо использовать пароль приложения.

---

# Запуск без Docker

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux
source .venv/bin/activate

pip install -r requirements.txt

uvicorn main:app --reload
```

Swagger:

```
http://127.0.0.1:8000/docs
```

---

# Запуск через Docker

Сборка:

```bash
docker compose build
```

Запуск:

```bash
docker compose up -d
```

После изменения кода:

```bash
docker compose up -d --build
```

Логи:

```bash
docker compose logs -f
```

Остановка:

```bash
docker compose down
```

---

# API

## GET /health

Ответ:

```json
{
  "status": "ok"
}
```

## POST /search

Запрос:

```json
{
  "query": "Лабиринт отражений"
}
```

Ответ:

```json
[
  {
    "author": "Лукьяненко Сергей",
    "title": "Лабиринт отражений",
    "url": "https://flibusta.is/b/111094/epub"
  }
]
```

## POST /send-book

Запрос:

```json
{
  "email": "reader@example.com",
  "book": {
    "author": "Лукьяненко Сергей",
    "title": "Лабиринт отражений",
    "url": "https://flibusta.is/b/111094/epub"
  }
}
```

Ответ:

```json
{
  "status": "ok"
}
```

---

# Архитектура

```text
HTTP Request
      │
      ▼
FastAPI
      │
      ▼
book_delivery.py
      │
 ┌────┴─────────────┐
 ▼                  ▼
download.py     mail.py
      │              │
      ▼              ▼
    OPDS         SMTP Server
```

---


# Планы

- Telegram Bot
- Поддержка нескольких OPDS-каталогов
- Пользователи и настройки
- История отправок
- Ограничение количества запросов
- Кэширование результатов поиска
- Поддержка нескольких форматов книг
