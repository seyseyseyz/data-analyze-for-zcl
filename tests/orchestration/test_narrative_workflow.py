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

    def _fake_finalize(rd, *, project_root=None, reason):
        called["reason"] = reason
        return {"stage": "blocked"}

    monkeypatch.setattr(nw, "finalize_deterministic", _fake_finalize)

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


def test_advance_success_path_writes_both_narrative_artifacts(tmp_path, monkeypatch):
    """A PASS->PASS run must deliver <name>.md + <name>.html from the narrative bundle,
    not the 确定性骨架版 skeleton — the documented `finalized` contract."""
    from xhs_ceramics_analytics.paths import outputs_dir, state_dir

    results, facts_json = _bundle_inputs(1)
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json,
                   report_name="叙事报告", project_root=tmp_path)

    capped_bundle = {
        "headline": "本周经营平稳🌱",
        "sections": [
            {"section_id": "域0", "title": "生意大盘",
             "claims": [{"rendered_sentence": "GMV 稳定在 100", "confidence": "Medium"}]},
        ],
    }

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
    nw.advance_run(tmp_path)  # gate PASS -> continuity
    state = nw.advance_run(tmp_path)  # continuity PASS -> finalized + writes artifacts

    assert state["stage"] == "finalized"
    out = outputs_dir(tmp_path) / "20260101-000000-叙事报告"
    md_path = out / "叙事报告.md"
    html_path = out / "叙事报告.html"
    assert md_path.exists(), "success path must write <name>.md"
    assert html_path.exists(), "success path must write <name>.html"
    md = md_path.read_text(encoding="utf-8")
    assert "确定性骨架版" not in md  # the narrative, not the skeleton fallback
    assert "本周经营平稳🌱" in md    # emoji preserved verbatim
    # telemetry records a gate-mode run (not skeleton)
    runs = (state_dir(tmp_path) / "report_runs.jsonl").read_text(encoding="utf-8")
    assert '"mode": "gate"' in runs


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

    def _fake_finalize(rd, *, project_root=None, reason):
        called["reason"] = reason
        return {"stage": "blocked"}

    monkeypatch.setattr(nw, "finalize_deterministic", _fake_finalize)

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


def test_finalize_deterministic_writes_two_artifacts(tmp_path):
    results = {"domain_slices": [
        {"title": "生意大盘", "facts": [{"metric": "GMV", "value": 12345}],
         "reading": {"conclusion": "大盘平稳", "action": "维持投放", "caveats": ["口径：支付时间"]}},
    ]}
    facts_json = {"facts_hash": "h1", "numbers": {"GMV": 12345}}
    project_root = tmp_path / "proj"
    project_root.mkdir()
    run_dir = tmp_path / "run"
    nw.prepare_run(run_dir, results=results, facts_json=facts_json,
                   report_name="确定性报告", project_root=project_root)

    state = nw.finalize_deterministic(run_dir, project_root=project_root, reason="denied")
    assert state["stage"] == "blocked"
    assert state["degradation_reason"] == "denied"

    out = project_root / ".xhs-ceramics-analytics" / "outputs" / "20260101-000000-确定性报告"
    md = out / "确定性报告.md"
    html = out / "确定性报告.html"
    assert md.exists() and html.exists()
    body = md.read_text(encoding="utf-8")
    assert "确定性骨架版" in body
    assert "大盘平稳" in body       # conclusion preserved
    assert "口径：支付时间" in body   # caveat preserved verbatim
    assert "12,345" in body or "12345" in body  # fact rendered


def test_deterministic_lists_unanswerable_questions(tmp_path):
    results = {
        "domain_slices": [{"title": "流量", "facts": [], "reading": {"conclusion": "c"}}],
        "blocked_modules": [{"slug": "search_efficiency_diagnosis", "reason": "缺少搜索词表"}],
    }
    facts_json = {"facts_hash": "h2", "numbers": {}}
    project_root = tmp_path / "proj"
    project_root.mkdir()
    run_dir = tmp_path / "run"
    nw.prepare_run(run_dir, results=results, facts_json=facts_json,
                   report_name="r", project_root=project_root)
    nw.finalize_deterministic(run_dir, project_root=project_root, reason="unsupported")
    body = (project_root / ".xhs-ceramics-analytics" / "outputs" / "20260101-000000-r" / "r.md").read_text(encoding="utf-8")
    assert "暂时答不了的问题" in body
    assert "缺少搜索词表" in body


