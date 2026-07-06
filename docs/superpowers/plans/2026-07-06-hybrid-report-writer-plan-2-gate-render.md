# Hybrid Report Writer — Plan 2: Gate / Render / Freeze / Skeleton / CLI

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic layer that consumes Plan 1's `FactBook`/`facts.json` and a
multi-agent-produced `narrative_bundle` (JSON) into a merchant report: a structural fact-check gate
(hard-fail truth violations, warn on timidity, deterministic confidence cap), a `{tN}`→`fact.rendered`
renderer, a frozen-narrative override (cache key), a first-screen assembler, a 0-agent skeleton floor,
and the `xhs-ca` subcommands that drive them.

**Architecture:** Every number string comes from Plan 1's `Fact.rendered`; the writer's sentences carry
only opaque `{tN}` tokens (no digits). `factcheck_gate.run_gate(bundle, facts_json)` validates the
declared token/claim structure against the facts and registries — a fabricated number-string is
*unrepresentable*. Gate PASS → `narrative_render` fills tokens, applies continuity edits, and freezes
the bundle under the triple key `(facts_hash, narrative_schema_version, renderer_version)` beside
`mapping_overrides.yaml`. Gate exhaustion or an agent-less host → deterministic `skeleton` reusing the
existing `render_markdown` compositor. All modules are pure/never-raise and host-neutral (0 agents).

**Tech Stack:** Python 3.14 stdlib only (`hashlib`, `json`, `re`, `inspect`, `dataclasses`), Typer for
CLI, existing `reporting/` renderers. Tests: pytest via `.venv/bin/python -m pytest`.

## Global Constraints

- Python 3.14; `.venv/bin/python` is THE interpreter. Ruff line-length 100.
- Modules never raise; degrade + record. Emoji is real merchant content — never strip.
- No Co-Authored-By trailer. Commit/push/发布 only on explicit user request.
- The writer owns wording; **Python owns rounding**; the gate owns truth. A magnitude number string
  must be byte-equal to a real `fact.rendered`; the writer never emits a bare digit.
- Bold conclusions are never suppressed — confidence is only ever a 强/中/弱 tag, never a deletion or a
  visual greying of the conclusion. HARD-FAIL blocks render; WARN attaches a caveat.
- Mechanism/causal claims are Python-capped at 弱 (single-window, no control group).
- No note→order attribution number; a *quantified* attribution on an absent link is a hard fail; a
  *directional* tagged-weak judgment passes.

## The narrative_bundle / claim JSON contract (produced by L3 agents, validated here)

These plain-dict shapes are the contract every task in this plan consumes. (Plan 3 ships the JSON
Schemas + agent prompts that emit them; this plan validates and renders them.)

```jsonc
// claim — the atom
{
  "claim_id": "core.gmv_bridge",
  "section_id": "core_business",
  "claim_kind": "measurement" | "mechanism" | "sizing",
  "sentence": "5→6月人均产出从 {t0} 回落到 {t1}。",   // opaque {tN}, NO digits
  "number_tokens": [
    {"token_id": "t0", "fact_id": "core_business_diagnosis.per_visitor_gmv_may",
     "expected_metric_key": "per_visitor_gmv_may", "direction": null}
  ],
  "entity_refs": [],                    // must ⊆ facts.entity_registry
  "confidence": "强" | "中" | "弱",
  "causal_link": {"from_entity_type": "note", "to_entity_type": "order", "quantified": false} | null,
  "next_test": null,
  "spine_ref": "L1" | null
}

// narrative_bundle — what the gate validates and freezes
{
  "facts_hash": "<sha256 from facts.json>",
  "headline": "6月人均产出走低，主要是客单价与转化拖累。",
  "first_screen": {
    "spine":  [claim, ...],            // 因果主线
    "panel":  [claim, ...],            // 盘面（够格结论）
    "actions": ["本周先做…", ...]       // 本周重点（纯文本，无数字或用 {tN}）
  },
  "spine_final": {
    "backbone": [
      {"link_id": "L1", "from": "traffic", "to": "gmv", "anchor_fact_ids": ["..."],
       "relation": "accounting_identity" | "weak_causal_overlay"}
    ]
  },
  "sections": [
    {"section_id": "core_business", "title": "生意大盘·月对月",
     "claims": [claim, ...], "table_ref": "core_business_diagnosis", "chart_ref": "scissors",
     "spine_callbacks": ["L1"]}
  ],
  "cannot_say": ["笔记→订单归因：平台无点击→成交链路，永久不可解。", ...]
}
```

`facts_json` is the parsed `facts.json` (Plan 1 `factbook_to_json`): keys `facts_hash`, `facts`
(`{fact_id: {rendered, metric_key, direction, pool_id, entity_type, evidence_strength,
descriptive_reliability, assumption, value, ...}}`), `entity_registry`, `absent_link_registry`,
`module_reading`, `blocked_modules`, `shared_spine_facts`, `non_additive_ledger`, `domain_slices`.

Evidence enums serialize as StrEnum values: `evidence_strength ∈ {strong,medium,weak,not_judgable}`,
`descriptive_reliability ∈ {high,medium,low,not_applicable}` or `null`.

## File structure & task map

| Task | File | Responsibility | Depends on |
|---|---|---|---|
| T1 | `reporting/first_screen.py` | assemble section-0 markdown from `first_screen` + headline | — |
| T2 | `reporting/factcheck_gate.py` | all gate rules + deterministic confidence cap → `GateReport` | Plan 1 facts_export |
| T3 | `reporting/frozen_narrative.py` | version keys + frozen override read/write + cache-hit test | Plan 1 facts_export |
| T4 | `reporting/narrative_render.py` | `{tN}` fill, continuity edits, bundle→markdown, render-frozen, skeleton | T1, T2 |
| T5 | `cli.py` | `gate`/`render-draft`/`finalize`/`render-frozen`/`skeleton` subcommands | T2, T3, T4 |

T1–T3 touch distinct new files (parallel-safe). T4 imports T1+T2. T5 imports T2+T3+T4 and edits the
shared `cli.py`, so it runs last.

---

### Task 1: First-screen assembler (`first_screen.py`)

**Files:**
- Create: `xhs_ceramics_analytics/reporting/first_screen.py`
- Test: `tests/test_reporting_first_screen.py`

