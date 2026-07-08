# tests/test_reporting_first_screen.py
from xhs_ceramics_analytics.reporting.first_screen import first_screen_markdown


def _claim(cid, sentence, conf="强"):
    return {"claim_id": cid, "rendered_sentence": sentence, "confidence": conf}


def test_renders_headline_spine_panel_actions():
    bundle = {
        "headline": "6月人均产出走低，主要是客单价与转化拖累。",
        "first_screen": {
            "spine": [_claim("s0", "5→6月人均产出从 ¥10.0 回落到 ¥8.7（与后台4.6%转化同口径）。")],
            "panel": [_claim("p0", "退款总额 ¥20.8万，发货前占 ¥12.9万。", "中")],
            "actions": ["本周先核对千帆是否支持发货前拦截。"],
        },
    }
    md = first_screen_markdown(bundle)
    assert "6月人均产出走低" in md
    assert "¥10.0 回落到 ¥8.7" in md
    assert "退款总额 ¥20.8万" in md
    # D2: the 首屏 no longer suffixes every teaser line with its （强/中/弱）tag —
    # the "每条结论后跟个弱" repetition is gone; confidence now lives on a per-section
    # pill in the body, not after each 引子 line.
    assert "（中）" not in md
    assert "（强）" not in md
    assert "本周先核对千帆是否支持发货前拦截。" in md


def test_content_driven_omits_empty_blocks():
    bundle = {"headline": "只有主线。", "first_screen": {"spine": [], "panel": [], "actions": []}}
    md = first_screen_markdown(bundle)
    assert "只有主线。" in md
    assert "盘面" not in md  # no empty 盘面 heading
    assert "本周重点" not in md


def test_never_raises_on_missing_keys():
    assert isinstance(first_screen_markdown({}), str)
