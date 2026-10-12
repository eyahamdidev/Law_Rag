"""Module evaluation (POST /v1/eval and `python -m eval.run_eval`).

Suites:
* financial  error-detection recall per fault, false-positive rate on valid plans
* sections   section-mapping accuracy on synthetic plans (keyword parser)
* writer     unflagged invented figures after the guard, with a model stub that invents numbers
* merge      profile/questionnaire/document precedence and conflict reporting
* latency    p50/p95 of the full pipeline on synthetic uploads

Everything here is synthetic. Rubric agreement and field-level accuracy against
real plans need the hand-scored sample (eval/datasets/README.md) and are reported
as null until it exists. Numbers are NOT results for real plans.
"""

from __future__ import annotations

import json
import os
import random
import statistics
import tempfile
import time
from pathlib import Path

DATASETS = Path(__file__).resolve().parent / "datasets"


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 1)


def financial(seed: int, n: int | None) -> dict:
    from app import financial as fin
    from eval.synthetic import FAULTS, dataset, to_model

    rows = dataset(seed, n_fault=n or 30, n_valid=20)
    hit: dict[str, list[int]] = {f: [] for f in FAULTS}
    fp, valid_n, detail = 0, 0, []
    for r in rows:
        m = to_model(r["model"])
        d = fin.derive(m)
        sigs = [s for s in fin.check(m, d) if s.severity in ("high", "review")]
        kinds = {s.kind for s in sigs}
        if r["fault"]:
            hit[r["fault"]].append(1 if r["fault"] in kinds else 0)
            if r["fault"] not in kinds:
                detail.append({"id": r["id"], "fault": r["fault"], "fired": sorted(kinds)})
        else:
            valid_n += 1
            if sigs:
                fp += 1
                detail.append({"id": r["id"], "fault": None, "fired": sorted(kinds)})
    per = {f: (round(sum(v) / len(v), 3) if v else None) for f, v in hit.items()}
    flat = [x for v in hit.values() for x in v]
    return {"plans_with_fault": len(flat), "valid_plans": valid_n, "recall_overall": round(sum(flat) / max(len(flat), 1), 3),
            "recall_by_fault": per, "false_positive_rate": round(fp / max(valid_n, 1), 3), "misses": detail[:20],
            "note": "Synthetic plans. Faults are injected by eval/synthetic.py. LLM-only arithmetic baseline is not run here."}


def sections(seed: int, n: int | None) -> dict:
    from app.agents.common import Trace
    from app.agents.parser import parse
    from app.intake import read_document
    from app.llm import LLMClient
    from app.masking import Masker
    from app.templates import load_template
    from eval.synthetic import plan_text

    rng = random.Random(seed)
    tpl = load_template("bfpme_creation")
    ids = [s["id"] for s in tpl["sections"]]
    ok = total = 0
    wrong = []
    for k in range(n or 25):
        present = rng.sample(ids, rng.randint(6, len(ids)))
        text, truth = plan_text(rng, present)
        doc = read_document(text.encode())
        plan = parse(doc, tpl, llm=LLMClient(api_key="", cache=False), masker=Masker(), lang="fr", trace=Trace(), mode="keywords")
        got = {}
        for sid, e in plan.sections.items():
            for seg in e["segments"]:
                got[seg["heading"]] = sid
        for h, sid in truth.items():
            total += 1
            if got.get(h) == sid:
                ok += 1
            else:
                wrong.append({"heading": h, "expected": sid, "got": got.get(h)})
    return {"headings": total, "mapping_accuracy": round(ok / max(total, 1), 3), "mode": "keywords",
            "errors": wrong[:15], "note": "Headings are written independently of the template keywords, so this is not circular, but it is still synthetic."}


def writer(seed: int, n: int | None) -> dict:
    """A stub 'model' that always invents figures. The guard must mark every one."""
    import httpx

    from app.agents.common import Trace
    from app.agents.writer import allowed_numbers, draft_section, unflagged_count
    from app.llm import LLMClient
    from app.masking import Masker
    from app.templates import load_template

    def handler(request: httpx.Request) -> httpx.Response:
        body = {"choices": [{"message": {"content": json.dumps({"text": "Le marché pèse 4 500 000 TND, notre part sera de 12 % et nous aurons 37 clients dès 2027."})}}]}
        return httpx.Response(200, json=body)

    llm = LLMClient(api_key="x", transport=httpx.MockTransport(handler), cache=False, max_retries=0)
    tpl = load_template("bfpme_creation")
    values = {"problem": "Perte de temps.", "headcount": 4}
    total_inv = flagged = unflagged = 0
    for sec in tpl["sections"][: (n or 12)]:
        d = draft_section(sec, values=values, derived=None, existing="", guidance=[], lang="fr", llm=llm, masker=Masker(), trace=Trace())
        allowed = allowed_numbers(values)
        unflagged += unflagged_count(d.text, allowed)
        flagged += len(d.flagged)
        total_inv += 3
    return {"drafts": min(n or 12, len(tpl["sections"])), "invented_figures_injected": total_inv, "flagged": flagged,
            "unflagged_after_guard": unflagged, "hallucinated_figure_rate_unflagged": round(unflagged / max(total_inv, 1), 3),
            "note": "Tests the guard against a stub that invents numbers. A real-model rate needs a model key and the hand-checked sample."}


