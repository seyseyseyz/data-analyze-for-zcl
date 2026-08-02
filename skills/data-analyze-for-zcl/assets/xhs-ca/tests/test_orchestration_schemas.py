import json
from dataclasses import fields
from pathlib import Path

from xhs_ceramics_analytics.reporting.view_spec import (
    TEMPLATES,
    ViewSpec,
    validate_view_spec,
)


SCHEMA_DIR = Path(__file__).resolve().parents[1] / "orchestration" / "schemas"
ROSTER = {
    "action_card",
    "challenge_report",
    "claim",
    "continuity_edit",
    "decision_brief",
    "domain_adjudication",
    "fact",
    "gate_report",
    "merchant_final_review",
    "narrative_bundle",
    "number_token",
    "review_verdict",
    "section_bundle",
    "spine_adjudication",
    "spine_brief",
    "spine_candidate",
    "synthesis_output",
    "targeted_revision",
    "view_spec",
    "visual_curation",
    "visual_coverage",
}
AGENT_OUTPUTS = ROSTER - {"fact", "gate_report", "number_token"}


def _load(name):
    return json.loads((SCHEMA_DIR / f"{name}.json").read_text(encoding="utf-8"))


def test_all_schemas_present():
    on_disk = {path.stem for path in SCHEMA_DIR.glob("*.json")}
    assert on_disk == ROSTER


def test_every_schema_is_wellformed_and_closed_at_root():
    for name in ROSTER:
        schema = _load(name)
        assert schema.get("$schema", "").startswith("https://json-schema.org/")
        assert schema.get("type") in {"object", "array"}
        assert "title" in schema
        if schema["type"] == "object":
            assert schema.get("additionalProperties") is False, name


