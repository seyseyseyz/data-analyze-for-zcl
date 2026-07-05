import re

from markupsafe import Markup

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength
from xhs_ceramics_analytics.reporting import charts


def _result(task_id, strength, tables):
    return AnalysisResult(
        task_id=task_id,
        title="t",
        findings=[Finding(title="f", conclusion="c", evidence_strength=strength)],
        tables=tables,
    )


def test_chart_badge_reads_folded_confidence_not_raw_causal_tier():
    # The design bug: a large-sample observational finding is causally WEAK by
    # construction, yet its prose shows the folded "置信度 高" (descriptive axis).
    # The chart badge must speak the SAME word — never contradict the section by
    # displaying the raw causal tier "可信度 弱" beside a "置信度 高" conclusion.
    result = AnalysisResult(
        task_id="core_business_diagnosis",
        title="t",
        findings=[Finding(
            title="f", conclusion="c",
            evidence_strength=EvidenceStrength.WEAK,
            descriptive_reliability=DescriptiveReliability.HIGH,
        )],
        tables={"business_trend": [
            {"date": "2026-04-01", "gmv": 1000.0, "is_changepoint": False},
            {"date": "2026-04-02", "gmv": 1500.0, "is_changepoint": True},
        ]},
    )
    html = charts.for_result(result)
    assert "置信度 高" in html      # folded reader-confidence, consistent with the prose
    assert "可信度" not in html     # the retired methodology term never surfaces
    assert "置信度 弱" not in html  # the raw causal tier is a footnote, not the headline


def test_for_result_returns_markup_empty_for_unknown_task():
    result = _result("account_baseline", EvidenceStrength.MEDIUM, {})
    out = charts.for_result(result)
    assert isinstance(out, Markup)
    assert out == ""


def test_for_result_suppresses_not_judgable():
    result = _result(
        "cover_style_effect",
        EvidenceStrength.NOT_JUDGABLE,
        {"cover_effects": [{"composition_type": "flatlay", "notes": 3,
                             "avg_reads": 900.0, "avg_collects": 40.0}]},
    )
    assert charts.for_result(result) == ""


def test_for_result_isolates_builder_exceptions(monkeypatch):
    result = _result("cover_style_effect", EvidenceStrength.MEDIUM, {"cover_effects": [{}]})

    def boom(*args, **kwargs):
        raise ValueError("bad row")

    monkeypatch.setitem(charts._BUILDERS, "cover_style_effect", boom)
    assert charts.for_result(result) == ""


def test_escape_neutralizes_markup():
    assert "<script>" not in charts._esc("<script>alert(1)</script>")
    assert "&lt;script&gt;" in charts._esc("<script>alert(1)</script>")


def test_empty_state_carries_message():
    svg = charts._frame(charts._empty_state(640, 200), 640, 200)
    assert "数据不足，无法判断" in svg
    assert svg.startswith("<svg")


def test_evidence_distribution_title_reads_confidence_not_reliability_term():
    # The segments are the folded 置信度 levels (高/中/低), so the chart title must
    # say 置信度 too — never the retired 可信度 term, which would re-split the one
    # confidence vocabulary the rest of the report was unified onto.
    counts = [{"value": "high", "label": "高", "count": 3, "help": "h"}]
    svg = charts.evidence_distribution(counts)
    assert "结论置信度分布" in svg
    assert "可信度" not in svg


def test_evidence_distribution_renders_segments_with_counts():
    counts = [
        {"value": "strong", "label": "强", "count": 2, "help": "h"},
        {"value": "medium", "label": "中", "count": 3, "help": "h"},
        {"value": "weak", "label": "弱", "count": 1, "help": "h"},
        {"value": "not_judgable", "label": "不可判断", "count": 4, "help": "h"},
    ]
    svg = charts.evidence_distribution(counts)
    assert "<svg" in svg
    assert "var(--green-bg)" in svg   # strong+medium share green
    # weak reads neutral-grey, not warning-yellow: an observational finding is
    # "directional", not "broken" (matches the report's tag palette).
    assert "var(--neutral-bg)" in svg  # weak
    assert "var(--yellow-bg)" not in svg
    assert "var(--red-bg)" in svg     # not_judgable
    assert "强 2" in svg and "中 3" in svg and "弱 1" in svg and "不可判断 4" in svg


