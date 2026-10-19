"""Legal-only retrieval, bounded correction and conservative cited synthesis."""
import json
import re

from app.agents.rag_agent import citation_from
from app.modules.rag.retrieval.hybrid import search_many
from app.prompts.library import get_prompt
from app.schemas.agents import AgentRequest, AgentResult, Claim
from app.schemas.common import ModuleStatus, TraceStep
from app.schemas.legal import GuidanceRequest, GuidanceResponse
from app.services.llm import LLMUnavailable, get_llm

TOPICS = [
    (("startup label", "startup act", "label", "المؤسسة الناشئة", "علامة مؤسسة"), ["startup"], "loi startup label conditions avantages décret 2018-840"),
    (("patent", "brevet", "براءة", "اختراع"), ["intellectual_property", "ip_guidance"], "brevet invention patent inventions demande protection"),
    (("trademark", "trade mark", "marque", "علامة تجارية", "العلامة التجارية", "العلامات التجارية"), ["intellectual_property", "ip_guidance"], "marque trademarks enregistrement protection distinctif"),
    (("copyright", "droit d'auteur", "droits d'auteur", "حق المؤلف", "حقوق المؤلف"), ["intellectual_property", "ip_guidance"], "حق المؤلف الملكية الأدبية الفنية copyright auteur reproduction"),
    (("intellectual property", "propriété intellectuelle", "ملكية فكرية"), ["intellectual_property", "ip_guidance"], "patent trademark copyright propriété intellectuelle protection startup"),
    (("nda", "contract", "contrat", "agreement", "عقد", "اتفاقية"), ["contracts", "company_law", "intellectual_property"], "contrat convention obligations consentement responsabilité associés cession"),
    (("sarl", "suarl", "company", "société", "societe", "incorporat", "شركة"), ["company_law", "startup"], "société constitution capital associés gérance statuts registre"),
]

MESSAGES = {
    "en": {
        "none": "The available legal corpus does not provide sufficient evidence for this question. I cannot establish the requested rule from these sources.",
        "evidence": "Original-language evidence is shown below. A supported generated answer is not available for this request.",
        "country": "Which jurisdiction should apply? The indexed legislation is Tunisian; I cannot apply it to another country.",
        "version": "Sources are supplied editions, not a confirmation of current consolidated law. Publication date is not necessarily the effective date.",
        "draft": "Use the legal contract intake to select an agreement and confirm the parties and terms: /#/contracts. The drafting API is /api/legal/contracts/draft.",
    },
    "fr": {
        "none": "Le corpus juridique disponible ne fournit pas de preuve suffisante pour cette question. Je ne peux pas établir la règle demandée à partir de ces sources.",
        "evidence": "Voici les passages dans leur langue originale. Aucune réponse générée suffisamment étayée n'est disponible pour cette demande.",
        "country": "Quel droit national faut-il appliquer ? Les textes indexés sont tunisiens ; je ne peux pas les appliquer à un autre pays.",
        "version": "Les sources sont des éditions fournies, sans confirmation de consolidation actuelle. La date de publication n'est pas nécessairement la date d'entrée en vigueur.",
        "draft": "Utilisez le formulaire de rédaction pour choisir un accord et confirmer les parties et modalités : /#/contracts. API : /api/legal/contracts/draft.",
    },
    "ar": {
        "none": "لا يوفر الرصيد القانوني المتاح أدلة كافية لهذا السؤال. لا يمكنني إثبات القاعدة المطلوبة اعتمادا على هذه المصادر.",
        "evidence": "فيما يلي مقتطفات بلغتها الأصلية. لا تتوفر إجابة مولدة ومدعومة بما يكفي لهذا الطلب.",
        "country": "ما القانون الوطني الواجب تطبيقه؟ النصوص المفهرسة تونسية ولا يمكن تطبيقها على بلد آخر.",
        "version": "المصادر نسخ مقدمة ولا تؤكد تحيين القانون المدمج. تاريخ النشر ليس بالضرورة تاريخ دخول النص حيز النفاذ.",
        "draft": "استعمل استمارة العقود لاختيار الاتفاق وتأكيد الأطراف والشروط: /#/contracts . واجهة البرمجة: /api/legal/contracts/draft .",
    },
}

