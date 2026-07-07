"""Tests for the declarative view-spec data model + pure validation.

Covers the numeric-trust boundary rules 1-3 (source/columns/rows/supports_claim/
digit-free prose), derive_confidence (rule 5), the count_view_kinds gate helper,
and the never-raise contract on garbage input.
"""
from xhs_ceramics_analytics.analysis.result import Finding
from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.reporting.view_spec import (
    TEMPLATES,
    ViewSpec,
    count_view_kinds,
    derive_confidence,
    validate_view_spec,
)


# ---- fixtures -------------------------------------------------------------

def _tables():
    return {
        "growth_bridge": [
            {"component": "转化", "delta_gmv": 12000, "note": "a"},
            {"component": "流量", "delta_gmv": 8000, "note": "b"},
            {"component": "客单价", "delta_gmv": -3000, "note": "c"},
        ]
    }


def _valid_spec():
    return {
        "view_id": "core.gmv_bridge_table",
        "section_id": "core_business",
        "supports_claim": "core.gmv_bridge",
        "template": "breakdown_waterfall",
        "source": {"task_id": "core_business_diagnosis", "table": "growth_bridge"},
        "columns": ["component", "delta_gmv"],
        "column_labels": {"component": "增长来源", "delta_gmv": "对GMV的拉动"},
        "rows": {
            "sort_by": "delta_gmv",
            "order": "desc",
            "top_n": 5,
            "highlight": {"component": "转化"},
        },
        "chart": {"x": "component", "y": "delta_gmv"},
        "title": "GMV 增长拆解:谁在拉动、谁在抵消",
        "how_to_read": "柱子向右为拉动、向左为抵消,越长影响越大",
        "why_it_matters": "锁定被转化抵消的那一块,是本周第一优先",
    }


# ---- whitelist ------------------------------------------------------------

def test_templates_whitelist_is_exactly_the_five():
    assert TEMPLATES == frozenset(
        {
            "comparison_table",
            "ranking_table",
            "trend_line",
            "breakdown_waterfall",
            "share_bar",
        }
    )


# ---- accept valid ---------------------------------------------------------

def test_accept_valid_spec():
    assert validate_view_spec(_valid_spec(), _tables()) == []


def test_validate_does_not_mutate_inputs():
    spec = _valid_spec()
    tables = _tables()
    before_spec = repr(spec)
    before_tables = repr(tables)
    validate_view_spec(spec, tables)
    assert repr(spec) == before_spec
    assert repr(tables) == before_tables


# ---- rule 1: source.table exists -----------------------------------------

def test_reject_nonexistent_table():
    spec = _valid_spec()
    spec["source"]["table"] = "does_not_exist"
    errs = validate_view_spec(spec, _tables())
    assert errs
    assert any("does_not_exist" in e for e in errs)


# ---- rule 1: columns subset -----------------------------------------------

def test_reject_nonexistent_column():
    spec = _valid_spec()
    spec["columns"] = ["component", "ghost_col"]
    errs = validate_view_spec(spec, _tables())
    assert any("ghost_col" in e for e in errs)


# ---- rule 1: rows are select/sort/TopN/highlight only ---------------------

def test_reject_aggregation_key_in_rows():
    spec = _valid_spec()
    spec["rows"] = {"aggregate": "sum", "group_by": "component"}
    errs = validate_view_spec(spec, _tables())
    assert any("aggregate" in e or "group_by" in e or "聚合" in e for e in errs)


def test_reject_numeric_threshold_highlight():
    spec = _valid_spec()
    spec["rows"]["highlight"] = {"delta_gmv": {">": 10000}}
    errs = validate_view_spec(spec, _tables())
    assert errs


def test_reject_highlight_value_not_existing_category():
    spec = _valid_spec()
    spec["rows"]["highlight"] = {"component": "不存在的类别"}
    errs = validate_view_spec(spec, _tables())
    assert errs


def test_reject_sort_by_nonexistent_column():
    spec = _valid_spec()
    spec["rows"]["sort_by"] = "ghost_col"
    errs = validate_view_spec(spec, _tables())
    assert any("ghost_col" in e for e in errs)


def test_reject_bad_order():
    spec = _valid_spec()
    spec["rows"]["order"] = "sideways"
    errs = validate_view_spec(spec, _tables())
    assert errs


def test_reject_non_positive_top_n():
    spec = _valid_spec()
    spec["rows"]["top_n"] = 0
    errs = validate_view_spec(spec, _tables())
    assert errs


def test_top_n_bool_is_rejected():
    spec = _valid_spec()
    spec["rows"]["top_n"] = True  # bool is not a structural int
    errs = validate_view_spec(spec, _tables())
    assert errs


# ---- unknown template -----------------------------------------------------

