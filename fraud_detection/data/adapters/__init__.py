"""Dataset adapters. Each source keeps its own label meaning."""

from fraud_detection.data.adapters.banksim_adapter import adapt_banksim
from fraud_detection.data.adapters.common import stack_datasets, training_pairs
from fraud_detection.data.adapters.elliptic_adapter import adapt_elliptic_transaction
from fraud_detection.data.adapters.fraud_handbook_adapter import adapt_handbook
from fraud_detection.data.adapters.ibm_aml_adapter import adapt_ibm_aml
from fraud_detection.data.adapters.paysim_adapter import adapt_paysim
from fraud_detection.data.adapters.saml_d_adapter import adapt_saml_d
from fraud_detection.data.adapters.ulb_adapter import adapt_ulb_creditcard
from fraud_detection.schema import LabelType, Transaction

__all__ = [
    "adapt_banksim",
    "adapt_elliptic_transaction",
    "adapt_handbook",
    "adapt_ibm_aml",
    "adapt_ieee_cis",
    "adapt_paysim",
    "adapt_procurement",
    "adapt_saml_d",
    "adapt_ulb_creditcard",
    "stack_datasets",
    "training_pairs",
]


def adapt_ieee_cis(row: dict) -> Transaction:
    """IEEE-CIS transaction row.

    The competition file was not downloaded. This adapter remains for a local
    non-commercial extract and is not used by the training command.
    """
    from fraud_detection.data.adapters.common import flag, text

    fraud_value = row.get("isFraud")
    label = None
    if fraud_value is not None and str(fraud_value).lower() != "nan":
        label = LabelType.CARD_FRAUD if flag(fraud_value) else None
    seconds = float(row.get("TransactionDT") or 0)
    return Transaction(
        transaction_id=f"ieee-{row.get('TransactionID', seconds)}",
        timestamp=__import__("datetime").datetime(2017, 12, 1) + __import__("datetime").timedelta(seconds=seconds),
        amount=float(row["TransactionAmt"]),
        currency="USD",
        transaction_type="card",
        channel="card",
        sender_id=str(row.get("card1") or row.get("TransactionID")),
        receiver_id=str(row.get("ProductCD") or "ieee-merchant"),
        device_id=text(row.get("DeviceInfo")),
        dataset="ieee_cis",
        label_type=label,
        metadata={"non_commercial_only": True},
    )


def adapt_procurement(row: dict) -> Transaction:
    from datetime import datetime

    from fraud_detection.data.adapters.common import as_float, flag, parse_timestamp

    del datetime
    risk = flag(row.get("is_risk", 0))
    estimated = as_float(row.get("estimated_value"))
    awarded = float(row["award_value"])
    ratio = as_float(row.get("award_to_estimate_ratio"))
    if ratio is None and estimated not in (None, 0):
        ratio = awarded / estimated
    return Transaction(
        transaction_id=str(row["notice_id"]),
        timestamp=parse_timestamp(row["award_date"]),
        amount=awarded,
        currency=str(row.get("currency") or "EUR"),
        transaction_type="procurement",
        sender_id=str(row["buyer_id"]),
        receiver_id=str(row["winner_id"]),
        bid_count=None if row.get("bid_count") in (None, "") else int(float(row["bid_count"])),
        award_to_estimate_ratio=ratio,
        submission_window_days=None
        if row.get("submission_window_days") in (None, "")
        else int(float(row["submission_window_days"])),
        dataset=str(row.get("dataset") or "procurement"),
        label_type=LabelType.PROCUREMENT_RISK if risk else None,
    )
