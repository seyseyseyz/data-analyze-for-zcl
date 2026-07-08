"""Option A (claims model) wiring — the fan/synth path emits structured claims +
first_screen and they survive through _record_section / ingest_output / _bundle_from_state
to the REAL fact-check gate and renderer.

The final test closes the monkeypatch-masking gap the summary flagged: every other
workflow test stubs ``run_gate``, so a body-vs-claims disconnect stayed invisible. Here
a real ``build_factbook`` facts.json + a hand-authored fan/synth output run through the
UNPATCHED gate and renderer, proving the assembled claims bundle both passes the gate and
renders real merchant prose (not the empty first-screen + heading-only output of the
incomplete body model).
"""
import json

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.orchestration import narrative_workflow as nw
from xhs_ceramics_analytics.paths import outputs_dir
from xhs_ceramics_analytics.reporting.facts_export import build_factbook, factbook_to_json
from xhs_ceramics_analytics.reporting.narrative_results import build_narrative_results


# ---- (b) fan brief requests claims + exposes fact_ids ---------------------

def _slice_with_fact():
    return {
        "title": "生意大盘",
        "facts": [
            {
                "metric": "gmv",
                "value": 120000,
                "fact_id": "core_business_diagnosis.gmv",
                "metric_key": "gmv",
                "rendered": "¥12.0万",
            }
        ],
        "reading": {"conclusion": "大盘走弱"},
    }


def test_fan_brief_requests_claims_and_exposes_fact_ids(tmp_path):
    results = {"domain_slices": [_slice_with_fact()]}
    facts_json = {"facts_hash": "h", "facts": {}}
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")
    brief = (tmp_path / "briefs" / "fan_00_生意大盘.md").read_text(encoding="utf-8")
    # the brief now asks for claims + curated_views, not a prose `body`
    assert "claims" in brief
    assert "curated_views" in brief
    assert "number_tokens" in brief
    # the resolvable fact_id is exposed so a claim can bind {tN} to it
    assert "core_business_diagnosis.gmv" in brief


# ---- (d) _record_section preserves claims + spine_callbacks ---------------

def test_record_section_preserves_claims_and_callbacks(tmp_path):
    results = {"domain_slices": [_slice_with_fact()]}
    facts_json = {"facts_hash": "h", "facts": {}}
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")
    nw.advance_run(tmp_path)  # seed -> fan
    section = {
        "section_id": "生意大盘",
        "title": "生意大盘",
        "claims": [
            {
                "claim_id": "c0",
                "section_id": "生意大盘",
                "claim_kind": "measurement",
                "sentence": "GMV 为 {t0}。",
                "number_tokens": [{"token_id": "t0", "fact_id": "core_business_diagnosis.gmv"}],
                "confidence": "强",
            }
        ],
        "spine_callbacks": ["L1"],
    }
    state = nw.ingest_output(tmp_path, stage="fan", text=json.dumps(section, ensure_ascii=False))
    recorded = state["sections"]["生意大盘"]
    assert recorded["claims"][0]["claim_id"] == "c0"
    assert recorded["claims"][0]["number_tokens"][0]["fact_id"] == "core_business_diagnosis.gmv"
    assert recorded["spine_callbacks"] == ["L1"]


# ---- (e) synth ingest captures bundle-level fields; bundle assembles them --

def test_synth_ingest_captures_first_screen_and_headline(tmp_path):
    results = {"domain_slices": [_slice_with_fact()]}
    facts_json = {"facts_hash": "h", "facts": {}}
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")
    nw.advance_run(tmp_path)  # seed -> fan
    nw.ingest_output(
        tmp_path,
        stage="fan",
        text=json.dumps(
            {"section_id": "生意大盘", "title": "生意大盘", "claims": [{"claim_id": "c0", "sentence": "x"}]},
            ensure_ascii=False,
        ),
    )
    nw.advance_run(tmp_path)  # fan -> synth (writes synth brief)
    synth_payload = {
        "headline": "大盘承压 🌧️",
        "first_screen": {"spine": [{"claim_id": "c0", "sentence": "x"}], "panel": [], "actions": ["复盘选品"]},
        "cannot_say": ["暂无法把订单归因到具体笔记"],
        "spine_final": {"backbone": [{"link_id": "L1"}]},
    }
    state = nw.ingest_output(tmp_path, stage="synth", text=json.dumps(synth_payload, ensure_ascii=False))
    assert state["_synth"]["headline"] == "大盘承压 🌧️"
    bundle = nw._bundle_from_state(state)
    assert bundle["headline"] == "大盘承压 🌧️"
    assert bundle["first_screen"]["actions"] == ["复盘选品"]
    assert bundle["cannot_say"] == ["暂无法把订单归因到具体笔记"]
    assert bundle["spine_final"]["backbone"][0]["link_id"] == "L1"
    # sections (with their claims) are still assembled
    assert bundle["sections"][0]["claims"][0]["claim_id"] == "c0"


