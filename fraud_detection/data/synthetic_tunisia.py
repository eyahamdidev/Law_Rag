from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel

from fraud_detection.schema import EntityRecord, LabelType, Transaction


class LabeledExample(BaseModel):
    transaction: Transaction
    label_type: LabelType | None
    scenario: str


def generate_tunisia(seed: int = 7) -> tuple[list[LabeledExample], list[EntityRecord]]:
    """Synthetic Tunisian flows with separate fraud types.

    The seed is accepted so callers can pin a population. The scenarios themselves
    are deterministic; randomness is not required for the typology patterns.
    """
    del seed
    entities: list[EntityRecord] = []
    examples: list[LabeledExample] = []
    opened = datetime(2019, 3, 1)

    for index in range(12):
        entities.append(
            _company(
                f"R{index:02d}",
                f"Restaurant {index}",
                "restaurant",
                "Tunis" if index % 2 == 0 else "Sfax",
                opened,
                480_000,
            )
        )
    for index in range(4):
        entities.append(
            _company(f"W{index:02d}", f"Grossiste {index}", "wholesale", "Tunis", opened, 2_000_000)
        )

    week_zero = datetime(2024, 1, 8, 10, 0)
    for week in range(20):
        for index in range(12):
            examples.append(
                _example(
                    scenario="normal_retail",
                    label=None,
                    transaction_id=f"normal-{week:02d}-{index:02d}",
                    timestamp=week_zero + timedelta(weeks=week, minutes=index),
                    amount=1800 + index * 70 + (week % 3) * 20,
                    sender_id=f"R{index:02d}",
                    receiver_id=f"W{index % 4:02d}",
                    merchant_category="food_wholesale",
                )
            )

    for ring in range(4):
        company = f"NC{ring:02d}"
        registered = datetime(2024, 5, 10) + timedelta(days=ring)
        entities.append(
            _company(company, f"Nouvelle Societe {ring}", "consulting", "Ariana", registered, 20_000)
        )
        foreign = f"FR{ring:02d}"
        entities.append(
            EntityRecord(
                entity_id=foreign,
                name=f"Compte Etranger {ring}",
                kind="account",
                country="FR",
                status="active",
            )
        )
        started = datetime(2024, 6, 3, 11, 0) + timedelta(days=ring * 4)
        total = 0.0
        for person_index in range(18):
            person = f"P{ring:02d}{person_index:02d}"
            entities.append(
                EntityRecord(
                    entity_id=person,
                    name=f"Personne {ring}-{person_index}",
                    kind="person",
                    country="TN",
                    status="active",
                )
            )
            amount = 800 + person_index * 30
            total += amount
            examples.append(
                _example(
                    scenario="pass_through_in",
                    label=LabelType.AML_LAUNDERING if person_index >= 8 else None,
                    transaction_id=f"ring-{ring}-in-{person_index:02d}",
                    timestamp=started + timedelta(minutes=person_index * 4),
                    amount=amount,
                    sender_id=person,
                    receiver_id=company,
                    sender_kind="person",
                    receiver_kind="company",
                )
            )
        examples.append(
            _example(
                scenario="pass_through_out",
                label=LabelType.AML_LAUNDERING,
                transaction_id=f"ring-{ring}-out",
                timestamp=started + timedelta(hours=2),
                amount=round(total * 0.91, 2),
                sender_id=company,
                receiver_id=foreign,
                sender_kind="company",
                receiver_kind="account",
                country_to="FR",
            )
        )

    for index in range(16):
        account = f"AT{index:02d}"
        usual = f"ATB{index:02d}"
        foreign = f"ATF{index:02d}"
        entities.append(_company(account, f"Commercant {index}", "retail", "Sousse", datetime(2018, 1, 10), 300_000))
        entities.append(_company(usual, f"Fournisseur {index}", "wholesale", "Sousse", opened, 900_000))
        entities.append(
            EntityRecord(entity_id=foreign, name=f"Beneficiaire Nuit {index}", kind="account", country="LY", status="active")
        )
        for week in range(12):
            examples.append(
                _example(
                    scenario="takeover_history",
                    label=None,
                    transaction_id=f"at-{index:02d}-hist-{week:02d}",
                    timestamp=datetime(2024, 1, 9, 11, 30) + timedelta(weeks=week, minutes=index),
                    amount=1400 + week * 15,
                    sender_id=account,
                    receiver_id=usual,
                )
            )
        examples.append(
            _example(
                scenario="account_takeover",
                label=LabelType.ACCOUNT_TAKEOVER,
                transaction_id=f"at-{index:02d}-fraud",
                timestamp=datetime(2024, 4, 16, 3, 15) + timedelta(days=index),
                amount=28_000,
                sender_id=account,
                receiver_id=foreign,
                channel="transfer",
                device_id=f"new-device-{index}",
            )
        )

    for index in range(16):
        for copy in range(3):
            examples.append(
                _example(
                    scenario="duplicate_invoice",
                    label=LabelType.INVOICE_FRAUD if copy else None,
                    transaction_id=f"inv-{index:02d}-{copy}",
                    timestamp=datetime(2024, 7, 2, 9, 0) + timedelta(days=index, minutes=15 * copy),
                    amount=4_200,
                    sender_id=f"R{index % 12:02d}",
                    receiver_id=f"W{index % 4:02d}",
                    invoice_id=f"FAC-{index:04d}",
                )
            )
        for copy in range(2):
            examples.append(
                _example(
                    scenario="duplicate_expense",
                    label=LabelType.EXPENSE_FRAUD if copy else None,
                    transaction_id=f"exp-{index:02d}-{copy}",
                    timestamp=datetime(2024, 7, 20, 15, 0) + timedelta(days=index, minutes=30 * copy),
                    amount=860,
                    sender_id=f"AT{index:02d}",
                    receiver_id=f"ATB{index:02d}",
                    expense_id=f"DEP-{index:04d}",
                )
            )

    for series in range(6):
        sender = f"ST{series:02d}"
        entities.append(_company(sender, f"Change {series}", "exchange", "Tunis", opened, 600_000))
        entities.append(_company(f"STD{series:02d}", f"Caisse {series}", "cash", "Tunis", opened, 400_000))
        for step in range(4):
            examples.append(
                _example(
                    scenario="structuring",
                    label=LabelType.AML_LAUNDERING if step >= 2 else None,
                    transaction_id=f"struct-{series}-{step}",
                    timestamp=datetime(2024, 8, 5, 16, 0) + timedelta(days=series, hours=12 * step),
                    amount=9_600,
                    sender_id=sender,
                    receiver_id=f"STD{series:02d}",
                )
            )

    entities.append(
        _company("INACTIVE", "Societe Dormante", "import", "Medenine", datetime(2016, 6, 1), 50_000, status="inactive")
    )
    entities.append(_company("INACTIVE-R", "Contrepartie Dormante", "import", "Medenine", opened, 80_000))
    examples.append(
        _example(
            scenario="inactive_company",
            label=LabelType.AML_LAUNDERING,
            transaction_id="inactive-1",
            timestamp=datetime(2024, 8, 18, 12, 0),
            amount=45_000,
            sender_id="INACTIVE",
            receiver_id="INACTIVE-R",
        )
    )

    entities.append(_company("TM", "Faible CA", "services", "Nabeul", datetime(2021, 2, 2), 24_000))
    entities.append(_company("TM-R", "Flux TM", "services", "Nabeul", opened, 100_000))
    for step in range(8):
        examples.append(
            _example(
                scenario="turnover_mismatch",
                label=LabelType.AML_LAUNDERING,
                transaction_id=f"tm-{step}",
                timestamp=datetime(2024, 8, 1, 13, 0) + timedelta(days=3 * step),
                amount=20_000,
                sender_id="TM",
                receiver_id="TM-R",
            )
        )

    for index in range(16):
        examples.append(
            _example(
                scenario="procurement_risk",
                label=LabelType.PROCUREMENT_RISK,
                transaction_id=f"award-risk-{index:02d}",
                timestamp=datetime(2024, 9, 2, 10, 0) + timedelta(days=index),
                amount=180_000,
                sender_id=f"BUYER-{index:02d}",
                receiver_id=f"WINNER-{index:02d}",
                transaction_type="procurement",
                bid_count=1,
                award_to_estimate_ratio=1.8,
                submission_window_days=3,
                currency="TND",
            )
        )
        entities.append(_company(f"BUYER-{index:02d}", f"Acheteur {index}", "public", "Tunis", opened, 0))
        entities.append(_company(f"WINNER-{index:02d}", f"Attributaire {index}", "construction", "Tunis", opened, 1_000_000))
    for index in range(8):
        examples.append(
            _example(
                scenario="procurement_fair",
                label=None,
                transaction_id=f"award-fair-{index:02d}",
                timestamp=datetime(2024, 9, 3, 10, 0) + timedelta(days=index),
                amount=90_000,
                sender_id=f"FAIR-BUYER-{index:02d}",
                receiver_id=f"FAIR-WINNER-{index:02d}",
                transaction_type="procurement",
                bid_count=6,
                award_to_estimate_ratio=0.97,
                submission_window_days=25,
            )
        )
        entities.append(_company(f"FAIR-BUYER-{index:02d}", f"Acheteur Ouvert {index}", "public", "Sfax", opened, 0))
        entities.append(_company(f"FAIR-WINNER-{index:02d}", f"Attributaire Ouvert {index}", "construction", "Sfax", opened, 800_000))

    for index in range(16):
        holder = f"CARD-{index:02d}"
        entities.append(EntityRecord(entity_id=holder, name=f"Porteur {index}", kind="person", country="FR", status="active"))
        entities.append(EntityRecord(entity_id=f"POS-{index:02d}", name=f"TPE {index}", kind="company", country="IT", status="active"))
        examples.append(
            _example(
                scenario="card_fraud",
                label=LabelType.CARD_FRAUD,
                transaction_id=f"card-fraud-{index:02d}",
                timestamp=datetime(2024, 9, 12, 2, 40) + timedelta(days=index),
                amount=6_500,
                currency="EUR",
                sender_id=holder,
                receiver_id=f"POS-{index:02d}",
                channel="card",
                transaction_type="card",
                country_from="FR",
                country_to="IT",
            )
        )
    for index in range(12):
        examples.append(
            _example(
                scenario="card_legit",
                label=None,
                transaction_id=f"card-ok-{index:02d}",
                timestamp=datetime(2024, 9, 12, 19, 0) + timedelta(days=index),
                amount=90 + index,
                sender_id=f"R{index % 12:02d}",
                receiver_id=f"W{index % 4:02d}",
                channel="card",
                transaction_type="card",
            )
        )

    for ring in range(3):
        nodes = [f"CY{ring}{letter}" for letter in ("A", "B", "C")]
        for node in nodes:
            entities.append(_company(node, f"Cycle {node}", "trading", "Tunis", opened, 250_000))
        stamps = [datetime(2024, 10, 1, 14, 0) + timedelta(days=ring, minutes=10 * step) for step in range(3)]
        pairs = ((nodes[0], nodes[1]), (nodes[1], nodes[2]), (nodes[2], nodes[0]))
        for step, (sender, receiver) in enumerate(pairs):
            examples.append(
                _example(
                    scenario="cycle",
                    label=LabelType.AML_LAUNDERING,
                    transaction_id=f"cycle-{ring}-{step}",
                    timestamp=stamps[step],
                    amount=3_000,
                    sender_id=sender,
                    receiver_id=receiver,
                )
            )

    examples.sort(key=lambda item: (item.transaction.timestamp, item.transaction.transaction_id))
    return examples, entities


