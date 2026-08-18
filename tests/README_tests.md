# BookFerry API Tests

This directory contains a deliberately small API automation framework for BookFerry.

The goal is not to build a large test platform around a small service. The suite checks the real HTTP contracts used by BookFerry clients and keeps the layers easy to follow:

```text
HTTP client -> fixtures / reusable flows -> test scenarios
```

Application Pydantic models are not imported into the tests. Test-side response models live in `tests/framework/models.py`, so HTTP responses are validated independently from the models that produced them.

## What is tested

The backend currently serves two real client paths:

- PocketBook uses the `uid`-based GET API;
- Telegram uses compatibility endpoints while sharing the same search/download backend logic.

The tests cover both paths where that adds value, without creating test-only production endpoints.

## Smoke suite

Smoke tests use committed deterministic SQLite snapshots and do not depend on external book sources being available.

Current smoke coverage includes:

- PocketBook registration;
- Telegram user creation through the real lazy settings flow;
- rejection of unsupported client types;
- reading PocketBook and Telegram profiles;
- changing PocketBook and Telegram catalogs;
- `404` for unknown PocketBook and Telegram users;
- local book search for PocketBook;
- local book search for Telegram;
- independent Pydantic response validation;
- the basic business flow `register/create -> select catalog -> search`.

The smoke suite answers one practical question:

> Did this code change break the basic BookFerry behavior used by current clients?

Smoke files:

```text
tests/smoke/test_users.py
tests/smoke/test_book_flow.py
```

## External E2E suite

External E2E starts the same BookFerry application with deterministic local metadata, then continues across the network boundary to real EPUB sources.

There are two parametrized scenarios for each built-in catalog:

1. **Search flow** — register a PocketBook user, select a catalog and find a known book in the local BookFerry index.
2. **Download flow** — perform the same search and download the selected EPUB through BookFerry from the real source.

Catalog cases currently cover:

- Project Gutenberg;
- The Anarchist Library;
- Flibusta;
- Библиотека Анархизма.

The download scenario verifies:

- HTTP `200`;
- EPUB content type;
- non-trivial response size;
- ZIP/EPUB signature (`PK`).

External scenarios are marked with `@pytest.mark.e2e`.

A failure here may mean either a BookFerry regression or a real external-source outage/change. That is why these tests are intentionally separated from deterministic smoke CI.

## Directory structure

```text
tests/
├── data/
│   ├── bookferry_test.db
│   └── catalog_test.db
│
├── fixtures/
│   └── users.py
│
├── framework/
│   ├── api.py
│   ├── flows.py
│   └── models.py
│
├── smoke/
│   ├── test_book_flow.py
│   └── test_users.py
│
├── e2e/
│   └── test_external_e2e.py
│
├── conftest.py
└── README_tests.md
```

## `framework/api.py`

`BookFerryApi` is a thin HTTP wrapper around the real server API.

Each method performs one HTTP request and returns the original `requests.Response`. Assertions do not belong in this layer.

Example:

```python
response = api.register_user(client_type="pocketbook")
assert response.status_code == 200
```

The wrapper covers endpoints used by current clients, including:

```text
GET   /users/register
GET   /users/{uid}
GET   /users/{uid}/catalog
GET   /users/{uid}/opds
GET   /search
GET   /download
GET   /users/telegram/{telegram_id}
PATCH /users/telegram/{telegram_id}/catalog
```

Tests normally use JSON responses. The PocketBook C client can request the supported GET resources with `plain=1`.

## `framework/models.py`

Test response models are independent from `app.models`.

Example:

```python
user = User.model_validate(response.json())
```

This makes model validation an actual contract check instead of validating an application response with the exact same model that created it.

## `framework/flows.py`

Flows contain reusable multi-step business scenarios.

Typical flow:

```text
register/create client
        ↓
select catalog
        ↓
read profile
        ↓
search books
```

Examples used by the current smoke suite:

```python
flow.create_configured_pocketbook_user(catalog_id=3)
flow.create_configured_telegram_user(telegram_id=..., catalog_id=3)
flow.find_first_book(uid=..., query="Лабиринт отражений")
```

