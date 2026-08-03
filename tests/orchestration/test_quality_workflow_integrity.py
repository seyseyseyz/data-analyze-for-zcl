import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
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


def test_dispatch_ledger_handles_six_tasks_with_capacity_five_without_duplicates(tmp_path):
    _prepare(tmp_path)
    state = nw._load_state(tmp_path)
    state["stage"] = "fan"
    tasks = []
    for index in range(6):
        brief = tmp_path / "briefs" / f"fan_{index}.md"
        brief.write_text(f"task {index}", encoding="utf-8")
        tasks.append(
            {
                "brief": brief,
                "section_id": f"域{index}",
                "role": "domain_writer",
            }
        )
    nw._set_stage_tasks(state, "fan", tasks)
    nw._write_state(tmp_path, state)

    first_batch = nw.reserve_tasks(tmp_path, capacity=5)
    assert len(first_batch) == 5
    assert len({task["task_id"] for task in first_batch}) == 5
    assert nw.reserve_tasks(tmp_path, capacity=5) == []

    for index, task in enumerate(first_batch[:2]):
        nw.record_dispatch(
            tmp_path,
            task_id=task["task_id"],
            agent_id=f"agent-{index}",
            result_path=tmp_path / "results" / f"agent-{index}.json",
        )
    for task in first_batch[2:]:
        nw.release_task(tmp_path, task_id=task["task_id"])

    recovered = nw.reserve_tasks(tmp_path, capacity=5)
    assert [task["task_id"] for task in recovered] == [
        task["task_id"] for task in first_batch[2:]
    ]
    for index, task in enumerate(recovered, 2):
        nw.record_dispatch(
            tmp_path,
            task_id=task["task_id"],
            agent_id=f"agent-{index}",
            result_path=tmp_path / "results" / f"agent-{index}.json",
        )

    state = nw._load_state(tmp_path)
    completed_task = nw._stage_tasks(state, "fan")[0]
    nw._complete_task(state, completed_task)
    nw._write_state(tmp_path, state)
    nw.record_agent_state(
        tmp_path,
        task_id=completed_task["task_id"],
        status="closed",
    )

    final_batch = nw.reserve_tasks(tmp_path, capacity=5)
    assert len(final_batch) == 1
    all_task_ids = {
        *(task["task_id"] for task in first_batch),
        *(task["task_id"] for task in final_batch),
    }
    assert len(all_task_ids) == 6


def test_successful_agent_ingest_releases_capacity_for_next_task(tmp_path):
    _prepare(tmp_path)
    state = nw._load_state(tmp_path)
    tasks = []
    for index in range(2):
        brief = tmp_path / "briefs" / f"seed_{index}.md"
        brief.write_text(f"candidate {index}", encoding="utf-8")
        tasks.append({"brief": brief, "role": "spine_candidate"})
    nw._set_stage_tasks(state, "seed", tasks)
    nw._write_state(tmp_path, state)

    first = nw.reserve_tasks(tmp_path, capacity=1)[0]
    result_path = tmp_path / "results" / "first.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text('{"sections": []}', encoding="utf-8")
    nw.record_dispatch(
        tmp_path,
        task_id=first["task_id"],
        agent_id="agent-1",
        result_path=result_path,
    )
    nw.record_agent_state(tmp_path, task_id=first["task_id"], status="result_ready")

    ingested = nw.ingest_output(
        tmp_path,
        stage="seed",
        task_id=first["task_id"],
        source=result_path,
    )

    completed = nw._dispatch_task(ingested, first["task_id"])
    assert completed["status"] == "completed"
    assert completed["dispatch_status"] == "ingested"
    closed = nw.record_agent_state(
        tmp_path,
        task_id=first["task_id"],
        status="closed",
    )
    assert closed["dispatch_status"] == "ingested"
    second = nw.reserve_tasks(tmp_path, capacity=1)
    assert len(second) == 1
    assert second[0]["task_id"] != first["task_id"]


