# tests/test_action_license.py
"""行动许可（action_license）投影 — Decision Compiler ADR §3.3 的运行时落地。

读者标签只有两个：描述置信（reporting.confidence.reader_confidence，已实现）与
行动许可（本文件测试）。行动许可回答"这条建议能不能直接干"：

- 可执行 execute：有对照的因果证据支持直接执行；
- 可试点 pilot：数字可靠但无对照 → 只能小规模试点（mechanism_hypothesis 封顶）；
- 仅观察 observe：弱证据且无升级路径 → 只是假设，不发建议；
- 先补数据 blocked：not_judgable → 先补齐数据。

gate 侧与置信度同构：agent 自报的 license 超出锚定事实允许的上限时确定性降档
（LICENSE_CAPPED 警告），永不硬失败——大胆但被纠正的行动优于沉默。
"""
import copy

from xhs_ceramics_analytics.analysis.result import Finding
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength
from xhs_ceramics_analytics.reporting.confidence import action_license
from xhs_ceramics_analytics.reporting.factcheck_gate import run_gate
from xhs_ceramics_analytics.reporting.html import _recommended_actions


def _finding(**kw):
    base = dict(
        title="退款集中在发货前",
        conclusion="发货前退款占比 62%。",
        evidence_strength=EvidenceStrength.WEAK,
    )
    base.update(kw)
    return Finding(**base)


# ---------------------------------------------------------------- finding 投影


def test_not_judgable_maps_to_blocked():
    lic = action_license(_finding(evidence_strength=EvidenceStrength.NOT_JUDGABLE))
    assert lic.level == "blocked"
    assert lic.label == "先补数据"


def test_finding_without_action_or_next_test_is_observe_only():
    lic = action_license(_finding())
    assert lic.level == "observe"
    assert lic.label == "仅观察"


def test_strong_evidence_with_action_is_executable():
    lic = action_license(
        _finding(
            evidence_strength=EvidenceStrength.STRONG,
            recommended_action="按已验证结论扩量",
        )
    )
    assert lic.level == "execute"
    assert lic.label == "可执行"


def test_medium_evidence_with_action_caps_at_pilot():
    lic = action_license(
        _finding(
            evidence_strength=EvidenceStrength.MEDIUM,
            recommended_action="小规模复制对照发现",
        )
    )
    assert lic.level == "pilot"
    assert lic.label == "可试点"


def test_weak_but_reliable_with_upgrade_path_is_pilot():
    lic = action_license(
        _finding(
            recommended_action="优先补发货前流程",
            next_test="下周对照观察发货前退款占比",
            descriptive_reliability=DescriptiveReliability.HIGH,
        )
    )
    assert lic.level == "pilot"


def test_weak_action_without_upgrade_path_stays_observe():
    # SKILL 规则 4：弱证据无升级路径的建议只是假设，不发放试点许可。
    lic = action_license(
        _finding(
            recommended_action="优先补发货前流程",
            descriptive_reliability=DescriptiveReliability.HIGH,
        )
    )
    assert lic.level == "observe"


def test_weak_unreliable_with_upgrade_path_stays_observe():
    lic = action_license(
        _finding(
            recommended_action="优先补发货前流程",
            next_test="下周对照观察",
            descriptive_reliability=DescriptiveReliability.LOW,
        )
    )
    assert lic.level == "observe"


# ---------------------------------------------------------------- gate 降档

_FACTS = {
    "facts_hash": "h",
    "facts": {
        "m.gmv": {"rendered": "¥20.8万", "metric_key": "gmv", "direction": "down",
                  "pool_id": None, "entity_type": None, "evidence_strength": "strong",
                  "descriptive_reliability": "high", "assumption": None},
        "m.aov": {"rendered": "¥195", "metric_key": "aov", "direction": "down",
                  "pool_id": None, "entity_type": None, "evidence_strength": "medium",
                  "descriptive_reliability": "medium", "assumption": None},
        "m.gap": {"rendered": "暂不可判", "metric_key": "gap", "direction": None,
                  "pool_id": None, "entity_type": None,
                  "evidence_strength": "not_judgable",
                  "descriptive_reliability": None, "assumption": None},
    },
    "entity_registry": [],
    "absent_link_registry": [],
    "non_additive_ledger": {"rows": [], "net_total": None, "banner": ""},
}


