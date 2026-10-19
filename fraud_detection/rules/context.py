from __future__ import annotations

from fraud_detection.ledger import Ledger
from fraud_detection.schema import EntityRecord, Transaction


class RuleContext:
    def __init__(self, ledger: Ledger, entities: dict[str, EntityRecord], registry_loaded: bool):
        self.ledger = ledger
        self.entities = entities
        self.registry_loaded = registry_loaded

    @property
    def tx(self) -> Transaction:
        return self.ledger.current

    def entity(self, entity_id: str) -> EntityRecord | None:
        return self.entities.get(entity_id)
