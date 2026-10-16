# Fraud agent API

This is the contract for the orchestration agent. Call the HTTP service. Do not import LightGBM, open model files, or reimplement features, the graph, or the sanctions index.

`risk_score` is a deterministic evidence score from 0 to 100. It is not the probability of fraud.

## Start

From the repository root, with the virtualenv installed:

```bash
.venv/bin/python -m fraud_detection serve
```

The service listens on `127.0.0.1:8000`. Models are loaded once at startup. `POST /v1/score` does not train.

Optional environment variables:

| Variable | Meaning |
| --- | --- |
| `FRAUD_MODEL_PATH` | Supervised artifact. Default `fraud_detection/models/artifacts/supervised.joblib` |
| `FRAUD_ANOMALY_PATH` | Population anomaly artifact |
| `FRAUD_SANCTIONS_CSV` | CSV with `name` and `list_name`, used instead of the saved sanctions index |
| `FRAUD_RNE_CSV` | Optional company registry |

## Health

`GET /health`

```json
{
  "status": "ok",
  "layers": ["rules", "supervised", "anomaly", "graph", "entity_intelligence"],
  "supervised_loaded": true,
  "anomaly_loaded": true,
  "sanctions_available": true,
  "general_behavior_loaded": true,
  "ulb_loaded": true,
  "tunisia_model_trained": false,
  "tunisia_score_policy": "null_until_real_labeled_transactions"
}
```

`tunisia_model_trained` stays false. There is no labeled Tunisian transaction model.

## Score

`POST /v1/score`

`history`, `entities`, and `document` are optional. Extra JSON fields are ignored. A missing sender, receiver, timestamp, or currency does not crash the service: the missing value is marked and `data_coverage` becomes `LOW` or `MEDIUM`.

`documents` in the response is null when no file was sent. Send a PNG, JPEG, or PDF in the same score call. The service finds the stamp and signature, crops them, and compares them with what is already saved for `document.entity_id` or, if that is omitted, the payment receiver.

```json
{
  "transaction": {"amount": 125, "currency": "EUR", "sender_id": "fr-sender", "receiver_id": "supplier-9"},
  "document": {"filename": "invoice.pdf", "pdf_base64": "<base64>", "expect_stamp": true, "expect_signature": true}
}
```

When a mark is present and nothing is saved yet, `documents.approval_required` is true. Each new mark has `status` `awaiting_approval`, a `crop_base64` preview, a `question`, and a `proposal_id`. Nothing is stored as the genuine mark until `POST /v1/documents/decide` with `{"proposal_id": "...", "approve": true, "comment": "Cachet officiel"}`. `approve: false` discards that crop. The enrollment directory starts empty for every fresh user, so the first file only crops and asks. It does not arrive with someone else's stamp already saved.

A later score reads the words on the crop and compares them with every stamp saved for that company. The company key is `document.entity_id` when it is sent, otherwise the payment `receiver_id`. There is no separate login: anyone who can score a payment for that receiver uses that receiver's stamps, and another receiver's stamps are not consulted. The drawing is then checked by a supervised verifier trained on labeled genuine and counterfeit pairs (`python -m fraud_detection train-stamps`). It is not an unsupervised anomaly detector. `genuine_probability` is the verifier score against the compared stamp. The enrollment `comment` is returned on the mark.

`marks[].verdict` is one of four values:

- `genuine` — the wording and the aligned drawing match a saved stamp. A photograph of the saved mark still matches when the lines line up.
- `fraudulent` — the wording is the same stamp, but the aligned drawing clearly is not. There is no enrollment question. The signal is `document_stamp_fraudulent` and the score floor is 75.
- `unrecognized` — the wording is a different stamp, such as a bank stamp after a startup stamp was saved. It is not called fraudulent. The mark includes `read_text`, `enrolled_text`, a `question`, and a `proposal_id`. Approve to enroll it as another genuine stamp. Decline to keep the warning.
- `uncertain` — the wording is close to a saved stamp, but the scan is not clear enough to call the drawing genuine or fraudulent. Nothing is enrolled. The signal is `document_stamp_uncertain` and the score floor is 60.

A missing expected mark raises the score with a floor of 45. An unrecognized stamp raises it with a floor of 60. An unreadable file is a warning and the payment is still scored. A photograph of a saved mark still matches. `documents.proof` stays false. Reading the words needs Tesseract with the French and English language packs.

```json
{
  "transaction": {
    "transaction_id": "pay-100",
    "timestamp": "2024-11-18T11:00:00",
    "amount": 125.0,
    "currency": "EUR",
    "transaction_type": "transfer",
    "sender_id": "fr-sender",
    "receiver_id": "usual-shop",
    "country_from": "FR",
    "country_to": "FR"
  },
  "history": [
    {
      "transaction_id": "pay-099",
      "timestamp": "2024-11-11T11:00:00",
      "amount": 120.0,
      "currency": "EUR",
      "transaction_type": "transfer",
      "sender_id": "fr-sender",
      "receiver_id": "usual-shop",
      "country_from": "FR",
      "country_to": "FR"
    }
  ],
  "entities": []
}
```

Common aliases are accepted on a transaction (`transaction_amount`, `sender_account`, `beneficiary`, `currency_code`, `payment_type`, `date`). Card PCA columns `V1`–`V28` may be sent as top-level fields.

## Response

The same input produces the same JSON. A quiet recurring transfer looks like this:

