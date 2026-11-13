# BookFerry for PocketBook

PocketBook использует общий BookFerry API. Отдельного `/pocketbook/...` backend нет.

Клиент написан на C с использованием PocketBook InkView SDK и находится в `pocketbook/main.c`.

## Как работает клиент

При первом запуске PocketBook регистрируется:

```text
GET /users/register?client_type=pocketbook&plain=1
```

Backend создаёт пользователя и возвращает UUID `uid`. Он сохраняется локально и затем используется для профиля, поиска и скачивания.

Конфигурация хранится в:

```text
/mnt/ext1/system/config/BookFerry/config.cfg
```

Текущий формат:

```text
uid
имя выбранного каталога
custom OPDS URL
server URL
```

Старый конфиг без четвёртой строки совместим: используется встроенный адрес сервера.

## API

PocketBook использует те же ресурсы, что и другие клиенты, но для простого парсинга может запросить `plain=1`.

### Каталоги

```text
GET /catalogs?plain=1
```

### Профиль

```text
GET /users/{uid}?plain=1
```

### Выбор встроенного каталога

```text
GET /users/{uid}/catalog?catalog_id=3&plain=1
```

### Custom OPDS

```text
GET /users/{uid}/opds?opds_url=<url>&plain=1
```

### Поиск

```text
GET /search?uid=<uid>&query=<query>&plain=1
```

Формат ответа:

```text
COUNT	20
BOOK	<title>	<author>	<url>
BOOK	<title>	<author>	<url>
NEXT	<page_token>
```

Строковые поля percent-encoded.

### Скачивание

```text
GET /download?uid=<uid>&url=<book_url>
```

Для PocketBook backend использует streaming download:

```text
book source -> BookFerry -> PocketBook
```

BookFerry не ждёт полной загрузки EPUB перед началом ответа клиенту и не создаёт временный файл.

PocketBook download flow не отправляет книгу по e-mail. E-mail delivery используется Telegram-клиентом.

URL книги проходит через `safe_http` validation.

## Сохранение книги

После получения данных клиент проверяет ZIP/EPUB signature (`PK`) и сохраняет книгу в:

```text
/mnt/ext1/Books
```

Локальное имя формируется из автора и названия книги:

```text
Автор - Название.epub
```

Недопустимые для имени файла символы заменяются.

## Интерфейс

Главный экран содержит:

- выбор библиотеки;
- поле названия или автора;
- кнопку поиска;
- экран «О программе».

Результаты показываются по 5 книг на экран.

Встроенные каталоги и custom OPDS выбираются через один экран библиотек.

## Автоматическое обновление библиотеки PocketBook (2.2)

После завершения асинхронной загрузки и успешного переименования временного
EPUB в `/mnt/ext1/Books`, клиент вызывает `BookReady(filepath)`.
Это экспериментальное уведомление InkView: появление книги в системной
библиотеке зависит от прошивки и требует проверки на устройстве PB632.
Ручная кнопка сканирования и запуск `scanner.app` удалены.

## Smoke test

Backend flow можно проверить без физического ридера:

```bash
python scripts/smoke_pocketbook.py \
  --base-url http://127.0.0.1:8000 \
  --query "лабиринт отражений"
```

Smoke test выполняет:

```text
register
  -> catalogs
  -> select catalog
  -> search
  -> download
```

Успешный результат:

```text
POCKETBOOK SMOKE: PASSED
```

## Автоматическая сборка приложения

GitHub Actions: [Build PocketBook client](../.github/workflows/pocketbook-build.yml).

После изменения файлов `pocketbook/**` в PR или main, либо ручного запуска
`workflow_dispatch`, собираются два варианта:

- `pb632-fw6` — PocketBook Touch HD 3 / PB632, SDK B288 6.10.
- `pocketbook-armv7-softfp` — экспериментальная общая сборка для ARMv7 softfp.
  Совместимость с другими моделями нужно проверить на реальных устройствах.

В каждом артефакте есть `BookFerry.app` и ZIP с этим файлом.
Из архива GitHub Actions извлеките `BookFerry.app`, затем скопируйте
его в папку `/applications` на накопителе PocketBook, заменив старую
версию при необходимости. Конфиг в `system/config/BookFerry` не трогайте.

Локальная сборка на Linux с `curl`, `7z`, `zip`, Python 3 и SDK:

```bash
PB_TARGET=pb632-fw6 bash pocketbook/build.sh
```

Скрипт проверяет SHA-256 SDK перед использованием, компилирует исходник
`pocketbook/main.c` через InkView SDK, проверяет ARM ELF и создаёт
`dist/BookFerry-pb632-fw6.zip`. Текущий `pocketbook/BookFerry.app`
остаётся нетронутым: CI публикует новый бинарник только как артефакт.
