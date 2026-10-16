const tabs = document.querySelectorAll(".tab");
const panels = document.querySelectorAll(".panel");

tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    const name = tab.dataset.panel;
    tabs.forEach((item) => {
      const active = item === tab;
      item.classList.toggle("is-active", active);
      item.setAttribute("aria-selected", active ? "true" : "false");
    });
    panels.forEach((panel) => {
      const active = panel.id === name;
      panel.classList.toggle("is-active", active);
      panel.hidden = !active;
    });
  });
});

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function traceList(trace) {
  if (!trace || !trace.length) return "";
  const items = trace
    .map((step) => `<li><strong>${escapeHtml(step.module)}</strong> — ${escapeHtml(step.detail)}</li>`)
    .join("");
  return `<ol class="trace">${items}</ol>`;
}

function ruleTraceList(trace) {
  if (!trace || !trace.length) return "";
  const items = trace.map((entry) => {
    const state = entry.passed ? "passed" : "failed";
    return (
      `<li class="rule-trace-entry ${state}">` +
      `<strong>${escapeHtml(entry.program_id)}</strong> · ` +
      `<span class="pill ${entry.passed ? "ok" : "hold"}">${escapeHtml(entry.step)}</span>` +
      `<br><span>${escapeHtml(entry.details)}</span></li>`
    );
  }).join("");
  return `<details><summary>Deterministic rule trace (${trace.length} checks)</summary><ol class="rule-trace">${items}</ol></details>`;
}

function checklistList(checklists) {
  if (!checklists || !checklists.length) return "";
  const items = checklists.map((checklist) => {
    const docs = checklist.required_documents
      .map((doc) => `<li>${escapeHtml(doc)}</li>`)
      .join("");
    return (
      `<article class="checklist"><h3>${escapeHtml(checklist.program_name)}</h3>` +
      `<ul class="files">${docs}</ul>` +
      (checklist.official_form_link
        ? `<p><strong>Official form:</strong> <code>${escapeHtml(checklist.official_form_link)}</code></p>`
        : "") +
      `</article>`
    );
  }).join("");
  return `<h2>Required documents</h2>${items}`;
}

function excludedList(programs) {
  if (!programs || !programs.length) return "";
  const items = programs.map((program) => {
    const reasons = (program.reasons || []).map((reason) => `<li>${escapeHtml(reason)}</li>`).join("");
    return `<li><strong>${escapeHtml(program.name)}</strong><ul>${reasons}</ul></li>`;
  }).join("");
  return `<details><summary>Excluded programs (${programs.length})</summary><ul class="excluded">${items}</ul></details>`;
}

function pills(pairs) {
  return `<div class="meta">${pairs
    .map(([label, kind]) => `<span class="pill ${kind}">${escapeHtml(label)}</span>`)
    .join("")}</div>`;
}

async function readError(response) {
  try {
    const body = await response.json();
    return body.detail ? JSON.stringify(body.detail) : response.statusText;
  } catch {
    return response.statusText;
  }
}

async function loadCounts() {
  const target = document.querySelector("#counts");
  try {
    const response = await fetch("/api/corpus");
    if (!response.ok) throw new Error(await readError(response));
    const body = await response.json();
    target.textContent =
      `Law corpus: ${body.law.pdf_count} PDFs. ` +
      `Aid folder: ${body.aid.file_count} files. ` +
      `Fraud drop folder: ${body.fraud.file_count} files.`;
  } catch (error) {
    target.textContent = `Could not read the local folders (${error.message}).`;
  }
}

let sessionId = null;

function citationList(citations) {
  if (!citations || !citations.length) return "";
  const items = citations
    .map((c) => {
      const where = [c.act || c.title, c.article ? `art. ${c.article}` : "", `p. ${c.page}`]
        .filter(Boolean)
        .join(", ");
      const check = c.supported === false ? "hold" : c.supported ? "ok" : "";
      return (
        `<li><strong>[${c.ref}]</strong> ${escapeHtml(where)} ` +
        `<span class="pill ${check}">${c.supported === null ? "unchecked" : c.supported ? "supported" : "weak"}</span>` +
        `<br><code>${escapeHtml(c.path)}</code>` +
        `<blockquote>${escapeHtml(c.quote)}…</blockquote></li>`
      );
    })
    .join("");
  return `<h2>Sources</h2><ol class="citations">${items}</ol>`;
}

const translations = {
  en: { aid: "Aid and financing", evaluate: "Evaluate eligibility", interface: "Interface language" },
  fr: { aid: "Aides et financement", evaluate: "Évaluer l'éligibilité", interface: "Langue de l'interface" },
  ar: { aid: "المساعدات والتمويل", evaluate: "تقييم الأهلية", interface: "لغة الواجهة" },
};

function setInterfaceLanguage(language) {
  const text = translations[language] || translations.en;
  document.documentElement.lang = language;
  document.documentElement.dir = language === "ar" ? "rtl" : "ltr";
  document.querySelector('[data-panel="aid"]').textContent = text.aid;
  document.querySelector('#aid-form button[type="submit"]').textContent = text.evaluate;
  document.querySelector(".language-picker").childNodes[0].textContent = `${text.interface} `;
}

