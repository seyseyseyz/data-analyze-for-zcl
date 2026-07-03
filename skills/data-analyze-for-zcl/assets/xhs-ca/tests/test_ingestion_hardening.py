from pathlib import Path

import pytest

from xhs_ceramics_analytics.importing.mapping import _normalize_column_name
from xhs_ceramics_analytics.importing.profile import FileProfile


def _profile(columns: list[str]) -> FileProfile:
    return FileProfile(
        path=Path("mem.csv"),
        table_name="mem",
        columns=columns,
        row_count=0,
        sample_rows=[],
    )


def test_fullwidth_and_halfwidth_parens_normalize_identically():
    assert _normalize_column_name("退款人数（支付时间）") == _normalize_column_name(
        "退款人数(支付时间)"
    )


def test_calibers_stay_distinct_after_normalization():
    pay = _normalize_column_name("退款金额（支付时间）")
    refundtime = _normalize_column_name("退款金额（退款时间）")
    assert pay != refundtime


def test_existing_ascii_normalization_unchanged():
    assert _normalize_column_name("Paid Time") == "paid_time"
    assert _normalize_column_name("  order-id  ") == "order_id"
    assert _normalize_column_name("退款人数（支付时间）") == "退款人数(支付时间)"


from xhs_ceramics_analytics.importing.mapping import (  # noqa: E402
    FIELD_ALIASES,
    GRAIN_KEYS,
    REQUIRED_COLUMNS,
    TABLE_SIGNATURES,
)


def test_every_signature_table_has_required_columns():
    assert set(REQUIRED_COLUMNS) == set(TABLE_SIGNATURES)


@pytest.mark.parametrize("table_type", sorted(TABLE_SIGNATURES))
def test_required_columns_invariants(table_type):
    signature = TABLE_SIGNATURES[table_type]
    required = REQUIRED_COLUMNS[table_type]
    alias_keys = set(FIELD_ALIASES.get(table_type, {}).keys())

    # Invariant A: the discriminative signature is required, EXCEPT its `_optional`
    # columns (orders.refund_status_optional, ad_performance_daily.campaign_name_optional),
    # which are guarded optional dims and must not raise false-positive diagnostics.
    mandatory_signature = {c for c in signature if not c.endswith("_optional")}
    assert mandatory_signature <= required

    # Invariant B: no required column is un-aliasable (would be permanently unmappable).
    assert required <= signature | alias_keys

    # Invariant C: grain keys are required (a missing grain key corrupts the coalesce).
    if table_type in GRAIN_KEYS:
        assert set(GRAIN_KEYS[table_type]) <= required


from xhs_ceramics_analytics.importing.mapping import (  # noqa: E402
    ColumnDiagnostic,
    ColumnMapping,
    guess_field_mapping,
    map_columns,
)

# A refund_overview header set that maps every Required column via shipped aliases.
_REFUND_FULL = [
    "统计时间", "账号名称", "载体",
    "退款金额（支付时间）", "退款人数（支付时间）", "退款率（支付时间）",
    "发货前退款金额（支付时间）", "发货后退款金额（支付时间）", "退货退款金额（支付时间）",
]


def test_map_columns_complete_profile_has_no_diagnostics():
    result = map_columns(_profile(_REFUND_FULL), "refund_overview")
    assert isinstance(result, ColumnMapping)
    assert result.diagnostics == ()
    assert result.mapping["refund_users"] == "退款人数（支付时间）"


def test_map_columns_missing_required_no_leftover_is_missing():
    # Drop the refund_users header; every other header still maps → empty leftover pool.
    columns = [c for c in _REFUND_FULL if c != "退款人数（支付时间）"]
    result = map_columns(_profile(columns), "refund_overview")
    diags = [d for d in result.diagnostics if d.required_column == "refund_users"]
    assert len(diags) == 1
    assert diags[0].status == "missing"
    assert diags[0].candidate_sources == ()
    assert isinstance(diags[0], ColumnDiagnostic)


def test_map_columns_unaliased_wording_is_ambiguous():
    # Replace the refund_users header with a genuinely-unaliased wording: it stays in
    # the leftover pool, so the diagnostic is "ambiguous" and names that header.
    columns = [c for c in _REFUND_FULL if c != "退款人数（支付时间）"] + ["退款人数合计"]
    result = map_columns(_profile(columns), "refund_overview")
    diags = [d for d in result.diagnostics if d.required_column == "refund_users"]
    assert len(diags) == 1
    assert diags[0].status == "ambiguous"
    assert "退款人数合计" in diags[0].candidate_sources


def test_map_columns_overrides_resolve_missing_column():
    columns = [c for c in _REFUND_FULL if c != "退款人数（支付时间）"] + ["退款人数合计"]
    overrides = {"refund_overview": {"refund_users": {"退款人数合计"}}}
    result = map_columns(_profile(columns), "refund_overview", overrides=overrides)
    assert result.mapping["refund_users"] == "退款人数合计"
    assert all(d.required_column != "refund_users" for d in result.diagnostics)


def test_guess_field_mapping_is_wrapper_over_map_columns():
    profile = _profile(_REFUND_FULL)
    assert guess_field_mapping(profile, "refund_overview") == map_columns(
        profile, "refund_overview"
    ).mapping


from xhs_ceramics_analytics.importing.overrides import load_overrides  # noqa: E402


def test_load_overrides_absent_file_returns_empty(tmp_path):
    assert load_overrides(tmp_path / "nope.yaml") == {}


def test_load_overrides_empty_file_returns_empty(tmp_path):
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")
    assert load_overrides(path) == {}


def test_load_overrides_parses_nested_dict_of_sets(tmp_path):
    path = tmp_path / "o.yaml"
    path.write_text(
        "refund_overview:\n"
        "  refund_users:\n"
        "    - 退款人数合计\n"
        "    - 退款客户数\n"
        "business_overview_daily:\n"
        "  net_gmv_pay: 退款后金额\n",  # scalar → one-element list
        encoding="utf-8",
    )
    result = load_overrides(path)
    assert result == {
        "refund_overview": {"refund_users": {"退款人数合计", "退款客户数"}},
        "business_overview_daily": {"net_gmv_pay": {"退款后金额"}},
    }


def test_load_overrides_malformed_top_level_raises(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_overrides(path)
