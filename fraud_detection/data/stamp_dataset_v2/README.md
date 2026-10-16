# Stamp datasets v2: four reference documents
All issuers are fictitious; every stamp carries SPECIMEN / FAUX / FICTIF text. Reference PDFs are the four files you supplied;
the generator reproduces the three vector references with 0 pixel difference (checked) and re-uses the embedded stamp image of the Labellisation PDF.

| doc | reference document | stamp type | counterfeit mutations |
|---|---|---|---|
| balance | Attestation de solde bancaire (BMC) | text-only, blue | size, letter-spacing, font substitution, dropped accents, baseline, rotation, offset, ink shade, dash |
| capital | Attestation de libération du capital (BPAE) | oval, blue, curved text | same as above + oval proportions/line weight |
| subvention | Décision d'attribution de subvention (FRAI) | rectangular, violet | same as above + rectangle size, line weight, inner-border inset |
| labellisation | Attestation de labellisation (original) | round raster stamp image | scale, rotation, offset, ink-colour shift, opacity, resolution mismatch, JPEG blockiness, ink flattening, edge clipping |

Layout: `dataset_all/<doc>/pages|stamp_crops/*.jpg`, `dataset_all/<doc>/labels.csv`, `dataset_all/labels_all.csv` (all docs, column `doc`).
Columns: label (reference|counterfeit), difficulty (none|subtle|medium|obvious), mutations (exact changes), split (80/20), scan-augmentation values, stamp_params (full spec).
Regenerate / scale: `python make_all_datasets.py --n 500 --seed 7 --out dataset_big` (needs reportlab, pillow, numpy, pdfplumber, svglib, arabic-reshaper, python-bidi, poppler).

Training notes
- Label by stamp class only: planted body flaws (see Answer_Key_Specimen_01-03.md) are identical in reference and counterfeit pages.
- Scan augmentation (rotation, blur, noise, tint, JPEG) uses the same distribution for both classes.
- Per-document models see one reference each; to test generalization, hold out a mutation type or a whole document.
- Validate on real printed-and-photographed stamps before trusting metrics; synthetic data overestimates accuracy.
