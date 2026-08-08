# BookFerry

BookFerry — backend-сервис для поиска электронных книг и доставки EPUB на электронные книги и другие устройства.

Основная идея проекта: **искать быстро по локальному индексу, а сам файл книги скачивать только в момент выбора пользователем**.

BookFerry не хранит библиотеку EPUB-файлов на сервере. В локальной SQLite-базе находятся только метаданные книг: источник, внешний ID, название, автор и язык. После выбора книги backend скачивает EPUB у исходного каталога, отправляет его по e-mail и возвращает файл клиенту.

Проект развивается как общий backend для нескольких клиентов:

- Telegram-бота;
- PocketBook-приложения;
- будущего Flutter-клиента.

> Текущее правило проекта: **поддерживается только EPUB**.

---

## Что уже умеет BookFerry

- быстрый локальный поиск по названию и автору через SQLite FTS5;
- несколько встроенных книжных каталогов;
- персональный выбор каталога для пользователя;
- подключение собственного OPDS-каталога;
- загрузка EPUB только после выбора книги;
- отправка EPUB на один или несколько e-mail;
- пользовательские настройки и UUID-профили;
- Telegram-совместимые API-ручки;
- отдельная база метаданных книг;
- безопасная атомарная пересборка каталога;
- автоматическое ежедневное обновление встроенных каталогов;
- Docker / Docker Compose;
- Swagger UI через FastAPI.

---

## Встроенные каталоги

### Русскоязычные

| Код | Каталог | Источник метаданных |
|---|---|---|
| `flibusta` | Flibusta | SQL-дампы библиотеки |
| `anarchist_ru` | Библиотека Анархизма | OPDS / AmuseWiki |

### Англоязычные

| Код | Каталог | Источник метаданных |
|---|---|---|
| `gutenberg` | Project Gutenberg | официальный `pg_catalog.csv.gz` |
| `anarchist` | The Anarchist Library | OPDS / AmuseWiki |

Для встроенных каталогов поиск выполняется **не по сети**, а по локальной базе `catalog.db`.

Внешний сайт используется только для:

1. обновления метаданных;
2. скачивания выбранного EPUB.

---

## Пользовательский OPDS

Пользователь может указать собственный OPDS URL.

Backend:

1. открывает URL;
2. проверяет, что получен Atom/OPDS feed;
3. ищет `rel="search"`;
4. при необходимости читает OpenSearch Description;
5. сохраняет поисковый шаблон с `{searchTerms}`;
6. использует этот OPDS только для конкретного пользователя.

Пользовательский OPDS **не импортируется** в общий `catalog.db`.

Поддерживаемый сейчас вариант — OPDS 1.x / Atom + OpenSearch и EPUB acquisition links.

OPDS 2.0 JSON пока не реализован.

### Безопасность custom OPDS

Так как URL вводится пользователем, сетевые запросы проходят через дополнительную проверку:

- разрешены только `http://` и `https://`;
- запрещены URL с логином/паролем;
- запрещены loopback, private, link-local и другие внутренние IP;
- каждый redirect проверяется заново;
- аналогичная проверка выполняется при фактическом скачивании EPUB.

Это защищает backend от использования пользовательского OPDS как SSRF-прокси к внутренней сети сервера.

---

## Архитектура

```text
                    ┌────────────────────┐
                    │ Telegram / PB / UI │
                    └─────────┬──────────┘
                              │
                              ▼
                       ┌─────────────┐
                       │   FastAPI   │
                       └──────┬──────┘
                              │
              ┌───────────────┴────────────────┐
              │                                │
              ▼                                ▼
      встроенный каталог                 custom OPDS
              │                                │
              ▼                                ▼
       SQLite FTS5 search             Atom + OpenSearch
              │                                │
              └───────────────┬────────────────┘
                              │
                              ▼
                       выбранный EPUB URL
                              │
                              ▼
                       download.py
                         │       │
                         ▼       ▼
                    HTTP file   SMTP
                         │       │
                         └───┬───┘
                             ▼
                         пользователь
```

---

## Две SQLite-базы

BookFerry специально разделяет пользовательские данные и большой перестраиваемый индекс книг.

### `bookferry.db`

