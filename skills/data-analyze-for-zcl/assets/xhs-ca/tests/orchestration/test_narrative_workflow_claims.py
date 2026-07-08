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


# ---- Gap C: fan brief exposes the table/column catalog so source.table is authorable --
# Without a schema inventory the curation agent guesses source.table + columns blind and
# the gate drops every view → the section silently degrades to prose-only. The brief must
# hand the agent the real table NAMES + COLUMN names (never values/rows — the brief stays
# number-free by design) so it can reference a real table.


def test_tables_catalog_lists_columns_by_table_names_only():
    catalog = nw._tables_catalog({
        "growth_bridge": [
            {"component": "转化", "delta_gmv": 34567},
            {"component": "流量", "delta_gmv": 8000, "note": "x"},  # 'note' is new in a later row
        ],
        "empty": [],          # no rows → dropped (nothing authorable)
        "": [{"a": 1}],        # blank table name → dropped
    })
    # names + first-seen column order, deterministic, NO values
    assert catalog["growth_bridge"] == ["component", "delta_gmv", "note"]
    assert "empty" not in catalog
    assert "" not in catalog
    assert "34567" not in str(catalog)  # values never enter the catalog


def test_tables_catalog_never_raises_on_garbage():
    assert nw._tables_catalog(None) == {}
    assert nw._tables_catalog("nope") == {}
    assert nw._tables_catalog({"t": "not-rows"}) == {}
    assert nw._tables_catalog({"t": ["not-a-dict", 42]}) == {}


def test_fan_brief_exposes_available_table_names_and_columns(tmp_path):
    results = {
        "domain_slices": [_slice_with_fact()],
        "result_tables": {"growth_bridge": [{"component": "转化", "delta_gmv": 34567}]},
    }
    facts_json = {"facts_hash": "h", "facts": {}}
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")
    brief = (tmp_path / "briefs" / "fan_00_生意大盘.md").read_text(encoding="utf-8")
    assert "available_tables" in brief             # the catalog key the agent consumes
    assert "growth_bridge" in brief                # a real table name it may reference
    assert "component" in brief and "delta_gmv" in brief  # its real columns
    assert "34567" not in brief                    # NAMES ONLY — no row value leaks in


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


# ---- never-block: gate-failing curated views drop, report never skeletons ----
# Design (§"any malformed spec, missing table, or unresolved review drops that single
# view; the report still delivers exactly two artifacts. A section with zero passing
# views degrades to prose-only"): a gate view-failure must DROP that view before the
# next patch round, never re-render the identical failing bundle until exhaustion →
# skeleton. Claim-level failures carry no view to drop and keep the exhaust→skeleton
# path (never-block is view-specific).


def test_drop_gate_failed_views_removes_labeled_view():
    # A per-view failure (VIEW_SPEC_INVALID) is keyed by the gate's view label; the
    # matching view drops, its healthy sibling stays.
    state = {"sections": {
        "生意大盘": {"section_id": "生意大盘", "curated_views": [
            {"view_id": "v_bad", "template": "comparison_table"},
            {"view_id": "v_ok", "template": "comparison_table"},
        ]},
    }}
    hard = [{"code": "VIEW_SPEC_INVALID", "claim_id": "v_bad", "detail": "x"}]
    assert nw._drop_gate_failed_views(state, hard) is True
    assert [v["view_id"] for v in state["sections"]["生意大盘"]["curated_views"]] == ["v_ok"]


def test_drop_gate_failed_views_uses_positional_label_when_no_view_id():
    # A view with no view_id is labeled `{section_id}:curated_view[{idx}]` by the gate;
    # the drop must map that positional label back to the right view.
    state = {"sections": {
        "s1": {"section_id": "s1", "curated_views": [
            {"template": "comparison_table"},   # idx 0 -> "s1:curated_view[0]" -> drop
            {"template": "ranking_table"},       # idx 1 -> kept
        ]},
    }}
    hard = [{"code": "VIEW_VALUE_MISMATCH", "claim_id": "s1:curated_view[0]", "detail": "x"}]
    assert nw._drop_gate_failed_views(state, hard) is True
    kept = state["sections"]["s1"]["curated_views"]
    assert len(kept) == 1 and kept[0]["template"] == "ranking_table"


def test_drop_gate_failed_views_trims_overcap_section():
    # An over-capped section (>2 tables) hard-fails VIEW_OVERCAP keyed by section_id;
    # trim to the per-domain cap (≤2 tables + ≤1 chart) so a re-gate stops failing.
    state = {"sections": {"s1": {"section_id": "s1", "curated_views": [
        {"view_id": "t1", "template": "comparison_table"},
        {"view_id": "t2", "template": "ranking_table"},
        {"view_id": "t3", "template": "comparison_table"},  # 3rd table -> over cap
        {"view_id": "c1", "template": "trend_line"},          # 1 chart is within cap
    ]}}}
    hard = [{"code": "VIEW_OVERCAP", "claim_id": "s1", "detail": "x"}]
    assert nw._drop_gate_failed_views(state, hard) is True
    kept = [v["view_id"] for v in state["sections"]["s1"]["curated_views"]]
    assert kept == ["t1", "t2", "c1"]  # first two tables + the one chart; surplus table dropped


