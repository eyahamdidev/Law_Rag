# Fraud detection agent

Hybrid fraud and AML agent for Tunisian business payments, card activity, invoices, expenses, and procurement awards.

The system is trained and evaluated on multiple public datasets, including real anonymized transactions and large synthetic/simulated financial datasets. BankSim, PaySim, and IBM AML are simulators. ULB is real anonymized European card data. Elliptic is a real Bitcoin transaction graph, not a bank ledger. This is not a model trained on millions of real bank transactions.

The model does not ask an LLM to decide "fraud or not fraud". Rules, a gradient-boosted model, anomaly detection, graph patterns, and entity screening produce the score. The explanation only describes that evidence. `risk_score` is a risk score from 0–100 produced by a deterministic evidence aggregation policy. It is not the probability of fraud.

```text
Transaction
    |
    +-- Rules (transaction, AML, Tunisia typologies, procurement)
    +-- Supervised model (LightGBM, one model per label type)
    +-- Anomaly detector (Isolation Forest, or a robust z-score on short history)
    +-- Graph patterns (fan-in, fan-out, cycles, pass-through)
    +-- Entity intelligence (registry, sanctions, PEP)
            |
            v
      Risk policy (0-100, not a probability)
            |
            v
      Evidence explanation  ->  orchestrator
```

Fraud types stay separate. A card-fraud row is never treated as a clean AML example, and datasets are not concatenated into one label. At scoring time a supervised head fires only for a matching payment shape: card, debit, or credit-card inputs for `CARD_FRAUD`, mobile-money, device, or balance-drain inputs for `ACCOUNT_TAKEOVER`, and wire, transfer, or cash formats for `AML_LAUNDERING`. The dataset name is not used. The supervised score is the maximum calibrated score inside that family, not the maximum across every head.

`CARD_FRAUD` `AML_LAUNDERING` `ACCOUNT_TAKEOVER` `INVOICE_FRAUD` `EXPENSE_FRAUD` `PROCUREMENT_RISK` `ANOMALY` `UNKNOWN`

