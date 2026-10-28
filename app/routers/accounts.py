from typing import Literal

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app import services
from app.database import get_db
from app.schemas import AccountCreate, AccountOut, BalanceOut, TransactionPage

router = APIRouter(prefix="/accounts", tags=["Accounts"])


@router.post("", response_model=AccountOut, status_code=201)
def create_account(data: AccountCreate, db: Session = Depends(get_db)):
    """Create an account with an initial balance of 0."""
    return services.create_account(db, data)


@router.get("/{account_id}", response_model=AccountOut)
def get_account(account_id: int = Path(ge=1), db: Session = Depends(get_db)):
    return services.get_account(db, account_id)


@router.get("/{account_id}/balance", response_model=BalanceOut)
def get_balance(account_id: int = Path(ge=1), db: Session = Depends(get_db)):
    """Current balance of an account."""
    account = services.get_account(db, account_id)
    return {"account_id": account.id, "balance": account.balance}


@router.get("/{account_id}/transactions", response_model=TransactionPage)
def list_transactions(
    account_id: int = Path(ge=1),
    page: int = Query(1, ge=1, le=1_000_000, description="1-based page number"),
    limit: int = Query(10, ge=1, le=100, description="Page size (max 100)"),
    type: Literal["credit", "debit"] | None = Query(None, description="Filter by type; omit for both"),
    db: Session = Depends(get_db),
):
    """Transactions of an account, latest first (by created_at), optionally filtered by type."""
    rows, pagination = services.list_transactions(db, account_id, page, limit, type)
    return {"data": rows, "pagination": pagination}
