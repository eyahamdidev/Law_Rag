# Stamp dataset v3 audit

Commit `b958666`. The decision rules were not changed, and no threshold was chosen from the test identities.

Two systems were scored separately.

- **Classifier.** The existing pair model (`StampVerifier`, LightGBM, same features as training). One model is the shipped file, left unchanged. Another was fit only on the 18 train identities. For both, the accept and fraud cutoffs come from the validation identities with the quantile rule in `stamp_dataset_v3/evaluate.py` (target false-fraud share 0.05). A score is `P(counterfeit) = 1 - P(genuine pair)`.
- **Agent.** The live stamp checker. A new identity is enrolled from its clean `*_gen_000` image. An original identity is enrolled from its genuine PDF. The verdict rules already in the service are used as they are.

Queries below leave out the clean reference image. Comparing that image with itself is an exact copy, not a later document. The shipped model file was not overwritten.

## 1. Manifest

1,726 rows, 30 identities, 1,726 image files present, 0 missing, 0 duplicate file hashes.

| Split | Identities | Genuine clean | Genuine variant | Counterfeit |
| --- | --- | --- | --- | --- |
| train | 18 | 18 | 180 | 720 |
| val | 6 | 4 | 140 | 260 |
| test | 6 | 4 | 140 | 260 |

No identity appears in two splits. No organization name is shared by two identities. Every v3 `parent_reference` stays inside its own identity. Every v3 counterfeit row has a parseable mutation list.

Family counts of identities, train / val / test: circle 5 / 2 / 1, oval 5 / 1 / 2, rect 4 / 2 / 2, text 4 / 1 / 1. The extra identity in circle, oval, rect, and text is one of the four originals. Validation holds `orig_capital` and `orig_subvention`. Test holds `orig_balance` and `orig_labellisation`.

Class balance is not even. A new identity has 1 clean genuine, 10 harmless variants, and 40 counterfeits. The four originals have 50 variants and 50 counterfeits and no clean image. Across the file, 1,240 / 1,726 rows are counterfeit.

Image sizes: the 1,326 new images are 566×400. The original crops keep their own sizes (100 each of 475×263, 384×267, 383×233, 368×368). Within one original identity both classes share that size, so size does not reveal the label.

## 2. Leakage

The filename is a perfect label. New files use `_gen_`, `_har_`, and `_cfr_`. Original files use `_reference` and `_counterfeit`. Neither the classifier nor the agent reads the filename.

The manifest column `degraded` is false only for the 26 clean genuine images, and those files are JPEG quality 95. Their median file size is 38,853 bytes. Genuine variants and counterfeits sit near 21,000 bytes, with JPEG quality from 40 to 90. A rule that says "clean, quality-95 file" would pick the reference images. It would not separate a harmless recapture from a counterfeit.

Rank separation of counterfeit versus genuine variant, 1,240 versus 460 files. 0.5 means the cue does not prefer either class.

| Cue | AUC |
| --- | --- |
| File size | 0.500 |
| JPEG quality | 0.448 |
| Mean of the top 50 rows (the page phrase) | 0.540 |
| Vertical sharpness | 0.405 |
| Ink-box width | 0.553 |

Harmless and counterfeit rows are passed through the same degradation function in `make_identities.py` (grayscale, rescale, small rotation, blur, tint, noise, JPEG). The drawing mutations are the intended difference. Background file size does not carry the label. Mild sharpness and ink-box differences are not strong enough to stand in for a fraud decision.

`evaluate.py` has a reporting bug. When it groups by difficulty it adds every genuine row to every difficulty bucket, so the false-fraud percentage is copied onto each line and the row count is not the size of that difficulty. The tables below are counted from the confusion matrices, not from those lines.

## 3. Classifier, validation cutoffs, then test

Retrained model, fit on train identities only. Validation, 144 genuine and 260 counterfeit: flag fraud if `P(counterfeit) >= 0.994485`, accept if `P(counterfeit) <= 0.254600`. Test identities were not used to move these cutoffs.

Test queries, 140 genuine and 260 counterfeit:

