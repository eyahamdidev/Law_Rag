"""Stream public datasets into leakage-safe behavioral features.

Every row is transformed with OnlineFeatures before the sampler decides whether
to keep it. Negatives are a seeded reservoir. All positives are kept.
"""

from __future__ import annotations

import csv
import json
import random
import time
from array import array
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from fraud_detection.data.adapters.banksim_adapter import BANKSIM_ORIGIN
from fraud_detection.data.adapters.common import canonical_currency, flag, unquote
from fraud_detection.data.adapters.paysim_adapter import PAYSIM_ORIGIN
from fraud_detection.models.features import FEATURE_NAMES
from fraud_detection.models.online_features import OnlineFeatures, stable_hash, timestamp_ns
from fraud_detection.paths import EVAL, PROCESSED, RAW

NEGATIVE_CAP = 180_000
SEED = 0
FEATURE_VERSION = "hourly-v2"


class BlockStore:
    """Append-only float32 blocks. Avoids one Python array object per row."""

    def __init__(self, width: int, block: int = 100_000) -> None:
        self.width = width
        self.block = block
        self.blocks: list[np.ndarray] = []
        self.labels: list[np.ndarray] = []
        self.buf = np.zeros((block, width), dtype=np.float32)
        self.lab = np.zeros(block, dtype=np.uint8)
        self.n = 0
        self.total = 0

    def add(self, vector: list[float], label: int) -> None:
        self.buf[self.n] = vector
        self.lab[self.n] = label
        self.n += 1
        self.total += 1
        if self.n == self.block:
            self.blocks.append(self.buf)
            self.labels.append(self.lab)
            self.buf = np.zeros((self.block, self.width), dtype=np.float32)
            self.lab = np.zeros(self.block, dtype=np.uint8)
            self.n = 0

    def finalize(self) -> tuple[np.ndarray, np.ndarray]:
        if self.n:
            self.blocks.append(self.buf[: self.n].copy())
            self.labels.append(self.lab[: self.n].copy())
            self.n = 0
        if not self.blocks:
            empty_x = np.zeros((0, self.width), dtype=np.float32)
            empty_y = np.zeros(0, dtype=np.uint8)
            return empty_x, empty_y
        return np.vstack(self.blocks), np.concatenate(self.labels)


class Reservoir:
    def __init__(self, width: int, cap: int, seed: int = SEED) -> None:
        self.cap = cap
        self.rng = random.Random(seed)
        self.neg = np.zeros((cap, width), dtype=np.float32)
        self.neg_n = 0
        self.neg_seen = 0

    def add(self, vector: list[float]) -> None:
        self.neg_seen += 1
        if self.neg_n < self.cap:
            self.neg[self.neg_n] = vector
            self.neg_n += 1
            return
        slot = self.rng.randrange(self.neg_seen)
        if slot < self.cap:
            self.neg[slot] = vector

    def finalize(self) -> tuple[np.ndarray, np.ndarray]:
        features = self.neg[: self.neg_n]
        return features, np.zeros(self.neg_n, dtype=np.uint8)


def _bounds(stamps: array) -> tuple[int, int]:
    count = len(stamps)
    if count < 3:
        raise RuntimeError(f"not enough timestamps to split: {count}")
    train_end = int(stamps[int((count - 1) * 0.70)])
    val_end = int(stamps[int((count - 1) * 0.85)])
    if val_end < train_end:
        val_end = train_end
    return train_end, val_end


def _ns_to_iso(ns: int) -> str:
    return (datetime(1970, 1, 1) + timedelta(microseconds=ns / 1000)).isoformat(sep=" ")


def _scan_bounds(rows) -> tuple[int, int, int]:
    stamps = array("q")
    for item in rows:
        if item is None:
            continue
        amount, sender, receiver = item[1], item[2], item[3]
        if amount is None or amount < 0 or not sender or not receiver:
            continue
        stamps.append(timestamp_ns(item[0]))
    train_end, val_end = _bounds(stamps)
    count = len(stamps)
    return train_end, val_end, count


