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
