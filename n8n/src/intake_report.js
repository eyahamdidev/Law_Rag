// Build one readable HTML report from the two API answers.
// Shown to the founder right after the form, and saved as a record.
const req = $('Prepare requests').first().json;
const aid = $('Funding eligibility').first().json;
const chat = $('Legal question').first().json;
const lang = req.lang;

const T = {
  en: { title: "Your startup report", legal: "Legal form and company creation", funding: "Funding programmes that may fit",
        none: "No programme in our catalogue matches these answers.", docs: "Documents usually requested (indicative)",
        confirm: "To confirm with the provider (figure not found in our official sources)", apply: "Where to apply",
        notfit: "Not a fit", sources: "Sources", down: "This part is unavailable right now. Please try again later.",
        note: "Answers come from Tunisian official texts. The provider makes the final eligibility decision; check important decisions with a professional." },
  fr: { title: "Votre rapport startup", legal: "Forme juridique et création de la société", funding: "Programmes de financement possibles",
        none: "Aucun programme de notre catalogue ne correspond à ces réponses.", docs: "Documents généralement demandés (indicatif)",
        confirm: "À confirmer auprès de l'organisme (chiffre absent de nos sources officielles)", apply: "Où postuler",
        notfit: "Non adaptés", sources: "Sources", down: "Cette partie est indisponible pour le moment. Réessayez plus tard.",
        note: "Les réponses proviennent des textes officiels tunisiens. L'organisme décide de l'éligibilité ; vérifiez les décisions importantes avec un professionnel." },
  ar: { title: "تقرير مشروعك", legal: "الشكل القانوني وتأسيس الشركة", funding: "برامج التمويل الممكنة",
        none: "لا يتوافق أي برنامج في الكتالوج مع هذه الإجابات.", docs: "الوثائق المطلوبة عادة (قائمة تقريبية)",
        confirm: "يجب التثبت لدى الجهة المانحة (رقم غير موجود في مصادرنا الرسمية)", apply: "مكان التقديم",
        notfit: "برامج غير مناسبة", sources: "المصادر", down: "هذا الجزء غير متوفر حاليا. أعد المحاولة لاحقا.",
        note: "الإجابات مستمدة من النصوص الرسمية التونسية. القرار النهائي للجهة المانحة؛ تثبت من القرارات المهمة مع مختص." },
}[lang];

