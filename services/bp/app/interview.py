"""Chat-style questionnaire: the same question bank, asked one question at a time.

The service keeps no session. The client sends back the ``state`` it received, so a
restart of the service loses nothing. Nothing here calls a model: parsing is the
bank's own ``normalise`` plus a few tolerant extras (numbers inside a sentence,
choice synonyms, "skip" words). That keeps the chat fast and deterministic.

Answers collected here go to ``/v1/run`` as ``options.answers``, exactly like the
form did, so precedence (questionnaire > orchestrator > document) is unchanged.
"""

from __future__ import annotations

import re
from typing import Any

from app.agents.common import fold
from app.profile import merge_context
from app.questionnaire import BANK_BY_ID, GOVERNORATES, ParseError, normalise, parse_number

CORE = ["project_name", "sector", "stage", "problem", "solution", "target_customers", "pricing", "founders", "headcount",
        "total_investment", "funding_instrument", "funding_need_amount", "horizon_years", "revenue_by_year"]
EXTRA = ["competitors", "differentiator", "market_size_note", "cogs_by_year", "payroll_by_year", "opex_by_year",
         "own_funds", "loan_amount", "loan_rate_pct", "loan_years", "risks", "legal_form", "governorate"]
NUDGE = {"problem", "solution", "differentiator", "risks"}
LOAN_ONLY = {"loan_amount", "loan_rate_pct", "loan_years"}

