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