**Interfaces:**
- Consumes: a `narrative_bundle` dict whose claims already carry a filled `rendered_sentence` (Plan 2
  T4 fills it before calling; for T1's own tests we pass claims that already have `rendered_sentence`).
- Produces: `first_screen_markdown(bundle: dict) -> str` — the section-0 markdown block (headline +
  因果主线 + 盘面 + 本周重点). Content-driven length: empty lists emit no heading. Never raises.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reporting_first_screen.py
from xhs_ceramics_analytics.reporting.first_screen import first_screen_markdown


def _claim(cid, sentence, conf="强"):
    return {"claim_id": cid, "rendered_sentence": sentence, "confidence": conf}


def test_renders_headline_spine_panel_actions():
    bundle = {
        "headline": "6月人均产出走低，主要是客单价与转化拖累。",
        "first_screen": {
            "spine": [_claim("s0", "5→6月人均产出从 ¥10.0 回落到 ¥8.7（与后台4.6%转化同口径）。")],
            "panel": [_claim("p0", "退款总额 ¥20.8万，发货前占 ¥12.9万。", "中")],
            "actions": ["本周先核对千帆是否支持发货前拦截。"],
        },
    }
    md = first_screen_markdown(bundle)
    assert "6月人均产出走低" in md
    assert "¥10.0 回落到 ¥8.7" in md
    assert "退款总额 ¥20.8万" in md
    assert "（中）" in md  # panel conclusion carries its confidence tag
    assert "本周先核对千帆是否支持发货前拦截。" in md


def test_content_driven_omits_empty_blocks():
    bundle = {"headline": "只有主线。", "first_screen": {"spine": [], "panel": [], "actions": []}}
    md = first_screen_markdown(bundle)
    assert "只有主线。" in md
    assert "盘面" not in md  # no empty 盘面 heading
    assert "本周重点" not in md


def test_never_raises_on_missing_keys():
    assert isinstance(first_screen_markdown({}), str)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reporting_first_screen.py -v`
Expected: FAIL with `ModuleNotFoundError: ...first_screen`.

- [ ] **Step 3: Write minimal implementation**

```python
# xhs_ceramics_analytics/reporting/first_screen.py
"""Assemble the section-0 首屏导读 (headline + 因果主线 + 盘面 + 本周重点).

Content-driven length: a block with no qualifying content emits no heading — the
首屏 is an引子, never padded to a fixed three-line template nor truncated to fit one.
Consumes claims whose ``rendered_sentence`` is already filled by narrative_render.
Pure, never raises.
"""


def _lines(claims: list[dict], *, tag: bool) -> list[str]:
    out: list[str] = []
    for claim in claims or []:
        sentence = str(claim.get("rendered_sentence") or claim.get("sentence") or "").strip()
        if not sentence:
            continue
        conf = claim.get("confidence")
        if tag and conf:
            sentence = f"{sentence}（{conf}）"
        out.append(f"- {sentence}")
    return out


def first_screen_markdown(bundle: dict) -> str:
    fs = (bundle or {}).get("first_screen") or {}
    parts: list[str] = ["## 首屏导读"]
    headline = str((bundle or {}).get("headline") or "").strip()
    if headline:
        parts.append(f"**{headline}**")

    spine = _lines(fs.get("spine"), tag=True)
    if spine:
        parts.append("**因果主线**")
        parts.extend(spine)

    panel = _lines(fs.get("panel"), tag=True)
    if panel:
        parts.append("**盘面**")
        parts.extend(panel)

    actions = [str(a).strip() for a in (fs.get("actions") or []) if str(a).strip()]
    if actions:
        parts.append("**本周重点**")
        parts.extend(f"- {a}" for a in actions)

    return "\n\n".join(parts) + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_reporting_first_screen.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/reporting/first_screen.py tests/test_reporting_first_screen.py
git commit -m "feat(reporting): first-screen 导读 assembler (content-driven)"
```

---

### Task 2: Fact-check gate (`factcheck_gate.py`)

**Files:**
- Create: `xhs_ceramics_analytics/reporting/factcheck_gate.py`
- Test: `tests/test_reporting_factcheck_gate.py`

**Interfaces:**
- Consumes: `bundle` (narrative_bundle dict), `facts_json` (parsed facts.json dict). Reads
  `facts_json["facts"]`, `entity_registry`, `absent_link_registry`, `non_additive_ledger`.
- Produces:
  - `GateReport` frozen dataclass: `status: str` (`"PASS"`/`"FAIL"`), `hard_failures: list[dict]`,
    `warnings: list[dict]`, `capped_claims: list[dict]`, `bundle: dict` (confidence-capped copy).
    Each failure/warning is `{"code": str, "claim_id": str | None, "detail": str}`.
  - `run_gate(bundle: dict, facts_json: dict) -> GateReport`.
  - `gate_report_to_json(report: GateReport) -> str` (deterministic, sorted keys, indent=2).
- HARD codes: `MISSING_FACT`, `NONEXISTENT_SLICE`, `METRIC_MISBIND`, `DIRECTION_CONFLICT`,
  `INVENTED_ENTITY`, `MAGNITUDE_UNBOUND`, `QUANTIFIED_ATTRIBUTION`, `SUMMED_POOLS`,
  `DANGLING_CALLBACK`.
- WARN codes: `UNTAGGED_MECHANISM`, `MISSED_MECHANISM`, `UNLABELED_SIZING`,
  `MISSING_SPINE_CALLBACK`, `REDUNDANT_HEADLINE`, `CONFIDENCE_CAPPED`.
- Confidence cap: `claim.confidence ≤ allowed(anchors)`; mechanism always 弱. Capping produces a NEW
  bundle (immutability) — the input is never mutated.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reporting_factcheck_gate.py
import copy

from xhs_ceramics_analytics.reporting.factcheck_gate import run_gate


def _facts(**overrides):
    base = {
        "facts_hash": "h",
        "facts": {
            "m.gmv": {"rendered": "¥20.8万", "metric_key": "gmv", "direction": "down",
                      "pool_id": None, "entity_type": None, "evidence_strength": "strong",
                      "descriptive_reliability": "high", "assumption": None},
            "m.aov": {"rendered": "¥195", "metric_key": "aov", "direction": "down",
                      "pool_id": None, "entity_type": None, "evidence_strength": "medium",
                      "descriptive_reliability": "medium", "assumption": None},
            "pool.pre": {"rendered": "¥12.9万", "metric_key": "preship", "direction": None,
                         "pool_id": "pre_ship", "entity_type": None, "evidence_strength": "strong",
                         "descriptive_reliability": "high", "assumption": "仅发货前池"},
            "pool.post": {"rendered": "¥7.9万", "metric_key": "postship", "direction": None,
                          "pool_id": "post_ship", "entity_type": None,
                          "evidence_strength": "strong", "descriptive_reliability": "high",
                          "assumption": None},
            "sku.hot": {"rendered": "¥3.1万", "metric_key": "sku_gmv", "direction": "up",
                        "pool_id": None, "entity_type": "sku", "evidence_strength": "weak",
                        "descriptive_reliability": "medium", "assumption": None},
        },
        "entity_registry": ["兴安岭之夜", "鱼盘"],
        "absent_link_registry": ["note->order", "退款原因"],
        "non_additive_ledger": {"rows": [], "net_total": None, "banner": "各池口径不同"},
    }
    base.update(overrides)
    return base


def _claim(**kw):
    c = {"claim_id": "c0", "section_id": "core_business", "claim_kind": "measurement",
         "sentence": "GMV {t0}。", "number_tokens": [
             {"token_id": "t0", "fact_id": "m.gmv", "expected_metric_key": "gmv",
              "direction": "down"}],
         "entity_refs": [], "confidence": "强", "causal_link": None}
    c.update(kw)
    return c


def _bundle(claims, **kw):
    b = {"facts_hash": "h", "headline": "标题。",
         "first_screen": {"spine": [], "panel": [], "actions": []},
         "spine_final": {"backbone": [{"link_id": "L1", "from": "traffic", "to": "gmv",
                                       "anchor_fact_ids": ["m.gmv"], "relation": "accounting_identity"}]},
         "sections": [{"section_id": "core_business", "title": "大盘", "claims": claims,
                       "table_ref": None, "chart_ref": None, "spine_callbacks": ["L1"]}],
         "cannot_say": []}
    b.update(kw)
    return b


def test_clean_bundle_passes():
    r = run_gate(_bundle([_claim()]), _facts())
    assert r.status == "PASS"
    assert r.hard_failures == []


def test_missing_fact_hard_fails():
    r = run_gate(_bundle([_claim(number_tokens=[
        {"token_id": "t0", "fact_id": "m.ghost", "expected_metric_key": "gmv",
         "direction": "down"}])]), _facts())
    assert r.status == "FAIL"
    assert any(f["code"] == "MISSING_FACT" for f in r.hard_failures)


def test_nonexistent_slice_hard_fails():
    facts = _facts()
    facts["facts"]["退款原因"] = {"rendered": "¥1", "metric_key": "reason", "direction": None,
                                  "pool_id": None, "entity_type": None, "evidence_strength": "weak",
                                  "descriptive_reliability": "low", "assumption": None}
    r = run_gate(_bundle([_claim(number_tokens=[
        {"token_id": "t0", "fact_id": "退款原因", "expected_metric_key": "reason",
         "direction": None}])]), facts)
    assert any(f["code"] == "NONEXISTENT_SLICE" for f in r.hard_failures)


def test_metric_misbind_hard_fails():
    r = run_gate(_bundle([_claim(number_tokens=[
        {"token_id": "t0", "fact_id": "m.gmv", "expected_metric_key": "aov",
         "direction": "down"}])]), _facts())
    assert any(f["code"] == "METRIC_MISBIND" for f in r.hard_failures)


def test_direction_conflict_hard_fails():
    r = run_gate(_bundle([_claim(number_tokens=[
        {"token_id": "t0", "fact_id": "m.gmv", "expected_metric_key": "gmv",
         "direction": "up"}])]), _facts())
    assert any(f["code"] == "DIRECTION_CONFLICT" for f in r.hard_failures)


def test_invented_entity_hard_fails():
    r = run_gate(_bundle([_claim(entity_refs=["不存在的系列"])]), _facts())
    assert any(f["code"] == "INVENTED_ENTITY" for f in r.hard_failures)


def test_magnitude_unbound_bare_digit_hard_fails():
    r = run_gate(_bundle([_claim(sentence="GMV 是 208364 元。", number_tokens=[])]), _facts())
    assert any(f["code"] == "MAGNITUDE_UNBOUND" for f in r.hard_failures)


def test_magnitude_unbound_token_mismatch_hard_fails():
    r = run_gate(_bundle([_claim(sentence="GMV {t0} 与 {t9}。")]), _facts())
    assert any(f["code"] == "MAGNITUDE_UNBOUND" for f in r.hard_failures)


def test_quantified_attribution_on_absent_link_hard_fails():
    c = _claim(claim_kind="mechanism", confidence="弱",
               causal_link={"from_entity_type": "note", "to_entity_type": "order",
                            "quantified": True})
    r = run_gate(_bundle([c]), _facts())
    assert any(f["code"] == "QUANTIFIED_ATTRIBUTION" for f in r.hard_failures)


def test_directional_mechanism_on_absent_link_passes():
    c = _claim(claim_kind="mechanism", confidence="弱", entity_refs=["兴安岭之夜"],
               causal_link={"from_entity_type": "note", "to_entity_type": "order",
                            "quantified": False})
    r = run_gate(_bundle([c]), _facts())
    assert not any(f["code"] == "QUANTIFIED_ATTRIBUTION" for f in r.hard_failures)


def test_summed_pools_hard_fails():
    c = _claim(sentence="可回收合计 {t0}+{t1}。", number_tokens=[
        {"token_id": "t0", "fact_id": "pool.pre", "expected_metric_key": "preship",
         "direction": None},
        {"token_id": "t1", "fact_id": "pool.post", "expected_metric_key": "postship",
         "direction": None}])
    r = run_gate(_bundle([c]), _facts())
    assert any(f["code"] == "SUMMED_POOLS" for f in r.hard_failures)


def test_dangling_callback_hard_fails():
    r = run_gate(_bundle([_claim()], sections=[{
        "section_id": "core_business", "title": "大盘", "claims": [_claim()],
        "table_ref": None, "chart_ref": None, "spine_callbacks": ["L_ghost"]}]), _facts())
    assert any(f["code"] == "DANGLING_CALLBACK" for f in r.hard_failures)


def test_mechanism_confidence_capped_to_weak():
    c = _claim(claim_kind="mechanism", confidence="强", entity_refs=["鱼盘"],
               number_tokens=[{"token_id": "t0", "fact_id": "sku.hot",
                               "expected_metric_key": "sku_gmv", "direction": "up"}],
               sentence="兴安岭之夜大概率带动鱼盘 {t0}。",
               causal_link={"from_entity_type": "note", "to_entity_type": "sku",
                            "quantified": False})
    r = run_gate(_bundle([c]), _facts())
    assert r.status == "PASS"
    capped = r.bundle["sections"][0]["claims"][0]
    assert capped["confidence"] == "弱"
    assert any(w["code"] == "CONFIDENCE_CAPPED" for w in r.warnings)


def test_measurement_confidence_capped_by_weak_anchor():
    c = _claim(confidence="强", number_tokens=[{"token_id": "t0", "fact_id": "sku.hot",
                                               "expected_metric_key": "sku_gmv", "direction": "up"}],
               sentence="某测量 {t0}。")
    r = run_gate(_bundle([c]), _facts())
    # sku.hot: evidence weak, descriptive medium -> allowed 中; stated 强 -> capped to 中
    assert r.bundle["sections"][0]["claims"][0]["confidence"] == "中"


def test_untagged_mechanism_warns():
    c = _claim(claim_kind="mechanism", confidence="", entity_refs=["鱼盘"],
               causal_link={"from_entity_type": "note", "to_entity_type": "sku",
                            "quantified": False})
    r = run_gate(_bundle([c]), _facts())
    assert any(w["code"] == "UNTAGGED_MECHANISM" for w in r.warnings)


def test_missed_mechanism_warns_when_entity_fact_unclaimed():
    # sku.hot has entity_type='sku' but no mechanism claim references it
    r = run_gate(_bundle([_claim()]), _facts())
    assert any(w["code"] == "MISSED_MECHANISM" for w in r.warnings)


def test_unlabeled_sizing_warns():
    c = _claim(claim_kind="sizing", confidence="中",
               number_tokens=[{"token_id": "t0", "fact_id": "pool.post",
                               "expected_metric_key": "postship", "direction": None}],
               sentence="发货后池约 {t0}。")  # pool.post has no assumption label
    r = run_gate(_bundle([c]), _facts())
    assert any(w["code"] == "UNLABELED_SIZING" for w in r.warnings)


def test_missing_spine_callback_warns():
    r = run_gate(_bundle([_claim()], sections=[{
        "section_id": "core_business", "title": "大盘", "claims": [_claim()],
        "table_ref": None, "chart_ref": None, "spine_callbacks": []}]), _facts())
    assert any(w["code"] == "MISSING_SPINE_CALLBACK" for w in r.warnings)


def test_redundant_headline_warns():
    c = _claim(sentence="GMV {t0}。")
    r = run_gate(_bundle([c], headline="GMV {t0}。"), _facts())
    assert any(w["code"] == "REDUNDANT_HEADLINE" for w in r.warnings)


def test_input_bundle_not_mutated():
    b = _bundle([_claim(claim_kind="mechanism", confidence="强", entity_refs=["鱼盘"],
                        causal_link={"from_entity_type": "note", "to_entity_type": "sku",
                                     "quantified": False})])
    snapshot = copy.deepcopy(b)
    run_gate(b, _facts())
    assert b == snapshot  # capping returns a new bundle; input untouched
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reporting_factcheck_gate.py -v`
Expected: FAIL with `ModuleNotFoundError: ...factcheck_gate`.

- [ ] **Step 3: Write minimal implementation**

```python
# xhs_ceramics_analytics/reporting/factcheck_gate.py
"""Structural fact-check gate — the truth owner (pure Python, never an agent).

The writer's sentences carry only opaque ``{tN}`` tokens; every magnitude is a
declared ``number_token`` pointing at a ``fact_id``. This gate validates that
structure against the FactBook and registries, so a fabricated number-string is
unrepresentable. HARD failures block render (编造数字/发明实体/引用不存在切片/
异口径池相加/带数字的既成归因/悬空回指). WARN codes fight timidity and label gaps
but never block a bold, tagged conclusion. Confidence is capped deterministically
(mechanism → 弱; else ≤ the strongest anchor) — the honesty mechanism that replaces
the nondeterministic "spine skeptic" agent. Immutable: capping returns a NEW bundle.
"""
import copy
import json
import re
from dataclasses import dataclass, field

_TOKEN_RE = re.compile(r"\{t\d+\}")
_DIGIT_RE = re.compile(r"\d")
_TAG_RANK = {"弱": 1, "中": 2, "强": 3}
_RANK_TAG = {1: "弱", 2: "中", 3: "强"}


@dataclass(frozen=True)
class GateReport:
    status: str
    hard_failures: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    capped_claims: list[dict] = field(default_factory=list)
    bundle: dict = field(default_factory=dict)


def _fail(code: str, claim_id: str | None, detail: str) -> dict:
    return {"code": code, "claim_id": claim_id, "detail": detail}


def _iter_claims(bundle: dict):
    """Yield every claim in the bundle (sections + first_screen), with its claim_id."""
    for section in bundle.get("sections") or []:
        for claim in section.get("claims") or []:
            yield claim
    fs = bundle.get("first_screen") or {}
    for key in ("spine", "panel"):
        for claim in fs.get(key) or []:
            if isinstance(claim, dict) and "sentence" in claim:
                yield claim


def _allowed_tag(claim: dict, facts: dict) -> str:
    """Strongest tag the claim's anchors support (mirrors trust_routing.confidence_tag)."""
    if claim.get("claim_kind") == "mechanism":
        return "弱"
    best = 1
    for tok in claim.get("number_tokens") or []:
        fact = facts.get(tok.get("fact_id")) or {}
        es = fact.get("evidence_strength")
        dr = fact.get("descriptive_reliability")
        if es == "strong" or dr == "high":
            rank = 3
        elif dr == "medium":
            rank = 2
        else:
            rank = 1
        best = max(best, rank)
    return _RANK_TAG[best]


def _check_tokens(claim: dict, facts: dict, absent: set, hard: list) -> None:
    cid = claim.get("claim_id")
    sentence = str(claim.get("sentence") or "")
    tokens = claim.get("number_tokens") or []
    # MAGNITUDE_UNBOUND — declared tokens must match {tN} in the sentence exactly,
    # and no bare digit may survive token removal (writer never emits a number).
    in_sentence = set(_TOKEN_RE.findall(sentence))
    declared = {"{" + str(t.get("token_id")) + "}" for t in tokens}
    if in_sentence != declared:
        hard.append(_fail("MAGNITUDE_UNBOUND", cid,
                          f"token mismatch: sentence {sorted(in_sentence)} vs declared "
                          f"{sorted(declared)}"))
    if _DIGIT_RE.search(_TOKEN_RE.sub("", sentence)):
        hard.append(_fail("MAGNITUDE_UNBOUND", cid, "bare digit outside a {tN} token"))
    for tok in tokens:
        fid = tok.get("fact_id")
        if fid in absent:
            hard.append(_fail("NONEXISTENT_SLICE", cid, f"cites absent slice/link: {fid}"))
            continue
        fact = facts.get(fid)
        if fact is None:
            hard.append(_fail("MISSING_FACT", cid, f"no such fact_id: {fid}"))
            continue
        if tok.get("expected_metric_key") not in (None, fact.get("metric_key")):
            hard.append(_fail("METRIC_MISBIND", cid,
                              f"{fid}: expected metric {tok.get('expected_metric_key')} "
                              f"!= fact {fact.get('metric_key')}"))
        td, fd = tok.get("direction"), fact.get("direction")
        if td is not None and fd is not None and td != fd:
            hard.append(_fail("DIRECTION_CONFLICT", cid, f"{fid}: token {td} != fact {fd}"))


def _check_pools(claim: dict, facts: dict, hard: list) -> None:
    pools = set()
    for tok in claim.get("number_tokens") or []:
        pid = (facts.get(tok.get("fact_id")) or {}).get("pool_id")
        if pid:
            pools.add(pid)
    if len(pools) >= 2:
        hard.append(_fail("SUMMED_POOLS", claim.get("claim_id"),
                          f"claim mixes incompatible pools {sorted(pools)} (use 不可加台账)"))


def _check_causal(claim: dict, absent_links: set, hard: list) -> None:
    link = claim.get("causal_link")
    if not link:
        return
    key = f"{link.get('from_entity_type')}->{link.get('to_entity_type')}"
    if link.get("quantified") and key in absent_links:
        hard.append(_fail("QUANTIFIED_ATTRIBUTION", claim.get("claim_id"),
                          f"quantified attribution on absent link {key}"))


def run_gate(bundle: dict, facts_json: dict) -> GateReport:
    """Validate + confidence-cap a narrative_bundle. Returns a new (capped) bundle."""
    bundle = copy.deepcopy(bundle)  # never mutate the caller's bundle
    facts = facts_json.get("facts") or {}
    registry = set(facts_json.get("entity_registry") or [])
    absent = set(facts_json.get("absent_link_registry") or [])
    absent_links = {a for a in absent if "->" in a}

    hard: list[dict] = []
    warnings: list[dict] = []
    capped: list[dict] = []

    backbone_ids = {b.get("link_id") for b in (bundle.get("spine_final") or {}).get("backbone") or []}
    entity_facts = {fid for fid, f in facts.items() if f.get("entity_type")}
    claimed_facts: set[str] = set()
    mechanism_facts: set[str] = set()

    for claim in _iter_claims(bundle):
        cid = claim.get("claim_id")
        _check_tokens(claim, facts, absent, hard)
        _check_pools(claim, facts, hard)
        _check_causal(claim, absent_links, hard)
        for ent in claim.get("entity_refs") or []:
            if ent not in registry:
                hard.append(_fail("INVENTED_ENTITY", cid, f"entity not in registry: {ent}"))
        for tok in claim.get("number_tokens") or []:
            claimed_facts.add(tok.get("fact_id"))
            if claim.get("claim_kind") == "mechanism":
                mechanism_facts.add(tok.get("fact_id"))
        # WARN: mechanism without a tag
        if claim.get("claim_kind") == "mechanism" and claim.get("confidence") not in _TAG_RANK:
            warnings.append(_fail("UNTAGGED_MECHANISM", cid, "mechanism claim missing 强/中/弱 tag"))
        # WARN: sizing without a caliber/assumption label on any anchor
        if claim.get("claim_kind") == "sizing":
            labelled = any((facts.get(t.get("fact_id")) or {}).get("assumption")
                           for t in claim.get("number_tokens") or [])
            if not labelled:
                warnings.append(_fail("UNLABELED_SIZING", cid, "sizing claim lacks caliber label"))
        # Confidence cap (deterministic; mechanism -> 弱, else <= strongest anchor)
        allowed = _allowed_tag(claim, facts)
        stated = claim.get("confidence")
        if stated in _TAG_RANK and _TAG_RANK[stated] > _TAG_RANK[allowed]:
            claim["confidence"] = allowed
            capped.append({"claim_id": cid, "from": stated, "to": allowed})
            warnings.append(_fail("CONFIDENCE_CAPPED", cid, f"{stated} -> {allowed}"))

    # Cross-section: dangling callbacks + missing callbacks
    for section in bundle.get("sections") or []:
        callbacks = section.get("spine_callbacks") or []
        if not callbacks:
            warnings.append(_fail("MISSING_SPINE_CALLBACK", section.get("section_id"),
                                  "section connects to no spine link"))
        for link_id in callbacks:
            if link_id not in backbone_ids:
                hard.append(_fail("DANGLING_CALLBACK", section.get("section_id"),
                                  f"callback to unknown spine link {link_id}"))

    # WARN: mechanism fact available but never claimed as mechanism
    for fid in sorted(entity_facts - mechanism_facts):
        warnings.append(_fail("MISSED_MECHANISM", None,
                              f"entity fact {fid} has no mechanism claim"))

    # WARN: headline duplicates a section claim verbatim
    headline = str(bundle.get("headline") or "").strip()
    if headline:
        for claim in _iter_claims(bundle):
            if str(claim.get("sentence") or "").strip() == headline:
                warnings.append(_fail("REDUNDANT_HEADLINE", claim.get("claim_id"),
                                      "headline duplicates a section claim"))
                break

    status = "FAIL" if hard else "PASS"
    return GateReport(status=status, hard_failures=hard, warnings=warnings,
                      capped_claims=capped, bundle=bundle)


def gate_report_to_json(report: GateReport) -> str:
    payload = {
        "status": report.status,
        "hard_failures": report.hard_failures,
        "warnings": report.warnings,
        "capped_claims": report.capped_claims,
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_reporting_factcheck_gate.py -v`
Expected: PASS (all ~20 tests).

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/reporting/factcheck_gate.py tests/test_reporting_factcheck_gate.py
git commit -m "feat(reporting): structural fact-check gate + deterministic confidence cap"
```

---

### Task 3: Frozen-narrative override + version keys (`frozen_narrative.py`)

**Files:**
- Create: `xhs_ceramics_analytics/reporting/frozen_narrative.py`
- Test: `tests/test_reporting_frozen_narrative.py`

**Interfaces:**
- Consumes: nothing at import beyond stdlib + `inspect` on reporting modules.
- Produces:
  - `narrative_schema_version() -> str` — 16-hex hash of the gate+render+first_screen source (Plan 3
    extends this to include prompt/schema assets; changing the hashed inputs moves the version).
  - `renderer_version() -> str` — 16-hex hash of the chart/html/markdown/money source.
  - `write_frozen(path, facts_hash: str, bundle: dict) -> None` — write
    `{schema_version, facts_hash, renderer_version, narrative_bundle}` (deterministic JSON).
  - `load_frozen(path) -> dict | None` — absent → None; malformed / missing keys → `ValueError`
    (mirrors `importing/overrides.py`).
  - `is_cache_hit(frozen: dict | None, facts_hash: str) -> bool` — True iff all three keys match the
    current versions and the given `facts_hash`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reporting_frozen_narrative.py
import pytest

from xhs_ceramics_analytics.reporting import frozen_narrative as fn


def test_versions_are_stable_16hex():
    assert fn.narrative_schema_version() == fn.narrative_schema_version()
    assert fn.renderer_version() == fn.renderer_version()
    assert len(fn.narrative_schema_version()) == 16
    assert len(fn.renderer_version()) == 16


def test_write_then_load_roundtrips(tmp_path):
    path = tmp_path / "frozen_narrative.json"
    bundle = {"facts_hash": "abc", "sections": []}
    fn.write_frozen(path, "abc", bundle)
    loaded = fn.load_frozen(path)
    assert loaded["facts_hash"] == "abc"
    assert loaded["narrative_bundle"] == bundle
    assert loaded["schema_version"] == fn.narrative_schema_version()
    assert loaded["renderer_version"] == fn.renderer_version()


def test_load_absent_returns_none(tmp_path):
    assert fn.load_frozen(tmp_path / "nope.json") is None


def test_load_malformed_raises(tmp_path):
    path = tmp_path / "frozen_narrative.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        fn.load_frozen(path)


def test_load_missing_keys_raises(tmp_path):
    path = tmp_path / "frozen_narrative.json"
    path.write_text('{"facts_hash": "x"}', encoding="utf-8")
    with pytest.raises(ValueError):
        fn.load_frozen(path)


def test_cache_hit_requires_all_three_keys(tmp_path):
    path = tmp_path / "frozen_narrative.json"
    fn.write_frozen(path, "abc", {"sections": []})
    frozen = fn.load_frozen(path)
    assert fn.is_cache_hit(frozen, "abc") is True
    assert fn.is_cache_hit(frozen, "different") is False
    frozen["schema_version"] = "stale"
    assert fn.is_cache_hit(frozen, "abc") is False
    assert fn.is_cache_hit(None, "abc") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reporting_frozen_narrative.py -v`
Expected: FAIL with `ModuleNotFoundError` / `AttributeError`.

- [ ] **Step 3: Write minimal implementation**

```python
# xhs_ceramics_analytics/reporting/frozen_narrative.py
"""Frozen-narrative override — the cache checkpoint beside mapping_overrides.yaml.

A narrative_bundle that passed the gate is persisted under the triple key
``(facts_hash, narrative_schema_version, renderer_version)``. A cache hit means the
whole agent layer is skipped and Python re-renders the frozen narrative at 0 LLM
calls. ``narrative_schema_version`` hashes the gate/render contract (prompts+schemas
fold in via Plan 3); ``renderer_version`` hashes the chart/html/markdown/money source.
Either bump silently invalidates a stale narrative — we never ship old bytes under a
changed contract. Mirrors ``importing/overrides.py``: absent → None, malformed → ValueError.
"""
import hashlib
import inspect
import json
from pathlib import Path

from xhs_ceramics_analytics.reporting import (
    charts,
    factcheck_gate,
    first_screen,
    markdown,
    money,
    narrative_render,
)
from xhs_ceramics_analytics.reporting import html as html_mod

_REQUIRED_KEYS = ("schema_version", "facts_hash", "renderer_version", "narrative_bundle")


def _hash_sources(modules) -> str:
    h = hashlib.sha256()
    for module in modules:
        h.update(inspect.getsource(module).encode("utf-8"))
    return h.hexdigest()[:16]


def narrative_schema_version() -> str:
    """Hash of the deterministic narrative contract (gate + render + first_screen)."""
    return _hash_sources((factcheck_gate, narrative_render, first_screen))


def renderer_version() -> str:
    """Hash of the rendering surface (charts / html / markdown / money)."""
    return _hash_sources((charts, html_mod, markdown, money))


def write_frozen(path, facts_hash: str, bundle: dict) -> None:
    payload = {
        "schema_version": narrative_schema_version(),
        "facts_hash": facts_hash,
        "renderer_version": renderer_version(),
        "narrative_bundle": bundle,
    }
    Path(path).write_text(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_frozen(path) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"frozen_narrative is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or any(k not in data for k in _REQUIRED_KEYS):
        raise ValueError(f"frozen_narrative missing required keys {_REQUIRED_KEYS}")
    return data


def is_cache_hit(frozen: dict | None, facts_hash: str) -> bool:
    if not frozen:
        return False
    return (
        frozen.get("facts_hash") == facts_hash
        and frozen.get("schema_version") == narrative_schema_version()
        and frozen.get("renderer_version") == renderer_version()
    )
```

> **Note for the implementer:** `frozen_narrative` imports `narrative_render` (T4). Because they are
> different modules the import is fine at runtime; just ensure T4 is present before running T3's tests
> in a parallel workflow (T3 depends on T4). If you implement T3 before T4, temporarily stub the import
> — but the recommended order is T1/T2 → T4 → T3 → T5.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_reporting_frozen_narrative.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/reporting/frozen_narrative.py tests/test_reporting_frozen_narrative.py
git commit -m "feat(reporting): frozen-narrative override + triple-key cache versions"
```

---

### Task 4: Narrative renderer (`narrative_render.py`)

**Files:**
- Create: `xhs_ceramics_analytics/reporting/narrative_render.py`
- Test: `tests/test_reporting_narrative_render.py`

**Interfaces:**
- Consumes: `factcheck_gate.run_gate`/`GateReport` (T2), `first_screen.first_screen_markdown` (T1),
  `reporting.html.render_markdown_document_html`, `reporting.markdown.render_markdown` (skeleton).
- Produces:
  - `fill_sentence(sentence: str, number_tokens: list[dict], facts: dict) -> str` — replace each
    `{token_id}` with `facts[fact_id]["rendered"]`; zero numeric derivation.
  - `render_draft(bundle: dict, facts_json: dict) -> dict` — returns a new bundle where every claim
    gains `rendered_sentence`.
  - `apply_continuity_edits(bundle: dict, edits: list[dict]) -> dict` — each edit `{claim_id, old,
    new}` must locate `old` exactly once in that claim's `rendered_sentence`; the digit multiset and
    `{tN}` multiset of `old` and `new` must match (continuity touches prose, never numbers). Raises
    `ValueError` on any violation.
  - `bundle_to_markdown(bundle: dict, facts_json: dict, *, title: str | None = None) -> str` — full
    report markdown from a drafted bundle (first-screen + sections + 暂时答不了的问题).
  - `render_frozen(frozen: dict, facts_json: dict) -> tuple[str, str]` — verify
    `frozen["facts_hash"] == facts_json["facts_hash"]`, re-gate the frozen bundle (must PASS), then
    return `(markdown, html)`. Raises `ValueError` on hash mismatch or gate FAIL (render-time tamper
    evidence).
  - `skeleton_markdown(results, *, title: str | None = None) -> str` — deterministic 0-agent floor:
    the banner + existing `render_markdown(results)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reporting_narrative_render.py
import pytest

from xhs_ceramics_analytics.reporting import narrative_render as nr


def _facts():
    return {
        "facts_hash": "h",
        "facts": {
            "m.may": {"rendered": "¥10.0", "metric_key": "pvg_may", "direction": None,
                      "pool_id": None, "entity_type": None, "evidence_strength": "strong",
                      "descriptive_reliability": "high", "assumption": None},
            "m.jun": {"rendered": "¥8.7", "metric_key": "pvg_jun", "direction": "down",
                      "pool_id": None, "entity_type": None, "evidence_strength": "strong",
                      "descriptive_reliability": "high", "assumption": None},
        },
        "entity_registry": [], "absent_link_registry": [], "non_additive_ledger": {},
    }


def _claim():
    return {"claim_id": "c0", "section_id": "core_business", "claim_kind": "measurement",
            "sentence": "人均产出从 {t0} 回落到 {t1}。", "number_tokens": [
                {"token_id": "t0", "fact_id": "m.may", "expected_metric_key": "pvg_may",
                 "direction": None},
                {"token_id": "t1", "fact_id": "m.jun", "expected_metric_key": "pvg_jun",
                 "direction": "down"}],
            "entity_refs": [], "confidence": "强", "causal_link": None}


def _bundle():
    return {"facts_hash": "h", "headline": "人均产出走低。",
            "first_screen": {"spine": [], "panel": [], "actions": ["核对千帆能力。"]},
            "spine_final": {"backbone": [{"link_id": "L1", "from": "t", "to": "g",
                                          "anchor_fact_ids": ["m.jun"],
                                          "relation": "accounting_identity"}]},
            "sections": [{"section_id": "core_business", "title": "生意大盘·月对月",
                          "claims": [_claim()], "table_ref": None, "chart_ref": None,
                          "spine_callbacks": ["L1"]}],
            "cannot_say": ["笔记→订单归因：平台无链路。"]}


def test_fill_sentence_uses_only_rendered_strings():
    filled = nr.fill_sentence(_claim()["sentence"], _claim()["number_tokens"], _facts()["facts"])
    assert filled == "人均产出从 ¥10.0 回落到 ¥8.7。"


def test_render_draft_adds_rendered_sentence():
    drafted = nr.render_draft(_bundle(), _facts())
    claim = drafted["sections"][0]["claims"][0]
    assert claim["rendered_sentence"] == "人均产出从 ¥10.0 回落到 ¥8.7。"


def test_bundle_to_markdown_includes_all_sections():
    md = nr.bundle_to_markdown(nr.render_draft(_bundle(), _facts()), _facts(), title="测试报告")
    assert "人均产出从 ¥10.0 回落到 ¥8.7。" in md
    assert "生意大盘·月对月" in md
    assert "暂时答不了的问题" in md
    assert "笔记→订单归因：平台无链路。" in md


def test_apply_continuity_edit_prose_only():
    drafted = nr.render_draft(_bundle(), _facts())
    edits = [{"claim_id": "c0", "old": "人均产出从 ¥10.0 回落到 ¥8.7。",
              "new": "人均产出由 ¥10.0 滑到 ¥8.7。"}]
    out = nr.apply_continuity_edits(drafted, edits)
    assert out["sections"][0]["claims"][0]["rendered_sentence"] == "人均产出由 ¥10.0 滑到 ¥8.7。"


def test_apply_continuity_edit_rejects_new_digit():
    drafted = nr.render_draft(_bundle(), _facts())
    edits = [{"claim_id": "c0", "old": "人均产出从 ¥10.0 回落到 ¥8.7。",
              "new": "人均产出从 ¥10.0 回落到 ¥8.7，跌了 15%。"}]
    with pytest.raises(ValueError):
        nr.apply_continuity_edits(drafted, edits)


def test_apply_continuity_edit_rejects_absent_old():
    drafted = nr.render_draft(_bundle(), _facts())
    with pytest.raises(ValueError):
        nr.apply_continuity_edits(drafted, [{"claim_id": "c0", "old": "不存在的句子", "new": "x"}])


def test_render_frozen_roundtrip():
    drafted = nr.render_draft(_bundle(), _facts())
    frozen = {"schema_version": "v", "facts_hash": "h", "renderer_version": "r",
              "narrative_bundle": drafted}
    md, html = nr.render_frozen(frozen, _facts())
    assert "人均产出从 ¥10.0 回落到 ¥8.7。" in md
    assert "<html" in html.lower()


def test_render_frozen_rejects_hash_mismatch():
    drafted = nr.render_draft(_bundle(), _facts())
    frozen = {"schema_version": "v", "facts_hash": "STALE", "renderer_version": "r",
              "narrative_bundle": drafted}
    with pytest.raises(ValueError):
        nr.render_frozen(frozen, _facts())


def test_skeleton_markdown_has_banner():
    from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
    from xhs_ceramics_analytics.evidence import EvidenceStrength
    result = AnalysisResult(task_id="core_business_diagnosis", title="大盘",
                            findings=[Finding(title="结论", conclusion="人均产出走低。",
                                              evidence_strength=EvidenceStrength.STRONG)])
    md = nr.skeleton_markdown([result], title="骨架报告")
    assert "确定性骨架版" in md
    assert "人均产出走低。" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reporting_narrative_render.py -v`
Expected: FAIL with `ModuleNotFoundError: ...narrative_render`.

- [ ] **Step 3: Write minimal implementation**

```python
# xhs_ceramics_analytics/reporting/narrative_render.py
"""Deterministic narrative renderer — fills {tN}, applies continuity edits, freezes, skeletons.

Python owns rounding: ``fill_sentence`` copies ``fact.rendered`` verbatim into each
``{tN}`` slot with zero numeric derivation, so a fabricated number is unrepresentable.
``apply_continuity_edits`` lets the Continuity pass rewrite prose only — the digit and
``{tN}`` multisets of every edit are invariant (the shipped merchant_voice ``{…}``
contract, generalized). ``render_frozen`` re-gates at render time (tamper evidence).
``skeleton_markdown`` is the 0-agent floor reusing the existing compositor. Pure; the
edit/hash guards raise ValueError by design (callers treat them as gate failures).
"""
import copy
import re

from xhs_ceramics_analytics.reporting.factcheck_gate import run_gate
from xhs_ceramics_analytics.reporting.first_screen import first_screen_markdown
from xhs_ceramics_analytics.reporting.html import render_markdown_document_html
from xhs_ceramics_analytics.reporting.markdown import render_markdown

_TOKEN_RE = re.compile(r"\{t\d+\}")
_DIGIT_RE = re.compile(r"\d")
_SKELETON_BANNER = (
    "> **本报告为确定性骨架版：叙事层未通过事实校验，数字与表格仍完整可核。**"
)


def fill_sentence(sentence: str, number_tokens: list[dict], facts: dict) -> str:
    """Replace each {token_id} with facts[fact_id]['rendered']. No numeric derivation."""
    out = sentence
    for tok in number_tokens or []:
        fid = tok.get("fact_id")
        rendered = str((facts.get(fid) or {}).get("rendered", "—"))
        out = out.replace("{" + str(tok.get("token_id")) + "}", rendered)
    return out


def _all_claim_lists(bundle: dict):
    for section in bundle.get("sections") or []:
        yield section.get("claims") or []
    fs = bundle.get("first_screen") or {}
    for key in ("spine", "panel"):
        yield [c for c in (fs.get(key) or []) if isinstance(c, dict) and "sentence" in c]


def render_draft(bundle: dict, facts_json: dict) -> dict:
    """Return a new bundle where every claim carries a filled ``rendered_sentence``."""
    bundle = copy.deepcopy(bundle)
    facts = facts_json.get("facts") or {}
    for claims in _all_claim_lists(bundle):
        for claim in claims:
            claim["rendered_sentence"] = fill_sentence(
                str(claim.get("sentence") or ""), claim.get("number_tokens"), facts
            )
    return bundle


def _digit_multiset(text: str) -> list[str]:
    return sorted(_DIGIT_RE.findall(text))


def _token_multiset(text: str) -> list[str]:
    return sorted(_TOKEN_RE.findall(text))


def apply_continuity_edits(bundle: dict, edits: list[dict]) -> dict:
    """Apply prose-only edits. old must occur once; digits/{tN} invariant. Raises on violation."""
    bundle = copy.deepcopy(bundle)
    index: dict[str, dict] = {}
    for claims in _all_claim_lists(bundle):
        for claim in claims:
            index[claim.get("claim_id")] = claim
    for edit in edits or []:
        cid = edit.get("claim_id")
        claim = index.get(cid)
        if claim is None:
            raise ValueError(f"continuity edit for unknown claim_id {cid}")
        old, new = str(edit.get("old")), str(edit.get("new"))
        text = str(claim.get("rendered_sentence") or "")
        if text.count(old) != 1:
            raise ValueError(f"continuity 'old' must occur exactly once in claim {cid}")
        if _digit_multiset(old) != _digit_multiset(new):
            raise ValueError(f"continuity edit changes the digit multiset in claim {cid}")
        if _token_multiset(old) != _token_multiset(new):
            raise ValueError(f"continuity edit changes the {{tN}} multiset in claim {cid}")
        claim["rendered_sentence"] = text.replace(old, new)
    return bundle


def _rendered(claim: dict) -> str:
    return str(claim.get("rendered_sentence") or claim.get("sentence") or "").strip()


def bundle_to_markdown(bundle: dict, facts_json: dict, *, title: str | None = None) -> str:
    parts: list[str] = []
    if title:
        parts.append(f"# {title}")
    parts.append(first_screen_markdown(bundle).rstrip())
    for section in bundle.get("sections") or []:
        heading = str(section.get("title") or section.get("section_id") or "").strip()
        parts.append(f"## {heading}")
        for claim in section.get("claims") or []:
            sentence = _rendered(claim)
            if not sentence:
                continue
            conf = claim.get("confidence")
            parts.append(f"{sentence}（{conf}）" if conf else sentence)
    cannot = [str(c).strip() for c in (bundle.get("cannot_say") or []) if str(c).strip()]
    if cannot:
        parts.append("## 暂时答不了的问题")
        parts.extend(f"- {c}" for c in cannot)
    return "\n\n".join(parts) + "\n"


def render_frozen(frozen: dict, facts_json: dict) -> tuple[str, str]:
    """Render (md, html) from a frozen narrative. Re-gates + checks facts_hash (tamper evidence)."""
    if frozen.get("facts_hash") != facts_json.get("facts_hash"):
        raise ValueError("frozen facts_hash does not match the supplied facts.json")
    bundle = frozen.get("narrative_bundle") or {}
    report = run_gate(bundle, facts_json)
    if report.status != "PASS":
        raise ValueError(f"frozen narrative fails the render-time gate: {report.hard_failures}")
    drafted = render_draft(report.bundle, facts_json)
    md = bundle_to_markdown(drafted, facts_json)
    html = render_markdown_document_html(md)
    return md, html


def skeleton_markdown(results, *, title: str | None = None) -> str:
    """Deterministic 0-agent floor: banner + the existing compositor's markdown."""
    body = render_markdown(results, title=title)
    return f"{_SKELETON_BANNER}\n\n{body}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_reporting_narrative_render.py -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/reporting/narrative_render.py tests/test_reporting_narrative_render.py
git commit -m "feat(reporting): narrative renderer ({tN} fill, continuity edits, frozen, skeleton)"
```

---

### Task 5: CLI subcommands (`gate` / `render-draft` / `finalize` / `render-frozen` / `skeleton`)

**Files:**
- Modify: `xhs_ceramics_analytics/cli.py` (add 5 `@app.command()` functions after `facts`)
- Test: `tests/test_cli_narrative.py`

**Interfaces:**
- Consumes: `factcheck_gate.run_gate`/`gate_report_to_json` (T2), `frozen_narrative.write_frozen`
  (T3), `narrative_render.render_draft`/`apply_continuity_edits`/`bundle_to_markdown`/`render_frozen`/
  `skeleton_markdown` (T4), existing `registry`/`coverage`/`facts_export` (Plan 1), `paths`.
- Produces (Typer subcommands, all lazy-import their deps inside the function body, matching the file
  convention):
  - `gate BUNDLE FACTS [--out]` → writes gate_report.json; exits 1 on FAIL.
  - `render-draft BUNDLE FACTS [--out]` → writes a drafted markdown.
  - `finalize BUNDLE FACTS [--edits] [--out]` → draft → apply edits → re-gate (must PASS) → write
    frozen_narrative.json.
  - `render-frozen FROZEN FACTS [--name]` → writes `<name>.md` + `<name>.html`.
  - `skeleton [tasks...] [--name]` → runs tasks → writes skeleton `<name>.md` + `<name>.html`.
- Typer maps hyphenated command names from underscore function names (`render_draft` → `render-draft`),
  matching the existing `render-html` command.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_narrative.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli_narrative.py -v`
Expected: FAIL (no `gate`/`render-draft`/`finalize`/`render-frozen` commands).

- [ ] **Step 3: Write minimal implementation**

Add these five commands to `xhs_ceramics_analytics/cli.py` immediately after the `facts` command
(before `coverage`). Keep the lazy-import-inside-function convention.

```python
@app.command()
def gate(
    bundle: Annotated[Path, typer.Argument(help="narrative_bundle.json to validate.")],
    facts: Annotated[Path, typer.Argument(help="facts.json from `xhs-ca facts`.")],
    out: Annotated[Path | None, typer.Option("--out", help="Where to write gate_report.json.")]
    = None,
) -> None:
    """Validate a narrative_bundle against the FactBook. Exits 1 on any HARD failure."""
    import json as _json

    from xhs_ceramics_analytics.reporting.factcheck_gate import gate_report_to_json, run_gate

    bundle_data = _json.loads(Path(bundle).read_text(encoding="utf-8"))
    facts_data = _json.loads(Path(facts).read_text(encoding="utf-8"))
    report = run_gate(bundle_data, facts_data)
    report_json = gate_report_to_json(report)
    if out is not None:
        Path(out).write_text(report_json, encoding="utf-8")
        typer.echo(f"Wrote gate report: {out}")
    typer.echo(f"gate: {report.status} "
               f"({len(report.hard_failures)} hard, {len(report.warnings)} warn)")
    if report.status != "PASS":
        for failure in report.hard_failures:
            typer.echo(f"  HARD {failure['code']}: {failure['detail']}", err=True)
        raise typer.Exit(code=1)


@app.command(name="render-draft")
def render_draft_command(
    bundle: Annotated[Path, typer.Argument(help="narrative_bundle.json.")],
    facts: Annotated[Path, typer.Argument(help="facts.json.")],
    out: Annotated[Path | None, typer.Option("--out", help="Where to write the draft markdown.")]
    = None,
) -> None:
    """Fill {tN} tokens from fact.rendered and write a draft markdown (no numbers invented)."""
    import json as _json

    from xhs_ceramics_analytics.reporting.narrative_render import (
        bundle_to_markdown,
        render_draft,
    )

    bundle_data = _json.loads(Path(bundle).read_text(encoding="utf-8"))
    facts_data = _json.loads(Path(facts).read_text(encoding="utf-8"))
    drafted = render_draft(bundle_data, facts_data)
    md = bundle_to_markdown(drafted, facts_data)
    target = out or (outputs_dir(None) / "draft.md")
    Path(target).write_text(md, encoding="utf-8")
    typer.echo(f"Wrote draft: {target}")


@app.command()
def finalize(
    bundle: Annotated[Path, typer.Argument(help="narrative_bundle.json.")],
    facts: Annotated[Path, typer.Argument(help="facts.json.")],
    edits: Annotated[Path | None, typer.Option("--edits", help="continuity_edits.json (list).")]
    = None,
    out: Annotated[Path | None, typer.Option("--out", help="Where to write frozen_narrative.json.")]
    = None,
) -> None:
    """Draft → apply continuity edits → re-gate (must PASS) → freeze the narrative override."""
    import json as _json

    from xhs_ceramics_analytics.reporting.factcheck_gate import run_gate
    from xhs_ceramics_analytics.reporting.frozen_narrative import write_frozen
    from xhs_ceramics_analytics.reporting.narrative_render import (
        apply_continuity_edits,
        render_draft,
    )

    bundle_data = _json.loads(Path(bundle).read_text(encoding="utf-8"))
    facts_data = _json.loads(Path(facts).read_text(encoding="utf-8"))
    report = run_gate(bundle_data, facts_data)
    if report.status != "PASS":
        typer.echo(f"gate FAIL — cannot finalize: {report.hard_failures}", err=True)
        raise typer.Exit(code=1)
    drafted = render_draft(report.bundle, facts_data)
    if edits is not None:
        edit_list = _json.loads(Path(edits).read_text(encoding="utf-8"))
        try:
            drafted = apply_continuity_edits(drafted, edit_list)
        except ValueError as exc:
            typer.echo(f"continuity edit rejected: {exc}", err=True)
            raise typer.Exit(code=1) from exc
    target = out or (outputs_dir(None) / "frozen_narrative.json")
    write_frozen(target, facts_data.get("facts_hash", ""), drafted)
    typer.echo(f"Wrote frozen narrative: {target}")


@app.command(name="render-frozen")
def render_frozen_command(
    frozen: Annotated[Path, typer.Argument(help="frozen_narrative.json.")],
    facts: Annotated[Path, typer.Argument(help="facts.json.")],
    name: Annotated[Path | None, typer.Option("--name", "-n", help="Output basename (no suffix).")]
    = None,
) -> None:
    """Render md+html from a frozen narrative; re-gates and checks facts_hash (tamper evidence)."""
    import json as _json

    from xhs_ceramics_analytics.reporting.narrative_render import render_frozen

    frozen_data = _json.loads(Path(frozen).read_text(encoding="utf-8"))
    facts_data = _json.loads(Path(facts).read_text(encoding="utf-8"))
    try:
        md, html = render_frozen(frozen_data, facts_data)
    except ValueError as exc:
        typer.echo(f"render-frozen refused: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    base = name or (outputs_dir(None) / "经营诊断报告")
    Path(f"{base}.md").write_text(md, encoding="utf-8")
    Path(f"{base}.html").write_text(html, encoding="utf-8")
    typer.echo(f"Wrote report: {base}.md")
    typer.echo(f"Wrote report: {base}.html")


@app.command()
def skeleton(
    tasks: Annotated[list[str] | None, typer.Argument(help="Task ids or 'auto'.")] = None,
    db: Annotated[Path | None, typer.Option(help="Override DuckDB file path.")] = None,
    project_root: Annotated[Path | None, typer.Option(help="Override state/output root.")] = None,
    name: Annotated[str | None, typer.Option("--name", "-n", help="Output basename.")] = None,
) -> None:
    """Deterministic 0-agent skeleton report (facts + tables + charts + tags), md+html."""
    from xhs_ceramics_analytics.analysis.coverage import producible_task_ids
    from xhs_ceramics_analytics.analysis.registry import TASKS, run_task
    from xhs_ceramics_analytics.reporting.html import render_markdown_document_html
    from xhs_ceramics_analytics.reporting.narrative_render import skeleton_markdown

    db_path = db or state_dir(project_root) / "analytics.duckdb"
    requested = list(tasks) if tasks else ["auto"]
    if requested == ["auto"]:
        task_ids = list(producible_task_ids(db_path))
    elif requested == ["all"]:
        task_ids = list(TASKS)
    else:
        task_ids = [t for t in requested if t in TASKS]
    results = [run_task(task_id, db_path) for task_id in task_ids]
    basename = name or "经营诊断报告"
    report_title = basename.replace("_", " ").strip()
    md = skeleton_markdown(results, title=report_title)
    output_dir = outputs_dir(project_root)
    (output_dir / f"{basename}.md").write_text(md, encoding="utf-8")
    (output_dir / f"{basename}.html").write_text(
        render_markdown_document_html(md, title=report_title), encoding="utf-8"
    )
    typer.echo(f"Wrote skeleton report: {output_dir / f'{basename}.md'}")
    typer.echo(f"Wrote skeleton report: {output_dir / f'{basename}.html'}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cli_narrative.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full suite + ruff, then commit**

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check xhs_ceramics_analytics/ tests/
git add xhs_ceramics_analytics/cli.py tests/test_cli_narrative.py
git commit -m "feat(cli): gate/render-draft/finalize/render-frozen/skeleton subcommands"
```

---

## Self-review

**Spec coverage (Plan-2 slice of §New/modified files + §Testing strategy):**
- `factcheck_gate.py` (structural validator + confidence cap) → T2, all HARD + WARN codes + cap tested.
- `narrative_render.py` (render-draft / render-frozen / skeleton + `{tN}` fill) → T4.
- `frozen_narrative.py` (override read/write + version keys) → T3.
- `first_screen.py` → T1.
- CLI `gate`/`render-draft`/`finalize`/`render-frozen`/`skeleton` → T5. (`facts` already shipped in
  Plan 1; `run auto` also-emits-facts.json is a Plan 3 wiring item.)
- Testing-strategy gate matrix: every HARD (MISSING_FACT, METRIC_MISBIND, DIRECTION_CONFLICT,
  INVENTED_ENTITY, NONEXISTENT_SLICE, QUANTIFIED_ATTRIBUTION, SUMMED_POOLS, MAGNITUDE_UNBOUND,
  DANGLING_CALLBACK) and every WARN (UNTAGGED_MECHANISM, MISSED_MECHANISM, UNLABELED_SIZING,
  MISSING_SPINE_CALLBACK, REDUNDANT_HEADLINE, CONFIDENCE_CAPPED) has a focused case; a tagged-weak
  mechanism claim PASSES (`test_directional_mechanism_on_absent_link_passes`,
  `test_mechanism_confidence_capped_to_weak`); confidence-cap + input-immutability asserted.
- `{tN}`/edit-pair mechanical contract → T4 (`fill_sentence` zero-derivation, continuity digit+token
  multiset invariance, `old`-occurs-once).
- Skeleton reuses `module_reading`/compositor + banner → T4 `skeleton_markdown` + T5 `skeleton`.

**Deferred to Plan 3 (not gaps):** orchestration assets (`orchestration/dag.md`, `schemas/*.json`,
`prompts/*.md`), the optional `report_writer_workflow.js`, SKILL.md step 7b, `run auto` also-emits
facts.json, `report_runs.jsonl` telemetry, skill-mirror sync, demo regen. `narrative_schema_version`
is authored here hashing the gate/render contract and will be extended in Plan 3 to fold in the
prompt/schema assets (a deliberate version bump).

**Type consistency:** claim/bundle/facts dict shapes are identical across T1–T5; evidence strings use
StrEnum values (`strong`/`high`); `GateReport.bundle` is the capped bundle consumed by
`render_draft`/`render_frozen`; `run_gate` never mutates its input (deep-copy). Tag ranks 强>中>弱 are
shared between gate cap and `trust_routing.confidence_tag` (mirrored logic).

**Execution order (parallel-safe):** T1, T2 (distinct new files) parallel → T4 (imports T1+T2) → T3
(imports T4) → T5 (edits shared cli.py, imports T2/T3/T4). Each task ends green + committed.
