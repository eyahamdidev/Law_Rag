// One browser session id, so what the assistant learns in one tab is available in the others.
const SESSION_ID = (() => {
  try {
    let id = localStorage.getItem("session_id");
    if (!id) {
      id = (crypto.randomUUID && crypto.randomUUID()) || String(Date.now()) + Math.random();
      localStorage.setItem("session_id", id);
    }
    return id;
  } catch {
    return "anonymous-" + Date.now();
  }
})();
const _fetch = window.fetch.bind(window);
window.fetch = (url, opts = {}) => {
  if (typeof url === "string" && url.startsWith("/api/")) {
    opts = { ...opts, headers: { ...(opts.headers || {}), "X-Session-Id": SESSION_ID } };
  }
  return _fetch(url, opts);
};

// Only the sidebar tabs and the top-level panels: the legal workspace has its own sub-tabs.
const tabs = document.querySelectorAll(".sidebar .tab");
const panels = document.querySelectorAll("main > .panel");
// URL hash -> panel, so links like /#/legal or /#/contracts (from /legal.html) open the right one.
// The "/" keeps hashes from matching element ids, which would make the browser jump down.
const HASH_PANELS = { "/ask": "ask", "/legal": "legal", "/contracts": "legal", "/aid": "aid", "/bp": "bp", "/fraud": "fraud" };

function showPanel(name) {
  tabs.forEach((item) => {
    const active = item.dataset.panel === name;
    item.classList.toggle("is-active", active);
    item.setAttribute("aria-selected", active ? "true" : "false");
  });
  panels.forEach((panel) => {
    const active = panel.id === name;
    panel.classList.toggle("is-active", active);
    panel.hidden = !active;
  });
  window.scrollTo({ top: 0 });
}

tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    history.replaceState(null, "", `#/${tab.dataset.panel}`);
    showPanel(tab.dataset.panel);
  });
});
window.addEventListener("hashchange", () => showPanel(HASH_PANELS[location.hash.slice(1)] || "ask"));
showPanel(HASH_PANELS[location.hash.slice(1)] || "ask");

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

// Catalogue figures not stated in their cited source: shown, never applied by the rules engine.
const UNVERIFIED_LABELS = {
  min_investment_tnd: "minimum project cost (TND)",
  max_investment_tnd: "maximum project cost (TND)",
  max_employees: "maximum number of employees",
};
function unverifiedNote(unverified) {
  const figures = Object.entries(unverified || {}).filter(([key]) => key !== "reason");
  if (!figures.length) return "";
  const items = figures
    .map(([key, value]) => `${escapeHtml(UNVERIFIED_LABELS[key] || key.replaceAll("_", " "))}: ${escapeHtml(Number(value).toLocaleString("en"))}`)
    .join("; ");
  return `<p class="unverified"><strong>To confirm with the provider</strong> (figure not found in our official sources): ${items}</p>`;
}

