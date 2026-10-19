"""The claim guard: unsupported claims become [NEEDED] placeholders, supported ones stay. Pure functions, no model."""

from app.agents import claim_guard as cg

M = "[to be confirmed by the founder]"


def ev(**values):
    return cg.build_evidence(values)


def test_unsupported_experience_claim_becomes_placeholder():
    text = "Polaris sells sensors. Our experienced professionals bring a wealth of experience to the table. Prices start at 450 TND."
    out, issues = cg.sanitize(text, ev(founders="Aya - CEO"))
    assert "wealth of experience" not in out and "experienced professionals" not in out
    assert "[NEEDED: relevant experience of each team member" in out
    assert out.startswith("Polaris sells sensors.") and out.endswith("Prices start at 450 TND.")
    assert [i["rule"] for i in issues] == ["experience_claim"]  # two sentences in the same sentence-list: one issue each sentence


def test_supported_experience_claim_is_kept():
    text = "Our CEO brings a wealth of experience from the cooperative sector."
    out, issues = cg.sanitize(text, ev(founders="Aya - CEO", key_skills="8 years at an olive cooperative"))
    assert out == text and not issues


def test_source_claim_needs_a_source_in_the_inputs():
    text = "According to recent studies, the market is growing. We start in Sfax."
    out, issues = cg.sanitize(text, ev(sector="olive sensors"))
    assert "recent studies" not in out and "[NEEDED: name the source" in out and out.endswith("We start in Sfax.")
    kept, _ = cg.sanitize("According to recent studies, 80 000 farms exist.", ev(market_size_note="80 000 farms, Ministry of Agriculture 2023"))
    assert kept == "According to recent studies, 80 000 farms exist."


def test_market_adjectives_need_a_sized_market():
    out, issues = cg.sanitize("The market is huge.", ev(sector="x"))
    assert out.startswith("[NEEDED: size of the market") and issues[0]["rule"] == "market_claim"
    kept, _ = cg.sanitize("The market is huge.", ev(market_size_note="14 000 farms in two regions (ministry)"))
    assert kept == "The market is huge."


def test_partner_and_pilot_claims():
    out, _ = cg.sanitize("We signed partnerships with three universities.", ev(sector="x"))
    assert "[NEEDED: name the partners" in out
    out, _ = cg.sanitize("The pilot results were strong.", ev(sector="x"))
    assert "[NEEDED: results of the pilot" in out
    kept, _ = cg.sanitize("The pilot results were strong.", ev(solution="pilot on 2 farms"))
    assert kept == "The pilot results were strong."


def test_foreign_currency_is_rewritten_and_marked():
    out, issues = cg.sanitize("We are seeking $8,000 to launch.", ev(total_investment=8000))
    assert "$" not in out and f"8,000 TND {M}" in out and issues[0]["rule"] == "currency"
    out, _ = cg.sanitize("We need 8000 USD.", ev(total_investment=8000))
    assert f"8000 TND {M}" in out
    kept, _ = cg.sanitize("We need $8,000.", ev(pricing="$8,000 per year, as quoted by the supplier"))
    assert kept == "We need $8,000."


def test_hype_adjectives_are_removed():
    out, issues = cg.sanitize("A revolutionary, cutting-edge platform for students.", ev(sector="x"))
    assert out == "A platform for students." and issues[0]["rule"] == "hype"


def test_french_text_is_left_alone():
    t = "Les artisans tunisiens peinent à vendre en ligne. Atelier Test propose une place de marché dédiée, avec 7777 clients attendus."
    out, issues = cg.sanitize(t, ev(sector="artisanat"), lang="fr")
    assert out == t and not issues


def test_french_unsupported_claim_gets_french_placeholder():
    out, _ = cg.sanitize("Notre équipe expérimentée connaît le marché.", ev(sector="x"), lang="fr")
    assert out.startswith("[NEEDED: expérience pertinente")


def test_existing_placeholders_survive_and_digits_inside_are_hidden():
    text = "Revenue is 100 000 TND. [NEEDED: how many competitors operate in the 2 regions?]"
    protected, spans = cg.protect(text)
    assert "NEEDED" not in protected and not any(c.isdigit() for c in protected.split("TND.")[1])
    assert cg.restore(protected, spans) == text
    out, issues = cg.sanitize(text, ev(sector="x"))
    assert out == text and not issues
    assert cg.needed_items(out) == ["how many competitors operate in the 2 regions?"]


def test_sanitize_is_idempotent_and_keeps_paragraphs():
    text = "Intro line.\nOur seasoned team is unmatched. Second line."
    once, _ = cg.sanitize(text, ev(sector="x"))
    twice, issues = cg.sanitize(once, ev(sector="x"))
    assert once == twice and not issues and once.count("\n") == 1


def test_evidence_from_final_writer_json():
    facts = '{"answers": {"founders": "Aya, 8 years at a cooperative"}, "derived": {}}'
    e = cg.evidence_from_json(facts, "plan text")
    assert "8 years" in e["founders"] and "plan text" in e["plan"]
    bad = cg.evidence_from_json("not json", "plan text")
    assert "not json" in bad["all"]
