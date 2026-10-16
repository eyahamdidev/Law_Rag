"""Train and evaluate the fraud agent on the downloaded public datasets.

Behavioral API model:
  BankSim -> CARD_FRAUD
  IBM AML HI-Small -> AML_LAUNDERING
  PaySim -> ACCOUNT_TAKEOVER

ULB is loaded by the API when a request contains V1-V28. Elliptic stays offline:
its anonymous graph columns are not a payment schema.
"""

from __future__ import annotations

import gc
import json
import math
import os
import traceback
import urllib.request
import zipfile
from pathlib import Path

import joblib
import numpy as np

from fraud_detection.data.featurize import FEATURE_VERSION, featurize_banksim, featurize_ibm, featurize_paysim
from fraud_detection.evaluation.metrics import classification_report, precision_at_k, recall_at_k
from fraud_detection.models.features import FEATURE_NAMES
from fraud_detection.models.general_behavior import GeneralBehavior
from fraud_detection.models.population_anomaly import PopulationAnomaly
from fraud_detection.models.portable import portable_indices
from fraud_detection.models.supervised import SupervisedDetector
from fraud_detection.paths import ARTIFACTS, EVAL, PROCESSED, RAW, ROOT

BEHAVIORAL = (
    ("banksim", "CARD_FRAUD", PROCESSED / "banksim_features.npz", featurize_banksim),
    ("paysim", "ACCOUNT_TAKEOVER", PROCESSED / "paysim_features.npz", featurize_paysim),
    ("ibm_aml", "AML_LAUNDERING", PROCESSED / "ibm_aml_features.npz", featurize_ibm),
)


def _sanitize(value):
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, (np.floating, float)):
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, np.ndarray):
        return _sanitize(value.tolist())
    return value


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_sanitize(payload), indent=2))


def _prepare(name: str, npz: Path, builder) -> dict:
    sidecar = EVAL / f"{name}_prepare.json"
    if npz.exists() and npz.stat().st_size > 0 and sidecar.exists():
        payload = json.loads(sidecar.read_text())
        if payload.get("feature_version") == FEATURE_VERSION:
            print(f"reuse prepared {name}", flush=True)
            return payload
        print(f"rebuild {name}; feature version changed", flush=True)
    stats = builder()
    gc.collect()
    return stats


def _slice_for_fit(features: np.ndarray, labels: np.ndarray, cap: int = 200_000, seed: int = 0):
    if len(labels) <= cap:
        return features, labels
    positives = np.flatnonzero(labels == 1)
    negatives = np.flatnonzero(labels == 0)
    rng = np.random.default_rng(seed)
    room = max(0, cap - len(positives))
    chosen_neg = rng.choice(negatives, size=min(room, len(negatives)), replace=False) if room and len(negatives) else np.array([], dtype=int)
    chosen = np.concatenate([positives, chosen_neg])
    rng.shuffle(chosen)
    return features[chosen], labels[chosen]


def _fit_lightgbm(train_x, train_y, val_x, val_y):
    import lightgbm as lgb

    model = lgb.LGBMClassifier(
        n_estimators=200,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=50,
        subsample=0.8,
        colsample_bytree=0.8,
        class_weight="balanced",
        random_state=0,
        verbosity=-1,
        n_jobs=4,
    )
    fit_x, fit_y = _slice_for_fit(val_x, val_y)
    if len(np.unique(fit_y)) > 1 and len(fit_y) > 20:
        model.fit(
            train_x,
            train_y,
            eval_set=[(fit_x, fit_y)],
            callbacks=[lgb.early_stopping(30, verbose=False)],
        )
    else:
        model.fit(train_x, train_y)
    calibrator = None
    calibrated_on = 0
    if int(np.sum(fit_y)) >= 20 and len(np.unique(fit_y)) > 1:
        raw = model.predict_proba(fit_x)[:, 1]
        if float(np.max(raw) - np.min(raw)) > 1e-8:
            from sklearn.isotonic import IsotonicRegression

            calibrator = IsotonicRegression(out_of_bounds="clip")
            calibrator.fit(raw, fit_y)
            calibrated_on = int(len(fit_y))
    return model, calibrator, calibrated_on


def _scores(model, calibrator, features: np.ndarray) -> np.ndarray:
    if len(features) == 0:
        return np.zeros(0, dtype=float)
    raw = model.predict_proba(features)[:, 1]
    if calibrator is None:
        return raw
    return np.clip(calibrator.predict(raw), 0.0, 1.0)


