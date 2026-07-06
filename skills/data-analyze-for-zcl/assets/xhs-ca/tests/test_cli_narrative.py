import json

from typer.testing import CliRunner

from xhs_ceramics_analytics.cli import app

runner = CliRunner()


def _facts_file(tmp_path):
    facts = {
        "facts_hash": "h",
        "facts": {"m.jun": {"rendered": "¥8.7", "metric_key": "pvg", "direction": "down",
                            "pool_id": None, "entity_type": None, "evidence_strength": "strong",
                            "descriptive_reliability": "high", "assumption": None}},
        "entity_registry": [], "absent_link_registry": [], "non_additive_ledger": {},
    }
    p = tmp_path / "facts.json"
    p.write_text(json.dumps(facts), encoding="utf-8")
    return p


def _bundle_file(tmp_path):
    claim = {"claim_id": "c0", "section_id": "core_business", "claim_kind": "measurement",
             "sentence": "人均产出 {t0}。", "number_tokens": [
                 {"token_id": "t0", "fact_id": "m.jun", "expected_metric_key": "pvg",
                  "direction": "down"}],
             "entity_refs": [], "confidence": "强", "causal_link": None}
    bundle = {"facts_hash": "h", "headline": "人均产出走低。",
              "first_screen": {"spine": [], "panel": [], "actions": []},
              "spine_final": {"backbone": [{"link_id": "L1", "from": "t", "to": "g",
                                            "anchor_fact_ids": ["m.jun"],
                                            "relation": "accounting_identity"}]},
              "sections": [{"section_id": "core_business", "title": "大盘", "claims": [claim],
                            "table_ref": None, "chart_ref": None, "spine_callbacks": ["L1"]}],
              "cannot_say": []}
    p = tmp_path / "bundle.json"
    p.write_text(json.dumps(bundle), encoding="utf-8")
    return p


def test_gate_command_passes_clean_bundle(tmp_path):
    out = tmp_path / "gate.json"
    result = runner.invoke(app, ["gate", str(_bundle_file(tmp_path)), str(_facts_file(tmp_path)),
                                 "--out", str(out)])
    assert result.exit_code == 0
    assert json.loads(out.read_text())["status"] == "PASS"


def test_render_draft_command_fills_tokens(tmp_path):
    out = tmp_path / "draft.md"
    result = runner.invoke(app, ["render-draft", str(_bundle_file(tmp_path)),
                                 str(_facts_file(tmp_path)), "--out", str(out)])
    assert result.exit_code == 0
    assert "人均产出 ¥8.7。" in out.read_text()


def test_render_draft_default_target_is_state_dir_not_outputs(tmp_path, monkeypatch):
    # draft.md is a cache checkpoint, not a deliverable — outputs/ stays a pure md+html surface.
    monkeypatch.setenv("XHS_CA_PROJECT_ROOT", str(tmp_path))
    result = runner.invoke(app, ["render-draft", str(_bundle_file(tmp_path)),
                                 str(_facts_file(tmp_path))])
    assert result.exit_code == 0, result.output
    state = tmp_path / ".xhs-ceramics-analytics"
    assert (state / "draft.md").exists()
    assert not (state / "outputs" / "draft.md").exists()


def test_finalize_default_target_is_state_dir_not_outputs(tmp_path, monkeypatch):
    # frozen_narrative.json is a cache checkpoint, not a deliverable.
    monkeypatch.setenv("XHS_CA_PROJECT_ROOT", str(tmp_path))
    result = runner.invoke(app, ["finalize", str(_bundle_file(tmp_path)),
                                 str(_facts_file(tmp_path))])
    assert result.exit_code == 0, result.output
    state = tmp_path / ".xhs-ceramics-analytics"
    assert (state / "frozen_narrative.json").exists()
    assert not (state / "outputs" / "frozen_narrative.json").exists()


def test_finalize_then_render_frozen(tmp_path):
    frozen = tmp_path / "frozen.json"
    r1 = runner.invoke(app, ["finalize", str(_bundle_file(tmp_path)), str(_facts_file(tmp_path)),
                             "--out", str(frozen)])
    assert r1.exit_code == 0, r1.output
    r2 = runner.invoke(app, ["render-frozen", str(frozen), str(_facts_file(tmp_path)),
                             "--name", str(tmp_path / "report")])
    assert r2.exit_code == 0, r2.output
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "report.html").exists()
    assert "人均产出 ¥8.7。" in (tmp_path / "report.md").read_text()
