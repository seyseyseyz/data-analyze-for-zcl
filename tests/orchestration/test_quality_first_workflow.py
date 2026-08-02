import json
from pathlib import Path

import pytest

from xhs_ceramics_analytics.orchestration import narrative_workflow as nw


def _inputs():
    metric_mapping = {
        "status": "observe",
        "mapped_count": 1,
        "unmapped_count": 0,
        "coverage_rate": 1.0,
        "unmapped_fact_ids": [],
        "error": None,
    }
    platform_semantics = {
        "status": "observe",
        "runtime_scopes": ["agent_context"],
        "effects": {
            "automatic_header_mapping": "validation_gate",
            "agent_decision_support": "enabled",
            "coverage": "none",
            "raw_values": "none",
            "calculations": "none",
        },
        "catalog_reference": {"source_snapshot_sha256": "platform-v1"},
        "accepted_references": [
            {
                "platform_metric_id": 20,
                "display_name": "支付金额",
                "canonical_table": "business_overview_daily",
                "canonical_field": "gmv",
            }
        ],
    }
    facts = {
        "canonical_version": 3,
        "facts_hash": "facts-v2",
        "registry_hash": "registry-v2",
        "metric_mapping": metric_mapping,
        "platform_semantics": platform_semantics,
        "facts": {
            "core.gmv": {
                "rendered": "¥12万",
                "metric_key": "gmv",
                "metric_id": "shop.gmv",
                "unit": "cny",
                "caliber": "amount",
                "aggregation": "direct",
                "grain": "shop_day_sum",
                "direction": "up",
                "pool_id": None,
                "entity_type": None,
                "evidence_strength": "strong",
                "descriptive_reliability": "high",
                "assumption": None,
            }
        },
        "entity_registry": [],
        "absent_link_registry": [],
        "non_additive_ledger": {},
    }
    results = {
        "canonical_version": 3,
        "facts_hash": "facts-v2",
        "registry_hash": "registry-v2",
        "metric_mapping": metric_mapping,
        "platform_semantics": platform_semantics,
        "domain_slices": [
            {
                "title": "生意大盘",
                "facts": [
                    {
                        "metric": "gmv",
                        "fact_id": "core.gmv",
                        "metric_key": "gmv",
                        "metric_id": "shop.gmv",
                        "rendered": "¥12万",
                    }
                ],
                "reading": {"conclusion": "支付金额上升"},
            }
        ],
        "blocked_modules": [],
        "result_tables": {"monthly": [{"month": "2026-07", "gmv": 120000}]},
    }
    return results, facts


def _state(run_dir: Path) -> dict:
    return json.loads((run_dir / "state.json").read_text(encoding="utf-8"))


def _pending(run_dir: Path) -> list[dict]:
    return nw.status_json(run_dir)["tasks"]["pending"]


def _ingest_task(run_dir: Path, task: dict, payload) -> dict:
    return nw.ingest_output(
        run_dir,
        stage=task["stage"],
        task_id=task["task_id"],
        text=json.dumps(payload, ensure_ascii=False),
    )


def _action_card():
    return {
        "action_id": "action.core",
        "action_family": "经营复盘",
        "title": "复盘支付金额增长来源",
        "owner_role": "店铺负责人",
        "steps": ["核对商品与流量贡献"],
        "primary_fact_id": "core.gmv",
        "guardrail_fact_id": None,
        "stop_rule": "事实不支持时停止扩量",
        "license": "pilot",
        "supporting_claim_ids": ["c1"],
        "number_tokens": [],
    }


def test_versioned_quality_run_requires_explicit_multi_agent_authorization(tmp_path):
    results, facts = _inputs()

    with pytest.raises(ValueError, match="multi-agent authorization"):
        nw.prepare_run(
            tmp_path / "run",
            results=results,
            facts_json=facts,
            report_name="店铺经营诊断",
            project_root=tmp_path,
        )


