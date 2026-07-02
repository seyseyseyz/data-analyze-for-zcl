# Paid Traffic Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add first-version Xiaohongshu effect-ad analytics for 聚光, 薯条, and merchant-backend paid traffic exports.

**Architecture:** Extend the existing fixed-table DuckDB pipeline with one flexible `ad_performance_daily` fact table, one derived `ad_metrics` view, and two analysis tasks. Keep the current CLI, `AnalysisResult`, reporting, and evidence-strength model unchanged.

**Tech Stack:** Python 3.11+, DuckDB, pandas, Pydantic, Typer, Jinja2, pytest.

## Global Constraints

- Do not implement 蒲公英达人合作 analysis in this version.
- Do not require browser automation or live Xiaohongshu backend access.
- Do not force note or SKU attribution when the paid export only contains campaign, unit, or creative identifiers.
- Keep public commands unchanged: `xhs-ca build <exports...>`, `xhs-ca run <task>`, and `xhs-ca run all`.
- Preserve unknown source columns with safe column names during import.
- All divide-by-zero paid metrics return `None` in machine output.
- Reports must separate "投放效率" from "内容/商品因果影响".
- Sync bundled skill assets after source changes.

---

## File Structure

- Modify `references/data_contract.md`: document `ad_performance_daily`.
- Modify `references/metric_definitions.md`: add paid traffic metric formulas.
- Modify `references/task_menu.md`: add task menu rows.
- Modify `xhs_ceramics_analytics/importing/mapping.py`: add table signature and aliases.
- Modify `xhs_ceramics_analytics/db/marts.py`: add `create_ad_metrics_view`.
- Modify `xhs_ceramics_analytics/db/build.py`: refresh `ad_metrics` and include `ad_performance_daily` in controlled tables through `TABLE_SIGNATURES`.
- Create `xhs_ceramics_analytics/analysis/ad_quality.py`: paid export readiness analysis.
- Create `xhs_ceramics_analytics/analysis/paid_traffic.py`: paid efficiency and budget-action analysis.
- Modify `xhs_ceramics_analytics/analysis/registry.py`: register the two task IDs.
- Modify `xhs_ceramics_analytics/reporting/html.py`: add field and value labels, paid group placement.
- Modify `xhs_ceramics_analytics/reporting/markdown.py` only if paid outputs need clearer fallback wording; otherwise leave it alone.
- Create `task_templates/ad_data_quality_check.md`.
- Create `task_templates/paid_traffic_efficiency.md`.
- Create fixtures in `tests/fixtures/ads_campaign.csv`, `tests/fixtures/ads_creative.csv`, and `tests/fixtures/ads_weak.csv`.
- Modify tests in `tests/test_mapping.py`, `tests/test_duckdb_build.py`, `tests/test_analysis_tasks.py`, `tests/test_report_rendering.py`, and `tests/test_metrics_evidence.py`.
- Run `scripts/sync-runtime` so matching files under `skills/data-analyze-for-zcl/assets/xhs-ca/` stay in sync.

---

### Task 1: Import Contract And Mapping

**Files:**
- Modify: `references/data_contract.md`
- Modify: `references/metric_definitions.md`
- Modify: `references/task_menu.md`
- Modify: `xhs_ceramics_analytics/importing/mapping.py`
- Test: `tests/test_mapping.py`

**Interfaces:**
- Produces: `TABLE_SIGNATURES["ad_performance_daily"]`
- Produces: `FIELD_ALIASES["ad_performance_daily"]`
- Later tasks consume normalized columns: `date`, `platform_source`, `spend`, `impressions`, `clicks`, `gmv_optional`, `roas_optional`, `campaign_name_optional`, `creative_name_optional`, `note_id_optional`, `sku_id_optional`.

- [ ] **Step 1: Write failing mapping tests**

Add these tests to `tests/test_mapping.py`:

```python
def test_guess_table_type_detects_paid_traffic_export(tmp_path):
    profile = FileProfile(
        path=tmp_path / "ads.csv",
        table_name="ads",
        columns=["投放日期", "计划名称", "消耗", "曝光量", "点击量", "成交金额"],
        row_count=1,
        sample_rows=[],
    )

    assert guess_table_type(profile) == "ad_performance_daily"


def test_guess_field_mapping_maps_paid_traffic_headers(tmp_path):
    profile = FileProfile(
        path=tmp_path / "ads.csv",
        table_name="ads",
        columns=[
            "投放日期",
            "投放平台",
            "计划名称",
            "创意名称",
            "笔记ID",
            "SKU ID",
            "消耗",
            "曝光量",
            "点击量",
            "成交金额",
            "广告投产比",
        ],
        row_count=1,
        sample_rows=[],
    )

    mapping = guess_field_mapping(profile, "ad_performance_daily")

    assert mapping["date"] == "投放日期"
    assert mapping["platform_source"] == "投放平台"
    assert mapping["campaign_name_optional"] == "计划名称"
    assert mapping["creative_name_optional"] == "创意名称"
    assert mapping["note_id_optional"] == "笔记ID"
    assert mapping["sku_id_optional"] == "SKU ID"
    assert mapping["spend"] == "消耗"
    assert mapping["impressions"] == "曝光量"
    assert mapping["clicks"] == "点击量"
    assert mapping["gmv_optional"] == "成交金额"
    assert mapping["roas_optional"] == "广告投产比"
```

- [ ] **Step 2: Run mapping tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_mapping.py::test_guess_table_type_detects_paid_traffic_export tests/test_mapping.py::test_guess_field_mapping_maps_paid_traffic_headers -q
```

Expected: both tests fail because `ad_performance_daily` is not in `TABLE_SIGNATURES`.

- [ ] **Step 3: Add mapping support**

In `xhs_ceramics_analytics/importing/mapping.py`, extend `TABLE_SIGNATURES`:

```python
    "ad_performance_daily": {
        "date",
        "spend",
        "impressions",
        "clicks",
        "campaign_name_optional",
    },
