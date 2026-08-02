from types import SimpleNamespace

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.reporting.curated_view import render_diagnostic_table
from xhs_ceramics_analytics.reporting.html import (
    RAW_HTML_CLOSE,
    RAW_HTML_OPEN,
    render_html,
    render_markdown_document_html,
)


def _result_with_explained_fields() -> AnalysisResult:
    return AnalysisResult(
        task_id="core_business_diagnosis",
        title="经营诊断",
        findings=[
            Finding(
                title="支付转化需要关注",
                conclusion="当前支付转化仍有提升空间。",
                evidence_strength=EvidenceStrength.MEDIUM,
                key_numbers={"refund_rate_pay": 0.18},
            )
        ],
        tables={
            "paid_traffic_efficiency": [
                {
                    "campaign_name_optional": "青釉杯投放",
                    "spend": 120,
                    "ctr_calc": 0.03,
                }
            ]
        },
    )


def test_field_explanations_are_focusable_tooltips_not_inline_copy():
    html = render_html([_result_with_explained_fields()])

    assert 'class="field-tooltip"' in html
    assert 'class="field-tooltip-content"' in html
    assert 'role="tooltip"' in html
    assert 'aria-describedby="field-tip-' in html
    assert 'tabindex="0"' in html
    assert 'class="field-help"' not in html
    assert 'class="field-tooltip-trigger"' not in html
    assert ">?</span>" not in html

    # The explanation remains available in the single-file report, but CSS keeps it
    # out of the normal layout until pointer hover or keyboard-visible focus.
    assert ".field-tooltip-content {" in html
    assert "visibility: hidden" in html
    assert ".field-tooltip:hover .field-tooltip-content" in html
    assert ".field-tooltip:focus-visible .field-tooltip-content" in html
    assert ".field-tooltip:focus-within .field-tooltip-content" not in html
    assert "cursor: pointer" in html
    assert "cursor: help" not in html


def test_tooltips_do_not_add_a_second_visible_field_definition_or_break_print():
    html = render_html([_result_with_explained_fields()])

    assert '<strong class="field-tooltip-label">退款率(支付时间)</strong>' in html
    assert '<strong class="field-tooltip-label">投放消耗</strong>' in html
    assert "position: fixed" in html
    assert "@media print" in html
    assert ".field-tooltip-content { display: none !important; }" in html
    assert "border-bottom: 1px dashed" in html


def test_all_tooltips_anchor_near_trigger_on_desktop_and_keep_mobile_fallback():
    fact_html = render_html([_result_with_explained_fields()])
    narrative_table = render_diagnostic_table(
        [{"refund_amount_refundtime": 2300}],
        ["refund_amount_refundtime"],
        table_name="business_overview_daily",
    )
    narrative_html = render_markdown_document_html(
        f"# 经营诊断报告\n\n{RAW_HTML_OPEN}\n{narrative_table}\n{RAW_HTML_CLOSE}\n",
        title="经营诊断报告",
    )

    for html in (fact_html, narrative_html):
        assert '<script id="field-tooltip-position">' in html
        assert 'const SELECTOR = ".field-tooltip"' in html
        assert '.field-tooltip--anchored .field-tooltip-content' in html
        assert '.table-wrap .field-tooltip--anchored' not in html
        assert 'trigger.getBoundingClientRect()' in html
        assert 'tooltip.getBoundingClientRect()' in html
        assert "triggerRect.top - tooltipRect.height - GAP" in html
        assert "triggerRect.bottom + GAP" in html
        assert "window.innerWidth - tooltipRect.width - EDGE" in html
        assert 'window.matchMedia("(max-width: 700px)")' in html
        assert 'trigger.dataset.tooltipPlacement = placement' in html
        assert "bottom: 24px" in html


