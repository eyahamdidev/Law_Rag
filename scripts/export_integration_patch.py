"""Export legal changes against the team's baseline without deleting other datasets."""
import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = "b1af0e57b77359ad663d14dd4efbde92bb8c3e5d"
# Review shared backend modifications before applying to a newer team checkout.
# The team README, Docker configuration and non-legal datasets are excluded.
PATHS = [
    "backend", "frontend", "requirements.txt", "requirements-legal.txt",
    "requirements-legal.lock.txt", "scripts", "docs", "LOCAL_SETUP.md",
    ".vscode", ".env.example", ".gitignore", ".gitattributes",
    "Legal-Agent.code-workspace", "run-agent.cmd",
    "law/TUNISIA_LEGAL_BUSINESS_CORPUS/03_COMPANIES/tn076ar.pdf",
    "law/TUNISIA_LEGAL_BUSINESS_CORPUS/03_COMPANIES/tn076ar.pdf.meta.json",
    "law/TUNISIA_LEGAL_BUSINESS_CORPUS/08_INTELLECTUAL_PROPERTY",
    "law/TUNISIA_LEGAL_BUSINESS_CORPUS/09_CONTRACTS", "law/contract_templates",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=BASE, help="Team baseline commit available locally")
    parser.add_argument("--output", type=Path, default=ROOT / "data/handoff/legal-component.patch")
    args = parser.parse_args()
    patch = subprocess.check_output([
        "git", "diff", "--binary", "--full-index", "--diff-filter=ACM",
        args.base, "HEAD", "--", *PATHS,
    ], cwd=ROOT)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(patch)
    print(f"Exported {len(patch):,} bytes to {args.output}")
    print("Review with git apply --stat, then git apply --check before applying.")


if __name__ == "__main__":
    main()
