from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db
from app.errors import register_error_handlers
from app.routers import accounts, transactions, transfers


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Ledger API",
    description="Accounts, immutable transactions and atomic money transfers.",
    version="1.0.0",
    lifespan=lifespan,
)
register_error_handlers(app)

app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(transfers.router)


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok"}
