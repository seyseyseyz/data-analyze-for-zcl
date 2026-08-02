"""业务主题域注册表 + group_by_domain 两级信息架构 (病根 B / Task B1)."""

from xhs_ceramics_analytics.analysis.registry import TASKS
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength
from xhs_ceramics_analytics.reporting.domains import DOMAINS, DomainGroup, group_by_domain
from xhs_ceramics_analytics.reporting.section_order import APPENDIX_TASKS


def test_every_task_mapped_to_exactly_one_domain():
    mapped = [t for _, _, tasks in DOMAINS for t in tasks]
    assert len(mapped) == len(set(mapped)), "task 重复归域"
    for task_id in TASKS:
        if task_id in APPENDIX_TASKS:
            continue
        assert task_id in mapped, f"{task_id} 未归入任何域"


def test_refund_modules_share_one_domain():
    titles = {title: tasks for title, _, tasks in DOMAINS}
    refund = titles["退款与售后"]
    assert "refund_structure_diagnosis" in refund
    assert "refund_root_cause_diagnosis" in refund


def test_paid_traffic_has_its_own_domain():
    titles = {title: tasks for title, _, tasks in DOMAINS}
    assert "paid_traffic_efficiency" in titles["付费增长"]
    assert "paid_traffic_efficiency" not in titles["流量与内容"]


def test_paid_growth_follows_organic_traffic_before_product_analysis():
    titles = [title for title, _, _ in DOMAINS]
    assert titles.index("流量与内容") < titles.index("付费增长") < titles.index("商品结构")


def _actionable(task_id: str, evidence: EvidenceStrength, reliability: DescriptiveReliability):
    return AnalysisResult(
        task_id=task_id,
        title=task_id,
        findings=[
            Finding(
                title=f"{task_id} 结论",
                conclusion="c",
                evidence_strength=evidence,
                descriptive_reliability=reliability,
                recommended_action="做点什么",
            )
        ],
    )


def test_group_by_domain_places_both_refund_modules_in_one_group():
    results = [
        _actionable("refund_root_cause_diagnosis", EvidenceStrength.WEAK, DescriptiveReliability.HIGH),
        _actionable("refund_structure_diagnosis", EvidenceStrength.WEAK, DescriptiveReliability.HIGH),
    ]
    groups = group_by_domain(results)
    assert all(isinstance(g, DomainGroup) for g in groups)
    refund = next(g for g in groups if g.title == "退款与售后")
    task_ids = {r.task_id for r in refund.results}
    assert task_ids == {"refund_root_cause_diagnosis", "refund_structure_diagnosis"}


def test_group_by_domain_sorts_results_by_priority_desc():
    # Same domain (商品结构); higher-lever + stronger evidence must rank first.
    strong = _actionable(
        "sku_structure_diagnosis", EvidenceStrength.STRONG, DescriptiveReliability.HIGH
    )
    weak = _actionable(
        "sku_counterfactual_lift", EvidenceStrength.WEAK, DescriptiveReliability.LOW
    )
    groups = group_by_domain([weak, strong])  # deliberately reversed input order
    product = next(g for g in groups if g.title == "商品结构")
    assert [r.task_id for r in product.results] == [
        "sku_structure_diagnosis",
        "sku_counterfactual_lift",
    ]


def test_paid_growth_domain_activates_with_observed_rows():
    result = _actionable(
        "paid_traffic_efficiency", EvidenceStrength.WEAK, DescriptiveReliability.LOW
    )
    result.tables = {
        "paid_traffic_efficiency": [{"spend": 100, "impressions": 1000}]
    }

    groups = group_by_domain([result])

    assert [group.title for group in groups] == ["付费增长"]


def test_paid_growth_domain_stays_hidden_without_observed_rows():
    result = _actionable(
        "paid_traffic_efficiency",
        EvidenceStrength.NOT_JUDGABLE,
        DescriptiveReliability.LOW,
    )
    result.tables = {"paid_traffic_efficiency": []}

    assert group_by_domain([result]) == []


def test_group_by_domain_never_drops_unknown_task():
    unknown = _actionable("some_future_module", EvidenceStrength.MEDIUM, DescriptiveReliability.HIGH)
    groups = group_by_domain([unknown])
    all_task_ids = {r.task_id for g in groups for r in g.results}
    assert "some_future_module" in all_task_ids
    # it lands in the trailing fallback domain, not any named business domain
    fallback = groups[-1]
    assert "some_future_module" in {r.task_id for r in fallback.results}


def test_group_by_domain_excludes_appendix_tasks():
    results = [
        _actionable("core_business_diagnosis", EvidenceStrength.WEAK, DescriptiveReliability.HIGH),
        AnalysisResult(task_id="data_quality_check", title="数据质量检查", findings=[]),
    ]
    groups = group_by_domain(results)
    all_task_ids = {r.task_id for g in groups for r in g.results}
    assert "data_quality_check" not in all_task_ids
    assert "core_business_diagnosis" in all_task_ids


def test_group_by_domain_never_raises_on_empty():
    assert group_by_domain([]) == []
