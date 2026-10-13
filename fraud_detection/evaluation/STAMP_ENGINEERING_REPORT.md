# Stamp verification engineering report

The stamp check compares an uploaded crop with the stamp a company has approved. It is not a universal genuine/fake classifier. Verdicts stay separate: genuine, fraudulent, unrecognized, uncertain, and missing.

## 1. Architecture verdict

Retain the reference-matching pipeline and simplify the decision. LightGBM stays loaded so `genuine_probability` can be inspected. It no longer changes the verdict.

A learned embedding, YOLO, or another service was not added. Four stamp identities cannot support that evaluation, and stamp localization already finds 400 / 400 labeled pages.

## 2. Root causes confirmed in code

- Fraud used to require a one-sided hole. Generated counterfeits are mutated drawings, so the 680-case run at `f141fa8` called 0 / 200 counterfeits fraudulent.
- The same run also refused to call a low alignment score fraud, because that rule had accused a genuine page rotated by 2°.
- `StampVerifier` training PR-AUC is 0.9999. Leave-one-document-out PR-AUC is 0.506, 0.548, 0.536, and 0.530. The model memorizes the four designs. The training split is `zlib.crc32(filename) % 5 == 0` inside each document, so the same identity is on both sides.
- Against the enrolled PDF, that score is low for both classes. A threshold of 0.30 calls 188 / 200 reference pages fraudulent and still accepts 1 counterfeit (`balance_0077_counterfeit.jpg`).
- Alignment score alone is not enough either. Four counterfeits have an aligned score of at least 0.955 (`capital_0024`, `capital_0051`, `capital_0068`, `subvention_0022`) and stay uncertain only because the text-line profile, block agreement, and error gates fail. Calling every score under 0.72 fraud would accuse 8 genuine labellisation pages.
- A 6 px blur of the capital PDF dropped the aligned score to 0.18 and was offered as a new organization. That is an unusable crop, not a new stamp.
- A high model score could still grant genuine when OCR disagreed. That contradicted the measured leave-one-document-out result.
- `labels.csv` is described in the dataset README and written by the generators. It is not in this checkout. Labels in use are the filename suffixes `_reference` and `_counterfeit`.
- There is no authentication. The organization partition is `document.entity_id` when it is non-blank, otherwise the payment `receiver_id`. A blank string used to be a legal key.

## 3. Implementation

| File | Change |
| --- | --- |
| `fraud_detection/documents/stamp_alignment.py` | `stamp_decision` returns the verdict and the reason code of the branch that fired. `crop_quality` marks a tiny or heavily blurred crop unusable. The model score is ignored. |
| `fraud_detection/documents/specimens.py` | Alignment runs even when the model file is missing. Unusable crops are uncertain. Blank tenants are refused. Marks carry `reason_codes` and `evidence`. |
| `fraud_detection/schema.py` | `DocumentMark.reason_codes` and `DocumentMark.evidence`. |
| `fraud_detection/api/app.py` | `/v1/score` resolves the tenant and does not compare or save when both ids are blank. `/health` reports `stamp_verdict_uses_model: false`. |
| `fraud_detection/evaluation/stamp_approaches.py` | Policy comparison and the pre-registered sample. Seed 20261012. |
| `fraud_detection/evaluation/stamp_stress.py` | Records `reason_codes`. |
| `tests/test_stamp_robustness.py` | Reason codes, severe blur, blank tenant, and the model score no longer granting genuine. |

Reason codes, each tied to a branch:

- `reference_match` — close scan or near-perfect alignment.
- `local_ink_anomaly` — strong one-sided hole, or same wording with a text-line profile below the enrolled stamp's own harmless recapture.
- `text_mismatch` — wording differs and the drawing is not a foreign stamp.
- `poor_image_quality` — alignment failed, pose is poor, or the crop is unusable.
- `no_matching_enrolled_identity` — drawing does not match an enrolled stamp.
- `insufficient_evidence` — same wording, pose recovered, nothing local enough to call fraud or genuine.
- `insufficient_reference` — no enrolled stamp for this organization yet.
- `missing_stamp` — no stamp region.

The text-line floor is unchanged: the weaker of a ±6° turn and a 1.2 px blur of the enrolled crop, minus 0.09. Blur variance under 40, or a crop shorter than 48 px, is unusable. Those cutoffs were measured on the capital PDF blur series (sharp variance about 4300, 2 px blur about 23) and on labeled scans (above 1500). They were not fit to maximize counterfeit recall.

