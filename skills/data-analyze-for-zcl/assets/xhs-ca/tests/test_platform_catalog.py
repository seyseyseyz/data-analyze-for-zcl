from __future__ import annotations

import csv
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from xhs_ceramics_analytics.contracts.platform_catalog import (
    PlatformMetricCatalog,
    PromotionDecision,
    SourceBindingRegistry,
    load_platform_metric_catalog,
    load_promotion_reviews,
    load_source_binding_registry,
    validate_catalog_bundle,
)
from xhs_ceramics_analytics.contracts import platform_catalog
from xhs_ceramics_analytics.importing.mapping import FIELD_ALIASES


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "references" / "platform" / "xhs_metric_catalog.yaml"
PROMOTION_PATH = ROOT / "references" / "platform" / "xhs_metric_promotion_review.csv"
BUSINESS_REVIEW_PATH = ROOT / "references" / "platform" / "xhs_business_overview_binding_review.csv"
BINDING_PATH = ROOT / "references" / "source_bindings" / "xhs_platform_metrics.yaml"
BUNDLED_RUNTIME = ROOT / "skills" / "data-analyze-for-zcl" / "assets" / "xhs-ca"
RAW_INPUTS = (
    ROOT / "output" / "xiaohongshu-api-metric-dictionary.csv",
    ROOT / "output" / "xiaohongshu-field-dictionary-core.csv",
    ROOT / "output" / "xiaohongshu-api-schema.csv",
)

BUNDLED_PLATFORM_FILES = (
    Path("xhs_ceramics_analytics/contracts/platform_catalog.py"),
    Path("references/platform/xhs_metric_catalog.yaml"),
    Path("references/platform/xhs_metric_promotion_review.csv"),
    Path("references/platform/xhs_business_overview_binding_review.csv"),
    Path("references/source_bindings/xhs_platform_metrics.yaml"),
    Path("tests/test_platform_catalog.py"),
)


def test_platform_catalog_is_complete_and_review_gated():
    catalog = load_platform_metric_catalog()
    reviews = load_promotion_reviews()
    registry = load_source_binding_registry()

    validate_catalog_bundle(catalog, registry, reviews)

    assert catalog.summary.model_dump(mode="json") == {
        "metric_count": 134,
        "current_count": 82,
        "deferred_count": 52,
        "bound_count": 0,
        "new_contract_count": 82,
        "rejected_count": 0,
    }
    assert registry.runtime_consumed is True
    assert registry.runtime_mode.value == "observe"
    assert [scope.value for scope in registry.runtime_scopes] == ["agent_context"]
    assert len(registry.bindings) == 15
    assert all(binding.status.value == "accepted" for binding in registry.bindings)
    assert not {14, 19} & {binding.platform_metric_id for binding in registry.bindings}
    assert all(review.decision != PromotionDecision.REJECTED for review in reviews)
    assert Counter(review.decision for review in reviews) == {
        PromotionDecision.PROPOSED: 48,
        PromotionDecision.DEFERRED: 52,
    }


def test_platform_semantic_context_exposes_approved_definitions_without_mapping_effects():
    context = platform_catalog.build_platform_semantic_context()

    assert context["status"] == "observe"
    assert context["runtime_scopes"] == ["agent_context"]
    assert context["effects"] == {
        "automatic_header_mapping": "validation_gate",
        "agent_decision_support": "enabled",
        "coverage": "none",
        "raw_values": "none",
        "calculations": "none",
    }
    gmv = next(
        reference
        for reference in context["accepted_references"]
        if reference["canonical_table"] == "business_overview_daily"
        and reference["canonical_field"] == "gmv"
    )
    assert gmv["platform_metric_id"] == 20
    assert gmv["display_name"] == "支付金额"
    assert gmv["modules"] == ["交易数据/成交分析", "数据总览"]
    assert gmv["time_anchor"] == "payment_time"
    assert gmv["unit"] == "cny"
    assert gmv["description"]
    assert context["catalog_reference"]["path"] == (
        "references/platform/xhs_metric_catalog.yaml"
    )
    assert context["catalog_reference"]["current_metric_count"] == 82
    assert context["catalog_reference"]["review_required_count"] == 82
    product_visitors = next(
        candidate
        for candidate in context["reference_only_candidates"]
        if candidate["platform_metric_id"] == 14
    )
    assert product_visitors["display_name"] == "商品访客数"
    assert product_visitors["possible_targets"] == [
        {
            "canonical_table": "business_overview_daily",
            "canonical_field": "product_visitors",
        }
    ]
    assert "no_approved_binding" in product_visitors["review_reasons"]
    assert product_visitors["mapping_permission"] == "none"


