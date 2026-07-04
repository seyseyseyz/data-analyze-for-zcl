from pathlib import Path

from xhs_ceramics_analytics.analysis.prose import qty
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.analytics.cadence import posting_windows
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.evidence import score_evidence
from xhs_ceramics_analytics.evidence import score_reliability

# A publish window needs at least this many posts before its mean performance is
# trusted — one lucky viral note must never crown a weekday×时段 combination.
_MIN_POSTS_PER_WINDOW = 3
_WEEKDAY_LABELS = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 7: "周日"}
# Time-of-day slots tuned for a lifestyle/ceramics account's posting rhythm.
_SLOTS = (
    (5, 11, "早间"),
    (11, 14, "午间"),
    (14, 18, "下午"),
    (18, 22, "晚间"),
)
_NIGHT_SLOT = "夜间"  # 22:00–04:59 wraps midnight
# Ranking-metric priority: the most universally present, least age-sensitive signal
# first. Whichever column exists ranks the windows; the rest ride along descriptively.
_METRIC_PRIORITY = (
    ("reads", "阅读量"),
    ("engagement", "互动量"),
    ("note_gmv", "带货 GMV"),
)


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        if not _table_exists(con, "notes"):
            return _missing_result("缺少 notes 表。")
        columns = _table_columns(con, "notes")
        if "publish_time" not in columns:
            return _missing_result("notes 表缺少 publish_time 字段。")
        reads_expr = "AVG(CAST(reads AS DOUBLE))" if "reads" in columns else "NULL"
        # The date/reads CASTs raise on a non-date publish_time or non-numeric
        # reads cell; degrade to an empty baseline (mirrors _fetch_publish_performance)
        # so a dirty export yields a NOT_JUDGABLE finding rather than an exception.
        try:
            result = con.sql(
                f"""
                SELECT
                  CAST(CAST(publish_time AS DATE) AS VARCHAR) AS date,
                  COUNT(*) AS posts,
                  {reads_expr} AS avg_reads
                FROM notes
                WHERE publish_time IS NOT NULL
                GROUP BY 1
                ORDER BY 1
                """
            )
            daily_posts = [
                {"date": date, "posts": posts, "avg_reads": avg_reads}
                for date, posts, avg_reads in result.fetchall()
            ]
        except Exception:
            daily_posts = []
        window_finding, window_rows = _posting_window_finding(con, columns)
    finally:
        con.close()
    sample_size = int(sum(row["posts"] for row in daily_posts))
    findings = [
        Finding(
            title="发布基线",
            conclusion=(
                f"当前数据包含 {qty(sample_size)} 篇笔记，覆盖 "
                f"{qty(len(daily_posts))} 个有发布记录的日期。"
            ),
            evidence_strength=score_evidence(
                sample_size, has_controls=False, confounder_count=1
            ),
            descriptive_reliability=score_reliability(sample_size),
            key_numbers={"posts": sample_size, "active_days": len(daily_posts)},
            caveats=[
                "样本量和对照上下文有限，这个基线只能做描述性判断。"
            ],
        )
    ]
    tables = {"daily_posts": daily_posts}
    if window_finding is not None:
        findings.append(window_finding)
        tables["posting_windows"] = window_rows
    return AnalysisResult(
        task_id="account_baseline",
        title="账号基线",
        findings=findings,
        tables=tables,
    )


def _posting_window_finding(con, columns: set[str]):
    """Best publish window (weekday × 时段) by note performance, net of note age.

    Notes accumulate reads the longer they are live, so a raw window mean confounds
    *when you post* with *how old the post is*; the cadence primitive detrends
    against publish day before ranking, and drops windows with fewer than
    ``_MIN_POSTS_PER_WINDOW`` posts. Degrades to ``(None, [])`` when there is no
    usable performance column or no window clears the sample guard.
    """
    metric = _pick_metric(columns)
    if metric is None:
        return None, []
    metric_key, metric_label = metric

    records = _fetch_publish_performance(con, columns)
    if not records:
        return None, []

    observations = [
        (
            (rec["weekday"], rec["slot"]),
            rec["day_order"],
            rec[metric_key],
        )
        for rec in records
        if rec["weekday"] is not None and rec["slot"] is not None
    ]
    windows = posting_windows(
        observations, min_n=_MIN_POSTS_PER_WINDOW, detrend=True
    )
    if not windows:
        return None, []

    enrich = _window_averages(records)
    rows = []
    for w in windows:
        weekday, slot = w["group"]
        extra = enrich.get(w["group"], {})
        rows.append(
            {
                "publish_window": f"{weekday}·{slot}",
                "posts": w["n"],
                "avg_reads": extra.get("reads"),
                "avg_engagement": extra.get("engagement"),
                "avg_note_gmv": extra.get("note_gmv"),
                "perf_lift": round(w["lift"], 2),
            }
        )

    best = rows[0]
    n_posts = int(sum(r["posts"] for r in rows))
    conclusion = (
        f"以{metric_label}衡量，去除笔记时长累积效应后，"
        f"「{best['publish_window']}」是当前表现最好的发布窗口"
        f"（{qty(best['posts'])} 篇，较窗口均值高 {best['perf_lift']}）。"
    )
    return (
        Finding(
            title="最优发布窗口",
            conclusion=conclusion,
            evidence_strength=score_evidence(
                n_posts, has_controls=False, confounder_count=2
            ),
            descriptive_reliability=score_reliability(n_posts),
            key_numbers={
                "best_window": best["publish_window"],
                "best_window_posts": best["posts"],
                "ranked_windows": len(rows),
                "metric": metric_label,
            },
            caveats=[
                "观察性节律：窗口表现已按发布日去趋势、并对每个窗口设最低 3 篇的样本门槛，"
                "但选题、投放与节假日仍是混淆项，不能读作「换个时间发就会更好」。",
                "缺具体发布小时时，时段维度会退化为按日归入夜间，仅周几维度可靠。",
            ],
            recommended_action=(
                "把选题与投放向高表现窗口集中做一轮对照测试，再据实际抬升决定是否固化排期。"
            ),
            evidence_reason=(
                "用 analytics.cadence.posting_windows 对 (周几,时段) 分组求去趋势后的"
                "平均表现，为观察性相对排序，无随机对照。"
            ),
            confounders=["笔记选题差异", "投放叠加", "节假日与活动", "笔记时长累积"],
        ),
        rows,
    )


