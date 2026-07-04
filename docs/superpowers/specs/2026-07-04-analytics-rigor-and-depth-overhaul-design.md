# 统计严谨性与挖掘深度二期重构 — 设计规格

**日期:** 2026-07-04
**目标:** 把报告从"统计诚实的观察性描述"升级为"可决策的诊断洞察"——在**设计源头**修正时序/统计方法层的硬伤(方向误判、季节性污染、周桶错位、跨时间混杂、单变点),并新增一批**共享分析原语**(GMV 归因桥、集中度、分布、文本挖掘、基准、弹性),让上层所有模块自动继承,而非逐模块打补丁。

## 设计哲学(为什么这样分层)

一期(`2026-07-03-analytics-depth-overhaul`)修了两处 bug、加了 FDR/时序分解、新增诊断模块。二期复核发现:**问题的根不在各模块,而在它们共用的 `analytics/` 原语层**。因此本次的第一性原则:

> **凡是多个模块共享的计算逻辑,修在 `analytics/` 源头,一次修复全线继承。凡是新能力,先落成可独立测试的原语,再由模块消费。绝不在模块内私改共享语义(那是补丁)。**

三层结构:

1. **地基层 `analytics/`(Phase 1)** — 纯函数、无 I/O、never-raise、全 TDD。所有统计/分解逻辑的唯一真源。
2. **布线层 `analysis/*`(Phase 2–4)** — 模块只做"取数 → 调原语 → 组装 Finding",不含统计实现。
3. **表达层 `reporting/*`** — 既有渲染层,新增 key_numbers/表自动继承。

## 全局约束(Global Constraints)

- 解释器:`.venv/bin/python`(裸 `python` 不存在;zsh 无 `mapfile`)。
- 模块契约:`def run(db_path) -> AnalysisResult`;**绝不 raise**;缺表/列优雅降级并记 `limitations`;每个 `Finding` 带 `confounders` + 观察性 `caveats`;观察性证据经 `score_evidence(...)` 封顶 WEAK,描述精度另经 `score_reliability(...)`。
- 原语层:纯 stdlib(`math`/`datetime`/`collections`),**不得引入 numpy/scipy/pandas**(与既有 `analytics/` 一致,保持零重依赖、可镜像)。
- 原语 never-raise:脏输入(空、None、除零、k>n、日期不可解析)一律降级到安全空值,绝不抛异常。
- HTML 报告硬约束不变:无 `<script>`/`http(s)`/`src=`/`linear-gradient`/`Lucide`;SVG 图标无 `xmlns`。
- 提交:**无 Co-Authored-By**(全局关闭);commit/push 仅在用户明确要求时。
- ruff line-length=100。TDD:先写失败测试(RED)→ 最小实现(GREEN)→ 重构。
- 真实数据量级参考(非硬编码断言):`business_overview_daily` ≈ 91 日;`sku_performance` 5250 行含 `category_l1/l2`+价格带;`notes` 1272 篇零膨胀;`comments` 若干。

---

# Phase 1 — 地基层:共享分析原语(设计源头)

## A1. 趋势方向的显著性门控 — `analytics/trends.py`

**问题:** `trend_summary` 的 OLS 斜率只要非零,`direction_label` 就判"上升/下降"(阈值仅 `_EPS`)。日度序列噪声大,持平序列被误判有向。

**设计(源头修复,所有消费者继承):**
- `trend_summary` 增算残差:拟合 `ŷ_i = a + b·i`,残差标准差 `s`,斜率标准误 `SE(b) = s / sqrt(Σ(i-x̄)²)`,`t = b / SE(b)`。
- 返回字段新增 `slope_se`、`t_stat`、`significant`(`abs(t) >= 2.0`,n≥3 时;n<3 退化 `significant=False`)、`rel_slope`(`b·(n-1)/mean_y`,整段相对变化,量纲无关)。
- 新增 `direction_from_summary(summary) -> str`:`significant` 才给"上升/下降",否则"趋势不明"。`direction_label(delta)` 保留给纯环比增量场景(语义不同,不动)。
- `trend_summary` 的 `direction` 字段改用显著性门控结果;**向后兼容**:字段名不变,消费者无需改签名,只是"上升/下降"更保守。

**测试:** 纯噪声序列 → `significant=False`、`direction="趋势不明"`;强线性 → `significant=True`、方向正确;n<3 → 不 raise、`significant=False`。

