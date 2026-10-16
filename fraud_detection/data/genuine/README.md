# Genuine documents

These four PDFs sit with the rest of the project data. The stamp reader that uses them is `fraud_detection/documents`, on the same score call as the payment model. Each file is a single page.

| Id | File | Document |
| --- | --- | --- |
| `labellisation_startup` | `attestation_labellisation_startup.pdf` | Attestation de labellisation Startup Act |
| `liberation_capital` | `attestation_liberation_capital.pdf` | Attestation de libération du capital social |
| `solde_bancaire` | `attestation_solde_bancaire.pdf` | Attestation de solde bancaire |
| `attribution_subvention` | `decision_attribution_subvention.pdf` | Décision d'attribution de subvention |

They are reference documents, not an enrolled stamp. The live enrollment store in `fraud_detection/data/specimens/` starts empty so each user crops and saves their own genuine stamp.

Labeled genuine and counterfeit crops used to train the supervised verifier are in `fraud_detection/data/stamp_dataset_v2/`. Train with `python -m fraud_detection train-stamps`. That training does not enroll these PDFs.

`manifest.json` records the same list and keeps `trained` false, because these files are not preloaded into a user's store.
