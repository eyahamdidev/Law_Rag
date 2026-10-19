# Fraud agent handoff

For the engineer building the orchestration agent. This is the contract. Field-level examples also live in `docs/FRAUD_AGENT_API.md`.

The system is trained and evaluated on multiple public datasets, including real anonymized transactions and large synthetic/simulated financial datasets.

---

## Page 1 — What the fraud agent is

The fraud agent scores one payment and returns structured evidence. It is one independent service in the larger application. The orchestrator decides what to do with that evidence. It does not train models, and it does not need to know how they work.

It looks for suspicious card payments, account takeover, laundering-style flows, repeated invoices or expenses, procurement-award risk, unusual behavior for the sender, and sanctions-name matches. A quiet recurring payment should stay low. A sanctions match or a strong rule should come back high, with the reason attached.

It is a hybrid system because no single model covers those cases. Card fraud, mobile-money takeover, and laundering were trained as separate problems. Rules catch duplicates, velocity, and typology patterns that do not need a model. Anomaly detection and the graph answer different questions from the supervised heads. Sanctions are a name check, not a fraud probability.

Three supervised families are loaded:

| Family | Used when the payment looks like | Trained on |
| --- | --- | --- |
| `CARD_FRAUD` | A card channel, a card payment type, or a complete `V1`–`V28` vector | BankSim; ULB replaces the score only when `V1`–`V28` are present |
| `ACCOUNT_TAKEOVER` | Mobile money, an account channel, a device, or a balance drain | PaySim |
| `AML_LAUNDERING` | A wire, transfer, cash, or similar account movement | IBM AML |

Rules can also emit `INVOICE_FRAUD`, `EXPENSE_FRAUD`, `PROCUREMENT_RISK`, and `ANOMALY`. Those are separate labels. They are not folded into one “fraud” class. The dataset name on a payload is ignored.

```text
Transaction
    |
    v
Input normalization / routing
    |
    v
Rules + Specialist ML + Anomaly + Graph + Entity/Sanctions
    |
    v
Risk aggregation
    |
    v
Risk score + fraud labels + evidence
    |
    v
Orchestrator
```

Call it as a service. Send the payment, optional history, and optional entities. Read the JSON. Do not import LightGBM, open artifact files, or reimplement features, the graph, or the sanctions index.

---

## Page 2 — Data, models, and output meaning

Training and evaluation used public files. BankSim, PaySim, and IBM AML are simulators, not a bank’s ledger. ULB is real anonymized European card data (284,807 rows, 492 frauds). Elliptic is a real Bitcoin graph and is not loaded by this API. There is no labeled Tunisian transaction model.

| Source | What it is | What the API does with it |
| --- | --- | --- |
| ULB | Real anonymized card transactions, PCA features `V1`–`V28` plus amount | Scores card requests that include those fields. Test PR-AUC 0.72, precision 0.83, recall 0.75 |
| BankSim | Synthetic card-payment simulator | Behavioral `CARD_FRAUD` head. Test PR-AUC 0.78, precision 0.84, recall 0.66, precision at 100 = 1.00 |
| PaySim | Synthetic mobile-money simulator | `ACCOUNT_TAKEOVER` only. Test PR-AUC 0.999 comes from balance-drain features. Do not quote it as the headline |
| IBM AML | Synthetic laundering simulator | Headline behavioral result. Test PR-AUC 0.28, ROC-AUC 0.98, precision 0.54, recall 0.22, precision at 100 = 0.96 |
| OFAC, UN, EU | Public sanctions name lists | Exact and limited fuzzy name match at score time |
| CTAF reports, BCT payment and macro statistics, Findex | Tunisian public context | Typology rules and explanation context only |

IBM’s positive rate on the test split is about 0.2%. PR-AUC 0.28 is about 138 times a random ranking. The top 50 scores on that test split were all true positives. Most missed laundering rows look like ordinary payments, so recall at the 0.50 cutoff stays near 0.22.

