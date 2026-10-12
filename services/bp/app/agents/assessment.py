"""Credibility assessment: red flags, strengths and a verdict band for a plan.

This answers "should anyone trust this plan?", which section completeness cannot.

Two layers share one taxonomy (the rule ids below):

* deterministic rules over the plan text (EN and FR patterns plus a few numeric
  cross-checks such as payouts above income or a headcount that disagrees with payroll)
* an optional model pass that may only label taxonomy ids and must quote the plan.
  A quote that is not in the plan is discarded.

Verdict bands: ``good``, ``moderate``, ``bad``, ``high_risk``.
``high_risk`` means several fraud-pattern signals fired. It is a reason to verify
the claims independently. It is never a statement that anyone committed fraud.

The rule weights were tuned on the 15 development cases in
``eval/datasets/pitch_cases``. They have not been tested on unseen plans, so the
numbers from that set are development results, not a measure of accuracy.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app import prompts
from app.agents.common import Trace, fold
from app.config import model_for
from app.llm import LLMClient, LLMUnavailable
from app.masking import Masker


@dataclass(frozen=True)
class Rule:
    id: str
    group: str  # fraud | weak | strength
    weight: float
    patterns: tuple[str, ...]
    why: str


def R(id, group, weight, why, *patterns):
    return Rule(id, group, weight, tuple(patterns), why)


RULES: list[Rule] = [
    # ------------------------------------------------------------------ fraud patterns
    R("guaranteed_returns", "fraud", 3, "Promises guaranteed or risk-free returns. No real investment can.",
      r"guarantee[sd]?\s+(?:\w+\s+){0,3}(?:returns?|profits?|yield|income|minimum)", r"(?:returns?|profits?)\s+(?:\w+\s+){0,3}(?:are\s+)?guarantee[sd]?",
      r"zero risk|risk[- ]free|no risk of loss|without (?:any )?risk", r"rendements? garantis?|sans risque|risque (?:nul|zero)"),
    R("fixed_investor_return", "fraud", 2, "Promises investors a fixed periodic return.",
      r"\b\d+(?:\.\d+)?\s*(?:%|percent)\s+(?:annual\s+|monthly\s+|weekly\s+|net\s+)?returns?\b.{0,60}(?:investors?|paid|monthly|weekly)",
      r"\b\d+(?:\.\d+)?\s*(?:%|percent)\s+per\s+(?:week|month)\b", r"investors?\s+(?:fund|deposit).{0,80}receive\s+\d+\s*(?:%|percent)",
      r"(?:pay|paying)\s+weekly returns? of \d+"),
    R("new_money_pays_old", "fraud", 3, "New investor money is used to pay existing investors, the pattern of a Ponzi scheme.",
      r"new\s+(?:investor\s+)?(?:deposits?|investors?|funds|money)\b.{0,60}\b(?:used|use|fund|pay|paying)\b.{0,50}(?:payouts?|returns?|withdrawals?|existing|earlier|previous|monthly)",
      r"(?:pay|paying)\s+(?:existing|earlier|previous|old)\s+investors"),
    R("payouts_exceed_income", "fraud", 3, "Payouts to investors are larger than the income the business collected.", ),
    R("commingled_funds", "fraud", 2, "Investor money is held in the same account as company money.",
      r"(?:investor|client|customer)\s+funds?\b.{0,80}(?:alongside|together with|same account|operating account|commingl)", r"commingl"),
    R("no_audit_or_bank_proof", "fraud", 2, "No audit, no bank statements or no independent review of the numbers.",
      r"audit has not been done|not (?:been )?audited|\bunaudited\b|no audit|cannot be (?:disclosed or )?audited|aging report is not provided|not been reviewed by an accountant|bank statements? cannot be shared"),
    R("pay_to_see_documents", "fraud", 3, "Asks for money before showing proof, or shows proof only after a deposit.",
      r"(?:after|upon|following)\s+(?:a\s+)?(?:wire transfer|deposit|payment)", r"(?:statements?|documents?|letter|copy)\b.{0,50}\bavailable upon deposit",
      r"(?:deposit|payment|fee)\b.{0,50}\b(?:required|requested)\s+to\s+(?:see|view|access|receive)"),
    R("asks_not_to_verify", "fraud", 3, "Asks investors not to verify the claims.",
      r"(?:ask(?:ing)?|requests?)\s+(?:investors?|you)\s+not\s+to\s+(?:conduct\s+)?(?:independent\s+)?(?:verif|check|investigat)", r"(?:do not|don't|please do not)\s+(?:conduct\s+)?(?:independent\s+)?(?:verif|check|contact)"),
    R("unverifiable_claims", "fraud", 2, "Key customers, credentials or results are hidden or cannot be checked.",
      r"(?:cannot|can't|could not|unable to)\s+(?:be\s+)?(?:independently\s+)?(?:verified|verify|shared|disclosed|named)", r"\bunverif", r"names? (?:are )?confidential|under nda",
      r"customer references are not available", r"details and company names are not provided", r"names and credentials cannot", r"known only as"),
    R("false_urgency", "fraud", 2, "Pressure to commit quickly.",
      r"(?:sign|invest|commit|act|buy|join)\s+(?:today|now|immediately)", r"(?:offer|round|term sheet|allocation)\b.{0,40}\b(?:closes|expires|ends)",
      r"expires? in \d+\s*(?:hours|days)", r"limited (?:spots|slots|allocation|places)", r"before the territory is sold", r"closes in \d+ hours", r"within \d+ hours"),
    R("referral_pyramid", "fraud", 3, "Pays for recruiting others, the structure of a pyramid scheme.",
      r"referral\s+(?:bonus|commission|payout|reward)", r"commission for every (?:new )?(?:investor|member|recruit)", r"\b\d+\s+levels?\b", r"downline",
      r"recruit(?:ing)?\s+(?:new\s+)?(?:members|investors|franchisees)"),
    R("unregistered_offering", "fraud", 2, "Says it is not registered or regulated while taking investor money.",
      r"not registered with any", r"unregistered", r"outside existing regulation", r"exempt from (?:registration|regulation)"),
    R("unverifiable_identity", "fraud", 3, "Founders' identity or degrees cannot be confirmed, or the team is anonymous.",
      r"no record of (?:the )?(?:person|degree)", r"publicly identified as", r"different person'?s? identity", r"known only as", r"names and credentials cannot be shared"),
    R("staged_demo", "fraud", 2, "The demo is recorded or pre-programmed, not live.",
      r"demo\w*\s+(?:is|was)\s+(?:a\s+)?recorded", r"recorded (?:video|demo)", r"pre-?programmed", r"scripted demo"),
    R("related_party_revenue", "fraud", 3, "Revenue comes from related parties or is funded by the company's own side.",
      r"owned by or affiliated with (?:our )?(?:board|founders?|directors?)", r"related (?:holding )?compan", r"round[- ]trip", r"credit line that funds their",
      r"purchased exclusively from (?:our )?affiliate", r"exclusively from our affiliated"),
    R("revenue_not_cash", "fraud", 2, "Counts revenue before cash is collected (invoices or pre-orders).",
      r"revenue is recogni[sz]ed when invoices are issued", r"regardless of collection", r"pre-?sold.{0,80}recogni[sz]e", r"recogni[sz]e[d]?\s+as\s+revenue\s+(?:next|in the)"),
    R("headcount_mismatch", "fraud", 2, "The stated headcount does not match payroll records."),
    R("advance_fee", "fraud", 3, "Refunds or support depend on paying more first.",
      r"refunded after (?:purchasing|buying|paying)", r"lead-activation package", r"after payment is received"),
    R("income_claims_no_disclosure", "fraud", 2, "Income claims without a disclosure document, based on the best case.",
      r"disclosure document is under preparation", r"income claims are based on (?:our )?top", r"working only \d+ hours", r"no experience (?:needed|required)"),
    R("impossible_accuracy", "fraud", 2, "Accuracy claim that no known technology reaches.",
      r"\b(?:99(?:\.\d)?|100)\s*(?:%|percent)\s+accura"),
    R("clearance_unproven", "fraud", 2, "Claims a regulatory clearance but cannot show the number or document.",
      r"(?:fda|ce|regulatory)\s+(?:clearance|approval).{0,100}(?:pending|publication|can be provided|after)"),
    R("fees_vs_operations", "fraud", 2, "Collected franchise fees from many people while very few units operate."),
    R("inconsistent_proof", "fraud", 2, "Supporting evidence contradicts itself (different currency, account name).",
      r"screenshot.{0,120}(?:different|inconsisten)"),
    R("no_risk_claim", "fraud", 1, "Claims there is no risk.",
      r"(?m)^\s*none\b", r"no risks? (?:is|are) anticipated", r"\bno risks?\b", r"does not (?:face|have) any risk", r"none,? because"),
    # ------------------------------------------------------------------ weaknesses
    R("buzzword_stacking", "weak", 1.5, "Stacks fashionable technologies without a concrete use case."),
    R("unfinished_model", "weak", 1, "Core parts are left for later.",
      r"to be finalized|to be determined|\btbd\b|prepared later|will be prepared later|to be decided|may also add .{0,30} later|revenue model to be"),
    R("top_down_market", "weak", 1.5, "Sizes the market top-down (a small percent of a huge number) instead of from real customers.",
      r"(?:just\s+)?(?:\d+|one|two|three)\s*(?:percent|%)\s+of\s+(?:the\s+)?(?:\w+\s+){0,3}(?:market|users|households|internet|population|owners)\b", r"we will capture (?:our|a) share", r"we can capture \d"),
    R("no_traction", "weak", 1, "No customers or revenue yet.",
      r"no (?:revenue|customers|users|sales|traction) (?:yet)?", r"\bpre-?(?:launch|revenue)\b", r"not yet launched", r"have not (?:yet )?(?:launched|sold)", r"no revenue yet"),
    R("unvalidated_core_claim", "weak", 1.5, "Key assumptions are not tested.",
      r"have not (?:yet )?(?:researched|validated|calculated|tested|modell?ed)", r"not yet validated", r"we think demand will be", r"assumed but not confirmed", r"did not model",
      r"not yet calculated", r"we have not (?:yet )?"),
    R("omitted_costs", "weak", 2, "Leaves out major cost categories.",
      r"zero (?:maintenance|crew|insurance|docking)", r"assume zero", r"no (?:maintenance|insurance) costs"),
    R("implausible_utilisation", "weak", 2, "Assumes an unrealistic number of operating days."),
    R("team_gap", "weak", 1.5, "No relevant experience on the team for what the plan needs.",
      r"no (?:prior |relevant )?(?:business|operating|veterinary|data science|technical|industry)\s+(?:experience|expertise)", r"marketing backgrounds", r"will hire (?:developers|engineers)",
      r"development will be outsourced", r"college student", r"loves boating", r"great idea", r"no .{0,30}expertise on the team"),
    R("numbers_missing", "weak", 1.5, "Asks for money without numbers behind it.",
      r"detailed numbers will be prepared", r"we expect to be profitable in year \d(?!.{0,80}\d{2,})"),
    R("spend_skewed_to_marketing", "weak", 2, "Most of the money goes to marketing, travel or offices and little to building."),
    R("optimistic_marketing", "weak", 1, "Sales volume looks too high for the marketing budget."),
    R("above_comparables", "weak", 1.5, "Projection is above comparable businesses with no slower scenario."),
    R("generic_risks", "weak", 1, "Risk section is generic or has no mitigation."),
    # ------------------------------------------------------------------ strengths
    R("real_traction", "strength", 1, "Verifiable traction.",
      r"\b(?:arr|mrr)\b", r"\b\d+\s+(?:paying|recurring)\s+(?:customers|clinics|clients)", r"operated profitably", r"profitabl[ey] for \d+ years", r"pilot (?:buildings|results|data)", r"\d+ pilot", r"launched \d+ months ago", r"\bpilot\b.{0,40}completed", r"beta testers"),
    R("primary_research", "strength", 1, "Customer research was done.",
      r"interviewed \d+", r"survey of \d+", r"customer survey", r"census data", r"park service data"),
    R("unit_economics", "strength", 1, "Unit economics are stated.",
      r"\bcac\b.{0,20}\d", r"payback", r"gross margin is \d+", r"churn is", r"\birr\b", r"unit cost \d+", r"net margin \d+", r"leaving roughly \d+"),
    R("stress_tested", "strength", 1, "Includes a sensitivity or break-even analysis.",
      r"sensitivity", r"breakeven (?:in|at)", r"break-even (?:occupancy|at)", r"downside"),
    R("named_competitors", "strength", 1, "Names real competitors and how it differs.",
      r"competitors (?:include|are) [a-z]", r"competing bakeries", r"two competing"),
    R("relevant_team", "strength", 1, "Team has relevant, checkable experience.",
      r"\b\d+ years(?: of experience)?\b", r"\blicensed\b", r"former .{0,40}(?:manager|engineer|banker)", r"\(pe\)", r"certified", r"practicing dentist"),
    R("evidence_available", "strength", 1, "Offers documents to check.",
      r"\battached\b", r"available in appendix", r"reference available", r"audit report available", r"tax returns", r"\bappendix\b", r"committed by", r"documented in", r"already signed"),
    R("risk_mitigation", "strength", 1, "Risks come with mitigations.",
      r"mitigat", r"contingency", r"\bhedge\b", r"fixed-rate"),
]
BY_ID = {r.id: r for r in RULES}


# French wording for the same taxonomy, plus a few language-neutral structure rules.
# Patterns run on accent-folded lower-case text, so write them without accents.
FR_PATTERNS: dict[str, tuple[str, ...]] = {
    "guaranteed_returns": (r"rendements? (?:est |sont )?garanti", r"garanti[es]? de \d+", r"sans aucun risque", r"capital (?:est )?garanti", r"gains? (?:garanti|assure)"),
    "fixed_investor_return": (r"\d+(?:[.,]\d+)?\s*(?:%|pour cent)\s+par\s+(?:mois|semaine|jour)", r"rendements? (?:de )?\d+\s*(?:%|pour cent)\s+(?:par|chaque)\s+(?:mois|semaine)"),
    "new_money_pays_old": (r"nouveaux? (?:depots?|investisseurs?|membres?|fonds)\b.{0,80}(?:verses?|payer|servent|financent|utilises)", r"benefices? provien\w+ .{0,60}nouveaux (?:depots?|membres|investisseurs)",
                           r"(?:payer|rembourser) les (?:anciens|premiers) (?:investisseurs|membres)"),
    "commingled_funds": (r"compte de l'entreprise\b.{0,60}(?:que nous gerons|avec l'argent)", r"meme compte", r"fonds? des (?:membres|clients|investisseurs) .{0,60}(?:compte (?:de l'entreprise|d'exploitation)|melange)"),
    "no_audit_or_bank_proof": (r"aucun audit", r"pas (?:d'|eu d')audit", r"non audite", r"aucun releve bancaire", r"releves? bancaires? ne .{0,20}(?:communiques|fournis)", r"pas de comptes? certifies"),
    "pay_to_see_documents": (r"uniquement apres (?:paiement|versement)", r"apres (?:le )?(?:paiement|versement) des frais", r"accessibles? (?:uniquement )?apres"),
    "asks_not_to_verify": (r"(?:pries|invites|demandons) de ne pas verifier", r"ne pas (?:verifier|contacter|enqueter)", r"merci de ne pas verifier"),
    "unverifiable_claims": (r"ne (?:peut|peuvent) pas etre (?:verifie|communique|divulgue)", r"confidentiels? pour des raisons", r"ne souhaite pas communiquer", r"restent? confidentiel", r"methodes? (?:sont )?confidentielle"),
    "false_urgency": (r"(?:signez|investissez|rejoignez|agissez)\s+(?:cette semaine|aujourd'hui|maintenant|immediatement)", r"(?:places?|offres?) limitee", r"seules? \d+ places?", r"apres,? le prix augmente",
                      r"avant (?:que le prix|la fin de)", r"offre (?:expire|se termine)"),
    "referral_pyramid": (r"parrain\w*.{0,60}prime", r"prime de \d+\s*%.{0,30}(?:depot|parrain)", r"commission pour chaque (?:nouveau )?(?:membre|investisseur|filleul)", r"filleuls?"),
    "unregistered_offering": (r"non enregistre", r"non reglemente", r"pas (?:agree|autorise) par"),
    "unverifiable_identity": (r"identite (?:reste |est )?confidentielle", r"ne souhaite pas communiquer (?:ses|leurs) noms", r"anonyme", r"identite ne peut pas"),
    "related_party_revenue": (r"societe affiliee", r"affiliee? (?:a|au) (?:notre )?(?:fondateur|dirigeant|gerant)", r"achat\b.{0,60}obligatoire.{0,60}(?:affili|fondateur)", r"parties? liees?"),
    "revenue_not_cash": (r"chiffre d'affaires\b.{0,80}provient (?:essentiellement|surtout|principalement) des droits d'entree", r"chiffre d'affaires comptabilise a l'emission"),
    "advance_fee": (r"non remboursables?", r"remboursement\b.{0,80}impossible", r"frais d'adhesion", r"droit d'entree de \d"),
    "income_claims_no_disclosure": (r"gagnez \d[\d\s]*\s*(?:tnd|dt|dinars)\s+par mois", r"aucune experience (?:n'est )?(?:necessaire|requise)", r"meilleurs? (?:mois|franchises|franchises)", r"tous (?:nos|les) franchises? realisent",
                                    r"aucun document d'information"),
    "impossible_accuracy": (r"\b(?:99(?:[.,]\d)?|100)\s*(?:%|pour cent)\s+(?:de )?(?:precision|fiabilite)",),
    "no_risk_claim": (r"il n'y a aucun risque", r"aucun risque", r"ne perd jamais", r"strategie sans risque"),
    "buzzword_stacking": (),
    "unfinished_model": (r"seront precises plus tard", r"a definir", r"sera precise", r"sera defini plus tard", r"seront communiques plus tard"),
    "top_down_market": (r"si nous captons seulement \d+\s*%", r"\b\d+\s*%\s+de ce marche", r"seulement \d+\s*%\s+du marche", r"\d+\s*%\s+du marche (?:tunisien|mondial|national)"),
    "no_traction": (r"pas encore de (?:client|commercant|vente|utilisateur)", r"aucun (?:client|commercant|utilisateur) signe", r"pas de chiffre d'affaires", r"aucune vente"),
    "unvalidated_core_claim": (r"nous pensons que (?:toutes|tous|les)", r"toutes les (?:femmes|personnes|entreprises) voudront", r"tout le monde (?:a besoin|voudra)", r"pas encore (?:valide|teste)"),
    "team_gap": (r"sera sous-traite", r"travaillera seule? ", r"sans experience", r"aucune experience du secteur", r"pas de (?:developpeur|cto|directeur technique)"),
    "numbers_missing": (r"seront precises plus tard", r"chiffres? (?:seront|sera) (?:precis|defini)"),
    "real_traction": (r"\bpilotes?\b", r"commandes? fermes?", r"liste d'attente", r"lettre d'intention", r"deja (?:signe|en service|realise)", r"clients? (?:pilotes? )?paient? deja", r"\d+ cabinets? clients?",
                      r"abonnement\b.{0,30}paient", r"chiffre d'affaires de [\d\s]+ tnd en 20\d\d", r"resultat net de [\d\s]+ tnd en 20\d\d", r"signe (?:avec|un accord|deux)"),
    "primary_research": (r"(?:nous avons )?(?:interroge|sonde|contacte|recense) (?:environ )?\d+", r"enquete (?:menee|realisee|aupres)", r"sondage", r"etude (?:de terrain|aupres)"),
    "unit_economics": (r"cout d'acquisition", r"rapport valeur", r"retour sur investissement", r"seuil de rentabilite (?:est|a ete) atteint", r"duree de vie moyenne", r"prix moyen (?:d'|de |du )"),
    "stress_tested": (r"scenario (?:prudent|pessimiste|de base|ou)", r"inferieur de \d+\s*%", r"sensibilite", r"baisse de \d+\s*%.{0,60}resultat", r"test[eé]s? (?:un|aussi)"),
    "named_competitors": (r"concurrents? (?:directs? )?(?:sont|:)", r"concurrents?\b.{0,60}\(dont ", r"(?:dont|comme|notamment) (?:menuiserie|huilerie|bois|fitness|gold|park)"),
    "relevant_team": (r"\d+ ans (?:d'experience|chez|comme|en )", r"\b(?:dix|huit|sept|six|neuf|quinze|quatre|cinq) ans\b", r"diplome[es]? (?:technique|en|d')", r"ingenieure? ", r"ancien(?:ne)? (?:responsable|chef|directeur|commercial)", r"certifie"),
    "evidence_available": (r"par ecrit", r"lettre (?:d'intention|de commande)", r"contrat(?:s)? (?:signe|cadre|d'approvisionnement)", r"accord (?:est )?deja signe", r"en annexe"),
    "risk_mitigation": (r"\bparade\b", r"attenu", r"couvert[es]? par", r"plan de secours", r"clause de revision", r"contrat de maintenance", r"acompte"),
}
EXTRA_RULES = [
    R("no_competitors_claim", "weak", 1.5, "Says there is no competitor or that everyone needs the product.",
      r"(?:n'avons|n'a) pas de concurrent", r"pas de concurrence", r"tout le monde a besoin", r"no competitors?", r"everyone needs"),
    R("no_customer_defined", "weak", 1.0, "Never says who the customer is or what problem they have.",),
]


def _install_french() -> None:
    by = {r.id: r for r in RULES}
    for rid, pats in FR_PATTERNS.items():
        r = by.get(rid)
        if r is not None and pats:
            RULES[RULES.index(r)] = Rule(r.id, r.group, r.weight, r.patterns + pats, r.why)
    RULES.extend(EXTRA_RULES)
    BY_ID.update({r.id: r for r in RULES})


_install_french()
BUZZ = ("blockchain", "revolutionnaire", "disruptive", "synergie", "leader mondial", "intelligence artificielle", "big data", "internet des objets", "tous les secteurs", "nouvelle generation", "metaverse", "quantum", "web3", "nft", "revolutioni", "disrupt", "every industry", "all industries", "internet of things", "big data")
BUZZ_AI = re.compile(r"\bai\b|artificial intelligence|\bia\b")

LABEL_TEXT = {
    "good": {"en": "Looks credible and reasonably complete", "fr": "Plan crédible et plutôt complet", "ar": "خطة جديرة بالثقة ومكتملة نسبيا"},
    "moderate": {"en": "Plausible but with gaps to close", "fr": "Plausible mais avec des lacunes à combler", "ar": "معقولة لكن بها ثغرات"},
    "bad": {"en": "Weak plan: major gaps or unrealistic assumptions", "fr": "Plan faible : lacunes majeures ou hypothèses irréalistes", "ar": "خطة ضعيفة: ثغرات كبيرة أو فرضيات غير واقعية"},
    "high_risk": {"en": "High risk: several fraud patterns. Verify everything independently before any commitment", "fr": "Risque élevé : plusieurs schémas de fraude. Tout vérifier de façon indépendante avant tout engagement", "ar": "خطر مرتفع: عدة مؤشرات احتيال. تحققوا من كل شيء بشكل مستقل قبل أي التزام"},
}


@dataclass
class Flag:
    rule: str
    group: str
    weight: float
    why: str
    quote: str | None = None
    source: str = "rule"

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Assessment:
    verdict: str
    score: int
    fraud_weight: float
    weak_weight: float
    strength_count: int
    flags: list[Flag] = field(default_factory=list)
    strengths: list[Flag] = field(default_factory=list)
    method: str = "rules"
    rationale: str = ""

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["flags"] = [f.to_dict() for f in self.flags]
        d["strengths"] = [f.to_dict() for f in self.strengths]
        return d


def _quote(text: str, m: re.Match, width: int = 110) -> str:
    s = max(0, m.start() - 25)
    e = min(len(text), m.end() + width)
    return re.sub(r"\s+", " ", text[s:e]).strip()


def _num(raw: str) -> float:
    raw = raw.lower().replace(",", "").strip()
    mult = 1.0
    if raw.endswith("m"):
        mult, raw = 1e6, raw[:-1]
    elif raw.endswith("k"):
        mult, raw = 1e3, raw[:-1]
    return float(raw) * mult


def _numeric_rules(text: str, sections: dict[str, str]) -> list[Flag]:
    out: list[Flag] = []
    low = text.lower()
    # payouts above the income that was collected
    for sent in re.split(r"(?<=[.!?])\s+", low):
        m1 = re.search(r"payouts?\b[^.]{0,60}?(\d+(?:\.\d+)?\s*[mk]?)\s*(?:usd|tnd|dt|eur|dollars)?", sent)
        m2 = re.search(r"(?:collected|income|earned|revenue|fees)\b[^.]{0,40}?(\d+(?:\.\d+)?\s*[mk]?)\s*(?:usd|tnd|dt|eur|dollars)?", sent)
        if m1 and m2:
            try:
                a, b = _num(m1.group(1)), _num(m2.group(1))
            except ValueError:
                continue
            if b > 0 and a > 1.2 * b:
                out.append(Flag("payouts_exceed_income", "fraud", BY_ID["payouts_exceed_income"].weight, BY_ID["payouts_exceed_income"].why, sent.strip()[:200]))
                break
    m = re.search(r"headcount\s+(?:is\s+)?reported as (\d+).{0,80}?(\d+)\s+employees on payroll", low, re.S)
    if m and int(m.group(1)) > 2 * int(m.group(2)):
        out.append(Flag("headcount_mismatch", "fraud", BY_ID["headcount_mismatch"].weight, BY_ID["headcount_mismatch"].why, _quote(text, m, 20)))
    m = re.search(r"from (\d+) franchisees?.{0,60}?only (\d+) operating", low, re.S) or re.search(r"only (\d+) operating.{0,80}?(\d+) franchisees", low, re.S)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        total, operating = (a, b) if "from" in m.group(0)[:6] else (b, a)
        if total and operating / total < 0.3:
            out.append(Flag("fees_vs_operations", "fraud", BY_ID["fees_vs_operations"].weight, BY_ID["fees_vs_operations"].why, _quote(text, m, 20)))
    folded_low = fold(text)
    m = re.search(r"(\d+)\s+franchises?\s+ont\s+ete\s+vendues?.{0,40}?(\d+)\s+(?:sont\s+)?en\s+activite", folded_low, re.S)
    if m and int(m.group(1)) and int(m.group(2)) / int(m.group(1)) < 0.3:
        out.append(Flag("fees_vs_operations", "fraud", BY_ID["fees_vs_operations"].weight, BY_ID["fees_vs_operations"].why, _quote(folded_low, m, 20)))
    m = re.search(r"(\d{3})\s+days?\s+(?:per|a)\s+year", low)
    if m and int(m.group(1)) >= 200:
        out.append(Flag("implausible_utilisation", "weak", BY_ID["implausible_utilisation"].weight, BY_ID["implausible_utilisation"].why, _quote(text, m, 40)))
    # use of funds
    pcts = {k: sum(int(x) for x in re.findall(rf"(\d+)\s*(?:percent|%)\s+(?:{k})", low)) for k in ("marketing", "conferences?", "travel", "office")}
    dev = sum(int(x) for x in re.findall(r"(\d+)\s*(?:percent|%)\s+(?:development|product|engineering|r&d|research)", low))
    non_build = sum(pcts.values())
    if non_build >= 60 and dev <= 20:
        m = re.search(r"use of funds[^.]*\.", low)
        out.append(Flag("spend_skewed_to_marketing", "weak", BY_ID["spend_skewed_to_marketing"].weight, BY_ID["spend_skewed_to_marketing"].why,
                        (m.group(0) if m else f"marketing, travel and offices {non_build} percent, development {dev} percent")[:200]))
    m = re.search(r"(\d[\d,]*)\s+units\b.{0,80}?marketing spend of (\d[\d,]*)", low, re.S)
    if m:
        units, spend = float(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))
        if units and spend / units < 25:
            out.append(Flag("optimistic_marketing", "weak", BY_ID["optimistic_marketing"].weight, BY_ID["optimistic_marketing"].why, _quote(text, m, 20)))
    m = re.search(r"project\w*\s+(\d+)\s*percent\b.{0,200}?comparable.{0,80}?(\d+)\s*-\s*(\d+)\s*percent", low, re.S)
    if m and int(m.group(1)) > int(m.group(3)):
        out.append(Flag("above_comparables", "weak", BY_ID["above_comparables"].weight, BY_ID["above_comparables"].why, _quote(text, m, 20)))
    risks = sections.get("risks", "")
    if risks and len(risks) < 170 and not re.search(r"mitigat|contingen|hedge|insur|plan to|fixed-rate|couvert|atténu", risks.lower()):
        out.append(Flag("generic_risks", "weak", BY_ID["generic_risks"].weight, BY_ID["generic_risks"].why, risks[:160]))
    return out


def run_rules(text: str, sections: dict[str, str]) -> tuple[list[Flag], list[Flag]]:
    folded = fold(text)
    flags: list[Flag] = []
    strengths: list[Flag] = []
    for r in RULES:
        if not r.patterns:
            continue
        for pat in r.patterns:
            m = re.search(pat, folded, re.I | re.S)
            if m:
                # quote from the original text at the same offsets when fold kept the length (it does for Latin text)
                q = _quote(text if len(text) == len(folded) else folded, m)
                (strengths if r.group == "strength" else flags).append(Flag(r.id, r.group, r.weight, r.why, q))
                break
    hits = [b for b in BUZZ if b in folded] + (["ai"] if BUZZ_AI.search(folded) else [])
    if len(hits) >= 3:
        flags.append(Flag("buzzword_stacking", "weak", BY_ID["buzzword_stacking"].weight, BY_ID["buzzword_stacking"].why, ", ".join(hits)))
    flags += _numeric_rules(text, sections)
    seen, uniq = set(), []
    for f in flags:
        if f.rule not in seen:
            seen.add(f.rule)
            uniq.append(f)
    return uniq, strengths


FIN_INTEGRITY = {"sum_mismatch", "sources_neq_uses", "impossible_margin", "growth_implausible", "negative_cash", "dscr_low", "loan_schedule_mismatch",
                 "margin_above_sector", "loan_rate_low", "payroll_inconsistent", "no_break_even"}


def structure_flags(structure: dict | None) -> tuple[list[Flag], list[Flag]]:
    """Weaknesses and strengths that come from the plan's shape and its financial checks, not its wording."""
    weak: list[Flag] = []
    strong: list[Flag] = []
    if not structure:
        return weak, strong
    high, review = structure.get("fin_high", 0), structure.get("fin_review", 0)
    if high:
        weak.append(Flag("financial_integrity", "weak", min(4.5, 1.5 * high), f"{high} financial check(s) failed in a way that changes the picture (see the signals).", None))
    if review:
        weak.append(Flag("financial_questions", "weak", min(2.25, 0.75 * review), f"{review} financial point(s) to review.", None))
    miss = structure.get("missing_ratio", 0.0)
    if miss >= 0.5:
        weak.append(Flag("sections_missing", "weak", 2.0, f"{miss:.0%} of the expected sections are missing.", None))
    elif miss >= 0.34:
        weak.append(Flag("sections_missing", "weak", 1.0, f"{miss:.0%} of the expected sections are missing.", None))
    if structure.get("has_financials") and not high and not review:
        strong.append(Flag("financials_consistent", "strength", 1, "Projection and funding tables are present and pass the checks.", None))
    elif not structure.get("has_financials") and structure.get("expects_financials"):
        weak.append(Flag("no_financials", "weak", 1.5, "No financial tables or figures that can be checked.", None))
    if structure.get("complete_ratio", 0.0) >= 0.5:
        strong.append(Flag("well_covered", "strength", 1, "Most expected sections are covered with substance.", None))
    return weak, strong


