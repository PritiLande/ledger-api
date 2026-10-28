import threading

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from fastapi.testclient import TestClient

from app import services
from app.database import engine
from app.main import app


def balance(client, account_id):
    return client.get(f"/accounts/{account_id}").json()["balance"]


def tx_count(client, account_id):
    return client.get(f"/accounts/{account_id}/transactions").json()["pagination"]["total_records"]


# ------------------------------- accounts -----------------------------------
def test_create_account_starts_at_zero(client):
    r = client.post("/accounts", json={"name": "  Alice  "})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Alice" and body["balance"] == 0


@pytest.mark.parametrize("payload", [{}, {"name": ""}, {"name": "   "}, {"name": 5}, {"name": "x", "balance": 100}])
def test_create_account_validation(client, payload):
    r = client.post("/accounts", json=payload)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_invalid_json_body(client):
    r = client.post("/accounts", content="{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_REQUEST_BODY"


def test_account_not_found_and_invalid_id(client):
    assert client.get("/accounts/999").status_code == 404
    assert client.get("/accounts/999").json()["error"]["code"] == "ACCOUNT_NOT_FOUND"
    r = client.get("/accounts/abc")
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_ACCOUNT_ID"
    assert client.get("/accounts/0").status_code == 400


# ------------------------------ transactions --------------------------------
def test_balance_matches_spec_example(client, make_account, tx):
    a = make_account()
    for kind, amt in [("credit", 100), ("credit", 50), ("debit", 30), ("debit", 20)]:
        assert tx(a, kind, amt).status_code == 201
    assert balance(client, a) == 100


def test_decimal_amounts_are_exact(client, make_account, tx):
    a = make_account()
    tx(a, "credit", 0.1)
    tx(a, "credit", 0.2)
    assert balance(client, a) == 0.3


def test_insufficient_balance_rejected_and_nothing_changes(client, make_account, tx):
    a = make_account()
    tx(a, "credit", 50)
    r = tx(a, "debit", 50.01)
    assert r.status_code == 422 and r.json()["error"]["code"] == "INSUFFICIENT_BALANCE"
    assert balance(client, a) == 50
    assert tx_count(client, a) == 1  # the rejected debit left no row behind


def test_debit_of_exact_balance_allowed(client, make_account, tx):
    a = make_account()
    tx(a, "credit", 50)
    assert tx(a, "debit", 50).status_code == 201
    assert balance(client, a) == 0


@pytest.mark.parametrize(
    "overrides, code",
    [
        ({"type": "transfer"}, "INVALID_TRANSACTION_TYPE"),
        ({"type": None}, "INVALID_TRANSACTION_TYPE"),
        ({"amount": 0}, "INVALID_AMOUNT"),
        ({"amount": -5}, "INVALID_AMOUNT"),
        ({"amount": 1.005}, "INVALID_AMOUNT"),
        ({"amount": "abc"}, "INVALID_AMOUNT"),
        ({"reference_id": ""}, "VALIDATION_ERROR"),
        ({"reference_id": "   "}, "VALIDATION_ERROR"),
        ({"account_id": "x"}, "VALIDATION_ERROR"),
    ],
)
def test_transaction_validation(client, make_account, overrides, code):
    a = make_account()
    payload = {"account_id": a, "type": "credit", "amount": 10, "reference_id": "r1", **overrides}
    r = client.post("/transactions", json=payload)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == code


def test_missing_reference_id(client, make_account):
    a = make_account()
    r = client.post("/transactions", json={"account_id": a, "type": "credit", "amount": 10})
    assert r.status_code == 422


def test_transaction_for_unknown_account(client, tx):
    r = tx(999, "credit", 10)
    assert r.status_code == 404 and r.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"


def test_duplicate_reference_same_account(client, make_account, tx):
    a = make_account()
    assert tx(a, "credit", 100, ref="dup").status_code == 201
    r = tx(a, "credit", 100, ref="dup")
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_TRANSACTION"
    assert balance(client, a) == 100  # not applied twice


def test_same_reference_different_accounts_is_fine(client, make_account, tx):
    a, b = make_account("A"), make_account("B")
    assert tx(a, "credit", 10, ref="shared").status_code == 201
    assert tx(b, "credit", 10, ref="shared").status_code == 201


# -------------------------------- pagination --------------------------------
def test_pagination_and_latest_first(client, make_account, tx):
    a = make_account()
    for i in range(1, 26):
        tx(a, "credit", i, ref=f"r{i}")
    r = client.get(f"/accounts/{a}/transactions?page=1&limit=10").json()
    assert r["pagination"] == {"current_page": 1, "page_size": 10, "total_records": 25, "total_pages": 3}
    assert [t["reference_id"] for t in r["data"]] == [f"r{i}" for i in range(25, 15, -1)]
    last = client.get(f"/accounts/{a}/transactions?page=3&limit=10").json()
    assert [t["reference_id"] for t in last["data"]] == [f"r{i}" for i in range(5, 0, -1)]
    beyond = client.get(f"/accounts/{a}/transactions?page=9&limit=10").json()
    assert beyond["data"] == [] and beyond["pagination"]["total_pages"] == 3


def test_pagination_defaults_and_empty(client, make_account):
    a = make_account()
    r = client.get(f"/accounts/{a}/transactions").json()
    assert r["pagination"] == {"current_page": 1, "page_size": 10, "total_records": 0, "total_pages": 0}


@pytest.mark.parametrize("qs", ["page=0", "page=-1", "page=abc", "limit=0", "limit=101", "limit=x"])
def test_invalid_pagination(client, make_account, qs):
    a = make_account()
    r = client.get(f"/accounts/{a}/transactions?{qs}")
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_PAGINATION"


def test_list_for_unknown_account(client):
    assert client.get("/accounts/999/transactions").status_code == 404


# ------------------------------- immutability -------------------------------
def test_no_edit_or_delete_endpoints(client, make_account, tx):
    a = make_account()
    t = tx(a, "credit", 10).json()
    for method in ("put", "patch", "delete"):
        r = getattr(client, method)(f"/transactions/{t['id']}")
        assert r.status_code == 405
    assert client.get(f"/transactions/{t['id']}").json() == t


def test_database_blocks_update_and_delete(client, make_account, tx):
    a = make_account()
    t = tx(a, "credit", 10).json()
    with engine.begin() as conn:
        with pytest.raises(DatabaseError):
            conn.execute(text("UPDATE transactions SET amount = 999 WHERE id = :i"), {"i": t["id"]})
    with engine.begin() as conn:
        with pytest.raises(DatabaseError):
            conn.execute(text("DELETE FROM transactions WHERE id = :i"), {"i": t["id"]})
    assert client.get(f"/transactions/{t['id']}").json() == t


def test_database_blocks_negative_balance(client, make_account):
    a = make_account()
    with engine.begin() as conn:
        with pytest.raises(DatabaseError):
            conn.execute(text("UPDATE accounts SET balance = -1 WHERE id = :i"), {"i": a})


# -------------------------------- atomicity ---------------------------------
def test_failure_after_insert_rolls_back_everything(client, make_account, tx, monkeypatch):
    a = make_account()
    tx(a, "credit", 100)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated crash while updating balance")

    monkeypatch.setattr(services, "_adjust_balance", boom)
    r = tx(a, "credit", 25)
    assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL_ERROR"
    monkeypatch.undo()
    assert balance(client, a) == 100
    assert tx_count(client, a) == 1  # the inserted row was rolled back too


def test_concurrent_debits_never_overspend(client, make_account, tx):
    a = make_account()
    tx(a, "credit", 100)
    results = []

    def worker(i):
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.post(
                "/transactions",
                json={"account_id": a, "type": "debit", "amount": 20, "reference_id": f"c{i}"},
            )
            results.append(r.status_code)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [201] * 5 + [422] * 5
    assert balance(client, a) == 0


def test_balance_equals_sum_of_transactions(client, make_account, tx):
    a = make_account()
    for kind, amt in [("credit", 75.5), ("debit", 10.25), ("credit", 4), ("debit", 0.25)]:
        tx(a, kind, amt)
    entries = client.get(f"/accounts/{a}/transactions?limit=100").json()["data"]
    expected = sum(e["amount"] if e["type"] == "credit" else -e["amount"] for e in entries)
    assert balance(client, a) == round(expected, 2) == 69


# --------------------------------- transfers --------------------------------
def transfer(client, src, dst, amount, ref="t1"):
    return client.post(
        "/transfers",
        json={"from_account_id": src, "to_account_id": dst, "amount": amount, "reference_id": ref},
    )


def test_transfer_success(client, make_account, tx):
    a, b = make_account("A"), make_account("B")
    tx(a, "credit", 100)
    tx(b, "credit", 50)
    r = transfer(client, a, b, 30)
    assert r.status_code == 201
    body = r.json()
    assert body["debit_transaction"]["type"] == "debit" and body["credit_transaction"]["type"] == "credit"
    assert balance(client, a) == 70 and balance(client, b) == 80


def test_transfer_insufficient_balance_changes_nothing(client, make_account, tx):
    a, b = make_account("A"), make_account("B")
    tx(a, "credit", 10)
    r = transfer(client, a, b, 30)
    assert r.status_code == 422 and r.json()["error"]["code"] == "INSUFFICIENT_BALANCE"
    assert balance(client, a) == 10 and balance(client, b) == 0
    assert tx_count(client, a) == 1 and tx_count(client, b) == 0


def test_transfer_rolls_back_if_second_leg_fails(client, make_account, tx, monkeypatch):
    a, b = make_account("A"), make_account("B")  # a.id < b.id -> a is processed first
    tx(a, "credit", 100)
    real = services._adjust_balance
    calls = {"n": 0}

    def flaky(db, account_id, tx_type, amount):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("second leg crashed")
        return real(db, account_id, tx_type, amount)

    monkeypatch.setattr(services, "_adjust_balance", flaky)
    r = transfer(client, a, b, 30)
    monkeypatch.undo()
    assert r.status_code == 500
    assert balance(client, a) == 100 and balance(client, b) == 0  # no partial transfer
    assert tx_count(client, a) == 1 and tx_count(client, b) == 0


def test_transfer_validation_errors(client, make_account, tx):
    a, b = make_account("A"), make_account("B")
    tx(a, "credit", 100)
    assert transfer(client, a, 999, 10).status_code == 404
    assert transfer(client, 999, b, 10).status_code == 404
    same = transfer(client, a, a, 10)
    assert same.status_code == 422 and same.json()["error"]["code"] == "INVALID_TRANSFER"
    assert transfer(client, a, b, 0).status_code == 422
    assert transfer(client, a, b, -1).status_code == 422
    assert balance(client, a) == 100 and balance(client, b) == 0


def test_duplicate_transfer_reference(client, make_account, tx):
    a, b = make_account("A"), make_account("B")
    tx(a, "credit", 100)
    assert transfer(client, a, b, 10, ref="same").status_code == 201
    r = transfer(client, a, b, 10, ref="same")
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_TRANSFER"
    assert balance(client, a) == 90 and balance(client, b) == 10


def test_opposite_direction_transfers_conserve_money(client, make_account, tx):
    a, b = make_account("A"), make_account("B")
    tx(a, "credit", 100)
    tx(b, "credit", 100)
    assert transfer(client, a, b, 40, ref="x1").status_code == 201
    assert transfer(client, b, a, 10, ref="x2").status_code == 201
    assert balance(client, a) + balance(client, b) == 200


# ------------------------- balance endpoint & filtering ----------------------
def test_balance_endpoint(client, make_account, tx):
    a = make_account()
    tx(a, "credit", 100)
    tx(a, "debit", 30)
    r = client.get(f"/accounts/{a}/balance")
    assert r.status_code == 200
    assert r.json() == {"account_id": a, "balance": 70}


def test_balance_endpoint_errors(client):
    assert client.get("/accounts/999/balance").status_code == 404
    assert client.get("/accounts/abc/balance").status_code == 400


def test_filter_by_type(client, make_account, tx):
    a = make_account()
    for i in range(3):
        tx(a, "credit", 100, ref=f"c{i}")
    for i in range(2):
        tx(a, "debit", 10, ref=f"d{i}")
    both = client.get(f"/accounts/{a}/transactions").json()
    assert both["pagination"]["total_records"] == 5
    credits = client.get(f"/accounts/{a}/transactions?type=credit").json()
    assert credits["pagination"]["total_records"] == 3
    assert {t["type"] for t in credits["data"]} == {"credit"}
    debits = client.get(f"/accounts/{a}/transactions?type=debit&limit=1&page=2").json()
    assert debits["pagination"] == {"current_page": 2, "page_size": 1, "total_records": 2, "total_pages": 2}
    assert [t["reference_id"] for t in debits["data"]] == ["d0"]  # latest first: d1 on page 1


def test_filter_by_invalid_type(client, make_account):
    a = make_account()
    r = client.get(f"/accounts/{a}/transactions?type=refund")
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_TRANSACTION_TYPE"


def test_duplicate_response_points_to_existing_transaction(client, make_account, tx):
    a = make_account()
    first = tx(a, "credit", 100, ref="dup").json()
    r = tx(a, "credit", 999, ref="dup")
    assert r.status_code == 409
    assert r.json()["error"]["details"] == [{"existing_transaction_id": first["id"]}]
    assert balance(client, a) == 100