ASK = {
    "project_name": {"en": "Let's start simple. What's your project or company called?",
                     "fr": "Commençons simplement. Comment s'appelle votre projet ou votre entreprise ?",
                     "ar": "لنبدأ ببساطة. ما اسم مشروعكم أو شركتكم؟"},
    "sector": {"en": "And what does {project_name} do, in a few plain words?",
               "fr": "Et que fait {project_name}, en quelques mots simples ?",
               "ar": "وماذا يفعل {project_name}؟ بكلمات بسيطة."},
    "stage": {"en": "Where are you right now: still an idea, being created, or an existing business that wants to grow?",
              "fr": "Où en êtes-vous : une idée, une création en cours, ou une entreprise existante qui veut se développer ?",
              "ar": "أين أنتم الآن: فكرة، أو مشروع قيد الإنشاء، أو مؤسسة قائمة تريد التوسع؟"},
    "problem": {"en": "What problem do your customers have that you want to fix?",
                "fr": "Quel problème rencontrent vos clients et que vous voulez résoudre ?",
                "ar": "ما المشكل الذي يواجهه حرفاؤكم وتريدون حله؟"},
    "solution": {"en": "How do you solve it? Tell me what you actually sell.",
                 "fr": "Comment le résolvez-vous ? Dites-moi ce que vous vendez concrètement.",
                 "ar": "كيف تحلونه؟ أخبروني ماذا تبيعون فعلا."},
    "target_customers": {"en": "Who would pay for it first? Describe your ideal customer.",
                         "fr": "Qui paierait en premier ? Décrivez votre client idéal.",
                         "ar": "من سيدفع أولا؟ صفوا الحريف المثالي."},
    "pricing": {"en": "What do you charge? A price per unit or per month is fine.",
                "fr": "Quel prix pratiquez-vous ? Un prix par unité ou par mois suffit.",
                "ar": "بكم تبيعون؟ يكفي سعر الوحدة أو السعر الشهري."},
    "founders": {"en": "Who is on the team, and what is each person's role?",
                 "fr": "Qui compose l'équipe, et quel est le rôle de chacun ?",
                 "ar": "من هم أعضاء الفريق وما دور كل واحد؟"},
    "headcount": {"en": "How many people will work in the company at the start?",
                  "fr": "Combien de personnes travailleront dans l'entreprise au démarrage ?",
                  "ar": "كم شخصا سيعمل في الشركة عند الانطلاق؟"},
    "total_investment": {"en": "Now the money. How much do you need to invest in total to get going, working capital included (in TND)?",
                         "fr": "Passons à l'argent. Combien faut-il investir au total pour démarrer, fonds de roulement compris (en TND) ?",
                         "ar": "لننتقل إلى المال. كم تحتاجون من الاستثمار الجملي للانطلاق بما في ذلك رأس المال العامل (بالدينار)؟"},
    "funding_instrument": {"en": "How do you plan to fund it: a loan, investors, a grant, or a mix?",
                           "fr": "Comment comptez-vous le financer : crédit, investisseurs, subvention, ou un mélange ?",
                           "ar": "كيف تنوون تمويله: قرض، مستثمرون، منحة، أو مزيج؟"},
    "funding_need_amount": {"en": "How much of that do you need from outside (in TND)?",
                            "fr": "Quelle part cherchez-vous à l'extérieur (en TND) ?",
                            "ar": "كم تحتاجون من التمويل الخارجي (بالدينار)؟"},
    "horizon_years": {"en": "How far ahead do you want to project the numbers: 3 or 5 years?",
                      "fr": "Sur quel horizon voulez-vous projeter les chiffres : 3 ou 5 ans ?",
                      "ar": "على أي أفق تريدون توقع الأرقام: 3 أم 5 سنوات؟"},
    "revenue_by_year": {"en": "What revenue do you expect each year? Give {n} numbers separated by commas, in TND.",
                        "fr": "Quel chiffre d'affaires attendez-vous chaque année ? Donnez {n} nombres séparés par des virgules, en TND.",
                        "ar": "ما رقم المعاملات المتوقع كل سنة؟ أعطوا {n} أرقام مفصولة بفواصل بالدينار."},
    "competitors": {"en": "Who else solves this problem today, even badly?", "fr": "Qui d'autre résout ce problème aujourd'hui, même mal ?",
                    "ar": "من يحل هذا المشكل اليوم، ولو بشكل سيئ؟"},
    "differentiator": {"en": "Why would a customer pick you over them?", "fr": "Pourquoi un client vous choisirait-il plutôt qu'eux ?",
                       "ar": "لماذا يختاركم الحريف بدل غيركم؟"},
    "market_size_note": {"en": "Do you have a figure for the size of your market, and where it comes from?",
                         "fr": "Avez-vous un chiffre pour la taille du marché, et sa source ?", "ar": "هل لديكم رقم لحجم السوق ومصدره؟"},
    "cogs_by_year": {"en": "What will it cost you to produce what you sell each year (materials, purchases)? {n} numbers, in TND.",
                     "fr": "Combien vous coûte la production de ce que vous vendez chaque année (achats, matières) ? {n} nombres, en TND.",
                     "ar": "كم تكلفكم كل سنة مواد وإنتاج ما تبيعون؟ {n} أرقام بالدينار."},
    "payroll_by_year": {"en": "And salaries including social charges, per year? {n} numbers, in TND.",
                        "fr": "Et les salaires charges comprises, par année ? {n} nombres, en TND.", "ar": "والأجور بالأعباء الاجتماعية سنويا؟ {n} أرقام بالدينار."},
    "opex_by_year": {"en": "Other running costs per year (rent, marketing, utilities)? {n} numbers, in TND.",
                     "fr": "Autres charges par année (loyer, marketing, énergie) ? {n} nombres, en TND.", "ar": "مصاريف أخرى سنويا (كراء، تسويق، طاقة)؟ {n} أرقام بالدينار."},
    "own_funds": {"en": "How much of your own money goes in (TND)?", "fr": "Combien apportez-vous de votre poche (TND) ?", "ar": "كم تساهمون من أموالكم الخاصة (دينار)؟"},
    "loan_amount": {"en": "How big is the loan you want (TND)?", "fr": "Quel montant de crédit visez-vous (TND) ?", "ar": "ما قيمة القرض المطلوب (دينار)؟"},
    "loan_rate_pct": {"en": "What interest rate, roughly (%)?", "fr": "Quel taux d'intérêt, environ (%) ?", "ar": "ما نسبة الفائدة تقريبا (%)؟"},
    "loan_years": {"en": "Over how many years?", "fr": "Sur combien d'années ?", "ar": "على كم سنة؟"},
    "risks": {"en": "What could go wrong, and what would you do about it?", "fr": "Qu'est-ce qui pourrait mal tourner, et que feriez-vous ?",
              "ar": "ما الذي قد يسير بشكل سيئ وماذا ستفعلون؟"},
    "legal_form": {"en": "Which legal form: SARL, SUARL, SA, SAS, sole proprietor?", "fr": "Quelle forme juridique : SARL, SUARL, SA, SAS, entreprise individuelle ?",
                   "ar": "ما الشكل القانوني: SARL أو SUARL أو SA أو SAS أو مؤسسة فردية؟"},
    "governorate": {"en": "Which governorate will you be based in?", "fr": "Dans quel gouvernorat serez-vous installés ?", "ar": "في أي ولاية ستستقرون؟"},
}