def _evaluate(labels, scores) -> dict:
    labels = np.asarray(labels).astype(int)
    scores = np.asarray(scores, dtype=float)
    if len(labels) == 0 or labels.min() == labels.max():
        return {"test_rows": int(len(labels)), "test_positives": int(labels.sum()) if len(labels) else 0, "note": "test split has one class"}
    top_k = max(1, min(100, len(labels)))
    report = classification_report(labels, scores, threshold=0.5, top_k=top_k)
    positives = int(labels.sum())
    report["precision_at_positive_count"] = precision_at_k(labels, scores, positives)
    report["recall_at_positive_count"] = recall_at_k(labels, scores, positives)
    report["test_rows"] = int(len(labels))
    report["test_positives"] = positives
    report["threshold"] = 0.5
    report["top_k"] = top_k
    return report


def _importance(model) -> list[dict]:
    gains = getattr(model, "feature_importances_", None)
    if gains is None:
        return []
    order = np.argsort(-np.asarray(gains))[:10]
    return [{"feature": FEATURE_NAMES[int(index)], "gain": int(gains[int(index)])} for index in order]


def train_behavioral(prepared: dict) -> dict:
    detector = SupervisedDetector()
    detector.binary = None
    detector.backend = "lightgbm"
    detector.feature_names = list(FEATURE_NAMES)
    detector.type_threshold = 0.70
    report = {}
    anomaly_parts = []
    rng = np.random.default_rng(0)
    for name, label, npz, _builder in BEHAVIORAL:
        print(f"fit {label} on {name}", flush=True)
        bundle = np.load(npz)
        train_x = np.nan_to_num(bundle["train_x"], nan=0.0, posinf=0.0, neginf=0.0)
        train_y = bundle["train_y"].astype(int)
        val_x = np.nan_to_num(bundle["val_x"], nan=0.0, posinf=0.0, neginf=0.0)
        val_y = bundle["val_y"].astype(int)
        test_x = np.nan_to_num(bundle["test_x"], nan=0.0, posinf=0.0, neginf=0.0)
        test_y = bundle["test_y"].astype(int)
        if len(np.unique(train_y)) < 2:
            report[label] = {"dataset": name, "error": "training split has one class"}
            bundle.close()
            continue
        model, calibrator, calibrated_on = _fit_lightgbm(train_x, train_y, val_x, val_y)
        scores = _scores(model, calibrator, test_x)
        metrics = _evaluate(test_y, scores)
        metrics["dataset"] = name
        metrics["calibrated_on_rows"] = calibrated_on
        metrics["calibration"] = "isotonic regression fit on the validation period" if calibrator is not None else "uncalibrated LightGBM probability"
        metrics["train_rows"] = int(len(train_y))
        metrics["train_positives"] = int(train_y.sum())
        metrics["validation_rows"] = int(len(val_y))
        metrics["validation_positives"] = int(val_y.sum())
        metrics["top_features"] = _importance(model)
        metrics["prepare"] = prepared.get(name, {})
        report[label] = metrics
        detector.by_type[label] = model
        if calibrator is not None:
            detector.calibrators[label] = calibrator
        legitimate = np.flatnonzero(train_y == 0)
        take = min(50_000, len(legitimate))
        if take:
            chosen = rng.choice(legitimate, size=take, replace=False)
            anomaly_parts.append(train_x[chosen])
        bundle.close()
        del train_x, val_x, test_x, scores
        gc.collect()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    detector.save(ARTIFACTS / "supervised.joblib")
    anomaly_report = {}
    if anomaly_parts:
        matrix = np.vstack(anomaly_parts)
        population = PopulationAnomaly().fit(matrix)
        population.save(ARTIFACTS / "anomaly.joblib")
        anomaly_report["trained_on_rows"] = int(len(matrix))
        anomaly_report["contamination"] = 0.01
        anomaly_report["n_estimators"] = 200
        anomaly_report["rows_per_dataset_cap"] = 50_000
        anomaly_report["fit_on"] = "legitimate training rows only"
        anomaly_report["score"] = "1 / (1 + exp(6 * decision_function)) after RobustScaler"
        per_dataset = {}
        for name, label, npz, _builder in BEHAVIORAL:
            bundle = np.load(npz)
            test_x = np.nan_to_num(bundle["test_x"], nan=0.0, posinf=0.0, neginf=0.0)
            test_y = bundle["test_y"].astype(int)
            parts = [population.score_matrix(test_x[start : start + 100_000]) for start in range(0, len(test_x), 100_000)]
            scored = np.concatenate(parts) if parts else np.zeros(0)
            per_dataset[label] = _evaluate(test_y, scored)
            per_dataset[label]["dataset"] = name
            bundle.close()
        anomaly_report["test"] = per_dataset
        indexes = portable_indices()
        general = GeneralBehavior().fit(matrix[:, indexes])
        general.save(ARTIFACTS / "general_behavior.joblib")
        anomaly_report["general_behavior"] = {
            "trained_on_rows": int(len(matrix)),
            "features": list(general.feature_names),
            "excluded": [name for name in FEATURE_NAMES if name not in general.feature_names],
            "fit_on": "legitimate training rows, portable columns only",
            "note": "Unsupervised suspicious-behavior score. Not a fraud-type label.",
        }
        del matrix
        gc.collect()
    return {"by_type": report, "anomaly": anomaly_report}


