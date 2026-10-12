"""Retrieval evaluation: chunking strategies x retrieval modes on the same questions.

    python -m app.eval.retrieval_eval --check          # every gold anchor exists in the corpus
    python -m app.eval.retrieval_eval                  # all configurations
    python -m app.eval.retrieval_eval --configs fixed:dense structural:hybrid structural:hybrid+rerank@e5-base

A configuration is <strategy>:<mode>[+rerank][@<model>], model one of
e5-small, e5-base, e5-large (default: EMBEDDING_MODEL).

A retrieved passage is relevant when it contains one of the question's gold
anchor phrases (and comes from the gold document when one is named). Anchors
rather than article ids keep the comparison fair: fixed-size chunks have no
article field, but they do contain the text.

Writes docs/RETRIEVAL_EVAL.md and data/eval/retrieval_<timestamp>.json.
"""

import argparse
import json
import re
import statistics
import time
from collections import defaultdict
from pathlib import Path

from app.config import REPO_ROOT, settings
from app.modules.rag.ingestion.pipeline import load_chunks
from app.modules.rag.retrieval.bm25 import _fold
from app.modules.rag.retrieval.hybrid import search

DATASET = Path(__file__).parent / "datasets" / "retrieval_questions.jsonl"
DEFAULT_CONFIGS = (
    "fixed:dense",  # the deck's baseline
    "fixed:bm25",
    "fixed:hybrid",
    "structural:dense",
    "structural:bm25",
    "structural:hybrid",
    "structural:hybrid+rerank",
)
TOP_K = 10


def _norm(text: str) -> str:
    text = text.replace("’", "'").replace("`", "'").replace("«", " ").replace("»", " ")
    return re.sub(r"\s+", " ", _fold(text)).strip()


def load_questions() -> list[dict]:
    with DATASET.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def is_relevant(passage_text: str, doc_id: str, gold: list[dict]) -> bool:
    text = _norm(passage_text)
    for item in gold:
        if item.get("doc") and not doc_id.startswith(item["doc"]):
            continue
        if _norm(item["anchor"]) in text:
            return True
    return False


def check_anchors(strategies: tuple[str, ...] = ("structural", "fixed")) -> int:
    missing = 0
    for strategy in strategies:
        rows = load_chunks(strategy)
        texts = [(row["doc_id"], row["text"]) for row in rows]
        for q in load_questions():
            if not any(is_relevant(text, doc, q["gold"]) for doc, text in texts):
                missing += 1
                print(f"[{strategy}] {q['id']} no chunk contains any gold anchor: {q['question']}")
    print("all anchors found" if not missing else f"{missing} question/strategy pairs without a gold chunk")
    return missing


MODELS = {
    "e5-small": "intfloat/multilingual-e5-small",
    "e5-base": "intfloat/multilingual-e5-base",
    "e5-large": "intfloat/multilingual-e5-large",
}


def run_config(config: str, questions: list[dict]) -> dict:
    config_main, _, model_key = config.partition("@")
    model = MODELS[model_key] if model_key else None
    strategy, _, mode = config_main.partition(":")
    rerank = mode.endswith("+rerank")
    mode = mode.replace("+rerank", "")
    if mode != "bm25":
        from app.services.embeddings import get_embedder
        from app.services.vectorstore import collection_name, get_store

        name = get_embedder(model).model_name
        if not get_store().exists(strategy, name):
            # Dense search returns nothing without its collection, which would score 0 silently.
            raise SystemExit(f"{config}: no index {collection_name(strategy, name)}. Build it first.")
    per_question, latencies = [], []
    for q in questions:
        started = time.perf_counter()
        passages = search(q["question"], k=TOP_K, mode=mode, strategy=strategy, rerank=rerank, embedding_model=model)
        latencies.append((time.perf_counter() - started) * 1000)
        rank = next(
            (i + 1 for i, p in enumerate(passages) if is_relevant(p.text, p.doc_id, q["gold"])),
            None,
        )
        per_question.append({"id": q["id"], "language": q["language"], "type": q.get("type", "natural"), "rank": rank})

    def summary(rows: list[dict]) -> dict:
        n = len(rows) or 1
        return {
            "n": len(rows),
            "recall@1": sum(1 for r in rows if r["rank"] == 1) / n,
            "recall@5": sum(1 for r in rows if r["rank"] and r["rank"] <= 5) / n,
            "mrr@10": sum(1 / r["rank"] for r in rows if r["rank"]) / n,
        }

    by_language, by_type = defaultdict(list), defaultdict(list)
    for row in per_question:
        by_language[row["language"]].append(row)
        by_type[row["type"]].append(row)
    latencies.sort()
    return {
        "config": config,
        "overall": summary(per_question),
        "by_language": {lang: summary(rows) for lang, rows in sorted(by_language.items())},
        "by_type": {kind: summary(rows) for kind, rows in sorted(by_type.items())},
        "p50_ms": statistics.median(latencies),
        "p95_ms": latencies[int(0.95 * (len(latencies) - 1))],
        "questions": per_question,
    }


