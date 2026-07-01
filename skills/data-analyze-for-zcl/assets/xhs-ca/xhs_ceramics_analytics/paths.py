import os
from pathlib import Path


STATE_DIR_NAME = ".xhs-ceramics-analytics"


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