def test_explicit_decline_prepares_single_html_deterministic_fallback(tmp_path):
    results, facts = _inputs()
    run_dir = tmp_path / "run"

    state = nw.prepare_run(
        run_dir,
        results=results,
        facts_json=facts,
        report_name="店铺经营诊断",
        project_root=tmp_path,
        multi_agent_declined=True,
    )
    finalized = nw.finalize_deterministic(
        run_dir,
        project_root=tmp_path,
        reason="denied",
        timestamp="20260801-120000",
    )

    output_dir = (
        tmp_path
        / ".xhs-ceramics-analytics"
        / "outputs"
        / "20260801-120000-店铺经营诊断"
    )
    assert state["workflow_version"] == nw.DETERMINISTIC_WORKFLOW_VERSION
    assert state["authorization_decision"] == "denied"
    assert finalized["stage"] == "blocked"
    assert [path.name for path in output_dir.iterdir()] == ["店铺经营诊断.html"]
    assert (run_dir / "internal" / "fallback.md").exists()


def test_quality_prepare_freezes_manifest_and_two_independent_spine_tasks(tmp_path):
    results, facts = _inputs()
    run_dir = tmp_path / "run"

    state = nw.prepare_run(
        run_dir,
        results=results,
        facts_json=facts,
        report_name="店铺经营诊断",
        project_root=tmp_path,
        multi_agent_authorized=True,
    )

    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    pending = _pending(run_dir)
    assert state["workflow_version"] == "quality-v2"
    assert manifest["authorization"]["decision"] == "authorized"
    assert manifest["delivery"] == {"surface": "single_html"}
    assert manifest["snapshot"]["facts_hash"] == "facts-v2"
    assert manifest["snapshot"]["registry_hash"] == "registry-v2"
    assert len(pending) == 2
    assert {task["role"] for task in pending} == {"spine_candidate"}
    assert len({task["task_id"] for task in pending}) == 2
    assert not list((run_dir / "briefs").glob("fan_*.md"))
    for task in pending:
        brief = Path(task["brief"]).read_text(encoding="utf-8")
        assert '"platform_semantics"' in brief
        assert '"display_name": "支付金额"' in brief


def test_quality_prepare_rejects_mismatched_platform_semantic_snapshots(tmp_path):
    results, facts = _inputs()
    facts["platform_semantics"] = {
        **facts["platform_semantics"],
        "status": "unavailable",
    }

    with pytest.raises(ValueError, match="platform_semantics"):
        nw.prepare_run(
            tmp_path / "run",
            results=results,
            facts_json=facts,
            report_name="店铺经营诊断",
            project_root=tmp_path,
            multi_agent_authorized=True,
        )


def test_quality_domain_payload_carries_read_only_platform_semantics():
    results, _facts = _inputs()

    payload = nw._quality_slice_payload(
        results["domain_slices"][0],
        {"spine_brief": {}},
        {"monthly": ["month", "gmv"]},
        results["platform_semantics"],
    )

    assert payload["platform_semantics"] == results["platform_semantics"]
    assert (
        payload["platform_semantics"]["effects"]["automatic_header_mapping"]
        == "validation_gate"
    )


def test_quality_seed_rejects_payload_outside_closed_schema_without_advancing(tmp_path):
    results, facts = _inputs()
    run_dir = tmp_path / "run"
    nw.prepare_run(
        run_dir,
        results=results,
        facts_json=facts,
        report_name="店铺经营诊断",
        project_root=tmp_path,
        multi_agent_authorized=True,
    )
    task = _pending(run_dir)[0]

    with pytest.raises(ValueError, match="spine_candidate.json"):
        _ingest_task(
            run_dir,
            task,
            {
                "candidate_id": task["candidate_id"],
                "spine_brief": {},
                "unexpected": "must be rejected",
            },
        )

    state = _state(run_dir)
    assert task["task_id"] in {item["task_id"] for item in _pending(run_dir)}
    assert state.get("_spine_candidates") in (None, {})


def test_quality_shared_stage_rejects_unknown_keys_before_task_completion(tmp_path):
    results, facts = _inputs()
    run_dir = tmp_path / "run"
    nw.prepare_run(
        run_dir,
        results=results,
        facts_json=facts,
        report_name="店铺经营诊断",
        project_root=tmp_path,
        multi_agent_authorized=True,
    )
    state = _state(run_dir)
    state["stage"] = "continuity"
    state["_bundle"] = {"sections": []}
    nw._write_continuity_brief(run_dir, state, state["_bundle"])
    nw._write_state(run_dir, state)
    task = _pending(run_dir)[0]

    with pytest.raises(ValueError, match="continuity_edit.json"):
        _ingest_task(run_dir, task, {"edits": [], "unexpected": True})

    assert task["task_id"] in {item["task_id"] for item in _pending(run_dir)}