def merge(seed: int, n: int | None) -> dict:
    from app.profile import merge_context

    cases = [
        ({"stage": "creation", "sector": "software"}, {"stage": "extension"}, {"legal_form": "SARL"}, "stage", "extension", "questionnaire", True),
        ({"sector": "Software"}, {"sector": "software"}, None, "sector", "software", "questionnaire", False),
        ({"legal_form": "SA"}, None, {"legal_form": "SARL"}, "legal_form", "SA", "orchestrator", True),
        (None, {"loan_amount": "50 000"}, {"loan_amount": 50400}, "loan_amount", 50000.0, "questionnaire", False),
        (None, {"loan_amount": "50 000"}, {"loan_amount": 80000}, "loan_amount", 50000.0, "questionnaire", True),
        ({"need": "financing", "amount": "80 000"}, None, None, "funding_instrument", "loan", "orchestrator", False),
    ]
    ok = 0
    for prof, ans, doc, field, value, src, conflict in cases:
        c = merge_context(prof, ans, doc)
        good = c.values.get(field) == value and c.provenance.get(field) == src and (bool(c.conflicts) == conflict)
        ok += good
    return {"cases": len(cases), "correct": ok, "accuracy": round(ok / len(cases), 3)}


def latency(seed: int, n: int | None) -> dict:
    from app import storage
    from app.contract import Request
    from app.pipeline import run
    from eval.synthetic import plan_text, ALT_HEADINGS

    os.environ.setdefault("BP_LLM", "off")
    rng = random.Random(seed)
    times = []
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["UPLOADS_DIR"] = tmp
        for i in range(n or 10):
            text, _ = plan_text(rng, list(ALT_HEADINGS))
            ref = storage.put(text.encode())
            t0 = time.perf_counter()
            run(Request(request_id=f"e{i}", file_ref=ref, lang="fr", options={"answers": {"revenue_by_year": "100000, 150000, 200000", "horizon_years": 3}}))
            times.append((time.perf_counter() - t0) * 1000)
    return {"runs": len(times), "p50_ms": _pct(times, 0.5), "p95_ms": _pct(times, 0.95), "llm": "off", "mean_ms": round(statistics.mean(times), 1)}


def run_all(suite: str = "all", seed: int = 7, n: int | None = None) -> dict:
    fns = {"financial": financial, "sections": sections, "writer": writer, "merge": merge, "latency": latency}
    chosen = fns if suite == "all" else {suite: fns[suite]} if suite in fns else {}
    out = {"dataset_version": "synthetic-v1", "seed": seed, "temperature": 0, "suites": {k: f(seed, n) for k, f in chosen.items()}}
    out["not_measured"] = {
        "rubric_agreement": "needs a hand-scored sample of about 10 plans (eval/datasets/README.md)",
        "field_level_accuracy_real_plans": "needs real or realistic plans",
        "hallucinated_figure_rate_with_real_model": "needs a model key",
    }
    uri = os.environ.get("MLFLOW_TRACKING_URI")
    if uri:
        try:
            import mlflow

            mlflow.set_tracking_uri(uri)
            mlflow.set_experiment("bp")
            with mlflow.start_run(run_name=f"bp-eval-{suite}"):
                mlflow.log_params({"module": "bp", "dataset_version": "synthetic-v1", "seed": seed, "suite": suite})
                for sname, res in out["suites"].items():
                    for k, v in res.items():
                        if isinstance(v, (int, float)):
                            mlflow.log_metric(f"{sname}.{k}", v)
        except Exception:  # noqa: BLE001  tracking must not break evaluation
            out["mlflow"] = "not logged (server unreachable or mlflow not installed)"
    return out


if __name__ == "__main__":
    import sys

    print(json.dumps(run_all(sys.argv[1] if len(sys.argv) > 1 else "all"), indent=2, ensure_ascii=False))
