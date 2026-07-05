"""病根 C 契约守卫:Finding.conclusion / caveats 只放商家能懂的经营语言。

一切方法学措辞(显著性门槛、去趋势、残差、ISO 周、多变点、最小二乘斜率、z 检验、
BH-FDR、LMDI、Wilson 区间、赫芬达尔/基尼、分位、效应量、"观察性")一律留在
``appendix`` —— 附录不扫,方法学诚实性不丢;但读者第一眼看到的结论和注意事项必须是人话。

扫描针对真实建库产物(全 registry),缺库时跳过(与其他 real-DB 测试一致)。
"""
import os
from pathlib import Path

import pytest

from xhs_ceramics_analytics.analysis.registry import TASKS

REAL_DB_PATH = "/tmp/xhs-real-run/analytics.duckdb"

# 面向商家的文本里禁止出现的方法学术语。这些词只允许出现在 appendix(方法与附录)。
_JARGON = [
    "显著性",
    "斜率",
    "残差",
    "去趋势",
    "多变点",
    "z检验",
    "z 检验",
    "BH-FDR",
    "LMDI",
    "赫芬达尔",
    "基尼",
    "观察性",
    "分位",
    "标准差",
    "σ",
    "Wilson",
    "两样本",
    "比例检验",
    "最小二乘",
    "置信区间",
    "效应量",
    "p值",
    "p 值",
]


def _findings(result):
    findings = list(result.findings)
    for subsection in result.subsections:
        findings.extend(subsection.findings)
    return findings


def _assert_merchant_facing(text, where):
    for token in _JARGON:
        assert token not in (text or ""), f"方法学术语「{token}」漏进商家文本 [{where}]: {text!r}"


@pytest.mark.skipif(not os.path.exists(REAL_DB_PATH), reason=f"real DB not at {REAL_DB_PATH}")
@pytest.mark.parametrize("task_id", sorted(TASKS))
def test_conclusions_and_caveats_are_merchant_facing(task_id):
    result = TASKS[task_id](Path(REAL_DB_PATH))
    for finding in _findings(result):
        _assert_merchant_facing(finding.conclusion, f"{task_id}:conclusion")
        for caveat in finding.caveats or []:
            _assert_merchant_facing(caveat, f"{task_id}:caveat")
