"""Exercise the configured provider with public corpus questions, saving local results."""
import json
import argparse
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url",help="Use the running API, avoiding embedded Qdrant locks")
    args=parser.parse_args()
    from app.agents.legal_guidance.engine import guidance
    from app.schemas.legal import GuidanceRequest, GuidanceResponse
    results = []
    cases = [("en", "What conditions must an invention meet to be patentable?"),
             ("fr", "Quels signes peuvent constituer une marque de fabrique ?"),
             ("ar", "ما هي شروط حماية الاختراع ببراءة؟")]
    for language, question in cases:
        started = time.perf_counter()
        request=GuidanceRequest(question=question, language=language)
        if args.api_url:
            import urllib.request
            http=urllib.request.Request(args.api_url.rstrip('/')+'/api/legal/guidance',data=request.model_dump_json().encode('utf-8'),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(http,timeout=300) as response:
                result=GuidanceResponse.model_validate(json.load(response))
        else:
            result=guidance(request)
        results.append({"question":question,"language":language,"seconds":round(time.perf_counter()-started,2),**result.model_dump(mode="json")})
        print(f"{language}: {result.mode}; {len(result.result.claims)} checked claims; {len(result.result.citations)} citations", flush=True)
        (ROOT / "data" / "legal-generation-smoke.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