## A2. 去趋势的周内节律 — `analytics/timeseries.py`

**问题:** `dow_seasonality` 在**原始水平**上按 weekday 求均值;整体上行时靠后的星期几天然偏高,"周六最高"可能只是趋势伪影。

**设计:** 先对序列去趋势(减 OLS 拟合值或 7 日中心移动均值,取残差),再按 weekday 求**残差均值**。返回结构不变(`by_weekday`/`peak_dow`/`trough_dow`),但语义改为"控制趋势后哪个星期几系统性偏高/偏低";另返回 `detrended=True` 标志供 caveat 使用。序列过短(<14)无法可靠去趋势 → 退回原始水平并标 `detrended=False`。

**测试:** 构造"上行趋势 + 周三固定抬升"序列,断言去趋势后 `peak_dow="周三"`(未去趋势会误判为周末);短序列降级不 raise。

## A3. 日历对齐的周桶 — `analytics/timeseries.py`

**问题:** `week_over_week` 按**行数**每 7 行切桶,缺日就漂移,桶不是周一–周日,WoW 对比失真。

**设计:** 用 `_parse_date` 把每点落到其 ISO 周(`date.isocalendar()[:2]` → `(year, week)`),按真实周分组求和;缺日的周照常成桶(标 `days_in_bucket`),日期不可解析的点落入 `None` 组并计 `limitations`。返回字段增 `iso_year`/`iso_week`/`days_in_bucket`,保留 `week_start`/`week_end`/`total`/`delta`/`pct`/`direction`。无任何可解析日期 → 退回行数切桶(保持兼容)并标 `calendar_aligned=False`。

**测试:** 含缺失日的 21 天序列,断言桶按周一–周日边界、`days_in_bucket` 正确反映缺日;全不可解析 → 行数切桶降级。

## A4. 分层两比例(控时间混杂)— `analytics/confidence.py`

**问题:** `two_proportion` 跨全窗池化比较渠道/客群 A vs B,若两组投放/流量节奏不同期,差异被时间混杂。

**设计(新增,不改旧函数):** `stratified_two_proportion(strata)`,入参为分层列表 `[{k1,n1,k2,n2}, ...]`(每层如一周)。用 **Cochran–Mantel–Haenszel**:
- CMH 统计量 `χ²_CMH = (|Σ(a_i - E_i)| - 0.5)² / Σ V_i`,其中 `a_i=k1_i`,`E_i = n1_i·m1_i/T_i`,`V_i = n1_i·n2_i·m1_i·m2_i / (T_i²·(T_i-1))`。
- 返回 `{pooled_diff, mh_chi2, significant(χ²≥3.841), n_strata, ci_overlap}`;任一层退化(T_i≤1)跳过该层;有效层<1 → 全 None、`significant=False`。
- 旧 `two_proportion` 保留;模块**在有可分层维度(如日期→周)时优先调分层版**,并在 caveat 注明"已按周分层控时间混杂"。

**测试:** 构造"整体看 A>B 但每层 A≈B"的辛普森反转 fixture,断言分层后 `significant=False`(未分层会误显著);单层退化不 raise。

## A5. 多变点(递归二分)— `analytics/timeseries.py`

**问题:** `changepoint` 只返回单个最大均值跳变;91 天可能多段结构变化,且变点无强度参照。

**设计(新增,旧 `changepoint` 保留供单变点消费者):** `changepoints(values, min_segment=3, max_k=3, min_rel_shift=0.15)`:
- 递归 binary segmentation:在整段找最大 `|Δmean|` 分割,若 `|Δmean| / (整体均值 or 残差尺度) >= min_rel_shift` 则接受,对左右子段递归,直至 `max_k` 个或不再显著。
- 返回 `[{index, date_index, before_mean, after_mean, shift, rel_shift}, ...]` 按位置排序。
- never-raise:短序列/常数序列 → `[]`。

**测试:** 双台阶序列(升-平-降)→ 返回 2 个变点位置正确;常数 → `[]`;单调噪声 → 不超过 `max_k`。

## A6. 相对提升带 CI + 最小可测效应 — `analytics/confidence.py`

**问题:** 两比例只报原始差值 `diff`,无相对提升、无 MDE,"不显著"分不清是"真无差"还是"样本不够"。

