"""Tests for the passive multi-reviewer `review` stage of the narrative workflow.

Covers the PURE vote-tally precedence, the per-view patch-round bounding, and the
prepare/status/ingest/advance wiring that routes each curated view to keep / drop /
patch after the deterministic gate has already locked every displayed number.
"""
import json

import pytest

from xhs_ceramics_analytics.orchestration import narrative_workflow as nw
from xhs_ceramics_analytics.paths import outputs_dir

# --- shared fixtures -------------------------------------------------------

_VALID_VIEW = {
    "view_id": "core.bridge",
    "section_id": "生意大盘",
    "supports_claim": "c1",
    "template": "comparison_table",
    "source": {"task_id": "core_business_diagnosis", "table": "growth_bridge"},
    "columns": ["component", "delta_gmv"],
    "column_labels": {"component": "来源", "delta_gmv": "拉动"},
    "title": "增长拆解 🍵",
    "how_to_read": "看谁在拉动",
    "why_it_matters": "锁定重点",
}
_TABLES = {
    "growth_bridge": [
        {"component": "转化", "delta_gmv": 123},
        {"component": "拉新", "delta_gmv": 45},
    ]
}


def _section(*, curated_views):
    section = {"section_id": "生意大盘", "title": "生意大盘", "body": "b"}
    if curated_views is not None:
        section["curated_views"] = curated_views
    return section


def _bundle_with_view():
    return {
        "headline": "本周平稳",
        "sections": [
            {
                "section_id": "生意大盘",
                "title": "生意大盘",
                "claims": [
                    {"claim_id": "c1", "sentence": "s", "rendered_sentence": "GMV 平稳", "confidence": "中"}
                ],
                "curated_views": [dict(_VALID_VIEW)],
            }
        ],
    }


def _prepare(tmp_path, *, result_tables=None):
    results = {
        "domain_slices": [
            {"title": "生意大盘", "facts": [{"metric": "GMV", "value": 100}], "reading": {"conclusion": "平稳"}}
        ]
    }
    if result_tables is not None:
        results["result_tables"] = result_tables
    facts_json = {"facts_hash": "h", "numbers": {}, "facts": {}}
    nw.prepare_run(
        tmp_path, results=results, facts_json=facts_json, report_name="叙事报告", project_root=tmp_path
    )


def _echo_gate(monkeypatch):
    """Monkeypatch run_gate to PASS and echo its input bundle back — exactly like the
    real gate (which returns a capped COPY of the bundle it was handed), so review
    edits (drops) persist through later gate re-checks instead of being resurrected."""
    def fake(bundle, *args, **kwargs):
        return type("_Pass", (), {"status": "PASS", "hard_failures": [], "bundle": bundle})()

    monkeypatch.setattr(nw, "run_gate", fake)


def _drive_to_synth(tmp_path, synth_section):
    """seed → fan → synth, ingesting `synth_section` (which may carry curated_views)
    as the synthesized bundle. Leaves the run AT the synth stage (not yet gated)."""
    nw.ingest_output(tmp_path, stage="seed",
                     text='{"sections":[{"section_id":"生意大盘","title":"生意大盘","body":"b"}]}')
    nw.advance_run(tmp_path)  # fan
    nw.ingest_output(tmp_path, stage="fan", text='{"section_id":"生意大盘","title":"生意大盘","body":"b"}')
    nw.advance_run(tmp_path)  # synth
    nw.ingest_output(tmp_path, stage="synth",
                     text=json.dumps({"sections": [synth_section]}, ensure_ascii=False))


def _ingest_review(tmp_path, verdict_by_lens, *, view_id="core.bridge", section_id="生意大盘"):
    for lens, verdict in verdict_by_lens.items():
        payload = {"section_id": section_id, "lens": lens,
                   "verdicts": [{"view_id": view_id, "verdict": verdict, "reason": f"{lens}理由"}]}
        nw.ingest_output(tmp_path, stage="review", text=json.dumps(payload, ensure_ascii=False))


# --- tally_votes: pure strict-precedence table -----------------------------


@pytest.mark.parametrize(
    "verdicts,expected",
    [
        (["drop", "drop"], "drop"),                # 2 drop -> drop
        (["drop", "drop", "keep"], "drop"),         # drop>=2 wins over a keep
        (["keep", "keep", "drop"], "keep"),         # 2 keep + 1 drop -> keep
        (["keep", "keep", "revise"], "keep"),       # 2 keep + 1 revise -> keep
        (["keep", "revise", "drop"], "patch"),      # no majority -> patch
        (["revise", "revise", "keep"], "patch"),    # 2 revise + 1 keep -> patch
        (["revise", "revise", "revise"], "patch"),  # all revise -> patch
        ([], "patch"),                              # empty -> safe default (patch)
    ],
)
def test_tally_votes_precedence(verdicts, expected):
    assert nw.tally_votes(verdicts) == expected


