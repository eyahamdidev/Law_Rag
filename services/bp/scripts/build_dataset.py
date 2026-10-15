"""Build one plan dataset: raw files + manifest.csv + labels.csv.

    python scripts/build_dataset.py add  plan_dataset  --folder my_plans --source classmates [--labels some.csv]
    python scripts/build_dataset.py fetch plan_dataset --urls scripts/sources.csv --contact "Your Name"
    python scripts/build_dataset.py report plan_dataset

* ``add`` copies plans you already have. Duplicates (same sha256) are skipped. ``--labels`` is an optional csv with
  columns file,verdict[,provenance] for plans whose verdict is already known.
* ``fetch`` downloads PDF/DOCX files listed in sources.csv (url,source,language,note). It obeys robots.txt, waits
  between requests and sends a User-Agent with your contact. Check each site's terms: files are for LOCAL testing,
  never commit them.
* Every file is opened with the module's own reader, so manifest.csv tells you which ones are unreadable
  (scans, legacy .doc/.xls, password-protected).
* labels.csv: a human fills 'verdict' (good / moderate / bad). 'provenance' says where a label came from.
  Plans that the rules were tuned on are forced into the dev split. Use eval/run_labeled_eval.py with
  <dataset>/raw as the plans folder.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import random
import re
import shutil
import sys
import time
import urllib.robotparser as robotparser
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
EXT = (".pdf", ".docx", ".doc", ".txt", ".xlsx", ".xls")
MAN = ["file", "source", "sha256", "added", "origin_url", "pages", "chars", "language", "status", "note"]
LAB = ["file", "verdict", "split", "provenance", "rater", "notes", "total_investment", "revenue_y1"]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def read_csv(p: Path) -> list[dict]:
    if not p.exists():
        return []
    with p.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(p: Path, cols: list[str], rows: list[dict]) -> None:
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def guess_lang(text: str) -> str:
    t = " " + re.sub(r"\W+", " ", text.lower()[:20000]) + " "
    fr = sum(t.count(w) for w in (" le ", " la ", " les ", " des ", " et ", " du ", " pour "))
    en = sum(t.count(w) for w in (" the ", " and ", " of ", " to ", " for ", " with "))
    ar = sum(1 for c in text[:20000] if "؀" <= c <= "ۿ")
    return "ar" if ar > 200 and ar > max(fr, en) else ("fr" if fr > en else "en") if (fr or en) else "?"


def inspect(path: Path) -> dict:
    if path.suffix.lower() in (".doc", ".xls"):
        return {"status": "convert_to_docx_or_xlsx_first", "pages": "", "chars": "", "language": "?"}
    try:
        from app.intake import read_document

        d = read_document(path.read_bytes())
        n = len(d.text.strip())
        status = "scan_no_text" if d.scanned_pages and n < 500 else ("ok" if n >= 500 else "very_short")
        return {"status": status, "pages": d.page_count or "", "chars": n, "language": guess_lang(d.text)}
    except Exception as exc:  # noqa: BLE001
        return {"status": f"unreadable: {str(exc)[:60]}", "pages": "", "chars": "", "language": "?"}


def register(ds: Path, rel: str, source: str, url: str = "", note: str = "") -> None:
    man = read_csv(ds / "manifest.csv")
    path = ds / "raw" / rel
    row = {"file": rel, "source": source, "sha256": sha(path.read_bytes()), "added": date.today().isoformat(), "origin_url": url, "note": note}
    row.update(inspect(path))
    man = [m for m in man if m["file"] != rel] + [row]
    write_csv(ds / "manifest.csv", MAN, sorted(man, key=lambda r: r["file"]))


def ensure_label(ds: Path, rel: str, verdict: str = "", provenance: str = "", forced_dev: bool = False) -> None:
    labs = read_csv(ds / "labels.csv")
    cur = next((r for r in labs if r["file"] == rel), None)
    if cur is None:
        seed = int(sha(rel.encode())[:8], 16)
        split = "dev" if forced_dev else ("test" if random.Random(seed).random() < 1 / 3 else "dev")
        cur = {c: "" for c in LAB} | {"file": rel, "split": split}
        labs.append(cur)
    if verdict and not cur["verdict"]:
        cur["verdict"], cur["provenance"] = verdict, provenance
    write_csv(ds / "labels.csv", LAB, sorted(labs, key=lambda r: r["file"]))


def known_hashes(ds: Path) -> set[str]:
    return {m["sha256"] for m in read_csv(ds / "manifest.csv")}


def cmd_add(a) -> None:
    ds = Path(a.dataset)
    (ds / "raw" / a.source).mkdir(parents=True, exist_ok=True)
    labels = {r["file"]: r for r in read_csv(Path(a.labels))} if a.labels else {}
    added = dup = 0
    for f in sorted(Path(a.folder).rglob("*")):
        if not f.is_file() or f.suffix.lower() not in EXT:
            continue
        h = sha(f.read_bytes())
        if h in known_hashes(ds):
            dup += 1
            continue
        rel = f"{a.source}/{f.name}"
        shutil.copy2(f, ds / "raw" / rel)
        register(ds, rel, a.source, note=a.note)
        lab = labels.get(f.name) or labels.get(f.stem) or {}
        ensure_label(ds, rel, (lab.get("verdict") or "").strip().lower(), lab.get("provenance") or ("given" if lab.get("verdict") else ""), forced_dev=a.tuned)
        added += 1
    print(f"added {added}, skipped {dup} duplicates")


def cmd_fetch(a) -> None:
    import httpx

    ds = Path(a.dataset)
    client = httpx.Client(headers={"User-Agent": f"bp-dataset-builder ({a.contact})"}, timeout=60, follow_redirects=True)
    robots: dict = {}
    for r in read_csv(Path(a.urls)):
        url, source = r["url"].strip(), (r.get("source") or "web").strip()
        host = "{0.scheme}://{0.netloc}".format(urlparse(url))
        if host not in robots:
            rp = robotparser.RobotFileParser()
            try:
                rp.set_url(host + "/robots.txt")
                rp.read()
            except Exception:  # noqa: BLE001
                rp = None
            robots[host] = rp
        if robots[host] is not None and not robots[host].can_fetch(client.headers["User-Agent"], url):
            print(f"skip (robots.txt): {url}")
            continue
        try:
            resp = client.get(url)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED {url}: {exc.__class__.__name__} {exc}")
            continue
        data = resp.content
        if sha(data) in known_hashes(ds):
            print(f"duplicate: {url}")
            continue
        ext = ".pdf" if data[:5] == b"%PDF-" else (".docx" if data[:2] == b"PK" else (".doc" if data[:4] == b"\xd0\xcf\x11\xe0" else ""))
        if not ext:
            print(f"not a pdf/docx/doc (login page or html?): {url}")
            continue
        name = re.sub(r"[^\w.-]+", "_", Path(urlparse(url).path).stem)[:60] or sha(data)[:10]
        rel = f"{source}/{name}{ext}"
        (ds / "raw" / source).mkdir(parents=True, exist_ok=True)
        (ds / "raw" / rel).write_bytes(data)
        register(ds, rel, source, url=url, note=r.get("note", ""))
        ensure_label(ds, rel)
        print(f"saved {rel}")
        time.sleep(a.delay)


def cmd_report(a) -> None:
    ds = Path(a.dataset)
    man, labs = read_csv(ds / "manifest.csv"), read_csv(ds / "labels.csv")
    print(f"{len(man)} files")
    for key in ("source", "status", "language"):
        counts: dict = {}
        for m in man:
            counts[m[key]] = counts.get(m[key], 0) + 1
        print(f"  by {key}: {counts}")
    done = [r for r in labs if r["verdict"]]
    print(f"labelled: {len(done)}/{len(labs)}  " + str({v: sum(r['verdict'] == v for r in done) for v in ('good', 'moderate', 'bad')}))
    print(f"split: dev {sum(r['split'] == 'dev' for r in labs)}, test {sum(r['split'] == 'test' for r in labs)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("dataset")
    p.add_argument("--folder", required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--labels")
    p.add_argument("--note", default="")
    p.add_argument("--tuned", action="store_true", help="the verdict rules were tuned on these plans: force them into dev")
    p = sub.add_parser("fetch")
    p.add_argument("dataset")
    p.add_argument("--urls", required=True)
    p.add_argument("--contact", default="student project")
    p.add_argument("--delay", type=float, default=3.0)
    p = sub.add_parser("report")
    p.add_argument("dataset")
    a = ap.parse_args()
    {"add": cmd_add, "fetch": cmd_fetch, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    main()
