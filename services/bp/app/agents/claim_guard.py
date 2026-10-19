"""Mechanical guard for the claims a number check cannot see.

``writer.guard`` marks every figure that is not in the founder's inputs. It cannot see a sentence such
as "our experienced team has a wealth of experience" or "recent studies show a huge market": no digit,
so it passes, yet nothing in the inputs supports it. This module closes that gap after the model has
written, so the guarantee does not depend on the model obeying its prompt.

* ``sanitize`` replaces each unsupported sentence by a visible ``[NEEDED: <question>]`` placeholder,
  rewrites a foreign currency symbol to the plan currency (and marks it), and strips empty hype adjectives.
* A claim is kept when the founder's own inputs contain evidence for it (a source, years of experience,
  a partner, a pilot ...). Evidence is looked up in the answers that concern the claim, plus the plan text.
* ``protect`` / ``restore`` hide the placeholders from ``writer.guard`` so the digits inside a question
  are not mistaken for untraceable figures.

Pure Python, no app imports: it can be tested alone.
"""

from __future__ import annotations

import json
import re
from typing import Any

NEEDED_RE = re.compile(r"\[NEEDED:[^\]]*\]")
_TOKEN_RE = re.compile(r"\x01([a-j]+)\x02")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-ÝÉ0-9\"'(\[\x01])")

MARKERS = {"en": "[to be confirmed by the founder]", "fr": "[à confirmer par le fondateur]", "ar": "[يؤكده الباعث]"}


# ---------------------------------------------------------------------------- placeholders
def _tok(i: int) -> str:
    return "\x01" + "".join(chr(ord("a") + int(d)) for d in str(i)) + "\x02"  # letters, so no digit can be read as a figure


def protect(text: str) -> tuple[str, list[str]]:
    """Swap every [NEEDED: ...] placeholder for a digit-free token. Returns the text and the saved spans."""
    spans: list[str] = []

    def _sub(m: re.Match) -> str:
        spans.append(m.group(0))
        return _tok(len(spans) - 1)

    return NEEDED_RE.sub(_sub, text or ""), spans


def restore(text: str, spans: list[str]) -> str:
    def _sub(m: re.Match) -> str:
        i = int("".join(str(ord(c) - ord("a")) for c in m.group(1)))
        return spans[i] if i < len(spans) else ""

    return _TOKEN_RE.sub(_sub, text or "")


def needed_items(text: str) -> list[str]:
    """The questions inside the [NEEDED: ...] placeholders, de-duplicated, in order of appearance."""
    out: list[str] = []
    for m in NEEDED_RE.finditer(text or ""):
        q = m.group(0)[len("[NEEDED:"):-1].strip()
        if q and q not in out:
            out.append(q)
    return out


# ---------------------------------------------------------------------------- evidence
EVIDENCE_KEYS = ("founders", "key_skills", "market_size_note", "competitors", "channels", "problem", "solution",
                 "differentiator", "risks", "traction_note", "ip_note", "awards_note", "permits_note")


def build_evidence(values: dict | None, extra_text: str = "") -> dict[str, str]:
    """Lower-cased text per answer id, plus ``plan`` (the founder's own plan text) and ``all``."""
    ev: dict[str, str] = {}
    parts: list[str] = []
    for k, v in (values or {}).items():
        s = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else str(v)
        ev[k] = s.lower()
        parts.append(s)
    ev["plan"] = (extra_text or "").lower()
    ev["all"] = (" ".join(parts) + " " + (extra_text or "")).lower()
    return ev


def evidence_from_json(facts_json: str, plan_text: str = "") -> dict[str, str]:
    """Same, from the JSON string the final writer receives ({"answers": {...}, "derived": {...}})."""
    try:
        obj = json.loads(facts_json)
    except (TypeError, ValueError):
        return build_evidence({}, f"{facts_json or ''} {plan_text or ''}")
    answers = obj.get("answers") if isinstance(obj, dict) and isinstance(obj.get("answers"), dict) else obj
    return build_evidence(answers if isinstance(answers, dict) else {}, plan_text)


def _ev(evidence: dict[str, str] | None, keys: tuple[str, ...] | None) -> str:
    evidence = evidence or {}
    if keys is None:
        return evidence.get("all", "")
    return " ".join(evidence.get(k, "") for k in keys) + " " + evidence.get("plan", "")


# ---------------------------------------------------------------------------- rules
class _Rule:
    def __init__(self, name: str, pattern: str, keys: tuple[str, ...] | None, evidence: str, needed_en: str, needed_fr: str):
        self.name = name
        self.pattern = re.compile(pattern, re.I)
        self.keys = keys
        self.evidence = re.compile(evidence, re.I)
        self.needed = {"en": needed_en, "fr": needed_fr}


