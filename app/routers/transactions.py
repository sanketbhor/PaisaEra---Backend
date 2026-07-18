from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.finance import Transaction
from app.services.fie.categorizer import categorize
from app.schemas.api import TransactionCreate, TransactionResponse, VoiceEntryBody

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=list[TransactionResponse])
def list_transactions(user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    return (
        db.query(Transaction)
        .filter(Transaction.user_id == user.id)
        .order_by(Transaction.transaction_ts.desc())
        .limit(100)
        .all()
    )


@router.post("", response_model=TransactionResponse)
def create_transaction(
    body: TransactionCreate,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    # Auto-categorize via the FIE's Categorizer stage if the client didn't
    # supply a category — keeps categorization logic in one place (see
    # app/services/fie/categorizer.py) instead of duplicated inline here.
    category = body.category or categorize(body.merchant_name)

    txn = Transaction(
        user_id=user.id,
        merchant_name=body.merchant_name,
        amount=body.amount,
        category=category,
        direction=body.direction,
        source=body.source,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


@router.post("/voice-entry", response_model=TransactionResponse)
def parse_voice_entry(
    body: VoiceEntryBody,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """
    Very simple amount/merchant extraction from a voice transcript.
    Good enough for a demo — replace with a proper NLU parse (or route
    through the AI Gateway for extraction) before relying on this in
    production, since real speech transcripts are messier than this
    regex handles.
    """
    import re

    amount_match = re.search(r"(\d+)", body.transcript)
    amount = Decimal(amount_match.group(1)) if amount_match else None
    if not amount:
        raise HTTPException(status_code=422, detail="Amount samajh nahi aaya, dobara try karo")

    merchant = body.transcript.strip()[:100]
    txn = Transaction(
        user_id=user.id,
        merchant_name=merchant,
        amount=amount,
        category=categorize(merchant),
        source="voice_parsed",
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


class SMSTransactionItem(BaseModel):
    merchant_name: str | None = None
    amount: Decimal = Field(..., gt=0)
    direction: str = Field("debit", pattern="^(debit|credit)$")
    transaction_ts: datetime
    category: str | None = None


class SMSImportBody(BaseModel):
    transactions: list[SMSTransactionItem] = Field(..., max_length=500)


@router.post("/sms-import")
def import_sms_transactions(
    body: SMSImportBody,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Bulk import of transactions the mobile app parsed from bank SMS
    on-device (raw SMS text never reaches the server — only these
    structured fields). Idempotent: an item matching an existing
    transaction's amount+direction within ±2 min of its timestamp is
    treated as already-imported and skipped, so re-syncing the same inbox
    window is safe."""
    imported = 0
    skipped = 0
    for item in body.transactions:
        window_start = item.transaction_ts - timedelta(minutes=2)
        window_end = item.transaction_ts + timedelta(minutes=2)
        exists = (
            db.query(Transaction)
            .filter(
                Transaction.user_id == user.id,
                Transaction.amount == item.amount,
                Transaction.direction == item.direction,
                Transaction.transaction_ts >= window_start,
                Transaction.transaction_ts <= window_end,
            )
            .first()
        )
        if exists:
            skipped += 1
            continue
        db.add(Transaction(
            user_id=user.id,
            merchant_name=item.merchant_name,
            amount=item.amount,
            category=item.category or categorize(item.merchant_name),
            direction=item.direction,
            source="sms_parsed",
            transaction_ts=item.transaction_ts,
        ))
        imported += 1
    db.commit()
    return {"imported": imported, "skipped_duplicates": skipped}
