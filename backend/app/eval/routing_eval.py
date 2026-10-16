"""Routing evaluation: keyword baseline vs LLM planner, Macro-F1 over agents.

    python -m app.eval.routing_eval                    # both routers
    python -m app.eval.routing_eval --router keyword
    python -m app.eval.routing_eval --dataset heldout --pause 20

Routing is multi-label: a message can need several agents, or none (vague or
off-topic). For each agent, a query is a binary decision (called / not
called); F1 is computed per agent and averaged (Macro-F1), plus an extra
"none" class for messages that should get a clarification or a refusal.
Exact-match accuracy (the whole agent set right) is reported beside it.
The deck's target is Macro-F1 >= 0.90.

Writes docs/ROUTING_EVAL.md (dev set) or docs/ROUTING_EVAL_HELDOUT.md.
Report the held-out score: the dev set was used to write the prompts.
"""

import argparse
import json
import time
from pathlib import Path

from app.agents.registry import AGENTS
from app.config import REPO_ROOT
from app.orchestrator.keyword_router import keyword_route
from app.orchestrator.planner import make_plan
from app.schemas.agents import FounderProfile

DATASETS = {
    # Labelled while writing planner v1-v4: v4 was written after reading v3's errors on it.
    "dev": Path(__file__).parent / "datasets" / "routing_queries.jsonl",
    # Never used to write or tune a prompt. Report this one as the routing score.
    "heldout": Path(__file__).parent / "datasets" / "routing_heldout.jsonl",
}
LABELS = list(AGENTS) + ["none"]


def load(name: str = "dev") -> list[dict]:
    with DATASETS[name].open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def predict(router: str, question: str, pause: float) -> tuple[set[str], str]:
    if router == "keyword":
        return set(keyword_route(question)[:3]) or {"none"}, "keyword"
    plan = make_plan(question, [], FounderProfile(), [])
    if plan.source != "llm":
        raise RuntimeError(f"LLM planner fell back to keywords: {plan.error}")
    # Groq free tier: 8,000 tokens/min per model, ~1,500 tokens per planner call.
    time.sleep(pause)
    return {s.agent for s in plan.steps} or {"none"}, plan.prompt_ref or ""


def scores(rows: list[dict]) -> dict:
    per_label = {}
    for label in LABELS:
        tp = sum(1 for r in rows if label in r["pred"] and label in r["gold"])
        fp = sum(1 for r in rows if label in r["pred"] and label not in r["gold"])
        fn = sum(1 for r in rows if label not in r["pred"] and label in r["gold"])
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_label[label] = {"precision": precision, "recall": recall, "f1": f1, "support": tp + fn}
    macro = sum(v["f1"] for v in per_label.values()) / len(per_label)
    exact = sum(1 for r in rows if r["pred"] == r["gold"]) / len(rows)
    return {"macro_f1": macro, "exact_match": exact, "per_label": per_label}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--router", choices=["keyword", "llm", "both"], default="both")
    parser.add_argument("--pause", type=float, default=12.0, help="seconds between LLM calls")
    parser.add_argument("--dataset", choices=sorted(DATASETS), default="dev")
    args = parser.parse_args(argv)
    routers = ["keyword", "llm"] if args.router == "both" else [args.router]
    data = load(args.dataset)
    report = {}
    for router in routers:
        rows = []
        for q in data:
            try:
                pred, served_by = predict(router, q["question"], args.pause)
            except RuntimeError as error:
                print(f"{router}: stopped at {q['id']}: {error}")
                rows = []
                break
            rows.append({"id": q["id"], "question": q["question"], "gold": set(q["agents"]) or {"none"}, "pred": pred, "served_by": served_by})
        if not rows:
            continue
        result = scores(rows)
        result["errors"] = [
            {"id": r["id"], "question": r["question"], "gold": sorted(r["gold"]), "pred": sorted(r["pred"])}
            for r in rows if r["pred"] != r["gold"]
        ]
        counts = {}
        for r in rows:
            counts[r["served_by"]] = counts.get(r["served_by"], 0) + 1
        result["served_by"] = counts
        report[router] = result
        print(f"{router:8s} Macro-F1 {result['macro_f1']:.3f}  exact {result['exact_match']:.2f}  served by {result['served_by']}")
        out = REPO_ROOT / "data" / "eval" / f"routing_{args.dataset}_{router}_{time.strftime('%Y%m%d-%H%M%S')}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps([{**r, "gold": sorted(r["gold"]), "pred": sorted(r["pred"])} for r in rows], ensure_ascii=False, indent=1), encoding="utf-8")

    lines = ["# Routing evaluation", "", f"{len(data)} labelled messages from `{DATASETS[args.dataset].name}` ({args.dataset} set). "
             "Generated by `python -m app.eval.routing_eval`.", "",
             "| Router | Macro-F1 | Exact match |", "| --- | --- | --- |"]
    lines += [f"| {name} | {r['macro_f1']:.3f} | {r['exact_match']:.2f} |" for name, r in report.items()]
    lines += ["", "Calls served by: " + "; ".join(
        f"{name}: " + ", ".join(f"{model} x{n}" for model, n in r["served_by"].items()) for name, r in report.items()
    )]
    for name, r in report.items():
        lines += ["", f"## {name}: F1 per agent", "", "| Agent | Precision | Recall | F1 | Support |", "| --- | --- | --- | --- | --- |"]
        lines += [f"| {label} | {v['precision']:.2f} | {v['recall']:.2f} | {v['f1']:.2f} | {v['support']} |" for label, v in r["per_label"].items()]
        lines += ["", f"### {name}: errors", ""]
        lines += [f"- `{e['id']}` {e['question']} — expected {e['gold']}, got {e['pred']}" for e in r["errors"]] or ["- none"]
    if report:
        name = "ROUTING_EVAL.md" if args.dataset == "dev" else f"ROUTING_EVAL_{args.dataset.upper()}.md"
        (REPO_ROOT / "docs" / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote docs/{name}")


if __name__ == "__main__":
    main()
