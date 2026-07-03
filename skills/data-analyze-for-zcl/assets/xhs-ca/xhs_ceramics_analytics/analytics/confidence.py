"""Honest small-sample confidence for observed rates.

Feeds ``evidence.py`` rather than duplicating its enum. Below
``MIN_ORDERS_FOR_RATE`` a rate is not judgable and should be left unranked.
"""
import math

MIN_ORDERS_FOR_RATE = 30


def wilson_interval(k: float, n: float, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return (max(0.0, center - margin), min(1.0, center + margin))


def min_n_guard(n: float | None) -> bool:
    return n is not None and n >= MIN_ORDERS_FOR_RATE


def rate_band(lo: float, hi: float) -> str:
    return f"约 {round(lo * 100)}%–{round(hi * 100)}%"