def history_before(examples: list[LabeledExample], transaction_id: str) -> list[Transaction]:
    current = next(item.transaction for item in examples if item.transaction.transaction_id == transaction_id)
    return [
        item.transaction
        for item in examples
        if item.transaction.transaction_id != transaction_id and item.transaction.timestamp <= current.timestamp
    ]


def find_example(examples: list[LabeledExample], scenario: str) -> LabeledExample:
    return next(item for item in examples if item.scenario == scenario)


def _company(
    entity_id: str,
    name: str,
    activity: str,
    governorate: str,
    registered_on: datetime,
    revenue: float,
    status: str = "active",
) -> EntityRecord:
    return EntityRecord(
        entity_id=entity_id,
        name=name,
        kind="company",
        country="TN",
        governorate=governorate,
        activity=activity,
        registered_on=registered_on,
        status=status,
        declared_annual_revenue=revenue,
    )


def _example(scenario: str, label: LabelType | None, **fields) -> LabeledExample:
    fields.setdefault("currency", "TND")
    fields.setdefault("country_from", "TN")
    fields.setdefault("country_to", "TN")
    fields.setdefault("transaction_type", "transfer")
    fields.setdefault("dataset", "tunisia_synth")
    transaction = Transaction(label_type=label, **fields)
    return LabeledExample(transaction=transaction, label_type=label, scenario=scenario)
