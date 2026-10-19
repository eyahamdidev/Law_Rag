# Enrollment store

This directory starts empty on purpose.

Each user enrolls their own genuine stamp. The Score API crops it, asks for approval, and saves it with the enrollment comment. Later documents are judged against that saved crop.

The supervised verifier weights live in `fraud_detection/models/artifacts/stamp_verifier.joblib`. They are not an enrolled stamp. Do not put training crops or another user's stamp in this folder.
