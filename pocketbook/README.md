# BookFerry для PocketBook

PocketBook использует тот же BookFerry API, что и другие клиенты.

Отдельного `/pocketbook/...` API больше нет.

## Как это работает

При первом запуске PocketBook регистрируется как обычный пользователь BookFerry:

```text
GET /users/register?client_type=pocketbook&plain=1
```

Сервер создаёт пользователя с `client_type=pocketbook` и возвращает `uid`.

`uid` сохраняется локально:

```text
/mnt/ext1/system/config/BookFerry/config.cfg
```

Дальше этот же `uid` используется для профиля, поиска и скачивания.

В БД также хранится `last_seen_at`, поэтому можно видеть, когда конкретный клиент последний раз обращался к серверу.

## Общие ручки

### Каталоги

Telegram получает JSON:

```text
GET /catalogs
```

PocketBook использует ту же ручку в простом текстовом формате:

```text
GET /catalogs?plain=1
```

### Профиль

```text
GET /users/{uid}
GET /users/{uid}?plain=1
```

### Выбор каталога

Обычный API:

```text
PATCH /users/{uid}/catalog
```

PocketBook GET-вариант для `QuickDownload()`:

```text
GET /users/{uid}/catalog?catalog_id=3&plain=1
```

### Пользовательский OPDS

```text
PATCH /users/{uid}/opds
```

PocketBook:

```text
GET /users/{uid}/opds?opds_url=<url>&plain=1
```

### Поиск

Одна ручка для Telegram и PocketBook:

```text
GET /search
```

Telegram:

```text
GET /search?telegram_id=123&query=лукьяненко
```

PocketBook:

```text
GET /search?uid=<uid>&query=лукьяненко&plain=1
```

Ответ PocketBook:

```text
COUNT\t20
BOOK\t<title>\t<author>\t<url>
BOOK\t<title>\t<author>\t<url>
NEXT\t<page_url>
```

Название, автор, URL и следующая страница percent-encoded.



### Скачивание

Одна ручка:

```text
GET /download
```

Telegram:

```text
GET /download?telegram_id=123&url=<book_url>
```

PocketBook:

```text
GET /download?uid=<uid>&url=<book_url>
```

Сервер всегда возвращает EPUB клиенту.

Если у пользователя настроены email, сервер дополнительно отправляет EPUB на них. У PocketBook-пользователя email не обязателен.

URL книги всё равно проходит через `safe_http`, поэтому отдельные подписанные токены не нужны.

## PocketBook client

Исходник:

```text
pocketbook/main.c
```

Клиент хранит:

```text
uid
имя текущей библиотеки
custom OPDS URL, если используется
```

Ридер больше не знает структуру Flibusta, Gutenberg или AmuseWiki.

Поиск и скачивание идут через BookFerry Server.

EPUB сохраняется в:

```text
/mnt/ext1/Books
```

Сканирование библиотеки запускается вручную кнопкой `Обн. библиотеку`.

## Smoke test

```bash
python scripts/smoke_pocketbook.py \
  --base-url https://api.heartlab.app \
  --query "лабиринт отражений"
```

Успешный финал:

```text
POCKETBOOK SMOKE: PASSED
```
