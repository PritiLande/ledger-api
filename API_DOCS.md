# API Documentation

Base URL: `http://127.0.0.1:8000` - interactive docs also at `/docs` (Swagger) and `/redoc`.
All bodies are JSON. Amounts are decimal numbers with **at most 2 decimal places**. Timestamps are UTC (ISO 8601, `Z`).

## Endpoints

| Method | Path | Description | Success |
|---|---|---|---|
| POST | `/accounts` | Create account (balance starts at 0) | 201 |
| GET | `/accounts/{account_id}` | Get account and current balance | 200 |
| GET | `/accounts/{account_id}/balance` | Current balance (`account_id`, `balance`) | 200 |
| GET | `/accounts/{account_id}/transactions?type=&page=&limit=` | Filtered, paginated transactions, latest first | 200 |
| POST | `/transactions` | Create a credit/debit (updates balance atomically) | 201 |
| GET | `/transactions/{transaction_id}` | Get one transaction | 200 |
| POST | `/transfers` | Transfer money between two accounts (bonus) | 201 |
| GET | `/health` | Health check | 200 |

Transactions are **immutable**: `PUT`, `PATCH` and `DELETE` on `/transactions/{id}` return `405`.

---

### POST /accounts
```json
{ "name": "Alice" }
```
Response `201`:
```json
{ "id": 1, "name": "Alice", "balance": 0.0, "created_at": "2026-10-28T10:00:00.123456Z" }
```

### GET /accounts/{account_id}/balance
```json
{ "account_id": 1, "balance": 70.0 }
```
Unknown account -> `404 ACCOUNT_NOT_FOUND`; non-numeric ID -> `400 INVALID_ACCOUNT_ID`.

### POST /transactions
```json
{
  "account_id": 1,
  "type": "credit",
  "amount": 100.50,
  "description": "Salary",
  "reference_id": "TXN-0001"
}
```
| Field | Rules |
|---|---|
| `account_id` | required, integer, account must exist (else 404) |
| `type` | required, `credit` or `debit` |
| `amount` | required, > 0, max 2 decimal places |
| `description` | optional, up to 255 chars |
| `reference_id` | required, non-blank, up to 100 chars, unique per account |

Response `201`:
```json
{
  "id": 1, "account_id": 1, "type": "credit", "amount": 100.5,
  "description": "Salary", "reference_id": "TXN-0001", "transfer_id": null,
  "created_at": "2026-10-28T10:00:01.000000Z"
}
```

### GET /accounts/{account_id}/transactions
Query: `type` (optional: `credit` or `debit`; omit to get both), `page` (default 1, min 1) and
`limit` (default 10, min 1, max 100). Sorted by `created_at` descending. `pagination.total_records`
counts only the filtered results. An invalid `type` returns `400 INVALID_TRANSACTION_TYPE`.
```json
{
  "data": [ { "id": 3, "account_id": 1, "type": "debit", "amount": 30.0, "...": "..." } ],
  "pagination": { "current_page": 1, "page_size": 10, "total_records": 25, "total_pages": 3 }
}
```
A page past the end returns `200` with an empty `data` list.

### POST /transfers
```json
{
  "from_account_id": 1,
  "to_account_id": 2,
  "amount": 30,
  "description": "Rent share",
  "reference_id": "TRF-0001"
}
```
Response `201`:
```json
{
  "id": 1, "reference_id": "TRF-0001", "from_account_id": 1, "to_account_id": 2, "amount": 30.0,
  "created_at": "...Z",
  "debit_transaction":  { "type": "debit",  "account_id": 1, "reference_id": "TRF-0001:debit",  "...": "..." },
  "credit_transaction": { "type": "credit", "account_id": 2, "reference_id": "TRF-0001:credit", "...": "..." }
}
```
`reference_id` max length is 90 (the suffixes `:debit` / `:credit` are appended to create the two ledger entries).

---

## Errors

Every error uses the same shape:
```json
{
  "error": {
    "code": "INSUFFICIENT_BALANCE",
    "message": "Account 1 has insufficient balance for this debit.",
    "details": [ { "field": "amount", "message": "..." } ]
  }
}
```
`details` appears only for validation errors.

| HTTP | `code` | When |
|---|---|---|
| 400 | `INVALID_PAGINATION` | `page`/`limit` non-numeric, `page < 1`, `limit < 1` or `> 100` |
| 400 | `INVALID_TRANSACTION_TYPE` | the `type` filter on the history endpoint is not `credit` / `debit` |
| 400 | `INVALID_ACCOUNT_ID` | account ID in the URL is not a positive integer |
| 404 | `ACCOUNT_NOT_FOUND` | account does not exist (transactions, listing, transfers) |
| 404 | `TRANSACTION_NOT_FOUND` | transaction does not exist |
| 404 | `NOT_FOUND` | unknown route |
| 405 | `METHOD_NOT_ALLOWED` | e.g. editing/deleting a transaction |
| 409 | `DUPLICATE_TRANSACTION` | same `reference_id` already used for that account; `details` holds `existing_transaction_id`. Nothing is created and the balance is unchanged |
| 409 | `DUPLICATE_TRANSFER` | transfer `reference_id` already used |
| 422 | `INVALID_TRANSACTION_TYPE` | `type` is not `credit` / `debit` |
| 422 | `INVALID_AMOUNT` | amount missing, not a number, <= 0, or more than 2 decimals |
| 422 | `INSUFFICIENT_BALANCE` | debit/transfer exceeds balance (nothing is changed) |
| 422 | `INVALID_TRANSFER` | source and destination are the same account |
| 422 | `INVALID_REQUEST_BODY` | body missing or not valid JSON |
| 422 | `VALIDATION_ERROR` | any other invalid field (blank name/reference, unknown field, wrong type) |
| 500 | `INTERNAL_ERROR` | unexpected failure - everything is rolled back, no internals leaked |

## Quick try (curl)
```bash
curl -X POST localhost:8000/accounts -H 'content-type: application/json' -d '{"name":"Alice"}'
curl -X POST localhost:8000/transactions -H 'content-type: application/json' \
  -d '{"account_id":1,"type":"credit","amount":100,"reference_id":"r1"}'
curl "localhost:8000/accounts/1/transactions?page=1&limit=10"
```
