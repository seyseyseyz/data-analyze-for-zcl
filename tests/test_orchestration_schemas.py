# tests/test_orchestration_schemas.py
import json
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "orchestration" / "schemas"
ROSTER = {
    "fact", "spine_brief", "claim", "section_bundle",
    "narrative_bundle", "gate_report", "continuity_edit",
}


def _load(name):
    return json.loads((SCHEMA_DIR / f"{name}.json").read_text(encoding="utf-8"))


def test_all_schemas_present():
    on_disk = {p.stem for p in SCHEMA_DIR.glob("*.json")}
    assert on_disk == ROSTER


def test_every_schema_is_wellformed_object_schema():
    for name in ROSTER:
        schema = _load(name)
        assert schema.get("$schema", "").startswith("https://json-schema.org/")
        assert schema.get("type") in {"object", "array"}
        assert "title" in schema


def test_claim_schema_names_gate_fields():
    props = _load("claim")["properties"]
    for field in ("claim_id", "claim_kind", "sentence", "number_tokens",
                  "entity_refs", "confidence", "causal_link"):
        assert field in props
    assert props["claim_kind"]["enum"] == ["measurement", "mechanism", "sizing"]
    assert props["confidence"]["enum"] == ["强", "中", "弱"]
    token = props["number_tokens"]["items"]["properties"]
    for field in ("token_id", "fact_id", "expected_metric_key", "direction"):
        assert field in token


def test_narrative_bundle_schema_names_gate_fields():
    props = _load("narrative_bundle")["properties"]
    for field in ("facts_hash", "headline", "first_screen", "spine_final",
                  "sections", "cannot_say"):
        assert field in props


def test_gate_report_schema_enumerates_status():
    props = _load("gate_report")["properties"]
    assert props["status"]["enum"] == ["PASS", "FAIL"]
    for field in ("hard_failures", "warnings", "capped_claims"):
        assert field in props


def test_fact_schema_matches_facts_json_fields():
    props = _load("fact")["properties"]
    for field in ("fact_id", "rendered", "metric_key", "direction", "pool_id",
                  "entity_type", "evidence_strength", "descriptive_reliability", "assumption"):
        assert field in props