def test_loading_platform_semantics_never_changes_header_mapping():
    from copy import deepcopy

    from xhs_ceramics_analytics.importing.mapping import map_columns
    from xhs_ceramics_analytics.importing.profile import FileProfile

    profile = FileProfile(
        path=Path("overview.csv"),
        table_name="overview",
        columns=["日期", "支付金额", "支付订单数"],
        row_count=1,
        sample_rows=[],
    )
    aliases_before = deepcopy(FIELD_ALIASES)
    mapping_before = map_columns(profile, "business_overview_daily")

    platform_catalog.build_platform_semantic_context()

    assert FIELD_ALIASES == aliases_before
    assert map_columns(profile, "business_overview_daily") == mapping_before


def test_formal_bindings_match_every_approved_business_overview_review():
    registry = load_source_binding_registry()
    with BUSINESS_REVIEW_PATH.open(encoding="utf-8-sig", newline="") as handle:
        approved_rows = [
            row for row in csv.DictReader(handle) if row["suggested_decision"] == "approve"
        ]

    expected_contexts = {
        (
            int(row["platform_metric_id"]),
            row["module"],
            row["canonical_table"],
            row["canonical_field"],
        )
        for row in approved_rows
    }
    actual_contexts = {
        (
            binding.platform_metric_id,
            binding.module,
            binding.canonical_table,
            binding.canonical_field,
        )
        for binding in registry.bindings
    }

    assert len(approved_rows) == 15
    assert actual_contexts == expected_contexts
    rows_by_context = {
        (
            int(row["platform_metric_id"]),
            row["module"],
            row["canonical_table"],
            row["canonical_field"],
        ): row
        for row in approved_rows
    }
    for binding in registry.bindings:
        context = (
            binding.platform_metric_id,
            binding.module,
            binding.canonical_table,
            binding.canonical_field,
        )
        row = rows_by_context[context]
        assert binding.status.value == "accepted"
        assert binding.match_basis.value == "exact_existing_alias"
        assert binding.confidence.value == "high"
        assert binding.grain.value == row["grain"]
        assert binding.time_basis.value == row["time_basis"]
        assert binding.unit.value == row["unit"]
        assert binding.value_encoding.value == row["value_encoding"]
        assert binding.aggregation.value == row["aggregation"]
        assert binding.approved_definition_sha256 == row["definition_sha256"]


def test_business_overview_binding_review_is_complete_and_non_executable():
    with BUSINESS_REVIEW_PATH.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    promotions = {
        review.promotion_id: review
        for review in load_promotion_reviews()
        if review.canonical_table == "business_overview_daily"
    }
    metrics = {
        str(metric.platform_metric_id): metric for metric in load_platform_metric_catalog().metrics
    }

    assert len(rows) == 17
    assert {row["promotion_id"] for row in rows} == set(promotions)
    assert Counter(row["suggested_decision"] for row in rows) == {
        "approve": 15,
        "blocked_contract_semantics": 2,
    }
    assert all(row["runtime_action"] == "none" for row in rows)
    assert all(row["evidence_tier"] == "strong" for row in rows)
    assert all(row["grain"] == "shop_day" for row in rows)
    assert all(row["aggregation"] == "direct" for row in rows)
    assert all(
        row["definition_sha256"] == promotions[row["promotion_id"]].definition_sha256
        for row in rows
    )
    for row in rows:
        promotion = promotions[row["promotion_id"]]
        metric = metrics[row["platform_metric_id"]]
        assert row["platform_metric_id"] == str(promotion.platform_metric_id)
        assert row["module"] == promotion.module
        assert row["canonical_table"] == promotion.canonical_table
        assert row["canonical_field"] == promotion.canonical_field
        assert row["time_basis"] == metric.time_anchor.value
        assert row["unit"] == metric.unit.value
        assert row["source_header"] in FIELD_ALIASES[row["canonical_table"]][row["canonical_field"]]
    assert {
        row["canonical_field"]
        for row in rows
        if row["suggested_decision"] == "blocked_contract_semantics"
    } == {"product_visitors", "paid_buyers"}
    assert {row["value_encoding"] for row in rows if row["platform_metric_id"] == "1776"} == {
        "ratio_0_1"
    }
    assert {
        row["suggested_decision"] for row in rows if row["platform_metric_id"] in {"370", "1776"}
    } == {"approve"}