def _specialist_split_metrics(train_x, train_y, val_x, val_y, test_x, test_y) -> tuple[dict, object, object]:
    model, calibrator, calibrated_on = _fit_lightgbm(train_x, train_y, val_x, val_y)
    metrics = _evaluate(test_y, _scores(model, calibrator, test_x))
    metrics["calibrated_on_rows"] = calibrated_on
    metrics["train_rows"] = int(len(train_y))
    metrics["train_positives"] = int(train_y.sum())
    metrics["validation_rows"] = int(len(val_y))
    metrics["validation_positives"] = int(val_y.sum())
    return metrics, model, calibrator


def train_ulb() -> dict:
    import pandas as pd

    frame = pd.read_csv(RAW / "ulb" / "creditcard.csv")
    frame = frame.sort_values("Time", kind="mergesort")
    time = frame["Time"].to_numpy()
    labels = frame["Class"].astype(int).to_numpy()
    columns = [f"V{index}" for index in range(1, 29)] + ["Amount"]
    features = frame[columns].to_numpy(dtype=np.float32)
    del frame
    count = len(labels)
    train_end = time[int((count - 1) * 0.70)]
    val_end = time[int((count - 1) * 0.85)]
    train = time <= train_end
    validation = (time > train_end) & (time <= val_end)
    test = time > val_end
    metrics, model, calibrator = _specialist_split_metrics(
        features[train], labels[train], features[validation], labels[validation], features[test], labels[test]
    )
    metrics.update(
        {
            "dataset": "ulb_creditcard",
            "label": "CARD_FRAUD",
            "features": columns,
            "excluded_from_features": ["Time", "Class"],
            "train_time_end": float(train_end),
            "validation_time_end": float(val_end),
            "rows": int(count),
            "positives": int(labels.sum()),
            "used_by_api": True,
            "reason": "Loaded by POST /v1/score only when the request contains V1-V28. It does not replace the behavioral card head.",
        }
    )
    joblib.dump({"model": model, "calibrator": calibrator, "features": columns}, ARTIFACTS / "ulb_card.joblib")
    return metrics


def train_elliptic() -> dict:
    import pandas as pd

    classes = pd.read_csv(RAW / "elliptic" / "elliptic_txs_classes.csv")
    features = pd.read_csv(RAW / "elliptic" / "elliptic_txs_features.csv", header=None)
    identifiers = features.iloc[:, 0].astype(np.int64).to_numpy()
    timestep = features.iloc[:, 1].astype(np.int16).to_numpy()
    matrix = features.iloc[:, 2:].to_numpy(dtype=np.float32)
    del features
    gc.collect()

    def token(value: object) -> str:
        text = str(value).strip().lower()
        return text[:-2] if text.endswith(".0") else text

    class_map = dict(zip(classes["txId"].astype(np.int64).tolist(), classes["class"].map(token).tolist()))
    labels_raw = np.array([class_map.get(int(identifier), "unknown") for identifier in identifiers])
    known = np.isin(labels_raw, ["1", "2"])
    illicit = labels_raw == "1"
    train = known & (timestep <= 34)
    validation = known & (timestep >= 35) & (timestep <= 39)
    test = known & (timestep >= 40)
    y = illicit.astype(np.uint8)
    metrics, model, calibrator = _specialist_split_metrics(
        matrix[train], y[train], matrix[validation], y[validation], matrix[test], y[test]
    )
    metrics.update(
        {
            "dataset": "elliptic",
            "label": "AML_LAUNDERING",
            "rows_in_features_file": int(len(identifiers)),
            "known_rows": int(known.sum()),
            "unknown_rows_excluded": int((~known).sum()),
            "illicit_rows": int(illicit.sum()),
            "split": "timestep 1-34 train, 35-39 validation, 40-49 test",
            "features": "anonymous columns after txId and timestep; txId is not a feature",
            "used_by_api": False,
            "reason": "anonymized graph features are not the behavioral transaction schema",
        }
    )
    joblib.dump(
        {"model": model, "calibrator": calibrator, "split": metrics["split"]},
        ARTIFACTS / "elliptic_aml.joblib",
    )
    return metrics


