from xhs_ceramics_analytics.reporting.report_telemetry import build_run_record, _VALID_MODES


def test_blocked_mode_is_valid():
    assert "blocked" in _VALID_MODES
    rec = build_run_record(mode="blocked", facts_hash="h", cache_hit=False, degradation_reason="denied")
    assert rec["mode"] == "blocked"
    assert rec["degradation_reason"] == "denied"


def test_existing_modes_still_valid():
    for mode in ("frozen", "skeleton", "gate"):
        rec = build_run_record(mode=mode, facts_hash="h", cache_hit=False)
        assert rec["mode"] == mode


def test_unknown_mode_degrades_to_unknown():
    # Telemetry never raises (module contract) — an unrecognized mode degrades
    # to the sentinel "unknown" rather than propagating an exception.
    rec = build_run_record(mode="bogus", facts_hash="h", cache_hit=False)
    assert rec["mode"] == "unknown"