Хранит данные, которые нельзя терять при обновлении книжного индекса:

```text
users
catalogs
```

Основные поля пользователя:

```text
uid
client_type
external_id
catalog_id
custom_opds_url
custom_opds_search_template
emails
subject
created_at
```

### `catalog.db`

Полностью перестраиваемая база метаданных:

```text
books
books_fts
```

`books`:

```text
id
catalog_code
external_id
title
author
language
```

Файлы книг в этой базе **не хранятся**.

FTS5 индексирует `title` и `author`.

---

## Как работает поиск

Для встроенного каталога:

```text
query
  ↓
нормализация слов
  ↓
SQLite FTS5
  ↓
books
  ↓
external_id
  ↓
EPUB URL конкретного источника
```

Поиск поддерживает префиксы слов. Например, запрос:

```text
лабиринт лукьян
```

может найти книгу по сочетанию названия и автора.

Пагинация совместима с Telegram-ботом: backend возвращает `next_page_url`, который для локального поиска является внутренним токеном вида:

```text
local:20
local:40
```

---

## EPUB URL встроенных каталогов

URL книги не хранится в `catalog.db` — он строится по `catalog_code` и `external_id`.

Принцип:

```text
Flibusta
external_id = BookID
→ /b/{BookID}/epub

Project Gutenberg
external_id = ebook ID
→ /ebooks/{id}.epub3.images

AmuseWiki-каталоги
external_id = slug
→ /library/{slug}.epub
```

Это позволяет хранить индекс компактным и не привязывать метаданные к полному URL.

---

## Обновление каталогов

Для ручной работы есть отдельные импортёры:

```text
scripts/import_flibusta.py
scripts/import_gutenberg.py
scripts/import_anarchist.py
scripts/import_anarchist_ru.py
```

Одиночный импорт строит временный `catalog.db.new`, сохраняет остальные каталоги, пересобирает общий FTS и только после успешного завершения заменяет рабочую базу.

Для production используется:

```text
scripts/update_all_catalogs.py
```

Он создаёт полный новый snapshot всех встроенных каталогов и заменяет рабочий `catalog.db` только после успешного импорта и проверок.

Если обновление оборвалось, текущая рабочая база остаётся нетронутой.

Также используется lock-файл, предотвращающий одновременный запуск двух обновлений.

### Проверки перед заменой базы

Ночной updater проверяет минимальное количество записей:

```text
Flibusta             >= 500 000
Project Gutenberg     >= 50 000
The Anarchist Library >= 10 000
Библиотека Анархизма  >= 500
```

и выполняет:

```sql
PRAGMA integrity_check;
```

---

## Ежедневное обновление

В `deploy/` находятся unit-файлы systemd:

```text
deploy/bookferry-catalog-update.service
deploy/bookferry-catalog-update.timer
```

Расписание:

```text
03:00 Asia/Almaty
```

Таймер запускает обновление каталогов внутри контейнера `bookferry`.

---

## Стек

- Python 3.12
- FastAPI
- Pydantic
- SQLite / FTS5
- Requests
- lxml
- python-dotenv
- SMTP
- Docker
- Docker Compose
- systemd timer

---

## Структура проекта

```text
BookFerry/
├── app/
│   ├── api.py
│   ├── config.py
│   ├── models.py
│   ├── db/
│   │   ├── database.py
│   │   ├── users.py
│   │   ├── catalogs.py
│   │   └── catalog_database.py
│   └── services/
│       ├── local_search.py
│       ├── opds.py
│       ├── safe_http.py
│       ├── download.py
│       └── mail.py
├── scripts/
│   ├── catalog_utils.py
│   ├── import_flibusta.py
│   ├── import_gutenberg.py
│   ├── import_anarchist.py
│   ├── import_anarchist_ru.py
│   ├── migrate_custom_opds.py
│   └── update_all_catalogs.py
├── deploy/
│   ├── bookferry-catalog-update.service
│   └── bookferry-catalog-update.timer
├── main.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## Конфигурация

Пример `.env`:

```env
SMTP_HOST=mail.example.com
SMTP_PORT=587
SMTP_LOGIN=books@example.com
SMTP_PASSWORD=secret
DEFAULT_SUBJECT=BookFerry

