# tests/test_reporting_narrative_render.py
import pytest

from xhs_ceramics_analytics.reporting import narrative_render as nr


def _facts():
    return {
        "facts_hash": "h",
        "facts": {
            "m.may": {"rendered": "¥10.0", "metric_key": "pvg_may", "direction": None,
                      "pool_id": None, "entity_type": None, "evidence_strength": "strong",
                      "descriptive_reliability": "high", "assumption": None},
            "m.jun": {"rendered": "¥8.7", "metric_key": "pvg_jun", "direction": "down",
                      "pool_id": None, "entity_type": None, "evidence_strength": "strong",
                      "descriptive_reliability": "high", "assumption": None},
        },
        "entity_registry": [], "absent_link_registry": [], "non_additive_ledger": {},
    }


def _claim():
    return {"claim_id": "c0", "section_id": "core_business", "claim_kind": "measurement",
            "sentence": "人均产出从 {t0} 回落到 {t1}。", "number_tokens": [
                {"token_id": "t0", "fact_id": "m.may", "expected_metric_key": "pvg_may",
                 "direction": None},
                {"token_id": "t1", "fact_id": "m.jun", "expected_metric_key": "pvg_jun",
                 "direction": "down"}],
            "entity_refs": [], "confidence": "强", "causal_link": None}


def _bundle():
    return {"facts_hash": "h", "headline": "人均产出走低。",
            "first_screen": {"spine": [], "panel": [], "actions": ["核对千帆能力。"]},
            "spine_final": {"backbone": [{"link_id": "L1", "from": "t", "to": "g",
                                          "anchor_fact_ids": ["m.jun"],
                                          "relation": "accounting_identity"}]},
            "sections": [{"section_id": "core_business", "title": "生意大盘·月对月",
                          "claims": [_claim()], "table_ref": None, "chart_ref": None,
                          "spine_callbacks": ["L1"]}],
            "cannot_say": ["笔记→订单归因：平台无链路。"]}


def test_fill_sentence_uses_only_rendered_strings():
    filled = nr.fill_sentence(_claim()["sentence"], _claim()["number_tokens"], _facts()["facts"])
    assert filled == "人均产出从 ¥10.0 回落到 ¥8.7。"


def test_render_draft_adds_rendered_sentence():
    drafted = nr.render_draft(_bundle(), _facts())
    claim = drafted["sections"][0]["claims"][0]
    assert claim["rendered_sentence"] == "人均产出从 ¥10.0 回落到 ¥8.7。"


def test_bundle_to_markdown_includes_all_sections():
    md = nr.bundle_to_markdown(nr.render_draft(_bundle(), _facts()), _facts(), title="测试报告")
    assert "人均产出从 ¥10.0 回落到 ¥8.7。" in md
    assert "生意大盘·月对月" in md
    assert "暂时答不了的问题" in md
    assert "笔记→订单归因：平台无链路。" in md


def test_apply_continuity_edit_prose_only():
    drafted = nr.render_draft(_bundle(), _facts())
    edits = [{"claim_id": "c0", "old": "人均产出从 ¥10.0 回落到 ¥8.7。",
              "new": "人均产出由 ¥10.0 滑到 ¥8.7。"}]
    out = nr.apply_continuity_edits(drafted, edits)
    assert out["sections"][0]["claims"][0]["rendered_sentence"] == "人均产出由 ¥10.0 滑到 ¥8.7。"


def test_apply_continuity_edit_rejects_new_digit():
    drafted = nr.render_draft(_bundle(), _facts())
    edits = [{"claim_id": "c0", "old": "人均产出从 ¥10.0 回落到 ¥8.7。",
              "new": "人均产出从 ¥10.0 回落到 ¥8.7，跌了 15%。"}]
    with pytest.raises(ValueError):
        nr.apply_continuity_edits(drafted, edits)


def test_apply_continuity_edit_rejects_absent_old():
    drafted = nr.render_draft(_bundle(), _facts())
    with pytest.raises(ValueError):
        nr.apply_continuity_edits(drafted, [{"claim_id": "c0", "old": "不存在的句子", "new": "x"}])


def test_render_frozen_roundtrip():
    drafted = nr.render_draft(_bundle(), _facts())
    frozen = {"schema_version": "v", "facts_hash": "h", "renderer_version": "r",
              "narrative_bundle": drafted}
    md, html = nr.render_frozen(frozen, _facts())
    assert "人均产出从 ¥10.0 回落到 ¥8.7。" in md
    assert "<html" in html.lower()


def test_render_frozen_preserves_continuity_edits():
    # A frozen bundle carries continuity-edited prose; re-rendering it at 0 LLM calls
    # must serve that prose, NOT re-fill from the raw {tN} sentence (which would revert it).
    drafted = nr.render_draft(_bundle(), _facts())
    edited = nr.apply_continuity_edits(drafted, [
        {"claim_id": "c0", "old": "人均产出从 ¥10.0 回落到 ¥8.7。",
         "new": "人均产出由 ¥10.0 一路滑到 ¥8.7。"}])
    frozen = {"schema_version": "v", "facts_hash": "h", "renderer_version": "r",
              "narrative_bundle": edited}
    md, _ = nr.render_frozen(frozen, _facts())
    assert "一路滑到" in md          # the frozen polished prose survives
    assert "回落到" not in md        # the raw-token wording did not come back


def test_render_frozen_rejects_hash_mismatch():
    drafted = nr.render_draft(_bundle(), _facts())
    frozen = {"schema_version": "v", "facts_hash": "STALE", "renderer_version": "r",
              "narrative_bundle": drafted}
    with pytest.raises(ValueError):
        nr.render_frozen(frozen, _facts())


def test_skeleton_markdown_has_banner():
    from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
    from xhs_ceramics_analytics.evidence import EvidenceStrength
    result = AnalysisResult(task_id="core_business_diagnosis", title="大盘",
                            findings=[Finding(title="结论", conclusion="人均产出走低。",
                                              evidence_strength=EvidenceStrength.STRONG)])
    md = nr.skeleton_markdown([result], title="骨架报告")
    assert "确定性骨架版" in md
    assert "人均产出走低。" in md


# ---- #8: the headline must not be echoed verbatim across the report --------

def _headline_echo_bundle():
    H = "核心结论：人均产出走低。"
    claim = lambda cid, s: {  # noqa: E731 - compact test fixture
        "claim_id": cid, "section_id": "core", "claim_kind": "measurement",
        "sentence": s, "rendered_sentence": s, "number_tokens": [],
        "entity_refs": [], "confidence": "强", "causal_link": None,
    }
    return H, {
        "facts_hash": "h",
        "headline": H,
        # the same hook the agent also dropped into the 首屏 teaser
        "first_screen": {"spine": [claim("s0", H)], "panel": [], "actions": []},
        # ...and selected as the opening step of the 跨模块主线 thesis
        "mechanism": [{"claim_id": "c1"}],
        "sections": [
            {"section_id": "core", "title": "生意大盘",
             "claims": [claim("c1", H), claim("c2", "退款率上升。")]},
        ],
        "cannot_say": [],
    }


def test_headline_is_not_repeated_verbatim():
    headline, bundle = _headline_echo_bundle()
    md = nr.bundle_to_markdown(nr.render_draft(bundle, _facts()), _facts(), title="报告")
    # The headline shows exactly once (as the 首屏 bold hook); its verbatim echoes in the
    # spine teaser, the 跨模块主线 step and the section claim are all suppressed.
    assert md.count(headline) == 1
    # distinct content is untouched
    assert "退款率上升。" in md
