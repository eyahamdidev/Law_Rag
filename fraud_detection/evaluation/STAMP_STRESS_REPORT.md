# Stamp stress test

Two executed runs of the same 680-case suite. The enrollment store was a temporary directory and was deleted. No original sample was modified. The LightGBM stamp model was not retrained.

The first run is the baseline, kept in `fraud_detection/evaluation/stamp_stress_baseline/`. The second run is after the decision and finder changes, in `fraud_detection/evaluation/stamp_stress_results/`.

The hole cutoff was taken from the four enrolled PDFs, not from the 400 labeled pages. On those PDFs a brightness or JPEG change stays under a peak of 20 once the drawing already lines up (aligned score at least 0.97). A hole that removes ink on the balance and labellisation stamps peaks at 118 or more. The gate sits at 40 in that gap. It was not swept against this suite.

There are only four stamp identities. The filename holdout (`zlib.crc32(name) % 5 == 0`) is not a held-out stamp. The model was trained on crops from these same four documents. These rates are not an independent trial of unseen printed counterfeits. Generated variations and single-feature edits are stress tests, not extra real forgeries.

The tables in sections 5–8 are the 680-case run at `f141fa8`, before the text-line rule. Section 9 is the rerun after that rule, with the model score removed from the verdict. The files in `stamp_stress_results/` are the section 9 run. Seed 11. 680 cases. Exit code 0.

## 1. Dataset inventory

| Group | Count | Label source |
| --- | --- | --- |
| Genuine PDFs | 4 | `fraud_detection/data/genuine/README.md` |
| Reference pages | 200 (50 × balance, capital, labellisation, subvention) | filename suffix `_reference` |
| Counterfeit pages | 200 (50 × the same four families) | filename suffix `_counterfeit` |
| Stamp crops | 200 reference + 200 counterfeit | same suffixes |

Every page and crop filename carries one of those two suffixes. None were unlabeled.

The dataset README says each family also has `labels.csv` with `difficulty` and `mutations`. That CSV is not in this checkout. Difficulty and the exact mutation list were not invented.

- One fictitious stamp identity per family.
- Reference pages are scan-style copies of that stamp, not 200 different genuine organizations.
- Counterfeit pages are generated mutations of that same stamp. They are not photographed forgeries.

## 2. What changed

The model file was not touched.

1. **Alignment search.** The shift is now scored at every angle from −14° to 14°. Previously only angles whose unshifted score was already near the best were shifted, so a 2° turn of the capital page scored 0.639 and was called fraudulent. The same page now scores 0.807 and is uncertain.
2. **A low score is not fraud.** Failing to line a stamp up returns uncertain. A fraudulent verdict now requires a compact patch of missing ink on a drawing that otherwise lined up (aligned score at least 0.97, one-sided brightness peak at least 100).
3. **OCR mismatch.** A wording mismatch is genuine only when the drawing is near-perfect, or when the aligned score is at least 0.87, the weakest block is at least 0.55, and the model score is at least 0.45. `labellisation_0083_counterfeit.jpg` (aligned score 0.9016, model score 0.0293) is uncertain.
4. **Finder.** Color ink is grouped at chroma 28, and a miss is retried at 20 so a light-blue text stamp survives JPEG. A grayscale page groups ink that sits just under the paper, and a stamp touching the page edge can be narrower. Starting at chroma 12 was tried and rejected: it widened good crops and, with two stamps on the page, picked the wrong one.

## 3. How a verdict is chosen

Company key: `document.entity_id`, otherwise the payment `receiver_id`. There is no login. Another company's stamps are not read.