document.querySelector("#ask-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  const result = document.querySelector("#ask-result");
  button.disabled = true;
  result.hidden = false;
  result.textContent = "Planning, searching and checking sources…";
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: form.question.value, session_id: sessionId }),
    });
    if (!response.ok) throw new Error(await readError(response));
    const body = await response.json();
    sessionId = body.session_id;
    const agents = body.plan.steps.length ? body.plan.steps.map((s) => s.agent).join(", ") : "none";
    const v = body.verification || {};
    result.innerHTML =
      `<p class="answer">${escapeHtml(body.answer).replaceAll("\n", "<br>")}</p>` +
      pills([
        [`plan: ${body.plan.source}`, body.plan.source === "llm" ? "ok" : "hold"],
        [`agents: ${agents}`, ""],
        [`language: ${body.language}`, ""],
        [body.abstained ? "abstained" : "answered", body.abstained ? "hold" : "ok"],
        [`claims supported: ${v.supported ?? 0}/${v.claims_total ?? 0}`, ""],
        [`${Math.round(body.latency_ms)} ms`, ""],
      ]) +
      citationList(body.citations) +
      `<p class="note">Information from official texts, not legal advice. Texts may have been amended since the cited version.</p>` +
      traceList(body.trace);
  } catch (error) {
    result.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#fraud-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  const result = document.querySelector("#fraud-result");
  button.disabled = true;
  result.hidden = false;
  result.textContent = "Reading the file…";
  try {
    const data = new FormData(form);
    const response = await fetch("/api/fraud/analyze", { method: "POST", body: data });
    if (!response.ok) throw new Error(await readError(response));
    const body = await response.json();
    result.innerHTML =
      `<p class="answer">${escapeHtml(body.summary)}</p>` +
      pills([
        [`type: ${body.document_type}`, ""],
        [`risk: ${body.risk_level}`, "hold"],
        [`sha256: ${body.document_hash.slice(0, 12)}…`, ""],
      ]) +
      traceList(body.trace);
  } catch (error) {
    result.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#aid-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  const result = document.querySelector("#aid-result");
  button.disabled = true;
  result.hidden = false;
  result.textContent = "Matching the catalog…";
  try {
    const numberOrNull = (value) => value === "" ? null : Number(value);
    const checkedOrNull = (name) => {
      const checkbox = form.querySelector(`[name="${name}"]`);
      return checkbox.checked ? true : null;
    };
    const response = await fetch("/api/aid/match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        stage: form.stage.value,
        sector: form.sector.value,
        need: form.need.value,
        funding_need_tnd: numberOrNull(form.funding_need_tnd.value),
        employees: numberOrNull(form.employees.value),
        governorate: form.governorate.value || null,
        is_innovative: checkedOrNull("is_innovative"),
        has_startup_label: checkedOrNull("has_startup_label"),
        is_graduate: checkedOrNull("is_graduate"),
        free_text: form.free_text.value || null,
      }),
    });
    if (!response.ok) throw new Error(await readError(response));
    const body = await response.json();
    const cards = body.programs
      .map((program) => {
        const files = program.required_documents
          .map((file) => `<li>${escapeHtml(file)}</li>`)
          .join("");
        return (
          `<article class="program">` +
          `<h2>${escapeHtml(program.name)}</h2>` +
          `<p>${escapeHtml(program.provider)}. ${escapeHtml(program.summary)}</p>` +
          `<p><strong>Source:</strong> <code>${escapeHtml(program.source_file)} · page ${escapeHtml(program.source_page)}</code></p>` +
          `<h3>Required documents</h3><ul class="files">${files}</ul>` +
          (program.official_form_link
            ? `<p><strong>Official form:</strong> <code>${escapeHtml(program.official_form_link)}</code></p>`
            : "") +
          `</article>`
        );
      })
      .join("");
    const handoff = body.handoff
      ? `<div class="handoff"><strong>Legal handoff:</strong> ${escapeHtml(body.handoff.question)}</div>`
      : "";
    result.innerHTML =
      `<p class="answer">${escapeHtml(body.summary)}</p>` +
      (body.answer ? `<div class="aid-explanation">${escapeHtml(body.answer).replaceAll("\n", "<br>")}</div>` : "") +
      citationList(body.citations) +
      pills([
        [`eligible: ${body.programs.length}`, body.programs.length ? "ok" : "hold"],
        [`excluded: ${body.excluded_programs.length}`, ""],
        [`checks: ${body.rule_trace.length}`, ""],
      ]) +
      handoff +
      cards +
      checklistList(body.document_checklists) +
      excludedList(body.excluded_programs) +
      ruleTraceList(body.rule_trace) +
      traceList(body.trace);
  } catch (error) {
    result.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

loadCounts();
document.querySelector("#ui-language").addEventListener("change", (event) => {
  setInterfaceLanguage(event.target.value);
});
setInterfaceLanguage("en");