```

Then extend `FIELD_ALIASES`:

```python
    "ad_performance_daily": {
        "date": {"日期", "时间", "投放日期", "数据日期"},
        "platform_source": {"平台", "来源", "投放平台"},
        "campaign_id_optional": {"计划ID", "计划id", "推广计划ID"},
        "campaign_name_optional": {"计划名称", "推广计划", "投放计划"},
        "unit_id_optional": {"单元ID", "广告单元ID"},
        "unit_name_optional": {"单元名称", "广告单元"},
        "creative_id_optional": {"创意ID", "素材ID"},
        "creative_name_optional": {"创意名称", "素材名称", "笔记标题"},
        "note_id_optional": {"笔记ID", "笔记id"},
        "note_url_optional": {"笔记链接", "推广链接", "落地页链接"},
        "product_id_optional": {"商品ID", "商品id"},
        "sku_id_optional": {"SKU ID", "sku_id", "规格ID"},
        "spend": {"消耗", "花费", "广告消耗", "投放消耗"},
        "impressions": {"曝光", "展现", "展现量", "曝光量"},
        "clicks": {"点击", "点击量"},
        "ctr": {"点击率", "CTR"},
        "cpc": {"平均点击成本", "CPC"},
        "cpm": {"千次曝光成本", "CPM"},
        "conversions_optional": {"转化数", "成交人数", "转化人数"},
        "orders_optional": {"成交订单数", "订单数", "支付订单数"},
        "gmv_optional": {"成交金额", "GMV", "支付金额"},
        "roi_optional": {"ROI", "投产比"},
        "roas_optional": {"ROAS", "广告投产比"},
    },
```

- [ ] **Step 4: Update references**

Append this section to `references/data_contract.md` after `calendar_events`:

```markdown
### `ad_performance_daily`

One row per paid traffic performance record at the most detailed export grain available.

- `date`
- `platform_source`
- `spend`

Recommended:

- `impressions`
- `clicks`
- `ctr`
- `cpc`
- `cpm`
- `conversions_optional`
- `orders_optional`
- `gmv_optional`
- `roi_optional`
- `roas_optional`

Optional identifiers:

- `campaign_id_optional`
- `campaign_name_optional`
- `unit_id_optional`
- `unit_name_optional`
- `creative_id_optional`
- `creative_name_optional`
- `note_id_optional`
- `note_url_optional`
- `product_id_optional`
- `sku_id_optional`

Paid exports may be campaign-level, unit-level, creative-level, note-level, product-level, or SKU-level. The analysis must not force note or SKU attribution when those identifiers are missing.
```

Append this section to `references/metric_definitions.md` after core sales metrics:

```markdown
Core paid traffic metrics:

- `spend`
- `impressions`
- `clicks`
- `ctr_calc = clicks / impressions`
- `cpc_calc = spend / clicks`
- `cpm_calc = spend / impressions * 1000`
- `cvr_calc = conversions_optional / clicks`
- `cost_per_order_calc = spend / orders_optional`
- `roas_calc = gmv_optional / spend`
```

Append rows to `references/task_menu.md`:

```markdown
| 看投放数据能不能分析 | `ad_data_quality_check` | `ad_performance_daily` | `notes`, `skus`, `products`, `daily_sku_sales` | 字段可用性、粒度、关联覆盖、补数建议 |
| 看投放消耗和投产效率 | `paid_traffic_efficiency` | `ad_performance_daily` | `notes`, `skus`, `products`, `daily_sku_sales`, `note_sku_links` | 投放消耗、点击效率、投产、预算动作建议 |
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_mapping.py::test_guess_table_type_detects_paid_traffic_export tests/test_mapping.py::test_guess_field_mapping_maps_paid_traffic_headers -q
```

Expected: pass.

Commit:

```bash
git add references/data_contract.md references/metric_definitions.md references/task_menu.md xhs_ceramics_analytics/importing/mapping.py tests/test_mapping.py
git commit -m "feat: recognize paid traffic exports"
```

---

### Task 2: Build Paid Metrics Mart

**Files:**
- Create: `tests/fixtures/ads_campaign.csv`
- Create: `tests/fixtures/ads_creative.csv`
- Create: `tests/fixtures/ads_weak.csv`
- Modify: `xhs_ceramics_analytics/db/marts.py`
- Modify: `xhs_ceramics_analytics/db/build.py`
- Test: `tests/test_duckdb_build.py`

**Interfaces:**
- Consumes: `ad_performance_daily` DuckDB table.
- Produces: `create_ad_metrics_view(con) -> None`.
- Produces: `ad_metrics` view with calculated fields `ctr_calc`, `cpc_calc`, `cpm_calc`, `cvr_calc`, `cost_per_order_calc`, and `roas_calc`.

- [ ] **Step 1: Add fixtures**

Create `tests/fixtures/ads_campaign.csv`:

```csv
投放日期,投放平台,计划名称,消耗,曝光量,点击量,成交订单数,成交金额,广告投产比,额外字段
2026-06-01,聚光,青釉杯投放,120,6000,180,6,720,6.0,keep-me
2026-06-02,聚光,青釉杯投放,80,4000,80,2,160,2.0,keep-me-too
```

Create `tests/fixtures/ads_creative.csv`:

```csv
投放日期,投放平台,计划名称,创意名称,笔记ID,SKU ID,消耗,曝光量,点击量,成交金额
2026-06-01,薯条,杯子笔记加热,青釉杯场景,n1,s1,30,1500,90,180
2026-06-02,薯条,杯子笔记加热,白瓷盘场景,n2,s2,40,1000,20,0
```

Create `tests/fixtures/ads_weak.csv`:

```csv
投放日期,计划名称,消耗,曝光量
2026-06-01,弱数据计划,50,5000
```

- [ ] **Step 2: Write failing build tests**

Add to `tests/test_duckdb_build.py`:

```python
def test_build_database_imports_paid_traffic_export(tmp_path: Path, fixture_dir: Path):
    db_path = tmp_path / "analytics.duckdb"

    build_database(db_path=db_path, files=[fixture_dir / "ads_campaign.csv"])

    con = duckdb.connect(str(db_path))
    try:
        tables = {row[0] for row in con.sql("SHOW TABLES").fetchall()}
        assert "ad_performance_daily" in tables
        assert "ad_metrics" in tables
        row = con.sql(
            """
            SELECT
              SUM(spend),
              SUM(impressions),
              SUM(clicks),
              SUM(gmv_optional),
              MAX(extra_field)
            FROM ad_performance_daily
            """
        ).fetchone()
        assert row == (200, 10000, 260, 880, "keep-me-too")
    finally:
        con.close()


