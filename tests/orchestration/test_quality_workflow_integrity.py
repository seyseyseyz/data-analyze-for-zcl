import json
from pathlib import Path

import pytest

from xhs_ceramics_analytics.orchestration import narrative_workflow as nw


def _slice(title: str) -> dict:
    return {
        "title": title,
        "facts": [{"fact_id": f"{title}.gmv", "metric": "GMV", "value": 100}],
        "reading": {"conclusion": "平稳"},
    }


def _prepare(tmp_path, *, slices=None) -> None:
    nw.prepare_run(
        tmp_path,
        results={"domain_slices": slices or [_slice("生意大盘")]},
        facts_json={"facts_hash": "h", "facts": {}},
        report_name="报告",
        project_root=tmp_path,
    )


def test_advance_refuses_when_current_stage_has_pending_briefs(tmp_path):
    _prepare(tmp_path)

    with pytest.raises(ValueError, match="pending briefs"):
        nw.advance_run(tmp_path)


def test_status_lists_only_pending_fan_briefs(tmp_path):
    _prepare(tmp_path, slices=[_slice("生意大盘"), _slice("商品结构")])
    nw.ingest_output(
        tmp_path,
        stage="seed",
        text='{"sections":[{"section_id":"生意大盘","title":"生意大盘","body":"b"}]}',
    )
    nw.advance_run(tmp_path)

    status = nw.status_json(tmp_path)
    assert len(status["briefs"]) == 2

    first = status["briefs"][0]
    nw.ingest_output(
        tmp_path,
        stage="fan",
        source=first,
        text='{"section_id":"生意大盘","title":"生意大盘","body":"b"}',
    )

    status = nw.status_json(tmp_path)
    assert status["briefs"] == [status["tasks"]["pending"][0]["brief"]]
    assert len(status["tasks"]["completed"]) == 1


def test_task_id_cannot_submit_another_section_or_replay(tmp_path):
    _prepare(tmp_path, slices=[_slice("生意大盘"), _slice("商品结构")])
    nw.ingest_output(
        tmp_path,
        stage="seed",
        text='{"sections":[{"section_id":"生意大盘","title":"生意大盘","body":"b"}]}',
    )
    nw.advance_run(tmp_path)
    first, second = nw.status_json(tmp_path)["tasks"]["pending"]

    with pytest.raises(ValueError, match="pending task"):
        nw.ingest_output(
            tmp_path,
            stage="fan",
            task_id=first["task_id"],
            text=json.dumps(
                {
                    "section_id": second["section_id"],
                    "title": second["section_id"],
                    "body": "错绑",
                },
                ensure_ascii=False,
            ),
        )

    payload = {
        "section_id": first["section_id"],
        "title": first["section_id"],
        "body": "正确",
    }
    nw.ingest_output(
        tmp_path,
        stage="fan",
        task_id=first["task_id"],
        text=json.dumps(payload, ensure_ascii=False),
    )
    with pytest.raises(ValueError, match="pending task"):
        nw.ingest_output(
            tmp_path,
            stage="fan",
            task_id=first["task_id"],
            text=json.dumps(payload, ensure_ascii=False),
        )


def test_review_ingest_is_idempotent_per_section_and_lens(tmp_path):
    _prepare(tmp_path)
    state = nw._load_state(tmp_path)
    state["stage"] = "review"
    state["_bundle"] = {
        "sections": [
            {
                "section_id": "生意大盘",
                "title": "生意大盘",
                "curated_views": [{"view_id": "v1", "template": "comparison_table"}],
            }
        ]
    }
    nw._write_review_briefs(tmp_path, state["_bundle"], state=state)
    nw._write_state(tmp_path, state)
    payload = {
        "section_id": "生意大盘",
        "lens": "价值",
        "verdicts": [{"view_id": "v1", "verdict": "keep", "reason": "有用"}],
    }

    nw.ingest_output(tmp_path, stage="review", text=json.dumps(payload, ensure_ascii=False))
    nw.ingest_output(tmp_path, stage="review", text=json.dumps(payload, ensure_ascii=False))

    state = nw._load_state(tmp_path)
    key = nw._view_key("生意大盘", {"view_id": "v1"}, 0)
    assert list(state["_reviews"][key]) == ["价值"]
    assert state["_reviews"][key]["价值"]["verdict"] == "keep"


