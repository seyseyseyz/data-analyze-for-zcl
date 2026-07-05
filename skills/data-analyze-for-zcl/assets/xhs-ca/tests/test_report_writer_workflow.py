# tests/test_report_writer_workflow.py
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[1] / ".xhs-ceramics-analytics" / "report_writer_workflow.js"
BANNED_MODEL_TOKENS = ("claude-", "gpt-", "o1-", "o3-", "sonnet-", "opus-", "haiku-")

# The accelerator lives in the (gitignored) runtime dir at repo root; absent in the mirror copy.
pytestmark = pytest.mark.skipif(
    not JS.is_file(),
    reason="report_writer_workflow.js is only present in the source checkout",
)


def test_workflow_file_exists():
    assert JS.is_file()


def test_exports_meta_and_drives_seed_fan_synthesizer():
    text = JS.read_text(encoding="utf-8")
    assert "export const meta" in text
    assert "report-writer" in text
    # seed → parallel fan-out of writers → synthesizer. Not a per-item pipeline(): the seed and
    # synthesizer run once each, only the writers fan out, so parallel()+agent() is the right shape.
    assert "parallel(" in text
    assert "agent(" in text


def test_reads_neutral_prompts_not_a_second_contract():
    text = JS.read_text(encoding="utf-8")
    assert "orchestration/prompts/seed.md" in text
    assert "orchestration/prompts/writer.md" in text
    assert "orchestration/prompts/synthesizer.md" in text


def test_uses_effort_tiers_not_model_ids():
    text = JS.read_text(encoding="utf-8")
    assert "effort" in text
    lower = text.lower()
    for token in BANNED_MODEL_TOKENS:
        assert token not in lower, f"workflow hard-codes a model id: {token}"
