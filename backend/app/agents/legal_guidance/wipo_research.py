"""Bounded public-page research; no founder data or arbitrary URLs are transmitted."""
from datetime import datetime, timezone
from html.parser import HTMLParser
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.modules.rag.retrieval.bm25 import tokenize
from app.schemas.rag import Passage

SOURCES = {
    "brevet": ("3819", "Law No. 2000-84 on Patents"),
    "marque": ("3832", "Law No. 2001-36 on Trademarks"),
    "copyright": ("6161", "Law No. 2009-33 amending copyright legislation"),
}
MAX_BYTES = 3 * 1024 * 1024
_cache = {}
_lock = threading.Lock()

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.legal_depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "div":
            if self.legal_depth:
                self.legal_depth += 1
            elif "htmlView" in dict(attrs).get("class", "").split():
                self.legal_depth = 1
        if tag in {"script", "style", "nav", "header", "footer"}:
            self.hidden += 1
        if self.legal_depth and not self.hidden and tag in {"p", "div", "li", "br", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "nav", "header", "footer"} and self.hidden:
            self.hidden -= 1
        if self.legal_depth and not self.hidden and tag in {"p", "div", "li"}:
            self.parts.append("\n")
        if tag == "div" and self.legal_depth:
            self.legal_depth -= 1

    def handle_data(self, data):
        if self.legal_depth and not self.hidden:
            self.parts.append(data)

def fetch_page(url):
    """Only fixed WIPO records, with no redirects, cookies or credentials."""
    allowed = {f"https://www.wipo.int/wipolex/en/legislation/details/{v[0]}" for v in SOURCES.values()}
    if url not in allowed:
        raise ValueError("Unapproved WIPO research URL")
    with _lock:
        cached = _cache.get(url)
        if cached and time.monotonic() - cached[0] < 600:
            return cached[1], cached[2]
    request = Request(url, headers={"User-Agent":"StartupLegalResearch/1.0", "Accept":"text/html"})
    with build_opener(NoRedirect()).open(request, timeout=8) as response:
        if response.status != 200 or "text/html" not in response.headers.get("Content-Type", ""):
            raise ValueError("WIPO did not return readable HTML")
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("WIPO page exceeds research size limit")
        parser = PageText()
        parser.feed(raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace"))
    text = re.sub(r"[ \t]+", " ", "".join(parser.parts))
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    accessed = datetime.now(timezone.utc).isoformat()
    with _lock:
        _cache[url] = (time.monotonic(), text, accessed)
    return text, accessed

def research_passages(query, expansion):
    selected = next((value for key, value in SOURCES.items() if key in expansion), None)
    if selected is None:
        return []
    record, title = selected
    url = f"https://www.wipo.int/wipolex/en/legislation/details/{record}"
    try:
        text, accessed = fetch_page(url)
    except (HTTPError, URLError, OSError, ValueError, TimeoutError):
        return []
    words = set(tokenize(query + " " + expansion))
    candidates = []
    for start in range(0, len(text), 700):
        excerpt = text[start:start+1000].strip()
        if len(excerpt) < 100 or not re.search(r"(?i)article|\bArt\.|\bloi\b|invention|trademark|copyright|الفصل", excerpt):
            continue
        score = len(words & set(tokenize(excerpt)))
        if score:
            candidates.append((score, start, excerpt))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [Passage(chunk_id=f"wipo:{record}:{start}", doc_id=f"wipo:{record}", title=f"WIPO Lex — {title}",
                    path=url, publisher_url=url, corpora=["law"], domain="intellectual_property", language="und",
                    page_start=1, page_end=1, text=excerpt, score=float(score), score_kind="web_keyword_overlap",
                    source_kind="official_web_page", extraction_method="web", retrieved_at=accessed,
                    current_version_verified=False) for score, start, excerpt in candidates[:3]]
