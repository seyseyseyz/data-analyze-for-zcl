import json
from pathlib import Path

import pytest

from xhs_ceramics_analytics.orchestration import narrative_workflow as nw


def _slice(i):
    return {"title": f"域{i}", "facts": [{"metric": f"m{i}", "value": i}], "reading": {"conclusion": f"c{i}"}}


def _bundle_inputs(n):
    results = {"domain_slices": [_slice(i) for i in range(n)]}
    facts_json = {"facts_hash": "abc123", "numbers": {}}
    return results, facts_json


def test_slug_preserves_cjk_and_normalizes_ascii():
    assert nw._slug("生意大盘") == "生意大盘"
    assert nw._slug("Traffic & Content") == "traffic-content"


def test_cap_slices_folds_tail_losslessly():
    slices = [_slice(i) for i in range(9)]
    capped, merged = nw._cap_slices(slices)
    assert len(capped) == nw.MAX_FAN_AGENTS
    # first five untouched, sixth is the folded remainder
    assert capped[-1]["title"] == "综合参考"
    assert [s["title"] for s in slices[nw.MAX_FAN_AGENTS - 1:]] == merged
    # every original fact survives in the capped set
    folded_facts = [f for s in capped for f in s["facts"]]
    assert len(folded_facts) == sum(len(s["facts"]) for s in slices)


def test_cap_slices_noop_under_cap():
    slices = [_slice(i) for i in range(4)]
    capped, merged = nw._cap_slices(slices)
    assert capped == slices
    assert merged == []


def test_prepare_run_writes_state_and_briefs(tmp_path):
    results, facts_json = _bundle_inputs(9)
    state = nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="测试报告")
    assert state["stage"] == "seed"
    assert state["report_name"] == "测试报告"
    assert state["facts_hash"] == "abc123"
    # tail folded → merged_sections recorded
    assert state["merged_sections"] == [f"域{i}" for i in range(5, 9)]
    assert (tmp_path / "state.json").exists()
    assert (tmp_path / "briefs" / "seed.md").exists()
    assert (tmp_path / "domain_slices.json").exists()
    fan_briefs = sorted((tmp_path / "briefs").glob("fan_*.md"))
    assert len(fan_briefs) == nw.MAX_FAN_AGENTS


def test_prepare_run_refuses_overwrite_of_unfinished_run(tmp_path):
    results, facts_json = _bundle_inputs(3)
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")
    with pytest.raises(FileExistsError):
        nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")
    # force overrides
    state = nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r", force=True)
    assert state["stage"] == "seed"


def test_prepare_run_allows_overwrite_when_finalized(tmp_path):
    results, facts_json = _bundle_inputs(3)
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")
    raw = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    raw["stage"] = "finalized"
    (tmp_path / "state.json").write_text(json.dumps(raw), encoding="utf-8")
    # no force needed once finalized/blocked
    state = nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")
    assert state["stage"] == "seed"