def test_evidence_distribution_empty_when_no_findings():
    counts = [{"value": v, "label": v, "count": 0, "help": "h"}
              for v in ("strong", "medium", "weak", "not_judgable")]
    assert charts.evidence_distribution(counts) == ""


def test_evidence_distribution_escapes_and_has_no_raw_float():
    counts = [{"value": "strong", "label": "强", "count": 1, "help": "h"}]
    svg = charts.evidence_distribution(counts)
    assert "0.333333" not in svg  # widths are formatted, never raw ratios


def test_cover_chart_has_two_measure_panels_and_zero_baseline():
    result = _result(
        "cover_style_effect",
        EvidenceStrength.MEDIUM,
        {"cover_effects": [
            {"composition_type": "flatlay", "notes": 5, "avg_reads": 1200.0, "avg_collects": 48.0},
            {"composition_type": "lifestyle", "notes": 4, "avg_reads": 800.0, "avg_collects": 60.0},
        ]},
    )
    html = charts.for_result(result)
    assert "平均阅读数" in html and "平均收藏数" in html
    assert 'class="chart-multiples"' in html
    assert "置信度 中" in html          # folded reader-confidence badge present
    assert html.count("<svg") == 2       # one panel per measure
    assert 'class="ca-axis"' in html     # zero baseline is actually drawn


def test_cover_chart_shows_empty_state_for_all_null_measure():
    result = _result(
        "cover_style_effect",
        EvidenceStrength.MEDIUM,
        {"cover_effects": [
            {"composition_type": "flatlay", "notes": 5, "avg_reads": 1200.0, "avg_collects": None},
        ]},
    )
    html = charts.for_result(result)
    assert "数据不足，无法判断" in html   # the collects panel degrades honestly


def test_cover_chart_weak_evidence_is_de_emphasized():
    result = _result(
        "cover_style_effect",
        EvidenceStrength.WEAK,
        {"cover_effects": [
            {"composition_type": "flatlay", "notes": 2, "avg_reads": 300.0, "avg_collects": 9.0},
        ]},
    )
    html = charts.for_result(result)
    # WEAK causal + no descriptive-reliability estimate folds to 低 (not the raw 弱 tier).
    assert "置信度 低" in html
    assert "url(#ca-hatch)" in html


def test_copy_chart_uses_copy_angle_column():
    result = _result(
        "copy_angle_effect",
        EvidenceStrength.MEDIUM,
        {"copy_effects": [
            {"copy_angle": "gift", "notes": 6, "avg_reads": 1100.0, "avg_collects": 70.0},
        ]},
    )
    html = charts.for_result(result)
    assert "送礼角度" in html          # value_label("gift")
    assert "<svg" in html


def test_comment_demand_share_bar_uses_percent_labels():
    result = _result(
        "comment_demand_mining",
        EvidenceStrength.MEDIUM,
        {"comment_demands": [
            {"demand_group": "capacity", "comments": 12, "notes": 5,
             "comment_share": 0.48, "example_comments": ["多大容量"]},
            {"demand_group": "price", "comments": 8, "notes": 4,
             "comment_share": 0.32, "example_comments": ["多少钱"]},
            {"demand_group": "other", "comments": 5, "notes": 3,
             "comment_share": 0.20, "example_comments": ["好看"]},
        ]},
    )
    html = charts.for_result(result)
    assert "<svg" in html
    assert "48%" in html                # format_percent(0.48)
    assert "容量/尺寸需求" in html        # value_label("capacity")
    assert "0.48" not in html           # never a raw ratio


def test_comment_demand_skips_zero_comment_groups():
    result = _result(
        "comment_demand_mining",
        EvidenceStrength.WEAK,
        {"comment_demands": [
            {"demand_group": "capacity", "comments": 3, "notes": 1,
             "comment_share": 1.0, "example_comments": []},
            {"demand_group": "gift", "comments": 0, "notes": 0,
             "comment_share": 0.0, "example_comments": []},
        ]},
    )
    html = charts.for_result(result)
    assert "置信度 低" in html            # folded reader-confidence badge
    assert "送礼角度" not in html         # zero-comment group omitted