def test_ad_metrics_calculates_null_safe_paid_rates(tmp_path: Path, fixture_dir: Path):
    db_path = tmp_path / "analytics.duckdb"

    build_database(db_path=db_path, files=[fixture_dir / "ads_campaign.csv"])

    con = duckdb.connect(str(db_path))
    try:
        row = con.sql(
            """
            SELECT ctr_calc, cpc_calc, cpm_calc, cost_per_order_calc, roas_calc
            FROM ad_metrics
            WHERE campaign_name_optional = '青釉杯投放'
              AND date = '2026-06-01'
            """
        ).fetchone()
        assert row[0] == pytest.approx(0.03)
        assert row[1] == pytest.approx(120 / 180)
        assert row[2] == pytest.approx(20)
        assert row[3] == pytest.approx(20)
        assert row[4] == pytest.approx(6)
    finally:
        con.close()
```

- [ ] **Step 3: Run build tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_duckdb_build.py::test_build_database_imports_paid_traffic_export tests/test_duckdb_build.py::test_ad_metrics_calculates_null_safe_paid_rates -q
```

Expected: fail because `ad_metrics` does not exist and paid exports are not yet included in marts.

- [ ] **Step 4: Implement `create_ad_metrics_view`**

Add this helper to `xhs_ceramics_analytics/db/marts.py`:

```python
def create_ad_metrics_view(con) -> None:
    columns = {row[1] for row in con.sql("PRAGMA table_info('ad_performance_daily')").fetchall()}

    spend = _numeric_expr(columns, "spend")
    impressions = _numeric_expr(columns, "impressions")
    clicks = _numeric_expr(columns, "clicks")
    conversions = _numeric_expr(columns, "conversions_optional")
    orders = _numeric_expr(columns, "orders_optional")
    gmv = _numeric_expr(columns, "gmv_optional")

    con.execute(
        f"""
        CREATE OR REPLACE VIEW ad_metrics AS
        SELECT
          *,
          CASE WHEN {impressions} > 0 THEN {clicks} * 1.0 / {impressions} END AS ctr_calc,
          CASE WHEN {clicks} > 0 THEN {spend} * 1.0 / {clicks} END AS cpc_calc,
          CASE WHEN {impressions} > 0 THEN {spend} * 1000.0 / {impressions} END AS cpm_calc,
          CASE WHEN {clicks} > 0 THEN {conversions} * 1.0 / {clicks} END AS cvr_calc,
          CASE WHEN {orders} > 0 THEN {spend} * 1.0 / {orders} END AS cost_per_order_calc,
          CASE WHEN {spend} > 0 THEN {gmv} * 1.0 / {spend} END AS roas_calc
        FROM ad_performance_daily
        """
    )


def _numeric_expr(columns: set[str], column: str) -> str:
    if column not in columns:
        return "NULL"
    return f"CAST({column} AS DOUBLE)"
```

- [ ] **Step 5: Wire mart creation into build**

In `xhs_ceramics_analytics/db/build.py`, import the new helper:

```python
from xhs_ceramics_analytics.db.marts import create_ad_metrics_view, create_note_metrics_view
```

Update `_DERIVED_VIEWS`:

```python
_DERIVED_VIEWS = ("note_metrics", "ad_metrics")
```

After `create_note_metrics_view` call in `build_database`, add:

```python
        if "ad_performance_daily" in _existing_tables(con):
            create_ad_metrics_view(con)
```

- [ ] **Step 6: Run tests and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_duckdb_build.py::test_build_database_imports_paid_traffic_export tests/test_duckdb_build.py::test_ad_metrics_calculates_null_safe_paid_rates -q
```

Expected: pass.

Commit:

```bash
git add tests/fixtures/ads_campaign.csv tests/fixtures/ads_creative.csv tests/fixtures/ads_weak.csv xhs_ceramics_analytics/db/marts.py xhs_ceramics_analytics/db/build.py tests/test_duckdb_build.py
git commit -m "feat: build paid traffic metrics mart"
```

---

### Task 3: Paid Traffic Data Quality Task

**Files:**
- Create: `xhs_ceramics_analytics/analysis/ad_quality.py`
- Modify: `xhs_ceramics_analytics/analysis/registry.py`
- Test: `tests/test_analysis_tasks.py`

**Interfaces:**
- Consumes: `ad_performance_daily` and optional existing tables.
- Produces: task ID `ad_data_quality_check`.
- Produces: result table `ad_data_quality`.
- Produces helper functions `_detect_grain(columns: set[str]) -> str` and `_link_coverage(rows: list[dict[str, object]]) -> dict[str, object]`.

- [ ] **Step 1: Write failing task tests**

Add to `tests/test_analysis_tasks.py`:

```python
def test_ad_data_quality_check_reports_paid_export_readiness(tmp_path, fixture_dir):
    db_path = tmp_path / "analytics.duckdb"
    build_database(db_path, [fixture_dir / "ads_campaign.csv"])

    result = run_task("ad_data_quality_check", db_path)

    assert result.task_id == "ad_data_quality_check"
    assert result.title == "投放数据可用性检查"
    assert result.findings[0].evidence_reason
    row = result.tables["ad_data_quality"][0]
    assert row["rows"] == 2
    assert row["detected_grain"] == "campaign"
    assert row["total_spend"] == 200
    assert row["has_click_metrics"] is True
    assert row["has_gmv_metrics"] is True


