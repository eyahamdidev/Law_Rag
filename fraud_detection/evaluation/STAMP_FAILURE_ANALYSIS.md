# Failure analysis of the reference stamp verifier

The live checker was re-scored and not modified. No threshold was chosen from the test identities, no rule was edited, and no model was trained. Train and validation identities are the exploratory comparison. The 400 test queries are a holdout.

The reproduction matches the previous holdout exactly: 8/260 counterfeits called fraudulent, 1/140 genuine images called fraudulent, 0/260 counterfeits called genuine, and 391/400 left unresolved (310 uncertain, 77 missing, 4 unrecognized).

## 1. How a verdict is reached

`stamp_decision` never returns `missing`. A missing stamp is decided earlier, in `SpecimenStore.check`, when `find_marks` returns no stamp and a stamp is expected. The mark status is `missing`, the verdict field is empty, and the reason code is `missing_stamp`.

`find_marks` tries three locators and keeps a box only when one of them accepts it.

- Dark components (`gray < 160`) can be a stamp only when the area is 0.2%–20% of the page, the aspect is 0.65–1.55, the ink density is 0.12–0.80, and the width is at least 5% of the page.
- Color ink (chroma at least 28, then 20 if that finds nothing, and gray under 235) can be a stamp only when the aspect is 0.40–2.8, the width is at least 10% of the page (6% if the box touches the edge), the height is at least 6% of the page, and the ink area is 0.08%–22% of the page.
- If both of those fail, gray ink darker than `min(paper 92nd percentile − 18, 210)` can be a stamp only when the aspect is 0.70–2.25, the width is 12%–72% of the page, the height is 5%–55% of the page, and the ink area is 0.08%–5% of the page.

`unrecognized` is only `no_matching_enrolled_identity`, and only from `stamp_decision`, in this order:

- Alignment quality `failed` is not unrecognized. It is `uncertain` / `poor_image_quality`.
- Content `unknown` and NCC below 0.50.
- Content `different`, NCC below 0.50, and quality not `poor`.
- Content `different` and NCC below 0.20, including when quality is `poor`.

Content is `unknown` when either OCR reading has fewer than two tokens. It is `same` when the overlap of tokens covers at least 45% of the shorter reading and at least two tokens. Otherwise it is `different`.

`uncertain` is everything else that is not genuine or fraudulent:

- Alignment quality `failed`, or quality `poor` (NCC below 0.20 or local minimum below −0.15) after the unrecognized checks above: `poor_image_quality`.
- The query crop is unusable before `stamp_decision` runs (shorter side under 48 pixels, or Laplacian variance under 40): `poor_image_quality`. This branch cannot become unrecognized.
- A one-sided hole is present (NCC at least 0.97, bright peak at least 40, and bright peak at least twice the dark peak) but it is not a strong hole, or the wording is not `same`: `local_ink_anomaly`, verdict `uncertain`. A strong hole (bright peak at least 100) with the same wording is `fraudulent`, not uncertain.
- The close-scan genuine test fails and the near-perfect test fails (NCC at least 0.992 and local minimum at least 0.90). If the wording is `different`, the reason is `text_mismatch`. Otherwise the reason is `insufficient_evidence`.

`fraudulent` is only the strong hole with the same wording, or the same wording with row correlation below that stamp’s harmless-recapture floor, NCC in [0.30, 0.82), and local minimum at least −0.18. `genuine` is the close-scan test (row correlation at least 0.97, NCC at least 0.955, local minimum at least 0.50, MAE at most 8, low-block share at most 0.02) or the near-perfect NCC test. The LightGBM score is loaded and ignored.

## 2. The 400 holdout queries

Queries leave out the four clean `*_gen_000` images. 140 genuine, 260 counterfeit.

| | Genuine | Fraudulent | Uncertain | Unrecognized | Missing |
| --- | --- | --- | --- | --- | --- |
| 140 genuine | 0 | 1 | 125 | 0 | 14 |
| 260 counterfeit | 0 | 8 | 185 | 4 | 63 |

Localization, meaning `find_marks` returned a box: 126/140 genuine, 197/260 counterfeit.

