# tests/test_facts_export_assembly.py
"""FactBook assembly from AnalysisResult — one Fact per numeric key_number."""
import pytest

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength
from xhs_ceramics_analytics.reporting.facts_export import (
    Fact,
    build_factbook,
    render_cny,
)


def test_render_cny_wan_notation():
    assert render_cny(208364) == "¥20.8万"
    assert render_cny(4000) == "¥4,000"
    assert render_cny(None) == "—"


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
