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

const FRAUD_SECRET_KEY = "fraud_tenant_secret";

function fraudTenantSecret() {
  try {
    return localStorage.getItem(FRAUD_SECRET_KEY) || "";
  } catch {
    return "";
  }
}

function storeFraudTenantSecret(secret) {
  if (!secret) return;
  try {
    localStorage.setItem(FRAUD_SECRET_KEY, secret);
  } catch {
    /* ignore */
  }
}

const _fetch = window.fetch.bind(window);
window.fetch = (url, opts = {}) => {
  if (typeof url === "string" && url.startsWith("/api/")) {
    const headers = { ...(opts.headers || {}), "X-Session-Id": SESSION_ID };
    const secret = fraudTenantSecret();
    if (secret) headers["X-Fraud-Tenant-Secret"] = secret;
    opts = { ...opts, headers };
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
    if (active && panel.hidden) {
      panel.hidden = false;
      panel.classList.remove("is-active");
      requestAnimationFrame(() => panel.classList.add("is-active"));
    } else {
      panel.classList.toggle("is-active", active);
      panel.hidden = !active;
    }
  });
  window.scrollTo({ top: 0, behavior: window.UI?.reduced ? "auto" : "smooth" });
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
    .map((step) => `<li><strong>${escapeHtml(step.module)}</strong> · ${escapeHtml(step.detail)}</li>`)
    .join("");
  return `<ol class="trace">${items}</ol>`;
}

const FRAUD_SIGNAL_TITLES = {
  document_stamp_uncertain: "Stamp unclear",
  document_stamp_fraudulent: "Stamp mismatch",
  document_stamp_missing: "Stamp missing",
  document_stamp_unrecognized: "Different stamp",
};

function fraudSignalTitle(code) {
  return FRAUD_SIGNAL_TITLES[code] || String(code || "signal").replaceAll("_", " ");
}

function fraudRiskLabel(level) {
  if (!level || level === "unknown") return "Unknown";
  return level.charAt(0).toUpperCase() + level.slice(1);
}

function fraudStampVerdictLabel(verdict) {
  const map = {
    genuine: "Matches saved",
    fraudulent: "Does not match",
    uncertain: "Unclear scan",
    unrecognized: "New stamp",
    awaiting_approval: "Needs save",
  };
  return map[verdict] || verdict || "—";
}

function fraudSignalsForDisplay(body) {
  const signals = body.signals || [];
  if (body.document_type === "payment") {
    return signals.filter((s) => !String(s.code || "").startsWith("document_stamp"));
  }
  return signals;
}

function fraudSignalCards(signals) {
  if (!signals?.length) return "";
  const cards = signals
    .map((signal) => {
      const severity = (signal.severity || "medium").toLowerCase();
      return (
        `<article class="fraud-signal-card severity-${escapeHtml(severity)}">` +
        `<p class="fraud-signal-kicker">${escapeHtml(severity)}</p>` +
        `<h3 class="fraud-signal-title">${escapeHtml(fraudSignalTitle(signal.code))}</h3>` +
        `<p class="fraud-signal-body">${escapeHtml(signal.description)}</p>` +
        `</article>`
      );
    })
    .join("");
  return `<section class="fraud-signals"><h3 class="fraud-section-title">Signals</h3><div class="fraud-signal-grid">${cards}</div></section>`;
}

function renderFraudResult(body) {
  const isPayment = body.document_type === "payment";
  const risk = body.risk_level || "unknown";
  const riskClass = risk === "low" ? "low" : risk === "medium" ? "medium" : risk === "high" ? "high" : "unknown";
  const score = body.risk_score != null ? `${body.risk_score}<span class="fraud-stat-unit">/100</span>` : "—";
  let headline = body.headline || body.summary || "";
  if (isPayment && headline.toLowerCase().includes("stamp")) {
    headline = "Payment scored. See risk and signals below.";
  }
  const displaySignals = fraudSignalsForDisplay(body);
  const traceBlock = body.trace?.length
    ? `<details class="note fraud-trace-details"><summary>Technical details</summary>${traceList(body.trace)}</details>`
    : "";
  return (
    `<p class="fraud-headline">${escapeHtml(headline)}</p>` +
    `<div class="fraud-stats">` +
    `<div class="fraud-stat fraud-stat-risk ${riskClass}"><span class="fraud-stat-label">Risk</span><span class="fraud-stat-value">${escapeHtml(fraudRiskLabel(risk))}</span></div>` +
    `<div class="fraud-stat fraud-stat-score"><span class="fraud-stat-label">Score</span><span class="fraud-stat-value">${score}</span></div>` +
    `</div>` +
    fraudSignalCards(displaySignals) +
    traceBlock
  );
}

