# Tunisia model design

## Flow

```
incoming transaction
        |
 normalize schema
        |
 country / data coverage
        |
   +----+----+
   |         |
 global     Tunisia layer
 models     (rules + aggregate context)
   |         |
   +----+----+
        |
  behavior / risk policy
        |
   final score
```

The global models are unchanged: behavioral LightGBM heads, the portable Isolation Forest, the population Isolation Forest, the ULB card specialist when `V1`–`V28` are present, the Elliptic model only offline, sanctions, and the deterministic evidence policy. `FEATURE_NAMES` was not extended. No specialist was retrained.

Tunisia routing uses only:

- currency `TND`
- `country_from == TN` or `country_to == TN`

`dataset` is not read. A row whose dataset name is `tunisia_synth` and whose currency and countries are not Tunisian is not scored as Tunisia.

## What runs for a Tunisian payment

`POST /v1/score` adds a `tunisia` object.

| Field | Value with the data on hand |
| --- | --- |
| `country` | `TN` when routing matches |
| `country_detection` | the currency and country fields that matched |
| `coverage` | `MEDIUM` if the BCT payment baseline file is present, otherwise `LOW`. Never `HIGH` |
| `global_score` | the existing supervised score, or null when no global model is loaded |
| `tunisia_score` | **null** |
| `anomaly_score` | the existing anomaly score |
| `sanctions_score` | 0, a match score, or null when no name or no list is available |
| `rule_score` | the existing rule aggregate, including any CTAF rule that fired |
| `final_score` | the existing 0–100 policy score |
| `risk_label` | `LOW_RISK`, `MEDIUM_RISK`, or `HIGH_RISK` |
| `specialist` | null. It is not `tunisia_behavior` |
| `model_trained` | false |
| `model_status` | `not_trained_no_transaction_labels` |

`coverage = HIGH` is reserved for a model trained on real labeled Tunisian transactions. That model does not exist. Returning a probability such as 0.72 would be a fabricated Tunisia prediction, so the field is null.

`data_coverage` on the parent assessment is still the global portable-feature coverage. It is a different question from `tunisia.coverage`.

Country does not raise the risk score. A TN-to-FR transfer under 20,000 does not match the existing cross-border rule. A large domestic transfer with no other pattern stays out of `HIGH_RISK`.

## Tunisia rules

Rules live in `fraud_detection/tunisia/ctaf_rules.py` and cite pattern ids in `ctaf_typologies.json`. They fire only when the payment fields show the documented behavior.

They do not use nationality, ethnicity, religion, age, gender, or occupation. Sender origin from the migrant-smuggling narrative is not a condition. A country code is used only to tell a domestic payment from a cross-border one, and only together with the rest of the pattern.

Operational counts (five payers, eight money orders, 70 percent onward, 30 days) are marked in the typology file. They are not statistics printed by CTAF. The documented case counts, 46 and 57 international money orders, are quoted in the explanation and are not the gate.

The older deterministic rules in `fraud_detection/rules/tunisia_rules.py` still run. They were not re-labeled as if they had been fit on the 2024 report.

## Context that is attached, not trained

When the channel maps onto a BCT instrument, the layer records the latest published average ticket and the ratio of this amount to that average. April 2025 bank cards average 176.35 TND in the saved table. The ratio is an aggregate comparison. It does not change `tunisia_score` and it does not by itself change the policy score.

ATM, DAB/GAB, and TPE-only averages are absent from the downloaded table, so a cash withdrawal does not receive a made-up channel baseline.

BCT monetary, trade, and reserve series are in `tunisia_macro_context.json` for calibration and documentation. They are not joined onto the payment as a training row. ILV1 and ILV2 do not share one obvious unit for the same reserve line, so neither series is forced into a feature.

## Training and evaluation rules that were not exercised

There is no Tunisian transaction table, so there is no chronological 70/15/15 split, no customer or beneficiary holdout, and no Tunisia model artifact. Global training already uses time splits on its own public datasets. That was not rerun.

Every future Tunisia model needs its own provenance report: source files, label definitions, split dates, and a statement that aggregate or case rows were not used as transactions. No such artifact was written, because no model was fit.

## Ablation

There is no Tunisia out-of-time test set. B–E were not computed. No improvement is claimed.

| Arm | What it would add | Result |
| --- | --- | --- |
| A | Existing global models | Not re-measured. Last public-data run, which is not a Tunisian test: IBM AML PR-AUC 0.283, ROC-AUC 0.975, precision@100 0.96; BankSim PR-AUC 0.778; ULB PR-AUC 0.717; Elliptic PR-AUC 0.645. PaySim PR-AUC 0.999 is a simulator result and is not the headline. |
| B | Global + Tunisia contextual aggregates | Not evaluated. No labeled Tunisia payments. |
| C | Global + Tunisia features | Not evaluated. Portable feature names were not changed. |
| D | Global + a Tunisia model | Not trained. |
| E | D + Tunisia rules | Not evaluated. Rules can fire and cite a CTAF page. That is not an out-of-time PR-AUC. |

Recall at 0.1%, 0.5%, and 1% FPR, calibration, and Brier score on Tunisian payments were not measured.

## Synthetic laboratory

`fraud_detection/data/synthetic_tunisia.py` remains a regression fixture. It is not training data for this layer and it is not described as Tunisian bank data.