def test_review_task_stays_pending_until_every_view_has_a_valid_verdict(tmp_path):
    _prepare(tmp_path)
    state = nw._load_state(tmp_path)
    state["stage"] = "review"
    state["_bundle"] = {
        "sections": [
            {
                "section_id": "生意大盘",
                "curated_views": [{"view_id": "v1"}, {"view_id": "v2"}],
            }
        ]
    }
    nw._write_review_briefs(tmp_path, state["_bundle"], state=state)
    nw._write_state(tmp_path, state)

    nw.ingest_output(
        tmp_path,
        stage="review",
        text=json.dumps(
            {
                "section_id": "生意大盘",
                "lens": "价值",
                "verdicts": [
                    {"view_id": "v1", "verdict": "keep"},
                    {"view_id": "v2", "verdict": "unknown"},
                ],
            },
            ensure_ascii=False,
        ),
    )

    status = nw.status_json(tmp_path)
    value_task = next(task for task in status["tasks"]["pending"] if task["lens"] == "价值")
    assert value_task["status"] == "pending"


def test_view_identity_is_namespaced_by_section():
    view = {"view_id": "shared"}
    assert nw._view_key("生意大盘", view, 0) != nw._view_key("商品结构", view, 0)


def test_continuity_ingest_records_edits_instead_of_sections(tmp_path):
    _prepare(tmp_path)
    state = nw._load_state(tmp_path)
    state["stage"] = "continuity"
    state["sections"] = {}
    nw._write_continuity_brief(tmp_path, state, {"sections": []})
    nw._write_state(tmp_path, state)
    edits = [{"claim_id": "c1", "old": "旧文案", "new": "新文案"}]

    nw.ingest_output(
        tmp_path,
        stage="continuity",
        text=json.dumps({"edits": edits}, ensure_ascii=False),
    )

    state = nw._load_state(tmp_path)
    assert state["_continuity_edits"] == edits
    assert state["sections"] == {}


def test_gate_patch_has_a_registered_pending_brief(tmp_path):
    _prepare(tmp_path)
    state = nw._load_state(tmp_path)
    state["stage"] = "patch"
    nw._write_gate_patch_brief(
        tmp_path,
        state,
        [{"code": "MAGNITUDE_UNBOUND", "claim_id": "c1"}],
    )
    nw._write_state(tmp_path, state)

    status = nw.status_json(tmp_path)
    assert status["briefs"] == [str(tmp_path / "briefs" / "patch.md")]
    assert status["tasks"]["pending"][0]["stage"] == "patch"
    with pytest.raises(ValueError, match="pending briefs"):
        nw.advance_run(tmp_path)


def test_finalize_narrative_fails_closed_when_html_rendering_fails(tmp_path, monkeypatch):
    _prepare(tmp_path)
    state = nw._load_state(tmp_path)
    state["_bundle"] = {"sections": []}
    nw._write_state(tmp_path, state)

    def fail_render(*_args, **_kwargs):
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr(nw, "render_markdown_document_html", fail_render)

    with pytest.raises(RuntimeError, match="renderer exploded"):
        nw.finalize_narrative(tmp_path, project_root=tmp_path)

    state = nw._load_state(tmp_path)
    assert state["stage"] == "delivery_failed"
    assert state["delivery_error"] == "renderer exploded"
    assert not state.get("artifacts", {}).get("html")


