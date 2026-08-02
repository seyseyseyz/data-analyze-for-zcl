# 经营决策编译器架构 — 设计规格 (Decision Compiler Architecture)

**日期:** 2026-07-10
**状态:** Draft / ADR
**触发:** PiGoo 手作瓷器 2026-04–06 事实层 + 叙事版双报告审计
**目标:** 把系统从「可信数字引擎 + 模块拼接报告」升级为「经营决策编译器」。根因治理，不做呈现层补丁堆叠。

---

## 1. 问题陈述

### 1.1 已有能力（应保留）

- L1 模块输出 `Finding` + tables，永不 raise，缺数据可降级。
- L2 `facts.json` 是数字唯一来源；叙事句只用 `{tN}`。
- L3 gate 阻止裸数字、未绑定 token、视图与表不一致。
- 双交付：事实层 HTML + 叙事版 HTML。

### 1.2 系统性失败模式（不是单点 bug）

对 PiGoo 季报审计可见、且可复现于任意店铺的根因：

| 根因 | 表现 | 为何补丁无效 |
|---|---|---|
| A. 无 Metric Ontology | 17.9% vs 14.7%「加购到支付」；多条退款率；「净利率线索」误称 | 改一处文案，下一模块再引入同名异义 |
| B. Period 非一等公民 | 季报口吻写「本周」；月桥被读成季趋势；历史笔记基线混入当期 | 模板替换「本周→本期」仍缺 analysis/compare window |
| C. 双置信度轴互打 | 事实层「高」、机制句「弱」、视图「强」 | 只统一 pill 文案，gate 与 reader_confidence 仍各算各的 |
| D. 产出是 Finding 不是 Decision | 行动多为口号；优先级按模块权重；无 owner/验收/停损 | 再写更顺的 recommended_action 字符串仍不可执行 |
| E. L3 目标函数偏了 | 15 图 22 表、导语承诺清单正文缺失、reviews 空跑 | 多加图/多写 prose 只会加强图册感 |
| F. 双报告职责未合同化 | 两边都讲故事又都堆模块；模板/缺口只在一侧 | 只改 compositor 分组，职责仍漂移 |
| G. 模块拼接 compositor | 套话 40 次、默认露 5 行截断决策清单 | 调 `_MAX_TABLE_ROWS` 治标不治本 |

### 1.3 北极星

**系统编译的是 DecisionBrief，不是 module 列表的两种排版。**

```text
L1 Signals (metric_id + period + evidence)
   → L2 FactBook (canonical metrics only)
   → L2.5 DecisionBrief (levers + action cards + evidence packs)
   → L3 Narrative view + Fact-layer evidence view
```

---

## 2. 非目标

- 不重做 DuckDB / 导入映射 / 现有分析公式（除非口径注册要求改名）。
- 不引入在线服务、新前端框架、多文件 SPA。
- 不要求笔记→订单强归因（缺 link 时保持 not-judgable）。
- 不把 UI 美化（空标题、英文 eyebrow、print CSS）作为本 ADR 主交付；它们属于 Phase 4 呈现层，且不得阻塞契约落地。

---

## 3. 核心对象模型

### 3.1 `AnalysisContext`（时间与节奏一等公民）

每个 run、每个 finding、每个 claim、每个 action 必须能解析到：

```yaml
analysis_window:
  start: YYYY-MM-DD
  end: YYYY-MM-DD
  cadence: week | month | quarter | custom   # 驱动文案模板
comparison_window:                            # 可选；GMV 桥等需要
  mode: previous_period | calendar_month_pair | trailing_n
  left: { start, end }                        # e.g. 2026-04
  right: { start, end }                       # e.g. 2026-06
baseline_window:                              # 可选；账号基线/分位
  start: YYYY-MM-DD
  end: YYYY-MM-DD
  note: "may exceed analysis_window; must be labeled 历史基线"
timezone: Asia/Shanghai
```

**规则：**

- 禁止硬编码「本周/下周」。渲染器按 `cadence` 选词：`本周/本月/本季/本期`。
- `baseline_window` 若超出 `analysis_window`，UI 必须标注「历史基线，非本期产能」。
- `comparison_window` 必须出现在 GMV 桥结论与首屏 spine 的可见位置。

