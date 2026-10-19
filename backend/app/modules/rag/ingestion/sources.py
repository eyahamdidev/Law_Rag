"""Find the PDFs to index and attach what we know about each one.

Every document gets a stable id, the corpora it belongs to, a domain tag
taken from its folder, its sha256, and the sidecar `.meta.json` fields when
the collection script left one. Byte-identical files are indexed once and
keep every corpus tag, so a law that also sits in the grants folder is
still visible to a grants-only search.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.config import REPO_ROOT, settings

# Folder prefix (relative to the corpus root) -> domain tag.
LAW_DOMAINS = {
    "01_STARTUPS": "startup",
    "02_INVESTMENT": "investment",
    "03_COMPANIES": "company_law",
    "04_BANKING_AND_FINANCE": "banking",
    "05_FOREIGN_EXCHANGE": "foreign_exchange",
    "06_FINANCING": "financing",
    "07_INSOLVENCY": "insolvency",
    "08_INTELLECTUAL_PROPERTY": "intellectual_property",
    "09_CONTRACTS": "contracts",
    "10_WIPO_GUIDES": "ip_guidance",
    "99_SOURCE_DOCUMENTS": "jort",
}
GRANT_DOMAINS = {
    "BFPME": "sme_bank",
    "Credit_lines_solidarity_finance_and_guarantees": "credit_guarantees",
    "International_donors_accelerators_and_calls": "donors_accelerators",
    "Investment_incentives": "investment_incentives",
    "Startup_Act_and_national_startup_funding_programme": "startup_programmes",
    "Business_Plan_Models": "business_plan_models",
}
BUSINESS_PLAN_DOMAINS = {
    "Accounting_rules": "accounting",
    "Business_model_templates_and_frameworks": "business_model",
    "Sector_benchmarks": "sector_benchmarks",
    "Tunisian_business_plan_and_business_model_guides": "business_plan_guides",
    "Tunisian_macro_and_financial_inputs_for_projection": "macro_inputs",
}

# Folders whose PDFs are lists of sources rather than sources.
SKIP_PARTS = {"00_REFERENCES"}
SKIP_NAME = re.compile(r"_DUPLICATE\.pdf$", re.IGNORECASE)

# Law PDFs carry their date in the file name: JORT_2016-10-07_N82_FR_Loi_2016-71.pdf.
# That is the gazette publication date. It is not an effective date.
JORT_NAME = re.compile(r"JORT_(\d{4}-\d{2}-\d{2})_N(\d+)_(FR|AR)")


@dataclass
class SourceDocument:
    doc_id: str
    path: Path
    title: str
    corpora: list[str]
    domain: str
    sha256: str
    language: str | None = None
    publisher_url: str | None = None
    publication_date: str | None = None
    jort_issue: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def rel_path(self) -> str:
        return self.path.relative_to(REPO_ROOT).as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _domain(rel: Path, table: dict[str, str], default: str) -> str:
    return table.get(rel.parts[0], default) if rel.parts else default


def _sidecar(path: Path) -> dict:
    meta = path.with_name(path.name + ".meta.json")
    if not meta.exists():
        return {}
    try:
        return json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _title(path: Path, meta: dict) -> str:
    if meta.get("name"):
        return str(meta["name"])
    # Law PDFs sit in a folder named after the text: Loi_2000-93_Code_Societes_Commerciales.
    if JORT_NAME.search(path.name) and path.parent.name not in {"JORT"}:
        return path.parent.name.replace("_", " ")
    return path.stem.replace("_", " ")


def _doc_id(corpus: str, path: Path) -> str:
    # Sidecar ids (S024) are shared by a landing page and its linked PDFs,
    # so the file stem is part of the id.
    stem = re.sub(r"[^A-Za-z0-9]+", "-", path.stem).strip("-").lower()
    return f"{corpus}:{stem}"[:120]


def _walk(corpus: str, root: Path, table: dict[str, str], default: str):
    if not root.exists():
        return
    for path in sorted(root.rglob("*.pdf")):
        rel = path.relative_to(root)
        if SKIP_PARTS & set(rel.parts) or SKIP_NAME.search(path.name):
            continue
        yield corpus, path, _domain(rel, table, default)


def discover(corpora: tuple[str, ...] = ("law", "grants")) -> list[SourceDocument]:
    roots = {
        "law": (settings.law_corpus_dir, LAW_DOMAINS, "law"),
        "grants": (settings.aid_corpus_dir, GRANT_DOMAINS, "grants"),
        "business_plan": (settings.business_plan_dir, BUSINESS_PLAN_DOMAINS, "business_plan"),
    }
    by_hash: dict[str, SourceDocument] = {}
    for corpus in corpora:
        root, table, default = roots[corpus]
        for corpus_name, path, domain in _walk(corpus, root, table, default):
            sha = _sha256(path)
            if sha in by_hash:
                existing = by_hash[sha]
                if corpus_name not in existing.corpora:
                    existing.corpora.append(corpus_name)
                continue
            meta = _sidecar(path)
            jort = JORT_NAME.search(path.name)
            by_hash[sha] = SourceDocument(
                doc_id=_doc_id(corpus_name, path),
                path=path,
                title=_title(path, meta),
                corpora=[corpus_name],
                domain=domain,
                sha256=sha,
                language=(jort.group(3).lower() if jort else meta.get("lang")),
                publisher_url=meta.get("final_url") or meta.get("url"),
                publication_date=jort.group(1) if jort else meta.get("publication_date"),
                jort_issue=jort.group(2) if jort else None,
                extra={"source_id": meta.get("id"), "section": meta.get("section"),
                       "article_numbering":meta.get("article_numbering"),"act":meta.get("act"),
                       "source_kind": meta.get("source_kind", "unknown"),
                       "current_version_verified": meta.get("current_version_verified", False)},
            )
    return list(by_hash.values())
