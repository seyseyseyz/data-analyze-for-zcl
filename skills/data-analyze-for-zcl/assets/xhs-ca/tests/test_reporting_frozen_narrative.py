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
    result_tables = {"trend": [{"month": "2026-07", "gmv": 12.0}]}
    fn.write_frozen(
        path,
        "abc",
        bundle,
        results_hash="results-v1",
        result_tables=result_tables,
    )
    loaded = fn.load_frozen(path)
    assert loaded["facts_hash"] == "abc"
    assert loaded["results_hash"] == "results-v1"
    assert loaded["narrative_bundle_hash"] == fn.payload_hash(bundle)
    assert loaded["narrative_bundle"] == bundle
    assert loaded["result_tables"] == result_tables
    assert loaded["result_tables_hash"] == fn.result_tables_hash(result_tables)
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


def test_load_unreadable_path_raises_valueerror(tmp_path):
    # A directory (not a file) surfaces an OSError on read; the contract is ValueError.
    path = tmp_path / "frozen_dir"
    path.mkdir()
    with pytest.raises(ValueError):
        fn.load_frozen(path)


def test_cache_hit_requires_all_input_hashes_and_versions(tmp_path):
    path = tmp_path / "frozen_narrative.json"
    fn.write_frozen(path, "abc", {"sections": []}, results_hash="results-v1")
    frozen = fn.load_frozen(path)
    assert fn.is_cache_hit(frozen, "abc", results_hash="results-v1") is True
    assert fn.is_cache_hit(frozen, "different", results_hash="results-v1") is False
    assert fn.is_cache_hit(frozen, "abc", results_hash="results-v2") is False
    frozen["schema_version"] = "stale"
    assert fn.is_cache_hit(frozen, "abc", results_hash="results-v1") is False
    assert fn.is_cache_hit(None, "abc", results_hash="results-v1") is False


def test_cache_hit_requires_same_result_tables(tmp_path):
    path = tmp_path / "frozen_narrative.json"
    tables = {"trend": [{"month": "2026-07", "gmv": 12.0}]}
    fn.write_frozen(
        path,
        "abc",
        {"sections": []},
        results_hash="results-v1",
        result_tables=tables,
    )
    frozen = fn.load_frozen(path)

    assert fn.is_cache_hit(
        frozen,
        "abc",
        results_hash="results-v1",
        result_tables=tables,
    ) is True
    assert fn.is_cache_hit(
        frozen,
        "abc",
        results_hash="results-v1",
        result_tables={"trend": [{"month": "2026-07", "gmv": 13.0}]},
    ) is False


def test_cache_rejects_tampered_narrative_bundle(tmp_path):
    path = tmp_path / "frozen_narrative.json"
    fn.write_frozen(
        path,
        "abc",
        {"headline": "可信结论", "sections": []},
        results_hash="results-v1",
    )
    frozen = fn.load_frozen(path)
    frozen["narrative_bundle"]["headline"] = "伪造结论 999 亿"

    assert fn.is_cache_hit(frozen, "abc", results_hash="results-v1") is False


def test_load_rejects_tampered_narrative_bundle(tmp_path):
    path = tmp_path / "frozen_narrative.json"
    fn.write_frozen(
        path,
        "abc",
        {"headline": "可信结论", "sections": []},
        results_hash="results-v1",
    )
    payload = __import__("json").loads(path.read_text(encoding="utf-8"))
    payload["narrative_bundle"]["headline"] = "伪造结论 999 亿"
    path.write_text(__import__("json").dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="narrative_bundle_hash"):
        fn.load_frozen(path)


def test_result_tables_hash_is_order_stable():
    left = {"b": [{"y": 2, "x": 1}], "a": []}
    right = {"a": [], "b": [{"x": 1, "y": 2}]}
    assert fn.result_tables_hash(left) == fn.result_tables_hash(right)


def test_schema_version_tracks_prompts_schemas_controller_and_registry(tmp_path):
    prompt = tmp_path / "orchestration" / "prompts" / "writer.md"
    schema = tmp_path / "orchestration" / "schemas" / "claim.json"
    controller = (
        tmp_path
        / "xhs_ceramics_analytics"
        / "orchestration"
        / "narrative_workflow.py"
    )
    registry = tmp_path / "references" / "metrics" / "registry.yaml"
    for path, body in (
        (prompt, "prompt-v1"),
        (schema, '{"title":"claim"}'),
        (controller, "WORKFLOW_VERSION = 'v1'"),
        (registry, "metrics: {}"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    baseline = fn.narrative_schema_version(tmp_path)
    for path in (prompt, schema, controller, registry):
        original = path.read_text(encoding="utf-8")
        path.write_text(original + "\nchanged", encoding="utf-8")
        assert fn.narrative_schema_version(tmp_path) != baseline
        path.write_text(original, encoding="utf-8")


def test_write_frozen_replaces_existing_payload_without_temp_files(tmp_path):
    path = tmp_path / "frozen_narrative.json"
    fn.write_frozen(
        path,
        "old",
        {"sections": [{"section_id": "old"}]},
        results_hash="results-old",
    )
    fn.write_frozen(
        path,
        "new",
        {"sections": [{"section_id": "new"}]},
        results_hash="results-new",
    )

    assert fn.load_frozen(path)["facts_hash"] == "new"
    assert list(tmp_path.iterdir()) == [path]
