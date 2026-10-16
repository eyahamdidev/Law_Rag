#!/usr/bin/env python3
"""Download the files listed in download_manifest.csv into this pack.

Run from anywhere:   python download.py            (all direct + api rows)
                     python download.py --csv      (also convert World Bank JSON to CSV)
                     python download.py --dry-run  (print what it would do)
Standard library only. Existing files are skipped. A log is written to download_log.csv.
Manual rows (method=manual) are printed as a checklist: they need a browser, a login or a decision.
"""
import argparse, csv, hashlib, json, sys, time, urllib.request, urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACK = HERE.parent
UA = {"User-Agent": "Mozilla/5.0 (bp-dataset-pack downloader)"}


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type", "")


def wdi_to_csv(json_path):
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    if not isinstance(data, list) or len(data) < 2 or not data[1]:
        return None
    out = Path(json_path).with_suffix(".csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["indicator_id", "indicator", "country", "year", "value"])
        for r in sorted(data[1], key=lambda x: x["date"]):
            w.writerow([r["indicator"]["id"], r["indicator"]["value"], r["country"]["value"], r["date"], r["value"]])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--csv", action="store_true", help="convert World Bank JSON to CSV")
    ap.add_argument("--manifest", default=str(HERE / "download_manifest.csv"))
    a = ap.parse_args()

    rows = list(csv.DictReader(open(a.manifest, encoding="utf-8-sig")))
    log = []
    for r in rows:
        if r["method"] == "manual":
            continue
        dest = PACK / r["target_dir"] / r["filename"]
        status = ""
        if dest.exists():
            status = "skipped_exists"
        elif a.dry_run:
            status = "dry_run"
        else:
            try:
                body, ctype = fetch(r["url"])
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(body)
                status = "ok"
                if r["method"] == "api" and a.csv:
                    wdi_to_csv(dest)
            except urllib.error.HTTPError as e:
                status = f"http_{e.code}"
            except Exception as e:  # network error, DNS, timeout
                status = f"error_{type(e).__name__}"
            time.sleep(0.5)
        size = dest.stat().st_size if dest.exists() else 0
        sha = hashlib.sha256(dest.read_bytes()).hexdigest() if dest.exists() else ""
        print(f"{status:16s} {r['id']:34s} {r['target_dir']}/{r['filename']}")
        log.append(dict(id=r["id"], status=status, bytes=size, sha256=sha, url=r["url"]))
    if not a.dry_run:
        with open(HERE / "download_log.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["id", "status", "bytes", "sha256", "url"])
            w.writeheader(); w.writerows(log)

    print("\nMANUAL CHECKLIST (browser needed):")
    for r in rows:
        if r["method"] == "manual":
            print(f"  [ ] {r['id']:22s} -> {r['target_dir']}/   {r['url']}\n        {r['note']}")
    bad = [l for l in log if l["status"] not in ("ok", "skipped_exists", "dry_run")]
    if bad:
        print(f"\n{len(bad)} download(s) failed: see download_log.csv (a 404 usually means the file name changed: open the page and download by hand).")


if __name__ == "__main__":
    main()
