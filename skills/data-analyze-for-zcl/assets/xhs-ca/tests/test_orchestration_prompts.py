# tests/test_orchestration_prompts.py
from pathlib import Path

ORCH = Path(__file__).resolve().parents[1] / "orchestration"
PROMPTS = ORCH / "prompts"
ROLES = {"seed", "writer", "synthesizer", "continuity", "patch"}
# Anthropic/OpenAI model ids that must never appear in a host-neutral asset.
BANNED_MODEL_TOKENS = ("claude-", "gpt-", "o1-", "o3-", "sonnet-", "opus-", "haiku-")


def test_dag_and_prompts_present():
    assert (ORCH / "dag.md").is_file()
    assert {p.stem for p in PROMPTS.glob("*.md")} == ROLES


def test_dag_uses_role_tiers_not_model_ids():
    text = (ORCH / "dag.md").read_text(encoding="utf-8")
    assert "judgment/high" in text
    assert "draft/medium" in text
    lower = text.lower()
    for token in BANNED_MODEL_TOKENS:
        assert token not in lower, f"dag.md hard-codes a model id: {token}"


def test_no_prompt_hardcodes_a_model_id():
    for role in ROLES:
        lower = (PROMPTS / f"{role}.md").read_text(encoding="utf-8").lower()
        for token in BANNED_MODEL_TOKENS:
            assert token not in lower, f"{role}.md hard-codes a model id: {token}"


def test_each_prompt_names_its_output_schema():
    expected = {
        "seed": "spine_brief",
        "writer": "section_bundle",
        "synthesizer": "narrative_bundle",
        "continuity": "continuity_edit",
        "patch": "claim",
    }
    for role, schema in expected.items():
        text = (PROMPTS / f"{role}.md").read_text(encoding="utf-8")
        assert schema in text, f"{role}.md does not reference its schema {schema}"


def test_writer_prompt_forbids_digits_in_sentences():
    text = (PROMPTS / "writer.md").read_text(encoding="utf-8")
    assert "{tN}" in text or "{t0}" in text
    assert "数字" in text  # must instruct: no digits, tokens only