def _stream(
    dataset: str,
    row_factory,
    destination: Path,
    *,
    train_negative_cap: int | None,
    collect_graph: bool = False,
) -> dict:
    """Two passes. The first only reads timestamps. The second builds features.

    Validation and test keep every row. Training keeps every positive and, when
    a cap is set, a seeded reservoir of earlier negatives. Features are computed
    on the full stream before that keep decision.
    """
    train_end, val_end, scanned = _scan_bounds(row_factory())
    print(f"{dataset}: scanned {scanned} rows; train_end={_ns_to_iso(train_end)} val_end={_ns_to_iso(val_end)}", flush=True)
    width = len(FEATURE_NAMES)
    engine = OnlineFeatures()
    train_pos = BlockStore(width)
    train_neg_blocks = BlockStore(width) if train_negative_cap is None else None
    train_neg_reservoir = None if train_negative_cap is None else Reservoir(width, train_negative_cap)
    validation = BlockStore(width)
    test = BlockStore(width)
    stats = {
        "dataset": dataset,
        "rows_read": 0,
        "rows_featurized": 0,
        "positives": 0,
        "negatives_seen": 0,
        "bad_rows": 0,
        "negative_amount": 0,
        "adjacent_duplicates": 0,
        "scanned_rows": scanned,
        "train_end": _ns_to_iso(train_end),
        "validation_end": _ns_to_iso(val_end),
        "train_negative_cap": train_negative_cap,
        "reservoir_seed": SEED,
        "feature_version": FEATURE_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "split": "full-stream timestamp quantiles 70/15/15; validation and test keep every row",
    }
    out_deg: dict[str, int] = defaultdict(int)
    in_deg: dict[str, int] = defaultdict(int)
    laundering_edges: list[list[str]] = []
    previous = None
    started = time.time()
    for item in row_factory():
        stats["rows_read"] += 1
        if item is None:
            stats["bad_rows"] += 1
            continue
        ts, amount, sender, receiver, currency, country_from, country_to, channel, old_balance, new_balance, positive = item
        if amount is None or amount < 0 or not sender or not receiver:
            stats["negative_amount"] += 1
            continue
        ts_ns = timestamp_ns(ts)
        key = (sender, receiver, ts_ns, round(float(amount), 2))
        if key == previous:
            stats["adjacent_duplicates"] += 1
        previous = key
        vector = engine.push(
            ts_ns=ts_ns,
            hour=ts.hour,
            amount=float(amount),
            sender=sender,
            receiver=receiver,
            currency=currency,
            country_from=country_from,
            country_to=country_to,
            channel=channel,
            old_balance=old_balance,
            new_balance=new_balance,
            company_age_days=None,
            declared_annual_revenue=None,
            bid_count=None,
            award_ratio=None,
            has_invoice=False,
            has_expense=False,
        )
        label = 1 if positive else 0
        if ts_ns <= train_end:
            if positive:
                train_pos.add(vector, 1)
            elif train_neg_reservoir is not None:
                train_neg_reservoir.add(vector)
            else:
                train_neg_blocks.add(vector, 0)
        elif ts_ns <= val_end:
            validation.add(vector, label)
        else:
            test.add(vector, label)
        stats["rows_featurized"] += 1
        if positive:
            stats["positives"] += 1
        else:
            stats["negatives_seen"] += 1
        if collect_graph:
            out_deg[stable_hash(sender)] += 1
            in_deg[stable_hash(receiver)] += 1
            if positive:
                laundering_edges.append([sender, receiver])
        if stats["rows_featurized"] % 500_000 == 0:
            elapsed = max(1e-6, time.time() - started)
            print(
                f"{dataset}: {stats['rows_featurized']} rows "
                f"({stats['rows_featurized'] / elapsed:.0f}/s) positives={stats['positives']} "
                f"accounts={engine.stats()['accounts']}",
                flush=True,
            )
    del engine
    pos_x, pos_y = train_pos.finalize()
    if train_neg_reservoir is not None:
        neg_x, neg_y = train_neg_reservoir.finalize()
    else:
        neg_x, neg_y = train_neg_blocks.finalize()
    train_x = np.vstack([neg_x, pos_x])
    train_y = np.concatenate([neg_y, pos_y])
    val_x, val_y = validation.finalize()
    test_x, test_y = test.finalize()
    destination.parent.mkdir(parents=True, exist_ok=True)
    np.savez(destination, train_x=train_x, train_y=train_y, val_x=val_x, val_y=val_y, test_x=test_x, test_y=test_y)
    stats["train_rows"] = int(len(train_y))
    stats["train_positives"] = int(train_y.sum())
    stats["validation_rows"] = int(len(val_y))
    stats["validation_positives"] = int(val_y.sum())
    stats["test_rows"] = int(len(test_y))
    stats["test_positives"] = int(test_y.sum())
    stats["elapsed_seconds"] = round(time.time() - started, 1)
    if collect_graph:
        stats["graph"] = {
            "edges": int(stats["rows_featurized"]),
            "fan_in_at_least_10": int(sum(1 for value in in_deg.values() if value >= 10)),
            "fan_out_at_least_10": int(sum(1 for value in out_deg.values() if value >= 10)),
            "max_in_degree": int(max(in_deg.values()) if in_deg else 0),
            "max_out_degree": int(max(out_deg.values()) if out_deg else 0),
            "laundering_edges": len(laundering_edges),
        }
        (EVAL / "ibm_laundering_edges.json").write_text(json.dumps({"edges": laundering_edges}))
    sidecar = EVAL / f"{dataset}_prepare.json"
    sidecar.write_text(json.dumps(stats, indent=2))
    print(
        f"{dataset}: train {stats['train_rows']} ({stats['train_positives']} pos), "
        f"val {stats['validation_rows']} ({stats['validation_positives']} pos), "
        f"test {stats['test_rows']} ({stats['test_positives']} pos)",
        flush=True,
    )
    return stats


