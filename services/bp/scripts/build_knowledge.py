"""Build data/knowledge.sqlite (a full-text index of cited passages) from the dataset pack.

Run on your machine, where the pack is:
    python scripts/build_knowledge.py "C:\\Users\\eyaha\\Desktop\\Law_Rag\\business_plan"

It reads catalog/file_index.csv, keeps the rows marked use=rag, finds the .txt next to each file,
cuts it into passages (by "Article N" where the text has them, otherwise by paragraphs of about
1000 characters) and stores each passage with its source id, title, url and a locator.
Nothing is sent anywhere. Rerun it whenever the pack changes.
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "knowledge.sqlite"
ARTICLE = re.compile(r"(?im)^\s*(?:art(?:icle)?\.?\s*(\d+[\w-]*))\b")
PARA_NO = re.compile(r"(?m)^\s*(\d{1,3})\.\s+\S")
TARGET, MIN_LEN, MAX_LEN = 1000, 120, 2200


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def find_txt(pack: Path, rel: str) -> Path | None:
    p = (pack / rel.replace("\\", "/")).with_suffix(".txt")
    if p.exists():
        return p
    hits = list(pack.rglob(p.name))
    return hits[0] if hits else None


def split_articles(text: str) -> list[tuple[str, str]]:
    marks = list(ARTICLE.finditer(text))
    if len(marks) < 5:
        return []
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((f"Article {m.group(1)}", text[m.start():end].strip()))
    return out


def split_paragraphs(text: str) -> list[tuple[str, str]]:
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n(?=\s*\d{1,3}\.\s)", text) if p.strip()]
    out, buf, first = [], "", None
    for p in paras:
        m = PARA_NO.match(p)
        if first is None:
            first = m.group(1) if m else None
        buf = (buf + "\n" + p).strip()
        if len(buf) >= TARGET:
            out.append((f"§ {first}" if first else f"part {len(out) + 1}", buf))
            buf, first = "", None
    if buf:
        out.append((f"§ {first}" if first else f"part {len(out) + 1}", buf))
    return out


def chunks(text: str) -> list[tuple[str, str]]:
    text = re.sub(r"[ \t]+", " ", text)
    base = split_articles(text) or split_paragraphs(text)
    out = []
    for loc, body in base:
        body = body.strip()
        while len(body) > MAX_LEN:  # an article can be long: split on a sentence end
            cut = body.rfind(". ", 0, MAX_LEN)
            cut = cut if cut > MAX_LEN // 2 else MAX_LEN
            out.append((f"{loc} (cont.)" if out and out[-1][0].startswith(loc) else loc, body[:cut + 1]))
            body = body[cut + 1:].strip()
        if len(body) >= MIN_LEN:
            out.append((loc, body))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pack")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--include", default="rag", help="comma list of 'use' values to index")
    a = ap.parse_args()
    pack = Path(a.pack)
    index = pack / "catalog" / "file_index.csv"
    if not index.exists():
        sys.exit(f"Not found: {index}. Pass the root folder of the pack.")
    use = set(a.include.split(","))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    con = sqlite3.connect(out)
    con.executescript("""
        create table sources(source_id text primary key, title text, url text, language text, kind text, files text, last_modified text);
        create table passages(id integer primary key, source_id text, file text, locator text, text text);
        create virtual table passages_fts using fts5(text, content='passages', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
    """)
    n_files = n_pass = 0
    skipped: list[str] = []
    with index.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("use") not in use:
                continue
            txt = find_txt(pack, row["pack_path"])
            if txt is None:
                skipped.append(row["pack_path"])
                continue
            sid = row["source_id"]
            con.execute("insert or ignore into sources values (?,?,?,?,?,?,?)",
                        (sid, row["title"], row["source_url"], row["language"], row["kind"], row["pack_path"], row["last_modified"]))
            for loc, body in chunks(read_text(txt)):
                cur = con.execute("insert into passages(source_id,file,locator,text) values (?,?,?,?)", (sid, txt.name, f"{txt.stem}, {loc}", body))
                con.execute("insert into passages_fts(rowid, text) values (?,?)", (cur.lastrowid, body))
                n_pass += 1
            n_files += 1
    con.commit()
    con.execute("insert into passages_fts(passages_fts) values('optimize')")
    con.commit()
    con.close()
    print(f"Indexed {n_pass} passages from {n_files} files into {out} ({out.stat().st_size / 1e6:.1f} MB).")
    if skipped:
        print(f"{len(skipped)} rows had no .txt next to them and were skipped, for example: {skipped[:3]}")


if __name__ == "__main__":
    main()
