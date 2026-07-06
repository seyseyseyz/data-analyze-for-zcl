import json

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


def test_extract_json_raw():
    assert nw.extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    text = "prose before\n```json\n{\"a\": 2}\n```\ntrailing"
    assert nw.extract_json(text) == {"a": 2}


def test_extract_json_balanced_scan():
    text = "the model said: {\"section_id\": \"x\", \"body\": \"hi 🍵\"} thanks!"
    assert nw.extract_json(text) == {"section_id": "x", "body": "hi 🍵"}


def test_extract_json_raises_when_absent():
    with pytest.raises(ValueError):
        nw.extract_json("no json here at all")


def test_ingest_rejects_wrong_stage(tmp_path):
    results, facts_json = _bundle_inputs(3)
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")
    # stage is 'seed'; ingesting a 'fan' result is out of order
    with pytest.raises(ValueError):
        nw.ingest_output(tmp_path, stage="fan", text='{"section_id": "域0", "body": "x"}')


def test_ingest_seed_records_sections(tmp_path):
    results, facts_json = _bundle_inputs(3)
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")
    payload = '{"sections": [{"section_id": "域0", "title": "域0", "body": "b0 🍶"}]}'
    state = nw.ingest_output(tmp_path, stage="seed", text=payload)
    assert "域0" in state["sections"]
    assert state["sections"]["域0"]["body"] == "b0 🍶"


def test_extract_json_skips_fake_bracket_before_real_payload():
    text = 'note: {oops not json} real payload: {"section_id": "a", "body": "hi 🍵"}'
    assert nw.extract_json(text) == {"section_id": "a", "body": "hi 🍵"}


def test_extract_json_returns_textually_earliest_valid_json():
    text = 'array first [1, 2, 3] then object {"a": 1}'
    assert nw.extract_json(text) == [1, 2, 3]


def test_ingest_rejects_non_dict_section(tmp_path):
    results = {"domain_slices": [_slice(0)]}
    facts_json = {"facts_hash": "abc123", "numbers": {}}
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")
    with pytest.raises(ValueError):
        nw.ingest_output(tmp_path, stage="seed", text='{"sections": ["not-a-dict"]}')


def test_status_json_reports_next_action(tmp_path):
    results, facts_json = _bundle_inputs(3)
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")
    status = nw.status_json(tmp_path)
    assert status["stage"] == "seed"
    assert "next_action" in status and status["next_action"]
    assert status["briefs"]  # seed brief listed
    assert status["merged_sections"] == []


def test_advance_seed_to_fan(tmp_path):
    results, facts_json = _bundle_inputs(3)
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")
    nw.ingest_output(tmp_path, stage="seed",
                     text='{"sections":[{"section_id":"域0","title":"域0","body":"b"}]}')
    state = nw.advance_run(tmp_path)
    assert state["stage"] == "fan"


def test_advance_exhausted_gate_routes_to_deterministic(tmp_path, monkeypatch):
    results, facts_json = _bundle_inputs(3)
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")

    # force the gate to always FAIL so rounds exhaust
    class _Fail:
        status = "FAIL"
        hard_failures = [{"section_id": "域0", "reason": "number mismatch"}]
        bundle = {"sections": []}

    monkeypatch.setattr(nw, "run_gate", lambda bundle, facts: _Fail())
    called = {}
    monkeypatch.setattr(
        nw, "finalize_deterministic",
        lambda rd, *, project_root=None, reason: called.setdefault("reason", reason) or {"stage": "blocked"},
    )

    # fast-forward to gate: seed→fan→synth
    nw.ingest_output(tmp_path, stage="seed", text='{"sections":[{"section_id":"域0","title":"域0","body":"b"}]}')
    nw.advance_run(tmp_path)  # fan
    nw.ingest_output(tmp_path, stage="fan", text='{"section_id":"域0","title":"域0","body":"b"}')
    nw.advance_run(tmp_path)  # synth
    nw.ingest_output(tmp_path, stage="synth", text='{"sections":[{"section_id":"域0","title":"域0","body":"b"}]}')
    # gate rounds: each advance re-fails; after MAX_GATE_ROUNDS → deterministic
    for _ in range(nw.MAX_GATE_ROUNDS + 2):
        state = nw.advance_run(tmp_path)
        if state["stage"] == "blocked":
            break
    assert called["reason"] == "gate_exhausted"


