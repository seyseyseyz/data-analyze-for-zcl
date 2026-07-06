from pathlib import Path

ORCH = Path(__file__).resolve().parents[2] / "xhs_ceramics_analytics" / "orchestration"

# Banned: any host/vendor/model identity leaking into shipped docs.
_BANNED = ("claude", "codex", "gpt", "opus", "sonnet", "anthropic", "openai")
# Banned phrase that previously implied a no-subagent host degrades to in-session role-passes.
_BANNED_PHRASE = "sequential in-session role-passes"


def _text(name: str) -> str:
    return (ORCH / name).read_text(encoding="utf-8").lower()


def test_dag_doc_is_host_neutral_and_drops_banned_phrase():
    body = _text("dag.md")
    assert _BANNED_PHRASE not in body
    for token in _BANNED:
        assert token not in body, f"dag.md leaks host identity: {token}"


def test_dag_doc_declares_all_stages():
    body = _text("dag.md")
    for stage in ("seed", "fan", "synth", "gate", "patch", "continuity", "finalized", "blocked"):
        assert stage in body


def test_runbook_is_host_neutral():
    body = _text("runbook.md")
    for token in _BANNED:
        assert token not in body, f"runbook leaks host identity: {token}"


def test_runbook_declares_the_control_loop():
    body = _text("runbook.md")
    for phrase in ("prepare", "authorize", "ingest", "advance", "status --json", "finalize-deterministic"):
        assert phrase in body


def test_runbook_declares_fallback_on_blocked_or_denied():
    body = _text("runbook.md")
    assert "blocked" in body and "denied" in body
    assert "deterministic" in body
