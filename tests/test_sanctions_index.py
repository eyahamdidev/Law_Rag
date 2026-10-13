import pytest

from fraud_detection.entity_intelligence.public_lists import load_ofac
from fraud_detection.entity_intelligence.sanctions import SanctionsIndex
from fraud_detection.paths import RAW
from fraud_detection.schema import SanctionsEntry


def test_exact_and_suffix_matches_score_one():
    index = SanctionsIndex([SanctionsEntry(name="Bad Actor SARL", list_name="OFAC_SDN")])
    found = index.match_scored("Bad Actor")
    assert found is not None
    assert found[1] == 1.0
    assert index.available is True


def test_empty_index_is_not_available():
    index = SanctionsIndex([])
    assert index.available is False
    assert index.match_scored("AEROCARIBBEAN AIRLINES") is None


def test_short_names_do_not_fuzzy_match():
    index = SanctionsIndex([SanctionsEntry(name="NORTH WIND TRADING", list_name="OFAC_SDN")])
    assert index.match("NORTH") is None


def test_ofac_file_matches_aerocaribbean():
    sdn = RAW / "sanctions" / "ofac_sdn.csv"
    alt = RAW / "sanctions" / "ofac_alt.csv"
    if not sdn.exists():
        pytest.skip("OFAC file was not downloaded")
    index = SanctionsIndex(load_ofac(sdn, alt if alt.exists() else None))
    exact = index.match_scored("AEROCARIBBEAN AIRLINES")
    alias = index.match_scored("AERO-CARIBBEAN")
    assert exact is not None
    assert exact[0].list_name == "OFAC_SDN"
    assert exact[1] == 1.0
    assert alias is not None
    assert index.match("this-name-is-not-on-the-list-zz") is None
