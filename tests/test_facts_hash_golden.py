# tests/test_facts_hash_golden.py
"""facts_hash is stable, excludes raw floats, and reacts to rendered/structure."""
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength
from xhs_ceramics_analytics.reporting.facts_export import (
    Fact,
    FactBook,
    canonical_payload,
    facts_hash,
    factbook_to_json,
)


def _book(value: float, rendered: str) -> FactBook:
    fact = Fact(
        fact_id="core.delta_gmv",
        value=value,
        rendered=rendered,
        metric_key="delta_gmv",
        unit="cny",
        evidence_strength=EvidenceStrength.WEAK,
        descriptive_reliability=DescriptiveReliability.HIGH,
    )
    return FactBook(
        facts={"core.delta_gmv": fact},
        entity_registry=["兴安岭之夜"],
        absent_link_registry=["note→order"],
    )


def test_hash_is_deterministic():
    assert facts_hash(_book(-29000.0, "-¥2.9万")) == facts_hash(_book(-29000.0, "-¥2.9万"))


def test_raw_float_noise_does_not_change_hash():
    # Same rendered string, float jittered → identical hash (the whole point).
    assert facts_hash(_book(-29000.0, "-¥2.9万")) == facts_hash(_book(-29000.0001, "-¥2.9万"))


def test_changed_rendered_string_changes_hash():
    assert facts_hash(_book(-29000.0, "-¥2.9万")) != facts_hash(_book(-29000.0, "-¥3.0万"))


def test_value_excluded_from_canonical_payload():
    payload = canonical_payload(_book(-29000.0, "-¥2.9万"))
    text = repr(payload)
    assert "29000" not in text  # raw float never appears
    assert "-¥2.9万" in text


def test_json_roundtrip_is_sorted_and_includes_value():
    js = factbook_to_json(_book(-29000.0, "-¥2.9万"))
    assert '"value"' in js  # full JSON keeps raw value for computation
    # sorted keys → deterministic ordering
    assert factbook_to_json(_book(-29000.0, "-¥2.9万")) == js


def test_golden_hash_pinned():
    # GOLDEN: run once, copy the printed hash below, and commit it. This is the
    # merge gate — a canonicalization change that moves the hash must be intentional.
    import xhs_ceramics_analytics.reporting.facts_export as fx
    got = facts_hash(_book(-29000.0, "-¥2.9万"))
    print("GOLDEN facts_hash:", got)
    assert got == fx._GOLDEN_TEST_HASH
