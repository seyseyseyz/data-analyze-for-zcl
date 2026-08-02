from types import SimpleNamespace

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.reporting.html import render_html


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
    assert 'class="field-tooltip-trigger"' in html
    assert 'class="field-tooltip-content"' in html
    assert 'role="tooltip"' in html
    assert 'aria-describedby="field-tip-' in html
    assert 'tabindex="0"' in html
    assert 'class="field-help"' not in html

    # The explanation remains available in the single-file report, but CSS keeps it
    # out of the normal layout until hover/focus (tap gives the trigger focus).
    assert ".field-tooltip-content {" in html
    assert "visibility: hidden" in html
    assert ".field-tooltip:hover .field-tooltip-content" in html
    assert ".field-tooltip:focus-within .field-tooltip-content" in html


def test_tooltips_do_not_add_a_second_visible_field_definition_or_break_print():
    html = render_html([_result_with_explained_fields()])

    assert '<strong class="field-tooltip-label">退款率(支付时间)</strong>' in html
    assert '<strong class="field-tooltip-label">投放消耗</strong>' in html
    assert ".table-wrap .field-tooltip-content" in html
    assert "position: fixed" in html
    assert "@media print" in html
    assert ".field-tooltip-content,\n      .field-tooltip-trigger { display: none !important; }" in html


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
                metric_id="review.weekly_sample_count",
                display_name="周度有效样本",
                rendered="11",
                unit="count",
                mapping_error=None,
            ),
            "weekly_business_review.finding_01.本周样本量": SimpleNamespace(
                metric_id="review.detail_sample_count",
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
