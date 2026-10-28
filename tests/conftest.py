import os
import tempfile

# Must be set BEFORE the app is imported so the engine uses a throwaway DB file.
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine, init_db
from app.main import app


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield


@pytest.fixture()
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def make_account(client):
    def _make(name="Alice"):
        r = client.post("/accounts", json={"name": name})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    return _make


@pytest.fixture()
def tx(client):
    counter = {"n": 0}

    def _tx(account_id, type_, amount, ref=None):
        counter["n"] += 1
        return client.post(
            "/transactions",
            json={
                "account_id": account_id,
                "type": type_,
                "amount": amount,
                "description": "test",
                "reference_id": ref or f"ref-{counter['n']}",
            },
        )

    return _tx