**设计(新增):**
- `relative_lift(k1,n1,k2,n2) -> {lift, lift_ci_low, lift_ci_high}`:`lift = p1/p2 - 1`;CI 用两比例 Wilson 端点组合的保守区间(`p1_lo/p2_hi - 1` … `p1_hi/p2_lo - 1`)。除零/退化 → None。
- `min_detectable_effect(n1, n2, p_base, power=0.8, alpha=0.05) -> float|None`:双比例检验在给定样本量下、80% power、绝对基线 `p_base` 时最小可测的绝对差 `MDE = (z_α/2 + z_β)·sqrt(p̄(1-p̄)(1/n1+1/n2))` 的近似(`z` 常量硬编码 1.96/0.84)。用于给"不显著"标注"本样本量最小可测 X pp"。
- 两比例消费者的 caveat 增一行 MDE。

**测试:** 已知 lift 场景断言 `lift` 与区间包含真值;`min_detectable_effect` 随 n 增大而减小、退化输入 → None。

## A7. 分布与双峰 — `analytics/distribution.py`(新文件)

**问题:** 客单价只报均值,掩盖陶瓷"引流小件 + 礼品大件"双峰。

**设计:** 纯 stdlib:
- `quantiles(values, qs=(0.25,0.5,0.75)) -> dict` — 线性插值分位。
- `describe(values) -> {n, mean, median, p25, p75, iqr, min, max, cv}`(`cv=std/mean` 离散度)。
- `histogram(values, bins) -> [{lo, hi, count, share}]` — 等宽或给定边界(价格带可传 `[0,50,100,200,∞]`)。
- `bimodality_coefficient(values) -> float|None` — Sarle's `b = (skew² + 1) / kurtosis`(样本修正);`b > 0.555` 提示双峰/多峰。空/常数 → None。

**测试:** 单峰正态样 `b<0.555`;双峰混合样 `b>0.555`;`describe` 分位正确、空输入全 None。

## B1. GMV 乘法归因桥 — `analytics/decomposition.py`(新文件)★最高价值

**问题:** GMV 变了,分不清是**流量 × 转化 × 客单**哪个杠杆驱动的。运营最想要的一张"为什么变"。

**设计(确定性分解,无因果风险):** GMV = 访客数 × 支付转化率 × 客单价。用 **LMDI(对数平均迪氏指数)** 把两期 ΔGMV **完全可加**地拆到三个因子:
```
ΔGMV = Σ_factor  L(GMV_t, GMV_0) · ln(factor_t / factor_0)
其中 L(a,b) = (a-b)/ln(a/b)  (a≠b), = a (a==b)
```
- `gmv_bridge(period_0, period_1) -> {delta_gmv, contrib_traffic, contrib_conversion, contrib_aov, residual, dominant_factor}`,三项贡献之和 == ΔGMV(residual≈0,仅浮点误差)。
- 入参为两期的 `{visitors, conversion, aov}` 或 `{gmv, visitors, buyers}`(内部反推 conversion/aov)。任一因子缺失/≤0 → 退化:能拆几个拆几个,其余进 `residual` 并标 `partial=True`。
- 提供 `gmv_bridge_series(periods)` 对相邻期链式分解(供趋势桥)。

**测试:** 构造已知三因子变化,断言三项贡献之和 == ΔGMV(容差 1e-6)、`dominant_factor` 正确;单因子缺失 → `partial=True` 不 raise;GMV 无变化 → 全 0。

## B5. 集中度单值与趋势 — `analytics/concentration.py`(新文件)

**问题:** 集中度只有帕累托头部占比,无单一可比数值、无时间趋势。

**设计:**
- `gini(values) -> float|None` — 洛伦兹基尼(0=均匀,1=极集中);负值/空 → None。
- `hhi(values) -> float|None` — 赫芬达尔(Σ share²,0–1)。
- `top_share(values, k_frac=0.2) -> float` — 头部 k 比例的份额(帕累托,保留)。
- `concentration_trend(period_to_values) -> [{period, gini, hhi}]` — 逐期集中度,供"越来越集中/分散"判断。

**测试:** 完全均匀 → gini≈0;单点垄断 → gini→1;已知分布对照值;空/单元素 → None/0 不 raise。

---

# Phase 2 — 布线:原语接入现有模块(不改契约)

