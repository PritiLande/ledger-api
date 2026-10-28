"""ORM models. Integrity rules live in the database as constraints, not just in Python.

Money is stored as an integer number of minor units (paise/cents) to avoid
floating point errors.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    DDL,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    """Naive UTC timestamp (all timestamps in this app are UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("balance >= 0", name="ck_accounts_balance_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    balance: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class Transfer(Base):
    __tablename__ = "transfers"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transfers_amount_positive"),
        CheckConstraint("from_account_id <> to_account_id", name="ck_transfers_distinct_accounts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    from_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    to_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("type IN ('credit', 'debit')", name="ck_transactions_type"),
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        UniqueConstraint("account_id", "reference_id", name="uq_transactions_account_reference"),
        Index("ix_transactions_account_created", "account_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(6), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reference_id: Mapped[str] = mapped_column(String(100), nullable=False)
    transfer_id: Mapped[int | None] = mapped_column(ForeignKey("transfers.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


# --- Immutability enforced at the database level (SQLite triggers) ---------
# Even direct SQL cannot modify or delete a ledger entry.
for _table in ("transactions", "transfers"):
    for _op in ("UPDATE", "DELETE"):
        event.listen(
            Base.metadata,
            "after_create",
            DDL(
                f"CREATE TRIGGER IF NOT EXISTS {_table}_no_{_op.lower()} "
                f"BEFORE {_op} ON {_table} "
                f"BEGIN SELECT RAISE(ABORT, '{_table} are immutable'); END"
            ).execute_if(dialect="sqlite"),
        )
