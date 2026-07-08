"""确定性叙事输入生产者 build_narrative_results (P1).

叙事控制器 ``xhs-ca narrative prepare --results`` 消费的是「域切片」视图:
``{domain_slices: [{title, facts, reading}], blocked_modules}``——一条切片一个业务域。
facts.json 里的 ``domain_slices`` 是缓存键用的 dict 且恒空,不能当 ``--results``;这个
生产者把同一批 AnalysisResult 经 group_by_domain 落成叙事真正能起步的切片列表。
"""

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.reporting.facts_export import build_factbook
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


def test_returns_domain_slices_blocked_modules_and_result_tables_keys():
    doc = build_narrative_results([], blocked_modules=("note_funnel",))
    # result_tables joins the contract: it is the numeric-trust source the curated-view
    # engine fills from + the gate polices against. Empty analysis → empty tables.
    assert set(doc) == {"domain_slices", "blocked_modules", "result_tables"}
    assert doc["domain_slices"] == []
    assert doc["result_tables"] == {}
    # blocked_modules is normalized to {slug, reason} dicts so the skeleton can
    # explain what is missing; a bare string gets an empty reason.
    assert doc["blocked_modules"] == [{"slug": "note_funnel", "reason": ""}]


def test_blocked_modules_carry_coverage_reason_when_given_as_pairs():
    doc = build_narrative_results(
        [], blocked_modules=[("note_funnel", "笔记表缺少 impressions 字段")]
    )
    assert doc["blocked_modules"] == [
        {"slug": "note_funnel", "reason": "笔记表缺少 impressions 字段"}
    ]


def test_blocked_modules_accepts_dicts_verbatim():
    doc = build_narrative_results(
        [], blocked_modules=[{"slug": "note_funnel", "reason": "缺表"}]
    )
    assert doc["blocked_modules"] == [{"slug": "note_funnel", "reason": "缺表"}]


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


def test_numeric_slice_facts_carry_factbook_fact_id():
    # Option A(claims 模型)的地基:每条 NUMERIC 切片 fact 必须带一个与 FactBook
    # 逐字节相同的 fact_id/metric_key/rendered。fan agent 的 claim 用 {tN}->fact_id
    # 绑定数字,gate 拿这个 fact_id 去 facts.json 里核对;若两侧 fact_id 不一致,
    # 每条 claim 都会 MISSING_FACT 硬失败。这里用「同一批 results 同时喂给
    # build_narrative_results 与 build_factbook」证明二者的 fact_id 完全一致。
    results = [
        _result("core_business_diagnosis", title="GMV", conclusion="c", key_numbers={"gmv": 12345})
    ]
    slice_fact = build_narrative_results(results)["domain_slices"][0]["facts"][0]
    assert slice_fact["fact_id"] == "core_business_diagnosis.gmv"
    assert slice_fact["metric_key"] == "gmv"
    assert slice_fact["rendered"], "rendered 由 Python 生成,不能为空"

    book = build_factbook(results)
    assert slice_fact["fact_id"] in book.facts, "切片 fact_id 必须在 FactBook 中可解析"
    canonical = book.facts[slice_fact["fact_id"]]
    assert slice_fact["metric_key"] == canonical.metric_key
    assert slice_fact["rendered"] == canonical.rendered  # 同一渲染,零漂移


def test_non_numeric_slice_fact_has_no_fact_id():
    # 非数值 key_number(如 SKU 名称)不是 facts.json 里的 fact,绝不能带 fact_id,
    # 否则 claim 绑上去会指向一个 FactBook 中不存在的键 -> MISSING_FACT。
    results = [
        _result("core_business_diagnosis", title="t", conclusion="c",
                 key_numbers={"最贵SKU": "兴安岭之夜"})
    ]
    slice_fact = build_narrative_results(results)["domain_slices"][0]["facts"][0]
    assert slice_fact["metric"] == "最贵SKU"
    assert "fact_id" not in slice_fact
    # 且它也确实不在 FactBook 里(数值过滤两侧一致)。
    assert build_factbook(results).facts == {}


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
    assert doc == {"domain_slices": [], "blocked_modules": [], "result_tables": {}}


# ---- result_tables: the numeric-trust source for curated views ------------

def _result_with_tables(task_id: str, tables: dict) -> AnalysisResult:
    return AnalysisResult(
        task_id=task_id,
        title=task_id,
        findings=[Finding(title="t", conclusion="c",
                          evidence_strength=EvidenceStrength.MEDIUM, key_numbers={"gmv": 1})],
        tables=tables,
    )


def test_result_tables_flattens_analysis_tables_by_bare_name():
    # The curated-view engine + gate look tables up by BARE name (source.table), so the
    # producer must surface AnalysisResult.tables flat, verbatim — never re-computed.
    rows = [
        {"component": "转化", "delta_gmv": 12000},
        {"component": "流量", "delta_gmv": 8000},
    ]
    doc = build_narrative_results([_result_with_tables("core_business_diagnosis",
                                                       {"growth_bridge": rows})])
    assert doc["result_tables"]["growth_bridge"] == rows


def test_result_tables_merges_across_results_first_wins_on_name_collision():
    a = _result_with_tables("t_a", {"shared": [{"x": 1}], "only_a": [{"y": 2}]})
    b = _result_with_tables("t_b", {"shared": [{"x": 99}], "only_b": [{"z": 3}]})
    doc = build_narrative_results([a, b])
    tables = doc["result_tables"]
    assert set(tables) == {"shared", "only_a", "only_b"}
    assert tables["shared"] == [{"x": 1}]  # first result wins — order-stable


def test_result_tables_never_raises_on_garbage_tables():
    # A malformed table degrades to skipped/filtered rows; the producer never raises.
    r = _result_with_tables("t", {"good": [{"a": 1}, "not-a-row"], "": [{"a": 1}]})
    doc = build_narrative_results([r])
    assert doc["result_tables"]["good"] == [{"a": 1}]  # non-dict row filtered
    assert "" not in doc["result_tables"]  # empty table name dropped