Uploaded scans stay at their own size up to 1600 px. The enrolled PDF is the 1200 px render.

## 4. Evaluation methodology

Same-identity check: enroll each genuine PDF, score that family's 50 reference and 50 counterfeit pages. Ground truth is the filename suffix. These are generated scans and mutations, not photographed forgeries.

The pre-registered sample does not look at predictions. Seed `20261012`. For each family, filenames are sorted, then `random.sample` draws 2 reference and 2 counterfeit names. Those 16 pages are scored after the draw.

Not reported as one headline:

- Unseen stamp identities: only the foreign-page stress cases. There is no fifth enrolled identity in the labeled set.
- Real-world counterfeits: none in the repository.
- The filename holdout: computed by the stress script and rejected as an evaluation split, because it does not separate identities.

## 5. Before and after

Same 400 labeled pages, enrolled PDF as the reference.

| Policy | Reference genuine / fraudulent | Counterfeit genuine / fraudulent / uncertain |
| --- | --- | --- |
| f141fa8 hole-only fraud rule | 0 / 0 | 0 / 0 / 155 (45 unrecognized) |
| A. LightGBM, genuine if score ≥ 0.30 | 12 / 188 | 1 / 199 / 0 |
| A. LightGBM with abstention (genuine ≥ 0.45, fraud < 0.08) | 2 / 139 | 0 / 173 / 27 |
| B. Aligned score only (≥ 0.955 genuine, < 0.50 unrecognized) | 14 / 0 | 4 / 0 / 189 |
| B. Score under 0.72 called fraud | 14 / 8 | 4 / 46 / 150 |
| C. Reference rules now in the service | 9 / 0 | 0 / 13 / 187 |

Reference-rule confusion matrix:

|  | Genuine | Fraudulent | Uncertain | Unrecognized | Missing |
| --- | --- | --- | --- | --- | --- |
| 200 reference pages | 9 | 0 | 191 | 0 | 0 |
| 200 counterfeit pages | 0 | 13 | 187 | 0 | 0 |

By family, reference genuine then counterfeit fraudulent: balance 0 and 7, capital 5 and 6, labellisation 0 and 0, subvention 4 and 0.

Fraudulent precision on this generated set is 13 / 13. Recall is 13 / 200. Uncertainty is not counted as detection. This does not establish a zero real-world false-positive rate.

## 6. Pre-registered sample and the selected demonstration

Pre-registered, seed 20261012, scored after selection:

| Filename | Ground truth | Verdict | Reason | Aligned score |
| --- | --- | --- | --- | --- |
| balance_0055_reference.jpg | reference | uncertain | insufficient_evidence | 0.8362 |
| balance_0001_reference.jpg | reference | uncertain | insufficient_evidence | 0.8762 |
| balance_0009_counterfeit.jpg | counterfeit | uncertain | insufficient_evidence | 0.8879 |
| balance_0000_counterfeit.jpg | counterfeit | uncertain | insufficient_evidence | 0.5168 |
| capital_0002_reference.jpg | reference | uncertain | insufficient_evidence | 0.9215 |
| capital_0069_reference.jpg | reference | uncertain | text_mismatch | 0.9410 |
| capital_0098_counterfeit.jpg | counterfeit | uncertain | insufficient_evidence | 0.9531 |
| capital_0068_counterfeit.jpg | counterfeit | uncertain | insufficient_evidence | 0.9598 |
| labellisation_0077_reference.jpg | reference | uncertain | text_mismatch | 0.7707 |
| labellisation_0011_reference.jpg | reference | uncertain | text_mismatch | 0.7437 |
| labellisation_0028_counterfeit.jpg | counterfeit | uncertain | text_mismatch | 0.7009 |
| labellisation_0055_counterfeit.jpg | counterfeit | uncertain | text_mismatch | 0.6959 |
| subvention_0007_reference.jpg | reference | uncertain | insufficient_evidence | 0.9367 |
| subvention_0017_reference.jpg | reference | genuine | reference_match | 0.9694 |
| subvention_0034_counterfeit.jpg | counterfeit | uncertain | insufficient_evidence | 0.8704 |
| subvention_0078_counterfeit.jpg | counterfeit | uncertain | insufficient_evidence | 0.9316 |

