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
    contains_fabricated_number,
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


def test_reject_digit_in_why_it_matters():
    # why_it_matters is agent-authored prose too — a bare digit here would smuggle
    # a fabricated number past the numeric-trust boundary into the merchant view.
    spec = _valid_spec()
    spec["why_it_matters"] = "被抵消了 9999 元,占 50%"
    errs = validate_view_spec(spec, _tables())
    assert any("why_it_matters" in e for e in errs)


def test_reject_cjk_magnitude_in_why_it_matters():
    # A fabricated magnitude written in CJK numerals (九十九万 = 990000) must not slip
    # past the digit scan just because it uses no ASCII digits — same trust-boundary
    # breach as a bare "990000".
    spec = _valid_spec()
    spec["why_it_matters"] = "预计损失约九十九万元"
    errs = validate_view_spec(spec, _tables())
    assert any("why_it_matters" in e for e in errs)


def test_reject_cjk_magnitude_in_title():
    spec = _valid_spec()
    spec["title"] = "GMV 增长三千万拆解"
    errs = validate_view_spec(spec, _tables())
    assert any("title" in e for e in errs)


def test_reject_cjk_proportion_in_how_to_read():
    # 三成 = 30% — a numeral bound to a magnitude unit is still a fabricated number.
    spec = _valid_spec()
    spec["how_to_read"] = "转化贡献约三成"
    errs = validate_view_spec(spec, _tables())
    assert any("how_to_read" in e for e in errs)


def test_reject_fullwidth_digit_in_why_it_matters():
    # Fullwidth digits (Unicode Nd) are numbers too; the scan must catch them.
    spec = _valid_spec()
    spec["why_it_matters"] = "被抵消了 ９９９９ 元"
    errs = validate_view_spec(spec, _tables())
    assert any("why_it_matters" in e for e in errs)


def test_cjk_ordinal_in_prose_is_allowed():
    # Incidental single CJK numerals — ordinals (第一) and "that block" (那一块) — are
    # not magnitudes and must NOT false-reject; the design's own caption uses them.
    spec = _valid_spec()
    spec["title"] = "第一优先"
    spec["how_to_read"] = "先看那一块,再看两个次要项"
    spec["why_it_matters"] = "锁定被转化抵消的那一块,是本周第一优先"
    assert validate_view_spec(spec, _tables()) == []


def test_reject_digit_in_column_label():
    spec = _valid_spec()
    spec["column_labels"]["delta_gmv"] = "对GMV的拉动(单位:1000元)"
    errs = validate_view_spec(spec, _tables())
    assert errs


def test_reject_digit_in_source_task_id():
    # source.task_id is free-form agent text rendered verbatim into the provenance
    # footer; a bare digit there smuggles a fabricated number past the numeric-trust
    # boundary just like a caption digit would.
    spec = _valid_spec()
    spec["source"]["task_id"] = "转化拉低GMV约99万"
    errs = validate_view_spec(spec, _tables())
    assert any("task_id" in e for e in errs)


def test_real_table_name_with_digit_is_accepted():
    # A real result.tables key may contain a digit (e.g. sku_category_l2_mix). source
    # .table is existence-checked, never fabricated, so its digit must not false-reject
    # the view — only the free-form task_id is digit-scanned.
    spec = _valid_spec()
    spec["source"] = {"task_id": "sku_structure_diagnosis", "table": "sku_category_l2_mix"}
    tables = {"sku_category_l2_mix": [
        {"component": "转化", "delta_gmv": 12000, "note": "a"},
        {"component": "流量", "delta_gmv": 8000, "note": "b"},
        {"component": "客单价", "delta_gmv": -3000, "note": "c"},
    ]}
    assert validate_view_spec(spec, tables) == []


def test_emoji_in_prose_is_allowed():
    spec = _valid_spec()
    spec["title"] = "GMV 增长拆解 🚀 谁在拉动"
    assert validate_view_spec(spec, _tables()) == []


# ---- rule 2: contains_fabricated_number hardened glyph coverage -----------
# These close the caption-scan bypass: a curated view whose prose smuggled a
# fabricated number written as a Unicode fraction/circled-digit/superscript/Roman
# numeral, a CJK decimal (三点五), or a numeral bound to a multiplier/discount unit
# (五倍 / 八折) passed the old scan verbatim into the shipped merchant view. The scan
# is over-blocking-biased: a false reject only drops one view (prose stays); a miss
# ships an unverified number.

def test_contains_fabricated_number_flags_unicode_fraction():
    assert contains_fabricated_number("转化只占了½,空间还很大") is True
    assert contains_fabricated_number("不足⅓") is True