def test_quality_review_brief_matches_closed_verdict_schema_and_ingests_response(tmp_path):
    results, facts = _inputs()
    run_dir = tmp_path / "run"
    nw.prepare_run(
        run_dir,
        results=results,
        facts_json=facts,
        report_name="店铺经营诊断",
        project_root=tmp_path,
        multi_agent_authorized=True,
    )
    state = _state(run_dir)
    state["stage"] = "review"
    state["_bundle"] = {
        "sections": [
            {
                "section_id": "生意大盘",
                "title": "生意大盘",
                "curated_views": [
                    {"view_id": "view.core", "template": "comparison_table"}
                ],
            }
        ]
    }
    nw._write_review_briefs(run_dir, state["_bundle"], state=state)
    nw._write_state(run_dir, state)
    task = next(
        item for item in _pending(run_dir) if item["lens"] == "merchant_decision"
    )
    brief = Path(task["brief"]).read_text(encoding="utf-8")

    assert '"blocker_codes":[]' in brief
    assert "revise/drop" in brief

    _ingest_task(
        run_dir,
        task,
        {
            "section_id": "生意大盘",
            "lens": "merchant_decision",
            "verdicts": [
                {
                    "view_id": "view.core",
                    "verdict": "keep",
                    "reason": "有明确经营价值",
                    "blocker_codes": [],
                }
            ],
        },
    )

    completed = nw.status_json(run_dir)["tasks"]["completed"]
    assert task["task_id"] in {item["task_id"] for item in completed}


def test_quality_review_revise_requires_a_blocker_code():
    with pytest.raises(ValueError, match="review_verdict.json"):
        nw._validate_quality_stage_payload(
            "review",
            {
                "section_id": "生意大盘",
                "lens": "merchant_decision",
                "verdicts": [
                    {
                        "view_id": "view.core",
                        "verdict": "revise",
                        "reason": "需要补足经营价值",
                        "blocker_codes": [],
                    }
                ],
            },
        )


def test_quality_workflow_never_folds_domains_for_cost(tmp_path):
    results, facts = _inputs()
    results["domain_slices"] = [
        {
            "title": f"经营域{index}",
            "facts": results["domain_slices"][0]["facts"],
            "reading": {"conclusion": f"结论{index}"},
        }
        for index in range(8)
    ]
    run_dir = tmp_path / "run"

    state = nw.prepare_run(
        run_dir,
        results=results,
        facts_json=facts,
        report_name="店铺经营诊断",
        project_root=tmp_path,
        multi_agent_authorized=True,
    )
    slices = json.loads((run_dir / "domain_slices.json").read_text(encoding="utf-8"))

    assert state["merged_sections"] == []
    assert len(slices["capped"]) == 8


def test_spine_adjudication_precedes_domain_writers_and_reaches_their_briefs(tmp_path):
    results, facts = _inputs()
    run_dir = tmp_path / "run"
    nw.prepare_run(
        run_dir,
        results=results,
        facts_json=facts,
        report_name="店铺经营诊断",
        project_root=tmp_path,
        multi_agent_authorized=True,
    )

    for index, task in enumerate(_pending(run_dir), 1):
        candidate_label = ("甲", "乙")[index - 1]
        _ingest_task(
            run_dir,
            task,
            {
                "candidate_id": f"candidate-{index}",
                "spine_brief": {
                    "decomposition_backbone": [],
                    "headline_candidate": f"候选主线{candidate_label}",
                    "section_callbacks": {"生意大盘": {"must_connect_to": "L1", "angle_hint": "钱"}},
                    "broadcast_facts": ["core.gmv"],
                },
            },
        )
    state = nw.advance_run(run_dir, project_root=tmp_path)
    assert state["stage"] == "spine_adjudication"
    adjudicator = _pending(run_dir)[0]
    assert adjudicator["role"] == "spine_adjudicator"

    _ingest_task(
        run_dir,
        adjudicator,
        {
            "selected_candidate_id": "candidate-1",
            "spine_brief": {
                "decomposition_backbone": [
                    {
                        "link_id": "L1",
                        "from": "支付金额",
                        "to": "经营结果",
                        "anchor_fact_ids": ["core.gmv"],
                        "relation": "accounting_identity",
                    }
                ],
                "headline_candidate": "支付金额决定本期盘面",
                "section_callbacks": {"生意大盘": {"must_connect_to": "L1", "angle_hint": "先钱后机制"}},
                "broadcast_facts": ["core.gmv"],
            },
            "rejected_reasons": [{"candidate_id": "candidate-2", "reason": "主线较弱"}],
            "unresolved_dissent": [],
        },
    )
    state = nw.advance_run(run_dir, project_root=tmp_path)

    assert state["stage"] == "fan"
    writer_task = _pending(run_dir)[0]
    assert writer_task["role"] == "domain_writer"
    brief = Path(writer_task["brief"]).read_text(encoding="utf-8")
    assert "core.gmv" in brief
    assert "先钱后机制" in brief


