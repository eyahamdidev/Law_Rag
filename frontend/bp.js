// Business plan tab: the user first picks ONE way in (upload a plan, or chat), never both at once.
// escapeHtml, readError, SESSION_ID and the fetch wrapper come from app.js.
(() => {
  window.BP_UI_VERSION = 5;
  const choose = document.querySelector("#bp-choose");
  const views = { upload: document.querySelector("#bp-upload"), chat: document.querySelector("#bp-chat") };
  const form = document.querySelector("#bp-form");
  const result = document.querySelector("#bp-result");
  const langSel = document.querySelector("#bp-lang");
  const log = document.querySelector("#bp-log");
  const chips = document.querySelector("#bp-chips");
  const say = document.querySelector("#bp-say");
  const input = document.querySelector("#bp-input");
  const UI = {
    en: { pick: "How do you want to give me your plan? Pick one. You can switch later.", upload_t: "Upload a plan", upload_d: "I already have a document (.docx, .pdf, .xlsx, .txt).",
      chat_t: "Chat with me", chat_d: "I'll ask a few questions, one at a time.", back: "← Change how I give my plan", file_l: "Your plan", act_review: "Review my plan",
      act_draft: "Draft missing or weak sections", run: "Run", send: "Send", lang: "Language", ph: "Type your answer…" },
    fr: { pick: "Comment voulez-vous me donner votre plan ? Choisissez une option, vous pourrez changer.", upload_t: "Téléverser un plan", upload_d: "J'ai déjà un document (.docx, .pdf, .xlsx, .txt).",
      chat_t: "Discuter avec moi", chat_d: "Je pose quelques questions, une à la fois.", back: "← Changer de méthode", file_l: "Votre plan", act_review: "Analyser mon plan",
      act_draft: "Rédiger les sections manquantes ou faibles", run: "Lancer", send: "Envoyer", lang: "Langue", ph: "Écrivez votre réponse…" },
    ar: { pick: "كيف تريدون تقديم خطتكم؟ اختاروا واحدة، ويمكنكم التغيير لاحقا.", upload_t: "رفع خطة", upload_d: "لدي وثيقة جاهزة (.docx, .pdf, .xlsx, .txt).",
      chat_t: "الدردشة معي", chat_d: "أطرح بعض الأسئلة واحدا تلو الآخر.", back: "← تغيير الطريقة", file_l: "خطتكم", act_review: "مراجعة خطتي",
      act_draft: "صياغة الأقسام الناقصة أو الضعيفة", run: "تشغيل", send: "إرسال", lang: "اللغة", ph: "اكتبوا إجابتكم…" },
  };
  function applyLang() {
    const t = UI[langSel.value] || UI.en;
    document.querySelectorAll("#bp [data-i18n]").forEach((el) => { el.textContent = t[el.dataset.i18n]; });
    document.querySelectorAll("#bp [data-i18n-ph]").forEach((el) => { el.placeholder = t[el.dataset.i18nPh]; });
    document.querySelector("#bp").dir = langSel.value === "ar" ? "rtl" : "ltr";
  }
  let chatState = null;
  let chatAnswers = {};
  let started = false;

  function show(mode) {
    choose.hidden = mode !== null;
    Object.entries(views).forEach(([k, el]) => (el.hidden = k !== mode));
    result.hidden = true;
    if (mode === "chat" && !started) { started = true; turn({}); }
  }
  document.querySelectorAll(".bp-card").forEach((b) => b.addEventListener("click", () => show(b.dataset.mode)));
  document.querySelectorAll("[data-back]").forEach((b) => b.addEventListener("click", () => show(null)));
  applyLang();
  langSel.addEventListener("change", () => { applyLang(); if (started) { started = false; chatState = null; chatAnswers = {}; log.innerHTML = ""; chips.innerHTML = ""; if (!views.chat.hidden) show("chat"); } });

  function bubble(text, who) {
    const d = document.createElement("div");
    d.className = `bubble ${who}`;
    d.textContent = text;
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
  }

  async function turn(payload) {
    const res = await fetch("/api/bp/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lang: langSel.value, state: chatState, ...payload }),
    });
    if (!res.ok) { bubble(`Sorry, I could not reach the business-plan service (${await readError(res)}).`, "bot"); return; }
    const data = await res.json();
    chatState = data.state;
    chatAnswers = data.answers || {};
    data.messages.forEach((m) => bubble(m, "bot"));
    chips.innerHTML = "";
    (data.chips || []).forEach((c) => addChip(c.label, () => send(c.value)));
    (data.actions || []).forEach((a) => addChip(a.label, () => {
      if (a.action === "finish") return review();
      bubble(a.label, "me");
      turn({ action: a.action });
    }, a.action === "finish" ? "primary" : ""));
  }

  function addChip(label, fn, cls = "") {
    const b = document.createElement("button");
    b.type = "button";
    b.className = `chip ${cls}`;
    b.textContent = label;
    b.addEventListener("click", fn);
    chips.appendChild(b);
  }

  function send(text) {
    if (!text.trim()) return;
    bubble(text, "me");
    input.value = "";
    turn({ message: text });
  }
  say.addEventListener("submit", (e) => { e.preventDefault(); send(input.value); });

  async function review() {
    chips.innerHTML = "";
    bubble("…", "bot");
    result.hidden = false;
    result.textContent = "Reviewing your answers…";
    try {
      const fd = new FormData();
      fd.append("mode", "review");
      fd.append("lang", langSel.value);
      fd.append("answers", JSON.stringify(chatAnswers));
      fd.append("generate_plan", "true");
      const res = await fetch("/api/bp/run", { method: "POST", body: fd });
      if (!res.ok) throw new Error(await readError(res));
      render(await res.json());
    } catch (e) {
      result.textContent = e.message;
    }
  }

  const money = (v) => (v == null ? "" : Math.round(v).toLocaleString("fr-FR"));
  const sevLabel = { high: "Look closely", review: "Review this", info: "Note" };

  function renderDraft(text) {
    return escapeHtml(text).replace(/\[(to be confirmed by the founder|à confirmer par le fondateur|يؤكده الباعث)\]/gi, "<mark>[$1]</mark>");
  }

  function render(data) {
    const { response: r, report: rep } = data;
    let html = `<p class="answer">${escapeHtml(r.status === "abstain" ? r.answer : rep ? rep.summary_text : r.answer)}</p>`;
    if (rep) {
      html += `<div class="meta">` + rep.input.methods.map((m) => `<span class="pill ok">${escapeHtml(m.replace("_", " "))}</span>`).join("") +
        `<span class="pill">${escapeHtml(rep.template.title)}</span>` +
        (rep.template.verified_against_official_model ? "" : `<span class="pill hold">skeleton not yet checked against the official model</span>`) +
        (rep.privacy.masking ? `<span class="pill">identifiers masked before any model call</span>` : `<span class="pill hold">masking off</span>`) + `</div>`;
      const a = rep.assessment;
      if (a) {
        const lab = a.label[langSel.value] || a.label.en;
        html += `<div class="verdict ${a.verdict}"><strong>${escapeHtml(lab)}</strong><span>${a.score}/100</span></div>` +
          `<p class="note">${escapeHtml(a.rationale)} This is a prompt to verify, not an accusation.</p>`;
        if (a.flags.length) html += `<h3>Red flags and weaknesses</h3>` + a.flags.map((f) =>
          `<div class="sig ${f.group === "fraud" ? "high" : "review"}">${escapeHtml(f.why)}${f.quote ? `<br><em>“${escapeHtml(f.quote)}”</em>` : ""}</div>`).join("");
        if (a.strengths.length) html += `<h3>Strengths</h3>` + a.strengths.map((f) => `<div class="sig info">${escapeHtml(f.why)}</div>`).join("");
      }
      html += `<h3>Sections</h3>` + rep.completeness.sections.map((s) =>
        `<div class="sec-row"><span>${escapeHtml(s.title)}</span><div class="bar ${s.status}"><i style="width:${s.score}%"></i></div><span>${s.score}</span></div>`).join("");
      const bn = rep.benchmarks;
      if (bn && (bn.sector || bn.notes.length || bn.country_risk)) {
        html += `<h3>Reference data</h3>`;
        if (bn.sector) {
          const b = bn.sector.benchmark;
          html += `<p class="note">Sector matched: <strong>${escapeHtml(bn.sector.matched_industry)}</strong>. Reference after-tax operating margin ${(b.after_tax_operating_margin * 100).toFixed(0)}% ` +
            `(${escapeHtml(b.region)} firms, ${escapeHtml(b.as_of)}, Damodaran). This is US data, a yardstick and not a Tunisian norm.</p>`;
        }
        if (bn.country_risk) html += `<p class="note">Tunisia country risk premium ${(bn.country_risk.country_risk_premium * 100).toFixed(1)}%, rating ${escapeHtml(bn.country_risk.rating)} (${escapeHtml(bn.country_risk.label)}).</p>`;
        html += bn.notes.map((n) => `<p class="note">${escapeHtml(n)}</p>`).join("");
      }
      const conflicts = rep.context.conflicts;
      if (conflicts.length) {
        html += `<h3>Sources disagree</h3>` + conflicts.map((c) =>
          `<div class="sig review">${escapeHtml(c.field)}: ${Object.entries(c.values).map(([s, v]) => `${escapeHtml(s)} = ${escapeHtml(String(v))}`).join(", ")}. Used: ${escapeHtml(c.chosen_source)}.</div>`).join("");
      }
      const sigs = r.signals || [];
      html += `<h3>Points to review (${sigs.length})</h3>` + (sigs.length ? sigs.map((s) =>
        `<div class="sig ${s.severity}"><strong>${sevLabel[s.severity]}</strong> · ${escapeHtml(s.message.replace(/^Review this:\s*/i, ""))}</div>`).join("") : `<p class="note">Nothing flagged.</p>`);
      const f = rep.financials;
      if (f && f.years && f.years.length) {
        const row = (k, lab) => `<tr><td>${lab}</td>${f[k].map((v) => `<td>${money(v)}</td>`).join("")}</tr>`;
        html += `<h3>Financial check (recomputed in code)</h3><table class="fin"><tr><th></th>${f.years.map((y) => `<th>${escapeHtml(y)}</th>`).join("")}</tr>` +
          row("revenue", "Revenue") + row("ebitda", "EBITDA") + row("net_income", "Net result") + row("cash_end", "Year-end cash") + `</table>`;
        if (f.break_even_year) html += `<p class="note">Break-even reached in ${escapeHtml(f.break_even_year)}.</p>`;
        if (f.assumptions && f.assumptions.length) html += `<p class="note"><strong>Assumptions:</strong> ${f.assumptions.map(escapeHtml).join(" ")}</p>`;
      }
      const png = (r.artifacts || []).find((a) => a.kind === "png");
      if (png) html += `<img alt="Projection chart" src="/api/files/${png.file_ref}?kind=png" />`;
      if (rep.drafts.length) {
        html += `<h3>Drafts</h3>` + rep.drafts.map((d) => `<h4>${escapeHtml(d.title)}</h4><div class="draft">${renderDraft(d.text)}</div>` +
          `<p class="note">${d.flagged.length} figure(s) marked for you to confirm. Method: ${escapeHtml(d.method)}.</p>`).join("");
      }
      const docx = (r.artifacts || []).find((a) => a.kind === "docx" && a.label !== "business_plan");
      if (docx) html += `<p class="dl"><a href="/api/files/${docx.file_ref}?kind=docx&name=business-plan-review">Download the review report (.docx)</a></p>`;
      const planDoc = (r.artifacts || []).find((a) => a.label === "business_plan");
      if (planDoc) html = `<p class="dl plan"><a href="/api/files/${planDoc.file_ref}?kind=docx&name=business-plan">Download your business plan (.docx)</a> <span class="note">built from your answers; items still missing are listed on its last page</span></p>` + html;
    }
    if (r.handoff) html += `<div class="sig info">This looks like a question for the ${escapeHtml(r.handoff.to)} assistant: ${escapeHtml(r.handoff.question)}</div>`;
    html += `<ol class="trace">${(r.trace || []).map((t) => `<li><strong>${escapeHtml(t.step)}</strong> — ${t.ms} ms${t.model ? ` · ${escapeHtml(t.model)}` : ""}</li>`).join("")}</ol>`;
    result.innerHTML = html;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    result.hidden = false;
    result.textContent = "Reading your plan…";
    try {
      const fd = new FormData();
      const mode = document.querySelector("#bp-action").value;
      fd.append("mode", mode);
      fd.append("lang", langSel.value);
      if (mode === "draft_section") fd.append("section_id", "missing");
      fd.append("file", document.querySelector("#bp-file").files[0]);
      const res = await fetch("/api/bp/run", { method: "POST", body: fd });
      if (!res.ok) throw new Error(await readError(res));
      render(await res.json());
    } catch (e) {
      result.textContent = e.message;
    } finally {
      button.disabled = false;
    }
  });
})();
