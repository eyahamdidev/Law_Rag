from __future__ import annotations

from fraud_detection.schema import EntityRecord


class EntityRegistry:
    def __init__(self, entities: list[EntityRecord]):
        self._by_id = {entity.entity_id: entity for entity in entities}
        self.loaded = bool(self._by_id)

    @property
    def by_id(self) -> dict[str, EntityRecord]:
        return self._by_id

    def get(self, entity_id: str) -> EntityRecord | None:
        return self._by_id.get(entity_id)

    def overlay(self, extra: list[EntityRecord]) -> EntityRegistry:
        merged = dict(self._by_id)
        for entity in extra:
            merged[entity.entity_id] = entity
        registry = EntityRegistry(list(merged.values()))
        registry.loaded = self.loaded or bool(extra)
        return registry