def _bad() -> None:
    return None


def iter_banksim(path: Path):
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle)
        required = {"step", "customer", "merchant", "amount", "fraud"}
        if reader.fieldnames is None:
            raise ValueError("BankSim file has no header")
        reader.fieldnames = [name.strip() for name in reader.fieldnames]
        if not required <= set(reader.fieldnames):
            raise ValueError(f"BankSim header missing columns: {reader.fieldnames}")
        for row in reader:
            try:
                step = int(float(unquote(row["step"])))
                amount = float(unquote(row["amount"]))
                yield (
                    BANKSIM_ORIGIN + timedelta(days=step),
                    amount,
                    unquote(row["customer"]),
                    unquote(row["merchant"]),
                    "EUR",
                    None,
                    None,
                    "card",
                    None,
                    None,
                    flag(row.get("fraud", 0)),
                )
            except (TypeError, ValueError):
                yield _bad()


def iter_paysim(path: Path):
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle)
        required = {"step", "type", "amount", "nameOrig", "nameDest", "isFraud"}
        if reader.fieldnames is None:
            raise ValueError("PaySim file has no header")
        reader.fieldnames = [name.strip() for name in reader.fieldnames]
        if not required <= set(reader.fieldnames):
            raise ValueError(f"PaySim header missing columns: {reader.fieldnames}")
        previous_step = -1
        for row in reader:
            try:
                step = int(float(row["step"]))
                if step < previous_step:
                    raise RuntimeError("PaySim steps go backwards; refuse to featurize an unsorted file")
                previous_step = step
                amount = float(row["amount"])
                old_balance = float(row["oldbalanceOrg"]) if row.get("oldbalanceOrg") not in (None, "") else None
                new_balance = float(row["newbalanceOrig"]) if row.get("newbalanceOrig") not in (None, "") else None
                yield (
                    PAYSIM_ORIGIN + timedelta(hours=step),
                    amount,
                    str(row["nameOrig"]),
                    str(row["nameDest"]),
                    "USD",
                    None,
                    None,
                    None,
                    old_balance,
                    new_balance,
                    flag(row.get("isFraud", 0)),
                )
            except RuntimeError:
                raise
            except (TypeError, ValueError):
                yield _bad()


def iter_ibm(path: Path):
    previous = ""
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if len(row) < 11:
                yield _bad()
                continue
            try:
                if row[0] < previous:
                    raise RuntimeError("IBM AML file is not time-sorted")
                previous = row[0]
                paid = row[7].strip()
                received = row[5].strip()
                amount = float(paid or received)
                payment_format = row[9]
                yield (
                    datetime.strptime(row[0], "%Y/%m/%d %H:%M"),
                    amount,
                    f"{row[1]}:{row[2]}",
                    f"{row[3]}:{row[4]}",
                    canonical_currency(row[8] or row[6]),
                    None,
                    None,
                    "card" if "card" in payment_format.lower() else None,
                    None,
                    None,
                    flag(row[10]),
                )
            except RuntimeError:
                raise
            except (TypeError, ValueError):
                yield _bad()


def featurize_banksim() -> dict:
    path = RAW / "banksim" / "bs140513_032310.csv"
    return _stream(
        "banksim",
        lambda: iter_banksim(path),
        PROCESSED / "banksim_features.npz",
        train_negative_cap=None,
    )


def featurize_paysim() -> dict:
    path = RAW / "paysim" / "paysim.csv"
    return _stream(
        "paysim",
        lambda: iter_paysim(path),
        PROCESSED / "paysim_features.npz",
        train_negative_cap=NEGATIVE_CAP,
    )


def featurize_ibm() -> dict:
    body = PROCESSED / "ibm_aml_sorted_body.csv"
    if not body.exists():
        raise FileNotFoundError(body)
    return _stream(
        "ibm_aml",
        lambda: iter_ibm(body),
        PROCESSED / "ibm_aml_features.npz",
        train_negative_cap=NEGATIVE_CAP,
        collect_graph=True,
    )
