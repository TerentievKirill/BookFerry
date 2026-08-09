# BookFerry для PocketBook

PocketBook-клиент использует BookFerry Server как единый источник поиска и скачивания EPUB.

Ридер больше не знает структуру Flibusta, Gutenberg или AmuseWiki и не разбирает OPDS встроенных каталогов напрямую.

## Что делает клиент

1. При первом запуске получает UUID устройства у BookFerry Server.
2. Сохраняет UUID локально в:

```text
/mnt/ext1/system/config/BookFerry/config.cfg
```

3. Получает список доступных библиотек с сервера.
4. Позволяет выбрать встроенную библиотеку или указать собственный OPDS.
5. Отправляет серверу поисковый запрос по названию или автору.
6. Показывает результаты по 5 книг на экране.
7. По нажатию скачивает EPUB через BookFerry Server.
8. Сохраняет файл в:

```text
/mnt/ext1/Books
```

9. Сканирование библиотеки PocketBook запускается вручную кнопкой `Обн. библиотеку`.

## Сервер

По умолчанию клиент использует:

```text
https://api.heartlab.app
```

Адрес задаётся константой `SERVER_URL` в `main.c`.

## PocketBook API

API специально сделан простым и GET-only, потому что клиент использует штатный InkView `QuickDownload()` и не требует JSON-библиотеки.

### Регистрация

```http
GET /pocketbook/register
```

Ответ:

```text
UID\t<uid>\t<catalog_id>\t<percent_encoded_catalog_name>
```

### Профиль

```http
GET /pocketbook/{uid}/profile
```

### Список библиотек

```http
GET /pocketbook/catalogs
```

Пример:

```text
CATALOG\t1\tProject%20Gutenberg
CATALOG\t3\tFlibusta
CUSTOM\t%D0%94%D1%80%D1%83%D0%B3%D0%BE%D0%B9%20OPDS
```

### Выбор встроенной библиотеки

```http
GET /pocketbook/{uid}/catalog/{catalog_id}
```

### Свой OPDS

```http
GET /pocketbook/{uid}/opds?url=<percent_encoded_url>
```

URL проверяется сервером тем же SSRF-safe механизмом, что используется остальными клиентами BookFerry.

### Поиск

```http
GET /pocketbook/{uid}/search?q=<query>
```

Следующая страница:

```http
GET /pocketbook/{uid}/search?q=<query>&page=<opaque_token>
```

Ответ:

```text
COUNT\t20
BOOK\t<title>\t<author>\t<download_token>
BOOK\t<title>\t<author>\t<download_token>
NEXT\t<page_token>
```

`title` и `author` percent-encoded. Токены opaque: клиент не должен разбирать их содержимое.

### Скачать EPUB

```http
GET /pocketbook/{uid}/download/{download_token}
```

Сервер скачивает EPUB у исходной библиотеки и возвращает файл PocketBook-клиенту. Email для PocketBook-клиента не требуется.

## Исходник

```text
pocketbook/main.c
```

Код рассчитан на InkView SDK и использует уже знакомые функции PocketBook:

```text
InkViewMain
QuickDownload
OpenKeyboard
Message
DrawString
DrawRect
FullUpdate
```

Команда сборки зависит от установленной версии PocketBook SDK/toolchain и в репозитории намеренно не зафиксирована.
