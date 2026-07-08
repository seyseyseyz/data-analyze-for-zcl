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
from xhs_ceramics_analytics.reporting.domains import group_by_domain
from xhs_ceramics_analytics.reporting.facts_export import numeric_facts_from_finding


def _iter_findings(result: AnalysisResult) -> list[Finding]:
    """域内一条 AnalysisResult 的全部 Finding:顶层 + 子节。"""
    findings = list(result.findings)
    for sub in result.subsections:
        findings.extend(sub.findings)
    return findings


def _finding_facts(task_id: str, finding: Finding) -> list[dict[str, object]]:
    """把一条 Finding 的 key_numbers 摊平成 facts,逐条带证据档与来源结论标题。

    NUMERIC 的 key_number 额外带上 FactBook 里逐字节相同的 ``fact_id`` /
    ``metric_key`` / ``rendered`` —— 直接复用 :func:`numeric_facts_from_finding`
    (facts_export 里 fact_id 的唯一真源),这样 fan agent 的 claim 用 ``{tN}`` 绑上
    ``fact_id`` 后能在 gate 里被 facts.json 解析。非数值 key_number(如 SKU 名称)不是
    FactBook 里的 fact,故不带 ``fact_id``,以免 claim 绑到一个不存在的键上。
    """
    tier = str(finding.evidence_strength)
    numeric = numeric_facts_from_finding(task_id, finding)
    by_metric = {fact.metric_key: fact for fact in numeric.values()}
    out: list[dict[str, object]] = []
    for metric, value in finding.key_numbers.items():
        fact: dict[str, object] = {
            "metric": metric,
            "value": value,
            "evidence": tier,
            "finding": finding.title,
        }
        canonical = by_metric.get(metric)
        if canonical is not None:  # 数值 fact —— 带上可被 gate 解析的 fact_id
            fact["fact_id"] = canonical.fact_id
            fact["metric_key"] = canonical.metric_key
            fact["rendered"] = canonical.rendered
        out.append(fact)
    return out


def _reading(findings: list[Finding]) -> dict[str, str]:
    conclusions = [f.conclusion for f in findings if f.conclusion]
    return {"conclusion": "；".join(conclusions)}


def _normalize_blocked(blocked_modules) -> list[dict[str, str]]:
    """规范每个阻断项为 ``{"slug", "reason"}``,让骨架能说清「缺什么」。

    容忍三种输入:裸字符串 slug(原因留空)、``(slug, reason)`` 二元组(coverage
    带原因的常见形态)、以及已成形的 dict。统一成 dict 后,确定性骨架 fallback 里
    ``_deterministic_markdown`` 就能渲染出「- note_funnel：笔记表缺少 impressions 字段」。
    """
    out: list[dict[str, str]] = []
    for item in blocked_modules:
        if isinstance(item, dict):
            out.append(
                {"slug": str(item.get("slug", "")), "reason": str(item.get("reason", ""))}
            )
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
) -> dict[str, object]:
    """构造叙事控制器的 results.json 文档。Never-raise。

    返回 ``{"domain_slices": [{"title", "facts", "reading"}], "blocked_modules":
    [{"slug", "reason"}]}``。切片顺序即 :data:`domains.DOMAINS` 的域顺序;facts 逐条来自
    Finding.key_numbers,绝不造数;某域无 key_numbers 时 facts 为空但切片仍保留(标题 +
    结论仍有价值)。``blocked_modules`` 被规范成 ``{slug, reason}`` dict(见
    :func:`_normalize_blocked`),原因供确定性骨架说明「缺什么」。
    """
    slices: list[dict[str, object]] = []
    for group in group_by_domain(results):
        # task_id 挂在 result 上而非 finding 上,所以要保留 (task_id, finding) 配对,
        # 才能把 fact_id 的域前缀正确传进 _finding_facts。
        pairs = [
            (result.task_id, finding)
            for result in group.results
            for finding in _iter_findings(result)
        ]
        findings = [finding for _task_id, finding in pairs]
        facts = [fact for task_id, finding in pairs for fact in _finding_facts(task_id, finding)]
        slices.append(
            {
                "title": group.title,
                "facts": facts,
                "reading": _reading(findings),
            }
        )
    return {"domain_slices": slices, "blocked_modules": _normalize_blocked(blocked_modules)}
