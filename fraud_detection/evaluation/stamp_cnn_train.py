"""Fine-tune ResNet-18 on training identities. Validation picks the checkpoint.

Test identities are not opened. The threshold is stored with the checkpoint
and is not refit later.

    .venv/bin/python -m fraud_detection.evaluation.stamp_cnn_train
"""

from __future__ import annotations

import json
import random

import numpy as np

from fraud_detection.documents.stamp_cnn import (
    CHECKPOINT,
    INPUT_SIZE,
    MODEL_NAME,
    MODEL_VERSION,
    SEED,
    TARGET_FPR,
    assert_identity_split,
    average_precision,
    decision_counts,
    iter_prepared,
    load_manifest,
    score_rows,
    thresholds_from_scores,
)
from fraud_detection.paths import EVAL

CONFIG_PATH = EVAL / "stamp_cnn_config.json"
VAL_SCORES = EVAL / "stamp_cnn_val_scores.csv"
MAX_EPOCHS = 8
PATIENCE = 2
BATCH_SIZE = 32
LEARNING_RATE = 3e-4


def _device() -> str:
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def _loader_batches(rows: list[dict], epoch: int, device: str):
    import torch

    tensors = []
    labels = []
    for tensor, label in iter_prepared(rows, SEED, epoch, augment=True):
        tensors.append(tensor)
        labels.append(label)
        if len(tensors) == BATCH_SIZE:
            yield torch.stack(tensors).to(device), torch.tensor(labels, dtype=torch.long, device=device)
            tensors = []
            labels = []
    if tensors:
        yield torch.stack(tensors).to(device), torch.tensor(labels, dtype=torch.long, device=device)


def main() -> None:
    import torch

    torch.manual_seed(SEED)
    np.random.seed(SEED)
    device = _device()
    rows = load_manifest()
    assert_identity_split(rows)
    train_rows = [row for row in rows if row["split"] == "train"]
    val_rows = [row for row in rows if row["split"] == "val"]
    if any(row["split"] == "test" for row in train_rows + val_rows):
        raise RuntimeError("test identities entered training")
    genuine = sum(row["kind"] != "counterfeit" for row in train_rows)
    counterfeit = sum(row["kind"] == "counterfeit" for row in train_rows)
    print(
        f"device {device} train {len(train_rows)} (genuine {genuine}, counterfeit {counterfeit}) val {len(val_rows)}",
        flush=True,
    )

    from fraud_detection.documents.stamp_cnn import build_model

    model = build_model(pretrained=True).to(device)
    total = genuine + counterfeit
    weights = torch.tensor(
        [total / (2 * genuine), total / (2 * counterfeit)],
        dtype=torch.float32,
        device=device,
    )
    criterion = torch.nn.CrossEntropyLoss(weight=weights)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=1e-4)

    best_ap = -1.0
    best_state = None
    stale = 0
    history = []
    for epoch in range(MAX_EPOCHS):
        model.train()
        seen = 0
        loss_sum = 0.0
        order = list(train_rows)
        random.Random(SEED + epoch).shuffle(order)
        for batch, target in _loader_batches(order, epoch, device):
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(batch), target)
            loss.backward()
            optimizer.step()
            seen += int(target.shape[0])
            loss_sum += float(loss.detach().cpu()) * int(target.shape[0])
        labels, scores = score_rows(model, val_rows, device=device, batch_size=BATCH_SIZE)
        ap = average_precision(labels, scores)
        history.append({"epoch": epoch, "train_loss": loss_sum / max(1, seen), "val_average_precision": ap})
        print(
            f"epoch {epoch} loss {history[-1]['train_loss']:.4f} val_pr_auc {ap:.4f}",
            flush=True,
        )
        if ap is not None and ap > best_ap + 1e-4:
            best_ap = ap
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= PATIENCE:
                print("early stop", flush=True)
                break

    if best_state is None:
        raise RuntimeError("no validation checkpoint")
    model.load_state_dict(best_state)
    labels, scores = score_rows(model, val_rows, device=device, batch_size=BATCH_SIZE)
    high, low = thresholds_from_scores(scores[labels == 0], scores[labels == 1], TARGET_FPR)
    counts = decision_counts(labels, scores, low, high)
    payload = {
        "state_dict": best_state,
        "model": MODEL_NAME,
        "version": MODEL_VERSION,
        "seed": SEED,
        "input_size": INPUT_SIZE,
        "learning_rate": LEARNING_RATE,
        "max_epochs": MAX_EPOCHS,
        "patience": PATIENCE,
        "epochs_ran": len(history),
        "target_fpr": TARGET_FPR,
        "threshold_high": high,
        "threshold_low": low,
        "val_average_precision": best_ap,
        "val_counts": counts,
        "history": history,
        "class_weight_genuine": float(weights[0].cpu()),
        "class_weight_counterfeit": float(weights[1].cpu()),
        "score_is_calibrated_probability": False,
        "test_identities_used_for_training_or_thresholds": False,
    }
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, CHECKPOINT)
    CONFIG_PATH.write_text(json.dumps({key: value for key, value in payload.items() if key != "state_dict"}, indent=2))
    with VAL_SCORES.open("w", encoding="utf-8") as handle:
        handle.write("id,score,label\n")
        for row, score, label in zip(val_rows, scores, labels):
            handle.write(f"{row['id']},{score:.6f},{int(label)}\n")
    print(
        f"saved {CHECKPOINT} t_hi {high:.4f} t_lo {low:.4f} val recall {counts['recall_count']} "
        f"false-fraud {counts['false_fraud_count']} false-accept {counts['false_accept_count']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