## Run

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pytest
.venv/bin/python -m fraud_detection serve
```

`POST /v1/score` accepts `transaction`, optional `history`, and optional `entities`. `GET /health` lists the layers. The orchestrator handoff is `docs/FRAUD_AGENT_HANDOFF.md`. The field contract is `docs/FRAUD_AGENT_API.md`. A caller that should not import the models can use `fraud_detection/fraud_client.py`.

Download the public files, train on them, and serve the saved artifacts:

```bash
bash scripts/download_public_data.sh
.venv/bin/python -m fraud_detection train
.venv/bin/python -m fraud_detection serve
```

`train` reads `fraud_detection/data/raw`, writes feature matrices under `fraud_detection/data/processed`, and saves models under `fraud_detection/models/artifacts`. The trained `.joblib` files are in git, so `serve` works after a pull. The raw datasets are not in git; they are only needed to train again. `FRAUD_MODEL_PATH` and `FRAUD_ANOMALY_PATH` override the defaults.

The synthetic Tunisia laboratory is a regression fixture, not training data:

```bash
.venv/bin/python -m fraud_detection generate --out fraud_detection/data/processed/canonical
.venv/bin/python -m fraud_detection train-synthetic --out model_store/supervised/tunisia.joblib
```

Optional local reference files:

- `FRAUD_RNE_CSV` — company registry extract
- `FRAUD_SANCTIONS_CSV` — columns `name`, `list_name`
- `FRAUD_MODEL_PATH` — joblib saved by `train`

## What the orchestrator receives

```json
{
  "risk_score": 95,
  "decision": "HIGH_RISK",
  "fraud_types": ["pass_through_account", "rapid_in_outflow", "new_company_many_payers"],
  "label_types": ["AML_LAUNDERING"],
  "signals": [
    {
      "signal": "pass_through_account",
      "severity": "high",
      "detail": "The account received funds from 18 counterparties within 6 hours and transferred 91% of that amount to a foreign beneficiary."
    }
  ],
  "model_scores": {"supervised": null, "anomaly": null, "graph": 0.88},
  "external_checks": {"sanctions": false, "entity_verified": true, "sanctions_lists": []},
  "confidence": 0.55,
  "requires_human_review": true,
  "explanation": "The account received funds from 18 counterparties within 6 hours and transferred 91% of that amount to a foreign beneficiary."
}
```

`supervised` is null until a model is loaded. The narrator cannot change `risk_score`. `evidence_bundle()` in `fraud_detection/explanations/narrator.py` is the payload to hand an LLM if you want a prose explanation later.

## Stamps

Stamp checks are supervised. Training pairs are labeled genuine (the same stamp, including another copy or a light scan) or fake (a counterfeit or a different stamp). An unsupervised anomaly model is not used for this decision.

```bash
.venv/bin/python -m fraud_detection train-stamps
```

The weights are `fraud_detection/models/artifacts/stamp_verifier.joblib`. Held-out crops are ranked with a validation PR-AUC of about 0.82 (`fraud_detection/evaluation/stamp_verifier_metrics.json`). The enrollment folder `fraud_detection/data/specimens/` starts empty. A user enrolls one genuine file. The service crops the stamp, reads its words, and saves it with a comment.

A later `POST /v1/score` reads the new stamp and compares that wording with the saved one. The company key is the document `entity_id` or, if omitted, the payment `receiver_id`. Stamps saved for another receiver are not used. The same wording and a drawing that lines up after alignment is `genuine`, including the same file and a darker copy of that drawing. The same wording with a drawing that clearly does not line up is `fraudulent`, and it is not offered for enrollment. A different wording, such as a bank stamp after a startup stamp, is `unrecognized`: the service asks whether to enroll it, and it is not called fraudulent. If the scan is too unclear, alignment fails, or the evidence conflicts, the verdict is `uncertain` and nothing is enrolled. A very close counterfeit can land in `uncertain` or, when both the aligned pixels and the model agree, in `genuine`. Reading the words needs Tesseract (`tesseract-ocr`, `tesseract-ocr-fra`, `tesseract-ocr-eng`).

## Detection layers

Rules catch duplicates, velocity, structuring just under round thresholds, night-time spikes, new large beneficiaries, impossible balances, rapid in-and-out flows, pass-through accounts, young companies collecting from many payers, declared-revenue mismatches, inactive companies, single-bid and short-deadline procurement awards, PEP counterparties, and sanctions matches.

The supervised layer is LightGBM (scikit-learn histogram boosting if LightGBM cannot load). Each label type is trained only against legitimate rows. Features are computed from prior transactions, so a future payment is not visible at training time.

Anomaly detection fits an Isolation Forest on the sender's own history when at least 25 earlier payments exist, and uses a median/MAD score between 8 and 24 payments. It answers "unlike this sender", which is a different question from "like fraud I have seen".

The graph layer looks six hours back for fan-in, fan-out, short cycles, and pass-through structure.

Entity checks use a registry overlay (RNE-style CSV) and an exact sanctions-name index. A missing registry does not by itself raise the score. A sanctions match forces a high-risk review and does not invent an `AML_LAUNDERING` label.

## Data

Raw files stay in `fraud_detection/data/raw/<source>/`. See `DATA_SOURCES.md` and `fraud_detection/data/README.md`. Adapters live in `fraud_detection/data/adapters/`. `data_origin=REAL_PUBLIC_DATA` means the file was a public download. `source_kind` says whether that download is `synthetic_simulated`, `real_anonymized`, or `real_cryptocurrency_graph`.

| Source | What it is | Label kept as | Constraint |
| --- | --- | --- | --- |
| IBM AML | synthetic AML simulator | `AML_LAUNDERING` | CDLA-Sharing-1.0 on the data. Headline behavioral result |
| IBM TabFormer | card sequences, not downloaded | | separate from AML extracts |
| SAML-D | synthetic AML simulator, validated only | `AML_LAUNDERING`, original laundering type kept in metadata | not mixed into the IBM head |
| PaySim | synthetic mobile money | `ACCOUNT_TAKEOVER` | account drain, not card fraud. Near-perfect metrics are not the headline |
| BankSim | synthetic bank-payment simulator | `CARD_FRAUD` | not a real card ledger |
| ULB | real anonymized European card transactions | `CARD_FRAUD` specialist | loaded by `/v1/score` when `V1`–`V28` are present |
| handbook simulator | synthetic, not generated here | `CARD_FRAUD` | |
| IEEE-CIS | not downloaded | `CARD_FRAUD` | non-commercial competition data only |
| Elliptic | real Bitcoin transaction graph | `AML_LAUNDERING` for illicit nodes | cryptocurrency, not bank payments; unknown nodes are dropped |
| Procurement awards | | `PROCUREMENT_RISK` | map EuroProcure-style rows through `adapt_procurement` |

Global files are for training. A Tunisian payment is recognized from TND or a TN country field, never from the dataset name. The Tunisia layer adds documented CTAF rules and BCT aggregate context. It does not add a Tunisia fraud probability: `tunisia_score` stays null until real labeled Tunisian transactions exist. See `docs/tunisia_data_inventory.md`.

Tunisian reference sources actually downloaded for this layer:

- [CTAF 2024 activity report](https://www.ctaf.gov.tn/data/uploads/pdf/68ed20ef1333f7.67071673.pdf), the 2023 report, and the 2020–2025 typology bulletin. Case-based, not a transaction table.
- [BCT SDMX](https://gosdmx.bct.gov.tn/gosdmx/pnrd?lang=FR) banking, external, and trade series, plus the [payment-count](https://www.bct.gov.tn/bct/siteprod/tableau_statistique.jsp?params=PL202020) and [payment-value](https://www.bct.gov.tn/bct/siteprod/tableau_statistique.jsp?params=PL202010) tables.
- World Bank Global Findex indicator API for Tunisia. Those rows are population aggregates. The microdata file was not downloaded.

The national company register and the 2024 Enterprise Survey microdata were not obtained. `catalog.data.gov.tn` did not complete a verified download. RNE public pages do not expose an unauthenticated KYC extract.

Entity screening sources, loaded by you under their own terms: [OFAC](https://ofac.treasury.gov/sanctions-list-service), the [UN consolidated list](https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list), the [EU financial sanctions list](https://data.europa.eu/data/datasets/consolidated-list-of-persons-groups-and-entities-subject-to-eu-financial-sanctions), [GLEIF](https://www.gleif.org/en/lei-data/gleif-golden-copy/download-the-golden-copy), and [OpenSanctions](https://www.opensanctions.org/datasets/default/) (commercial use needs a license).

`python -m fraud_detection generate` writes a deterministic Tunisia laboratory: weekly restaurant-to-wholesaler payments, pass-through rings, account takeover, duplicate invoices and expenses, structuring, inactive companies, turnover mismatches, procurement awards, card payments, and short cycles.

## Evaluation

Do not use accuracy. `fraud_detection/evaluation/metrics.py` reports PR-AUC, precision, recall, F1, recall at a fixed false-positive rate, precision at top K, and false positives per 1,000 rows.

Cite IBM AML first: the positive rate is tiny, PR-AUC is about 0.28, ROC-AUC is about 0.98, and precision at 100 is 0.96. BankSim (PR-AUC about 0.78) and the ULB specialist (PR-AUC about 0.72) are the other numbers worth quoting. PaySim's PR-AUC and ROC-AUC near 0.999 were measured, and they come from simulator balance-drain features. Do not lead with them.

`python -m fraud_detection evaluate` prints `fraud_detection/evaluation/metrics.json` from the public-data training run. `evaluate-synthetic` is only the Tunisia laboratory smoke check. `temporal_masks` splits by time. `holdout_entities` keeps every payment of a held-out account out of training.

The policy weights are rules 0.30, supervised 0.30, anomaly 0.20, and graph 0.20 when the graph score is positive. A supervised calibrated score of at least 0.90, or a graph score of at least 0.90, raises the policy score to at least 75. A sanctions match raises it to at least 80. None of those floors is a probability.

## Layout

```text
fraud_detection/rules/                 deterministic checks
fraud_detection/models/                features, LightGBM, Isolation Forest, graph
fraud_detection/entity_intelligence/   registry and sanctions
fraud_detection/inference/             aggregator and scoring pipeline
fraud_detection/explanations/          evidence text; score is already fixed
fraud_detection/evaluation/            metrics and splits
fraud_detection/api/                   FastAPI
fraud_detection/data/                  adapters, synthetic generator, raw drops
model_store/                       trained joblib files (not source)
```
