"""Declarative view-spec data model + PURE validation (the numeric-trust boundary).

A curation agent emits only a *view-spec*: which template to use, which existing
columns/rows to select, and prose captions. It writes **no numeric values** except
structural integers (``top_n``). A deterministic engine (``curated_view``) later
fills every displayed number from the already-computed ``result.tables``. This
module owns the boundary check: it rejects any spec that would let agent-authored
text carry a fabricated number, or that tries to re-aggregate what L1 already
computed.

Everything here is pure and never raises — a malformed spec (even a non-dict) or a
missing/garbage ``result_tables`` returns a list of human-readable error strings
(empty list == valid), so a bad view degrades to "dropped" rather than crashing the
report. The per-domain cap (rule 4) is cross-view and belongs to the gate; this
module only exposes :func:`count_view_kinds` for the gate to use.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from xhs_ceramics_analytics.evidence import EvidenceStrength

# Whitelist enum (spec §Templates). Split by rendered kind so the gate's per-domain
# cap (≤2 tables + ≤1 chart) can count each view without re-deriving the mapping.
TABLE_TEMPLATES: frozenset[str] = frozenset({"comparison_table", "ranking_table"})
CHART_TEMPLATES: frozenset[str] = frozenset(
    {"trend_line", "breakdown_waterfall", "share_bar"}
)
TEMPLATES: frozenset[str] = TABLE_TEMPLATES | CHART_TEMPLATES

# rows may only select / sort / TopN / highlight — never aggregate or numeric-threshold.
_ALLOWED_ROW_KEYS: frozenset[str] = frozenset({"sort_by", "order", "top_n", "highlight"})
_ALLOWED_ORDERS: frozenset[str] = frozenset({"asc", "desc"})

_DIGIT_RE = re.compile(r"\d")  # any Unicode decimal digit — incl. fullwidth ０-９

# A fabricated magnitude can also be smuggled in CJK numerals (九十九万 = 990000),
# which carry no ASCII digit and so slip past ``_DIGIT_RE``. We flag any of:
#   • a run of ≥2 adjacent CJK numerals (九十九万 / 三千万 / 十万 / 五十);
#   • a 点-linked decimal (三点五 = 3.5);
#   • a single numeral bound to a magnitude unit — proportion/money (三成 / 五元), a
#     multiplier (五倍) or a discount (八折);
#   • a 分之-connective proportion (百分之五 = 5% / 三分之一 = 1/3 / 千分之二 = 2‰), plus
#     the 百分百 contraction (= 100%). This is the dangerous case a single-numeral
#     percentage/fraction otherwise escapes: 百分之五十 (2-run) and 五成 (unit) are
#     caught, but 百分之五 has no run and no bound unit — the 之 connective separates its
#     numerals — so without this branch a fabricated "5%" ships un-gated. The branch
#     requires BOTH the 之 connective and a bound numeral, so non-quantity 分-words stay
#     allowed: 十分满意 (very), 部分, 分析, 百分点 (几 not a numeral) all pass.
# Incidental *single* numerals — ordinals (第一) and "that block" (那一块) — carry no
# scale/unit neighbour and are tolerated, so the design's own captions still pass. The
# bias is deliberate: a false-reject only drops one curated view (the section keeps its
# prose), whereas a miss would ship a fabricated number — over-blocking is the safe
# direction, so rare idioms (千万别, 万一 = "just in case", 一一 = "one by one") are
# accepted casualties.
#
# Deliberately EXCLUDED: 块/角 (colloquial money) as units — they collide with the
# measure-word phrase 一块 (a piece/area) that the design's own caption uses ("那一块"),
# so treating them as magnitude units would false-reject legitimate prose (倍/折 have no
# such collision — 翻倍/打折 carry no bound numeral — so they are safe). And 半 as a
# numeral — it is a qualitative "half/semi" descriptor (减半/过半), and admitting it would
# false-reject 半成品 (semi-finished ware, core ceramics vocabulary) via the 成 unit.
_CJK_NUMERAL = "〇零一二三四五六七八九十百千万亿两"
_CJK_MAGNITUDE_UNIT = "元成％%‰倍折"
_CJK_MAGNITUDE_RE = re.compile(
    rf"[{_CJK_NUMERAL}]{{2,}}"
    rf"|[{_CJK_NUMERAL}]\s*点\s*[{_CJK_NUMERAL}]"
    rf"|[{_CJK_NUMERAL}]\s*[{_CJK_MAGNITUDE_UNIT}]"
    rf"|[{_CJK_NUMERAL}]\s*分\s*之\s*[{_CJK_NUMERAL}]"  # 百分之N / X分之Y 百分比·分数
    rf"|百\s*分\s*百"  # 百分百 = 100% 的口语缩写(两个 百 不相邻,run 分支漏掉)
)


def _has_foreign_numeric_glyph(s: str) -> bool:
    """True if any char is a *non-decimal* number glyph the plain ``\\d`` scan misses:
    a vulgar fraction (½ ⅓), circled/parenthesised or superscript digit (① ③ ³), or a
    Roman numeral (Ⅳ). These are Unicode number categories ``No``/``Nl`` — never used in
    legitimate merchant prose, so a single one is a fabricated number. CJK numerals
    (三 / 五 / 兆) are category ``Lo`` (ideographs), NOT ``No``/``Nl``, so this never
    fires on them or on ideographic words like 征兆 — they are handled with nuance by
    ``_CJK_MAGNITUDE_RE`` instead. ``〇`` is ``Nl`` but a CJK numeral, so it is skipped
    explicitly. Decimal digits (``Nd``) are left to ``_DIGIT_RE``. Never raises."""
    for ch in s:
        if ch in _CJK_NUMERAL:
            continue
        if unicodedata.category(ch) in ("No", "Nl"):
            return True
    return False


def contains_fabricated_number(text: object) -> bool:
    """True if ``text`` carries a bare number the numeric-trust boundary forbids.

    Three complementary detectors:
      1. ASCII / fullwidth decimal digits (``_DIGIT_RE``);
      2. CJK-numeral magnitudes (``_CJK_MAGNITUDE_RE``) — a ≥2-numeral run, a 点-linked
         decimal, a numeral bound to a magnitude unit (成/元/倍/折), or a 分之-connective
         proportion (百分之五 / 三分之一 / 百分百);
      3. non-decimal number glyphs — fractions, circled/superscript digits, Roman
         numerals (:func:`_has_foreign_numeric_glyph`).
    Pure and never raises — non-str input is stringified, so callers can scan any
    agent-authored caption/sentence uniformly."""
    s = str(text)
    return bool(
        _DIGIT_RE.search(s)
        or _CJK_MAGNITUDE_RE.search(s)
        or _has_foreign_numeric_glyph(s)
    )

# evidence_strength → reader-facing confidence tag (rule 5). NOT_JUDGABLE and any
# unrecognized value degrade to the weakest tag rather than raising.
_EVIDENCE_TO_TAG: dict[EvidenceStrength, str] = {
    EvidenceStrength.STRONG: "强",
    EvidenceStrength.MEDIUM: "中",
    EvidenceStrength.WEAK: "弱",
    EvidenceStrength.NOT_JUDGABLE: "弱",
}


@dataclass(frozen=True)
class ViewSpec:
    """Typed container for one curated view. All fields default to empty so a
    partially-formed spec is still constructible; validation is done by
    :func:`validate_view_spec` on the raw dict (agents emit dicts)."""

    view_id: str = ""
    section_id: str = ""
    supports_claim: str = ""
    template: str = ""
    source: dict = field(default_factory=dict)  # {task_id, table}
    columns: tuple[str, ...] = ()
    column_labels: dict = field(default_factory=dict)  # {column: label}
    rows: dict = field(default_factory=dict)  # {sort_by, order, top_n, highlight}
    chart: dict = field(default_factory=dict)  # {x, y}
    title: str = ""
    how_to_read: str = ""
    why_it_matters: str = ""

    @classmethod
    def from_dict(cls, spec: object) -> "ViewSpec":
        """Build a ViewSpec from a raw dict, tolerating missing/garbage fields.
        Never raises — unknown types fall back to the field default."""
        if not isinstance(spec, dict):
            return cls()
        cols = spec.get("columns")
        columns = tuple(cols) if isinstance(cols, (list, tuple)) else ()
        return cls(
            view_id=str(spec.get("view_id") or ""),
            section_id=str(spec.get("section_id") or ""),
            supports_claim=str(spec.get("supports_claim") or ""),
            template=str(_template_of(spec) or ""),
            source=spec.get("source") if isinstance(spec.get("source"), dict) else {},
            columns=columns,
            column_labels=spec.get("column_labels")
            if isinstance(spec.get("column_labels"), dict)
            else {},
            rows=spec.get("rows") if isinstance(spec.get("rows"), dict) else {},
            chart=spec.get("chart") if isinstance(spec.get("chart"), dict) else {},
            title=str(spec.get("title") or ""),
            how_to_read=str(spec.get("how_to_read") or ""),
            why_it_matters=str(spec.get("why_it_matters") or ""),
        )


def derive_confidence(finding: object) -> str:
    """Rule 5: derive 强/中/弱 deterministically from ``finding.evidence_strength``.

    Never authored by the agent, never raises. Accepts an enum member, its raw
    string value, or garbage; anything unrecognized degrades to 弱."""
    es = getattr(finding, "evidence_strength", None)
    if not isinstance(es, EvidenceStrength):
        try:
            es = EvidenceStrength(es)
        except (ValueError, TypeError):
            return "弱"
    return _EVIDENCE_TO_TAG.get(es, "弱")


def count_view_kinds(specs: object) -> dict[str, int]:
    """Split a list of view-specs into {tables, charts} counts for the gate's
    per-domain cap (rule 4). Ignores unknown/garbage entries. Never raises."""
    tables = charts = 0
    if not isinstance(specs, (list, tuple)):
        return {"tables": 0, "charts": 0}
    for spec in specs:
        template = _template_of(spec)
        if template in TABLE_TEMPLATES:
            tables += 1
        elif template in CHART_TEMPLATES:
            charts += 1
    return {"tables": tables, "charts": charts}


def validate_view_spec(spec: object, result_tables: object) -> list[str]:
    """Validate one view-spec against the real ``result.tables`` (rules 1-3).

    Returns human-readable error strings; an empty list means valid. Pure — it
    never mutates its inputs and never raises, so any malformed input (including a
    non-dict spec) yields errors instead of an exception. rules 4 (per-domain cap)
    and 5 (confidence) are handled elsewhere (gate / :func:`derive_confidence`).
    """
    if not isinstance(spec, dict):
        return ["view-spec 必须是对象(dict)"]
    if not isinstance(result_tables, dict):
        result_tables = {}

    errors: list[str] = []

    _check_template(spec, errors)
    _check_supports_claim(spec, errors)
    table_rows, real_columns = _check_source(spec, result_tables, errors)
    _check_columns(spec, table_rows, real_columns, errors)
    _check_rows(spec, table_rows, real_columns, errors)
    _check_chart(spec, real_columns, errors)
    _check_no_digits(spec, errors)

    return errors


# ---- rule checks (each pure, appends to `errors`) -------------------------


def _check_template(spec: dict, errors: list[str]) -> None:
    template = _template_of(spec)
    if template not in TEMPLATES:
        errors.append(
            f"未知模板 template={template!r}(允许:{sorted(TEMPLATES)})"
        )


def _check_supports_claim(spec: dict, errors: list[str]) -> None:
    # rule 3: anti-dump — every view MUST cite a claim (real-claim check is the gate's).
    sc = spec.get("supports_claim")
    if not (isinstance(sc, str) and sc.strip()):
        errors.append("supports_claim 必填且不能为空(anti-dump)")


def _check_source(
    spec: dict, result_tables: dict, errors: list[str]
) -> tuple[list | None, set[str]]:
    """rule 1a: source.table must exist in result.tables. Returns (rows, columns)."""
    source = spec.get("source")
    if not isinstance(source, dict):
        errors.append("source 必须是含 task_id/table 的对象")
        return None, set()
    table_name = source.get("table")
    if not table_name:
        errors.append("source.table 必填")
        return None, set()
    if table_name not in result_tables:
        errors.append(f"source.table={table_name!r} 不在 result.tables 中")
        return None, set()
    table_rows = result_tables.get(table_name)
    return table_rows, _columns_of(table_rows)


def _check_columns(
    spec: dict, table_rows: list | None, real_columns: set[str], errors: list[str]
) -> None:
    """rule 1b: columns required, non-empty, and ⊆ the table's real columns."""
    columns = spec.get("columns")
    if not isinstance(columns, (list, tuple)) or not columns:
        errors.append("columns 必填且为非空列表")
        return
    if not real_columns:
        return  # unknown columns (empty/garbage table) — can't verify, don't false-reject
    for col in columns:
        if col not in real_columns:
            errors.append(f"列 {col!r} 不存在于源表")