def _claim(**kw):
    c = {"claim_id": "c0", "section_id": "core_business", "claim_kind": "measurement",
         "sentence": "GMV {t0}。", "number_tokens": [
             {"token_id": "t0", "fact_id": "m.gmv", "expected_metric_key": "gmv",
              "direction": "down"}],
         "entity_refs": [], "confidence": "强", "causal_link": None}
    c.update(kw)
    return c


def _card(**overrides):
    card = {
        "action_id": "a0",
        "action_family": "商品优化",
        "title": "优先复盘支付金额",
        "owner_role": "店铺负责人",
        "steps": ["围绕已验证的问题安排复盘"],
        "primary_fact_id": "m.gmv",
        "guardrail_fact_id": None,
        "stop_rule": "指标回落时停止",
        "license": "pilot",
        "supporting_claim_ids": ["c0"],
        "number_tokens": [],
    }
    card.update(overrides)
    return card


def _bundle(claims, **kw):
    b = {"facts_hash": "h", "headline": "标题。",
         "first_screen": {"spine": [], "panel": [], "actions": []},
         "spine_final": {"backbone": [{"link_id": "L1", "from": "traffic", "to": "gmv",
                                       "anchor_fact_ids": ["m.gmv"],
                                       "relation": "accounting_identity"}]},
         "sections": [{"section_id": "core_business", "title": "大盘", "claims": claims,
                       "table_ref": None, "chart_ref": None, "spine_callbacks": ["L1"]}],
         "cannot_say": []}
    b.update(kw)
    return b


def _gate(card, claims=None):
    claims = claims if claims is not None else [_claim()]
    return run_gate(_bundle(claims, action_cards=[card]), copy.deepcopy(_FACTS))


def _card_out(report):
    return (report.bundle.get("action_cards") or [])[0]


def test_gate_keeps_license_within_evidence_allowance():
    r = _gate(_card(license="execute"))  # primary m.gmv 为 strong → execute 合法
    assert r.status == "PASS"
    assert _card_out(r)["license"] == "execute"
    assert not any(w["code"] == "ACTION_LICENSE_CAPPED" for w in r.warnings)


def test_gate_caps_execute_on_medium_evidence_to_pilot():
    r = _gate(_card(license="execute", primary_fact_id="m.aov"))
    assert r.status == "PASS"  # 降档是警告，不是硬失败
    assert _card_out(r)["license"] == "pilot"
    assert any(w["code"] == "ACTION_LICENSE_CAPPED" for w in r.warnings)
    assert {"claim_id": "a0", "from": "execute", "to": "pilot"} in r.capped_claims


def test_gate_caps_mechanism_supported_action_to_pilot():
    # ADR：mechanism_hypothesis 支撑的行动 pilot 封顶，哪怕主锚事实是 strong。
    r = _gate(
        _card(license="execute"),
        claims=[_claim(claim_kind="mechanism", confidence="弱")],
    )
    assert _card_out(r)["license"] == "pilot"
    assert any(w["code"] == "ACTION_LICENSE_CAPPED" for w in r.warnings)


def test_gate_caps_not_judgable_anchor_to_blocked():
    r = _gate(_card(license="pilot", primary_fact_id="m.gap"))
    assert _card_out(r)["license"] == "blocked"
    assert any(w["code"] == "ACTION_LICENSE_CAPPED" for w in r.warnings)


def test_gate_never_upgrades_a_timid_license():
    # 与置信度同构：只向下封顶，agent 保守选择 observe 时不动它。
    r = _gate(_card(license="observe"))
    assert _card_out(r)["license"] == "observe"
    assert not any(w["code"] == "ACTION_LICENSE_CAPPED" for w in r.warnings)


# ---------------------------------------------------------------- 事实层 HTML


def test_recommended_actions_carry_license_chip():
    finding = _finding(
        evidence_strength=EvidenceStrength.STRONG,
        recommended_action="按已验证结论扩量",
    )
    (entry,) = _recommended_actions([finding])
    assert entry["license"] == "可执行"
    assert entry["license_class"] == "execute"
