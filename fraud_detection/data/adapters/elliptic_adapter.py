from __future__ import annotations

from datetime import datetime, timedelta

from fraud_detection.data.adapters.common import Row, public_metadata
from fraud_detection.schema import LabelType, Transaction


def adapt_elliptic_transaction(row: Row) -> Transaction:
    """Elliptic transaction node.

    Class 1 is illicit, class 2 is licit, and unknown rows are not legitimate
    negatives. They are marked unlabeled so training skips them.
    """
    raw = str(row.get("class", row.get("Class", ""))).strip().lower()
    label = None
    unlabeled = False
    if raw in {"1", "1.0", "illicit"}:
        label = LabelType.AML_LAUNDERING
    elif raw in {"2", "2.0", "licit"}:
        label = None
    else:
        unlabeled = True
    timestep = int(float(row.get("time step") or row.get("Time step") or row.get("timestep") or 1))
    tx_id = str(row.get("txId") or row.get("tx_id") or row["transaction_id"])
    return Transaction(
        transaction_id=f"elliptic-{tx_id}",
        timestamp=datetime(2016, 1, 1) + timedelta(days=timestep),
        amount=float(row.get("amount") or 0),
        currency="BTC",
        transaction_type="crypto",
        sender_id=tx_id,
        receiver_id=str(row.get("counterparty") or "elliptic-graph"),
        dataset="elliptic",
        label_type=label,
        metadata=public_metadata("real_cryptocurrency_graph", unlabeled=unlabeled, timestep=timestep),
    )