def test_tally_votes_is_case_and_whitespace_insensitive():
    assert nw.tally_votes(["DROP", " Drop "]) == "drop"
    assert nw.tally_votes([" keep ", "KEEP"]) == "keep"


def test_tally_votes_never_raises_on_garbage():
    for bad in [None, "drop", 123, [1, 2, 3], ["???", "", None], [{"verdict": "drop"}]]:
        assert nw.tally_votes(bad) in {"keep", "drop", "patch"}


# --- _view_action: patch-round bounding + degradation ----------------------


def test_view_action_patch_within_budget():
    assert nw._view_action(["keep", "revise", "drop"], patch_rounds=0) == "patch"
    assert nw._view_action(["keep", "revise", "drop"], patch_rounds=1) == "patch"


def test_view_action_patch_exhausted_becomes_drop():
    assert nw._view_action(
        ["keep", "revise", "drop"], patch_rounds=nw.MAX_REVIEW_PATCH_ROUNDS
    ) == "drop"


def test_view_action_missing_or_garbled_input_degrades_to_drop():
    assert nw._view_action([], patch_rounds=0) == "drop"
    assert nw._view_action(None, patch_rounds=0) == "drop"
    assert nw._view_action(["???", ""], patch_rounds=0) == "drop"


def test_view_action_keep_and_drop_pass_through():
    assert nw._view_action(["keep", "keep"], patch_rounds=0) == "keep"
    assert nw._view_action(["drop", "drop"], patch_rounds=0) == "drop"


# --- calibrated reject bias: only 支撑's drop forces removal at exhaustion --
# The narrative was going thin because ANY unconverged view was dropped once the
# patch budget ran out — value/readability quibbles (keep+revise, no drop) killed
# otherwise-valuable visuals. Calibrated: at exhaustion a view is dropped ONLY if a
# reviewer actually voted to remove it (支撑 is the one drop-capable lens); a view no
# one voted to drop is KEPT rather than starve the narrative.


def test_view_action_unconverged_without_drop_vote_is_kept():
    # keep + revise + revise never reaches a majority, but NO reviewer said drop →
    # at exhaustion it is kept (was previously dropped — the reject-bias bug).
    assert nw._view_action(
        ["keep", "revise", "revise"], patch_rounds=nw.MAX_REVIEW_PATCH_ROUNDS
    ) == "keep"
    # within budget it still routes to patch (a re-author may yet fix the quibbles)
    assert nw._view_action(["keep", "revise", "revise"], patch_rounds=0) == "patch"


def test_view_action_unconverged_with_drop_vote_still_drops():
    # a single drop vote (支撑 flagged it) + never converging → still dropped at
    # exhaustion: the trust/anti-dump anchor keeps its removal power.
    assert nw._view_action(
        ["keep", "revise", "drop"], patch_rounds=nw.MAX_REVIEW_PATCH_ROUNDS
    ) == "drop"


def test_review_lenses_encode_calibrated_intent():
    lenses = dict(nw._REVIEW_LENSES)
    assert set(lenses) == {"价值", "可读性", "支撑"}
    # 价值: value = business-meaningful insight; actionability is one form, not the bar;
    # the old "must let the merchant take an action" gate is gone, and unsure → keep.
    assert "可行动只是其中一种" in lenses["价值"]
    assert "拿不准就 keep" in lenses["价值"]
    assert "能让商家做出一个动作" not in lenses["价值"]
    # 可读性: fixable issues prefer revise over drop (so continuity can improve them)
    assert "优先判 revise 而非 drop" in lenses["可读性"]
    # 支撑: the one lens allowed to drop — the anti-dump / trust anchor
    assert "底线" in lenses["支撑"] and "允许 drop" in lenses["支撑"]
    # lenses stay ASCII-digit-free (the old 可读性 lens leaked a bare "5 秒")
    for _name, text in nw._REVIEW_LENSES:
        assert not any(ch.isdigit() for ch in text)


