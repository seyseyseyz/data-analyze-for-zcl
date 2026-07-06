from pathlib import Path

from xhs_ceramics_analytics.analysis.core_business import _bridge_rows
from xhs_ceramics_analytics.analysis.registry import run_task
from xhs_ceramics_analytics.db.duck import connect


def test_bridge_movement_share_stays_sane_when_delta_near_zero():
    # Large offsetting factors with a tiny net ΔGMV used to make share = contrib/ΔGMV
    # blow up to 608% — meaningless to a merchant. Share is now a fraction of the
    # gross factor movement, so it always reads as a sane 0–100% split.
    bridge = {
        "delta_gmv": 100.0,
        "contrib_traffic": 5000.0,
        "contrib_conversion": -3000.0,
        "contrib_aov": -1900.0,
        "dominant_factor": "traffic",
    }
    rows = _bridge_rows(bridge)
    shares = [row["movement_share"] for row in rows]
    assert all(-1.0 <= s <= 1.0 for s in shares)
    # absolute shares sum to 1 (each factor's slice of total absolute movement)
    assert abs(sum(abs(s) for s in shares) - 1.0) < 1e-9
    # the old exploding key is gone
    assert all("share" not in {k for k in row if k != "movement_share"} for row in rows)


def _con(tmp_path: Path):
    db_path = tmp_path / "core.duckdb"
    return connect(db_path), db_path