def _markdown(results: list[dict], n_questions: int) -> str:
    lines = [
        "# Retrieval evaluation",
        "",
        f"{n_questions} questions from `backend/app/eval/datasets/retrieval_questions.jsonl`. "
        "A hit is a retrieved passage containing a gold anchor phrase. "
        "Generated by `python -m app.eval.retrieval_eval`.",
        "",
        "| Configuration | Recall@1 | Recall@5 | MRR@10 | p50 ms | p95 ms |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        o = r["overall"]
        lines.append(
            f"| {r['config']} | {o['recall@1']:.2f} | {o['recall@5']:.2f} | {o['mrr@10']:.3f} "
            f"| {r['p50_ms']:.0f} | {r['p95_ms']:.0f} |"
        )
    lines += ["", "## Recall@5 by question language", ""]
    languages = sorted({lang for r in results for lang in r["by_language"]})
    lines.append("| Configuration | " + " | ".join(f"{l} (n={results[0]['by_language'][l]['n']})" for l in languages) + " |")
    lines.append("| --- |" + " --- |" * len(languages))
    for r in results:
        cells = [f"{r['by_language'][l]['recall@5']:.2f}" for l in languages]
        lines.append(f"| {r['config']} | " + " | ".join(cells) + " |")
    types = sorted({t for r in results for t in r["by_type"]})
    lines += ["", "## Recall@5 / MRR by question type", "",
              "`natural`: a founder's question. `article_lookup`: names an article or a law number.", ""]
    lines.append("| Configuration | " + " | ".join(f"{t} (n={results[0]['by_type'][t]['n']})" for t in types) + " |")
    lines.append("| --- |" + " --- |" * len(types))
    for r in results:
        cells = [f"{r['by_type'][t]['recall@5']:.2f} / {r['by_type'][t]['mrr@10']:.2f}" for t in types]
        lines.append(f"| {r['config']} | " + " | ".join(cells) + " |")
    lines += ["", "## Misses at k=5 for the best configuration", ""]
    best = max(results, key=lambda r: r["overall"]["mrr@10"])
    questions = {q["id"]: q for q in load_questions()}
    for row in best["questions"]:
        if not row["rank"] or row["rank"] > 5:
            lines.append(f"- `{row['id']}` ({row['language']}) rank={row['rank']}: {questions[row['id']]['question']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--configs", nargs="+", default=list(DEFAULT_CONFIGS))
    args = parser.parse_args(argv)
    if args.check:
        check_anchors()
        return

    questions = load_questions()
    results = []
    for config in args.configs:
        result = run_config(config, questions)
        o = result["overall"]
        by = "  ".join(f"{t}: R@5 {v['recall@5']:.2f} MRR {v['mrr@10']:.2f}" for t, v in result["by_type"].items())
        print(f"{config:34s} R@1 {o['recall@1']:.2f}  R@5 {o['recall@5']:.2f}  MRR {o['mrr@10']:.3f}  p50 {result['p50_ms']:.0f} ms | {by}", flush=True)
        results.append(result)

    out_dir = settings.data_dir / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (out_dir / f"retrieval_{stamp}.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    (REPO_ROOT / "docs" / "RETRIEVAL_EVAL.md").write_text(_markdown(results, len(questions)), encoding="utf-8")
    print("wrote docs/RETRIEVAL_EVAL.md")


if __name__ == "__main__":
    main()