// Words for the rules engine's internal values.
const AID_WORDS = {
  idea: "idea", creation: "company creation", early: "early stage", extension: "expansion", growth: "growth",
  grant: "grant", loan: "loan", guarantee: "loan guarantee", tax_incentive: "tax advantage", mixed: "support package",
  financing: "financing", guidance: "guidance",
};
const aidWord = (value) => AID_WORDS[value] || String(value).replaceAll("_", " ");
const aidList = (text) => text.replace(/[[\]']/g, "").split(",").map((v) => aidWord(v.trim())).filter(Boolean).join(", ");

// Turn a rules-engine reason ("Incompatible stage: requires ['extension', 'growth']") into a sentence.
function plainReason(reason) {
  const rules = [
    [/^Incompatible stage: requires (\[.*\])$/, (m) => `Only for projects at these stages: ${aidList(m[1])}.`],
    [/^Sector '(.+)' not in eligible sectors \((\[.*\])\)$/, (m) => `Your sector (${aidWord(m[1])}) is not covered. It funds: ${aidList(m[2])}.`],
    [/^Sector '(.+)' (is explicitly excluded|is in excluded cluster).*$/, (m) => `Your sector (${aidWord(m[1])}) is excluded by this programme.`],
    [/^Program type '(.+)' does not match requested need '(.+)'$/, (m) => `It offers a ${aidWord(m[1])}, not the ${aidWord(m[2])} you asked for.`],
    [/^Headcount (\d+) exceeds max (\d+)$/, (m) => `For companies with at most ${m[2]} employees (you have ${m[1]}).`],
    [/^Headcount (\d+) below min (\d+)$/, (m) => `For companies with at least ${m[2]} employees (you have ${m[1]}).`],
    [/^Funding need (.+) TND exceeds cap (.+) TND$/, (m) => `Your need (${m[1]} TND) is above its limit of ${m[2]} TND.`],
    [/^Funding need (.+) TND below min threshold (.+) TND$/, (m) => `Your need (${m[1]} TND) is below its minimum of ${m[2]} TND.`],
    [/^Program strictly requires innovation.*$/, () => "Only for innovative projects."],
    [/^Program requires an active Startup Label.*$/, () => "Only for companies with the Startup Label."],
    [/^Program requires founder to hold a university degree.*$/, () => "Only for founders with a university degree or certified vocational training."],
    [/^Program requires location in a designated regional development zone.*$/, () => "Only in regional development zones: give your governorate to check."],
    [/^Governorate '(.+)' is not an eligible regional development zone$/, (m) => `${aidWord(m[1]).replace(/^./, (c) => c.toUpperCase())} is not a regional development zone.`],
  ];
  for (const [pattern, write] of rules) {
    const match = reason.match(pattern);
    if (match) return write(match);
  }
  return reason.replace(/[[\]']/g, "");
}

function programCard(program) {
  const docs = program.required_documents.map((doc) => `<li>${escapeHtml(doc)}</li>`).join("");
  const link = program.official_form_link || "";
  const form = !link ? ""
    : /^https?:\/\//.test(link)
      ? `<p><strong>Where to apply:</strong> <a href="${escapeHtml(link)}" target="_blank" rel="noopener">${escapeHtml(link.replace(/^https?:\/\//, ""))}</a></p>`
      : `<p><strong>Application form:</strong> ${escapeHtml(link.split("/").pop())} (in the project's grants folder)</p>`;
  const source = program.source_file ? `${program.source_file.split("/").pop()}, page ${program.source_page}` : "";
  return (
    `<article class="program">` +
    `<h2>${escapeHtml(program.name)}</h2>` +
    `<p>${escapeHtml(program.provider)}. ${escapeHtml(program.summary)}</p>` +
    unverifiedNote(program.unverified) +
    (docs ? `<h3>Documents usually requested</h3><p class="note">Indicative list: confirm with the provider.</p><ul class="files">${docs}</ul>` : "") +
    form +
    (source ? `<p class="note">Source: ${escapeHtml(source)}</p>` : "") +
    `</article>`
  );
}

function excludedList(programs) {
  if (!programs || !programs.length) return "";
  const items = programs.map((program) => {
    const reasons = (program.reasons || []).map((reason) => `<li>${escapeHtml(plainReason(reason))}</li>`).join("");
    return `<li><strong>${escapeHtml(program.name)}</strong><ul>${reasons}</ul></li>`;
  }).join("");
  return `<details><summary>Not a fit for you (${programs.length})</summary><ul class="excluded">${items}</ul></details>`;
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
    // Founders see the match itself: programme cards and plain reasons. The LLM-written
    // explanation (body.answer) is not shown: it was raw markdown and could restate
    // documents or reasons that are not in the catalogue. Rule checks go under "Technical details".
    const cards = body.programs.map(programCard).join("");
    const count = body.programs.length;
    const headline = count
      ? `${count} programme${count > 1 ? "s" : ""} may fit your profile. The provider makes the final decision.`
      : "No programme in our catalogue matches these answers. Try leaving a field empty, or ask in the Chat tab.";
    const handoff = body.handoff
      ? `<div class="handoff">This looks like a question about the law itself. Ask it in the <strong>Chat</strong> or <strong>Legal workspace</strong> tab.</div>`
      : "";
    result.innerHTML =
      `<p class="answer">${escapeHtml(headline)}</p>` +
      handoff +
      cards +
      excludedList(body.excluded_programs) +
      `<details class="technical"><summary>Technical details (for reviewers)</summary>` +
      pills([
        [`eligible: ${body.programs.length}`, body.programs.length ? "ok" : "hold"],
        [`excluded: ${body.excluded_programs.length}`, ""],
        [`checks: ${body.rule_trace.length}`, ""],
      ]) +
      `<p class="note">${escapeHtml(body.summary)}</p>` +
      ruleTraceList(body.rule_trace) +
      traceList(body.trace) +
      `</details>`;
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
