"""Passive, file-based narrative-workflow controller (host-neutral).

The controller prepares durable briefs and state and ingests sub-agent JSON,
but never spawns sub-agents. The host agent drives it (see runbook.md).
"""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from functools import lru_cache, wraps
from html.parser import HTMLParser
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from xhs_ceramics_analytics.paths import (
    project_root as resolve_project_root,
    run_output_dir,
    run_timestamp,
    state_dir,
)
from xhs_ceramics_analytics.reporting.factcheck_gate import run_gate
from xhs_ceramics_analytics.reporting.factcheck_gate import (
    _decision_critical_claim_ids,
    _view_label as _gate_view_label,
)
from xhs_ceramics_analytics.reporting.data_gaps import data_gap_markdown
from xhs_ceramics_analytics.reporting.html import render_markdown_document_html
from xhs_ceramics_analytics.reporting.narrative_render import (
    apply_continuity_edits,
    bundle_to_markdown,
    has_chartable_tables,
    render_draft,
)
from xhs_ceramics_analytics.reporting.report_telemetry import (
    append_run_record,
    build_run_record,
)
from xhs_ceramics_analytics.reporting.view_spec import _template_of

MAX_FAN_AGENTS = 6
MAX_GATE_ROUNDS = 5
# Review-stage patch budget (spec §Multi-Reviewer Review): a view whose 3 reviewers
# reach no keep/drop majority is re-authored at most this many times; a view still
# unconverged after the budget is spent is dropped, never blocking the report.
MAX_REVIEW_PATCH_ROUNDS = 2
MAX_MERCHANT_REVISION_ROUNDS = 2
QUALITY_WORKFLOW_VERSION = "quality-v2"
DETERMINISTIC_WORKFLOW_VERSION = "deterministic-v2"
LEGACY_WORKFLOW_VERSION = "legacy-v1"
_SINGLE_HTML_WORKFLOWS = {
    QUALITY_WORKFLOW_VERSION,
    DETERMINISTIC_WORKFLOW_VERSION,
}

_STATE_FILE = "state.json"
_STATE_LOCK_FILE = ".state.lock"
_RESULT_TABLES_FILE = "result_tables.json"
_SLUG_STRIP = re.compile(r"[^\w一-鿿]+")
_TERMINAL_STAGES = {"finalized", "blocked", "delivery_failed"}
_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "orchestration" / "schemas"

# The three adversarial reviewer lenses (spec §Multi-Reviewer Review). Each is a
# distinct failure-mode lens — NOT three copies of "默认拒绝". The old uniform
# reject-bias starved the narrative: every lens defaulted to drop, so a view no one
# actually objected to still died once the patch budget ran out. Calibrated bias by
# lens: 价值 keeps when unsure (value = business-meaningful insight, not a required
# action); 可读性 prefers revise over drop (most readability faults are fixable);
# only 支撑 — the trust / anti-dump anchor — defaults toward drop. Prose only, no
# ASCII digits (the old 可读性 lens leaked a bare "5 秒").
_REVIEW_LENSES: tuple[tuple[str, str], ...] = (
    (
        "价值",
        "这张图表让商家知道了什么『不看它就不知道』的经营事实?能校正或印证商家很可能"
        "持有的假设、把问题或机会定位到具体 SKU 渠道人群时段、给出量级占比趋势让商家"
        "知道先看哪里、或直接指向一个可调的杠杆——满足任一即算有价值(可行动只是其中"
        "一种,不是门槛)。仅当它是纯内部或流程统计而无经营含义,或只是把 claim 句里"
        "已有的数字换个壳重复、无新增对比拆解排序时,才判 drop;拿不准就 keep。",
    ),
    (
        "可读性",
        "商家(非分析师)能否一眼读对?优先判 revise 而非 drop,因为多数可读性问题可修:"
        "先看它有没有用最合适的呈现形式——模板与数据形态错配(时间序列该用趋势线、构成"
        "占比该用占比条、增减分解该用瀑布、并列对照才用表)判 revise 并指出正确模板;列"
        "或维度多到满屏扫不完或需横向滚动"
        "判 revise 建议裁列;列名标题是内部字段黑话(如 delta_gmv)判 revise 建议用 "
        "column_labels 写成商家能懂的词。只有排版到读不出任何信息且单轮 revise 修不好"
        "时才 drop。",
    ),
    (
        "支撑",
        "它是否诚实地佐证了 supports_claim 那条结论且不误导?展示的维度必须就是该结论"
        "讲的维度,无关判 drop;排序 TopN 高亮不能让商家读出与结论相反或被夸大的方向,"
        "轻则 revise 加注、重则 drop;视图呈现的确定感不得超过它所支撑 claim 的证据档"
        "(强中弱),拿弱证据撑起看似铁证的图判 revise 要求加『弱证据』标注。整表照搬、"
        "逐行堆砌、未做编辑取舍的原始数据倾倒判 drop。这条是 anti-dump 与信任的底线,"
        "允许 drop。",
    ),
)

_QUALITY_REVIEW_LENS_NAMES = {
    "价值": "merchant_decision",
    "可读性": "editorial_visual",
    "支撑": "evidence_semantics",
}

# Verdict vocabulary a reviewer may return (spec: keep / revise / drop). Anything
# outside this set counts toward neither keep nor drop, pushing the tally to patch.
_KEEP_VERDICT = "keep"
_DROP_VERDICT = "drop"
_KNOWN_VERDICTS: frozenset[str] = frozenset({"keep", "revise", "drop"})

_NEXT_ACTION = {
    "seed": "run every pending independent spine-candidate brief, ingest each result, then advance",
    "spine_adjudication": "run the spine adjudicator brief, ingest its decision, then advance",
    "fan": "read briefs/fan_*.md, spawn one sub-agent per brief, ingest --stage fan each, then advance",
    "domain_challenge": "run one challenger per domain, ingest every challenge report, then advance",
    "domain_adjudication": "run one adjudicator per domain, ingest every adjudicated section, then advance",
    "synth": "read briefs/synth.md, spawn one sub-agent to assemble the first screen, "
             "ingest --stage synth, then advance",
    "visual_curation": "run the independent visual-curator brief, ingest view specs, then advance",
    "gate": "run advance to apply the deterministic fact-check gate",
    "patch": "read the patch brief, spawn one sub-agent, ingest --stage patch, then advance",
    "review": "read briefs/review_*.md, spawn 3 reviewers (价值/可读性/支撑) per domain, "
              "ingest --stage review each verdict, then advance",
    "continuity": "spawn one sub-agent to smooth transitions, ingest --stage continuity, then advance",
    "merchant_review": "review candidate.html as the merchant; ingest pass or targeted issues, then advance",
    "merchant_patch": "apply only the merchant review targets, ingest the revision, then advance",
    "finalized": "done — deliver <name>.html",
    "blocked": "deterministic skeleton delivered — report degradation reason",
    "delivery_failed": "HTML delivery failed — report delivery_error and retry rendering",
}


def tally_votes(verdicts) -> str:
    """Resolve one curated view's 3 reviewer verdicts to ``keep`` / ``drop`` / ``patch``.

    PURE and total: the exact strict precedence of spec §Multi-Reviewer Review, so
    every verdict combination maps to exactly one outcome:

    1. ``drop >= 2`` → ``drop`` (a clear majority to remove wins first).
    2. else ``keep >= 2`` → ``keep`` (2 keep + 1 drop, or 2 keep + 1 revise → keep).
    3. else → ``patch`` (any mix with no majority, incl. empty / all-revise).

    Tolerant of missing/garbled input and NEVER raises: a non-list, non-string
    elements, and unrecognized tokens (``revise`` or noise) simply count toward
    neither keep nor drop — they push the tally to ``patch``. Case- and
    whitespace-insensitive.
    """
    keep = drop = 0
    if isinstance(verdicts, (list, tuple)):
        for verdict in verdicts:
            if not isinstance(verdict, str):
                continue
            token = verdict.strip().lower()
            if token == _DROP_VERDICT:
                drop += 1
            elif token == _KEEP_VERDICT:
                keep += 1
    if drop >= 2:
        return "drop"
    if keep >= 2:
        return "keep"
    return "patch"


def _view_action(verdicts, *, patch_rounds: int) -> str:
    """Final fate of one curated view: ``keep`` / ``drop`` / ``patch``. Never raises.

    Layers stage policy on the pure :func:`tally_votes`:

    - Missing / garbled reviewer input (no recognized keep/revise/drop verdict at
      all) degrades to ``drop`` — a view no reviewer could judge is dropped, not
      kept (unjudgeable ≠ endorsed).
    - A ``patch`` outcome whose patch budget is already spent is resolved by whether
      any reviewer actually voted to remove the view: with a ``drop`` vote it
      degrades to ``drop`` (支撑's removal power survives exhaustion); with none it is
      ``keep``. This is the calibrated reject-bias fix — an unconverged view that no
      lens objected to (e.g. keep + two revise) is retained rather than starving the
      narrative, while never blocking the report.
    - ``keep`` / ``drop`` pass through.
    """
    recognized = [
        v for v in (verdicts or [])
        if isinstance(v, str) and v.strip().lower() in _KNOWN_VERDICTS
    ]
    if not recognized:
        return "drop"
    outcome = tally_votes(recognized)
    if outcome == "patch" and patch_rounds >= MAX_REVIEW_PATCH_ROUNDS:
        has_drop = any(v.strip().lower() == _DROP_VERDICT for v in recognized)
        return "drop" if has_drop else "keep"
    return outcome


def _slug(title: str) -> str:
    """Canonical section_id: preserve CJK, lowercase ASCII, dashes for the rest."""
    lowered = title.strip().lower()
    slug = _SLUG_STRIP.sub("-", lowered).strip("-")
    return slug or "section"


def _cap_slices(slices: list[dict]) -> tuple[list[dict], list[str]]:
    """Fold any slices beyond MAX_FAN_AGENTS into one lossless '综合参考' slice."""
    if len(slices) <= MAX_FAN_AGENTS:
        return list(slices), []
    head = list(slices[: MAX_FAN_AGENTS - 1])
    tail = list(slices[MAX_FAN_AGENTS - 1 :])
    merged_titles = [s.get("title", "") for s in tail]
    merged = {
        "title": "综合参考",
        "facts": [f for s in tail for f in s.get("facts", [])],
        "reading": {
            "conclusion": "；".join(
                s.get("reading", {}).get("conclusion", "") for s in tail if s.get("reading", {}).get("conclusion")
            ),
        },
        "merged_from": merged_titles,
    }
    head.append(merged)
    return head, merged_titles


def _load_state(run_dir: Path) -> dict | None:
    path = run_dir / _STATE_FILE
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_state(run_dir: Path, state: dict) -> None:
    """Atomically replace state.json so an interrupted write cannot corrupt a run."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    destination = run_dir / _STATE_FILE
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=run_dir,
            prefix=f".{_STATE_FILE}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


@contextmanager
def _state_lock(run_dir: Path):
    """Serialize read-modify-write transactions across host processes and threads."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / _STATE_LOCK_FILE).open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _serialized_state_mutation(function):
    @wraps(function)
    def wrapped(run_dir, *args, **kwargs):
        with _state_lock(Path(run_dir)):
            return function(run_dir, *args, **kwargs)

    return wrapped


def _write_json_atomic(path: Path, payload: dict) -> None:
    """Atomically publish a JSON artifact beside its final destination."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _write_text_atomic(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _stable_hash(value) -> str:
    blob = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _brief_hash(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _task_id(stage: str, brief, *, section_id=None, lens=None) -> str:
    parts = [stage]
    if section_id not in (None, ""):
        parts.append(str(section_id))
    if lens not in (None, ""):
        parts.append(str(lens))
    if len(parts) == 1:
        parts.append(Path(brief).stem)
    return ":".join(parts)


def _set_stage_tasks(state: dict, stage: str, tasks) -> None:
    items: list[dict] = []
    for task in tasks or []:
        item = dict(task)
        item["stage"] = stage
        item["brief"] = str(item["brief"])
        item.setdefault("role", stage)
        item.setdefault(
            "task_id",
            _task_id(
                stage,
                item["brief"],
                section_id=item.get("section_id"),
                lens=item.get("lens"),
            ),
        )
        if Path(item["brief"]).exists():
            item.setdefault("brief_hash", _brief_hash(item["brief"]))
        item.setdefault(
            "snapshot",
            {
                "facts_hash": state.get("facts_hash"),
                "registry_hash": state.get("registry_hash"),
            },
        )
        item.setdefault("status", "pending")
        item.setdefault("dispatch_status", "pending")
        item.setdefault("attempt", 0)
        item.setdefault(
            "result_path",
            str(Path(item["brief"]).parent.parent / "results" / f"{Path(item['brief']).stem}.json"),
        )
        items.append(item)
    state["_tasks"] = {"stage": stage, "items": items}


def _stage_tasks(state: dict, stage: str | None = None) -> list[dict]:
    manifest = state.get("_tasks")
    current_stage = stage or state.get("stage")
    if not isinstance(manifest, dict) or manifest.get("stage") != current_stage:
        return []
    items = manifest.get("items")
    return items if isinstance(items, list) else []


def _pending_tasks(state: dict, stage: str | None = None) -> list[dict]:
    return [task for task in _stage_tasks(state, stage) if task.get("status") != "completed"]


def _complete_task(state: dict, task: dict | None) -> None:
    if task is not None:
        task["status"] = "completed"
        task["dispatch_status"] = "ingested" if task.get("agent_id") else "closed"


_IN_FLIGHT_DISPATCH_STATES = {"reserved", "dispatched", "result_ready", "ingested"}


def _dispatch_task(state: dict, task_id: str) -> dict:
    matches = [
        task
        for task in _stage_tasks(state)
        if str(task.get("task_id")) == str(task_id)
    ]
    if len(matches) != 1:
        raise ValueError(f"unknown task_id for current stage: {task_id}")
    return matches[0]


@_serialized_state_mutation
def reserve_tasks(run_dir, *, capacity: int) -> list[dict]:
    """Reserve only the tasks that fit in the host's currently available slots."""
    if capacity < 1:
        raise ValueError("capacity must be at least 1")
    run_dir = Path(run_dir)
    state = _load_state(run_dir)
    if state is None:
        raise FileNotFoundError(f"no run at {run_dir}")
    tasks = _stage_tasks(state)
    in_flight = sum(
        1
        for task in tasks
        if task.get("status") != "completed"
        and task.get("dispatch_status") in _IN_FLIGHT_DISPATCH_STATES
    )
    slots = max(capacity - in_flight, 0)
    reserved: list[dict] = []
    for task in tasks:
        if slots == 0:
            break
        if task.get("status") == "completed":
            continue
        dispatch_status = task.get("dispatch_status") or "pending"
        if dispatch_status not in {"pending", "failed", "closed"}:
            continue
        task["dispatch_status"] = "reserved"
        task["attempt"] = int(task.get("attempt") or 0) + 1
        task.pop("agent_id", None)
        task.pop("last_error", None)
        reserved.append(_task_with_contract(run_dir, state, task))
        slots -= 1
    if reserved:
        _write_state(run_dir, state)
    return reserved


@_serialized_state_mutation
def record_dispatch(run_dir, *, task_id: str, agent_id: str, result_path) -> dict:
    run_dir = Path(run_dir)
    state = _load_state(run_dir)
    if state is None:
        raise FileNotFoundError(f"no run at {run_dir}")
    task = _dispatch_task(state, task_id)
    if task.get("dispatch_status") != "reserved":
        raise ValueError("task must be reserved before recording a dispatch")
    if not str(agent_id).strip():
        raise ValueError("agent_id must be non-empty")
    if any(
        other is not task and str(other.get("agent_id") or "") == str(agent_id)
        for other in _stage_tasks(state)
    ):
        raise ValueError(f"agent_id is already assigned: {agent_id}")
    canonical_result_path = Path(result_path).resolve()
    if any(
        other is not task
        and other.get("result_path")
        and Path(str(other["result_path"])).resolve() == canonical_result_path
        for other in _stage_tasks(state)
    ):
        raise ValueError(f"result_path is already assigned: {canonical_result_path}")
    task["agent_id"] = str(agent_id)
    task["result_path"] = str(canonical_result_path)
    task["dispatch_status"] = "dispatched"
    _write_state(run_dir, state)
    return _task_with_contract(run_dir, state, task)


@_serialized_state_mutation
def release_task(run_dir, *, task_id: str) -> dict:
    run_dir = Path(run_dir)
    state = _load_state(run_dir)
    if state is None:
        raise FileNotFoundError(f"no run at {run_dir}")
    task = _dispatch_task(state, task_id)
    if task.get("dispatch_status") != "reserved" or task.get("agent_id"):
        raise ValueError("only an unassigned reservation can be released")
    task["dispatch_status"] = "pending"
    _write_state(run_dir, state)
    return _task_with_contract(run_dir, state, task)


@_serialized_state_mutation
def record_agent_state(
    run_dir,
    *,
    task_id: str,
    status: str,
    error: str | None = None,
) -> dict:
    if status not in {"result_ready", "failed", "closed"}:
        raise ValueError("agent status must be result_ready, failed, or closed")
    run_dir = Path(run_dir)
    state = _load_state(run_dir)
    if state is None:
        raise FileNotFoundError(f"no run at {run_dir}")
    task = _dispatch_task(state, task_id)
    current = task.get("dispatch_status")
    if status == "result_ready" and current != "dispatched":
        raise ValueError("only a dispatched task can become result_ready")
    if status == "failed" and current not in {"reserved", "dispatched", "result_ready"}:
        raise ValueError("only an in-flight task can fail")
    if status == "closed" and not (
        task.get("status") == "completed" or current == "failed"
    ):
        raise ValueError("close only an ingested or failed task")
    if not (status == "closed" and task.get("status") == "completed"):
        task["dispatch_status"] = status
    if error not in (None, ""):
        task["last_error"] = str(error)
    _write_state(run_dir, state)
    return _task_with_contract(run_dir, state, task)


def next_task(run_dir, *, project_root=None) -> dict:
    """One serial-host step: hand out exactly one dispatched task, or say why not.

    Hosts without a parallel sub-agent facility (e.g. Codex CLI) drive the run as
    "take one task → do it → hand it back". This folds status + advance + reserve +
    record-dispatch into a single call and generates the agent_id / result_path pair
    itself, so the host can never invent a value the dispatch ledger would reject.
    Returns ``{"status": "ready", "task": <contract>}`` when a task was dispatched,
    ``"in_flight"`` when everything pending is already dispatched (submit first),
    or ``"terminal"`` when the run has finished or degraded.
    """
    run_dir = Path(run_dir)
    # Bounded: every loop iteration either returns or advances the stage machine,
    # and a run has a fixed number of stages.
    for _ in range(64):
        state = _load_state(run_dir)
        if state is None:
            raise FileNotFoundError(f"no run at {run_dir}")
        stage = state["stage"]
        if stage in _TERMINAL_STAGES:
            return {
                "status": "terminal",
                "stage": stage,
                "next_action": _NEXT_ACTION.get(stage, ""),
                "degradation_reason": state.get("degradation_reason"),
            }
        if _pending_tasks(state, stage):
            reserved = reserve_tasks(run_dir, capacity=1)
            if not reserved:
                return {
                    "status": "in_flight",
                    "stage": stage,
                    "pending": [
                        task.get("task_id") for task in _pending_tasks(state, stage)
                    ],
                }
            task = reserved[0]
            task_id = str(task["task_id"])
            attempt = int(task.get("attempt") or 1)
            dispatched = record_dispatch(
                run_dir,
                task_id=task_id,
                agent_id=f"host-{task_id}-r{attempt}",
                result_path=task.get("result_path")
                or run_dir / "results" / f"{task_id}.json",
            )
            # The host writes its result straight to this path — make sure the
            # directory exists so the handed-out contract is usable as-is.
            Path(str(dispatched["result_path"])).parent.mkdir(
                parents=True, exist_ok=True
            )
            return {"status": "ready", "stage": stage, "task": dispatched}
        advance_run(run_dir, project_root=project_root)
    raise RuntimeError("next_task did not converge after 64 stage advances")