def verdict_from(flags: list[Flag], strengths: list[Flag]) -> tuple[str, int]:
    fraud = sum(f.weight for f in flags if f.group == "fraud")
    weak = sum(f.weight for f in flags if f.group == "weak")
    s = len(strengths)
    score = int(max(0, min(100, 50 + 7 * min(s, 7) - 6 * weak - 4 * fraud)))
    if fraud >= 6:
        return "high_risk", score
    if score >= 66 and weak <= 2.5:
        return "good", score
    if score >= 38:
        return "moderate", score
    return "bad", score


def assess(text: str, sections: dict[str, str], *, lang: str, llm: LLMClient, masker: Masker, trace: Trace, use_llm: bool = True,
           structure: dict | None = None) -> Assessment:
    with trace.step("assessment.rules"):
        flags, strengths = run_rules(text, sections)
    method = "rules"
    if use_llm and llm.available:
        extra = _model_flags(text, flags, strengths, llm, masker, trace)
        if extra is not None:
            flags += extra[0]
            strengths += extra[1]
            method = "rules+model"
    sw, ss = structure_flags(structure)
    flags += sw
    strengths += ss
    verdict, score = verdict_from(flags, strengths)
    fraud = sum(f.weight for f in flags if f.group == "fraud")
    weak = sum(f.weight for f in flags if f.group == "weak")
    rationale = {
        "en": f"{len([f for f in flags if f.group == 'fraud'])} fraud-pattern signal(s), {len([f for f in flags if f.group == 'weak'])} weakness(es), {len(strengths)} strength(s).",
        "fr": f"{len([f for f in flags if f.group == 'fraud'])} signal(aux) de fraude, {len([f for f in flags if f.group == 'weak'])} faiblesse(s), {len(strengths)} point(s) fort(s).",
        "ar": f"{len([f for f in flags if f.group == 'fraud'])} مؤشرات احتيال، {len([f for f in flags if f.group == 'weak'])} نقاط ضعف، {len(strengths)} نقاط قوة.",
    }.get(lang, "")
    flags.sort(key=lambda f: (-f.weight, f.rule))
    return Assessment(verdict, score, fraud, weak, len(strengths), flags, strengths, method, rationale)


