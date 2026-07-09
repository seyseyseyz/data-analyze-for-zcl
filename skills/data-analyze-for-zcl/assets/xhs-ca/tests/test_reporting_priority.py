"""Tests for the cross-module 「最弱环节 × 最高杠杆」 priority table (D2)."""
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength
from xhs_ceramics_analytics.reporting.priority import build_priority_table


def _finding(
    title: str,
    evidence: EvidenceStrength,
    *,
    action: str | None = "先动这里",
    reliability: DescriptiveReliability | None = DescriptiveReliability.HIGH,
) -> Finding:
    return Finding(
        title=title,
        conclusion=f"{title} 的结论",
        evidence_strength=evidence,
        recommended_action=action,
        descriptive_reliability=reliability,
    )


def _result(task_id: str, title: str, findings: list[Finding]) -> AnalysisResult:
    return AnalysisResult(task_id=task_id, title=title, findings=findings)


def test_ranks_by_impact_times_feasibility():
    # Same feasibility (strong + high) on both; core_business has the higher curated
    # lever weight, so it must outrank the low-weight account_baseline reference module.
    results = [
        _result(
            "account_baseline",
            "账号基线",
            [_finding("基线", EvidenceStrength.STRONG)],
        ),
        _result(
            "core_business_diagnosis",
            "整体经营诊断",
            [_finding("经营结构", EvidenceStrength.STRONG)],
        ),
    ]
    table = build_priority_table(results)
    assert [row["task_id"] for row in table] == [
        "core_business_diagnosis",
        "account_baseline",
    ]
    assert table[0]["priority"] > table[1]["priority"]


def test_excludes_appendix_and_non_actionable():
    results = [
        _result(
            "data_quality_check",
            "数据质量检查",
            [_finding("质量", EvidenceStrength.STRONG)],
        ),
        _result(
            "core_business_diagnosis",
            "整体经营诊断",
            [_finding("无动作", EvidenceStrength.STRONG, action=None)],
        ),
        _result(
            "search_efficiency_diagnosis",
            "搜索效率",
            [_finding("不可判断", EvidenceStrength.NOT_JUDGABLE)],
        ),
        _result(
            "refund_root_cause_diagnosis",
            "退款根因",
            [_finding("退款结构", EvidenceStrength.MEDIUM)],
        ),
    ]
    table = build_priority_table(results)
    task_ids = {row["task_id"] for row in table}
    assert task_ids == {"refund_root_cause_diagnosis"}


def test_picks_best_actionable_finding_per_module():
    # A module contributes exactly one row — the actionable finding with the
    # highest feasibility, not simply the first finding.
    results = [
        _result(
            "core_business_diagnosis",
            "整体经营诊断",
            [
                _finding(
                    "弱结论",
                    EvidenceStrength.WEAK,
                    reliability=DescriptiveReliability.LOW,
                ),
                _finding(
                    "强结论",
                    EvidenceStrength.STRONG,
                    reliability=DescriptiveReliability.HIGH,
                ),
            ],
        ),
    ]
    table = build_priority_table(results)
    assert len(table) == 1
    assert table[0]["weak_link"] == "强结论"


def test_row_shape_carries_reader_facing_fields():
    results = [
        _result(
            "core_business_diagnosis",
            "整体经营诊断",
            [_finding("经营结构", EvidenceStrength.MEDIUM)],
        ),
    ]
    row = build_priority_table(results)[0]
    for key in (
        "task_id",
        "module",
        "weak_link",
        "lever",
        "impact",
        "impact_label",
        "feasibility",
        "feasibility_label",
        "priority",
        "evidence",
        "evidence_class",
    ):
        assert key in row
    assert row["module"] == "整体经营诊断"
    assert row["lever"] == "先动这里"
    assert row["impact_label"] in {"高", "中", "低"}
    assert row["feasibility_label"] in {"高", "中", "低"}


def test_row_carries_confidence_label_and_no_canned_why():
    # D2 fix: the priority table no longer carries a band-composed "为什么值得先做"
    # sentence — on real data every top module collapses to the same impact/
    # feasibility/confidence bands, so any band-derived prose is identical across all
    # rows (a dead column). The row keeps only the genuinely per-row signals plus the
    # required 置信度 rating.
    results = [
        _result(
            "core_business_diagnosis",
            "整体经营诊断",
            [_finding("经营结构", EvidenceStrength.MEDIUM)],
        ),
    ]
    row = build_priority_table(results)[0]
    assert "why" not in row  # the canned reasoning sentence is gone
    assert row["confidence_label"] in {"高", "中", "低", "暂不下定论"}
    assert row["confidence_class"] in {"high", "medium", "low", "not_judgable"}


def test_no_dead_prose_column_on_homogeneous_modules():
    # The exact real-data scenario that defeated the old _why: several high-lever
    # modules that ALL score causally WEAK + descriptively HIGH → identical impact/
    # feasibility/confidence bands. The table must not emit any prose field that reads
    # verbatim-identical down every row; the rows stay differentiated by 哪个环节/具体先做什么.
    results = [
        _result(task_id, title, [_finding(weak, EvidenceStrength.WEAK, action=action)])
        for task_id, title, weak, action in [
            ("core_business_diagnosis", "整体经营诊断", "经营是最弱环节", "补详情页承接"),
            ("refund_root_cause_diagnosis", "退款根因诊断", "发货前退款为主漏点", "查发货前退款"),
            ("search_efficiency_diagnosis", "搜索效率诊断", "点击多成交少", "优化搜索承接"),
        ]
    ]
    table = build_priority_table(results)
    assert len(table) == 3
    # No free-prose "reason" field is a constant sentence repeated across every row (the
    # dead-column smell). Categorical ratings/labels/enums are ALLOWED to be uniform —
    # they are single-token ratings (高/中/低, weak), honest even when they don't vary,
    # not a sentence pretending to be per-row reasoning.
    rating_fields = {
        "confidence_label",
        "confidence_class",
        "evidence",
        "evidence_label",
        "evidence_class",
        "impact_label",
        "feasibility_label",
    }
    prose_keys = {k for k in table[0] if isinstance(table[0][k], str)} - rating_fields
    for key in prose_keys:
        values = {row[key] for row in table}
        assert len(values) == 3, f"{key} should vary per row, not read identical down the table"
    # The rows remain differentiated by their weak-link and lever.
    assert len({row["weak_link"] for row in table}) == 3


def test_caps_rows_and_degrades_empty():
    assert build_priority_table([]) == []
    # Nothing actionable → empty, never raises.
    only_appendix = [
        _result("data_quality_check", "数据质量检查", [_finding("q", EvidenceStrength.STRONG)])
    ]
    assert build_priority_table(only_appendix) == []
    many = [
        _result(
            f"mod_{i}",
            f"模块{i}",
            [_finding(f"结论{i}", EvidenceStrength.MEDIUM)],
        )
        for i in range(20)
    ]
    assert len(build_priority_table(many, max_rows=8)) == 8
    # Default converges to a focused shortlist (top 5), not a long diffuse list —
    # a "先做什么" table the reader can hold in their head.
    assert len(build_priority_table(many)) == 5


def test_never_raises_on_missing_reliability():
    results = [
        _result(
            "core_business_diagnosis",
            "整体经营诊断",
            [_finding("经营结构", EvidenceStrength.MEDIUM, reliability=None)],
        ),
    ]
    row = build_priority_table(results)[0]
    assert 0.0 <= row["feasibility"] <= 1.0