def test_unknown_field_has_no_tooltip_or_dashed_affordance():
    result = AnalysisResult(
        task_id="weekly_business_review",
        title="周度复盘",
        findings=[
            Finding(
                title="未知探针",
                conclusion="保留原值。",
                evidence_strength=EvidenceStrength.MEDIUM,
                key_numbers={"unmapped_probe": 0.12},
            )
        ],
    )

    html = render_html([result])

    assert '<strong class="field-label">unmapped probe</strong>' in html
    assert "原始数据字段，保留用于查数和追溯。" not in html
    assert html.count('class="field-tooltip"') == 0


def test_known_field_with_failed_fact_mapping_has_no_tooltip():
    result = AnalysisResult(
        task_id="weekly_business_review",
        title="周度复盘",
        findings=[
            Finding(
                title="映射失败",
                conclusion="保留原始数值。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                key_numbers={"gmv": 100},
            )
        ],
    )
    factbook = SimpleNamespace(
        facts={
            "weekly_business_review.gmv": SimpleNamespace(
                metric_id="shop.gmv",
                display_name="成交额",
                rendered="100 元",
                unit="cny",
                mapping_error="unmapped",
            )
        }
    )

    html = render_html([result], factbook=factbook)

    assert '<strong class="field-label">销售额</strong>' in html
    assert 'class="field-tooltip"' not in html


def test_final_narrative_diagnostic_table_uses_confirmed_field_tooltips():
    table = render_diagnostic_table(
        [{"refund_amount_refundtime": 2300, "unknown_column": "原值"}],
        ["refund_amount_refundtime", "unknown_column"],
        table_name="business_overview_daily",
    )
    markdown = f"# 经营诊断报告\n\n{RAW_HTML_OPEN}\n{table}\n{RAW_HTML_CLOSE}\n"

    html = render_markdown_document_html(markdown, title="经营诊断报告")

    assert '<strong class="field-tooltip-label">退款金额(退款时间)</strong>' in html
    assert "根据完成退款的时间统计" in html
    assert '<span class="field-tooltip-key">时间口径</span>' in html
    assert "退款完成时间" in html
    assert "unknown column</th>" in html
    assert "unknown column</strong>" not in html
    assert "border-bottom: 1px dashed" in html
    assert 'role="tooltip"' in html
    assert 'class="field-tooltip-trigger"' not in html
    assert 'event.target.closest(".field-tooltip")' not in html


def test_validated_complex_metric_adds_only_relevant_business_caliber_rows():
    result = AnalysisResult(
        task_id="core_business_diagnosis",
        title="经营诊断",
        findings=[
            Finding(
                title="买家规模",
                conclusion="支付买家规模已汇总。",
                evidence_strength=EvidenceStrength.STRONG,
                key_numbers={"paid_buyer_days": 11},
            )
        ],
    )
    factbook = SimpleNamespace(
        facts={
            "core_business_diagnosis.paid_buyer_days": SimpleNamespace(
                metric_id="shop.paid_buyer_days",
                display_name="支付买家人次（逐日去重）",
                rendered="11",
                unit="person_day",
                mapping_error=None,
            )
        }
    )

    html = render_html([result], factbook=factbook)

    assert "逐日去重人数之和，只能称人次" in html
    assert '<span class="field-tooltip-key">统计方式</span>' in html
    assert "逐日去重后按人次相加" in html
    assert '<span class="field-tooltip-key">数据粒度</span>' in html
    assert "店铺 × 观察期" in html
    assert "SUM_AS_PERSON_DAYS" not in html
    assert "shop_window" not in html


def test_accepted_platform_definition_is_used_only_for_exact_table_field_context():
    from xhs_ceramics_analytics.reporting.html import _column_view

    accepted = _column_view(
        "refund_amount_refundtime",
        table_name="business_overview_daily",
        tooltip_scope="accepted",
    )
    unrelated = _column_view(
        "gmv",
        table_name="sku_performance",
        tooltip_scope="unrelated",
    )

    assert "根据完成退款的时间统计" in accepted["help"]
    assert {row["label"] for row in accepted["details"]} >= {"时间口径", "数据粒度"}
    assert unrelated["help"] == "该 SKU 在观察期内产生的成交金额。"


