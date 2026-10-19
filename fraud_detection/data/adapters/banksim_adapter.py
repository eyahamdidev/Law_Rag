from __future__ import annotations

from datetime import datetime, timedelta

from fraud_detection.data.adapters.common import Row, flag, public_metadata, text, unquote
from fraud_detection.schema import LabelType, Transaction

# bs140513 is the public file date 2014-05-13. `step` is a day index. The file
# has no clock time, so every row is placed at 12:00 and the night rule does
# not fire from a missing hour. Currency is not in the file; EUR is an
# assumption. Country is left empty. BankSim is a synthetic bank-payment
# simulator, not a real card ledger. The card channel keeps this head off
# mobile-money rows. The age column is a demographic bin, not account age.
BANKSIM_ORIGIN = datetime(2014, 5, 13, 12, 0, 0)


def adapt_banksim(row: Row) -> Transaction:
    step_key = "step" if "step" in row else "Step"
    customer = unquote(row.get("customer") or row.get("Customer"))
    merchant = unquote(row.get("merchant") or row.get("Merchant"))
    step = int(float(unquote(row[step_key])))
    fraud = flag(row.get("fraud", row.get("Fraud", 0)))
    return Transaction(
        transaction_id=f"banksim-{customer}-{merchant}-{step}",
        timestamp=BANKSIM_ORIGIN + timedelta(days=step),
        amount=float(unquote(row.get("amount") or row["Amount"])),
        currency="EUR",
        transaction_type="card",
        channel="card",
        sender_id=customer,
        receiver_id=merchant,
        merchant_category=text(row.get("category") or row.get("Category")),
        dataset="banksim",
        label_type=LabelType.CARD_FRAUD if fraud else None,
        metadata=public_metadata("synthetic_simulated", currency_assumption="EUR"),
    )