def elliptic_graph() -> dict:
    import pandas as pd

    classes = pd.read_csv(RAW / "elliptic" / "elliptic_txs_classes.csv", dtype=str)
    edges = pd.read_csv(RAW / "elliptic" / "elliptic_txs_edgelist.csv", dtype=str)
    label = classes["class"].str.replace(".0", "", regex=False)
    illicit = set(classes.loc[label == "1", "txId"])
    licit = set(classes.loc[label == "2", "txId"])
    unknown = int((~label.isin(["1", "2"])).sum())
    source = edges["txId1"]
    destination = edges["txId2"]
    in_degree = destination.value_counts()
    out_degree = source.value_counts()
    source_illicit = source.isin(illicit)
    destination_illicit = destination.isin(illicit)
    return {
        "edges": int(len(edges)),
        "illicit_transactions": len(illicit),
        "licit_transactions": len(licit),
        "unknown_transactions": unknown,
        "fan_in_at_least_10": int((in_degree >= 10).sum()),
        "fan_out_at_least_10": int((out_degree >= 10).sum()),
        "max_in_degree": int(in_degree.max()),
        "max_out_degree": int(out_degree.max()),
        "edges_touching_illicit": int((source_illicit | destination_illicit).sum()),
        "edges_between_illicit": int((source_illicit & destination_illicit).sum()),
    }


def ibm_cycles() -> dict:
    path = EVAL / "ibm_laundering_edges.json"
    if not path.exists():
        return {"status": "not_available", "reason": "laundering edge file was not written"}
    payload = json.loads(path.read_text())
    edges = payload.get("edges") or []
    import networkx as nx

    graph = nx.DiGraph()
    graph.add_edges_from(tuple(edge) for edge in edges)
    found = 0
    try:
        iterator = nx.simple_cycles(graph, length_bound=5)
    except TypeError:
        iterator = nx.simple_cycles(graph)
    for _cycle in iterator:
        found += 1
        if found >= 200:
            break
    return {
        "laundering_edges": len(edges),
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "cycles_found_capped_at_200": found,
        "cycle_length_bound": 5,
    }


def build_sanctions() -> dict:
    from fraud_detection.entity_intelligence.public_lists import load_public_sanctions

    index, counts = load_public_sanctions(RAW)
    joblib.dump(index, ARTIFACTS / "sanctions.joblib")
    probe = index.match_scored("AEROCARIBBEAN AIRLINES")
    return {
        "counts": counts,
        "entries": len(index.entries),
        "available": index.available,
        "aerocaribbean_match": probe is not None,
        "aerocaribbean_score": None if probe is None else probe[1],
        "aerocaribbean_list": None if probe is None else probe[0].list_name,
    }


def validate_saml() -> dict:
    archive = RAW / "saml_d" / "SAML-D.zip"
    csv_path = RAW / "saml_d" / "SAML-D.csv"
    if not csv_path.exists() and archive.exists():
        with zipfile.ZipFile(archive) as handle:
            handle.extract("SAML-D.csv", RAW / "saml_d")
    if not csv_path.exists():
        return {"status": "not_downloaded"}
    import pandas as pd

    rows = 0
    positives = 0
    min_date = None
    max_date = None
    missing_amount = 0
    header = pd.read_csv(csv_path, nrows=0)
    columns = set(header.columns)
    usecols = [name for name in ("Date", "Time", "Amount", "Is_laundering") if name in columns]
    for chunk in pd.read_csv(csv_path, usecols=usecols, chunksize=400_000):
        rows += int(len(chunk))
        if "Is_laundering" in chunk:
            positives += int(pd.to_numeric(chunk["Is_laundering"], errors="coerce").fillna(0).sum())
        if "Amount" in chunk:
            missing_amount += int(chunk["Amount"].isna().sum())
        if "Date" in chunk:
            dates = chunk["Date"].astype(str)
            low = dates.min()
            high = dates.max()
            min_date = low if min_date is None or low < min_date else min_date
            max_date = high if max_date is None or high > max_date else max_date
    available = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_AVPHYS_PAGES")
    return {
        "status": "validated_not_used_for_training",
        "rows": rows,
        "positives": positives,
        "missing_amount": missing_amount,
        "min_date": min_date,
        "max_date": max_date,
        "columns": sorted(columns),
        "free_ram_bytes_at_decision": int(available),
        "reason": "Row counts were measured. The API AML model stays on IBM HI-Small only. A second 9.5M-row feature pass was not run in this memory budget.",
    }


def _probe(url: str, timeout: int = 20) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "fraud-detection-academic-demo"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            peeked = response.read(1200)
            return {
                "url": url,
                "status": int(response.status),
                "content_type": response.headers.get("content-type", ""),
                "peek_bytes": len(peeked),
                "saved": False,
            }
    except Exception as exc:
        return {"url": url, "error": str(exc), "saved": False}


def probe_optional_sources() -> dict:
    tunisia = _probe("https://catalog.data.gov.tn/api/3/action/package_search?q=registre&rows=1")
    ctaf = _probe("https://www.ctaf.gov.tn/")
    return {
        "tunisia_ckan": tunisia,
        "ctaf": ctaf,
        "tabformer": {
            "status": "not_downloaded",
            "reason": "IBM TabFormer transactions are distributed through a request form, not as a direct public file.",
        },
        "fraud_handbook": {
            "status": "not_downloaded",
            "reason": "The handbook publishes a simulator rather than a static transaction extract. It was not generated in this run.",
        },
        "ieee_cis": {
            "status": "not_downloaded",
            "reason": "IEEE-CIS is a Kaggle competition file. No Kaggle credentials were used.",
        },
        "opensanctions": {
            "status": "not_downloaded",
            "reason": "Official OFAC, UN, and EU lists are loaded instead of the OpenSanctions bulk database.",
        },
    }


