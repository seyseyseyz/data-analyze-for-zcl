from pathlib import Path

from xhs_ceramics_analytics.analytics.numeric import to_finite_float
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        rows, limitations, has_sales = _fetch_product_opportunities(con)
    finally:
        con.close()

    return AnalysisResult(
        task_id="product_opportunity_matrix",
        title="商品机会矩阵",
        findings=[
            Finding(
                title="SKU 机会已排序",
                conclusion="已按观察期销量表现对 SKU 排序，并标记初步机会类型。",
                evidence_strength=(
                    EvidenceStrength.WEAK if rows and has_sales else EvidenceStrength.NOT_JUDGABLE
                ),
                evidence_reason=_evidence_reason(rows, has_sales),
                key_numbers={"sku_count": len(rows)},
                caveats=["有显式 note-SKU 关联后，内容表现象限会更可靠。"],
            )
        ],
        tables={"product_opportunities": rows},
        limitations=limitations,
    )


def _fetch_product_opportunities(
    con,
) -> tuple[list[dict[str, object]], list[str], bool]:
    has_sales_table = _table_exists(con, "daily_sku_sales")
    sales_columns = _table_columns(con, "daily_sku_sales") if has_sales_table else set()
    has_sales_columns = has_sales_table and {"sku_id", "units", "gmv"}.issubset(sales_columns)
    sales = _sales_by_sku(con, sales_columns) if has_sales_columns else {}
    has_sales = bool(sales)

    catalog: dict[str, dict[str, object]] = {}
    if _table_exists(con, "skus"):
        sku_columns = _table_columns(con, "skus")
        if "sku_id" not in sku_columns:
            return [], ["skus 表缺少 sku_id 字段。"], False
        relation = con.sql("SELECT * FROM skus")
        for raw in _rows(relation):
            if raw.get("sku_id") is None:
                continue
            sku_id = str(raw["sku_id"])
            catalog[sku_id] = {
                "sku_id": sku_id,
                "sku_name": str(raw.get("sku_name") or sku_id),
                "inventory_optional": _maybe_float(raw.get("inventory_optional")),
            }

    sku_ids = sorted(set(catalog) | set(sales))
    if not sku_ids:
        return [], ["缺少 skus 表和可用的 daily_sku_sales 数据。"], False

    rows: list[dict[str, object]] = []
    for sku_id in sku_ids:
        catalog_row = catalog.get(sku_id, {})
        sales_row = sales.get(sku_id)
        units = sales_row.get("units") if sales_row else None
        gmv = sales_row.get("gmv") if sales_row else None
        active_days = sales_row.get("active_days") if sales_row else None
        units_per_day = units / active_days if units is not None and active_days else None
        gmv_per_day = gmv / active_days if gmv is not None and active_days else None
        inventory = catalog_row.get("inventory_optional")
        inventory_cover = (
            inventory / units_per_day
            if inventory is not None and units_per_day and units_per_day > 0
            else None
        )
        if sales_row is None:
            opportunity_type = "needs_sales_data"
        elif inventory is not None and inventory <= 0:
            opportunity_type = "out_of_stock_risk"
        elif inventory_cover is not None and inventory_cover <= 7:
            opportunity_type = "low_inventory_risk"
        else:
            opportunity_type = "sales_response_present"
        rows.append(
            {
                "sku_id": sku_id,
                "sku_name": catalog_row.get("sku_name") or sku_id,
                "units": units,
                "gmv": gmv,
                "active_days": active_days,
                "units_per_active_day": units_per_day,
                "gmv_per_active_day": gmv_per_day,
                "inventory_optional": inventory,
                "inventory_cover_active_days": inventory_cover,
                "opportunity_type": opportunity_type,
            }
        )
    rows.sort(
        key=lambda row: (
            row["gmv"] is not None,
            row["gmv"] or 0,
            row["units"] or 0,
            row["sku_id"],
        ),
        reverse=True,
    )

    limitations: list[str] = []
    if not catalog:
        limitations.append("缺少 skus 表，SKU 名称使用 sku_id。")
    if not has_sales:
        limitations.append(_sales_limitation(has_sales_table, has_sales_columns))
    if catalog and has_sales and "inventory_optional" not in _table_columns(con, "skus"):
        limitations.append("skus 缺少 inventory_optional，无法判断缺货和库存覆盖天数。")
    return rows, limitations, has_sales


def _sales_by_sku(con, columns: set[str]) -> dict[str, dict[str, object]]:
    relation = con.sql("SELECT * FROM daily_sku_sales")
    groups: dict[str, dict[str, object]] = {}
    for raw in _rows(relation):
        if raw.get("sku_id") is None:
            continue
        units = _maybe_float(raw.get("units"))
        gmv = _maybe_float(raw.get("gmv"))
        if units is None and gmv is None:
            continue
        sku_id = str(raw["sku_id"])
        group = groups.setdefault(
            sku_id, {"units_values": [], "gmv_values": [], "dates": set(), "rows": 0}
        )
        if units is not None:
            group["units_values"].append(units)
        if gmv is not None:
            group["gmv_values"].append(gmv)
        if "date" in columns and raw.get("date") is not None:
            group["dates"].add(str(raw["date"]))
        group["rows"] += 1

    output: dict[str, dict[str, object]] = {}
    for sku_id, group in groups.items():
        output[sku_id] = {
            "units": sum(group["units_values"]) if group["units_values"] else None,
            "gmv": sum(group["gmv_values"]) if group["gmv_values"] else None,
            "active_days": len(group["dates"]) if group["dates"] else group["rows"],
        }
    return output


def _maybe_float(value: object) -> float | None:
    return to_finite_float(value, None)


def _evidence_reason(rows: list[dict[str, object]], has_sales: bool) -> str:
    if rows and has_sales:
        return (
            "SKU 销售数据可用，可按销量、GMV 与活跃日速度排序；"
            "库存存在时仅做库存覆盖风险提示。当前仍是描述性机会排序，"
            "内容表现象限还需要继续纳入 note-SKU 关联证据。"
        )
    if rows:
        return "当前能识别 SKU 清单，但缺少可用销售数据，适合先补齐销量和销售额后再判断商品机会。"
    return "缺少 SKU 或销售数据，当前结论只适合指导补数顺序。"


def _rows(result) -> list[dict[str, object]]:
    columns = result.columns
    return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]


def _has_observed_sales(con) -> bool:
    return bool(
        con.sql(
            """
            SELECT COUNT(*)
            FROM daily_sku_sales
            WHERE sku_id IS NOT NULL
              AND (units IS NOT NULL OR gmv IS NOT NULL)
            """
        ).fetchone()[0]
    )


def _sales_limitation(has_sales_table: bool, has_sales_columns: bool) -> str:
    if not has_sales_table:
        return "缺少 daily_sku_sales 表。"
    if not has_sales_columns:
        return "daily_sku_sales 表的 units/gmv 字段不完整。"
    return "daily_sku_sales 表没有可用的 SKU 销售记录。"


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
