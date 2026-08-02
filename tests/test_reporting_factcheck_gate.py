# tests/test_reporting_factcheck_gate.py
import copy

from xhs_ceramics_analytics.reporting.factcheck_gate import run_gate


def _facts(**overrides):
    base = {
        "facts_hash": "h",
        "facts": {
            "m.gmv": {"rendered": "¥20.8万", "metric_key": "gmv", "direction": "down",
                      "pool_id": None, "entity_type": None, "evidence_strength": "strong",
                      "descriptive_reliability": "high", "assumption": None},
            "m.aov": {"rendered": "¥195", "metric_key": "aov", "direction": "down",
                      "pool_id": None, "entity_type": None, "evidence_strength": "medium",
                      "descriptive_reliability": "medium", "assumption": None},
            "pool.pre": {"rendered": "¥12.9万", "metric_key": "preship", "direction": None,
                         "pool_id": "pre_ship", "entity_type": None, "evidence_strength": "strong",
                         "descriptive_reliability": "high", "assumption": "仅发货前池"},
            "pool.post": {"rendered": "¥7.9万", "metric_key": "postship", "direction": None,
                          "pool_id": "post_ship", "entity_type": None,
                          "evidence_strength": "strong", "descriptive_reliability": "high",
                          "assumption": None},
            "sku.hot": {"rendered": "¥3.1万", "metric_key": "sku_gmv", "direction": "up",
                        "pool_id": None, "entity_type": "sku", "evidence_strength": "weak",
                        "descriptive_reliability": "medium", "assumption": None},
        },
        "entity_registry": ["兴安岭之夜", "鱼盘"],
        "absent_link_registry": ["note->order", "退款原因"],
        "non_additive_ledger": {"rows": [], "net_total": None, "banner": "各池口径不同"},
    }
    base.update(overrides)
    return base


def _claim(**kw):
    c = {"claim_id": "c0", "section_id": "core_business", "claim_kind": "measurement",
         "sentence": "GMV {t0}。", "number_tokens": [
             {"token_id": "t0", "fact_id": "m.gmv", "expected_metric_key": "gmv",
              "direction": "down"}],
         "entity_refs": [], "confidence": "强", "causal_link": None}
    c.update(kw)
    return c


def _bundle(claims, **kw):
    b = {"facts_hash": "h", "headline": "标题。",
         "first_screen": {"spine": [], "panel": [], "actions": []},
         "spine_final": {"backbone": [{"link_id": "L1", "from": "traffic", "to": "gmv",
                                       "anchor_fact_ids": ["m.gmv"], "relation": "accounting_identity"}]},
         "sections": [{"section_id": "core_business", "title": "大盘", "claims": claims,
                       "table_ref": None, "chart_ref": None, "spine_callbacks": ["L1"]}],
         "cannot_say": []}
    b.update(kw)
    return b


def _action_card(**overrides):
    card = {
        "action_id": "a0",
        "action_family": "商品优化",
        "title": "优先复盘支付金额",
        "owner_role": "店铺负责人",
        "steps": ["围绕已验证的问题安排复盘"],
        "primary_fact_id": "m.gmv",
        "guardrail_fact_id": "m.aov",
        "stop_rule": "客单价继续低于 {t0} 时停止扩量",
        "license": "pilot",
        "supporting_claim_ids": ["c0"],
        "number_tokens": [
            {
                "token_id": "t0",
                "fact_id": "m.aov",
                "expected_metric_key": "aov",
                "direction": "down",
            }
        ],
    }
    card.update(overrides)
    return card


def test_clean_bundle_passes():
    r = run_gate(_bundle([_claim()]), _facts())
    assert r.status == "PASS"
    assert r.hard_failures == []


def test_bundle_from_another_fact_and_registry_snapshot_hard_fails():
    bundle = _bundle([_claim()])
    bundle["facts_hash"] = "stale-facts-and-registry"

    result = run_gate(bundle, _facts())

    assert result.status == "FAIL"
    assert any(failure["code"] == "FACTS_SNAPSHOT_MISMATCH" for failure in result.hard_failures)


def test_missing_fact_hard_fails():
    r = run_gate(_bundle([_claim(number_tokens=[
        {"token_id": "t0", "fact_id": "m.ghost", "expected_metric_key": "gmv",
         "direction": "down"}])]), _facts())
    assert r.status == "FAIL"
    assert any(f["code"] == "MISSING_FACT" for f in r.hard_failures)


def test_duplicate_token_id_hard_fails():
    # Two tokens sharing token_id "t0" collapse in the {tN} multiset and would pass
    # MAGNITUDE_UNBOUND; only the first ever fills, silently dropping the second fact.
    r = run_gate(_bundle([_claim(number_tokens=[
        {"token_id": "t0", "fact_id": "m.gmv", "expected_metric_key": "gmv", "direction": "down"},
        {"token_id": "t0", "fact_id": "m.aov", "expected_metric_key": "aov", "direction": "down"},
    ])]), _facts())
    assert r.status == "FAIL"
    assert any(f["code"] == "MAGNITUDE_UNBOUND" for f in r.hard_failures)


