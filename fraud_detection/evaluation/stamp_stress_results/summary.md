# Stamp stress test

Do not read these rates as performance on unseen printed forgeries. The supervised stamp model was trained on crops from these same four documents. Generated variations and single-feature edits are stress tests. They are counted separately and are not extra real counterfeits.

## Commands

```bash
.venv/bin/python -m fraud_detection.evaluation.stamp_stress
```

Results directory: `/workspace/fraud_detection/evaluation/stamp_stress_results`.
Cases: 680. Seed: 11. Enrollment directory was temporary and was deleted.

## Dataset

Four fictitious stamp identities, 50 reference pages and 50 counterfeit pages each (400 labeled pages), plus four genuine PDFs. Filename suffix is the only label in this checkout. `labels.csv` (difficulty, mutations) described in the dataset README is absent. Reference pages are scan-style copies of one stamp per document. Counterfeit pages are generated mutations of that stamp, not photographed forgeries.

## Baseline, same family

Each genuine PDF was enrolled for its own company. Every labeled page of that family was then scored. A counterfeit counted as detected only when the verdict was `fraudulent`. `uncertain` and `unrecognized` are separate.

- Reference pages: 200. Accepted as genuine: 9 (0.045).
- Called fraudulent (false rejection): 0 (0.0).
- Reference uncertain: 191. Reference unrecognized: 0.
- Counterfeit pages: 200. Accepted as genuine: 0 (0.0).
- Called fraudulent: 13 (0.065).
- Counterfeit uncertain: 187. Counterfeit unrecognized: 0.
- Review recommended: 191 / 200 reference pages, 200 / 200 counterfeit pages.
- High risk tier: 0 reference, 13 counterfeit. A high tier queues a person. It is not a fraud probability.
- Precision / recall / F1 for the fraudulent verdict: 1.0 / 0.065 / 0.1221.
- Stamp detected on labeled pages: 400 (1.0). OCR empty when a stamp was detected: 0.

Confusion matrix (rows are ground truth, columns are the verdict):

| Ground truth | genuine | fraudulent | uncertain | unrecognized | other |
| --- | --- | --- | --- | --- | --- |
| reference | 9 | 0 | 191 | 0 | 0 |
| counterfeit | 0 | 13 | 187 | 0 | 0 |

The filename holdout (`zlib.crc32(name) % 5 == 0`) is the split used by `train_stamps.py`. It is not a held-out stamp identity. The model was trained on this same four-document set, so these rates are not an independent trial.

- Holdout references accepted as genuine: 1/43 (0.0233).
- Holdout references called fraudulent: 0.
- Holdout counterfeits accepted as genuine: 0/42 (0.0).
- Holdout counterfeits called fraudulent: 6 (0.1429).
- Holdout counterfeits uncertain: 36.

## Genuine variations of the enrolled PDF

These are synthetic scan changes of the enrolled genuine page. Mild cases are the ones a normal scan should still accept. A hard blur or a strong perspective warp may legitimately be uncertain. Calling one fraudulent is recorded, and it is a false rejection only when the stamp is still intact.

| Severity | n | genuine | uncertain | fraudulent | unrecognized | other |
| --- | --- | --- | --- | --- | --- | --- |
| mild | 48 | 22 | 26 | 0 | 0 | 0 |
| medium | 28 | 3 | 25 | 0 | 0 | 0 |
| hard | 20 | 1 | 19 | 0 | 0 | 0 |

## Controlled edits

One feature of the enrolled crop was changed, then pasted on a clean page. These are not real counterfeits. A genuine verdict here is a false accept of a modified drawing.

- n: 28. Predicted genuine: 4. Fraudulent: 2. Uncertain: 22. Unrecognized: 0.

## Other legitimate stamps

A reference page or genuine PDF from another organization. Expected verdict: unrecognized. Fraudulent is the wrong accusation.

- n: 141. Unrecognized: 129. Uncertain: 12. Genuine: 0. Fraudulent: 0.

## API workflow

- enroll_proposal: pass — awaiting_approval
- decline_saves_nothing: pass — {'proposal_id': 'bf1ac1d9ba4343ea85af9be7e5bad908', 'decision': 'declined', 'enrolled': False, 'reason': 'declined', 'specimen_id': None, 'kind': 'stamp', 'entity_id': 'company-a', 'comment': None}
- approve_enrolls: pass — saved
- exact_resubmit_stable: pass — genuine then genuine, specimens=1
- darker_scan: pass — genuine
- other_organization: pass — unrecognized
- company_isolation: pass — awaiting_approval
- restart_keeps_reference: pass — genuine
- unknown_proposal: pass — unknown_proposal
- invalid_kind: pass — kind must be stamp or signature
- malformed_image: pass — ['document_unreadable']
- malformed_pdf: pass — ['document_unreadable']
- blank_page: pass — missing

## False accepts (counterfeit page called genuine)

- None.

## Genuine pages called fraudulent

- None.

## Assessment

The four enrolled genuine PDFs can be recognized, and a different organization's stamp is not automatically called fraudulent. The system is a stamp similarity and anomaly screening prototype, not a guaranteed forgery detector. On the labeled pages, 0 counterfeit pages were accepted as genuine. Most counterfeits are uncertain or unrecognized, which asks for a person rather than declaring fraud. There are only four stamp identities. The 400 pages are scan and mutation variants of those four, and the LightGBM model was trained on this same set. That is not an independent live-counterfeit trial.