RESEARCH_LINKS = ["https://www.wipo.int/wipolex/en/", "https://www.innorpi.tn/", "https://startup.gov.tn/"]

def _normalized(text):
    return " ".join(str(text).split()).casefold()

# A thousands separator (space, no-break space, dot or comma before exactly three digits).
_THOUSANDS = re.compile(r"(?<=\d)[   .,](?=\d{3}(?!\d))")

def numbers(text):
    """Numbers in a text, with thousands separators removed: "50.000", "50 000" and "50,000" are one number.

    Used to reject a claim or a translation that adds or changes a figure. Without
    the normalisation, a correct "50 000 dinars" against the law's "50.000 dinars"
    was rejected and the answer fell back to raw excerpts.
    """
    return set(re.findall(r"\d+(?:[.,]\d+)?", _THOUSANDS.sub("", str(text))))

def topic(question):
    folded = question.casefold()
    for terms, domains, expansion in TOPICS:
        if any(term in folded for term in terms):
            if "brevet" in expansion and any(word in folded for word in ("condition", "requirement", "شروط", "brevetable", "patentable")):
                expansion += " nouveauté activité inventive application industrielle novel inventive step industrial application الاختراعات الجديدة نشاط ابتكاري قابلة للتطبيق الصناعي"
            if trademark_signs_question(question, expansion):
                expansion += " Peuvent notamment constituer un tel signe dénominations mots noms patronymiques lettres chiffres signes figuratifs sonores signs words names letters numerals figurative sound"
            return domains, expansion
    return None, ""

def is_drafting_request(question):
    return bool(re.search(r"(?i)(draft|generate|rédig|redig|prépar|prepar|صياغ|حرر|إعداد).{0,70}(contract|agreement|nda|contrat|pacte|عقد|اتفاق)|(?:contract|contrat|عقد).{0,40}(draft|rédig|صياغ)", question))

def _evidence_only(passages, language, trace):
    text = MESSAGES[language]
    # One line per excerpt, so its [n] covers all of it: the chat's citation guardrail removes lines without one.
    answer = text["evidence"] + "\n\n" + "\n\n".join(f"[{n}] {' '.join(p.text[:650].split())}" for n, p in enumerate(passages, 1))
    return AgentResult(agent="legal", status="ok", answer=answer,
                       citations=[citation_from(n, p) for n, p in enumerate(passages, 1)], passages=passages, trace=trace)


def quote_options(passage):
    """Offer short literal excerpts so small local models select rather than paraphrase quotes."""
    text = " ".join(passage.text[:1000].split())
    options = []
    for sentence in re.split(r"(?<=[.!?;])\s+|\s+(?=[a-z]\)\s)", text):
        while len(sentence) > 350:
            excerpt = sentence[:350].rsplit(" ", 1)[0]
            options.append(excerpt)
            sentence = sentence[len(excerpt):].lstrip()
        if len(sentence) >= 12:
            options.append(sentence)
    return list(dict.fromkeys(options)) or [text[:350]]


def patentability_question(question, expansion):
    return "brevet" in expansion and any(word in question.casefold() for word in ("condition","requirement","شروط","brevetable","patentable"))


def trademark_signs_question(question, expansion):
    folded = question.casefold()
    return "trademarks" in expansion and any(word in folded for word in ("signe", "signs", "constituer", "définition", "definition", "علامات", "إشارات"))


def trademark_definition_score(passage):
    text = passage.text.casefold()
    groups = [("dénominations", "denominations", "names", "تسميات"),
              ("figurat", "figurative", "تصوير"), ("sonores", "sound", "صوت")]
    return sum(any(term in text for term in group) for group in groups)


