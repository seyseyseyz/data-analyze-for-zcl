from pathlib import Path


ORCH = Path(__file__).resolve().parents[1] / "orchestration"
PROMPTS = ORCH / "prompts"
ROLE_SCHEMAS = {
    "seed": "spine_candidate",
    "spine_adjudicator": "spine_adjudication",
    "writer": "section_bundle",
    "challenger": "challenge_report",
    "domain_adjudicator": "domain_adjudication",
    "synthesizer": "synthesis_output",
    "visual_curator": "visual_curation",
    "reviewer": "review_verdict",
    "continuity": "continuity_edit",
    "merchant_final_review": "merchant_final_review",
    "patch": "targeted_revision",
}
# Anthropic/OpenAI model ids that must never appear in a host-neutral asset.
BANNED_MODEL_TOKENS = ("claude-", "gpt-", "o1-", "o3-", "sonnet-", "opus-", "haiku-")


def _prompt(role: str) -> str:
    return (PROMPTS / f"{role}.md").read_text(encoding="utf-8")


def test_dag_and_complete_quality_first_prompt_roster_present():
    assert (ORCH / "dag.md").is_file()
    assert {path.stem for path in PROMPTS.glob("*.md")} == set(ROLE_SCHEMAS)


def test_dag_uses_role_tiers_not_model_ids():
    text = (ORCH / "dag.md").read_text(encoding="utf-8")
    assert "judgment/high" in text
    assert "draft/medium" in text
    lower = text.lower()
    for token in BANNED_MODEL_TOKENS:
        assert token not in lower, f"dag.md hard-codes a model id: {token}"


def test_no_prompt_hardcodes_a_model_id():
    for role in ROLE_SCHEMAS:
        lower = _prompt(role).lower()
        for token in BANNED_MODEL_TOKENS:
            assert token not in lower, f"{role}.md hard-codes a model id: {token}"


def test_each_prompt_names_its_output_schema():
    for role, schema in ROLE_SCHEMAS.items():
        assert schema in _prompt(role), f"{role}.md does not reference its schema {schema}"


def test_numeric_authoring_prompts_enforce_tokens_and_registry_ownership():
    numeric_roles = {
        "seed",
        "writer",
        "domain_adjudicator",
        "synthesizer",
        "visual_curator",
        "continuity",
        "patch",
    }
    for role in numeric_roles:
        text = _prompt(role)
        assert "{tN}" in text or "number_token" in text, role
        assert "registry" in text.lower() or "注册表" in text, role
        for field in ("名称", "单位", "口径", "周期", "aggregation"):
            assert field in text, f"{role}.md misses deterministic ownership of {field}"


def test_synthesizer_emits_runtime_first_screen_without_numeric_headline_or_actions():
    text = _prompt("synthesizer")
    for field in ("spine[]", "panel[]", "actions[]"):
        assert field in text
    assert "headline_number_tokens" not in text
    assert "headline 和 actions" in text and "不得含业务数字" in text


def test_seed_and_adjudicator_require_two_independent_spine_candidates():
    seed = _prompt("seed")
    adjudicator = _prompt("spine_adjudicator")
    assert "独立" in seed and "candidate_id" in seed
    assert '"spine_brief"' in seed
    assert "两个" in adjudicator and "独立" in adjudicator
    assert '"spine_brief"' in adjudicator


def test_domain_quality_roles_are_adversarial_and_adjudicated():
    challenger = _prompt("challenger")
    adjudicator = _prompt("domain_adjudicator")
    assert "默认不通过" in challenger
    assert "blocker" in challenger.lower()
    assert "直接输出" in adjudicator and "section_bundle" in adjudicator
    assert "逐条" in adjudicator and "challenge" in adjudicator.lower()


def test_reviewer_prompt_names_the_three_required_lenses():
    text = _prompt("reviewer")
    for lens in ("evidence_semantics", "merchant_decision", "editorial_visual"):
        assert lens in text
    assert "只能" in text and "一个 lens" in text


def test_visual_prompt_emits_the_runtime_view_spec_shape():
    text = _prompt("visual_curator")
    for field in (
        "supports_claim",
        "source.table",
        "columns",
        "column_labels",
        "rows",
        "chart",
    ):
        assert field in text
    assert "supports_claim_id" not in text


def test_visual_prompt_preserves_high_value_diagnostic_breadth():
    text = _prompt("visual_curator")
    for topic in ("搜索词", "笔记", "SKU"):
        assert topic in text
    assert "经营诊断明细" in text
    assert "不得删除" in text


def test_merchant_final_review_reads_candidate_html_and_is_not_an_editor():
    text = _prompt("merchant_final_review")
    assert "candidate HTML" in text
    assert "不得直接改写" in text
    assert "quality blocker" in text.lower()


def test_prompts_name_the_runtime_ingest_envelopes():
    assert '"sections"' in _prompt("visual_curator")
    assert '"curated_views"' in _prompt("visual_curator")
    assert '"visual_coverage"' in _prompt("visual_curator")
    assert "decision-critical" in _prompt("visual_curator")
    assert '"edits"' in _prompt("continuity")
    merchant = _prompt("merchant_final_review")
    assert '"issues"' in merchant
    assert '"verdict":"pass|revise"' in merchant
    assert "pass|revise|block" not in merchant


def test_patch_prompt_is_targeted_by_claim_view_or_action():
    text = _prompt("patch")
    for target in ("claim", "view", "action"):
        assert target in text
    assert "整份" in text and "不得" in text