SAY = {
    "ack": {"en": ["Got it.", "Nice.", "Thanks, that helps.", "Understood.", "Great."],
            "fr": ["Compris.", "Très bien.", "Merci, c'est utile.", "Noté.", "Parfait."],
            "ar": ["فهمت.", "جيد.", "شكرا، هذا مفيد.", "تم.", "ممتاز."]},
    "skip": {"en": "No problem, we'll leave that open. It will show up as something to fill in later.",
             "fr": "Pas de souci, on laisse ça ouvert. Ce sera signalé comme à compléter.",
             "ar": "لا مشكلة، نتركه مفتوحا وسيظهر كنقطة للاستكمال."},
    "hello": {"en": "Hi! I'll ask a few questions, one at a time, like a chat. Skip anything you don't know.",
              "fr": "Bonjour ! Je vais vous poser quelques questions, une à la fois, comme dans une discussion. Passez celles que vous ne connaissez pas.",
              "ar": "مرحبا! سأطرح بعض الأسئلة واحدا تلو الآخر كأنها محادثة. تجاوزوا ما لا تعرفونه."},
    "known": {"en": "I already know a few things from earlier: {facts}. Tell me if any of it is wrong.",
              "fr": "Je sais déjà quelques éléments d'après nos échanges précédents : {facts}. Dites-moi si quelque chose est faux.",
              "ar": "أعرف بعض المعطيات من قبل: {facts}. أخبروني إن كان شيء خاطئا."},
    "offer": {"en": "That's enough for a first review. Want me to run it now, or add detail on costs, competitors and risks first?",
              "fr": "C'est suffisant pour une première revue. Je la lance maintenant, ou on ajoute d'abord des détails sur les coûts, la concurrence et les risques ?",
              "ar": "هذا يكفي لمراجعة أولى. أشغلها الآن أم نضيف تفاصيل عن الكلفة والمنافسة والمخاطر أولا؟"},
    "done": {"en": "That's everything I wanted to ask. Ready for the review whenever you are.",
             "fr": "J'ai fini mes questions. La revue est prête quand vous voulez.",
             "ar": "انتهت أسئلتي. المراجعة جاهزة متى شئتم."},
    "more": {"en": "Sure, a few more.", "fr": "Volontiers, quelques questions de plus.", "ar": "حسنا، بعض الأسئلة الإضافية."},
    "nudge": {"en": "Could you add a bit more? One or two sentences is perfect.", "fr": "Pouvez-vous en dire un peu plus ? Une ou deux phrases suffisent.",
              "ar": "هل يمكنكم الإضافة قليلا؟ جملة أو جملتان تكفي."},
    "bad": {"en": "I couldn't read that one: {why}. Try again, or say 'skip'.", "fr": "Je n'ai pas pu lire cette réponse : {why}. Réessayez, ou dites « passer ».",
            "ar": "لم أستطع قراءة الإجابة: {why}. أعيدوا المحاولة أو قولوا «تجاوز»."},
    "years": {"en": "I need {n} numbers, one per year.", "fr": "Il me faut {n} nombres, un par année.", "ar": "أحتاج {n} أرقام، رقم لكل سنة."},
    "help_default": {"en": "Just answer in your own words. If you don't know, say 'skip'.", "fr": "Répondez simplement avec vos mots. Si vous ne savez pas, dites « passer ».",
                     "ar": "أجيبوا بكلماتكم. إن لم تعرفوا قولوا «تجاوز»."},
}
BTN = {"skip": {"en": "Skip", "fr": "Passer", "ar": "تجاوز"}, "review": {"en": "Review my plan now", "fr": "Lancer la revue", "ar": "ابدأ المراجعة"},
       "more": {"en": "Add more detail", "fr": "Ajouter des détails", "ar": "إضافة تفاصيل"}}

