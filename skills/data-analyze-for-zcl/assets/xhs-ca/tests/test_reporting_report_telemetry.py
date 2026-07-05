# tests/test_reporting_report_telemetry.py
import json

from xhs_ceramics_analytics.reporting import report_telemetry as rt


def test_build_run_record_is_deterministic():
    a = rt.build_run_record(mode="frozen", facts_hash="abc", cache_hit=True)
    b = rt.build_run_record(mode="frozen", facts_hash="abc", cache_hit=True)
    assert a == b
    assert a["mode"] == "frozen"
    assert a["facts_hash"] == "abc"
    assert a["cache_hit"] is True
    assert a["hard_fail_counts"] == {}
    assert a["degradation_reason"] is None


def test_build_run_record_carries_skeleton_reason():
    rec = rt.build_run_record(mode="skeleton", facts_hash="h", cache_hit=False,
                              hard_fail_counts={"SUMMED_POOLS": 2},
                              degradation_reason="gate_exhausted")
    assert rec["mode"] == "skeleton"
    assert rec["degradation_reason"] == "gate_exhausted"
    assert rec["hard_fail_counts"] == {"SUMMED_POOLS": 2}


def test_append_run_record_writes_one_jsonl_line(tmp_path):
    path = tmp_path / "sub" / "report_runs.jsonl"
    rt.append_run_record(path, rt.build_run_record(mode="frozen", facts_hash="h1", cache_hit=False))
    rt.append_run_record(path, rt.build_run_record(mode="skeleton", facts_hash="h2", cache_hit=False))
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["facts_hash"] == "h1"
    assert json.loads(lines[1])["mode"] == "skeleton"


def test_append_run_record_coerces_non_dict(tmp_path):
    path = tmp_path / "report_runs.jsonl"
    rt.append_run_record(path, ["not", "a", "dict"])
    line = json.loads(path.read_text(encoding="utf-8").strip())
    assert line == {"error": "invalid_record"}


def test_summarize_runs_counts_modes():
    records = [
        rt.build_run_record(mode="frozen", facts_hash="a", cache_hit=True),
        rt.build_run_record(mode="frozen", facts_hash="b", cache_hit=False),
        rt.build_run_record(mode="skeleton", facts_hash="c", cache_hit=False,
                            hard_fail_counts={"MISSING_FACT": 1}, degradation_reason="gate_exhausted"),
    ]
    summary = rt.summarize_runs(records)
    assert "3 runs" in summary
    assert "2 frozen" in summary
    assert "1 skeleton" in summary
