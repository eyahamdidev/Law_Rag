// Business plan tab: the user first picks ONE way in (upload a plan, or chat), never both at once.
// escapeHtml, readError, SESSION_ID and the fetch wrapper come from app.js.
(() => {
  window.BP_UI_VERSION = 8;
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
    en: { pick: "Choose one path", upload_t: "Upload a plan", upload_d: "Docx, PDF, xlsx, or txt",
      chat_t: "Chat with me", chat_d: "Answer questions, get a Word plan", back: "← Back", file_l: "Your plan", act_review: "Review my plan",
      act_draft: "Draft missing or weak sections", act_full: "Review + institutional rewrite (slow)", run: "Run", send: "Send", lang: "Language", ph: "Type your answer…" },
    fr: { pick: "Choisissez une option", upload_t: "Téléverser un plan", upload_d: "Docx, PDF, xlsx ou txt",
      chat_t: "Discuter avec moi", chat_d: "Questions puis plan Word", back: "← Retour", file_l: "Votre plan", act_review: "Analyser mon plan",
      act_draft: "Rédiger les sections manquantes ou faibles", act_full: "Analyser + réécriture institutionnelle (long)", run: "Lancer", send: "Envoyer", lang: "Langue", ph: "Écrivez votre réponse…" },
    ar: { pick: "كيف تريدون تقديم خطتكم؟ اختاروا واحدة، ويمكنكم التغيير لاحقا.", upload_t: "رفع خطة", upload_d: "لدي وثيقة جاهزة (.docx, .pdf, .xlsx, .txt).",
      chat_t: "الدردشة معي", chat_d: "أطرح بعض الأسئلة واحدا تلو الآخر.", back: "← تغيير الطريقة", file_l: "خطتكم", act_review: "مراجعة خطتي",
      act_draft: "صياغة الأقسام الناقصة أو الضعيفة", act_full: "مراجعة + إعادة صياغة (بطيء)", run: "تشغيل", send: "إرسال", lang: "اللغة", ph: "اكتبوا إجابتكم…" },
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
  let lastBuild = null;
  let chatAutoBuild = false;

  function show(mode) {
    choose.hidden = mode !== null;
    choose.classList.toggle("bp-view-visible", mode === null);
    Object.entries(views).forEach(([k, el]) => {
      const on = k === mode;
      el.hidden = !on;
      el.classList.toggle("bp-view-visible", on);
    });
    result.hidden = true;
    if (mode === "chat" && !started) { started = true; turn({}); }
  }
  document.querySelectorAll(".bp-card").forEach((b) => b.addEventListener("click", () => show(b.dataset.mode)));
  document.querySelectorAll("[data-back]").forEach((b) => b.addEventListener("click", () => show(null)));
  applyLang();
  window.UI?.reveal(document.querySelector("#bp-choose"));
  langSel.addEventListener("change", () => { applyLang(); if (started) { started = false; chatState = null; chatAnswers = {}; log.innerHTML = ""; chips.innerHTML = ""; if (!views.chat.hidden) show("chat"); } });

  function bubble(text, who) {
    const d = document.createElement("div");
    d.className = `bubble ${who}`;
    d.textContent = text;
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
  }

  function formatBpError(msg) {
    if (/429/.test(msg)) {
      return "Groq rate limit (too many tokens per minute). Wait 1–2 minutes and run again, or use a smaller LLM_MODEL_MAIN in .env.";
    }
    return msg;
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
      if (a.action === "finish") { chatAutoBuild = true; return runReview(); }
      bubble(a.label, "me");
      turn({ action: a.action });
    }, a.action === "finish" ? "primary" : ""));
    if (data.phase === "done" && data.ready_to_review && !chatAutoBuild) {
      chatAutoBuild = true;
      runReview();
    }
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

  function buildChatFd() {
    const fd = new FormData();
    fd.append("mode", "review");
    fd.append("lang", langSel.value);
    fd.append("answers", JSON.stringify(chatAnswers));
    fd.append("generate_plan", "true");
    fd.append("chat_build", "true");
    return fd;
  }

  async function runReview() {
    chips.innerHTML = "";
    const building = {
      en: "Building your business plan from your answers (this can take 2–3 minutes)…",
      fr: "Construction de votre business plan à partir de vos réponses (comptez 2–3 minutes)…",
      ar: "جاري بناء خطة العمل من إجاباتكم (قد يستغرق 2–3 دقائق)…",
    };
    bubble(building[langSel.value] || building.en, "bot");
    result.hidden = false;
    result.textContent = building[langSel.value] || building.en;
    const runBtn = document.querySelector("#bp-form button[type=submit], #bp-say button[type=submit], #bp-chips .chip.primary");
    window.UI?.busy(runBtn, true, "Building…");
    try {
      lastBuild = buildChatFd;
      const res = await fetch("/api/bp/run", { method: "POST", body: buildChatFd() });
      if (!res.ok) throw new Error(await readError(res));
      render(await res.json());
    } catch (e) {
      result.textContent = e.message;
    } finally {
      window.UI?.busy(runBtn, false);
    }
  }

  async function regenerate() {
    if (!lastBuild) return;
    result.hidden = false;
    result.textContent = "Regenerating the plan with a new variation…";
    try {
      const fd = lastBuild();
      fd.append("seed", String(Math.floor(Math.random() * 1e9)));
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
    return escapeHtml(text)
      .replace(/\[(to be confirmed by the founder|à confirmer par le fondateur|يؤكده الباعث)\]/gi, "<mark>[$1]</mark>")
      .replace(/\[NEEDED:[^\]]*\]/gi, (m) => `<mark class="needed">${m}</mark>`);
  }

  function render(data) {
    const { response: r, report: rep } = data;
    const planDoc = (r.artifacts || []).find((a) => a.label === "business_plan");
    const gp = rep && rep.generated_plan;
    let html = "";
    if (planDoc) {
      const nPol = gp ? gp.sections.filter((s) => s.polished).length : 0;
      const nSec = gp ? gp.sections.length : 0;
      html += `<div class="bp-doc-hero"><a class="dl plan" href="/api/files/${planDoc.file_ref}?kind=docx&name=business-plan">Download your business plan (.docx)</a>` +
        `<p class="note note--compact">${nPol ? `${nPol}/${nSec} sections drafted` : "Built from your answers"}. Open items are in the file.</p></div>`;
    } else if (lastBuild === buildChatFd) {
      html += `<p class="sig high">No Word file was produced (timeout or model error). Try again in a minute or raise BP_TIMEOUT_S in .env.</p>`;
    }
    html += `<p class="answer">${escapeHtml(r.status === "abstain" ? r.answer : rep ? rep.summary_text : r.answer)}</p>`;
    if (rep) {
      html += `<div class="meta">` + rep.input.methods.map((m) => `<span class="pill ok">${escapeHtml(m.replace("_", " "))}</span>`).join("") +
        `<span class="pill">${escapeHtml(rep.template.title)}</span>` +
        (rep.template.verified_against_official_model ? "" : `<span class="pill hold">skeleton not yet checked against the official model</span>`) +
        (rep.privacy.masking ? `<span class="pill">identifiers masked before any model call</span>` : `<span class="pill hold">masking off</span>`) + `</div>`;
      const a = rep.assessment;
      if (a) {
        const lab = a.label[langSel.value] || a.label.en;
        html += `<div class="verdict ${a.verdict}"><strong>${escapeHtml(lab)}</strong></div>` +
          `<p class="note note--compact">${escapeHtml(a.rationale)}</p>`;
        if (a.flags.length) html += `<h3>Red flags and weaknesses</h3>` + a.flags.map((f) =>
          `<div class="sig ${f.group === "fraud" ? "high" : "review"}">${escapeHtml(f.why)}${f.quote ? `<br><em>“${escapeHtml(f.quote)}”</em>` : ""}</div>`).join("");
        if (a.strengths.length) html += `<h3>Strengths</h3>` + a.strengths.map((f) => `<div class="sig info">${escapeHtml(f.why)}</div>`).join("");
      }
      html += `<h3>Sections</h3><div class="ui-stagger">` + rep.completeness.sections.map((s) =>
        `<div class="sec-row ui-in"><span>${escapeHtml(s.title)}</span><div class="bar ${s.status}"><i style="--bar-w:${s.score}%"></i></div><span>${s.score}</span></div>`).join("") + `</div>`;
      const fp = rep.final_plan;
      if (fp && fp.sections) {
        html += `<h3>Final plan (institutional rewrite)</h3>`;
        if (fp.verdict) html += `<p class="note verdict-line"><strong>Verdict:</strong> ${escapeHtml(fp.verdict)}</p>`;
        html += fp.sections.map((s) =>
          `<h4>${escapeHtml(s.title)}${s.status === "ok" ? "" : ` <span class="pill hold">${escapeHtml(s.status)}</span>`}</h4>` +
          `<div class="draft">${s.text ? renderDraft(s.text) : `<p class="note">${escapeHtml(formatBpError(s.error || "not generated"))}</p>`}</div>`).join("");
        if (fp.open_items && fp.open_items.length) {
          html += `<h4>Open items to confirm</h4><ol class="open-items">` +
            fp.open_items.map((i) => `<li>${escapeHtml(i)}</li>`).join("") + `</ol>`;
        }
        html += `<div class="regen-row"><button type="button" id="bp-regen" class="chip">Regenerate</button>` +
          `<span class="note">same answers, new variation</span></div>`;
      }
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
      const cr = rep.critique;
      if (cr && cr.weaknesses && cr.weaknesses.length) {
        html += `<h3>Plan critic (${cr.weaknesses.length} findings)</h3>` +
          cr.weaknesses.map((w) => `<div class="sig ${w.severity === "high" ? "high" : "review"}">${escapeHtml(w.why)}` +
            (w.quote ? `<br><em>“${escapeHtml(w.quote)}”</em>` : "") +
            (w.fix ? `<br><span class="note">Fix: ${escapeHtml(w.fix)}</span>` : "") + `</div>`).join("");
      }
      const miss = rep.context.missing_required || [];
      if (miss.length) {
        html += `<h3>Still needed</h3><ul class="open-items">${miss.map((id) => `<li>${escapeHtml(id.replace(/_/g, " "))}</li>`).join("")}</ul>`;
      }
      const f = rep.financials;
      if (f && f.years && f.years.length) {
        const row = (k, lab) => `<tr><td>${lab}</td>${(f[k] || []).map((v) => `<td>${money(v)}</td>`).join("")}</tr>`;
        const inc = f.incomplete;
        html += `<h3>Financial check (recomputed in code)${inc ? " · incomplete projection" : ""}</h3>` +
          `<table class="fin"><tr><th></th>${f.years.map((y) => `<th>${escapeHtml(y)}</th>`).join("")}</tr>` +
          row("revenue", "Revenue");
        if (inc && f.cogs) {
          const margin = f.revenue.map((r, i) => (r != null && f.cogs[i] != null ? r - f.cogs[i] : null));
          html += `<tr><td>Direct margin</td>${margin.map((v) => `<td>${money(v)}</td>`).join("")}</tr>`;
        } else {
          html += row("ebitda", "EBITDA") + row("net_income", "Net result") + row("cash_end", "Year-end cash");
        }
        html += `</table>`;
        if (!inc && f.break_even_year) html += `<p class="note">Break-even reached in ${escapeHtml(f.break_even_year)}.</p>`;
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
    }
    if (r.handoff) html += `<div class="sig info">This looks like a question for the ${escapeHtml(r.handoff.to)} assistant: ${escapeHtml(r.handoff.question)}</div>`;
    html += `<details class="trace-fold"><summary>Timing</summary><ol class="trace">${(r.trace || []).map((t) => `<li><strong>${escapeHtml(t.step)}</strong> · ${t.ms} ms${t.model ? ` · ${escapeHtml(t.model)}` : ""}</li>`).join("")}</ol></details>`;
    result.innerHTML = html;
    result.classList.add("ui-reveal-active");
    window.UI?.reveal(result);
    const regen = document.querySelector("#bp-regen");
    if (regen) regen.addEventListener("click", regenerate);
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    window.UI?.busy(button, true, "Running…");
    result.hidden = false;
    result.textContent = "Reading your plan…";
    try {
      const fd = new FormData();
      const action = document.querySelector("#bp-action").value;
      const mode = action === "review_full" ? "review" : action;
      fd.append("mode", mode);
      fd.append("lang", langSel.value);
      if (mode === "draft_section") fd.append("section_id", "missing");
      if (action === "review_full") fd.append("generate_plan", "true");
      fd.append("file", document.querySelector("#bp-file").files[0]);
      lastBuild = () => {
        const again = new FormData();
        const act = document.querySelector("#bp-action").value;
        const m = act === "review_full" ? "review" : act;
        again.append("mode", m);
        again.append("lang", langSel.value);
        if (m === "draft_section") again.append("section_id", "missing");
        if (act === "review_full") again.append("generate_plan", "true");
        again.append("file", document.querySelector("#bp-file").files[0]);
        return again;
      };
      const res = await fetch("/api/bp/run", { method: "POST", body: fd });
      if (!res.ok) throw new Error(await readError(res));
      render(await res.json());
    } catch (e) {
      result.textContent = e.message;
    } finally {
      window.UI?.busy(button, false);
    }
  });
})();
