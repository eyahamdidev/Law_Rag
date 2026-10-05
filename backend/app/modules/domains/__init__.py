"""Domain workers. One worker per legal or financial topic."""

from app.modules.domains.banking import BankingWorker
from app.modules.domains.intellectual_property import IntellectualPropertyWorker
from app.modules.domains.labour import LabourWorker
from app.modules.domains.legal import LegalWorker
from app.modules.domains.tax import TaxWorker

WORKERS = {
    "legal": LegalWorker(),
    "tax": TaxWorker(),
    "banking": BankingWorker(),
    "labour": LabourWorker(),
    "intellectual_property": IntellectualPropertyWorker(),
}
