# Model evaluation

The system is trained and evaluated on multiple public datasets, including real anonymized transactions and large synthetic/simulated financial datasets.
BankSim, PaySim, and IBM AML HI-Small are synthetic or simulated. They are not a bank's real ledger, and this model was not trained on millions of real bank transactions.
ULB is the real-anonymized card exception. Elliptic is a real Bitcoin transaction graph, not bank payments.
These numbers were produced by `python -m fraud_detection.train_real` on this machine.
The behavioral API model is three LightGBM heads. Each head is trained only on the dataset whose label means that fraud type, and at scoring time that head runs only when the input matches the same family.
Validation and test rows are later time periods and include every row from that period.
PaySim and IBM training negatives are a reservoir of 180,000 rows, seed 0, drawn from the training period after features were computed on the full stream.
BankSim training keeps every row.
The decision threshold for precision, recall, F1, and the confusion matrix is 0.50 on the calibrated score when an isotonic calibrator was fit.
The headline behavioral result is IBM AML. PaySim's near-perfect scores are a real measurement of an easy simulator and are not the headline.
`risk_score` is a risk score from 0-100 produced by a deterministic evidence aggregation policy. It is not the probability of fraud.

## AML_LAUNDERING

Dataset: `ibm_aml`. Calibration: isotonic regression fit on the validation period.
Headline result. The source is synthetic AMLSim data and the positive rate is tiny, so cite PR-AUC and precision at 100.

| metric | value |
| --- | --- |
| test_rows | 761639 |
| test_positives | 1561 |
| pr_auc | 0.282590 |
| roc_auc | 0.975330 |
| precision | 0.542400 |
| recall | 0.217168 |
| f1 | 0.310156 |
| false_positive_rate | 0.000376 |
| tn | 759792 |
| fp | 286 |
| fn | 1222 |
| tp | 339 |
| precision_at_k | 0.960000 |
| recall_at_k | 0.061499 |
| precision_at_positive_count | 0.324151 |
| recall_at_positive_count | 0.324151 |
| threshold | 0.500000 |
| top_k | 100 |

Largest LightGBM split gains:

- `log_amount`: 819
- `hours_since_prev`: 679
- `out_count_7d`: 597
- `out_count_24h`: 460
- `amount_vs_median`: 450
- `out_count_1h`: 407
- `hour`: 401
- `in_sum_24h`: 388
- `out_sum_24h`: 338
- `in_count_24h`: 255

## CARD_FRAUD

Dataset: `banksim`. Calibration: isotonic regression fit on the validation period.
Synthetic BankSim bank-payment simulator. Respectable for a demo. The real anonymized card result is the ULB specialist.

| metric | value |
| --- | --- |
| test_rows | 89093 |
| test_positives | 960 |
| pr_auc | 0.778270 |
| roc_auc | 0.985691 |
| precision | 0.841755 |
| recall | 0.659375 |
| f1 | 0.739486 |
| false_positive_rate | 0.001350 |
| tn | 88014 |
| fp | 119 |
| fn | 327 |
| tp | 633 |
| precision_at_k | 1.000000 |
| recall_at_k | 0.104167 |
| precision_at_positive_count | 0.729167 |
| recall_at_positive_count | 0.729167 |
| threshold | 0.500000 |
| top_k | 100 |

Largest LightGBM split gains:

- `log_amount`: 1603
- `amount_vs_median`: 1119
- `amount_percentile`: 1089
- `out_sum_24h`: 688
- `out_count_7d`: 583
- `hours_since_prev`: 329
- `amount`: 261
- `is_new_counterparty`: 165
- `repeat_same_amount_72h`: 69
- `out_count_1h`: 67

## ACCOUNT_TAKEOVER

Dataset: `paysim`. Calibration: isotonic regression fit on the validation period.
Synthetic PaySim mobile money. Not the headline. Near-perfect scores come from simulator balance-drain features.

| metric | value |
| --- | --- |
| test_rows | 918617 |
| test_positives | 4006 |
| pr_auc | 0.998508 |
| roc_auc | 0.999251 |
| precision | 0.999750 |
| recall | 0.998502 |
| f1 | 0.999126 |
| false_positive_rate | 0.000001 |
| tn | 914610 |
| fp | 1 |
| fn | 6 |
| tp | 4000 |
| precision_at_k | 1.000000 |
| recall_at_k | 0.024963 |
| precision_at_positive_count | 0.998502 |
| recall_at_positive_count | 0.998502 |
| threshold | 0.500000 |
| top_k | 100 |

