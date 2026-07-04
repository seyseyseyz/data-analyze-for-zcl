from xhs_ceramics_analytics.reporting.field_labels import FIELD_LABELS
from xhs_ceramics_analytics.reporting.html import _field_help, _field_label

_NEW_LABELS = {
    "net_gmv_pay": "退款后GMV",
    "refund_rate_pay": "退款率(支付时间)",
    "click_to_order": "点击到订单",
    "gmv_per_click": "每次点击GMV",
    "note_gmv": "笔记支付金额",
    "category_l2": "二级品类",
    "add_to_cart_users": "加购人数",
}


_GENERIC_HELP_FALLBACK = "原始数据字段，保留用于查数和追溯。"


def test_new_metric_labels_render_chinese():
    for key, label in _NEW_LABELS.items():
        assert _field_label(key) == label


def test_new_metric_labels_have_specific_help_text():
    # each key must resolve to its OWN help sentence, not the generic fallback
    # (which _field_help returns for any unknown key) — proving the entry landed.
    for key in _NEW_LABELS:
        help_text = _field_help(key)
        assert help_text and help_text != _GENERIC_HELP_FALLBACK
        assert help_text.endswith("。")


# --- 病根 C / Task C2: 词表说人话 —— 集中度/基线标签不得外泄统计术语 ---

_STAT_JARGON = ("基尼", "赫芬达尔", "Wilson", "分位", "FDR", "p 值", "p值", "斜率")


def test_reader_field_labels_avoid_statistical_jargon():
    # The reader-facing *label* (the first tuple element, shown in 关键数字) must
    # read as merchant business language. Jargon (基尼/赫芬达尔/…) belongs only in
    # the methodology appendix, never as the headline label of a number.
    offenders = {
        key: label
        for key, (label, _help) in FIELD_LABELS.items()
        if any(token in label for token in _STAT_JARGON)
    }
    assert not offenders, f"字段标签仍含统计术语：{offenders}"


def test_concentration_labels_read_as_business_language():
    # gini/hhi 键改说人话："集中度"而非"基尼系数/赫芬达尔指数"。
    for key in ("gmv_gini", "gmv_hhi", "note_gmv_gini", "note_gmv_hhi"):
        label, help_text = FIELD_LABELS[key]
        assert "集中" in label
        assert "基尼" not in label and "赫芬达尔" not in label
        assert help_text.endswith("。")


def test_baseline_labels_say_overall_not_bare_baseline():
    # #18 基线值: 商家看不懂"基线"。改成"整体X"，help 说明是对比基准。
    for key in (
        "baseline_effectiveness",
        "click_baseline",
        "conversion_baseline",
        "baseline_conversion",
        "baseline_refund_rate",
        "baseline_rate",
    ):
        label, _help = FIELD_LABELS[key]
        assert "整体" in label
        assert label != key