1. Find a stamp-sized ink region. A missing stamp is not genuine.
2. Read the words (Tesseract, French and English).
3. Align the drawing (paper lift, rotation, scale, and shift) and measure the brightest 8×8 patch of missing ink.
4. **Fraudulent** when the words match and a large patch of ink is missing from an otherwise aligned drawing, or when the words match, the pose was recovered, and the horizontal text-line profile is worse than a harmless recapture of the enrolled stamp. A low alignment score alone is not fraud. Nothing is enrolled.
5. **Genuine** when the aligned drawing is a close scan (score at least 0.955, text-line agreement at least 0.97, mean absolute error at most 8, weakest-block share at most 0.02), or when the aligned score is at least 0.992 and the weakest block is at least 0.90, with no missing-ink patch. A wording mismatch can still be genuine when the model score is at least 0.45 and the aligned score is at least 0.87. A model score by itself is not proof.
6. **Unrecognized** when there are no usable words and the aligned score is under 0.50, or the words differ and the aligned score is under 0.50. A foreign stamp in the stress set stays under 0.23. The caller may enroll it as a new stamp.
7. **Uncertain** otherwise, including a failed alignment, a subtle copy inside the scan envelope, and a wording mismatch the model does not support. Nothing is enrolled.

`genuine_probability` is the stamp model's score. It is not a calibrated probability.

## 4. Command

```bash
.venv/bin/python -m fraud_detection.evaluation.stamp_stress
```

Seed 11. Both runs finished with 680 cases. The baseline copy is `stamp_stress_baseline/`. The current copy is `stamp_stress_results/`.

## 5. Labeled pages against the enrolled PDF

| | Before | After |
| --- | --- | --- |
| Reference pages accepted as genuine | 0 / 200 | 0 / 200 |
| Reference pages called fraudulent | 0 / 200 | 0 / 200 |
| Reference uncertain / unrecognized / missing | 145 / 49 / 6 | 151 / 49 / 0 |
| Counterfeits accepted as genuine | 1 / 200 | 0 / 200 |
| Counterfeits called fraudulent | 23 / 200 | 0 / 200 |
| Counterfeits uncertain / unrecognized / missing | 119 / 46 / 11 | 155 / 45 / 0 |
| Stamp found on labeled pages | 383 / 400 | 400 / 400 |

The one false accept, `labellisation_0083_counterfeit.jpg`, is now uncertain.

The 23 counterfeits that were called fraudulent were called that because the words matched and the aligned score was under 0.72. That is the same rule that accused a genuine page rotated by 2°. They are now uncertain or unrecognized. None are genuine. Explicit fraud on this set is no longer "the score is low." A low score asks for a person.

Filename holdout, after: 0 / 43 reference pages genuine, 0 / 42 counterfeits genuine, 0 / 42 counterfeits fraudulent, 34 counterfeits uncertain. This split does not separate stamp identities.

## 6. Genuine variations of the enrolled PDF

96 synthetic scan changes. A fraudulent verdict here is a false accusation.

| Severity | n | genuine before → after | fraudulent before → after | missing before → after |
| --- | --- | --- | --- | --- |
| mild | 48 | 26 → 26 | 1 → 0 | 8 → 0 |
| medium | 28 | 3 → 4 | 1 → 0 | 2 → 0 |
| hard | 20 | 3 → 2 | 2 → 0 | 1 → 0 |

No genuine variation is called fraudulent. The capital page at +2°, the subvention page at +12°, and the perspective cases that were fraudulent are uncertain.

Mild by family, after (12 transforms each): balance 3 genuine and 9 uncertain; capital 7 genuine and 5 uncertain; labellisation 7 genuine and 5 uncertain; subvention 9 genuine and 3 uncertain. Balance is no longer missing under JPEG, brightness, contrast, color, or grayscale. Two of those are uncertain because the grayscale and brightened crops are loose (aligned scores 0.22 and 0.17). The stamp is found.

Two mild labellisation cases that were genuine are now uncertain: scale 0.85 (model score 0.383) and color 0.70 (model score 0.283). The words did not match and the model score is under 0.45, so they are not promoted.

## 7. Controlled edits

One change to the enrolled crop, pasted on a white page. These are not real counterfeits. A genuine verdict is a false accept of a modified drawing.

| Edit | Before (4 families) | After |
| --- | --- | --- |
| 14×14 white center | 4 genuine | balance fraudulent; capital and labellisation uncertain; subvention genuine |
| 32×32 white center | 3 genuine, balance uncertain | capital fraudulent; the other three uncertain |
| Ink shifted toward red | 3 genuine, capital uncertain | same |
| Band shift, erased border, thicker lines | mixed, 5 fraudulent | uncertain or unrecognized, none genuine |

