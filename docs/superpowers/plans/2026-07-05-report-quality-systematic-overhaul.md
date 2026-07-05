# 报告质量系统性重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline, batch execution with checkpoints) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从设计源头修复用户报告的 19 条质量问题——收敛到 5 个架构性病根,一处改、所有模块继承,不打补丁。

**Architecture:** 五个病根各有单一设计源头:(A) 证据双轴在**呈现层**融合为单一「置信度」,以描述可靠性为主,因果强度降级为脚注;图表灰化从"因果弱"解绑到"描述不可靠/不可判断"。(B) 编排层建立**数据驱动的两级信息架构**——6 个业务主题域(大结构)× 域内按优先级归并(主次),取代 html.py 手写的 `_ANALYSIS_GROUPS`。(C) `Finding` 立"商家话 vs 方法学"契约,方法学一律进 `appendix`;`field_labels`/词表一轮说人话改写,消除英文枚举与术语。(D) GMV 桥结论显式说明前后半程口径与抵消关系。(E) 单-Finding 构造改为逐 section emit;趋势表按时序检测强制折叠只留图;CSS overflow 链修复。

**Tech Stack:** Python 3.14 (`.venv/bin/python`)、DuckDB、pandas、pytest、ruff(line-length=100)、Jinja2(`autoescape=True`,live 模板 `reporting/templates/report.html.j2`)。

## Global Constraints

- 解释器固定为 `.venv/bin/python`;所有命令用它,不要用裸 `python`。
- 模块**永不抛异常**(never-raise):所有新逻辑坏输入降级,不 crash 整份报告。
- 真实 `小红书千帆4-7月数据` 导出为**只读**(WeChat 缓存):只 copy OUT 到 `/tmp`,绝不写/移/改/删其内部。
- emoji 是商家真实笔记原文,**忠实渲染,不 strip**;minimalist-ui 的禁 emoji 只管我们自造的界面文字。
- 不加 Co-Authored-By trailer;commit/push/发布**只在用户明确要求时**执行。
- 每次改完跑 `.venv/bin/python -m pytest`(现 611 passed + 3 skipped by design),不得引入回归;镜像套件(`data-analyze-for-zcl` skill assets)保持同步。
- ruff line-length=100;类型标注齐全;immutable 优先;文件 <800 行。
- 中文回复用户。

---

## File Structure

新增/修改的文件及其职责:

