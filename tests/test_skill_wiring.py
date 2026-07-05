from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "skills" / "data-analyze-for-zcl" / "scripts" / "sync-runtime"
SKILL = ROOT / "skills" / "data-analyze-for-zcl" / "SKILL.md"


def test_sync_runtime_mirrors_orchestration():
    text = SYNC.read_text(encoding="utf-8")
    assert "$repo_root/orchestration" in text
    assert "$runtime_dir/orchestration" in text  # bannered too


def test_skill_has_step_7b_host_neutral():
    text = SKILL.read_text(encoding="utf-8")
    assert "7b" in text
    assert "orchestration/dag.md" in text
    # host-neutral: names the three host paths, no hard model binding
    assert "Codex" in text
    assert "skeleton" in text


def test_skill_step_7b_precedes_step_8():
    text = SKILL.read_text(encoding="utf-8")
    assert text.index("7b") < text.index("8. **Custom integrated reports**")
