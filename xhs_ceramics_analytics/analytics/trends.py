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
