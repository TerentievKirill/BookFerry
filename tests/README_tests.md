# BookFerry API Tests

This directory contains a small API automation framework for BookFerry.

The goal of this test suite is not to maximize the number of test cases.  
It is intentionally small and demonstrates how I usually structure API automation: clear separation between HTTP clients, test data, reusable business flows, response models, and test scenarios.

## What is tested

The current suite covers the main BookFerry API scenarios:

- user registration for supported client types;
- validation of unsupported client types;
- user profile updates;
- handling of unknown users;
- book search;
- validation of search response contracts;
- a complete business flow: create user → configure catalog → search for a book.

Some scenarios are parametrized, so the current suite produces 10 pytest test cases while keeping the number of logical scenarios small.

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
catalog_test.db    — local searchable book index
```

The test suite does not access these databases directly.

BookFerry itself receives their paths when the Docker container is started,
and tests interact with the application only through HTTP.

This keeps the tests close to black-box API testing while providing
deterministic test data.

The catalog contains a few predefined books, so search tests do not depend
on external OPDS services or network availability.

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

This demonstrates the same scenario for several inputs without creating
separate nearly identical tests.

## Running locally

BookFerry should be available on:

```text
http://127.0.0.1:8000
```

Run:

```bash
pytest tests -v
```

A different API endpoint can be supplied explicitly:

```bash
pytest tests -v --base-url=http://example:8000
```

## CI

The test suite is executed automatically by GitHub Actions.

The workflow:

```text
checkout repository
        ↓
install dependencies
        ↓
build BookFerry Docker image
        ↓
start BookFerry with test databases
        ↓
run pytest
```

Every GitHub Actions run starts from the committed clean SQLite databases,
so test-created users and other changes are automatically discarded together
with the CI runner.

No separate shared testing environment or persistent test database is
required.

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
- test data is deterministic;
- CI runs the real application in Docker;
- each test should demonstrate a meaningful behavior rather than increase
  the test count.

The result is a small test suite that can be understood quickly while still
showing the structure used in larger API automation projects.