const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
// The chat answer is light markdown: headings, bold, bullets, line breaks.
const md = (text) => esc(text)
  .replace(/^#{1,6}\s*(.+)$/gm, "<h4>$1</h4>")
  .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
  .replace(/^\s*[-*•]\s+(.+)$/gm, "<li>$1</li>")
  .replace(/(<li>.*<\/li>\n?)+/g, (m) => `<ul>${m}</ul>`)
  .replace(/\n{2,}/g, "<br><br>").replace(/\n/g, "<br>");

const LABELS = { min_investment_tnd: { en: "minimum project cost (TND)", fr: "coût minimum du projet (TND)", ar: "الحد الأدنى لكلفة المشروع (د.ت)" },
                 max_investment_tnd: { en: "maximum project cost (TND)", fr: "coût maximum du projet (TND)", ar: "الحد الأقصى لكلفة المشروع (د.ت)" },
                 max_employees: { en: "maximum employees", fr: "nombre maximum d'employés", ar: "الحد الأقصى لعدد العاملين" } };
const STAGES = { idea: { en: "idea", fr: "idée", ar: "فكرة" }, creation: { en: "company creation", fr: "création", ar: "تأسيس" },
                 extension: { en: "expansion", fr: "extension", ar: "توسعة" }, growth: { en: "growth", fr: "croissance", ar: "نمو" } };
const word = (v) => (STAGES[v] && STAGES[v][lang]) || String(v).replace(/_/g, " ");
const list = (s) => s.replace(/[[\]']/g, "").split(",").map((v) => word(v.trim())).join(", ");
// Rules-engine reasons -> one sentence; the four common ones are translated, others are cleaned up.
function reason(r) {
  let m;
  if ((m = r.match(/^Incompatible stage: requires (\[.*\])$/)))
    return { en: `Only for these stages: ${list(m[1])}.`, fr: `Uniquement pour ces stades : ${list(m[1])}.`, ar: `فقط لهذه المراحل: ${list(m[1])}.` }[lang];
  if ((m = r.match(/^Sector '(.+)' not in eligible sectors/)))
    return { en: `Your sector (${m[1]}) is not covered.`, fr: `Votre secteur (${m[1]}) n'est pas couvert.`, ar: `قطاعك (${m[1]}) غير مشمول.` }[lang];
  if ((m = r.match(/^Program type '(.+)' does not match requested need '(.+)'$/)))
    return { en: "It does not offer the type of support you asked for.", fr: "Il n'offre pas le type d'aide demandé.", ar: "لا يقدم نوع الدعم المطلوب." }[lang];
  if ((m = r.match(/^Governorate '(.+)' is not an eligible regional development zone$/)))
    return { en: `${m[1]} is not a regional development zone.`, fr: `${m[1]} n'est pas une zone de développement régional.`, ar: `${m[1]} ليست منطقة تنمية جهوية.` }[lang];
  return r.replace(/[[\]']/g, "");
}

// Legal part (from the orchestrator)
let legal;
if (chat.error || !chat.answer) {
  legal = `<p class="warn">${esc(T.down)}</p>`;
} else {
  const sources = (chat.citations || []).map((c) =>
    `<li>[${c.ref}] ${esc(c.act || c.title)}${c.article ? ", art. " + esc(c.article) : ""}, p. ${esc(c.page)}</li>`).join("");
  legal = `<div class="answer">${md(chat.answer)}</div>` + (sources ? `<p class="small"><strong>${T.sources}</strong></p><ol class="small">${sources}</ol>` : "");
}

// Funding part (from the rules engine; the API's LLM explanation is not used)
let funding;
if (aid.error || !Array.isArray(aid.programs)) {
  funding = `<p class="warn">${esc(T.down)}</p>`;
} else if (!aid.programs.length) {
  funding = `<p>${esc(T.none)}</p>`;
} else {
  funding = aid.programs.map((p) => {
    const confirm = Object.entries(p.unverified || {}).filter(([k]) => k !== "reason")
      .map(([k, v]) => `${esc((LABELS[k] && LABELS[k][lang]) || k)}: ${Number(v).toLocaleString("en")}`).join("; ");
    const docs = (p.required_documents || []).map((d) => `<li>${esc(d)}</li>`).join("");
    const link = p.official_form_link || "";
    const apply = /^https?:\/\//.test(link) ? `<p><strong>${T.apply}:</strong> <a href="${esc(link)}">${esc(link.replace(/^https?:\/\//, ""))}</a></p>` : "";
    return `<div class="card"><h3>${esc(p.name)}</h3><p>${esc(p.provider)}. ${esc(p.summary)}</p>` +
      (confirm ? `<p class="warn">${T.confirm}: ${confirm}</p>` : "") +
      (docs ? `<p class="small"><strong>${T.docs}</strong></p><ul class="small">${docs}</ul>` : "") + apply + `</div>`;
  }).join("");
}
const notfit = (aid.excluded_programs || []).map((e) =>
  `<li><strong>${esc(e.name)}</strong>: ${esc((e.reasons || []).map(reason).join(" "))}</li>`).join("");
if (notfit) funding += `<details><summary>${T.notfit} (${aid.excluded_programs.length})</summary><ul class="small">${notfit}</ul></details>`;

const dir = lang === "ar" ? "rtl" : "ltr";
const html = `<div dir="${dir}" class="report">
<style>
.report{font-family:"Segoe UI",Candara,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;color:#1e1a16;line-height:1.55}
.report h1{font-family:Georgia,serif;margin:0 0 .3rem}.report h2{font-family:Georgia,serif;border-bottom:1px solid #ddd4c4;padding-bottom:.3rem;margin-top:2rem}
.report .card{border:1px solid #ddd4c4;border-radius:.8rem;padding:1rem;margin:.8rem 0;background:#fffdf8}.report .card h3{margin:0 0 .3rem}
.report .small{font-size:.9rem;color:#5e564c}.report .warn{color:#8a5a12}.report .answer{background:#fffdf8;border:1px solid #ddd4c4;border-radius:.8rem;padding:1rem}
.report .meta{color:#5e564c}.report .note{font-size:.85rem;color:#5e564c;margin-top:2rem}
</style>
<h1>${T.title}</h1>
<p class="meta">${esc(req.description)} · ${esc(req.stage_text || req.stage_label)}${req.aid.sector ? " · " + esc(req.aid.sector) : ""}${req.aid.governorate ? " · " + esc(req.aid.governorate) : ""}</p>
<h2>${T.legal}</h2>${legal}
<h2>${T.funding}</h2>${funding}
<p class="note">${esc(T.note)}</p>
</div>`;

return [{ json: {
  html,
  record: {
    request_id: req.request_id, submitted_at: req.submitted_at, lang, description: req.description,
    profile: req.aid, question: req.question,
    legal: { answer: chat.answer || null, agents: (chat.plan?.steps || []).map((s) => s.agent), citations: (chat.citations || []).length,
             verification: chat.verification || null, error: chat.error?.message || null },
    funding: { eligible: (aid.programs || []).map((p) => p.id), excluded: (aid.excluded_programs || []).map((e) => e.program_id),
               error: aid.error?.message || null },
  },
} }];