def _check_rows(
    spec: dict, table_rows: list | None, real_columns: set[str], errors: list[str]
) -> None:
    """rule 1c: rows may only select / sort / TopN / highlight-by-existing-category."""
    rows = spec.get("rows")
    if rows is None:
        return
    if not isinstance(rows, dict):
        errors.append("rows 必须是对象")
        return

    extra = set(rows) - _ALLOWED_ROW_KEYS
    if extra:
        errors.append(
            f"rows 含非法键 {sorted(extra)}(仅允许 select/sort/TopN/highlight,"
            "禁止聚合或数值阈值)"
        )

    sort_by = rows.get("sort_by")
    if sort_by is not None and real_columns and sort_by not in real_columns:
        errors.append(f"rows.sort_by={sort_by!r} 不是源表的列")

    order = rows.get("order")
    if order is not None and order not in _ALLOWED_ORDERS:
        errors.append(f"rows.order={order!r} 只能是 asc/desc")

    top_n = rows.get("top_n")
    if top_n is not None and (
        not isinstance(top_n, int) or isinstance(top_n, bool) or top_n <= 0
    ):
        errors.append(f"rows.top_n={top_n!r} 必须是正整数")

    _check_highlight(rows.get("highlight"), table_rows, real_columns, errors)


def _check_highlight(
    highlight: object, table_rows: list | None, real_columns: set[str], errors: list[str]
) -> None:
    """highlight selects an EXISTING categorical value — never a numeric threshold."""
    if highlight is None:
        return
    if not isinstance(highlight, dict):
        errors.append("rows.highlight 必须是 {列: 类别值} 对象")
        return
    for col, value in highlight.items():
        # A dict value is how you'd smuggle a numeric threshold ({">": 10000}).
        if isinstance(value, (dict, list, tuple, set)):
            errors.append(
                f"rows.highlight[{col!r}] 只能按已有类别值高亮,不能是数值阈值/操作符"
            )
            continue
        if not real_columns:
            continue
        if col not in real_columns:
            errors.append(f"rows.highlight 列 {col!r} 不存在于源表")
        elif not _value_in_column(table_rows, col, value):
            errors.append(
                f"rows.highlight[{col!r}]={value!r} 不是该列已有的类别值"
            )