def submit_task(run_dir, *, task_id: str, source=None) -> dict:
    """Hand one finished task result back: validate → result_ready → ingest → close.

    The counterpart of :func:`next_task`. ``source`` defaults to the result_path
    recorded at dispatch time. Validation runs read-only first, so a malformed
    result leaves the task dispatched (fix the file and submit again) instead of
    wedging the ledger. The trailing ``closed`` transition is the controller-ledger
    compatibility call the runbook requires after a successful ingest.
    """
    run_dir = Path(run_dir)
    state = _load_state(run_dir)
    if state is None:
        raise FileNotFoundError(f"no run at {run_dir}")
    stage = state["stage"]
    task = _dispatch_task(state, task_id)
    result_path = source if source is not None else task.get("result_path")
    if result_path in (None, ""):
        raise FileNotFoundError(f"task {task_id} has no recorded result_path")
    result_file = Path(str(result_path))
    if not result_file.exists():
        raise FileNotFoundError(f"result file not found: {result_file}")
    validate_output(run_dir, stage=stage, source=result_file, task_id=task_id)
    record_agent_state(run_dir, task_id=task_id, status="result_ready")
    new_state = ingest_output(run_dir, stage=stage, source=result_file, task_id=task_id)
    try:
        record_agent_state(run_dir, task_id=task_id, status="closed")
    except ValueError:
        pass  # ledger-compat only — ingest may have already recycled the slot
    return {
        "ingested": task_id,
        "stage": new_state["stage"],
        "pending": len(_pending_tasks(new_state, new_state.get("stage"))),
    }


def _task_for_ingest(
    state: dict,
    stage: str,
    *,
    source=None,
    section_id=None,
    lens=None,
    target_id=None,
    task_id=None,
) -> dict | None:
    pending = _pending_tasks(state, stage)
    if not _stage_tasks(state, stage):
        return None

    if task_id not in (None, ""):
        matches = [task for task in pending if str(task.get("task_id")) == str(task_id)]
        if len(matches) != 1:
            return None
        task = matches[0]
        if section_id not in (None, "") and str(task.get("section_id")) != str(section_id):
            return None
        if lens not in (None, "") and str(task.get("lens")) != str(lens):
            return None
        if (
            target_id not in (None, "")
            and task.get("target_id") not in (None, "")
            and str(task.get("target_id")) != str(target_id)
        ):
            return None
        return task

    if source is not None:
        source_path = Path(source)
        matches = [
            task
            for task in pending
            if Path(task.get("brief", "")) == source_path
            or Path(task.get("brief", "")).name == source_path.name
        ]
        if len(matches) == 1:
            return matches[0]

    matches = pending
    if section_id not in (None, ""):
        matches = [task for task in matches if str(task.get("section_id")) == str(section_id)]
    if lens not in (None, ""):
        matches = [task for task in matches if str(task.get("lens")) == str(lens)]
    if target_id not in (None, ""):
        matches = [
            task
            for task in matches
            if task.get("target_id") in (None, "")
            or str(task.get("target_id")) == str(target_id)
        ]
    if len(matches) == 1:
        return matches[0]
    if len(pending) == 1 and (
        (source is None and section_id in (None, "") and lens in (None, ""))
        or (
            pending[0].get("section_id") in (None, "")
            and pending[0].get("lens") in (None, "")
        )
    ):
        return pending[0]
    return None


def _enforce_agent_ingest_contract(
    state: dict,
    stage: str,
    *,
    source=None,
    text=None,
    task_id=None,
) -> str | None:
    """Validate and atomically read a dispatched agent's registered result file."""
    agent_tasks = [
        task
        for task in _pending_tasks(state, stage)
        if task.get("agent_id")
        and task.get("dispatch_status") in {"dispatched", "result_ready"}
    ]
    if agent_tasks and task_id in (None, ""):
        raise ValueError("task_id is required while the current stage has dispatched agent tasks")
    task = _task_for_ingest(state, stage, source=source, task_id=task_id)
    if agent_tasks and task is None:
        raise ValueError("task_id must match one pending task in the current stage")
    if task is None or not task.get("agent_id"):
        return None
    if task.get("dispatch_status") != "result_ready":
        raise ValueError("agent task must be result_ready before ingest")
    if source is None:
        raise ValueError("agent ingest must read the registered result_path")
    registered = Path(str(task.get("result_path") or ""))
    provided = Path(source)
    if registered.is_symlink() or provided.is_symlink():
        raise ValueError("agent ingest result_path must not be a symbolic link")
    expected = registered.resolve()
    actual = provided.resolve()
    if actual != expected:
        raise ValueError("agent ingest source must match the registered result_path")
    if text is not None:
        raise ValueError("agent ingest cannot use inline text")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(registered, flags)
    except FileNotFoundError as exc:
        raise ValueError(
            "agent ingest registered result_path must be an existing file"
        ) from exc
    except OSError as exc:
        raise ValueError("agent ingest could not open the registered result_path") from exc
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError("agent ingest registered result_path must be a regular file")
        file_identity = (int(file_stat.st_dev), int(file_stat.st_ino))
        with os.fdopen(descriptor, mode="r", encoding="utf-8") as handle:
            descriptor = -1
            verified_text = handle.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if any(
        other is not task
        and (
            other.get("result_file_device"),
            other.get("result_file_inode"),
        )
        == file_identity
        for other in _stage_tasks(state, stage)
    ):
        raise ValueError("agent ingest result file was already ingested by another task")
    if any(
        other is not task
        and other.get("result_path")
        and _same_regular_file_identity(
            Path(str(other["result_path"])),
            file_identity,
        )
        for other in _stage_tasks(state, stage)
    ):
        raise ValueError("agent ingest result_path aliases another task's result file")
    task["result_file_device"], task["result_file_inode"] = file_identity
    return verified_text


def _same_regular_file_identity(path: Path, identity: tuple[int, int]) -> bool:
    try:
        file_stat = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISREG(file_stat.st_mode) and (
        int(file_stat.st_dev),
        int(file_stat.st_ino),
    ) == identity