Abstention reason codes, 391 rows:

| Reason | Count |
| --- | --- |
| `insufficient_evidence` | 155 |
| `text_mismatch` | 104 |
| `missing_stamp` | 77 |
| `poor_image_quality` | 51 |
| `no_matching_enrolled_identity` | 4 |

| Identity | Genuine n | Counterfeit n | Genuine verdicts G / F / U / R / M | Counterfeit verdicts G / F / U / R / M | Found |
| --- | --- | --- | --- | --- | --- |
| `orig_balance` | 50 | 50 | 0 / 0 / 50 / 0 / 0 | 0 / 4 / 46 / 0 / 0 | 50/50, 50/50 |
| `orig_labellisation` | 50 | 50 | 0 / 0 / 50 / 0 / 0 | 0 / 0 / 50 / 0 / 0 | 50/50, 50/50 |
| `oval_02` | 10 | 40 | 0 / 0 / 3 / 0 / 7 | 0 / 0 / 8 / 2 / 30 | 3/10, 10/40 |
| `oval_07` | 10 | 40 | 0 / 0 / 9 / 0 / 0 | 0 / 2 / 33 / 1 / 4 | 9/10, 36/40 |
| `rect_02` | 10 | 40 | 0 / 0 / 4 / 0 / 6 | 0 / 0 / 15 / 1 / 24 | 4/10, 16/40 |
| `rect_04` | 10 | 40 | 0 / 1 / 9 / 0 / 0 | 0 / 2 / 33 / 0 / 5 | 10/10, 35/40 |

G / F / U / R / M are genuine, fraudulent, uncertain, unrecognized, missing. Found is genuine found, then counterfeit found.

| Family | What it contains | Counterfeit fraudulent | Genuine fraudulent | Missing | Uncertain | Unrecognized |
| --- | --- | --- | --- | --- | --- | --- |
| circle | `orig_labellisation` | 0 / 50 | 0 / 50 | 0 / 100 | 100 / 100 | 0 / 100 |
| oval | `oval_02`, `oval_07` | 2 / 80 | 0 / 20 | 42 / 100 | 53 / 100 | 3 / 100 |
| rect | `rect_02`, `rect_04` | 2 / 80 | 1 / 20 | 35 / 100 | 61 / 100 | 1 / 100 |
| text | `orig_balance` | 4 / 50 | 0 / 50 | 0 / 100 | 96 / 100 | 0 / 100 |

`orig_balance` abstains as `insufficient_evidence` (79) and `poor_image_quality` (17). `orig_labellisation` abstains as `text_mismatch` (92), `insufficient_evidence` (6), and `poor_image_quality` (2). The oval and rectangle misses are `missing_stamp`.

On the localized holdout crops, median alignment still overlaps:

| | n | NCC | Local min | Row gap | Low-block | Content same / different / unknown |
| --- | --- | --- | --- | --- | --- | --- |
| Genuine | 126 | 0.775 | 0.389 | 0.093 | 0.111 | 70 / 50 / 6 |
| Counterfeit | 197 | 0.700 | 0.139 | 0.065 | 0.306 | 116 / 67 / 14 |

`orig_labellisation` is the OCR failure: 46/50 genuine and 48/50 counterfeit read as `different`, with NCC 0.769 versus 0.749. `text_mismatch` is the round stamp’s reading, not a forgery feature. `rect_04` is the opposite of a forgery gap: counterfeit median NCC is 0.755 and genuine median NCC is 0.708. `rect_02`, when a box is returned, sits near NCC 0.22 for both classes.

## 3. Localization is not the same failure as classification

Every one of the 77 missing queries has a plausible ink group (area at least 0.8% of the image, aspect 0.45–4.5, height at least 8% of the image). None is an empty page. The group is rejected by the live gray or color gates:

| Failed gates on the largest ink group | Missing queries |
| --- | --- |
| `area_ratio` only | 57 |
| `height_frac` and `area_ratio` | 11 |
| `height_frac` only | 2 |
| `width_ratio` and `area_ratio` | 2 |
| `aspect` and `area_ratio` | 2 |
| `aspect` only | 1 |
| `width_ratio`, `height_frac`, and `area_ratio` | 1 |
| `aspect`, `width_ratio`, and `area_ratio` | 1 |

