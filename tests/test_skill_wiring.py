from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "skills" / "data-analyze-for-zcl" / "scripts" / "sync-runtime"
SKILL = ROOT / "skills" / "data-analyze-for-zcl" / "SKILL.md"

# The skill's own scripts/SKILL.md live outside the mirrored runtime; skip in the mirror copy.
pytestmark = pytest.mark.skipif(
    not SYNC.exists() or not SKILL.exists(),
    reason="skill wiring files are only present in the source checkout",
)


def test_sync_runtime_mirrors_orchestration():
    text = SYNC.read_text(encoding="utf-8")
    assert "$repo_root/orchestration" in text
    assert "$runtime_dir/orchestration" in text  # bannered too


def test_skill_has_step_7b_host_neutral():
    text = SKILL.read_text(encoding="utf-8")
    assert "7b" in text
    assert "orchestration/runbook.md" in text
    # host-neutral: no hard model/vendor binding, always falls back to a
    # deterministic skeleton report if the narrative workflow can't finish.
    assert "finalize-deterministic" in text
    assert "确定性骨架版" in text
    banned = ("claude", "codex", "gpt", "opus", "sonnet", "anthropic", "openai")
    lowered = text.lower()
    for term in banned:
        assert term not in lowered, f"SKILL.md must stay host-neutral, found {term!r}"


def test_skill_step_7b_precedes_step_8():
    text = SKILL.read_text(encoding="utf-8")
    assert text.index("7b") < text.index("8. **Custom integrated reports**")


def test_skill_7b_authorization_is_mandatory_and_distinct_from_spawning():
    text = SKILL.read_text(encoding="utf-8")
    # 7b must make asking for authorization a required, unconditional step and
    # spell out that asking is not spawning — so a host that forbids unsolicited
    # spawning still asks instead of silently degrading to the skeleton.
    assert "asking is not spawning" in text


def test_skill_notes_curated_deterministic_visuals():
    text = SKILL.read_text(encoding="utf-8")
    lowered = text.lower()
    # The narrative report now carries agent-curated deterministic tables/charts:
    # the agent curates the view, a deterministic engine supplies every number.
    assert "curate" in lowered
    assert "deterministic" in lowered
    # numbers are deterministic; the agent only chooses the view, never the values.
    assert "table" in lowered and "chart" in lowered
    # stays host-neutral even with the new note.
    banned = ("claude", "codex", "gpt", "opus", "sonnet", "anthropic", "openai")
    for term in banned:
        assert term not in lowered, f"SKILL.md must stay host-neutral, found {term!r}"