def test_first_screen_action_with_fabricated_magnitude_hard_fails():
    # first_screen.actions are writer free-text, not token claims — the only narrative
    # surface the token gate doesn't cover. A currency/percent/万 magnitude there is a
    # fabricated number (no fact anchor) and must HARD-fail, not slip through un-gated.
    for bad in ("把客单价提到 ¥150", "转化率冲到 5%", "把 GMV 做到 3 万"):
        b = _bundle([_claim()])
        b["first_screen"]["actions"] = [bad]
        r = run_gate(b, _facts())
        assert r.status == "FAIL", bad
        assert any(f["code"] == "MAGNITUDE_UNBOUND" for f in r.hard_failures), bad


def test_first_screen_action_with_benign_count_passes():
    # Imperative counts ("发 2 到 3 条内容") are advice granularity, not data magnitudes,
    # and must NOT trip the gate.
    b = _bundle([_claim()])
    b["first_screen"]["actions"] = ["围绕同一个 SKU 连续发 2 到 3 条内容，只改一个变量。"]
    r = run_gate(b, _facts())
    assert r.status == "PASS"


def test_grounded_action_card_passes():
    result = run_gate(_bundle([_claim()], action_cards=[_action_card()]), _facts())

    assert result.status == "PASS"


def test_rendered_grounded_action_card_still_passes_gate():
    from xhs_ceramics_analytics.reporting.narrative_render import render_draft

    drafted = render_draft(_bundle([_claim()], action_cards=[_action_card()]), _facts())
    result = run_gate(drafted, _facts())

    assert result.status == "PASS"


def test_action_card_rejects_unknown_references_and_unbound_numbers():
    card = _action_card(
        primary_fact_id="missing.fact",
        supporting_claim_ids=["missing.claim"],
        stop_rule="转化率低于 5% 时停止扩量",
        number_tokens=[],
    )

    result = run_gate(_bundle([_claim()], action_cards=[card]), _facts())
    codes = {failure["code"] for failure in result.hard_failures}

    assert result.status == "FAIL"
    assert "ACTION_PRIMARY_FACT_MISSING" in codes
    assert "ACTION_SUPPORTS_UNKNOWN_CLAIM" in codes
    assert "MAGNITUDE_UNBOUND" in codes


def test_nonexistent_slice_hard_fails():
    facts = _facts()
    facts["facts"]["退款原因"] = {"rendered": "¥1", "metric_key": "reason", "direction": None,
                                  "pool_id": None, "entity_type": None, "evidence_strength": "weak",
                                  "descriptive_reliability": "low", "assumption": None}
    r = run_gate(_bundle([_claim(number_tokens=[
        {"token_id": "t0", "fact_id": "退款原因", "expected_metric_key": "reason",
         "direction": None}])]), facts)
    assert any(f["code"] == "NONEXISTENT_SLICE" for f in r.hard_failures)


def test_metric_misbind_hard_fails():
    r = run_gate(_bundle([_claim(number_tokens=[
        {"token_id": "t0", "fact_id": "m.gmv", "expected_metric_key": "aov",
         "direction": "down"}])]), _facts())
    assert any(f["code"] == "METRIC_MISBIND" for f in r.hard_failures)


def test_direction_conflict_hard_fails():
    r = run_gate(_bundle([_claim(number_tokens=[
        {"token_id": "t0", "fact_id": "m.gmv", "expected_metric_key": "gmv",
         "direction": "up"}])]), _facts())
    assert any(f["code"] == "DIRECTION_CONFLICT" for f in r.hard_failures)


def test_invented_entity_hard_fails():
    r = run_gate(_bundle([_claim(entity_refs=["不存在的系列"])]), _facts())
    assert any(f["code"] == "INVENTED_ENTITY" for f in r.hard_failures)


def test_magnitude_unbound_bare_digit_hard_fails():
    r = run_gate(_bundle([_claim(sentence="GMV 是 208364 元。", number_tokens=[])]), _facts())
    assert any(f["code"] == "MAGNITUDE_UNBOUND" for f in r.hard_failures)


def test_magnitude_unbound_token_mismatch_hard_fails():
    r = run_gate(_bundle([_claim(sentence="GMV {t0} 与 {t9}。")]), _facts())
    assert any(f["code"] == "MAGNITUDE_UNBOUND" for f in r.hard_failures)


def test_quantified_attribution_on_absent_link_hard_fails():
    c = _claim(claim_kind="mechanism", confidence="弱",
               causal_link={"from_entity_type": "note", "to_entity_type": "order",
                            "quantified": True})
    r = run_gate(_bundle([c]), _facts())
    assert any(f["code"] == "QUANTIFIED_ATTRIBUTION" for f in r.hard_failures)


