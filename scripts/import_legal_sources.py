"""Import selected user-supplied WIPO texts into ignored local corpus storage."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    ("tn001en_1.pdf", "08_INTELLECTUAL_PROPERTY", "Patents — Law 2000-84 — English supplied edition", "en"),
    ("tn001ar_1.pdf", "08_INTELLECTUAL_PROPERTY", "Patents — Law 2000-84 — Arabic supplied edition", "ar"),
    ("tn014en_1.pdf", "08_INTELLECTUAL_PROPERTY", "Trademarks — Law 2001-36 — English supplied edition", "en"),
    ("tn085ar_1.pdf", "08_INTELLECTUAL_PROPERTY", "Copyright — Law 1994-36 amended by Law 2009-33 — Arabic supplied edition", "ar"),
    ("tn034fr.pdf", "09_CONTRACTS", "Code des obligations et des contrats — supplied 2005 edition", "fr"),
    ("tn076ar.pdf", "03_COMPANIES", "Code de commerce — supplied Arabic 2018 edition", "ar"),
    ("wipo-pub-2008-en-wipo-guide-to-trade-secrets-and-innovation.pdf", "10_WIPO_GUIDES", "WIPO Guide to Trade Secrets and Innovation — educational guide", "en"),
    ("wipo-pub-917-1-en-inventing-the-future.pdf", "10_WIPO_GUIDES", "WIPO Inventing the Future — educational guide", "en"),
    ("wipo-pub-918-23-en-creative-expression.pdf", "10_WIPO_GUIDES", "WIPO Creative Expression — educational guide", "en"),
    ("wipo-pub-961-ar-enterprising-ideas.pdf", "10_WIPO_GUIDES", "WIPO Enterprising Ideas — educational guide", "ar"),
]
VERIFIED_SOURCE_LINKS = {
    "tn001en_1.pdf": "https://www.wipo.int/wipolex/en/legislation/details/3819",
    "tn001ar_1.pdf": "https://www.wipo.int/wipolex/en/legislation/details/3819",
    "tn014en_1.pdf": "https://www.wipo.int/wipolex/en/text/201850",
    "tn034fr.pdf": "https://www.wipo.int/wipolex/fr/text/201900",
}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path.home() / "Downloads")
    args = parser.parse_args()
    destination = ROOT / "data" / "corpus" / "law"
    shutil.copytree(ROOT / "law" / "TUNISIA_LEGAL_BUSINESS_CORPUS", destination, dirs_exist_ok=True)
    report = []
    for filename, category, title, language in SOURCES:
        source = args.input / filename
        if not source.is_file():
            report.append({"file": filename, "status": "not_supplied"})
            continue
        target = destination / category / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        metadata = {"name": title, "lang": language, "jurisdiction": "TN",
                    "article_numbering":"bare_en" if filename=="tn001en_1.pdf" else None,
                    "act":{"tn001en_1.pdf":"Law No. 2000-84","tn001ar_1.pdf":"Law No. 2000-84","tn014en_1.pdf":"Law No. 2001-36"}.get(filename),
                    "source_kind": "educational_guide" if category == "10_WIPO_GUIDES" else "legislation",
                    "provenance": "User-supplied WIPO download; exact original document URL not recorded",
                    "current_version_verified": False,
                    "url": VERIFIED_SOURCE_LINKS.get(filename),
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
        target.with_name(target.name + ".meta.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        report.append({"file": filename, "status": "imported", **metadata})
    (ROOT / "data" / "corpus" / "import-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    env = ROOT / ".env"
    content = env.read_text(encoding="utf-8-sig") if env.exists() else ""
    rows = [line for line in content.splitlines() if not line.startswith("LAW_CORPUS_DIR=")]
    rows.append("LAW_CORPUS_DIR=data/corpus/law")
    env.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"Imported {sum(r['status'] == 'imported' for r in report)} legal sources into ignored local data storage.")

if __name__ == "__main__":
    main()