@pytest.mark.skipif(
    not (ROOT / "skills" / "data-analyze-for-zcl" / "scripts" / "sync-runtime").exists(),
    reason="bundled runtime is only present in the maintainer checkout",
)
def test_platform_catalog_machine_readable_assets_match_bundled_runtime():
    for relative_path in BUNDLED_PLATFORM_FILES:
        assert (ROOT / relative_path).read_bytes() == (BUNDLED_RUNTIME / relative_path).read_bytes()


def test_platform_catalog_semantic_classification_regression():
    catalog = load_platform_metric_catalog()

    assert Counter(metric.measure_kind.value for metric in catalog.metrics) == {
        "event_count": 34,
        "amount_total": 28,
        "ratio": 26,
        "count": 17,
        "distinct_count": 15,
        "duration_average": 9,
        "average_amount": 3,
        "share": 1,
        "net_amount": 1,
    }
    duplicate_groups = {
        metric.display_name
        for metric in catalog.metrics
        if "duplicate_display_name" in metric.review_reasons
    }
    assert duplicate_groups == {
        "支付订单数",
        "直播支付金额",
        "笔记商品点击人数",
        "笔记商品点击率",
        "笔记支付人数",
        "笔记支付订单数",
        "笔记支付金额",
        "退款率(支付时间)",
    }
    unknown_duration_units = {
        metric.platform_metric_id
        for metric in catalog.metrics
        if "unknown_duration_unit" in metric.review_reasons
    }
    assert unknown_duration_units == {95, 96, 97, 147, 148, 150, 151}
    may_exceed_one = {
        metric.platform_metric_id
        for metric in catalog.metrics
        if "ratio_may_exceed_100_percent" in metric.review_reasons
    }
    assert may_exceed_one == {52, 94}
    metrics_by_id = {metric.platform_metric_id: metric for metric in catalog.metrics}
    assert sum(metric.division_formula_explicit for metric in catalog.metrics) == 33
    date_example_metrics = {41, 42, 43, 1498, 1499, 1500, 1762, 1766, 1774, 1777, 1785}
    assert all(
        not metrics_by_id[metric_id].division_formula_explicit for metric_id in date_example_metrics
    )
    payment_amount = next(metric for metric in catalog.metrics if metric.platform_metric_id == 20)
    assert {domain.value for domain in payment_amount.business_domains} == {
        "transaction",
        "product",
        "overview",
        "traffic",
    }
    assert {
        metric_id: metrics_by_id[metric_id].time_anchor.value for metric_id in (19, 20, 37, 1788)
    } == {
        19: "payment_time",
        20: "payment_time",
        37: "payment_time",
        1788: "payment_time",
    }
    assert {
        metric_id: metrics_by_id[metric_id].refund_inclusion.value for metric_id in (185, 371)
    } == {
        185: "gross_includes_refunds",
        371: "gross_includes_refunds",
    }


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("用户10/1支付，10/2申请退款，10/5退款成功", False),
        ("用户数/100", True),
        ("100/用户数", True),
        ("100/200", True),
        ("退款金额 / 支付金额", True),
        ("退款金额÷支付金额", True),
        ("退款金额除以支付金额", True),
    ],
)
def test_explicit_division_formula_ignores_dates_without_hiding_operands(description, expected):
    from scripts.build_xhs_semantic_catalog import has_explicit_division_formula

    assert has_explicit_division_formula(description) is expected


@pytest.mark.parametrize("field", ["description", "unit", "time_anchor", "classifier_version"])
def test_catalog_definition_hash_detects_semantic_drift(field):
    payload = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    metric = payload["metrics"][0]
    replacements = {
        "description": f"{metric['description']} changed",
        "unit": "minutes" if metric["unit"] != "minutes" else "seconds",
        "time_anchor": (
            "payment_time" if metric["time_anchor"] != "payment_time" else "event_time"
        ),
        "classifier_version": f"{metric['classifier_version']}-changed",
    }
    metric[field] = replacements[field]

    with pytest.raises(ValidationError, match="definition hash mismatch"):
        PlatformMetricCatalog.model_validate(payload)