def _pick_metric(columns: set[str]) -> tuple[str, str] | None:
    """First available ranking metric by priority (reads → 互动 → 带货)."""
    for key, label in _METRIC_PRIORITY:
        if key == "engagement":
            if columns & {"likes", "collects", "comments"}:
                return key, label
        elif key in columns:
            return key, label
    return None


def _fetch_publish_performance(con, columns: set[str]) -> list[dict]:
    """Per-note (weekday, slot, day_order, reads, engagement, note_gmv). Never raises
    — an unparseable publish_time degrades the whole window finding to empty."""
    reads_expr = "CAST(reads AS DOUBLE)" if "reads" in columns else "NULL"
    engage_parts = [
        f"COALESCE(CAST({col} AS DOUBLE), 0)"
        for col in ("likes", "collects", "comments")
        if col in columns
    ]
    engage_expr = " + ".join(engage_parts) if engage_parts else "NULL"
    gmv_expr = "CAST(note_gmv AS DOUBLE)" if "note_gmv" in columns else "NULL"
    try:
        result = con.sql(
            f"""
            SELECT
              EXTRACT(isodow FROM CAST(publish_time AS TIMESTAMP)) AS iso_dow,
              EXTRACT(hour FROM CAST(publish_time AS TIMESTAMP)) AS hour_of_day,
              EXTRACT(epoch FROM CAST(publish_time AS DATE)) / 86400.0 AS day_order,
              {reads_expr} AS reads,
              {engage_expr} AS engagement,
              {gmv_expr} AS note_gmv
            FROM notes
            WHERE publish_time IS NOT NULL
            """
        )
        raw = result.fetchall()
    except Exception:
        return []

    records = []
    for iso_dow, hour_of_day, day_order, reads, engagement, note_gmv in raw:
        records.append(
            {
                "weekday": _WEEKDAY_LABELS.get(int(iso_dow)) if iso_dow is not None else None,
                "slot": _slot_label(hour_of_day),
                "day_order": float(day_order) if day_order is not None else None,
                "reads": reads,
                "engagement": engagement,
                "note_gmv": note_gmv,
            }
        )
    return records


def _slot_label(hour) -> str | None:
    if hour is None:
        return None
    h = int(hour)
    for start, end, label in _SLOTS:
        if start <= h < end:
            return label
    return _NIGHT_SLOT


def _window_averages(records: list[dict]) -> dict:
    """Descriptive per-window means for reads / engagement / note_gmv (rounded)."""
    buckets: dict = {}
    for rec in records:
        key = (rec["weekday"], rec["slot"])
        if key[0] is None or key[1] is None:
            continue
        buckets.setdefault(key, {"reads": [], "engagement": [], "note_gmv": []})
        for metric in ("reads", "engagement", "note_gmv"):
            value = rec[metric]
            if isinstance(value, (int, float)):
                buckets[key][metric].append(float(value))
    return {
        key: {
            metric: round(sum(vals) / len(vals), 2) if vals else None
            for metric, vals in metrics.items()
        }
        for key, metrics in buckets.items()
    }


def _missing_result(reason: str) -> AnalysisResult:
    return AnalysisResult(
        task_id="account_baseline",
        title="账号基线",
        findings=[
            Finding(
                title="发布基线不可计算",
                conclusion="需要带发布时间的笔记导出数据后，才能计算账号基线。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                key_numbers={"posts": 0, "active_days": 0},
                caveats=["基线数据缺失应视为导入缺口。"],
                recommended_action="导出包含 publish_time 和 reads 的 notes 数据，然后重新构建。"
            )
        ],
        tables={"daily_posts": []},
        limitations=[reason],
    )


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
