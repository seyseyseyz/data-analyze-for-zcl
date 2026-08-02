# Adaptive Report Domains Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a stable six-domain core with a data-activated paid-growth domain while preserving every module's details and explicit data limitations.

**Architecture:** Keep the existing shared `DOMAINS` registry used by Markdown and HTML. Add a small domain-activation policy beside the registry: core domains activate when a member result exists, while data-activated domains require at least one observed table row. Keep data-quality tasks in the appendix and unknown tasks in the fallback domain.

**Tech Stack:** Python 3.11+, dataclasses, pytest, Jinja2, shared source plus bundled `data-analyze-for-zcl` asset copy.

## Global Constraints

- Preserve the six existing core domain titles and their order.
- Move `paid_traffic_efficiency` to the new `付费增长` domain exactly once.
- A weak paid result with observed rows activates the domain; an empty paid result does not.
- Never infer causal lift or budget effectiveness in the domain layer.
- Preserve unrelated dirty-worktree changes.
- Do not create commits unless the user explicitly requests them.

---

### Task 1: Specify Paid Domain Behavior

**Files:**
- Modify: `tests/test_reporting_domains.py`
- Modify: `skills/data-analyze-for-zcl/assets/xhs-ca/tests/test_reporting_domains.py`

**Interfaces:**
- Consumes: `DOMAINS` and `group_by_domain(results: list[AnalysisResult]) -> list[DomainGroup]`
- Produces: Regression expectations for exact task mapping and observed-row activation.

- [ ] **Step 1: Write the failing mapping test**

```python
def test_paid_traffic_has_its_own_domain():
    titles = {title: tasks for title, _, tasks in DOMAINS}
    assert "paid_traffic_efficiency" in titles["付费增长"]
    assert "paid_traffic_efficiency" not in titles["流量与内容"]
```

- [ ] **Step 2: Write failing activation tests**

```python
def test_paid_growth_domain_activates_with_observed_rows():
    result = _actionable("paid_traffic_efficiency", EvidenceStrength.WEAK, DescriptiveReliability.LOW)
    result.tables = {"paid_traffic_efficiency": [{"spend": 100, "impressions": 1000}]}
    assert [group.title for group in group_by_domain([result])] == ["付费增长"]


def test_paid_growth_domain_stays_hidden_without_observed_rows():
    result = _actionable("paid_traffic_efficiency", EvidenceStrength.NOT_JUDGABLE, DescriptiveReliability.LOW)
    result.tables = {"paid_traffic_efficiency": []}
    assert group_by_domain([result]) == []
```

- [ ] **Step 3: Run tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/test_reporting_domains.py`

Expected: mapping and activation tests fail because paid traffic still belongs to `流量与内容` and empty results still create a group.

### Task 2: Implement Data-Activated Domains

**Files:**
- Modify: `xhs_ceramics_analytics/reporting/domains.py`
- Modify: `skills/data-analyze-for-zcl/assets/xhs-ca/xhs_ceramics_analytics/reporting/domains.py`

**Interfaces:**
- Consumes: `AnalysisResult.tables: dict[str, list[dict[str, object]]]`
- Produces: `DATA_ACTIVATED_DOMAINS: frozenset[str]` and unchanged `group_by_domain` public signature.

- [ ] **Step 1: Add the paid-growth domain**

Remove `paid_traffic_efficiency` from `流量与内容`, then add this domain before `实验与下周行动`:

```python
(
    "付费增长",
    "投放消耗、点击效率与可见投产，预算花在哪、是否值得继续。",
    ("paid_traffic_efficiency",),
),
```

- [ ] **Step 2: Add observed-data activation**

```python
DATA_ACTIVATED_DOMAINS: frozenset[str] = frozenset({"付费增长"})


def _has_observed_rows(result: AnalysisResult) -> bool:
    return any(bool(rows) for rows in result.tables.values())
```

Inside `group_by_domain`, after collecting `members`:

```python
if title in DATA_ACTIVATED_DOMAINS and not any(_has_observed_rows(result) for result in members):
    continue
```

- [ ] **Step 3: Run tests and verify GREEN**

Run: `.venv/bin/python -m pytest -q tests/test_reporting_domains.py`

Expected: all domain registry and activation tests pass.

### Task 3: Align Reader-Facing Report Copy

**Files:**
- Modify: `tests/test_report_rendering.py`
- Modify: `xhs_ceramics_analytics/reporting/templates/report.html.j2`
- Modify: `skills/data-analyze-for-zcl/assets/xhs-ca/tests/test_report_rendering.py`
- Modify: `skills/data-analyze-for-zcl/assets/xhs-ca/xhs_ceramics_analytics/reporting/templates/report.html.j2`

**Interfaces:**
- Consumes: shared domain grouping in `render_html` and `render_markdown`
- Produces: accurate report explanation and paid-growth heading in both outputs.

- [ ] **Step 1: Write failing rendering assertions**

Extend the paid-traffic rendering test:

```python
assert "付费增长" in html
assert "核心经营领域" in html
assert "有相应数据时增加专项领域" in html
```

Add an empty-result test:

```python
def test_html_hides_empty_paid_growth_domain():
    result = AnalysisResult(
        task_id="paid_traffic_efficiency",
        title="投放效率分析",
        findings=[],
        tables={"paid_traffic_efficiency": []},
    )
    assert "付费增长" not in render_html([result])
```

- [ ] **Step 2: Run the focused rendering tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/test_report_rendering.py -k 'paid_traffic or paid_growth'`

Expected: new copy and domain visibility assertions fail before the template and registry changes are complete.

- [ ] **Step 3: Update the hero explanation**

Replace the fixed six-domain sentence with:

```text
这份报告以六个核心经营领域组织完整分析，并在有相应数据时增加付费增长等专项领域。每个领域默认展示核心结论，其余模块和明细仍保留在同一份报告中，可展开备查。先看结论和行动，再按领域下钻，数据质量与口径说明放在末尾附录。
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `.venv/bin/python -m pytest -q tests/test_reporting_domains.py tests/test_report_rendering.py -k 'domain or paid_traffic or paid_growth'`

Expected: all selected tests pass.

### Task 4: Verify Source And Bundled Skill Parity

**Files:**
- Verify: all files listed in Tasks 1–3

**Interfaces:**
- Consumes: source and bundled test suites
- Produces: synchronized installable skill behavior.

- [ ] **Step 1: Run source tests**

Run: `.venv/bin/python -m pytest -q tests/test_reporting_domains.py tests/test_report_rendering.py`

Expected: all tests pass.

- [ ] **Step 2: Run bundled tests**

Run from `skills/data-analyze-for-zcl/assets/xhs-ca`: `../../../../.venv/bin/python -m pytest -q tests/test_reporting_domains.py tests/test_report_rendering.py`

Expected: all tests pass against the bundled package.

- [ ] **Step 3: Check synchronization and whitespace**

Run: `diff -u xhs_ceramics_analytics/reporting/domains.py skills/data-analyze-for-zcl/assets/xhs-ca/xhs_ceramics_analytics/reporting/domains.py`

Expected: no output.

Run: `diff -u tests/test_reporting_domains.py skills/data-analyze-for-zcl/assets/xhs-ca/tests/test_reporting_domains.py`

Expected: no output.

Run: `git diff --check`

Expected: no whitespace errors introduced by this change.
