"""Tax codes, finance laws, and filing obligations."""

from app.modules.domains.base import DomainWorker


class TaxWorker(DomainWorker):
    domain = "tax"
    description = "Tax codes, finance laws, and DGI obligations."
