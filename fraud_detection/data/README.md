# Data laboratory

Keep every raw download immutable in its own folder. Do not concatenate sources into one training CSV: a PaySim fraud flag, an IBM laundering flag, and a procurement-risk flag are different targets.

These are public datasets. BankSim, PaySim, IBM AML, and SAML-D are synthetic or simulated. ULB is real anonymized card data. Elliptic is a real Bitcoin graph. Do not describe the simulators as real bank transactions.

```text
raw/ibm_aml/     raw/tabformer/   raw/saml_d/    raw/paysim/
raw/ieee_cis/    raw/handbook/    raw/banksim/   raw/elliptic/
raw/tunisia/     raw/sanctions/
genuine/
processed/canonical/
features/  labels/  splits/
```

Adapters in `adapters.py` map each file into the canonical transaction and set `dataset` plus `label_type`. Unlabeled Elliptic rows are skipped as training negatives. ULB PCA columns stay in metadata.

IEEE-CIS is non-commercial only. OpenSanctions needs a commercial license for commercial use. CTAF reports are typology sources for rules, not a labeled transaction file.

Genuine reference documents for the stamp check live in `genuine/`. They are part of this same project, not a separate dataset branch. The reader is `fraud_detection/documents`, called from `POST /v1/score`. Fake copies are not stored yet, and `genuine/manifest.json` keeps `trained` false.
