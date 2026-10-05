"""Marks, patents, and copyright."""

from app.modules.domains.base import DomainWorker


class IntellectualPropertyWorker(DomainWorker):
    domain = "intellectual_property"
    description = "Intellectual property."