Largest LightGBM split gains:

- `log_amount`: 2480
- `hour`: 1485
- `amount_to_old_balance`: 892
- `amount`: 666
- `balance_mismatch`: 196
- `balance_zeroed`: 156
- `is_new_counterparty`: 49
- `is_round_1000`: 47
- `is_night`: 29
- `out_count_24h`: 0

## Population isolation forest

```json
{
  "trained_on_rows": 150000,
  "contamination": 0.01,
  "n_estimators": 200,
  "rows_per_dataset_cap": 50000,
  "fit_on": "legitimate training rows only",
  "score": "1 / (1 + exp(6 * decision_function)) after RobustScaler",
  "test": {
    "CARD_FRAUD": {
      "precision": 0.0,
      "recall": 0.0,
      "f1": 0.0,
      "pr_auc": 0.20751911231316783,
      "roc_auc": 0.922204580009758,
      "recall_at_fpr": 0.2791666666666667,
      "precision_at_k": 0.61,
      "recall_at_k": 0.06354166666666666,
      "false_positives_per_1000": 0.0,
      "tn": 88133,
      "fp": 0,
      "fn": 960,
      "tp": 0,
      "false_positive_rate": 0.0,
      "precision_at_positive_count": 0.2552083333333333,
      "recall_at_positive_count": 0.2552083333333333,
      "test_rows": 89093,
      "test_positives": 960,
      "threshold": 0.5,
      "top_k": 100,
      "dataset": "banksim"
    },
    "ACCOUNT_TAKEOVER": {
      "precision": 0.0,
      "recall": 0.0,
      "f1": 0.0,
      "pr_auc": 0.014124588016787853,
      "roc_auc": 0.8285914202964286,
      "recall_at_fpr": 0.01797304043934099,
      "precision_at_k": 0.0,
      "recall_at_k": 0.0,
      "false_positives_per_1000": 0.0,
      "tn": 914611,
      "fp": 0,
      "fn": 4006,
      "tp": 0,
      "false_positive_rate": 0.0,
      "precision_at_positive_count": 0.0,
      "recall_at_positive_count": 0.0,
      "test_rows": 918617,
      "test_positives": 4006,
      "threshold": 0.5,
      "top_k": 100,
      "dataset": "paysim"
    },
    "AML_LAUNDERING": {
      "precision": 0.0014655593551538837,
      "recall": 0.04612427930813581,
      "f1": 0.0028408530450393576,
      "pr_auc": 0.001606563486396447,
      "roc_auc": 0.38604263606385764,
      "recall_at_fpr": 0.0064061499039077515,
      "precision_at_k": 0.0,
      "recall_at_k": 0.0,
      "false_positives_per_1000": 64.40846647821343,
      "tn": 711022,
      "fp": 49056,
      "fn": 1489,
      "tp": 72,
      "false_positive_rate": 0.0645407445025379,
      "precision_at_positive_count": 0.0,
      "recall_at_positive_count": 0.0,
      "test_rows": 761639,
      "test_positives": 1561,
      "threshold": 0.5,
      "top_k": 100,
      "dataset": "ibm_aml"
    }
  },
  "general_behavior": {
    "trained_on_rows": 150000,
    "features": [
      "log_amount",
      "amount",
      "hour",
      "is_night",
      "is_round_1000",
      "is_cross_border",
      "out_count_1h",
      "out_count_24h",
      "out_sum_24h",
      "in_count_24h",
      "in_sum_24h",
      "unique_in_counterparties_24h",
      "unique_out_counterparties_24h",
      "is_new_counterparty",
      "repeat_same_amount_72h",
      "hours_since_prev",
      "account_age_days",
      "amount_over_monthly_revenue",
      "is_foreign_receiver",
      "in_out_ratio_6h",
      "amount_vs_median",
      "amount_percentile",
      "out_count_7d"
    ],
    "excluded": [
      "is_tnd",
      "bid_count",
      "award_to_estimate_ratio",
      "is_card",
      "has_invoice",
      "has_expense",
      "balance_mismatch",
      "amount_to_old_balance",
      "balance_zeroed"
    ],
    "fit_on": "legitimate training rows, portable columns only",
    "note": "Unsupervised suspicious-behavior score. Not a fraud-type label."
  }
}
```

## ulb

