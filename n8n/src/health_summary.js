// One status line per check, from the four HTTP nodes (each continues on error,
// so a service that is down arrives here as { error: ... } instead of stopping the run).
const read = (node) => { try { return $(node).first().json; } catch (e) { return { error: { message: "node did not run" } }; } };
const failed = (r) => Boolean(r.error) || (r.status && r.status !== "ok");

const app = read("Main app");
const fraud = read("Fraud service");
const bp = read("Business-plan service");
const llm = read("LLM keys");

const checks = [
  { name: "Main app (port 8000)", ok: !failed(app), detail: app.error?.message || app.status || "" },
  { name: "Fraud service (port 8100)", ok: !failed(fraud),
    detail: fraud.error?.message || `models loaded: ${Boolean(fraud.supervised_loaded && fraud.anomaly_loaded)}` },
  { name: "Business-plan service (port 8104)", ok: !failed(bp) && bp.llm_reachable !== false,
    detail: bp.error?.message || `model reachable: ${bp.llm_reachable}` },
];
// One line per LLM provider: key accepted and configured models still listed.
for (const [provider, info] of Object.entries(llm.providers || {})) {
  checks.push({ name: `LLM ${provider}`, ok: info.status === "ok",
    detail: info.status + (info.missing?.length ? ` (missing: ${info.missing.join(", ")})` : "") });
}
if (llm.error) checks.push({ name: "LLM keys", ok: false, detail: llm.error.message });

const now = new Date();
const down = checks.filter((c) => !c.ok).map((c) => c.name);
return [{ json: {
  checked_at: now.toISOString(),
  ok: down.length === 0,
  down,
  summary: down.length ? `${down.length} problem(s): ${down.join("; ")}` : `All ${checks.length} checks passed`,
  checks,
  file_name: now.toISOString().slice(0, 16).replace(/[:T]/g, "-"),
} }];