### 3.2 `MetricSpec`（指标注册表）

权威文件：`references/metrics/registry.yaml`（验证型语义注册表；当前不驱动运行时）。

每个可进入报告的数字必须映射到：

```yaml
metric_id: shop.avg_daily_cart_to_pay_ratio   # 全局唯一，稳定
display_name: 日均加购→支付比（非严格漏斗）
forbidden_aliases: [加购到支付, 加购转化, 加购支付率]  # 仅 display_name 可写
unit: percent
formula: MEAN_BY_VALID_DAY(paid_buyers / NULLIF(add_to_cart_users, 0))
source_grain: shop_day
grain: shop_window               # shop_day | shop_window | sku | note | carrier | ...
aggregation: mean_of_daily_ratios
distinct_scope: day
period_unique: false
window_role: analysis            # analysis | comparison | baseline
numerator: paid_buyers
denominator: add_to_cart_users
caliber: dimensionless           # 与人数/金额/订单数口径互斥
additive: false
proxy: false                     # true → 禁止称「率/利润」等财务词
proxy_label: null                # e.g. 转化减退款（非会计净利率）
non_additive_group: null         # e.g. refund_share_mix
owners_modules: [demand_funnel_diagnosis]
legacy_keys:                     # 迁移期
  - demand_funnel_diagnosis.avg_daily_cart_to_pay
```

**硬规则：**

1. `Fact.metric_id` 必填（迁移期可用 `legacy_keys` 反查，但 export 必须写出 metric_id）。
2. 同 `display_name` 不得对应多个 `metric_id`。
3. `proxy: true` 的指标，renderer 禁止输出「净利率/利润率」等词。
4. 不同 `caliber` / `non_additive_group` 的份额不得在同一可加总视觉中无警告并置。
5. 叙事 claim 的 `expected_metric_key` 升级为必须等于 `metric_id`（或 registry 声明的 alias key）。

### 3.3 `Signal`（L1 对决策层的标准输出）

`Finding` 保留以兼容旧模块；新增并行结构（可从 Finding 编译）：

```yaml
signal_id: refund.pre_ship_amount_share
metric_refs: [shop.refund_amount_rate, refund.pre_ship_amount_share]
period: $ref AnalysisContext
direction: up | down | flat | mixed
severity: critical | high | medium | low   # 由阈值 + 金额池规则推导，非文案
claim_kind: measurement | comparison | composition | mechanism_hypothesis
descriptive_confidence: high | medium | low | not_judgable
action_license: execute | pilot | observe | blocked
# execute=可执行；pilot=可试点；observe=仅观察；blocked=数据不足
evidence_fact_ids: [...]
evidence_table_ids: [...]
confounders: [...]
next_data_needed: [...]
```

**Epistemics 统一政策（取代互打标签）：**

| claim_kind | descriptive 可高？ | action_license 上限 |
|---|---|---|
| measurement / composition | 是（大样本） | execute（若可行动且无缺口） |
| comparison（有对照/重复） | 是 | execute 或 pilot |
| mechanism_hypothesis | 是（数字准） | **pilot 封顶**（无对照不得 execute） |
| 缺关键分母/表 | not_judgable | blocked |

呈现只允许这两种读者标签：

- **描述置信：** 高/中/低/暂不下定论
- **行动许可：** 可执行/可试点/仅观察/先补数据

禁止再并行输出「证据强」与「置信度高」两套互相矛盾的主标签。
内部仍保留 `EvidenceStrength` 供统计与 gate 使用，但必须经 `action_license` 投影后才能上屏。

### 3.4 `ActionCard`（行动一等公民）

```yaml
action_id: act.pre_ship_refund.triage
action_family: pre_ship_refund          # 去重键
title: 发货前退款原因分拣与拦截
owner_role: 售后负责人                   # 角色，非人名
cadence_label: 本期                      # 由 AnalysisContext 渲染
steps:
  - 导出本期发货前退款订单
  - 按原因码分拣 Top3
  - 对 Top1 上拦截话术/时效承诺
primary_metric: refund.pre_ship_rate
guardrail_metric: shop.avg_daily_pay_conversion_uv
observe_window_days: 14
stop_rule: 若发货前率下降但整体 GMV 下滑>X% 且转化同步恶化，则暂停并回滚话术
impact_hypothesis:
  kind: pool_fraction                   # pool_fraction | rate_delta_to_gmv | qualitative
  pool_metric: shop.refund_amount
  conservative_note: 仅标池子大小，不承诺回收率
  optimistic_bound: null                # 仅当 money.py 规则允许
signal_ids: [refund.pre_ship_amount_share]
license: pilot | execute
```