def test_advance_gate_pass_flows_to_finalized_with_capped_bundle(tmp_path, monkeypatch):
    """A PASS report's capped .bundle must be adopted at every gate check, not discarded."""
    results, facts_json = _bundle_inputs(1)
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")

    capped_bundle = {"sections": [], "_capped_marker": "confidence-downgraded-by-gate"}

    class _Pass:
        status = "PASS"
        hard_failures = []
        bundle = capped_bundle

    monkeypatch.setattr(nw, "run_gate", lambda bundle, facts: _Pass())

    nw.ingest_output(tmp_path, stage="seed",
                     text='{"sections":[{"section_id":"域0","title":"域0","body":"b"}]}')
    nw.advance_run(tmp_path)  # fan
    nw.ingest_output(tmp_path, stage="fan", text='{"section_id":"域0","title":"域0","body":"b"}')
    nw.advance_run(tmp_path)  # synth
    nw.ingest_output(tmp_path, stage="synth",
                     text='{"sections":[{"section_id":"域0","title":"域0","body":"b"}]}')
    state = nw.advance_run(tmp_path)  # gate: PASS -> continuity, must adopt report.bundle
    assert state["stage"] == "continuity"
    assert state["_bundle"] == capped_bundle

    state = nw.advance_run(tmp_path)  # continuity recheck: PASS -> finalized
    assert state["stage"] == "finalized"
    # the capped bundle (not the stale pre-gate one) must be what's carried forward
    assert state["_bundle"] == capped_bundle


def test_advance_patch_round_recovers_after_one_gate_fail(tmp_path, monkeypatch):
    """A patch round that fails once then passes must reach continuity, not blocked."""
    results, facts_json = _bundle_inputs(1)
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")

    calls = {"n": 0}

    class _Fail:
        status = "FAIL"
        hard_failures = [{"section_id": "域0", "reason": "number mismatch"}]
        bundle = {"sections": []}

    class _Pass:
        status = "PASS"
        hard_failures = []
        bundle = {"sections": [], "_capped_marker": "patched-and-capped"}

    def fake_run_gate(bundle, facts):
        calls["n"] += 1
        return _Fail() if calls["n"] == 1 else _Pass()

    monkeypatch.setattr(nw, "run_gate", fake_run_gate)

    nw.ingest_output(tmp_path, stage="seed",
                     text='{"sections":[{"section_id":"域0","title":"域0","body":"b"}]}')
    nw.advance_run(tmp_path)  # fan
    nw.ingest_output(tmp_path, stage="fan", text='{"section_id":"域0","title":"域0","body":"b"}')
    nw.advance_run(tmp_path)  # synth
    nw.ingest_output(tmp_path, stage="synth",
                     text='{"sections":[{"section_id":"域0","title":"域0","body":"b"}]}')
    state = nw.advance_run(tmp_path)  # gate: FAIL (round 1) -> patch
    assert state["stage"] == "patch"
    assert state.get("degradation_reason") is None

    nw.ingest_output(tmp_path, stage="patch",
                     text='{"sections":[{"section_id":"域0","title":"域0","body":"patched"}]}')
    state = nw.advance_run(tmp_path)  # gate: PASS (round 2) -> continuity, not blocked

    assert state["stage"] == "continuity"
    assert state.get("degradation_reason") is None
    assert state["_bundle"] == _Pass.bundle


def test_advance_continuity_gate_failure_routes_to_blocked(tmp_path, monkeypatch):
    """The continuity recheck FAIL branch must route to deterministic/blocked, not raise."""
    results, facts_json = _bundle_inputs(1)
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")

    class _Pass:
        status = "PASS"
        hard_failures = []
        bundle = {"sections": []}

    class _Fail:
        status = "FAIL"
        hard_failures = [{"section_id": "域0", "reason": "continuity edit introduced drift"}]
        bundle = {"sections": []}

    calls = {"n": 0}

    def fake_run_gate(bundle, facts):
        calls["n"] += 1
        return _Pass() if calls["n"] == 1 else _Fail()

    monkeypatch.setattr(nw, "run_gate", fake_run_gate)
    called = {}
    monkeypatch.setattr(
        nw, "finalize_deterministic",
        lambda rd, *, project_root=None, reason: called.setdefault("reason", reason) or {"stage": "blocked"},
    )

    nw.ingest_output(tmp_path, stage="seed",
                     text='{"sections":[{"section_id":"域0","title":"域0","body":"b"}]}')
    nw.advance_run(tmp_path)  # fan
    nw.ingest_output(tmp_path, stage="fan", text='{"section_id":"域0","title":"域0","body":"b"}')
    nw.advance_run(tmp_path)  # synth
    nw.ingest_output(tmp_path, stage="synth",
                     text='{"sections":[{"section_id":"域0","title":"域0","body":"b"}]}')
    state = nw.advance_run(tmp_path)  # gate: PASS -> continuity
    assert state["stage"] == "continuity"

    state = nw.advance_run(tmp_path)  # continuity recheck: FAIL -> blocked, no exception raised
    assert state["stage"] == "blocked"
    assert called["reason"] == "continuity_gate_failed"