def test_ad_data_quality_check_degrades_when_ad_table_missing(tmp_path):
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    con.close()

    result = run_task("ad_data_quality_check", db_path)

    assert result.findings[0].evidence_strength.value == "not_judgable"
    assert result.tables["ad_data_quality"] == []
    assert "ad_performance_daily" in result.limitations[0]
```

- [ ] **Step 2: Run task tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_analysis_tasks.py::test_ad_data_quality_check_reports_paid_export_readiness tests/test_analysis_tasks.py::test_ad_data_quality_check_degrades_when_ad_table_missing -q
```

Expected: fail with unknown task or missing module.

- [ ] **Step 3: Implement `ad_quality.py`**

Create `xhs_ceramics_analytics/analysis/ad_quality.py`:

```python
from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength, score_evidence


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        if not _table_exists(con, "ad_performance_daily"):
            return _missing_result("缺少 ad_performance_daily 表。")
        rows = _quality_rows(con)
    finally:
        con.close()

    row = rows[0] if rows else {}
    sample_size = int(row.get("rows") or 0)
    has_gmv = bool(row.get("has_gmv_metrics"))
    evidence_strength = score_evidence(
        sample_size=sample_size,
        has_controls=has_gmv,
        confounder_count=1 if has_gmv else 2,
    )

    return AnalysisResult(
        task_id="ad_data_quality_check",
        title="投放数据可用性检查",
        findings=[
            Finding(
                title="投放导出已完成结构检查",
                conclusion=(
                    f"当前投放表有 {sample_size} 行，识别为 {row.get('detected_grain', 'unknown')} 粒度。"
                ),
                evidence_strength=evidence_strength,
                evidence_reason=(
                    "该检查只判断字段和粒度可用性，不判断投放效果好坏。"
                ),
                key_numbers={
                    "rows": sample_size,
                    "total_spend": row.get("total_spend"),
                    "detected_grain": row.get("detected_grain"),
                },
                caveats=_quality_caveats(row),
                recommended_action=_recommended_next_import(row),
            )
        ],
        tables={"ad_data_quality": rows},
        limitations=[],
    )


def _quality_rows(con) -> list[dict[str, object]]:
    columns = _table_columns(con, "ad_performance_daily")
    spend_expr = _sum_expr(columns, "spend")
    result = con.sql(
        f"""
        SELECT
          COUNT(*) AS rows,
          MIN(CAST(date AS DATE)) AS first_date,
          MAX(CAST(date AS DATE)) AS last_date,
          {spend_expr} AS total_spend
        FROM ad_performance_daily
        """
    )
    rows, first_date, last_date, total_spend = result.fetchone()
    quality = {
        "rows": int(rows),
        "first_date": str(first_date) if first_date is not None else None,
        "last_date": str(last_date) if last_date is not None else None,
        "total_spend": round(float(total_spend), 4) if total_spend is not None else None,
        "detected_grain": _detect_grain(columns),
        "has_exposure_metrics": "impressions" in columns,
        "has_click_metrics": {"impressions", "clicks"}.issubset(columns),
        "has_conversion_metrics": bool({"conversions_optional", "orders_optional"} & columns),
        "has_gmv_metrics": bool({"gmv_optional", "roi_optional", "roas_optional"} & columns),
        "note_link_rows": _non_null_count(con, "note_id_optional", columns),
        "sku_link_rows": _non_null_count(con, "sku_id_optional", columns),
        "campaign_link_rows": _non_null_count(con, "campaign_name_optional", columns),
        "creative_link_rows": _non_null_count(con, "creative_name_optional", columns),
    }
    return [quality]


def _detect_grain(columns: set[str]) -> str:
    if "sku_id_optional" in columns:
        return "sku"
    if "product_id_optional" in columns:
        return "product"
    if "note_id_optional" in columns or "note_url_optional" in columns:
        return "note"
    if "creative_id_optional" in columns or "creative_name_optional" in columns:
        return "creative"
    if "unit_id_optional" in columns or "unit_name_optional" in columns:
        return "unit"
    if "campaign_id_optional" in columns or "campaign_name_optional" in columns:
        return "campaign"
    return "unknown"


def _recommended_next_import(row: dict[str, object]) -> str:
    if not row.get("has_click_metrics"):
        return "下一次导出请勾选曝光量和点击量，先补齐基础点击效率。"
    if not row.get("has_gmv_metrics"):
        return "下一次导出请勾选成交金额、成交订单数或 ROI 字段，才能判断投产。"
    if not row.get("note_link_rows") and not row.get("sku_link_rows"):
        return "如果后台支持，请补充笔记ID、笔记链接、商品ID 或 SKU ID，提升关联分析可信度。"
    return "当前投放导出可用于投放效率分析；后续可继续补充更细的创意或 SKU 维度。"


def _quality_caveats(row: dict[str, object]) -> list[str]:
    caveats = []
    if not row.get("has_gmv_metrics"):
        caveats.append("缺少 GMV/ROI/ROAS 字段，不能判断投产。")
    if not row.get("note_link_rows") and not row.get("sku_link_rows"):
        caveats.append("缺少笔记或 SKU 关联，只能做投放平台侧效率分析。")
    return caveats


def _sum_expr(columns: set[str], column: str) -> str:
    if column not in columns:
        return "NULL"
    return f"SUM(CAST({column} AS DOUBLE))"


def _non_null_count(con, column: str, columns: set[str]) -> int:
    if column not in columns:
        return 0
    return int(
        con.sql(
            f"SELECT COUNT(*) FROM ad_performance_daily WHERE {column} IS NOT NULL"
        ).fetchone()[0]
    )


def _missing_result(reason: str) -> AnalysisResult:
    return AnalysisResult(
        task_id="ad_data_quality_check",
        title="投放数据可用性检查",
        findings=[
            Finding(
                title="投放数据不可判断",
                conclusion="当前没有可识别的投放效果导出表。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                evidence_reason="缺少投放事实表，当前结果只适合指导补数。",
                key_numbers={"rows": 0},
                caveats=[reason],
                recommended_action="先导入包含日期、消耗、曝光或点击字段的投放导出。",
            )
        ],
        tables={"ad_data_quality": []},
        limitations=[reason],
    )


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
```

