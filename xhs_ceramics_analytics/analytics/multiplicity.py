"""Multiple-comparison control for outlier scans.

When a module scans hundreds of notes / thousands of SKUs for "rate above
baseline", some will clear the bar by chance alone. Per-item Wilson intervals
guard small samples but do NOT control the family-wide false-discovery rate.
Benjamini-Hochberg (BH) does: it caps the expected share of false positives
among the flagged items at ``alpha``.

Pure stdlib (math only) — never raises on dirty input; degrades to a safe
"nothing significant" verdict when data is missing or degenerate.
"""
import math


def one_sided_binomial_p(k: float, n: float, p0: float) -> float:
    """Upper-tail p-value for observing ``k`` successes in ``n`` trials under
    H0 proportion ``p0`` (H1: observed rate > ``p0``).

    Uses a normal approximation with a continuity correction — adequate for the
    n≥10 sample sizes these scans guard to. Returns 1.0 (no evidence) for any
    degenerate input rather than raising: n≤0, p0 outside (0, 1), or observed
    rate at/below p0.
    """
    if n <= 0 or not (0.0 < p0 < 1.0):
        return 1.0
    k = min(max(k, 0.0), n)
    phat = k / n
    if phat <= p0:
        return 1.0
    se = math.sqrt(p0 * (1.0 - p0) / n)
    if se == 0:
        return 1.0
    # Continuity correction on the count scale (0.5/n on the rate scale).
    z = (phat - p0 - 0.5 / n) / se
    if z <= 0:
        return 1.0
    # Upper-tail standard-normal survival via erfc.
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def benjamini_hochberg(pvalues: list[float], alpha: float = 0.05) -> list[bool]:
    """Return, per input p-value, whether it survives BH-FDR control at ``alpha``.

    Output order matches input order. ``None`` entries (untestable items) are
    treated as non-significant. Empty input → empty output. Never raises.
    """
    clean = [(i, p) for i, p in enumerate(pvalues) if p is not None]
    n = len(clean)
    survived = [False] * len(pvalues)
    if n == 0 or not (0.0 < alpha <= 1.0):
        return survived
    ordered = sorted(clean, key=lambda t: t[1])
    # Largest rank k with p_(k) <= (k/n)*alpha; everything up to it survives.
    max_rank = 0
    for rank, (_, p) in enumerate(ordered, start=1):
        if p <= (rank / n) * alpha:
            max_rank = rank
    for rank, (orig_idx, _) in enumerate(ordered, start=1):
        if rank <= max_rank:
            survived[orig_idx] = True
    return survived


def expected_false_positives(n_tests: int, alpha: float = 0.05) -> float:
    """Rough count of flags expected by chance if every null were true.

    Used only to annotate a finding ("预计假阳性约 N 个"); not a decision rule.
    """
    if n_tests <= 0 or alpha <= 0:
        return 0.0
    return n_tests * alpha
