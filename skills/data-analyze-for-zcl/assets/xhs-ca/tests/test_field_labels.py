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