def test_deterministic_lists_string_blocked_modules(tmp_path):
    results = {
        "domain_slices": [{"title": "流量", "facts": [], "reading": {"conclusion": "c"}}],
        "blocked_modules": ["note_funnel"],
    }
    facts_json = {"facts_hash": "h2b", "numbers": {}}
    project_root = tmp_path / "proj"
    project_root.mkdir()
    run_dir = tmp_path / "run"
    nw.prepare_run(run_dir, results=results, facts_json=facts_json,
                   report_name="r", project_root=project_root)
    nw.finalize_deterministic(run_dir, project_root=project_root, reason="unsupported")
    body = (project_root / ".xhs-ceramics-analytics" / "outputs" / "20260101-000000-r" / "r.md").read_text(encoding="utf-8")
    assert "暂时答不了的问题" in body
    assert "note_funnel" in body


def test_producer_output_feeds_finalize_deterministic_without_crash(tmp_path):
    """The real P1 producer emits blocked_modules as strings; the skeleton fallback
    must consume that exact shape. This is the integration the P1 tests missed and
    the live run hit as AttributeError: 'str' has no attribute 'get'."""
    from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
    from xhs_ceramics_analytics.evidence import EvidenceStrength
    from xhs_ceramics_analytics.reporting.narrative_results import build_narrative_results

    analysis = [
        AnalysisResult(
            task_id="core_business_diagnosis",
            title="大盘",
            findings=[Finding(title="t", conclusion="大盘走弱", evidence_strength=EvidenceStrength.WEAK, key_numbers={"gmv": 1})],
        )
    ]
    results = build_narrative_results(
        analysis,
        blocked_modules=[("note_funnel", "笔记表缺少 impressions 字段"), "paid_traffic_efficiency"],
    )
    # contract: normalized to {slug, reason} dicts — the skeleton reader consumes this.
    assert all(isinstance(b, dict) and "slug" in b for b in results["blocked_modules"])
    facts_json = {"facts_hash": "h", "numbers": {}}
    project_root = tmp_path / "proj"
    project_root.mkdir()
    run_dir = tmp_path / "run"
    nw.prepare_run(run_dir, results=results, facts_json=facts_json, report_name="r", project_root=project_root)
    nw.finalize_deterministic(run_dir, project_root=project_root, reason="unsupported")
    body = (project_root / ".xhs-ceramics-analytics" / "outputs" / "20260101-000000-r" / "r.md").read_text(encoding="utf-8")
    assert "note_funnel" in body and "paid_traffic_efficiency" in body
    # the coverage reason must reach the skeleton, not just the bare slug.
    assert "笔记表缺少 impressions 字段" in body


def test_finalize_deterministic_handles_slice_with_no_reading_key(tmp_path):
    """A slice missing the 'reading' key entirely must not raise; both artifacts still land."""
    results = {"domain_slices": [
        {"title": "流量", "facts": [{"metric": "曝光", "value": 100}]},
    ]}
    facts_json = {"facts_hash": "h3", "numbers": {}}
    project_root = tmp_path / "proj"
    project_root.mkdir()
    run_dir = tmp_path / "run"
    nw.prepare_run(run_dir, results=results, facts_json=facts_json,
                   report_name="r", project_root=project_root)

    state = nw.finalize_deterministic(run_dir, project_root=project_root, reason="denied")
    assert state["stage"] == "blocked"

    out = project_root / ".xhs-ceramics-analytics" / "outputs" / "20260101-000000-r"
    assert (out / "r.md").exists()
    assert (out / "r.html").exists()


def test_finalize_deterministic_preserves_emoji_verbatim(tmp_path):
    """Emoji in merchant conclusion/caveat text must survive verbatim, never stripped."""
    results = {"domain_slices": [
        {"title": "生意大盘", "facts": [{"metric": "GMV", "value": 999}],
         "reading": {"conclusion": "大盘冲刺 🚀 表现亮眼", "caveats": ["数据来源：门店后台 📊"]}},
    ]}
    facts_json = {"facts_hash": "h4", "numbers": {"GMV": 999}}
    project_root = tmp_path / "proj"
    project_root.mkdir()
    run_dir = tmp_path / "run"
    nw.prepare_run(run_dir, results=results, facts_json=facts_json,
                   report_name="r", project_root=project_root)

    nw.finalize_deterministic(run_dir, project_root=project_root, reason="denied")
    body = (project_root / ".xhs-ceramics-analytics" / "outputs" / "20260101-000000-r" / "r.md").read_text(encoding="utf-8")
    assert "大盘冲刺 🚀 表现亮眼" in body
    assert "数据来源：门店后台 📊" in body


