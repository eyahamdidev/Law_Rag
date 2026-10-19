"""Keyword search over the chunk files with BM25 (rank-bm25).

The tokenizer folds what differs between how founders type and how the
gazette prints: French accents ("societe" finds "société"), Arabic letter
variants (أ إ آ -> ا, ة -> ه, ى -> ي), tatweel and diacritics. Article
numbers stay as tokens, so "article 16" matches the heading exactly; that is
where BM25 beats dense search on legal text.
"""

import re
import unicodedata

import numpy as np
from rank_bm25 import BM25Okapi

from app.modules.rag.ingestion.pipeline import load_chunks

_STOP = set(
    """
    le la les l un une des du de d et ou en au aux a à ce ces cet cette qui que quoi dont où
    est sont être pour par sur dans avec sans ne pas plus se sa son ses leur leurs il elle ils
    on nous vous je tu y quel quelle quels quelles comment est-ce
    the a an of to in for on and or is are be what which how do does can my i
    في من على إلى الى عن مع أو او و ما هل كيف التي الذي هذا هذه ذلك
    """.split()
)
_ARABIC_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_TOKEN = re.compile(r"\w+", re.UNICODE)


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = _ARABIC_DIACRITICS.sub("", text)
    text = re.sub("[أإآ]", "ا", text).replace("ة", "ه").replace("ى", "ي")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def tokenize(text: str) -> list[str]:
    tokens = []
    for token in _TOKEN.findall(_fold(text)):
        if token in _STOP or (len(token) < 2 and not token.isdigit()):
            continue
        # Light plural folding for French and English.
        if len(token) > 4 and token.endswith("s") and not token.isdigit():
            token = token[:-1]
        tokens.append(token)
    return tokens


class BM25Index:
    def __init__(self, strategy: str) -> None:
        self.strategy = strategy
        self.rows = load_chunks(strategy)
        corpus = [tokenize(row["embed_text"]) for row in self.rows]
        self.bm25 = BM25Okapi(corpus) if corpus else None

    def search(
        self,
        query: str,
        *,
        corpora: list[str] | None = None,
        domains: list[str] | None = None,
        limit: int = 20,
    ) -> list[tuple[dict, float]]:
        if self.bm25 is None:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = self.bm25.get_scores(tokens)
        if corpora or domains:
            keep = np.array(
                [
                    (not corpora or bool(set(corpora) & set(row["corpora"])))
                    and (not domains or row["domain"] in domains)
                    for row in self.rows
                ]
            )
            scores = np.where(keep, scores, -1.0)
        top = np.argsort(-scores)[:limit]
        return [(self.rows[i], float(scores[i])) for i in top if scores[i] > 0]


_indexes: dict[str, BM25Index] = {}


def get_bm25(strategy: str) -> BM25Index:
    if strategy not in _indexes:
        _indexes[strategy] = BM25Index(strategy)
    return _indexes[strategy]