def test_dispatch_rejects_result_path_already_assigned_to_another_task(tmp_path):
    _prepare(tmp_path)
    state = nw._load_state(tmp_path)
    tasks = []
    for index in range(2):
        brief = tmp_path / "briefs" / f"seed_{index}.md"
        brief.write_text(f"candidate {index}", encoding="utf-8")
        tasks.append({"brief": brief, "role": "spine_candidate"})
    nw._set_stage_tasks(state, "seed", tasks)
    nw._write_state(tmp_path, state)
    first, second = nw.reserve_tasks(tmp_path, capacity=2)
    shared_path = tmp_path / "results" / "shared.json"

    nw.record_dispatch(
        tmp_path,
        task_id=first["task_id"],
        agent_id="agent-1",
        result_path=shared_path,
    )
    with pytest.raises(ValueError, match="result_path"):
        nw.record_dispatch(
            tmp_path,
            task_id=second["task_id"],
            agent_id="agent-2",
            result_path=shared_path.parent / "." / shared_path.name,
        )


@pytest.mark.parametrize("alias_kind", ["symlink", "hardlink"])
def test_agent_ingest_rejects_result_file_aliases_created_after_dispatch(
    tmp_path,
    alias_kind,
):
    _prepare(tmp_path)
    state = nw._load_state(tmp_path)
    tasks = []
    for index in range(2):
        brief = tmp_path / "briefs" / f"seed_{index}.md"
        brief.write_text(f"candidate {index}", encoding="utf-8")
        tasks.append({"brief": brief, "role": "spine_candidate"})
    nw._set_stage_tasks(state, "seed", tasks)
    nw._write_state(tmp_path, state)
    first, second = nw.reserve_tasks(tmp_path, capacity=2)
    first_path = tmp_path / "results" / "first.json"
    second_path = tmp_path / "results" / "second.json"
    nw.record_dispatch(
        tmp_path,
        task_id=first["task_id"],
        agent_id="agent-1",
        result_path=first_path,
    )
    nw.record_dispatch(
        tmp_path,
        task_id=second["task_id"],
        agent_id="agent-2",
        result_path=second_path,
    )
    shared_path = tmp_path / "results" / "shared.json"
    shared_path.parent.mkdir(parents=True)
    shared_path.write_text('{"sections": []}', encoding="utf-8")
    if alias_kind == "symlink":
        first_path.symlink_to(shared_path)
        second_path.symlink_to(shared_path)
    else:
        os.link(shared_path, first_path)
        os.link(shared_path, second_path)
    nw.record_agent_state(tmp_path, task_id=first["task_id"], status="result_ready")
    nw.record_agent_state(tmp_path, task_id=second["task_id"], status="result_ready")

    with pytest.raises(ValueError, match="alias|symbolic link"):
        nw.ingest_output(
            tmp_path,
            stage="seed",
            task_id=first["task_id"],
            source=first_path,
        )


def test_agent_ingest_rejects_result_file_moved_from_completed_task(tmp_path):
    _prepare(tmp_path)
    state = nw._load_state(tmp_path)
    tasks = []
    for index in range(2):
        brief = tmp_path / "briefs" / f"seed_{index}.md"
        brief.write_text(f"candidate {index}", encoding="utf-8")
        tasks.append({"brief": brief, "role": "spine_candidate"})
    nw._set_stage_tasks(state, "seed", tasks)
    nw._write_state(tmp_path, state)
    first, second = nw.reserve_tasks(tmp_path, capacity=2)
    first_path = tmp_path / "results" / "first.json"
    second_path = tmp_path / "results" / "second.json"
    nw.record_dispatch(
        tmp_path,
        task_id=first["task_id"],
        agent_id="agent-1",
        result_path=first_path,
    )
    nw.record_dispatch(
        tmp_path,
        task_id=second["task_id"],
        agent_id="agent-2",
        result_path=second_path,
    )
    first_path.parent.mkdir(parents=True)
    first_path.write_text('{"sections": []}', encoding="utf-8")
    nw.record_agent_state(tmp_path, task_id=first["task_id"], status="result_ready")
    nw.ingest_output(
        tmp_path,
        stage="seed",
        task_id=first["task_id"],
        source=first_path,
    )
    first_path.rename(second_path)
    nw.record_agent_state(tmp_path, task_id=second["task_id"], status="result_ready")

    with pytest.raises(ValueError, match="alias|already ingested"):
        nw.ingest_output(
            tmp_path,
            stage="seed",
            task_id=second["task_id"],
            source=second_path,
        )


