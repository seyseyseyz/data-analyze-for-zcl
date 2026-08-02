from pathlib import Path

import pytest
import yaml

from xhs_ceramics_analytics.contracts import metrics as metric_contracts
from xhs_ceramics_analytics.contracts.metrics import (
    MetricRegistry,
    MetricSpec,
    load_metric_registry,
)
from xhs_ceramics_analytics.analysis.core_business import _avg_daily_pay_conversion


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "references" / "metrics" / "registry.yaml"


def test_metric_registry_declares_observation_only_runtime_consumption():
    registry = load_metric_registry()

    assert registry.runtime_consumed is True
    assert registry.runtime_mode == "observe"
    assert registry.runtime_scopes == ["fact_annotation"]
    assert registry.metrics


def test_runtime_index_resolves_only_complete_legacy_fact_ids():
    build_index = getattr(metric_contracts, "build_metric_runtime_index", None)
    assert callable(build_index), "metric runtime index is not implemented"
    index = build_index(load_metric_registry())

    metric = index.resolve("core_business_diagnosis.click_pay_rate")
    assert metric is not None
    assert metric.metric_id == "shop.click_pay_rate"
    assert index.resolve("click_pay_rate") is None
    assert len(index.registry_hash) == 64


def test_runtime_index_rejects_a_producer_unit_mismatch():
    index = metric_contracts.build_metric_runtime_index(load_metric_registry())

    metric, error = index.resolve_validated(
        "core_business_diagnosis.click_pay_rate",
        metric_key="click_pay_rate",
        producer_unit="cny",
    )

    assert metric is None
    assert "unit mismatch" in (error or "")


def test_every_legacy_binding_has_a_pinned_producer_contract():
    registry = load_metric_registry()
    legacy_keys = {
        legacy_key
        for metric in registry.metrics
        for legacy_key in metric.legacy_keys
    }

    assert set(registry.legacy_contracts) == legacy_keys


@pytest.mark.parametrize(
    "updates",
    [
        {"unit": "pp"},
        {"caliber": "amount"},
        {"grain": "sku"},
        {"source_grain": "shop_day", "aggregation": "direct"},
    ],
)
def test_registry_rejects_drift_from_the_producer_contract(updates):
    payload = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    metric = next(item for item in payload["metrics"] if item["metric_id"] == "shop.click_pay_rate")
    metric.update(updates)

    with pytest.raises(ValueError, match="legacy contract"):
        MetricRegistry.model_validate(payload)


def test_dynamic_dimension_outputs_cannot_be_bound_to_a_fixed_metric():
    index = metric_contracts.build_metric_runtime_index(load_metric_registry())
    ambiguous_fact_ids = {
        "channel_structure_diagnosis.dominant_gmv_share",
        "refund_structure_diagnosis.dominant_share",
        "audience_structure_diagnosis.top_gmv_share",
        "note_commercial_diagnosis.baseline_refund_rate",
    }

    assert all(index.resolve(fact_id) is None for fact_id in ambiguous_fact_ids)


def test_high_refund_sku_metric_uses_sku_count_caliber():
    metrics = {metric.metric_id: metric for metric in load_metric_registry().metrics}
    metric = metrics["sku.high_refund_count"]

    assert metric.unit == "count"
    assert metric.grain == "sku"
    assert metric.caliber == "count"


def test_registry_rejects_reintroducing_an_unscoped_dynamic_dimension_key():
    payload = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    metric = next(item for item in payload["metrics"] if item["metric_id"] == "carrier.card_gmv_share")
    metric["legacy_keys"].append("channel_structure_diagnosis.dominant_gmv_share")

    with pytest.raises(ValueError, match="dynamic-dimension"):
        MetricRegistry.model_validate(payload)


def test_registry_rejects_a_scoped_dynamic_dimension_binding():
    payload = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    metric = next(item for item in payload["metrics"] if item["metric_id"] == "shop.gmv")
    scoped_key = "channel_structure_diagnosis.finding_00.dominant_gmv_share"
    metric["legacy_keys"].append(scoped_key)
    payload["legacy_contracts"][scoped_key] = "cny|amount|shop_window|direct"

    with pytest.raises(ValueError, match="dynamic-dimension"):
        MetricRegistry.model_validate(payload)


def test_runtime_index_maps_are_read_only():
    index = metric_contracts.build_metric_runtime_index(load_metric_registry())

    with pytest.raises(TypeError):
        index.by_legacy_fact_id["probe.metric"] = next(iter(index.by_metric_id.values()))


