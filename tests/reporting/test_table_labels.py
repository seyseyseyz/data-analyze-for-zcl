"""The shared human table-label lookup (the numeric-trust-boundary's provenance
names). Both the fact-layer HTML and the narrative provenance stamp read from ONE
map here so a table's merchant-facing name never diverges between the two layers."""
from xhs_ceramics_analytics.reporting.table_labels import TABLE_LABELS, table_label


def test_known_table_returns_its_human_label():
    # A real diagnosis table resolves to the curated Chinese label, not the raw key.
    assert table_label("gmv_bridge") == "增长归因（GMV 桥）"
    assert table_label("business_trend") == "GMV 趋势与结构性变化"


def test_unknown_table_degrades_to_underscore_stripped_key():
    # An unmapped table is never dropped — it degrades to a readable form of its key
    # (matching the fact-layer fallback), so provenance always renders SOMETHING.
    assert table_label("some_new_table") == "some new table"


def test_non_string_input_never_raises():
    # Provenance is a never-raise render path — garbage degrades to "".
    assert table_label(None) == ""
    assert table_label(123) == "123"


def test_table_labels_is_a_nonempty_mapping():
    assert isinstance(TABLE_LABELS, dict) and TABLE_LABELS
    # Spot-check the map still carries the deep-diagnosis tables the narrative cites.
    for key in ("business_trend", "gmv_bridge", "search_term_opportunities"):
        assert key in TABLE_LABELS