**硬规则：**

- 进入「本期行动」区的卡片必须含：`owner_role, steps, primary_metric, stop_rule, license`。
- 仅有 `recommended_action: str` 的旧 Finding → 可进「参考建议」，不得进 Top 行动。
- 同 `action_family` 多信号合并为一张卡，子步骤可并列，优先级表不得占多行。

### 3.5 `Lever` 与 `DecisionBrief`

```yaml
lever_id: lever.conversion_drag
problem: 流量托住 GMV，转化抵消增量
spine_position: 1
signals: [...]
primary_visual: view_spec_id | null     # 每杠杆最多 1 主视觉
detail_table: table_id | null
action_cards: [...]
evidence_pack_id: ev.conversion_drag    # 指向事实层锚点
```

```yaml
DecisionBrief:
  report_name: ...
  shop_name: ...
  context: AnalysisContext
  headline: ...
  spine: [lever_ids ordered]
  kpi_snapshot: [metric_id...]          # 仅 registry 白名单
  levers: [Lever...]                    # 默认 3–5
  open_questions: [...]                 # 业务语言
  data_gaps: [{ missing, unlocks_decision }]
  content_templates: [...]              # 可实例化到本店实体
  module_dump_ref: facts_hash           # 全量模块仅作证据库
```

---

## 4. 双产品职责合同

| 维度 | 叙事版 | 事实层 |
|---|---|---|
| 主对象 | DecisionBrief | Evidence packs + 全量 Signals |
| 读者问题 | 先做什么、为什么、怎么验收 | 数字从哪来、是否可信、明细是什么 |
| 图表 | 每杠杆 ≤1 主图 + 必要明细（可折） | 模块级图表/全表，默认可展开 |
| 口径 | 首屏 KPI 字典 5–8 条 | 完整口径附录 |
| 行动 | 完整 ActionCard 排期 | 信号级 suggested action（可链到叙事卡） |
| 缺口 | 业务后果导向 | 表/字段导向 |
| 禁止 | 全量模块 dump、重复表图堆叠 | 英文化导航、伪周报口吻、决策主故事与叙事分叉 |

**深链：** 叙事 `evidence_pack_id` → 事实层 `id="ev-..."`。
**一致性：** 两边 KPI 必须来自同一 `metric_id` 集合；gate 交叉校验。

---

## 5. 流水线改造

### 5.1 目标流水线

```text
build/import
  → run modules (L1)  -- emit Finding + Signal (Signal 可渐进)
  → compile FactBook (L2)  -- metric_id 必填, context 写入
  → compile DecisionBrief (L2.5, Python)  -- 确定性杠杆/行动/去重
  → narrative DAG (L3)
        seed/fan/synth 只编辑 brief 的叙事投影（仍禁止裸数字）
        gate: 数字绑定 + 决策完整性 + 口径/时间/许可
  → render
        narrative.html ← DecisionBrief 主视图
        fact.html      ← Evidence 视图（可用同一 brief 的 pack 索引）
```

### 5.2 L2.5 `compile_decision_brief`（新，确定性）

输入：`FactBook` + `list[AnalysisResult]` + `AnalysisContext`
输出：`decision_brief.json`

确定性步骤：

1. 收集 Signals（从 Finding 适配器或原生字段）。
2. 按 `action_family` / 业务规则聚类为 Levers。
3. 影响排序：`money_pool × severity × action_license_weight × non_overlap`
   - 替换纯 `LEVER_WEIGHTS[module_id]` 作为主排序（权重可留作 tie-break）。
4. 生成/合并 ActionCards；不完整卡降级到 reference。
5. 选择每杠杆 primary visual 候选（表 id + 推荐 template），供 L3 review 裁剪，不得无 claim 堆图。
6. 写出 `kpi_snapshot`、`data_gaps`、`open_questions`。