def _check_chart(spec: dict, real_columns: set[str], errors: list[str]) -> None:
    """Chart templates bind already-chosen columns — x/y must be real columns."""
    chart = spec.get("chart")
    if not isinstance(chart, dict) or not real_columns:
        return
    for axis in ("x", "y"):
        col = chart.get(axis)
        if col is not None and col not in real_columns:
            errors.append(f"chart.{axis}={col!r} 不是源表的列")


def _check_no_digits(spec: dict, errors: list[str]) -> None:
    """rule 2: title / how_to_read / why_it_matters / column_labels are prose — no
    bare digits. Every agent-authored caption is scanned so no path lets a fabricated
    number reach the merchant view; displayed numbers live only in table cells,
    filled by the deterministic engine.

    ``source.task_id`` is scanned too: it is free-form agent text that is never
    validated against a registry, yet the engine renders it verbatim into the
    merchant-facing provenance footer (``来源:{task_id} · {table} · 证据:{...}``), so a
    bare digit there (e.g. ``转化拉低GMV约99万``) would smuggle a fabricated number
    past the boundary. ``source.table`` is deliberately NOT scanned here: it is
    existence-checked against ``result.tables`` (:func:`_check_source`), so it can
    only ever be a real, deterministic table key — a digit in one (e.g.
    ``sku_category_l2_mix``) is a traceable system identifier, not agent-fabricated
    content, and scanning it would false-reject a legitimate view."""
    for field_name in ("title", "how_to_read", "why_it_matters"):
        value = spec.get(field_name)
        if value is not None and contains_fabricated_number(value):
            errors.append(f"{field_name} 含裸数字(数字只能出现在表格单元格中)")
    labels = spec.get("column_labels")
    if isinstance(labels, dict):
        for col, label in labels.items():
            if label is not None and contains_fabricated_number(label):
                errors.append(
                    f"column_labels[{col!r}] 含裸数字(数字只能出现在表格单元格中)"
                )
    source = spec.get("source")
    if isinstance(source, dict):
        task_id = source.get("task_id")
        if task_id is not None and contains_fabricated_number(task_id):
            errors.append(
                "source.task_id 含裸数字(会被原样写入溯源脚注,数字只能出现在表格单元格中)"
            )


