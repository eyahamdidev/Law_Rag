from __future__ import annotations

from datetime import datetime, timedelta

from fraud_detection.data.adapters.common import Row, as_float, flag, public_metadata
from fraud_detection.schema import LabelType, Transaction

# PaySim has no calendar date and no currency. Step 1 is one hour after this
# origin, so the hour-of-day feature is the simulator hour. USD is an explicit
# assumption. Country is left empty.
PAYSIM_ORIGIN = datetime(2020, 1, 1)


def adapt_paysim(row: Row) -> Transaction:
    """PaySim mobile-money row.

    Fraud in PaySim is an account drain through TRANSFER and CASH_OUT, so the
    label stays ACCOUNT_TAKEOVER rather than card fraud or laundering.
    """
    step = int(float(row["step"]))
    fraud = flag(row.get("isFraud", 0))
    return Transaction(
        transaction_id=f"paysim-{row['nameOrig']}-{row['nameDest']}-{step}",
        timestamp=PAYSIM_ORIGIN + timedelta(hours=step),
        amount=float(row["amount"]),
        currency="USD",
        transaction_type=str(row.get("type", "transfer")).lower(),
        sender_id=str(row["nameOrig"]),
        receiver_id=str(row["nameDest"]),
        old_balance=as_float(row.get("oldbalanceOrg")),
        new_balance=as_float(row.get("newbalanceOrig")),
        dataset="paysim",
        label_type=LabelType.ACCOUNT_TAKEOVER if fraud else None,
        metadata=public_metadata("synthetic_simulated", currency_assumption="USD"),
    )
