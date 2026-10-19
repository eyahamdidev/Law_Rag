"""Three post-enrollment outcomes for one organization, all through PDF upload.

1. Approve attestation_liberation_capital.pdf for organization-a.
2. Upload that same genuine PDF again: genuine / reference_match.
3. Upload capital_0019_counterfeit.pdf: fraudulent / local_ink_anomaly.
4. Upload decision_attribution_subvention.pdf: unrecognized, and ask to enroll it.

capital_0019_counterfeit.pdf embeds capital_0019_counterfeit.jpg unchanged.
The PDF route still rasterizes the page at 1.6x and limits the long side to
1200 px. This script records the verdict that route actually returns.

The balance counterfeit is not used. It is a different stamp.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path

import pymupdf
from fastapi.testclient import TestClient

from fraud_detection.api.app import create_app
from fraud_detection.inference.pipeline import FraudDetectionEngine

FOLDER = Path(__file__).resolve().parent
CAPITAL_PDF = FOLDER / "attestation_liberation_capital.pdf"
CAPITAL_COUNTERFEIT_JPG = FOLDER / "capital_0019_counterfeit.jpg"
CAPITAL_COUNTERFEIT_PDF = FOLDER / "capital_0019_counterfeit.pdf"
UNRELATED_PDF = FOLDER / "decision_attribution_subvention.pdf"
GENUINE_SCAN = FOLDER / "capital_0000_reference.jpg"
SUBTLE_COUNTERFEIT = FOLDER / "capital_0008_counterfeit.jpg"
MISSING_STAMP = FOLDER / "oval_02_har_000.jpg"
OUTCOMES = FOLDER / "observed_outcomes.json"
ORGANIZATION = "organization-a"


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _payment() -> dict:
    return {
        "transaction_id": "demo-organization-a",
        "timestamp": "2024-11-18T11:00:00",
        "amount": 125.0,
        "currency": "TND",
        "transaction_type": "transfer",
        "sender_id": "demo-sender",
        "receiver_id": ORGANIZATION,
        "country_from": "TN",
        "country_to": "TN",
    }


def _embedded_jpeg(pdf: Path) -> bytes:
    document = pymupdf.open(pdf)
    try:
        images = document[0].get_images()
        if len(images) != 1:
            raise RuntimeError(f"{pdf.name} should contain the counterfeit JPEG once")
        return document.extract_image(images[0][0])["image"]
    finally:
        document.close()


def _mark(body: dict, kind: str) -> dict | None:
    return next((mark for mark in body["documents"]["marks"] if mark["kind"] == kind), None)


def _score(client: TestClient, path: Path, *, secret: str | None, pdf: bool) -> dict:
    document = {
        "entity_id": ORGANIZATION,
        "expect_signature": False,
        "filename": path.name,
        "tenant_secret": secret,
    }
    encoded = _b64(path)
    if pdf:
        document["pdf_base64"] = encoded
    else:
        document["image_base64"] = encoded
    response = client.post("/v1/score", json={"transaction": _payment(), "document": document})
    response.raise_for_status()
    body = response.json()
    mark = _mark(body, "stamp")
    if mark is None:
        raise RuntimeError(f"{path.name} produced no stamp mark")
    signature = _mark(body, "signature")
    return {
        "http_status": response.status_code,
        "file": path.name,
        "upload": "pdf" if pdf else "image",
        "checked": body["documents"].get("checked"),
        "approval_required": body["documents"].get("approval_required"),
        "warnings": body["documents"].get("warnings"),
        "verdict": mark.get("verdict"),
        "status": mark.get("status"),
        "reason_codes": mark.get("reason_codes"),
        "alignment_ncc": mark.get("alignment_ncc"),
        "question": mark.get("question"),
        "proposal_id_present": bool(mark.get("proposal_id")),
        "proposal_id": mark.get("proposal_id"),
        "review_recommended": mark.get("review_recommended"),
        "risk_level": mark.get("risk_level"),
        "signature_status": None if signature is None else signature.get("status"),
    }


def _approve(client: TestClient, proposal_id: str) -> dict:
    response = client.post(
        "/v1/documents/decide",
        json={
            "proposal_id": proposal_id,
            "approve": True,
            "comment": "Organization A capital stamp",
        },
    )
    response.raise_for_status()
    return response.json()


def _show(title: str, row: dict) -> None:
    verdict = row.get("verdict") or row.get("status")
    reasons = ",".join(row.get("reason_codes") or [])
    print(f"{title}\t{row['file']}\t{row['upload']}\t{verdict}\t{reasons}\tncc={row.get('alignment_ncc')}")
    if row.get("question"):
        print(f"  question: {row['question']}")


def main() -> None:
    required = (CAPITAL_PDF, CAPITAL_COUNTERFEIT_JPG, CAPITAL_COUNTERFEIT_PDF, UNRELATED_PDF)
    missing = [path for path in required if not path.is_file()]
    if missing:
        raise SystemExit("missing files: " + ", ".join(str(path) for path in missing))
    embedded = _embedded_jpeg(CAPITAL_COUNTERFEIT_PDF)
    original = CAPITAL_COUNTERFEIT_JPG.read_bytes()
    if embedded != original:
        raise SystemExit("capital_0019_counterfeit.pdf does not contain the original JPEG bytes")

    with tempfile.TemporaryDirectory() as store:
        os.environ["FRAUD_SPECIMEN_DIR"] = store
        client = TestClient(create_app(FraudDetectionEngine()))
        proposed = _score(client, CAPITAL_PDF, secret=None, pdf=True)
        if proposed["status"] != "awaiting_approval" or not proposed["proposal_id"]:
            raise SystemExit(f"capital PDF was not offered for approval: {proposed}")
        approved = _approve(client, proposed["proposal_id"])
        if not approved.get("enrolled"):
            raise SystemExit(f"approval did not enroll the capital PDF: {approved}")
        secret = str(approved["tenant_secret"])

        genuine = _score(client, CAPITAL_PDF, secret=secret, pdf=True)
        fraudulent = _score(client, CAPITAL_COUNTERFEIT_PDF, secret=secret, pdf=True)
        unrelated = _score(client, UNRELATED_PDF, secret=secret, pdf=True)
        extra = []
        for path, pdf in (
            (GENUINE_SCAN, False),
            (CAPITAL_COUNTERFEIT_JPG, False),
            (SUBTLE_COUNTERFEIT, False),
            (MISSING_STAMP, False),
        ):
            if path.is_file():
                extra.append(_score(client, path, secret=secret, pdf=pdf))

    report = {
        "organization": ORGANIZATION,
        "counterfeit_jpeg_sha256": hashlib.sha256(original).hexdigest(),
        "counterfeit_pdf_embeds_that_jpeg": True,
        "enrollment": {
            "file": CAPITAL_PDF.name,
            "upload": "pdf",
            "status_before_approval": proposed["status"],
            "reason_codes_before_approval": proposed["reason_codes"],
            "decide_enrolled": approved.get("enrolled"),
            "decide_reason": approved.get("reason"),
        },
        "genuine": genuine,
        "fraudulent": fraudulent,
        "unrecognized": {key: value for key, value in unrelated.items() if key != "proposal_id"},
        "additional": [{key: value for key, value in row.items() if key != "proposal_id"} for row in extra],
    }
    OUTCOMES.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("step\tfile\tupload\tverdict\treason\tncc")
    print("enroll\t" + CAPITAL_PDF.name + "\tpdf\tapproved\tsaved")
    _show("genuine", genuine)
    _show("fraudulent", fraudulent)
    _show("unrecognized", unrelated)
    for row in extra:
        _show("additional", row)

    checks = [
        (genuine["verdict"] == "genuine" and genuine["reason_codes"] == ["reference_match"], "genuine PDF"),
        (fraudulent["verdict"] == "fraudulent" and fraudulent["reason_codes"] == ["local_ink_anomaly"], "capital counterfeit PDF"),
        (
            unrelated["verdict"] == "unrecognized"
            and unrelated["reason_codes"] == ["no_matching_enrolled_identity"]
            and unrelated["proposal_id_present"]
            and "Save it as a new genuine stamp?" in (unrelated["question"] or ""),
            "unrelated PDF",
        ),
    ]
    failed = [name for ok, name in checks if not ok]
    if failed:
        raise SystemExit("unexpected verdicts: " + ", ".join(failed))


if __name__ == "__main__":
    main()