# ---- helpers --------------------------------------------------------------


def _columns_of(table_rows: object) -> set[str]:
    """Union of keys across all row dicts. Empty set for empty/garbage tables."""
    if not isinstance(table_rows, (list, tuple)):
        return set()
    columns: set[str] = set()
    for row in table_rows:
        if isinstance(row, dict):
            columns.update(row.keys())
    return columns


def _value_in_column(table_rows: object, column: str, value: object) -> bool:
    """True if `value` appears in `column` across the rows (string-compared)."""
    if not isinstance(table_rows, (list, tuple)):
        return False
    target = str(value)
    for row in table_rows:
        if isinstance(row, dict) and column in row and str(row[column]) == target:
            return True
    return False


def _template_of(spec: object) -> str | None:
    if isinstance(spec, ViewSpec):
        return spec.template
    if isinstance(spec, dict):
        template = spec.get("template")
        if isinstance(template, str) and template:
            return template
        chart_template = spec.get("chart_template") or spec.get("chart_type")
        if isinstance(chart_template, str) and chart_template in CHART_TEMPLATES:
            return chart_template
        alias = spec.get("view_type") or spec.get("type")
        if isinstance(alias, str):  # guard: `alias in CHART_TEMPLATES` hashes it → never raise
            if alias in ("table", "comparison_table"):
                return "comparison_table"
            if alias == "ranking_table":
                return "ranking_table"
            if alias in CHART_TEMPLATES:
                return alias
    return None