def test_advance_exhaustion_preserves_finalize_history(tmp_path, monkeypatch):
    """When gate exhausts and routes to finalize_deterministic, the history entry must survive.

    Regression test for bug where _route_deterministic clobbered the history entry
    appended by finalize_deterministic. The real finalize_deterministic (not monkeypatched)
    must run and its history append must persist without being lost.
    """
    results, facts_json = _bundle_inputs(3)
    project_root = tmp_path / "proj"
    project_root.mkdir()
    run_dir = tmp_path / "run"
    nw.prepare_run(run_dir, results=results, facts_json=facts_json,
                   report_name="r", project_root=project_root)

    # Force gate to always FAIL so rounds exhaust; do NOT monkeypatch finalize_deterministic
    class _Fail:
        status = "FAIL"
        hard_failures = [{"section_id": "域0", "reason": "number mismatch"}]
        bundle = {"sections": []}

    monkeypatch.setattr(nw, "run_gate", lambda bundle, facts: _Fail())

    # Fast-forward to gate: seed→fan→synth
    nw.ingest_output(run_dir, stage="seed",
                     text='{"sections":[{"section_id":"域0","title":"域0","body":"b"}]}')
    nw.advance_run(run_dir, project_root=project_root)  # fan
    nw.ingest_output(run_dir, stage="fan", text='{"section_id":"域0","title":"域0","body":"b"}')
    nw.advance_run(run_dir, project_root=project_root)  # synth
    nw.ingest_output(run_dir, stage="synth",
                     text='{"sections":[{"section_id":"域0","title":"域0","body":"b"}]}')

    # Gate rounds: each advance re-fails; after MAX_GATE_ROUNDS → finalize_deterministic
    for _ in range(nw.MAX_GATE_ROUNDS + 2):
        state = nw.advance_run(run_dir, project_root=project_root)
        if state["stage"] == "blocked":
            break

    # Assert stage is blocked and history entry was appended by finalize_deterministic
    assert state["stage"] == "blocked"
    assert state["history"][-1] == "finalize_deterministic:gate_exhausted"

    # Reload state from disk to verify history persisted correctly
    reloaded = nw._load_state(run_dir)
    assert reloaded["stage"] == "blocked"
    assert reloaded["history"][-1] == "finalize_deterministic:gate_exhausted"


# ---- visuals_missing degradation (non-blocking success-path signal) ---------
#
# The narrative may finalize with charts genuinely missing while the fact layer HAD
# chartable data (agents gave none AND the bundle carried no section the deterministic
# fallback could chart). That is a real, honest gap: finalize STILL succeeds (never
# skeleton, never a gate FAIL) but stamps degradation_reason="visuals_missing" on both
# the state and the telemetry line, so the delivery note can surface it.

def _finalize_with(tmp_path, *, bundle, result_tables):
    results = {"domain_slices": [_slice(0)], "result_tables": result_tables}
    facts_json = {"facts_hash": "abc123", "facts": {}}
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json,
                   report_name="r", project_root=tmp_path)
    raw = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    raw["_bundle"] = bundle
    raw["stage"] = "continuity"
    (tmp_path / "state.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return nw.finalize_narrative(tmp_path, project_root=tmp_path)


def test_finalize_flags_visuals_missing_when_chartable_data_but_no_chart(tmp_path):
    from xhs_ceramics_analytics.paths import state_dir
    bundle = {"headline": "h", "sections": [], "cannot_say": []}  # no chartable section
    tables = {"business_trend": [{"date": "2026-04-01", "gmv": 14356.0}]}
    state = _finalize_with(tmp_path, bundle=bundle, result_tables=tables)
    assert state["stage"] == "finalized"                    # NOT skeleton / blocked
    assert state["degradation_reason"] == "visuals_missing"
    runs = (state_dir(tmp_path) / "report_runs.jsonl").read_text(encoding="utf-8")
    assert '"degradation_reason": "visuals_missing"' in runs
    assert '"mode": "gate"' in runs                          # still a success-path run


def test_finalize_no_degradation_when_fallback_injects_chart(tmp_path):
    from xhs_ceramics_analytics.paths import outputs_dir
    bundle = {"headline": "h",
              "sections": [{"section_id": "s", "title": "生意大盘",
                            "claims": [{"rendered_sentence": "GMV 稳。", "confidence": "中"}],
                            "curated_views": []}],
              "cannot_say": []}
    tables = {"business_trend": [{"date": "2026-04-01", "gmv": 14356.0},
                                 {"date": "2026-04-02", "gmv": 22687.0}]}
    state = _finalize_with(tmp_path, bundle=bundle, result_tables=tables)
    assert state["stage"] == "finalized"
    assert state.get("degradation_reason") is None
    md = (outputs_dir(tmp_path) / "20260101-000000-r" / "r.md").read_text(encoding="utf-8")
    assert "<svg" in md    # the fallback chart landed in the delivered artifact


def test_finalize_no_degradation_when_no_chartable_data(tmp_path):
    # thin data (no mapped chartable table) → chart-less is honest, not a degradation
    bundle = {"headline": "h", "sections": [], "cannot_say": []}
    state = _finalize_with(tmp_path, bundle=bundle, result_tables={"growth_bridge": [{"a": 1}]})
    assert state["stage"] == "finalized"
    assert state.get("degradation_reason") is None