def test_domain_writer_flows_through_challenge_and_domain_adjudication(tmp_path):
    results, facts = _inputs()
    run_dir = tmp_path / "run"
    nw.prepare_run(
        run_dir,
        results=results,
        facts_json=facts,
        report_name="店铺经营诊断",
        project_root=tmp_path,
        multi_agent_authorized=True,
    )
    state = _state(run_dir)
    state["stage"] = "fan"
    state["_spine"] = {
        "spine_brief": {
            "decomposition_backbone": [],
            "headline_candidate": "主线",
            "section_callbacks": {},
            "broadcast_facts": ["core.gmv"],
        }
    }
    writer_brief = run_dir / "briefs" / "fan_00_生意大盘.md"
    writer_brief.write_text("writer", encoding="utf-8")
    nw._set_stage_tasks(
        state,
        "fan",
        [{"brief": writer_brief, "section_id": "生意大盘", "role": "domain_writer"}],
    )
    nw._write_state(run_dir, state)

    claim = {
        "claim_id": "c1",
        "section_id": "生意大盘",
        "claim_kind": "measurement",
        "sentence": "支付金额 {t0}。",
        "number_tokens": [
            {
                "token_id": "t0",
                "fact_id": "core.gmv",
                "expected_metric_key": "gmv",
                "direction": "up",
            }
        ],
        "entity_refs": [],
        "confidence": "强",
        "causal_link": None,
    }
    _ingest_task(
        run_dir,
        _pending(run_dir)[0],
        {"section_id": "生意大盘", "title": "生意大盘", "claims": [claim], "spine_callbacks": []},
    )
    state = nw.advance_run(run_dir, project_root=tmp_path)
    assert state["stage"] == "domain_challenge"
    assert _pending(run_dir)[0]["role"] == "domain_challenger"

    _ingest_task(
        run_dir,
        _pending(run_dir)[0],
        {
            "section_id": "生意大盘",
            "issues": [{"claim_id": "c1", "severity": "note", "reason": "保留"}],
            "recommendation": "accept",
        },
    )
    state = nw.advance_run(run_dir, project_root=tmp_path)
    assert state["stage"] == "domain_adjudication"
    assert _pending(run_dir)[0]["role"] == "domain_adjudicator"


def test_adjudicated_claim_tokens_reach_synth_before_visual_curation(tmp_path):
    results, facts = _inputs()
    run_dir = tmp_path / "run"
    nw.prepare_run(
        run_dir,
        results=results,
        facts_json=facts,
        report_name="店铺经营诊断",
        project_root=tmp_path,
        multi_agent_authorized=True,
    )
    claim = {
        "claim_id": "c1",
        "section_id": "生意大盘",
        "claim_kind": "measurement",
        "sentence": "支付金额 {t0}。",
        "number_tokens": [
            {
                "token_id": "t0",
                "fact_id": "core.gmv",
                "expected_metric_key": "gmv",
                "direction": "up",
            }
        ],
        "entity_refs": [],
        "confidence": "强",
        "causal_link": None,
    }
    state = _state(run_dir)
    state.update(
        {
            "stage": "domain_adjudication",
            "sections": {
                "生意大盘": {
                    "section_id": "生意大盘",
                    "title": "生意大盘",
                    "body": "",
                    "claims": [claim],
                    "spine_callbacks": [],
                }
            },
        }
    )
    nw._set_stage_tasks(state, "domain_adjudication", [])
    nw._write_state(run_dir, state)

    state = nw.advance_run(run_dir, project_root=tmp_path)
    assert state["stage"] == "synth"
    synth_brief = Path(_pending(run_dir)[0]["brief"]).read_text(encoding="utf-8")
    assert '"number_tokens"' in synth_brief
    assert "core.gmv" in synth_brief

    _ingest_task(
        run_dir,
        _pending(run_dir)[0],
        {
            "headline": "支付金额上升",
            "first_screen": {"spine": [claim], "panel": [], "actions": []},
            "action_cards": [_action_card()],
            "mechanism": [],
            "cannot_say": [],
            "spine_final": {"backbone": []},
        },
    )
    state = nw.advance_run(run_dir, project_root=tmp_path)

    assert state["stage"] == "visual_curation"
    assert _pending(run_dir)[0]["role"] == "visual_curator"
    assert state["_synth"]["action_cards"][0]["action_id"] == "action.core"


