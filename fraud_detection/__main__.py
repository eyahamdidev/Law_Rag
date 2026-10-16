from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import uvicorn

from fraud_detection.data.synthetic_tunisia import generate_tunisia
from fraud_detection.entity_intelligence.registry import EntityRegistry
from fraud_detection.evaluation.metrics import classification_report
from fraud_detection.evaluation.splits import assert_time_order, temporal_masks
from fraud_detection.inference.pipeline import FraudDetectionEngine
from fraud_detection.models.supervised import SupervisedDetector
from fraud_detection.paths import EVAL
from fraud_detection.schema import Transaction


def _write_population(destination: Path) -> None:
    examples, entities = generate_tunisia()
    destination.mkdir(parents=True, exist_ok=True)
    rows = []
    for example in examples:
        payload = example.transaction.model_dump(mode="json")
        payload["scenario"] = example.scenario
        payload["metadata"] = json.dumps(payload["metadata"])
        rows.append(payload)
    pd.DataFrame(rows).to_csv(destination / "tunisia_synth.csv", index=False)
    pd.DataFrame([entity.model_dump(mode="json") for entity in entities]).to_csv(
        destination / "tunisia_entities.csv",
        index=False,
    )
    print(f"wrote {len(rows)} transactions to {destination}")


def _train(model_path: Path) -> SupervisedDetector:
    examples, entities = generate_tunisia()
    entity_map = {entity.entity_id: entity for entity in entities}
    detector = SupervisedDetector().fit(
        [(item.transaction, item.label_type) for item in examples],
        entity_map,
    )
    detector.save(model_path)
    print(f"saved {detector.backend} model to {model_path}")
    return detector


def _evaluate_saved() -> None:
    path = EVAL / "metrics.json"
    if not path.exists():
        raise SystemExit("No metrics file yet. Run: .venv/bin/python -m fraud_detection train")
    print(path.read_text())


def _evaluate_synthetic() -> None:
    examples, entities = generate_tunisia()
    entity_map = {entity.entity_id: entity for entity in entities}
    timestamps = [item.transaction.timestamp for item in examples]
    train, validation, test = temporal_masks(
        timestamps,
        datetime(2024, 7, 1),
        datetime(2024, 9, 1),
    )
    assert_time_order(timestamps, train, validation, test)
    train_rows = [
        (item.transaction, item.label_type)
        for item, keep in zip(examples, train)
        if keep
    ]
    detector = SupervisedDetector().fit(train_rows, entity_map)
    engine = FraudDetectionEngine(supervised=detector, registry=EntityRegistry(entities))
    labels = []
    scores = []
    for example, keep in zip(examples, test):
        if not keep:
            continue
        history = [
            other.transaction
            for other in examples
            if other.transaction.timestamp < example.transaction.timestamp
        ]
        assessment = engine.score(example.transaction, history, entities)
        labels.append(0 if example.label_type is None else 1)
        scores.append(assessment.risk_score / 100)
    report = classification_report(labels, scores, threshold=0.75, top_k=min(50, len(labels)))
    print(json.dumps({"split": "time", "test_rows": len(labels), "metrics": report}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Fraud detection agent")
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate", help="write the synthetic Tunisia laboratory")
    generate.add_argument("--out", type=Path, default=Path("fraud_detection/data/processed/canonical"))
    sub.add_parser("train", help="prepare public datasets and train the real models")
    sub.add_parser("train-stamps", help="train the supervised genuine-versus-fake stamp verifier")
    synthetic = sub.add_parser("train-synthetic", help="fit the synthetic Tunisia laboratory only")
    synthetic.add_argument("--out", type=Path, default=Path("model_store/supervised/tunisia.joblib"))
    sub.add_parser("evaluate", help="print the saved real-data metrics")
    sub.add_parser("evaluate-synthetic", help="temporal split on the synthetic laboratory")
    serve = sub.add_parser("serve", help="run the scoring API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    score = sub.add_parser("score", help="score one transaction JSON file")
    score.add_argument("--transaction", type=Path, required=True)
    score.add_argument("--history", type=Path)
    score.add_argument("--model", type=Path)
    args = parser.parse_args()

    if args.command == "generate":
        _write_population(args.out)
    elif args.command == "train":
        from fraud_detection.train_real import main as train_main

        train_main()
    elif args.command == "train-stamps":
        from fraud_detection.documents.train_stamps import main as train_stamps_main

        train_stamps_main()
    elif args.command == "train-synthetic":
        _train(args.out)
    elif args.command == "evaluate":
        _evaluate_saved()
    elif args.command == "evaluate-synthetic":
        _evaluate_synthetic()
    elif args.command == "serve":
        uvicorn.run("fraud_detection.api.app:app", host=args.host, port=args.port, reload=False)
    elif args.command == "score":
        from fraud_detection.api.app import engine_from_env

        transaction = Transaction.model_validate_json(args.transaction.read_text())
        history = []
        if args.history:
            history = [Transaction.model_validate(item) for item in json.loads(args.history.read_text())]
        engine = engine_from_env()
        if args.model:
            engine.supervised = SupervisedDetector.load(args.model)
        print(engine.score(transaction, history).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
