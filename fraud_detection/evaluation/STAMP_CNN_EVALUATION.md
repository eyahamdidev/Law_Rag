# ResNet-18 stamp baseline

The live verifier is unchanged. This run asks whether a pretrained image classifier, fine-tuned on the v3 identity split, detects counterfeits the rules miss. It does not. The checkpoint stays available for the comparison. It is not called from the API.

## Setup

Train identities only: 198 genuine or harmless images, 720 counterfeits. Validation identities choose the checkpoint and the thresholds. Test identities are scored after that, once.

Model: torchvision ResNet-18, ImageNet initialization, new 2-class head. Input is the largest dark-ink group on the page, letterboxed to 224×224 so the stamp is not stretched. Training augmentations are small rotation, brightness, contrast, mild blur, and JPEG quality 40–90. No flips. Class weights are inverse frequency. Seed `20261012`. AdamW learning rate `3e-4`. Early stop on validation PR-AUC, patience 2, cap 8 epochs. CPU. Best checkpoint is epoch 1 of 4 run (validation PR-AUC 0.712). Epochs 2 and 3 did not improve it.

The score is the softmax of the counterfeit class. It is not a calibrated probability.

Thresholds, validation only, same quantile rule as `stamp_dataset_v3/evaluate.py` with a 5% budget:

- suspicious if score ≥ 0.8936
- likely genuine if score ≤ 0.5960
- otherwise manual review

A score in the middle is not called fraud.

## What the images actually are

New identities are 566×400 page snippets (a phrase, the stamp, a scribble). The four original identities are tight crops at four other sizes, and none of them is in the training split. The crop function is the same on every split: the largest dark-ink group, padded. On snippets that group is about 30% of the image. On the original crops it is about 77%. Test files were not edited on their own.

## Validation, before the test look

144 genuine, 260 counterfeit.

|  | Likely genuine | Manual review | Suspicious |
| --- | --- | --- | --- |
| Genuine | 4 | 132 | 8 |
| Counterfeit | 13 | 224 | 23 |

| Metric | Count |
| --- | --- |
| Counterfeit recall | 23 / 260 = 0.0885 |
| False-fraud rate | 8 / 144 = 0.0556 |
| False-accept rate | 13 / 260 = 0.0500 |
| Precision | 23 / 31 = 0.7419 |
| PR-AUC | 0.712 |
| Unresolved | 356 / 404 = 0.8812 |

Counterfeit prevalence on validation is 260 / 404 = 0.644. PR-AUC 0.712 is a small lift over that base rate. Recall at the 5% false-fraud budget is 23 / 260.

## Test queries

Same 400 images the verifier was scored on. The four clean `*_gen_000` self-images are left out. 140 genuine, 260 counterfeit. Thresholds were not moved after these counts.

|  | Likely genuine | Manual review | Suspicious |
| --- | --- | --- | --- |
| 140 genuine | 7 | 83 | 50 |
| 260 counterfeit | 10 | 200 | 50 |

| Metric | ResNet-18 | Reference verifier |
| --- | --- | --- |
| Counterfeit recall | 50 / 260 = 0.1923 | 8 / 260 = 0.0308 |
| False-fraud rate | 50 / 140 = 0.3571 | 1 / 140 = 0.0071 |
| False-accept rate | 10 / 260 = 0.0385 | 0 / 260 = 0 |
| Precision | 50 / 100 = 0.5000 | 8 / 9 = 0.8889 |
| PR-AUC | 0.610 | not a ranked score |
| Unresolved | 283 / 400 = 0.7075 | 391 / 400 = 0.9775 |

Counterfeit prevalence on these 400 is 0.650. PR-AUC 0.610 is below that base rate, so the ranking is worse than scoring every image with the same number.

The reference verifier is the current checker after the near-black localization fix: 8 counterfeits called fraudulent, 1 genuine called fraudulent (`rect_04_har_002`), 0 counterfeits called genuine, 391 left unresolved. Those verdicts were not recomputed for this table. They are the saved agent records.

## New identities and the two originals

