#!/usr/bin/env python3
"""Identity-split evaluation. Input: manifest.csv + predictions.csv (columns: id,score) where score = P(counterfeit).
Thresholds are chosen on VAL only; results are reported on TEST (held-out identities).
  python evaluate.py --manifest dataset/manifest.csv --pred preds.csv --target-fpr 0.05 [--split test]"""
import argparse,csv,collections,json
import numpy as np
ap=argparse.ArgumentParser();ap.add_argument("--manifest",default="dataset/manifest.csv");ap.add_argument("--pred",required=True)
ap.add_argument("--target-fpr",type=float,default=.05);ap.add_argument("--split",default="test");a=ap.parse_args()
S={r["id"]:float(r["score"]) for r in csv.DictReader(open(a.pred))};rows=[r for r in csv.DictReader(open(a.manifest,encoding="utf-8")) if r["id"] in S]
isg=lambda r:r["kind"]!="counterfeit";val=[r for r in rows if r["split"]=="val"]
vg=np.array([S[r["id"]] for r in val if isg(r)]);vc=np.array([S[r["id"]] for r in val if not isg(r)])
t_hi=float(np.quantile(vg,1-a.target_fpr));t_lo=min(float(np.quantile(vc,a.target_fpr)),t_hi)
print(f"thresholds from val: flag fraud if score>={t_hi:.3f}; accept if score<={t_lo:.3f}; between = uncertain")
def rep(name,sub):
    g=[S[r["id"]] for r in sub if isg(r)];c=[S[r["id"]] for r in sub if not isg(r)]
    out=[name.ljust(34)]
    if c:
        c=np.array(c);out.append(f"fraud detected {np.mean(c>=t_hi):.1%} | missed {np.mean(c<=t_lo):.1%} | uncertain {np.mean((c>t_lo)&(c<t_hi)):.1%}")
    if g:
        g=np.array(g);out.append(f"false-fraud {np.mean(g>=t_hi):.1%} | genuine uncertain {np.mean((g>t_lo)&(g<t_hi)):.1%}")
    print("  ".join(out)+f"  (n={len(sub)})")
T=[r for r in rows if r["split"]==a.split];print(f"\n== {a.split} (held-out identities: {len(set(r['identity_id'] for r in T))}) ==");rep("ALL",T)
for k in ("family","difficulty","identity_id"):
    print(f"\n-- by {k} --")
    for v in sorted(set(r[k] for r in T)): rep(f"{k}={v}",[r for r in T if r[k]==v or (k=="difficulty" and isg(r))])
print("\n-- by mutation type (counterfeits with that mutation + all genuine) --")
mt=collections.defaultdict(list)
for r in T:
    if not isg(r):
        for m in set(x.split(":")[0] for x in json.loads(r["mutations"])): mt[m].append(r)
for m,sub in sorted(mt.items()): rep(f"mutation={m}",sub+[r for r in T if isg(r)])
