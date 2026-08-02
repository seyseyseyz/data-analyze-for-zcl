from pathlib import Path


# The host-facing orchestration contract (dag.md, runbook.md, prompts/, schemas/)
# lives at the repo-root orchestration/; the package orchestration/ holds only code.
ORCH = Path(__file__).resolve().parents[2] / "orchestration"

# Banned: any host/vendor/model identity leaking into shipped docs.
_BANNED = ("claude", "codex", "gpt", "opus", "sonnet", "anthropic", "openai")
_BANNED_PHRASE = "sequential in-session role-passes"


def _text(name: str) -> str:
    return (ORCH / name).read_text(encoding="utf-8").lower()


def test_dag_doc_is_host_neutral_and_drops_banned_phrase():
    body = _text("dag.md")
    assert _BANNED_PHRASE not in body
    for token in _BANNED:
        assert token not in body, f"dag.md leaks host identity: {token}"


def test_dag_doc_declares_quality_first_roles_and_order():
    body = _text("dag.md")
    stages = (
        "authorization",
        "spine_candidates",
        "spine_adjudication",
        "domain_writer",
        "domain_challenge",
        "domain_adjudication",
        "cross_domain_synthesis",
        "visual_curation",
        "gate",
        "review",
        "targeted_revision",
        "continuity",
        "candidate_html",
        "merchant_final_review",
        "finalized",
        "blocked",
    )
    for stage in stages:
        assert stage in body
    pipeline = next(line for line in body.splitlines() if line.startswith("pipeline:"))
    positions = [pipeline.index(stage) for stage in stages[:-2]]
    assert positions == sorted(positions)


def test_dag_requires_two_spines_and_three_review_lenses():
    body = _text("dag.md")
    assert "2 independent" in body
    for lens in ("evidence_semantics", "merchant_decision", "editorial_visual"):
        assert lens in body


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
    assert "blocking gate" in body
    assert "wait" in body
    assert "no answer yet" in body
    assert "distinct question" in body
    assert "progress update" in body
    assert "asking is not spawning" in body


def test_runbook_reuses_authorization_until_the_report_changes():
    body = _text("runbook.md")
    authorization = body[
        body.index("## authorization"):body.index("## human decision boundary")
    ]

    assert "same report" in authorization
    assert "do not ask again" in authorization
    assert "concurrency limits" in authorization


def test_runbook_treats_agent_capacity_as_retryable_not_degradation():
    body = " ".join(_text("runbook.md").split())
    capacity = body[
        body.index("if dispatch reports a concurrency limit"):
        body.index("## dispatch map")
    ]

    actions = (
        "inspect all already-dispatched agents",
        "ingest finished results",
        "close completed agents",
        "retry pending tasks",
    )
    positions = [capacity.index(action) for action in actions]
    assert positions == sorted(positions)
    assert "must not trigger `unsupported`" in capacity
    assert "deterministic fallback" in capacity
    assert "another user prompt" in capacity


def test_runbook_requires_a_complete_manual_mapping_decision_packet():
    body = _text("runbook.md")
    packet = body[
        body.index("when judgment is required"):body.index("## freeze and prepare")
    ]

    for phrase in (
        "source file and sheet",
        "source header",
        "sample values",
        "candidate canonical fields",
        "official definitions",
        "unit",
        "grain",
        "aggregation",
        "pv/uv",
        "payment/refund-time",
        "mapping method/score/conflict reason",
        "affected tasks",
        "conclusions",
        "recommended option",
        "leave unmapped",
    ):
        assert phrase in packet


def test_runbook_prepare_wires_results_and_facts_inputs():
    body = _text("runbook.md")
    assert "--results" in body and "--facts" in body
    assert "results.json" in body


def test_runbook_documents_quality_blockers_and_targeted_convergence():
    body = _text("runbook.md")
    for blocker in (
        "evidence",
        "semantic",
        "decision",
        "visual",
        "continuity",
        "delivery",
    ):
        assert blocker in body
    assert "at most 2 targeted revision rounds" in body
    assert "convergence" in body
    assert "cost" in body
    for target in ("claim_id", "view_id", "action_id"):
        assert target in body


def test_runbook_documents_one_html_delivery_and_internal_artifacts():
    body = _text("runbook.md")
    assert "one final html" in body
    assert "internal only" in body
    for artifact in ("markdown", "facts", "review"):
        assert artifact in body
    assert "tooltip" in body
    assert "inline field glossary" in body


def test_runbook_places_merchant_review_after_candidate_html():
    body = _text("runbook.md")
    assert body.index("candidate html") < body.index("merchant final review")
    assert "cannot edit" in body


def test_runbook_documents_no_per_domain_cap_and_claim_anchor():
    body = _text("runbook.md")
    assert "≤2 tables" not in body
    assert "≤1 chart" not in body
    assert "no per-domain cap" in body
    assert "supports_claim" in body


def test_review_docs_stay_host_neutral():
    for name in ("dag.md", "runbook.md"):
        body = _text(name)
        for token in _BANNED:
            assert token not in body, f"{name} leaks host identity: {token}"