One of eight reference pages is genuine. Zero of eight counterfeit pages are fraudulent. None are false accepts. `capital_0068_counterfeit.jpg` has an aligned score of 0.9598 and is still uncertain, because the text-line agreement is 0.9551.

The eight-file demonstration in `STAMP_CLASSIFICATION.md` was chosen because the checker already called those files genuine or fraudulent. It is a selected demonstration. It is not this sample.

## 7. Regression tests

```bash
.venv/bin/python -m pytest tests/test_stamp_robustness.py tests/test_stamp_verifier.py tests/test_documents.py tests/test_api.py -q --tb=line
```

32 passed.

```bash
.venv/bin/python -m fraud_detection.evaluation.stamp_approaches
```

Exit code 0. Wrote `fraud_detection/evaluation/stamp_approaches.json`.

```bash
.venv/bin/python -m fraud_detection.evaluation.stamp_stress
```

Exit code 0. 680 cases. Seed 11.

On the 96 genuine variations, fraudulent verdicts stayed 0. Genuine calls moved from 32 to 26 because a model score no longer promotes an OCR mismatch. Those six are uncertain.

Foreign pages: 129 unrecognized, 12 uncertain, 0 genuine, 0 fraudulent.

Controlled edits that remove ink are fraudulent when the hole is strong and the wording matches (balance 14 px, capital 32 px). The subvention center is blank paper, so a 14 px hole there stays genuine. Red-ink shifts are not fraudulent.

API cases inside the stress suite passed: decline saves nothing, companies stay separate, an exact resubmit is genuine, a darker copy is genuine, another organization is unrecognized, a blank page is missing, malformed files are unreadable.

```bash
.venv/bin/python -m pytest tests/ --ignore=tests/test_real_inference.py -q --tb=no
```

89 passed, 1 skipped, exit code 0.

`tests/test_real_inference.py` was run on its own: 2 passed, and `test_raw_banksim_header_is_present` failed with `FileNotFoundError` for `fraud_detection/data/raw/banksim/bs140513_032310.csv`. That file is not in the checkout. The failure is outside stamp verification.

## 8. Security

References are stored under the organization string and are not read for a different string. Declined proposals do not enter the index. A blank or whitespace id is `missing_tenant` and writes nothing. `/v1/score` uses `entity_id` when present and non-blank, otherwise `receiver_id`.

At that revision there was no authentication. The follow-up in section 11 adds a per-organization secret on the HTTP API. Approval still means the caller accepted the crop. It does not prove the stamp is authentic. The service is not production-secure.

## 9. Limits

Image comparison can see a broken text line or a hole on these generated mutations. It cannot see a competent physical forgery that reproduces the drawing. Subtle spacing, ink, and scan noise overlap. Labellisation OCR is unstable for both classes, so those pages stay uncertain on purpose.

The real-world false-acceptance rate is unknown.

## 10. Answers and next steps

1. The stack is adequate for a first screening version: Pillow, PyMuPDF, SciPy alignment, Tesseract, and explicit rules.
2. LightGBM does not add a usable decision beyond reference matching. Using it as the classifier accuses most genuine scans.
3. The largest error source is the data, not the threshold. Most generated counterfeits sit inside the genuine scan envelope, and labellisation OCR does not confirm identity.
4. The dataset is not sufficient to train a general counterfeit classifier. Four identities, shared scan augmentation, no physical forgeries.
5. Software can keep abstaining, name a local ink anomaly, and refuse a blank tenant. It cannot invent a fifth identity or a physical forgery.
6. Keep the architecture, with the model off the decision path.
7. The next useful set is new stamp identities, enrolled from a trusted source, plus physical recaptures and physical alterations that were not generated from the enrolled file. Dozens of identities, with every capture of one identity kept in one split.
8. Postpone YOLO, embeddings, vector search, and another LightGBM training run until that set exists.

Ranked next work:

1. Collect physical recaptures and physical alterations of stamps that are not the four training designs. Without that, further threshold moves will keep fitting this generator.
2. Put an authenticated organization id in front of enroll and decide. The string partition is already in place.
3. Improve labellisation OCR or stop asking OCR to confirm that family, only after a labeled reading audit. The current abstention is the safe behavior.

