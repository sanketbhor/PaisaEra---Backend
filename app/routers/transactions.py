from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.finance import Transaction, MerchantCategoryOverride
from app.services.fie.categorizer import categorize
from app.services.fie.ai_categorizer import ALLOWED_CATEGORIES, categorize_merchants
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


def _resolve_sms_category(item: SMSTransactionItem, overrides: dict[str, tuple[str, str]]) -> str:
    """Priority: user's own corrections > strong SMS-body hints (Credit
    Card/EMI — only the phone saw the body) > merchant-name rules
    (swiggy → Khana) > AI-learned mappings > weak hints (UPI) > default."""
    from app.services.fie.categorizer import DEFAULT_CATEGORY, STRONG_SMS_HINTS

    override = overrides.get(item.merchant_name) if item.merchant_name else None
    if override and override[1] == "user":
        return override[0]
    if item.category in STRONG_SMS_HINTS:
        return item.category
    rule_category = categorize(item.merchant_name)
    if rule_category != DEFAULT_CATEGORY:
        return rule_category
    if override:  # ai-learned
        return override[0]
    return item.category or DEFAULT_CATEGORY


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
    if not body.transactions:
        return {"imported": 0, "skipped_duplicates": 0}

    overrides = {
        merchant: (category, source)
        for merchant, category, source in db.query(
            MerchantCategoryOverride.merchant_name,
            MerchantCategoryOverride.category,
            MerchantCategoryOverride.source,
        ).filter(MerchantCategoryOverride.user_id == user.id)
    }

    # ONE window query for the whole batch instead of one per item — the
    # per-item version was 500 sequential round-trips to Supabase, which
    # blew past the mobile client's request timeout on real inboxes.
    min_ts = min(t.transaction_ts for t in body.transactions) - timedelta(minutes=2)
    max_ts = max(t.transaction_ts for t in body.transactions) + timedelta(minutes=2)
    existing_rows = (
        db.query(Transaction.amount, Transaction.direction, Transaction.transaction_ts)
        .filter(
            Transaction.user_id == user.id,
            Transaction.transaction_ts >= min_ts,
            Transaction.transaction_ts <= max_ts,
        )
        .all()
    )
    seen: dict[tuple, list] = {}
    for amount, direction, ts in existing_rows:
        seen.setdefault((amount, direction), []).append(ts)

    window = timedelta(minutes=2)
    for item in body.transactions:
        candidates = seen.get((item.amount, item.direction), [])
        if any(abs(item.transaction_ts - ts) <= window for ts in candidates):
            skipped += 1
            continue
        db.add(Transaction(
            user_id=user.id,
            merchant_name=item.merchant_name,
            amount=item.amount,
            category=_resolve_sms_category(item, overrides),
            direction=item.direction,
            source="sms_parsed",
            transaction_ts=item.transaction_ts,
        ))
        # Register in the index so an intra-batch duplicate (same SMS
        # delivered twice) is also caught.
        seen.setdefault((item.amount, item.direction), []).append(item.transaction_ts)
        imported += 1
    db.commit()
    return {"imported": imported, "skipped_duplicates": skipped}


class UpdateCategoryBody(BaseModel):
    category: str


@router.patch("/{txn_id}/category")
def update_category(
    txn_id: str,
    body: UpdateCategoryBody,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Tap-to-recategorize: set this transaction's category, remember the
    correction as a user-level merchant override (user corrections beat
    both AI and rule-based categorization forever), and apply it to every
    other transaction of the same merchant in one go."""
    if body.category not in ALLOWED_CATEGORIES:
        raise HTTPException(status_code=422, detail="Aisi category nahi hai")

    txn = db.query(Transaction).filter(Transaction.id == txn_id, Transaction.user_id == user.id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction nahi mila")

    txn.category = body.category
    updated = 1

    if txn.merchant_name:
        override = (
            db.query(MerchantCategoryOverride)
            .filter(
                MerchantCategoryOverride.user_id == user.id,
                MerchantCategoryOverride.merchant_name == txn.merchant_name,
            )
            .first()
        )
        if override:
            override.category = body.category
            override.source = "user"
        else:
            db.add(MerchantCategoryOverride(
                user_id=user.id,
                merchant_name=txn.merchant_name,
                category=body.category,
                source="user",
            ))
        updated += (
            db.query(Transaction)
            .filter(
                Transaction.user_id == user.id,
                Transaction.merchant_name == txn.merchant_name,
                Transaction.id != txn.id,
            )
            .update({Transaction.category: body.category})
        )

    db.commit()
    return {"updated": updated, "category": body.category}


@router.post("/recategorize-ai")
async def recategorize_with_ai(
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Batch-categorize this user's Miscellaneous merchants via the AI
    categorizer, persist the learned mappings (source='ai'), and apply
    them. Each merchant string costs one LLM lookup at most once ever."""
    # Merchants that already have any override are settled -- don't re-ask.
    overridden = {
        m for (m,) in db.query(MerchantCategoryOverride.merchant_name)
        .filter(MerchantCategoryOverride.user_id == user.id)
        .all()
    }
    rows = (
        db.query(Transaction.merchant_name)
        .filter(
            Transaction.user_id == user.id,
            Transaction.category.in_(["Miscellaneous", "Aur Kuch"]) | Transaction.category.is_(None),
            Transaction.merchant_name.isnot(None),
        )
        .distinct()
        .limit(200)
        .all()
    )
    merchants = [m for (m,) in rows if m and m not in overridden and not m.startswith("UPI Transfer")]

    learned: dict[str, str] = {}
    for i in range(0, len(merchants), 50):
        learned.update(await categorize_merchants(merchants[i : i + 50]))

    updated = 0
    for merchant, category in learned.items():
        db.add(MerchantCategoryOverride(
            user_id=user.id, merchant_name=merchant, category=category, source="ai",
        ))
        updated += (
            db.query(Transaction)
            .filter(Transaction.user_id == user.id, Transaction.merchant_name == merchant)
            .update({Transaction.category: category})
        )
    db.commit()
    return {"merchants_asked": len(merchants), "merchants_learned": len(learned), "transactions_updated": updated}