def test_daily_distinct_metrics_declare_safe_cross_period_semantics():
    metrics = {metric.metric_id: metric for metric in load_metric_registry().metrics}
    expected = {
        "shop.paid_buyer_days": ("sum_as_person_days", "person_day"),
        "shop.avg_daily_paid_buyers": ("mean_daily", "count"),
        "shop.product_visitor_days": ("sum_as_person_days", "person_day"),
        "shop.avg_daily_product_visitors": ("mean_daily", "count"),
        "shop.add_to_cart_user_days": ("sum_as_person_days", "person_day"),
        "shop.avg_daily_add_to_cart_users": ("mean_daily", "count"),
        "shop.new_wishlist_user_days": ("sum_as_person_days", "person_day"),
        "shop.avg_daily_new_wishlist_users": ("mean_daily", "count"),
        "shop.avg_daily_aov": ("mean_of_daily_ratios", "cny"),
        "shop.avg_daily_pay_conversion_uv": ("mean_of_daily_ratios", "percent"),
        "shop.avg_daily_cart_to_pay_ratio": ("mean_of_daily_ratios", "percent"),
        "shop.avg_daily_wishlist_to_cart_ratio": ("mean_of_daily_ratios", "percent"),
    }

    for metric_id, (aggregation, unit) in expected.items():
        metric = metrics[metric_id]
        assert metric.source_grain == "shop_day"
        assert metric.distinct_scope == "day"
        assert metric.aggregation == aggregation
        assert metric.period_unique is False
        assert metric.additive is False
        assert metric.unit == unit


def test_daily_distinct_primitives_remain_day_grain_and_non_additive():
    metrics = {metric.metric_id: metric for metric in load_metric_registry().metrics}
    expected = {
        "shop.paid_buyers": "paid_buyers",
        "shop.product_visitors": "product_visitors",
        "shop.add_to_cart_users": "add_to_cart_users",
        "shop.wishlist_new": '"新增加入心愿单人数"',
    }

    for metric_id, source_field in expected.items():
        metric = metrics[metric_id]
        assert metric.source_grain == "shop_day"
        assert metric.grain == "shop_day"
        assert metric.aggregation == "direct"
        assert metric.distinct_scope == "day"
        assert metric.period_unique is False
        assert metric.additive is False
        assert source_field in metric.formula
        assert metric.legacy_keys == []


def test_daily_distinct_legacy_keys_match_current_analysis_outputs():
    metrics = {metric.metric_id: metric for metric in load_metric_registry().metrics}
    legacy_keys = {
        legacy_key
        for metric in metrics.values()
        for legacy_key in metric.legacy_keys
    }

    assert {
        "core_business_diagnosis.paid_buyer_days",
        "core_business_diagnosis.avg_daily_paid_buyers",
        "core_business_diagnosis.product_visitor_days",
        "core_business_diagnosis.avg_daily_product_visitors",
        "core_business_diagnosis.avg_daily_aov",
        "core_business_diagnosis.avg_daily_pay_conversion",
        "demand_funnel_diagnosis.add_to_cart_user_days",
        "demand_funnel_diagnosis.avg_daily_add_to_cart_users",
        "demand_funnel_diagnosis.paid_buyer_days",
        "demand_funnel_diagnosis.avg_daily_paid_buyers",
        "demand_funnel_diagnosis.avg_daily_cart_to_pay",
        "demand_funnel_diagnosis.new_wishlist_user_days",
        "demand_funnel_diagnosis.avg_daily_new_wishlist_users",
        "demand_funnel_diagnosis.avg_daily_wishlist_to_cart",
        "demand_funnel_diagnosis.add_to_cart_observed_days",
        "demand_funnel_diagnosis.paid_buyer_observed_days",
        "demand_funnel_diagnosis.paired_ratio_observed_days",
    } <= legacy_keys
    assert not {
        "core_business_diagnosis.total_paid_buyers",
        "demand_funnel_diagnosis.total_paid_buyers",
        "demand_funnel_diagnosis.total_add_to_cart_users",
        "demand_funnel_diagnosis.total_new_wishlist",
        "core_business_diagnosis.delta_gmv",
        "core_business_diagnosis.contrib_traffic",
        "core_business_diagnosis.contrib_conversion",
        "core_business_diagnosis.contrib_aov",
    } & legacy_keys