`risk_score` is an integer from 0 to 100. It is a deterministic evidence score, not the probability of fraud. The same request returns the same body. The policy averages the layers that are present: rules 0.30, the applicable specialist 0.30, anomaly 0.20, and graph 0.20 when the graph score is above 0. A high-severity rule, a specialist at or above 0.90 with high coverage, a graph score at or above 0.90, or a confirmed sanctions match can raise the score. Sanctions raise it to at least 80.

`risk_level` and `decision` are the same cutoff: `HIGH_RISK` at 75 or above, `MEDIUM_RISK` at 45 or above, otherwise `LOW_RISK`.

`model_scores.supervised` is the calibrated score of the one applicable specialist, or null when none applies. `anomaly` is an isolation-forest score. `graph` is a pattern score. None of those three numbers is a fraud probability. `general_behavior` is a second unsupervised score on portable columns. It does not add a label by itself.

`tunisia.tunisia_score` is always null. A Tunisian payment is recognized from currency `TND` or a `TN` country field. CTAF patterns can add rule signals and explanation text. They are not transaction-level fraud labels.

---

## Page 3 — How the orchestrator calls it

Pull `cursor/tunisia-real-public-data-a4df`. The trained weights are already in that branch, so scoring does not need BankSim, PaySim, IBM, ULB, or the sanctions source files. Those stay out of git and are only needed to train again.

From the repository root:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m fraud_detection serve
```

The service listens on `http://127.0.0.1:8000`. It loads these files once at startup:

| File | Used for |
| --- | --- |
| `supervised.joblib` | BankSim, PaySim, and IBM heads |
| `ulb_card.joblib` | Card score when `V1`–`V28` are present |
| `anomaly.joblib` | Population anomaly score |
| `general_behavior.joblib` | Portable behavior score |
| `sanctions.joblib` | OFAC, UN, and EU name index |

`elliptic_aml.joblib` is in the same folder and is not loaded by `/v1/score`. A score request does not train and does not read the raw datasets.

`GET /health` returns `status: ok` and which layers loaded. `tunisia_model_trained` is false.

`POST /v1/score` body:

```json
{
  "transaction": {
    "amount": 125.0,
    "currency": "EUR",
    "timestamp": "2024-11-18T11:00:00",
    "transaction_type": "transfer",
    "sender_id": "fr-sender",
    "receiver_id": "usual-shop",
    "sender_name": "Epicerie Medina",
    "receiver_name": "Fournisseur Central",
    "country_from": "FR",
    "country_to": "FR"
  },
  "history": [],
  "entities": []
}
```

`history` and `entities` may be omitted. Extra fields are ignored. Useful optional transaction fields are `channel`, `device_id`, `old_balance`, `new_balance`, `invoice_id`, `expense_id`, `bid_count`, and names for sanctions. Card PCA columns `V1`–`V28` may be sent as top-level fields. Common aliases (`transaction_amount`, `sender_account`, `beneficiary`, `currency_code`, `payment_type`, `date`) are accepted.

Missing sender, receiver, timestamp, or currency does not crash the call. The service marks the gap and lowers `data_coverage`. A negative amount, or a `transaction` that is not an object, returns 422. The service does not call the network while scoring.

Python, without importing any model code:

```python
from fraud_detection.fraud_client import health, score_transaction

health("http://127.0.0.1:8000")
result = score_transaction(
    "http://127.0.0.1:8000",
    {
        "amount": 125,
        "currency": "EUR",
        "sender_id": "fr-sender",
        "receiver_id": "usual-shop",
        "timestamp": "2024-11-18T11:00:00",
        "transaction_type": "transfer",
    },
)
```

The response always includes `risk_score`, `risk_level`, `decision`, `label_types`, `fraud_types`, `signals`, `model_scores`, `entity_checks`, `data_coverage`, `model_confidence`, `requires_human_review`, `explanation`, and `tunisia`. `external_checks` repeats the sanctions and registry result. `evidence` lists the sentences behind the score. `graph_status` is `insufficient_history` when no earlier payment was supplied, and `scored` otherwise.