let fraudEnrollmentQueue = [];
let fraudEnrollmentIndex = 0;

function closeFraudModal() {
  const modal = document.querySelector("#fraud-modal");
  modal.hidden = true;
  fraudEnrollmentQueue = [];
  fraudEnrollmentIndex = 0;
}

function showCurrentFraudEnrollment() {
  const item = fraudEnrollmentQueue[fraudEnrollmentIndex];
  if (!item) {
    closeFraudModal();
    return;
  }
  document.querySelector("#fraud-modal-title").textContent = item.title;
  document.querySelector("#fraud-modal-sub").textContent = item.subtitle || "Future uploads will be compared to what you save.";
  const preview = document.querySelector("#fraud-modal-preview");
  if (item.preview_base64) {
    preview.innerHTML = `<img src="data:image/png;base64,${item.preview_base64}" alt="${escapeHtml(item.kind)} preview">`;
    preview.classList.add("is-loaded");
  } else {
    preview.innerHTML = `<span class="note">Preview not available — you can still save the crop.</span>`;
    preview.classList.remove("is-loaded");
  }
  const step = document.querySelector("#fraud-modal-step");
  step.textContent =
    fraudEnrollmentQueue.length > 1 ? `Step ${fraudEnrollmentIndex + 1} of ${fraudEnrollmentQueue.length}` : "";
  const status = document.querySelector("#fraud-modal-status");
  status.textContent = "";
  status.className = "fraud-modal-status";
}

function openFraudEnrollments(enrollments) {
  const stamps = (enrollments || []).filter((item) => item.kind === "stamp");
  if (!stamps.length) return;
  fraudEnrollmentQueue = stamps;
  fraudEnrollmentIndex = 0;
  document.querySelector("#fraud-modal").hidden = false;
  showCurrentFraudEnrollment();
}

async function submitFraudEnrollment(approve) {
  const item = fraudEnrollmentQueue[fraudEnrollmentIndex];
  if (!item) return;
  const saveBtn = document.querySelector("#fraud-modal-save");
  const skipBtn = document.querySelector("#fraud-modal-skip");
  const status = document.querySelector("#fraud-modal-status");
  saveBtn.disabled = true;
  skipBtn.disabled = true;
  status.textContent = approve ? "Saving…" : "Skipping…";
  try {
    const response = await fetch("/api/fraud/decide", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        proposal_id: item.proposal_id,
        approve,
        tenant_secret: fraudTenantSecret() || null,
      }),
    });
    if (!response.ok) throw new Error(await readError(response));
    const body = await response.json();
    storeFraudTenantSecret(body.tenant_secret);
    status.textContent = body.message;
    status.className = "fraud-modal-status ok";
    await new Promise((r) => setTimeout(r, approve && body.enrolled ? 900 : 400));
    fraudEnrollmentIndex += 1;
    if (fraudEnrollmentIndex >= fraudEnrollmentQueue.length) {
      closeFraudModal();
    } else {
      showCurrentFraudEnrollment();
    }
  } catch (error) {
    status.textContent = error.message;
    status.className = "fraud-modal-status";
  } finally {
    saveBtn.disabled = false;
    skipBtn.disabled = false;
  }
}

document.querySelector("#fraud-modal-save")?.addEventListener("click", () => submitFraudEnrollment(true));
document.querySelector("#fraud-modal-skip")?.addEventListener("click", () => submitFraudEnrollment(false));
document.querySelectorAll("[data-fraud-dismiss]").forEach((el) => {
  el.addEventListener("click", () => {
    if (fraudEnrollmentQueue.length) submitFraudEnrollment(false);
    else closeFraudModal();
  });
});

function formatStampDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function closeFraudGallery() {
  document.querySelector("#fraud-gallery").hidden = true;
}

