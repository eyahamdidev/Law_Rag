# Stamp identity dataset v3
30 stamp identities (26 new fictitious + your 4 originals), 1726 rows. Every issuer is fictitious; every stamp carries SPÉCIMEN / FAUX.
- `manifest.csv`: id, identity_id, family (oval|circle|rect|text), organization, source_dataset (v3 = new, v2 = your 4 originals),
  kind (genuine = clean reference | genuine_variant = harmless degradation | counterfeit), difficulty, mutations, split, parent_reference, stamp_params, jpeg_q.
- Per new identity: 1 genuine + 10 harmless variants + 40 counterfeit (1-4 mutations, subtle/medium/obvious). Same degradation distribution for harmless and counterfeit rows
  (grayscale, down/up-scaling, rotation, blur, noise, tint, contrast, JPEG), so degradation is not a fraud signal.
- Split is BY IDENTITY: 18 train / 6 val / 6 test, stratified by family. No identity appears in two splits (verified).
- The 4 originals use page-level stamp crops from v2 (different context rendering); they carry only genuine_variant + counterfeit rows.
- `evaluate.py`: thresholds chosen on val, then reports on held-out identities: fraud detected, missed, uncertain %, false-fraud rate, per family/difficulty/identity/mutation.
- Regenerate/scale: `python make_identities.py --counterfeit 50 --harmless 10 --seed 7 --out dataset2` (needs reportlab, pillow, numpy, svglib, arabic-reshaper, python-bidi, poppler).
Caveats: generated counterfeits test robustness, not real forger behaviour; validate on real printed/photographed stamps; the 26 new identities are synthetic designs, so add real genuine stamps when you can.