```json
{
  "risk_score": 4,
  "risk_level": "LOW_RISK",
  "decision": "LOW_RISK",
  "label_types": [],
  "fraud_types": [],
  "signals": [],
  "model_scores": {
    "supervised": 0.0069,
    "anomaly": 0.1531,
    "graph": 0.0,
    "supervised_by_type": {"AML_LAUNDERING": 0.0069},
    "general_behavior": 0.1206
  },
  "entity_checks": {
    "sanctions_status": "no_name_supplied",
    "sanctions_match": false,
    "matched_list": null,
    "matched_entity": null,
    "match_score": null,
    "entity_verified": false
  },
  "data_coverage": "HIGH",
  "model_confidence": 0.85,
  "confidence": 0.85,
  "requires_human_review": false,
  "explanation": "No rule, graph pattern, sanctions hit, or entity alert fired for pay-100.",
  "tunisia": {"tunisia_score": null, "model_trained": false}
}
```

`external_checks` repeats the sanctions and registry result. `evidence` lists the sentences that support the score. `graph_status` is `insufficient_history` when no earlier payment was supplied, and `scored` otherwise.

## What the fields mean

`risk_score` averages the evidence that is present:

- rules, weight 0.30
- the applicable specialist score, weight 0.30
- anomaly score, weight 0.20
- graph score, weight 0.20, only when it is above 0

Floors, still not probabilities:

- a high-severity rule (internal weight at least 0.85) keeps at least 90% of that rule weight
- a calibrated specialist at least 0.90, and only when coverage is `HIGH`, raises the score to at least 75
- a graph score of at least 0.90 raises the score to at least 75
- a confirmed sanctions match raises the score to at least 80

`risk_level` and `decision` use the same cutoffs: `HIGH_RISK` at 75 or above, `MEDIUM_RISK` at 45 or above, otherwise `LOW_RISK`.

Read `signals` as well as `risk_level`. One medium signal is averaged with quiet model scores and can stay `LOW_RISK`. A fan-in or fan-out graph score of 0.72 is below the 0.90 floor, so the level can stay `LOW_RISK` while `signals` still names the pattern.

`label_types` are separate fraud families. They are not concatenated into one label.

| Label | When it can appear |
| --- | --- |
| `CARD_FRAUD` | Card channel, a card payment type, or a complete `V1`–`V28` vector |
| `ACCOUNT_TAKEOVER` | Mobile-money, an account channel, a device, a balance drain, or a new-beneficiary rule |
| `AML_LAUNDERING` | Wire, transfer, cash, or a graph or AML rule |
| `INVOICE_FRAUD` | Invoice fields, including a repeated invoice |
| `EXPENSE_FRAUD` | Expense fields |
| `PROCUREMENT_RISK` | Procurement or bid fields |
| `ANOMALY` | Velocity or a behavioral anomaly rule |

A type such as `gift_card_barter` does not select the card model. A domestic payment outside Tunisia is not treated as cross-border. Cross-border means both country codes are present and different.

`model_scores.supervised` is the calibrated score of the one applicable specialist, or null when none applies. It is not a probability and it is not the max across every head. `anomaly` is an isolation-forest score, not a fraud probability. `graph` is a pattern score, not a model probability. The ULB card specialist replaces the card score only when `V1`–`V28` are present.

`data_coverage`:

- `HIGH` — sender, receiver, and timestamp are present, and the portable features sit inside the training ranges
- `MEDIUM` — unknown or missing currency, or a moderate share of features outside those ranges
- `LOW` — missing sender, receiver, or timestamp, or a large share of features outside those ranges

`LOW` coverage withholds specialist labels and down-weights the specialist score. `model_confidence` is then 0.35. `MEDIUM` coverage sets `model_confidence` to 0.55. Otherwise `model_confidence` is the agreement of the evidence layers, with a floor of 0.70, or 0.80 when a specialist is at least 0.90 or a sanctions match is confirmed.

`requires_human_review` is true for `HIGH_RISK`, for a sanctions match, or for `MEDIUM_RISK` when confidence is below 0.70.

`tunisia.tunisia_score` is always null. Tunisian public sources are context and typology rules, not a transaction-level fraud model. Country is detected from currency `TND` or a `TN` country field, not from a dataset name.

## Failure behavior

- Valid but incomplete JSON returns 200 with a low score and low coverage.
- A negative amount, or a `transaction` that is not an object, returns 422.
- The same payload scored twice returns the same body.
- The service does not call an external network during scoring.

## Python client

```python
from fraud_detection.fraud_client import health, score_transaction

health("http://127.0.0.1:8000")
result = score_transaction(
    "http://127.0.0.1:8000",
    {"amount": 125, "currency": "EUR", "sender_id": "fr-sender", "receiver_id": "usual-shop"},
    history=[],
)
# document=invoice_bytes and document_filename="invoice.pdf" crop and review inside the same call.
# decide_document_mark(base_url, proposal_id, approve=True) saves a cropped mark.
```

`history` and `entities` can be omitted.

## curl

```bash
curl -s http://127.0.0.1:8000/health

curl -s http://127.0.0.1:8000/v1/score \
  -H 'content-type: application/json' \
  -d '{"transaction":{"amount":125,"currency":"EUR","sender_id":"fr-sender","receiver_id":"usual-shop","timestamp":"2024-11-18T11:00:00","transaction_type":"transfer","country_from":"FR","country_to":"FR"}}'
```
