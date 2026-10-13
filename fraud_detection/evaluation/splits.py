from __future__ import annotations

from datetime import datetime

import numpy as np


def temporal_masks(
    timestamps: list[datetime],
    train_end: datetime,
    validation_end: datetime,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Train, then validate, then test. Boundaries are exclusive of the next slice."""
    times = np.asarray(timestamps)
    train = np.asarray([item < train_end for item in times])
    validation = np.asarray([(train_end <= item < validation_end) for item in times])
    test = np.asarray([item >= validation_end for item in times])
    return train, validation, test


def assert_time_order(timestamps: list[datetime], train: np.ndarray, validation: np.ndarray, test: np.ndarray) -> None:
    times = np.asarray(timestamps)
    if train.any() and validation.any() and times[train].max() >= times[validation].min():
        raise AssertionError("training rows overlap or follow the validation window")
    if validation.any() and test.any() and times[validation].max() >= times[test].min():
        raise AssertionError("validation rows overlap or follow the test window")
    if train.any() and test.any() and times[train].max() >= times[test].min():
        raise AssertionError("training rows overlap or follow the test window")


def holdout_entities(
    entity_ids: list[str],
    test_fraction: float = 0.2,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Hold out entire entities so the test set contains no account seen in training."""
    if not 0 < test_fraction < 1:
        raise ValueError("test_fraction must be between 0 and 1")
    unique = sorted(set(entity_ids))
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(unique))
    holdout_count = max(1, int(round(len(unique) * test_fraction)))
    held = {unique[index] for index in order[:holdout_count]}
    test = np.asarray([entity in held for entity in entity_ids])
    train = ~test
    return train, test
