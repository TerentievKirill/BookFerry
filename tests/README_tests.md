# BookFerry Test Engineering

BookFerry is a small production project, so there is little value in building hundreds of tests just to increase the test count.

Instead, I built the test infrastructure using the same principles I would use for a much larger production system, while keeping the actual suite proportional to the size of the project.

The repository is intended to demonstrate **test engineering decisions rather than test volume**. A test for something like `GET /health -> 200 OK` would be trivial to add, but would not demonstrate anything particularly interesting.

At the same time, these tests are not portfolio-only examples: they solve practical regression and integration problems for the live BookFerry service.

With the current parametrization the project has **22 test cases** across three deliberately different layers:

| Layer | Cases | Main purpose |
|---|---:|---|
| Deterministic backend smoke | 10 | Detect basic BookFerry regressions quickly |
| Backend external E2E | 8 | Check catalog flows and the real EPUB download boundary |
| BookFerryBot cross-repository E2E | 4 | Verify the real client/server integration against the deployed API |

## Quick links

- **Live Allure report:** https://allure.heartlab.app/
- **Backend smoke tests:** [BookFerry/tests/smoke](https://github.com/TerentievKirill/BookFerry/tree/readme/tests/smoke)
- **Backend external E2E:** [BookFerry/tests/e2e/test_external_e2e.py](https://github.com/TerentievKirill/BookFerry/blob/readme/tests/e2e/test_external_e2e.py)
- **Telegram client repository:** [BookFerryBot](https://github.com/TerentievKirill/BookFerryBot)
- **BookFerryBot cross-repository E2E:** [BookFerryBot/tests/test_external_e2e.py](https://github.com/TerentievKirill/BookFerryBot/blob/main/tests/test_external_e2e.py)
- **BookFerryBot E2E workflow:** [BookFerryBot/.github/workflows/external-e2e.yml](https://github.com/TerentievKirill/BookFerryBot/blob/main/.github/workflows/external-e2e.yml)
- **Combined quality workflow:** [BookFerry/.github/workflows/allure-report.yml](../.github/workflows/allure-report.yml)

## Two repositories, one quality pipeline

BookFerry is not tested as an isolated repository only.

The backend and the Telegram client are developed and deployed separately:

```text
BookFerry repository
  ├─ deterministic backend smoke
  └─ backend external E2E

BookFerryBot repository
  └─ E2E using the bot's production API client
```

The scheduled/manual quality workflow in the backend repository checks out **both repositories**, runs all three groups and writes their results into the same `allure-results` directory:

```text
BookFerry smoke
        +
BookFerry external E2E
        +
BookFerryBot production-client E2E
        ↓
 one Allure 3 report
        ↓
https://allure.heartlab.app/
```

This is useful for a real architectural reason: a backend can pass its own tests and still break an independently deployed client. The BookFerryBot scenario checks that boundary from the client side using the same API client code as the application itself.

## Testing strategy

The suites are separated by what a failure means, not just by directory structure.

### 1. Deterministic smoke — did I break BookFerry?

The smoke suite checks the basic application behavior and **both current backend client contracts**:

- PocketBook uses the `uid`-based API;
- Telegram uses its compatibility API while sharing the same backend search logic.

It runs against committed SQLite test snapshots and does not require external book providers to be available. That makes it useful as fast CI feedback: a smoke failure normally points to the application or its API contract rather than to a temporary Internet dependency.

The suite runs automatically on pull requests targeting `main` and on pushes to `main` / `testing`.

The current smoke coverage includes:

**PocketBook API**

- user registration and UUID creation;
- reading a user profile;
- changing the selected catalog;
- handling an unknown user;
- deterministic book search through the `uid` contract.

**Telegram compatibility API**

- lazy user creation through the real settings flow;
- reading a Telegram user profile;
- changing the Telegram user's catalog;
- handling an unknown Telegram user;
- deterministic book search through the Telegram contract.

**Contract / business behavior**

- rejection of unsupported client types;
- independent Pydantic response model validation;
- the basic business flow `register/create -> select catalog -> search`.

So the smoke suite is intentionally more than a PocketBook test set: the same backend behavior is exercised through two different real client contracts where that distinction matters.

The practical question is intentionally simple:

> Did this code change break the basic BookFerry functionality used by current clients?

Smoke files:

- [`tests/smoke/test_users.py`](smoke/test_users.py)
- [`tests/smoke/test_book_flow.py`](smoke/test_book_flow.py)

### 2. Backend external E2E — does BookFerry still work with the outside world?

External E2E uses the same application and deterministic catalog metadata, but continues past local search and reaches the **real EPUB source**.

There are **two parametrized scenarios for each built-in catalog**:

1. **Search scenario** — create/configure a PocketBook user, select a catalog and find a known book through BookFerry.
2. **Download scenario** — repeat the search flow, follow the selected book URL through BookFerry and retrieve a real EPUB from the external provider.

The scenarios are parametrized across all four built-in catalogs:

- Project Gutenberg;
- The Anarchist Library;
- Flibusta;
- Библиотека Анархизма.

That produces 8 backend external E2E cases without duplicating the scenario code.

The download test validates an actual book payload, not just a successful HTTP response:

```python
assert response.status_code == 200
assert response.headers["Content-Type"].startswith("application/epub")
assert len(response.content) > 1000
assert response.content.startswith(b"PK")
```

The last check verifies the ZIP signature used by EPUB files. Together these assertions make the scenario closer to "a usable book was returned" than simply "the endpoint answered 200".

A failure here has a different diagnostic meaning from a smoke failure: BookFerry may have regressed, but an external provider may also be unavailable or may have changed its behavior.

That distinction is why this suite has its own workflow instead of running as part of every pull request.

Backend E2E source: [`tests/e2e/test_external_e2e.py`](e2e/test_external_e2e.py).

### 3. Cross-repository E2E — does the real client still work with the real server?

This is the most system-level scenario in the project.

The Telegram client is maintained in a separate repository: [BookFerryBot](https://github.com/TerentievKirill/BookFerryBot).

Its E2E test does **not** use a test-only HTTP wrapper. It imports the same production API client functions that the bot itself uses:

```python
from app.api_client import download_book, search_books, update_catalog
```

The parametrized scenario performs the real client operations:

```text
BookFerryBot production API client
              ↓
       deployed BookFerry API
              ↓
       select real catalog
              ↓
          search book
              ↓
       external EPUB source
              ↓
     download + validate EPUB
```

The test connects to the deployed BookFerry API rather than to the Dockerized backend used by the deterministic suite. In other words, this is a compatibility check across **two repositories and two independently deployable components**.

The scenario runs for the same four catalog families and validates the downloaded EPUB by filename, payload size and ZIP/EPUB signature.

This means a server-side contract change can be caught from the point of view of the actual client integration rather than only from the backend test framework.

Direct links:

- [BookFerryBot E2E test](https://github.com/TerentievKirill/BookFerryBot/blob/main/tests/test_external_e2e.py)
- [BookFerryBot production API client](https://github.com/TerentievKirill/BookFerryBot/blob/main/app/api_client.py)
- [BookFerryBot scheduled E2E workflow](https://github.com/TerentievKirill/BookFerryBot/blob/main/.github/workflows/external-e2e.yml)

## Test architecture

```mermaid
flowchart TD
    PR[Push / Pull Request] --> SMOKE[Backend deterministic smoke]
    SMOKE --> TESTDB[(Committed SQLite snapshots)]

    MANUAL[Manual external run] --> BE2E[Backend external E2E]
    BE2E --> TESTDB
    BE2E --> SOURCES[Real book sources]

    BOTREPO[BookFerryBot repository] --> BOTE2E[Production-client E2E]
    BOTE2E --> LIVE[Deployed BookFerry API]
    LIVE --> SOURCES

    QUALITY[Scheduled / manual quality run] --> BACKENDREPO[Checkout BookFerry]
    QUALITY --> BOTCHECKOUT[Checkout BookFerryBot]
    BACKENDREPO --> SMOKE
    BACKENDREPO --> BE2E
    BOTCHECKOUT --> BOTE2E

    SMOKE --> RESULTS[Shared allure-results]
    BE2E --> RESULTS
    BOTE2E --> RESULTS
    RESULTS --> ALLURE[Unified Allure 3 report]
```

The important part is not the number of boxes. Each level answers a different question and has a different failure boundary, while the combined report still gives one place to inspect the state of the whole system.

## Representative test design

The individual tests stay deliberately small. Infrastructure details belong in reusable layers; scenario files should make the behavior obvious.

A typical smoke scenario reads almost like the product flow:

```python
user = flow.create_configured_pocketbook_user(
    catalog_id=3,
)

book = flow.find_first_book(
    uid=user.uid,
    query="Лабиринт отражений",
)

assert book.title
assert book.url
```

The test does not know how registration, catalog selection or search requests are serialized. Those details belong to the API and flow layers.

The same idea is used for Telegram: test scenarios describe client behavior, while the framework hides only repetitive protocol details rather than the meaning of the test.

## Small framework, clear responsibilities

The local framework is intentionally simple:

```text
BookFerryApi
     ↓
fixtures + reusable flows
     ↓
test scenarios
```

### `framework/api.py` — HTTP only

`BookFerryApi` is a thin wrapper around the real HTTP API.

Each method performs one request and returns the original `requests.Response`.

Assertions stay in the scenario layer:

```python
response = api.register_user(client_type="pocketbook")
assert response.status_code == 200
```

This keeps protocol details reusable without hiding test expectations behind framework magic.

### `framework/flows.py` — reusable business behavior

Flows contain multi-step operations that appear in more than one scenario:

```text
register/create client
        ↓
select catalog
        ↓
read profile
        ↓
search books
```

Single HTTP calls stay in `BookFerryApi`. A flow is added only when it represents reusable behavior rather than as another abstraction layer for its own sake.

### `framework/models.py` — independent contract models

The test suite does not import application Pydantic response models from `app.models`.

Instead it validates HTTP responses with independent test-side models:

```python
user = User.model_validate(response.json())
```

That way model validation checks the external HTTP contract instead of validating an application response using the exact same model that generated it.

### Fixtures — state through public APIs

Fixtures prepare users and configuration through BookFerry HTTP endpoints.

Tests do not directly edit SQLite to create convenient states. The databases are controlled test data, but the scenarios still interact with the service the way a client does.

## Deterministic test data

Smoke uses two committed SQLite snapshots:

```text
bookferry_test.db  — users and catalog configuration
catalog_test.db    — small searchable metadata snapshot
```

The Docker test container receives their paths through environment variables:

```text
DB_NAME=/app/tests/data/bookferry_test.db
CATALOG_DB_NAME=/app/tests/data/catalog_test.db
```

Every CI runner starts from the repository copy, so state created by one run disappears with that runner.

This gives smoke predictable search data without mocking the BookFerry API itself.

## CI/CD and reporting

The automation around the tests is part of the test design, not an afterthought.

### Pull request feedback

[`tests.yml`](../.github/workflows/tests.yml) builds the application in Docker, starts it with deterministic test databases and runs the smoke suite.

```text
checkout BookFerry
   ↓
install dependencies
   ↓
build BookFerry Docker image
   ↓
start isolated BookFerry
   ↓
run PocketBook + Telegram smoke
   ↓
upload allure-results
```

This workflow runs on pull requests targeting `main` and on pushes to `main` / `testing`.

The goal is fast and interpretable feedback on ordinary changes.

### External backend checks

[`external-e2e.yml`](../.github/workflows/external-e2e.yml) is manually triggered and runs the backend external suite against real book sources.

Keeping it separate means a third-party outage does not automatically turn normal development CI red.

### BookFerryBot's own external workflow

The client repository also has its own [scheduled/manual external E2E workflow](https://github.com/TerentievKirill/BookFerryBot/blob/main/.github/workflows/external-e2e.yml).

It runs the [cross-repository test](https://github.com/TerentievKirill/BookFerryBot/blob/main/tests/test_external_e2e.py) with the bot's production API client against the deployed BookFerry service.

So the client/server compatibility check can run independently of the backend repository's larger reporting pipeline.

### Combined quality run

[`allure-report.yml`](../.github/workflows/allure-report.yml) is the larger scheduled/manual quality workflow.

It explicitly checks out **two repositories**:

```text
BookFerry
BookFerryBot
```

and combines three test groups in one run:

```text
BookFerry deterministic smoke
BookFerry backend external E2E
BookFerryBot cross-repository E2E
```

The backend suites run against the Dockerized test instance. The BookFerryBot scenario uses the bot's production API client and connects to the deployed BookFerry API.

All three suites write into the same `allure-results` directory. Allure 3 groups them by suite and publishes one report for the whole quality run.

**Live report:** https://allure.heartlab.app/

Allure metadata stays intentionally minimal:

```python
@allure.parent_suite("BookFerry")
@allure.suite("Smoke")
@allure.title("PocketBook user can be registered")
```

The report should make a failure easier to understand; reporting code should not become a second test framework.

## What does a failure tell us?

One reason for keeping the layers separate is diagnostic value.

| Failure | First area to investigate |
|---|---|
| Deterministic PocketBook/Telegram smoke | BookFerry regression or HTTP contract change |
| Backend external E2E | BookFerry integration or external source |
| BookFerryBot E2E | Bot/server compatibility, deployed backend, or external source |

This is more useful than one large suite where every red test means "something somewhere is broken".

## Deliberate trade-offs

A few choices are intentionally boring.

**Why not test every endpoint?**  
Because this is a small project and test count is not the goal. Straightforward low-value cases such as a dedicated `GET /health -> 200` test can be added at any time; they do not demonstrate a different testing technique or protect an important business flow today.

**Why test both PocketBook and Telegram contracts in smoke?**  
Because they are two real clients using different public API shapes over shared backend logic. A change can preserve the common logic while still breaking one client contract.

**Why not mock every external dependency?**  
Smoke is already deterministic. The external suite exists specifically to verify the real integration boundary that mocks cannot prove.

**Why keep external E2E out of normal PR CI?**  
A third-party outage should not look like a deterministic regression in every pull request.

**Why independent response models?**  
Reusing application models in tests would make part of the contract validation self-referential.

**Why use the bot's production API client in E2E?**  
Because the interesting question is whether the independently deployed client still works after backend changes, not whether a second test-only client can call the same URL.

**Why no direct DB helper, repository abstraction or generic HTTP hierarchy?**  
Because none is needed yet. The framework should become more complex only when the product and test suite create a real reason for that complexity.

## Repository structure

```text
tests/
├── data/
│   ├── bookferry_test.db
│   └── catalog_test.db
├── fixtures/
│   └── users.py
├── framework/
│   ├── api.py
│   ├── flows.py
│   └── models.py
├── smoke/
│   ├── test_book_flow.py
│   └── test_users.py
├── e2e/
│   └── test_external_e2e.py
├── conftest.py
└── README_tests.md
```

The client-side cross-repository scenario is intentionally outside this tree because it belongs to the independently maintained client repository:

- [BookFerryBot/tests/test_external_e2e.py](https://github.com/TerentievKirill/BookFerryBot/blob/main/tests/test_external_e2e.py)

## Running locally

BookFerry should be available at:

```text
http://127.0.0.1:8000
```

Run deterministic backend smoke:

```bash
pytest tests/smoke -v -s -m "not e2e"
```

Run backend external E2E:

```bash
pytest tests/e2e/test_external_e2e.py -v -s -m e2e
```

Run all backend tests:

```bash
pytest tests -v
```

Use another backend instance:

```bash
pytest tests -v --base-url=http://example:8000
```

The framework is deliberately small. The interesting part is not how many abstractions or tests can be added, but how little infrastructure is needed to get useful, diagnosable feedback from a real running system — including a separately deployed client from another repository.