def test_catalog_rejects_incoherent_review_state():
    payload = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    payload["metrics"][0]["candidate_binding_status"] = "approved"

    with pytest.raises(ValidationError, match="incompatible candidate binding status"):
        PlatformMetricCatalog.model_validate(payload)


def test_partial_module_binding_does_not_bind_whole_metric():
    payload = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    metric_payload = next(
        metric for metric in payload["metrics"] if metric["platform_metric_id"] == 20
    )
    metric_payload["review_status"] = "bound"
    metric_payload["candidate_binding_status"] = "approved"
    metric_payload["review_required"] = False
    payload["summary"]["bound_count"] = 1
    payload["summary"]["new_contract_count"] -= 1
    catalog = PlatformMetricCatalog.model_validate(payload)
    registry = SourceBindingRegistry.model_validate(
        {
            "version": 1,
            "platform": "xiaohongshu_qianfan",
            "runtime_consumed": False,
            "bindings": [
                {
                    "platform_metric_id": 20,
                    "module": "数据总览",
                    "canonical_table": "business_overview_daily",
                    "canonical_field": "gmv",
                    "status": "accepted",
                    "match_basis": "exact_existing_alias",
                    "confidence": "high",
                    "grain": "shop_day",
                    "time_basis": "payment_time",
                    "unit": "cny",
                    "value_encoding": "decimal",
                    "aggregation": "sum",
                    "approved_definition_sha256": metric_payload["definition_sha256"],
                }
            ],
        }
    )

    with pytest.raises(ValueError, match="does not cover every current module"):
        validate_catalog_bundle(catalog, registry)


def test_tracked_catalog_assets_are_scrubbed():
    forbidden = ("https://", "http://", "/Users/", ".har", "authorization", "cookie")

    for path in (CATALOG_PATH, PROMOTION_PATH, BUSINESS_REVIEW_PATH, BINDING_PATH):
        text = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token.lower() not in text, f"{path} contains forbidden token {token!r}"

    catalog = load_platform_metric_catalog()
    for metric in catalog.metrics:
        assert metric.endpoint_path.startswith("/")
        assert "://" not in metric.endpoint_path
        assert "?" not in metric.endpoint_path
        assert "@" not in metric.endpoint_path


def test_catalog_rejects_local_endpoint_paths():
    payload = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    payload["metrics"][0]["endpoint_path"] = "/Users/alice/capture.har"

    with pytest.raises(ValidationError, match="endpoint_path"):
        PlatformMetricCatalog.model_validate(payload)


def test_generator_scrubs_local_source_locators_from_review_ledger():
    from scripts.build_xhs_semantic_catalog import build_candidate_ledger, endpoint_path

    catalog = load_platform_metric_catalog()
    reviews = load_promotion_reviews()
    rows = build_candidate_ledger(
        catalog,
        [],
        [
            {
                "field": "测试字段",
                "explanation": "测试解释",
                "confidence": "medium",
                "source_asset": "/Users/alice/capture.har",
                "source_key": "capture.har:42",
                "source_url": "file:///Users/alice/capture.har",
            }
        ],
        reviews,
    )
    serialized = str(rows)

    assert endpoint_path("file:///Users/alice/capture.har") == "/unknown"
    assert "/Users/" not in serialized
    assert ".har" not in serialized


