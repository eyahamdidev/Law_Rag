from __future__ import annotations

import heapq
import math

BUCKETS = 32


def amount_bucket(amount: float) -> int:
    if amount <= 1:
        return 0
    if amount >= 1e8:
        return BUCKETS - 1
    scaled = int(math.log10(amount) * 4)
    return min(BUCKETS - 1, max(0, scaled))


def amount_percentile(amounts: list[float], current: float) -> float:
    if not amounts:
        return 0.5
    counts = [0] * BUCKETS
    for amount in amounts:
        counts[amount_bucket(amount)] += 1
    return percentile_from_counts(counts, current)


def percentile_from_counts(counts: list[int], current: float) -> float:
    total = sum(counts)
    if total <= 0:
        return 0.5
    bucket = amount_bucket(current)
    below = sum(counts[:bucket])
    return float((below + 0.5 * counts[bucket]) / total)


def median_of(amounts: list[float]) -> float:
    tracker = RunningMedian()
    for amount in amounts:
        tracker.add(amount)
    return tracker.median()


def amount_to_old_balance(old_balance: float | None, amount: float) -> float:
    if old_balance is None or old_balance <= 0:
        return 0.0
    return float(min(50.0, amount / old_balance))


def balance_zeroed_flag(old_balance: float | None, new_balance: float | None) -> float:
    if old_balance is None or new_balance is None:
        return 0.0
    if old_balance > 0 and new_balance == 0:
        return 1.0
    return 0.0


def balance_mismatch_flag(old_balance: float | None, new_balance: float | None, amount: float) -> float:
    if old_balance is None or new_balance is None:
        return 0.0
    tolerance = max(1.0, 0.01 * amount)
    if abs(new_balance - (old_balance - amount)) <= tolerance:
        return 0.0
    if abs(new_balance - (old_balance + amount)) <= tolerance:
        return 0.0
    return 1.0


class RunningMedian:
    """Exact median. Even counts use the mean of the two central values."""

    def __init__(self) -> None:
        self._low: list[float] = []
        self._high: list[float] = []

    def add(self, value: float) -> None:
        if not self._low or value <= -self._low[0]:
            heapq.heappush(self._low, -value)
        else:
            heapq.heappush(self._high, value)
        if len(self._low) > len(self._high) + 1:
            heapq.heappush(self._high, -heapq.heappop(self._low))
        elif len(self._high) > len(self._low):
            heapq.heappush(self._low, -heapq.heappop(self._high))

    def median(self) -> float:
        if not self._low:
            return 0.0
        if len(self._low) == len(self._high):
            return float((-self._low[0] + self._high[0]) / 2.0)
        return float(-self._low[0])