def write_paysim_demo() -> dict:
    import csv

    from fraud_detection.data.adapters.common import flag
    from fraud_detection.data.adapters.paysim_adapter import adapt_paysim
    from fraud_detection.entity_intelligence.sanctions import SanctionsIndex
    from fraud_detection.inference.pipeline import FraudDetectionEngine
    from fraud_detection.models.population_anomaly import PopulationAnomaly

    path = RAW / "paysim" / "paysim.csv"
    counts: dict[str, int] = {}
    buckets: dict[str, list[dict]] = {}
    chosen = None
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle)
        reader.fieldnames = [name.strip() for name in (reader.fieldnames or [])]
        for row in reader:
            origin = row["nameOrig"]
            counts[origin] = counts.get(origin, 0) + 1
            count = counts[origin]
            if count > 8:
                buckets.pop(origin, None)
                continue
            buckets.setdefault(origin, []).append(row)
            if flag(row.get("isFraud", 0)) and count >= 2:
                chosen = origin
                break
    if chosen is None:
        return {"status": "no_short_history_fraud_found"}
    rows = buckets[chosen]
    current = adapt_paysim(rows[-1])
    history = [adapt_paysim(row) for row in rows[:-1]]
    request = {
        "data_origin": "REAL_PUBLIC_DATA",
        "source_kind": "synthetic_simulated",
        "source_dataset": "paysim",
        "note": "Public PaySim simulator rows for this account up to and including the fraud row. PaySim is synthetic mobile money, not a real bank ledger. Currency USD is the documented assumption. This is not a Tunisian bank transaction.",
        "transaction": current.model_dump(mode="json"),
        "history": [item.model_dump(mode="json") for item in history],
        "entities": [],
    }
    _write_json(EVAL / "demo_paysim_request.json", request)
    from fraud_detection.models.general_behavior import GeneralBehavior

    supervised = SupervisedDetector.load(ARTIFACTS / "supervised.joblib")
    anomaly_path = ARTIFACTS / "anomaly.joblib"
    anomaly = PopulationAnomaly.load(anomaly_path) if anomaly_path.exists() else None
    sanctions_path = ARTIFACTS / "sanctions.joblib"
    sanctions = joblib.load(sanctions_path) if sanctions_path.exists() else None
    if not isinstance(sanctions, SanctionsIndex):
        sanctions = SanctionsIndex([])
    general_path = ARTIFACTS / "general_behavior.joblib"
    general = GeneralBehavior.load(general_path) if general_path.exists() else None
    engine = FraudDetectionEngine(
        supervised=supervised,
        sanctions=sanctions,
        population_anomaly=anomaly,
        general_behavior=general,
    )
    assessment = engine.score(current, history)
    _write_json(EVAL / "demo_paysim_response.json", assessment.model_dump(mode="json"))
    return {
        "transaction_id": current.transaction_id,
        "history_rows": len(history),
        "risk_score": assessment.risk_score,
        "decision": assessment.decision.value,
        "label_types": assessment.label_types,
        "supervised": assessment.model_scores.supervised,
        "supervised_by_type": assessment.model_scores.supervised_by_type,
        "anomaly": assessment.model_scores.anomaly,
        "sanctions_status": assessment.external_checks.sanctions_status,
        "risk_score_meaning": "0-100 deterministic evidence aggregation policy, not a fraud probability",
    }


def _file_record(path: Path) -> dict:
    if not path.exists():
        return {"path": str(path.relative_to(ROOT)), "present": False}
    return {"path": str(path.relative_to(ROOT)), "present": True, "bytes": path.stat().st_size}