RULES: list[_Rule] = [
    _Rule(
        "source_claim",
        r"\b(?:according to|based on|as per)\s+(?:(?:the|a|some|several|various|multiple|recent|latest|industry|market|independent|official)\s+)*"
        r"(?:studies|study|research|reports?|surveys?|analysts?|experts?|statistics)\b"
        r"|\b(?:recent|latest|industry|market)\s+(?:studies|research|reports?|surveys?|statistics)\b"
        r"|\b(?:studies|research|surveys?|reports?|analysts?|experts?)\s+(?:show|shows|showed|suggest|suggests|indicate|indicates|estimate|estimates|predict|predicts|confirm|confirms)\b"
        r"|\bselon\s+(?:des|les|plusieurs|de récentes)?\s*(?:études|étude|rapports?|analystes?|statistiques|experts?)\b"
        r"|\b(?:études|rapports)\s+(?:récentes?|montrent|indiquent)\b",
        None,
        r"\b(?:source|sources|ministry|ministère|ministere|insee|ins\b|world bank|banque mondiale|statista|survey|sondage|enquête|enquete|interviews?|study|étude|etude|report|rapport)\b",
        "name the source (study, ministry, survey) behind this statement",
        "indiquez la source (étude, ministère, enquête) de cette affirmation",
    ),
    _Rule(
        "experience_claim",
        r"\b(?:experienced|seasoned|veteran|highly skilled|highly qualified|talented|expert)\s+(?:professionals?|team|founders?|leaders?|management|entrepreneurs?|engineers?|developers?)\b"
        r"|\bwealth of\s+(?:relevant\s+)?(?:experience|expertise|knowledge)\b"
        r"|\b(?:proven|strong|solid|extensive|deep|significant)\s+(?:track record|experience|expertise|background)\b"
        r"|\bdecades? of\b"
        r"|\béquipe\s+(?:expérimentée|chevronnée|d'experts)\b"
        r"|\b(?:forte|solide)\s+expérience\b|\bexpérience\s+(?:avérée|significative|approfondie)\b",
        ("founders", "key_skills"),
        r"\d+\s*(?:\+\s*)?(?:years?|yrs?|ans|an\b|سنة|سنوات)|\b(?:ex-|former|formerly|previously|worked|working at|graduat\w*|degree|phd|master|msc|engineer|ingénieur|diploma|diplôme|experience|expérience|background)\b",
        "relevant experience of each team member (role, years, past work)",
        "expérience pertinente de chaque membre de l'équipe (rôle, années, réalisations)",
    ),
    _Rule(
        "traction_claim",
        r"\b(?:strong|growing|proven|significant|robust|solid)\s+(?:traction|customer base|user base|adoption|demand)\b"
        r"|\b(?:forte|solide)\s+traction\b",
        None,
        r"traction|waitlist|wait-list|pre-?orders?|signed|letters? of intent|\b\d[\d\s.,]*\s*(?:users|utilisateurs|clients|customers|students|étudiants|subscribers|abonnés)\b",
        "evidence of customer traction (number of users, pre-orders, letters of intent)",
        "preuve de traction commerciale (nombre d'utilisateurs, précommandes, lettres d'intention)",
    ),
    _Rule(
        "partner_or_certification_claim",
        r"\b(?:signed|secured|established|existing|strategic)\s+(?:partnerships?|agreements?|contracts?|letters? of intent|collaborations?)\b"
        r"|\bpartnerships? with\b"
        r"|\b(?:is|are|been|being)\s+(?:certified|patented)\b|\bpatent(?:ed|s)?\b"
        r"|\bpartenariats?\s+(?:avec|stratégiques?)\b",
        None,
        r"partner|partenaire|agreement|accord|contract|contrat|certif|patent|brevet|licen|label",
        "name the partners, certifications or patents you actually hold",
        "nommez les partenaires, certifications ou brevets que vous détenez réellement",
    ),
    _Rule(
        "pilot_claim",
        r"\bpilot(?:s)?\s+(?:results?|customers?|users?|study|programs?|programmes?)\b|\bpilot(?:ed)?\s+with\b",
        None,
        r"pilot|pilote",
        "results of the pilot (who, how long, what was measured)",
        "résultats du pilote (qui, combien de temps, quelle mesure)",
    ),
    _Rule(
        "market_claim",
        r"\b(?:huge|massive|vast|enormous|significant|large|sizeable|growing|promising|lucrative|untapped)\s+(?:and\s+\w+\s+)?(?:market|markets|opportunity|opportunities|demand|potential)\b"
        r"|\bmarket\s+(?:is|are)\s+(?:huge|large|growing|promising|significant|massive)\b"
        r"|\b(?:significant|large|substantial|growing)\s+(?:portion|share|proportion|number|percentage)\s+of\b"
        r"|\b(?:vaste|énorme|immense|prometteur|important)\s+marché\b|\bmarché\s+(?:est\s+)?(?:énorme|immense|prometteur|en forte croissance)\b",
        ("market_size_note",),
        r"\d[\d\s.,]*\s*(?:%|million|millions|m\b|k\b|md|billion|tnd|dt|farms|students|users|clients|customers|étudiants|entreprises|companies)|\b(?:tam|sam|som)\b",
        "size of the market you serve (number of potential customers in your area) and its source",
        "taille du marché servi (nombre de clients potentiels dans votre zone) et sa source",
    ),
]

