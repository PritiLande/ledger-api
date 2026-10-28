# Assumptions and Design Decisions

1. **Endpoint design.** The brief didn't prescribe URLs, so: `POST /accounts`, `POST /transactions` (with
   `account_id` in the body, as the spec says "Account ID must exist when creating a transaction"),
   `GET /accounts/{id}/transactions` for the paginated list, and `POST /transfers`.
2. **Account.** Only `name` is accepted on creation; the initial balance is always 0 and can change only through
   transactions. Account names need not be unique. There is no endpoint to edit or delete accounts.
3. **Money.** Amounts are positive decimals with at most 2 decimal places (rupees/dollars). Internally they are
   stored as integer paise/cents to avoid floating-point errors. Maximum 15 digits.
4. **Credit** increases the balance, **debit** decreases it. A debit may use the entire balance; the balance can
   never go below 0.
5. **Duplicate `reference_id`.** Unique per account (not globally). A repeated reference on the same account
   returns `409` and is **not** applied again, so a client retry can never double-charge. The same reference may be
   used on a different account.
6. **`type` is case-insensitive** on input (`"CREDIT"` is accepted) and stored lowercase. Surrounding whitespace in
   `name` and `reference_id` is trimmed; blank values are rejected.
7. **Unknown JSON fields are rejected** (422) so typos such as `ammount` don't silently pass.
8. **Immutability.** Transactions have no update/delete API (405). A database trigger additionally blocks direct
   `UPDATE`/`DELETE`. Corrections are made by posting a new compensating transaction. `transfers` rows are
   immutable too.
9. **Duplicate response.** A repeated `reference_id` returns `409 DUPLICATE_TRANSACTION` including the id of the
   existing transaction, rather than `200` with the old record, so clients can't mistake a retry for a new posting.
   **History filter.** `type=credit|debit` filters; omitted means both; any other value is `400`.
   **Balance.** Available both as `GET /accounts/{id}` (full account) and `GET /accounts/{id}/balance`.
10. **Sorting.** Latest first by `created_at`; `id` is the tie-breaker so ordering is stable.
11. **Pagination.** `page` starts at 1, default `limit` is 10, maximum 100. Invalid values are rejected with `400`
    rather than silently clamped. A page beyond the last returns an empty list (not an error).
12. **Status codes.** 400 for invalid path/query values, 404 for missing resources, 409 for duplicates, 422 for
    invalid body data and for business-rule rejections (insufficient balance, invalid transfer).
13. **Transfers.** Recorded as one `transfers` row plus two ledger transactions (a debit on the source and a
    credit on the destination, with `reference_id` = `<ref>:debit` / `<ref>:credit` and a shared `transfer_id`).
    Source and destination must differ. Transfer `reference_id` must be globally unique.
14. **Timestamps** are UTC, returned in ISO 8601 with a `Z` suffix.
15. **Database.** SQLite for zero-setup local running. Concurrency is handled by `BEGIN IMMEDIATE` plus an atomic
    conditional `UPDATE`; the design maps directly to PostgreSQL (row locks) if needed.
16. **Out of scope:** authentication, multi-currency, account closing, rate limiting.
