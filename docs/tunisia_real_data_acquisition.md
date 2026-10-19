# Acquiring real Tunisian transaction data

Public CTAF cases, BCT aggregates, and Findex indicators do not support a transaction-level Tunisia fraud model. The next data has to come from an institution that already holds payments and is allowed to share an anonymized extract.

This note is a request list. It does not describe a way around authentication, a paid RNE contract, or a BCT reporting gate.

## Who can lawfully provide it

1. Tunisian banks, under their own customer-data and secrecy rules, with a written research or vendor agreement.
2. Tunisian payment institutions.
3. Monétique Tunisie or another switch participant, for card, ATM/DAB/GAB, TPE, and e-commerce clearing totals or anonymized transactions they are permitted to share. No public SMT file was retrieved on 2026-10-06 (`www.smt.tn` timed out).
4. A BCT-licensed fintech or processor.
5. Merchants or acquirers, for their own anonymized card and TPE flow.
6. A university project that already has a bank data-sharing agreement. The agreement has to exist before the extract moves.
7. An authorized AML or financial-crime sharing arrangement with the CTAF or with reporting entities. CTAF annual reports are already public. The underlying suspicious-activity reports are not, and they are not requested in raw form here.

The Registre National des Entreprises public site (https://www.registre-entreprises.tn/rne-public/) is an application shell. Beneficial-owner and KYC web services require an account or a contract. That access was not bypassed. A future entity join should use a licensed RNE or open-data extract, not a scrape.

`catalog.data.gov.tn` did not complete a verified TLS handshake on 2026-10-06 because the server presented an intermediate that does not sign the leaf. The download was not retried with verification disabled.

## What to request

Anonymized payments only. The provider hashes identifiers before transfer. Hashes must be irreversible and salted or keyed on the provider side. The same account should hash to the same value inside one extract so velocity can be computed, and the salt must not be sent with the file.

Preferred columns:

- `transaction_id_hash`
- `timestamp`
- `amount_tnd`
- `original_currency`
- `fx_rate`
- `transaction_type`
- `channel`
- `sender_account_hash`
- `receiver_account_hash`
- `beneficiary_hash`
- `merchant_hash`
- `merchant_category`
- `issuer_hash`
- `acquirer_hash`
- `ATM_hash`
- `TPE_hash`
- `country_sender`
- `country_receiver`
- `domestic_or_cross_border`
- `card_present`
- `ecommerce`
- `mobile_payment`
- `cash_withdrawal`
- `device_hash`
- `session_hash`
- `ip_country`
- `customer_age_band_if_legally_available`
- `account_age_days`
- `historical_velocity`
- `previous_transaction_time`
- `available_balance_bucket_if_allowed`

Labels, only when the provider already has them. Missing labels stay missing.

- `confirmed_fraud`
- `suspected_fraud`
- `chargeback`
- `account_takeover`
- `card_fraud`
- `merchant_fraud`
- `money_mule`
- `aml_suspicion`
- `confirmed_aml_case`
- `sanctions_alert`
- `legitimate`
- `false_positive`
- `investigation_result`
- `fraud_confirmation_timestamp`
- `case_resolution`
- `chargeback_reason`
- `alert_source`
- `investigation_outcome`

Do not request or store PAN, CVV, PIN, passwords, authentication secrets, national ID numbers, or raw names and addresses. Age, if provided, should be a band. Balance, if provided, should be a bucket.

## How it would be used

- Chronological split: 70 percent train, 15 percent validation, 15 percent final out-of-time test, when the sample is large enough.
- No random split of one customer's history across train and test.
- No target, customer, account, beneficiary, future, or dataset-name leakage.
- Report PR-AUC, recall at 0.1 percent, 0.5 percent, and 1 percent false-positive rate, precision, calibration, and Brier score. ROC-AUC is secondary.
- Ablation A–E in `docs/tunisia_model_design.md` is recomputed on that out-of-time slice only.
- Until that file exists, `tunisia_score` stays null and Tunisia coverage stays below `HIGH`.

## Minimum useful extract

At least one full year of domestic and cross-border retail payments, with stable account hashes, channel, amount, timestamp, and a delayed label for confirmed fraud or a confirmed AML case. A file of suspicious-activity narratives without the underlying payments would stay case-based, like the CTAF reports already on disk.
