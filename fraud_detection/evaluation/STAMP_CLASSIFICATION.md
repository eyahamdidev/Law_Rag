# Labeled stamp classification

The 680-case stress run left every counterfeit page uncertain or unrecognized. That avoided false approvals and also failed to name a counterfeit. This pass separates four questions and scores the labeled pages with the live checker.

1. Is this a stamp identity the company has enrolled?
2. Does the drawing match that genuine stamp closely enough to call it genuine?
3. Is there positive evidence the drawing was altered?
4. Is the evidence too weak or in conflict, so the verdict stays uncertain?

A low alignment score is not fraud. A high alignment score, or a low LightGBM score, is not proof the stamp is genuine. Another organization's stamp stays unrecognized unless the drawing shows a local alteration of an enrolled stamp.

The LightGBM stamp model was not retrained.

## Why counterfeits were not called fraudulent

`stamp_verdict` returned fraudulent only for a strong one-sided hole: aligned score at least 0.97 and a brightness peak of at least 100 that was at least twice the opposite residual. The labeled counterfeits are not holes. They are mutated drawings (spacing, font, baseline, oval or rectangle geometry) plus the same scan augmentation used on the genuine pages. Their residual is two-sided, or the whole drawing fails to line up. Both of those were uncertain on purpose, because a genuine page rotated by 2°, a perspective warp, and a 12° turn had been called fraudulent by the older "same words and score under 0.72" rule.

The packaged model does not separate the classes once the anchor is the enrolled PDF. On the filename holdout its validation PR-AUC is 0.824, with genuine recall 0.784 and counterfeit recall 0.75, at threshold 0.30. Leave-one-document-out PR-AUC is 0.506 (balance), 0.548 (capital), 0.536 (labellisation), and 0.530 (subvention). Training PR-AUC on the same four designs is 0.9999. The model is remembering those designs. OCR does not separate them either: balance, capital, and subvention read as the same wording on both classes, and labellisation reads as different on both.

## Training split

Labels are the filename suffixes `_reference` and `_counterfeit`. All 400 page names carry one of those suffixes. The training split is `zlib.crc32(name) % 5 == 0` inside each document, so crops and their scan copies of one source page can sit on opposite sides of the split, and every stamp identity appears in both sides. There is no fifth identity to hold out. Four source documents, with one shared scan process, are not a large enough set for an identity-independent test. The eight-file run below is a demonstration.

Retraining LightGBM on these pairs is not justified. A model fit on three identities and tested on the fourth does not beat chance in any useful way, and a model fit inside one identity would leak that identity into the weights.

## What the checker uses instead

After alignment, two measurements were added in `compare_drawings`:

- `row_corr`: correlation of the horizontal ink profile. A moved or resized text line breaks it. A small blur does not.
- `low_block`: share of informative 6×6 blocks whose ink correlation is under 0.55, plus the mean absolute error of the aligned grayscale.

Fraud requires the same wording, a recovered pose (aligned score from 0.30 up to but not including 0.82, weakest block at least −0.18), and a text-line profile below the enrolled stamp's own harmless recaptures. That floor is the weaker of a +6° turn, a −6° turn, and a 1.2 px blur, minus 0.09. The margin sits under every genuine reference page of the four PDFs. It was not chosen to maximize counterfeit recall. A pose that fails (`local_min` under −0.18, including the capital 12° turn and the gray and brightened balance pages) stays uncertain.

A genuine verdict for a close scan requires text-line agreement of at least 0.97, aligned score at least 0.955, weakest block at least 0.50, mean absolute error at most 8, and a low-block share of at most 0.02. The model probability is not consulted for that shortcut. A different wording with an aligned score under 0.50 is unrecognized. Labellisation scans of the same stamp sit above 0.50 even when OCR is noisy, so they are uncertain rather than offered as a new organization. Foreign stress pages stay under 0.23.

Subtle copies (ink shade, a tiny spacing change, a small stamp rotation) stay inside the scan envelope and remain uncertain. `subvention_0067_counterfeit.jpg` has a text-line score of 0.9052 against a floor of 0.9043, so it stays uncertain. The margin was not tightened to catch that one file.

## Labeled pages

Each family was enrolled from its genuine PDF, then all 100 pages were checked with `SpecimenStore.check`. Uploaded scans are kept at their native size (1404 px). The PDF render is limited to 1200 px. Command: `.venv/bin/python -m fraud_detection.evaluation.stamp_classification`.

| | Genuine | Fraudulent | Uncertain | Unrecognized | Missing |
| --- | --- | --- | --- | --- | --- |
| 200 reference pages | 9 | 0 | 191 | 0 | 0 |
| 200 counterfeit pages | 0 | 13 | 187 | 0 | 0 |

By family, reference then counterfeit:

| Family | Reference genuine / uncertain | Counterfeit fraudulent / uncertain |
| --- | --- | --- |
| balance | 0 / 50 | 7 / 43 |
| capital | 5 / 45 | 6 / 44 |
| labellisation | 0 / 50 | 0 / 50 |
| subvention | 4 / 46 | 0 / 50 |

No reference page is called fraudulent. No counterfeit page is called genuine. Labellisation stays uncertain because the wording comparison does not confirm the identity, and fraud is not declared from the drawing alone. Most counterfeits are subtle relative to the scan noise and stay uncertain. The 13 fraudulent calls are the pages whose text lines actually miss.

## Eight-document demonstration

Selection, after the rule was frozen, in filename order: the first four reference pages the checker calls genuine, and the first four counterfeit pages it calls fraudulent. Labellisation and subvention have no fraudulent call, so they are absent. These files come from the same four source documents the floor was inspected on. This is not an independent evaluation.

They were then sent through `POST /v1/score` with the capital PDF and the balance PDF enrolled for receiver `demo-company` (`POST /v1/documents/decide`). The subvention PDF was scored against that store and was not enrolled.

| Filename | Ground truth | Verdict | Aligned score | Model score |
| --- | --- | --- | --- | --- |
| capital_0000_reference.jpg | reference | genuine | 0.9754 | 0.0193 |
| capital_0005_reference.jpg | reference | genuine | 0.9674 | 0.0041 |
| capital_0014_reference.jpg | reference | genuine | 0.9648 | 0.0120 |
| capital_0021_reference.jpg | reference | genuine | 0.9694 | 0.0142 |
| balance_0028_counterfeit.jpg | counterfeit | fraudulent | 0.6952 | 0.0154 |
| balance_0036_counterfeit.jpg | counterfeit | fraudulent | 0.6402 | 0.0408 |
| balance_0044_counterfeit.jpg | counterfeit | fraudulent | 0.4784 | 0.0005 |
| balance_0047_counterfeit.jpg | counterfeit | fraudulent | 0.6155 | 0.0002 |

`decision_attribution_subvention.pdf` against the capital and balance stamps is unrecognized (aligned score 0.1818) and is offered for enrollment. `capital_0008_counterfeit.jpg`, a subtle copy, is uncertain (aligned score 0.9230, model score 0.0061) and is not accepted.

Shrinking the 1404 px scans to 1200 px, which the API used to do, dropped `capital_0000_reference.jpg` to 0.8985 and left it uncertain, while the same shrink left `capital_0008_counterfeit.jpg` at 0.9251. The upload path now keeps scans up to 1600 px so that thumbnail is not applied to these pages. The enrolled PDF is still the 1200 px render the rule was measured on.

`tests/test_stamp_robustness.py`, `tests/test_stamp_verifier.py`, and `tests/test_documents.py`: 28 passed. The pre-existing missing BankSim CSV failure in `tests/test_real_inference.py` is unrelated.
