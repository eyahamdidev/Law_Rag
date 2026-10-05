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

document.querySelector("#ask-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  const result = document.querySelector("#ask-result");
  button.disabled = true;
  result.hidden = false;
  result.textContent = "Routing…";
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: form.question.value }),
    });
    if (!response.ok) throw new Error(await readError(response));
    const body = await response.json();
    const domains = body.domains.length ? body.domains.join(", ") : "none yet";
    result.innerHTML =
      `<p class="answer">${escapeHtml(body.answer)}</p>` +
      pills([
        [`intent: ${body.intent}`, "ok"],
        [`domains: ${domains}`, ""],
        [`language: ${body.language}`, ""],
        [body.abstained ? "abstained" : "answered", body.abstained ? "hold" : "ok"],
      ]) +
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
    const response = await fetch("/api/aid/match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        stage: form.stage.value,
        sector: form.sector.value,
        need: form.need.value,
      }),
    });
    if (!response.ok) throw new Error(await readError(response));
    const body = await response.json();
    const cards = body.programs
      .map((program) => {
        const files = program.local_files
          .map((file) => `<li><code>${escapeHtml(file)}</code></li>`)
          .join("");
        return (
          `<article class="program">` +
          `<h2>${escapeHtml(program.name)}</h2>` +
          `<p>${escapeHtml(program.provider)}. ${escapeHtml(program.summary)}</p>` +
          `<ul class="files">${files}</ul>` +
          `</article>`
        );
      })
      .join("");
    result.innerHTML =
      `<p class="answer">${escapeHtml(body.summary)}</p>` +
      cards +
      traceList(body.trace);
  } catch (error) {
    result.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

loadCounts();