def test_quality_synth_requires_explicit_action_cards_decision(tmp_path):
    results, facts = _inputs()
    run_dir = tmp_path / "run"
    nw.prepare_run(
        run_dir,
        results=results,
        facts_json=facts,
        report_name="店铺经营诊断",
        project_root=tmp_path,
        multi_agent_authorized=True,
    )
    state = _state(run_dir)
    state["stage"] = "synth"
    synth_brief = run_dir / "briefs" / "synth.md"
    synth_brief.write_text("synth", encoding="utf-8")
    nw._set_stage_tasks(
        state,
        "synth",
        [{"brief": synth_brief, "role": "cross_domain_synthesizer"}],
    )
    nw._write_state(run_dir, state)

    with pytest.raises(ValueError, match="action_cards"):
        _ingest_task(
            run_dir,
            _pending(run_dir)[0],
            {
                "headline": "支付金额上升",
                "first_screen": {"spine": [], "panel": [], "actions": []},
                "mechanism": [],
                "cannot_say": [],
                "spine_final": {"backbone": []},
            },
        )


def test_continuity_routes_to_merchant_review_before_final_delivery(tmp_path, monkeypatch):
    results, facts = _inputs()
    run_dir = tmp_path / "run"
    nw.prepare_run(
        run_dir,
        results=results,
        facts_json=facts,
        report_name="店铺经营诊断",
        project_root=tmp_path,
        multi_agent_authorized=True,
    )
    state = _state(run_dir)
    state.update(
        {
            "stage": "continuity",
            "_bundle": {
                "facts_hash": "facts-v2",
                "headline": "支付金额上升",
                "first_screen": {"spine": [], "panel": [], "actions": []},
                "spine_final": {"backbone": []},
                "sections": [],
                "cannot_say": [],
            },
            "_continuity_edits": [],
        }
    )
    continuity_brief = run_dir / "briefs" / "continuity.md"
    continuity_brief.write_text("continuity", encoding="utf-8")
    nw._set_stage_tasks(state, "continuity", [])
    nw._write_state(run_dir, state)
    monkeypatch.setattr(
        nw,
        "_run_gate",
        lambda bundle, facts_json, tables: type(
            "Report", (), {"status": "PASS", "bundle": bundle, "hard_failures": []}
        )(),
    )

    state = nw.advance_run(run_dir, project_root=tmp_path)

    assert state["stage"] == "merchant_review"
    task = _pending(run_dir)[0]
    assert task["role"] == "merchant_final_reviewer"
    assert (run_dir / "candidate.html").exists()


