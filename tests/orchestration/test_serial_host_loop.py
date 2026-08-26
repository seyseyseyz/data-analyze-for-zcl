"""串行宿主省力循环：``next_task`` / ``submit_task``。

Codex 一类没有并行子 agent 设施的宿主按「领一个任务 → 自己完成 → 交回」的节奏驱动
叙事工作流。原语序列（status → reserve → record-dispatch → 干活 → validate →
record-agent-state → ingest → closed）每个任务要 5+ 次 CLI 调用，全靠宿主自觉按
runbook 散文执行。这两个组合命令把它压成 2 次，并把 agent_id / result_path 的
唯一性约定交给控制器自动生成——宿主永远拿不到一个会被拒绝的派单参数。
"""
import json

import pytest

from xhs_ceramics_analytics.orchestration import narrative_workflow as nw


def _slice(title: str) -> dict:
    return {
        "title": title,
        "facts": [{"fact_id": f"{title}.gmv", "metric": "GMV", "value": 100}],
        "reading": {"conclusion": "平稳"},
    }


def _prepare_fan_run(tmp_path, count: int = 2) -> None:
    """Legacy-mode run parked at fan stage with ``count`` hand-built ledger tasks."""
    nw.prepare_run(
        tmp_path,
        results={"domain_slices": [_slice("生意大盘")]},
        facts_json={"facts_hash": "h", "facts": {}},
        report_name="报告",
        project_root=tmp_path,
    )
    state = nw._load_state(tmp_path)
    state["stage"] = "fan"
    tasks = []
    for index in range(count):
        brief = tmp_path / "briefs" / f"fan_{index}.md"
        brief.write_text(f"task {index}", encoding="utf-8")
        tasks.append({"brief": brief, "section_id": f"域{index}", "role": "domain_writer"})
    nw._set_stage_tasks(state, "fan", tasks)
    nw._write_state(tmp_path, state)


def _result_payload(section_id: str) -> str:
    return json.dumps(
        {"section_id": section_id, "title": section_id, "body": "结论正文。"},
        ensure_ascii=False,
    )


def test_next_reserves_and_dispatches_one_task_with_generated_identity(tmp_path):
    _prepare_fan_run(tmp_path)

    handed = nw.next_task(tmp_path)

    assert handed["status"] == "ready"
    task = handed["task"]
    assert task["dispatch_status"] == "dispatched"
    assert task["agent_id"]  # controller 生成，宿主无需发明
    assert str(tmp_path / "results") in str(task["result_path"])
    # 状态机里确实记录了这次派单
    state = nw._load_state(tmp_path)
    ledger = {t["task_id"]: t for t in nw._stage_tasks(state, "fan")}
    assert ledger[task["task_id"]]["dispatch_status"] == "dispatched"


def test_next_reports_in_flight_instead_of_double_dispatch(tmp_path):
    _prepare_fan_run(tmp_path, count=1)
    nw.next_task(tmp_path)

    second = nw.next_task(tmp_path)

    assert second["status"] == "in_flight"
    assert second["stage"] == "fan"


def test_submit_validates_ingests_and_frees_the_next_task(tmp_path):
    _prepare_fan_run(tmp_path, count=2)
    first = nw.next_task(tmp_path)["task"]
    result_path = first["result_path"]
    with open(result_path, "w", encoding="utf-8") as fh:
        fh.write(_result_payload(first["section_id"]))

    outcome = nw.submit_task(tmp_path, task_id=first["task_id"])

    assert outcome["ingested"] == first["task_id"]
    # 提交默认使用派单时登记的 result_path，无需重复传 source
    follow_up = nw.next_task(tmp_path)
    assert follow_up["status"] == "ready"
    assert follow_up["task"]["task_id"] != first["task_id"]


def test_submit_missing_result_file_fails_without_state_damage(tmp_path):
    _prepare_fan_run(tmp_path, count=1)
    handed = nw.next_task(tmp_path)["task"]

    with pytest.raises(FileNotFoundError):
        nw.submit_task(tmp_path, task_id=handed["task_id"])

    state = nw._load_state(tmp_path)
    ledger = {t["task_id"]: t for t in nw._stage_tasks(state, "fan")}
    assert ledger[handed["task_id"]]["dispatch_status"] == "dispatched"


def test_next_surfaces_terminal_stage_instead_of_reserving(tmp_path):
    _prepare_fan_run(tmp_path, count=1)
    state = nw._load_state(tmp_path)
    state["stage"] = "finalized"
    nw._write_state(tmp_path, state)

    handed = nw.next_task(tmp_path)

    assert handed["status"] == "terminal"
    assert handed["stage"] == "finalized"


def test_status_exposes_the_recorded_authorization_decision(tmp_path):
    # 恢复会话的宿主从 status 就能看到已记录的授权，不再重复问用户。
    _prepare_fan_run(tmp_path)

    status = nw.status_json(tmp_path)

    assert "authorization_decision" in status