- [ ] **Step 4: Register task**

Modify imports in `xhs_ceramics_analytics/analysis/registry.py`:

```python
    ad_quality,
```

Add to `TASKS` after `data_quality_check`:

```python
    "ad_data_quality_check": ad_quality.run,
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_analysis_tasks.py::test_ad_data_quality_check_reports_paid_export_readiness tests/test_analysis_tasks.py::test_ad_data_quality_check_degrades_when_ad_table_missing -q
```

Expected: pass.

Commit:

```bash
git add xhs_ceramics_analytics/analysis/ad_quality.py xhs_ceramics_analytics/analysis/registry.py tests/test_analysis_tasks.py
git commit -m "feat: add paid traffic data quality task"
```

---

### Task 4: Paid Traffic Efficiency Task

**Files:**
- Create: `xhs_ceramics_analytics/analysis/paid_traffic.py`
- Modify: `xhs_ceramics_analytics/analysis/registry.py`
- Test: `tests/test_analysis_tasks.py`
- Test: `tests/test_metrics_evidence.py`

**Interfaces:**
- Consumes: `ad_metrics` if present, otherwise `ad_performance_daily`.
- Produces: task ID `paid_traffic_efficiency`.
- Produces: result table `paid_traffic_efficiency`.
- Produces function `classify_budget_action(spend: float | None, clicks: float | None, gmv: float | None, roas: float | None, active_days: int) -> str`.

- [ ] **Step 1: Write failing helper tests**

Add to `tests/test_metrics_evidence.py`:

```python
from xhs_ceramics_analytics.analysis.paid_traffic import classify_budget_action


def test_classify_budget_action_increase():
    assert classify_budget_action(200, 120, 1000, 5.0, 2) == "increase"


def test_classify_budget_action_reduce_for_spend_without_return():
    assert classify_budget_action(200, 10, 0, 0.0, 2) == "reduce"


def test_classify_budget_action_needs_data_without_clicks():
    assert classify_budget_action(200, None, None, None, 2) == "needs_data"


def test_classify_budget_action_hold_for_one_day_signal():
    assert classify_budget_action(200, 120, 1000, 5.0, 1) == "hold"
```

- [ ] **Step 2: Write failing task tests**

Add to `tests/test_analysis_tasks.py`:

```python
def test_paid_traffic_efficiency_ranks_campaigns_and_budget_actions(tmp_path, fixture_dir):
    db_path = tmp_path / "analytics.duckdb"
    build_database(db_path, [fixture_dir / "ads_campaign.csv"])

    result = run_task("paid_traffic_efficiency", db_path)

    assert result.task_id == "paid_traffic_efficiency"
    assert result.title == "投放效率分析"
    rows = result.tables["paid_traffic_efficiency"]
    assert rows[0]["campaign_name_optional"] == "青釉杯投放"
    assert rows[0]["spend"] == 200
    assert rows[0]["gmv_optional"] == 880
    assert rows[0]["roas_calc"] == pytest.approx(4.4)
    assert rows[0]["budget_action"] == "increase"
    assert result.findings[0].recommended_action


def test_paid_traffic_efficiency_handles_weak_export(tmp_path, fixture_dir):
    db_path = tmp_path / "analytics.duckdb"
    build_database(db_path, [fixture_dir / "ads_weak.csv"])

    result = run_task("paid_traffic_efficiency", db_path)

    assert result.findings[0].evidence_strength.value in {"weak", "not_judgable"}
    assert result.tables["paid_traffic_efficiency"][0]["budget_action"] == "needs_data"
    assert "成交金额" in result.findings[0].recommended_action
```

Add `import pytest` at the top of `tests/test_analysis_tasks.py` if it is not already present.

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_metrics_evidence.py::test_classify_budget_action_increase tests/test_metrics_evidence.py::test_classify_budget_action_reduce_for_spend_without_return tests/test_metrics_evidence.py::test_classify_budget_action_needs_data_without_clicks tests/test_metrics_evidence.py::test_classify_budget_action_hold_for_one_day_signal tests/test_analysis_tasks.py::test_paid_traffic_efficiency_ranks_campaigns_and_budget_actions tests/test_analysis_tasks.py::test_paid_traffic_efficiency_handles_weak_export -q
```

Expected: fail because `paid_traffic.py` and registry entries do not exist.

- [ ] **Step 4: Implement `paid_traffic.py`**

Create `xhs_ceramics_analytics/analysis/paid_traffic.py`:

```python
from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength, score_evidence


