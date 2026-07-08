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
    for stage in ("seed", "fan", "synth", "gate", "review", "patch", "continuity", "finalized", "blocked"):
        assert stage in body


def test_dag_doc_places_review_after_gate_before_continuity():
    # The curated-visuals review stage runs after the deterministic gate has locked
    # every displayed number and before continuity smooths the prose.
    body = _text("dag.md")
    assert body.index("gate") < body.index("review") < body.index("continuity")


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
    # The ask must be a distinct question, never smuggled into a progress update
    # then run past — the exact self-rationalization the live host admitted to.
    assert "distinct question" in body
    assert "progress update" in body


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


def test_runbook_documents_the_review_loop():
    body = _text("runbook.md")
    # after the gate, spawn three reviewers per domain, one per adversarial lens.
    assert "review" in body
    assert "3 reviewers per domain" in body
    for lens in ("价值", "可读性", "支撑"):
        assert lens in body, f"runbook must name the {lens!r} lens"
    # adversarial default: reject trivial / hard-to-read / unsupported views.
    assert "defaults to reject" in body
    # every curated view must cite a real supporting claim (anti-dump).
    assert "supports_claim" in body


def test_runbook_documents_review_tally_precedence():
    body = _text("runbook.md")
    # strict precedence — every verdict combination maps to exactly one outcome.
    assert "drop ≥ 2 → drop" in body
    assert "keep ≥ 2 → keep" in body
    # no majority → bounded patch, then the view is dropped (never blocks delivery).
    assert "patch ≤2 rounds, then drop" in body


def test_runbook_documents_no_per_domain_cap():
    body = _text("runbook.md")
    # No per-domain view cap: anti-dump is enforced per view (real supports_claim +
    # gate rules 1-3), not by a table/chart count. The runbook must not resurrect a
    # numeric cap.
    assert "≤2 tables" not in body
    assert "≤1 chart" not in body
    assert "no per-domain cap" in body
    # per-view anti-dump anchor still stated.
    assert "supports_claim" in body


def test_review_docs_stay_host_neutral():
    # Re-assert neutrality now that both docs carry the curated-visuals review flow.
    for name in ("dag.md", "runbook.md"):
        body = _text(name)
        for token in _BANNED:
            assert token not in body, f"{name} leaks host identity: {token}"
