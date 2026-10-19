"""Small reproducible legal-only retrieval smoke set, not a legal-accuracy benchmark."""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

CASES = [
    ("patent_en", "What are the conditions for patenting a new invention?", "tn001"),
    ("patent_fr", "Quelles inventions sont brevetables selon la loi sur les brevets ?", "tn001"),
    ("patent_ar", "ما هي شروط حماية الاختراع ببراءة؟", "tn001"),
    ("trademark_en", "What signs can be registered as a trademark?", "tn014"),
    ("trademark_fr", "Quels signes peuvent constituer une marque de fabrique ?", "tn014"),
    ("trademark_ar", "كيف تحمى العلامة التجارية؟", "tn014"),
    ("copyright_ar", "ما هي المصنفات المحمية بحق المؤلف؟", "tn085"),
    ("copyright_fr", "Quels droits d'auteur protègent un logiciel ?", "tn085"),
    ("startup_fr", "Quelles sont les conditions d'obtention du label startup ?", "2018"),
]

def main():
    from app.config import settings
    from app.agents.legal_guidance.engine import topic, prioritize_intent, patentability_question, trademark_signs_question
    from app.modules.rag.retrieval.hybrid import search_many
    results = []
    for name, question, expected in CASES:
        domains, expansion = topic(question)
        primary = [d for d in domains if d != "ip_guidance"] if domains else None
        started = time.perf_counter()
        passages = search_many([question, expansion], rerank_query=question, corpora=["law"], domains=primary, k=20 if patentability_question(question,expansion) or trademark_signs_question(question,expansion) else 5)
        passages=prioritize_intent(passages,question,expansion)[:5]
        results.append({"id": name, "question": question, "expected_document_fragment": expected,
            "hit_at_5": any(expected in p.path for p in passages),
            "law_scope_only": all("law" in p.corpora for p in passages),
            "patentability_article_at_1": (passages[0].article == "2" if passages else False) if name.startswith("patent_") else None,
            "seconds": round(time.perf_counter() - started, 2),
            "retrieved": [{"doc_id":p.doc_id,"page":p.page_start,"article":p.article,"path":p.path} for p in passages]})
        print(f"{name}: hit@5={results[-1]['hit_at_5']}", flush=True)
    report = {"purpose":"Source retrieval smoke checks, not a legal accuracy or freshness certification",
              "mode":settings.retrieval_mode,"model":settings.embedding_model,
              "hits":sum(r["hit_at_5"] for r in results),"total":len(results),"results":results}
    target = ROOT / "data" / "legal-retrieval-evaluation.json"
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"{report['hits']}/{report['total']} source hits; report: {target}")

if __name__ == "__main__":
    main()
