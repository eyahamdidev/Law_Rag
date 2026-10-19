from __future__ import annotations

from datetime import datetime, timedelta

from fraud_detection.normalize import civil_date
from fraud_detection.schema import EntityRecord, Transaction


class Ledger:
    """Current transaction plus earlier activity. Later rows are ignored."""

    def __init__(self, current: Transaction, history: list[Transaction]):
        self.current = current
        prior: list[Transaction] = []
        for item in history:
            if item.transaction_id == current.transaction_id:
                continue
            if item.timestamp <= current.timestamp:
                prior.append(item)
        prior.sort(key=lambda item: (item.timestamp, item.transaction_id))
        self.prior = prior

    @property
    def all_rows(self) -> list[Transaction]:
        return self.prior + [self.current]

    def outgoing(self, entity_id: str, rows: list[Transaction] | None = None) -> list[Transaction]:
        source = self.prior if rows is None else rows
        return [item for item in source if item.sender_id == entity_id]

    def incoming(self, entity_id: str, rows: list[Transaction] | None = None) -> list[Transaction]:
        source = self.prior if rows is None else rows
        return [item for item in source if item.receiver_id == entity_id]


def since(timestamp: datetime, **delta) -> datetime:
    return timestamp - timedelta(**delta)


def apply_entity_defaults(transaction: Transaction, entities: dict[str, EntityRecord]) -> Transaction:
    """Registry facts override caller-supplied age, status, revenue, and country."""
    data = transaction.model_dump()
    sender = entities.get(transaction.sender_id)
    receiver = entities.get(transaction.receiver_id)
    if sender is not None:
        data["sender_name"] = sender.name
        data["sender_kind"] = sender.kind
        if sender.country:
            data["country_from"] = sender.country
        data["company_status"] = sender.status
        data["declared_annual_revenue"] = sender.declared_annual_revenue
        if sender.registered_on is not None:
            age = (civil_date(transaction.timestamp) - civil_date(sender.registered_on)).days
            data["company_age_days"] = max(0, age)
    if receiver is not None:
        data["receiver_name"] = receiver.name
        data["receiver_kind"] = receiver.kind
        if receiver.country:
            data["country_to"] = receiver.country
    return Transaction(**data)