def classify_budget_action(
    spend: float | None,
    clicks: float | None,
    gmv: float | None,
    roas: float | None,
    active_days: int,
) -> str:
    if spend is None or spend <= 0 or clicks is None:
        return "needs_data"
    if gmv is None or roas is None:
        return "needs_data"
    if active_days < 2 and roas >= 3:
        return "hold"
    if spend >= 100 and roas >= 3 and gmv > 0:
        return "increase"
    if spend >= 100 and (clicks < 20 or gmv <= 0 or roas < 1):
        return "reduce"
    return "hold"


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        if not _table_exists(con, "ad_performance_daily"):
            return _missing_result("缺少 ad_performance_daily 表。")
        source = "ad_metrics" if _table_exists(con, "ad_metrics") else "ad_performance_daily"
        rows = _efficiency_rows(con, source)
    finally:
        con.close()

    for row in rows:
        row["budget_action"] = classify_budget_action(
            _float_or_none(row.get("spend")),
            _float_or_none(row.get("clicks")),
            _float_or_none(row.get("gmv_optional")),
            _float_or_none(row.get("roas_calc")),
            int(row.get("active_days") or 0),
        )

    total_spend = sum(float(row.get("spend") or 0) for row in rows)
    total_gmv = sum(float(row.get("gmv_optional") or 0) for row in rows)
    has_return = any(row.get("gmv_optional") is not None for row in rows)
    evidence_strength = score_evidence(
        sample_size=sum(int(row.get("active_days") or 0) for row in rows),
        has_controls=has_return,
        confounder_count=1 if has_return else 3,
    )

    return AnalysisResult(
        task_id="paid_traffic_efficiency",
        title="投放效率分析",
        findings=[
            Finding(
                title="投放消耗和投产效率已汇总",
                conclusion=(
                    f"已汇总 {len(rows)} 个投放对象，总消耗 {round(total_spend, 2)}，"
                    f"可见成交金额 {round(total_gmv, 2)}。"
                ),
                evidence_strength=evidence_strength,
                evidence_reason=_evidence_reason(has_return),
                key_numbers={
                    "rows": len(rows),
                    "spend": round(total_spend, 2),
                    "gmv_optional": round(total_gmv, 2) if has_return else None,
                },
                caveats=_caveats(rows, has_return),
                recommended_action=_recommended_action(rows, has_return),
            )
        ],
        tables={"paid_traffic_efficiency": rows},
        limitations=[],
    )


def _efficiency_rows(con, source: str) -> list[dict[str, object]]:
    columns = _table_columns(con, source)
    dimensions = [
        column
        for column in (
            "campaign_name_optional",
            "creative_name_optional",
            "note_id_optional",
            "sku_id_optional",
        )
        if column in columns
    ]
    if not dimensions:
        dimensions = ["platform_source"] if "platform_source" in columns else []

    select_dimensions = ", ".join(dimensions) + "," if dimensions else ""
    group_dimensions = ", ".join(str(index + 1) for index in range(len(dimensions)))
    group_clause = f"GROUP BY {group_dimensions}" if group_dimensions else ""
    order_expr = "roas_calc DESC NULLS LAST, spend DESC NULLS LAST"

    result = con.sql(
        f"""
        SELECT
          {select_dimensions}
          COUNT(DISTINCT CAST(date AS DATE)) AS active_days,
          SUM(CAST(spend AS DOUBLE)) AS spend,
          SUM(CAST(impressions AS DOUBLE)) AS impressions,
          SUM(CAST(clicks AS DOUBLE)) AS clicks,
          SUM(CAST(gmv_optional AS DOUBLE)) AS gmv_optional,
          CASE WHEN SUM(CAST(spend AS DOUBLE)) > 0
            THEN SUM(CAST(gmv_optional AS DOUBLE)) * 1.0 / SUM(CAST(spend AS DOUBLE))
          END AS roas_calc,
          CASE WHEN SUM(CAST(impressions AS DOUBLE)) > 0
            THEN SUM(CAST(clicks AS DOUBLE)) * 1.0 / SUM(CAST(impressions AS DOUBLE))
          END AS ctr_calc,
          CASE WHEN SUM(CAST(clicks AS DOUBLE)) > 0
            THEN SUM(CAST(spend AS DOUBLE)) * 1.0 / SUM(CAST(clicks AS DOUBLE))
          END AS cpc_calc
        FROM {source}
        {group_clause}
        ORDER BY {order_expr}
        LIMIT 20
        """
    )
    return [_clean_row(dict(zip(result.columns, row, strict=True))) for row in result.fetchall()]


def _clean_row(row: dict[str, object]) -> dict[str, object]:
    cleaned = dict(row)
    for key in ("spend", "impressions", "clicks", "gmv_optional", "roas_calc", "ctr_calc", "cpc_calc"):
        if cleaned.get(key) is not None:
            cleaned[key] = round(float(cleaned[key]), 4)
    if cleaned.get("active_days") is not None:
        cleaned["active_days"] = int(cleaned["active_days"])
    return cleaned


def _recommended_action(rows: list[dict[str, object]], has_return: bool) -> str:
    if not rows:
        return "先导入包含消耗、曝光、点击的投放数据。"
    if not has_return:
        return "当前只能看点击效率；下一次导出请补充成交金额、成交订单数或 ROI 字段。"
    increase = [row for row in rows if row.get("budget_action") == "increase"]
    reduce = [row for row in rows if row.get("budget_action") == "reduce"]
    if increase:
        return "优先小幅增加高投产对象预算，同时保留日级观察，避免只凭单日波动放量。"
    if reduce:
        return "先压低高消耗低回报对象预算，把预算转给有点击和成交信号的对象。"
    return "保持当前预算，继续观察更多天数后再决定放量或缩量。"


def _caveats(rows: list[dict[str, object]], has_return: bool) -> list[str]:
    caveats = ["投放效率来自后台导出，不等同于内容或商品的因果影响。"]
    if not has_return:
        caveats.append("缺少成交金额或投产字段，不能判断 ROAS。")
    if any(int(row.get("active_days") or 0) < 2 for row in rows):
        caveats.append("部分对象只有单日数据，预算动作需要保守执行。")
    return caveats


