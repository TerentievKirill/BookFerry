# BookFerry API Tests

This directory contains a small API automation framework for BookFerry.

The goal of this test suite is not to maximize the number of test cases.  
It is intentionally small and demonstrates how I usually structure API automation: clear separation between HTTP clients, test data, reusable business flows, response models, and test scenarios.

## Test strategy

The suite is intentionally split into two layers with different purposes.

### Smoke tests

The deterministic smoke suite runs on every push and pull request.

Its purpose is to answer a simple question:

> Did this code change break the basic BookFerry functionality?

The smoke tests cover:

- user registration for supported client types;
- validation of unsupported client types;
- user profile updates;
- handling of unknown users;
- book search;
- validation of search response contracts;
- a complete business flow: create user → configure catalog → search for a book.

Some scenarios are parametrized, so the current smoke suite produces 10 pytest test cases while keeping the number of logical scenarios small.

These tests use deterministic local test data and do not depend on external libraries being available.

### External E2E tests

External E2E tests verify BookFerry as a complete service, including its real external dependencies.

They are intentionally separated from the smoke suite because an external library can be temporarily unavailable even when BookFerry itself is healthy.

There are two logical E2E scenarios, parametrized by supported library:

1. **Search E2E** — create a user, select a catalog, search for a known book and verify that the expected book is returned.
2. **Download E2E** — perform the same search, take the returned download URL and actually download the book through BookFerry.

The download scenario verifies:

- HTTP 200 response;
- EPUB content type;
- non-empty file content;
- ZIP/EPUB signature (`PK`).

The current parameter set covers the built-in catalogs:

- Project Gutenberg;
- The Anarchist Library;
- Flibusta;
- Библиотека Анархизма.

These tests are marked with `@pytest.mark.e2e`.

A failure in this suite can therefore mean either a BookFerry regression or a real availability/problem in one of the external services. That is useful information: the purpose of this suite is to verify that the service actually works from the user's point of view.

## Structure

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
├── conftest.py
├── test_book_flow.py
├── test_external_e2e.py
├── test_search.py
└── test_users.py
```

### `framework/api.py`

`BookFerryApi` is a thin HTTP client around the BookFerry API.

Each method corresponds to an API operation and returns the original
`requests.Response`.

Assertions are deliberately kept out of the API layer.

This makes the same client suitable for both positive and negative tests:

```python
response = api.register_user(
    client_type="pocketbook",
    external_id="autotest-user",
)

assert response.status_code == 201
```

### `framework/models.py`

The tests have their own Pydantic response models:

```python
user = User.model_validate(response.json())
```

They are intentionally separate from the application models.

The tests therefore validate the HTTP contract independently instead of
reusing the same Python models that generated the response.

This allows model validation to work as an additional API contract check.

### `framework/flows.py`

Flows contain reusable multi-step business scenarios.

For example:

```text
register user
    ↓
select catalog
    ↓
read user
    ↓
search books
```

Simple HTTP calls remain in `BookFerryApi`; only actual multi-step scenarios
belong in the flow layer.

This keeps tests short without hiding their intent.

### `fixtures/`

Reusable test entities are created through pytest fixtures.

Example:

```python
def test_user_profile_can_be_updated(api, pocketbook_user):
    ...
```

Fixtures may depend on other fixtures, which allows more complex test states
to be composed without duplicating preparation code.

### `data/`

Tests use dedicated SQLite databases:

```text
bookferry_test.db  — users and available catalogs
catalog_test.db    — searchable book catalog snapshot
```

The test suite does not access these databases directly.

BookFerry itself receives their paths when the Docker container is started,
and tests interact with the application only through HTTP.

`bookferry_test.db` provides deterministic user/catalog configuration.

`catalog_test.db` can be a snapshot of the real BookFerry catalog database. This allows search scenarios to use realistic production-like catalog data while keeping the test input reproducible. External E2E download tests then use the real download URLs generated from that catalog data and contact the external libraries through BookFerry.

## Parametrization

Client registration is checked using pytest parametrization:

```python
@pytest.mark.parametrize(
    "client_type",
    [
        pytest.param("telegram", id="telegram"),
        pytest.param("pocketbook", id="pocketbook"),
        pytest.param("flutter", id="flutter"),
    ],
)
```

The same approach is used for external E2E scenarios: one logical search test and one logical download test are executed against multiple supported catalogs.

This keeps the number of test functions small without duplicating scenarios.

## Running locally

BookFerry should be available on:

```text
http://127.0.0.1:8000
```

Run the deterministic smoke suite:

```bash
pytest tests -v -m "not e2e"
```

Run only external E2E tests:

```bash
pytest tests/test_external_e2e.py -v -s -m e2e
```

Run everything:

```bash
pytest tests -v
```

A different API endpoint can be supplied explicitly:

```bash
pytest tests -v --base-url=http://example:8000
```

## CI

The project uses two GitHub Actions workflows.

### Smoke CI

The regular `Tests` workflow runs on pushes and pull requests:

```text
checkout repository
        ↓
install dependencies
        ↓
build BookFerry Docker image
        ↓
start BookFerry with test databases
        ↓
run deterministic smoke tests
```

Its job is to detect regressions introduced by code changes as quickly and reliably as possible.

### Daily External E2E

The `External E2E` workflow runs once per day and can also be started manually.

```text
checkout repository
        ↓
build and start BookFerry
        ↓
search known books in supported catalogs
        ↓
download the books through BookFerry
        ↓
verify the real end-to-end result
```

This workflow acts as a daily check that BookFerry and its supported external libraries still work together in practice.

Every GitHub Actions run starts from the committed clean test databases, so test-created users and other changes are automatically discarded together with the CI runner.

No separate shared testing environment or persistent test database is required.

## Design decisions

The framework is intentionally small.

There is no generic HTTP abstraction hierarchy, repository layer, database
helper framework, or large collection of utility classes.

For a project of this size they would add more code than value.

The main principles are:

- tests describe behavior rather than implementation details;
- HTTP operations are isolated in the API layer;
- response contracts are validated independently with Pydantic;
- reusable preparation lives in fixtures;
- reusable multi-step scenarios live in flows;
- smoke test data is deterministic;
- external E2E tests deliberately verify real dependencies;
- CI runs the real application in Docker;
- smoke and E2E tests answer different questions and therefore run on different schedules;
- each test should demonstrate meaningful behavior rather than increase the test count.

The result is a small test suite that can be understood quickly while still showing the structure used in larger API automation projects.
