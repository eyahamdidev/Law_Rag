# bp v14: why the plans were poor, and what changed

Copy the files in this zip over the same paths in your repo (the hierarchy mirrors it). Nothing else was touched.

## What was wrong (both modes)

1. **The anti-fabrication writer never reached the plan the founder downloads.** `final_writer` v6 ran *after* the plan
   .docx was built and only fed the review report. The .docx was built by `plan_doc.polish`, which had no such rules.
2. **`plan_doc.polish` invented things.** It was not given the founders' answer yet rewrote that text, so the model made
   up a team ("our CEO has over 10 years of experience"). It also had no label telling "total investment" from
   "external funding sought" (hence "$8,000" in a TND plan), and its prompt used `[[NAME_1]]` as an *example*, which the
   model copied as a person's name and `unmask` turned into the project name.
3. **The number guard only caught digits.** Invented sources, "recent studies", "a wealth of experience", partners and
   pilots passed untouched.
4. **Chat mode never asked** for the team's background, competitors, channels, production means, suppliers or equipment
   purchases (`key_skills`, `competitors`, `channels`, `production_means`, `suppliers`, `capex_items`), so the plan had
   nothing true to say there. Founders = project name was accepted. "sa" (French "his/her") was read as legal form SA,
   and ordinary words ("new", "start") as the business stage.
5. **Upload mode leaked names.** The masker was built before the document was read, so names that only appear in the
   uploaded plan went to the model in clear text. Founder chunks like "Aya - CEO" were masked as one string.

## What changed

| File | Change |
|---|---|
| `app/agents/claim_guard.py` (new) | Pure, model-free guard: unsupported experience / source / market / partner / pilot claims become `[NEEDED: ...]` questions; foreign currency is rewritten to TND and marked; hype words removed. Idempotent; digit-free tokens protect placeholders from the number guard. |
| `app/plan_doc.py` | `polish` sees founders (masked) and labelled anchors, retries once on invented figures, runs claim guard + number guard, returns the model's `needed` questions into the open items. New `consistency_notes` (contradictions in the founder's own answers become questions). `build_plan_docx(final_plan=...)` opens the plan with the six-section narrative. Fixed duplicate summary, hard-coded "no facts were added" note and the "(score N/100)" leak. |
| `prompts/bp/plan_writer/v2.yaml` (new) | Hard rules from `final_writer@v6`, no example token, missing points returned as `needed`. v1 is kept for rollback. |
| `app/pipeline.py` | Final writer now runs **before** the plan document and is passed into it; founders are part of its facts; every section goes through the claim guard (`_guard_final_plan`); masker is rebuilt after parsing an upload; `_names` masks the person, not "name - role". |
| `app/interview.py` | Chat asks the six missing topics; refuses a team answer that is just the project name; legal form only from an upper-case SARL/SUARL/SA/SAS; stage only from explicit phrases; bank entries of an unreadable type are skipped, not fatal; free text is tidied. |
| `tests/test_claim_guard.py`, `tests/test_interview_v14.py`, `tests/test_plan_doc_v14.py` (new) | 21 tests. |

`app/agents/final_writer.py`, `masking.py`, `writer.py` are unchanged (the guard is applied in `pipeline.py`).

## Not done / limits

- **Not run against your real repo.** I only had these files, so I tested the new modules with stand-ins for the rest
  (21 new tests pass there). Run `pytest services/bp/tests` first. Existing tests that count chat turns until
  "ready to review" may need their expected number raised: the chat now asks 16 core questions instead of 14.
- Upload-review *scoring* (`parser`, `assessment`, `reviewer`) was not examined in depth and is unchanged.
- No real-model run: the guards are tested on crafted bad outputs, not on live generations.
- Check that `key_skills`, `competitors`, `channels`, `production_means`, `suppliers`, `capex_items` exist in your
  question bank (the chat silently skips any that don't, or whose type it can't read; `capex_items` as a table type is skipped).
- The Drive folder contains a `.env`. I did not open it and it is not in this zip. If its key was ever committed or shared, rotate it.