def test_directional_mechanism_on_absent_link_passes():
    c = _claim(claim_kind="mechanism", confidence="弱", entity_refs=["兴安岭之夜"],
               causal_link={"from_entity_type": "note", "to_entity_type": "order",
                            "quantified": False})
    r = run_gate(_bundle([c]), _facts())
    assert not any(f["code"] == "QUANTIFIED_ATTRIBUTION" for f in r.hard_failures)


def test_summed_pools_hard_fails():
    c = _claim(sentence="可回收合计 {t0}+{t1}。", number_tokens=[
        {"token_id": "t0", "fact_id": "pool.pre", "expected_metric_key": "preship",
         "direction": None},
        {"token_id": "t1", "fact_id": "pool.post", "expected_metric_key": "postship",
         "direction": None}])
    r = run_gate(_bundle([c]), _facts())
    assert any(f["code"] == "SUMMED_POOLS" for f in r.hard_failures)


def test_dangling_callback_hard_fails():
    r = run_gate(_bundle([_claim()], sections=[{
        "section_id": "core_business", "title": "大盘", "claims": [_claim()],
        "table_ref": None, "chart_ref": None, "spine_callbacks": ["L_ghost"]}]), _facts())
    assert any(f["code"] == "DANGLING_CALLBACK" for f in r.hard_failures)


def test_mechanism_confidence_capped_to_weak():
    c = _claim(claim_kind="mechanism", confidence="强", entity_refs=["鱼盘"],
               number_tokens=[{"token_id": "t0", "fact_id": "sku.hot",
                               "expected_metric_key": "sku_gmv", "direction": "up"}],
               sentence="兴安岭之夜大概率带动鱼盘 {t0}。",
               causal_link={"from_entity_type": "note", "to_entity_type": "sku",
                            "quantified": False})
    r = run_gate(_bundle([c]), _facts())
    assert r.status == "PASS"
    capped = r.bundle["sections"][0]["claims"][0]
    assert capped["confidence"] == "弱"
    assert any(w["code"] == "CONFIDENCE_CAPPED" for w in r.warnings)


def test_measurement_confidence_capped_by_weak_anchor():
    c = _claim(confidence="强", number_tokens=[{"token_id": "t0", "fact_id": "sku.hot",
                                               "expected_metric_key": "sku_gmv", "direction": "up"}],
               sentence="某测量 {t0}。")
    r = run_gate(_bundle([c]), _facts())
    # sku.hot: evidence weak, descriptive medium -> allowed 中; stated 强 -> capped to 中
    assert r.bundle["sections"][0]["claims"][0]["confidence"] == "中"


def test_untagged_mechanism_warns():
    c = _claim(claim_kind="mechanism", confidence="", entity_refs=["鱼盘"],
               causal_link={"from_entity_type": "note", "to_entity_type": "sku",
                            "quantified": False})
    r = run_gate(_bundle([c]), _facts())
    assert any(w["code"] == "UNTAGGED_MECHANISM" for w in r.warnings)


def test_missed_mechanism_warns_when_entity_fact_unclaimed():
    # sku.hot has entity_type='sku' but no mechanism claim references it
    r = run_gate(_bundle([_claim()]), _facts())
    assert any(w["code"] == "MISSED_MECHANISM" for w in r.warnings)


def test_unlabeled_sizing_warns():
    c = _claim(claim_kind="sizing", confidence="中",
               number_tokens=[{"token_id": "t0", "fact_id": "pool.post",
                               "expected_metric_key": "postship", "direction": None}],
               sentence="发货后池约 {t0}。")  # pool.post has no assumption label
    r = run_gate(_bundle([c]), _facts())
    assert any(w["code"] == "UNLABELED_SIZING" for w in r.warnings)


def test_missing_spine_callback_warns():
    r = run_gate(_bundle([_claim()], sections=[{
        "section_id": "core_business", "title": "大盘", "claims": [_claim()],
        "table_ref": None, "chart_ref": None, "spine_callbacks": []}]), _facts())
    assert any(w["code"] == "MISSING_SPINE_CALLBACK" for w in r.warnings)


def test_redundant_headline_warns():
    c = _claim(sentence="GMV {t0}。")
    r = run_gate(_bundle([c], headline="GMV {t0}。"), _facts())
    assert any(w["code"] == "REDUNDANT_HEADLINE" for w in r.warnings)


def test_input_bundle_not_mutated():
    b = _bundle([_claim(claim_kind="mechanism", confidence="强", entity_refs=["鱼盘"],
                        causal_link={"from_entity_type": "note", "to_entity_type": "sku",
                                     "quantified": False})])
    snapshot = copy.deepcopy(b)
    run_gate(b, _facts())
    assert b == snapshot  # capping returns a new bundle; input untouched