The gray area cap is 5% of the image. It is the binding constraint on 57/77 misses. Those misses are concentrated on `oval_02` (37) and `rect_02` (30), the near-black stamps whose ink group is large on a 566×400 snippet.

A second mode is not a missing verdict. On 17/400 queries `find_marks` returns a box, and a larger ink group that does not overlap it was rejected. The comparator then runs on the smaller box. That split is `rect_02` 10, `oval_02` 4, `oval_07` 2, `orig_balance` 1. Of the 20 `rect_02` queries that are not missing, 10 are this wrong-region case. Their NCC near 0.22 is not a clean stamp-to-stamp comparison.

The remaining 306/400 queries are localized without that larger rejected group.

The area cap is not what keeps body text off the four genuine PDFs. On each page, in color and in grayscale, the largest gray group is the body text and it fails `width_ratio` only:

| Document | Body-text width ratio | Body-text area ratio | Stamp still selected in grayscale |
| --- | --- | --- | --- |
| balance | 0.794 | 0.024 | yes, lower on the page |
| capital | 0.794 | 0.029 | yes |
| labellisation | 0.809 | 0.035 | yes |
| subvention | 0.794 | 0.021 | yes |

Raising the area cap would not, on these four pages, hand the stamp slot to the body text. That is not a license to raise it from the test misses. Counterfeit snippets miss more often than genuine ones (63/260 versus 14/140) because a size or rotation mutation makes the ink group larger. Calling a miss fraudulent would accuse that geometry. A training identity shows the other edge of the same gates: `text_01_gen_000` does not enroll. Its text block has aspect 2.43, and the gray cap is 2.25. Borderless text is outside the locator. That fact comes from a training identity, and it was not used to edit the cap.

## 4. Signals on pairs that were actually localized

The comparison is within one identity, harmless recapture versus counterfeit, and only where alignment ran. Clean `*_gen_000` copies are left out. The reported number is ROC AUC for ranking a counterfeit above a harmless recapture. 0.5 is no separation. An identity is included only when both classes have at least five localized queries.

On 16 training identities the median AUCs are all weak:

| Feature | Median within-identity AUC |
| --- | --- |
| Lower NCC | 0.591 |
| Lower row correlation | 0.596 |
| Lower row gap | 0.596 |
| Higher low-block share | 0.586 |
| Higher bright peak | 0.577 |
| Higher MAE | 0.537 |
| Lower local minimum | 0.532 |
| Higher dark peak | 0.464 |

Individual training identities swing from about 0.43 to about 0.77. `rect_01` and `text_02` are at or below 0.5 for NCC. No feature is stable across issuers.

Validation median AUC looks a bit higher (bright peak 0.656, low-block 0.623, NCC 0.611) only because `orig_capital` and `orig_subvention` are in that split. On the four new validation identities the NCC AUCs are 0.616, 0.374, 0.607, and 0.503 (`circle_02`, `circle_06`, `rect_07`, `text_03`). `circle_06` is inverted: the harmless copies look less like the reference than the counterfeits do.

The live fraud conjunction, counted without moving it, fires on validation for 7 counterfeits and 1 genuine image among localized same-wording pairs. On training identities it fires for 23 counterfeits and 4 genuine images. The close-scan genuine test fires for 10 genuine and 3 counterfeit validation images, and for 1 counterfeit training image. The rule can fire. It does not separate the two classes on new issuers.

Holdout medians are reported and were not used to pick a feature. `orig_balance` NCC is 0.833 versus 0.755. `orig_labellisation` is 0.769 versus 0.749. `rect_04` counterfeits score higher (0.755 versus 0.708). Within-identity holdout AUCs exist for only four identities, and `rect_04` is below 0.5 on every alignment feature. That spread is why a cutoff fit on one identity would not be a verifier.

## 5. The ResNet `orig_balance` result is not a forgery cue