|  | Called genuine | Called fraudulent | Uncertain |
| --- | --- | --- | --- |
| Genuine | 0 | 7 | 133 |
| Counterfeit | 2 | 27 | 231 |

| Metric | Count |
| --- | --- |
| Counterfeit precision | 27 / 34 = 0.7941 |
| Counterfeit recall | 27 / 260 = 0.1038 |
| False-fraud rate | 7 / 140 = 0.0500 |
| False-accept rate | 2 / 260 = 0.0077 |
| Uncertain | 364 / 400 = 0.9100 |
| Unrecognized | undefined. This model has no unrecognized verdict. |

By family on those 400 queries:

| Family | What it contains | Genuine fraud / n | Counterfeit detected / n | False accepts | Uncertain |
| --- | --- | --- | --- | --- | --- |
| circle | `orig_labellisation` only | 1 / 50 | 0 / 50 | 0 / 50 | 99 / 100 |
| oval | `oval_02`, `oval_07` | 2 / 20 | 13 / 80 | 1 / 80 | 84 / 100 |
| rect | `rect_02`, `rect_04` | 1 / 20 | 5 / 80 | 0 / 80 | 94 / 100 |
| text | `orig_balance` only | 3 / 50 | 9 / 50 | 1 / 50 | 87 / 100 |

New synthetic test identities only (`oval_02`, `oval_07`, `rect_02`, `rect_04`), 40 genuine and 160 counterfeit: precision 18 / 21, recall 18 / 160, false fraud 3 / 40, false accept 1 / 160, uncertain 178 / 200.

The two original test identities, 100 genuine and 100 counterfeit: precision 9 / 13, recall 9 / 100, false fraud 4 / 100, false accept 1 / 100, uncertain 186 / 200.

Including the four clean reference images (144 genuine) does not create any new genuine accepts. Those four self-comparisons landed in the uncertain band. Exact copies were not in the training pairs.

Shipped model, weights unchanged. It was trained on crops from the four original documents, so `orig_balance` and `orig_labellisation` are not new identities for this model. Validation cutoff: fraud if `P(counterfeit) >= 0.999687`, accept if `P(counterfeit) <= 0.910180`.

Test queries, 140 genuine and 260 counterfeit:

|  | Called genuine | Called fraudulent | Uncertain |
| --- | --- | --- | --- |
| Genuine | 34 | 10 | 96 |
| Counterfeit | 19 | 35 | 206 |

| Metric | Count |
| --- | --- |
| Counterfeit precision | 35 / 45 = 0.7778 |
| Counterfeit recall | 35 / 260 = 0.1346 |
| False-fraud rate | 10 / 140 = 0.0714 |
| False-accept rate | 19 / 260 = 0.0731 |
| Uncertain | 302 / 400 = 0.7550 |

On the new identities the shipped model’s false-fraud rate is 10 / 40. On the two originals, which this model has seen before, false fraud is 0 / 100 and counterfeit recall is 1 / 100, with 14 / 100 counterfeits accepted. That is not a held-out identity result.

## 4. Agent

Same 400 test queries. The agent enrolled `orig_balance`, `orig_labellisation`, `oval_07`, and `rect_04`. It did not enroll `oval_02` or `rect_02`: `find_marks` found no stamp on the clean reference, so those 100 images were not compared (`unscored`). On the queries it did see, some stamps were still missed.

|  | Genuine | Fraudulent | Uncertain | Unrecognized | Missing | Unscored |
| --- | --- | --- | --- | --- | --- | --- |
| 140 genuine | 0 | 1 | 117 | 0 | 2 | 20 |
| 260 counterfeit | 0 | 5 | 159 | 1 | 15 | 80 |

| Metric | Count |
| --- | --- |
| Counterfeit precision | 5 / 6 = 0.8333 |
| Counterfeit recall | 5 / 260 = 0.0192 |
| False-fraud rate | 1 / 140 = 0.0071 |
| False-accept rate | 0 / 260 = 0 |
| Uncertain | 276 / 400 = 0.6900 |
| Unrecognized | 1 / 400 = 0.0025 |
| Missing stamp | 17 / 400 = 0.0425 |
| Unscored, no enrolled reference | 100 / 400 = 0.2500 |

