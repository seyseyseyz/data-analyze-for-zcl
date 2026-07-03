"""Month-over-month trend helpers (observational; report direction, not p-values)."""

_EPS = 1e-9


def pct_change(old: float | None, new: float | None) -> float | None:
    if new is None or not old:
        return None
    return (new - old) / old


def direction_label(delta: float | None) -> str:
    if delta is None or abs(delta) < _EPS:
        return "持平"
    return "上升" if delta > 0 else "下降"


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
        }
    values = [v for _, v in series]
    first_value, last_value = values[0], values[-1]
    start_period, end_period = series[0][0], series[-1][0]
    if n == 1:
        slope = 0.0
    else:
        mean_x = (n - 1) / 2.0
        mean_y = sum(values) / n
        cov = sum((i - mean_x) * (values[i] - mean_y) for i in range(n))
        var_x = sum((i - mean_x) ** 2 for i in range(n))
        slope = cov / var_x if var_x else 0.0
    return {
        "direction": direction_label(slope),
        "slope": slope,
        "first_value": first_value,
        "last_value": last_value,
        "start_period": start_period,
        "end_period": end_period,
        "n": n,
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
