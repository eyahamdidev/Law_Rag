"""Planned review signals.

Each signal is a reason a person should look again. None of them, alone or
together, is a finding that someone committed fraud.

- missing_fiscal_id: matricule fiscal or TVA mention absent on an invoice.
- date_inconsistency: issue date, due date, or period disagree.
- duplicate_document: same file hash already seen in fraud_detection/.
- amount_mismatch: total does not match the sum of lines.
- round_amount: unusually round figures worth a second look.
"""

PLANNED_SIGNALS = (
    "missing_fiscal_id",
    "date_inconsistency",
    "duplicate_document",
    "amount_mismatch",
    "round_amount",
)