def test_nested_object_shapes_are_closed_or_explicit_maps():
    def visit(node, path="$"):
        if isinstance(node, dict):
            node_type = node.get("type")
            is_object = node_type == "object" or (
                isinstance(node_type, list) and "object" in node_type
            )
            if is_object and "properties" in node:
                assert node.get("additionalProperties") is False, path
            for key, value in node.items():
                visit(value, f"{path}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                visit(value, f"{path}/{index}")

    for name in ROSTER:
        visit(_load(name), name)


def test_claim_schema_names_gate_fields_and_reuses_number_token():
    props = _load("claim")["properties"]
    for field in (
        "claim_id",
        "claim_kind",
        "sentence",
        "number_tokens",
        "entity_refs",
        "confidence",
        "causal_link",
    ):
        assert field in props
    assert props["claim_kind"]["enum"] == ["measurement", "mechanism", "sizing"]
    assert props["confidence"]["enum"] == ["强", "中", "弱"]
    assert props["number_tokens"]["items"]["$ref"] == "number_token.json"


def test_number_token_binds_fact_without_agent_owned_metric_metadata():
    schema = _load("number_token")
    props = schema["properties"]
    assert set(props) == {"token_id", "fact_id", "expected_metric_key", "direction"}
    assert {"token_id", "fact_id", "expected_metric_key"} <= set(schema["required"])


def test_narrative_bundle_schema_names_gate_fields():
    props = _load("narrative_bundle")["properties"]
    for field in (
        "facts_hash",
        "headline",
        "first_screen",
        "action_cards",
        "spine_final",
        "sections",
        "cannot_say",
    ):
        assert field in props
    assert "headline_number_tokens" not in props
    first_screen = props["first_screen"]
    assert first_screen["required"] == ["spine", "panel", "actions"]
    assert first_screen["properties"]["spine"]["items"]["$ref"] == "claim.json"
    assert first_screen["properties"]["panel"]["items"]["$ref"] == "claim.json"
    assert first_screen["properties"]["actions"]["items"]["type"] == "string"
    assert "mechanism" in props


def test_quality_stage_schemas_match_runtime_ingest_envelopes():
    candidate = _load("spine_candidate")
    assert candidate["required"] == ["candidate_id", "spine_brief"]
    assert candidate["properties"]["spine_brief"]["$ref"] == "spine_brief.json"

    adjudication = _load("spine_adjudication")
    assert "spine_brief" in adjudication["required"]
    assert "resolved_spine" not in adjudication["properties"]

    challenge = _load("challenge_report")
    assert challenge["required"] == ["section_id", "issues", "recommendation"]

    domain = _load("domain_adjudication")
    assert "section_id" in domain["required"]
    assert "resolved_section" not in domain["properties"]

    visual = _load("visual_curation")
    assert visual["required"] == ["sections"]
    section_patch = visual["properties"]["sections"]["items"]
    assert section_patch["required"] == [
        "section_id",
        "curated_views",
        "visual_coverage",
    ]
    assert section_patch["properties"]["visual_coverage"]["items"]["$ref"] == (
        "visual_coverage.json"
    )

    continuity = _load("continuity_edit")
    assert continuity["type"] == "object"
    assert continuity["required"] == ["edits"]

    merchant = _load("merchant_final_review")
    assert merchant["required"] == ["verdict", "issues"]
    assert merchant["properties"]["verdict"]["enum"] == ["pass", "revise"]
    assert "issue_id" in merchant["properties"]["issues"]["items"]["required"]
    assert "findings" not in merchant["properties"]

    synthesis = _load("synthesis_output")
    assert synthesis["required"] == [
        "headline",
        "first_screen",
        "action_cards",
        "mechanism",
        "cannot_say",
        "spine_final",
    ]


def test_gate_report_schema_enumerates_status():
    props = _load("gate_report")["properties"]
    assert props["status"]["enum"] == ["PASS", "FAIL"]
    for field in ("hard_failures", "warnings", "capped_claims"):
        assert field in props


def test_fact_schema_matches_facts_json_and_registry_owned_fields():
    schema = _load("fact")
    props = schema["properties"]
    for field in (
        "fact_id",
        "rendered",
        "metric_key",
        "direction",
        "pool_id",
        "metric_id",
        "entity_type",
        "evidence_strength",
        "descriptive_reliability",
        "assumption",
    ):
        assert field in props
    assert "metric_id" in schema["required"]
    assert props["metric_id"]["type"] == ["string", "null"]
    for field in ("display_name", "aggregation", "grain", "formula", "mapping_error"):
        assert field in props
        assert props[field]["type"] == ["string", "null"]


def test_quality_role_schemas_are_strict_and_targeted():
    challenge = _load("challenge_report")["properties"]
    assert challenge["recommendation"]["enum"] == ["accept", "revise"]

    review = _load("review_verdict")["properties"]
    assert review["lens"]["enum"] == [
        "evidence_semantics",
        "merchant_decision",
        "editorial_visual",
    ]

    targeted = _load("targeted_revision")["properties"]
    assert targeted["target_type"]["enum"] == ["claim", "view", "action"]
    assert targeted["round"]["maximum"] == 2

    merchant = _load("merchant_final_review")["properties"]
    assert merchant["verdict"]["enum"] == ["pass", "revise"]
    assert "issues" in merchant


def test_view_spec_matches_the_deterministic_runtime_contract():
    view = _load("view_spec")
    props = view["properties"]
    for field in (
        "view_id",
        "section_id",
        "supports_claim",
        "template",
        "source",
        "columns",
        "column_labels",
        "rows",
        "chart",
        "title",
        "how_to_read",
        "why_it_matters",
    ):
        assert field in props
    assert "supports_claim_id" not in props
    assert "table_id" not in props
    assert "column_ids" not in props

    source = props["source"]
    assert source["additionalProperties"] is False
    assert source["required"] == ["table"]
    assert set(source["properties"]) == {"task_id", "table"}

    labels = props["column_labels"]
    assert labels["type"] == "object"
    assert labels["additionalProperties"] == {"type": "string", "minLength": 1}


def test_visual_coverage_schema_requires_closed_retained_or_omitted_records():
    coverage = _load("visual_coverage")

    assert coverage["required"] == [
        "claim_id",
        "status",
        "view_ids",
        "reason_code",
        "reason",
    ]
    assert coverage["properties"]["status"]["enum"] == ["retained", "omitted"]
    assert "dropped_by_review" in coverage["properties"]["reason_code"]["enum"]


def test_view_schema_emits_a_directly_consumable_runtime_spec():
    props = _load("view_spec")["properties"]
    runtime_fields = {field.name for field in fields(ViewSpec)}
    assert set(props) <= runtime_fields
    assert set(props["template"]["enum"]) == set(TEMPLATES)

    spec = {
        "view_id": "core.bridge",
        "section_id": "core",
        "supports_claim": "claim.core",
        "template": "comparison_table",
        "source": {"task_id": "core_business", "table": "growth_bridge"},
        "columns": ["component", "delta_gmv"],
        "rows": {"sort_by": "delta_gmv", "order": "desc", "top_n": 2},
        "chart": None,
        "title": "增长拆解",
        "how_to_read": "看主要拉动项",
        "why_it_matters": "锁定优先改善方向",
    }
    tables = {
        "growth_bridge": [
            {"component": "转化", "delta_gmv": 100},
            {"component": "流量", "delta_gmv": 80},
        ]
    }
    assert validate_view_spec(spec, tables) == []


def test_agent_outputs_do_not_own_metric_semantics():
    banned_properties = {
        "metric_name",
        "display_name",
        "unit",
        "caliber",
        "period",
        "aggregation",
        "formula",
        "grain",
        "denominator",
    }

    def property_names(node):
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                yield from properties
            for value in node.values():
                yield from property_names(value)
        elif isinstance(node, list):
            for value in node:
                yield from property_names(value)

    for name in AGENT_OUTPUTS:
        leaked = banned_properties & set(property_names(_load(name)))
        assert not leaked, f"{name} lets an agent author registry semantics: {sorted(leaked)}"


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
    for name in ROSTER:
        assert _load(name).get("$id") == f"{name}.json", name


def test_cross_file_refs_resolve_to_roster_schemas():
    roster_files = {f"{name}.json" for name in ROSTER}
    for name in ROSTER:
        for ref in _iter_refs(_load(name)):
            if ref.startswith("#"):
                continue
            base = ref.split("#", 1)[0]
            assert base in roster_files, f"{name}: unresolvable $ref {ref}"
