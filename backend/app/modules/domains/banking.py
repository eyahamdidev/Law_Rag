"""Banking, central-bank circulars, and foreign exchange."""

from app.modules.domains.base import DomainWorker


class BankingWorker(DomainWorker):
    domain = "banking"
    description = "Banking law, BCT circulars, and foreign exchange."
