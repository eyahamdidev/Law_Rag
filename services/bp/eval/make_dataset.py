import json
from pathlib import Path

from eval.synthetic import dataset

out = Path(__file__).parent / "datasets" / "bp_synthetic_financial.jsonl"
out.write_text("\n".join(json.dumps(r) for r in dataset(7)) + "\n")
print("wrote", out)
