"""Request and response models (validation lives here)."""
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


def _clean(value: str, field: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field} must not be blank")
    return value


# ----------------------------- requests ------------------------------------
class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")  # unknown fields -> 422


Money = Decimal  # validated with Field(gt=0, decimal_places=2) below


class AccountCreate(_Request):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return _clean(v, "name")


class TransactionCreate(_Request):
    account_id: int = Field(gt=0)
    type: Literal["credit", "debit"]
    amount: Money = Field(gt=0, max_digits=15, decimal_places=2)
    description: str | None = Field(default=None, max_length=255)
    reference_id: str = Field(min_length=1, max_length=100)

    @field_validator("type", mode="before")
    @classmethod
    def _type(cls, v):
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("reference_id")
    @classmethod
    def _ref(cls, v: str) -> str:
        return _clean(v, "reference_id")


class TransferCreate(_Request):
    from_account_id: int = Field(gt=0)
    to_account_id: int = Field(gt=0)
    amount: Money = Field(gt=0, max_digits=15, decimal_places=2)
    description: str | None = Field(default=None, max_length=255)
    # shorter than transactions.reference_id: ":debit" / ":credit" is appended
    reference_id: str = Field(min_length=1, max_length=90)

    @field_validator("reference_id")
    @classmethod
    def _ref(cls, v: str) -> str:
        return _clean(v, "reference_id")


# ----------------------------- responses -----------------------------------
class _Response(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("created_at", check_fields=False)
    def _ts(self, v: datetime) -> str:
        return v.isoformat() + "Z"  # stored as naive UTC


def _from_minor(v):
    return round(v / 100, 2) if isinstance(v, int) else v


class AccountOut(_Response):
    id: int
    name: str
    balance: float
    created_at: datetime

    _balance = field_validator("balance", mode="before")(_from_minor)


class BalanceOut(BaseModel):
    account_id: int
    balance: float

    _balance = field_validator("balance", mode="before")(_from_minor)


class TransactionOut(_Response):
    id: int
    account_id: int
    type: str
    amount: float
    description: str | None
    reference_id: str
    transfer_id: int | None
    created_at: datetime

    _amount = field_validator("amount", mode="before")(_from_minor)


class PaginationOut(BaseModel):
    current_page: int
    page_size: int
    total_records: int
    total_pages: int


class TransactionPage(BaseModel):
    data: list[TransactionOut]
    pagination: PaginationOut


class TransferOut(_Response):
    id: int
    reference_id: str
    from_account_id: int
    to_account_id: int
    amount: float
    created_at: datetime
    debit_transaction: TransactionOut
    credit_transaction: TransactionOut

    _amount = field_validator("amount", mode="before")(_from_minor)