SKIP_RE = re.compile(r"^\s*(skip|pass|next|idk|i don'?t know|dunno|no idea|not sure|passer|suivant|je ne sais pas|je sais pas|aucune idée|"
                     r"pas encore|later|plus tard|تجاوز|لا أعرف|لا ادري|لا أدري)\s*[.!]*\s*$", re.I)
FINISH_RE = re.compile(r"\b(review|analy[sz]e|run it|finish|done|that'?s all|lance|revue|terminé|termine|fini|c'?est tout|ابدأ|انتهيت)\b", re.I)
MORE_RE = re.compile(r"\b(more|detail|add|continue|ajouter|détails|encore|continuer|المزيد|تفاصيل)\b", re.I)
HELP_RE = re.compile(r"(\?\s*$|^\s*(what|why|how|comment|pourquoi|c'?est quoi|qu'?est|ماذا|لماذا|كيف)\b)", re.I)

CHOICE_SYNONYMS = {  # a trailing * means "starts with"
    "stage": {"idea": ["idea", "idée", "idee", "فكرة", "concept", "thinking", "just starting to think", "pas encore lancé"],
              "creation": ["creat*", "créat*", "creation", "création", "crée", "start*", "launch*", "lanc*", "new", "nouveau", "begin*", "démarr*", "demarr*", "setting up", "en cours", "إنشاء"],
              "extension": ["extension", "exist*", "grow*", "expand*", "running", "already", "déjà", "deja", "développ*", "developp*", "توسع", "قائمة"]},
    "funding_instrument": {"loan": ["loan", "credit", "crédit", "bank*", "banque", "قرض"], "equity": ["equity", "investor*", "investisseur*", "vc", "مستثمر*"],
                           "grant": ["grant*", "subsid*", "subvention*", "منحة"], "mixed": ["mix*", "mélange", "both", "combin*", "مزيج"], "none": ["none", "no funding", "aucun*", "self*", "own money"]},
    "legal_form": {"SUARL": ["suarl"], "SARL": ["sarl"], "SAS": ["sas"], "SA": ["sa"], "sole_proprietor": ["sole*", "individuel*", "personne physique", "فردية"]},
    "horizon_years": {"3": ["3", "three", "trois", "ثلاث*"], "5": ["5", "five", "cinq", "خمس*"]},
}
CHOICE_LABEL = {"idea": {"en": "Just an idea", "fr": "Une idée", "ar": "فكرة"}, "creation": {"en": "Being created", "fr": "En création", "ar": "قيد الإنشاء"},
                "extension": {"en": "Existing, growing", "fr": "Existante, en développement", "ar": "قائمة وتتوسع"},
                "loan": {"en": "A loan", "fr": "Un crédit", "ar": "قرض"}, "equity": {"en": "Investors", "fr": "Investisseurs", "ar": "مستثمرون"},
                "grant": {"en": "A grant", "fr": "Une subvention", "ar": "منحة"}, "mixed": {"en": "A mix", "fr": "Un mélange", "ar": "مزيج"},
                "none": {"en": "No outside funding", "fr": "Aucun financement externe", "ar": "بدون تمويل خارجي"}}


def _l(lang: str) -> str:
    return lang if lang in ("en", "fr", "ar") else "en"


def _horizon(values: dict) -> int:
    return int(values.get("horizon_years") or 3)


def _text(table: dict, lang: str, **kw: Any) -> str:
    return table[_l(lang)].format(**kw) if kw else table[_l(lang)]


def new_state() -> dict:
    return {"answers": {}, "skipped": [], "current": None, "phase": "core", "nudged": [], "turn": 0, "greeted": False}


def _order(state: dict, values: dict) -> list[str]:
    ids = CORE if state["phase"] == "core" else EXTRA
    out = []
    for q in ids:
        if q in values or q in state["skipped"]:
            continue
        if q in LOAN_ONLY and values.get("funding_instrument") not in ("loan", "mixed"):
            continue
        if q == "funding_need_amount" and values.get("funding_instrument") == "none":
            continue
        out.append(q)
    return out


