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


def _iter_refs(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                yield value
            else:
                yield from _iter_refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_refs(item)


def test_every_schema_declares_id_matching_its_filename():
    # Relative cross-file $refs (e.g. "claim.json") only resolve deterministically when
    # each schema sets a $id as its base URI; without it resolution depends on the
    # retrieval URI. Pin the $id to the filename so refs resolve the same everywhere.
    for name in ROSTER:
        assert _load(name).get("$id") == f"{name}.json", name


def test_cross_file_refs_resolve_to_roster_schemas():
    roster_files = {f"{name}.json" for name in ROSTER}
    for name in ROSTER:
        for ref in _iter_refs(_load(name)):
            if ref.startswith("#"):  # intra-document pointer, always local
                continue
            base = ref.split("#", 1)[0]
            assert base in roster_files, f"{name}: unresolvable $ref {ref}"
