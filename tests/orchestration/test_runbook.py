from pathlib import Path

# The host-facing orchestration contract (dag.md, runbook.md, prompts/, schemas/)
# lives at the repo-root orchestration/; the package orchestration/ holds only code.
ORCH = Path(__file__).resolve().parents[2] / "orchestration"

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


def test_runbook_authorization_is_a_blocking_wait_gate():
    body = _text("runbook.md")
    # After asking you STOP and wait for the reply (it comes in a later turn); you
    # must NOT ask-and-degrade in the same turn — the observed live failure.
    assert "blocking gate" in body
    assert "wait" in body
    # "no answer yet" is a third state, distinct from denied/unsupported.
    assert "no answer yet" in body


def test_runbook_prepare_wires_results_and_facts_inputs():
    body = _text("runbook.md")
    # prepare must consume a domain-sliced results.json plus facts.json — not just
    # --run-dir/--name. Before P1 the drift here made the host hand-fabricate results.
    assert "--results" in body and "--facts" in body
    # And it must say where results.json comes from: the deterministic run/facts step.
    assert "results.json" in body


def test_runbook_authorization_is_mandatory_and_distinct_from_spawning():
    body = _text("runbook.md")
    # Asking for authorization is a required first step and is NOT spawning, so a
    # host whose policy forbids unsolicited spawning must still ask — the user's
    # yes is that explicit request. This prevents "not yet asked" being mislabeled
    # as "cannot spawn" (the observed failure).
    assert "asking is not spawning" in body
    # The reason taxonomy must stay distinct: declined vs no-capability-at-all.
    assert "denied" in body and "unsupported" in body