def _match_choice(qid: str, text: str) -> str | None:
    f = fold(text)
    for val, words in CHOICE_SYNONYMS.get(qid, {}).items():
        for w in words:
            stem = w.endswith("*")
            w = w.rstrip("*")
            if not w.isascii():
                if w in text:
                    return val
                continue
            end = "" if stem else r"(?![a-z0-9])"
            if re.search(r"(?<![a-z0-9])" + re.escape(fold(w)) + end, f):
                return val
    return None


def _numbers(text: str) -> list[float]:
    out = []
    for tok in re.findall(r"\d[\d\s .,]*\s*[kKmM]?(?![a-zA-Z])", text):
        try:
            out.append(parse_number(tok.strip().rstrip(".,")))
        except ParseError:
            continue
    return out


def _series(text: str, n: int) -> tuple[list[float] | None, str | None]:
    """Numbers separated by commas, semicolons, new lines, 'and'/'et', or plain spaces."""
    t = re.sub(r"\b(?:tnd|dt|dinars?|then|puis|and|et|:)\b", ",", text, flags=re.I)
    t = re.sub(r"\b(?:year|ann[ée]e|an|y)\s*\d+\s*[:=-]?", ",", t, flags=re.I)
    for parts in (re.split(r"[;\n|]+|,\s*(?=\S)", t), t.split()):
        parts = [p.strip(" ,") for p in parts if p.strip(" ,")]
        try:
            vals = [parse_number(p) for p in parts]
        except ParseError:
            continue
        if len(vals) == n:
            return vals, None
    return None, "years"


def parse_reply(qid: str, text: str, values: dict) -> tuple[Any, str | None]:
    """Return (value, error). A value of None with no error means 'nothing usable'."""
    q = BANK_BY_ID[qid]
    t = text.strip()
    if q.type == "choice":
        m = _match_choice(qid, t)
        if m is None and qid == "governorate":
            for g in GOVERNORATES:
                if fold(g) in fold(t):
                    m = g
        if m is None:
            try:
                return normalise(q, t), None
            except ParseError:
                return None, "choice"
        return normalise(q, m), None
    if q.type == "year_series":
        n = _horizon(values)
        return _series(t, n)
    if q.type in ("number", "pct", "int"):
        try:
            return normalise(q, t), None
        except ParseError as exc:
            nums = _numbers(t)
            if nums:
                try:
                    return normalise(q, nums[0]), None
                except ParseError as exc2:
                    return None, str(exc2)
            return None, str(exc)
    return normalise(q, t), None


def _extras(text: str, current: str, values: dict) -> dict:
    """Facts volunteered in passing, for choice questions that are not the current one."""
    found: dict[str, Any] = {}
    for qid in ("stage", "funding_instrument", "legal_form"):
        if qid == current or qid in values:
            continue
        m = _match_choice(qid, text)
        if m and qid != "legal_form":
            # stage and instrument words are common in sentences; only keep the strong ones
            if qid == "stage" and m == "extension" and not re.search(r"extension|existing|existante|توسع", text, re.I):
                continue
            if qid == "funding_instrument" and m in ("loan", "equity", "grant") and len(text.split()) > 12:
                continue
        if m:
            found[qid] = m
    return found


def _chips(qid: str, lang: str) -> list[dict]:
    q = BANK_BY_ID.get(qid)
    if not q or q.type != "choice" or qid == "governorate":
        return []
    return [{"value": c, "label": CHOICE_LABEL.get(c, {}).get(_l(lang), c)} for c in q.choices]


def _ask(qid: str, lang: str, values: dict) -> str:
    q = BANK_BY_ID[qid]
    tpl = ASK.get(qid)
    if tpl is None:
        return {"en": q.en, "fr": q.fr, "ar": q.ar}[_l(lang)]
    return tpl[_l(lang)].format(project_name=values.get("project_name", {"en": "the project", "fr": "le projet", "ar": "المشروع"}[_l(lang)]),
                                n=_horizon(values))


