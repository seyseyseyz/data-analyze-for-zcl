"""确定性叙事输入生产者 —— 把 AnalysisResult 落成叙事控制器要的 results.json (P1).

``xhs-ca narrative prepare --results`` 消费的是一个「域切片」视图:
``{domain_slices: [{title, facts, reading:{conclusion}}], blocked_modules}``——一条切片
一个业务主题域。这与 facts.json 完全不同:facts.json 里的 ``domain_slices`` 是缓存键用的
dict 且恒空(``build_factbook`` 从不带 ``domain_slices=`` 调用),拿它当 ``--results`` 会让
叙事一开局就 ``capped=0``、无内容可写。

本模块用报告层同一套 :func:`group_by_domain` 把结果收成域切片:域标题即切片标题,域内所有
Finding 的 ``key_numbers`` 逐条摊平成 facts(不造数),结论拼成 ``reading.conclusion``。
这样 L3 叙事路径从真实、可溯源的切片起步,而不是靠手搓文件。纯函数,never-raise。
"""

from __future__ import annotations

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.contracts.platform_catalog import (
    build_platform_semantic_context,
)
from xhs_ceramics_analytics.reporting.domains import group_by_domain
from xhs_ceramics_analytics.reporting.facts_export import (
    CANONICAL_VERSION,
    FactBook,
    build_factbook,
    fact_id_map_for_result,
    facts_hash,
    iter_result_finding_refs,
    metric_mapping_to_dict,
)


def _finding_facts(
    task_id: str,
    finding_path: str,
    finding: Finding,
    factbook: FactBook,
    fact_ids: dict[tuple[str, str], str],
) -> list[dict[str, object]]:
    """把一条 Finding 的 key_numbers 摊平成 facts,逐条带证据档与来源结论标题。

    NUMERIC 的 key_number 额外带上同一 FactBook 中的 ``fact_id`` / ``metric_key`` /
    ``metric_id`` / ``rendered``。这样 fan agent 的 claim 用 ``{tN}`` 绑上 ``fact_id``
    后能在 gate 里被 facts.json 解析。非数值 key_number(如 SKU 名称)不是 FactBook
    里的 fact,故不带 ``fact_id``,以免 claim 绑到一个不存在的键上。
    """
    tier = str(finding.evidence_strength)
    out: list[dict[str, object]] = []
    for metric, value in finding.key_numbers.items():
        fact: dict[str, object] = {
            "metric": metric,
            "value": value,
            "evidence": tier,
            "finding": finding.title,
        }
        canonical_id = fact_ids.get((finding_path, str(metric)))
        canonical = factbook.facts.get(canonical_id) if canonical_id is not None else None
        if canonical is not None:  # 数值 fact —— 带上可被 gate 解析的 fact_id
            fact["fact_id"] = canonical.fact_id
            fact["metric_key"] = canonical.metric_key
            fact["metric_id"] = canonical.metric_id
            fact["rendered"] = canonical.rendered
        out.append(fact)
    return out


def _reading(findings: list[Finding]) -> dict[str, str]:
    conclusions = [f.conclusion for f in findings if f.conclusion]
    return {"conclusion": "；".join(conclusions)}


def _collect_result_tables(
    results: list[AnalysisResult],
) -> dict[str, list[dict[str, object]]]:
    """把每个 AnalysisResult.tables 摊平成一个 ``{表名: 行列表}`` 的扁平 dict —— 这是策展
    视图引擎「填数」和 gate「核对」共用的数值真源(numeric-trust source)。

    键是**裸表名**,因为 curated view 的 ``source.table`` 与 gate 的 ``_check_source``
    都按裸表名查(``result_tables[table]``);故绝不加域前缀,否则 agent 引用不到。跨任务
    重名时**先到先得**(靠前的域权威),让合并结果与结果顺序一致、可复现。只保留真正的
    list-of-dict 行,非 dict 行被过滤、空表名被丢弃。纯函数,never-raise —— 数字仍来自
    L1 已算好的 result.tables,这里只搬运不重算。
    """
    out: dict[str, list[dict[str, object]]] = {}
    for result in results:
        tables = getattr(result, "tables", None)
        if not isinstance(tables, dict):
            continue
        for name, rows in tables.items():
            if not isinstance(name, str) or not name or name in out:
                continue
            if isinstance(rows, (list, tuple)):
                out[name] = [dict(row) for row in rows if isinstance(row, dict)]
    return out


