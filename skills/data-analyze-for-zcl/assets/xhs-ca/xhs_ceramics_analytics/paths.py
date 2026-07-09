import os
from datetime import datetime
from pathlib import Path


STATE_DIR_NAME = ".xhs-ceramics-analytics"
RUN_TIMESTAMP_ENV = "XHS_CA_RUN_TIMESTAMP"


def project_root(start: Path | None = None) -> Path:
    configured_root = os.environ.get("XHS_CA_PROJECT_ROOT")
    if configured_root:
        return Path(configured_root).expanduser().resolve()

    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return current


def state_dir(root: Path | None = None) -> Path:
    directory = (root or project_root()) / STATE_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def outputs_dir(root: Path | None = None) -> Path:
    directory = state_dir(root) / "outputs"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def run_timestamp() -> str:
    """Wall-clock stamp for a production folder name: ``YYYYMMDD-HHMMSS`` (local time).

    Read only at the CLI/orchestration boundary that names a fresh output folder — never
    inside report rendering, so the report bytes stay deterministic (the stamp lands in
    the FOLDER path only). ``XHS_CA_RUN_TIMESTAMP`` overrides it, which makes a production
    folder reproducible for tests and for a deterministic re-render of the same run.
    """
    override = os.environ.get(RUN_TIMESTAMP_ENV)
    if override:
        return override
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def run_output_dir(basename: str, timestamp: str, root: Path | None = None) -> Path:
    """Per-production output folder: ``outputs/<timestamp>-<basename>/`` (created).

    Every report production lands in its own timestamped folder so successive runs never
    overwrite one another and each deliverable set (md + html [+ render_errors.txt]) is
    uniquely addressable. The caller supplies ``timestamp`` (from :func:`run_timestamp`)
    rather than this helper reading the clock, so the pure path layer stays clock-free.
    """
    directory = outputs_dir(root) / f"{timestamp}-{basename}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory
