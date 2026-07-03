from xhs_ceramics_analytics.analytics.periods import period_month_expr
from xhs_ceramics_analytics.db.sql_helpers import numeric_expr


def create_ad_metrics_view(con) -> None:
    columns = {row[1] for row in con.sql("PRAGMA table_info('ad_performance_daily')").fetchall()}

    spend = numeric_expr(columns, "spend")
    impressions = numeric_expr(columns, "impressions")
    clicks = numeric_expr(columns, "clicks")
    conversions = numeric_expr(columns, "conversions_optional")
    orders = numeric_expr(columns, "orders_optional")
    gmv = numeric_expr(columns, "gmv_optional")

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
    product_clicks = numeric_expr(note_columns, "product_clicks")
    note_paid_orders = numeric_expr(note_columns, "note_paid_orders")
    note_gmv = numeric_expr(note_columns, "note_gmv")
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
          END AS engagement_rate,
          CASE WHEN {product_clicks} > 0 THEN {note_paid_orders} * 1.0 / {product_clicks} END AS click_to_order,
          CASE WHEN {product_clicks} > 0 THEN {note_gmv} * 1.0 / {product_clicks} END AS gmv_per_click
        FROM notes
        """
    )


def create_business_overview_monthly(con) -> None:
    columns = {
        row[1] for row in con.sql("PRAGMA table_info('business_overview_daily')").fetchall()
    }
    if "date" not in columns:
        return
    period = period_month_expr("date")
    gmv = numeric_expr(columns, "gmv")
    paid_orders = numeric_expr(columns, "paid_orders")
    paid_buyers = numeric_expr(columns, "paid_buyers")
    paid_units = numeric_expr(columns, "paid_units")
    refund_amount_pay = numeric_expr(columns, "refund_amount_pay")
    net_gmv_pay = numeric_expr(columns, "net_gmv_pay")
    con.execute(
        f"""
        CREATE TABLE business_overview_monthly AS
        SELECT
          {period} AS period_month,
          SUM({gmv}) AS gmv,
          SUM({paid_orders}) AS paid_orders,
          SUM({paid_buyers}) AS paid_buyers,
          SUM({paid_units}) AS paid_units,
          SUM({refund_amount_pay}) AS refund_amount_pay,
          SUM({net_gmv_pay}) AS net_gmv_pay,
          SUM({gmv}) / NULLIF(SUM({paid_orders}), 0) AS aov,
          SUM({refund_amount_pay}) / NULLIF(SUM({gmv}), 0) AS refund_rate_pay
        FROM business_overview_daily
        GROUP BY 1
        ORDER BY 1
        """
    )