def test_finalize_narrative_marks_final_validation_failure_as_delivery_failed(
    tmp_path, monkeypatch
):
    _prepare(tmp_path)
    state = nw._load_state(tmp_path)
    state["_bundle"] = {"sections": []}
    nw._write_state(tmp_path, state)

    def fail_gate(*_args, **_kwargs):
        raise ValueError("final gate exploded")

    monkeypatch.setattr(nw, "_run_gate", fail_gate)

    with pytest.raises(ValueError, match="final gate exploded"):
        nw.finalize_narrative(tmp_path, project_root=tmp_path)

    state = nw._load_state(tmp_path)
    assert state["stage"] == "delivery_failed"
    assert state["delivery_status"] == "failed"
    assert state["error"]["code"] == "FINAL_VALIDATION_FAILED"
    assert state["history"][-1] == "delivery_failed:final_validation"
    assert not state.get("artifacts", {}).get("html")


def test_finalize_narrative_rebuilds_untrusted_rendered_sentence(tmp_path):
    _prepare(tmp_path)
    state = nw._load_state(tmp_path)
    state["_bundle"] = {
        "facts_hash": "h",
        "headline": "可信结论",
        "first_screen": {"spine": [], "panel": [], "actions": []},
        "spine_final": {"backbone": []},
        "sections": [
            {
                "section_id": "生意大盘",
                "title": "生意大盘",
                "claims": [
                    {
                        "claim_id": "c1",
                        "section_id": "生意大盘",
                        "claim_kind": "measurement",
                        "sentence": "可信结论。",
                        "rendered_sentence": "伪造结果 999 亿。",
                        "number_tokens": [],
                        "entity_refs": [],
                        "confidence": "中",
                        "causal_link": None,
                    }
                ],
                "spine_callbacks": [],
            }
        ],
        "cannot_say": [],
    }
    nw._write_state(tmp_path, state)

    finalized = nw.finalize_narrative(
        tmp_path,
        project_root=tmp_path,
        timestamp="20260802-120000",
    )
    markdown = Path(finalized["internal_artifacts"]["markdown"]).read_text(encoding="utf-8")

    assert "可信结论。" in markdown
    assert "伪造结果 999 亿" not in markdown


def test_finalize_uses_configured_project_root_when_state_omits_it(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    output_root = tmp_path / "configured-root"
    monkeypatch.setenv("XHS_CA_PROJECT_ROOT", str(output_root))
    nw.prepare_run(
        run_dir,
        results={"domain_slices": []},
        facts_json={"facts_hash": "h", "facts": {}},
        report_name="报告",
    )
    state = nw._load_state(run_dir)
    state["_bundle"] = {
        "facts_hash": "h",
        "first_screen": {"spine": [], "panel": [], "actions": []},
        "spine_final": {"backbone": []},
        "sections": [],
    }
    nw._write_state(run_dir, state)

    finalized = nw.finalize_narrative(
        run_dir,
        timestamp="20260802-120000",
    )

    assert str(finalized["artifacts"]["html"]).startswith(str(output_root))


def test_state_write_is_atomic_and_preserves_previous_state_on_replace_failure(
    tmp_path, monkeypatch
):
    original = {"stage": "seed", "marker": "original"}
    nw._write_state(tmp_path, original)

    def fail_replace(_self, _destination):
        raise RuntimeError("replace interrupted")

    monkeypatch.setattr(nw.Path, "replace", fail_replace)

    with pytest.raises(RuntimeError, match="replace interrupted"):
        nw._write_state(tmp_path, {"stage": "fan", "marker": "new"})

    assert nw._load_state(tmp_path) == original
    assert list(tmp_path.glob(".state.json.*.tmp")) == []


def test_finalize_deterministic_fails_closed_when_html_rendering_fails(
    tmp_path, monkeypatch
):
    _prepare(tmp_path)

    def fail_render(*_args, **_kwargs):
        raise RuntimeError("fallback renderer exploded")

    monkeypatch.setattr(nw, "render_markdown_document_html", fail_render)

    with pytest.raises(RuntimeError, match="fallback renderer exploded"):
        nw.finalize_deterministic(
            tmp_path,
            project_root=tmp_path,
            reason="gate_exhausted",
        )

    state = nw._load_state(tmp_path)
    assert state["stage"] == "delivery_failed"
    assert state["delivery_error"] == "fallback renderer exploded"
