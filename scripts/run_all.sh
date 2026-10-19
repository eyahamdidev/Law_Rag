#!/usr/bin/env bash
set -euo pipefail
cd /workspace
bash scripts/download_public_data.sh
.venv/bin/python -u -m fraud_detection train
.venv/bin/pytest
.venv/bin/python -m fraud_detection evaluate
