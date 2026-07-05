"""Growth attribution bridges calendar months, not an arbitrary split-half."""
from pathlib import Path

import duckdb
import pytest

from xhs_ceramics_analytics.analysis.core_business import _growth_attribution_finding


def _con_with_two_months(tmp_path: Path):
    db = tmp_path / "t.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        "CREATE TABLE business_overview_daily "
        "(date INTEGER, gmv DOUBLE, paid_buyers DOUBLE, product_visitors DOUBLE)"
    )
    # 2026-05: 15 days; 2026-06: 15 days. Values chosen so ΔGMV is non-trivial.
    rows = []
    for d in range(1, 16):
        rows.append((20260500 + d, 2000.0, 20.0, 400.0))  # May
    for d in range(1, 16):
        rows.append((20260600 + d, 1700.0, 18.0, 420.0))  # June
    con.executemany("INSERT INTO business_overview_daily VALUES (?, ?, ?, ?)", rows)
    con.close()
    return db


def test_bridge_names_calendar_months_not_halves(tmp_path):
    con = duckdb.connect(str(_con_with_two_months(tmp_path)))
    finding, tables = _growth_attribution_finding(con, [])
    con.close()
    assert finding is not None
    joined = finding.conclusion + " ".join(finding.caveats)
    assert "2026-05" in joined and "2026-06" in joined
    assert "前半程" not in joined and "前段" not in joined


def test_bridge_residual_reconciles_to_zero(tmp_path):
    con = duckdb.connect(str(_con_with_two_months(tmp_path)))
    finding, tables = _growth_attribution_finding(con, [])
    con.close()
    kn = finding.key_numbers
    total = (kn["contrib_traffic"] or 0) + (kn["contrib_conversion"] or 0) + (kn["contrib_aov"] or 0)
    assert kn["delta_gmv"] == pytest.approx(total + (kn["residual"] or 0), abs=1e-6)


def test_single_month_degrades(tmp_path):
    db = tmp_path / "one.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        "CREATE TABLE business_overview_daily "
        "(date INTEGER, gmv DOUBLE, paid_buyers DOUBLE, product_visitors DOUBLE)"
    )
    con.executemany(
        "INSERT INTO business_overview_daily VALUES (?, ?, ?, ?)",
        [(20260600 + d, 1700.0, 18.0, 420.0) for d in range(1, 10)],
    )
    limitations: list[str] = []
    finding, tables = _growth_attribution_finding(con, limitations)
    con.close()
    assert finding is None
    assert any("月" in msg for msg in limitations)