def turn(*, lang: str, profile: dict | None, state: dict | None, message: str | None, action: str | None = None) -> dict:
    lang = _l(lang)
    st = {**new_state(), **(state or {})}
    st["answers"] = dict(st["answers"])
    st["skipped"] = list(st["skipped"])
    st["nudged"] = list(st["nudged"])
    say: list[str] = []
    st["turn"] += 1

    def values() -> dict:
        return merge_context(profile, st["answers"], None).values

    if not st["greeted"]:
        st["greeted"] = True
        say.append(_text(SAY["hello"], lang))
        ctx = merge_context(profile, None, None)
        known = [f"{k} = {v}" for k, v in ctx.values.items() if not isinstance(v, (list, dict))][:6]
        if known:
            say.append(_text(SAY["known"], lang, facts=", ".join(known)))
        msg, action = None, None
    msg = (message or "").strip()
    cur = st["current"]

    if action == "finish" or (st["phase"] == "offer" and msg and FINISH_RE.search(msg) and not MORE_RE.search(msg)):
        st["phase"] = "done"
        st["current"] = None
        return _out(st, say, lang, None, values())
    if st["phase"] == "offer" and action == "more" or (st["phase"] == "offer" and msg and MORE_RE.search(msg)):
        st["phase"] = "extra"
        say.append(_text(SAY["more"], lang))
        cur = None
    elif cur and (action == "skip" or SKIP_RE.match(msg)):
        st["skipped"].append(cur)
        say.append(_text(SAY["skip"], lang))
        cur = None
    elif cur and msg:
        q = BANK_BY_ID[cur]
        try:
            val, err = parse_reply(cur, msg, values())
        except ParseError as exc:
            val, err = None, str(exc)
        if err or val is None:
            if HELP_RE.search(msg):
                say.append((q.help_en if lang == "en" else q.help_fr or q.help_en) or _text(SAY["help_default"], lang))
            elif err == "years":
                say.append(_text(SAY["years"], lang, n=_horizon(values())))
            elif err == "choice":
                opts = ", ".join(CHOICE_LABEL.get(c, {}).get(lang, c) for c in q.choices)
                say.append({"en": f"I couldn't tell which one you mean. Is it: {opts}? You can tap a button below.",
                            "fr": f"Je n'ai pas compris lequel. C'est : {opts} ? Vous pouvez toucher un bouton ci-dessous.",
                            "ar": f"لم أفهم المقصود. هل هو: {opts}؟ يمكنكم الضغط على أحد الأزرار."}[lang])
            else:
                say.append(_text(SAY["bad"], lang, why=err or "?"))
            return _out(st, say, lang, cur, values())
        if cur in NUDGE and len(msg.split()) < 4 and cur not in st["nudged"]:
            st["nudged"].append(cur)
            say.append(_text(SAY["nudge"], lang))
            return _out(st, say, lang, cur, values())
        st["answers"][cur] = val
        for k, v in _extras(msg, cur, values()).items():
            st["answers"].setdefault(k, v)
        acks = SAY["ack"][lang]
        say.append(acks[st["turn"] % len(acks)])
        cur = None

    todo = _order(st, values())
    if not todo:
        if st["phase"] == "core":
            st["phase"] = "offer"
            say.append(_text(SAY["offer"], lang))
            st["current"] = None
            return _out(st, say, lang, None, values())
        st["phase"] = "done"
        say.append(_text(SAY["done"], lang))
        st["current"] = None
        return _out(st, say, lang, None, values())
    nxt = todo[0]
    st["current"] = nxt
    say.append(_ask(nxt, lang, values()))
    return _out(st, say, lang, nxt, values())


def _out(st: dict, say: list[str], lang: str, qid: str | None, vals: dict) -> dict:
    st["current"] = qid
    core_left = len([q for q in CORE if q not in vals and q not in st["skipped"]])
    chips = _chips(qid, lang) if qid else []
    actions = []
    if qid:
        actions.append({"action": "skip", "label": BTN["skip"][lang]})
    if st["phase"] in ("offer", "extra", "done") or core_left == 0:
        actions.append({"action": "finish", "label": BTN["review"][lang]})
    if st["phase"] == "offer":
        actions.append({"action": "more", "label": BTN["more"][lang]})
    return {
        "messages": say, "state": st, "answers": st["answers"], "asking": qid, "type": BANK_BY_ID[qid].type if qid else None,
        "chips": chips, "actions": actions, "phase": st["phase"],
        "ready_to_review": st["phase"] in ("offer", "extra", "done"),
        "progress": {"core_total": len(CORE), "core_left": core_left},
    }
