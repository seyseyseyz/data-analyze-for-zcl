"""Month-over-month trend helpers (observational; report direction, not p-values)."""
import math

_EPS = 1e-9
# A slope is called a real trend only when its t-statistic clears this bar. 2.0 is
# the ~95% two-sided normal cutoff and keeps daily noise from reading as a trend.
_SLOPE_T_THRESHOLD = 2.0


def pct_change(old: float | None, new: float | None) -> float | None:
    if new is None or not old:
        return None
    return (new - old) / old


def direction_label(delta: float | None) -> str:
    if delta is None or abs(delta) < _EPS:
        return "持平"
    return "上升" if delta > 0 else "下降"


def direction_from_summary(summary: dict) -> str:
    """Significance-gated trend direction for a ``trend_summary`` result.

    Unlike :func:`direction_label` (which reads any non-zero slope as a move), this
    reports "趋势不明" whenever the slope is not statistically distinguishable from
    noise, so a flat-but-wobbly daily series does not masquerade as a real trend.
    """
    if not summary or not summary.get("significant"):
        return "趋势不明"
    slope = summary.get("slope") or 0.0
    if abs(slope) < _EPS:
        return "持平"
    return "上升" if slope > 0 else "下降"


def trend_summary(series: list[tuple[str, float]]) -> dict:
    """Robust trend over a (period, value) series via ordinary least-squares slope.

    Direction is taken from the OLS slope across *all* points, not the first-vs-last
    delta — a single noisy endpoint cannot flip a stable trend. Returns
    ``{direction, slope, first_value, last_value, start_period, end_period, n}``.
    Degrades to a flat/zero summary on empty or single-point series.
    """
    n = len(series)
    if n == 0:
        return {
            "direction": "持平", "slope": 0.0, "first_value": None,
            "last_value": None, "start_period": None, "end_period": None, "n": 0,
            "slope_se": None, "t_stat": None, "significant": False, "rel_slope": None,
        }
    values = [v for _, v in series]
    first_value, last_value = values[0], values[-1]
    start_period, end_period = series[0][0], series[-1][0]
    mean_y = sum(values) / n
    if n == 1:
        slope = 0.0
        var_x = 0.0
    else:
        mean_x = (n - 1) / 2.0
        cov = sum((i - mean_x) * (values[i] - mean_y) for i in range(n))
        var_x = sum((i - mean_x) ** 2 for i in range(n))
        slope = cov / var_x if var_x else 0.0
    slope_se, t_stat, significant = _slope_significance(values, slope, var_x, n)
    # Dimension-free whole-window change: slope spans (n-1) steps, scaled by level.
    rel_slope = (slope * (n - 1) / mean_y) if mean_y else None
    return {
        "direction": direction_label(slope),
        "slope": slope,
        "first_value": first_value,
        "last_value": last_value,
        "start_period": start_period,
        "end_period": end_period,
        "n": n,
        "slope_se": slope_se,
        "t_stat": t_stat,
        "significant": significant,
        "rel_slope": rel_slope,
    }


def _slope_significance(
    values: list[float], slope: float, var_x: float, n: int
) -> tuple[float | None, float | None, bool]:
    """t-test on the OLS slope against zero. Degrades to (None, None, False).

    Needs at least 3 points for a residual variance (n-2 dof). A perfect fit
    (zero residual, non-zero slope) is treated as significant with an infinite t,
    never a ZeroDivisionError.
    """
    if n < 3 or var_x <= 0:
        return None, None, False
    mean_x = (n - 1) / 2.0
    mean_y = sum(values) / n
    intercept = mean_y - slope * mean_x
    sse = sum((values[i] - (intercept + slope * i)) ** 2 for i in range(n))
    resid_var = sse / (n - 2)
    if resid_var <= _EPS:
        # Exact linear fit: a real slope is unambiguously significant.
        return 0.0, (math.inf if abs(slope) > _EPS else 0.0), abs(slope) > _EPS
    slope_se = math.sqrt(resid_var / var_x)
    if slope_se <= 0:
        return slope_se, None, False
    t_stat = slope / slope_se
    return slope_se, t_stat, abs(t_stat) >= _SLOPE_T_THRESHOLD


_MIN_POINTS_FOR_EXTRAPOLATION = 4


def trend_extrapolation(
    series: list[tuple[str, float]], horizon: int = 7, non_negative: bool = False
) -> dict | None:
    """Short-horizon linear projection of the trend — an observational hint, never a promise.

    Extends the OLS trend line ``horizon`` steps past the last observation, but *only*
    when the slope is statistically significant (via :func:`trend_summary`); a flat or
    noisy series returns ``None`` rather than a spurious forecast. This deliberately
    projects the fitted trend, not the raw last value, so a single noisy endpoint cannot
    drive the number. ``non_negative`` clamps the projection at zero for quantities that
    cannot go negative (GMV, counts). Returns ``{horizon, slope, last_value,
    projected_value, direction, basis}`` or ``None``. Degrades on short series; never raises.
    """
    summary = trend_summary(series)
    if summary.get("n", 0) < _MIN_POINTS_FOR_EXTRAPOLATION or not summary.get("significant"):
        return None
    slope = summary.get("slope") or 0.0
    last_value = summary.get("last_value")
    if last_value is None:
        return None
    projected = last_value + slope * horizon
    if non_negative and projected < 0:
        projected = 0.0
    return {
        "horizon": horizon,
        "slope": slope,
        "last_value": last_value,
        "projected_value": projected,
        "direction": direction_from_summary(summary),
        "basis": "ols_trend",
    }


def mom_change(series: list[tuple[str, float]]) -> list[dict]:
    rows: list[dict] = []
    previous: float | None = None
    for period, value in series:
        delta = None if previous is None else value - previous
        pct = None if previous is None else pct_change(previous, value)
        rows.append(
            {
                "period": period,
                "value": value,
                "delta": delta,
                "pct": pct,
                "direction": direction_label(delta),
            }
        )
        previous = value
    return rows
