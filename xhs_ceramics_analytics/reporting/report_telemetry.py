"""Per-run telemetry — the guard against a silently-degrading report.

Each report run appends one canonical JSON line to ``report_runs.jsonl`` recording
mode (frozen / skeleton / gate), the facts_hash, whether the frozen-narrative cache
hit, per-rule hard-fail counts, and a degradation reason code. The skill surfaces
``summarize_runs`` in its step-9 delivery note, so an over-strict gate rule cannot
make skeleton the silent default — the counters make it visible. Records are
timestamp-free by design (deterministic + replay-safe; the spec bars a wall clock in
the hashed path). Pure + never raises on a normal filesystem.
"""
import json
from collections import Counter
from pathlib import Path

_VALID_MODES = ("frozen", "skeleton", "gate")


def build_run_record(
    *,
    mode: str,
    facts_hash: str,
    cache_hit: bool,
    hard_fail_counts: dict | None = None,
    degradation_reason: str | None = None,
) -> dict:
    """Deterministic run record. mode ∈ {frozen, skeleton, gate}. No timestamp by design."""
    return {
        "mode": mode if mode in _VALID_MODES else "gate",
        "facts_hash": facts_hash,
        "cache_hit": bool(cache_hit),
        "hard_fail_counts": dict(hard_fail_counts or {}),
        "degradation_reason": degradation_reason,
    }


def append_run_record(path, record: dict) -> None:
    """Append one canonical JSON line to report_runs.jsonl. Coerces a non-dict to an error row."""
    if not isinstance(record, dict):
        record = {"error": "invalid_record"}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True, ensure_ascii=False)
    with p.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def summarize_runs(records: list[dict]) -> str:
    """One-line human summary for the skill's step-9 delivery note."""
    modes = Counter(str(r.get("mode")) for r in records if isinstance(r, dict))
    hard = sum(
        sum((r.get("hard_fail_counts") or {}).values())
        for r in records
        if isinstance(r, dict)
    )
    parts = [f"{n} {mode}" for mode, n in sorted(modes.items())]
    tail = f" ({hard} gate hard-fail)" if hard else ""
    return f"{len(records)} runs: {', '.join(parts)}{tail}"
