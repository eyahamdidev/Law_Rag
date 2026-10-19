"""Score the labeled stamp pages with the live enrollment path.

Ground truth is the filename suffix ``_reference`` or ``_counterfeit``.
Each family is enrolled from its genuine PDF, then every page of that family
is checked with ``SpecimenStore.check``. Nothing is written to the user's
specimen directory.

The eight-document demonstration is chosen after this pass by a fixed rule:
the first reference pages, in filename order, that this checker calls
genuine, and the first counterfeit pages it calls fraudulent. That set is a
demonstration. Four stamp identities that share one scan process are not an
independent test, and the files were all drawn from the same four source
documents the features were inspected on. ``POST /v1/score`` keeps uploaded
scans up to 1600 px, which is this page size, so the API sees the same pixels.
"""

from __future__ import annotations

import base64
import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

from fraud_detection.documents.intake import load_pages
from fraud_detection.documents.specimens import SpecimenStore
from fraud_detection.evaluation.stamp_stress import PDF_BY_DOC
from fraud_detection.paths import EVAL, GENUINE, STAMP_DATASET

OUT = EVAL / "stamp_classification_results.json"


def _pdf_page(doc: str) -> np.ndarray:
    raw = (GENUINE / PDF_BY_DOC[doc]).read_bytes()
    _source, pages, _excerpt = load_pages(None, base64.b64encode(raw).decode("ascii"))
    return pages[0]


def _label(name: str) -> str:
    if name.endswith("_reference.jpg"):
        return "reference"
    if "counterfeit" in name:
        return "counterfeit"
    return "unlabeled"


def score_family(doc: str, root: Path) -> list[dict]:
    store = SpecimenStore(root / doc)
    enrolled = store.enroll(doc, "stamp", _pdf_page(doc), comment=doc)
    if not enrolled.get("enrolled"):
        raise RuntimeError(f"could not enroll {doc}: {enrolled}")
    rows = []
    for path in sorted((STAMP_DATASET / doc / "pages").glob("*.jpg")):
        page = np.asarray(Image.open(path).convert("RGB"))
        result = store.check(doc, page, expect_signature=False)
        stamp = result["matches"].get("stamp") or {}
        rows.append(
            {
                "doc": doc,
                "name": path.name,
                "ground_truth": _label(path.name),
                "verdict": stamp.get("verdict"),
                "status": stamp.get("status"),
                "alignment_ncc": stamp.get("alignment_ncc"),
                "genuine_probability": stamp.get("genuine_probability"),
            }
        )
    return rows


def _counts(rows: list[dict], ground: str) -> dict:
    subset = [row for row in rows if row["ground_truth"] == ground]
    verdicts = Counter(row["verdict"] or row["status"] for row in subset)
    return {"n": len(subset), **{key: int(verdicts.get(key, 0)) for key in ("genuine", "fraudulent", "uncertain", "unrecognized", "missing")}}


def demonstration(rows: list[dict]) -> dict:
    """First decisive files in filename order. Not a random or held-out sample."""
    genuine = [row for row in rows if row["ground_truth"] == "reference" and row["verdict"] == "genuine"]
    fraudulent = [row for row in rows if row["ground_truth"] == "counterfeit" and row["verdict"] == "fraudulent"]
    return {
        "procedure": (
            "After the decision rule was frozen, take pages in filename order. "
            "The genuine demonstration is the first four reference pages the live checker calls genuine. "
            "The counterfeit demonstration is the first four counterfeit pages it calls fraudulent. "
            "Families with no fraudulent call are absent from that list. "
            "This is a demonstration of the cases with positive evidence, not an independent evaluation."
        ),
        "genuine": genuine[:4],
        "fraudulent": fraudulent[:4],
    }


def main() -> None:
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="stamp-class-"))
    rows: list[dict] = []
    for doc in PDF_BY_DOC:
        print(doc, flush=True)
        family = score_family(doc, root)
        rows.extend(family)
        print(" ", _counts(family, "reference"), _counts(family, "counterfeit"), flush=True)
    payload = {
        "reference": _counts(rows, "reference"),
        "counterfeit": _counts(rows, "counterfeit"),
        "by_doc": {
            doc: {
                "reference": _counts([row for row in rows if row["doc"] == doc], "reference"),
                "counterfeit": _counts([row for row in rows if row["doc"] == doc], "counterfeit"),
            }
            for doc in PDF_BY_DOC
        },
        "demonstration": demonstration(rows),
        "rows": rows,
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
