"""Chat questionnaire v14: wider coverage, a founders answer must name people, no false legal-form / stage guesses."""

from app import interview as iv


def _run(answers_in_order, lang="en"):
    st, out = None, None
    for msg in answers_in_order:
        out = iv.turn(lang=lang, profile=None, state=st, message=msg)
        st = out["state"]
    return out


def test_chat_now_asks_for_team_background_and_competitors():
    assert "key_skills" in iv.CORE and "competitors" in iv.CORE
    assert {"channels", "production_means", "suppliers", "capex_items"} <= set(iv.EXTRA)
    for qid in ("key_skills", "competitors", "channels", "production_means", "suppliers", "capex_items"):
        assert set(iv.ASK[qid]) == {"en", "fr", "ar"}


def test_founders_answer_equal_to_project_name_is_refused():
    st = iv.new_state()
    st["answers"] = {"project_name": "Polaris"}
    st["current"] = "founders"
    st["greeted"] = True
    out = iv.turn(lang="en", profile=None, state=st, message="Polaris", action=None)
    assert "founders" not in out["answers"] and out["asking"] == "founders"
    assert "name of the project" in out["messages"][0]
    out = iv.turn(lang="en", profile=None, state=out["state"], message="Aya Ben Salah - CEO")
    assert out["answers"]["founders"] == "Aya Ben Salah - CEO"
    # a role written after the project name does not make it a person either
    st2 = iv.new_state()
    st2.update(answers={"project_name": "Polaris"}, current="founders", greeted=True)
    out = iv.turn(lang="en", profile=None, state=st2, message="Polaris - CEO")
    assert "founders" not in out["answers"]


def test_french_possessive_sa_is_not_a_legal_form():
    assert iv._extras("Nous vendons sa production en ligne", "solution", {}) == {}
    assert iv._extras("We will register as a SARL next month", "solution", {}) == {"legal_form": "SARL"}


def test_stage_is_not_guessed_from_ordinary_words():
    assert "stage" not in iv._extras("We sell a new product and start with farms in Sfax", "solution", {})
    assert iv._extras("It is still an idea for now", "solution", {}) == {"stage": "idea"}


def test_free_text_is_tidied_not_rewritten():
    assert iv._tidy("  We  sell   olives , daily .") == "We sell olives, daily."


def test_unreadable_bank_entries_are_skipped_not_fatal(monkeypatch):
    class Odd:
        type = "table"

    monkeypatch.setitem(iv.BANK_BY_ID, "capex_items", Odd())
    st = {"phase": "extra", "skipped": []}
    assert "capex_items" not in iv._order(st, {})