```json
{
  "precision": 0.8297872340425532,
  "recall": 0.75,
  "f1": 0.7878787878787878,
  "pr_auc": 0.7167731877134899,
  "roc_auc": 0.9643330052262767,
  "recall_at_fpr": 0.8461538461538461,
  "precision_at_k": 0.4,
  "recall_at_k": 0.7692307692307693,
  "false_positives_per_1000": 0.18726153414011845,
  "tn": 42661,
  "fp": 8,
  "fn": 13,
  "tp": 39,
  "false_positive_rate": 0.00018748974665447983,
  "precision_at_positive_count": 0.75,
  "recall_at_positive_count": 0.75,
  "test_rows": 42721,
  "test_positives": 52,
  "threshold": 0.5,
  "top_k": 100,
  "calibrated_on_rows": 42718,
  "train_rows": 199368,
  "train_positives": 384,
  "validation_rows": 42718,
  "validation_positives": 56,
  "dataset": "ulb_creditcard",
  "label": "CARD_FRAUD",
  "features": [
    "V1",
    "V2",
    "V3",
    "V4",
    "V5",
    "V6",
    "V7",
    "V8",
    "V9",
    "V10",
    "V11",
    "V12",
    "V13",
    "V14",
    "V15",
    "V16",
    "V17",
    "V18",
    "V19",
    "V20",
    "V21",
    "V22",
    "V23",
    "V24",
    "V25",
    "V26",
    "V27",
    "V28",
    "Amount"
  ],
  "excluded_from_features": [
    "Time",
    "Class"
  ],
  "train_time_end": 132929.0,
  "validation_time_end": 151328.0,
  "rows": 284807,
  "positives": 492,
  "used_by_api": true,
  "reason": "Loaded by POST /v1/score only when the request contains V1-V28. It does not replace the behavioral card head."
}
```

## elliptic

```json
{
  "precision": 0.9055690072639225,
  "recall": 0.5880503144654088,
  "f1": 0.7130600571973308,
  "pr_auc": 0.6454560796221334,
  "roc_auc": 0.9002359384950023,
  "recall_at_fpr": 0.6053459119496856,
  "precision_at_k": 0.97,
  "recall_at_k": 0.15251572327044025,
  "false_positives_per_1000": 3.4871244635193133,
  "tn": 10509,
  "fp": 39,
  "fn": 262,
  "tp": 374,
  "false_positive_rate": 0.003697383390216155,
  "precision_at_positive_count": 0.6147798742138365,
  "recall_at_positive_count": 0.6147798742138365,
  "test_rows": 11184,
  "test_positives": 636,
  "threshold": 0.5,
  "top_k": 100,
  "calibrated_on_rows": 5486,
  "train_rows": 29894,
  "train_positives": 3462,
  "validation_rows": 5486,
  "validation_positives": 447,
  "dataset": "elliptic",
  "label": "AML_LAUNDERING",
  "rows_in_features_file": 203769,
  "known_rows": 46564,
  "unknown_rows_excluded": 157205,
  "illicit_rows": 4545,
  "split": "timestep 1-34 train, 35-39 validation, 40-49 test",
  "features": "anonymous columns after txId and timestep; txId is not a feature",
  "used_by_api": false,
  "reason": "anonymized graph features are not the behavioral transaction schema"
}
```

## elliptic_graph

```json
{
  "edges": 234355,
  "illicit_transactions": 4545,
  "licit_transactions": 42019,
  "unknown_transactions": 157205,
  "fan_in_at_least_10": 1912,
  "fan_out_at_least_10": 758,
  "max_in_degree": 284,
  "max_out_degree": 472,
  "edges_touching_illicit": 8145,
  "edges_between_illicit": 998
}
```

## ibm_graph

```json
{
  "edges": 5078345,
  "fan_in_at_least_10": 178243,
  "fan_out_at_least_10": 110008,
  "max_in_degree": 1084,
  "max_out_degree": 168672,
  "laundering_edges": 5177
}
```

## ibm_cycles

```json
{
  "laundering_edges": 5177,
  "nodes": 6357,
  "edges": 4936,
  "cycles_found_capped_at_200": 200,
  "cycle_length_bound": 5
}
```

## saml_d