A quiet recurring transfer comes back near `risk_score` 4, `LOW_RISK`, empty `label_types`, and `requires_human_review: false`. A confirmed sanctions match comes back at least 80, `HIGH_RISK`, with `entity_checks.sanctions_status` of `match`. That match does not invent an `AML_LAUNDERING` label.

---

## Page 4 — How to read the response, and what not to depend on

Read `signals` together with `risk_level`. One medium signal is averaged with quiet model scores and can stay `LOW_RISK`. Fan-in or fan-out can appear as an `AML_LAUNDERING` signal with graph score 0.72 while the level stays `LOW_RISK`, because the graph floor is 0.90. The signal is the finding. The level is the policy cutoff.

`label_types` says which family was assigned. `fraud_types` and `signals` say which pattern fired (`duplicate_invoice`, `new_counterparty`, `fan_in`, `sanctions_match`, and so on). `explanation` only restates that evidence. It is not a separate judgment, and an LLM must not replace `risk_score`.

`data_coverage` is `HIGH` when sender, receiver, and timestamp are present and the portable features sit inside training ranges. `MEDIUM` means an unknown or missing currency, or a moderate share of features outside those ranges. `LOW` means a missing party or timestamp, or a large share of features outside those ranges. `LOW` withholds specialist labels. `model_confidence` is then 0.35. `MEDIUM` sets it to 0.55. Otherwise it reflects agreement among the evidence layers.

`requires_human_review` is true for `HIGH_RISK`, for a sanctions match, or for `MEDIUM_RISK` when confidence is below 0.70.

`entity_checks.sanctions_status` is `match`, `possible_match`, `no_match`, `no_name_supplied`, or `not_available`. Only `match` forces the sanctions floor. `possible_match` is a lead, not a confirmed hit. Names need to be supplied; account ids are not screened as names.

Limitations the orchestrator should keep:

- This is not a model of millions of real bank transactions. PaySim’s near-perfect score is a simulator result. IBM recall at the operating point is about 0.22.
- History matters. With no earlier payments, the graph score is 0 and several rules cannot fire. That low score means “no evidence in what was sent,” not “proven legitimate.”
- Country alone does not make a payment high risk. Cross-border means both country codes are present and they differ.
- A type such as `gift_card_barter` does not select the card model. Unknown types such as `pix` select no specialist.
- `tunisia_score` will stay null until real labeled Tunisian transactions exist. Do not treat CTAF or BCT figures as a fraud probability.
- Send a PNG, JPEG, or PDF on `POST /v1/score` as `document`. The service crops a stamp or signature and reads the stamp wording. The enrollment store starts empty. Stamps are kept per company: `document.entity_id`, or the payment `receiver_id` when that field is omitted. There is no separate login. If none is saved for that company yet, `documents.approval_required` is true and `POST /v1/documents/decide` saves the crop with a comment or discards it. A later score has four verdicts. `genuine` means the wording and the aligned drawing match a saved stamp. `fraudulent` means the wording is the same but the drawing clearly is not, and nothing is offered for enrollment. `unrecognized` means the wording is a different stamp. `uncertain` means the scan is too unclear to choose, and nothing is enrolled. Approving an unrecognized proposal enrolls it as another genuine stamp. A photograph of a saved mark still matches when the lines line up. This is not proof, and it is not a YOLO model.
- A three-letter unknown currency code can still receive `HIGH` coverage. Rely on `data_coverage` and the signals, not on currency validation being complete.

Do not depend on any of the following:

- Opening the `.joblib` files, feature names, LightGBM parameters, or dataset paths. The service loads the weights. The orchestrator only calls HTTP.
- The `dataset` field. It does not route and it is not a feature.
- Applying one specialist to every payment. Routing is internal.
- Treating `anomaly`, `graph`, or `supervised` as probabilities, or averaging them yourself.
- Elliptic, SAML-D, or the synthetic Tunisia laboratory. They are not part of this response.
- A second fraud score computed in the orchestrator from these internals.

Health, then `POST /v1/score`, then `risk_score`, `risk_level`, `label_types`, `signals`, `entity_checks`, `data_coverage`, and `requires_human_review`. That is the whole integration.