def test_review_lenses_flag_form_choice_and_raw_dumping():
    # D4: two editorial criteria made explicit at the enforcement point — 可读性 asks
    # whether the view uses the most-appropriate FORM (图 vs 表), and 支撑 (the one
    # drop-capable, anti-dump anchor) explicitly kills a raw-data dump. These target the
    # original complaints (ugly/meaningless per-day tables; raw-export dumping).
    lenses = dict(nw._REVIEW_LENSES)
    assert "最合适的呈现形式" in lenses["可读性"]
    assert "原始数据倾倒" in lenses["支撑"]
    # unchanged: still exactly three calibrated lenses, still ASCII-digit-free
    assert set(lenses) == {"价值", "可读性", "支撑"}
    for _name, text in nw._REVIEW_LENSES:
        assert not any(ch.isdigit() for ch in text)


# --- finalize carries retained curated views -------------------------------


def test_finalize_narrative_carries_retained_curated_views(tmp_path):
    _prepare(tmp_path, result_tables=_TABLES)
    state = nw._load_state(tmp_path)
    state["_bundle"] = _bundle_with_view()
    nw._write_state(tmp_path, state)

    finalized = nw.finalize_narrative(tmp_path, project_root=tmp_path)
    assert finalized["stage"] == "finalized"

    md = (outputs_dir(tmp_path) / "20260101-000000-叙事报告" / "叙事报告.md").read_text(encoding="utf-8")
    # deterministic engine filled the REAL cells from result_tables
    assert "转化" in md and "123" in md
    assert "拉新" in md and "45" in md
    # agent-authored caption + emoji survive verbatim
    assert "增长拆解 🍵" in md
    # provenance stamp locates the source table in the audit trail — de-leaked:
    # named by the table's human label, no internal task_id
    assert "来源:growth bridge" in md
    assert "core_business_diagnosis" not in md
    # both artifacts land
    assert (outputs_dir(tmp_path) / "20260101-000000-叙事报告" / "叙事报告.html").exists()


# --- empty views section finalizes fine (no review, prose-only) ------------


def test_empty_curated_views_skips_review_and_finalizes(tmp_path, monkeypatch):
    _prepare(tmp_path)  # no result_tables
    _echo_gate(monkeypatch)
    _drive_to_synth(tmp_path, _section(curated_views=[]))
    state = nw.advance_run(tmp_path)  # gate PASS -> continuity (no curated views to review)
    assert state["stage"] == "continuity"
    state = nw.advance_run(tmp_path)  # continuity PASS -> finalized
    assert state["stage"] == "finalized"
    assert (outputs_dir(tmp_path) / "20260101-000000-叙事报告" / "叙事报告.md").exists()


# --- review stage: keep / drop / patch routing -----------------------------


def test_gate_pass_with_views_enters_review_and_lists_briefs(tmp_path, monkeypatch):
    _prepare(tmp_path, result_tables=_TABLES)
    _echo_gate(monkeypatch)
    _drive_to_synth(tmp_path, _section(curated_views=[dict(_VALID_VIEW)]))
    state = nw.advance_run(tmp_path)  # gate PASS -> review (curated views present)
    assert state["stage"] == "review"
    status = nw.status_json(tmp_path)
    assert status["stage"] == "review"
    assert len(status["briefs"]) == 3  # three lenses per domain


def test_review_keep_retains_and_renders_view(tmp_path, monkeypatch):
    _prepare(tmp_path, result_tables=_TABLES)
    _echo_gate(monkeypatch)
    _drive_to_synth(tmp_path, _section(curated_views=[dict(_VALID_VIEW)]))
    nw.advance_run(tmp_path)  # -> review
    _ingest_review(tmp_path, {"价值": "keep", "可读性": "keep", "支撑": "keep"})
    state = nw.advance_run(tmp_path)  # review resolves keep -> continuity
    assert state["stage"] == "continuity"
    assert state["_bundle"]["sections"][0]["curated_views"]  # retained
    state = nw.advance_run(tmp_path)  # -> finalized
    assert state["stage"] == "finalized"
    md = (outputs_dir(tmp_path) / "20260101-000000-叙事报告" / "叙事报告.md").read_text(encoding="utf-8")
    assert "转化" in md and "123" in md


def test_review_two_drops_removes_view(tmp_path, monkeypatch):
    _prepare(tmp_path, result_tables=_TABLES)
    _echo_gate(monkeypatch)
    _drive_to_synth(tmp_path, _section(curated_views=[dict(_VALID_VIEW)]))
    nw.advance_run(tmp_path)  # -> review
    _ingest_review(tmp_path, {"价值": "drop", "可读性": "drop", "支撑": "keep"})
    state = nw.advance_run(tmp_path)  # 2 drop -> view removed -> continuity
    assert state["stage"] == "continuity"
    assert state["_bundle"]["sections"][0]["curated_views"] == []
    state = nw.advance_run(tmp_path)  # -> finalized
    md = (outputs_dir(tmp_path) / "20260101-000000-叙事报告" / "叙事报告.md").read_text(encoding="utf-8")
    assert "123" not in md  # dropped view's numbers never rendered


