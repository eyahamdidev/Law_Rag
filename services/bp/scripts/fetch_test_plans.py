"""Download public plan pages into test folders: good / moderate / bad.

Honest limits, read first:
* The websites do not label their plans. YOU decide the label for each url (a column in urls.csv).
  Polished sample plans are usually 'good' or 'moderate'. Real 'bad' plans are rare online: make them
  with scripts/mutation_test.py instead, or put a plan your professor calls weak in the bad folder.
* SEC litigation releases describe real frauds. They are not plans, so they go to fraud_language/
  and are NOT counted in accuracy. They help you check that the red-flag wording matches real cases.
* The script respects robots.txt, waits between requests and identifies itself. Check each site's
  terms before you use its text, and keep the files for local testing only. Do not commit or share them.

urls.csv (header: url,label,name):
    https://upmetrics.co/template/coffee-truck-business-plan,good,coffee_truck
    https://upmetrics.co/template/hospital-business-plan,moderate,hospital

Run from services/bp:
    python scripts/fetch_test_plans.py --urls urls.csv --out test_plans
    python scripts/fetch_test_plans.py --sec 17188,20853,16577 --contact "Your Name your@email" --out test_plans
Pages become .docx (headings kept) so both the module and the mutation test can read them.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import urllib.robotparser as robotparser
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

LABELS = {"good", "moderate", "bad"}
SKIP_TAGS = {"script", "style", "nav", "footer", "header", "form", "noscript", "svg", "aside", "button"}
HEAD_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 3}
BLOCK_TAGS = {"p", "li", "td", "th", "div", "section", "article", "tr", "br"}


class Extract(HTMLParser):
    """Keep headings and paragraphs; drop navigation and scripts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[tuple[str, str]] = []  # (kind, text) kind = h1..h3 | p
        self._skip = 0
        self._tag: str | None = None
        self._buf: list[str] = []

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        if text and len(text) > 1:
            kind = self._tag if self._tag in HEAD_TAGS else "p"
            self.items.append((kind, text))
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self._skip += 1
        elif not self._skip and (tag in HEAD_TAGS or tag in BLOCK_TAGS):
            self._flush()
            self._tag = tag

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1
        elif not self._skip and (tag in HEAD_TAGS or tag in BLOCK_TAGS):
            self._flush()
            self._tag = None

    def handle_data(self, data):
        if not self._skip:
            self._buf.append(data)


def extract(html: str) -> list[tuple[str, str]]:
    p = Extract()
    p.feed(html)
    p._flush()
    seen, out = set(), []
    for kind, text in p.items:  # drop exact repeats (menus, cookie banners)
        if text in seen and kind == "p":
            continue
        seen.add(text)
        out.append((kind, text))
    return out


def save_docx(items: list[tuple[str, str]], path: Path) -> None:
    import docx

    d = docx.Document()
    for kind, text in items:
        if kind in HEAD_TAGS:
            d.add_heading(text, level=HEAD_TAGS[kind])
        else:
            d.add_paragraph(text)
    d.save(str(path))


class Fetcher:
    def __init__(self, contact: str, delay: float) -> None:
        import httpx

        self.client = httpx.Client(headers={"User-Agent": f"bp-test-data-fetcher ({contact})"}, timeout=30, follow_redirects=True)
        self.delay, self._robots = delay, {}

    def allowed(self, url: str) -> bool:
        host = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        if host not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                rp.set_url(host + "/robots.txt")
                rp.read()
            except Exception:  # noqa: BLE001  no robots file readable: be conservative only if the fetch itself failed
                rp = None
            self._robots[host] = rp
        rp = self._robots[host]
        return True if rp is None else rp.can_fetch("*", url)

    def get(self, url: str) -> str | None:
        if not self.allowed(url):
            print(f"  skipped (robots.txt disallows): {url}")
            return None
        time.sleep(self.delay)
        r = self.client.get(url)
        if r.status_code != 200:
            print(f"  failed {r.status_code}: {url}")
            return None
        return r.text


def safe(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name).strip("_")[:80] or "page"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--urls", help="csv with url,label,name")
    ap.add_argument("--sec", help="comma list of SEC litigation release numbers, e.g. 17188,20853")
    ap.add_argument("--contact", default="student project", help="name and email sent in the User-Agent (SEC asks for one)")
    ap.add_argument("--out", default="test_plans")
    ap.add_argument("--delay", type=float, default=2.0, help="seconds between requests")
    a = ap.parse_args()
    if not a.urls and not a.sec:
        sys.exit("Give --urls urls.csv and/or --sec 17188,20853")
    out = Path(a.out)
    for lab in (*LABELS, "fraud_language"):
        (out / lab).mkdir(parents=True, exist_ok=True)
    f = Fetcher(a.contact, a.delay)
    done = 0
    if a.urls:
        with open(a.urls, encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                label = (row.get("label") or "").strip().lower()
                if label not in LABELS:
                    print(f"  skipped (label must be good, moderate or bad): {row}")
                    continue
                html = f.get(row["url"].strip())
                if html is None:
                    continue
                items = extract(html)
                if sum(len(t) for _, t in items) < 1500:
                    print(f"  too little text (page may need JavaScript): {row['url']}")
                    continue
                name = safe(row.get("name") or urlparse(row["url"]).path.rsplit("/", 1)[-1])
                save_docx(items, out / label / f"{name}.docx")
                (out / label / f"{name}.source.txt").write_text(row["url"], encoding="utf-8")
                done += 1
                print(f"  saved {label}/{name}.docx ({len(items)} blocks)")
    for num in (a.sec or "").split(","):
        num = num.strip()
        if not num:
            continue
        url = f"https://www.sec.gov/enforcement-litigation/litigation-releases/lr-{num}"
        html = f.get(url)
        if html is None:
            continue
        save_docx(extract(html), out / "fraud_language" / f"sec_lr_{num}.docx")
        (out / "fraud_language" / f"sec_lr_{num}.source.txt").write_text(url, encoding="utf-8")
        done += 1
        print(f"  saved fraud_language/sec_lr_{num}.docx")
    print(f"Done: {done} files in {out}. Check them by eye before you trust them.")


if __name__ == "__main__":
    main()