# adjectives that carry no information; removed (not replaced), the sentence stays
_HYPE = re.compile(
    r"\b(?:revolutionary|groundbreaking|cutting-edge|state-of-the-art|world-class|game-changing|best-in-class|"
    r"next-generation|disruptive|révolutionnaire|innovant(?:e|s|es)?)\b[,]?\s+", re.I)

_CURRENCY_AFTER = re.compile(r"(?<![\w.])(\d[\d.,\s]*\d|\d)\s*(?:US\$|USD|EUR|€|\$|dollars?|euros?)(?![\w])", re.I)
_CURRENCY_BEFORE = re.compile(r"(?:US\$|USD|EUR|€|\$)\s?(\d[\d.,\s]*\d|\d)", re.I)
_FOREIGN_CURRENCY_FACT = re.compile(r"US\$|USD|EUR|€|\$|dollars?|euros?", re.I)


def _needed(rule: _Rule, lang: str) -> str:
    return f"[NEEDED: {rule.needed.get(lang) or rule.needed['en']}]"


def _fix_currency(text: str, currency: str, evidence: dict[str, str] | None, marker: str) -> tuple[str, int]:
    """A $ or EUR amount in a TND plan is a model slip unless the founder wrote it. Rewrite to the plan currency and mark it."""
    if _FOREIGN_CURRENCY_FACT.search((evidence or {}).get("all", "")):
        return text, 0
    n = 0

    def _sub(m: re.Match) -> str:
        nonlocal n
        n += 1
        num = re.sub(r"\s+$", "", m.group(1))
        return f"{num} {currency} {marker}".rstrip()

    text = _CURRENCY_BEFORE.sub(_sub, text)
    text = _CURRENCY_AFTER.sub(_sub, text)
    return text, n


def sanitize(text: str, evidence: dict[str, str] | None, *, currency: str = "TND", marker: str = "", lang: str = "en") -> tuple[str, list[dict]]:
    """Return (clean text, issues). Each issue: {"rule", "sentence"}; a sentence that was removed becomes a [NEEDED: ...] placeholder."""
    if not text:
        return text, []
    marker = marker or MARKERS.get(lang, MARKERS["en"])
    issues: list[dict] = []
    protected, spans = protect(text)
    out_lines: list[str] = []
    for line in protected.split("\n"):
        kept: list[str] = []
        last_placeholder = None
        for sent in _SENT_SPLIT.split(line):
            if not sent.strip():
                kept.append(sent)
                continue
            hit = None
            for rule in RULES:
                if rule.pattern.search(sent) and not rule.evidence.search(_ev(evidence, rule.keys)):
                    hit = rule
                    break
            if hit is None:
                kept.append(sent)
                last_placeholder = None
                continue
            issues.append({"rule": hit.name, "sentence": restore(sent, spans)[:200]})
            ph = _needed(hit, lang)
            if ph != last_placeholder:  # two weak sentences in a row about the same thing give one placeholder
                kept.append(ph)
                last_placeholder = ph
        out_lines.append(" ".join(s for s in kept if s))
    result = "\n".join(out_lines)
    hype_n = len(_HYPE.findall(result))
    if hype_n:
        result = _HYPE.sub("", result)
        issues.append({"rule": "hype", "sentence": f"{hype_n} empty adjective(s) removed"})
    result, cur_n = _fix_currency(result, currency, evidence, marker)
    if cur_n:
        issues.append({"rule": "currency", "sentence": f"{cur_n} amount(s) rewritten to {currency} and marked"})
    # the placeholders were hidden while the rules ran; put the original ones back (new ones are plain text already)
    result = restore(result, spans)
    return result, issues