async function openFraudGallery() {
  const modal = document.querySelector("#fraud-gallery");
  const grid = document.querySelector("#fraud-gallery-grid");
  const status = document.querySelector("#fraud-gallery-status");
  modal.hidden = false;
  grid.innerHTML = "";
  status.textContent = "Loading…";
  try {
    const response = await fetch("/api/fraud/stamps");
    if (!response.ok) throw new Error(await readError(response));
    const body = await response.json();
    if (body.locked) {
      status.textContent = body.message;
      return;
    }
    if (!body.stamps?.length) {
      status.textContent = body.message || "No saved stamps yet. Run a check and save a stamp from the popup.";
      return;
    }
    status.textContent = `${body.stamps.length} saved stamp${body.stamps.length > 1 ? "s" : ""} for this browser`;
    grid.innerHTML = body.stamps
      .map((stamp) => {
        const preview = stamp.preview_base64
          ? `<img src="data:image/png;base64,${stamp.preview_base64}" alt="Saved stamp">`
          : `<div class="fraud-gallery-placeholder">No preview</div>`;
        const text = stamp.read_text ? `<p class="fraud-gallery-text"><strong>Text:</strong> ${escapeHtml(stamp.read_text)}</p>` : "";
        return (
          `<article class="fraud-gallery-card">` +
          `<div class="fraud-gallery-preview">${preview}</div>` +
          `<p class="fraud-gallery-id">${escapeHtml(stamp.specimen_id)}</p>` +
          `<p class="fraud-gallery-meta">${escapeHtml(formatStampDate(stamp.created_at))}</p>` +
          `<p class="fraud-gallery-comment">${escapeHtml(stamp.comment || "")}</p>` +
          text +
          `</article>`
        );
      })
      .join("");
  } catch (error) {
    status.textContent = error.message;
  }
}

document.querySelector("#fraud-gallery-open")?.addEventListener("click", () => openFraudGallery());
document.querySelectorAll("[data-fraud-gallery-dismiss]").forEach((el) => {
  el.addEventListener("click", () => closeFraudGallery());
});

function setFraudMode(mode) {
  const stamp = mode === "stamp";
  document.querySelector("#fraud-mode-input").value = mode;
  for (const button of document.querySelectorAll("[data-fraud-mode]")) {
    const active = button.dataset.fraudMode === mode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  }
  document.querySelector("#fraud-stamp-note").hidden = !stamp;
  document.querySelector("#fraud-payment-fields").hidden = stamp;
  const galleryBtn = document.querySelector("#fraud-gallery-open");
  if (galleryBtn) galleryBtn.hidden = !stamp;
  const result = document.querySelector("#fraud-result");
  if (result) {
    result.hidden = true;
    result.innerHTML = "";
  }
  const file = document.querySelector("#fraud-file");
  file.value = "";
  file.accept = stamp ? ".pdf,.png,.jpg,.jpeg,.webp" : ".json,.pdf,.txt,.md";
}

for (const button of document.querySelectorAll("[data-fraud-mode]")) {
  button.addEventListener("click", () => setFraudMode(button.dataset.fraudMode));
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
  window.UI?.busy(button, true, "Searching…");
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
    window.UI?.busy(button, false);
    result.classList.add("ui-reveal-active");
    window.UI?.reveal(result);
  }
});

document.querySelector("#fraud-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  const result = document.querySelector("#fraud-result");
  window.UI?.busy(button, true, "Checking…");
  result.hidden = false;
  result.textContent = "Reading the file…";
  try {
    const data = new FormData(form);
    if (data.get("mode") === "stamp") {
      data.delete("entity_id");
      const secret = fraudTenantSecret();
      if (secret) data.set("tenant_secret", secret);
    }
    const response = await fetch("/api/fraud/analyze", { method: "POST", body: data });
    if (!response.ok) throw new Error(await readError(response));
    const body = await response.json();
    result.innerHTML = renderFraudResult(body);
    openFraudEnrollments(body.enrollments);
  } catch (error) {
    result.textContent = error.message;
  } finally {
    window.UI?.busy(button, false);
    result.classList.add("ui-reveal-active");
    window.UI?.reveal(result);
  }
});

document.querySelector("#aid-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  const result = document.querySelector("#aid-result");
  window.UI?.busy(button, true, "Matching…");
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
    window.UI?.busy(button, false);
    result.classList.add("ui-reveal-active");
    window.UI?.reveal(result);
  }
});

loadCounts();
document.querySelector("#ui-language").addEventListener("change", (event) => {
  setInterfaceLanguage(event.target.value);
});
setInterfaceLanguage("en");