_WINDOWS = ("d0_1_units", "d1_3_units", "d4_7_units", "d8_14_units")


def _rw(note_id, sku_id, vals):
    row = {"note_id": note_id, "sku_id": sku_id, "publish_time": "2026-06-01"}
    row.update(dict(zip(_WINDOWS, vals)))
    return row


def test_response_curve_draws_lines_over_four_windows():
    result = _result(
        "content_response_curve",
        EvidenceStrength.MEDIUM,
        {"response_windows": [
            _rw("n1", "s1", [2.0, 5.0, 3.0, 1.0]),
            _rw("n2", "s1", [0.0, 4.0, 6.0, 2.0]),
        ]},
    )
    html = charts.for_result(result)
    assert "<svg" in html
    assert "<path" in html                 # multi-point series draw a line
    assert "发布后 0-1 天" in html          # value_label("d0_1")
    assert "发布后 8-14 天" in html


def test_response_curve_single_point_series_draws_dot_not_line():
    result = _result(
        "content_response_curve",
        EvidenceStrength.WEAK,
        {"response_windows": [
            _rw("n1", "s1", [3.0, None, None, None]),
        ]},
    )
    html = charts.for_result(result)
    assert "<circle" in html
    assert "<path" not in html             # one observed point never draws a line
    assert "置信度 低" in html


def test_response_curve_empty_when_no_rows():
    result = _result("content_response_curve", EvidenceStrength.MEDIUM,
                     {"response_windows": []})
    assert charts.for_result(result) == ""


def test_response_curve_weak_evidence_dashes_aggregate_line():
    result = _result(
        "content_response_curve",
        EvidenceStrength.WEAK,
        {"response_windows": [
            _rw("n1", "s1", [2.0, 5.0, 3.0, 1.0]),
            _rw("n2", "s1", [0.0, 4.0, 6.0, 2.0]),
        ]},
    )
    html = charts.for_result(result)
    assert 'stroke-dasharray="4 3"' in html   # weak aggregate is honestly de-emphasized


def test_response_curve_marker_radius_meets_accessibility_floor():
    result = _result(
        "content_response_curve",
        EvidenceStrength.MEDIUM,
        {"response_windows": [
            _rw("n1", "s1", [2.0, 5.0, 3.0, 1.0]),
            _rw("n2", "s1", [0.0, 4.0, 6.0, 2.0]),
        ]},
    )
    html = charts.for_result(result)
    assert 'r="4"' in html
    assert 'r="3.5"' not in html


def test_opportunity_scatter_plots_only_rows_with_sales():
    result = _result(
        "product_opportunity_matrix",
        EvidenceStrength.MEDIUM,
        {"product_opportunities": [
            {"sku_id": "a", "sku_name": "青瓷杯", "units": 12.0, "gmv": 480.0,
             "opportunity_type": "sales_response_present"},
            {"sku_id": "b", "sku_name": "礼盒", "units": 1.0, "gmv": 60.0,
             "opportunity_type": "needs_more_content_or_data"},
            {"sku_id": "c", "sku_name": "无数据", "units": None, "gmv": None,
             "opportunity_type": "needs_sales_data"},
        ]},
    )
    html = charts.for_result(result)
    assert "<circle" in html
    assert "青瓷杯" in html
    assert "无数据" not in html          # null units/gmv row is not plotted


def test_opportunity_scatter_uses_shape_not_hue_for_type():
    result = _result(
        "product_opportunity_matrix",
        EvidenceStrength.MEDIUM,
        {"product_opportunities": [
            {"sku_id": "a", "sku_name": "A", "units": 12.0, "gmv": 480.0,
             "opportunity_type": "sales_response_present"},
            {"sku_id": "b", "sku_name": "B", "units": 1.0, "gmv": 60.0,
             "opportunity_type": "needs_more_content_or_data"},
        ]},
    )
    html = charts.for_result(result)
    # hollow marks paint their interior with the surface token, not a new hue
    assert "var(--surface)" in html
    assert "var(--ink-strong)" in html