def test_merchant_revision_is_id_scoped_and_cannot_replace_the_bundle(tmp_path):
    results, facts = _inputs()
    run_dir = tmp_path / "run"
    nw.prepare_run(
        run_dir,
        results=results,
        facts_json=facts,
        report_name="店铺经营诊断",
        project_root=tmp_path,
        multi_agent_authorized=True,
    )
    claim = {
        "claim_id": "c1",
        "section_id": "生意大盘",
        "claim_kind": "measurement",
        "sentence": "支付金额 {t0}。",
        "number_tokens": [
            {
                "token_id": "t0",
                "fact_id": "core.gmv",
                "expected_metric_key": "gmv",
                "direction": "up",
            }
        ],
        "entity_refs": [],
        "confidence": "强",
        "causal_link": None,
    }
    bundle = {
        "facts_hash": "facts-v2",
        "headline": "支付金额上升",
        "first_screen": {"spine": [claim], "panel": [], "actions": []},
        "action_cards": [_action_card()],
        "mechanism": [],
        "spine_final": {"backbone": []},
        "sections": [
            {
                "section_id": "生意大盘",
                "title": "生意大盘",
                "claims": [claim],
                "spine_callbacks": [],
            }
        ],
        "cannot_say": [],
    }
    state = _state(run_dir)
    state.update({"stage": "merchant_review", "_bundle": bundle})
    review_brief = run_dir / "briefs" / "merchant_review.md"
    review_brief.write_text("review", encoding="utf-8")
    nw._set_stage_tasks(
        state,
        "merchant_review",
        [{"brief": review_brief, "role": "merchant_final_reviewer"}],
    )
    nw._write_state(run_dir, state)

    _ingest_task(
        run_dir,
        _pending(run_dir)[0],
        {
            "verdict": "revise",
            "issues": [
                {
                    "issue_id": "merchant-1",
                    "target_type": "action",
                    "target_id": "action.core",
                    "severity": "major",
                    "reason": "动作标题不够明确",
                    "requested_change": "明确复盘对象",
                }
            ],
        },
    )
    state = nw.advance_run(run_dir, project_root=tmp_path)
    assert state["stage"] == "merchant_patch"

    with pytest.raises(ValueError, match="revision array"):
        _ingest_task(run_dir, _pending(run_dir)[0], {"bundle": {"sections": []}})

    replacement = {**_action_card(), "title": "复盘支付金额增长来源与可持续性"}
    state = _ingest_task(
        run_dir,
        _pending(run_dir)[0],
        [
            {
                "revision_id": "revision-1",
                "round": 1,
                "target_type": "action",
                "target_id": "action.core",
                "operation": "replace",
                "source_blocker_ids": ["merchant-1"],
                "replacement": replacement,
                "reason": "按终审意见明确动作",
            }
        ],
    )

    assert state["_bundle"]["action_cards"][0]["title"] == replacement["title"]
    assert state["_bundle"]["sections"] == bundle["sections"]


def test_merchant_review_rejects_unknown_target(tmp_path):
    results, facts = _inputs()
    run_dir = tmp_path / "run"
    nw.prepare_run(
        run_dir,
        results=results,
        facts_json=facts,
        report_name="店铺经营诊断",
        project_root=tmp_path,
        multi_agent_authorized=True,
    )
    state = _state(run_dir)
    state.update(
        {
            "stage": "merchant_review",
            "_bundle": {
                "facts_hash": "facts-v2",
                "headline": "支付金额上升",
                "first_screen": {"spine": [], "panel": [], "actions": []},
                "action_cards": [],
                "mechanism": [],
                "spine_final": {"backbone": []},
                "sections": [],
                "cannot_say": [],
            },
        }
    )
    review_brief = run_dir / "briefs" / "merchant_review.md"
    review_brief.write_text("review", encoding="utf-8")
    nw._set_stage_tasks(state, "merchant_review", [{"brief": review_brief}])
    nw._write_state(run_dir, state)

    with pytest.raises(ValueError, match="unknown merchant review target"):
        _ingest_task(
            run_dir,
            _pending(run_dir)[0],
            {
                "verdict": "revise",
                "issues": [
                    {
                        "issue_id": "merchant-1",
                        "target_type": "claim",
                        "target_id": "missing-claim",
                        "severity": "blocker",
                        "reason": "不存在",
                        "requested_change": "修复",
                    }
                ],
            },
        )


def test_merchant_replacement_cannot_change_claim_fact_binding():
    claim = {
        "claim_id": "c1",
        "section_id": "生意大盘",
        "claim_kind": "measurement",
        "sentence": "支付金额 {t0}。",
        "number_tokens": [
            {
                "token_id": "t0",
                "fact_id": "core.gmv",
                "expected_metric_key": "gmv",
                "direction": "up",
            }
        ],
        "entity_refs": [],
        "confidence": "强",
        "causal_link": None,
    }
    bundle = {
        "sections": [{"section_id": "生意大盘", "claims": [claim]}],
        "first_screen": {"spine": [], "panel": [], "actions": []},
    }
    review = {
        "issues": [
            {
                "issue_id": "merchant-claim",
                "target_type": "claim",
                "target_id": "c1",
            }
        ]
    }
    replacement = json.loads(json.dumps(claim))
    replacement["number_tokens"][0]["fact_id"] = "other.valid.fact"

    with pytest.raises(ValueError, match="immutable evidence binding"):
        nw._apply_merchant_revisions(
            bundle,
            [
                {
                    "revision_id": "revision-claim",
                    "round": 1,
                    "target_type": "claim",
                    "target_id": "c1",
                    "operation": "replace",
                    "source_blocker_ids": ["merchant-claim"],
                    "replacement": replacement,
                    "reason": "尝试换事实",
                }
            ],
            review,
            expected_round=1,
        )


