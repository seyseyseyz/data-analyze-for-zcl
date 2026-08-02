# tests/test_facts_export_assembly.py
"""FactBook assembly from AnalysisResult — one Fact per numeric key_number."""
from pathlib import Path

import pytest
import yaml

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding, Subsection
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength
from xhs_ceramics_analytics.reporting.facts_export import (
    Fact,
    build_factbook,
    fact_id_map_for_result,
    iter_result_finding_refs,
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


def test_build_observes_metric_ids_without_blocking_unmapped_facts():
    result = AnalysisResult(
        task_id="core_business_diagnosis",
        title="整体经营",
        findings=[
            Finding(
                title="转化",
                conclusion="观察",
                evidence_strength=EvidenceStrength.MEDIUM,
                key_numbers={"click_pay_rate": 0.12, "unmapped_probe": 7},
            )
        ],
    )

    book = build_factbook([result])

    assert book.facts["core_business_diagnosis.click_pay_rate"].metric_id == "shop.click_pay_rate"
    assert book.facts["core_business_diagnosis.unmapped_probe"].metric_id is None
    assert book.metric_mapping.status == "observe"
    assert book.metric_mapping.mapped_count == 1
    assert book.metric_mapping.unmapped_count == 1
    assert book.metric_mapping.coverage_rate == pytest.approx(0.5)
    assert book.metric_mapping.unmapped_fact_ids == (
        "core_business_diagnosis.unmapped_probe",
    )
    assert book.metric_mapping.registry_hash is not None


def test_registry_semantics_drive_mapped_fact_name_unit_caliber_and_aggregation():
    result = AnalysisResult(
        task_id="core_business_diagnosis",
        title="整体经营",
        findings=[
            Finding(
                title="买家",
                conclusion="观察",
                evidence_strength=EvidenceStrength.MEDIUM,
                key_numbers={"paid_buyer_days": 12},
            )
        ],
    )

    fact = build_factbook([result]).facts["core_business_diagnosis.paid_buyer_days"]

    assert fact.metric_id == "shop.paid_buyer_days"
    assert fact.display_name == "支付买家人次（逐日去重人次）"
    assert fact.unit == "person_day"
    assert fact.caliber == "user_count"
    assert fact.aggregation == "sum_as_person_days"
    assert fact.grain == "shop_window"
    assert fact.formula == "SUM_AS_PERSON_DAYS(shop.paid_buyers)"
    assert fact.rendered == "12"
    assert fact.mapping_error is None


def test_registry_count_semantics_override_ratio_substring_only_after_validation():
    result = AnalysisResult(
        task_id="demand_funnel_diagnosis",
        title="需求漏斗",
        findings=[
            Finding(
                title="有效天数",
                conclusion="观察",
                evidence_strength=EvidenceStrength.MEDIUM,
                key_numbers={"paired_ratio_observed_days": 7},
            )
        ],
    )

    fact = build_factbook([result]).facts[
        "demand_funnel_diagnosis.paired_ratio_observed_days"
    ]

    assert fact.metric_id == "quality.paired_cart_to_pay_observed_days"
    assert fact.unit == "count"
    assert fact.rendered == "7"
    assert fact.caliber == "count"


def test_semantically_incompatible_registry_contract_disables_annotations(tmp_path):
    registry_path = Path(__file__).resolve().parents[1] / "references/metrics/registry.yaml"
    payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    metric = next(item for item in payload["metrics"] if item["metric_id"] == "shop.click_pay_rate")
    metric["unit"] = "cny"
    metric["caliber"] = "amount"
    broken_path = tmp_path / "registry.yaml"
    broken_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    result = AnalysisResult(
        task_id="core_business_diagnosis",
        title="整体经营",
        findings=[
            Finding(
                title="转化",
                conclusion="观察",
                evidence_strength=EvidenceStrength.MEDIUM,
                key_numbers={"click_pay_rate": 0.12},
            )
        ],
    )

    book = build_factbook([result], metric_registry_path=broken_path)
    fact = book.facts["core_business_diagnosis.click_pay_rate"]

    assert fact.metric_id is None
    assert fact.unit == "percent"
    assert fact.rendered == "12.0%"
    assert fact.mapping_error is None
    assert book.metric_mapping.status == "unavailable"
    assert "legacy contract mismatch" in (book.metric_mapping.error or "")


def test_registry_failure_disables_annotations_without_dropping_facts(tmp_path):
    broken_registry = tmp_path / "registry.yaml"
    broken_registry.write_text("metrics: [", encoding="utf-8")
    result = AnalysisResult(
        task_id="core_business_diagnosis",
        title="整体经营",
        findings=[
            Finding(
                title="转化",
                conclusion="观察",
                evidence_strength=EvidenceStrength.MEDIUM,
                key_numbers={"click_pay_rate": 0.12},
            )
        ],
    )

    book = build_factbook([result], metric_registry_path=broken_registry)

    fact = book.facts["core_business_diagnosis.click_pay_rate"]
    assert fact.metric_id is None
    assert fact.value == pytest.approx(0.12)
    assert fact.rendered == "12.0%"
    assert book.metric_mapping.status == "unavailable"
    assert book.metric_mapping.mapped_count == 0
    assert book.metric_mapping.unmapped_count == 1
    assert book.metric_mapping.registry_hash is None
    assert book.metric_mapping.error


def test_build_factbook_includes_subsection_facts():
    result = AnalysisResult(
        task_id="core_business_diagnosis",
        title="整体经营",
        findings=[],
        subsections=[
            Subsection(
                title="转化补充",
                findings=[
                    Finding(
                        title="点击支付",
                        conclusion="观察",
                        evidence_strength=EvidenceStrength.MEDIUM,
                        key_numbers={"click_pay_rate": 0.12},
                    )
                ],
            )
        ],
    )

    book = build_factbook([result])

    fact = book.facts["core_business_diagnosis.click_pay_rate"]
    assert fact.metric_id == "shop.click_pay_rate"


def test_build_factbook_disambiguates_duplicate_keys_by_stable_finding_location():
    result = AnalysisResult(
        task_id="core_business_diagnosis",
        title="整体经营",
        findings=[
            Finding(
                title="转化 A",
                conclusion="观察",
                evidence_strength=EvidenceStrength.MEDIUM,
                key_numbers={"click_pay_rate": 0.12},
            ),
            Finding(
                title="转化 B",
                conclusion="观察",
                evidence_strength=EvidenceStrength.MEDIUM,
                key_numbers={"click_pay_rate": 0.18, "unique_probe": 3},
            ),
        ],
        subsections=[
            Subsection(
                title="转化补充",
                findings=[
                    Finding(
                        title="转化 C",
                        conclusion="观察",
                        evidence_strength=EvidenceStrength.MEDIUM,
                        key_numbers={"click_pay_rate": 0.21},
                    )
                ],
            )
        ],
    )

    refs = list(iter_result_finding_refs(result))
    assert [ref.path for ref in refs] == [
        "finding_00",
        "finding_01",
        "subsection_00.finding_00",
    ]
    id_map = fact_id_map_for_result(result)
    assert id_map == {
        ("finding_00", "click_pay_rate"): "core_business_diagnosis.finding_00.click_pay_rate",
        ("finding_01", "click_pay_rate"): "core_business_diagnosis.finding_01.click_pay_rate",
        ("finding_01", "unique_probe"): "core_business_diagnosis.unique_probe",
        ("subsection_00.finding_00", "click_pay_rate"): (
            "core_business_diagnosis.subsection_00.finding_00.click_pay_rate"
        ),
    }

    book = build_factbook([result])

    assert book.facts["core_business_diagnosis.finding_00.click_pay_rate"].value == 0.12
    assert book.facts["core_business_diagnosis.finding_01.click_pay_rate"].value == 0.18
    assert book.facts[
        "core_business_diagnosis.subsection_00.finding_00.click_pay_rate"
    ].value == 0.21
    assert book.facts["core_business_diagnosis.unique_probe"].value == 3
    # The old unscoped registry binding is not exact for any repeated occurrence.
    assert all(
        book.facts[fact_id].metric_id is None
        for fact_id in book.facts
        if fact_id.endswith(".click_pay_rate")
    )
    assert all(
        "scoped fact requires an explicit registry binding"
        in (book.facts[fact_id].mapping_error or "")
        for fact_id in book.facts
        if fact_id.endswith(".click_pay_rate")
    )


def test_explicit_scoped_binding_takes_precedence_over_unscoped_legacy_binding(tmp_path):
    registry_path = Path(__file__).resolve().parents[1] / "references/metrics/registry.yaml"
    payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    unscoped_id = "core_business_diagnosis.click_pay_rate"
    scoped_id = "core_business_diagnosis.finding_00.click_pay_rate"
    metric = next(item for item in payload["metrics"] if unscoped_id in item["legacy_keys"])
    metric["legacy_keys"].append(scoped_id)
    payload["legacy_contracts"][scoped_id] = payload["legacy_contracts"][unscoped_id]
    custom_registry = tmp_path / "registry.yaml"
    custom_registry.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    result = AnalysisResult(
        task_id="core_business_diagnosis",
        title="整体经营",
        findings=[
            Finding(
                title="转化 A",
                conclusion="观察",
                evidence_strength=EvidenceStrength.MEDIUM,
                key_numbers={"click_pay_rate": 0.12},
            ),
            Finding(
                title="转化 B",
                conclusion="观察",
                evidence_strength=EvidenceStrength.MEDIUM,
                key_numbers={"click_pay_rate": 0.18},
            ),
        ],
    )

    book = build_factbook([result], metric_registry_path=custom_registry)

    assert book.facts[scoped_id].metric_id == "shop.click_pay_rate"
    assert book.facts[scoped_id].mapping_error is None
    second_fact = book.facts["core_business_diagnosis.finding_01.click_pay_rate"]
    assert second_fact.metric_id is None
    assert "scoped fact requires" in (second_fact.mapping_error or "")


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
