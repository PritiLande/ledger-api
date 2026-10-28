# Ledger API

A small REST API for **accounts**, **immutable transactions** and **atomic money transfers**, built with
**FastAPI + SQLAlchemy 2 + SQLite**. Integrity rules are enforced both in code *and* in the database.

## Run locally

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

- API: http://127.0.0.1:8000
- Interactive docs (Swagger): http://127.0.0.1:8000/docs
- The SQLite file `ledger.db` is created automatically on first start.
- Use another database with `DATABASE_URL` (SQLAlchemy URL). Note the immutability triggers are SQLite-specific.

## Run the tests

```bash
pytest -q
```

51 tests cover validation, error codes, pagination, immutability (API and database level), atomicity/rollback,
transfers and a concurrency test (10 parallel debits against a balance that only covers 5).

## Project structure

```
app/
  main.py          app wiring, startup (creates tables)
  database.py      engine, sessions, SQLite transaction setup
  models.py        tables + constraints + immutability triggers
  schemas.py       request validation and response models
  services.py      business logic (one DB transaction per operation)
  errors.py        error classes + handlers (consistent error JSON)
  routers/         accounts.py, transactions.py, transfers.py
tests/             pytest suite
API_DOCS.md        endpoint reference with examples
ASSUMPTIONS.md     design decisions and assumptions
```

## How each requirement is met

| Requirement | Approach |
|---|---|
| Filtering | `type=credit\|debit` on the history endpoint (omit for both) |
| Pagination | `page` / `limit` query params; response has `current_page`, `page_size`, `total_records`, `total_pages` |
| Latest first | `ORDER BY created_at DESC, id DESC` (id breaks ties) |
| Immutability | No PUT/PATCH/DELETE routes (405) **and** DB triggers reject any UPDATE/DELETE on `transactions` |
| Balance consistency | Balance only changes inside the same DB transaction that inserts the ledger row; `CHECK (balance >= 0)` backstop |
| Atomicity | Insert + balance update commit together or roll back together (see `services.py`) |
| Insufficient funds | Single `UPDATE ... WHERE balance >= amount` - check and spend in one statement, safe under concurrency |
| Duplicate reference | `UNIQUE (account_id, reference_id)` -> `409 DUPLICATE_TRANSACTION` |
| Validation | Pydantic models: required fields, type enum, amount > 0 with max 2 decimals, non-blank strings, unknown fields rejected |
| Error handling | One JSON shape for every error with a machine-readable `code` (see API_DOCS.md) |
| Transfer (bonus) | One DB transaction for both legs; both accounts verified; accounts touched in ascending id order to avoid deadlocks |
| DB constraints | `CHECK` (balance, amount, type), `UNIQUE`, `FOREIGN KEY` (enforced via `PRAGMA foreign_keys=ON`) |
| Money precision | Stored as integer minor units (paise/cents), never floats |

## Known limitations

- SQLite serialises writers (`BEGIN IMMEDIATE`), which is simple and correct but not built for high write throughput.
  On PostgreSQL the same code relies on the atomic conditional `UPDATE` and the constraints; the SQLite-only
  triggers would need to be ported.
- No authentication/authorisation (out of scope for the assignment).
- No account list/update/delete endpoints (not required).