def test_quality_patch_rejects_bundle_overwrite_and_changes_only_named_target(tmp_path):
    results, facts = _inputs()
    run_dir = tmp_path / "run"
    nw.prepare_run(
        run_dir,
        results=results,
        facts_json=facts,
        report_name="店铺经营诊断",
        project_root=tmp_path,
        multi_agent_authorized=True,
    )
    claim = {
        "claim_id": "c1",
        "section_id": "生意大盘",
        "claim_kind": "measurement",
        "sentence": "支付金额 {t0}。",
        "number_tokens": [
            {
                "token_id": "t0",
                "fact_id": "core.gmv",
                "expected_metric_key": "gmv",
                "direction": "up",
            }
        ],
        "entity_refs": [],
        "confidence": "强",
        "causal_link": None,
    }
    bundle = {
        "facts_hash": "facts-v2",
        "headline": "原始标题",
        "first_screen": {"spine": [], "panel": [], "actions": []},
        "sections": [{"section_id": "生意大盘", "claims": [claim]}],
    }
    state = _state(run_dir)
    state.update(
        {
            "stage": "patch",
            "_bundle": bundle,
            "_patch_round": 1,
            "_patch_review": {
                "issues": [
                    {
                        "issue_id": "gate-1",
                        "target_type": "claim",
                        "target_id": "c1",
                    }
                ]
            },
        }
    )
    patch_brief = run_dir / "briefs" / "patch.md"
    patch_brief.write_text("patch", encoding="utf-8")
    nw._set_stage_tasks(state, "patch", [{"brief": patch_brief}])
    nw._write_state(run_dir, state)

    with pytest.raises(ValueError, match="targeted revision array"):
        _ingest_task(run_dir, _pending(run_dir)[0], {"bundle": {"headline": "覆盖"}})

    replacement = {**claim, "sentence": "支付金额已提升至 {t0}。"}
    patched = _ingest_task(
        run_dir,
        _pending(run_dir)[0],
        [
            {
                "revision_id": "revision-gate-1",
                "round": 1,
                "target_type": "claim",
                "target_id": "c1",
                "operation": "replace",
                "source_blocker_ids": ["gate-1"],
                "replacement": replacement,
                "reason": "只修正文案",
            }
        ],
    )

    assert patched["_bundle"]["headline"] == "原始标题"
    assert patched["_bundle"]["sections"][0]["claims"][0]["sentence"] == replacement[
        "sentence"
    ]


def test_quality_finalize_publishes_one_html_and_writes_internal_cache(tmp_path):
    results, facts = _inputs()
    run_dir = tmp_path / "run"
    nw.prepare_run(
        run_dir,
        results=results,
        facts_json=facts,
        report_name="店铺经营诊断",
        project_root=tmp_path,
        multi_agent_authorized=True,
    )
    state = _state(run_dir)
    state["_bundle"] = {
        "facts_hash": "facts-v2",
        "headline": "支付金额上升",
        "first_screen": {"spine": [], "panel": [], "actions": []},
        "spine_final": {"backbone": []},
        "sections": [],
        "cannot_say": [],
    }
    nw._write_state(run_dir, state)

    finalized = nw.finalize_narrative(
        run_dir,
        project_root=tmp_path,
        timestamp="20260801-120000",
    )

    output_dir = (
        tmp_path
        / ".xhs-ceramics-analytics"
        / "outputs"
        / "20260801-120000-店铺经营诊断"
    )
    assert finalized["stage"] == "finalized"
    assert finalized["delivery_status"] == "ready"
    assert finalized["cache_status"] == "written"
    assert [path.name for path in output_dir.iterdir()] == ["店铺经营诊断.html"]
    assert (run_dir / "internal" / "final.md").exists()
    frozen = json.loads(
        (tmp_path / ".xhs-ceramics-analytics" / "frozen_narrative.json").read_text(
            encoding="utf-8"
        )
    )
    assert frozen["result_tables"] == results["result_tables"]


