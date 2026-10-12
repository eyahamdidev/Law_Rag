"""Chart maker: projection chart (png) and, when a vision model is configured, chart/table reading.

Labels are Latin script only. Matplotlib does not shape Arabic text, so the
chart uses French or English labels even when the plan is in Arabic.
"""

from __future__ import annotations

import io

from app import prompts
from app.agents.common import Trace
from app.config import model_for
from app.intake import Document, page_images
from app.llm import LLMClient, LLMUnavailable

LABELS = {
    "fr": {"title": "Projection financière", "rev": "Chiffre d'affaires", "net": "Résultat net", "cash": "Trésorerie fin d'année", "unit": "TND"},
    "en": {"title": "Financial projection", "rev": "Revenue", "net": "Net result", "cash": "Year-end cash", "unit": "TND"},
}


def projection_png(derived: dict, lang: str = "fr") -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    L = LABELS.get(lang, LABELS["en"])
    years = derived["years"]
    x = list(range(len(years)))
    fig, ax = plt.subplots(figsize=(7.5, 4.2), dpi=130)
    w = 0.38
    ax.bar([i - w / 2 for i in x], derived["revenue"], w, label=L["rev"], color="#2f5d8a")
    ax.bar([i + w / 2 for i in x], derived["net_income"], w, label=L["net"], color="#7aa95c")
    ax.plot(x, derived["cash_end"], marker="o", color="#b5532a", label=L["cash"])
    ax.axhline(0, color="#444", lw=0.8)
    ax.set_xticks(x, years)
    ax.set_ylabel(L["unit"])
    ax.set_title(L["title"])
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:,.0f}".replace(",", " "))
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def read_charts(doc: Document, llm: LLMClient, trace: Trace) -> list[dict]:
    """Ask the vision model to read tables or charts from scanned pages. Returns candidate rows, never final numbers.

    The caller shows these as 'read by a model, check them'. They are not used in
    checks unless the deterministic table reader found nothing.
    """
    if not doc.scanned_pages or not llm.available:
        return []
    imgs = page_images(doc)
    if not imgs:
        return []
    p = prompts.load("chart_reader")
    model = model_for("llm_vision")
    with trace.step("chart_reader.vision", model=model, prompt_id=prompts.ref(p)):
        try:
            out = llm.chat_json(model=model, system="You read tables and charts from plan pages. Reply with JSON only.",
                                user=p["text"], images=imgs, schema=p.get("output_schema"), max_tokens=1500)
        except LLMUnavailable as exc:
            trace.note(f"chart_reader skipped: {exc}")
            return []
    rows = out.get("rows", [])
    return [r for r in rows if isinstance(r, dict) and "label" in r][:60]
