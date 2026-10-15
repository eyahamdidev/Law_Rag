# plan_dataset (starter)

raw/pitch_cases   15 dev cases (docx). Labels from the answer key (fraudulent -> bad). The verdict rules were TUNED on these.
raw/invented_tn   12 invented Tunisian-style plans (not real companies), written to represent good / moderate / bad.
manifest.csv      every file: source, sha256, pages, characters, language, whether the module can read it.
labels.csv        verdict, split (dev/test), provenance. Both sources above are forced into dev: a score on them proves nothing.

All 27 are artificial. There is NO real plan here yet. Add real ones:

    python scripts/build_dataset.py fetch plan_dataset --urls scripts/sources.csv --contact "Your Name"
    python scripts/build_dataset.py add   plan_dataset --folder classmates_plans --source classmates
    python scripts/build_dataset.py report plan_dataset

Then have two people fill the verdict column (see eval/LABELING_GUIDE.md) and run:

    python eval/run_labeled_eval.py plan_dataset/raw plan_dataset/labels.csv --split dev --llm off

New plans get a random split (1 in 3 is test). Do not tune on test.