**原则：** 杠杆排序与行动许可是 Python 的职责，不是 agent 的创意。

### 5.3 L3 gate 扩面（决策完整性）

在现有 HARD（裸数字/token/视图）之上新增：

| 代码 | 含义 |
|---|---|
| `METRIC_ID_UNKNOWN` | fact/claim 引用未注册 metric |
| `METRIC_ALIAS_COLLISION` | 同展示名多 metric 或禁用别名 |
| `PERIOD_UNBOUND` | claim/action 无 analysis/comparison 上下文 |
| `LICENSE_OVERCLAIM` | mechanism 被标 execute / 描述低却强处方 |
| `ACTION_INCOMPLETE` | Top 行动缺 steps/metric/stop_rule |
| `ACTION_FAMILY_DUP` | 同 family 占多条优先级 |
| `SPINE_PROMISE_UNFULFILLED` | 首屏/导语提到的实体清单无对应 view/table |
| `CROSS_REPORT_KPI_DRIFT` | 叙事 KPI 与事实层 KPI metric_id 集合不一致 |
| `PROXY_LABEL_ABUSE` | proxy 指标使用财务禁词 |

WARN（不阻断，但进 telemetry）：`VIEW_REDUNDANT_PAIR`（同数据表+同型图重复）、`BOILERPLATE_CAVEAT_FLOOD`。

### 5.4 叙事 agent 的权限收缩

Agent **可以**：选 lever 叙述顺序（在 brief 已排序的 Top-N 内微调）、写连接词、选 view_spec 列/TopN、实例化内容模板占位。
Agent **不可以**：发明 metric 含义、改 action_license、写影响金额、创建未在 brief 的杠杆、把 observe 写成 execute。

`shared_spine_facts` 不得为空当 KPI 存在；seed 必须注入 context 与 brief spine。

### 5.5 策展 review 不得空跑

若 `DecisionBrief.levers` 含 visual 候选而 `_reviews` 为空，finalize 前应：

- 走确定性默认 view（每杠杆 1 表或 1 图），或
- 标记 `degradation_reason=review_skipped` 并限制视觉数量。

禁止「无 review 却堆满 auto 图」的静默成功。

---

## 6. 指标注册表 — 首批必须消歧的冲突簇

完整注册表见 `references/metrics/registry.yaml`。下列冲突必须在 Phase 1 消解：

### 6.1 加购→支付

| metric_id | 含义 | 旧 key |
|---|---|---|
| `shop.avg_daily_cart_to_pay_ratio` | 有效日逐日支付买家 / 加购人数后取均值（非严格漏斗） | `demand_funnel_diagnosis.avg_daily_cart_to_pay` |
| `sku.cart_to_pay_line` | SKU 池加购到支付（SKU 表聚合） | `sku_structure_diagnosis.overall_cart_to_pay` |

叙事首屏默认只允许 `shop.avg_daily_cart_to_pay_ratio`。
禁止笼统写「加购到支付」而不带 registry `display_name`。

### 6.2 退款率簇

| metric_id | 含义 |
|---|---|
| `shop.refund_amount_rate` | 退款金额 / 支付金额 |
| `shop.refund_order_rate` | 退款订单 / 支付订单 |
| `carrier.note_refund_rate` / `carrier.card_refund_rate` | 载体订单退款率 |
| `refund.pre_ship_order_rate` / `refund.post_ship_order_rate` | 发货前/后订单率 |
| `refund.pre_ship_amount_share` | 发货前金额占退款金额份额（构成，非与上者相加） |

`refund.return_amount_share` 与 pre/post 不得无警告并置为可加总 100% 条形图，除非 ledger 声明同一构成分解。

### 6.3 甜点 proxy

| metric_id | display_name | 禁词 |
|---|---|---|
| `price.sweet_net_yield` | 甜点带净收益（转化−退款） | 净利率、利润率、margin%（财务义） |

旧 key：`sku_structure_diagnosis.sweet_net_margin` → 迁移改名，避免 `margin` 误读。

### 6.4 GMV 桥

