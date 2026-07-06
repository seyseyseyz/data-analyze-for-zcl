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


def test_partial_boundary_month_excluded_when_whole_months_exist(tmp_path):
    # 2026-05 only has days 20–31 (partial). The bridge must compare the two WHOLE
    # months (06 vs 07), not drag the partial May in as months[0] — that would flip
    # the direction (May→Jul reads as growth; Jun→Jul is a decline).
    db = tmp_path / "partial.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        "CREATE TABLE business_overview_daily "
        "(date INTEGER, gmv DOUBLE, paid_buyers DOUBLE, product_visitors DOUBLE)"
    )
    rows = []
    for d in range(20, 32):  # 2026-05 days 20–31 → partial, must be excluded
        rows.append((20260500 + d, 3000.0, 30.0, 500.0))
    for d in range(1, 31):  # 2026-06 full month
        rows.append((20260600 + d, 2000.0, 20.0, 400.0))
    for d in range(1, 32):  # 2026-07 full month
        rows.append((20260700 + d, 1700.0, 18.0, 420.0))
    con.executemany("INSERT INTO business_overview_daily VALUES (?, ?, ?, ?)", rows)
    finding, _ = _growth_attribution_finding(con, [])
    con.close()
    assert finding is not None
    joined = finding.conclusion + " ".join(finding.caveats)
    assert "2026-06" in joined and "2026-07" in joined
    assert "2026-05" in joined  # acknowledged as the excluded partial boundary month
    # Jun(60000) → Jul(52700) is a decline; May(36000) → Jul would read as growth.
    assert finding.key_numbers["delta_gmv"] is not None
    assert finding.key_numbers["delta_gmv"] < 0


def test_two_partial_months_kept_with_honest_caveat(tmp_path):
    # Only two months, both partial (15 days each) — nothing whole to fall back to.
    # Keep the comparison but the caveat must NOT claim "两个整月".
    con = duckdb.connect(str(_con_with_two_months(tmp_path)))
    finding, _ = _growth_attribution_finding(con, [])
    con.close()
    assert finding is not None
    assert "两个整月" not in " ".join(finding.caveats)


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