DB_NAME=/app/data/bookferry.db
CATALOG_DB_NAME=/app/data/catalog.db

DEFAULT_OPDS_URL=https://flibusta.is/opds/
```

`CATALOG_DB_NAME` необязателен: по умолчанию `catalog.db` создаётся рядом с `DB_NAME`.

---

## Docker

Сборка и запуск:

```bash
docker compose up -d --build
```

Логи:

```bash
docker compose logs -f bookferry
```

Остановка:

```bash
docker compose down
```

В production каталог `/opt/data` хоста монтируется в контейнер как:

```text
/app/data
```

---

## API

Swagger UI после запуска:

```text
http://127.0.0.1:8000/docs
```

### Health

```http
GET /health
```

Ответ:

```json
{
  "status": "ok"
}
```

### Список встроенных каталогов

```http
GET /catalogs
```

### Регистрация клиента

```http
POST /users/register
```

```json
{
  "client_type": "pocketbook"
}
```

Поддерживаемые типы:

```text
telegram
pocketbook
flutter
```

Backend создаёт UUID `uid`, который клиент может хранить локально и использовать дальше.

### Получение профиля

```http
GET /users/{uid}
```

### Выбор встроенного каталога

```http
PATCH /users/{uid}/catalog
```

```json
{
  "catalog_id": 3
}
```

Выбор встроенного каталога автоматически отключает ранее заданный custom OPDS.

### Пользовательский OPDS

```http
PATCH /users/{uid}/opds
```

```json
{
  "opds_url": "https://example.org/opds"
}
```

### Telegram-compatible search

Текущий `/search` пока использует Telegram ID:

```http
POST /search
```

```json
{
  "telegram_id": 172361118,
  "query": "лабиринт отражений"
}
```

Ответ:

```json
{
  "books": [
    {
      "author": "Сергей Лукьяненко",
      "title": "Лабиринт отражений",
      "url": "https://example.org/book.epub"
    }
  ],
  "next_page_url": "local:20"
}
```

### Скачать и отправить книгу

```http
POST /send-book
```

```json
{
  "telegram_id": 172361118,
  "url": "https://example.org/book.epub"
}
```

Backend:

1. скачивает EPUB во временный каталог;
2. отправляет его на e-mail пользователя;
3. возвращает файл клиенту;
4. удаляет временный файл после ответа.

---

## Telegram-бот

Telegram-клиент находится в отдельном репозитории `BookFerryBot`.

Текущий бот использует compatibility API по `telegram_id`.

Старый экран `/setting`, который принимает OPDS URL, остаётся совместимым: теперь backend может распознать встроенный каталог либо сохранить URL как персональный custom OPDS.

---

## Что важно не сломать

1. **EPUB-only** — другие форматы пока не входят в контракт проекта.
2. `bookferry.db` и `catalog.db` решают разные задачи и не должны сливаться в одну большую базу.
3. Большой импорт не должен писать напрямую в рабочий `catalog.db`.
4. Рабочая база заменяется только после успешной сборки нового snapshot.
5. Выбор встроенного каталога должен очищать custom OPDS пользователя.
6. URL пользовательского OPDS и EPUB обязательно проходят проверку публичного адреса.
7. Поиск встроенных каталогов должен оставаться локальным — сеть нужна только при обновлении и скачивании книги.

---

## Roadmap

Ближайшие логичные шаги:

- завершить UI выбора четырёх встроенных каталогов в Telegram-боте;
- унифицировать `/search` и `/send-book` под `uid`, а не только Telegram ID;
- подключить PocketBook-клиент;
- подключить Flutter-клиент;
- добавить тесты API, локального поиска, импортёров и custom OPDS;
- добавить Allure/CI после стабилизации функциональности;
- улучшить мониторинг ночного обновления каталогов;
- при реальной необходимости добавить OPDS 2.0.

---

## Состояние проекта

BookFerry уже вышел за рамки простого «прокси к OPDS».

Сейчас это backend с локальным полнотекстовым индексом, несколькими источниками данных, пользовательскими профилями, доставкой EPUB, персональными OPDS-каталогами и безопасной фоновой пересборкой метаданных.