The one false fraud is `rect_04_har_002`, a harmless variant, reason `local_ink_anomaly`. The five fraud calls are that variant plus `rect_04_cfr_013` and balance crops `balance_0028`, `balance_0044`, `balance_0047`, and `balance_0081`, all `local_ink_anomaly`. No counterfeit was called genuine.

New synthetic queries, 40 genuine and 160 counterfeit: recall 1 / 160, false fraud 1 / 40, false accept 0 / 160, uncertain 80 / 200, missing 17 / 200, unscored 100 / 200. Among the two new identities that did enroll (`oval_07`, `rect_04`), 20 genuine and 80 counterfeit: recall 1 / 80, false fraud 1 / 20, false accept 0 / 80.

Original test crops, 100 genuine and 100 counterfeit: recall 4 / 100, false fraud 0 / 100, false accept 0 / 100, uncertain 196 / 200. All four fraud calls are balance. Labellisation is 100 / 100 uncertain.

By family:

| Family | Counterfeit recall | False fraud | False accept | Uncertain | Missing | Unscored |
| --- | --- | --- | --- | --- | --- | --- |
| circle (`orig_labellisation`) | 0 / 50 | 0 / 50 | 0 / 50 | 100 / 100 | 0 / 100 | 0 / 100 |
| oval (two new) | 0 / 80 | 0 / 20 | 0 / 80 | 41 / 100 | 8 / 100 | 50 / 100 |
| rect (two new) | 1 / 80 | 1 / 20 | 0 / 80 | 39 / 100 | 9 / 100 | 50 / 100 |
| text (`orig_balance`) | 4 / 50 | 0 / 50 | 0 / 50 | 96 / 100 | 0 / 100 | 0 / 100 |

## 5. Comparison with the previous full-page run

The previous run enrolled the four PDFs and scored full pages, not these crops. Same verdict rules. Reference pages: 9 / 200 genuine, 0 / 200 fraudulent, 191 / 200 uncertain. Counterfeit pages: 0 / 200 genuine, 13 / 200 fraudulent, 187 / 200 uncertain.

On the two original families that v3 puts in test, that full-page run called 7 / 50 balance counterfeits fraudulent and 0 / 50 labellisation counterfeits fraudulent, with no genuine page called fraudulent. This crop run calls 4 / 50 balance counterfeits fraudulent and 0 / 50 labellisation counterfeits fraudulent, again with no genuine original called fraudulent. The crop run detects fewer of the same balance counterfeits. It is not an improvement, and the input is not the same image.

The new identities have no previous full-page baseline. The agent’s false-accept count on them is 0 / 160, and its fraud count is 1 / 160. Most of those images are uncertain, missing, or unscored.

## 6. Tests

```bash
.venv/bin/python -m fraud_detection.evaluation.stamp_v3_audit
```

Exit code 0.

```bash
.venv/bin/python -m pytest tests/test_stamp_review.py tests/test_stamp_robustness.py tests/test_stamp_verifier.py tests/test_documents.py tests/test_api.py -q --tb=line
```

Exit code 0. 39 passed.

The 680-case full-page suite was not rerun. The verdict rules were not edited, so the previous exit-0 result remains the full-page baseline cited above.

## 7. What this establishes

The v3 split is a real identity split: 18 / 6 / 6, with no identity on both sides of a split. Filename labels are trustworthy as labels and would be cheating if a model read them. File size and JPEG quality do not separate harmless recaptures from counterfeits. The clean reference image is visibly a different generation setting.

On held-out identities, both the retrained classifier and the agent leave most images uncertain. The retrained classifier, at a validation false-fraud target of about 5%, detects 27 / 260 test counterfeits and accepts 2 / 260. The agent accepts 0 / 260 counterfeits, detects 5 / 260, and never sees 100 / 400 because two reference stamps are not localized. Neither result is better than the earlier full-page baseline on the original documents.

Nothing here is a real-world forgery test. The counterfeits are generated edits plus the same scan damage as the harmless copies. The page around a new stamp is a short synthetic snippet.