def test_agent_ingest_uses_the_verified_result_file_snapshot(tmp_path, monkeypatch):
    _prepare(tmp_path)
    task = nw.reserve_tasks(tmp_path, capacity=1)[0]
    result_path = tmp_path / "results" / "agent.json"
    replacement_path = tmp_path / "results" / "replacement.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text('{"sections": []}', encoding="utf-8")
    replacement_path.write_text(
        '{"sections":[{"section_id":"swapped","title":"swapped","body":"b"}]}',
        encoding="utf-8",
    )
    nw.record_dispatch(
        tmp_path,
        task_id=task["task_id"],
        agent_id="agent-1",
        result_path=result_path,
    )
    nw.record_agent_state(tmp_path, task_id=task["task_id"], status="result_ready")
    original_read_text = Path.read_text
    swapped = False

    def swap_before_read(path, *args, **kwargs):
        nonlocal swapped
        if path == result_path and not swapped:
            replacement_path.replace(result_path)
            swapped = True
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", swap_before_read)

    ingested = nw.ingest_output(
        tmp_path,
        stage=task["stage"],
        task_id=task["task_id"],
        source=result_path,
    )

    assert "swapped" not in ingested.get("sections", {})


def test_dispatched_agent_task_must_be_result_ready_before_ingest(tmp_path):
    _prepare(tmp_path)
    task = nw.reserve_tasks(tmp_path, capacity=1)[0]
    result_path = tmp_path / "results" / "agent.json"
    nw.record_dispatch(
        tmp_path,
        task_id=task["task_id"],
        agent_id="agent-1",
        result_path=result_path,
    )

    with pytest.raises(ValueError, match="result_ready"):
        nw.ingest_output(
            tmp_path,
            stage=task["stage"],
            task_id=task["task_id"],
            text='{"sections": []}',
        )


def test_result_ready_agent_task_only_ingests_its_registered_result_path(tmp_path):
    _prepare(tmp_path)
    task = nw.reserve_tasks(tmp_path, capacity=1)[0]
    result_path = tmp_path / "results" / "agent.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text('{"sections": []}', encoding="utf-8")
    nw.record_dispatch(
        tmp_path,
        task_id=task["task_id"],
        agent_id="agent-1",
        result_path=result_path,
    )
    nw.record_agent_state(
        tmp_path,
        task_id=task["task_id"],
        status="result_ready",
    )
    wrong_path = tmp_path / "results" / "stale.json"
    wrong_path.write_text('{"sections": []}', encoding="utf-8")

    with pytest.raises(ValueError, match="registered result_path"):
        nw.ingest_output(
            tmp_path,
            stage=task["stage"],
            task_id=task["task_id"],
            source=wrong_path,
        )

    ingested = nw.ingest_output(
        tmp_path,
        stage=task["stage"],
        task_id=task["task_id"],
        source=result_path,
    )

    assert nw._stage_tasks(ingested, task["stage"])[0]["status"] == "completed"
    assert nw._stage_tasks(ingested, task["stage"])[0]["dispatch_status"] == "ingested"


def test_result_ready_agent_ingest_rejects_inline_text_with_registered_source(tmp_path):
    _prepare(tmp_path)
    task = nw.reserve_tasks(tmp_path, capacity=1)[0]
    result_path = tmp_path / "results" / "agent.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text('{"sections": []}', encoding="utf-8")
    nw.record_dispatch(
        tmp_path,
        task_id=task["task_id"],
        agent_id="agent-1",
        result_path=result_path,
    )
    nw.record_agent_state(
        tmp_path,
        task_id=task["task_id"],
        status="result_ready",
    )

    with pytest.raises(ValueError, match="inline text"):
        nw.ingest_output(
            tmp_path,
            stage=task["stage"],
            task_id=task["task_id"],
            source=result_path,
            text='{"sections": [{"title": "伪造"}]}',
        )