def test_bundle_from_state_prose_only_is_unchanged_when_no_synth(tmp_path):
    # backward-compat: with no synth capture, the bundle is exactly {"sections": [...]}
    results = {"domain_slices": [_slice_with_fact()]}
    facts_json = {"facts_hash": "h", "facts": {}}
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")
    nw.advance_run(tmp_path)
    nw.ingest_output(tmp_path, stage="fan",
                     text=json.dumps({"section_id": "生意大盘", "title": "生意大盘", "body": "b"}, ensure_ascii=False))
    bundle = nw._bundle_from_state(nw._load_state(tmp_path))
    assert set(bundle) == {"sections"}


# ---- (c) synth brief written on fan->synth + surfaced by status -----------

def test_advance_fan_writes_synth_brief_and_status_lists_it(tmp_path):
    results = {"domain_slices": [_slice_with_fact()]}
    facts_json = {"facts_hash": "h", "facts": {}}
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")
    nw.advance_run(tmp_path)  # seed -> fan
    nw.ingest_output(tmp_path, stage="fan",
                     text=json.dumps({"section_id": "生意大盘", "title": "生意大盘",
                                      "claims": [{"claim_id": "c0", "sentence": "GMV 为 {t0}。"}]},
                                     ensure_ascii=False))
    state = nw.advance_run(tmp_path)  # fan -> synth
    assert state["stage"] == "synth"
    synth_brief = tmp_path / "briefs" / "synth.md"
    assert synth_brief.exists()
    text = synth_brief.read_text(encoding="utf-8")
    assert "first_screen" in text
    assert "c0" in text  # the fan claim_id is surfaced so synth can reference it
    status = nw.status_json(tmp_path)
    assert status["stage"] == "synth"
    assert str(synth_brief) in status["briefs"]


# ---- (f)+(g) REAL gate + renderer over an assembled claims bundle ----------

def _real_analysis():
    return [
        AnalysisResult(
            task_id="core_business_diagnosis",
            title="大盘",
            findings=[
                Finding(
                    title="GMV",
                    conclusion="大盘走弱",
                    evidence_strength=EvidenceStrength.STRONG,
                    key_numbers={"gmv": 120000},
                )
            ],
        )
    ]


def test_real_gate_passes_assembled_claims_bundle_and_renders_prose(tmp_path):
    # The gap-closer: NO monkeypatch. Real facts.json + a fan/synth claims bundle run
    # through the UNPATCHED gate & renderer, proving prose actually renders.
    analysis = _real_analysis()
    results = build_narrative_results(analysis)
    facts_json = json.loads(factbook_to_json(build_factbook(analysis)))
    proj = tmp_path / "proj"
    proj.mkdir()
    run_dir = tmp_path / "run"
    nw.prepare_run(run_dir, results=results, facts_json=facts_json,
                   report_name="叙事报告", project_root=proj)

    claim = {
        "claim_id": "c0",
        "section_id": "生意大盘",
        "claim_kind": "measurement",
        "sentence": "GMV 为 {t0}。",
        "number_tokens": [
            {"token_id": "t0", "fact_id": "core_business_diagnosis.gmv", "expected_metric_key": "gmv"}
        ],
        "entity_refs": [],
        "confidence": "强",
    }

    nw.advance_run(run_dir, project_root=proj)  # seed -> fan
    nw.ingest_output(run_dir, stage="fan",
                     text=json.dumps({"section_id": "生意大盘", "title": "生意大盘", "claims": [claim]},
                                     ensure_ascii=False))
    nw.advance_run(run_dir, project_root=proj)  # fan -> synth
    nw.ingest_output(run_dir, stage="synth",
                     text=json.dumps({
                         "headline": "大盘承压",
                         "first_screen": {"spine": [claim], "panel": [], "actions": ["复盘选品结构"]},
                         "cannot_say": ["暂无法把订单归因到具体笔记"],
                     }, ensure_ascii=False))
    nw.advance_run(run_dir, project_root=proj)  # synth -> gate (REAL) -> continuity
    state = nw.advance_run(run_dir, project_root=proj)  # continuity -> finalized

    assert state["stage"] == "finalized", "the real gate must PASS the assembled claims bundle"
    md = (outputs_dir(proj) / "叙事报告.md").read_text(encoding="utf-8")
    # the number is filled by Python from the FactBook (never invented by the agent)
    assert "¥12.0万" in md
    # the claim sentence renders as real merchant prose — NOT empty (the body-model drop)
    assert "GMV 为 ¥12.0万" in md
    # first-screen headline rendered too
    assert "大盘承压" in md
    assert "确定性骨架版" not in md  # narrative path, not skeleton fallback