```json
{
  "status": "validated_not_used_for_training",
  "rows": 9504852,
  "positives": 9873,
  "missing_amount": 0,
  "min_date": "2022-10-07",
  "max_date": "2023-08-23",
  "columns": [
    "Amount",
    "Date",
    "Is_laundering",
    "Laundering_type",
    "Payment_currency",
    "Payment_type",
    "Received_currency",
    "Receiver_account",
    "Receiver_bank_location",
    "Sender_account",
    "Sender_bank_location",
    "Time"
  ],
  "free_ram_bytes_at_decision": 10817466368,
  "reason": "Row counts were measured. The API AML model stays on IBM HI-Small only. A second 9.5M-row feature pass was not run in this memory budget."
}
```

## sanctions

```json
{
  "counts": {
    "OFAC_SDN": 39187,
    "UN": 3731,
    "EU": 30475
  },
  "entries": 73393,
  "available": true,
  "aerocaribbean_match": true,
  "aerocaribbean_score": 1.0,
  "aerocaribbean_list": "OFAC_SDN"
}
```

## demo

```json
{
  "transaction_id": "paysim-C803411135-C1325722809-185",
  "history_rows": 1,
  "risk_score": 75,
  "decision": "HIGH_RISK",
  "label_types": [
    "ACCOUNT_TAKEOVER"
  ],
  "supervised": 1.0,
  "supervised_by_type": {
    "ACCOUNT_TAKEOVER": 1.0
  },
  "anomaly": 0.1996,
  "sanctions_status": "no_name_supplied",
  "risk_score_meaning": "0-100 deterministic evidence aggregation policy, not a fraud probability"
}
```

## Limitations

- The API behavioral model was trained on three public simulators: BankSim, IBM AML HI-Small, and PaySim. It was not trained on millions of real bank transactions. ULB is loaded by `/v1/score` when `V1`–`V28` are present. Elliptic is not loaded.
- Prevalence, Brier score, calibration, the validation threshold sweep, and the validation-only LightGBM comparison are in `operating_points.json`. Candidates were compared on the last 30% of validation. The test set was not used to choose a model or a threshold. No candidate cleared a 0.02 validation-tail PR-AUC gain without a precision drop, so the saved heads were kept.
- SAML-D, TabFormer, the Fraud Detection Handbook simulator, IEEE-CIS, CTAF extracts, and Tunisian registry microdata were not fitting data for these heads.
- A supervised head scores an input only when that input matches its family. A PaySim cash-out cannot receive CARD_FRAUD from the BankSim head.
- Streaming features keep hourly buckets for seven days, cap unique counterparties at 48, and drop accounts idle for eight days. Scoring uses the same class, so the approximation is shared by training and the API.
- PaySim has no currency or country. USD is an assumption and country is empty, so `is_tnd` is 0. Its near-perfect metrics are not the headline.
- BankSim has no currency or country. EUR is an assumption, the clock is fixed at 12:00, and the age field is not used as account age. It is a synthetic bank-payment simulator.
- IBM AML transactions are synthetically generated by AMLSim.
- Synthetic Tunisia scenarios are regression tests. They are not real Tunisian bank transactions and they are not in this training run.
- risk_score is a policy score from 0-100, not P(fraud).
- A sanctions miss is returned only when a list is loaded. An empty index returns `sanctions_status=not_available`.

## Final tuning pass

The saved test metrics above were reproduced from the current artifacts. A four-configuration LightGBM comparison, plus IBM hard-negative mining, was scored only on the chronological validation tail. Nothing was adopted.

| Model | Validation-tail PR-AUC, current refit | Best other candidate | Gain | Adopted |
| --- | ---: | ---: | ---: | --- |
| CARD_FRAUD | 0.861 | current | 0 | no |
| ACCOUNT_TAKEOVER | 1.000 | current | 0 | no |
| AML_LAUNDERING | 0.112 | wider, 0.119 | 0.007 | no |
| ULB | 0.913 | shallow, 0.923 | 0.010 | no |

IBM AML test prevalence is 0.00205. Test PR-AUC 0.283 is about 138 times that random baseline. Test precision at 50 is 1.00. Most missed validation positives are ordinary new-beneficiary payments: median amount-versus-sender-median is 1.06, and median 24-hour outgoing count is 2. Caught positives have a shorter gap since the previous payment and a higher 6-hour in/out ratio. Balance, country, currency, invoice, and procurement columns are constant on this file, so they do not drive the head. A larger negative reservoir was not refit: hard-negative mining on the existing training reservoir already targeted the difficult legitimate rows and did not clear the gain bar.
