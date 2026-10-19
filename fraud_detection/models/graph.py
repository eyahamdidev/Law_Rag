from __future__ import annotations

from collections import defaultdict

from fraud_detection.ledger import Ledger, since
from fraud_detection.schema import LabelType, Severity, Signal


def _path_back(start: str, goal: str, edges: list[tuple[str, str]], max_depth: int = 4) -> bool:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for source, destination in edges:
        if source != destination:
            adjacency[source].add(destination)
    stack = [(start, 0)]
    best_depth = {start: 0}
    while stack:
        node, depth = stack.pop()
        if depth >= max_depth:
            continue
        for nxt in adjacency.get(node, ()):
            if nxt == goal:
                return True
            nxt_depth = depth + 1
            if nxt_depth < max_depth and best_depth.get(nxt, max_depth) > nxt_depth:
                best_depth[nxt] = nxt_depth
                stack.append((nxt, nxt_depth))
    return False


def _usable(entity_id: str) -> bool:
    return bool(entity_id) and not entity_id.startswith("missing-")


def analyze_graph(ledger: Ledger) -> tuple[float, list[Signal], str]:
    """Score structure in the supplied history.

    With no earlier transactions the status is insufficient_history and the
    score is 0. The current payment alone is not treated as a graph pattern.
    """
    if not ledger.prior:
        return 0.0, [], "insufficient_history"
    current = ledger.current
    window_start = since(current.timestamp, hours=6)
    window = [
        item
        for item in ledger.all_rows
        if item.timestamp >= window_start and _usable(item.sender_id) and _usable(item.receiver_id)
    ]
    incoming: dict[str, set[str]] = defaultdict(set)
    outgoing: dict[str, set[str]] = defaultdict(set)
    inflow_sum: dict[str, float] = defaultdict(float)
    outflow_sum: dict[str, float] = defaultdict(float)
    outbound_count: dict[str, int] = defaultdict(int)
    pair_sum: dict[tuple[str, str], float] = defaultdict(float)
    edges: list[tuple[str, str]] = []
    for item in window:
        incoming[item.receiver_id].add(item.sender_id)
        outgoing[item.sender_id].add(item.receiver_id)
        inflow_sum[item.receiver_id] += item.amount
        outflow_sum[item.sender_id] += item.amount
        outbound_count[item.sender_id] += 1
        pair_sum[(item.sender_id, item.receiver_id)] += item.amount
        edges.append((item.sender_id, item.receiver_id))

    signals: list[Signal] = []
    score = 0.0
    receiver_fan_in = len(incoming.get(current.receiver_id, ()))
    sender_fan_out = len(outgoing.get(current.sender_id, ()))
    sender_fan_in = len(incoming.get(current.sender_id, ()))

    if receiver_fan_in >= 10:
        score = max(score, 0.72)
        signals.append(
            Signal(
                signal="fan_in",
                severity=Severity.HIGH,
                label_types=[LabelType.AML_LAUNDERING],
                detail=f"{current.receiver_id} received funds from {receiver_fan_in} accounts within 6 hours.",
                evidence={"fan_in": receiver_fan_in},
            )
        )
    if sender_fan_out >= 10:
        score = max(score, 0.72)
        signals.append(
            Signal(
                signal="fan_out",
                severity=Severity.HIGH,
                label_types=[LabelType.AML_LAUNDERING],
                detail=f"{current.sender_id} sent funds to {sender_fan_out} accounts within 6 hours.",
                evidence={"fan_out": sender_fan_out},
            )
        )
    if _path_back(current.receiver_id, current.sender_id, edges):
        score = max(score, 0.93)
        signals.append(
            Signal(
                signal="cycle",
                severity=Severity.HIGH,
                label_types=[LabelType.AML_LAUNDERING],
                detail=(
                    f"Recent transfers form a path from {current.receiver_id} back to {current.sender_id}."
                ),
                evidence={"max_hops": 4},
            )
        )

    inflow = inflow_sum.get(current.sender_id, 0.0)
    payers = incoming.get(current.sender_id, set())
    if sender_fan_in >= 5 and inflow > 0 and current.amount / inflow >= 0.70 and current.receiver_id not in payers:
        score = max(score, 0.88)
        signals.append(
            Signal(
                signal="pass_through_account",
                severity=Severity.HIGH,
                label_types=[LabelType.AML_LAUNDERING],
                detail=(
                    f"{current.sender_id} received funds from {sender_fan_in} accounts and sent "
                    f"{current.amount / inflow:.0%} onward within 6 hours."
                ),
                evidence={"fan_in": sender_fan_in, "outflow_ratio": round(current.amount / inflow, 3)},
            )
        )
    if sender_fan_in >= 2 and inflow > 0 and current.amount / inflow >= 0.50 and current.receiver_id not in payers:
        score = max(score, 0.64)
        signals.append(
            Signal(
                signal="rapid_chain",
                severity=Severity.MEDIUM,
                label_types=[LabelType.AML_LAUNDERING],
                detail=(
                    f"{current.sender_id} forwarded funds after receiving from {sender_fan_in} accounts "
                    "inside the same 6 hour window."
                ),
                evidence={"fan_in": sender_fan_in},
            )
        )
    sent = outflow_sum.get(current.sender_id, 0.0)
    top_pair = pair_sum.get((current.sender_id, current.receiver_id), 0.0)
    if outbound_count.get(current.sender_id, 0) >= 4 and sent > 0 and top_pair / sent >= 0.80:
        score = max(score, 0.58)
        signals.append(
            Signal(
                signal="counterparty_concentration",
                severity=Severity.MEDIUM,
                label_types=[LabelType.AML_LAUNDERING],
                detail=(
                    f"{current.sender_id} sent {top_pair / sent:.0%} of its 6 hour outflow to {current.receiver_id}."
                ),
                evidence={"share": round(top_pair / sent, 3)},
            )
        )
    return score, signals, "scored"
