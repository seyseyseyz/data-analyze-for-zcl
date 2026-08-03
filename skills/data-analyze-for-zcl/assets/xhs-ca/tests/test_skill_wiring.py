from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "skills" / "data-analyze-for-zcl" / "scripts" / "sync-runtime"
SKILL = ROOT / "skills" / "data-analyze-for-zcl" / "SKILL.md"
OPENAI_METADATA = ROOT / "skills" / "data-analyze-for-zcl" / "agents" / "openai.yaml"

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


def test_skill_requests_multi_agent_authorization_before_work_starts():
    text = SKILL.read_text(encoding="utf-8")

    authorization = text.index("Authorize multi-agent final report")
    assert authorization < text.index("**Bootstrap**")
    assert authorization < text.index("**Ask for exports**")
    assert authorization < text.index("**Build**")


def test_skill_reuses_authorization_for_the_same_report():
    text = SKILL.read_text(encoding="utf-8").lower()
    authorization = text[text.index("2. **authorize"):text.index("3. **bootstrap")]

    assert "same report" in authorization
    assert "do not ask again" in authorization
    assert "concurrency limits" in authorization


def test_skill_capacity_pressure_ingests_finished_agents_before_retrying():
    text = " ".join(SKILL.read_text(encoding="utf-8").lower().split())
    capacity = text[
        text.index("if agent dispatch hits a concurrency limit"):
        text.index("3. if step 2 was declined")
    ]

    actions = (
        "inspect the already-dispatched agents",
        "ingest their finished results to release controller capacity",
        "close or recycle completed host agents to release host capacity",
        "retry pending tasks",
    )
    positions = [capacity.index(action) for action in actions]
    assert positions == sorted(positions)
    assert "must not trigger `unsupported`" in capacity
    assert "deterministic fallback" in capacity
    assert "another user authorization prompt" in capacity
    assert "`record-agent-state --status closed` is only a controller-ledger compatibility call" in capacity


def test_skill_manual_mapping_question_includes_decision_evidence():
    text = SKILL.read_text(encoding="utf-8").lower()
    packet = text[
        text.index("that question must provide a complete decision packet"):
        text.index("never ask a bare")
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


def test_skill_does_not_ask_for_optional_shop_name_or_every_mapping_gap():
    text = " ".join(SKILL.read_text(encoding="utf-8").lower().split())
    exports = text[text.index("4. **ask for exports**"):text.index("5. **build**")]
    build = text[text.index("5. **build**"):text.index("6. **task selection")]
    naming = text[text.index("name the report"):text.index("2. drive the quality-first")]
    risk_gate = text[text.index("3. **risk gate"):text.index("4. **`mapping_overrides.yaml`")]

    assert "only when they cannot be inferred and are required to proceed" in exports
    assert "use the neutral `店铺` fallback" in exports
    assert "negotiate unmapped columns with the user" not in build
    assert "request operator judgment only when that gate says it is genuinely required" in build
    assert "neutral fallback" in naming
    assert "without asking" in naming
    assert "ask the operator only when a mapping decision is genuinely required" in risk_gate
    assert "would materially change a metric or report conclusion" in risk_gate


def test_skill_delivers_one_final_html_and_keeps_facts_internal():
    text = SKILL.read_text(encoding="utf-8")
    lowered = text.lower()

    assert "exactly one user-facing single-file html report" in lowered
    assert "facts auto" in lowered
    assert "do not present or link the internal fact layer" in lowered
    assert "exactly two single-file html reports" not in lowered


def test_skill_default_prompt_starts_with_authorization_and_promises_final_only():
    text = OPENAI_METADATA.read_text(encoding="utf-8")

    assert "若本次报告尚未获得多智能体授权" in text
    assert "已授权则直接续跑" in text
    assert "只交付最终单文件 HTML" in text


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


def test_skill_platform_catalog_requires_accepted_binding():
    text = SKILL.read_text(encoding="utf-8")
    assert "platform/xhs_metric_catalog.yaml" in text
    assert "platform/xhs_metric_promotion_review.csv" in text
    assert "source_bindings/xhs_platform_metrics.yaml" in text
    assert "platform/xhs_business_overview_binding_review.csv" in text
    assert "Only an accepted row" in text
    assert "`proposed` means a candidate" in text
    assert "only, never an approved mapping" in text
    assert "payment/refund time basis, PV/UV grain, unit, and aggregation" in text
    assert "review evidence only" in text
    assert "`runtime_mode: observe`" in text
    assert "`runtime_scopes: [agent_context]`" in text
    assert "Candidates remain `mapping_permission: none`" in text
    assert "must not change" in text


def test_skill_distinguishes_metric_ontology_from_import_bindings():
    text = SKILL.read_text(encoding="utf-8")

    assert "references/metrics/registry.yaml" in text
    assert "report-facing metric ontology" in text
    assert "not an import mapping" in text
    assert "observation-only" in text
    assert "fact annotation" in text


@pytest.mark.parametrize(
    "relative_path",
    [
        Path("references/metrics/registry.yaml"),
        Path("xhs_ceramics_analytics/contracts/metrics.py"),
        Path("tests/test_metric_registry.py"),
    ],
)
def test_metric_registry_contract_is_packaged_without_drift(relative_path: Path):
    bundled_path = (
        ROOT / "skills" / "data-analyze-for-zcl" / "assets" / "xhs-ca" / relative_path
    )

    assert bundled_path.read_bytes() == (ROOT / relative_path).read_bytes()


def test_daily_distinct_task_templates_use_non_additive_contract():
    core = (ROOT / "task_templates" / "core_business_diagnosis.md").read_text(
        encoding="utf-8"
    )
    demand = (ROOT / "task_templates" / "demand_funnel_diagnosis.md").read_text(
        encoding="utf-8"
    )

    assert "avg_daily_paid_buyers" in core
    assert "跳过 GMV 桥" in core
    assert "avg_daily_cart_to_pay" in demand
    assert "不把日级去重人数相加" in demand
    assert "total_add_to_cart_users" not in demand
    assert "total_new_wishlist" not in demand
