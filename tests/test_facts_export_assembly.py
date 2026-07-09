# tests/test_facts_export_assembly.py
"""FactBook assembly from AnalysisResult — one Fact per numeric key_number."""
import pytest

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength
from xhs_ceramics_analytics.reporting.facts_export import (
    Fact,
    build_factbook,
    render_cny,
    render_count,
    render_pct,
)


def test_render_cny_wan_notation():
    assert render_cny(208364) == "¥20.8万"
    assert render_cny(4000) == "¥4,000"
    assert render_cny(None) == "—"


def test_render_count_has_no_currency_sign():
    assert render_count(250) == "250"
    assert render_count(208364) == "20.8万"
    assert render_count(None) == "—"


def test_render_pct_scales_fraction():
    assert render_pct(0.23) == "23.0%"
    assert render_pct(1.0) == "100.0%"
    # already a percentage-point value (>1) is not double-scaled
    assert render_pct(23.0) == "23.0%"
    assert render_pct(None) == "—"


def test_renderers_never_emit_negative_zero():
    # A tiny negative that rounds to zero at the display precision must not carry a
    # stray minus sign ("-0.0%" / "-0" / "-¥0" are numeric-form bugs the merchant sees).
    assert render_pct(-0.0004) == "0.0%"   # scaled -0.04 rounds to 0 → never "-0.0%"
    assert render_count(-0.3) == "0"       # rounds to 0 → never "-0"
    assert render_cny(-0.3) == "¥0"        # rounds to 0 → never "-¥0"
    # a genuine negative magnitude still keeps its sign
    assert render_pct(-0.04) == "-4.0%"
    assert render_count(-1) == "-1"
    assert render_cny(-29000.0) == "-¥2.9万"


def test_metric_kind_uses_fact_layer_allow_list_first():
    # Render-path parity (the meta-bug): a MONEY key that merely CONTAINS "conversion"
    # (contrib_conversion is a yuan LMDI GMV-bridge contribution, in MONEY_FIELDS) must
    # render as money — exactly as the table path (format_scalar) does — never as an
    # unscaled percent. This was the root of the "-17104.8%" figure.
    book = build_factbook([_finding_with({"contrib_conversion": -17104.8})])
    fact = book.facts["mod.contrib_conversion"]
    assert fact.unit == "cny"
    assert fact.rendered == "-¥1.7万"      # NOT "-17104.8%"


def test_conversion_lookalike_count_key_is_not_forced_percent():
    # conversion_universe is a population count, not a rate; with "conversion" removed
    # from the loose substring hints (real conversion RATES stay in PERCENT_FIELDS), it
    # classifies as a count instead of a nonsensical "3991.0%".
    book = build_factbook([_finding_with({"conversion_universe": 3991})])
    fact = book.facts["mod.conversion_universe"]
    assert fact.unit == "count"
    assert fact.rendered == "3,991"        # NOT "3991.0%"


def test_concentration_index_is_not_rendered_as_money():
    # HHI / gini concentration indices merely CONTAIN "gmv" (repeat_gmv_hhi, gmv_gini),
    # so the last-resort "gmv" substring hint used to force them to money — a 0.64 index
    # became the nonsensical "¥1" ("集中度指标为 ¥1" in the narrative). They are
    # dimensionless indices: mirror the table path (format_scalar's _hhi branch) and
    # render the value with its leading significant digits, never a currency sign.
    book = build_factbook(
        [
            _finding_with(
                {
                    "repeat_gmv_hhi": 0.637444,
                    "gmv_gini": 0.55,
                    "note_gmv_hhi": 0.018,
                    "gmv_hhi": 0.0028,
                }
            )
        ]
    )
    assert book.facts["mod.repeat_gmv_hhi"].unit == "index"
    assert book.facts["mod.repeat_gmv_hhi"].rendered == "0.64"  # NOT "¥1"
    assert book.facts["mod.gmv_gini"].rendered == "0.55"
    assert book.facts["mod.note_gmv_hhi"].rendered == "0.018"
    assert book.facts["mod.gmv_hhi"].rendered == "0.0028"


def _finding_with(key_numbers: dict) -> AnalysisResult:
    return AnalysisResult(
        task_id="mod",
        title="mod",
        findings=[
            Finding(
                title="t",
                conclusion="c",
                evidence_strength=EvidenceStrength.MEDIUM,
                key_numbers=key_numbers,
            )
        ],
    )


def test_count_metric_is_not_rendered_as_money():
    book = build_factbook([_finding_with({"posts": 250, "active_days": 12})])
    posts = book.facts["mod.posts"]
    assert posts.rendered == "250"  # NOT "¥250"
    assert posts.unit == "count"
    assert book.facts["mod.active_days"].rendered == "12"


def test_rate_metric_is_rendered_as_percent_not_zero_cny():
    book = build_factbook([_finding_with({"overall_conversion": 0.23})])
    conv = book.facts["mod.overall_conversion"]
    assert conv.rendered == "23.0%"  # NOT "¥0"
    assert conv.unit == "percent"


def test_money_metric_still_renders_as_cny():
    book = build_factbook([_finding_with({"delta_gmv": -29000.0, "client_price": 85})])
    assert book.facts["mod.delta_gmv"].rendered == "-¥2.9万"
    assert book.facts["mod.delta_gmv"].unit == "cny"
    assert book.facts["mod.client_price"].rendered == "¥85"  # 客单价-style key


def _core_result() -> AnalysisResult:
    finding = Finding(
        title="增长归因",
        conclusion="GMV 下滑主要来自客单价。",
        evidence_strength=EvidenceStrength.WEAK,
        descriptive_reliability=DescriptiveReliability.HIGH,
        key_numbers={"delta_gmv": -29000.0, "dominant_factor": "客单价"},
        recommended_action="回补高价礼盒占比。",
        caveats=["按日历月聚合。"],
    )
    return AnalysisResult(
        task_id="core_business_diagnosis",
        title="整体经营",
        findings=[finding],
        named_examples=[{"name": "兴安岭之夜"}, {"name": "鱼盘"}],
    )


def test_build_extracts_one_fact_per_numeric_key():
    book = build_factbook([_core_result()])
    assert "core_business_diagnosis.delta_gmv" in book.facts
    # Non-numeric key_numbers ("客单价") do not become facts.
    assert "core_business_diagnosis.dominant_factor" not in book.facts
    fact = book.facts["core_business_diagnosis.delta_gmv"]
    assert isinstance(fact, Fact)
    assert fact.value == pytest.approx(-29000.0)
    assert fact.rendered == "-¥2.9万"
    assert fact.evidence_strength == EvidenceStrength.WEAK
    assert fact.descriptive_reliability == DescriptiveReliability.HIGH


def test_build_collects_entity_registry_and_module_reading():
    book = build_factbook([_core_result()])
    assert "兴安岭之夜" in book.entity_registry and "鱼盘" in book.entity_registry
    reading = book.module_reading["core_business_diagnosis"]
    assert reading["conclusion"] == "GMV 下滑主要来自客单价。"
    assert reading["action"] == "回补高价礼盒占比。"
    assert reading["caveats"] == ["按日历月聚合。"]


def test_blocked_and_absent_links_carried():
    book = build_factbook(
        [_core_result()],
        blocked_modules=["paid_traffic_efficiency"],
        absent_links=["note→order", "退款原因"],
    )
    assert book.blocked_modules == ["paid_traffic_efficiency"]
    assert "退款原因" in book.absent_link_registry
