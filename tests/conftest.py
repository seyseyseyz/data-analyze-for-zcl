from pathlib import Path

import pytest

# Every report production lands in a timestamped folder ``outputs/<TS>-<name>/``.
# Pinning the stamp makes that folder path deterministic so tests can address the
# delivered artifacts directly. Tests that exercise the wall-clock path clear or
# override the env var themselves (see test_project_foundation).
RUN_TS = "20260101-000000"


@pytest.fixture(autouse=True)
def _fixed_run_timestamp(monkeypatch):
    monkeypatch.setenv("XHS_CA_RUN_TIMESTAMP", RUN_TS)


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parent / "fixtures"