def _model_flags(text, flags, strengths, llm, masker, trace):
    p = prompts.load("assessor")
    taxonomy = "\n".join(f"- {r.id} ({r.group}): {r.why}" for r in RULES if r.group != "strength")
    have = ", ".join(f.rule for f in flags) or "none"
    user = prompts.render(p["text"], taxonomy=taxonomy, already=have, plan=masker.mask(text)[:6000])
    model = model_for("llm_main")
    with trace.step("assessment.llm", model=model, prompt_id=prompts.ref(p)):
        try:
            out = llm.chat_json(model=model, system="You are a careful due-diligence analyst. Reply with JSON only.", user=user, schema=p.get("output_schema"), max_tokens=1500)
        except LLMUnavailable as exc:
            trace.note(f"assessment.llm skipped: {exc}")
            return None
    known = {f.rule for f in flags}
    folded = re.sub(r"\s+", " ", fold(text))
    new: list[Flag] = []
    for item in out.get("flags", []):
        rid, quote = item.get("rule"), masker.unmask(str(item.get("quote", "")))
        r = BY_ID.get(rid)
        q = re.sub(r"\s+", " ", fold(quote)).strip(" .")
        if r is None or r.group == "strength" or rid in known or len(q) < 8 or q not in folded:
            continue  # unknown id, already found, or a quote that is not in the plan
        known.add(rid)
        new.append(Flag(rid, r.group, r.weight, r.why, quote[:200], "model"))
    return new, []