def _evidence_reason(has_return: bool) -> str:
    if has_return:
        return "投放消耗和成交金额可用，可用于预算效率判断；仍需注意平台归因口径。"
    return "只有投放消耗或点击数据，适合判断流量效率，不能判断投产。"


def _missing_result(reason: str) -> AnalysisResult:
    return AnalysisResult(
        task_id="paid_traffic_efficiency",
        title="投放效率分析",
        findings=[
            Finding(
                title="投放效率不可判断",
                conclusion="当前没有可识别的投放效果导出表。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                evidence_reason="缺少投放事实表，不能计算消耗、点击或投产。",
                key_numbers={"rows": 0},
                caveats=[reason],
                recommended_action="先导入包含日期、消耗、曝光或点击字段的投放导出。",
            )
        ],
        tables={"paid_traffic_efficiency": []},
        limitations=[reason],
    )


def _float_or_none(value: object | None) -> float | None:
    return float(value) if value is not None else None


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
```

- [ ] **Step 5: Register task**

Modify imports in `xhs_ceramics_analytics/analysis/registry.py`:

```python
    paid_traffic,
```

Add to `TASKS` after `ad_data_quality_check`:

```python
    "paid_traffic_efficiency": paid_traffic.run,
```

- [ ] **Step 6: Run tests and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_metrics_evidence.py::test_classify_budget_action_increase tests/test_metrics_evidence.py::test_classify_budget_action_reduce_for_spend_without_return tests/test_metrics_evidence.py::test_classify_budget_action_needs_data_without_clicks tests/test_metrics_evidence.py::test_classify_budget_action_hold_for_one_day_signal tests/test_analysis_tasks.py::test_paid_traffic_efficiency_ranks_campaigns_and_budget_actions tests/test_analysis_tasks.py::test_paid_traffic_efficiency_handles_weak_export -q
```

Expected: pass.

Commit:

```bash
git add xhs_ceramics_analytics/analysis/paid_traffic.py xhs_ceramics_analytics/analysis/registry.py tests/test_analysis_tasks.py tests/test_metrics_evidence.py
git commit -m "feat: analyze paid traffic efficiency"
```

---

### Task 5: Report Labels, Templates, And All-Task Coverage

**Files:**
- Create: `task_templates/ad_data_quality_check.md`
- Create: `task_templates/paid_traffic_efficiency.md`
- Modify: `xhs_ceramics_analytics/reporting/html.py`
- Modify: `tests/test_report_rendering.py`
- Modify: `tests/test_analysis_tasks.py`

**Interfaces:**
- Consumes: registered tasks from earlier tasks.
- Produces: reader-friendly paid traffic labels in HTML report.
- Produces: task templates for skill users.
- Ensures: `xhs-ca run all` includes new tasks through registry order and tolerates missing ad data.

- [ ] **Step 1: Write failing report tests**

Add to `tests/test_report_rendering.py`:

```python
def test_render_html_labels_paid_traffic_fields():
    result = AnalysisResult(
        task_id="paid_traffic_efficiency",
        title="投放效率分析",
        findings=[
            Finding(
                title="投放消耗和投产效率已汇总",
                conclusion="已汇总 1 个投放对象。",
                evidence_strength=EvidenceStrength.MEDIUM,
                key_numbers={"spend": 120, "roas_calc": 6},
                recommended_action="优先小幅增加高投产对象预算。",
            )
        ],
        tables={
            "paid_traffic_efficiency": [
                {
                    "campaign_name_optional": "青釉杯投放",
                    "spend": 120,
                    "impressions": 6000,
                    "clicks": 180,
                    "ctr_calc": 0.03,
                    "cpc_calc": 0.6667,
                    "gmv_optional": 720,
                    "roas_calc": 6,
                    "budget_action": "increase",
                }
            ]
        },
    )

    html = render_html([result])

    assert "投放消耗" in html
    assert "点击率" in html
    assert "投产比" in html
    assert "增加预算" in html
```

Add to `tests/test_analysis_tasks.py`:

```python
def test_all_tasks_include_paid_traffic_tasks_when_ad_data_missing(tmp_path, fixture_dir):
    db_path = _db(tmp_path, fixture_dir)

    for task_id in ["ad_data_quality_check", "paid_traffic_efficiency"]:
        result = run_task(task_id, db_path)
        assert result.task_id == task_id
        assert result.findings
```

- [ ] **Step 2: Run report tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_report_rendering.py::test_render_html_labels_paid_traffic_fields tests/test_analysis_tasks.py::test_all_tasks_include_paid_traffic_tasks_when_ad_data_missing -q
```

Expected: fail until labels and tasks are fully wired.

- [ ] **Step 3: Add labels and value labels**

In `xhs_ceramics_analytics/reporting/html.py`, add to `_FIELD_LABELS`:

```python
    "active_days": ("活跃投放天数", "该投放对象出现数据的天数。"),
    "budget_action": ("预算动作", "系统根据消耗、点击和投产给出的下周预算建议。"),
    "campaign_name_optional": ("投放计划", "后台导出的投放计划名称。"),
    "creative_name_optional": ("创意名称", "后台导出的素材或创意名称。"),
    "ctr_calc": ("点击率", "点击量除以曝光量。"),
    "cpc_calc": ("点击成本", "投放消耗除以点击量。"),
    "cpm_calc": ("千次曝光成本", "每一千次曝光对应的投放消耗。"),
    "cost_per_order_calc": ("单订单成本", "投放消耗除以成交订单数。"),
    "gmv_optional": ("成交金额", "投放后台或订单侧可见的成交金额。"),
    "platform_source": ("投放平台", "聚光、薯条、商家后台或其他来源。"),
    "roas_calc": ("投产比", "成交金额除以投放消耗。"),
    "spend": ("投放消耗", "投放后台记录的广告消耗。"),
    "total_spend": ("总投放消耗", "当前投放表里汇总的广告消耗。"),
    "detected_grain": ("识别粒度", "系统根据字段判断出的导出粒度。"),
