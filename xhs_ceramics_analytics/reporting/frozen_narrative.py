"""Frozen-narrative override — the cache checkpoint beside mapping_overrides.yaml.

A narrative_bundle that passed the gate is persisted under the triple key
``(facts_hash, narrative_schema_version, renderer_version)``. A cache hit means the
whole agent layer is skipped and Python re-renders the frozen narrative at 0 LLM
calls. ``narrative_schema_version`` hashes the gate/render contract (prompts+schemas
fold in via Plan 3); ``renderer_version`` hashes the chart/html/markdown/money source.
Either bump silently invalidates a stale narrative — we never ship old bytes under a
changed contract. Mirrors ``importing/overrides.py``: absent → None, malformed → ValueError.
"""
import hashlib
import inspect
import json
from pathlib import Path

from xhs_ceramics_analytics.reporting import (
    charts,
    factcheck_gate,
    first_screen,
    markdown,
    money,
    narrative_render,
)
from xhs_ceramics_analytics.reporting import html as html_mod

_REQUIRED_KEYS = ("schema_version", "facts_hash", "renderer_version", "narrative_bundle")


def _hash_sources(modules) -> str:
    h = hashlib.sha256()
    for module in modules:
        h.update(inspect.getsource(module).encode("utf-8"))
    return h.hexdigest()[:16]


def narrative_schema_version() -> str:
    """Hash of the deterministic narrative contract (gate + render + first_screen)."""
    return _hash_sources((factcheck_gate, narrative_render, first_screen))


def renderer_version() -> str:
    """Hash of the rendering surface (charts / html / markdown / money)."""
    return _hash_sources((charts, html_mod, markdown, money))


def write_frozen(path, facts_hash: str, bundle: dict) -> None:
    payload = {
        "schema_version": narrative_schema_version(),
        "facts_hash": facts_hash,
        "renderer_version": renderer_version(),
        "narrative_bundle": bundle,
    }
    Path(path).write_text(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_frozen(path) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"frozen_narrative could not be read as JSON: {exc}") from exc
    if not isinstance(data, dict) or any(k not in data for k in _REQUIRED_KEYS):
        raise ValueError(f"frozen_narrative missing required keys {_REQUIRED_KEYS}")
    return data


def is_cache_hit(frozen: dict | None, facts_hash: str) -> bool:
    if not frozen:
        return False
    return (
        frozen.get("facts_hash") == facts_hash
        and frozen.get("schema_version") == narrative_schema_version()
        and frozen.get("renderer_version") == renderer_version()
    )