- **core_business:** 新增 Finding「增长归因」调 `gmv_bridge_series`,一句话定位 ΔGMV 主因子;`_decompose_gmv` 的节律换 A2 去趋势版、周桶换 A3 日历版、变点换 A5 多变点(取最强 1–2 个);趋势方向继承 A1 显著性门控。AOV 增 `describe`+双峰 caveat。
- **sku_structure / note_commercial:** GMV 帕累托旁增 `gini`/`hhi` 单值 + `concentration_trend`(若有日期)。
- **channel_structure / audience_structure / core_business 渠道:** 两比例在有日期时优先 `stratified_two_proportion`(按周分层),caveat 注明;所有两比例 finding 增 `relative_lift` + MDE 注释。
- **sku_structure 价格带:** 用 `distribution.histogram` 统一价格带口径。

# Phase 3 — 深度:评论语义挖掘 `analytics/text_mining.py`(新文件)

- `emergent_themes(texts, seed_lexicon)`:中文 2–4 gram 共现统计(stdlib 正则切分,停用词表),按频次×文档覆盖率排序出**涌现主题**;固定 `_KEYWORDS` 降级为 `seed_lexicon` 只做冷启动兜底。
- `polarity(text, pos_lexicon, neg_lexicon) -> float` — 词典极性(陶瓷场景:好评词/差评词种子表),聚合到主题级正负比。
- `objection_to_hook(theme)` — 高频异议(色差/磕碰/尺寸/釉面/微波炉/洗碗机)→ 建议内容钩子映射表。
- `comment_demand.py` 消费上述,输出「涌现需求主题 + 频次趋势 + 异议→待补内容点」,证据仍观察性。

# Phase 4 — 运营视角

- **C1 基准带 `analytics/benchmark.py`:** 无外部行业数据 → 用账号**自身历史分位**做锚(`self_percentile(value, history)`),把"2% 转化"标注为"处于自身近 N 期的 P__ 分位",给相对好坏。
- **C2 发布节奏:** `account_baseline`/`note_funnel` 增 Finding:notes 按发布 weekday×时段 分组,对阅读/互动/带货求表现,输出最优发布窗口(去趋势 + min_n 守卫)。
- **C3 活动抬升:** 若有 `calendar_events`,core_business 增"活动期 vs 平销期 GMV/转化抬升"对比(两比例 + 效应量)。
- **C4 客户质量:** audience_structure 增新客/老客的 **GMV 贡献占比**与复购客集中度(非仅转化对比)。
- **C5 价格甜点:** sku_structure 增「价格带 × 转化 × 退款」三维表,标注"转化高且退款低"的甜点带。
- **C6 投放弹性:** paid_traffic 用 `spend→gmv` 的**边际 ROAS / 饱和曲线**(分位分箱看边际投产递减点)替代 `HIGH/LOW_ROAS_THRESHOLD` 硬阈值给预算再分配建议;阈值常量降级为兜底。

# Phase 5 — 收口 & 表达

- **D1 前瞻:** trend 桥外推 + 日度超 ±2σ 的异常日标记(观察性提示,非预测承诺)。
- **D2 总导读优先级表:** compositor 增一张跨模块「最弱环节 × 最高杠杆」优先级表(按预期影响×可行性排序),让读者一页看清先动哪。
- 全量 pytest + ruff clean + `sync-runtime` 镜像 + 真实千帆 export 重跑(零越界、零禁令 token、桥/集中度/主题正确渲染)。

## 分层依赖与执行顺序

```
Phase 1 (原语, 无依赖, 全 TDD)
   ├─ trends.A1 ─┐
   ├─ timeseries.A2/A3/A5 ─┤
   ├─ confidence.A4/A6 ─┤
   ├─ distribution.A7 ─┤→ Phase 2 布线 → Phase 4 运营
   ├─ decomposition.B1 ─┤
   └─ concentration.B5 ─┘
Phase 3 (text_mining, 独立, 可与 2 并行)
Phase 5 收口(依赖全部)
```

## 验收标准

1. 每个原语有独立 TDD 测试,覆盖正常 + 退化 + never-raise。
2. 现有模块契约不变(签名、never-raise、双轴证据),旧测试全绿。
3. 真实数据重跑:GMV 归因桥三项贡献可加、集中度单值合理、周内节律去趋势后稳定、涌现主题非空。
4. 报告 HTML 零禁令 token、零越界。
5. ruff clean;镜像与根一致。