def test_validated_factbook_values_override_only_key_number_name_value_and_unit():
    result = AnalysisResult(
        task_id="core_business_diagnosis",
        title="经营诊断",
        findings=[
            Finding(
                title="买家规模",
                conclusion="支付买家规模已汇总。",
                evidence_strength=EvidenceStrength.STRONG,
                key_numbers={"paid_buyer_days": 11},
            )
        ],
    )
    factbook = SimpleNamespace(
        facts={
            "core_business_diagnosis.paid_buyer_days": SimpleNamespace(
                metric_id="shop.paid_buyer_days",
                display_name="支付买家人次（逐日去重）",
                rendered="11",
                unit="person_day",
                mapping_error=None,
            )
        }
    )

    html = render_html([result], factbook=factbook)

    assert '<strong class="field-tooltip-label">支付买家人次（逐日去重）</strong>' in html
    assert "<strong>11 人次</strong>" in html
    assert "paid_buyer_days" not in html


def test_factbook_lookup_uses_scoped_ids_for_repeated_keys():
    result = AnalysisResult(
        task_id="weekly_business_review",
        title="周度复盘",
        findings=[
            Finding(
                title="周样本",
                conclusion="周样本已汇总。",
                evidence_strength=EvidenceStrength.MEDIUM,
                key_numbers={"本周样本量": 11},
            ),
            Finding(
                title="明细样本",
                conclusion="明细样本已汇总。",
                evidence_strength=EvidenceStrength.MEDIUM,
                key_numbers={"本周样本量": 1272},
            ),
        ],
    )
    factbook = SimpleNamespace(
        facts={
            "weekly_business_review.finding_00.本周样本量": SimpleNamespace(
                metric_id="account.posts",
                display_name="周度有效样本",
                rendered="11",
                unit="count",
                mapping_error=None,
            ),
            "weekly_business_review.finding_01.本周样本量": SimpleNamespace(
                metric_id="shop.paid_orders",
                display_name="明细有效样本",
                rendered="1,272",
                unit="count",
                mapping_error=None,
            ),
        }
    )

    html = render_html([result], factbook=factbook)

    assert "周度有效样本" in html
    assert "明细有效样本" in html
    assert "<strong>11</strong>" in html
    assert "<strong>1,272</strong>" in html
    tooltip_ids = [
        chunk.split('"', 1)[0] for chunk in html.split('aria-describedby="')[1:]
    ]
    assert len(tooltip_ids) == 2
    assert len(set(tooltip_ids)) == 2


def test_unmapped_scoped_fact_still_owns_the_rendered_number():
    result = AnalysisResult(
        task_id="weekly_business_review",
        title="周度复盘",
        findings=[
            Finding(
                title="周样本",
                conclusion="周样本已汇总。",
                evidence_strength=EvidenceStrength.MEDIUM,
                key_numbers={"unmapped_probe": 0.12},
            ),
            Finding(
                title="明细样本",
                conclusion="明细样本已汇总。",
                evidence_strength=EvidenceStrength.MEDIUM,
                key_numbers={"unmapped_probe": 0.18},
            ),
        ],
    )
    factbook = SimpleNamespace(
        facts={
            "weekly_business_review.finding_00.unmapped_probe": SimpleNamespace(
                metric_id=None,
                display_name=None,
                rendered="12.00%",
                unit="percent",
                mapping_error=None,
            ),
            "weekly_business_review.finding_01.unmapped_probe": SimpleNamespace(
                metric_id=None,
                display_name=None,
                rendered="18.00%",
                unit="percent",
                mapping_error=None,
            ),
        }
    )

    html = render_html([result], factbook=factbook)

    assert "<strong>12.00%</strong>" in html
    assert "<strong>18.00%</strong>" in html
