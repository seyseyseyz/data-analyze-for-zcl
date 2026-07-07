"""确定性叙事输入生产者 build_narrative_results (P1).

叙事控制器 ``xhs-ca narrative prepare --results`` 消费的是「域切片」视图:
``{domain_slices: [{title, facts, reading}], blocked_modules}``——一条切片一个业务域。
facts.json 里的 ``domain_slices`` 是缓存键用的 dict 且恒空,不能当 ``--results``;这个
生产者把同一批 AnalysisResult 经 group_by_domain 落成叙事真正能起步的切片列表。
"""

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.reporting.narrative_results import build_narrative_results


def _result(task_id: str, *, title: str, conclusion: str, key_numbers: dict) -> AnalysisResult:
    return AnalysisResult(
        task_id=task_id,
        title=task_id,
        findings=[
            Finding(
                title=title,
                conclusion=conclusion,
                evidence_strength=EvidenceStrength.MEDIUM,
                key_numbers=key_numbers,
            )
        ],
    )


def test_returns_domain_slices_and_blocked_modules_keys():
    doc = build_narrative_results([], blocked_modules=("note_funnel",))
    assert set(doc) == {"domain_slices", "blocked_modules"}
    assert doc["domain_slices"] == []
    assert doc["blocked_modules"] == ["note_funnel"]


def test_slice_shape_matches_narrative_consumer():
    # 切片必须是 {title, facts, reading:{conclusion}} —— 与 narrative_workflow 的
    # _cap_slices / _write_seed_brief / _write_fan_briefs 消费的形状一致。
    doc = build_narrative_results(
        [_result("core_business_diagnosis", title="GMV 结论", conclusion="大盘走弱", key_numbers={"gmv": 12345})]
    )
    slices = doc["domain_slices"]
    assert len(slices) == 1
    sl = slices[0]
    assert set(sl) == {"title", "facts", "reading"}
    assert sl["title"] == "生意大盘"
    assert isinstance(sl["facts"], list) and sl["facts"], "facts 不能为空"
    fact = sl["facts"][0]
    assert fact["metric"] == "gmv" and fact["value"] == 12345
    assert sl["reading"]["conclusion"], "reading.conclusion 不能为空"
    assert "大盘走弱" in sl["reading"]["conclusion"]


def test_facts_are_grounded_in_finding_key_numbers():
    # facts 必须逐条来自 Finding.key_numbers,不得凭空造数。
    doc = build_narrative_results(
        [_result("core_business_diagnosis", title="t", conclusion="c", key_numbers={"a": 1, "b": 2})]
    )
    metrics = {f["metric"]: f["value"] for f in doc["domain_slices"][0]["facts"]}
    assert metrics == {"a": 1, "b": 2}


def test_multiple_domains_are_separate_slices_in_registry_order():
    doc = build_narrative_results(
        [
            _result("audience_structure_diagnosis", title="人群", conclusion="人群偏中年", key_numbers={"age": 40}),
            _result("core_business_diagnosis", title="大盘", conclusion="大盘走弱", key_numbers={"gmv": 1}),
        ]
    )
    titles = [s["title"] for s in doc["domain_slices"]]
    # 生意大盘 域在 用户与需求 域之前(DOMAINS 顺序)。
    assert titles == ["生意大盘", "用户与需求"]


def test_never_raises_on_empty_and_defaults_blocked_empty():
    doc = build_narrative_results([])
    assert doc == {"domain_slices": [], "blocked_modules": []}