Single HTTP calls stay in `BookFerryApi`; only reusable multi-step behavior belongs in `flows.py`.

## Fixtures

`tests/fixtures/users.py` prepares reusable client state through the HTTP API.

The suite intentionally does not mutate the SQLite files directly to prepare scenarios. Pytest talks to BookFerry through HTTP, the same way a real client does.

Telegram e-mail/subject settings are not mixed into the basic search fixture because they belong to the delivery path rather than the minimal search smoke.

## Test data

Tests use two committed SQLite snapshots:

```text
bookferry_test.db  — users and catalog configuration
catalog_test.db    — searchable metadata snapshot
```

The Docker test container receives these paths through environment variables:

```text
DB_NAME=/app/tests/data/bookferry_test.db
CATALOG_DB_NAME=/app/tests/data/catalog_test.db
```

Each CI runner starts from the repository copy, so users created during a run disappear with the runner.

The local catalog snapshot makes search deterministic while external E2E can still use the source URLs generated by BookFerry and verify the actual download boundary.

## Running locally

BookFerry should be available at:

```text
http://127.0.0.1:8000
```

Run deterministic smoke tests:

```bash
pytest tests/smoke -v -s -m "not e2e"
```

Run external E2E only:

```bash
pytest tests/e2e/test_external_e2e.py -v -s -m e2e
```

Run everything:

```bash
pytest tests -v
```

Use another server:

```bash
pytest tests -v --base-url=http://example:8000
```

## CI

BookFerry has three GitHub Actions workflows related to tests and reporting.

### `tests.yml` — deterministic smoke

Runs on:

- push to `main`;
- push to `testing`;
- pull request targeting `main`.

Flow:

```text
checkout
   ↓
install Python dependencies
   ↓
build BookFerry Docker image
   ↓
start BookFerry with committed test DBs
   ↓
run tests/smoke
   ↓
upload allure-results artifact
```

Smoke should fail only when the application or its deterministic HTTP contract is broken.

### `external-e2e.yml` — real-source boundary

Triggered manually through `workflow_dispatch`.

Flow:

```text
start BookFerry
    ↓
search known books in all built-in catalogs
    ↓
download EPUB from real source
    ↓
validate returned file
    ↓
upload allure-results artifact
```

Keeping this workflow separate prevents temporary third-party outages from turning ordinary commits red.

### `allure-report.yml` — combined report

Runs daily and can also be triggered manually.

It checks out both repositories:

```text
BookFerry
BookFerryBot
```

Then it runs:

```text
BookFerry smoke
BookFerry external E2E
BookFerryBot external E2E
```

All suites write into one `allure-results` directory. Allure 3 groups the final report by `parentSuite` and `suite`, so backend smoke, backend external E2E and bot E2E remain visually separated without producing multiple reports.

Published report: https://allure.heartlab.app/

## Allure metadata

Tests use only a small amount of Allure metadata on purpose.

Typical structure:

```python
@allure.parent_suite("BookFerry")
@allure.suite("Smoke")
@allure.title("PocketBook user can be registered")
```

External tests use:

```python
@allure.parent_suite("BookFerry")
@allure.suite("External E2E")
```

The point is readable reporting, not decorating every line with reporting-specific code.

## Design rules

The framework is intentionally small.

There is no generic repository layer, HTTP abstraction hierarchy, direct DB helper, or test-only production API.

The main rules are:

- tests describe behavior rather than implementation details;
- the API layer contains HTTP calls, not assertions;
- response models are independent from application models;
- reusable state belongs in fixtures;
- reusable multi-step behavior belongs in flows;
- smoke data is deterministic;
- external E2E is isolated from smoke;
- both real client contracts may be tested when useful;
- tests follow endpoints used by real clients instead of keeping obsolete routes alive only for automation;
- Allure metadata stays minimal and readable.

The result is a compact suite that is close to the application, easy to understand and useful both as regression protection and as an example of API automation structure.