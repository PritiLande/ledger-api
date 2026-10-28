"""Business logic. Every public function is ONE database transaction:
it either commits completely or rolls back completely."""
import math
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import (
    AccountNotFound,
    DuplicateTransaction,
    DuplicateTransfer,
    InsufficientBalance,
    InvalidTransfer,
    TransactionNotFound,
)
from app.models import Account, Transaction, Transfer
from app.schemas import AccountCreate, TransactionCreate, TransferCreate


def to_minor(amount: Decimal) -> int:
    """Decimal rupees/dollars -> integer paise/cents."""
    return int((amount * 100).to_integral_exact())


def _is_unique_violation(exc: IntegrityError) -> bool:
    return "unique" in str(exc.orig).lower()


def _require_account(db: Session, account_id: int) -> None:
    exists = db.execute(select(Account.id).where(Account.id == account_id)).first()
    if exists is None:
        raise AccountNotFound(f"Account {account_id} not found.")


# --------------------------- low-level building blocks ----------------------
def _insert_entry(db: Session, **fields) -> Transaction:
    tx = Transaction(**fields)
    db.add(tx)
    try:
        db.flush()
    except IntegrityError as exc:
        if _is_unique_violation(exc):
            raise DuplicateTransaction(
                f"A transaction with reference_id '{fields['reference_id']}' "
                f"already exists for account {fields['account_id']}."
            ) from exc
        raise
    return tx


def _adjust_balance(db: Session, account_id: int, tx_type: str, amount: int) -> None:
    """Atomic balance change. A debit only succeeds if funds are sufficient;
    the check and the update happen in a single SQL statement, so two
    concurrent debits can never both spend the same money."""
    if tx_type == "credit":
        stmt = update(Account).where(Account.id == account_id).values(balance=Account.balance + amount)
    else:
        stmt = (
            update(Account)
            .where(Account.id == account_id, Account.balance >= amount)
            .values(balance=Account.balance - amount)
        )
    result = db.execute(stmt)
    if result.rowcount != 1:
        raise InsufficientBalance(f"Account {account_id} has insufficient balance for this debit.")


def _post_entry(db: Session, *, account_id, tx_type, amount, reference_id, description, transfer_id=None):
    tx = _insert_entry(
        db,
        account_id=account_id,
        type=tx_type,
        amount=amount,
        description=description,
        reference_id=reference_id,
        transfer_id=transfer_id,
    )
    _adjust_balance(db, account_id, tx_type, amount)
    return tx


# --------------------------------- accounts ---------------------------------
def create_account(db: Session, data: AccountCreate) -> Account:
    account = Account(name=data.name, balance=0)
    db.add(account)
    db.commit()
    return account


def get_account(db: Session, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise AccountNotFound(f"Account {account_id} not found.")
    return account


# ------------------------------- transactions -------------------------------
def create_transaction(db: Session, data: TransactionCreate) -> Transaction:
    try:
        _require_account(db, data.account_id)
        tx = _post_entry(
            db,
            account_id=data.account_id,
            tx_type=data.type,
            amount=to_minor(data.amount),
            reference_id=data.reference_id,
            description=data.description,
        )
        db.commit()
        return tx
    except DuplicateTransaction as exc:
        db.rollback()
        existing_id = db.scalar(
            select(Transaction.id).where(
                Transaction.account_id == data.account_id,
                Transaction.reference_id == data.reference_id,
            )
        )
        exc.details = [{"existing_transaction_id": existing_id}]
        raise
    except BaseException:
        db.rollback()  # neither the transaction row nor the balance change persists
        raise


def get_transaction(db: Session, transaction_id: int) -> Transaction:
    tx = db.get(Transaction, transaction_id)
    if tx is None:
        raise TransactionNotFound(f"Transaction {transaction_id} not found.")
    return tx


def list_transactions(db: Session, account_id: int, page: int, limit: int, tx_type: str | None = None):
    _require_account(db, account_id)
    conditions = [Transaction.account_id == account_id]
    if tx_type is not None:
        conditions.append(Transaction.type == tx_type)
    total = db.scalar(select(func.count(Transaction.id)).where(*conditions)) or 0
    rows = db.scalars(
        select(Transaction)
        .where(*conditions)
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())  # latest first
        .offset((page - 1) * limit)
        .limit(limit)
    ).all()
    pagination = {
        "current_page": page,
        "page_size": limit,
        "total_records": total,
        "total_pages": math.ceil(total / limit) if total else 0,
    }
    return rows, pagination


# --------------------------------- transfers --------------------------------
def create_transfer(db: Session, data: TransferCreate):
    try:
        if data.from_account_id == data.to_account_id:
            raise InvalidTransfer("Source and destination accounts must be different.")
        _require_account(db, data.from_account_id)
        _require_account(db, data.to_account_id)

        amount = to_minor(data.amount)
        transfer = Transfer(
            reference_id=data.reference_id,
            from_account_id=data.from_account_id,
            to_account_id=data.to_account_id,
            amount=amount,
        )
        db.add(transfer)
        try:
            db.flush()
        except IntegrityError as exc:
            if _is_unique_violation(exc):
                raise DuplicateTransfer(f"A transfer with reference_id '{data.reference_id}' already exists.") from exc
            raise

        legs = [
            (data.from_account_id, "debit", f"{data.reference_id}:debit"),
            (data.to_account_id, "credit", f"{data.reference_id}:credit"),
        ]
        # Always touch accounts in ascending id order -> no deadlocks between
        # opposite-direction transfers on databases with row-level locks.
        legs.sort(key=lambda leg: leg[0])
        posted = {}
        for account_id, tx_type, ref in legs:
            posted[tx_type] = _post_entry(
                db,
                account_id=account_id,
                tx_type=tx_type,
                amount=amount,
                reference_id=ref,
                description=data.description,
                transfer_id=transfer.id,
            )
        db.commit()
        return transfer, posted["debit"], posted["credit"]
    except BaseException:
        db.rollback()  # a partial transfer is impossible
        raise
