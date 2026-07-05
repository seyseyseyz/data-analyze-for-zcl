"""自身历史基准分位 (C1) 的读者面正确性单测。

回归两个会误导商家的 bug:
1. 结论把「较高水平」写死——最新一周实际处于历史 **低** 分位 (P4) 时,仍宣称
   「处于自身历史较高水平」,方向完全反了。descriptor 必须由真实分位推导。
2. 尾部不完整 ISO 周 (如 2 天的残周) 混入周序列,会把最新周 GMV 求和拉低、
   percentile 判低,并连带污染环比——残周必须从自身基准里剔除。
"""
from xhs_ceramics_analytics.analysis.core_business import (
    _benchmark_conclusion,
    _percentile_phrase,
    _weekly_metric_series,
)


def test_percentile_phrase_tracks_actual_percentile():
    # 低分位绝不能读成「较高」。
    assert "较高" in _percentile_phrase(0.92)
    assert "偏上" in _percentile_phrase(0.6)
    assert "偏下" in _percentile_phrase(0.3)
    assert "较低" in _percentile_phrase(0.04)
    assert "较高" not in _percentile_phrase(0.04)


def test_benchmark_conclusion_low_percentile_reads_low():
    # headline 是最强指标,但它本身就处于历史低位 (P4) → 结论必须说「较低」。
    headline = {"metric": "周 GMV", "self_percentile": 0.04, "percentile_label": "P4"}
    text = _benchmark_conclusion(headline, headline, n_weeks=14)
    assert "较低" in text
    assert "较高" not in text
    # 只有一个指标时,不拼出自相矛盾的「而…」对比子句。
    assert "而" not in text


def test_benchmark_conclusion_contrasts_two_distinct_metrics():
    headline = {"metric": "周 GMV", "self_percentile": 0.62, "percentile_label": "P62"}
    worst = {"metric": "周支付转化率", "self_percentile": 0.08, "percentile_label": "P8"}
    text = _benchmark_conclusion(headline, worst, n_weeks=14)
    assert "周 GMV" in text and "周支付转化率" in text
    assert "P62" in text and "P8" in text


def test_weekly_series_drops_partial_trailing_week():
    # 5 个满 7 天周 + 尾部 2 天残周;残周必须被剔除,不进自身基准。
    import datetime

    cols = ["date", "gmv", "pay_conversion_uv"]
    rows = []
    start = datetime.date(2026, 6, 1)  # 周一,2026-W23 起连续 5 整周
    for i in range(35):  # 5 full ISO weeks
        d = start + datetime.timedelta(days=i)
        rows.append({"date": int(d.strftime("%Y%m%d")), "gmv": 1000.0, "pay_conversion_uv": 0.05})
    for i in range(35, 37):  # 2-day trailing stub
        d = start + datetime.timedelta(days=i)
        rows.append({"date": int(d.strftime("%Y%m%d")), "gmv": 10.0, "pay_conversion_uv": 0.01})

    series = _weekly_metric_series(cols, rows)
    weeks = [w for w, _ in series["weekly_gmv"]]
    stub_week = "2026-W" + str(datetime.date(2026, 7, 6).isocalendar()[1]).zfill(2)
    assert stub_week not in weeks
    # 最新保留周的 GMV 应是满周求和 (7000),不是被残周污染的 20。
    assert series["weekly_gmv"][-1][1] == 7000.0