def test_opportunity_scatter_weak_evidence_uses_gray_ring():
    result = _result(
        "product_opportunity_matrix",
        EvidenceStrength.WEAK,
        {"product_opportunities": [
            {"sku_id": "a", "sku_name": "A", "units": 12.0, "gmv": 480.0,
             "opportunity_type": "sales_response_present"},
        ]},
    )
    html = charts.for_result(result)
    assert 'stroke="var(--muted)"' in html   # weak sample -> gray ring, not a confident tone


def test_opportunity_scatter_filled_point_uses_surface_ring_when_confident():
    result = _result(
        "product_opportunity_matrix",
        EvidenceStrength.MEDIUM,
        {"product_opportunities": [
            {"sku_id": "a", "sku_name": "A", "units": 12.0, "gmv": 480.0,
             "opportunity_type": "sales_response_present"},
        ]},
    )
    html = charts.for_result(result)
    assert 'stroke="var(--surface)"' in html  # 2px surface ring separates overlapping marks


def test_opportunity_scatter_max_x_label_flips_to_avoid_clipping():
    result = _result(
        "product_opportunity_matrix",
        EvidenceStrength.MEDIUM,
        {"product_opportunities": [
            {"sku_id": "a", "sku_name": "小杯子", "units": 1.0, "gmv": 50.0,
             "opportunity_type": "sales_response_present"},
            {"sku_id": "b", "sku_name": "超长商品名称示例文本", "units": 20.0, "gmv": 900.0,
             "opportunity_type": "sales_response_present"},
        ]},
    )
    html = charts.for_result(result)
    assert 'text-anchor="end"' in html   # rightmost point's label grows inward, not off-canvas


def test_paid_scatter_suppressed_when_no_spend():
    result = _result(
        "paid_traffic_efficiency",
        EvidenceStrength.WEAK,
        {"paid_traffic_efficiency": [
            {"campaign_name_optional": "c1", "spend": 0.0, "roas_calc": None,
             "gmv_optional": None, "budget_action": "needs_data", "paid_active_days": 1},
        ]},
    )
    assert charts.for_result(result) == ""


def test_paid_scatter_colors_budget_action_status():
    result = _result(
        "paid_traffic_efficiency",
        EvidenceStrength.MEDIUM,
        {"paid_traffic_efficiency": [
            {"campaign_name_optional": "c1", "spend": 300.0, "roas_calc": 4.0,
             "gmv_optional": 1200.0, "budget_action": "increase", "paid_active_days": 5},
            {"campaign_name_optional": "c2", "spend": 250.0, "roas_calc": 0.5,
             "gmv_optional": 125.0, "budget_action": "reduce", "paid_active_days": 4},
        ]},
    )
    html = charts.for_result(result)
    assert "<circle" in html
    assert "var(--green-text)" in html   # increase -> good
    assert "var(--red-text)" in html     # reduce -> bad
    assert "增加预算" in html            # value_label("increase")


def test_paid_scatter_needs_data_is_neutral_hollow():
    result = _result(
        "paid_traffic_efficiency",
        EvidenceStrength.MEDIUM,
        {"paid_traffic_efficiency": [
            {"campaign_name_optional": "c1", "spend": 300.0, "roas_calc": 2.0,
             "gmv_optional": 600.0, "budget_action": "needs_data", "paid_active_days": 5},
        ]},
    )
    html = charts.for_result(result)
    assert "需要补数据" in html                        # value_label("needs_data")
    assert 'fill="var(--ink-strong)"' not in html      # never a confident-looking mark


def test_demand_funnel_draws_two_stage_funnel_and_trend():
    result = _result(
        "demand_funnel_diagnosis",
        EvidenceStrength.WEAK,
        {"demand_funnel_trend": [
            {"date": "2026-04-01", "add_to_cart_users": 100.0, "paid_buyers": 20.0,
             "cart_to_pay": 0.20},
            {"date": "2026-04-02", "add_to_cart_users": 120.0, "paid_buyers": 30.0,
             "cart_to_pay": 0.25},
            {"date": "2026-04-03", "add_to_cart_users": 80.0, "paid_buyers": 24.0,
             "cart_to_pay": 0.30},
        ]},
    )
    html = charts.for_result(result)
    assert "加购人数" in html and "成交人数" in html
    assert "加购→成交转化率趋势" in html
    assert "<path" in html                 # cart_to_pay trend draws a line
    assert "置信度 低" in html
    assert "n=300" in html                 # total add_to_cart_users, not a row count