def test_quality_prepare_cache_hit_skips_all_agent_briefs(tmp_path):
    results, facts = _inputs()
    first_run = tmp_path / "first"
    nw.prepare_run(
        first_run,
        results=results,
        facts_json=facts,
        report_name="店铺经营诊断",
        project_root=tmp_path,
        multi_agent_authorized=True,
    )
    state = _state(first_run)
    state["_bundle"] = {
        "facts_hash": "facts-v2",
        "headline": "支付金额上升",
        "first_screen": {"spine": [], "panel": [], "actions": []},
        "spine_final": {"backbone": []},
        "sections": [],
        "cannot_say": [],
    }
    nw._write_state(first_run, state)
    nw.finalize_narrative(
        first_run,
        project_root=tmp_path,
        timestamp="20260801-120000",
    )

    cached_run = tmp_path / "cached"
    cached = nw.prepare_run(
        cached_run,
        results=results,
        facts_json=facts,
        report_name="店铺经营诊断复跑",
        project_root=tmp_path,
        multi_agent_authorized=True,
    )

    assert cached["stage"] == "finalized"
    assert cached["cache_status"] == "hit"
    assert nw.status_json(cached_run)["tasks"]["pending"] == []
    assert not list((cached_run / "briefs").glob("*.md"))


def test_quality_prepare_cache_misses_when_results_change(tmp_path):
    results, facts = _inputs()
    first_run = tmp_path / "first"
    nw.prepare_run(
        first_run,
        results=results,
        facts_json=facts,
        report_name="店铺经营诊断",
        project_root=tmp_path,
        multi_agent_authorized=True,
    )
    state = _state(first_run)
    state["_bundle"] = {
        "facts_hash": "facts-v2",
        "headline": "支付金额上升",
        "first_screen": {"spine": [], "panel": [], "actions": []},
        "spine_final": {"backbone": []},
        "sections": [],
        "cannot_say": [],
    }
    nw._write_state(first_run, state)
    nw.finalize_narrative(
        first_run,
        project_root=tmp_path,
        timestamp="20260801-120000",
    )

    changed_results = dict(results)
    changed_results["blocked_modules"] = ["newly_blocked"]
    second_run = tmp_path / "changed"
    prepared = nw.prepare_run(
        second_run,
        results=changed_results,
        facts_json=facts,
        report_name="店铺经营诊断复跑",
        project_root=tmp_path,
        multi_agent_authorized=True,
    )

    assert prepared["stage"] == "seed"
    assert prepared["cache_status"] == "miss"
    assert len(nw.status_json(second_run)["tasks"]["pending"]) == 2


def test_quality_prepare_regates_hash_consistent_but_semantically_invalid_cache(tmp_path):
    from xhs_ceramics_analytics.reporting.frozen_narrative import payload_hash

    results, facts = _inputs()
    first_run = tmp_path / "first"
    nw.prepare_run(
        first_run,
        results=results,
        facts_json=facts,
        report_name="店铺经营诊断",
        project_root=tmp_path,
        multi_agent_authorized=True,
    )
    state = _state(first_run)
    state["_bundle"] = {
        "facts_hash": "facts-v2",
        "headline": "支付金额上升",
        "first_screen": {"spine": [], "panel": [], "actions": []},
        "spine_final": {"backbone": []},
        "sections": [],
        "cannot_say": [],
    }
    nw._write_state(first_run, state)
    nw.finalize_narrative(
        first_run,
        project_root=tmp_path,
        timestamp="20260802-120000",
    )

    cache_path = tmp_path / ".xhs-ceramics-analytics" / "frozen_narrative.json"
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["narrative_bundle"]["first_screen"]["actions"] = ["把支付金额做到 999 亿"]
    payload["narrative_bundle_hash"] = payload_hash(payload["narrative_bundle"])
    cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    second_run = tmp_path / "second"
    prepared = nw.prepare_run(
        second_run,
        results=results,
        facts_json=facts,
        report_name="店铺经营诊断复跑",
        project_root=tmp_path,
        multi_agent_authorized=True,
    )

    assert prepared["stage"] == "seed"
    assert prepared["cache_status"] == "invalid"
