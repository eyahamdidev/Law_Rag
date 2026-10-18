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
const QUESTION = {
  en: `I am starting this project in Tunisia: ${description}. Stage: ${stageText}. Sector: ${sector || "not given"}. Which legal form should I choose, and what are the main steps to create the company?`,
  fr: `Je lance ce projet en Tunisie : ${description}. Stade : ${stageText}. Secteur : ${sector || "non précisé"}. Quelle forme juridique choisir, et quelles sont les principales étapes pour créer la société ?`,
  ar: `أطلق هذا المشروع في تونس: ${description}. المرحلة: ${stageText}. القطاع: ${sector || "غير محدد"}. ما الشكل القانوني الذي يجب اختياره، وما هي أهم مراحل تأسيس الشركة؟`,
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
