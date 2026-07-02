# Phase 1a · Plan 1 — Report Contract & Renderer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every analysis finding *able* to carry all 8 report-contract elements (conclusion, key numbers, evidence strength, why, confounders, action, next test, appendix) plus rollup subsections and named examples, and *require* STRONG/MEDIUM findings to justify themselves — fixing report root-cause #2 (the `Finding` dataclass structurally cannot emit confounders/next_test/appendix).

**Architecture:** Extend the two result dataclasses (`Finding`, `AnalysisResult`) with the missing fields and a new `Subsection`. Teach the two renderers to emit them: HTML renders all 8 (canonical rich output), Markdown renders 7 (everything but `evidence_reason`, which stays HTML-only by deliberate design). Add a standalone `finding_contract` validator that consuming §-tasks opt into — it is **not** wired into the renderers, because the existing test suite creates many STRONG/MEDIUM findings without confounders and wiring it in would break them.

**Tech Stack:** Python 3.11+ dataclasses, Jinja2 (`report.html.j2`), pytest.

## Global Constraints

- Python **3.11+**; ruff **line-length = 100**.
- `evidence_reason` ("why") stays **HTML-only** — `tests/test_report_rendering.py::test_render_markdown_does_not_render_html_only_evidence_reason` MUST stay green.
- **Omit absent fields**: empty list / `None` → render nothing. Never emit "N/A" / "无".
- The contract guard is a **standalone validator**, NOT called from `render_html` / `render_markdown`. Legacy findings are grandfathered.
- No `Co-Authored-By` trailer on commits.
- Runtime mirror at `skills/data-analyze-for-zcl/assets/xhs-ca/` — run **sync-runtime** after source changes (or defer to Plan 3's final task if executing all of Phase 1a together).

---

### Task 0: Commit the pre-existing WIP (shared prerequisite for all Phase 1a plans)

The working tree already contains an **unrelated, coherent WIP feature** —
`render_markdown_document_html` (in `xhs_ceramics_analytics/reporting/html.py`),
the `render-html` CLI command (`xhs_ceramics_analytics/cli.py`), and matching
tests in `tests/test_report_rendering.py` — mirrored into
`skills/data-analyze-for-zcl/assets/xhs-ca/…` and touching
`README.md`, `references/cheatsheet.md`, `references/report_contract.md`,
`skills/data-analyze-for-zcl/SKILL.md`. It is **not** part of this plan. Commit it
first so every task below starts from a clean tree and has clean boundaries.

**Files:**
- Modify (already dirty): `xhs_ceramics_analytics/reporting/html.py`, `xhs_ceramics_analytics/cli.py`, `tests/test_report_rendering.py`, `references/report_contract.md`, `references/cheatsheet.md`, `README.md`, `skills/data-analyze-for-zcl/**`

- [ ] **Step 1: Confirm the WIP is green before committing**

Run: `pytest -q`
Expected: PASS (the WIP tests `test_render_markdown_document_html_wraps_custom_report`, `test_cli_render_html_*` pass). If anything fails, stop and report — do not "fix" WIP you did not write.

- [ ] **Step 2: Review what is staged**

Run: `git status --porcelain && git diff --stat`
Expected: only the WIP files listed above are modified; no deletions of source data.

- [ ] **Step 3: Commit the WIP as its own commit**

```bash
git add -A
git commit -m "feat(report): render-html command + markdown-document HTML wrapper"
```

- [ ] **Step 4: Verify a clean tree**

Run: `git status --porcelain`
Expected: empty output.

---

### Task 1: Extend result dataclasses (`Finding`, `Subsection`, `AnalysisResult`)

**Files:**
- Modify: `xhs_ceramics_analytics/analysis/result.py`
- Test: `tests/test_result_types.py` (create)

**Interfaces:**
- Produces:
  - `Finding(..., confounders: list[str] = [], next_test: str | None = None, appendix: str | None = None)` — new trailing fields, all defaulted (backward compatible with every existing `Finding(...)` call site).
  - `Subsection(title: str, body: str | None = None, table_name: str | None = None, findings: list[Finding] = [])`.
  - `AnalysisResult(..., subsections: list[Subsection] = [], named_examples: list[dict[str, object]] = [])`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_result_types.py
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding, Subsection
from xhs_ceramics_analytics.evidence import EvidenceStrength


def test_finding_defaults_new_contract_fields_to_empty():
    finding = Finding(
        title="t", conclusion="c", evidence_strength=EvidenceStrength.WEAK
    )
    assert finding.confounders == []
    assert finding.next_test is None
    assert finding.appendix is None


def test_finding_accepts_full_contract():
    finding = Finding(
        title="t",
        conclusion="c",
        evidence_strength=EvidenceStrength.STRONG,
        confounders=["季节性需求上升"],
        next_test="下周只改文案角度做 A/B",
        appendix="口径：退款后GMV=支付时间口径",
    )
    assert finding.confounders == ["季节性需求上升"]
    assert finding.next_test.startswith("下周")


def test_analysis_result_carries_subsections_and_examples():
    sub = Subsection(title="买前确认区", body="高退款SKU", table_name="sku_performance")
    result = AnalysisResult(
        task_id="x",
        title="X",
        findings=[],
        subsections=[sub],
        named_examples=[{"label": "鱼盘12寸", "detail": "退款率偏高"}],
    )
    assert result.subsections[0].title == "买前确认区"
    assert result.subsections[0].findings == []
    assert result.named_examples[0]["label"] == "鱼盘12寸"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_result_types.py -v`
Expected: FAIL — `ImportError: cannot import name 'Subsection'` and `TypeError: __init__() got an unexpected keyword argument 'confounders'`.

- [ ] **Step 3: Write the implementation**

Replace the entire body of `xhs_ceramics_analytics/analysis/result.py` with:

```python
from dataclasses import dataclass, field

from xhs_ceramics_analytics.evidence import EvidenceStrength


@dataclass
class Finding:
    title: str
    conclusion: str
    evidence_strength: EvidenceStrength
    key_numbers: dict[str, object] = field(default_factory=dict)
    caveats: list[str] = field(default_factory=list)
    recommended_action: str | None = None
    evidence_reason: str | None = None
    confounders: list[str] = field(default_factory=list)
    next_test: str | None = None
    appendix: str | None = None


@dataclass
class Subsection:
    title: str
    body: str | None = None
    table_name: str | None = None
    findings: list[Finding] = field(default_factory=list)


@dataclass
class AnalysisResult:
    task_id: str
    title: str
    findings: list[Finding]
    tables: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    subsections: list[Subsection] = field(default_factory=list)
    named_examples: list[dict[str, object]] = field(default_factory=list)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_result_types.py -v && pytest -q`
Expected: new tests PASS; full suite still PASS (new fields are trailing + defaulted).

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/analysis/result.py tests/test_result_types.py
git commit -m "feat(result): add confounders/next_test/appendix + Subsection/named_examples"
```

---

### Task 2: Markdown renders 7 elements + subsections + named examples

**Files:**
- Modify: `xhs_ceramics_analytics/reporting/markdown.py` (`render_markdown`, lines 30-64)
- Test: `tests/test_report_rendering.py` (add tests)

**Interfaces:**
- Consumes: `Finding.confounders/next_test/appendix`, `AnalysisResult.subsections/named_examples`, `Subsection` (Task 1).
- Produces: `_render_finding(finding, heading_level="###") -> list[str]` (extracted; reused for subsection findings).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_report_rendering.py  (add)
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding, Subsection
from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.reporting.markdown import render_markdown


def _full_finding():
    return Finding(
        title="退款率偏高",
        conclusion="鱼盘SKU退款率显著高于账号均值。",
        evidence_strength=EvidenceStrength.MEDIUM,
        key_numbers={"refund_rate_pay": 0.18},
        caveats=["样本较小"],
        recommended_action="在详情页加买前确认区。",
        evidence_reason="仅HTML应出现的原因。",
        confounders=["季节性退货高峰"],
        next_test="下周只改详情页做对照。",
        appendix="口径：退款率为支付时间口径。",
    )


def test_markdown_renders_seven_contract_elements_not_evidence_reason():
    md = render_markdown([AnalysisResult(task_id="x", title="X", findings=[_full_finding()])])
    assert "可能的混淆因素：" in md
    assert "季节性退货高峰" in md
    assert "下一步验证：" in md
    assert "方法与附录：" in md
    assert "建议动作：" in md
    # evidence_reason stays HTML-only:
    assert "仅HTML应出现的原因。" not in md


def test_markdown_renders_subsections_and_named_examples():
    result = AnalysisResult(
        task_id="x",
        title="X",
        findings=[],
        subsections=[Subsection(title="买前确认区", body="高退款SKU清单", findings=[_full_finding()])],
        named_examples=[{"label": "鱼盘12寸", "detail": "退款率0.18"}],
    )
    md = render_markdown([result])
    assert "#### 买前确认区" in md
    assert "高退款SKU清单" in md
    assert "命名示例：" in md
    assert "鱼盘12寸" in md
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_report_rendering.py -k "seven_contract or subsections_and_named" -v`
Expected: FAIL — assertions on "可能的混淆因素：" etc. not found.

- [ ] **Step 3: Write the implementation**

In `xhs_ceramics_analytics/reporting/markdown.py`, replace `render_markdown` (lines 30-64) with the version below, and add the three helpers after it (before `_render_table_preview`):

```python
def render_markdown(results: list[AnalysisResult]) -> str:
    lines = ["# 小红书账号分析报告", ""]
    for result in results:
        lines.extend([f"## {_display_title(result.title)}", ""])
        if result.limitations:
            lines.append("限制：")
            for limitation in result.limitations:
                lines.append(f"- {_display_limitation(limitation)}")
            lines.append("")
        for finding in result.findings:
            lines.extend(_render_finding(finding))
        for subsection in result.subsections:
            lines.extend(_render_subsection(subsection))
        if result.named_examples:
            lines.extend(_render_named_examples(result.named_examples))
        for table_name, rows in result.tables.items():
            lines.extend(_render_table_preview(table_name, rows))
    return "\n".join(lines).rstrip() + "\n"


def _render_finding(finding, heading_level: str = "###") -> list[str]:
    lines = [
        f"{heading_level} {finding.title}",
        "",
        finding.conclusion,
        "",
        f"证据强度：{_evidence_label(finding.evidence_strength.value)}",
        "",
    ]
    if finding.key_numbers:
        lines.append("关键数字：")
        for key, value in finding.key_numbers.items():
            lines.append(f"- `{key}`: {value}")
        lines.append("")
    if finding.caveats:
        lines.append("注意事项：")
        for caveat in finding.caveats:
            lines.append(f"- {caveat}")
        lines.append("")
    if finding.confounders:
        lines.append("可能的混淆因素：")
        for confounder in finding.confounders:
            lines.append(f"- {confounder}")
        lines.append("")
    if finding.recommended_action:
        lines.extend(["建议动作：", "", finding.recommended_action, ""])
    if finding.next_test:
        lines.extend(["下一步验证：", "", finding.next_test, ""])
    if finding.appendix:
        lines.extend(["方法与附录：", "", finding.appendix, ""])
    return lines


def _render_subsection(subsection) -> list[str]:
    lines = [f"#### {subsection.title}", ""]
    if subsection.body:
        lines.extend([subsection.body, ""])
    for finding in subsection.findings:
        lines.extend(_render_finding(finding, heading_level="#####"))
    return lines


def _render_named_examples(examples: list[dict]) -> list[str]:
    lines = ["命名示例：", ""]
    for example in examples:
        label = example.get("label") or example.get("name") or ""
        detail = example.get("detail") or example.get("note") or ""
        lines.append(f"- **{label}**：{detail}" if detail else f"- **{label}**")
    lines.append("")
    return lines
```

Note: `evidence_reason` is deliberately never appended here.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_report_rendering.py -v`
Expected: new tests PASS; `test_render_markdown_does_not_render_html_only_evidence_reason` still PASS.

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/reporting/markdown.py tests/test_report_rendering.py
git commit -m "feat(markdown): render confounders/next_test/appendix + subsections + named examples"
```

---

### Task 3: HTML renders all 8 elements + subsections + named examples

**Files:**
- Modify: `xhs_ceramics_analytics/reporting/html.py` (`_result_view` 740-751, `_finding_view` 754-769; add `_subsection_view`)
- Modify: `xhs_ceramics_analytics/reporting/templates/report.html.j2` (finding block 860-900)
- Test: `tests/test_report_rendering.py` (add test)

**Interfaces:**
- Consumes: `Finding.confounders/next_test/appendix`, `AnalysisResult.subsections/named_examples`, `Subsection` (Task 1).
- Produces: `_subsection_view(subsection: Subsection) -> dict` with keys `title/body/table_name/findings`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report_rendering.py  (add)
from xhs_ceramics_analytics.reporting.html import render_html


def test_html_renders_all_eight_contract_elements():
    result = AnalysisResult(
        task_id="x",
        title="X",
        findings=[_full_finding()],
        subsections=[Subsection(title="买前确认区", body="高退款SKU清单", findings=[_full_finding()])],
        named_examples=[{"label": "鱼盘12寸", "detail": "退款率0.18"}],
    )
    html = render_html([result])
    assert "可信度原因：" in html          # evidence_reason (HTML-only, element 4)
    assert "仅HTML应出现的原因。" in html
    assert "可能的混淆因素" in html          # element 5
    assert "下一步验证：" in html            # element 7
    assert "方法与附录：" in html            # element 8
    assert "买前确认区" in html              # subsection
    assert "命名示例" in html and "鱼盘12寸" in html


def test_html_omits_empty_contract_fields():
    lean = Finding(title="t", conclusion="c", evidence_strength=EvidenceStrength.WEAK)
    html = render_html([AnalysisResult(task_id="x", title="X", findings=[lean])])
    assert "可能的混淆因素" not in html
    assert "下一步验证：" not in html
    assert "方法与附录：" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_report_rendering.py -k "all_eight or omits_empty" -v`
Expected: FAIL — "可能的混淆因素" / "下一步验证：" not present.

- [ ] **Step 3a: Extend the view builders in `html.py`**

Replace `_result_view` (lines 740-751) and `_finding_view` (lines 754-769), and add `_subsection_view` after `_finding_view`:

```python
def _result_view(result: AnalysisResult) -> dict[str, object]:
    return {
        "task_id": result.task_id,
        "title": result.title,
        "label": _result_label(result.task_id, result.title),
        "findings": [_finding_view(finding) for finding in result.findings],
        "chart_svg": charts.for_result(result),
        "table_views": [
            _table_view(table_name, rows) for table_name, rows in result.tables.items()
        ],
        "limitations": result.limitations,
        "subsections": [_subsection_view(subsection) for subsection in result.subsections],
        "named_examples": result.named_examples,
    }


def _finding_view(finding: Finding) -> dict[str, object]:
    summary = _finding_summary(finding)
    return {
        **summary,
        "key_numbers": [
            {
                "label": _field_label(key),
                "help": _field_help(key),
                "value": _display_cell(key, value),
            }
            for key, value in finding.key_numbers.items()
        ],
        "caveats": finding.caveats,
        "recommended_action": finding.recommended_action,
        "evidence_reason": finding.evidence_reason,
        "confounders": finding.confounders,
        "next_test": finding.next_test,
        "appendix": finding.appendix,
    }


def _subsection_view(subsection) -> dict[str, object]:
    return {
        "title": subsection.title,
        "body": subsection.body,
        "table_name": subsection.table_name,
        "findings": [_finding_view(finding) for finding in subsection.findings],
    }
```

Add `Subsection` to the existing `from xhs_ceramics_analytics.analysis.result import ...` line at the top of `html.py` (it already imports `AnalysisResult, Finding`).

- [ ] **Step 3b: Add a reusable `finding_card` macro + render the new fields in `report.html.j2`**

At the very top of `report.html.j2` (before `<!DOCTYPE html>`), add a macro that
holds the full finding card, then reuse it. First define the macro:

```jinja
{% macro finding_card(finding) %}
<article class="finding-card">
  <span class="tag {{ finding.evidence_class }}">可信度 {{ finding.evidence }}</span>
  <h3>{{ finding.title }}</h3>
  <p>{{ finding.body }}</p>

  {% if finding.evidence_reason %}
  <p><strong>可信度原因：</strong>{{ finding.evidence_reason }}</p>
  {% endif %}

  {% if finding.key_numbers %}
  <div class="numbers">
    {% for item in finding.key_numbers %}
    <div class="number-row">
      <span class="field-name">
        <strong>{{ item.label }}</strong>
        <span class="field-help">{{ item.help }}</span>
      </span>
      <strong>{{ item.value }}</strong>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  {% if finding.caveats %}
  <ul class="note-list">
    {% for caveat in finding.caveats %}
    <li>{{ caveat }}</li>
    {% endfor %}
  </ul>
  {% endif %}

  {% if finding.confounders %}
  <div class="notice">
    <strong>可能的混淆因素</strong>
    <ul class="note-list">
      {% for confounder in finding.confounders %}
      <li>{{ confounder }}</li>
      {% endfor %}
    </ul>
  </div>
  {% endif %}

  {% if finding.recommended_action %}
  <p><strong>建议：</strong>{{ finding.recommended_action }}</p>
  {% endif %}

  {% if finding.next_test %}
  <p><strong>下一步验证：</strong>{{ finding.next_test }}</p>
  {% endif %}

  {% if finding.appendix %}
  <p><strong>方法与附录：</strong>{{ finding.appendix }}</p>
  {% endif %}
</article>
{% endmacro %}
```

Then replace the inline finding block (lines 860-900) so the main grid uses the macro and subsections/named-examples render after it:

```jinja
            {% if result.findings %}
            <div class="finding-grid">
              {% for finding in result.findings %}
              {{ finding_card(finding) }}
              {% endfor %}
            </div>
            {% endif %}

            {% for subsection in result.subsections %}
            <div class="subsection">
              <h4>{{ subsection.title }}</h4>
              {% if subsection.body %}<p>{{ subsection.body }}</p>{% endif %}
              {% if subsection.findings %}
              <div class="finding-grid">
                {% for finding in subsection.findings %}
                {{ finding_card(finding) }}
                {% endfor %}
              </div>
              {% endif %}
            </div>
            {% endfor %}

            {% if result.named_examples %}
            <div class="notice">
              <strong>命名示例</strong>
              <ul class="note-list">
                {% for example in result.named_examples %}
                <li><strong>{{ example.label }}</strong>{% if example.detail %}：{{ example.detail }}{% endif %}</li>
                {% endfor %}
              </ul>
            </div>
            {% endif %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_report_rendering.py -v`
Expected: new tests PASS; all pre-existing HTML tests still PASS (macro output for the main grid is byte-identical to the old inline block plus the three new guarded fields, which are absent when empty).

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/reporting/html.py xhs_ceramics_analytics/reporting/templates/report.html.j2 tests/test_report_rendering.py
git commit -m "feat(html): render all 8 contract elements + subsections + named examples"
```

---

### Task 4: Contract guard + anti-filler contract test

**Files:**
- Create: `xhs_ceramics_analytics/contracts/finding_contract.py`
- Test: `tests/test_finding_contract.py` (create)

**Interfaces:**
- Consumes: `Finding` (Task 1), `EvidenceStrength`.
- Produces: `assert_finding_contract(finding: Finding) -> None` — raises `ValueError` when a STRONG/MEDIUM finding has empty `confounders` or missing `next_test`; no-op for WEAK/NOT_JUDGABLE. **Not** called by any renderer.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_finding_contract.py
import pytest

from xhs_ceramics_analytics.analysis.result import Finding
from xhs_ceramics_analytics.contracts.finding_contract import assert_finding_contract
from xhs_ceramics_analytics.evidence import EvidenceStrength


def test_strong_without_confounders_raises():
    finding = Finding(
        title="t", conclusion="c", evidence_strength=EvidenceStrength.STRONG,
        next_test="下周A/B",
    )
    with pytest.raises(ValueError, match="confounders"):
        assert_finding_contract(finding)


def test_medium_without_next_test_raises():
    finding = Finding(
        title="t", conclusion="c", evidence_strength=EvidenceStrength.MEDIUM,
        confounders=["季节性"],
    )
    with pytest.raises(ValueError, match="next_test"):
        assert_finding_contract(finding)


def test_strong_with_full_contract_passes():
    finding = Finding(
        title="t", conclusion="c", evidence_strength=EvidenceStrength.STRONG,
        confounders=["季节性"], next_test="下周A/B",
    )
    assert assert_finding_contract(finding) is None


def test_weak_is_exempt():
    finding = Finding(title="t", conclusion="c", evidence_strength=EvidenceStrength.WEAK)
    assert assert_finding_contract(finding) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_finding_contract.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xhs_ceramics_analytics.contracts.finding_contract'`.

- [ ] **Step 3: Write the implementation**

```python
# xhs_ceramics_analytics/contracts/finding_contract.py
"""Opt-in report-contract guard for analysis findings.

Consuming §-tasks call ``assert_finding_contract`` on the findings they emit.
It is deliberately NOT wired into the renderers: legacy findings predate the
confounders/next_test fields and are grandfathered.
"""
from xhs_ceramics_analytics.analysis.result import Finding
from xhs_ceramics_analytics.evidence import EvidenceStrength

_REQUIRES_FULL_CONTRACT = {EvidenceStrength.STRONG, EvidenceStrength.MEDIUM}


def assert_finding_contract(finding: Finding) -> None:
    """Raise ``ValueError`` if a STRONG/MEDIUM finding omits required elements."""
    if finding.evidence_strength not in _REQUIRES_FULL_CONTRACT:
        return
    missing: list[str] = []
    if not finding.confounders:
        missing.append("confounders")
    if not finding.next_test:
        missing.append("next_test")
    if missing:
        raise ValueError(
            f"{finding.evidence_strength.value} finding {finding.title!r} "
            f"missing required contract fields: {', '.join(missing)}."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_finding_contract.py -v && pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/contracts/finding_contract.py tests/test_finding_contract.py
git commit -m "feat(contracts): opt-in STRONG/MEDIUM finding contract guard"
```

---

### Task 5: Field labels for the seven new Phase-1a metrics

**Files:**
- Modify: `xhs_ceramics_analytics/reporting/html.py:31` (`_FIELD_LABELS` dict)
- Test: `tests/test_field_labels.py` (create)

**Interfaces:**
- Consumes: `_field_label(field_name: str) -> str` and `_field_help(field_name: str) -> str` (existing helpers at `html.py:1190`/`1197`; they read `_FIELD_LABELS`, falling back to `field_name.replace("_", " ")` when a key is absent).
- Produces: seven new `_FIELD_LABELS` keys so the metrics the ingestion marts and Phase-2 analyses emit render as Chinese labels + help text in the HTML report, instead of the raw snake_case fallback.

**Context:** Spec §C report changes call for Chinese labels on the new metric keys introduced by Phase-1a ingestion (`net_gmv_pay`, `refund_rate_pay`, `click_to_order`, `gmv_per_click`, `note_gmv`, `category_l2`, `add_to_cart_users`). Without them, `_field_label("net_gmv_pay")` falls back to `"net gmv pay"` in the report. Spec line: "No new report sections in 1a" — this task adds labels only, no sections.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_field_labels.py
from xhs_ceramics_analytics.reporting.html import _field_help, _field_label

_NEW_LABELS = {
    "net_gmv_pay": "退款后GMV",
    "refund_rate_pay": "退款率(支付时间)",
    "click_to_order": "点击到订单",
    "gmv_per_click": "每次点击GMV",
    "note_gmv": "笔记支付金额",
    "category_l2": "二级品类",
    "add_to_cart_users": "加购人数",
}


_GENERIC_HELP_FALLBACK = "原始数据字段，保留用于查数和追溯。"


def test_new_metric_labels_render_chinese():
    for key, label in _NEW_LABELS.items():
        assert _field_label(key) == label


def test_new_metric_labels_have_specific_help_text():
    # each key must resolve to its OWN help sentence, not the generic fallback
    # (which _field_help returns for any unknown key) — proving the entry landed.
    for key in _NEW_LABELS:
        help_text = _field_help(key)
        assert help_text and help_text != _GENERIC_HELP_FALLBACK
        assert help_text.endswith("。")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_field_labels.py -v`
Expected: FAIL — `_field_label("net_gmv_pay")` returns `"net gmv pay"` (fallback), not `"退款后GMV"`.

- [ ] **Step 3: Add the seven entries to `_FIELD_LABELS`**

Add these seven `(label, help)` entries to the `_FIELD_LABELS` dict in `html.py` (the dict starts at line 31). Insert each key so the dict stays alphabetically sorted (ruff does not enforce dict-key order, but the file is maintained in alpha order — e.g. `add_to_cart_users` goes just after `active_days`, `category_l2`/`click_to_order` between `candidate_notes` and `collect_rate`):

```python
    "add_to_cart_users": ("加购人数", "将商品加入购物车的人数。"),
    "category_l2": ("二级品类", "商品的二级品类。"),
    "click_to_order": ("点击到订单", "笔记支付订单数除以商品点击次数。"),
    "gmv_per_click": ("每次点击GMV", "笔记支付金额除以商品点击次数。"),
    "net_gmv_pay": ("退款后GMV", "支付金额减去退款金额后的净额（平台按支付时间口径给出）。"),
    "note_gmv": ("笔记支付金额", "该笔记带来的支付金额。"),
    "refund_rate_pay": ("退款率(支付时间)", "退款金额占支付金额的比例，按支付时间口径统计。"),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_field_labels.py -v && pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/reporting/html.py tests/test_field_labels.py
git commit -m "feat(reporting): Chinese labels for the seven Phase-1a metric keys"
```

---

## Self-Review (run after all tasks)

1. **Spec coverage (Section C):** C.1 result types → Task 1. C.2 rendering (HTML 8 / markdown 7, labels) → Tasks 2-3. C.3 anti-filler (omit-when-empty test, contract test, guard) → Tasks 3-4. C report-changes (Chinese labels for the seven new Phase-1a metric keys) → Task 5. ✅
2. **Placeholder scan:** none — every code step is complete.
3. **Type consistency:** `_render_finding(finding, heading_level=...)`, `_subsection_view(subsection)`, `assert_finding_contract(finding)`, `Subsection(title, body, table_name, findings)` used identically across tasks. `Finding` new fields spelled `confounders`/`next_test`/`appendix` everywhere.
4. **Regression guard:** `test_render_markdown_does_not_render_html_only_evidence_reason` referenced in Task 2 Step 4; full `pytest -q` in Tasks 1 & 4.
