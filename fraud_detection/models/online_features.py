"""Incremental behavioral features with a bounded memory footprint.

Account state keeps hourly count and sum buckets for at most seven days, a
32-bin amount histogram, and at most 48 recent counterparties. Idle accounts
are dropped after eight days. The new-counterparty flag uses a fixed-size
Bloom filter. These approximations are identical at training and scoring time
because both paths use this class.
"""

from __future__ import annotations

from array import array
from datetime import datetime

from fraud_detection.models.feature_stats import (
    amount_bucket,
    amount_to_old_balance,
    balance_mismatch_flag,
    balance_zeroed_flag,
    percentile_from_counts,
)
from fraud_detection.models.features import FEATURE_NAMES
from fraud_detection.normalize import country_code, local_hour
from fraud_detection.schema import Transaction

_HOUR_NS = 3_600_000_000_000
_EPOCH = datetime(1970, 1, 1)
_PARTY_CAP = 48
_REPEAT_CAP = 48
_ACCOUNT_CAP = 400_000
_BLOOM_BITS = 1 << 28


def timestamp_ns(value: datetime) -> int:
    """Nanoseconds for a civil timestamp. Naive values are not shifted into local time."""
    if value.tzinfo is not None:
        value = value.replace(tzinfo=None)
    delta = value - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000


