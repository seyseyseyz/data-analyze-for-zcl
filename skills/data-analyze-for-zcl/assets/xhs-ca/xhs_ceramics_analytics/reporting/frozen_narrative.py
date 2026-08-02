"""Versioned cache for a gate-approved narrative and its source tables.

The cache is reusable only when facts, result tables, prompts, schemas, registry,
controller, and renderer all match. Cache writes are atomic so an interrupted run
cannot replace a valid checkpoint with a partial JSON file.
"""

import hashlib
import inspect
import json
import os
from pathlib import Path
import tempfile

from xhs_ceramics_analytics.reporting import (
    charts,
    factcheck_gate,
    first_screen,
    markdown,
    money,
    narrative_render,
)
from xhs_ceramics_analytics.reporting import html as html_mod

_FORMAT_VERSION = 4
_REQUIRED_KEYS = (
    "format_version",
    "schema_version",
    "facts_hash",
    "results_hash",
    "renderer_version",
    "result_tables_hash",
    "narrative_bundle_hash",
    "narrative_bundle",
    "result_tables",
)

_CONTRACT_PATTERNS = (
    "orchestration/prompts/*.md",
    "orchestration/schemas/*.json",
    "xhs_ceramics_analytics/orchestration/narrative_workflow.py",
    "xhs_ceramics_analytics/contracts/metrics.py",
    "xhs_ceramics_analytics/contracts/platform_catalog.py",
    "references/metrics/*.yaml",
    "references/platform/*.yaml",
    "references/source_bindings/*.yaml",
)

_RENDERER_PATTERNS = ("xhs_ceramics_analytics/reporting/templates/*.j2",)


def _hash_sources(modules) -> str:
    digest = hashlib.sha256()
    for module in modules:
        digest.update(module.__name__.encode("utf-8"))
        digest.update(b"\0")
        digest.update(inspect.getsource(module).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def _project_root(project_root: str | Path | None = None) -> Path:
    if project_root is not None:
        return Path(project_root)
    return Path(__file__).resolve().parents[2]


def _contract_files(project_root: Path, patterns: tuple[str, ...]) -> list[Path]:
    files: set[Path] = set()
    for pattern in patterns:
        files.update(path for path in project_root.glob(pattern) if path.is_file())
    return sorted(files, key=lambda path: path.relative_to(project_root).as_posix())


def _update_with_files(digest, project_root: Path, patterns: tuple[str, ...]) -> None:
    for path in _contract_files(project_root, patterns):
        digest.update(path.relative_to(project_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")


def _canonical_json(value) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def narrative_schema_version(project_root: str | Path | None = None) -> str:
    """Hash every input that can change how agents interpret or validate facts."""
    digest = hashlib.sha256()
    digest.update(_hash_sources((factcheck_gate, narrative_render, first_screen)).encode("ascii"))
    _update_with_files(digest, _project_root(project_root), _CONTRACT_PATTERNS)
    return digest.hexdigest()[:16]


def renderer_version(project_root: str | Path | None = None) -> str:
    """Hash Python renderers and their HTML templates."""
    digest = hashlib.sha256()
    digest.update(_hash_sources((charts, html_mod, markdown, money)).encode("ascii"))
    _update_with_files(digest, _project_root(project_root), _RENDERER_PATTERNS)
    return digest.hexdigest()[:16]


def result_tables_hash(result_tables: dict | None) -> str:
    """Canonical hash of the deterministic table snapshot used by curated views."""
    return hashlib.sha256(_canonical_json(result_tables or {})).hexdigest()


def payload_hash(value) -> str:
    """Canonical hash for an upstream JSON payload."""
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def build_frozen(
    facts_hash: str,
    bundle: dict,
    *,
    results_hash: str,
    result_tables: dict | None = None,
    project_root: str | Path | None = None,
) -> dict:
    """Build a complete, self-validating cache payload without touching disk."""
    if not isinstance(results_hash, str) or not results_hash:
        raise ValueError("results_hash must be a non-empty string")
    tables = result_tables or {}
    return {
        "format_version": _FORMAT_VERSION,
        "schema_version": narrative_schema_version(project_root),
        "facts_hash": facts_hash,
        "results_hash": results_hash,
        "renderer_version": renderer_version(project_root),
        "result_tables_hash": result_tables_hash(tables),
        "narrative_bundle_hash": payload_hash(bundle),
        "narrative_bundle": bundle,
        "result_tables": tables,
    }


def write_frozen(
    path,
    facts_hash: str,
    bundle: dict,
    *,
    results_hash: str,
    result_tables: dict | None = None,
    project_root: str | Path | None = None,
) -> None:
    payload = build_frozen(
        facts_hash,
        bundle,
        results_hash=results_hash,
        result_tables=result_tables,
        project_root=project_root,
    )
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, sort_keys=True, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


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
    if data.get("format_version") != _FORMAT_VERSION:
        raise ValueError(
            f"unsupported frozen_narrative format_version {data.get('format_version')!r}"
        )
    if not isinstance(data.get("results_hash"), str) or not data["results_hash"]:
        raise ValueError("frozen_narrative results_hash must be a non-empty string")
    if data.get("result_tables_hash") != result_tables_hash(data.get("result_tables")):
        raise ValueError("frozen_narrative result_tables_hash does not match result_tables")
    if data.get("narrative_bundle_hash") != payload_hash(data.get("narrative_bundle")):
        raise ValueError("frozen_narrative narrative_bundle_hash does not match narrative_bundle")
    return data


def is_cache_hit(
    frozen: dict | None,
    facts_hash: str,
    *,
    results_hash: str,
    result_tables: dict | None = None,
    project_root: str | Path | None = None,
) -> bool:
    if not frozen:
        return False
    return (
        frozen.get("format_version") == _FORMAT_VERSION
        and frozen.get("facts_hash") == facts_hash
        and frozen.get("results_hash") == results_hash
        and frozen.get("schema_version") == narrative_schema_version(project_root)
        and frozen.get("renderer_version") == renderer_version(project_root)
        and frozen.get("result_tables_hash") == result_tables_hash(result_tables)
        and frozen.get("narrative_bundle_hash") == payload_hash(frozen.get("narrative_bundle"))
    )