def test_contains_fabricated_number_flags_circled_and_superscript_digits():
    assert contains_fabricated_number("第①名遥遥领先") is True
    assert contains_fabricated_number("增长了³个身位") is True


def test_contains_fabricated_number_flags_roman_numeral():
    # Roman numerals are Unicode category Nl — a number glyph the plain \\d scan misses.
    assert contains_fabricated_number("阶段Ⅳ的表现") is True


def test_contains_fabricated_number_flags_cjk_decimal():
    # 三点五 = 3.5 — a decimal written entirely in CJK numerals, no ASCII digit.
    assert contains_fabricated_number("客单价约三点五") is True
    assert contains_fabricated_number("退货率二点八") is True


def test_contains_fabricated_number_flags_multiplier_and_discount_units():
    # 倍 (multiplier) and 折 (discount) are magnitude units in the same sense as 成/元:
    # a numeral bound to them is a fabricated quantity.
    assert contains_fabricated_number("转化拉动了五倍") is True
    assert contains_fabricated_number("客单价翻了两倍") is True
    assert contains_fabricated_number("清仓打到八折") is True


def test_contains_fabricated_number_tolerates_measure_word_and_ordinals():
    # Must NOT over-block: 那一块 (that block/area, a measure word), ordinals (第一),
    # and words that merely contain a unit/连接 char without a bound numeral.
    assert contains_fabricated_number("锁定被转化抵消的那一块") is False
    assert contains_fabricated_number("本周第一优先") is False
    assert contains_fabricated_number("重点看转化这个环节") is False  # 点 not between numerals
    assert contains_fabricated_number("这是一个好征兆") is False       # 兆 is a CJK ideograph, not a No/Nl glyph
    assert contains_fabricated_number("清仓要打折促销") is False       # 折 without a bound numeral
    assert contains_fabricated_number("增长倍数值得关注") is False     # 倍 without a bound numeral
    assert contains_fabricated_number("谁在拉动、谁在抵消") is False


def test_contains_fabricated_number_flags_chinese_percentage_and_fraction():
    # 百分之X / X分之Y is the dominant TEXTUAL form of a Chinese percentage/fraction. A
    # single-numeral operand carries no ≥2-numeral run and no bound unit, so without a
    # 分之-connective branch "5%" ships as 百分之五 un-gated while its synonyms 百分之五十
    # (2-run) and 五成 (unit) are blocked — an exploitable, inconsistent bypass.
    assert contains_fabricated_number("环比提升百分之五") is True
    assert contains_fabricated_number("百分之九的退货") is True
    assert contains_fabricated_number("转化只占三分之一") is True
    assert contains_fabricated_number("千分之二的差异") is True
    assert contains_fabricated_number("满意度百分之百") is True   # 百分之百 = 100%
    assert contains_fabricated_number("好评率百分百") is True     # 百分百 contraction = 100%


def test_contains_fabricated_number_tolerates_fen_zhi_lookalikes():
    # The 分之 branch requires BOTH the 之 connective and a bound numeral, so common
    # 分-words that are NOT quantities stay allowed (the over-block bias has limits).
    assert contains_fabricated_number("十分满意这批货") is False   # 十分 = "very", no 之
    assert contains_fabricated_number("大部分已售出") is False     # 部分, 分 not numeral-bound
    assert contains_fabricated_number("先做数据分析") is False     # 分析
    assert contains_fabricated_number("半成品占比偏高") is False   # 半 is not a numeral; 半成 must not trip the unit branch
    assert contains_fabricated_number("提升了几个百分点") is False  # 百分点: 几 not a numeral, no 之+numeral


def test_reject_chinese_percentage_in_why_it_matters():
    # End-to-end: a 百分之X percentage in agent prose must be rejected by the gate's
    # caption scan, just like the ASCII/万-numeral and 成/元 magnitude forms.
    spec = _valid_spec()
    spec["why_it_matters"] = "转化环比提升百分之五,值得复盘"
    errs = validate_view_spec(spec, _tables())
    assert any("why_it_matters" in e for e in errs)


def test_reject_cjk_decimal_in_why_it_matters():
    spec = _valid_spec()
    spec["why_it_matters"] = "客单价约三点五,仍有提升空间"
    errs = validate_view_spec(spec, _tables())
    assert any("why_it_matters" in e for e in errs)


def test_reject_unicode_fraction_in_how_to_read():
    spec = _valid_spec()
    spec["how_to_read"] = "转化只占了½,空间很大"
    errs = validate_view_spec(spec, _tables())
    assert any("how_to_read" in e for e in errs)


def test_reject_multiplier_unit_in_title():
    spec = _valid_spec()
    spec["title"] = "转化拉动五倍的秘密"
    errs = validate_view_spec(spec, _tables())
    assert any("title" in e for e in errs)


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