| metric_id | 要求 |
|---|---|
| `bridge.delta_gmv` | 必须绑定 `comparison_window` |
| `bridge.contrib_traffic/conversion/aov` | unit=cny；claim_kind=composition 或 mechanism_hypothesis；license≤pilot |

---

## 7. 分阶段落地（可实施顺序）

### Phase 1a — 语义地基（验证态，当前）

**代码/契约：**

- 新增 `references/metrics/registry.yaml` + loader `xhs_ceramics_analytics/contracts/metrics.py`
- loader 仅做结构/口径校验，`runtime_consumed: false`
- daily primitive、逐日去重人次、日均值、逐日比率均值分别注册
- source / repo bundle / installed Skill 保持同版

**验收：**

- registry 严格 loader、非可加语义、bundle parity 测试通过
- importer / coverage / facts / reports 均未导入 loader
- 店铺日均加购→支付比与 SKU 池指标不得使用同一 display_name

### Phase 1b — 语义运行时接入（后续独立评审）

**代码/契约：**

- 扩展 `Fact`：`metric_id`, `window_role`, `period_start`, `period_end` 必填策略
- `facts_export` 经 registry 渲染 `display_name`；proxy 禁词检查
- 统一 reader 标签投影：`reporting/epistemics.py`（描述置信 + 行动许可）
- 事实层/叙事层 pill 共用投影；删除互斥主标签
- gate：`METRIC_*`, `PROXY_LABEL_ABUSE`, `PERIOD_UNBOUND`（最小集）

**验收：**

- 单测：日均店铺比与 SKU 池比不得被同一 display 输出
- 单测：sweet 指标渲染不含「净利率」
- 同一 bridge fact 在事实层与叙事层 action_license 一致
- PiGoo facts.json 再导出后 `caliber/metric_id` 非空率 ≥ 核心 30 指标的 100%

### Phase 2 — 决策编译（落地）

- `ActionCard` + `DecisionBrief` schema（`orchestration/schemas/`）
- `compile_decision_brief.py` 确定性编译
- `Finding.recommended_action` 适配器；完整卡才进 Top
- priority 主排序改为 impact pool；`action_family` 去重
- gate：`ACTION_*`, `LICENSE_OVERCLAIM`, `SPINE_PROMISE_UNFULFILLED`
- 文案模板按 cadence 生成（消灭硬编码本周）

**验收：**

- Top≤5 行动 100% 含 steps/primary_metric/stop_rule/owner_role
- 发货前退款只占 1 个 family
- 首屏承诺「20 个流失词」则必须有对应 table/view，否则 HARD fail

### Phase 3 — 双产品矩阵（去内耗）

- 叙事 renderer 改为消费 DecisionBrief
- 事实层 renderer 改为 Evidence pack 索引 + 全量可折明细
- 深链 id 对齐
- `CROSS_REPORT_KPI_DRIFT` 接入 CI

**验收：**

- 叙事不再全量模块平铺；事实层不再承担首屏决策主故事
- 两份 KPI metric_id 集合相等

### Phase 4 — 呈现层（仅在 1–3 后）

- 全局一次因果免责 + 卡片级差异化 caveat
- 决策实体清单默认 Top15 可展开，非决策宽表默认折叠
- 图：标题必填、正负分色、异常日标记、唯一 pattern id
- 中文导航、print CSS、sticky KPI

**验收：** 观感问题不再以破坏契约的方式「修掉」。

---

## 8. 文件级影响图（实施导航）