def _write_seed_brief(run_dir: Path, capped_slices: list[dict], report_name: str) -> None:
    lines = [
        f"# Seed brief — {report_name}",
        "",
        "Draft the report skeleton bundle: one section shell per slice below,",
        "in this order. Return JSON: {\"sections\": [{\"section_id\", \"title\", \"body\"}]}.",
        "Use only the facts provided; do not invent numbers. Return JSON only.",
        "",
    ]
    for s in capped_slices:
        lines.append(f"- {_slug(s['title'])}: {s['title']}")
    (run_dir / "briefs" / "seed.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_spine_candidate_briefs(
    run_dir: Path,
    capped_slices: list[dict],
    facts_json: dict,
    report_name: str,
) -> list[Path]:
    """Create two isolated briefs so the second spine cannot anchor on the first."""
    payload = {
        "report_name": report_name,
        "facts_hash": facts_json.get("facts_hash"),
        "registry_hash": facts_json.get("registry_hash"),
        "domain_slices": capped_slices,
        "shared_spine_facts": facts_json.get("shared_spine_facts") or [],
        "non_additive_ledger": facts_json.get("non_additive_ledger") or {},
        "absent_link_registry": facts_json.get("absent_link_registry") or [],
        "platform_semantics": facts_json.get("platform_semantics") or {},
    }
    paths: list[Path] = []
    for candidate_id in ("candidate-a", "candidate-b"):
        path = Path(run_dir) / "briefs" / f"spine_{candidate_id}.md"
        lines = [
            f"# Independent spine candidate — {candidate_id}",
            "",
            "你独立提出一套经营主线。不要寻找、引用或猜测另一位候选人的答案。",
            "主线必须先解释经营结果和钱，再连接流量、内容、商品、退款等机制；",
            "会计恒等式与弱因果必须分开。只绑定下方已有 fact_id，不重算、不发明数字。",
            "metric 名称、单位、口径、周期、aggregation 均由注册表快照解释，不能自行改名。",
            "platform_semantics 是只读平台口径参考；没有 accepted reference 时标记未知，不得猜测映射。",
            "",
            "返回 JSON only:",
            '{"candidate_id":"' + candidate_id + '","spine_brief":{'
            '"decomposition_backbone":[...],"headline_candidate":"...",'
            '"section_callbacks":{...},"broadcast_facts":[...]}}',
            "",
            "```json",
            json.dumps(payload, ensure_ascii=False, indent=2),
            "```",
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def _write_spine_adjudication_brief(run_dir: Path, state: dict) -> Path:
    path = Path(run_dir) / "briefs" / "spine_adjudication.md"
    candidates = state.get("_spine_candidates") or {}
    lines = [
        "# Spine adjudication",
        "",
        "比较两套独立主线，选择证据覆盖更完整、经营解释更清晰的一套。",
        "你可以做最小合并，但不能偷偷写第三套无来源主线；必须保留选择、拒绝理由和未决异议。",
        "所有 anchor_fact_ids 必须来自候选和当前事实快照。",
        "",
        "返回 JSON only:",
        '{"selected_candidate_id","spine_brief":{...},'
        '"rejected_reasons":[{"candidate_id","reason"}],"unresolved_dissent":[]}',
        "",
        "```json",
        json.dumps({"candidates": candidates}, ensure_ascii=False, indent=2),
        "```",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _quality_slice_payload(
    slice_doc: dict,
    spine: dict,
    tables_catalog: dict,
    platform_semantics: dict | None = None,
) -> dict:
    title = str(slice_doc.get("title") or "")
    spine_brief = spine.get("spine_brief") if isinstance(spine, dict) else {}
    spine_brief = spine_brief if isinstance(spine_brief, dict) else {}
    callbacks = spine_brief.get("section_callbacks") or {}
    callback = callbacks.get(title) or callbacks.get(_slug(title)) or {}
    return {
        "section_id": _slug(title),
        "title": title,
        "facts": slice_doc.get("facts") or [],
        "reading": slice_doc.get("reading") or {},
        "spine_callback": callback,
        "broadcast_facts": spine_brief.get("broadcast_facts") or [],
        "available_tables": tables_catalog,
        "platform_semantics": platform_semantics or {},
    }


def _write_quality_fan_briefs(
    run_dir: Path,
    capped_slices: list[dict],
    spine: dict,
    tables_catalog: dict[str, list[str]],
    platform_semantics: dict | None = None,
) -> list[Path]:
    """Write claim-only domain briefs after the spine has been adjudicated."""
    paths: list[Path] = []
    for index, slice_doc in enumerate(capped_slices):
        payload = _quality_slice_payload(
            slice_doc,
            spine,
            tables_catalog,
            platform_semantics,
        )
        path = Path(run_dir) / "briefs" / f"fan_{index:02d}_{payload['section_id']}.md"
        lines = [
            f"# Domain writer — {payload['title']}",
            "",
            "先钱后机制，写出清楚、可判断的 section claims；本阶段不要设计图表。",
            "每个数字只能写成 {tN} 并绑定 payload 中真实 fact_id；不得自行解释单位、口径、",
            "周期或 aggregation，它们由注册表和确定性层负责。必须回应 spine_callback；",
            "如事实与主线冲突，写入 spine_dissent，不要强行顺从。",
            "platform_semantics 仅用于解释平台口径；不得据此改映射或补造缺失数据。",
            "",
            '返回 JSON only: {"section_id","title","claims":[...],'
            '"spine_callbacks":[...],"spine_dissent":null|{...}}',
            "",
            "```json",
            json.dumps(payload, ensure_ascii=False, indent=2),
            "```",
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def _write_domain_challenge_briefs(run_dir: Path, state: dict) -> list[Path]:
    paths: list[Path] = []
    for index, section_id in enumerate(state.get("_section_order") or []):
        section = (state.get("sections") or {}).get(section_id)
        if not isinstance(section, dict):
            continue
        path = Path(run_dir) / "briefs" / f"challenge_{index:02d}_{section_id}.md"
        lines = [
            f"# Domain challenger — {section.get('title', section_id)}",
            "",
            "你是反方，不直接改稿。逐 claim 检查遗漏、反例、夸大、口径误读和行动跳跃；",
            "每个问题必须指向 claim_id。没有实质问题就明确 accept，禁止为了显得有用而挑刺。",
            "",
            '返回 JSON only: {"section_id","issues":[{"claim_id","severity",'
            '"reason","suggested_resolution"}],"recommendation":"accept|revise"}',
            "",
            "```json",
            json.dumps(
                {"section": section, "spine": state.get("_spine") or {}},
                ensure_ascii=False,
                indent=2,
            ),
            "```",
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def _write_domain_adjudication_briefs(run_dir: Path, state: dict) -> list[Path]:
    paths: list[Path] = []
    challenges = state.get("_domain_challenges") or {}
    for index, section_id in enumerate(state.get("_section_order") or []):
        section = (state.get("sections") or {}).get(section_id)
        if not isinstance(section, dict):
            continue
        path = Path(run_dir) / "briefs" / f"domain_adjudication_{index:02d}_{section_id}.md"
        lines = [
            f"# Domain adjudicator — {section.get('title', section_id)}",
            "",
            "裁决写手与反方：只接受有事实依据的问题，输出本域最终 section。",
            "可删除或定向修改 claim，但不得改写任何 fact 值、单位、口径或 aggregation；",
            "所有未被挑战的 claim 必须原样保留。",
            "",
            '返回 JSON only: {"section_id","title","claims":[...],'
            '"spine_callbacks":[...],"adjudication_notes":[...]}',
            "",
            "```json",
            json.dumps(
                {
                    "section": section,
                    "challenge": challenges.get(section_id) or {},
                    "spine": state.get("_spine") or {},
                },
                ensure_ascii=False,
                indent=2,
            ),
            "```",
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def _tables_catalog(result_tables: object) -> dict[str, list[str]]:
    """Compact ``{table_name: [column names]}`` inventory of the already-computed
    ``result.tables`` — the schema the fan brief hands the curation agent so it can
    name a REAL ``source.table`` + ``columns`` instead of guessing blind (whereupon the
    gate drops the view and the section silently degrades to prose-only).

    NAMES ONLY — never row values, so the brief stays number-free by construction and no
    new fabrication channel opens (the deterministic engine still fills every displayed
    number from ``result.tables``, independent of what the agent was shown). Column order
    is first-seen across rows (deterministic → stable brief output). Empty/garbage tables
    and tables with no dict rows are dropped (nothing authorable there). A missing/garbage
    ``result_tables`` yields ``{}`` so prose-only runs still get a valid brief. Never raises.
    """
    catalog: dict[str, list[str]] = {}
    if not isinstance(result_tables, dict):
        return catalog
    for name, rows in result_tables.items():
        if not isinstance(name, str) or not name or not isinstance(rows, (list, tuple)):
            continue
        cols: list[str] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            for col in row.keys():
                if isinstance(col, str) and col not in seen:
                    seen.add(col)
                    cols.append(col)
        if cols:
            catalog[name] = cols
    return catalog


def _write_fan_briefs(
    run_dir: Path,
    capped_slices: list[dict],
    tables_catalog: dict[str, list[str]],
    platform_semantics: dict | None = None,
) -> list[Path]:
    paths: list[Path] = []
    briefs = run_dir / "briefs"
    for idx, s in enumerate(capped_slices):
        section_id = _slug(s["title"])
        payload = {
            "section_id": section_id,
            "title": s["title"],
            "facts": s.get("facts", []),
            "reading": s.get("reading", {}),
            # NAMES ONLY (no values) — the schema the curation agent selects source.table
            # + columns from; the same catalog is shared by every section (the gate imposes
            # no per-section allowlist; relevance is governed by supports_claim discipline).
            "available_tables": tables_catalog,
            "platform_semantics": platform_semantics or {},
        }
        body = [
            f"# Fan brief — {s['title']}",
            "",
            f"为版块 `{section_id}` 写「claims + 策展视图」。数字只出现在 claim 的 number_tokens 里,",
            "由确定性引擎从下方 facts 回填 —— 你只写句子模板(用 {tN} 占位)与结构,绝不写裸数字。",
            "",
            "每条 claim 的结构:",
            '  {"claim_id","section_id","claim_kind":"measurement|mechanism|sizing",',
            '   "sentence":"…{t0}…(仅含 {tN} 占位,不得含任何裸数字)",',
            '   "number_tokens":[{"token_id":"t0","fact_id":"<下方 facts 里的 fact_id>",'
            '"expected_metric_key":"<该 fact 的 metric_key>"}],',
            '   "entity_refs":[],"confidence":"强|中|弱"}',
            "每个 number_token 的 fact_id 必须精确等于下方某个 facts[].fact_id;",
            "没有 fact_id 的 fact 是标签(非数值),不能被 number_token 绑定。",
            "platform_semantics 仅作平台定义参考；不得据此改映射、改数或猜测未审核绑定。",
            "",
            "curated_views(每域至少给 1 表 + 1 图,无上限:本域有几个值得展示的角度就给几个,"
            "把数据讲透;仅当本域 available_tables 里确无可画的表时,才可省略图并在对应 claim 里"
            "说明原因 —— 缺图会被记为 visuals_missing):",
            '  必填 template, 只允许 "comparison_table"|"ranking_table"|"trend_line"|"breakdown_waterfall"|"share_bar"|"horizontal_bar";',
            '  ("horizontal_bar" 是横向条形图:类目标签较长时(搜索词/SKU 名/长中文)比 share_bar 更易读,优先选它;)',
            "  先按数据形态选最合适的呈现形式:随时间变化用 trend_line、构成占比用 share_bar/占比条、"
            "增减分解用 breakdown_waterfall、并列对照才用表 —— 形态选错会被 revise;",
            '  source 形如 {"task_id":"…","table":"<下方 available_tables 里的表名>"};',
            "  columns 必须是该表列名的子集;只做选列/排序/TopN,严禁聚合或改数;",
            '  图表必须同时给 chart, 如 {"x":"date","y":"gmv"} 或 {"x":"carrier","y":"gmv_share"};',
            "  supports_claim 必须指向本域某条 claim_id;标题/图注/列标签是纯文字,不得含裸数字;",
            "  只挑与本域 claim 相关的表(available_tables 是全量目录,并非都要用);",
            "  available_tables 只给表名与列名(不含数值)—— 人类可读列名写进 column_labels,",
            "  别把带数字的原始表名/列名抄进图注(会被判为裸数字而丢弃该视图)。",
            "",
            'Return JSON only: {"section_id","title","claims":[...],"curated_views":[...]}; 不要使用 type/view_type 代替 template.',
            "",
            "```json",
            json.dumps(payload, ensure_ascii=False, indent=2),
            "```",
        ]
        path = briefs / f"fan_{idx:02d}_{section_id}.md"
        path.write_text("\n".join(body) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def _claim_summaries(state: dict) -> list[dict]:
    """Flatten the recorded fan claims into compact summaries so the synth agent can
    reference real ``claim_id``s when assembling the first screen. Ordered by the
    prepared slice order (falling back to any extra recorded sections at the end)."""
    sections = state.get("sections", {})
    order = state.get("_section_order", [])
    ordered_ids = [sid for sid in order if sid in sections]
    seen = set(ordered_ids)
    ordered_ids += [sid for sid in sections if sid not in seen]
    out: list[dict] = []
    for sid in ordered_ids:
        section = sections[sid]
        for claim in section.get("claims", []):
            if not isinstance(claim, dict):
                continue
            out.append(
                {
                    "claim_id": claim.get("claim_id", ""),
                    "section_id": claim.get("section_id", section.get("section_id", sid)),
                    "claim_kind": claim.get("claim_kind", ""),
                    "sentence": claim.get("sentence", ""),
                    "number_tokens": list(claim.get("number_tokens") or []),
                    "entity_refs": list(claim.get("entity_refs") or []),
                    "confidence": claim.get("confidence", ""),
                    "causal_link": claim.get("causal_link"),
                    "next_test": claim.get("next_test"),
                    "spine_ref": claim.get("spine_ref"),
                }
            )
    return out


def _write_synth_brief(run_dir: Path, state: dict) -> None:
    """Write the synth brief: surface every recorded fan claim (so synth can reference
    real ``claim_id``s) and request the bundle-level first screen. The synth agent
    invents no numbers — spine/panel entries stay claim-like dicts whose ``{tN}`` tokens
    the deterministic engine later fills from facts.json."""
    summaries = _claim_summaries(state)
    lines = [
        "# Synth brief — 组装首屏与全局综合",
        "",
        "下面是各版块 fan agent 已产出的 claims 摘要。据此组装「首屏」:挑出最能支撑主结论的",
        "claim 进 spine/panel(整条 claim-like dict,含 sentence 与 number_tokens;数字仍由确定性",
        "引擎回填,你绝不写裸数字),并给出 headline / mechanism / cannot_say / spine_final。",
        "",
        'Return JSON only: {"headline","first_screen":{"spine":[…],"panel":[…],"actions":[…]},'
        '"action_cards":[…],"mechanism":[…],"cannot_say":[…],"spine_final":{…}}.',
        "spine/panel 每条须是 claim-like dict(可直接复用下方某条 claim,或组合其 claim_id);",
        "复用/新写的 claim 都遵守同一数字纪律:sentence 仅含 {tN} 占位、绝不含任何裸数字,",
        "且句中出现的每个 {tN} 必须与 number_tokens 里声明的 token_id 精确一一对应(多一个或少一个都会被判 MAGNITUDE_UNBOUND 而拒绝);",
        "actions 是首屏纯文字摘要,不得含业务数字;action_cards 必须显式给出(允许空数组),",
        "每张行动卡绑定 primary_fact_id、supporting_claim_ids、负责人、步骤、许可与停止规则;",
        "行动卡中的业务数字也只能用 {tN}/number_tokens。cannot_say 是本次数据答不了的问题。",
        "",
        "mechanism 是「跨模块因果主线」:把不同版块的 claim 按因果顺序串成一条链,回答「为什么会这样」。",
        "每个元素形如 {\"claim_id\":\"<下方某条 claim_id>\",\"link\":\"<可选的纯文字连接词,如 因此/结果/根源在于>\"};",
        "只引用已存在的 claim_id(数字随该 claim 回填,你不另写数字);link 是连接词,绝不含任何数字/月份/百分比,",
        "含数字会被丢弃。优先跨版块选 claim(如 流量→内容→退款),让主线把各域串成一个故事,而非罗列同域结论。",
        "",
        "## 已产出的 claims",
        "",
        "```json",
        json.dumps(summaries, ensure_ascii=False, indent=2),
        "```",
    ]
    (run_dir / "briefs" / "synth.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_visual_curation_brief(run_dir: Path, state: dict) -> Path:
    """Ask a dedicated curator for view specs only, after claims are locked."""
    path = Path(run_dir) / "briefs" / "visual_curation.md"
    tables = _load_result_tables(run_dir)
    lines = [
        "# Independent visual curation",
        "",
        "你只负责把已经裁决的 claim 配成最合适的表或图，不改 claim、不写新结论。",
        "每个视图必须绑定 supports_claim 和真实 source.table；columns 只能来自表目录。",
        "仅选列、排序、TopN，不聚合、不重算。column_labels 只把真实字段翻译成商家可读纯文字，",
        "不得改指标定义、单位、口径或数值；字段解释不直接铺在 HTML 中。",
        "没有增量阅读价值的视图不要放，避免把原始数据整表倾倒给用户。",
        "确定性渲染层会另行保留经营诊断明细；搜索词、笔记、SKU、渠道、人群、退款等高价值",
        "结果表不得删除。策展视图负责提炼重点，不负责裁掉这些诊断明细。",
        "每个 decision-critical claim 必须写一条 visual_coverage：要么 retained 并列出",
        "同 claim 的 view_ids，要么 omitted 并给出结构化 reason_code 与具体 reason。",
        "",
        '返回 JSON only: {"sections":[{"section_id","curated_views":[...],'
        '"visual_coverage":[...]}]}',
        "",
        "```json",
        json.dumps(
            {
                "sections": list((state.get("sections") or {}).values()),
                "decision_critical_claim_ids": sorted(
                    _decision_critical_claim_ids(_bundle_from_state(state))
                ),
                "available_tables": _tables_catalog(tables),
            },
            ensure_ascii=False,
            indent=2,
        ),
        "```",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _validate_sidecar_snapshot(results: dict, facts_json: dict) -> None:
    results_versioned = "canonical_version" in results
    facts_versioned = "canonical_version" in facts_json
    if not results_versioned and not facts_versioned:
        return
    if results_versioned != facts_versioned:
        raise ValueError("sidecar metric snapshot mismatch: canonical_version")
    for field in (
        "canonical_version",
        "facts_hash",
        "registry_hash",
        "metric_mapping",
        "platform_semantics",
    ):
        if results.get(field) != facts_json.get(field):
            raise ValueError(f"sidecar metric snapshot mismatch: {field}")


def _write_run_manifest(
    run_dir: Path,
    *,
    results_hash: str,
    facts_json: dict,
    result_tables: dict,
    report_name: str,
) -> dict:
    from xhs_ceramics_analytics.reporting.frozen_narrative import (
        narrative_schema_version,
        renderer_version,
        result_tables_hash,
    )

    snapshot = {
        "facts_hash": facts_json.get("facts_hash"),
        "results_hash": results_hash,
        "result_tables_hash": result_tables_hash(result_tables),
        "registry_hash": facts_json.get("registry_hash"),
        "contract_hash": narrative_schema_version(),
        "renderer_version": renderer_version(),
    }
    manifest = {
        "workflow_version": QUALITY_WORKFLOW_VERSION,
        "run_id": hashlib.sha256(
            f"{report_name}:{snapshot['facts_hash']}:{snapshot['results_hash']}".encode("utf-8")
        ).hexdigest()[:20],
        "report_name": report_name,
        "authorization": {"decision": "authorized", "source": "user"},
        "snapshot": snapshot,
        "delivery": {"surface": "single_html"},
    }
    _write_json_atomic(Path(run_dir) / "run_manifest.json", manifest)
    return manifest


def prepare_run(
    run_dir,
    *,
    results: dict,
    facts_json: dict,
    report_name: str,
    project_root=None,
    force: bool = False,
    multi_agent_authorized: bool = False,
    multi_agent_declined: bool = False,
    multi_agent_unavailable: bool = False,
    workflow_version: str | None = None,
) -> dict:
    """Initialize a run directory: state.json + seed/fan briefs + domain_slices.json.

    Raises FileExistsError if an unfinished run already exists and force is False.
    """
    _validate_sidecar_snapshot(results, facts_json)
    versioned_sidecars = "canonical_version" in results and "canonical_version" in facts_json
    authorization_flags = sum(
        bool(flag)
        for flag in (
            multi_agent_authorized,
            multi_agent_declined,
            multi_agent_unavailable,
        )
    )
    if authorization_flags > 1:
        raise ValueError("multi-agent authorization state must be unambiguous")
    if workflow_version not in {
        None,
        QUALITY_WORKFLOW_VERSION,
        DETERMINISTIC_WORKFLOW_VERSION,
        LEGACY_WORKFLOW_VERSION,
    }:
        raise ValueError(f"unknown workflow_version {workflow_version!r}")
    selected_workflow = workflow_version
    if selected_workflow is None:
        if versioned_sidecars and (multi_agent_declined or multi_agent_unavailable):
            selected_workflow = DETERMINISTIC_WORKFLOW_VERSION
        elif versioned_sidecars:
            selected_workflow = QUALITY_WORKFLOW_VERSION
        else:
            selected_workflow = LEGACY_WORKFLOW_VERSION
    quality_workflow = selected_workflow == QUALITY_WORKFLOW_VERSION
    deterministic_workflow = selected_workflow == DETERMINISTIC_WORKFLOW_VERSION
    if quality_workflow and not versioned_sidecars:
        raise ValueError("quality-v2 requires versioned facts/results sidecars")
    if quality_workflow and not multi_agent_authorized:
        raise ValueError(
            "explicit multi-agent authorization is required for a versioned quality run"
        )
    if deterministic_workflow and not versioned_sidecars:
        raise ValueError("deterministic-v2 requires versioned facts/results sidecars")
    if deterministic_workflow and not (multi_agent_declined or multi_agent_unavailable):
        raise ValueError(
            "an explicit decline or unavailable-host reason is required for deterministic-v2"
        )
    run_dir = Path(run_dir)
    existing = _load_state(run_dir)
    if existing is not None and existing.get("stage") not in _TERMINAL_STAGES and not force:
        raise FileExistsError(
            f"run at {run_dir} is at stage {existing.get('stage')!r}; pass force=True to overwrite"
        )

    (run_dir / "briefs").mkdir(parents=True, exist_ok=True)

    slices = list(results.get("domain_slices", []))
    if selected_workflow == LEGACY_WORKFLOW_VERSION:
        capped, merged = _cap_slices(slices)
    else:
        capped, merged = list(slices), []

    (run_dir / "domain_slices.json").write_text(
        json.dumps(
            {
                "capped": capped,
                "merged_sections": merged,
                "blocked_modules": list(results.get("blocked_modules", [])),
                "platform_semantics": results.get("platform_semantics") or {},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    # Resolve the already-computed result.tables up front: it is BOTH the numeric-trust
    # source persisted below (for the curated-view engine + gate) AND the schema the fan
    # brief exposes so the curation agent can name a real source.table + columns instead
    # of guessing blind. Absent/garbage degrades to {} → prose-only. (Persist happens later
    # so the write stays alongside facts.json; the value is computed once here.)
    tables = results.get("result_tables")
    if not isinstance(tables, dict):
        tables = results.get("tables") if isinstance(results.get("tables"), dict) else {}
    results_hash = _stable_hash(results)

    frozen_cache = None
    cache_status = "not_applicable"
    if quality_workflow:
        from xhs_ceramics_analytics.reporting.frozen_narrative import (
            is_cache_hit,
            load_frozen,
        )

        cache_path = state_dir(project_root) / "frozen_narrative.json"
        cache_status = "miss"
        try:
            candidate = load_frozen(cache_path)
        except ValueError:
            cache_status = "invalid"
        else:
            if is_cache_hit(
                candidate,
                facts_json.get("facts_hash", ""),
                results_hash=results_hash,
                result_tables=tables,
            ):
                cache_report = _run_gate(
                    candidate.get("narrative_bundle") or {},
                    facts_json,
                    tables,
                )
                if cache_report.status == "PASS":
                    frozen_cache = candidate
                    cache_status = "hit"
                else:
                    cache_status = "invalid"

    if quality_workflow and frozen_cache is None:
        seed_briefs = _write_spine_candidate_briefs(
            run_dir, capped, facts_json, report_name
        )
        fan_briefs: list[Path] = []
    elif quality_workflow:
        seed_briefs = []
        fan_briefs = []
    else:
        _write_seed_brief(run_dir, capped, report_name)
        seed_briefs = [run_dir / "briefs" / "seed.md"]
        fan_briefs = _write_fan_briefs(
            run_dir,
            capped,
            _tables_catalog(tables),
            results.get("platform_semantics") or {},
        )

    state = {
        "stage": "cache_hit" if frozen_cache is not None else "seed",
        "workflow_version": selected_workflow,
        "authorization_decision": (
            "authorized"
            if quality_workflow
            else (
                "denied"
                if multi_agent_declined
                else "unsupported" if multi_agent_unavailable else None
            )
        ),
        "report_name": report_name,
        "canonical_version": facts_json.get("canonical_version"),
        "facts_hash": facts_json.get("facts_hash", ""),
        "results_hash": results_hash,
        "registry_hash": facts_json.get("registry_hash"),
        "metric_mapping_status": (
            facts_json.get("metric_mapping", {}).get("status")
            if isinstance(facts_json.get("metric_mapping"), dict)
            else None
        ),
        "merged_sections": merged,
        "_section_order": [_slug(s["title"]) for s in capped],
        "sections": {},
        "history": ["prepared"],
        "degradation_reason": None,
        "project_root": str(project_root) if project_root else None,
    }
    _set_stage_tasks(
        state,
        "seed",
        [
            {
                "brief": path,
                "role": "spine_candidate" if quality_workflow else "seed",
                "candidate_id": path.stem.removeprefix("spine_") if quality_workflow else None,
            }
            for path in seed_briefs
        ],
    )
    state["_fan_tasks"] = [
        {
            "brief": str(path),
            "section_id": _slug(capped[idx]["title"]),
        }
        for idx, path in enumerate(fan_briefs)
    ]
    if quality_workflow:
        manifest = _write_run_manifest(
            run_dir,
            results_hash=results_hash,
            facts_json=facts_json,
            result_tables=tables,
            report_name=report_name,
        )
        state["run_id"] = manifest["run_id"]
        state["cache_status"] = cache_status
        if frozen_cache is not None:
            state["_bundle"] = frozen_cache["narrative_bundle"]
            _set_stage_tasks(state, "cache_hit", [])
    _write_state(run_dir, state)
    # persist facts.json alongside state for downstream gate/fallback
    (run_dir / "facts.json").write_text(
        json.dumps(facts_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # persist the already-computed result.tables (numeric-trust source for the
    # curated-view engine + gate; resolved above so the brief could expose its schema).
    (run_dir / _RESULT_TABLES_FILE).write_text(
        json.dumps(tables, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if frozen_cache is not None:
        return finalize_narrative(
            run_dir,
            project_root=project_root,
            cache_hit=True,
            write_cache=False,
        )
    return state


def _load_result_tables(run_dir: Path) -> dict:
    """Load the persisted ``result.tables``. Missing/garbage degrades to ``{}`` so
    the curated-view path silently falls back to prose-only. Never raises."""
    path = Path(run_dir) / _RESULT_TABLES_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _run_gate(bundle: dict, facts_json: dict, result_tables: dict):
    """Call ``run_gate`` with ``result_tables`` only when there are tables to police.

    When no tables were provided (today's prose-only runs, and the existing test
    suite's 2-arg ``run_gate`` monkeypatches), this stays a 2-arg call so the gate's
    behavior and signature expectations are unchanged. When tables ARE present the
    3rd arg lets the gate enforce the curated-view trust/anti-dump rules."""
    if result_tables:
        return run_gate(bundle, facts_json, result_tables)
    return run_gate(bundle, facts_json)


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

_EXPECTED_STATUS = {
    "seed": {"seed"},
    "spine_adjudication": {"spine_adjudication"},
    "fan": {"fan"},
    "domain_challenge": {"domain_challenge"},
    "domain_adjudication": {"domain_adjudication"},
    "synth": {"synth"},
    "visual_curation": {"visual_curation"},
    "patch": {"patch"},
    "review": {"review"},
    "continuity": {"continuity"},
    "merchant_review": {"merchant_review"},
    "merchant_patch": {"merchant_patch"},
}

_QUALITY_STAGE_SCHEMAS = {
    "seed": "spine_candidate.json",
    "spine_adjudication": "spine_adjudication.json",
    "fan": "section_bundle.json",
    "domain_challenge": "challenge_report.json",
    "domain_adjudication": "domain_adjudication.json",
    "synth": "synthesis_output.json",
    "visual_curation": "visual_curation.json",
    "review": "review_verdict.json",
    "continuity": "continuity_edit.json",
    "merchant_review": "merchant_final_review.json",
}
_QUALITY_REVISION_STAGES = {"patch", "merchant_patch"}
_TASK_CONTRACT_VERSION = 1


@lru_cache(maxsize=1)
def _quality_schema_registry() -> Registry:
    registry = Registry()
    for schema_path in sorted(_SCHEMA_DIR.glob("*.json")):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema["$id"] = schema_path.resolve().as_uri()
        registry = registry.with_resource(
            schema["$id"], Resource.from_contents(schema)
        )
    return registry


@lru_cache(maxsize=None)
def _quality_schema_validator(schema_name: str) -> Draft202012Validator:
    schema_path = (_SCHEMA_DIR / schema_name).resolve()
    if not schema_path.is_file():
        raise FileNotFoundError(f"quality workflow schema is missing: {schema_path}")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["$id"] = schema_path.as_uri()
    return Draft202012Validator(schema, registry=_quality_schema_registry())


def _validate_against_quality_schema(payload, schema_name: str, *, location: str = "$") -> None:
    errors = sorted(
        _quality_schema_validator(schema_name).iter_errors(payload),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            tuple(str(part) for part in error.absolute_schema_path),
        ),
    )
    if errors:
        error = errors[0]
        suffix = "".join(
            f"[{part}]" if isinstance(part, int) else f".{part}"
            for part in error.absolute_path
        )
        raise ValueError(
            f"{schema_name} validation failed at {location}{suffix}: {error.message}"
        )


def _validate_quality_stage_payload(stage: str, payload) -> None:
    if stage in _QUALITY_REVISION_STAGES:
        if not isinstance(payload, list):
            raise ValueError(
                "targeted_revision.json validation failed at $: "
                f"{stage} output must be a targeted revision array"
            )
        for index, revision in enumerate(payload):
            _validate_against_quality_schema(
                revision, "targeted_revision.json", location=f"$[{index}]"
            )
        return

    schema_name = _QUALITY_STAGE_SCHEMAS.get(stage)
    if schema_name is not None:
        _validate_against_quality_schema(payload, schema_name)


@lru_cache(maxsize=None)
def _quality_schema_enum_hints(schema_name: str) -> dict[str, list]:
    def collect(schema: dict, prefix: str, seen: frozenset[str]) -> dict[str, list]:
        hints: dict[str, list] = {}
        ref = schema.get("$ref")
        if isinstance(ref, str) and ref and ref not in seen:
            ref_path = (_SCHEMA_DIR / ref).resolve()
            if ref_path.is_file():
                referenced = json.loads(ref_path.read_text(encoding="utf-8"))
                hints.update(collect(referenced, prefix, seen | {ref}))
        enum = schema.get("enum")
        if isinstance(enum, list) and prefix:
            hints[prefix] = list(enum)
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for key, child in properties.items():
                if isinstance(child, dict):
                    child_prefix = f"{prefix}.{key}" if prefix else str(key)
                    hints.update(collect(child, child_prefix, seen))
        items = schema.get("items")
        if isinstance(items, dict):
            hints.update(collect(items, f"{prefix}[]", seen))
        for keyword in ("oneOf", "anyOf", "allOf"):
            branches = schema.get(keyword)
            if isinstance(branches, list):
                for branch in branches:
                    if isinstance(branch, dict):
                        hints.update(collect(branch, prefix, seen))
        return hints

    schema_path = (_SCHEMA_DIR / schema_name).resolve()
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return collect(schema, "", frozenset({schema_name}))


def _quality_schema_name(stage: str) -> str | None:
    if stage in _QUALITY_REVISION_STAGES:
        return "targeted_revision.json"
    return _QUALITY_STAGE_SCHEMAS.get(stage)


def _task_current_round(state: dict, stage: str) -> int:
    if stage == "patch":
        return int(state.get("_patch_round") or 0)
    if stage == "merchant_patch":
        return int(state.get("_merchant_revision_rounds") or 0)
    if stage == "review":
        return int(state.get("_review_patch_rounds") or 0)
    return 0


def _task_with_contract(run_dir: Path, state: dict, task: dict) -> dict:
    enriched = dict(task)
    stage = str(task.get("stage") or state.get("stage") or "")
    schema_name = (
        _quality_schema_name(stage)
        if state.get("workflow_version") == QUALITY_WORKFLOW_VERSION
        else None
    )
    result_path = task.get("result_path")
    if result_path in (None, ""):
        brief_stem = Path(task.get("brief") or task.get("task_id") or "result").stem
        result_path = Path(run_dir) / "results" / f"{brief_stem}.json"
    controller_fields = {
        key: task[key]
        for key in (
            "task_id",
            "candidate_id",
            "section_id",
            "lens",
            "target_type",
            "target_id",
            "source_blocker_ids",
        )
        if task.get(key) not in (None, "")
    }
    current_round = _task_current_round(state, stage)
    if stage in _QUALITY_REVISION_STAGES:
        controller_fields["round"] = current_round
    dynamic_allowed = {
        "spine_link_ids": _spine_link_ids(state),
    }
    patch_review = state.get("_patch_review")
    if isinstance(patch_review, dict):
        dynamic_allowed["source_blocker_ids"] = sorted(
            {
                str(blocker_id)
                for issue in (patch_review.get("issues") or [])
                if isinstance(issue, dict)
                for blocker_id in (issue.get("source_blocker_ids") or [])
                if blocker_id not in (None, "")
            }
        )
    enriched.update(
        {
            "result_path": str(result_path),
            "schema_path": str(_SCHEMA_DIR / schema_name) if schema_name else None,
            "allowed_enums": (
                _quality_schema_enum_hints(schema_name) if schema_name else {}
            ),
            "controller_fields": controller_fields,
            "current_round": current_round,
            "dynamic_allowed": dynamic_allowed,
            "contract_version": _TASK_CONTRACT_VERSION,
        }
    )
    return enriched


def _bind_controller_field(payload: dict, field: str, expected) -> dict:
    if expected in (None, ""):
        return payload
    actual = payload.get(field)
    if actual not in (None, "") and str(actual) != str(expected):
        raise ValueError(
            f"controller field {field!r} conflicts with task contract: "
            f"expected {expected!r}, got {actual!r}"
        )
    return {**payload, field: expected}


def _payload_with_controller_fields(
    state: dict,
    stage: str,
    task: dict,
    payload,
):
    if stage in _QUALITY_REVISION_STAGES:
        if not isinstance(payload, list):
            return payload
        normalized = []
        current_round = _task_current_round(state, stage)
        for revision in payload:
            if not isinstance(revision, dict):
                normalized.append(revision)
                continue
            item = revision
            for field in ("target_type", "target_id", "source_blocker_ids"):
                item = _bind_controller_field(item, field, task.get(field))
            item = _bind_controller_field(item, "round", current_round)
            normalized.append(item)
        return normalized
    if not isinstance(payload, dict):
        return payload
    normalized = payload
    bindings = {
        "candidate_id": task.get("candidate_id") if stage == "seed" else None,
        "section_id": task.get("section_id"),
        "lens": task.get("lens") if stage == "review" else None,
    }
    for field, expected in bindings.items():
        normalized = _bind_controller_field(normalized, field, expected)
    return normalized


def _validate_quality_task_output(
    state: dict,
    stage: str,
    payload,
    *,
    source=None,
    section_id=None,
    lens=None,
    task_id=None,
) -> tuple[dict, object, list[dict]]:
    parsed_section = payload.get("section_id") if isinstance(payload, dict) else None
    task = _task_for_ingest(
        state,
        stage,
        source=source,
        section_id=(section_id or parsed_section) if task_id in (None, "") else None,
        lens=(lens or (payload.get("lens") if isinstance(payload, dict) else None))
        if task_id in (None, "")
        else None,
        task_id=task_id,
    )
    if task is None:
        raise ValueError(f"quality stage {stage!r} output does not identify one pending task")
    normalized = _payload_with_controller_fields(state, stage, task, payload)
    _validate_quality_stage_payload(stage, normalized)
    if stage == "visual_curation":
        _validate_visual_curation_coverage(state, normalized)
    return task, normalized, []


def _validate_visual_curation_coverage(state: dict, payload: dict) -> None:
    """Reject semantically incomplete visual curation before task completion."""
    bundle = _bundle_from_state(state)
    critical = _decision_critical_claim_ids(bundle)
    section_ids: set[str] = set()
    claim_sections: dict[str, str] = {}
    for section in bundle.get("sections") or []:
        if not isinstance(section, dict) or not section.get("section_id"):
            continue
        section_id = str(section["section_id"])
        section_ids.add(section_id)
        for claim in section.get("claims") or []:
            if not isinstance(claim, dict) or not claim.get("claim_id"):
                continue
            claim_id = str(claim["claim_id"])
            previous = claim_sections.setdefault(claim_id, section_id)
            if previous != section_id:
                raise ValueError(
                    f"claim {claim_id} belongs to multiple sections: "
                    f"{previous}, {section_id}"
                )
    claim_ids = set(claim_sections)
    views: dict[str, dict] = {}
    coverage: dict[str, dict] = {}
    duplicates: set[str] = set()
    payload_sections: set[str] = set()
    for section in payload.get("sections") or []:
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("section_id") or "")
        if section_id not in section_ids:
            raise ValueError(f"visual curation cites unknown section: {section_id}")
        if section_id in payload_sections:
            raise ValueError(f"visual curation has duplicate section: {section_id}")
        payload_sections.add(section_id)
        for view in section.get("curated_views") or []:
            if isinstance(view, dict) and view.get("view_id"):
                view_id = str(view["view_id"])
                view_section = str(view.get("section_id") or "")
                if view_section != section_id:
                    raise ValueError(
                        f"view {view_id} belongs to section {view_section}, "
                        f"not {section_id}"
                    )
                supports_claim = str(view.get("supports_claim") or "")
                claim_section = claim_sections.get(supports_claim)
                if claim_section is not None and claim_section != section_id:
                    raise ValueError(
                        f"view {view_id} supports claim {supports_claim} from section "
                        f"{claim_section}, not {section_id}"
                    )
                views[view_id] = view
        for record in section.get("visual_coverage") or []:
            if not isinstance(record, dict) or not record.get("claim_id"):
                continue
            claim_id = str(record["claim_id"])
            claim_section = claim_sections.get(claim_id)
            if claim_section is not None and claim_section != section_id:
                raise ValueError(
                    f"claim {claim_id} belongs to section {claim_section}, "
                    f"not {section_id}"
                )
            if claim_id in coverage:
                duplicates.add(claim_id)
            coverage[claim_id] = record
    if duplicates:
        raise ValueError(
            "visual coverage duplicates claim_id: " + ", ".join(sorted(duplicates))
        )
    unknown = sorted(set(coverage) - claim_ids)
    if unknown:
        raise ValueError("visual coverage cites unknown claim: " + ", ".join(unknown))
    missing = sorted(critical - set(coverage))
    if missing:
        raise ValueError(
            "decision-critical claim has no visual coverage: " + ", ".join(missing)
        )
    for claim_id, record in coverage.items():
        if record.get("status") != "retained":
            continue
        for view_id in record.get("view_ids") or []:
            view = views.get(str(view_id))
            if not isinstance(view, dict) or str(view.get("supports_claim") or "") != claim_id:
                raise ValueError(
                    f"visual coverage for {claim_id} references a missing or mismatched view: "
                    f"{view_id}"
                )
    for view_id, view in views.items():
        claim_id = str(view.get("supports_claim") or "")
        record = coverage.get(claim_id)
        if (
            not isinstance(record, dict)
            or record.get("status") != "retained"
            or view_id not in {str(value) for value in record.get("view_ids") or []}
        ):
            raise ValueError(f"view {view_id} is not retained by visual coverage")


def validate_output(
    run_dir,
    *,
    stage: str,
    source=None,
    text=None,
    section_id=None,
    lens=None,
    task_id=None,
) -> dict:
    """Validate one task result without changing run state or task status."""
    run_dir = Path(run_dir)
    state = _load_state(run_dir)
    if state is None:
        raise FileNotFoundError(f"no run at {run_dir}")
    allowed = _EXPECTED_STATUS.get(stage)
    if allowed is None:
        raise ValueError(f"unknown stage {stage!r}")
    if state.get("stage") not in allowed:
        raise ValueError(
            f"cannot validate {stage!r} while run is at stage {state.get('stage')!r}"
        )
    if text is None:
        if source is None:
            raise ValueError("provide either source or text")
        text = Path(source).read_text(encoding="utf-8")
    payload = extract_json(text)
    if state.get("workflow_version") == QUALITY_WORKFLOW_VERSION:
        task, payload, diagnostics = _validate_quality_task_output(
            state,
            stage,
            payload,
            source=source,
            section_id=section_id,
            lens=lens,
            task_id=task_id,
        )
    else:
        task = _task_for_ingest(
            state,
            stage,
            source=source,
            section_id=section_id,
            lens=lens,
            task_id=task_id,
        )
        if _stage_tasks(state, stage) and task is None:
            raise ValueError(f"{stage} output does not identify one pending task")
        diagnostics = []
    return {
        "valid": True,
        "task_id": task.get("task_id") if task is not None else None,
        "payload": payload,
        "diagnostics": diagnostics,
    }


def _scan_balanced(text: str):
    """Return the earliest balanced {...}/[...] substring that parses as JSON."""
    pairs = {"{": "}", "[": "]"}
    for start, ch in enumerate(text):
        closer = pairs.get(ch)
        if closer is None:
            continue
        depth = 0
        for i in range(start, len(text)):
            c = text[i]
            if c == ch:
                depth += 1
            elif c == closer:
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break  # this opener didn't yield JSON; try the next opener position
    return None


def extract_json(text: str):
    """Parse JSON tolerantly: raw, then fenced, then first balanced block."""
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    for match in _FENCE_RE.finditer(text):
        inner = match.group(1).strip()
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            continue
    scanned = _scan_balanced(text)
    if scanned is not None:
        return scanned
    raise ValueError("no parseable JSON found in text")


def _record_section(state: dict, section: dict) -> None:
    if not isinstance(section, dict):
        raise ValueError(f"section entry must be a JSON object, got {type(section).__name__}")
    title = section.get("title") or section.get("section_id") or "section"
    section_id = _slug(section.get("section_id") or title)
    recorded = {
        "section_id": section_id,
        "title": title,
        "body": section.get("body", ""),
    }
    # Preserve the agent-emitted claims (Option A: the renderer/gate/first_screen are
    # all built on ``section.claims[]``, not on prose ``body``). Kept as opaque dicts —
    # sentence carries only {tN}, number_tokens bind to real fact_ids, confidence is
    # gate-capped. Only added when present, so prose-only/skeleton sections that carry
    # no claims stay byte-identical to before.
    claims = section.get("claims")
    if isinstance(claims, (list, tuple)):
        recorded["claims"] = [c for c in claims if isinstance(c, dict)]
    # Preserve the agent-emitted curated view-specs so they survive into the
    # bundle (via _bundle_from_state) and reach the gate / review / render.
    views = section.get("curated_views")
    if isinstance(views, (list, tuple)):
        recorded["curated_views"] = [v for v in views]
    # Preserve section→spine callbacks so the gate's cross-section continuity check
    # (DANGLING_CALLBACK / MISSING_SPINE_CALLBACK) sees them.
    callbacks = section.get("spine_callbacks")
    if isinstance(callbacks, (list, tuple)):
        recorded["spine_callbacks"] = list(callbacks)
    for key in (
        "spine_dissent",
        "adjudication_notes",
        "table_ref",
        "chart_ref",
        "action_cards",
    ):
        if key in section:
            recorded[key] = section[key]
    state["sections"][section_id] = recorded


# Bundle-level synthesis the SYNTH agent assembles once, across all sections (spec
# §First screen). Captured into state['_synth'] and re-emitted by _bundle_from_state.
_BUNDLE_LEVEL_KEYS = (
    "first_screen",
    "headline",
    "action_cards",
    "cannot_say",
    "spine_final",
    "mechanism",
)
# What marks a synth dict as a section payload (vs a pure first-screen payload) — used
# so a bare {first_screen, headline, ...} is NOT mis-recorded as a bogus section.
_SECTION_MARKERS = ("section_id", "claims", "body", "curated_views")


def _capture_bundle_fields(state: dict, parsed) -> None:
    """Capture the synth agent's bundle-level synthesis into ``state['_synth']``.

    Only keys actually present are copied, so a synth output carrying just some of the
    fields (or none) degrades gracefully — a later ``_bundle_from_state`` simply omits
    the absent ones. Never raises."""
    if not isinstance(parsed, dict):
        return
    synth = state.setdefault("_synth", {})
    for key in _BUNDLE_LEVEL_KEYS:
        if key in parsed:
            synth[key] = parsed[key]


def _looks_like_section(parsed) -> bool:
    """True if a dict carries section content (so synth can still fold in a section it
    re-emits alongside the first screen), False for a pure bundle-level payload."""
    return isinstance(parsed, dict) and any(k in parsed for k in _SECTION_MARKERS)


def _ingest_synth(state: dict, text: str) -> None:
    """Ingest a SYNTH result: capture the bundle-level first screen AND record any
    section(s) the synth agent re-emitted. Unlike the generic path, a bare
    ``{first_screen, headline, …}`` payload (no section markers) records NO section, so
    it is never mistaken for a section titled 'section'. Never raises beyond a genuinely
    unparseable payload (extract_json), matching the other stages."""
    parsed = extract_json(text)
    if isinstance(parsed, list):
        for section in parsed:
            _record_section(state, section)
        return
    if isinstance(parsed, dict):
        if (
            state.get("workflow_version") == QUALITY_WORKFLOW_VERSION
            and not isinstance(parsed.get("action_cards"), list)
        ):
            raise ValueError("quality synth output must include action_cards as a list")
        _capture_bundle_fields(state, parsed)
        sections = parsed.get("sections")
        if isinstance(sections, list):
            for section in sections:
                _record_section(state, section)
        elif _looks_like_section(parsed):
            _record_section(state, parsed)
        return
    raise ValueError("ingested JSON is neither an object nor a list of sections")


def _merge_section_fields(state: dict, section_patch: dict) -> None:
    if not isinstance(section_patch, dict):
        return
    raw_id = section_patch.get("section_id") or section_patch.get("title")
    section_id = _slug(str(raw_id or "section"))
    existing = (state.get("sections") or {}).get(section_id)
    if not isinstance(existing, dict):
        _record_section(state, section_patch)
        return
    allowed = {
        "title",
        "body",
        "claims",
        "curated_views",
        "visual_coverage",
        "spine_callbacks",
        "spine_dissent",
        "adjudication_notes",
        "table_ref",
        "chart_ref",
        "action_cards",
    }
    state["sections"][section_id] = {
        **existing,
        **{key: value for key, value in section_patch.items() if key in allowed},
        "section_id": section_id,
    }


def _spine_link_ids(state: dict) -> list[str]:
    spine = state.get("_spine") or {}
    spine_brief = spine.get("spine_brief") if isinstance(spine, dict) else {}
    backbone = (
        spine_brief.get("decomposition_backbone")
        if isinstance(spine_brief, dict)
        else []
    )
    return [
        str(item["link_id"])
        for item in (backbone or [])
        if isinstance(item, dict) and item.get("link_id") not in (None, "")
    ]


def _normalize_spine_callbacks(
    run_dir: Path,
    state: dict,
    payload: dict,
    task: dict,
) -> dict:
    callbacks = payload.get("spine_callbacks")
    if not isinstance(callbacks, list):
        return payload
    allowed = _spine_link_ids(state)
    allowed_set = set(allowed)
    kept = [callback for callback in callbacks if callback in allowed_set]
    removed = [callback for callback in callbacks if callback not in allowed_set]
    if not removed:
        return payload
    record = {
        "stage": "domain_adjudication",
        "task_id": task.get("task_id"),
        "section_id": payload.get("section_id"),
        "field": "spine_callbacks",
        "removed": removed,
        "kept": kept,
        "allowed": allowed,
    }
    records = state.setdefault("_normalizations", [])
    records.append(record)
    audit_text = "\n".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True) for item in records
    )
    _write_text_atomic(Path(run_dir) / "normalizations.jsonl", audit_text + "\n")
    return {**payload, "spine_callbacks": kept}


def _ingest_quality_stage(
    run_dir: Path,
    state: dict,
    *,
    stage: str,
    text: str,
    source=None,
    section_id=None,
    lens=None,
    task_id=None,
) -> dict | None:
    """Handle quality-v2 stages; return ``None`` for legacy/shared stages."""
    if state.get("workflow_version") != QUALITY_WORKFLOW_VERSION:
        return None
    if stage not in {
        "seed",
        "spine_adjudication",
        "domain_challenge",
        "domain_adjudication",
        "visual_curation",
        "patch",
        "merchant_review",
        "merchant_patch",
    }:
        return None

    parsed = extract_json(text)
    parsed_target_id = None
    if stage == "patch" and isinstance(parsed, list) and len(parsed) == 1:
        item = parsed[0]
        if isinstance(item, dict):
            parsed_target_id = item.get("target_id")
    task = _task_for_ingest(
        state,
        stage,
        source=source,
        section_id=section_id or (parsed.get("section_id") if isinstance(parsed, dict) else None),
        lens=lens,
        target_id=parsed_target_id,
        task_id=task_id,
    )
    if task is None:
        raise ValueError(f"quality stage {stage!r} output does not identify one pending task")

    if stage == "seed":
        if not isinstance(parsed, dict) or not isinstance(parsed.get("spine_brief"), dict):
            raise ValueError("spine candidate output must include spine_brief")
        candidate_id = str(parsed.get("candidate_id") or task.get("candidate_id") or task["task_id"])
        state.setdefault("_spine_candidates", {})[candidate_id] = {
            **parsed,
            "candidate_id": candidate_id,
        }
    elif stage == "spine_adjudication":
        if not isinstance(parsed, dict) or not isinstance(parsed.get("spine_brief"), dict):
            raise ValueError("spine adjudication output must include spine_brief")
        state["_spine"] = parsed
    elif stage == "domain_challenge":
        if not isinstance(parsed, dict) or not parsed.get("section_id"):
            raise ValueError("domain challenge output must include section_id")
        state.setdefault("_domain_challenges", {})[_slug(str(parsed["section_id"]))] = parsed
    elif stage == "domain_adjudication":
        if not isinstance(parsed, dict):
            raise ValueError("domain adjudication output must be an object")
        parsed = _normalize_spine_callbacks(run_dir, state, parsed, task)
        _record_section(state, parsed)
    elif stage == "visual_curation":
        if not isinstance(parsed, dict) or not isinstance(parsed.get("sections"), list):
            raise ValueError("visual curation output must include sections")
        for section_patch in parsed["sections"]:
            if isinstance(section_patch, dict):
                _merge_section_fields(
                    state,
                    {
                        "section_id": section_patch.get("section_id"),
                        "curated_views": list(section_patch.get("curated_views") or []),
                        "visual_coverage": list(
                            section_patch.get("visual_coverage") or []
                        ),
                    },
                )
    elif stage == "patch":
        if not isinstance(parsed, list) or len(parsed) != 1:
            raise ValueError(
                "quality patch output must be a targeted revision array with exactly one item"
            )
        patch_review = state.get("_patch_review") or {}
        state["_bundle"] = _apply_merchant_revisions(
            state.get("_bundle") or _bundle_from_state(state),
            parsed,
            patch_review,
            expected_round=int(state.get("_patch_round") or 0),
        )
        _sync_recorded_visuals_from_bundle(state, state["_bundle"])
    elif stage == "merchant_review":
        if not isinstance(parsed, dict) or parsed.get("verdict") not in {"pass", "revise"}:
            raise ValueError("merchant review verdict must be pass or revise")
        _validate_merchant_review_payload(
            state.get("_bundle") or _bundle_from_state(state),
            parsed,
        )
        state["_merchant_review"] = parsed
    elif stage == "merchant_patch":
        if not isinstance(parsed, list):
            raise ValueError("merchant patch output must be a targeted revision array")
        state["_bundle"] = _apply_merchant_revisions(
            state.get("_bundle") or _bundle_from_state(state),
            parsed,
            state.get("_merchant_review") or {},
            expected_round=int(state.get("_merchant_revision_rounds") or 0),
        )
        _sync_recorded_visuals_from_bundle(state, state["_bundle"])

    _complete_task(state, task)
    state.setdefault("history", []).append(f"ingest:{stage}")
    _write_state(run_dir, state)
    return state


@_serialized_state_mutation
def ingest_output(
    run_dir,
    *,
    stage: str,
    source=None,
    text=None,
    section_id=None,
    lens=None,
    task_id=None,
) -> dict:
    """Ingest a sub-agent result for the given stage, guarding stage order."""
    run_dir = Path(run_dir)
    state = _load_state(run_dir)
    if state is None:
        raise FileNotFoundError(f"no run at {run_dir}")

    allowed = _EXPECTED_STATUS.get(stage)
    if allowed is None:
        raise ValueError(f"unknown stage {stage!r}")
    if state["stage"] not in allowed:
        raise ValueError(
            f"cannot ingest {stage!r} while run is at stage {state['stage']!r}"
        )

    verified_agent_text = _enforce_agent_ingest_contract(
        state,
        stage,
        source=source,
        text=text,
        task_id=task_id,
    )

    if verified_agent_text is not None:
        text = verified_agent_text
    elif text is None:
        if source is None:
            raise ValueError("provide either source or text")
        text = Path(source).read_text(encoding="utf-8")

    if state.get("workflow_version") == QUALITY_WORKFLOW_VERSION:
        validation = validate_output(
            run_dir,
            stage=stage,
            source=source,
            text=text,
            section_id=section_id,
            lens=lens,
            task_id=task_id,
        )
        text = json.dumps(validation["payload"], ensure_ascii=False)

    quality_state = _ingest_quality_stage(
        run_dir,
        state,
        stage=stage,
        text=text,
        source=source,
        section_id=section_id,
        lens=lens,
        task_id=task_id,
    )
    if quality_state is not None:
        return quality_state

    if stage == "review":
        # Reviewer verdicts, not sections. Parse tolerantly — garbled/unparseable
        # reviewer output records nothing (never raises); the advance step then
        # degrades any view with no usable verdict to a drop.
        try:
            parsed = extract_json(text)
        except ValueError:
            parsed = None
        parsed_section = parsed.get("section_id") if isinstance(parsed, dict) else None
        parsed_lens = parsed.get("lens") if isinstance(parsed, dict) else None
        task = _task_for_ingest(
            state,
            stage,
            source=source,
            section_id=section_id or parsed_section,
            lens=lens or parsed_lens,
            task_id=task_id,
        )
        if task is None and (task_id not in (None, "") or source is not None):
            raise ValueError("review output does not identify one pending task")
        ingested_keys = _ingest_review_verdicts(state, parsed)
        expected_keys = set(task.get("view_keys") or []) if task is not None else set()
        if task is not None and expected_keys and expected_keys.issubset(ingested_keys):
            _complete_task(state, task)
        state.setdefault("history", []).append("ingest:review")
        _write_state(run_dir, state)
        return state

    if stage == "synth":
        # SYNTH assembles the bundle-level first screen (+ may re-emit sections). Handled
        # separately so a pure first-screen payload is captured, not recorded as a section.
        task = _task_for_ingest(state, stage, source=source, task_id=task_id)
        if _stage_tasks(state, stage) and task is None:
            raise ValueError("synth output does not identify one pending task")
        _ingest_synth(state, text)
        _complete_task(state, task)
        state.setdefault("history", []).append("ingest:synth")
        _write_state(run_dir, state)
        return state

    parsed = extract_json(text)

    if stage == "continuity":
        if not isinstance(parsed, dict) or not isinstance(parsed.get("edits"), list):
            raise ValueError("continuity output must be an object with an edits list")
        state["_continuity_edits"] = [
            edit for edit in parsed["edits"] if isinstance(edit, dict)
        ]
        task = _task_for_ingest(state, stage, source=source, task_id=task_id)
        if _stage_tasks(state, stage) and task is None:
            raise ValueError("continuity output does not identify one pending task")
        _complete_task(state, task)
        state.setdefault("history", []).append("ingest:continuity")
        _write_state(run_dir, state)
        return state

    parsed_section = None
    if isinstance(parsed, dict):
        parsed_section = parsed.get("section_id")
        if parsed_section is None and isinstance(parsed.get("sections"), list):
            section_ids = {
                item.get("section_id")
                for item in parsed["sections"]
                if isinstance(item, dict) and item.get("section_id")
            }
            if len(section_ids) == 1:
                parsed_section = next(iter(section_ids))
    task = _task_for_ingest(
        state,
        stage,
        source=source,
        section_id=(section_id or parsed_section) if stage == "fan" else section_id,
        task_id=task_id,
    )
    if _stage_tasks(state, stage) and task is None:
        raise ValueError(f"{stage} output does not identify one pending task")

    if stage == "patch":
        patch_bundle = parsed.get("bundle") if isinstance(parsed, dict) else None
        if isinstance(patch_bundle, dict):
            _capture_bundle_fields(state, patch_bundle)
            for section_patch in patch_bundle.get("sections") or []:
                _merge_section_fields(state, section_patch)
        elif isinstance(parsed, dict) and isinstance(parsed.get("sections"), list):
            _capture_bundle_fields(state, parsed)
            for section_patch in parsed["sections"]:
                _merge_section_fields(state, section_patch)
        elif isinstance(parsed, dict):
            _merge_section_fields(state, parsed)
        elif isinstance(parsed, list):
            for section_patch in parsed:
                _merge_section_fields(state, section_patch)
        else:
            raise ValueError("patch output must be a bundle, section object, or section list")
        _complete_task(state, task)
        state.setdefault("history", []).append("ingest:patch")
        _write_state(run_dir, state)
        return state

    if isinstance(parsed, dict) and "sections" in parsed:
        for section in parsed["sections"]:
            _record_section(state, section)
    elif isinstance(parsed, dict):
        if section_id and "section_id" not in parsed:
            parsed = {**parsed, "section_id": section_id}
        _record_section(state, parsed)
    elif isinstance(parsed, list):
        for section in parsed:
            _record_section(state, section)
    else:
        raise ValueError("ingested JSON is neither an object nor a list of sections")

    _complete_task(state, task)
    state.setdefault("history", []).append(f"ingest:{stage}")
    _write_state(run_dir, state)
    return state


def _bundle_from_state(state: dict) -> dict:
    """Assemble a narrative bundle from the sections recorded so far, in prepared order.

    Ordered by the prepared slice order (recorded at ``prepare_run`` time), not by
    ingestion-completion order — under parallel fan-out, sections can complete out of
    order. Any recorded section whose id isn't in the prepared order (defensive) is
    appended at the end, stably. Builds a new list; never mutates ``state``.
    """
    sections = state.get("sections", {})
    order = state.get("_section_order", [])
    ordered = [sections[sid] for sid in order if sid in sections]
    ordered_ids = set(order)
    extras = [section for sid, section in sections.items() if sid not in ordered_ids]
    bundle: dict = {
        "facts_hash": state.get("facts_hash", ""),
        "sections": ordered + extras,
    }
    # Fold in the synth agent's bundle-level synthesis (first_screen / headline /
    # cannot_say / spine_final). Only keys actually captured are added, so a prose-only
    # or pre-synth run yields exactly {"sections": [...]} as before (backward compatible).
    synth = state.get("_synth") or {}
    for key in _BUNDLE_LEVEL_KEYS:
        if key in synth:
            bundle[key] = synth[key]
    if "spine_final" not in bundle:
        spine = state.get("_spine") or {}
        spine_brief = spine.get("spine_brief") if isinstance(spine, dict) else {}
        if isinstance(spine_brief, dict) and spine_brief.get("decomposition_backbone") is not None:
            bundle["spine_final"] = {
                "backbone": list(spine_brief.get("decomposition_backbone") or [])
            }
    return bundle


# ---- curated-view review stage (spec §Multi-Reviewer Review) --------------


def _view_key(section_id, view, idx: int) -> str:
    """Stable section-scoped identity for one curated view."""
    section = str(section_id or "section")
    if isinstance(view, dict):
        vid = view.get("view_id")
        if isinstance(vid, str) and vid.strip():
            return f"{section}::{vid.strip()}"
    return f"{section}::#{idx}"


def _iter_curated_views(bundle):
    """Yield ``(section_id, idx, view)`` for every curated view in the bundle.
    Never raises — malformed sections/views are skipped."""
    for section in (bundle or {}).get("sections") or []:
        if not isinstance(section, dict):
            continue
        section_id = section.get("section_id")
        views = section.get("curated_views")
        if not isinstance(views, (list, tuple)):
            continue
        for idx, view in enumerate(views):
            yield section_id, idx, view


def _bundle_has_curated_views(bundle) -> bool:
    """True iff at least one section carries a (dict) curated view to review."""
    for _sid, _idx, view in _iter_curated_views(bundle):
        if isinstance(view, dict):
            return True
    return False


def _iter_verdict_items(parsed):
    """Yield the per-view verdict dicts from a tolerant range of shapes. Never raises.

    Accepts ``{"verdicts": [...]}`` / ``{"views": [...]}`` / ``{"reviews": [...]}``,
    a bare list of verdict dicts, or a single ``{"verdict": ...}`` object.
    """
    if isinstance(parsed, dict):
        for field_name in ("verdicts", "views", "reviews"):
            seq = parsed.get(field_name)
            if isinstance(seq, (list, tuple)):
                for item in seq:
                    if isinstance(item, dict):
                        yield item
                return
        if "verdict" in parsed:
            yield parsed
    elif isinstance(parsed, (list, tuple)):
        for item in parsed:
            if isinstance(item, dict):
                yield item


def _ingest_review_verdicts(state: dict, parsed) -> set[str]:
    """Upsert verdicts by section + view + lens, making retries idempotent."""
    reviews = state.setdefault("_reviews", {})
    reasons = state.setdefault("_review_reasons", {})
    ingested: set[str] = set()
    default_section = parsed.get("section_id") if isinstance(parsed, dict) else None
    default_lens = parsed.get("lens") if isinstance(parsed, dict) else None
    for item in _iter_verdict_items(parsed):
        raw_key = item.get("view_id") or item.get("view_key")
        section_id = item.get("section_id") or default_section
        lens = item.get("lens") or default_lens
        verdict = item.get("verdict")
        if not (isinstance(raw_key, str) and raw_key and section_id and lens):
            continue
        normalized_verdict = verdict.strip().lower() if isinstance(verdict, str) else ""
        if normalized_verdict not in _KNOWN_VERDICTS:
            continue
        prefix = f"{section_id}::"
        key = raw_key if raw_key.startswith(prefix) else f"{prefix}{raw_key}"
        record = {"verdict": normalized_verdict}
        reason = item.get("reason")
        if isinstance(reason, str) and reason.strip():
            record["reason"] = reason.strip()
            reasons.setdefault(key, {})[str(lens)] = reason.strip()
        reviews.setdefault(key, {})[str(lens)] = record
        ingested.add(key)
    return ingested


def _review_verdict_values(value) -> list[str]:
    if isinstance(value, dict):
        return [
            record.get("verdict")
            for record in value.values()
            if isinstance(record, dict) and isinstance(record.get("verdict"), str)
        ]
    if isinstance(value, (list, tuple)):
        return [verdict for verdict in value if isinstance(verdict, str)]
    return []


def _quality_review_action(value, *, patch_rounds: int) -> str:
    """Resolve quality-v2 lenses by blocker semantics instead of majority vote."""
    if not isinstance(value, dict):
        return "drop"
    verdicts = {
        str(lens): str(record.get("verdict") or "").strip().lower()
        for lens, record in value.items()
        if isinstance(record, dict)
    }
    if set(verdicts) != set(_QUALITY_REVIEW_LENS_NAMES.values()):
        return "drop"
    evidence = verdicts["evidence_semantics"]
    merchant = verdicts["merchant_decision"]
    editorial = verdicts["editorial_visual"]
    if evidence == "drop" or editorial == "drop":
        return "drop"
    if merchant == "drop":
        return "drop"
    if "revise" in {evidence, merchant, editorial}:
        return "drop" if patch_rounds >= MAX_REVIEW_PATCH_ROUNDS else "patch"
    return "keep"


def _resolve_section_views(
    section_id,
    views,
    reviews: dict,
    patch_rounds: int,
    *,
    quality_workflow: bool = False,
):
    """Decide each view's fate for one section. Returns ``(kept_views, patched_keys)``.

    ``kept_views`` retains keep AND patch views (a patch view is re-authored in
    place); dropped views are omitted. ``patched_keys`` lists views still needing a
    patch round. Never raises."""
    kept: list = []
    patched: list[str] = []
    if not isinstance(views, (list, tuple)):
        return kept, patched
    for idx, view in enumerate(views):
        key = _view_key(section_id, view, idx)
        review_value = reviews.get(key, {})
        action = (
            _quality_review_action(review_value, patch_rounds=patch_rounds)
            if quality_workflow
            else _view_action(
                _review_verdict_values(review_value), patch_rounds=patch_rounds
            )
        )
        if action == "drop":
            continue
        kept.append(view)
        if action == "patch":
            patched.append(key)
    return kept, patched


def _sync_recorded_curated_views(
    state: dict,
    reviews: dict,
    patch_rounds: int,
    *,
    quality_workflow: bool = False,
    reasons: dict | None = None,
) -> None:
    """Apply the same drop decisions to ``state['sections']`` so a later patch
    rebuild (via :func:`_bundle_from_state`) does not resurrect a dropped view.
    Rebuilds each ``curated_views`` list; never raises."""
    for sid, section in (state.get("sections") or {}).items():
        if not isinstance(section, dict):
            continue
        views = section.get("curated_views")
        if not isinstance(views, (list, tuple)) or not views:
            continue
        kept, _patched = _resolve_section_views(
            section.get("section_id", sid),
            views,
            reviews,
            patch_rounds,
            quality_workflow=quality_workflow,
        )
        section["curated_views"] = kept
        if quality_workflow:
            section["visual_coverage"] = _coverage_after_view_drop(
                section,
                kept,
                reason_code="dropped_by_review",
                review_reasons=reasons or {},
            )


def _coverage_after_view_drop(
    section: dict,
    kept_views,
    *,
    reason_code: str,
    review_reasons: dict | None = None,
) -> list[dict]:
    """Keep visual coverage aligned when deterministic review removes views."""
    coverage = section.get("visual_coverage")
    if not isinstance(coverage, list):
        return []
    kept_ids = {
        str(view.get("view_id"))
        for view in kept_views or []
        if isinstance(view, dict) and view.get("view_id")
    }
    reasons = review_reasons or {}
    section_id = section.get("section_id")
    output: list[dict] = []
    for record in coverage:
        if not isinstance(record, dict) or record.get("status") != "retained":
            output.append(record)
            continue
        original_ids = [str(view_id) for view_id in record.get("view_ids") or []]
        retained_ids = [view_id for view_id in original_ids if view_id in kept_ids]
        if retained_ids:
            output.append({**record, "view_ids": retained_ids})
            continue
        reason_texts: list[str] = []
        for view_id in original_ids:
            values = reasons.get(_view_key(section_id, {"view_id": view_id}, 0), {})
            if isinstance(values, dict):
                reason_texts.extend(str(value) for value in values.values() if value)
        output.append(
            {
                "claim_id": record.get("claim_id"),
                "status": "omitted",
                "view_ids": [],
                "reason_code": reason_code,
                "reason": "；".join(dict.fromkeys(reason_texts))
                or (
                    "独立评审未保留可用视图"
                    if reason_code == "dropped_by_review"
                    else "确定性门禁未保留可用视图"
                ),
            }
        )
    return output


def _sync_recorded_visuals_from_bundle(state: dict, bundle: dict) -> None:
    """Keep durable section visuals aligned with a targeted bundle revision."""
    recorded_sections = state.get("sections")
    if not isinstance(recorded_sections, dict):
        return
    for section in bundle.get("sections") or []:
        if not isinstance(section, dict):
            continue
        section_id = _slug(str(section.get("section_id") or section.get("title") or ""))
        recorded = recorded_sections.get(section_id)
        if not isinstance(recorded, dict):
            continue
        for field in ("curated_views", "visual_coverage"):
            if field in section:
                recorded[field] = copy.deepcopy(section[field])


def _recover_orphaned_review_coverage_patch(state: dict) -> bool:
    """Repair interrupted runs whose review patch dropped views but not coverage.

    The recovery is deliberately narrow: every current gate failure must be a
    visual-coverage failure, every missing view must be named by the preceding
    review patch, and every pending task must be the generated claim repair for
    one of those failures.  This prevents a genuine curator/gate mismatch from
    being silently reclassified as a review omission.
    """
    if (
        state.get("workflow_version") != QUALITY_WORKFLOW_VERSION
        or state.get("stage") != "patch"
    ):
        return False
    pending = _pending_tasks(state, "patch")
    failures = state.get("_gate_failures")
    review_pending = {
        str(value) for value in state.get("_review_patch_pending") or [] if value
    }
    if not pending or not isinstance(failures, list) or not failures or not review_pending:
        return False
    if any(
        not isinstance(failure, dict)
        or failure.get("code") != "VISUAL_COVERAGE_INVALID"
        or not failure.get("claim_id")
        for failure in failures
    ):
        return False
    failure_claims = {str(failure["claim_id"]) for failure in failures}
    issues = {
        str(issue.get("issue_id")): issue
        for issue in (state.get("_patch_review") or {}).get("issues") or []
        if isinstance(issue, dict) and issue.get("issue_id")
    }
    pending_claims = {str(task.get("target_id") or "") for task in pending}
    if not issues or pending_claims != failure_claims:
        return False
    for task in pending:
        target_id = str(task.get("target_id") or "")
        blocker_ids = task.get("source_blocker_ids")
        if task.get("target_type") != "claim" or not blocker_ids:
            return False
        if any(
            str(blocker_id) not in issues
            or issues[str(blocker_id)].get("target_type") != "claim"
            or str(issues[str(blocker_id)].get("target_id") or "") != target_id
            for blocker_id in blocker_ids
        ):
            return False

    bundle = state.get("_bundle")
    if not isinstance(bundle, dict):
        return False
    recovered_claims: set[str] = set()
    recovery_plan: list[tuple[dict, set[str], dict[str, str]]] = []
    for section in bundle.get("sections") or []:
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("section_id") or section.get("title") or "")
        views = section.get("curated_views") or []
        view_claims = {
            str(view.get("view_id")): str(view.get("supports_claim") or "")
            for view in views
            if isinstance(view, dict) and view.get("view_id")
        }
        recoverable_claims: set[str] = set()
        for record in section.get("visual_coverage") or []:
            if not isinstance(record, dict) or record.get("status") != "retained":
                continue
            claim_id = str(record.get("claim_id") or "")
            absent_ids = [
                str(view_id)
                for view_id in record.get("view_ids") or []
                if str(view_id) not in view_claims
            ]
            mismatched_ids = [
                str(view_id)
                for view_id in record.get("view_ids") or []
                if str(view_id) in view_claims
                and view_claims[str(view_id)] != claim_id
            ]
            if not absent_ids or mismatched_ids:
                continue
            review_keys = {f"{section_id}::{view_id}" for view_id in absent_ids}
            if review_keys.issubset(review_pending):
                recoverable_claims.add(claim_id)
                if claim_id in failure_claims:
                    recovered_claims.add(claim_id)
        if recoverable_claims:
            recovery_plan.append((section, recoverable_claims, view_claims))
    if not recovery_plan or recovered_claims != failure_claims:
        return False

    for section, recoverable_claims, view_claims in recovery_plan:
        updated_coverage = []
        for record in section.get("visual_coverage") or []:
            claim_id = str(record.get("claim_id") or "") if isinstance(record, dict) else ""
            if (
                not isinstance(record, dict)
                or record.get("status") != "retained"
                or claim_id not in recoverable_claims
            ):
                updated_coverage.append(record)
                continue
            retained_ids = [
                str(view_id)
                for view_id in record.get("view_ids") or []
                if view_claims.get(str(view_id)) == claim_id
            ]
            if retained_ids:
                updated_coverage.append({**record, "view_ids": retained_ids})
                continue
            updated_coverage.append(
                {
                    "claim_id": record.get("claim_id"),
                    "status": "omitted",
                    "view_ids": [],
                    "reason_code": "dropped_by_review",
                    "reason": "独立评审未保留可用视图",
                }
            )
        section["visual_coverage"] = updated_coverage

    _sync_recorded_visuals_from_bundle(state, bundle)
    _set_stage_tasks(state, "patch", [])
    state.pop("_review_patch_pending", None)
    state.setdefault("history", []).append("recover:orphaned_visual_coverage")
    return True


def _write_review_briefs(run_dir: Path, bundle: dict, *, state: dict | None = None) -> list[Path]:
    """Write one reviewer brief per (domain, lens) — 3 lenses per domain, each
    judging that domain's curated views through its single failure-mode lens. Prose
    + column names only (no numbers — the gate already locked those). Never raises."""
    briefs_dir = run_dir / "briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    tasks: list[dict] = []
    by_section: dict = {}
    quality_workflow = (
        state is not None
        and state.get("workflow_version") == QUALITY_WORKFLOW_VERSION
    )
    for section_id, idx, view in _iter_curated_views(bundle):
        by_section.setdefault(section_id, []).append((idx, view))
    for section_id, views in by_section.items():
        payload_views = []
        for idx, view in views:
            v = view if isinstance(view, dict) else {}
            payload_views.append(
                {
                    "view_id": v.get("view_id") or f"#{idx}",
                    "template": _template_of(v) or "",  # normalize aliases so kind is legible
                    "title": v.get("title", ""),
                    "columns": list(v.get("columns") or []),
                    "how_to_read": v.get("how_to_read", ""),
                    "why_it_matters": v.get("why_it_matters", ""),
                    "supports_claim": v.get("supports_claim", ""),
                }
            )
        for legacy_lens, question in _REVIEW_LENSES:
            lens = (
                _QUALITY_REVIEW_LENS_NAMES[legacy_lens]
                if quality_workflow
                else legacy_lens
            )
            if quality_workflow:
                output_contract = (
                    '{"section_id","lens","verdicts":[{"view_id",'
                    '"verdict":"keep|revise|drop","reason","blocker_codes":[]}]}'
                )
                blocker_guidance = [
                    "keep 时 blocker_codes 返回 []; revise/drop 时至少返回一个适用 code。",
                    "可用 code: UNSUPPORTED / SEMANTIC_MISMATCH / NO_DECISION_VALUE / "
                    "UNREADABLE / WRONG_VISUAL_FORM / RAW_DUMP / DUPLICATE。",
                ]
            else:
                output_contract = (
                    '{"section_id","lens","verdicts":[{"view_id",'
                    '"verdict":"keep|revise|drop","reason"}]}'
                )
                blocker_guidance = []
            lines = [
                f"# Review brief — 域『{section_id}』· 视角『{lens}』",
                "",
                f"你是「{lens}」评审员。只问一件事:{question}",
                "对下面每个策展视图给出 keep / revise / drop 之一 + 一句理由。",
                "你只评判价值/可读性/支撑,不能改数字(确定性 gate 已锁定数值)。",
                "宁可少放视图,也不要堆砌。返回 JSON:",
                output_contract,
                *blocker_guidance,
                "",
                "```json",
                json.dumps(
                    {"section_id": section_id, "lens": lens, "views": payload_views},
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
            ]
            path = briefs_dir / f"review_{_slug(str(section_id))}_{_slug(lens)}.md"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            paths.append(path)
            tasks.append(
                {
                    "brief": path,
                    "section_id": section_id,
                    "lens": lens,
                    "role": f"reviewer_{lens}",
                    "view_keys": [
                        _view_key(section_id, view, idx) for idx, view in views
                    ],
                }
            )
    if state is not None:
        _set_stage_tasks(state, "review", tasks)
    return paths


def _write_review_patch_brief(
    run_dir: Path, bundle: dict, patched_keys, reasons: dict
) -> None:
    """Write the patch brief for views the reviewers could not converge on. The
    patch agent re-authors only the view-spec (template/columns/rows/source/prose)
    using the merged reviewer reasons — never writes a number. Never raises."""
    briefs_dir = run_dir / "briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)
    targets = set(patched_keys)
    payload = []
    for section_id, idx, view in _iter_curated_views(bundle):
        key = _view_key(section_id, view, idx)
        if key not in targets:
            continue
        v = view if isinstance(view, dict) else {}
        payload.append(
            {
                "view_id": v.get("view_id") or f"#{idx}",
                "view_key": key,
                "section_id": section_id,
                "template": _template_of(v) or "",  # normalize aliases so kind is legible
                "title": v.get("title", ""),
                "columns": list(v.get("columns") or []),
                "supports_claim": v.get("supports_claim", ""),
                "merged_reasons": (
                    list(reasons.get(key, {}).values())
                    if isinstance(reasons.get(key), dict)
                    else list(reasons.get(key, []))
                ),
            }
        )
    lines = [
        "# Patch brief — 评审未收敛的策展视图",
        "",
        "以下视图三位评审投票无多数(既非 keep 也非 drop)。请按 merged_reasons 重挑列/减列/",
        "换模板/换源表后重写其 view-spec。只改 view-spec,不得写入任何数值(确定性引擎从源表填数)。",
        '返回 JSON:{"sections":[{"section_id","title","body","curated_views":[...]}]}',
        "",
        "```json",
        json.dumps({"views_to_repatch": payload}, ensure_ascii=False, indent=2),
        "```",
    ]
    (briefs_dir / "review_patch.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _target_object(bundle: dict, target_type: str, target_id: str) -> dict | None:
    id_field = {"claim": "claim_id", "view": "view_id", "action": "action_id"}.get(
        target_type
    )
    if id_field is None:
        return None
    candidates = []
    for section in bundle.get("sections") or []:
        if not isinstance(section, dict):
            continue
        candidates.extend(section.get("claims") or [])
        candidates.extend(section.get("curated_views") or [])
        candidates.extend(section.get("action_cards") or [])
    first_screen = bundle.get("first_screen") or {}
    candidates.extend(first_screen.get("spine") or [])
    candidates.extend(first_screen.get("panel") or [])
    candidates.extend(bundle.get("action_cards") or [])
    for item in candidates:
        if isinstance(item, dict) and str(item.get(id_field) or "") == target_id:
            return item
    return None


def _write_targeted_patch_brief(
    run_dir: Path,
    *,
    filename: str,
    title: str,
    bundle: dict,
    issues: list[dict],
) -> Path:
    path = Path(run_dir) / "briefs" / filename
    targets = []
    for issue in issues:
        target_type = str(issue.get("target_type") or "")
        target_id = str(issue.get("target_id") or "")
        target = _target_object(bundle, target_type, target_id)
        if target is not None:
            targets.append(
                {
                    "target_type": target_type,
                    "target_id": target_id,
                    "current": target,
                }
            )
    lines = [
        f"# {title}",
        "",
        "只修改 issues 指向的单个 claim/view/action；不得覆盖 section 或 bundle。",
        "不得改变 fact_id、number_tokens、source、supports_claim、单位、口径、聚合或方向。",
        "返回 JSON 数组，每项严格符合 targeted_revision；replace 必须保留 target_id，",
        "source_blocker_ids 必须引用对应 issue_id。无需修改的目标使用 drop，不得返回整包。",
        "",
        "```json",
        json.dumps({"issues": issues, "targets": targets}, ensure_ascii=False, indent=2),
        "```",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_targeted_patch_briefs(
    run_dir: Path,
    *,
    prefix: str,
    title: str,
    bundle: dict,
    issues: list[dict],
) -> list[tuple[Path, dict]]:
    outputs = []
    for issue in issues:
        issue_id = _slug(str(issue.get("issue_id") or "issue"))
        path = _write_targeted_patch_brief(
            run_dir,
            filename=f"{prefix}_{issue_id}.md",
            title=title,
            bundle=bundle,
            issues=[issue],
        )
        outputs.append((path, issue))
    return outputs


def _review_patch_issues(bundle: dict, patched_keys, reasons: dict, round_number: int) -> list[dict]:
    targets = set(patched_keys)
    issues = []
    for section_id, idx, view in _iter_curated_views(bundle):
        key = _view_key(section_id, view, idx)
        if key not in targets or not isinstance(view, dict) or not view.get("view_id"):
            continue
        reason_values = reasons.get(key, {})
        if isinstance(reason_values, dict):
            reason_text = "；".join(str(value) for value in reason_values.values() if value)
        else:
            reason_text = "；".join(str(value) for value in reason_values or [] if value)
        issues.append(
            {
                "issue_id": f"review-{round_number}-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:10]}",
                "target_type": "view",
                "target_id": str(view["view_id"]),
                "reason": reason_text or "独立评审要求定向修订",
            }
        )
    return issues


def _gate_patch_issues(bundle: dict, failures, round_number: int) -> list[dict]:
    targets = _bundle_target_ids(bundle)
    issues = []
    seen: set[tuple[str, str]] = set()
    for index, failure in enumerate(failures or []):
        if not isinstance(failure, dict):
            continue
        target_id = str(failure.get("claim_id") or "")
        target_type = next(
            (
                candidate
                for candidate in ("claim", "view", "action")
                if target_id and target_id in targets[candidate]
            ),
            None,
        )
        if target_type is None or (target_type, target_id) in seen:
            continue
        seen.add((target_type, target_id))
        issues.append(
            {
                "issue_id": f"gate-{round_number}-{index}-{_slug(str(failure.get('code') or 'failure'))}",
                "target_type": target_type,
                "target_id": target_id,
                "reason": str(failure.get("detail") or failure.get("message") or failure),
            }
        )
    return issues


def _write_gate_patch_brief(run_dir: Path, state: dict, failures) -> Path:
    """Write and register the ordinary deterministic-gate repair task."""
    briefs_dir = Path(run_dir) / "briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)
    path = briefs_dir / "patch.md"
    lines = [
        "# Patch brief — 确定性 gate 未通过",
        "",
        "只修复 failures 指出的 claim 或 view 结构。不得自行改写数字；所有数字仍必须由",
        "number_tokens 或确定性视图引擎回填。返回 JSON sections/bundle，保持未被指出的内容不变。",
        "",
        "```json",
        json.dumps(
            {
                "failures": list(failures or []),
                "bundle": state.get("_bundle") or _bundle_from_state(state),
            },
            ensure_ascii=False,
            indent=2,
        ),
        "```",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _set_stage_tasks(state, "patch", [{"brief": path}])
    return path


def _write_continuity_brief(run_dir: Path, state: dict, bundle: dict) -> Path:
    """Write the prose-only continuity task and register it as the current task."""
    briefs_dir = Path(run_dir) / "briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)
    path = briefs_dir / "continuity.md"
    lines = [
        "# Continuity brief — 全文连贯性复核",
        "",
        "只修正文之间的衔接、重复和措辞，不得改变任何数字、token、claim_id 或事实含义。",
        "返回 JSON only: {\"edits\":[{\"claim_id\",\"old\",\"new\"}]}。",
        "无需修改时返回 {\"edits\":[]}。",
        "",
        "```json",
        json.dumps(bundle or {}, ensure_ascii=False, indent=2),
        "```",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _set_stage_tasks(state, "continuity", [{"brief": path}])
    return path


def _enter_review_or_continuity(run_dir: Path, state: dict) -> dict:
    """Post-gate router: a bundle carrying curated views goes to the ``review``
    stage (fresh verdict slate + reviewer briefs); a prose-only bundle skips
    straight to ``continuity`` (today's behavior). Persists + returns state."""
    bundle = state.get("_bundle") or {}
    if _bundle_has_curated_views(bundle):
        state["_reviews"] = {}
        state["_review_reasons"] = {}
        state.setdefault("_review_patch_rounds", 0)
        state.pop("_review_patch_pending", None)
        state["stage"] = "review"
        _write_review_briefs(run_dir, bundle, state=state)
    else:
        state["stage"] = "continuity"
        _write_continuity_brief(run_dir, state, bundle)
    _write_state(run_dir, state)
    return state


def _resolve_review_stage(run_dir: Path, state: dict) -> dict:
    """Tally each curated view's verdicts and route: drop → remove; keep → retain;
    no-majority → patch (bounded to ``MAX_REVIEW_PATCH_ROUNDS``, then dropped).

    When any view still needs a patch round, routes to the existing ``patch`` stage
    with a re-author brief and a fresh verdict slate. Otherwise applies the drops
    and advances to ``continuity``. Never raises; a section left with zero views
    degrades to prose-only, and the report still finalizes."""
    reviews = state.get("_reviews") or {}
    reasons = state.get("_review_reasons") or {}
    patch_rounds = state.get("_review_patch_rounds", 0)
    bundle = state.get("_bundle") or _bundle_from_state(state)
    quality_workflow = state.get("workflow_version") == QUALITY_WORKFLOW_VERSION

    patched_keys: list[str] = []
    new_sections: list = []
    for section in bundle.get("sections") or []:
        if not isinstance(section, dict):
            new_sections.append(section)
            continue
        views = section.get("curated_views")
        if not isinstance(views, (list, tuple)) or not views:
            new_sections.append(section)
            continue
        kept, patched = _resolve_section_views(
            section.get("section_id"),
            views,
            reviews,
            patch_rounds,
            quality_workflow=quality_workflow,
        )
        patched_keys.extend(patched)
        updated_section = {**section, "curated_views": kept}
        if quality_workflow:
            updated_section["visual_coverage"] = _coverage_after_view_drop(
                section,
                kept,
                reason_code="dropped_by_review",
                review_reasons=reasons,
            )
        new_sections.append(updated_section)

    new_bundle = {**bundle, "sections": new_sections}
    state["_bundle"] = new_bundle
    # keep the recorded sections in sync so a patch rebuild preserves the drops
    _sync_recorded_curated_views(
        state,
        reviews,
        patch_rounds,
        quality_workflow=quality_workflow,
        reasons=reasons,
    )

    if patched_keys:
        state["_review_patch_rounds"] = patch_rounds + 1
        state["_reviews"] = {}
        state["_review_reasons"] = {}
        state["_review_patch_pending"] = list(patched_keys)
        if quality_workflow:
            issues = _review_patch_issues(
                new_bundle,
                patched_keys,
                reasons,
                patch_rounds + 1,
            )
            if not issues:
                return _route_deterministic(
                    run_dir,
                    state,
                    state.get("project_root"),
                    "untargetable_review_blocker",
                )
            state["_patch_review"] = {"issues": issues}
            state["_patch_round"] = patch_rounds + 1
            patch_outputs = _write_targeted_patch_briefs(
                run_dir,
                prefix="review_patch",
                title="Targeted review revision",
                bundle=new_bundle,
                issues=issues,
            )
        else:
            _write_review_patch_brief(run_dir, new_bundle, patched_keys, reasons)
            patch_outputs = [
                (run_dir / "briefs" / "review_patch.md", {"target_id": None})
            ]
        state["stage"] = "patch"
        _set_stage_tasks(
            state,
            "patch",
            [
                {
                    "brief": path,
                    "role": "targeted_reviser",
                    "target_type": issue.get("target_type"),
                    "target_id": issue.get("target_id"),
                    "source_blocker_ids": [issue.get("issue_id")],
                }
                for path, issue in patch_outputs
            ],
        )
        _write_state(run_dir, state)
        return state

    state["_reviews"] = {}
    state["_review_reasons"] = {}
    state.pop("_review_patch_pending", None)
    state["stage"] = "continuity"
    _write_continuity_brief(run_dir, state, new_bundle)
    _write_state(run_dir, state)
    return state


def status_json(run_dir) -> dict:
    """Machine-readable run status: stage, next action, pending briefs, degradation."""
    run_dir = Path(run_dir)
    state = _load_state(run_dir)
    if state is None:
        raise FileNotFoundError(f"no run at {run_dir}")
    stage = state["stage"]
    briefs_dir = run_dir / "briefs"
    tasks = _stage_tasks(state, stage)
    if tasks:
        briefs = [str(task["brief"]) for task in tasks if task.get("status") != "completed"]
    elif stage == "seed":
        briefs = [str(briefs_dir / "seed.md")]
    elif stage == "fan":
        briefs = [str(p) for p in sorted(briefs_dir.glob("fan_*.md"))]
    elif stage == "synth":
        briefs = [str(briefs_dir / "synth.md")]
    elif stage == "review":
        briefs = [str(p) for p in sorted(briefs_dir.glob("review_*.md")) if p.name != "review_patch.md"]
    elif stage == "patch" and state.get("_review_patch_pending"):
        briefs = [str(briefs_dir / "review_patch.md")]
    else:
        briefs = []
    pending = [
        _task_with_contract(run_dir, state, task)
        for task in tasks
        if task.get("status") != "completed"
    ]
    completed = [
        _task_with_contract(run_dir, state, task)
        for task in tasks
        if task.get("status") == "completed"
    ]
    return {
        "stage": stage,
        "workflow_version": state.get("workflow_version"),
        "run_id": state.get("run_id"),
        # Recorded once at prepare; a resuming host reads it here instead of
        # asking the user for multi-agent authorization a second time.
        "authorization_decision": state.get("authorization_decision"),
        "next_action": _NEXT_ACTION.get(stage, ""),
        "briefs": briefs,
        "tasks": {"pending": pending, "completed": completed},
        "cache_status": state.get("cache_status"),
        "delivery_status": state.get("delivery_status"),
        "artifacts": state.get("artifacts") or {},
        "error": state.get("error"),
        "degradation_reason": state.get("degradation_reason"),
        "merged_sections": state.get("merged_sections", []),
    }


# Gate failure codes that target ONE curated view (keyed by its `_view_label`), as
# opposed to a claim (keyed by claim_id) or a whole section. A view carrying any of
# these drops under the never-block contract; a claim-level failure has no view to
# drop and keeps the exhaust→skeleton path.
_PER_VIEW_GATE_CODES = frozenset(
    {"VIEW_SPEC_INVALID", "VIEW_VALUE_MISMATCH", "VIEW_SUPPORTS_UNKNOWN_CLAIM"}
)


def _drop_gate_failed_views(state: dict, hard_failures) -> bool:
    """Drop every curated view the gate hard-failed, in place on ``state['sections']``.

    The never-block contract (design §"any malformed spec, missing table, or unresolved
    review drops that single view; the report still delivers exactly two artifacts. A
    section with zero passing views degrades to prose-only"): a bad view is removed so
    the next patch rebuild (via :func:`_bundle_from_state`) omits it, instead of
    re-rendering the identical failing bundle every round until gate exhaustion routes
    to the skeleton.

    Per-view failures (:data:`_PER_VIEW_GATE_CODES`) are keyed by the gate's own
    ``_view_label`` — reused verbatim so the drop matches the gate byte-for-byte,
    including the positional ``{section_id}:curated_view[{idx}]`` fallback. There is no
    per-domain cap, so a section is only ever trimmed by its own failed views, never by
    a table/chart count. Claim-level failures carry no view label, so nothing drops for
    them — they keep the exhaust→skeleton path (never-block is view-specific). Returns
    ``True`` iff any view was removed. Never raises."""
    failed_labels: set[str] = set()
    failure_details: dict[str, str] = {}
    for failure in hard_failures or []:
        if not isinstance(failure, dict):
            continue
        code = failure.get("code")
        key = failure.get("claim_id")
        if code in _PER_VIEW_GATE_CODES and isinstance(key, str) and key:
            failed_labels.add(key)
            failure_details[key] = str(
                failure.get("detail") or failure.get("message") or "确定性门禁未通过"
            )
    if not failed_labels:
        return False

    sections = state.get("sections")
    if not isinstance(sections, dict):  # a truthy non-dict (list/str) must not crash .items()
        return False
    changed = False
    for sid, section in sections.items():
        if not isinstance(section, dict):
            continue
        views = section.get("curated_views")
        if not isinstance(views, (list, tuple)) or not views:
            continue
        # The gate labels views against the section_id it saw in the bundle
        # (_bundle_from_state passes these very section dicts), so use the same.
        section_id = section.get("section_id", sid)
        original_views = list(views)
        kept = [
            view
            for idx, view in enumerate(views)
            if _gate_view_label(view, section_id, idx) not in failed_labels
        ]
        if len(kept) != len(views):
            section["curated_views"] = kept
            if "visual_coverage" in section:
                reason_map = {}
                for idx, view in enumerate(original_views):
                    label = _gate_view_label(view, section_id, idx)
                    if label not in failed_labels or not isinstance(view, dict):
                        continue
                    view_id = view.get("view_id")
                    if view_id:
                        reason_map[_view_key(section_id, view, idx)] = {
                            "gate": failure_details.get(label, "确定性门禁未通过")
                        }
                section["visual_coverage"] = _coverage_after_view_drop(
                    section,
                    kept,
                    reason_code="dropped_by_gate",
                    review_reasons=reason_map,
                )
            changed = True
    return changed


def _persist_gate_attempt(run_dir: Path, state: dict, report, bundle: dict) -> Path:
    """Persist one gate result before any state transition or fallback."""
    run_dir = Path(run_dir)
    attempt = int(state.get("_gate_attempt") or 0) + 1
    archive_path = run_dir / "gate_reports" / f"gate-{attempt}.json"
    latest_path = run_dir / "gate_report.json"
    report_text = json.dumps(
        {
            "status": report.status,
            "hard_failures": list(report.hard_failures),
            "warnings": list(getattr(report, "warnings", []) or []),
            "capped_claims": list(getattr(report, "capped_claims", []) or []),
        },
        sort_keys=True,
        ensure_ascii=False,
        indent=2,
    )
    _write_text_atomic(archive_path, report_text)
    _write_text_atomic(latest_path, report_text)
    state["_gate_attempt"] = attempt
    state["_gate_failures"] = list(report.hard_failures)
    state["_gate_report_path"] = str(latest_path)
    state["_gate_bundle_hash"] = _stable_hash(bundle)
    _write_state(run_dir, state)
    return latest_path


def _run_gate_stage(run_dir: Path, state: dict, facts_json: dict, project_root) -> dict:
    result_tables = _load_result_tables(run_dir)
    bundle = state.get("_bundle", _bundle_from_state(state))
    report = _run_gate(bundle, facts_json, result_tables)
    _persist_gate_attempt(run_dir, state, report, bundle)
    if report.status == "PASS":
        state["_bundle"] = report.bundle
        # numeric trust is now locked; a bundle with curated views goes to the
        # adversarial review stage, a prose-only bundle straight to continuity.
        return _enter_review_or_continuity(run_dir, state)
    # Never-block: drop the curated views this round's gate hard-failed so the next
    # patch rebuild omits them, rather than re-rendering the identical failing bundle
    # until exhaustion. Claim-level failures drop nothing and still route to skeleton.
    dropped_views = _drop_gate_failed_views(state, report.hard_failures)
    quality_workflow = state.get("workflow_version") == QUALITY_WORKFLOW_VERSION
    if quality_workflow and dropped_views:
        state["_bundle"] = render_draft(_bundle_from_state(state), facts_json)
        report = _run_gate(state["_bundle"], facts_json, result_tables)
        _persist_gate_attempt(run_dir, state, report, state["_bundle"])
        if report.status == "PASS":
            return _enter_review_or_continuity(run_dir, state)
    rounds = state.get("_gate_rounds", 0) + 1
    state["_gate_rounds"] = rounds
    if rounds > MAX_GATE_ROUNDS:
        return _route_deterministic(run_dir, state, project_root, "gate_exhausted")
    state["stage"] = "patch"
    if quality_workflow:
        issues = _gate_patch_issues(
            state.get("_bundle") or _bundle_from_state(state),
            report.hard_failures,
            rounds,
        )
        if not issues:
            return _route_deterministic(
                run_dir,
                state,
                project_root,
                "untargetable_gate_blocker",
            )
        state["_patch_review"] = {"issues": issues}
        state["_patch_round"] = rounds
        patch_outputs = _write_targeted_patch_briefs(
            run_dir,
            prefix="patch",
            title="Targeted gate revision",
            bundle=state.get("_bundle") or _bundle_from_state(state),
            issues=issues,
        )
        _set_stage_tasks(
            state,
            "patch",
            [
                {
                    "brief": path,
                    "role": "targeted_reviser",
                    "target_type": issue.get("target_type"),
                    "target_id": issue.get("target_id"),
                    "source_blocker_ids": [issue.get("issue_id")],
                }
                for path, issue in patch_outputs
            ],
        )
    else:
        _write_gate_patch_brief(run_dir, state, report.hard_failures)
    _write_state(run_dir, state)
    return state


def _route_deterministic(run_dir: Path, state: dict, project_root, reason: str) -> dict:
    """Adopt the state finalize_deterministic returns rather than re-deriving one.

    Defensively re-asserts stage/degradation_reason on top of the returned dict so
    a monkeypatched finalize_deterministic (which may return a minimal stand-in
    without degradation_reason) still yields a correctly-routed state. Builds one
    new dict and persists it exactly once — never double-writes state.json.
    """
    result = finalize_deterministic(run_dir, project_root=project_root, reason=reason)
    result = {**result, "stage": "blocked", "degradation_reason": reason}
    _write_state(run_dir, result)
    return result


def _load_capped_slices(run_dir: Path) -> list[dict]:
    payload = json.loads((Path(run_dir) / "domain_slices.json").read_text(encoding="utf-8"))
    slices = payload.get("capped") if isinstance(payload, dict) else None
    return [item for item in (slices or []) if isinstance(item, dict)]


def _load_platform_semantics(run_dir: Path) -> dict:
    payload = json.loads((Path(run_dir) / "domain_slices.json").read_text(encoding="utf-8"))
    context = payload.get("platform_semantics") if isinstance(payload, dict) else None
    return context if isinstance(context, dict) else {}


def _bundle_target_ids(bundle: dict) -> dict[str, set[str]]:
    targets = {"claim": set(), "view": set(), "action": set()}
    for section in bundle.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for claim in section.get("claims") or []:
            if isinstance(claim, dict) and claim.get("claim_id"):
                targets["claim"].add(str(claim["claim_id"]))
        for view in section.get("curated_views") or []:
            if isinstance(view, dict) and view.get("view_id"):
                targets["view"].add(str(view["view_id"]))
        for action in section.get("action_cards") or []:
            if isinstance(action, dict) and action.get("action_id"):
                targets["action"].add(str(action["action_id"]))
    for key in ("spine", "panel"):
        for claim in (bundle.get("first_screen") or {}).get(key) or []:
            if isinstance(claim, dict) and claim.get("claim_id"):
                targets["claim"].add(str(claim["claim_id"]))
    for action in bundle.get("action_cards") or []:
        if isinstance(action, dict) and action.get("action_id"):
            targets["action"].add(str(action["action_id"]))
    return targets


def _validate_merchant_review_payload(bundle: dict, review: dict) -> None:
    issues = review.get("issues")
    if not isinstance(issues, list):
        raise ValueError("merchant review issues must be a list")
    if review.get("verdict") == "pass" and issues:
        raise ValueError("merchant pass cannot carry revision issues")
    if review.get("verdict") == "revise" and not issues:
        raise ValueError("merchant revise must name at least one issue")
    targets = _bundle_target_ids(bundle)
    issue_ids: set[str] = set()
    required = {
        "issue_id",
        "target_type",
        "target_id",
        "severity",
        "reason",
        "requested_change",
    }
    for issue in issues:
        if not isinstance(issue, dict) or set(issue) != required:
            raise ValueError("merchant review issue does not match the strict envelope")
        issue_id = issue.get("issue_id")
        target_type = issue.get("target_type")
        target_id = issue.get("target_id")
        if not isinstance(issue_id, str) or not issue_id or issue_id in issue_ids:
            raise ValueError("merchant review issue_id must be unique and non-empty")
        issue_ids.add(issue_id)
        if target_type not in targets or str(target_id) not in targets[target_type]:
            raise ValueError(
                f"unknown merchant review target: {target_type}:{target_id}"
            )
        if issue.get("severity") not in {"blocker", "major"}:
            raise ValueError("merchant review severity must be blocker or major")
        if not str(issue.get("reason") or "").strip() or not str(
            issue.get("requested_change") or ""
        ).strip():
            raise ValueError("merchant review issue text must be non-empty")


def _replace_target(items, *, id_field: str, target_id: str, replacement) -> tuple[list, bool]:
    changed = False
    output = []
    for item in items or []:
        if isinstance(item, dict) and str(item.get(id_field) or "") == target_id:
            changed = True
            if replacement is not None:
                output.append(copy.deepcopy(replacement))
        else:
            output.append(item)
    return output, changed


def _apply_one_merchant_revision(bundle: dict, revision: dict) -> bool:
    target_type = revision["target_type"]
    target_id = str(revision["target_id"])
    replacement = revision["replacement"] if revision["operation"] == "replace" else None
    id_field = {"claim": "claim_id", "view": "view_id", "action": "action_id"}[target_type]
    if replacement is not None and str(replacement.get(id_field) or "") != target_id:
        raise ValueError("targeted replacement must preserve the target ID")

    immutable_fields = {
        "claim": (
            "claim_id",
            "section_id",
            "claim_kind",
            "number_tokens",
            "entity_refs",
            "causal_link",
        ),
        "view": ("view_id", "section_id", "supports_claim", "source"),
        "action": (
            "action_id",
            "action_family",
            "primary_fact_id",
            "guardrail_fact_id",
            "supporting_claim_ids",
            "number_tokens",
        ),
    }[target_type]
    if replacement is not None:
        current_targets = []
        if target_type == "claim":
            for section in bundle.get("sections") or []:
                if isinstance(section, dict):
                    current_targets.extend(section.get("claims") or [])
            first_screen = bundle.get("first_screen") or {}
            current_targets.extend(first_screen.get("spine") or [])
            current_targets.extend(first_screen.get("panel") or [])
        elif target_type == "view":
            for section in bundle.get("sections") or []:
                if isinstance(section, dict):
                    current_targets.extend(section.get("curated_views") or [])
        else:
            current_targets.extend(bundle.get("action_cards") or [])
            for section in bundle.get("sections") or []:
                if isinstance(section, dict):
                    current_targets.extend(section.get("action_cards") or [])
        matched = [
            item
            for item in current_targets
            if isinstance(item, dict) and str(item.get(id_field) or "") == target_id
        ]
        for current in matched:
            if any(current.get(field) != replacement.get(field) for field in immutable_fields):
                raise ValueError("targeted replacement changes an immutable evidence binding")

    changed = False
    if target_type == "claim":
        for section in bundle.get("sections") or []:
            if not isinstance(section, dict):
                continue
            section["claims"], section_changed = _replace_target(
                section.get("claims"),
                id_field=id_field,
                target_id=target_id,
                replacement=replacement,
            )
            changed = changed or section_changed
        first_screen = bundle.get("first_screen") or {}
        for key in ("spine", "panel"):
            first_screen[key], section_changed = _replace_target(
                first_screen.get(key),
                id_field=id_field,
                target_id=target_id,
                replacement=replacement,
            )
            changed = changed or section_changed
        if replacement is None:
            bundle["mechanism"] = [
                item
                for item in bundle.get("mechanism") or []
                if not (isinstance(item, dict) and str(item.get("claim_id") or "") == target_id)
            ]
            for section in bundle.get("sections") or []:
                if not isinstance(section, dict):
                    continue
                section["curated_views"] = [
                    view
                    for view in section.get("curated_views") or []
                    if not (
                        isinstance(view, dict)
                        and str(view.get("supports_claim") or "") == target_id
                    )
                ]
                section["visual_coverage"] = [
                    record
                    for record in section.get("visual_coverage") or []
                    if not (
                        isinstance(record, dict)
                        and str(record.get("claim_id") or "") == target_id
                    )
                ]
            for owner in [bundle, *(bundle.get("sections") or [])]:
                if not isinstance(owner, dict):
                    continue
                kept_actions = []
                for action in owner.get("action_cards") or []:
                    if not isinstance(action, dict):
                        kept_actions.append(action)
                        continue
                    supporting = [
                        claim_id
                        for claim_id in action.get("supporting_claim_ids") or []
                        if str(claim_id) != target_id
                    ]
                    if supporting:
                        kept_actions.append({**action, "supporting_claim_ids": supporting})
                owner["action_cards"] = kept_actions
    elif target_type == "view":
        for section in bundle.get("sections") or []:
            if not isinstance(section, dict):
                continue
            section["curated_views"], section_changed = _replace_target(
                section.get("curated_views"),
                id_field=id_field,
                target_id=target_id,
                replacement=replacement,
            )
            if section_changed and "visual_coverage" in section:
                section["visual_coverage"] = _coverage_after_view_drop(
                    section,
                    section["curated_views"],
                    reason_code="dropped_by_review",
                )
            changed = changed or section_changed
    else:
        for owner in [bundle, *(bundle.get("sections") or [])]:
            if not isinstance(owner, dict) or not isinstance(owner.get("action_cards"), list):
                continue
            owner["action_cards"], section_changed = _replace_target(
                owner.get("action_cards"),
                id_field=id_field,
                target_id=target_id,
                replacement=replacement,
            )
            changed = changed or section_changed
    return changed


def _apply_merchant_revisions(
    bundle: dict,
    revisions: list,
    review: dict,
    *,
    expected_round: int,
) -> dict:
    if not revisions:
        raise ValueError("merchant patch requires at least one targeted revision")
    issues = {
        str(issue.get("issue_id")): issue
        for issue in review.get("issues") or []
        if isinstance(issue, dict) and issue.get("issue_id")
    }
    required = {
        "revision_id",
        "round",
        "target_type",
        "target_id",
        "operation",
        "source_blocker_ids",
        "replacement",
        "reason",
    }
    output = copy.deepcopy(bundle)
    revised_targets: set[tuple[str, str]] = set()
    revision_ids: set[str] = set()
    for revision in revisions:
        if not isinstance(revision, dict) or set(revision) != required:
            raise ValueError("merchant targeted revision does not match the strict envelope")
        revision_id = revision.get("revision_id")
        if not isinstance(revision_id, str) or not revision_id or revision_id in revision_ids:
            raise ValueError("revision_id must be unique and non-empty")
        revision_ids.add(revision_id)
        if revision.get("round") != expected_round or expected_round not in {1, 2}:
            raise ValueError("targeted revision round does not match controller state")
        target_type = revision.get("target_type")
        target_id = str(revision.get("target_id") or "")
        target = (str(target_type), target_id)
        if target_type not in {"claim", "view", "action"} or not target_id:
            raise ValueError("targeted revision has an invalid target")
        if target in revised_targets:
            raise ValueError("a merchant patch may revise each target only once")
        revised_targets.add(target)
        blocker_ids = revision.get("source_blocker_ids")
        if not isinstance(blocker_ids, list) or not blocker_ids:
            raise ValueError("targeted revision must cite source_blocker_ids")
        for blocker_id in blocker_ids:
            issue = issues.get(str(blocker_id))
            if issue is None or (
                issue.get("target_type"), str(issue.get("target_id") or "")
            ) != target:
                raise ValueError("targeted revision cites an unrelated blocker")
        operation = revision.get("operation")
        replacement = revision.get("replacement")
        if operation not in {"replace", "drop"}:
            raise ValueError("targeted revision operation must be replace or drop")
        if operation == "replace" and not isinstance(replacement, dict):
            raise ValueError("replace revision requires a replacement object")
        if operation == "drop" and replacement is not None:
            raise ValueError("drop revision replacement must be null")
        if not str(revision.get("reason") or "").strip():
            raise ValueError("targeted revision reason must be non-empty")
        current_target = _target_object(output, str(target_type), target_id)
        if operation == "replace" and current_target == replacement:
            raise ValueError(
                f"targeted revision did not change {target_type}:{target_id}"
            )
        if not _apply_one_merchant_revision(output, revision):
            raise ValueError(f"targeted revision did not match {target_type}:{target_id}")
    return output


def _write_merchant_review_brief(
    run_dir: Path,
    state: dict,
    bundle: dict,
    candidate_path: Path,
) -> Path:
    path = Path(run_dir) / "briefs" / "merchant_review.md"
    lines = [
        "# Merchant final review",
        "",
        "从店铺经营者视角审阅 candidate.html。检查首屏是否直接回答盘面、优先级是否清楚、",
        "行动是否有负责人/观察指标/停止规则、图表是否帮决策、术语是否自然。",
        "你不能改数字、单位、口径、公式或事实；问题必须指向 claim_id/view_id/action_id。",
        "只有会误导经营判断、让关键动作不可执行或让报告明显难读的问题才判 revise。",
        "",
        '返回 JSON only: {"verdict":"pass|revise","issues":[{'
        '"issue_id","target_type":"claim|view|action","target_id","severity":"blocker|major",'
        '"reason","requested_change"}]}',
        "",
        f"Candidate HTML: {candidate_path}",
        "",
        "```json",
        json.dumps(
            {
                "headline": bundle.get("headline"),
                "first_screen": bundle.get("first_screen") or {},
                "action_cards": bundle.get("action_cards") or [],
                "sections": bundle.get("sections") or [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        "```",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_merchant_patch_brief(run_dir: Path, state: dict) -> Path:
    path = Path(run_dir) / "briefs" / "merchant_patch.md"
    lines = [
        "# Merchant targeted revision",
        "",
        "只修改 issues 指向的 claim/view/action；其他内容必须保持不变。",
        "不得改数字、fact_id、metric_id、单位、口径、aggregation 或方向。",
        "返回 JSON 数组，每项严格符合 targeted_revision：replace/drop 单个目标，",
        "source_blocker_ids 必须引用下方 issue_id，replacement 必须保留原 target_id。",
        "",
        "```json",
        json.dumps(
            {
                "issues": (state.get("_merchant_review") or {}).get("issues") or [],
                "bundle": state.get("_bundle") or _bundle_from_state(state),
            },
            ensure_ascii=False,
            indent=2,
        ),
        "```",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _enter_merchant_review(
    run_dir: Path,
    state: dict,
    facts_json: dict,
) -> dict:
    bundle = state.get("_bundle") or _bundle_from_state(state)
    tables = _load_result_tables(run_dir)
    markdown = bundle_to_markdown(
        bundle,
        facts_json,
        title=state.get("report_name"),
        result_tables=tables,
    )
    html = render_markdown_document_html(markdown, title=state.get("report_name"))
    _validate_delivery_html(
        html,
        str(state.get("report_name") or ""),
        retained_view_ids=_retained_view_ids(bundle),
    )
    candidate_path = Path(run_dir) / "candidate.html"
    _write_text_atomic(candidate_path, html)
    review_brief = _write_merchant_review_brief(run_dir, state, bundle, candidate_path)
    state["stage"] = "merchant_review"
    state["candidate_html"] = str(candidate_path)
    state["candidate_lineage"] = {
        "bundle_hash": _stable_hash(bundle),
        "markdown_hash": _sha256_bytes(markdown.encode("utf-8")),
        "candidate_html_hash": _sha256_bytes(html.encode("utf-8")),
    }
    state.pop("_merchant_review", None)
    _set_stage_tasks(
        state,
        "merchant_review",
        [{"brief": review_brief, "role": "merchant_final_reviewer"}],
    )
    _write_state(run_dir, state)
    return state


def _advance_quality_stage(
    run_dir: Path,
    state: dict,
    facts_json: dict,
    project_root,
) -> dict | None:
    stage = state.get("stage")
    if stage == "seed":
        path = _write_spine_adjudication_brief(run_dir, state)
        state["stage"] = "spine_adjudication"
        _set_stage_tasks(
            state,
            "spine_adjudication",
            [{"brief": path, "role": "spine_adjudicator"}],
        )
    elif stage == "spine_adjudication":
        slices = _load_capped_slices(run_dir)
        paths = _write_quality_fan_briefs(
            run_dir,
            slices,
            state.get("_spine") or {},
            _tables_catalog(_load_result_tables(run_dir)),
            _load_platform_semantics(run_dir),
        )
        state["stage"] = "fan"
        _set_stage_tasks(
            state,
            "fan",
            [
                {
                    "brief": path,
                    "section_id": _slug(slices[index].get("title", "")),
                    "role": "domain_writer",
                }
                for index, path in enumerate(paths)
            ],
        )
    elif stage == "fan":
        paths = _write_domain_challenge_briefs(run_dir, state)
        state["stage"] = "domain_challenge"
        _set_stage_tasks(
            state,
            "domain_challenge",
            [
                {
                    "brief": path,
                    "section_id": path.stem.split("_", 2)[-1],
                    "role": "domain_challenger",
                }
                for path in paths
            ],
        )
    elif stage == "domain_challenge":
        paths = _write_domain_adjudication_briefs(run_dir, state)
        state["stage"] = "domain_adjudication"
        _set_stage_tasks(
            state,
            "domain_adjudication",
            [
                {
                    "brief": path,
                    "section_id": path.stem.split("_", 3)[-1],
                    "role": "domain_adjudicator",
                }
                for path in paths
            ],
        )
    elif stage == "domain_adjudication":
        _write_synth_brief(run_dir, state)
        state["stage"] = "synth"
        _set_stage_tasks(
            state,
            "synth",
            [
                {
                    "brief": Path(run_dir) / "briefs" / "synth.md",
                    "role": "cross_domain_synthesizer",
                }
            ],
        )
    elif stage == "synth":
        path = _write_visual_curation_brief(run_dir, state)
        state["stage"] = "visual_curation"
        _set_stage_tasks(
            state,
            "visual_curation",
            [{"brief": path, "role": "visual_curator"}],
        )
    elif stage == "visual_curation":
        bundle = render_draft(_bundle_from_state(state), facts_json)
        state["_bundle"] = bundle
        state["_gate_rounds"] = 0
        state["_review_patch_rounds"] = 0
        state["stage"] = "gate"
        _set_stage_tasks(state, "gate", [])
        return _run_gate_stage(run_dir, state, facts_json, project_root)
    elif stage == "patch":
        bundle = render_draft(
            state.get("_bundle") or _bundle_from_state(state),
            facts_json,
        )
        state["_bundle"] = bundle
        state["stage"] = "gate"
        _set_stage_tasks(state, "gate", [])
        return _run_gate_stage(run_dir, state, facts_json, project_root)
    elif stage == "continuity":
        edits = state.get("_continuity_edits", [])
        bundle = apply_continuity_edits(
            state.get("_bundle", _bundle_from_state(state)), edits
        )
        report = _run_gate(bundle, facts_json, _load_result_tables(run_dir))
        if report.status != "PASS":
            state["_bundle"] = bundle
            return _route_deterministic(
                run_dir, state, project_root, "continuity_gate_failed"
            )
        state["_bundle"] = report.bundle
        return _enter_merchant_review(run_dir, state, facts_json)
    elif stage == "merchant_review":
        review = state.get("_merchant_review") or {}
        if review.get("verdict") == "pass":
            return finalize_narrative(run_dir, project_root=project_root)
        rounds = int(state.get("_merchant_revision_rounds") or 0)
        if rounds >= MAX_MERCHANT_REVISION_ROUNDS:
            return _route_deterministic(
                run_dir, state, project_root, "merchant_review_exhausted"
            )
        path = _write_merchant_patch_brief(run_dir, state)
        state["_merchant_revision_rounds"] = rounds + 1
        state["stage"] = "merchant_patch"
        _set_stage_tasks(
            state,
            "merchant_patch",
            [{"brief": path, "role": "merchant_targeted_reviser"}],
        )
    elif stage == "merchant_patch":
        bundle = state.get("_bundle") or _bundle_from_state(state)
        state["_bundle"] = render_draft(bundle, facts_json)
        state["stage"] = "continuity"
        state["_continuity_edits"] = []
        _write_continuity_brief(run_dir, state, state["_bundle"])
    else:
        return None
    _write_state(run_dir, state)
    return state


@_serialized_state_mutation
def advance_run(run_dir, *, project_root=None) -> dict:
    """Move the run forward one step: seed→fan→synth→gate→(patch→gate)*→continuity→gate→finalized.

    On gate exhaustion, routes to finalize_deterministic and sets stage to blocked.
    Never raises a gate failure as an exception — degradation is always graceful.
    """
    run_dir = Path(run_dir)
    state = _load_state(run_dir)
    if state is None:
        raise FileNotFoundError(f"no run at {run_dir}")
    stage = state["stage"]
    if _recover_orphaned_review_coverage_patch(state):
        stage = state["stage"]
    pending = _pending_tasks(state, stage)
    if pending:
        task_ids = ", ".join(str(task.get("task_id")) for task in pending)
        raise ValueError(f"cannot advance {stage!r}: pending briefs: {task_ids}")
    facts_json = json.loads((run_dir / "facts.json").read_text(encoding="utf-8"))
    project_root = project_root or state.get("project_root")

    if state.get("workflow_version") == QUALITY_WORKFLOW_VERSION:
        quality_state = _advance_quality_stage(
            run_dir,
            state,
            facts_json,
            project_root,
        )
        if quality_state is not None:
            return quality_state

    if stage == "seed":
        state["stage"] = "fan"
        _set_stage_tasks(state, "fan", state.pop("_fan_tasks", []))
    elif stage == "fan":
        state["stage"] = "synth"
        # Surface the recorded fan claims so the synth agent can assemble the first
        # screen from real claim_ids (Option A). Falls through to _write_state below.
        _write_synth_brief(run_dir, state)
        _set_stage_tasks(
            state,
            "synth",
            [{"brief": run_dir / "briefs" / "synth.md"}],
        )
    elif stage == "synth":
        bundle = render_draft(_bundle_from_state(state), facts_json)
        state["_bundle"] = bundle
        state["_gate_rounds"] = 0
        state["_review_patch_rounds"] = 0
        state["stage"] = "gate"
        _set_stage_tasks(state, "gate", [])
        return _run_gate_stage(run_dir, state, facts_json, project_root)
    elif stage == "gate":
        return _run_gate_stage(run_dir, state, facts_json, project_root)
    elif stage == "patch":
        bundle = render_draft(_bundle_from_state(state), facts_json)
        state["_bundle"] = bundle
        state["stage"] = "gate"
        _set_stage_tasks(state, "gate", [])
        return _run_gate_stage(run_dir, state, facts_json, project_root)
    elif stage == "review":
        # Passive multi-reviewer resolution: tally per view, route keep/drop/patch.
        return _resolve_review_stage(run_dir, state)
    elif stage == "continuity":
        edits = state.get("_continuity_edits", [])
        bundle = apply_continuity_edits(state.get("_bundle", _bundle_from_state(state)), edits)
        report = _run_gate(bundle, facts_json, _load_result_tables(run_dir))
        if report.status == "PASS":
            state["_bundle"] = report.bundle
            _write_state(run_dir, state)
            return finalize_narrative(run_dir, project_root=project_root)
        state["_bundle"] = bundle
        return _route_deterministic(run_dir, state, project_root, "continuity_gate_failed")
    _write_state(run_dir, state)
    return state


def _fmt_value(value):
    """Render a fact value for the skeleton table: thousands-separated for numbers."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:,}"
    return str(value)


def _deterministic_markdown(run_dir, facts_json: dict, report_name: str) -> str:
    """Build the '确定性骨架版' markdown straight from capped slices + facts.

    Preserves conclusions/actions/caveats verbatim (no paraphrasing) and turns
    blocked modules into a merchant-facing data request with unlocked analyses.
    Never raises on missing/partial data — absent fields are simply omitted.
    """
    run_dir = Path(run_dir)
    slices_doc = json.loads((run_dir / "domain_slices.json").read_text(encoding="utf-8"))
    capped = slices_doc.get("capped", [])

    lines = [
        f"# {report_name}（确定性骨架版）",
        "",
        "> 本报告为确定性骨架版：多智能体叙事流程未能完成，"
        "以下内容直接来自确定性分析层（L1）与唯一数字源（L2），未经叙事改写。",
        "",
    ]
    for s in capped:
        title = s.get("title", "")
        reading = s.get("reading") or {}
        lines.append(f"## {title}")
        lines.append("")
        if reading.get("conclusion"):
            lines.append(f"**结论：** {reading['conclusion']}")
            lines.append("")
        if reading.get("action"):
            lines.append(f"**建议动作：** {reading['action']}")
            lines.append("")
        facts = s.get("facts") or []
        if facts:
            lines.append("| 指标 | 数值 |")
            lines.append("| --- | --- |")
            for f in facts:
                lines.append(f"| {f.get('metric', '')} | {_fmt_value(f.get('value', ''))} |")
            lines.append("")
        caveats = reading.get("caveats") or []
        for caveat in caveats:
            lines.append(f"> 口径/证据说明：{caveat}")
        if caveats:
            lines.append("")

    blocked = slices_doc.get("blocked_modules") or []
    gaps = data_gap_markdown(blocked, result_tables=_load_result_tables(run_dir))
    if gaps:
        lines.append(gaps)
        lines.append("")

    return "\n".join(lines) + "\n"


def _visual_coverage_reason(
    markdown: str,
    result_tables: object,
    bundle: dict | None = None,
) -> str | None:
    """Non-blocking success-path signal: ``"visuals_missing"`` when the fact layer HAD
    chartable data yet the finalized narrative carries zero charts, else ``None``.

    This is the honest last line of defense behind the deterministic chart fallback
    (reporting.narrative_render): the fallback auto-injects a chart per core domain that
    *has a section present*, so the only way chartable data survives with no ``<svg>`` is
    a total gap — e.g. the bundle dropped every domain section. It is a SIGNAL, never a
    failure: the caller still finalizes (no skeleton, no gate FAIL), it just stamps the
    reason so the delivery note can say charts are missing. Never raises."""
    try:
        coverage = [
            record
            for section in (bundle or {}).get("sections") or []
            if isinstance(section, dict)
            for record in section.get("visual_coverage") or []
            if isinstance(record, dict)
        ]
        if coverage and any(record.get("status") == "omitted" for record in coverage):
            return "visuals_missing"
        if has_chartable_tables(result_tables) and "<svg" not in (markdown or ""):
            return "visuals_missing"
        return None
    except Exception:
        return "visuals_missing"


def _retained_view_ids(bundle: dict) -> list[str]:
    return [
        str(view["view_id"])
        for _section_id, _idx, view in _iter_curated_views(bundle)
        if isinstance(view, dict) and view.get("view_id")
    ]


_RESOURCE_ATTRS = {
    "script": {"src"},
    "link": {"href"},
    "img": {"src", "srcset"},
    "iframe": {"src"},
    "source": {"src", "srcset"},
    "video": {"src", "poster"},
    "audio": {"src"},
    "object": {"data"},
    "embed": {"src"},
}
_EXTERNAL_URL = re.compile(r"(?:^|,\s*)(?:https?:)?//", re.IGNORECASE)


class _DeliveryHTMLAudit(HTMLParser):
    """Collect delivery invariants from real tags, ignoring comments/script text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.starts: dict[str, int] = {"html": 0, "body": 0, "h1": 0}
        self.ends: dict[str, int] = {"html": 0, "body": 0, "h1": 0}
        self.title_starts = 0
        self.title_ends = 0
        self.titles: list[list[str]] = []
        self.h1s: list[list[str]] = []
        self.current_title: list[str] | None = None
        self.current_h1: list[str] | None = None
        self.view_ids: list[str] = []
        self.external_dependency = False
        self.css_fragments: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        attr_map = {str(key).lower(): value for key, value in attrs}
        if tag in self.starts:
            self.starts[tag] += 1
        if tag == "title" and "head" in self.stack and "svg" not in self.stack:
            self.title_starts += 1
            self.current_title = []
            self.titles.append(self.current_title)
        if tag == "h1":
            self.current_h1 = []
            self.h1s.append(self.current_h1)
        marker = attr_map.get("data-view-id")
        if marker is not None:
            self.view_ids.append(str(marker))
        for attr_name in _RESOURCE_ATTRS.get(tag, set()):
            value = attr_map.get(attr_name)
            if value is not None and _EXTERNAL_URL.search(str(value)):
                self.external_dependency = True
        style = attr_map.get("style")
        if style is not None:
            self.css_fragments.append(str(style))
        self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.ends:
            self.ends[tag] += 1
        if tag == "title" and self.current_title is not None:
            self.title_ends += 1
            self.current_title = None
        if tag == "h1" and self.current_h1 is not None:
            self.current_h1 = None
        if tag in self.stack:
            reverse_index = self.stack[::-1].index(tag)
            del self.stack[len(self.stack) - reverse_index - 1 :]

    def handle_data(self, data: str) -> None:
        if self.current_title is not None:
            self.current_title.append(data)
        if self.current_h1 is not None:
            self.current_h1.append(data)
        if "style" in self.stack:
            self.css_fragments.append(data)


def _validate_delivery_html(
    html: str,
    report_name: str,
    *,
    retained_view_ids: list[str] | None = None,
) -> None:
    html = str(html or "")
    if not html.strip():
        raise ValueError("HTML renderer returned an empty document")
    audit = _DeliveryHTMLAudit()
    audit.feed(html)
    audit.close()
    for tag in ("html", "body"):
        if audit.starts[tag] != 1 or audit.ends[tag] != 1:
            raise ValueError(f"HTML document must contain one complete {tag} element")
    if audit.title_starts != 1 or audit.title_ends != 1:
        raise ValueError("HTML document must contain one complete head title")
    title_text = "".join(audit.titles[0]).strip()
    if title_text != str(report_name or ""):
        raise ValueError("HTML title does not exactly match the report title")
    if audit.starts["h1"] != 1 or audit.ends["h1"] != 1:
        raise ValueError("HTML h1 does not exactly match the report title")
    h1_texts = ["".join(value).strip() for value in audit.h1s]
    if h1_texts != [str(report_name or "")]:
        raise ValueError("HTML h1 does not exactly match the report title")
    if re.search(r"\{t\d+\}", html):
        raise ValueError("HTML document contains an unresolved number token")
    if audit.external_dependency or any(
        re.search(r"url\(\s*[\"']?\s*(?:https?:)?//", fragment, re.IGNORECASE)
        or re.search(
            r"@import\s+(?:url\(\s*)?[\"']?\s*(?:https?:)?//",
            fragment,
            re.IGNORECASE,
        )
        for fragment in audit.css_fragments
    ):
        raise ValueError("HTML document contains an external dependency")
    markers = audit.view_ids
    for view_id in retained_view_ids or []:
        if markers.count(str(view_id)) != 1:
            raise ValueError(
                f"retained view {view_id!r} must appear exactly once in delivery HTML"
            )
    unexpected_markers = sorted(set(markers) - {str(value) for value in retained_view_ids or []})
    if unexpected_markers:
        raise ValueError(
            "delivery HTML contains unexpected data-view-id markers: "
            + ", ".join(unexpected_markers)
        )


def _validate_delivery_directory(out_dir: Path, html_path: Path) -> None:
    html_files = sorted(Path(out_dir).glob("*.html"))
    if html_files != [Path(html_path)] or not html_path.is_file():
        raise ValueError("production directory must contain exactly one final HTML")


def finalize_narrative(
    run_dir,
    *,
    project_root=None,
    timestamp=None,
    cache_hit: bool = False,
    write_cache: bool = True,
) -> dict:
    """Success delivery boundary — render the gate-passed narrative bundle to internal
    Markdown plus the user-facing HTML under a timestamped production
    folder ``outputs/<timestamp>-<report_name>/`` so successive runs never overwrite.

    The .md is written unconditionally from ``state["_bundle"]`` via bundle_to_markdown
    (the narrative renderer, NOT the skeleton one — no 确定性骨架版 banner). HTML render/write
    and gate-mode telemetry are independent. HTML failure is fail-closed: state becomes
    ``delivery_failed`` and the precise renderer error is raised. The run is finalized only
    after the HTML artifact exists.
    """
    run_dir = Path(run_dir)
    state = _load_state(run_dir)
    if state is None:
        raise FileNotFoundError(f"no run at {run_dir}")
    project_root = Path(
        project_root or state.get("project_root") or resolve_project_root()
    )
    facts_json = json.loads((run_dir / "facts.json").read_text(encoding="utf-8"))
    report_name = state["report_name"]
    bundle = state.get("_bundle") or _bundle_from_state(state)
    result_tables = _load_result_tables(run_dir)

    try:
        candidate_lineage = state.get("candidate_lineage") or {}
        expected_bundle_hash = candidate_lineage.get("bundle_hash")
        if expected_bundle_hash and expected_bundle_hash != _stable_hash(bundle):
            raise ValueError("candidate bundle changed after review")
        final_gate = _run_gate(bundle, facts_json, result_tables)
        if final_gate.status != "PASS":
            raise ValueError(f"final narrative gate failed: {final_gate.hard_failures}")
        if cache_hit:
            bundle = final_gate.bundle
        else:
            bundle = render_draft(final_gate.bundle, facts_json)
            edits = state.get("_continuity_edits") or []
            if edits:
                bundle = apply_continuity_edits(bundle, edits)
    except Exception as exc:
        failed_state = {
            **state,
            "stage": "delivery_failed",
            "delivery_status": "failed",
            "delivery_error": str(exc),
            "error": {"code": "FINAL_VALIDATION_FAILED", "message": str(exc)},
            "history": [
                *state.get("history", []),
                "delivery_failed:final_validation",
            ],
        }
        _write_state(run_dir, failed_state)
        raise

    # Pass result_tables so each retained curated view's numbers are filled by the
    # deterministic engine from the source table (the numeric-trust boundary). With
    # no tables the views degrade to prose-only — the report still delivers.
    markdown = bundle_to_markdown(
        bundle, facts_json, title=report_name, result_tables=result_tables
    )
    out_dir = run_output_dir(report_name, timestamp or run_timestamp(), project_root)
    quality_workflow = state.get("workflow_version") == QUALITY_WORKFLOW_VERSION
    single_html_workflow = state.get("workflow_version") in _SINGLE_HTML_WORKFLOWS
    if single_html_workflow:
        internal_markdown = run_dir / "internal" / "final.md"
    else:
        internal_markdown = out_dir / f"{report_name}.md"
    _write_text_atomic(internal_markdown, markdown)

    # Non-blocking visual audit of the delivered markdown: if the fact layer had
    # chartable data but not one chart survived (fallback included), record the gap so
    # the delivery note surfaces it. This never routes to skeleton or fails the gate —
    # the report still finalizes with whatever visuals it does carry.
    reason = _visual_coverage_reason(markdown, result_tables, bundle)

    html_path = out_dir / f"{report_name}.html"
    error_path = run_dir / "internal" / "render_errors.txt"
    try:
        for stale_html in out_dir.glob("*.html"):
            stale_html.unlink()
        html_path.unlink(missing_ok=True)
        html = render_markdown_document_html(markdown, title=report_name)
        _validate_delivery_html(
            html,
            report_name,
            retained_view_ids=_retained_view_ids(bundle),
        )
        final_html_hash = _sha256_bytes(html.encode("utf-8"))
        candidate_html_hash = candidate_lineage.get("candidate_html_hash")
        if candidate_html_hash and final_html_hash != candidate_html_hash:
            raise ValueError("final HTML differs from the merchant-reviewed candidate")
        _write_text_atomic(html_path, html)
        _validate_delivery_directory(out_dir, html_path)
        error_path.unlink(missing_ok=True)
    except Exception as exc:
        _write_text_atomic(error_path, f"HTML rendering failed: {exc}\n")
        failed_state = {
            **state,
            "stage": "delivery_failed",
            "delivery_status": "failed",
            "delivery_error": str(exc),
            "error": {"code": "HTML_RENDER_FAILED", "message": str(exc)},
            "artifacts": {
                key: value
                for key, value in (state.get("artifacts") or {}).items()
                if key != "html"
            },
            "internal_artifacts": {
                "markdown": str(internal_markdown),
                "error": str(error_path),
            },
            "history": [*state.get("history", []), "delivery_failed:html"],
        }
        _write_state(run_dir, failed_state)
        raise RuntimeError(f"HTML rendering failed: {exc}") from exc

    cache_status = "hit" if cache_hit else state.get("cache_status")
    cache_error = None
    cache_path = state_dir(project_root) / "frozen_narrative.json"
    if quality_workflow and write_cache and not cache_hit:
        try:
            from xhs_ceramics_analytics.reporting.frozen_narrative import write_frozen

            write_frozen(
                cache_path,
                facts_json.get("facts_hash", ""),
                bundle,
                results_hash=state.get("results_hash", ""),
                result_tables=result_tables,
            )
            cache_status = "written"
        except Exception as exc:
            cache_status = "write_failed"
            cache_error = str(exc)

    state = {
        **state,
        "_bundle": bundle,
        "stage": "finalized",
        "degradation_reason": reason,
        "delivery_status": "ready",
        "delivery_error": None,
        "error": None,
        "cache_status": cache_status,
        "cache_error": cache_error,
        "artifacts": {**(state.get("artifacts") or {}), "html": str(html_path)},
        "internal_artifacts": {
            **(state.get("internal_artifacts") or {}),
            "markdown": str(internal_markdown),
            **({"cache": str(cache_path)} if quality_workflow and cache_path.exists() else {}),
        },
        "artifact_lineage": {
            **(state.get("candidate_lineage") or {}),
            "final_bundle_hash": _stable_hash(bundle),
            "final_html_hash": _sha256_bytes(html.encode("utf-8")),
        },
        "history": [*state.get("history", []), "finalize_narrative"],
    }
    _write_state(run_dir, state)
    try:
        record = build_run_record(
            mode="frozen" if cache_hit else "gate",
            facts_hash=facts_json.get("facts_hash", ""),
            cache_hit=cache_hit,
            cache_status=cache_status,
            delivery_status="ready",
            hard_fail_counts={},
            degradation_reason=reason,
            task_counts={
                "completed": len(_stage_tasks(state, state.get("stage"))),
                "pending": 0,
            },
            quality_gates={"factcheck": "pass", "merchant_review": "pass"},
        )
        append_run_record(state_dir(project_root) / "report_runs.jsonl", record)
    except Exception:
        pass  # telemetry is best-effort; never break the report
    return state


def finalize_deterministic(run_dir, *, project_root=None, reason, timestamp=None) -> dict:
    """Deterministic skeleton fallback with the same fail-closed HTML boundary.

    Writes <report_name>.md unconditionally under a timestamped production folder
    ``outputs/<timestamp>-<report_name>/`` (matching finalize_narrative), then
    renders <report_name>.html and appends skeleton-mode telemetry to
    state_dir(project_root)/"report_runs.jsonl" (the canonical telemetry file cli.py
    also writes to, read by summarize_runs). Telemetry remains best-effort, but an
    HTML failure persists ``delivery_failed`` and raises the exact renderer error.
    Marks the run blocked only after the user-facing HTML exists.
    """
    run_dir = Path(run_dir)
    state = _load_state(run_dir)
    if state is None:
        raise FileNotFoundError(f"no run at {run_dir}")
    project_root = Path(
        project_root or state.get("project_root") or resolve_project_root()
    )
    facts_json = json.loads((run_dir / "facts.json").read_text(encoding="utf-8"))
    report_name = state["report_name"]

    markdown = _deterministic_markdown(run_dir, facts_json, report_name)
    out_dir = run_output_dir(report_name, timestamp or run_timestamp(), project_root)
    single_html_workflow = state.get("workflow_version") in _SINGLE_HTML_WORKFLOWS
    internal_markdown = (
        run_dir / "internal" / "fallback.md"
        if single_html_workflow
        else out_dir / f"{report_name}.md"
    )
    _write_text_atomic(internal_markdown, markdown)

    html_path = out_dir / f"{report_name}.html"
    error_path = run_dir / "internal" / "render_errors.txt"
    try:
        for stale_html in out_dir.glob("*.html"):
            stale_html.unlink()
        html_path.unlink(missing_ok=True)
        skeleton_title = f"{report_name}（确定性骨架版）"
        html = render_markdown_document_html(markdown, title=skeleton_title)
        _validate_delivery_html(html, skeleton_title)
        _write_text_atomic(html_path, html)
        _validate_delivery_directory(out_dir, html_path)
        error_path.unlink(missing_ok=True)
    except Exception as exc:
        _write_text_atomic(error_path, f"HTML rendering failed: {exc}\n")
        failed_state = {
            **state,
            "stage": "delivery_failed",
            "delivery_status": "failed",
            "delivery_error": str(exc),
            "error": {"code": "HTML_RENDER_FAILED", "message": str(exc)},
            "artifacts": {
                key: value
                for key, value in (state.get("artifacts") or {}).items()
                if key != "html"
            },
            "internal_artifacts": {
                "markdown": str(internal_markdown),
                "error": str(error_path),
            },
            "degradation_reason": reason,
            "history": [*state.get("history", []), "delivery_failed:html"],
        }
        _write_state(run_dir, failed_state)
        raise RuntimeError(f"HTML rendering failed: {exc}") from exc

    state = {
        **state,
        "stage": "blocked",
        "degradation_reason": reason,
        "delivery_status": "ready",
        "delivery_error": None,
        "error": None,
        "artifacts": {**(state.get("artifacts") or {}), "html": str(html_path)},
        "internal_artifacts": {
            **(state.get("internal_artifacts") or {}),
            "markdown": str(internal_markdown),
        },
        "history": [*state.get("history", []), f"finalize_deterministic:{reason}"],
    }
    _write_state(run_dir, state)
    try:
        record = build_run_record(
            mode="skeleton",
            facts_hash=facts_json.get("facts_hash", ""),
            cache_hit=False,
            cache_status=state.get("cache_status"),
            delivery_status="ready",
            degradation_reason=reason,
        )
        append_run_record(state_dir(project_root) / "report_runs.jsonl", record)
    except Exception:
        pass  # telemetry is best-effort; never break the report
    return state
