// Turn the form answers into the inputs of the two API calls.
const f = $input.first().json;
const LANG = { "English": "en", "Français": "fr", "العربية": "ar" };
const STAGE = { "Idea": "idea", "Company creation": "creation", "Expansion": "extension", "Growth": "growth" };
const NEED = { "Any support": "unspecified", "Loan": "loan", "Grant": "grant", "Loan guarantee": "guarantee",
               "Tax advantage": "tax_incentive", "Guidance": "guidance" };

const lang = LANG[f["Answer language"]] || "en";
const description = String(f["Describe your project"] || "").trim();
const stageLabel = f["Stage"] || "";
const sector = String(f["Sector"] || "").trim();
const amount = Number(String(f["Funding need (TND)"] ?? "").replace(/[^\d.]/g, "")) || null;
const governorate = String(f["Governorate"] || "").trim();

// The legal question goes to the orchestrator in the founder's language.
const STAGE_TEXT = {
  en: { "Idea": "idea", "Company creation": "creating the company", "Expansion": "expanding", "Growth": "growth" },
  fr: { "Idea": "idée", "Company creation": "création de la société", "Expansion": "extension", "Growth": "croissance" },
  ar: { "Idea": "فكرة", "Company creation": "تأسيس الشركة", "Expansion": "توسعة", "Growth": "نمو" },
};
const stageText = (STAGE_TEXT[lang] || STAGE_TEXT.en)[stageLabel] || stageLabel;
// Asked as what the law states (partners, minimum capital per form), not "which form should I
// choose": the legal agent only answers what it can quote, and the texts set rules, not advice.
const QUESTION = {
  en: `Under Tunisian law, how many partners and what minimum capital are required to create a SARL, a SUARL and a société anonyme (SA)?`,
  fr: `Selon le droit tunisien, combien d'associés et quel capital minimum faut-il pour créer une SARL, une SUARL et une société anonyme (SA) ?`,
  ar: `حسب القانون التونسي، كم عدد الشركاء وما هو الحد الأدنى لرأس المال المطلوب لتأسيس شركة ذات مسؤولية محدودة، وشركة الشخص الواحد ذات المسؤولية المحدودة، وشركة خفية الاسم؟`,
};

return [{ json: {
  request_id: `intake-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
  submitted_at: f.submittedAt,
  lang,
  description,
  stage_label: stageLabel,
  stage_text: stageText,
  aid: {
    stage: STAGE[stageLabel] || "unspecified",
    sector,
    need: NEED[f["What do you need?"]] || "unspecified",
    funding_need_tnd: amount,
    governorate: governorate || null,
    free_text: description,
  },
  question: QUESTION[lang],
} }];