- **`xhs_ceramics_analytics/reporting/confidence.py`** (新建) — 呈现层单一「置信度」原语:`reader_confidence(finding) -> ReaderConfidence`,以描述可靠性为主、因果强度为脚注。md/html/charts/priority 的唯一来源。
- **`xhs_ceramics_analytics/reporting/domains.py`** (新建) — 业务主题域注册表 `DOMAINS` + `group_by_domain(results)`;数据驱动的一级 IA。
- **`xhs_ceramics_analytics/reporting/charts.py`** (改) — 灰化 `de_emphasize` 从 `strength==WEAK` 解绑到 `reader_confidence`。
- **`xhs_ceramics_analytics/reporting/priority.py`** (改) — 优先级表砍成 4 列人话;复用为域内排序信号。
- **`xhs_ceramics_analytics/reporting/html.py`** (改) — 删 `_ANALYSIS_GROUPS`,改由 `domains` 驱动;删高亮卡(#2)、技术追溯 tier(#12)、evidence_reason(#10);置信度改名;域内主次归并。
- **`xhs_ceramics_analytics/reporting/markdown.py`** (改) — 同步置信度改名、域分组、Finding 契约渲染、field_help。
- **`xhs_ceramics_analytics/reporting/templates/report.html.j2`** (改) — 删 evidence_reason/可靠性锚点/元叙述/技术追溯块;"怎么读"提一级;CSS overflow 修复;域两级结构。
- **`xhs_ceramics_analytics/reporting/formatting.py`** (改) — 时序检测 `is_timeseries_table`;markdown field_help 对齐。
- **`xhs_ceramics_analytics/reporting/field_labels.py`** (改) — 词表说人话改写;`stage` 列改名;新客/老客词条。
- **`xhs_ceramics_analytics/analysis/result.py`** (改) — `Finding` 契约文档化(conclusion 只放人话,方法学进 appendix)。
- **`xhs_ceramics_analytics/analysis/core_business.py`** (改) — GMV 桥前后半程口径说明 + 抵消解释;英文枚举 `traffic`→中文。
- **`xhs_ceramics_analytics/analysis/weekly_review.py`** (改) — 单 Finding 改逐 section emit。
- **`xhs_ceramics_analytics/analysis/*.py`** (改) — conclusion/caveats 方法学句子迁移到 appendix(全模块一轮)。

---

# 批次一 · 病根 A:证据双轴 → 单一「置信度」+ 图表灰化解绑

覆盖投诉 #3(全是低/改置信度)、#7(颜色坏)、#10(可信度原因)、#11(可靠性点击滚动)。

### Task A1: 新建呈现层置信度原语 `reporting/confidence.py`

**Files:**
- Create: `xhs_ceramics_analytics/reporting/confidence.py`
- Test: `tests/test_reporting_confidence.py`

**Interfaces:**
- Consumes: `Finding`(`evidence_strength: EvidenceStrength`、`descriptive_reliability: DescriptiveReliability | None`)、`EvidenceStrength`、`DescriptiveReliability`。
- Produces:
  - `class ReaderConfidence(NamedTuple)`: `level: str`("high"/"medium"/"low"/"not_judgable")、`label: str`(高/中/低/暂不下定论)、`help: str`、`de_emphasize: bool`、`causal_caveat: str | None`。
  - `reader_confidence(finding: Finding) -> ReaderConfidence` — 纯函数,never-raise。

**设计原则(写进模块 docstring):** 面向商家的单一「置信度」回答"这条结论能多大程度用于经营决策"。它**以描述可靠性(样本量/置信区间)为主轴**——大样本、窄区间的观察性事实对本期是精确描述,理应"高";因果强度(有无对照)只作为一句 `causal_caveat` 脚注,不再作为主标签,也不再把大样本方向图打成"坏图"。当描述可靠性未评分(None)时,回退到软化后的因果映射(strong/medium→中,weak→低,not_judgable→暂不下定论)。

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reporting_confidence.py
from xhs_ceramics_analytics.analysis.result import Finding
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength
from xhs_ceramics_analytics.reporting.confidence import reader_confidence


def _finding(strength, reliability):
    return Finding(
        title="t", conclusion="c", evidence_strength=strength,
        descriptive_reliability=reliability,
    )


def test_large_sample_observational_reads_high_not_low():
    # The real-data default: causal WEAK but descriptively HIGH → 商家看到"高".
    rc = reader_confidence(_finding(EvidenceStrength.WEAK, DescriptiveReliability.HIGH))
    assert rc.level == "high"
    assert rc.label == "高"
    assert rc.de_emphasize is False
    # 因果口径作为脚注保留,不作为主标签.
    assert rc.causal_caveat is not None


def test_low_reliability_de_emphasizes():
    rc = reader_confidence(_finding(EvidenceStrength.WEAK, DescriptiveReliability.LOW))
    assert rc.level == "low"
    assert rc.de_emphasize is True


def test_not_judgable_stays_not_judgable():
    rc = reader_confidence(_finding(EvidenceStrength.NOT_JUDGABLE, None))
    assert rc.level == "not_judgable"
    assert rc.de_emphasize is True


def test_falls_back_to_softened_evidence_when_no_reliability():
    # 未评描述精度时,不该恒为低.
    rc = reader_confidence(_finding(EvidenceStrength.MEDIUM, None))
    assert rc.level == "medium"
    assert rc.de_emphasize is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reporting_confidence.py -v`
Expected: FAIL(`ModuleNotFoundError: reporting.confidence`)。

- [ ] **Step 3: Write minimal implementation**

```python
# xhs_ceramics_analytics/reporting/confidence.py
"""面向商家的单一「置信度」——呈现层唯一来源。

因果强度 (EvidenceStrength) 恒受"有无对照组"限制,单窗口店铺数据永远最多 WEAK;
把它当主标签会让每条结论都显示"低",并把大样本方向图打成坏图。这个原语改以
**描述可靠性** (样本量/置信区间) 为主轴——它回答"这个数字作为对本期的描述有多精确",
大样本、窄区间的观察性事实理应"高"。因果口径降级为一句 caveat 脚注。纯函数,never-raise。
"""
from typing import NamedTuple

from xhs_ceramics_analytics.analysis.result import Finding
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength


class ReaderConfidence(NamedTuple):
    level: str            # high / medium / low / not_judgable
    label: str            # 高 / 中 / 低 / 暂不下定论
    help: str
    de_emphasize: bool    # 图表/卡片是否降调呈现
    causal_caveat: str | None


_LABELS = {"high": "高", "medium": "中", "low": "低", "not_judgable": "暂不下定论"}
_HELP = {
    "high": "样本量大、口径清晰,可以直接作为本期经营依据。",
    "medium": "可以用于本周决策,建议持续观察。",
    "low": "样本偏小或区间较宽,先当参考方向,不宜直接下定论。",
    "not_judgable": "当前数据不足,需要先补齐导入或埋点。",
}
_CAUSAL_CAVEAT = "这是对已发生数据的描述,尚无对照组,不能据此断定因果。"

_RELIABILITY_TO_LEVEL = {
    DescriptiveReliability.HIGH: "high",
    DescriptiveReliability.MEDIUM: "medium",
    DescriptiveReliability.LOW: "low",
    DescriptiveReliability.NOT_APPLICABLE: None,  # 落到因果回退
}
# 无描述精度时的软化因果映射:不再让观察性数据恒为低.
_EVIDENCE_FALLBACK = {
    EvidenceStrength.STRONG: "high",
    EvidenceStrength.MEDIUM: "medium",
    EvidenceStrength.WEAK: "low",
    EvidenceStrength.NOT_JUDGABLE: "not_judgable",
}


def reader_confidence(finding: Finding) -> ReaderConfidence:
    if finding.evidence_strength is EvidenceStrength.NOT_JUDGABLE:
        level = "not_judgable"
    else:
        level = None
        reliability = finding.descriptive_reliability
        if reliability is not None:
            level = _RELIABILITY_TO_LEVEL.get(reliability)
        if level is None:
            level = _EVIDENCE_FALLBACK.get(finding.evidence_strength, "low")
    caveat = None if level == "not_judgable" else _CAUSAL_CAVEAT
    return ReaderConfidence(
        level=level,
        label=_LABELS[level],
        help=_HELP[level],
        de_emphasize=level in ("low", "not_judgable"),
        causal_caveat=caveat,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_reporting_confidence.py -v`
Expected: PASS(4 passed)。

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/reporting/confidence.py tests/test_reporting_confidence.py
git commit -m "feat(reporting): 呈现层单一置信度原语,以描述可靠性为主轴"
```

### Task A2: 图表灰化从「因果弱」解绑到 `reader_confidence`

**Files:**
- Modify: `xhs_ceramics_analytics/reporting/charts.py`(`for_result` 与各 builder 的 `de = strength == EvidenceStrength.WEAK` 判定,约 :289/326/412/502/535/710/728)
- Test: `tests/test_reporting_charts.py`(新增用例)

**Interfaces:**
- Consumes: `reader_confidence`(Task A1)。
- Produces: 图表 de-emphasize 语义改为 `reader_confidence(finding).de_emphasize`;大样本观察性图恢复实心正常色。

- [ ] **Step 1: Write the failing test** — 断言一个 `WEAK + HIGH` finding 生成的 SVG **不含** hatch/虚线降调标记(`url(#ca-hatch)`、`stroke-dasharray`),而 `WEAK + LOW` 的仍含。

```python
# tests/test_reporting_charts.py (追加)
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength
from xhs_ceramics_analytics.reporting import charts


def _result(reliability):
    f = Finding(
        title="转化", conclusion="c", evidence_strength=EvidenceStrength.WEAK,
        descriptive_reliability=reliability,
        key_numbers={"pay_conversion": 0.046},
    )
    return AnalysisResult(task_id="core_business_diagnosis", title="经营", findings=[f],
                          tables={})


def test_large_sample_observational_chart_not_greyed():
    svg = charts.for_result(_result(DescriptiveReliability.HIGH)) or ""
    assert "ca-hatch" not in svg  # 不再因果弱=坏图


def test_low_reliability_chart_still_de_emphasized():
    svg = charts.for_result(_result(DescriptiveReliability.LOW)) or ""
    # 低可靠性仍降调(具体标记依 builder,断言存在降调 class 之一)
    assert ("ca-hatch" in svg) or ("dasharray" in svg) or (svg == "")
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_reporting_charts.py -v` → 预期第一个 FAIL(当前恒灰)。

- [ ] **Step 3: Implement** — 在 `charts.py` 顶部 `from xhs_ceramics_analytics.reporting.confidence import reader_confidence`;把各处 `de = strength == EvidenceStrength.WEAK` 改为从对应 finding 求 `de = reader_confidence(finding).de_emphasize`。`for_result` 已能拿到 result.findings[0];各 builder 若只收到 `strength`,改为接收 `de_emphasize: bool` 形参,由 `for_result` 统一传入,builder 内部不再自算。保持 never-raise(finding 缺失时 `de_emphasize=False`)。

- [ ] **Step 4: Run** 全图表测试 `.venv/bin/python -m pytest tests/test_reporting_charts.py -v` → PASS。

- [ ] **Step 5: Commit** `fix(reporting): 图表灰化改由描述可靠性驱动,大样本观察性图恢复正常色`

### Task A3: md/html 置信度改名 + 删 evidence_reason(#10)与可靠性锚点(#11)

**Files:**
- Modify: `xhs_ceramics_analytics/reporting/html.py`(`_EVIDENCE_LABELS` :19-24 与 `_finding_summary`/`_finding_view` :817-835;glossary "可信度" :768-770)
- Modify: `xhs_ceramics_analytics/reporting/markdown.py`(`_render_finding` :99-133、`_evidence_label`/`_reliability_label`)
- Modify: `xhs_ceramics_analytics/reporting/templates/report.html.j2`(evidence_reason 渲染 :49-51;可靠性 chip 锚点 `<a href="#appendix">` :42-44)
- Test: `tests/test_reporting_html.py`、`tests/test_reporting_markdown.py`

**Interfaces:**
- Consumes: `reader_confidence`(A1)。
- Produces: 每条 finding 呈现单一「置信度：高/中/低/暂不下定论」+ hover help;因果口径作为一句普通 caveat 文本(非可点击、非独立"可信度原因"标签)。`evidence_reason` 不再单独渲染。可靠性 chip 去掉 `<a href>` 滚动锚点,改纯文本/`<span title>`。

- [ ] **Step 1: Write failing tests** — (a) html:渲染输出含"置信度"且**不含**"可信度"与"描述可靠性原因";(b) 输出不含 `href="#appendix"` 的可靠性链接;(c) markdown:`_render_finding` 输出行以"置信度："开头,不再有"证据强度："与"描述可靠性："两行并列。

```python
# tests/test_reporting_markdown.py (追加)
def test_finding_renders_single_confidence_line():
    from xhs_ceramics_analytics.reporting.markdown import _render_finding
    from xhs_ceramics_analytics.analysis.result import Finding
    from xhs_ceramics_analytics.evidence import EvidenceStrength, DescriptiveReliability
    f = Finding(title="t", conclusion="c", evidence_strength=EvidenceStrength.WEAK,
                descriptive_reliability=DescriptiveReliability.HIGH)
    out = "\n".join(_render_finding(f))
    assert "置信度：高" in out
    assert "证据强度：" not in out
    assert "描述可靠性：" not in out
```

- [ ] **Step 2: Run** 两个测试文件 → 预期 FAIL。

- [ ] **Step 3: Implement**
  - markdown `_render_finding`:把 :105 "证据强度" + :109-110 "描述可靠性" 两行,替换为单行 `f"置信度：{rc.label}"`(rc = reader_confidence(finding)),并把 `rc.causal_caveat` 作为 caveats 追加一行(若非 None 且 finding 未自带同义 caveat)。
  - html `_finding_view`:删 `"evidence_reason": finding.evidence_reason`;`_finding_summary` 改用 `reader_confidence` 产 label/help/class。
  - 模板:删 :49-51 evidence_reason 块;:42-44 可靠性 chip 去 `<a href>` 改 `<span class="chip" title="{{ help }}">`。
  - glossary "可信度" 词条改 "置信度"(:768-770)。

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_reporting_html.py tests/test_reporting_markdown.py -v` → PASS。

- [ ] **Step 5: Commit** `refactor(reporting): 证据双轴呈现层融合为单一「置信度」,删可信度原因与可靠性锚点`

---

# 批次二 · 病根 C:Finding 契约 + 词表说人话

覆盖 #8(元叙述)、#9(术语)、#12(技术追溯)、#15(英文/stage)、#16(新客老客)、#18(基线值)。

### Task C1: `Finding` 立"商家话 vs 方法学"契约 + 全模块方法学句子迁移到 appendix

**Files:**
- Modify: `xhs_ceramics_analytics/analysis/result.py`(`Finding` docstring 契约)
- Modify: `xhs_ceramics_analytics/analysis/*.py`(conclusion/caveats 里的方法学句子迁到 appendix)
- Test: `tests/test_finding_contract.py`(新建,守卫回归)

**契约(写进 `Finding` docstring):** `conclusion` 与 `caveats` 只放**商家能懂的经营语言**;一切方法学措辞(显著性门槛、去趋势、残差、ISO 周、多变点、最小二乘斜率、z 检验、BH-FDR、LMDI、±2σ、赫芬达尔/基尼、分位、"观察性")一律放 `appendix`。`appendix` 在 markdown 渲染为"方法与附录",在 HTML 折叠。

- [ ] **Step 1: Write failing test** — 用一份禁用词表扫描真实构造出的 findings 的 conclusion/caveats。

```python
# tests/test_finding_contract.py
import pytest
from xhs_ceramics_analytics.analysis import core_business
# 依赖一个已建好的测试 DB fixture(复用现有 conftest 的 tmp DB 构造)

_JARGON = ["显著性", "斜率", "残差", "去趋势", "多变点", "z检验", "z 检验",
           "BH-FDR", "LMDI", "赫芬达尔", "基尼", "观察性", "分位", "标准差", "σ"]

def _assert_no_jargon(text):
    for token in _JARGON:
        assert token not in (text or ""), f"方法学术语漏进商家文本: {token} in {text!r}"

def test_core_business_conclusions_are_merchant_facing(built_db_path):
    result = core_business.run(built_db_path)
    for f in result.findings:
        _assert_no_jargon(f.conclusion)
        for c in f.caveats:
            _assert_no_jargon(c)
```

- [ ] **Step 2: Run** → 预期 FAIL(如 core_business.py:589「日度斜率未过显著性门槛」等)。

- [ ] **Step 3: Implement** — 逐模块把方法学句子从 conclusion/caveats **移动**到 appendix(不是删除,保留在附录里,方法学诚实性不丢)。已知点:`core_business.py:154-157`(去趋势/残差/ISO周/多变点)、`:589`(日度斜率显著性);其余模块按测试扩到全 registry 逐个补 fixture 后修。conclusion 里改写成经营语言,如"日环比的涨跌还在正常波动范围内,先不当成趋势"。

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_finding_contract.py -v` → PASS(fixture 覆盖的模块)。

- [ ] **Step 5: Commit** `refactor(analysis): Finding 立商家话契约,方法学措辞迁移到附录`

### Task C2: `field_labels` 词表说人话 + 英文枚举消除 + markdown field_help(#9/#18)

**Files:**
- Modify: `xhs_ceramics_analytics/reporting/field_labels.py`(基尼/赫芬达尔/基线* 等标签;`:186-188` baseline;`:295` audience_type)
- Modify: `xhs_ceramics_analytics/analysis/core_business.py:665`(`dominant_factor="traffic"` → 中文枚举值)
- Modify: `xhs_ceramics_analytics/reporting/markdown.py:112-116`(key_numbers 追加 field_help 行,与 HTML 对齐)
- Modify: `xhs_ceramics_analytics/reporting/formatting.py`(field_help 导出对齐)
- Test: `tests/test_field_labels.py`、`tests/test_reporting_markdown.py`

- [ ] **Step 1: Write failing tests** — (a) `field_label("gini")` 等不含"基尼/赫芬达尔"字样,返回如"集中度(0=均摊,越高越集中在少数)";(b) core_business 输出的 `dominant_factor` 值 ∈ 中文集合,不为 "traffic";(c) markdown key_numbers 行含 field_help 说明文本。

- [ ] **Step 2: Run** → FAIL。

- [ ] **Step 3: Implement** — 词表改写(gini/hhi/baseline_*/各 `*_baseline`);枚举在**产出源**改中文(core_business 的 `dominant_factor` 存 "流量"/"转化"/"客单" 而非英文,连带删任何 `_STAGE_ZH` 之外的英文残留);markdown `_render_finding` 的 key_numbers 循环追加 `field_help(key)`(非空时)。

- [ ] **Step 4: Run** 相关测试 → PASS。

- [ ] **Step 5: Commit** `refactor(reporting): 词表改说人话,消除英文枚举,markdown 补字段说明`

### Task C3: `stage` 列改名解决 shop funnel 错标(#15)+ 新客/老客词条(#16)

**Files:**
- Modify: `xhs_ceramics_analytics/reporting/field_labels.py:235-236`(`stage`/`stage_zh` 被标"退款环节"的碰撞)
- Modify: 产出 shop funnel 的分析模块(把漏斗列名从复用的 `stage` 改为 `funnel_stage`,去掉重复的 `stage_zh` 列)
- Modify: `xhs_ceramics_analytics/reporting/html.py`(glossary 增新客/老客定义)、`field_labels.py:295`
- Modify: `xhs_ceramics_analytics/analysis/audience_structure.py:65-68`(新客/老客判定挂钩首购窗口,注释口径)
- Test: `tests/test_field_labels.py`、`tests/test_reporting_html.py`

- [ ] **Step 1: Write failing test** — shop funnel 表头渲染为"访问→点击/点击→支付/访问→支付"而非"退款环节"/英文;glossary 含"新客"、"老客"定义。

- [ ] **Step 2: Run** → FAIL。

- [ ] **Step 3: Implement** — 漏斗列 `stage`→`funnel_stage`(专属 label),退款模块保留自己的语义;`funnel_stage` 值映射 `visit_click→"访问 → 点击"` 等中文(源头,非展示层 hack);删 `stage_zh` 冗余列;glossary 增两条定义(挂钩 365 天首购窗口口径,与 memory `real-export-caliber-quirks` 的 rollup 说明一致)。

- [ ] **Step 4: Run** → PASS。

- [ ] **Step 5: Commit** `fix(reporting): 漏斗环节列改名去碰撞与重复,补新客/老客定义`

### Task C4: 删技术追溯 tier(#12)与元叙述文字(#8)

**Files:**
- Modify: `xhs_ceramics_analytics/reporting/html.py:847-873`(`_table_view` 去 `technical_columns`/`technical_rows`)
- Modify: `xhs_ceramics_analytics/reporting/templates/report.html.j2:1275-1309`(技术追溯块)、`:1166-1167`、`:1248`(元叙述 prose)
- Test: `tests/test_reporting_html.py`

- [ ] **Step 1: Write failing test** — 渲染输出**不含**"技术追溯"字样,也不含":1166/1248" 的元叙述句("这里按业务问题分组…"/"原始字段在技术追溯信息里")。原始列名仍可在 markdown 表格预览查到(附录留证)。

- [ ] **Step 2: Run** → FAIL。

- [ ] **Step 3: Implement** — `_table_view` 只留 `user_columns`/`user_rows`(删 technical_*);模板删技术追溯 `<details>` 与两处元叙述 prose。

- [ ] **Step 4: Run** → PASS(顺带确认表格仍渲染)。

- [ ] **Step 5: Commit** `refactor(reporting): 删技术追溯 tier 与元叙述文字,原始列名保留在 markdown 附录`

---

# 批次三 · 病根 B:6 域两级信息架构 + 优先级表重写

覆盖 #2(怎么读放最前)、#4(优先级表不说人话)、#19(碎+无轻重),并删高亮卡(#2 决定项)。

### Task B1: 新建业务主题域注册表 `reporting/domains.py`

**Files:**
- Create: `xhs_ceramics_analytics/reporting/domains.py`
- Test: `tests/test_reporting_domains.py`

**Interfaces:**
- Consumes: `AnalysisResult`、`APPENDIX_TASKS`(section_order)、`build_priority_table`/per-result priority(priority.py)。
- Produces:
  - `DOMAINS: tuple[tuple[str, str, tuple[str, ...]], ...]` — (域标题, 域一句话导语, 归入的 task_id 元组)。
  - `group_by_domain(results) -> list[DomainGroup]`,`DomainGroup(NamedTuple)`: `title`、`intro`、`results`(域内按优先级降序)。附录任务不进域,由 section_order 单独收尾。未列入任何域的 task_id 落到最后一个"其他"兜底域,不丢。

**域划分(经用户确认):**
```python
DOMAINS = (
    ("生意大盘", "整体 GMV、转化、客单与增长归因,先看生意本身怎么样。",
     ("core_business_diagnosis", "demand_funnel_diagnosis")),
    ("流量与内容", "笔记商业效能、搜索承接、渠道结构与重拍机会,发什么、从哪来。",
     ("note_commercial_diagnosis", "search_efficiency_diagnosis",
      "channel_structure_diagnosis", "reshoot_repost_candidates",
      "cover_style_effect", "copy_angle_effect", "content_portfolio_optimization",
      "product_content_interaction", "paid_traffic_efficiency",
      "content_response_curve", "note_funnel")),
    ("商品结构", "SKU 的 GMV/退款结构与销售反馈,卖什么、补哪些。",
     ("sku_structure_diagnosis", "product_opportunity_matrix",
      "sku_counterfactual_lift")),
    ("用户与需求", "人群结构与评论里的真实疑问,谁在买、还想问什么。",
     ("audience_structure_diagnosis", "comment_demand_mining")),
    ("退款与售后", "退款结构、层级与根因合并成一块,售后哪里在漏。",
     ("refund_structure_diagnosis", "refund_root_cause_diagnosis")),
    ("实验与下周行动", "把结论转成一周可执行排期与假设留存。",
     ("weekly_experiment_matrix", "weekly_business_review",
      "hypothesis_knowledge_base", "account_baseline")),
)
```

- [ ] **Step 1: Write failing test** — (a) 每个已注册 task 恰好归入一个域(除 APPENDIX);(b) `group_by_domain` 把退款两模块归入同一 "退款与售后" 域;(c) 域内 results 按 priority 降序;(d) 未知 task_id 落兜底域不丢。

```python
# tests/test_reporting_domains.py
from xhs_ceramics_analytics.reporting.domains import DOMAINS, group_by_domain
from xhs_ceramics_analytics.analysis.registry import TASKS
from xhs_ceramics_analytics.reporting.section_order import APPENDIX_TASKS

def test_every_task_mapped_to_exactly_one_domain():
    mapped = [t for _, _, tasks in DOMAINS for t in tasks]
    assert len(mapped) == len(set(mapped)), "task 重复归域"
    for task_id in TASKS:
        if task_id in APPENDIX_TASKS:
            continue
        assert task_id in mapped, f"{task_id} 未归入任何域"

def test_refund_modules_share_one_domain():
    titles = {title: tasks for title, _, tasks in DOMAINS}
    refund = titles["退款与售后"]
    assert "refund_structure_diagnosis" in refund
    assert "refund_root_cause_diagnosis" in refund
```

- [ ] **Step 2: Run** → FAIL(module 不存在)。

- [ ] **Step 3: Implement** `domains.py` — 定义 `DOMAINS`、`DomainGroup`、`group_by_domain`(用 priority.py 的 per-result 打分排序;附录剔除;兜底 "其他参考" 域收容未列 task)。never-raise。

- [ ] **Step 4: Run** → PASS。

- [ ] **Step 5: Commit** `feat(reporting): 业务主题域注册表与 group_by_domain 两级信息架构`

### Task B2: html 用域驱动渲染,替换手写 `_ANALYSIS_GROUPS`;域内主次归并;删高亮卡

**Files:**
- Modify: `xhs_ceramics_analytics/reporting/html.py:73-134`(删 `_ANALYSIS_GROUPS`,`_analysis_groups` 改调 `group_by_domain`)、`:1055-1068`(删 reshoot 高亮卡)、`_business_highlights` 相关
- Modify: `xhs_ceramics_analytics/reporting/templates/report.html.j2`(域两级结构:域标题 + 域内 headline 大卡、其余折 `<details>`)
- Test: `tests/test_reporting_html.py`

- [ ] **Step 1: Write failing tests** — (a) 渲染输出含 6 个域标题且退款两模块在同一域下;(b) 输出**不含**"重拍机会：先复用「"高亮卡文案;(c) 每个域至多一条 headline 大卡,其余在 `<details>` 内。

- [ ] **Step 2: Run** → FAIL。

- [ ] **Step 3: Implement** — `_analysis_groups(result_views)` 改为基于 `group_by_domain` 产出域结构(每域: title/intro/headline_result/secondary_results);模板据此渲染两级;删 `_business_highlights` 里 reshoot 高亮卡分支(:1055-1068),该函数其余分支保留。

- [ ] **Step 4: Run** → PASS。

- [ ] **Step 5: Commit** `feat(reporting): HTML 改由业务主题域驱动两级结构,删重拍高亮卡`

### Task B3: markdown 同步域分组

**Files:**
- Modify: `xhs_ceramics_analytics/reporting/markdown.py:47-65`(render 循环按 `group_by_domain` 加域一级标题)
- Test: `tests/test_reporting_markdown.py`

- [ ] **Step 1: Write failing test** — markdown 输出含"## 生意大盘"等域级标题,退款两模块在同一域下。

- [ ] **Step 2: Run** → FAIL。 **Step 3:** 用 `group_by_domain` 分组渲染(域标题 `##`,模块降为 `###`)。 **Step 4:** PASS。

- [ ] **Step 5: Commit** `feat(reporting): markdown 报告按业务主题域分组`

### Task B4: 优先级表砍成 4 列人话 + "怎么读"提为一级 section(#4/#2)

**Files:**
- Modify: `xhs_ceramics_analytics/reporting/priority.py`(`build_priority_table` 输出列精简;去三网格)
- Modify: `xhs_ceramics_analytics/reporting/markdown.py:68-96`(4 列表 + 表头改人话)
- Modify: `xhs_ceramics_analytics/reporting/html.py`(`_priority_table_view`)、`templates/report.html.j2`("怎么读"从 bento 提为一级 section 并进导航 :1005-1008)
- Test: `tests/test_reporting_priority.py`、`tests/test_reporting_markdown.py`

- [ ] **Step 1: Write failing tests** — (a) 优先级表恰 4 列:先动顺序/哪个环节/具体先做什么/为什么值得先做,**不含**"预期影响""可行性""证据"三列并列;(b) 表头文案含"从上到下就是本周先后顺序",不含"预期影响 × 可行性"公式;(c) html 输出"这份报告怎么读"是一级 section(在导航锚点里)。

- [ ] **Step 2: Run** → FAIL。

- [ ] **Step 3: Implement** — `build_priority_table` 保留内部 `priority` 排序但对外行只暴露 4 个人话字段(顺序由 enumerate 给);置信度作为一个小标签附在"为什么值得先做"里(用 A1 的 label),不再是独立三网格;markdown/html 表头与列改写;模板把"怎么读"卡移出 bento 提为首个一级 section + 加导航项。

- [ ] **Step 4: Run** → PASS。

- [ ] **Step 5: Commit** `refactor(reporting): 优先级表精简为四列人话,「怎么读」提为一级 section`

---

# 批次四 · 病根 D + E:GMV 桥口径 + 内容降级逻辑

覆盖 #14(GMV 桥)、#5(行动计划只 1 条)、#17(趋势表折叠)、#13(表截断)。

### Task D1: GMV 桥前后半程口径说明 + 抵消解释(#14)

**Files:**
- Modify: `xhs_ceramics_analytics/analysis/core_business.py:638-645`(半程切分处补口径)、`_bridge_conclusion :698-718`
- Test: `tests/test_core_business.py`

- [ ] **Step 1: Write failing test** — bridge finding 的 conclusion 显式含"前半程/后半程"口径说明;当主因子贡献 > |净增| 且同向时,含"被…抵消"的解释句。用构造的 fixture(前段流量涨、转化/客单跌、净增微增)断言。

- [ ] **Step 2: Run** → FAIL。

- [ ] **Step 3: Implement** — `_bridge_conclusion` 加入:①口径句("把窗口分成前半程和后半程对比,下面是两段之间的变化");②抵消句(当 `abs(dominant_contribution) > abs(net_delta)`:"流量在涨,但被转化/客单下滑抵消,所以整体只微增")。数字口径不变,仅补文字。方法学细节(LMDI 等)进 appendix(与 C1 契约一致)。

- [ ] **Step 4: Run** → PASS。

- [ ] **Step 5: Commit** `fix(analysis): GMV 桥显式说明前后半程口径与抵消关系`

### Task E1: `weekly_review` 单 Finding 改逐 ready-section emit(#5)

**Files:**
- Modify: `xhs_ceramics_analytics/analysis/weekly_review.py:24-53`
- Test: `tests/test_weekly_review.py`

- [ ] **Step 1: Write failing test** — 当多个子段有数据时,`run` 产出多条 finding(每个 ready section 一条),而非恒 1 条"已汇总 N 个模块"。

- [ ] **Step 2: Run** → FAIL。

- [ ] **Step 3: Implement** — 按每个有数据的子段 emit 一条 finding;子段全空时才降级为单条 not_judgable。同模式若 `experiment_matrix.py:32-61` 也是单 Finding 硬编码,一并改(YAGNI:仅当测试证明它同样折叠时)。

- [ ] **Step 4: Run** → PASS。

- [ ] **Step 5: Commit** `fix(analysis): 每周复盘按子段逐条产出结论,不再折叠为单条`

### Task E2: 趋势表时序检测 → 强制折叠只留图(#17)

**Files:**
- Modify: `xhs_ceramics_analytics/reporting/formatting.py`(新增 `is_timeseries_table(table_name, columns) -> bool`,复用 `is_date_field` :106)
- Modify: `xhs_ceramics_analytics/reporting/html.py:864-867`(`_table_view` 的 `open` 判定加时序检测)
- (可选) 给退款/搜索/心愿单趋势补 `_timeseries_line` builder(charts.py `_BUILDERS`)
- Test: `tests/test_formatting.py`、`tests/test_reporting_html.py`

- [ ] **Step 1: Write failing test** — 表名以 `_trend` 结尾或首列是日期字段时,`_table_view(...)["open"] is False`(强制折叠),即便行数 <10。

- [ ] **Step 2: Run** → FAIL(当前只看行数)。

- [ ] **Step 3: Implement** — `is_timeseries_table`: `table_name.endswith("_trend") or (columns and is_date_field(columns[0]))`;`_table_view` 的 `open = (len(rows) < _MAX_OPEN_TABLE_ROWS) and not is_timeseries_table(...)`。若时间允许,给缺图的趋势表补 line builder(否则保持"只折叠表"亦满足 #17"默认折叠")。

- [ ] **Step 4: Run** → PASS。

- [ ] **Step 5: Commit** `feat(reporting): 时序趋势表默认折叠,优先呈现图表`

### Task E3: 修复表格 CSS overflow 截断链(#13)

**Files:**
- Modify: `xhs_ceramics_analytics/reporting/templates/report.html.j2`(CSS: `.panel-body` :576 加 `min-width:0`;`.field-help` :732 加 `white-space:normal`;确认 `.table-wrap` :831 `overflow-x:auto` 生效)
- Test: 视觉验证(无单测;跑真实报告并肉眼确认宽表可横向滚动)

- [ ] **Step 1:** 改 CSS:grid 子项 `.panel-body{min-width:0}` 让 `.table-wrap` 的 `overflow-x:auto` 能触发;`.field-help{white-space:normal}` 防换行撑破;宽表出现横向滚动条而非裁切。

- [ ] **Step 2:** 跑一份真实报告(见"最终验证"),打开 HTML 确认 p4 的宽表不再截断、可横向滚动。

- [ ] **Step 3: Commit** `fix(reporting): 修复宽表 overflow 截断,启用横向滚动`

---

# 最终验证与交付

- [ ] **全量测试**:`.venv/bin/python -m pytest`(预期 ≥611 passed + 3 skipped by design,无新增 failure)。
- [ ] **ruff**:`.venv/bin/python -m ruff check xhs_ceramics_analytics tests`(line-length=100 clean)。
- [ ] **镜像同步**:把改动同步到 `data-analyze-for-zcl` skill 的 `assets/xhs-ca/`(镜像套件 278 passed + 3 skipped by design 保持)。
- [ ] **真实数据回归**:从 WeChat 缓存(只读)copy 出 13 个 xlsx 到 `/tmp`,`build` 后 `run auto --name 千帆经营诊断报告`,人工核对报告:19 条投诉逐条消解、6 域大结构成型、置信度不再全"低"、图表恢复正常色、宽表不截断、emoji 保留、无高亮卡。
- [ ] **不 commit/push,除非用户明确要求**。

---

## Self-Review

- **Spec 覆盖**:19 条投诉均映射到批次任务(A:#3/#7/#10/#11;B:#2/#4/#19+高亮卡;C:#8/#9/#12/#15/#16/#18;D:#14;E:#5/#17/#13;#1/#6 emoji 已按 1a 保留,无需任务)。
- **无占位符**:关键设计源头(confidence.py、domains.py)给了完整代码;机械改写(词表/方法学迁移)给了精确定位与判据(禁用词表守卫)。
- **类型一致**:`reader_confidence -> ReaderConfidence`、`group_by_domain -> list[DomainGroup]`、`DOMAINS` 三元组结构在 B1/B2/B3 引用一致。
- **批次依赖**:A1 是 A2/A3/B4 的前置(置信度原语);B1 是 B2/B3 的前置(域注册表);C1 契约是 D1 的前提。批次内 TDD、批次间 checkpoint。