def stable_hash(value: str) -> int:
    hashed = 14695981039346656037
    for byte in value.encode():
        hashed ^= byte
        hashed = (hashed * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return hashed


def _bucket_representative(index: int) -> float:
    if index <= 0:
        return 1.0
    return float(10 ** (index / 4))


def _median_from_counts(counts) -> float:
    total = sum(counts)
    if total <= 0:
        return 0.0
    need = (total + 1) / 2
    running = 0
    for index, count in enumerate(counts):
        running += count
        if running >= need:
            return _bucket_representative(index)
    return 0.0


class _Bloom:
    def __init__(self) -> None:
        self.bits = _BLOOM_BITS
        self.data = bytearray(self.bits // 8)

    def seen_then_add(self, left: int, right: int) -> bool:
        present = True
        mixed = (left + 0x9E3779B97F4A7C15 * (right + 1)) & 0xFFFFFFFFFFFFFFFF
        for salt in (0xBF58476D1CE4E5B9, 0x94D049BB133111EB, 0xD6E8FEB86659FD93):
            mixed = (mixed * salt) & 0xFFFFFFFFFFFFFFFF
            index = mixed % self.bits
            byte = index >> 3
            mask = 1 << (index & 7)
            if not self.data[byte] & mask:
                present = False
                self.data[byte] |= mask
        return present


class _Acc:
    __slots__ = (
        "last_out_ns",
        "last_in_ns",
        "hist",
        "out_hours",
        "in_hours",
        "out_parties",
        "in_parties",
        "repeats",
    )

    def __init__(self) -> None:
        self.last_out_ns = 0
        self.last_in_ns = 0
        self.hist = array("I", [0] * 32)
        self.out_hours: dict[int, tuple[int, float]] = {}
        self.in_hours: dict[int, tuple[int, float]] = {}
        self.out_parties: dict[int, int] = {}
        self.in_parties: dict[int, int] = {}
        self.repeats: dict[tuple[int, int], tuple[int, int]] = {}


def _window(hours: dict[int, tuple[int, float]], hour_id: int, span: int) -> tuple[int, float]:
    cutoff = hour_id - span + 1
    count = 0
    total = 0.0
    for key, (item_count, item_sum) in hours.items():
        if cutoff <= key <= hour_id:
            count += item_count
            total += item_sum
    return count, total


def _drop_old(hours: dict, hour_id: int, keep: int) -> None:
    cutoff = hour_id - keep
    stale = [key for key in hours if key < cutoff]
    for key in stale:
        del hours[key]


def _purge(parties: dict[int, int], hour_id: int, span: int) -> int:
    cutoff = hour_id - span + 1
    stale = [key for key, seen in parties.items() if seen < cutoff]
    for key in stale:
        del parties[key]
    return len(parties)


def _remember(parties: dict[int, int], party: int, hour_id: int, span: int) -> None:
    _purge(parties, hour_id, span)
    parties[party] = hour_id
    if len(parties) > _PARTY_CAP:
        oldest = min(parties, key=parties.get)
        if oldest != party:
            del parties[oldest]


class OnlineFeatures:
    """Call rows in timestamp order."""

    def __init__(self) -> None:
        self._accounts: dict[int, _Acc] = {}
        self._bloom = _Bloom()
        self._seen_rows = 0

    def stats(self) -> dict[str, int]:
        return {"accounts": len(self._accounts)}

    def transform_transaction(self, transaction: Transaction) -> list[float]:
        return self.push(
            ts_ns=timestamp_ns(transaction.timestamp),
            hour=local_hour(transaction.timestamp),
            amount=float(transaction.amount),
            sender=transaction.sender_id,
            receiver=transaction.receiver_id,
            currency=transaction.currency or "",
            country_from=transaction.country_from,
            country_to=transaction.country_to,
            channel=transaction.channel,
            old_balance=transaction.old_balance,
            new_balance=transaction.new_balance,
            company_age_days=transaction.company_age_days,
            declared_annual_revenue=transaction.declared_annual_revenue,
            bid_count=transaction.bid_count,
            award_ratio=transaction.award_to_estimate_ratio,
            has_invoice=bool(transaction.invoice_id),
            has_expense=bool(transaction.expense_id),
        )

    def push(
        self,
        *,
        ts_ns: int,
        hour: int,
        amount: float,
        sender: str,
        receiver: str,
        currency: str,
        country_from: str | None,
        country_to: str | None,
        channel: str | None,
        old_balance: float | None,
        new_balance: float | None,
        company_age_days: int | None,
        declared_annual_revenue: float | None,
        bid_count: int | None,
        award_ratio: float | None,
        has_invoice: bool,
        has_expense: bool,
    ) -> list[float]:
        sender_id = stable_hash(sender)
        receiver_id = stable_hash(receiver)
        hour_id = ts_ns // _HOUR_NS
        rounded = int(round(amount))
        sender_acc = self._account(sender_id)
        vector = self._vector(
            sender_acc=sender_acc,
            ts_ns=ts_ns,
            hour=hour,
            hour_id=hour_id,
            amount=amount,
            sender_id=sender_id,
            receiver_id=receiver_id,
            rounded=rounded,
            currency=currency,
            country_from=country_from,
            country_to=country_to,
            channel=channel,
            old_balance=old_balance,
            new_balance=new_balance,
            company_age_days=company_age_days,
            declared_annual_revenue=declared_annual_revenue,
            bid_count=bid_count,
            award_ratio=award_ratio,
            has_invoice=has_invoice,
            has_expense=has_expense,
        )
        self._observe(sender_acc, sender_id, receiver_id, ts_ns, hour_id, amount, rounded)
        self._seen_rows += 1
        if self._seen_rows % 200_000 == 0:
            self._evict(ts_ns)
        return vector

    def _account(self, code: int) -> _Acc:
        found = self._accounts.get(code)
        if found is None:
            found = _Acc()
            self._accounts[code] = found
        return found

    def _vector(self, **item) -> list[float]:
        sender_acc: _Acc = item["sender_acc"]
        hour_id = item["hour_id"]
        amount = item["amount"]
        out_1h = _window(sender_acc.out_hours, hour_id, 1)
        out_24 = _window(sender_acc.out_hours, hour_id, 24)
        out_7 = _window(sender_acc.out_hours, hour_id, 168)
        in_6 = _window(sender_acc.in_hours, hour_id, 6)
        in_24 = _window(sender_acc.in_hours, hour_id, 24)
        out_parties = _purge(sender_acc.out_parties, hour_id, 24)
        in_parties = _purge(sender_acc.in_parties, hour_id, 24)
        source = country_code(item["country_from"])
        destination = country_code(item["country_to"])
        hour = item["hour"]
        last = sender_acc.last_out_ns
        hours_since = 720.0 if last == 0 else min(720.0, (item["ts_ns"] - last) / _HOUR_NS)
        typical = _median_from_counts(sender_acc.hist)
        revenue = item["declared_annual_revenue"] or 0.0
        monthly = revenue / 12 if revenue else 0.0
        age = float(item["company_age_days"]) if item["company_age_days"] is not None else -1.0
        repeat = self._repeat_count(sender_acc, item["receiver_id"], item["rounded"], hour_id)
        seen_before = self._bloom.seen_then_add(item["sender_id"], item["receiver_id"])
        values = {
            "log_amount": math_log1p(amount),
            "amount": float(amount),
            "hour": float(hour),
            "is_night": 1.0 if hour >= 23 or hour <= 5 else 0.0,
            "is_round_1000": 1.0 if amount >= 1000 and abs(amount % 1000) <= 1e-6 else 0.0,
            "is_cross_border": 1.0 if source and destination and source != destination else 0.0,
            "out_count_1h": float(out_1h[0]),
            "out_count_24h": float(out_24[0]),
            "out_sum_24h": float(out_24[1]),
            "in_count_24h": float(in_24[0]),
            "in_sum_24h": float(in_24[1]),
            "unique_in_counterparties_24h": float(in_parties),
            "unique_out_counterparties_24h": float(out_parties),
            "is_new_counterparty": 0.0 if seen_before else 1.0,
            "repeat_same_amount_72h": float(repeat),
            "hours_since_prev": float(hours_since),
            "account_age_days": age,
            "amount_over_monthly_revenue": float(amount / monthly) if monthly > 0 else 0.0,
            "is_foreign_receiver": 1.0 if destination not in (None, "TN") else 0.0,
            "is_tnd": 1.0 if item["currency"].upper() == "TND" else 0.0,
            "in_out_ratio_6h": float(min(5.0, amount / in_6[1])) if in_6[1] > 0 else 0.0,
            "bid_count": float(item["bid_count"] or 0),
            "award_to_estimate_ratio": float(item["award_ratio"] or 0),
            "is_card": 1.0 if (item["channel"] or "").lower() in {"card", "pos", "foreign_card"} else 0.0,
            "has_invoice": 1.0 if item["has_invoice"] else 0.0,
            "has_expense": 1.0 if item["has_expense"] else 0.0,
            "amount_vs_median": float(amount / typical) if typical else 1.0,
            "amount_percentile": percentile_from_counts(list(sender_acc.hist), amount),
            "out_count_7d": float(out_7[0]),
            "balance_mismatch": balance_mismatch_flag(item["old_balance"], item["new_balance"], amount),
            "amount_to_old_balance": amount_to_old_balance(item["old_balance"], amount),
            "balance_zeroed": balance_zeroed_flag(item["old_balance"], item["new_balance"]),
        }
        return [values[name] for name in FEATURE_NAMES]

    def _repeat_count(self, sender_acc: _Acc, party: int, rounded: int, hour_id: int) -> int:
        cutoff = hour_id - 71
        total = 0
        stale = []
        for key, (seen, count) in sender_acc.repeats.items():
            if seen < cutoff:
                stale.append(key)
                continue
            if key[0] == party and abs(key[1] - rounded) <= 1:
                total += count
        for key in stale:
            del sender_acc.repeats[key]
        return total

    def _observe(
        self,
        sender_acc: _Acc,
        sender_id: int,
        receiver_id: int,
        ts_ns: int,
        hour_id: int,
        amount: float,
        rounded: int,
    ) -> None:
        _drop_old(sender_acc.out_hours, hour_id, 168)
        count, total = sender_acc.out_hours.get(hour_id, (0, 0.0))
        sender_acc.out_hours[hour_id] = (count + 1, total + amount)
        _remember(sender_acc.out_parties, receiver_id, hour_id, 24)
        repeat_key = (receiver_id, rounded)
        seen, repeat_count = sender_acc.repeats.get(repeat_key, (hour_id, 0))
        if seen < hour_id - 71:
            repeat_count = 0
        sender_acc.repeats[repeat_key] = (hour_id, repeat_count + 1)
        if len(sender_acc.repeats) > _REPEAT_CAP:
            oldest = min(sender_acc.repeats, key=lambda key: sender_acc.repeats[key][0])
            if oldest != repeat_key:
                del sender_acc.repeats[oldest]
        sender_acc.last_out_ns = ts_ns
        sender_acc.hist[amount_bucket(amount)] += 1

        receiver_acc = self._account(receiver_id)
        _drop_old(receiver_acc.in_hours, hour_id, 24)
        in_count, in_total = receiver_acc.in_hours.get(hour_id, (0, 0.0))
        receiver_acc.in_hours[hour_id] = (in_count + 1, in_total + amount)
        _remember(receiver_acc.in_parties, sender_id, hour_id, 24)
        receiver_acc.last_in_ns = ts_ns

    def _evict(self, now_ns: int) -> None:
        cutoff = now_ns - 8 * 24 * _HOUR_NS
        stale = [
            key
            for key, account in self._accounts.items()
            if account.last_out_ns < cutoff and account.last_in_ns < cutoff
        ]
        for key in stale:
            del self._accounts[key]
        if len(self._accounts) <= _ACCOUNT_CAP:
            return
        ranked = sorted(
            self._accounts.items(),
            key=lambda item: max(item[1].last_out_ns, item[1].last_in_ns),
        )
        for key, _account in ranked[: len(self._accounts) - _ACCOUNT_CAP]:
            del self._accounts[key]


def math_log1p(value: float) -> float:
    import math

    return math.log1p(value)