| Slice | Recall | False fraud | False accept | PR-AUC | Prevalence | Unresolved |
| --- | --- | --- | --- | --- | --- | --- |
| Four new test identities | 1 / 160 | 0 / 40 | 2 / 160 | 0.814 | 0.800 | 197 / 200 |
| Two original test identities | 49 / 100 | 50 / 100 | 8 / 100 | 0.488 | 0.500 | 86 / 200 |

On the new identities the only suspicious call is `rect_02_cfr_007`. The two false accepts are `oval_02_cfr_026` and `oval_02_cfr_037`. PR-AUC 0.814 against a prevalence of 0.800 is not separation.

On the originals, 49 of the 50 suspicious counterfeit calls are `orig_balance`, and that same identity is suspicious on 50 / 50 genuine images. Precision there is 49 / 99 = 0.495. `orig_labellisation` contributes 0 detections, 0 false frauds, and 8 false accepts.

| Family | What it contains | Recall | False fraud | False accept | Unresolved |
| --- | --- | --- | --- | --- | --- |
| circle | `orig_labellisation` | 0 / 50 | 0 / 50 | 8 / 50 | 85 / 100 |
| oval | `oval_02`, `oval_07` | 0 / 80 | 0 / 20 | 2 / 80 | 98 / 100 |
| rect | `rect_02`, `rect_04` | 1 / 80 | 0 / 20 | 0 / 80 | 99 / 100 |
| text | `orig_balance` | 49 / 50 | 50 / 50 | 0 / 50 | 1 / 100 |

## Shortcuts

Within one source, file size and JPEG quality do not separate the classes in a useful way. The classifier does not beat them.

| Slice | Prevalence | Model PR-AUC | Lower JPEG quality | Smaller file |
| --- | --- | --- | --- | --- |
| New synthetic queries | 0.800 | 0.814 | 0.831 | 0.835 |
| Original queries | 0.500 | 0.488 | 0.486 | 0.496 |

Across all 400 queries, lower JPEG quality has PR-AUC 0.710 and the model has 0.610. That mixed number is not a within-identity cue. The new files are 80% counterfeit and the original files are 50% counterfeit, so a cue that tracks which pool an image came from looks better than it is. Inside each pool the cue is flat, and so is the model.

## Recommendation

Do not integrate this classifier. Do not replace the reference matcher with it, and do not attach the score to API responses.

The pre-registered bar was test recall at least 0.20, false fraud at most 0.10, false accept at most 0.05, and recall at least 0.10 on both the new identities and the original identities. The test result misses that bar. Recall is 50 / 260 only because `orig_balance` is flagged almost regardless of label, which is also why false fraud is 50 / 140.

The limiting factor is the training distribution. Every training identity is a synthetic snippet. Held-out snippets from new issuers stay in manual review (197 / 200). The original balance crop, which training never saw, is scored as suspicious on both classes. A longer sweep of the same recipe is not justified by the validation curve: PR-AUC peaked at epoch 1 and the next two epochs were lower.

Synthetic test performance would not have been real-world forgery performance even if the numbers had been strong. These counterfeits are generator edits. This run does not show that the network learned those edits for an unseen issuer.

## Commands

```bash
.venv/bin/python -m fraud_detection.evaluation.stamp_cnn_train
```

```text
epoch 0 loss 0.8845 val_pr_auc 0.6849
epoch 1 loss 0.7177 val_pr_auc 0.7117
epoch 2 loss 0.6993 val_pr_auc 0.7020
epoch 3 loss 0.6825 val_pr_auc 0.6913
early stop
saved stamp_resnet18.pt t_hi 0.8936 t_lo 0.5960 val recall 23/260 false-fraud 8/144 false-accept 13/260
```

```bash
.venv/bin/python -m fraud_detection.evaluation.stamp_cnn_eval
```

```text
recall 50/260
false_fraud 50/140
false_accept 10/260
precision 0.5
pr_auc 0.610
unresolved 283/400
synthetic_recall 1/160
original_recall 49/100
integrate false
```

Checkpoint: `fraud_detection/models/artifacts/stamp_resnet18.pt`. Scores: `stamp_cnn_val_scores.csv`, `stamp_cnn_test_scores.csv`. Full counts: `stamp_cnn_eval.json`.
