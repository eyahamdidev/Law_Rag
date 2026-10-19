from __future__ import annotations

from fraud_detection.entity_intelligence.sanctions import SanctionsIndex
from fraud_detection.rules.context import RuleContext
from fraud_detection.rules.transaction_rules import _signal
from fraud_detection.schema import LabelType, Severity, Signal, Transaction


def pep_counterparty(ctx: RuleContext) -> list[Signal]:
    if ctx.tx.amount < 5000:
        return []
    for entity_id in (ctx.tx.sender_id, ctx.tx.receiver_id):
        entity = ctx.entity(entity_id)
        if entity is not None and entity.is_pep:
            return [
                _signal(
                    "pep_counterparty",
                    Severity.MEDIUM,
                    [LabelType.AML_LAUNDERING],
                    f"{entity.name} is marked as a politically exposed person.",
                    {"entity_id": entity.entity_id},
                )
            ]
    return []


def unverified_company(ctx: RuleContext) -> list[Signal]:
    if not ctx.registry_loaded:
        return []
    missing: list[str] = []
    for entity_id, kind in (
        (ctx.tx.sender_id, ctx.tx.sender_kind),
        (ctx.tx.receiver_id, ctx.tx.receiver_kind),
    ):
        if (kind or "").lower() != "company":
            continue
        if ctx.entity(entity_id) is None:
            missing.append(entity_id)
    if not missing:
        return []
    return [
        _signal(
            "entity_unverified",
            Severity.LOW,
            [],
            f"No registry record was found for {', '.join(missing)}.",
            {"missing_ids": missing},
        )
    ]


def sanctions_signals(transaction: Transaction, index: SanctionsIndex) -> list[Signal]:
    signals: list[Signal] = []
    seen: set[str] = set()
    for name, role in ((transaction.sender_name, "sender"), (transaction.receiver_name, "receiver")):
        if not name:
            continue
        found = index.match_scored(name, possible=True)
        if found is None:
            continue
        match, score = found
        if match.name in seen:
            continue
        seen.add(match.name)
        confirmed = score >= 0.92
        signals.append(
            _signal(
                "sanctions_match" if confirmed else "sanctions_possible_match",
                Severity.HIGH if confirmed else Severity.MEDIUM,
                [],
                (
                    f"The {role} name matches {match.name} on the {match.list_name} list."
                    if confirmed
                    else f"The {role} name is a possible match for {match.name} on the {match.list_name} list."
                ),
                {
                    "list_name": match.list_name,
                    "matched_name": match.name,
                    "match_score": round(score, 4),
                    "role": role,
                    "status": "match" if confirmed else "possible_match",
                },
            )
        )
    return signals