def write_reports(results: dict) -> None:
    _write_json(EVAL / "metrics.json", results)
    metadata = {
        "behavioral_model": "fraud_detection/models/artifacts/supervised.joblib",
        "anomaly_model": "fraud_detection/models/artifacts/anomaly.joblib",
        "sanctions_index": "fraud_detection/models/artifacts/sanctions.joblib",
        "ulb_specialist_used_when_pca_present": "fraud_detection/models/artifacts/ulb_card.joblib",
        "general_behavior_model": "fraud_detection/models/artifacts/general_behavior.joblib",
        "specialists_not_used_by_api": [
            "fraud_detection/models/artifacts/elliptic_aml.joblib",
        ],
        "feature_names": list(FEATURE_NAMES),
        "label_map": {
            "CARD_FRAUD": "banksim",
            "AML_LAUNDERING": "ibm_aml",
            "ACCOUNT_TAKEOVER": "paysim",
        },
        "aggregation": {
            "weights": {"rules": 0.30, "supervised": 0.30, "anomaly": 0.20, "graph_if_positive": 0.20},
            "floors": {
                "rules_at_least_0.85": "max(score, 0.9 * rules)",
                "supervised_at_least_0.90": 0.75,
                "graph_at_least_0.90": 0.75,
                "two_model_components_at_least_0.80": 0.78,
                "sanctions_match": 0.80,
            },
            "levels": {"HIGH_RISK": ">= 75", "MEDIUM_RISK": ">= 45", "LOW_RISK": "< 45"},
            "meaning": "risk score from 0-100 produced by a deterministic evidence aggregation policy, not a probability of fraud",
            "type_gate": "schema only, not dataset name: CARD_FRAUD for card or ULB PCA inputs; ACCOUNT_TAKEOVER for mobile-money, device, or balance-drain inputs; AML_LAUNDERING for transfers and AML payment formats",
            "supervised_floor": "0.75 only when data coverage is HIGH and the eligible calibrated specialist score is at least 0.90",
        },
    }
    _write_json(ARTIFACTS / "metadata.json", metadata)
    (EVAL / "MODEL_EVALUATION.md").write_text(_evaluation_markdown(results))
    (ROOT / "DATA_SOURCES.md").write_text(_sources_markdown(results))


def _fmt_metrics(metrics: dict) -> str:
    if not metrics or metrics.get("error") or metrics.get("note"):
        return json.dumps(_sanitize(metrics), indent=2)
    keys = [
        "test_rows",
        "test_positives",
        "pr_auc",
        "roc_auc",
        "precision",
        "recall",
        "f1",
        "false_positive_rate",
        "tn",
        "fp",
        "fn",
        "tp",
        "precision_at_k",
        "recall_at_k",
        "precision_at_positive_count",
        "recall_at_positive_count",
        "threshold",
        "top_k",
    ]
    lines = ["| metric | value |", "| --- | --- |"]
    for key in keys:
        if key in metrics:
            value = metrics[key]
            if isinstance(value, float):
                value = f"{value:.6f}"
            lines.append(f"| {key} | {value} |")
    return "\n".join(lines)


def _evaluation_markdown(results: dict) -> str:
    behavioral = results.get("behavioral", {})
    by_type = behavioral.get("by_type", {})
    parts = [
        "# Model evaluation",
        "",
        "The system is trained and evaluated on multiple public datasets, including real anonymized transactions and large synthetic/simulated financial datasets.",
        "BankSim, PaySim, and IBM AML HI-Small are synthetic or simulated. They are not a bank's real ledger, and this model was not trained on millions of real bank transactions.",
        "ULB is the real-anonymized card exception. Elliptic is a real Bitcoin transaction graph, not bank payments.",
        "These numbers were produced by `python -m fraud_detection.train_real` on this machine.",
        "The behavioral API model is three LightGBM heads. Each head is trained only on the dataset whose label means that fraud type, and at scoring time that head runs only when the input matches the same family.",
        "Validation and test rows are later time periods and include every row from that period.",
        "PaySim and IBM training negatives are a reservoir of 180,000 rows, seed 0, drawn from the training period after features were computed on the full stream.",
        "BankSim training keeps every row.",
        "The decision threshold for precision, recall, F1, and the confusion matrix is 0.50 on the calibrated score when an isotonic calibrator was fit.",
        "Prevalence, Brier score, calibration, the validation threshold sweep, and the validation-only LightGBM comparison are in `fraud_detection/evaluation/operating_points.json` when that file exists. Candidates are compared on the validation tail. The test set is not used to choose one.",
        "The headline behavioral result is IBM AML. PaySim's near-perfect scores are a real measurement of an easy simulator and are not the headline.",
        "`risk_score` is a risk score from 0-100 produced by a deterministic evidence aggregation policy. It is not the probability of fraud.",
        "",
    ]
    order = ["AML_LAUNDERING", "CARD_FRAUD", "ACCOUNT_TAKEOVER"]
    labels = [name for name in order if name in by_type] + [name for name in by_type if name not in order]
    notes = {
        "AML_LAUNDERING": "Headline result. The source is synthetic AMLSim data and the positive rate is tiny, so cite PR-AUC and precision at 100.",
        "CARD_FRAUD": "Synthetic BankSim bank-payment simulator. Respectable for a demo. The real anonymized card result is the ULB specialist.",
        "ACCOUNT_TAKEOVER": "Synthetic PaySim mobile money. Not the headline. Near-perfect scores come from simulator balance-drain features.",
    }
    for label in labels:
        metrics = by_type[label]
        parts.append(f"## {label}")
        parts.append("")
        parts.append(f"Dataset: `{metrics.get('dataset')}`. Calibration: {metrics.get('calibration')}.")
        if label in notes:
            parts.append(notes[label])
        parts.append("")
        parts.append(_fmt_metrics(metrics))
        parts.append("")
        if metrics.get("top_features"):
            parts.append("Largest LightGBM split gains:")
            parts.append("")
            for item in metrics["top_features"]:
                parts.append(f"- `{item['feature']}`: {item['gain']}")
            parts.append("")
    anomaly = behavioral.get("anomaly", {})
    parts.extend(["## Population isolation forest", "", "```json", json.dumps(_sanitize(anomaly), indent=2), "```", ""])
    for name in ("ulb", "elliptic", "elliptic_graph", "ibm_graph", "ibm_cycles", "saml_d", "sanctions", "demo"):
        if name in results:
            parts.extend([f"## {name}", "", "```json", json.dumps(_sanitize(results[name]), indent=2), "```", ""])
    if results.get("errors"):
        parts.extend(["## Errors recorded while finishing optional steps", "", "```json", json.dumps(results["errors"], indent=2), "```", ""])
    parts.extend(
        [
            "## Limitations",
            "",
            "- The API behavioral model was trained on three public simulators: BankSim, IBM AML HI-Small, and PaySim. It was not trained on millions of real bank transactions. ULB and Elliptic specialists are not loaded by `/v1/score`.",
            "- SAML-D, TabFormer, the Fraud Detection Handbook simulator, IEEE-CIS, CTAF extracts, and Tunisian registry microdata were not fitting data for these heads.",
            "- A supervised head scores an input only when that input matches its family. A PaySim cash-out cannot receive CARD_FRAUD from the BankSim head.",
            "- Streaming features keep hourly buckets for seven days, cap unique counterparties at 48, and drop accounts idle for eight days. Scoring uses the same class, so the approximation is shared by training and the API.",
            "- PaySim has no currency or country. USD is an assumption and country is empty, so `is_tnd` is 0. Its near-perfect metrics are not the headline.",
            "- BankSim has no currency or country. EUR is an assumption, the clock is fixed at 12:00, and the age field is not used as account age. It is a synthetic bank-payment simulator.",
            "- IBM AML transactions are synthetically generated by AMLSim.",
            "- Synthetic Tunisia scenarios are regression tests. They are not real Tunisian bank transactions and they are not in this training run.",
            "- risk_score is a policy score from 0-100, not P(fraud).",
            "- A sanctions miss is returned only when a list is loaded. An empty index returns `sanctions_status=not_available`.",
            "",
        ]
    )
    return "\n".join(parts)