10 genuine accepts became 4. The four that remain are the three red-ink shifts and the subvention 14×14 hole. The red shift does not change the grayscale drawing, so it is not treated as a forgery. The subvention hole sits on blank paper in the middle of the oval (missing-ink peak 21, under the gate of 40). A 14×14 or 32×32 hole that actually removes ink is no longer accepted on global correlation.

## 8. Other organizations, edges, and the API

Other legitimate stamps: 141 cases. Before: 135 unrecognized, 6 missing, 0 genuine, 0 fraudulent. After: 129 unrecognized, 12 uncertain, 0 genuine, 0 fraudulent. The 6 that were missing are found. Twelve pages whose aligned score sits just above 0.20 are uncertain instead of unrecognized. None are called fraudulent.

Edges:

- Grayscale capital PDF: missing → found, uncertain.
- Stamp against the top-right edge: missing → found, unrecognized (only a sliver of the oval is on the page).
- Capital and subvention together, capital enrolled: still genuine.
- Blank page and a stamp reduced to one fifth: still missing.
- Solid blue square: still unrecognized.

API workflow, all passing in both runs: declined enrollment saves nothing, company isolation holds, an exact resubmit stays genuine, a darker scan stays genuine, another organization is unrecognized, a malformed image and a malformed PDF return `document_unreadable`.

## 9. Rerun after the reference rule

Command, after the text-line rule and after the model score was removed from the verdict:

```bash
.venv/bin/python -m fraud_detection.evaluation.stamp_stress
```

Seed 11. 680 cases. Exit code 0. This replaced `stamp_stress_results/`.

| | f141fa8 | This rerun |
| --- | --- | --- |
| Reference pages genuine | 0 / 200 | 9 / 200 |
| Reference pages fraudulent | 0 / 200 | 0 / 200 |
| Reference uncertain / unrecognized | 151 / 49 | 191 / 0 |
| Counterfeits genuine | 0 / 200 | 0 / 200 |
| Counterfeits fraudulent | 0 / 200 | 13 / 200 |
| Counterfeits uncertain / unrecognized | 155 / 45 | 187 / 0 |
| Stamp found | 400 / 400 | 400 / 400 |
| Genuine variations called fraudulent | 0 / 96 | 0 / 96 |
| Mild / medium / hard variations genuine | 26 / 4 / 2 | 22 / 3 / 1 |
| Other organizations fraudulent or genuine | 0 / 141 | 0 / 141 |
| Other organizations unrecognized / uncertain | 129 / 12 | 129 / 12 |

The 13 fraudulent calls are all `local_ink_anomaly`. The 9 genuine calls are all `reference_match`. Precision on those 13 calls is 1.0 inside this generated set. That is not a real-world false-positive rate.

Six mild, medium, and hard variations that the model score used to call genuine are now uncertain. None became fraudulent. Foreign pages are unchanged: none genuine, none fraudulent.

Controlled edits: balance 14 px hole and capital 32 px hole are fraudulent. The subvention 14 px hole sits on blank paper and stays genuine. Red-channel ink shifts stay genuine or uncertain, not fraudulent. API checks in the suite all passed, including declined enrollment, company isolation, exact resubmit, darker scan, and another organization unrecognized.

## 10. What is still weak

- 191 / 200 reference pages and 187 / 200 generated counterfeits are uncertain. Abstaining is the supported decision for a subtle mutation inside the scan envelope.
- Labellisation produces no genuine and no fraudulent verdict. OCR does not confirm the identity, and the drawing is not in the close-scan band.
- A hole on blank paper and a color-only ink shift are still not treated as forgery.
- The filename holdout is not an unseen stamp. One reference page in that slice is genuine and six counterfeit pages are fraudulent. That slice still shares the four identities.
- No independently printed counterfeit has been tested. The real-world false-acceptance rate is unknown.

The engineering decision and the policy comparison are in `STAMP_ENGINEERING_REPORT.md`.
