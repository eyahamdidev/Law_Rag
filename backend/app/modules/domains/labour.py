"""Labour and employment obligations."""

from app.modules.domains.base import DomainWorker


class LabourWorker(DomainWorker):
    domain = "labour"
    description = "Labour code and employment obligations."
