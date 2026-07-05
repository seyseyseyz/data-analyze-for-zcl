import pytest

from xhs_ceramics_analytics.reporting import frozen_narrative as fn


def test_versions_are_stable_16hex():
    assert fn.narrative_schema_version() == fn.narrative_schema_version()
    assert fn.renderer_version() == fn.renderer_version()
    assert len(fn.narrative_schema_version()) == 16
    assert len(fn.renderer_version()) == 16


def test_write_then_load_roundtrips(tmp_path):
    path = tmp_path / "frozen_narrative.json"
    bundle = {"facts_hash": "abc", "sections": []}
    fn.write_frozen(path, "abc", bundle)
    loaded = fn.load_frozen(path)
    assert loaded["facts_hash"] == "abc"
    assert loaded["narrative_bundle"] == bundle
    assert loaded["schema_version"] == fn.narrative_schema_version()
    assert loaded["renderer_version"] == fn.renderer_version()


def test_load_absent_returns_none(tmp_path):
    assert fn.load_frozen(tmp_path / "nope.json") is None


def test_load_malformed_raises(tmp_path):
    path = tmp_path / "frozen_narrative.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        fn.load_frozen(path)


def test_load_missing_keys_raises(tmp_path):
    path = tmp_path / "frozen_narrative.json"
    path.write_text('{"facts_hash": "x"}', encoding="utf-8")
    with pytest.raises(ValueError):
        fn.load_frozen(path)


def test_cache_hit_requires_all_three_keys(tmp_path):
    path = tmp_path / "frozen_narrative.json"
    fn.write_frozen(path, "abc", {"sections": []})
    frozen = fn.load_frozen(path)
    assert fn.is_cache_hit(frozen, "abc") is True
    assert fn.is_cache_hit(frozen, "different") is False
    frozen["schema_version"] = "stale"
    assert fn.is_cache_hit(frozen, "abc") is False
    assert fn.is_cache_hit(None, "abc") is False