def _accepted_binding_payload(metric) -> dict[str, object]:
    return {
        "platform_metric_id": metric.platform_metric_id,
        "module": "数据总览",
        "canonical_table": "business_overview_daily",
        "canonical_field": "gmv",
        "status": "accepted",
        "match_basis": "exact_existing_alias",
        "confidence": "high",
        "grain": "shop_day",
        "time_basis": "payment_time",
        "unit": "cny",
        "value_encoding": "decimal",
        "aggregation": "sum",
        "approved_definition_sha256": metric.definition_sha256,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [("unit", "bananas"), ("aggregation", "execute_code")],
)
def test_formal_registry_rejects_unrecognized_binding_semantics(field, value):
    metric = next(
        metric
        for metric in load_platform_metric_catalog().metrics
        if metric.platform_metric_id == 20
    )
    binding = _accepted_binding_payload(metric)
    binding[field] = value

    with pytest.raises(ValidationError, match=field):
        SourceBindingRegistry.model_validate(
            {
                "version": 1,
                "platform": "xiaohongshu_qianfan",
                "runtime_consumed": False,
                "bindings": [binding],
            }
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("grain", "note_window", "binding grain"),
        ("time_basis", "analysis_window", "binding time_basis"),
        ("unit", "percent", "binding unit"),
        ("value_encoding", "integer", "binding value_encoding"),
        ("aggregation", "average", "binding aggregation"),
    ],
)
def test_catalog_bundle_rejects_incompatible_binding_semantics(field, value, message):
    catalog = load_platform_metric_catalog()
    metric = next(metric for metric in catalog.metrics if metric.platform_metric_id == 20)
    binding = _accepted_binding_payload(metric)
    binding[field] = value
    registry = SourceBindingRegistry.model_validate(
        {
            "version": 1,
            "platform": "xiaohongshu_qianfan",
            "runtime_consumed": False,
            "bindings": [binding],
        }
    )

    with pytest.raises(ValueError, match=message):
        validate_catalog_bundle(catalog, registry)


def test_catalog_bundle_accepts_compatible_partial_binding_semantics():
    catalog = load_platform_metric_catalog()
    metric = next(metric for metric in catalog.metrics if metric.platform_metric_id == 20)
    registry = SourceBindingRegistry.model_validate(
        {
            "version": 1,
            "platform": "xiaohongshu_qianfan",
            "runtime_consumed": False,
            "bindings": [_accepted_binding_payload(metric)],
        }
    )

    validate_catalog_bundle(catalog, registry)


def test_catalog_bundle_rejects_binding_outside_module_table_scope():
    catalog = load_platform_metric_catalog()
    metric = next(metric for metric in catalog.metrics if metric.platform_metric_id == 20)
    binding = _accepted_binding_payload(metric)
    binding.update(
        {
            "canonical_table": "search_terms",
            "canonical_field": "gmv",
            "grain": "search_term_window",
        }
    )
    registry = SourceBindingRegistry.model_validate(
        {
            "version": 1,
            "platform": "xiaohongshu_qianfan",
            "runtime_consumed": False,
            "bindings": [binding],
        }
    )

    with pytest.raises(ValueError, match="outside module .* scope"):
        validate_catalog_bundle(catalog, registry)


def test_catalog_bundle_rejects_promotion_outside_module_table_scope():
    catalog = load_platform_metric_catalog()
    registry = load_source_binding_registry()
    reviews = load_promotion_reviews()
    review_index = next(
        index
        for index, review in enumerate(reviews)
        if review.platform_metric_id == 20 and review.module == "数据总览"
    )
    payload = reviews[review_index].model_dump(mode="json")
    payload.update({"canonical_table": "search_terms", "canonical_field": "gmv"})
    reviews[review_index] = type(reviews[review_index]).model_validate(payload)

    with pytest.raises(ValueError, match="outside module .* scope"):
        validate_catalog_bundle(catalog, registry, reviews)


def test_formal_registry_rejects_unapproved_entries(tmp_path):
    payload = {
        "version": 1,
        "platform": "xiaohongshu_qianfan",
        "runtime_consumed": False,
        "bindings": [
            {
                "platform_metric_id": 20,
                "module": "数据总览",
                "canonical_table": "business_overview_daily",
                "canonical_field": "gmv",
                "status": "proposed",
                "match_basis": "exact_existing_alias",
                "confidence": "high",
                "grain": "shop_day",
                "time_basis": "payment_time",
                "unit": "cny",
                "value_encoding": "decimal",
                "aggregation": "sum",
                "approved_definition_sha256": "0" * 64,
            }
        ],
    }
    path = tmp_path / "bindings.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")

    from xhs_ceramics_analytics.contracts.platform_catalog import load_source_binding_registry

    with pytest.raises(ValidationError, match="only contain accepted"):
        load_source_binding_registry(path)


