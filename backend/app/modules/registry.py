"""Catalog of modules shown by the API and the web shell."""

from app.schemas.common import ModuleInfo, ModuleStatus

MODULES: list[ModuleInfo] = [
    ModuleInfo(
        id="intake",
        pillar="shared",
        role="Extract text, run OCR on scans, detect language.",
    ),
    ModuleInfo(
        id="router",
        pillar="shared",
        role="Choose cited answers, fraud review, or aid matching, then the legal domain.",
        status=ModuleStatus.ok,
    ),
    ModuleInfo(
        id="rag.ingestion",
        pillar="cited_answers",
        role="Read PDFs, keep publisher, hash, edition, article, page, and highlight boxes.",
    ),
    ModuleInfo(
        id="rag.retrieval",
        pillar="cited_answers",
        role="Hybrid keyword and multilingual search, domain and version filters, rerank.",
    ),
    ModuleInfo(
        id="rag.generation",
        pillar="cited_answers",
        role="Draft from retrieved passages with the local Ollama model.",
    ),
    ModuleInfo(
        id="domains.legal",
        pillar="cited_answers",
        role="Company creation, commercial companies, contracts.",
    ),
    ModuleInfo(
        id="domains.tax",
        pillar="cited_answers",
        role="Tax codes, finance laws, DGI obligations.",
    ),
    ModuleInfo(
        id="domains.banking",
        pillar="cited_answers",
        role="Banking law, BCT circulars, foreign exchange.",
    ),
    ModuleInfo(
        id="domains.labour",
        pillar="cited_answers",
        role="Labour code and employment obligations.",
    ),
    ModuleInfo(
        id="domains.intellectual_property",
        pillar="cited_answers",
        role="Marks, patents, and copyright.",
    ),
    ModuleInfo(
        id="fraud",
        pillar="fraud_signals",
        role="Flag review signals on uploaded invoices, statements, and applications.",
    ),
    ModuleInfo(
        id="aid",
        pillar="aid_and_financing",
        role="Point a founder profile at local BFPME, business-plan, and incentive files.",
        status=ModuleStatus.ok,
    ),
    ModuleInfo(
        id="verifier",
        pillar="shared",
        role="Check document ids, pages, articles, version, and claim support.",
    ),
    ModuleInfo(
        id="composer",
        pillar="shared",
        role="Merge supported findings or abstain and point to a professional.",
        status=ModuleStatus.ok,
    ),
]