def _make_business_full(con, rows):
    con.execute(
        """
        CREATE TABLE business_overview_daily (
          date INTEGER, gmv DOUBLE, paid_orders DOUBLE, paid_buyers DOUBLE, aov DOUBLE,
          note_gmv DOUBLE, card_gmv DOUBLE, note_paid_orders DOUBLE, card_paid_orders DOUBLE,
          product_visitors DOUBLE, paid_units DOUBLE, pay_conversion_uv DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO business_overview_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows
    )


def _make_business_minimal(con, rows):
    con.execute(
        """
        CREATE TABLE business_overview_daily (
          date INTEGER, gmv DOUBLE, paid_orders DOUBLE, paid_buyers DOUBLE, aov DOUBLE
        )
        """
    )
    if rows:
        con.executemany("INSERT INTO business_overview_daily VALUES (?,?,?,?,?)", rows)


def _make_traffic(con, rows):
    con.execute(
        """
        CREATE TABLE traffic_source (
          xhs_id VARCHAR, channel VARCHAR, product_clicks DOUBLE,
          product_click_users DOUBLE, paid_buyers DOUBLE
        )
        """
    )
    con.executemany("INSERT INTO traffic_source VALUES (?,?,?,?,?)", rows)


def _make_funnel(con, rows):
    con.execute(
        """
        CREATE TABLE shop_page_funnel (
          date INTEGER, audience_type VARCHAR, first_purchase_cycle VARCHAR,
          shop_visitors DOUBLE, product_click_users DOUBLE, shop_payers DOUBLE
        )
        """
    )
    con.executemany("INSERT INTO shop_page_funnel VALUES (?,?,?,?,?,?)", rows)


_FULL_ROWS = [
    (20260401, 10000.0, 200.0, 180.0, 55.5, 6000.0, 4000.0, 120.0, 80.0, 2000.0, 220.0, 0.09),
    (20260402, 12000.0, 240.0, 210.0, 57.0, 7000.0, 5000.0, 150.0, 90.0, 2400.0, 260.0, 0.0875),
    (20260403, 15000.0, 300.0, 260.0, 57.6, 9000.0, 6000.0, 180.0, 120.0, 3000.0, 320.0, 0.0867),
]

_TRAFFIC_ROWS = [
    ("acc", "搜索", 1200.0, 900.0, 300.0),
    ("acc", "推荐", 2000.0, 1500.0, 200.0),
    ("acc", "搜索", 400.0, 300.0, 90.0),
]

# visitors 1000, clicks 300 (visit_click .30), payers 60 (click_pay .20, visit_pay .06)
_FUNNEL_ROWS = [
    (20260401, "新客", "首购", 700.0, 210.0, 30.0),
    (20260402, "老客", "复购", 300.0, 90.0, 30.0),
]


def test_missing_business_overview_is_not_judgable(tmp_path):
    con, db_path = _con(tmp_path)
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    assert result.task_id == "core_business_diagnosis"
    assert result.findings[0].evidence_strength.value == "not_judgable"
    assert "business_overview_daily" in result.limitations[0]


def test_snapshot_finding_always_emitted_with_trend(tmp_path):
    con, db_path = _con(tmp_path)
    _make_business_full(con, _FULL_ROWS)
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    assert result.findings, "findings must never be empty"
    snap = result.findings[0]
    kn = snap.key_numbers
    assert kn["total_gmv"] == 37000.0
    assert kn["total_paid_buyers"] == 650.0
    assert kn["trend_direction"] == "上升"
    assert snap.evidence_strength.value == "weak"
    assert len(result.tables["business_trend"]) == 3
    assert len(result.tables["business_snapshot"]) == 1
    assert snap.confounders  # every finding carries confounders


def test_carrier_and_channel_structure_emitted(tmp_path):
    con, db_path = _con(tmp_path)
    _make_business_full(con, _FULL_ROWS)
    _make_traffic(con, _TRAFFIC_ROWS)
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    titles = [f.title for f in result.findings]
    assert any("载体" in t or "渠道" in t for t in titles)
    carrier = result.tables["carrier_structure"]
    assert {r["carrier"] for r in carrier} == {"note", "card"}
    note_row = next(r for r in carrier if r["carrier"] == "note")
    assert note_row["gmv"] == 22000.0
    channel = result.tables["traffic_channel_structure"]
    assert {r["channel"] for r in channel} == {"搜索", "推荐"}
    struct = next(f for f in result.findings if "载体" in f.title or "渠道" in f.title)
    # two_proportion ran on top-2 channels (real counts), reports diff
    assert "channel_diff" in struct.key_numbers


def test_funnel_finding_identifies_weakest_stage_and_audience(tmp_path):
    con, db_path = _con(tmp_path)
    _make_business_full(con, _FULL_ROWS)
    _make_funnel(con, _FUNNEL_ROWS)
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    funnel = next(f for f in result.findings if "漏斗" in f.title)
    assert funnel.key_numbers["weakest_stage"] == "点击→支付"
    assert funnel.recommended_action  # lever text present
    stages = result.tables["shop_funnel_stages"]
    # #15: 漏斗环节列改名为 funnel_stage（与退款环节 stage 解碰撞），值直接为中文，
    # 且不再复用 stage / stage_zh。
    assert "stage" not in stages[0]
    assert "stage_zh" not in stages[0]
    assert {r["funnel_stage"] for r in stages} == {"访问→点击", "点击→支付", "访问→支付"}
    aud = result.tables["audience_conversion"]
    assert {r["audience_type"] for r in aud} == {"新客", "老客"}


def test_optional_tables_missing_degrades_without_raise(tmp_path):
    con, db_path = _con(tmp_path)
    _make_business_minimal(
        con,
        [
            (20260401, 10000.0, 200.0, 180.0, 55.5),
            (20260402, 12000.0, 240.0, 210.0, 57.0),
        ],
    )
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    titles = [f.title for f in result.findings]
    # snapshot still emitted; carrier/channel/funnel skipped with limitations
    assert any("快照" in t or "经营" in t for t in titles)
    assert "carrier_structure" not in result.tables
    assert "shop_funnel_stages" not in result.tables
    assert result.limitations  # degradations logged


def test_single_row_skips_trend_without_raise(tmp_path):
    con, db_path = _con(tmp_path)
    _make_business_minimal(con, [(20260401, 10000.0, 200.0, 180.0, 55.5)])
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    assert result.findings  # never empty
    assert "business_trend" not in result.tables or len(
        result.tables.get("business_trend", [])
    ) <= 1
    assert any("趋势" in lim for lim in result.limitations)


def test_empty_business_overview_does_not_raise(tmp_path):
    con, db_path = _con(tmp_path)
    _make_business_minimal(con, [])
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    # required table exists but empty: still emits Finding 1, no exception
    assert result.findings
    assert result.findings[0].key_numbers.get("total_gmv") in (0.0, None)


def _make_business_dated(con, rows):
    """business_overview_daily with ISO date strings → exercises timeseries decomp."""
    con.execute(
        """
        CREATE TABLE business_overview_daily (
          date VARCHAR, gmv DOUBLE, paid_orders DOUBLE, paid_buyers DOUBLE, aov DOUBLE
        )
        """
    )
    con.executemany("INSERT INTO business_overview_daily VALUES (?,?,?,?,?)", rows)


def test_gmv_trend_decomposition_reports_structure(tmp_path):
    con, db_path = _con(tmp_path)
    # 14 consecutive days: a clear level shift after the first week so the
    # changepoint lands inside the second week (D3 timeseries decomposition).
    rows = []
    for day in range(1, 15):
        gmv = 5000.0 if day <= 7 else 15000.0
        rows.append((f"2026-04-{day:02d}", gmv, gmv / 50, gmv / 55, 55.0))
    _make_business_dated(con, rows)
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    snap = result.findings[0]
    kn = snap.key_numbers
    # changepoint sits at the start of the high week (2026-04-08)
    assert kn["changepoint_date"] == "2026-04-08"
    assert kn["peak_dow"] is not None  # a weekday label parsed from real dates
    assert kn["wow_last_pct"] is not None  # week-over-week bucket produced a delta
    # trend table flags exactly the changepoint row
    flagged = [r for r in result.tables["business_trend"] if r.get("is_changepoint")]
    assert len(flagged) == 1 and flagged[0]["date"] == "2026-04-08"
    assert "结构性变化" in snap.conclusion


def test_growth_attribution_identifies_traffic_driver(tmp_path):
    con, db_path = _con(tmp_path)
    # 2026-05 (two days) vs 2026-06 (two days): visitors double, conversion & AOV
    # flat → the GMV bridge (B1 LMDI) must attribute ΔGMV to traffic.
    rows = [
        (20260501, 5000.0, 100.0, 100.0, 50.0, 3000.0, 2000.0, 60.0, 40.0, 1000.0, 100.0, 0.1),
        (20260502, 5000.0, 100.0, 100.0, 50.0, 3000.0, 2000.0, 60.0, 40.0, 1000.0, 100.0, 0.1),
        (20260601, 10000.0, 200.0, 200.0, 50.0, 6000.0, 4000.0, 120.0, 80.0, 2000.0, 200.0, 0.1),
        (20260602, 10000.0, 200.0, 200.0, 50.0, 6000.0, 4000.0, 120.0, 80.0, 2000.0, 200.0, 0.1),
    ]
    _make_business_full(con, rows)
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    bridge = next(f for f in result.findings if "增长归因" in f.title)
    kn = bridge.key_numbers
    # 读者面 key_numbers 只暴露中文枚举值，不含英文残留，也不与 _zh 重复。
    assert kn["dominant_factor"] == "流量"
    assert "dominant_factor_zh" not in kn
    assert kn["delta_gmv"] == 10000.0
    # three contributions reconstruct ΔGMV (LMDI is exactly additive)
    total = kn["contrib_traffic"] + kn["contrib_conversion"] + kn["contrib_aov"]
    assert abs(total - kn["delta_gmv"]) < 1e-6
    # gmv_bridge 表格行以中文因子名呈现，不外泄英文枚举（traffic/conversion/aov）。
    bridge_rows = result.tables["gmv_bridge"]
    assert bridge_rows
    factor_values = {str(row.get("factor_zh")) for row in bridge_rows}
    assert factor_values == {"流量", "转化", "客单价"}
    assert all("factor" not in row or row.get("factor") not in {"traffic", "conversion", "aov"}
               for row in bridge_rows)
    assert "流量" in bridge.conclusion


def test_growth_attribution_explains_caliber_and_offset(tmp_path):
    con, db_path = _con(tmp_path)
    # Traffic surges (visitors 4x) but conversion & AOV fall, so net GMV only nudges
    # up (+1000): the dominant factor (traffic) moves the same way as the net change
    # yet far outweighs it — the bridge must (a) spell out the calendar-month caliber
    # and (b) say the traffic gain was offset by the other factors.
    rows = [
        (20260501, 5000.0, 100.0, 100.0, 50.0, 3000.0, 2000.0, 60.0, 40.0, 1000.0, 100.0, 0.1),
        (20260502, 5000.0, 100.0, 100.0, 50.0, 3000.0, 2000.0, 60.0, 40.0, 1000.0, 100.0, 0.1),
        (20260601, 5500.0, 125.0, 125.0, 44.0, 3300.0, 2200.0, 75.0, 50.0, 4000.0, 125.0, 0.03125),
        (20260602, 5500.0, 125.0, 125.0, 44.0, 3300.0, 2200.0, 75.0, 50.0, 4000.0, 125.0, 0.03125),
    ]
    _make_business_full(con, rows)
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    bridge = next(f for f in result.findings if "增长归因" in f.title)
    assert "2026-05" in bridge.conclusion and "2026-06" in bridge.conclusion
    assert "抵消" in bridge.conclusion
    assert bridge.key_numbers["dominant_factor"] == "流量"


def test_growth_attribution_skipped_without_visitors(tmp_path):
    con, db_path = _con(tmp_path)
    _make_business_minimal(
        con,
        [
            (20260401, 10000.0, 200.0, 180.0, 55.5),
            (20260402, 12000.0, 240.0, 210.0, 57.0),
            (20260403, 15000.0, 300.0, 260.0, 57.6),
            (20260404, 16000.0, 320.0, 280.0, 57.1),
        ],
    )
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    # no product_visitors column → bridge finding absent, degrades with limitation
    assert not any("增长归因" in f.title for f in result.findings)
    assert any("增长归因" in lim or "GMV 桥" in lim for lim in result.limitations)


def test_flat_noisy_series_reads_trend_unclear(tmp_path):
    con, db_path = _con(tmp_path)
    # Wobble around 10000 with no real slope: significance gating (A1) must report
    # 趋势不明, not a spurious direction from a near-zero OLS slope.
    rows = [
        ("2026-04-01", 10000.0, 200.0, 180.0, 55.5),
        ("2026-04-02", 9800.0, 196.0, 176.0, 55.5),
        ("2026-04-03", 10200.0, 204.0, 184.0, 55.5),
        ("2026-04-04", 9900.0, 198.0, 178.0, 55.5),
        ("2026-04-05", 10100.0, 202.0, 182.0, 55.5),
        ("2026-04-06", 9950.0, 199.0, 179.0, 55.5),
        ("2026-04-07", 10050.0, 201.0, 181.0, 55.5),
    ]
    _make_business_dated(con, rows)
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    assert result.findings[0].key_numbers["trend_direction"] == "趋势不明"


def _make_calendar_events(con, rows):
    con.execute(
        """
        CREATE TABLE calendar_events (
          date VARCHAR, event_type VARCHAR, event_name VARCHAR, severity VARCHAR
        )
        """
    )
    con.executemany("INSERT INTO calendar_events VALUES (?,?,?,?)", rows)


def test_event_activity_lift_compares_event_vs_baseline(tmp_path):
    con, db_path = _con(tmp_path)
    # 4 baseline days (GMV 5000, conv .05) vs 3 event days (GMV 15000, conv .10).
    # Business dates are INTEGER YYYYMMDD; calendar dates are ISO strings — the
    # shared iso_date key must still align the two calibers.
    base = [
        (d, 5000.0, 50.0, 50.0, 100.0, 3000.0, 2000.0, 30.0, 20.0, 1000.0, 50.0, 0.05)
        for d in (20260401, 20260402, 20260403, 20260404)
    ]
    event = [
        (d, 15000.0, 120.0, 120.0, 125.0, 9000.0, 6000.0, 70.0, 50.0, 1200.0, 120.0, 0.10)
        for d in (20260405, 20260406, 20260407)
    ]
    _make_business_full(con, base + event)
    _make_calendar_events(
        con,
        [
            ("2026-04-05", "大促", "五五购物节", "high"),
            ("2026-04-06", "大促", "五五购物节", "high"),
            ("2026-04-07", "大促", "五五购物节", "high"),
        ],
    )
    con.close()
    result = run_task("core_business_diagnosis", db_path)

    lift = result.tables["event_activity_lift"]
    gmv_row = next(r for r in lift if r["metric"] == "日均 GMV")
    assert gmv_row["event_value"] == 15000.0
    assert gmv_row["baseline_value"] == 5000.0
    assert gmv_row["lift_pct"] == 200.0
    conv_row = next(r for r in lift if r["metric"] == "支付转化率")
    assert conv_row["event_value"] == 0.1
    assert conv_row["baseline_value"] == 0.05
    assert conv_row["significance"] == "显著"

    finding = next(f for f in result.findings if f.title == "活动期抬升对比")
    assert finding.key_numbers["event_days"] == 3
    assert finding.key_numbers["baseline_days"] == 4
    assert finding.key_numbers["gmv_lift_pct"] == 200.0


def test_event_activity_lift_absent_without_calendar(tmp_path):
    con, db_path = _con(tmp_path)
    _make_business_full(con, _FULL_ROWS)
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    assert "event_activity_lift" not in result.tables
    assert not any(f.title == "活动期抬升对比" for f in result.findings)


def test_self_benchmark_places_latest_week_at_top_percentile(tmp_path):
    con, db_path = _con(tmp_path)
    # Five clean ISO weeks (one Monday each) with strictly rising weekly GMV, so the
    # latest week is the strict max of five points → midrank (4 + 0.5)/5 = 0.9 → P90.
    rows = [
        ("2026-04-06", 1000.0, 20.0, 18.0, 55.0),  # ISO week 15
        ("2026-04-13", 2000.0, 40.0, 36.0, 55.0),  # week 16
        ("2026-04-20", 3000.0, 60.0, 54.0, 55.0),  # week 17
        ("2026-04-27", 4000.0, 80.0, 72.0, 55.0),  # week 18
        ("2026-05-04", 5000.0, 100.0, 90.0, 55.0),  # week 19 (latest, strict max)
    ]
    _make_business_dated(con, rows)
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    bench = result.tables["business_self_benchmark"]
    gmv_row = next(r for r in bench if r["metric"] == "周 GMV")
    assert gmv_row["percentile_label"] == "P90"
    assert gmv_row["periods"] == 5
    assert gmv_row["latest_period"] == "2026-W19"
    finding = next(f for f in result.findings if f.title == "自身历史基准分位")
    assert "P90" in finding.conclusion


def test_self_benchmark_skipped_below_four_weeks(tmp_path):
    con, db_path = _con(tmp_path)
    # Only three ISO weeks — a percentile over 2–3 points is noise, so the finding
    # must degrade (no table, no finding) rather than emit a spurious rank.
    rows = [
        ("2026-04-06", 1000.0, 20.0, 18.0, 55.0),
        ("2026-04-13", 2000.0, 40.0, 36.0, 55.0),
        ("2026-04-20", 3000.0, 60.0, 54.0, 55.0),
    ]
    _make_business_dated(con, rows)
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    assert "business_self_benchmark" not in result.tables
    assert not any(f.title == "自身历史基准分位" for f in result.findings)


def test_channel_share_only_without_paid_buyers(tmp_path):
    con, db_path = _con(tmp_path)
    _make_business_full(con, _FULL_ROWS)
    con.execute(
        """
        CREATE TABLE traffic_source (
          xhs_id VARCHAR, channel VARCHAR, product_clicks DOUBLE,
          product_click_users DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO traffic_source VALUES (?,?,?,?)",
        [("acc", "搜索", 1200.0, 900.0), ("acc", "推荐", 2000.0, 1500.0)],
    )
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    channel = result.tables["traffic_channel_structure"]
    assert {r["channel"] for r in channel} == {"搜索", "推荐"}
    struct = next(f for f in result.findings if "载体" in f.title or "渠道" in f.title)
    # no two_proportion without paid_buyers counts
    assert struct.key_numbers.get("channel_diff") is None


def test_snapshot_flags_anomaly_days_and_projects_trend(tmp_path):
    # 14 rising days with one sharp spike on day 8 → significant upward trend +
    # a single >2σ anomaly day; the snapshot must flag the anomaly and project forward.
    con, db_path = _con(tmp_path)
    rows = []
    for i in range(14):
        date = 20260401 + i
        gmv = 1000.0 + 100.0 * i
        if i == 7:
            gmv += 2500.0  # anomalous spike
        rows.append((date, gmv, 20.0 + i, 18.0 + i, 55.0))
    _make_business_minimal(con, rows)
    con.close()

    result = run_task("core_business_diagnosis", db_path)
    snapshot = next(f for f in result.findings if f.title == "整体经营快照与趋势")

    # Anomaly day surfaced in key_numbers and flagged on the trend table.
    assert snapshot.key_numbers.get("anomaly_day_count", 0) >= 1
    trend = result.tables["business_trend"]
    flagged = [r for r in trend if r.get("is_anomaly")]
    assert any(r["date"] == "2026-04-08" for r in flagged)
    # A significant rising trend yields a forward projection (observational hint).
    assert "projected_gmv_next" in snapshot.key_numbers
    # The projection is framed as an observational hint, not a promise.
    assert any("外推" in c or "预测" in c for c in snapshot.caveats)