def test_result_ready_agent_ingest_requires_registered_result_file(tmp_path):
    _prepare(tmp_path)
    task = nw.reserve_tasks(tmp_path, capacity=1)[0]
    result_path = tmp_path / "results" / "missing.json"
    nw.record_dispatch(
        tmp_path,
        task_id=task["task_id"],
        agent_id="agent-1",
        result_path=result_path,
    )
    nw.record_agent_state(
        tmp_path,
        task_id=task["task_id"],
        status="result_ready",
    )

    with pytest.raises(ValueError, match="existing file"):
        nw.ingest_output(
            tmp_path,
            stage=task["stage"],
            task_id=task["task_id"],
            source=result_path,
        )


def test_agent_ingest_requires_task_id_when_multiple_tasks_are_pending(tmp_path):
    _prepare(tmp_path)
    state = nw._load_state(tmp_path)
    state["stage"] = "fan"
    tasks = []
    for index in range(2):
        brief = tmp_path / "briefs" / f"fan_{index}.md"
        brief.write_text(f"fan {index}", encoding="utf-8")
        tasks.append({"brief": brief, "section_id": f"域{index}"})
    nw._set_stage_tasks(state, "fan", tasks)
    nw._write_state(tmp_path, state)
    reserved = nw.reserve_tasks(tmp_path, capacity=2)
    result_path = tmp_path / "results" / "fan_0.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        '{"section_id":"域0","title":"域0","body":"完成"}',
        encoding="utf-8",
    )
    for index, task in enumerate(reserved):
        nw.record_dispatch(
            tmp_path,
            task_id=task["task_id"],
            agent_id=f"agent-{index}",
            result_path=result_path if index == 0 else tmp_path / "results" / "fan_1.json",
        )
    nw.record_agent_state(
        tmp_path,
        task_id=reserved[0]["task_id"],
        status="result_ready",
    )

    with pytest.raises(ValueError, match="task_id"):
        nw.ingest_output(tmp_path, stage="fan", source=result_path)


def test_concurrent_dispatch_updates_do_not_overwrite_each_other(tmp_path, monkeypatch):
    _prepare(tmp_path)
    state = nw._load_state(tmp_path)
    tasks = []
    for index in range(2):
        brief = tmp_path / "briefs" / f"seed_{index}.md"
        brief.write_text(f"task {index}", encoding="utf-8")
        tasks.append({"brief": brief, "role": "spine_candidate"})
    nw._set_stage_tasks(state, "seed", tasks)
    first_two = nw._stage_tasks(state, "seed")
    for task in first_two:
        task["dispatch_status"] = "reserved"
    nw._write_state(tmp_path, state)

    original_load = nw._load_state
    both_loaded = threading.Barrier(2)

    def delayed_load(run_dir):
        loaded = original_load(run_dir)
        try:
            both_loaded.wait(timeout=0.2)
        except threading.BrokenBarrierError:
            pass
        return loaded

    monkeypatch.setattr(nw, "_load_state", delayed_load)

    def dispatch(index):
        task = first_two[index]
        return nw.record_dispatch(
            tmp_path,
            task_id=task["task_id"],
            agent_id=f"agent-{index}",
            result_path=tmp_path / "results" / f"agent-{index}.json",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(dispatch, range(2)))

    persisted = original_load(tmp_path)
    dispatched = nw._stage_tasks(persisted, "seed")[:2]
    assert [task["dispatch_status"] for task in dispatched] == [
        "dispatched",
        "dispatched",
    ]
    assert [task["agent_id"] for task in dispatched] == ["agent-0", "agent-1"]


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