def test_trim_views_to_cap_counts_alias_only_views():
    # Alias-only views (view_type/type/chart_type, no "template" key) must be
    # normalized via _template_of so the overcap trim actually counts + trims them.
    # Reading the raw "template" key left them uncounted → the section never shrank,
    # re-failed VIEW_OVERCAP every round, and routed the narrative to the skeleton.
    views = [
        {"view_id": "t1", "view_type": "table"},
        {"view_id": "t2", "type": "comparison_table"},
        {"view_id": "t3", "view_type": "table"},        # 3rd table -> over the ≤2 cap
        {"view_id": "c1", "chart_type": "trend_line"},   # 1 chart is within cap
    ]
    kept = [v["view_id"] for v in nw._trim_views_to_cap(views)]
    assert kept == ["t1", "t2", "c1"]  # surplus alias-only table dropped, chart kept


def test_drop_gate_failed_views_noop_on_claim_level_failures():
    # Claim-level failures (INVENTED_ENTITY / MISSING_FACT …) are NOT view failures —
    # nothing drops, so they legitimately keep the exhaust→skeleton path.
    state = {"sections": {"s1": {"section_id": "s1", "curated_views": [{"view_id": "v"}]}}}
    hard = [{"code": "INVENTED_ENTITY", "claim_id": "c0", "detail": "x"}]
    assert nw._drop_gate_failed_views(state, hard) is False
    assert len(state["sections"]["s1"]["curated_views"]) == 1


def test_drop_gate_failed_views_never_raises_on_garbage():
    assert nw._drop_gate_failed_views({}, None) is False
    assert nw._drop_gate_failed_views({"sections": None}, [{"code": "VIEW_SPEC_INVALID", "claim_id": "x"}]) is False
    assert nw._drop_gate_failed_views({"sections": {"s": "not-a-dict"}}, ["garbage", 42]) is False
    # a TRUTHY non-dict `sections` (list/str) must not blow up .items() — the never-raise
    # contract covers malformed state, not just the falsy/None case.
    hard = [{"code": "VIEW_SPEC_INVALID", "claim_id": "x"}]
    assert nw._drop_gate_failed_views({"sections": ["not-a-dict"]}, hard) is False
    assert nw._drop_gate_failed_views({"sections": "garbage"}, hard) is False


def _analysis_with_table():
    # Like _real_analysis but carries a real result.tables so build_narrative_results
    # populates result_tables → the gate actually polices curated views (a bad view can
    # then fail and be dropped, instead of the tables-empty prose-only short-circuit).
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
            tables={"growth_bridge": [
                {"component": "转化", "delta_gmv": 12000},
                {"component": "流量", "delta_gmv": 8000},
            ]},
        )
    ]


def test_gate_failed_view_drops_and_report_finalizes_not_skeleton(tmp_path):
    # End-to-end never-block: a curated view referencing a ghost table hard-fails the
    # REAL gate (VIEW_SPEC_INVALID). The controller must DROP that view and finalize
    # the narrative — NOT re-render the identical failing bundle every round until
    # gate exhaustion routes to the 确定性骨架版 skeleton.
    analysis = _analysis_with_table()
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
    bad_view = {
        "view_id": "core.ghost",
        "section_id": "生意大盘",
        "supports_claim": "c0",
        "template": "comparison_table",
        "source": {"task_id": "core_business_diagnosis", "table": "ghost_table"},  # not in result.tables
        "columns": ["component"],
        "title": "幽灵视图",
        "how_to_read": "无",
        "why_it_matters": "无",
    }

    nw.advance_run(run_dir, project_root=proj)  # seed -> fan
    nw.ingest_output(run_dir, stage="fan",
                     text=json.dumps({"section_id": "生意大盘", "title": "生意大盘",
                                      "claims": [claim], "curated_views": [bad_view]},
                                     ensure_ascii=False))
    nw.advance_run(run_dir, project_root=proj)  # fan -> synth
    nw.ingest_output(run_dir, stage="synth",
                     text=json.dumps({
                         "headline": "大盘承压",
                         "first_screen": {"spine": [claim], "panel": [], "actions": ["复盘选品结构"]},
                         "cannot_say": ["暂无法把订单归因到具体笔记"],
                     }, ensure_ascii=False))

    # Drive the controller to a terminal stage — robust to the exact number of internal
    # gate/patch/continuity transitions (the drop adds one patch round vs the clean path).
    state = nw._load_state(run_dir)
    for _ in range(8):
        state = nw.advance_run(run_dir, project_root=proj)
        if state["stage"] in ("finalized", "blocked"):
            break

    assert state["stage"] == "finalized", "never-block: the bad view drops, the report finalizes"
    md = (outputs_dir(proj) / "叙事报告.md").read_text(encoding="utf-8")
    assert "确定性骨架版" not in md          # narrative path, NOT the exhaustion skeleton
    assert "GMV 为 ¥12.0万" in md            # the healthy claim still renders as prose
    assert "幽灵视图" not in md              # the dropped view left no trace in the output
