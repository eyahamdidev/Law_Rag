# Stamp stress test

The narrative report with the failure lists is `fraud_detection/evaluation/STAMP_STRESS_REPORT.md`.

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

- Reference pages: 200. Accepted as genuine: 0 (0.0).
- Called fraudulent (false rejection): 0 (0.0).
- Reference uncertain: 145. Reference unrecognized: 49.
- Counterfeit pages: 200. Accepted as genuine: 1 (0.005).
- Called fraudulent: 23 (0.115).
- Counterfeit uncertain: 119. Counterfeit unrecognized: 46.
- Precision / recall / F1 for the fraudulent verdict: 1.0 / 0.115 / 0.2063.
- Stamp detected on labeled pages: 383 (0.9575). OCR empty when a stamp was detected: 0.

Confusion matrix (rows are ground truth, columns are the verdict):

| Ground truth | genuine | fraudulent | uncertain | unrecognized | other |
| --- | --- | --- | --- | --- | --- |
| reference | 0 | 0 | 145 | 49 | 6 |
| counterfeit | 1 | 23 | 119 | 46 | 11 |

The filename holdout (`zlib.crc32(name) % 5 == 0`) is the split used by `train_stamps.py`. It is not a held-out stamp identity. The model was trained on this same four-document set, so these rates are not an independent trial.

- Holdout references accepted as genuine: 0/43 (0.0).
- Holdout references called fraudulent: 0.
- Holdout counterfeits accepted as genuine: 0/42 (0.0).
- Holdout counterfeits called fraudulent: 5 (0.119).
- Holdout counterfeits uncertain: 23.

## Genuine variations of the enrolled PDF

These are synthetic scan changes of the enrolled genuine page. Mild cases are the ones a normal scan should still accept. A hard blur or a strong perspective warp may legitimately be uncertain. Calling one fraudulent is recorded, and it is a false rejection only when the stamp is still intact.

| Severity | n | genuine | uncertain | fraudulent | unrecognized | other |
| --- | --- | --- | --- | --- | --- | --- |
| mild | 48 | 26 | 12 | 1 | 1 | 8 |
| medium | 28 | 3 | 18 | 1 | 4 | 2 |
| hard | 20 | 3 | 7 | 2 | 7 | 1 |

## Controlled edits

One feature of the enrolled crop was changed, then pasted on a clean page. These are not real counterfeits. A genuine verdict here is a false accept of a modified drawing.

- n: 28. Predicted genuine: 10. Fraudulent: 5. Uncertain: 10. Unrecognized: 3.

## Other legitimate stamps

A reference page or genuine PDF from another organization. Expected verdict: unrecognized. Fraudulent is the wrong accusation.

- n: 141. Unrecognized: 135. Uncertain: 0. Genuine: 0. Fraudulent: 0.

## API workflow

- enroll_proposal: pass — awaiting_approval
- decline_saves_nothing: pass — {'proposal_id': '1117f806ac854deca3f844b48bdf0263', 'decision': 'declined', 'enrolled': False, 'reason': 'declined', 'specimen_id': None, 'kind': 'stamp', 'entity_id': 'company-a', 'comment': None}
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

- `labellisation_0083_counterfeit.jpg` enrolled `labellisation` ncc=0.9016 p=0.0293 status=match

## Genuine pages called fraudulent

- `balance:perspective_0.10` (variation, hard) ncc=0.5143 p=0.0027
- `capital:rot_p2` (variation, mild) ncc=0.6393 p=0.1106
- `subvention:rot_p12` (variation, hard) ncc=0.6353 p=0.0008
- `subvention:perspective_0.04` (variation, medium) ncc=0.5664 p=0.0114

## Assessment

The four enrolled genuine PDFs can be recognized, and a different organization's stamp is not automatically called fraudulent. The system is not ready to claim that close counterfeits are reliably rejected. On the labeled pages, many counterfeits are uncertain rather than fraudulent, and some are accepted as genuine. There are only four stamp identities. The 400 pages are scan and mutation variants of those four, and the LightGBM model was trained on this same set. That is not an independent live-counterfeit trial.