## 11. Recall-oriented review, without a new fraud cutoff

The 187 generated counterfeit pages that stay `uncertain` were scored again, one family at a time, against the enrolled PDF. Five controlled recaptures of each PDF were scored in the same run: a 2° turn, a 12° turn, a 1.2 px blur, JPEG quality 60, and a grayscale copy. Nothing in that script changes a threshold. The per-case measurements are in `fraud_detection/evaluation/stamp_unresolved.json`. Full page images and difference pictures were not stored. `worst_block` is the weakest informative cell of the aligned 6×6 block map, which is what a later request now returns as `block_map`.

Verdicts on the 400 pages did not move.

|  | Genuine | Fraudulent | Uncertain | Unrecognized |
| --- | --- | --- | --- | --- |
| 200 reference pages | 9 | 0 | 191 | 0 |
| 200 counterfeit pages | 0 | 13 | 187 | 0 |

By family (reference genuine / counterfeit fraudulent): balance 0 / 7, capital 5 / 6, labellisation 0 / 0, subvention 4 / 0. Labellisation is `text_mismatch` on 50 / 50 reference pages and 47 / 50 counterfeit pages. That code is OCR disagreement, not a forgery finding.

Why the 187 stay uncertain:

| Group | n | row_gap min / median | worst_block min / median | low_block max | aligned score min / median |
| --- | --- | --- | --- | --- | --- |
| Reference pages | 200 | −0.0085 / 0.0916 | −0.0124 / 0.6083 | 0.333 | 0.6951 / 0.8826 |
| Uncertain counterfeits | 187 | −0.3440 / 0.0870 | −0.2971 / 0.3447 | 0.931 | 0.2331 / 0.8372 |
| Controlled recaptures | 20 | −0.3136 / 0.0887 | −0.2703 / 0.7060 | 1.000 | 0.1987 / 0.8866 |
| Counterfeits already fraudulent | 13 | −0.2523 / −0.0667 | −0.0741 / 0.0000 | 0.759 | 0.3964 / 0.6090 |

The uncertain counterfeits sit inside the same range as the reference scans and the controlled recaptures. A cutoff placed just outside every controlled recapture would flag 1 of 187 uncertain counterfeits on `worst_block` and 1 of 187 on `row_gap`. `low_block` above 0.333, the maximum on the 200 reference pages, flags 26 uncertain counterfeits and also the 12° turn and the grayscale copy of genuine PDFs. Those recaptures are ordinary capture damage. They are not proof of forgery, so that cutoff was not added. The existing text-line fraud rule was left as it is, including the 0.09 margin.

The 13 fraudulent pages are the same names as before: `balance_0028`, `balance_0036`, `balance_0044`, `balance_0047`, `balance_0073`, `balance_0081`, `balance_0086`, `capital_0019`, `capital_0038`, `capital_0065`, `capital_0079`, `capital_0086`, `capital_0091`. Two uncertain counterfeits are `poor_image_quality` (`capital_0023`, `labellisation_0078`), which is an unusable comparison, not a fraud call.

Review priority, from the branch that fired. This is not a probability.

| Verdict or code | review_recommended | risk_level |
| --- | --- | --- |
| `genuine` / `reference_match` | false | low |
| `fraudulent` or `local_ink_anomaly` | true | high |
| `possible_inserted_image` | true | high |
| `text_mismatch`, `insufficient_evidence`, `poor_image_quality`, unrecognized, missing | true | medium |

On these 400 JPEG pages that means high review for the 13 fraudulent counterfeits and for no reference page. Medium review for the other 191 reference pages and 187 counterfeit pages. `text_mismatch` stays medium because it is shared by genuine and generated labellisation pages. A high tier is a queue, not an automatic rejection.

Copy and paste. An exact crop of a genuine stamp is not identifiable as a paste. JPEG quality 60 and grayscale of the enrolled subvention render were both `genuine`. The evidence field `exact_stamp_copy_from_crop_alone` is false on every comparison. For a PDF, the response can include image-object and drawing counts. The clue `possible_inserted_image` is added only when the verdict is already uncertain or unrecognized and the file has at least one image object. It does not change the verdict. The genuine labellisation PDF already contains an image object, and a phone scan of a paper page is often one image, so the clue is not proof. Separating a pixel-perfect paste from the enrolled file needs something outside the crop: who issued the document, a signature on the PDF, or a record that this impression was used once.