def test_task_id_accepts_an_arbitrarily_named_result_file(tmp_path):
    _prepare(tmp_path, slices=[_slice("生意大盘"), _slice("商品结构")])
    nw.ingest_output(
        tmp_path,
        stage="seed",
        text='{"sections":[{"section_id":"生意大盘","title":"生意大盘","body":"b"}]}',
    )
    nw.advance_run(tmp_path)
    task = nw.status_json(tmp_path)["tasks"]["pending"][0]
    result_path = tmp_path / "agent-results" / "result.json"
    result_path.parent.mkdir()
    result_path.write_text(
        json.dumps(
            {
                "section_id": task["section_id"],
                "title": task["section_id"],
                "body": "来自任意命名结果文件",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    nw.ingest_output(
        tmp_path,
        stage="fan",
        task_id=task["task_id"],
        source=result_path,
    )

    completed = nw.status_json(tmp_path)["tasks"]["completed"]
    assert [item["task_id"] for item in completed] == [task["task_id"]]


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


def test_gate_allows_a_fifth_targeted_repair_round(tmp_path, monkeypatch):
    _prepare(tmp_path)
    state = nw._load_state(tmp_path)
    state["_bundle"] = {
        "sections": [
            {
                "section_id": "生意大盘",
                "claims": [{"claim_id": "c1"}],
                "actions": [],
                "curated_views": [],
            }
        ]
    }
    state["_gate_rounds"] = 4
    nw._write_state(tmp_path, state)

    class FifthRoundFailure:
        status = "FAIL"
        hard_failures = [
            {
                "code": "MAGNITUDE_UNBOUND",
                "claim_id": "c1",
                "detail": "claim magnitude is not bound to evidence",
            }
        ]
        warnings = []
        capped_claims = []
        bundle = state["_bundle"]

    monkeypatch.setattr(nw, "_run_gate", lambda *_args: FifthRoundFailure())

    def unexpected_fallback(*_args, **_kwargs):
        pytest.fail("the fifth repair round must not fall back")

    monkeypatch.setattr(nw, "finalize_deterministic", unexpected_fallback)

    result = nw._run_gate_stage(tmp_path, state, {"facts": {}}, tmp_path)

    assert nw.MAX_GATE_ROUNDS == 5
    assert result["stage"] == "patch"
    assert result["_gate_rounds"] == 5
    pending = nw._pending_tasks(result, "patch")
    assert len(pending) == 1
    assert Path(pending[0]["brief"]).name == "patch.md"


def test_gate_exhaustion_persists_the_latest_report_before_fallback(tmp_path, monkeypatch):
    _prepare(tmp_path)
    state = nw._load_state(tmp_path)
    state["_bundle"] = {"sections": []}
    state["_gate_rounds"] = nw.MAX_GATE_ROUNDS
    state["_gate_failures"] = [{"code": "STALE", "detail": "old failure"}]
    nw._write_state(tmp_path, state)
    latest_failures = [
        {
            "code": "DANGLING_CALLBACK",
            "claim_id": "商品结构",
            "detail": "callback to unknown spine link L5",
        }
    ]

    class LatestReport:
        status = "FAIL"
        hard_failures = latest_failures
        warnings = []
        capped_claims = []
        bundle = {"sections": []}

    monkeypatch.setattr(nw, "_run_gate", lambda *_args: LatestReport())
    observed = {}

    def capture_fallback(rd, *, project_root=None, reason):
        persisted = nw._load_state(rd)
        observed["failures"] = persisted.get("_gate_failures")
        observed["report"] = json.loads(
            (Path(rd) / "gate_report.json").read_text(encoding="utf-8")
        )
        return persisted

    monkeypatch.setattr(nw, "finalize_deterministic", capture_fallback)

    result = nw._run_gate_stage(tmp_path, state, {"facts": {}}, tmp_path)

    assert result["stage"] == "blocked"
    assert observed["failures"] == latest_failures
    assert observed["report"]["hard_failures"] == latest_failures
    assert nw._load_state(tmp_path)["_gate_failures"] == latest_failures


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


@pytest.mark.parametrize(
    "html,expected_error",
    [
        (
            "<html><head><title>错题</title></head><body><h1>店铺报告</h1></body></html>",
            "title",
        ),
        (
            "<html><head><title>店铺报告</title></head><body><h1>错题</h1></body></html>",
            "h1",
        ),
        (
            "<html><head><title>店铺报告</title></head><body><h1>店铺报告</h1>{t0}</body></html>",
            "token",
        ),
        (
            '<html><head><title>店铺报告</title></head><body><h1>店铺报告</h1><img src="https://cdn.example/a.png"></body></html>',
            "external",
        ),
        (
            '<html><head><title>店铺报告</title></head><body><h1>店铺报告</h1>'
            '<img srcset="data:image/png;base64,iVBORw0KGgo 1x, https://cdn.example/a.png 2x">'
            "</body></html>",
            "external",
        ),
    ],
)
def test_delivery_html_rejects_wrong_identity_tokens_and_external_dependencies(
    html, expected_error
):
    with pytest.raises(ValueError, match=expected_error):
        nw._validate_delivery_html(html, "店铺报告")


def test_delivery_html_accepts_embedded_data_image_with_url_like_base64_bytes():
    html = (
        '<html><head><title>店铺报告</title></head><body><h1>店铺报告'
        '<img src="data:image/gif;base64,R0lGODlhAA//AA" alt="小熊">'
        "</h1></body></html>"
    )

    nw._validate_delivery_html(html, "店铺报告")


def test_delivery_html_requires_each_retained_view_marker_exactly_once():
    html = (
        "<html><head><title>店铺报告</title></head><body><h1>店铺报告</h1>"
        '<div data-view-id="v1"></div><div data-view-id="v1"></div>'
        "</body></html>"
    )

    with pytest.raises(ValueError, match="retained view.*v1.*exactly once"):
        nw._validate_delivery_html(html, "店铺报告", retained_view_ids=["v1"])


def test_delivery_html_rejects_marker_for_a_non_retained_view():
    html = (
        "<html><head><title>店铺报告</title></head><body><h1>店铺报告</h1>"
        '<div data-view-id="v1"></div><div data-view-id="dropped"></div>'
        "</body></html>"
    )

    with pytest.raises(ValueError, match="unexpected.*dropped"):
        nw._validate_delivery_html(html, "店铺报告", retained_view_ids=["v1"])


def test_delivery_html_does_not_accept_document_shell_inside_a_comment():
    html = (
        "<!-- <html><body></body></html> -->"
        "<title>店铺报告</title><h1>店铺报告</h1>"
    )

    with pytest.raises(ValueError, match="HTML document"):
        nw._validate_delivery_html(html, "店铺报告")


def test_delivery_html_does_not_count_view_marker_inside_script_text():
    html = (
        "<html><head><title>店铺报告</title></head><body><h1>店铺报告</h1>"
        "<script>const fake = '<div data-view-id=\"v1\"></div>';</script>"
        "</body></html>"
    )

    with pytest.raises(ValueError, match="retained view.*v1.*exactly once"):
        nw._validate_delivery_html(html, "店铺报告", retained_view_ids=["v1"])


def test_delivery_html_rejects_external_css_import():
    html = (
        "<html><head><title>店铺报告</title>"
        '<style>@import "https://cdn.example/report.css";</style></head>'
        "<body><h1>店铺报告</h1></body></html>"
    )

    with pytest.raises(ValueError, match="external dependency"):
        nw._validate_delivery_html(html, "店铺报告")


def test_visual_coverage_audit_error_fails_closed(monkeypatch):
    def fail_audit(_tables):
        raise RuntimeError("audit exploded")

    monkeypatch.setattr(nw, "has_chartable_tables", fail_audit)

    assert nw._visual_coverage_reason("", {}) == "visuals_missing"


def test_ready_telemetry_is_not_written_before_final_state(tmp_path, monkeypatch):
    _prepare(tmp_path)
    state = nw._load_state(tmp_path)
    state["_bundle"] = {"sections": []}
    nw._write_state(tmp_path, state)
    original_write_state = nw._write_state
    events = []

    def fail_final_state(run_dir, payload):
        if payload.get("stage") == "finalized":
            events.append("state")
            raise OSError("state write failed")
        return original_write_state(run_dir, payload)

    monkeypatch.setattr(nw, "_write_state", fail_final_state)
    monkeypatch.setattr(
        nw,
        "append_run_record",
        lambda *_args, **_kwargs: events.append("telemetry"),
    )

    with pytest.raises(OSError, match="state write failed"):
        nw.finalize_narrative(tmp_path, project_root=tmp_path)

    assert events == ["state"]


def test_fallback_ready_telemetry_is_not_written_before_blocked_state(
    tmp_path,
    monkeypatch,
):
    _prepare(tmp_path)
    original_write_state = nw._write_state
    events = []

    def fail_blocked_state(run_dir, payload):
        if payload.get("stage") == "blocked":
            events.append("state")
            raise OSError("state write failed")
        return original_write_state(run_dir, payload)

    monkeypatch.setattr(nw, "_write_state", fail_blocked_state)
    monkeypatch.setattr(
        nw,
        "append_run_record",
        lambda *_args, **_kwargs: events.append("telemetry"),
    )

    with pytest.raises(OSError, match="state write failed"):
        nw.finalize_deterministic(
            tmp_path,
            project_root=tmp_path,
            reason="denied",
        )

    assert events == ["state"]


def test_finalize_cleans_stale_html_from_reused_production_directory(tmp_path):
    _prepare(tmp_path)
    state = nw._load_state(tmp_path)
    state["_bundle"] = {"sections": []}
    nw._write_state(tmp_path, state)
    output_dir = (
        tmp_path
        / ".xhs-ceramics-analytics"
        / "outputs"
        / "20260802-120000-报告"
    )
    output_dir.mkdir(parents=True)
    (output_dir / "stale.html").write_text("stale", encoding="utf-8")

    finalized = nw.finalize_narrative(
        tmp_path,
        project_root=tmp_path,
        timestamp="20260802-120000",
    )

    assert finalized["stage"] == "finalized"
    assert [path.name for path in output_dir.glob("*.html")] == ["报告.html"]


def test_merchant_candidate_records_hash_lineage_and_matches_final_html(tmp_path):
    _prepare(tmp_path)
    state = nw._load_state(tmp_path)
    state["_bundle"] = {"sections": []}
    nw._write_state(tmp_path, state)
    candidate_state = nw._enter_merchant_review(
        tmp_path,
        state,
        json.loads((tmp_path / "facts.json").read_text(encoding="utf-8")),
    )

    lineage = candidate_state["candidate_lineage"]
    candidate_bytes = Path(candidate_state["candidate_html"]).read_bytes()
    assert lineage["candidate_html_hash"] == nw._sha256_bytes(candidate_bytes)
    assert lineage["bundle_hash"] == nw._stable_hash(candidate_state["_bundle"])

    finalized = nw.finalize_narrative(
        tmp_path,
        project_root=tmp_path,
        timestamp="20260802-130000",
    )
    final_bytes = Path(finalized["artifacts"]["html"]).read_bytes()

    assert finalized["artifact_lineage"]["candidate_html_hash"] == nw._sha256_bytes(
        candidate_bytes
    )
    assert finalized["artifact_lineage"]["final_html_hash"] == nw._sha256_bytes(
        final_bytes
    )
    assert candidate_bytes == final_bytes


def test_finalize_rejects_bundle_changed_after_merchant_candidate_review(tmp_path):
    _prepare(tmp_path)
    state = nw._load_state(tmp_path)
    state["_bundle"] = {"sections": []}
    nw._write_state(tmp_path, state)
    state = nw._enter_merchant_review(
        tmp_path,
        state,
        json.loads((tmp_path / "facts.json").read_text(encoding="utf-8")),
    )
    state["_bundle"] = {"headline": "审阅后被替换", "sections": []}
    nw._write_state(tmp_path, state)

    with pytest.raises(ValueError, match="candidate bundle changed after review"):
        nw.finalize_narrative(
            tmp_path,
            project_root=tmp_path,
            timestamp="20260802-130000",
        )

    failed = nw._load_state(tmp_path)
    assert failed["stage"] == "delivery_failed"
    assert failed["error"]["code"] == "FINAL_VALIDATION_FAILED"


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