def test_demand_funnel_empty_when_no_trend_table():
    result = _result("demand_funnel_diagnosis", EvidenceStrength.MEDIUM, {})
    assert charts.for_result(result) == ""


def test_demand_funnel_survives_null_cart_to_pay():
    result = _result(
        "demand_funnel_diagnosis",
        EvidenceStrength.MEDIUM,
        {"demand_funnel_trend": [
            {"date": "2026-04-01", "add_to_cart_users": 50.0, "paid_buyers": 10.0,
             "cart_to_pay": None},
        ]},
    )
    html = charts.for_result(result)
    assert "加购人数" in html               # funnel still renders
    assert "数据不足，无法判断" in html      # the trend panel degrades honestly


def test_core_business_draws_gmv_trend_with_changepoint():
    result = _result(
        "core_business_diagnosis",
        EvidenceStrength.MEDIUM,
        {"business_trend": [
            {"date": "2026-04-01", "gmv": 1000.0, "is_changepoint": False},
            {"date": "2026-04-02", "gmv": 1500.0, "is_changepoint": True},
            {"date": "2026-04-03", "gmv": 1200.0, "is_changepoint": False},
        ]},
    )
    html = charts.for_result(result)
    assert "成交金额" in html               # timeseries title
    assert "<path" in html
    assert "结构转折" in html               # changepoint annotation drawn
    assert "置信度 中" in html


def test_core_business_empty_when_no_trend():
    result = _result("core_business_diagnosis", EvidenceStrength.MEDIUM,
                     {"business_trend": []})
    assert charts.for_result(result) == ""


def test_channel_structure_bars_use_carrier_zh_labels():
    result = _result(
        "channel_structure_diagnosis",
        EvidenceStrength.MEDIUM,
        {"channel_scale": [
            {"carrier": "note", "carrier_zh": "笔记", "gmv": 8000.0},
            {"carrier": "card", "carrier_zh": "商品卡", "gmv": 3000.0},
        ]},
    )
    html = charts.for_result(result)
    assert "笔记" in html and "商品卡" in html
    assert "<rect" in html
    assert html.index("笔记") < html.index("商品卡")   # ranked by gmv desc


def test_channel_structure_empty_when_absent():
    result = _result("channel_structure_diagnosis", EvidenceStrength.MEDIUM, {})
    assert charts.for_result(result) == ""


def test_sku_structure_bars_rank_category_l2_by_gmv():
    result = _result(
        "sku_structure_diagnosis",
        EvidenceStrength.MEDIUM,
        {"sku_category_l2_mix": [
            {"category_l2": "马克杯", "gmv": 5000.0},
            {"category_l2": "盖碗", "gmv": 9000.0},
        ]},
    )
    html = charts.for_result(result)
    assert "盖碗" in html and "马克杯" in html
    assert html.index("盖碗") < html.index("马克杯")    # highest gmv sits on top
    assert "<rect" in html


def test_sku_structure_empty_when_absent():
    result = _result("sku_structure_diagnosis", EvidenceStrength.MEDIUM, {})
    assert charts.for_result(result) == ""


def test_refund_root_cause_bars_use_refund_orders():
    result = _result(
        "refund_root_cause_diagnosis",
        EvidenceStrength.MEDIUM,
        {"refund_by_category": [
            {"category_l1": "茶具", "paid_orders": 100.0, "refund_orders": 12.0,
             "refund_rate": 0.12},
            {"category_l1": "餐具", "paid_orders": 80.0, "refund_orders": 4.0,
             "refund_rate": 0.05},
        ]},
    )
    html = charts.for_result(result)
    assert "茶具" in html and "餐具" in html
    assert html.index("茶具") < html.index("餐具")     # ranked by refund_orders desc
    assert "<rect" in html


def test_refund_root_cause_empty_when_absent():
    result = _result("refund_root_cause_diagnosis", EvidenceStrength.MEDIUM, {})
    assert charts.for_result(result) == ""