def test_review_missing_verdicts_drops_view_and_finalizes(tmp_path, monkeypatch):
    _prepare(tmp_path, result_tables=_TABLES)
    _echo_gate(monkeypatch)
    _drive_to_synth(tmp_path, _section(curated_views=[dict(_VALID_VIEW)]))
    state = nw.advance_run(tmp_path)  # -> review
    assert state["stage"] == "review"
    # reviewers never returned anything: advance must degrade, not raise
    state = nw.advance_run(tmp_path)  # no verdicts -> drop view -> continuity
    assert state["stage"] == "continuity"
    assert state["_bundle"]["sections"][0]["curated_views"] == []
    state = nw.advance_run(tmp_path)  # -> finalized (report still delivers)
    assert state["stage"] == "finalized"


def test_review_no_majority_routes_to_patch(tmp_path, monkeypatch):
    _prepare(tmp_path, result_tables=_TABLES)
    _echo_gate(monkeypatch)
    _drive_to_synth(tmp_path, _section(curated_views=[dict(_VALID_VIEW)]))
    nw.advance_run(tmp_path)  # -> review
    _ingest_review(tmp_path, {"价值": "keep", "可读性": "revise", "支撑": "drop"})
    state = nw.advance_run(tmp_path)  # no majority -> patch
    assert state["stage"] == "patch"
    assert state["_review_patch_rounds"] == 1
    # the review-patch brief is surfaced to the host
    status = nw.status_json(tmp_path)
    assert any("review_patch.md" in b for b in status["briefs"])


# --- brief writers normalize alias-only templates --------------------------
# An alias-only curated view (view_type/type/chart_type, no "template" key) is a
# valid table/chart that passed the gate. The reviewer + patch briefs must show its
# NORMALIZED template, not template="" — a blank misrepresents the view kind to the
# reviewer/patch agents and, with the reject-bias calibration, can misfire a drop.


def _alias_only_view():
    return {
        "view_id": "v1", "section_id": "生意大盘", "view_type": "table",
        "title": "增长拆解 🍵", "columns": ["component"], "supports_claim": "c1",
    }


def _alias_only_bundle():
    return {"sections": [{"section_id": "生意大盘", "title": "生意大盘",
                          "curated_views": [_alias_only_view()]}]}


def test_review_briefs_show_normalized_template_for_alias_only_view(tmp_path):
    nw._write_review_briefs(tmp_path, _alias_only_bundle())
    texts = [b.read_text(encoding="utf-8") for b in (tmp_path / "briefs").glob("review_*.md")]
    assert texts  # a brief per lens was written
    assert any('"template": "comparison_table"' in t for t in texts)
    assert all('"template": ""' not in t for t in texts)  # never the blank misrepresentation


def test_review_patch_brief_shows_normalized_template_for_alias_only_view(tmp_path):
    view = _alias_only_view()
    key = nw._view_key("生意大盘", view, 0)
    nw._write_review_patch_brief(tmp_path, _alias_only_bundle(), {key}, {key: ["理由"]})
    brief = (tmp_path / "briefs" / "review_patch.md").read_text(encoding="utf-8")
    assert '"template": "comparison_table"' in brief
    assert '"template": ""' not in brief


def test_review_patch_eventually_drops_when_never_converges(tmp_path, monkeypatch):
    """A view that keeps failing to reach a majority is dropped after the patch
    budget is spent — it never blocks the report from finalizing."""
    _prepare(tmp_path, result_tables=_TABLES)
    _echo_gate(monkeypatch)
    _drive_to_synth(tmp_path, _section(curated_views=[dict(_VALID_VIEW)]))
    state = nw.advance_run(tmp_path)  # -> review
    assert state["stage"] == "review"

    for _ in range(12):
        if state["stage"] == "review":
            _ingest_review(tmp_path, {"价值": "keep", "可读性": "revise", "支撑": "drop"})
        state = nw.advance_run(tmp_path)
        if state["stage"] in {"continuity", "finalized", "blocked"}:
            break

    # never raises; converges to a terminal-ish stage with the view dropped
    assert state["stage"] in {"continuity", "finalized", "blocked"}
    if state["stage"] == "continuity":
        assert state["_bundle"]["sections"][0]["curated_views"] == []