| 区域 | 文件 | 动作 |
|---|---|---|
| 契约 | `references/metrics/registry.yaml` | 新增 |
| 契约 | `references/metric_definitions.md` | 改为 registry 的人读摘要或生成物 |
| 契约 | `references/evidence_strength.md` | 扩展 action_license 政策 |
| 契约 | `references/report_contract.md` | 改为 DecisionBrief 合同 |
| Schema | `orchestration/schemas/fact.json` | 加 metric_id/period |
| Schema | `orchestration/schemas/claim.json` | confidence 投影字段；metric_id |
| Schema | `orchestration/schemas/decision_brief.json` | 新增 |
| Schema | `orchestration/schemas/action_card.json` | 新增 |
| 代码 | `contracts/metrics.py` | 新增 loader/校验 |
| 代码 | `reporting/facts_export.py` | metric_id + period |
| 代码 | `reporting/epistemics.py` | 新增统一投影 |
| 代码 | `reporting/confidence.py` | 委托 epistemics 或瘦身 |
| 代码 | `reporting/priority.py` | impact + family 去重 |
| 代码 | `reporting/decision_compile.py` | 新增 L2.5 |
| 代码 | `reporting/factcheck_gate.py` | 决策完整性规则 |
| 代码 | `reporting/narrative_render.py` / `html.py` | 消费 brief；双产品职责 |
| 代码 | `analysis/result.py` | Signal/Action 字段扩展（渐进） |
| 代码 | `analysis/*.py` | 逐步挂 metric_id；改 cadence 文案 |
| 测试 | `tests/contracts/`, `tests/reporting/` | 口径冲突、许可、行动完整性、双报 KPI |

---

## 9. 迁移策略

1. **双写期：** Finding.key_numbers 仍用旧 local key，export 时经 `legacy_keys` 映射 metric_id。
2. **门禁期：** CI 对核心 metric 集合 fail-on-unmapped。
3. **收紧期：** 禁止新模块使用未注册 key；旧 key 仅 alias。
4. **叙事缓存：** `narrative_schema_version` 纳入 registry hash + epistemics policy hash，避免旧 bundle 误命中。

---

## 10. 用 PiGoo 样例做回归断言（设计验收场景）

实现后对同一数据重跑，应满足：

1. 首屏只出现一个加购→支付指标，且为 `shop.avg_daily_cart_to_pay_ratio`（按有效日逐日比率取均值），SKU 池指标仅出现在商品章并带不同 display_name。
2. GMV 桥可见「对比窗：2026-04 vs 2026-06」；Δ¥3,256 与贡献项同时出现；license=可试点。
3. 退款主杠杆一张卡：发货前金额份额 61.9% + 订单率 9.8% 分列，不在同一可加总图里装成 100%+退货。
4. `price.sweet_net_yield` 文案为净收益/转化减退款，无净利率。
5. 叙事行动 ≥3 张完整 ActionCard；与优先级 family 对齐。
6. 搜索流失词/高退款 SKU 若在 spine 或导语出现，正文必有表。
7. 事实层与叙事层 KPI 集合一致；事实层保留全量明细证据包。

---

## 11. 决策记录（ADR）

**采纳：** 以 DecisionBrief 为报告中段编译目标；Metric Registry + Period Context + Epistemics 投影 + ActionCard 为强制契约。

**拒绝：**

- 仅扩大 curated view 数量「显得更专业」
- 仅用 prompt 约束 agent 不写冲突口径
- 保留「证据强/置信度高」双主标签并行上屏
- 继续用 module lever 权重作为唯一优先级

**后果：**

- 短期：模块改造与测试量上升
- 中期：报告变短、决策变硬、跨店口径稳定
- 长期：新分析模块接入成本下降（先挂 metric/signal，再自动进 brief）

---

## 12. 开放问题（实现前需拍板）

1. `owner_role` 是否允许店铺自定义字典，还是固定枚举（运营/内容/售后/商品）？
2. 影响估算是否在 Phase 2 只做「池子暴露」不做乐观回收，以避免过度承诺？
3. 事实层是否保留独立「优先级导读」，还是统一改为「指向叙事 DecisionBrief 的索引」？

**建议默认：**
1=固定枚举+可扩展；2=Phase 2 仅池子暴露+定性方向；3=事实层保留信号优先级，但主行动以叙事 ActionCard 为准并深链。

---

## 13. 完成定义（Definition of Done）

本 ADR 落地完成，当且仅当：

- [ ] registry 覆盖核心冲突簇 + loader 测试通过
- [ ] Fact export 核心指标 100% 带 metric_id 与 period
- [ ] epistemics 投影单测覆盖 mechanism 封顶
- [ ] DecisionBrief 可对 PiGoo 数据确定性生成
- [ ] 叙事 gate 决策完整性规则上线
- [ ] 双 HTML 职责符合 §4，并过 §10 回归断言
- [ ] 旧「本周」硬编码从 analysis 模板主路径移除（按 cadence 渲染）