The frozen ResNet threshold is 0.8936, chosen on validation. On the holdout it marked 49/50 `orig_balance` counterfeits suspicious and 50/50 `orig_balance` genuine images suspicious. The scores of the two classes are the same distribution:

| `orig_balance` | n | Score median | p10–p90 | JPEG median | File bytes median | Page | Crop median | Corner mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Genuine | 50 | 0.972 | 0.966–0.978 | 71.5 | 15,926 | 475×263 | 209×132 | 248.7 |
| Counterfeit | 50 | 0.972 | 0.944–0.978 | 73.5 | 15,519 | 475×263 | 209×133 | 249.1 |

Training never saw a 475×263 text crop. Every training identity is a 566×400 snippet. The network assigns this whole unseen layout a score above the threshold. JPEG quality, file size, crop size, and the flat corner background do not differ by label inside the identity.

`orig_labellisation` is the check on that story. It is also absent from training, it is a 368×368 circle crop, and both classes score about 0.63 (genuine median 0.628, counterfeit median 0.627), under the threshold. JPEG medians match at 68. File size, crop size, and corner color match. The network does not flag it, and it also does not separate it.

On the four new holdout identities, genuine and counterfeit score medians differ by only a few hundredths, and page size is 566×400 for both classes. The earlier PR-AUC of 0.814 on those 200 images sits on a counterfeit prevalence of 0.800. File size and JPEG quality rank that slice at least as well. None of those cues is a within-identity forgery feature.

## 6. Ranked bottlenecks

1. **There is no stable within-identity signal in this file.** On training issuers, every alignment and ink feature has a median AUC near 0.59 or worse, and some issuers are inverted. Validation on new issuers looks the same. The holdout was not used to shop for a better feature, and the one new holdout rectangle where alignment was measured runs the wrong direction.

2. **Most unresolved queries never reach a confident branch of `stamp_decision`.** Of 400 queries, 155 are `insufficient_evidence` and 51 are `poor_image_quality`. The fraud conjunction is rare. The genuine conjunction is rare on the synthetic snippets. Abstaining is the rule working as written, not a missing else-branch.

3. **77/400 queries are missing, all because a real ink group fails a gate, mostly the 5% area cap.** 17 more run the comparator on a smaller box than the main ink group. This is a coverage problem. It is not, by itself, evidence of forgery, and the area cap is not the guard that rejects body text on the four PDFs. The width cap is.

4. **OCR on the round labellisation stamp is `different` for both classes** (46/50 genuine, 48/50 counterfeit). `text_mismatch` cannot rank a counterfeit above a harmless copy of that stamp.

5. **The ResNet gain on `orig_balance` is an unseen crop layout.** Both classes sit at score 0.972. The same measurement on `orig_labellisation` and on the new identities shows no label gap.

## 7. Smallest next experiment

Do not train another model on this file. Do not add another verdict cutoff. The training identities do not contain a reliable separator between a harmless recapture and a generated mutation, so another fit would memorize issuer appearance or the generator.

The experiment that can change the claim is a paired physical capture: one real stamp, a harmless recapture, and a physical alteration, with every capture of that stamp kept in one split. Until those images exist, the supported claim is the holdout behavior of the current checker: it called 0/260 counterfeits genuine and 1/140 genuine images fraudulent, and it left 391/400 unresolved.

A localization change is a smaller measurement, not that experiment. If it is done, do it on validation identities and on the four genuine PDFs only, and do not score the test identities until the PDF grayscale box is still the stamp. The width ratios above are why the body-text block is rejected today. They are not a new threshold.

## Command

```bash
.venv/bin/python -m fraud_detection.evaluation.stamp_failure_analysis
```

The run enrolled every identity that has a stamp region. `text_01` did not enroll. The printed holdout matrix was:

```text
genuine: genuine 0, fraudulent 1, uncertain 125, unrecognized 0, missing 14
counterfeit: genuine 0, fraudulent 8, uncertain 185, unrecognized 4, missing 63
missing diagnosis: outside_bounds 77
```

Counts and the within-identity AUCs are in `fraud_detection/evaluation/stamp_failure_analysis.json`.
