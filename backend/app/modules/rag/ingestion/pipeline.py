"""Build the passage index: discover -> extract -> chunk -> embed -> Qdrant.

    python -m app.modules.rag.ingestion.pipeline --strategy structural
    python -m app.modules.rag.ingestion.pipeline --strategy fixed --chunks-only
    python -m app.modules.rag.ingestion.pipeline --strategy structural --corpora law grants business_plan
    python -m app.modules.rag.ingestion.pipeline --strategy structural --reuse-chunks --model intfloat/multilingual-e5-base

Run from backend/. Outputs live under data/ (git-ignored):
  data/index/<strategy>/chunks.jsonl   passages and metadata, also read by BM25
  data/index/report.json               pages, OCR gaps, decoded-font pages per document
  data/qdrant/                         embedded Qdrant collections passages_<strategy>
"""

import argparse
import json
import sys
import time
from pathlib import Path

from app.config import settings
from app.modules.rag.ingestion.chunking import STRATEGIES, Chunk
from app.modules.rag.ingestion.extract import extract_pages
from app.modules.rag.ingestion.sources import discover
from app.schemas.common import ModuleStatus, TraceStep

DEFAULT_CORPORA = ("law", "grants")


def index_dir(strategy: str) -> Path:
    return settings.data_dir / "index" / strategy


def chunks_path(strategy: str) -> Path:
    return index_dir(strategy) / "chunks.jsonl"


def load_chunks(strategy: str) -> list[dict]:
    path = chunks_path(strategy)
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def build_chunks(strategy: str, corpora: tuple[str, ...]) -> tuple[list[Chunk], list[dict]]:
    chunker = STRATEGIES[strategy]
    chunks: list[Chunk] = []
    report: list[dict] = []
    for doc in discover(corpora):
        try:
            pages = extract_pages(doc.path, doc.sha256)
        except Exception as error:  # a damaged PDF should not stop the run
            report.append({"doc_id": doc.doc_id, "path": doc.rel_path, "error": str(error)})
            continue
        doc_chunks = chunker(doc, pages)
        chunks.extend(doc_chunks)
        report.append(
            {
                "doc_id": doc.doc_id,
                "path": doc.rel_path,
                "corpora": doc.corpora,
                "domain": doc.domain,
                "pages": len(pages),
                "needs_ocr_pages": [p.page for p in pages if p.needs_ocr],
                "ocr_pages": sum(1 for p in pages if p.source == "ocr"),
                "decoded_font_pages": sum(1 for p in pages if p.source == "decoded_font"),
                "chunks": len(doc_chunks),
                "chunks_with_article": sum(1 for c in doc_chunks if c.article),
            }
        )
    return chunks, report


def write_chunks(strategy: str, chunks: list[Chunk]) -> Path:
    path = chunks_path(strategy)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            row = chunk.payload()
            row["point_id"] = chunk.point_id
            row["embed_text"] = chunk.embed_text
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def embed_and_index(strategy: str, chunks: list[Chunk], model: str | None = None, batch: int = 64) -> None:
    from app.services.embeddings import get_embedder
    from app.services.vectorstore import get_store

    embedder, store = get_embedder(model), get_store()
    store.recreate(strategy, embedder.dimension, embedder.model_name)
    started = time.time()
    for start in range(0, len(chunks), batch):
        part = chunks[start : start + batch]
        vectors = embedder.embed_passages([c.embed_text for c in part])
        store.upsert(strategy, [c.point_id for c in part], vectors, [c.payload() for c in part], embedder.model_name)
        done = start + len(part)
        rate = done / max(time.time() - started, 1e-6)
        eta = (len(chunks) - done) / max(rate, 1e-6)
        print(f"  {done}/{len(chunks)} chunks  {rate:.1f}/s  eta {eta / 60:.0f} min", flush=True)


def run_ingestion() -> TraceStep:
    """Status for the API: is an index present for the configured strategy?"""
    rows = load_chunks(settings.chunk_strategy)
    if not rows:
        return TraceStep(
            module="rag.ingestion",
            status=ModuleStatus.placeholder,
            detail="No index built. Run python -m app.modules.rag.ingestion.pipeline.",
        )
    docs = len({row["doc_id"] for row in rows})
    return TraceStep(
        module="rag.ingestion",
        status=ModuleStatus.ok,
        detail=f"{len(rows)} {settings.chunk_strategy} passages from {docs} documents.",
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--strategy", choices=sorted(STRATEGIES), default=settings.chunk_strategy)
    parser.add_argument("--corpora", nargs="+", default=list(DEFAULT_CORPORA))
    parser.add_argument("--chunks-only", action="store_true", help="skip embedding")
    parser.add_argument("--model", default=settings.embedding_model, help="embedding model")
    parser.add_argument("--reuse-chunks", action="store_true", help="embed the existing chunks.jsonl")
    args = parser.parse_args(argv)

    started = time.time()
    if args.reuse_chunks:
        rows = load_chunks(args.strategy)
        fields = set(Chunk.__dataclass_fields__)
        chunks = [Chunk(**{k: v for k, v in row.items() if k in fields}) for row in rows]
        print(f"embedding {len(chunks)} existing {args.strategy} chunks with {args.model}", flush=True)
        embed_and_index(args.strategy, chunks, args.model)
        print(f"indexed in {(time.time() - started) / 60:.1f} min", flush=True)
        return
    chunks, report = build_chunks(args.strategy, tuple(args.corpora))
    path = write_chunks(args.strategy, chunks)
    report_path = settings.data_dir / "index" / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    ocr_gaps = sum(len(row.get("needs_ocr_pages", [])) for row in report)
    print(
        f"{args.strategy}: {len(chunks)} chunks from {len(report)} documents "
        f"in {time.time() - started:.0f}s -> {path}\n"
        f"pages still needing OCR: {ocr_gaps} (see {report_path})",
        flush=True,
    )
    if not args.chunks_only:
        embed_and_index(args.strategy, chunks, args.model)
        print(f"indexed in {(time.time() - started) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    sys.exit(main())