def prioritize_intent(passages, question, expansion):
    """For patentability questions, prefer the actual criteria over filing boilerplate."""
    if trademark_signs_question(question, expansion):
        return sorted(passages, key=trademark_definition_score, reverse=True)
    if not patentability_question(question,expansion):
        return passages
    groups = [("novel", "nouve", "جديد"), ("inventive", "inventiv", "ابتكاري"), ("industrial", "industri", "الصناعي")]
    def relevance(passage):
        text=passage.text.casefold()
        return sum(any(term in text for term in group) for group in groups)
    return sorted(passages,key=relevance,reverse=True)


def language_matches(text, language):
    letters = [c for c in text if c.isalpha()]
    arabic = sum("\u0600" <= c <= "\u06ff" for c in letters) / max(len(letters),1)
    if language == "ar":
        return arabic > .4
    if arabic > .2:
        return False
    words = set(re.findall(r"\w+",text.casefold()))
    french = len(words & {"le","la","les","un","une","des","du","de","est","sont","doit","peut","brevet","marque","droits","droit","pour","dans","aux","être"})
    english = len(words & {"the","a","an","of","and","is","are","shall","must","may","which","that","under","be","to","with","can"})
    return french > english if language == "fr" else english >= french


def localize_claims(client, claims, language):
    if all(language_matches(c.text,language) for c in claims):
        return claims
    prompt = get_prompt("legal.translate_claims")
    data,_ = client.chat_json(prompt.messages(
        instruction=prompt.extras["instructions"][language],
        payload=json.dumps([{"id":i,"text":c.text} for i,c in enumerate(claims)],ensure_ascii=False),
    ),max_tokens=700,output_schema={"type":"object","properties":{"translations":{"type":"array","minItems":len(claims),"maxItems":len(claims),
        "items":{"type":"object","properties":{"id":{"type":"integer","enum":list(range(len(claims)))},"text":{"type":"string"}},
                 "required":["id","text"],"additionalProperties":False}}},"required":["translations"],"additionalProperties":False})
    translated={item["id"]:item["text"] for item in data.get("translations",[]) if isinstance(item,dict)}
    result=[]
    for index,claim in enumerate(claims):
        value=translated.get(index)
        if not isinstance(value,str) or not 0<len(value)<=1600 or not language_matches(value,language):
            raise ValueError("Requested answer language was not produced")
        if numbers(value) != numbers(claim.text):
            raise ValueError("Translation changed numeric facts")
        result.append(claim.model_copy(update={"text":value}))
    return result

def guidance(body: GuidanceRequest) -> GuidanceResponse:
    from app.config import settings
    result = _guidance(body)
    if settings.legal_web_fallback_enabled and (result.mode == "abstained" or (result.mode == "evidence_only" and get_llm().available)):
        from app.agents.legal_guidance.wipo_research import research_passages
        _, expansion = topic(body.question)
        remote = research_passages(body.question, expansion)
        if remote:
            return _guidance(body, web_passages=remote, prior_trace=result.result.trace)
    return result


