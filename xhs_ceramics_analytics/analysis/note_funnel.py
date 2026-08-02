from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.db.sql_helpers import numeric_expr
from xhs_ceramics_analytics.evidence import EvidenceStrength

_COMMERCIAL_COLUMNS = {
    "product_clicks",
    "product_click_users",
    "note_paid_orders",
    "note_paid_buyers",
    "note_gmv",
    "note_refund_amount_pay",
    "to_shop_home_gmv",
    "to_live_gmv",
}


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        if not _table_exists(con, "notes"):
            return _missing_result("缺少 notes 表。")
        columns = _table_columns(con, "notes")
        if "note_id" not in columns:
            return _missing_result("notes 表缺少 note_id 字段。")

        rows = _funnel_rows(con, columns)
        limitations = _metric_limitations(columns)
    finally:
        con.close()

    findings = [
        Finding(
            title="漏斗指标已计算",
            conclusion="已在分母可用的情况下计算阅读率、互动率和分享率。",
            evidence_strength=(
                EvidenceStrength.MEDIUM
                if rows and not limitations
                else EvidenceStrength.NOT_JUDGABLE
            ),
            key_numbers={"notes": len(rows)},
            caveats=[],
        )
    ]
    tables = {"note_funnel": rows}

    if columns & _COMMERCIAL_COLUMNS:
        summary = _commercial_summary(rows)
        tables["note_commercial_funnel"] = [summary]
        findings.append(_commercial_finding(columns, summary, len(rows)))

    return AnalysisResult(
        task_id="note_funnel",
        title="笔记漏斗",
        findings=findings,
        tables=tables,
        limitations=limitations,
    )


def _funnel_rows(con, columns: set[str]) -> list[dict[str, object]]:
    text_fields = {
        "note_id": "note_id",
        "note_type": "note_type_optional",
        "related_product_id": "related_product_id_optional",
        "related_product_name": "related_product_name_optional",
    }
    numeric_fields = {
        "impressions": "impressions",
        "likes": "likes",
        "collects": "collects",
        "comments": "comments",
        "shares": "shares_optional",
        "video_seconds": "video_seconds_optional",
        "avg_read_seconds": "avg_read_seconds_optional",
        "completion_rate_pv": "completion_rate_pv_optional",
        "product_clicks": "product_clicks_optional",
        "product_click_rate_pv": "product_click_rate_pv_optional",
        "product_click_users": "product_click_users_optional",
        "pay_conversion_pv": "pay_conversion_pv_optional",
        "pay_conversion_uv": "pay_conversion_uv_optional",
        "note_paid_orders": "paid_orders_optional",
        "note_paid_buyers": "paid_buyers_optional",
        "note_gmv": "note_gmv_optional",
        "note_refund_amount_pay": "refund_amount_optional",
        "note_refund_rate_pay": "refund_rate_pay_optional",
        "note_refund_orders_pay": "refund_orders_optional",
        "add_to_cart_units": "add_to_cart_units_optional",
        "to_shop_home_count": "to_shop_home_count_optional",
        "to_shop_home_gmv": "to_shop_home_gmv_optional",
        "to_live_count": "to_live_count_optional",
        "to_live_gmv": "to_live_gmv_optional",
        "follow_clicks": "follow_clicks_optional",
        "danmu_count": "danmu_count_optional",
    }
    impressions = numeric_expr(columns, "impressions")
    reads = numeric_expr(columns, "reads")
    likes = numeric_expr(columns, "likes")
    collects = numeric_expr(columns, "collects")
    comments = numeric_expr(columns, "comments")
    shares = numeric_expr(columns, "shares")
    product_clicks = numeric_expr(columns, "product_clicks")
    paid_orders = numeric_expr(columns, "note_paid_orders")
    note_gmv = numeric_expr(columns, "note_gmv")
    refund_amount = numeric_expr(columns, "note_refund_amount_pay")
    selections = [
        f"{_text_expr(columns, 'title', fallback='note_id')} AS note_title",
        f"{reads} AS reads",
        f"CASE WHEN {impressions} > 0 THEN {reads} / {impressions} END AS read_rate",
        f"CASE WHEN {reads} > 0 THEN {likes} / {reads} END AS like_rate",
        f"CASE WHEN {reads} > 0 THEN {collects} / {reads} END AS collect_rate",
        f"CASE WHEN {reads} > 0 THEN {comments} / {reads} END AS comment_rate",
    ]
    selections.extend(
        f"{_text_expr(columns, field)} AS {alias}" for field, alias in text_fields.items()
    )
    selections.extend(
        f"{numeric_expr(columns, field)} AS {alias}" for field, alias in numeric_fields.items()
    )
    selections.extend(
        [
            f"CASE WHEN {reads} > 0 THEN {shares} / {reads} END AS share_rate",
            (f"CASE WHEN {reads} > 0 THEN {product_clicks} / {reads} END AS read_to_product_click"),
            (
                f"CASE WHEN {product_clicks} > 0 THEN {paid_orders} / {product_clicks} END "
                "AS product_click_to_order"
            ),
            (
                f"CASE WHEN {impressions} > 0 THEN {note_gmv} * 1000 / {impressions} END "
                "AS gmv_per_1k_impressions"
            ),
            (
                f"CASE WHEN {note_gmv} IS NOT NULL THEN {note_gmv} - "
                f"COALESCE({refund_amount}, 0) END AS net_note_gmv"
            ),
        ]
    )

    try:
        result = con.sql(
            f"""
            SELECT {", ".join(selections)}
            FROM notes
            ORDER BY reads DESC NULLS LAST
            """
        )
    except Exception:
        return []
    result_columns = result.columns
    return [_clean_row(dict(zip(result_columns, row, strict=True))) for row in result.fetchall()]