def test_audience_structure_prefers_conversion_comparison():
    result = _result(
        "audience_structure_diagnosis",
        EvidenceStrength.MEDIUM,
        {"audience_conversion_comparison": [
            {"audience_type": "新客", "visitors": 500.0, "payers": 25.0, "conversion": 0.05},
            {"audience_type": "老客", "visitors": 200.0, "payers": 40.0, "conversion": 0.20},
        ]},
    )
    html = charts.for_result(result)
    assert "新客" in html and "老客" in html
    assert "20%" in html                   # format_percent(0.20)


def test_audience_structure_falls_back_to_composition():
    result = _result(
        "audience_structure_diagnosis",
        EvidenceStrength.MEDIUM,
        {"audience_composition": [
            {"audience_segment": "礼品客", "gmv": 3000.0, "gmv_share": 0.6},
            {"audience_segment": "自用客", "gmv": 2000.0, "gmv_share": 0.4},
        ]},
    )
    html = charts.for_result(result)
    assert "礼品客" in html and "自用客" in html
    assert "60%" in html                   # gmv_share as percent when no conversion


def test_audience_structure_empty_when_absent():
    result = _result("audience_structure_diagnosis", EvidenceStrength.MEDIUM, {})
    assert charts.for_result(result) == ""


def test_short_date_trims_iso_and_passes_through_non_iso():
    # Dates arrive already normalized to ISO from the analysis modules; _short_date
    # only strips the year and never re-derives a compact YYYYMMDD form.
    assert charts._short_date("2026-06-30") == "06-30"   # ISO → MM-DD
    assert charts._short_date("20260630") == "20260630"  # non-ISO left untouched
    assert charts._short_date("第 12 周") == "第 12 周"    # anything else untouched


def test_truncate_clips_long_label_with_ellipsis():
    assert charts._truncate("盖碗", 200) == "盖碗"          # fits -> unchanged
    out = charts._truncate("超长二级品类名称示例文本内容", 90)
    assert out.endswith("…")
    assert charts._legend_text_w(out) <= 90


def _num_label_right_edges(html):
    """Right edge (x + estimated width) of every left-anchored ca-num label."""
    edges = []
    for m in re.finditer(r'<text x="([-\d.]+)"(?![^>]*text-anchor)[^>]*class="ca-num"[^>]*>([^<]*)</text>',
                          html):
        x = float(m.group(1))
        edges.append(x + charts._legend_text_w(m.group(2)))
    return edges


def test_hbar_value_label_stays_within_bounds_for_large_numbers():
    # a full-length bar with a wide 千分位 number used to run off the right edge
    result = _result(
        "channel_structure_diagnosis",
        EvidenceStrength.MEDIUM,
        {"channel_scale": [
            {"carrier": "note", "carrier_zh": "笔记", "gmv": 839335.64},
            {"carrier": "card", "carrier_zh": "商品卡", "gmv": 12000.0},
        ]},
    )
    html = charts.for_result(result)
    # GMV renders as whole yuan (shared format_money) — the wide 千分位 label is
    # 839,336, and the layout must still keep its right edge within the viewBox.
    assert "839,336" in html
    assert "839,335.64" not in html
    assert _num_label_right_edges(html), "expected value labels to be present"
    assert max(_num_label_right_edges(html)) <= 640 + 1   # within the 640-wide viewBox


def test_hbar_long_category_label_is_truncated_but_full_in_title():
    result = _result(
        "sku_structure_diagnosis",
        EvidenceStrength.MEDIUM,
        {"sku_category_l2_mix": [
            {"category_l2": "非常长的二级品类名称用于测试截断行为", "gmv": 9000.0},
        ]},
    )
    html = charts.for_result(result)
    assert "…" in html                                    # visible label clipped
    assert "非常长的二级品类名称用于测试截断行为" in html    # full name kept in <title>


def test_builder_escapes_injected_text():
    result = _result(
        "product_opportunity_matrix",
        EvidenceStrength.MEDIUM,
        {"product_opportunities": [
            {"sku_id": "x", "sku_name": "<script>alert(1)</script>",
             "units": 5.0, "gmv": 100.0, "opportunity_type": "sales_response_present"},
        ]},
    )
    html = charts.for_result(result)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