def test_daily_column_fallback_is_dataset_level_not_rowwise_coalesce():
    metrics = {metric.metric_id: metric for metric in load_metric_registry().metrics}

    for metric_id in (
        "shop.avg_daily_aov",
        "shop.avg_daily_pay_conversion_uv",
    ):
        formula = metrics[metric_id].formula
        assert "FALLBACK_IF_NO_VALID" in formula
        assert "COALESCE" not in formula


def test_pay_conversion_registry_matches_runtime_rate_normalization():
    metrics = {metric.metric_id: metric for metric in load_metric_registry().metrics}
    formula = metrics["shop.avg_daily_pay_conversion_uv"].formula

    assert "BOUNDED_RATE(pay_conversion_uv)" in formula
    value, source = _avg_daily_pay_conversion(
        {"pay_conversion_uv"},
        [
            {"pay_conversion_uv": 10},
            {"pay_conversion_uv": 0.2},
            {"pay_conversion_uv": 150},
        ],
    )
    assert value == pytest.approx(0.15)
    assert source == "daily_column_average"


def test_daily_distinct_semantics_require_an_explicit_cross_period_aggregation():
    payload = {
        "metric_id": "shop.example_daily_users",
        "display_name": "示例日去重人数",
        "unit": "count",
        "formula": "AVG(example_daily_users)",
        "grain": "shop_window",
        "window_role": "analysis",
        "caliber": "user_count",
        "additive": False,
        "proxy": False,
        "owners_modules": ["example"],
        "legacy_keys": ["example.daily_users"],
        "source_grain": "shop_day",
        "distinct_scope": "day",
        "period_unique": False,
    }

    with pytest.raises(ValueError, match="aggregation"):
        MetricSpec.model_validate(payload)


def test_person_day_metric_must_be_labeled_as_person_days():
    payload = {
        "metric_id": "shop.example_user_days",
        "display_name": "示例用户数",
        "unit": "person_day",
        "formula": "SUM(example_daily_users)",
        "grain": "shop_window",
        "window_role": "analysis",
        "caliber": "user_count",
        "additive": False,
        "proxy": False,
        "owners_modules": ["example"],
        "legacy_keys": ["example.user_days"],
        "source_grain": "shop_day",
        "distinct_scope": "day",
        "aggregation": "sum_as_person_days",
        "period_unique": False,
    }

    with pytest.raises(ValueError, match="人次"):
        MetricSpec.model_validate(payload)


def test_person_day_metric_requires_daily_distinct_scope():
    payload = {
        "metric_id": "shop.example_user_days",
        "display_name": "示例用户人次",
        "unit": "person_day",
        "formula": "SUM(example_daily_users)",
        "grain": "shop_window",
        "window_role": "analysis",
        "caliber": "user_count",
        "additive": False,
        "proxy": False,
        "owners_modules": ["example"],
        "legacy_keys": ["example.user_days"],
        "source_grain": "shop_day",
        "aggregation": "sum_as_person_days",
    }

    with pytest.raises(ValueError, match="distinct_scope=day"):
        MetricSpec.model_validate(payload)


def test_mean_daily_amount_does_not_require_user_distinct_scope():
    metric = MetricSpec.model_validate(
        {
            "metric_id": "shop.avg_daily_gmv",
            "display_name": "日均支付金额",
            "unit": "cny",
            "formula": "MEAN_BY_DAY(gmv)",
            "grain": "shop_window",
            "window_role": "analysis",
            "caliber": "amount",
            "additive": False,
            "proxy": False,
            "owners_modules": ["example"],
            "source_grain": "shop_day",
            "aggregation": "mean_daily",
        }
    )

    assert metric.distinct_scope is None
    assert metric.period_unique is None


def test_registry_file_is_the_default_loader_source():
    registry = load_metric_registry(REGISTRY_PATH)

    assert registry.version == 1


def test_registry_enum_declarations_cannot_weaken_python_validation():
    payload = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    payload["enums"]["unit"].remove("index")

    with pytest.raises(ValueError, match="enums.unit"):
        MetricRegistry.model_validate(payload)


def test_loader_rejects_duplicate_yaml_keys(tmp_path):
    duplicate_registry = REGISTRY_PATH.read_text(encoding="utf-8").replace(
        "version: 1",
        "version: 1\nversion: 1",
        1,
    )
    path = tmp_path / "duplicate.yaml"
    path.write_text(duplicate_registry, encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate YAML key"):
        load_metric_registry(path)