def _commercial_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    totals = {
        field: _sum_optional(rows, field)
        for field in (
            "impressions",
            "reads",
            "product_clicks_optional",
            "product_click_users_optional",
            "paid_orders_optional",
            "paid_buyers_optional",
            "note_gmv_optional",
            "refund_amount_optional",
            "refund_orders_optional",
            "add_to_cart_units_optional",
            "to_shop_home_count_optional",
            "to_shop_home_gmv_optional",
            "to_live_count_optional",
            "to_live_gmv_optional",
            "follow_clicks_optional",
            "danmu_count_optional",
        )
    }
    impressions = _float_or_none(totals["impressions"])
    reads = _float_or_none(totals["reads"])
    clicks = _float_or_none(totals["product_clicks_optional"])
    orders = _float_or_none(totals["paid_orders_optional"])
    gmv = _float_or_none(totals["note_gmv_optional"])
    refund = _float_or_none(totals["refund_amount_optional"])
    totals.update(
        {
            "read_rate": _rate(reads, impressions),
            "read_to_product_click": _rate(clicks, reads),
            "product_click_to_order": _rate(orders, clicks),
            "gmv_per_1k_impressions": _rate(gmv * 1000 if gmv is not None else None, impressions),
            "net_note_gmv": round(gmv - (refund or 0), 4) if gmv is not None else None,
        }
    )
    return totals


def _commercial_finding(columns: set[str], summary: dict[str, object], note_count: int) -> Finding:
    full_funnel = {"product_clicks", "note_paid_orders", "note_gmv"} <= columns
    available_labels = [
        label
        for field, label in (
            ("product_clicks", "商品点击"),
            ("product_click_users", "商品点击人数"),
            ("note_paid_orders", "支付订单"),
            ("note_paid_buyers", "支付人数"),
            ("note_gmv", "成交金额"),
            ("note_refund_amount_pay", "退款金额"),
            ("to_shop_home_gmv", "进店成交"),
            ("to_live_gmv", "直播间成交"),
        )
        if field in columns
    ]
    has_refund = "note_refund_amount_pay" in columns
    return Finding(
        title="笔记商业漏斗已贯通" if full_funnel else "笔记商业指标已扩展",
        conclusion=(
            "已把曝光、阅读、商品点击、支付订单和成交金额串联"
            + ("，并计算退款后净成交。" if has_refund else "；当前导出未含退款金额。")
            if full_funnel
            else f"已纳入当前导出可用的商业指标：{'、'.join(available_labels)}。"
        ),
        evidence_strength=(
            EvidenceStrength.MEDIUM if note_count else EvidenceStrength.NOT_JUDGABLE
        ),
        key_numbers={
            "notes": note_count,
            "paid_orders_optional": summary["paid_orders_optional"],
            "note_gmv_optional": summary["note_gmv_optional"],
            "net_note_gmv": summary["net_note_gmv"],
        },
        caveats=[
            "商业漏斗使用平台归因口径，是观察性结果，不代表笔记带来的增量成交。",
            "不同导出中的支付、退款和跳转指标可能存在归因窗口差异。",
        ],
        recommended_action=(
            "优先复用阅读到商品点击、商品点击到支付均较强且"
            + ("退款后净成交" if has_refund else "成交金额")
            + "仍高的笔记。"
            if full_funnel
            else "继续补齐商品点击、支付订单和成交金额，形成可比较的完整商业漏斗。"
        ),
    )


def _sum_optional(rows: list[dict[str, object]], field: str) -> float | None:
    values = [float(row[field]) for row in rows if row.get(field) is not None]
    return round(sum(values), 4) if values else None


def _rate(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _clean_row(row: dict[str, object]) -> dict[str, object]:
    cleaned = dict(row)
    for key, value in cleaned.items():
        if value is not None and isinstance(value, float):
            cleaned[key] = round(value, 6)
    return cleaned


def _text_expr(columns: set[str], column: str, fallback: str | None = None) -> str:
    if column in columns:
        return f"CAST({column} AS VARCHAR)"
    if fallback is not None and fallback in columns:
        return f"CAST({fallback} AS VARCHAR)"
    return "NULL"


def _missing_result(reason: str) -> AnalysisResult:
    return AnalysisResult(
        task_id="note_funnel",
        title="笔记漏斗",
        findings=[
            Finding(
                title="漏斗指标不可计算",
                conclusion="需要笔记 ID 和互动指标后，才能计算笔记漏斗。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                key_numbers={"notes": 0},
                caveats=["漏斗数据缺失应视为导入缺口。"],
                recommended_action="导出包含 impressions、reads、likes、collects 和 comments 的 notes 数据。",
            )
        ],
        tables={"note_funnel": []},
        limitations=[reason],
    )


def _metric_limitations(columns: set[str]) -> list[str]:
    missing = [
        column
        for column in ("impressions", "reads", "likes", "collects", "comments")
        if column not in columns
    ]
    return [f"笔记表缺少漏斗指标字段：{', '.join(missing)}。"] if missing else []


def _float_or_none(value: object | None) -> float | None:
    return float(value) if value is not None else None


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