def _guidance(body: GuidanceRequest, web_passages=None, prior_trace=None) -> GuidanceResponse:
    language = body.language
    text = MESSAGES[language]
    limitations = [text["version"]]
    if _normalized(body.jurisdiction) not in {"tunisia", "tunisie", "tn", "تونس"}:
        return GuidanceResponse(result=AgentResult(agent="legal", status="needs_info", answer=text["country"], missing_info=[text["country"]]),
                                mode="needs_info", jurisdiction=body.jurisdiction, research_links=RESEARCH_LINKS, limitations=limitations)
    if is_drafting_request(body.question):
        return GuidanceResponse(result=AgentResult(agent="legal", status="needs_info", answer=text["draft"], missing_info=[text["draft"]]),
                                mode="needs_info", jurisdiction=body.jurisdiction, limitations=limitations)
    domains, expansion = topic(body.question)
    primary_domains = [d for d in domains if d != "ip_guidance"] if domains else None
    candidates = 20 if patentability_question(body.question,expansion) or trademark_signs_question(body.question,expansion) else 5
    passages = web_passages if web_passages is not None else search_many([body.question, expansion], rerank_query=body.question, corpora=["law"], domains=primary_domains, k=candidates)
    trace = list(prior_trace or []) + [TraceStep(module="legal.wipo_research" if web_passages is not None else "legal.retrieve", status=ModuleStatus.ok,
        detail=(f"Bounded WIPO lookup: {passages[0].publisher_url}; accessed {passages[0].retrieved_at}; no profile or uploads transmitted." if web_passages else f"{len(passages)} legal passages; domain filter={domains}; multilingual query expansion."))]
    if not passages:
        # One bounded correction, still scoped to legal data. Never substitute grants.
        passages = search_many([expansion or body.question], rerank_query=body.question, corpora=["law"], k=5)
        if domains:
            passages = [p for p in passages if p.domain in domains]
        trace.append(TraceStep(module="legal.corrective_retrieval", status=ModuleStatus.ok, detail=f"One additional search; {len(passages)} in-scope passages."))
    if not passages:
        return GuidanceResponse(result=AgentResult(agent="legal", status="abstained", answer=text["none"], trace=trace), mode="abstained",
                                jurisdiction=body.jurisdiction, research_links=RESEARCH_LINKS, limitations=limitations)
    passages=prioritize_intent(passages,body.question,expansion)[:5]
    client = get_llm()
    fallback = _evidence_only(passages, language, trace)
    if not client.available:
        return GuidanceResponse(result=fallback, mode="evidence_only", jurisdiction=body.jurisdiction, limitations=limitations)
    try:
        options=[quote_options(p) for p in passages]
        if trademark_signs_question(body.question,expansion):
            best = max(map(trademark_definition_score, passages), default=0)
            if best >= 2:
                options = [quotes if trademark_definition_score(p)==best else [] for p,quotes in zip(passages,options)]
        if patentability_question(body.question,expansion):
            groups=[("novel","nouve","جديد"),("inventive","inventiv","ابتكاري"),("industrial","industri","الصناعي")]
            def criteria_score(quote):
                return sum(any(term in quote.casefold() for term in group) for group in groups)
            best=max((criteria_score(q) for quotes in options for q in quotes),default=0)
            if best>=2:
                options=[[q for q in quotes if criteria_score(q)==best] for quotes in options]
        literal_quotes = list(dict.fromkeys(q for quotes in options for q in quotes))
        guidance_prompt = get_prompt("legal.guidance")
        data, generated = client.chat_json(guidance_prompt.messages(
            language_name={'fr':'French','en':'English','ar':'Arabic'}[language],
            payload=json.dumps({"language": language, "jurisdiction": body.jurisdiction, "question": body.question,
                "profile": body.profile.known(), "user_documents": [{"filename": a.filename, "text": a.text[:1800]} for a in body.attachments],
                "source_passages": [{"ref":i,"source_kind":p.source_kind,"current_version_verified":p.current_version_verified,"allowed_quotes":options[i-1]} for i,p in enumerate(passages,1) if options[i-1]]}, ensure_ascii=False),
        ), max_tokens=1400, output_schema={
            "type":"object", "properties":{
                "claims":{"type":"array","maxItems":4,"items":{"type":"object","properties":{
                    "quote":{"type":"string","enum":literal_quotes},
                    "refs":{"type":"array","items":{"type":"integer","enum":list(range(1,len(passages)+1))},"minItems":1,"maxItems":2},
                    "text":{"type":"string","maxLength":600}},"required":["quote","refs","text"],"additionalProperties":False}},
                "missing_info":{"type":"array","items":{"type":"string"},"maxItems":2}},
            "required":["claims","missing_info"],"additionalProperties":False})
        if data.get("claims") == []:
            missing = [m[:300] for m in (data.get("missing_info") or []) if isinstance(m, str)][:6]
            return GuidanceResponse(result=AgentResult(agent="legal",status="abstained",answer=text["none"],missing_info=missing,trace=trace),
                                    mode="abstained",jurisdiction=body.jurisdiction,research_links=RESEARCH_LINKS,limitations=limitations)
        proposed = []
        seen_quotes=set()
        for claim in (data.get("claims") or [])[:4]:
            if not isinstance(claim, dict):
                continue
            refs = claim.get("refs")
            if not isinstance(refs, list) or not refs or any(type(r) is not int or not 1 <= r <= len(passages) for r in refs):
                continue
            quote = _normalized(claim.get("quote", ""))
            refs = [r for r in refs if quote in _normalized(passages[r - 1].text[:1000])]
            if len(quote) < 12 or not refs:
                continue
            if language == "ar" and patentability_question(body.question,expansion):
                claim_text = str(claim.get("text", ""))
                if "اختيار" in claim_text:
                    continue
            key=(quote,tuple(sorted(refs)))
            if key in seen_quotes:
                continue
            seen_quotes.add(key)
            evidence_text = " ".join(passages[r - 1].text[:1000] for r in refs)
            if numbers(claim.get("text", "")) - numbers(evidence_text):
                continue
            if isinstance(claim.get("text"), str) and 0 < len(claim["text"]) <= 1600:
                proposed.append(Claim(text=claim["text"], refs=list(dict.fromkeys(refs)),quote=claim["quote"]))
        if not proposed:
            return GuidanceResponse(result=fallback, mode="evidence_only", jurisdiction=body.jurisdiction, limitations=limitations)
        proposed = localize_claims(client,proposed,language)
        if language == "ar" and patentability_question(body.question,expansion) and any("اختيار" in c.text for c in proposed):
            raise ValueError("Arabic patent terminology changed during translation")
        check_prompt = get_prompt("legal.claim_check")
        checked, _ = client.chat_json(check_prompt.messages(
            payload=json.dumps([{"claim": i, "text": c.text, "evidence": [{"source_kind":passages[r - 1].source_kind,"article":passages[r-1].article,"act":passages[r-1].act,"text":c.quote} for r in c.refs]} for i, c in enumerate(proposed)], ensure_ascii=False),
        ), tier="fast", max_tokens=400, output_schema={"type":"object","properties":{
            "verdicts":{"type":"array","maxItems":4,"items":{"type":"object","properties":{
                "claim":{"type":"integer","enum":list(range(len(proposed)))},
                "verdict":{"type":"string","enum":["supported","unsupported"]}},"required":["claim","verdict"],"additionalProperties":False}}},
            "required":["verdicts"],"additionalProperties":False})
        accepted = {item.get("claim") for item in checked.get("verdicts", []) if isinstance(item, dict) and item.get("verdict") == "supported" and type(item.get("claim")) is int}
        claims = [c.model_copy(update={"verdict": "supported"}) for i, c in enumerate(proposed) if i in accepted]
        if not claims:
            return GuidanceResponse(result=fallback, mode="evidence_only", jurisdiction=body.jurisdiction, limitations=limitations)
        used = sorted({r for c in claims for r in c.refs})
        citations=[]
        for n in used:
            citation=citation_from(n,passages[n-1])
            supporting="\n\n".join(dict.fromkeys(c.quote for c in claims if n in c.refs and c.quote))
            if supporting:
                citation=citation.model_copy(update={"quote":supporting})
            citations.append(citation)
        answer = "\n\n".join(c.text + " [" + ", ".join(map(str, c.refs)) + "]" for c in claims)
        missing = [m[:300] for m in (data.get("missing_info") or []) if isinstance(m, str)][:6]
        trace.append(TraceStep(module="legal.grounding", status=ModuleStatus.ok, detail=f"{len(claims)} quote-checked claims accepted by evidence review via {generated.provider}/{generated.model} ({guidance_prompt.ref}, {check_prompt.ref})."))
        result = AgentResult(agent="legal", status="ok", answer=answer, claims=claims, citations=citations,
                             passages=passages, missing_info=missing, trace=trace)
        return GuidanceResponse(result=result, mode="grounded_answer", jurisdiction=body.jurisdiction, limitations=limitations)
    except (LLMUnavailable, ValueError, TypeError, KeyError):
        trace.append(TraceStep(module="legal.grounding", status=ModuleStatus.skipped, detail="Generation or evidence review unavailable; returning original source excerpts."))
        return GuidanceResponse(result=fallback, mode="evidence_only", jurisdiction=body.jurisdiction, limitations=limitations)
