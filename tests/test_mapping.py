from pathlib import Path

import pytest

from xhs_ceramics_analytics.importing.mapping import guess_field_mapping, guess_table_type
from xhs_ceramics_analytics.importing.profile import FileProfile, profile_csv


def test_profile_csv_detects_columns(fixture_dir):
    profile = profile_csv(fixture_dir / "notes.csv")
    assert profile.row_count == 3
    assert "note_id" in profile.columns
    assert profile.sample_rows[0]["note_id"] == "n1"


def test_profile_csv_normalizes_missing_sample_values(tmp_path):
    csv_path = tmp_path / "missing_values.csv"
    csv_path.write_text(
        "row_id,score,label\n"
        "1,10,filled\n"
        "2,,\n",
        encoding="utf-8",
    )

    profile = profile_csv(csv_path)

    assert profile.sample_rows[1]["score"] is None
    assert profile.sample_rows[1]["label"] is None


def test_guess_table_type_for_notes(fixture_dir):
    profile = profile_csv(fixture_dir / "notes.csv")
    assert guess_table_type(profile) == "notes"


def test_guess_table_type_rejects_unknown_columns():
    profile = FileProfile(
        path=Path("unknown.csv"),
        table_name="unknown_export",
        columns=["foo", "bar", "baz"],
        row_count=1,
        sample_rows=[],
    )

    with pytest.raises(ValueError, match="unknown_export"):
        guess_table_type(profile)


def test_guess_field_mapping_for_orders(fixture_dir):
    profile = profile_csv(fixture_dir / "orders.csv")
    mapping = guess_field_mapping(profile, "orders")
    assert mapping["order_id"] == "order_id"
    assert mapping["paid_time"] == "paid_time"
    assert mapping["sku_id"] == "sku_id"


def test_guess_field_mapping_preserves_spaced_order_headers():
    profile = FileProfile(
        path=Path("orders.csv"),
        table_name="orders",
        columns=["Order ID", "Paid Time", "SKU ID", "Quantity", "Paid Amount"],
        row_count=1,
        sample_rows=[],
    )

    mapping = guess_field_mapping(profile, "orders")

    assert mapping["order_id"] == "Order ID"
    assert mapping["paid_time"] == "Paid Time"
    assert mapping["sku_id"] == "SKU ID"
    assert mapping["quantity"] == "Quantity"
    assert mapping["paid_amount"] == "Paid Amount"


def test_guess_field_mapping_does_not_reuse_source_columns():
    profile = FileProfile(
        path=Path("comments.csv"),
        table_name="comments",
        columns=["note_id", "comment_text"],
        row_count=1,
        sample_rows=[],
    )

    mapping = guess_field_mapping(profile, "comments")

    assert mapping["comment_text"] == "comment_text"
    assert "comment_time" not in mapping