The highest-value next experiment is physical recaptures and physical alterations of stamps that are not these 30 designs, with every capture of one identity kept in one split. Section 8 is the localization measurement that was next on this file. The fraud thresholds were left as they were.

## 8. Localization of the near-black references

`oval_02` and `rect_02` use near-black ink. On the clean reference the color mask is a thin sliver (`oval_02`, aspect about 4.5) or empty (`rect_02`, chroma stays under 20). The gray finder already grouped the real stamp, then rejected it. On a 566×400 patch that box is about 0.55–0.69 of the width and 0.46–0.49 of the height, with the rotated rectangle at aspect 2.12. The old caps were width 0.48, height 0.30, aspect 2.05.

`_gray_stamp` now accepts aspect up to 2.25, width up to 0.72, and height up to 0.55. Ink area stays at 0.05. Width stays under 0.72 because the body-text block on each of the four genuine PDFs is about 0.79 of the page width. That block still fails the gray finder, on the color render and on a grayscale copy, and the selected stamp box on those eight pages is the same box as before. Across the 400 v2 full pages, every page still has a color stamp, so this gray-path change does not move a box there. The original test crops (`orig_balance`, `orig_labellisation`) also keep the same box. `stamp_decision` was not edited.

The clean references now enroll. A self-check of each `*_gen_000` is genuine, NCC 1.0. Query images leave that file out.

Of the 100 queries that were unscored, the finder still misses 67 (the box is larger than these caps, usually because a size or rotation mutation spreads the ink). Those stay `missing`. The 33 that localize are uncertain or unrecognized. None of them is fraudulent, and none is a false accept.

Seven queries on `oval_07` and `rect_04` had no box before and have one now. Three of those counterfeits fall under the existing `local_ink_anomaly` rule: `oval_07_cfr_023`, `oval_07_cfr_026`, and `rect_04_cfr_000`. The box sits on the stamp. On `oval_07_cfr_023` and `rect_04_cfr_000` the signature scribble also enters the bottom of the box, so part of that local difference can be the scribble. The false fraud remains the one from the previous run, `rect_04_har_002`.

Held-out queries after this finder change, originals taken from the previous run because their boxes did not move, 140 genuine and 260 counterfeit:

|  | Genuine | Fraudulent | Uncertain | Unrecognized | Missing | Unscored |
| --- | --- | --- | --- | --- | --- | --- |
| 140 genuine | 0 | 1 | 125 | 0 | 14 | 0 |
| 260 counterfeit | 0 | 8 | 185 | 4 | 63 | 0 |

| Metric | Count |
| --- | --- |
| Counterfeit precision | 8 / 9 = 0.8889 |
| Counterfeit recall | 8 / 260 = 0.0308 |
| False-fraud rate | 1 / 140 = 0.0071 |
| False-accept rate | 0 / 260 = 0 |
| Uncertain | 310 / 400 = 0.7750 |
| Unrecognized | 4 / 400 = 0.0100 |
| Missing stamp | 77 / 400 = 0.1925 |
| Unscored | 0 / 400 = 0 |

By family:

| Family | Counterfeit recall | False fraud | False accept | Uncertain | Missing | Unrecognized |
| --- | --- | --- | --- | --- | --- | --- |
| circle (`orig_labellisation`) | 0 / 50 | 0 / 50 | 0 / 50 | 100 / 100 | 0 / 100 | 0 / 100 |
| oval (`oval_02`, `oval_07`) | 2 / 80 | 0 / 20 | 0 / 80 | 53 / 100 | 42 / 100 | 3 / 100 |
| rect (`rect_02`, `rect_04`) | 2 / 80 | 1 / 20 | 0 / 80 | 61 / 100 | 35 / 100 | 1 / 100 |
| text (`orig_balance`) | 4 / 50 | 0 / 50 | 0 / 50 | 96 / 100 | 0 / 100 | 0 / 100 |

Per-image rows are in `stamp_v3_localization.json`. This is a localization fix. It is not a new fraud cutoff, and it is not a real-world forgery result. Recall on the 400 queries moved from 5 / 260 to 8 / 260 because three previously invisible counterfeit crops now meet the old local-ink rule. Most near-black counterfeits are still missing or uncertain.
