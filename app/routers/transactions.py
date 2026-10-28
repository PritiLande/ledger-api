from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app import services
from app.database import get_db
from app.schemas import TransactionCreate, TransactionOut

router = APIRouter(prefix="/transactions", tags=["Transactions"])


# NOTE: there are intentionally NO update/delete endpoints: ledger entries are immutable.
@router.post("", response_model=TransactionOut, status_code=201)
def create_transaction(data: TransactionCreate, db: Session = Depends(get_db)):
    """Create a credit/debit and update the account balance atomically."""
    return services.create_transaction(db, data)


@router.get("/{transaction_id}", response_model=TransactionOut)
def get_transaction(transaction_id: int = Path(ge=1), db: Session = Depends(get_db)):
    return services.get_transaction(db, transaction_id)
