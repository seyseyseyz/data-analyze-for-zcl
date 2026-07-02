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


def create_note_metrics_view(con) -> None:
    note_columns = {
        row[1] for row in con.sql("PRAGMA table_info('notes')").fetchall()
    }
    impressions = "CAST(impressions AS DOUBLE)" if "impressions" in note_columns else "NULL"
    reads = "CAST(reads AS DOUBLE)" if "reads" in note_columns else "NULL"
    likes = "COALESCE(CAST(likes AS DOUBLE), 0)" if "likes" in note_columns else "0"
    collects = (
        "COALESCE(CAST(collects AS DOUBLE), 0)" if "collects" in note_columns else "0"
    )
    comments = (
        "COALESCE(CAST(comments AS DOUBLE), 0)" if "comments" in note_columns else "0"
    )
    shares = "COALESCE(CAST(shares AS DOUBLE), 0)" if "shares" in note_columns else "0"
    con.execute(
        f"""
        CREATE OR REPLACE VIEW note_metrics AS
        SELECT
          *,
          CASE WHEN {impressions} > 0 THEN {reads} * 1.0 / {impressions} END AS read_rate,
          CASE WHEN {reads} > 0 THEN {likes} * 1.0 / {reads} END AS like_rate,
          CASE WHEN {reads} > 0 THEN {collects} * 1.0 / {reads} END AS collect_rate,
          CASE WHEN {reads} > 0 THEN {comments} * 1.0 / {reads} END AS comment_rate,
          CASE
            WHEN {reads} > 0 THEN
              ({likes} + {collects} + {comments} + {shares}) * 1.0 / {reads}
          END AS engagement_rate
        FROM notes
        """
    )