@pytest.mark.skipif(
    not all(path.exists() for path in RAW_INPUTS),
    reason="ignored HAR extracts are only available in the maintainer checkout",
)
def test_semantic_catalog_generator_is_deterministic_and_scrubbed(tmp_path):
    script = ROOT / "scripts" / "build_xhs_semantic_catalog.py"
    outputs: list[dict[str, Path]] = []

    for run_name in ("first", "second"):
        run_dir = tmp_path / run_name
        catalog_path = run_dir / "catalog.yaml"
        promotion_path = run_dir / "promotion.csv"
        local_output_dir = run_dir / "local"
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--api-metrics",
                str(RAW_INPUTS[0]),
                "--field-candidates",
                str(RAW_INPUTS[1]),
                "--api-schema",
                str(RAW_INPUTS[2]),
                "--source-bindings",
                str(BINDING_PATH),
                "--catalog-output",
                str(catalog_path),
                "--promotion-output",
                str(promotion_path),
                "--local-output-dir",
                str(local_output_dir),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        outputs.append(
            {
                "catalog": catalog_path,
                "promotion": promotion_path,
                "ledger": local_output_dir / "field_review_ledger.csv",
                "schema": local_output_dir / "api_schema_snapshot.csv",
                "metadata": local_output_dir / "metadata.json",
            }
        )

    for key in outputs[0]:
        assert outputs[0][key].read_bytes() == outputs[1][key].read_bytes()

    forbidden = ("https://", "http://", "/Users/", ".har")
    for path in outputs[0].values():
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"generated file {path} contains {token!r}"

    metadata = (outputs[0]["metadata"]).read_text(encoding="utf-8")
    assert '"platform_metric_count": 134' in metadata
    assert '"candidate_count": 892' in metadata
    assert '"schema_path_count": 2359' in metadata


@pytest.mark.skipif(
    not all(path.exists() for path in RAW_INPUTS),
    reason="ignored HAR extracts are only available in the maintainer checkout",
)
def test_generator_fails_before_overwriting_catalog_on_empty_metric_input(tmp_path):
    empty_metrics = tmp_path / "empty.csv"
    empty_metrics.write_text(
        "field,explanation,metric_id,modules,online,source_url\n",
        encoding="utf-8",
    )
    catalog_output = tmp_path / "catalog.yaml"
    catalog_output.write_text("sentinel\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_xhs_semantic_catalog.py"),
            "--api-metrics",
            str(empty_metrics),
            "--field-candidates",
            str(RAW_INPUTS[1]),
            "--api-schema",
            str(RAW_INPUTS[2]),
            "--source-bindings",
            str(BINDING_PATH),
            "--catalog-output",
            str(catalog_output),
            "--promotion-output",
            str(tmp_path / "promotion.csv"),
            "--local-output-dir",
            str(tmp_path / "local"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "contains no stable numeric metric IDs" in result.stderr
    assert catalog_output.read_text(encoding="utf-8") == "sentinel\n"


@pytest.mark.skipif(
    not all(path.exists() for path in RAW_INPUTS),
    reason="ignored HAR extracts are only available in the maintainer checkout",
)
def test_generator_fails_before_overwriting_catalog_on_incomplete_metric_input(tmp_path):
    incomplete_metrics = tmp_path / "incomplete.csv"
    with incomplete_metrics.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "field",
                "explanation",
                "metric_id",
                "modules",
                "online",
                "source_url",
            ),
        )
        writer.writeheader()
        writer.writerow(
            {
                "field": "支付金额",
                "explanation": "统计时间（订单支付时间）内的支付金额",
                "metric_id": "20",
                "modules": "数据总览",
                "online": "true",
                "source_url": (
                    "https://ark.xiaohongshu.com/api/edith/business_data/"
                    "metric_dictionary/batchsearch"
                ),
            }
        )
    catalog_output = tmp_path / "catalog.yaml"
    catalog_output.write_text("sentinel\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_xhs_semantic_catalog.py"),
            "--api-metrics",
            str(incomplete_metrics),
            "--field-candidates",
            str(RAW_INPUTS[1]),
            "--api-schema",
            str(RAW_INPUTS[2]),
            "--source-bindings",
            str(BINDING_PATH),
            "--catalog-output",
            str(catalog_output),
            "--promotion-output",
            str(tmp_path / "promotion.csv"),
            "--local-output-dir",
            str(tmp_path / "local"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "API metric input is incomplete" in result.stderr
    assert catalog_output.read_text(encoding="utf-8") == "sentinel\n"
