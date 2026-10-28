from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import services
from app.database import get_db
from app.schemas import TransferCreate, TransferOut

router = APIRouter(prefix="/transfers", tags=["Transfers"])


@router.post("", response_model=TransferOut, status_code=201)
def create_transfer(data: TransferCreate, db: Session = Depends(get_db)):
    """Move money between two accounts. All-or-nothing."""
    transfer, debit, credit = services.create_transfer(db, data)
    return {
        "id": transfer.id,
        "reference_id": transfer.reference_id,
        "from_account_id": transfer.from_account_id,
        "to_account_id": transfer.to_account_id,
        "amount": transfer.amount,
        "created_at": transfer.created_at,
        "debit_transaction": debit,
        "credit_transaction": credit,
    }