def test_reject_unknown_template():
    spec = _valid_spec()
    spec["template"] = "pie_chart_3d"
    errs = validate_view_spec(spec, _tables())
    assert any("pie_chart_3d" in e or "template" in e for e in errs)


# ---- rule 3: supports_claim non-empty -------------------------------------

def test_reject_empty_supports_claim():
    spec = _valid_spec()
    spec["supports_claim"] = "  "
    errs = validate_view_spec(spec, _tables())
    assert any("supports_claim" in e for e in errs)


def test_reject_missing_supports_claim():
    spec = _valid_spec()
    del spec["supports_claim"]
    errs = validate_view_spec(spec, _tables())
    assert any("supports_claim" in e for e in errs)


# ---- rule 2: no bare digits in prose --------------------------------------

def test_reject_digit_in_title():
    spec = _valid_spec()
    spec["title"] = "GMV 增长 12000 元拆解"
    errs = validate_view_spec(spec, _tables())
    assert any("title" in e for e in errs)


def test_reject_digit_in_how_to_read():
    spec = _valid_spec()
    spec["how_to_read"] = "看前 3 名"
    errs = validate_view_spec(spec, _tables())
    assert any("how_to_read" in e for e in errs)


def test_reject_digit_in_column_label():
    spec = _valid_spec()
    spec["column_labels"]["delta_gmv"] = "对GMV的拉动(单位:1000元)"
    errs = validate_view_spec(spec, _tables())
    assert errs


def test_emoji_in_prose_is_allowed():
    spec = _valid_spec()
    spec["title"] = "GMV 增长拆解 🚀 谁在拉动"
    assert validate_view_spec(spec, _tables()) == []


# ---- derive_confidence (rule 5) -------------------------------------------

def _finding(strength):
    return Finding(title="t", conclusion="c", evidence_strength=strength)


def test_derive_confidence_strong():
    assert derive_confidence(_finding(EvidenceStrength.STRONG)) == "强"


def test_derive_confidence_medium():
    assert derive_confidence(_finding(EvidenceStrength.MEDIUM)) == "中"


def test_derive_confidence_weak():
    assert derive_confidence(_finding(EvidenceStrength.WEAK)) == "弱"


def test_derive_confidence_not_judgable_degrades_to_weak():
    assert derive_confidence(_finding(EvidenceStrength.NOT_JUDGABLE)) == "弱"


def test_derive_confidence_accepts_raw_string():
    class Raw:
        evidence_strength = "strong"

    assert derive_confidence(Raw()) == "强"


def test_derive_confidence_never_raises_on_garbage():
    assert derive_confidence(None) == "弱"
    assert derive_confidence(object()) == "弱"

    class Bad:
        evidence_strength = "banana"

    assert derive_confidence(Bad()) == "弱"


# ---- count_view_kinds (gate helper, rule 4 lives in the gate) -------------

def test_count_view_kinds_splits_tables_and_charts():
    specs = [
        {"template": "comparison_table"},
        {"template": "ranking_table"},
        {"template": "trend_line"},
        {"template": "breakdown_waterfall"},
        {"template": "share_bar"},
    ]
    assert count_view_kinds(specs) == {"tables": 2, "charts": 3}


def test_count_view_kinds_ignores_unknown_templates():
    specs = [{"template": "comparison_table"}, {"template": "bogus"}, {}]
    assert count_view_kinds(specs) == {"tables": 1, "charts": 0}


def test_count_view_kinds_never_raises_on_garbage():
    assert count_view_kinds(None) == {"tables": 0, "charts": 0}
    assert count_view_kinds("nope") == {"tables": 0, "charts": 0}
    assert count_view_kinds([None, 42, "x"]) == {"tables": 0, "charts": 0}


def test_count_view_kinds_accepts_viewspec_objects():
    specs = [ViewSpec(template="comparison_table"), ViewSpec(template="trend_line")]
    assert count_view_kinds(specs) == {"tables": 1, "charts": 1}


# ---- never-raise on garbage input -----------------------------------------

def test_validate_never_raises_on_non_dict_spec():
    assert isinstance(validate_view_spec(None, _tables()), list)
    assert validate_view_spec(None, _tables())  # non-empty errors, no raise
    assert isinstance(validate_view_spec("garbage", _tables()), list)
    assert isinstance(validate_view_spec(42, _tables()), list)


def test_validate_never_raises_on_bad_result_tables():
    assert isinstance(validate_view_spec(_valid_spec(), None), list)
    assert isinstance(validate_view_spec(_valid_spec(), "nope"), list)
    assert isinstance(validate_view_spec({}, {}), list)


def test_validate_tolerates_empty_spec():
    errs = validate_view_spec({}, _tables())
    assert isinstance(errs, list)
    assert errs  # missing everything → many errors, but no raise
