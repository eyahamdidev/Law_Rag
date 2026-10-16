"""Describe a big data folder (or one big file) in a small report you can send me.

It reads your data locally and writes two small files: data_profile.json and data_profile.md.
Nothing is uploaded and no network call is made. Send me only those two files.

Usage (Windows PowerShell, from services/bp):
    python scripts/profile_data.py "C:\\path\\to\\your\\data"
    python scripts/profile_data.py "C:\\path\\to\\big_file.csv" --out report

Options:
    --no-samples    leave out all text excerpts (only counts, columns and statistics)
    --max-files N   profile at most N files per folder in detail (default 40)
    --sample-chars  length of each text excerpt (default 300)

Optional packages make it richer: pymupdf (pdf), python-docx (docx), openpyxl (xlsx).
Without them those files are only counted. Excerpts have emails and phone numbers masked.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import re
import statistics
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

csv.field_size_limit(10_000_000)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d\s.-]{7,}\d)(?!\d)")
FR = {"le", "la", "les", "de", "des", "du", "et", "est", "une", "pour", "dans", "que", "sur", "avec", "par"}
EN = {"the", "and", "of", "to", "in", "is", "for", "with", "that", "on", "as", "are", "this"}
LABELISH = re.compile(r"label|class|target|verdict|status|outcome|result|score|rating|fraud|approved|funded|default|category|type", re.I)


def mask(s: str) -> str:
    return PHONE.sub("[phone]", EMAIL.sub("[email]", s))


def language(text: str) -> str:
    if not text:
        return "unknown"
    ar = sum("\u0600" <= c <= "\u06ff" for c in text[:5000])
    if ar > 0.3 * min(len(text), 5000):
        return "ar"
    words = re.findall(r"[a-zàâçéèêëîïôûùüÿœ']+", text[:5000].lower())
    fr, en = sum(w in FR for w in words), sum(w in EN for w in words)
    return "fr" if fr > en else "en" if en > fr else "unknown"


def human(n: float) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {u}"
        n /= 1024
    return f"{n:.1f} PB"


# ----------------------------------------------------------------------------- tables
def profile_rows(header: list[str], rows_iter, max_rows: int = 50_000) -> dict:
    cols = [{"name": h, "n": 0, "empty": 0, "nums": [], "vals": Counter(), "maxlen": 0} for h in header]
    total = 0
    for row in rows_iter:
        total += 1
        if total <= max_rows:
            for c, v in zip(cols, row):
                v = "" if v is None else str(v).strip()
                c["n"] += 1
                if not v:
                    c["empty"] += 1
                    continue
                c["maxlen"] = max(c["maxlen"], len(v))
                try:
                    c["nums"].append(float(v.replace(",", ".").replace(" ", "")))
                except ValueError:
                    pass
                if len(c["vals"]) < 2000:
                    c["vals"][v[:60]] += 1
    out = []
    for c in cols:
        filled = c["n"] - c["empty"]
        info = {"name": c["name"], "empty_pct": round(100 * c["empty"] / c["n"], 1) if c["n"] else None, "max_len": c["maxlen"]}
        if filled and len(c["nums"]) >= 0.8 * filled:
            nums = c["nums"]
            info["type"] = "number"
            info["min"], info["median"], info["max"] = min(nums), statistics.median(nums), max(nums)
        else:
            info["type"] = "text"
            info["distinct_seen"] = len(c["vals"])
            if len(c["vals"]) <= 25:
                info["values"] = {mask(k): v for k, v in c["vals"].most_common(25)}
                info["label_like"] = bool(LABELISH.search(c["name"])) or len(c["vals"]) <= 6
        out.append(info)
    return {"rows": total, "rows_profiled": min(total, max_rows), "columns": out}


def read_csv(path: Path | None, data: bytes | None = None) -> dict:
    raw = data if data is not None else path.read_bytes()[:50_000_000]
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return {"error": "encoding not readable"}
    dialect = csv.excel
    try:
        dialect = csv.Sniffer().sniff(text[:5000], delimiters=",;\t|")
    except csv.Error:
        pass
    reader = csv.reader(io.StringIO(text), dialect)
    header = next(reader, [])
    return profile_rows(header, reader)


def read_xlsx(path: Path) -> dict:
    try:
        import openpyxl
    except ImportError:
        return {"note": "install openpyxl to profile xlsx"}
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheets = {}
    for ws in wb.worksheets[:12]:
        it = ws.iter_rows(values_only=True)
        header = [str(h or f"col{i}") for i, h in enumerate(next(it, []))]
        sheets[ws.title] = profile_rows(header, it)
    return {"sheets": sheets}


def read_json(path: Path) -> dict:
    size = path.stat().st_size
    if path.suffix == ".jsonl" or size > 200_000_000:
        keys: Counter = Counter()
        n = 0
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                n += 1
                if n <= 5000:
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            keys.update(obj.keys())
                    except ValueError:
                        pass
        return {"records": n, "keys": dict(keys.most_common(40))}
    obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if isinstance(obj, list):
        keys = Counter(k for r in obj[:5000] if isinstance(r, dict) for k in r)
        return {"records": len(obj), "keys": dict(keys.most_common(40))}
    return {"top_level_keys": list(obj)[:40] if isinstance(obj, dict) else type(obj).__name__}


# ----------------------------------------------------------------------------- documents
def read_pdf(path: Path, chars: int, samples: bool) -> dict:
    try:
        import pymupdf
    except ImportError:
        return {"note": "install pymupdf to profile pdf"}
    doc = pymupdf.open(path)
    pages = doc.page_count
    text = ""
    heads: list[str] = []
    scanned = 0
    for i, page in enumerate(doc):
        t = page.get_text()
        if len(t.strip()) < 20:
            scanned += 1
        if i < 6:
            text += t
        if i < 40:
            for b in page.get_text("dict")["blocks"]:
                for ln in b.get("lines", []):
                    sp = ln["spans"]
                    s = "".join(x["text"] for x in sp).strip()
                    if sp and 3 < len(s) < 80 and all(x["flags"] & 16 for x in sp if x["text"].strip()):
                        heads.append(s)
        if i > 400:
            break
    out = {"pages": pages, "pages_without_text": scanned, "language": language(text), "tables_hint": "tabular" if text.count("  ") > 200 else ""}
    if samples:
        out["headings_sample"] = [mask(h) for h in heads[:15]]
        out["excerpt"] = mask(re.sub(r"\s+", " ", text)[:chars])
    return out


def read_docx(path: Path, chars: int, samples: bool) -> dict:
    try:
        import docx
    except ImportError:
        return {"note": "install python-docx to profile docx"}
    d = docx.Document(path)
    paras = [p for p in d.paragraphs if p.text.strip()]
    heads = [p.text.strip() for p in paras if (p.style.name or "").lower().startswith(("heading", "titre", "title"))]
    text = " ".join(p.text for p in paras[:60])
    out = {"paragraphs": len(paras), "tables": len(d.tables), "language": language(text)}
    if samples:
        out["headings_sample"] = [mask(h) for h in heads[:15]]
        out["excerpt"] = mask(re.sub(r"\s+", " ", text)[:chars])
    return out


def read_text(path: Path, chars: int, samples: bool) -> dict:
    raw = path.read_bytes()[:200_000]
    text = raw.decode("utf-8", errors="replace")
    out = {"chars_read": len(text), "language": language(text)}
    if samples:
        out["excerpt"] = mask(re.sub(r"\s+", " ", text)[:chars])
    return out


def profile_file(path: Path, chars: int, samples: bool) -> dict:
    ext = path.suffix.lower()
    info: dict = {"size": path.stat().st_size}
    try:
        if ext in (".csv", ".tsv"):
            info.update(read_csv(path))
        elif ext in (".xlsx", ".xlsm"):
            info.update(read_xlsx(path))
        elif ext in (".json", ".jsonl"):
            info.update(read_json(path))
        elif ext == ".pdf":
            info.update(read_pdf(path, chars, samples))
        elif ext == ".docx":
            info.update(read_docx(path, chars, samples))
        elif ext in (".txt", ".md"):
            info.update(read_text(path, chars, samples))
        elif ext == ".zip":
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                info["members"] = len(names)
                info["member_extensions"] = dict(Counter(Path(n).suffix.lower() for n in names).most_common(15))
                info["note"] = "zip is not opened further; extract it and run again on the folder"
        else:
            info["note"] = "not profiled (type not supported)"
    except Exception as exc:  # noqa: BLE001  a bad file must not stop the run
        info["error"] = f"{exc.__class__.__name__}: {str(exc)[:120]}"
    return info


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--out", default="data_profile")
    ap.add_argument("--no-samples", action="store_true")
    ap.add_argument("--max-files", type=int, default=40)
    ap.add_argument("--sample-chars", type=int, default=300)
    a = ap.parse_args()
    root = Path(a.path)
    if not root.exists():
        sys.exit(f"Path not found: {root}")
    files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
    by_ext: Counter = Counter()
    size_ext: defaultdict = defaultdict(int)
    by_dir: Counter = Counter()
    for p in files:
        by_ext[p.suffix.lower() or "(none)"] += 1
        size_ext[p.suffix.lower() or "(none)"] += p.stat().st_size
        by_dir[str(p.parent.relative_to(root.parent if root.is_file() else root)) if not root.is_file() else "."] += 1
    groups: defaultdict = defaultdict(list)
    for p in files:
        groups[(str(p.parent), p.suffix.lower())].append(p)
    rnd = random.Random(7)
    detailed: dict[str, dict] = {}
    for (_, _), ps in groups.items():
        pick = ps if len(ps) <= a.max_files else rnd.sample(ps, a.max_files)
        for p in pick:
            rel = str(p.relative_to(root)) if root.is_dir() else p.name
            detailed[rel] = profile_file(p, a.sample_chars, not a.no_samples)
    langs = Counter(v.get("language") for v in detailed.values() if v.get("language"))
    report = {
        "root": root.name, "files": len(files), "total_size": human(sum(size_ext.values())),
        "extensions": {e: {"files": n, "size": human(size_ext[e])} for e, n in by_ext.most_common()},
        "folders_top": dict(by_dir.most_common(25)),
        "languages_in_profiled_files": dict(langs),
        "profiled_files": len(detailed),
        "note": f"At most {a.max_files} files per folder and type were opened; the rest are counted only.",
        "details": detailed,
    }
    Path(f"{a.out}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md = [f"# Data profile: {root.name}", f"{len(files)} files, {report['total_size']}. Languages seen: {dict(langs)}", "", "## Types"]
    md += [f"- {e}: {v['files']} files, {v['size']}" for e, v in report["extensions"].items()]
    md += ["", "## Folders (top)"] + [f"- {d}: {n}" for d, n in by_dir.most_common(15)]
    md += ["", "## Tables (columns)"]
    for name, d in detailed.items():
        tabs = d.get("sheets") or ({"": d} if d.get("columns") else {})
        for sheet, t in tabs.items():
            md.append(f"- **{name}** {sheet}: {t['rows']} rows; " + ", ".join(
                f"{c['name']}" + (f" {list(c['values'])[:6]}" if c.get("label_like") else "") for c in t["columns"][:30]))
    Path(f"{a.out}.md").write_text("\n".join(md), encoding="utf-8")
    kb = Path(f"{a.out}.json").stat().st_size / 1024
    print(f"Done. Wrote {a.out}.json ({kb:.0f} KB) and {a.out}.md. Send me those two files.")
    if kb > 2000:
        print("The json is large. Re-run with --no-samples or a smaller --max-files.")


if __name__ == "__main__":
    main()
