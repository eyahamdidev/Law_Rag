from __future__ import annotations

from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parent
RAW = PACKAGE / "data" / "raw"
PROCESSED = PACKAGE / "data" / "processed"
GENUINE = PACKAGE / "data" / "genuine"
STAMP_DATASET = PACKAGE / "data" / "stamp_dataset_v2" / "dataset_all"
ARTIFACTS = PACKAGE / "models" / "artifacts"
STAMP_VERIFIER = ARTIFACTS / "stamp_verifier.joblib"
EVAL = PACKAGE / "evaluation"