def _normalize_blocked(blocked_modules) -> list[dict[str, str]]:
    """规范每个阻断项为 ``{"slug", "reason"}``,让骨架能说清「缺什么」。

    容忍三种输入:裸字符串 slug(原因留空)、``(slug, reason)`` 二元组(coverage
    带原因的常见形态)、以及已成形的 dict。统一成 dict 后,确定性骨架 fallback 里
    ``_deterministic_markdown`` 就能渲染出「- note_funnel：笔记表缺少 impressions 字段」。
    """
    out: list[dict[str, str]] = []
    for item in blocked_modules:
        if isinstance(item, dict):
            out.append({"slug": str(item.get("slug", "")), "reason": str(item.get("reason", ""))})
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            slug, reason = item
            out.append({"slug": str(slug), "reason": str(reason)})
        else:
            out.append({"slug": str(item), "reason": ""})
    return out


def build_narrative_results(
    results: list[AnalysisResult],
    *,
    blocked_modules: tuple[str, ...] | list[str] = (),
    factbook: FactBook | None = None,
) -> dict[str, object]:
    """从同一 FactBook 快照构造叙事控制器的 results.json 文档。

    返回 ``{"domain_slices": [{"title", "facts", "reading"}], "blocked_modules":
    [{"slug", "reason"}], "result_tables": {表名: 行列表}}``。切片顺序即
    :data:`domains.DOMAINS` 的域顺序;facts 逐条来自 Finding.key_numbers,绝不造数;某域无
    key_numbers 时 facts 为空但切片仍保留(标题 + 结论仍有价值)。``blocked_modules`` 被
    规范成 ``{slug, reason}`` dict(见 :func:`_normalize_blocked`),原因供确定性骨架说明
    「缺什么」。``result_tables`` 把 L1 已算好的 ``result.tables`` 扁平摊出(见
    :func:`_collect_result_tables`),作为策展视图引擎填数、gate 核对数值的唯一源 —— 没有
    它,任何 agent 产出的 curated view 都会因「表不在 result.tables」被 gate 判非法。
    """
    factbook = factbook or build_factbook(results)
    slices: list[dict[str, object]] = []
    for group in group_by_domain(results):
        # task_id 挂在 result 上而非 finding 上,所以要保留 (task_id, finding) 配对,
        # 才能把 fact_id 的域前缀正确传进 _finding_facts。
        pairs = []
        for result in group.results:
            fact_ids = fact_id_map_for_result(result)
            pairs.extend(
                (result.task_id, ref.path, ref.finding, fact_ids)
                for ref in iter_result_finding_refs(result)
            )
        findings = [finding for _task_id, _path, finding, _fact_ids in pairs]
        facts = [
            fact
            for task_id, finding_path, finding, fact_ids in pairs
            for fact in _finding_facts(
                task_id,
                finding_path,
                finding,
                factbook,
                fact_ids,
            )
        ]
        slices.append(
            {
                "title": group.title,
                "facts": facts,
                "reading": _reading(findings),
            }
        )
    return {
        "canonical_version": CANONICAL_VERSION,
        "facts_hash": facts_hash(factbook),
        "registry_hash": factbook.metric_mapping.registry_hash,
        "metric_mapping": metric_mapping_to_dict(factbook.metric_mapping),
        "platform_semantics": build_platform_semantic_context(),
        "domain_slices": slices,
        "blocked_modules": _normalize_blocked(blocked_modules),
        "result_tables": _collect_result_tables(results),
    }