```

Add to `_VALUE_LABELS`:

```python
    "ad_data_quality_check": "投放数据可用性检查",
    "ad_performance_daily": "投放效果表",
    "campaign": "计划粒度",
    "creative": "创意粒度",
    "increase": "增加预算",
    "paid_traffic_efficiency": "投放效率分析",
    "product": "商品粒度",
    "reduce": "减少预算",
    "hold": "保持预算",
    "unit": "单元粒度",
```

Add table priorities to `_TABLE_LABELS` and field ordering near existing table order maps:

```python
    "ad_data_quality": "投放数据可用性",
    "paid_traffic_efficiency": "投放效率明细",
```

If `_TABLE_COLUMNS` exists in the current file, add:

```python
    "ad_data_quality": (
        "rows",
        "first_date",
        "last_date",
        "total_spend",
        "detected_grain",
        "has_click_metrics",
        "has_gmv_metrics",
    ),
    "paid_traffic_efficiency": (
        "campaign_name_optional",
        "creative_name_optional",
        "spend",
        "impressions",
        "clicks",
        "ctr_calc",
        "cpc_calc",
        "gmv_optional",
        "roas_calc",
        "budget_action",
    ),
```

- [ ] **Step 4: Add task templates**

Create `task_templates/ad_data_quality_check.md`:

```markdown
# ad_data_quality_check

## User question

看小红书投放导出的数据能不能分析。

## Required data

- `ad_performance_daily`

## Optional data

- `notes`
- `skus`
- `products`
- `daily_sku_sales`

## Output

Returns paid export row count, date range, spend, detected grain, metric availability, link coverage, caveats, and the next import action.
```

Create `task_templates/paid_traffic_efficiency.md`:

```markdown
# paid_traffic_efficiency

## User question

看小红书聚光、薯条或商家后台投放消耗和投产效率，判断下周预算怎么调。

## Required data

- `ad_performance_daily`

## Optional data

- `notes`
- `skus`
- `products`
- `daily_sku_sales`
- `note_sku_links`

## Output

Returns spend, impressions, clicks, click efficiency, GMV/ROAS when available, inefficient spend candidates, high-signal candidates, budget actions, caveats, and next export suggestions.
```

- [ ] **Step 5: Run report and task tests, then commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_report_rendering.py::test_render_html_labels_paid_traffic_fields tests/test_analysis_tasks.py::test_all_tasks_include_paid_traffic_tasks_when_ad_data_missing -q
```

Expected: pass.

Commit:

```bash
git add task_templates/ad_data_quality_check.md task_templates/paid_traffic_efficiency.md xhs_ceramics_analytics/reporting/html.py tests/test_report_rendering.py tests/test_analysis_tasks.py
git commit -m "feat: render paid traffic reports"
```

---

### Task 6: Full Verification And Skill Runtime Sync

**Files:**
- Modify: `skills/data-analyze-for-zcl/assets/xhs-ca/**` through `scripts/sync-runtime`
- Modify: `skills/data-analyze-for-zcl/SKILL.md` only if its task menu or usage instructions mention task IDs explicitly.
- Modify: `skills/data-analyze-for-zcl/evals/evals.json` only if eval prompts enumerate available tasks.

**Interfaces:**
- Consumes all source changes from Tasks 1-5.
- Produces bundled skill assets matching source runtime.

- [ ] **Step 1: Run focused test suite**

Run:

```bash
.venv/bin/python -m pytest tests/test_mapping.py tests/test_duckdb_build.py tests/test_analysis_tasks.py tests/test_metrics_evidence.py tests/test_report_rendering.py -q
```

Expected: pass.

- [ ] **Step 2: Run full test suite**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: pass.

- [ ] **Step 3: Run diff check**

Run:

```bash
git diff --check
```

Expected: no output and exit code 0.

- [ ] **Step 4: Sync bundled skill runtime**

Run:

```bash
scripts/sync-runtime
```

Expected: files under `skills/data-analyze-for-zcl/assets/xhs-ca/` update to match source runtime.

- [ ] **Step 5: Verify bundled runtime still passes focused tests**

Run:

```bash
.venv/bin/python -m pytest skills/data-analyze-for-zcl/assets/xhs-ca/tests/test_mapping.py skills/data-analyze-for-zcl/assets/xhs-ca/tests/test_duckdb_build.py skills/data-analyze-for-zcl/assets/xhs-ca/tests/test_analysis_tasks.py -q
```

Expected: pass.

- [ ] **Step 6: Verify install listing**

Run:

```bash
npx skills add seyseyseyz/data-analyze-for-zcl -l
```

Expected: command lists `data-analyze-for-zcl`.

- [ ] **Step 7: Commit sync and final verification**

Run:

```bash
git status --short
git add skills/data-analyze-for-zcl xhs_ceramics_analytics tests references task_templates
git commit -m "chore: sync paid traffic analytics skill assets"
```

Expected: final commit contains only source, tests, docs, templates, and bundled asset updates related to paid traffic analytics.

---

## Self-Review Checklist

- Spec coverage: Tasks cover data contract, mapping, derived metrics, data quality task, efficiency task, reporting labels, task templates, CLI task registry, tests, and skill asset sync.
- Scope boundary: No 蒲公英达人合作 model, no browser automation, no full multi-touch attribution model.
- Type consistency: `ad_performance_daily`, `ad_metrics`, `ad_data_quality_check`, `paid_traffic_efficiency`, `ctr_calc`, `cpc_calc`, `cpm_calc`, and `roas_calc` names are consistent across tasks.
- Scan result: No red-flag tokens or undefined future function references remain.