def _sources_markdown(results: dict) -> str:
    files = [
        RAW / "ulb" / "creditcard.csv",
        RAW / "ibm_aml" / "HI-Small_Trans.csv",
        RAW / "paysim" / "paysim.csv",
        RAW / "banksim" / "bs140513_032310.csv",
        RAW / "saml_d" / "SAML-D.zip",
        RAW / "elliptic" / "elliptic_txs_classes.csv",
        RAW / "elliptic" / "elliptic_txs_edgelist.csv",
        RAW / "elliptic" / "elliptic_txs_features.csv",
        RAW / "sanctions" / "ofac_sdn.csv",
        RAW / "sanctions" / "ofac_alt.csv",
        RAW / "sanctions" / "un_consolidated.xml",
        RAW / "sanctions" / "eu_sanctions.csv",
    ]
    lines = [
        "# Data sources",
        "",
        "The system is trained and evaluated on multiple public datasets, including real anonymized transactions and large synthetic/simulated financial datasets. It was not trained on millions of real bank transactions.",
        "",
        "Raw files stay on disk and are gitignored. This note records what was actually downloaded and how it was used. `data_origin=REAL_PUBLIC_DATA` means the file is a public download, not that the rows are a real bank ledger.",
        "",
        "| file | bytes |",
        "| --- | ---: |",
    ]
    for path in files:
        record = _file_record(path)
        lines.append(f"| `{record['path']}` | {record.get('bytes', 'missing')} |")
    lines.extend(
        [
            "",
            "## Used to train the API behavioral model",
            "",
            "- **BankSim** `bs140513_032310.csv`, from the Hugging Face mirror `LordNR/AMLGraphX-Banksim` (zip `Banksim.zip`). Synthetic bank-payment simulator, not a real card ledger. The mirror is marked CC BY-NC-SA 4.0. Academic/demo use. Mapped to `CARD_FRAUD`. Currency EUR and a 12:00 timestamp are assumptions; country is empty. Age bins are not account age. `source_kind=synthetic_simulated`.",
            "- **IBM AML HI-Small** `HI-Small_Trans.csv`, from the Hugging Face mirror `bbfizp/AMLSim-HI-Small`. Synthetically generated by AMLSim, not a real bank ledger. Community Data License Agreement Sharing 1.0 (CDLA-Sharing-1.0). Mapped to `AML_LAUNDERING`. Headline behavioral result. The file was externally sorted by timestamp before features were built. Sender is `From Bank:Account` and receiver is `To Bank:second Account column`. `source_kind=synthetic_simulated`.",
            "- **PaySim** `paysim.csv`, from the Hugging Face mirror `theman10/paysim`. Synthetic mobile-money simulator. The original PaySim release is CC BY-SA 4.0. Mapped to `ACCOUNT_TAKEOVER`. Near-perfect metrics are not the headline. The file has no currency; USD is an assumption. Country is empty. Step 0 starts at 2020-01-01, which is a clock for the simulator hour, not a date stored in the file. `source_kind=synthetic_simulated`.",
            "",
            "## Trained as separate specialists, not loaded by `/v1/score`",
            "",
            "- **ULB credit card** `creditcard.csv` from the TensorFlow public mirror of the ULB/Worldline Kaggle set (Open Database License). Real anonymized European card transactions (284,807 rows). Not mixed into the BankSim head. Time-ordered split. Features are `V1`–`V28` and `Amount`. `Time` is the split key and is not a model input. `source_kind=real_anonymized`.",
            "- **Elliptic** classes, edgelist, and features from the Hugging Face mirrors `SuodhanJ6/elliptic_txs_*`. Real Bitcoin transaction graph, not bank payments. Research release with anonymized features. Unknown class rows are excluded from supervised training. Timestep split: 1–34 train, 35–39 validation, 40–49 test. The edgelist is used for the graph report. `source_kind=real_cryptocurrency_graph`.",
            "",
            "## Downloaded and validated, not used to fit the API model",
            "",
            "- **SAML-D** zip from `LordNR/AMLGraphX-SAML-D`, CC BY-NC-SA 4.0. Synthetic simulator. See the SAML section of the evaluation report for the measured row count. It was not mixed into the IBM AML head. `source_kind=synthetic_simulated`.",
            "",
            "## Loaded for entity checks",
            "",
            "- **OFAC SDN and ALT**, US Treasury public lists.",
            "- **UN Security Council consolidated XML** from `scsanctions.un.org`, generated date in the file.",
            "- **EU consolidated sanctions CSV** from the public Financial Sanctions Database endpoint. The `token-2017` value is the published public token.",
            "",
            "## Not downloaded",
            "",
            "- **IEEE-CIS**: Kaggle competition access was not used.",
            "- **IBM TabFormer**: no direct public transaction file; the publisher uses a request form.",
            "- **Fraud Detection Handbook simulator**: not executed in this run.",
            "- **OpenSanctions bulk data**: not downloaded. OFAC, UN, and EU lists are the screening sources.",
            "- **CTAF reports and Tunisian RNE microdata**: see the probe result below. No file from those probes was used as training labels. Synthetic Tunisia scenarios in `fraud_detection/data/synthetic_tunisia.py` are `SYNTHETIC_TUNISIAN_SCENARIO` regression tests, not real bank data.",
            "",
            "## Optional-source probes from this run",
            "",
            "```json",
            json.dumps(_sanitize(results.get("optional_sources", {})), indent=2),
            "```",
            "",
            "## Reproduce",
            "",
            "```bash",
            "bash scripts/download_public_data.sh",
            ".venv/bin/python -m fraud_detection train",
            ".venv/bin/pytest",
            ".venv/bin/python -m fraud_detection serve",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    EVAL.mkdir(parents=True, exist_ok=True)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    results: dict = {"errors": {}}
    results["optional_sources"] = probe_optional_sources()
    prepared = {}
    for name, _label, npz, builder in BEHAVIORAL:
        try:
            prepared[name] = _prepare(name, npz, builder)
        except Exception as exc:
            results["errors"][name] = traceback.format_exc()
            print(f"prepare failed for {name}: {exc}", flush=True)
            write_reports(results)
            raise
    results["prepared"] = prepared
    results["behavioral"] = train_behavioral(prepared)
    write_reports(results)
    try:
        results["ibm_cycles"] = ibm_cycles()
        prepare_graph = prepared.get("ibm_aml", {}).get("graph")
        if prepare_graph:
            results["ibm_graph"] = prepare_graph
    except Exception:
        results["errors"]["ibm_cycles"] = traceback.format_exc()
    for key, function in (
        ("ulb", train_ulb),
        ("elliptic", train_elliptic),
        ("elliptic_graph", elliptic_graph),
        ("sanctions", build_sanctions),
        ("saml_d", validate_saml),
        ("demo", write_paysim_demo),
    ):
        try:
            print(f"step {key}", flush=True)
            results[key] = function()
            gc.collect()
        except Exception:
            results["errors"][key] = traceback.format_exc()
            print(results["errors"][key], flush=True)
    write_reports(results)
    print("training finished", flush=True)


if __name__ == "__main__":
    main()