Replicas. The labeled counterfeit pages are generator mutations (spacing, font, geometry, ink, and the same scan augmentation as the reference pages). `labels.csv`, which the dataset README says lists the mutation on each page, is not in this checkout. Filename suffixes are the labels. Multiple saved impressions for one organization are already compared, and the best verdict is kept. A genuine impression is not required to be pixel-identical. The controlled recaptures above are the available model of that variation, and they overlap the mutations.

Provenance. Every labeled row is a generated page from one of four source PDFs. The script enrolls that PDF and scores that family's pages together. It does not use a random page split. The filename holdout remains a non-split. These labels are not independently verified physical forgeries. No real-world detection rate is claimed, and no target percentage was set.

Security. The first saved reference for an organization returns `tenant_secret`. After that, `/v1/score`, `/v1/documents/check`, `/v1/documents/enroll`, and `/v1/documents/decide` for that organization id require the secret. Another organization's secret does not match. A blank id is still `missing_tenant` and writes nothing. Declining a proposal marks it `declined`, and a later approval of that id does not enroll. The first proposal, before any reference exists, can still be approved or declined without a secret so onboarding works. The in-process store used by the evaluation scripts does not ask for the secret. There is still no login. Whoever enrolls an organization id first receives the secret. A `proposal_id` is an unguessable token, and it is not enough to approve or reject a reference once that organization is locked. Approval still does not prove the stamp is authentic.

Commands after this change:

```bash
.venv/bin/python -m fraud_detection.evaluation.stamp_unresolved
```

Exit code 0. Wrote `fraud_detection/evaluation/stamp_unresolved.json`.

```bash
.venv/bin/python -m pytest tests/test_stamp_review.py tests/test_stamp_robustness.py tests/test_stamp_verifier.py tests/test_documents.py tests/test_api.py -q --tb=line
```

Exit code 0. 39 passed.

```bash
.venv/bin/python -m pytest tests/ --ignore=tests/test_real_inference.py -q --tb=line
```

Exit code 0. 96 passed, 1 skipped.

```bash
.venv/bin/python -m pytest tests/test_real_inference.py -q --tb=line
```

Exit code 1. 2 passed. `test_raw_banksim_header_is_present` failed with `FileNotFoundError` for `fraud_detection/data/raw/banksim/bs140513_032310.csv`. That file is not in the checkout. It is outside stamp verification.

```bash
.venv/bin/python -m fraud_detection.evaluation.stamp_stress
```

Exit code 0. 680 cases. Seed 11. Results in `fraud_detection/evaluation/stamp_stress_results`.

Verdicts on the 400 labeled pages match the previous reference-rule run: 9 / 200 reference pages genuine, 0 fraudulent; 0 / 200 counterfeit pages genuine, 13 fraudulent, 187 uncertain. False accepts: none. False fraud on reference pages: none. Fraudulent precision on this generated set remains 13 / 13. Recall remains 13 / 200. That recall is not a new claim and is not a real-world rate.

Review on those 400 pages:

| | Review recommended | High risk | Medium risk | Low, not queued |
| --- | --- | --- | --- | --- |
| 200 reference | 191 | 0 | 191 | 9 |
| 200 counterfeit | 200 | 13 | 187 | 0 |

High risk is exactly the 13 `local_ink_anomaly` fraud verdicts. By family, high-risk counterfeits are balance 7, capital 6, labellisation 0, subvention 0. No reference page is high risk. The medium queue is 191 reference pages and 187 counterfeit pages, so about half of the medium queue is a generated counterfeit. That is the overlap, not a calibrated yield.

Genuine variations: mild 22 genuine / 26 uncertain, medium 3 / 25, hard 1 / 19. Fraudulent variations: 0. Foreign pages: 129 unrecognized, 12 uncertain, 0 genuine, 0 fraudulent. Controlled edits: the balance 14 px hole and the capital 32 px hole are fraudulent; the capital 14 px hole, both labellisation holes, and the subvention 32 px hole are uncertain at high risk because the ink anomaly is present and not strong enough, or the wording does not confirm it. The subvention 14 px hole stays genuine. Red-ink shift is not fraudulent. All 13 API workflow checks passed, including decline-saves-nothing, exact resubmit genuine, company isolation, and a blank page missing.
