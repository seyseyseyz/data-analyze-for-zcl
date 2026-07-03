# 数据挖掘深度提升 — 设计规格 (Analytics Depth Overhaul)

**日期:** 2026-07-03
**目标:** 把报告从"描述性基线"升级为"诊断级挖掘"——修正已发现的两处计算错误、补齐统计严谨性(多重比较控制、时序分解)、并新增两个回答核心商业问题的模块,全部复用现有表、不需补数据。

## 背景与动机(专业数据分析师复核)

真实库(`/tmp/xhs-real-run`)复核后发现:现有模块是统计诚实的描述性基线,但存在 (a) 两处会产出**错误数字**的 bug,(b) 大量现成高价值字段未被利用,(c) 缺少多重比较控制与时序分解。本次一次性优化到位。

关键事实(真实数据,用于设计与测试断言的量级参考,非硬编码):
- `notes`: 1272 篇,仅 **315 篇(24.8%)有成交**,1148 篇有阅读 → 笔记转化是零膨胀分布。
- `sku_performance`: 5250 行(sku_id 全唯一),3405 个 GMV>0;含 `category_l1/l2`、`pre_ship_refund_rate_pay`、`post_ship_refund_rate_pay`、`aov`。
- `business_overview_daily`: 商卡 GMV 占 **64.5%** > 笔记 36%;发货前退款率 9.7% > 发货后 6.0%,总退款 15.7%;含 note/card 的 gmv/orders/buyers/refund 全套拆分列。
- `shop_page_funnel`: 行 = {全部/全部, 新客/180天, 新客/365天, 老客/180天, 老客/365天} → **含 `全部` 汇总行 + 180天/365天 累计窗口重叠**。

## 全局约束(Global Constraints)

- 解释器:`.venv/bin/python`(裸 `python` 不存在)。
- 模块契约(镜像 `audience_structure.py`):`def run(db_path) -> AnalysisResult`;**绝不 raise**;`_table_exists`/`_table_columns`/`_fetch_all`/`_num` 守卫;缺必需表 → `_missing_result`;每个 `Finding` 带 `confounders` + 观察性 `caveats`;证据经 `score_evidence(n, has_controls=False, confounder_count)` → 观察性封顶 WEAK;比例检验用 `two_proportion`、区间用 `wilson_interval`、小样本守卫 `min_n_guard`、比率归一 `bounded_rate`。
- 通用可兼容:任意列/表缺失都优雅降级并记 `limitations`,不得因脏数据崩溃。
- 提交:**无 Co-Authored-By trailer**(全局关闭署名)。
- ruff line-length=100。TDD:先写失败测试。

---

## 工作项 A — 修正计算错误(最高优先级)

### A1. `audience_structure` 汇总行双计 bug

**问题:** `_conversion_finding`/`_cycle_finding` 直接对 `shop_page_funnel` 全表按 `audience_type`/`first_purchase_cycle` 聚合,把 `全部` 汇总行(= 新客+老客)与 180天/365天**重叠累计窗口**一起 SUM。结果:新客访客被 180天+365天 双计(14920+14470),且 top-2 对比会拿"新客 vs 全部"(全部含新客),对比无意义。

**修复:**
1. 新增内部行过滤 `_partition_rows(rows)`:排除 `audience_type == '全部'` 与 `first_purchase_cycle == '全部'`;对首购周期,只保留**单一规范窗口**(present 中取最长,如 `365天`),避免累计窗口重叠双计。记 `limitations`("首购周期含累计窗口,人群对比固定取 <window> 避免重复计数")。
2. 人群转化对比在过滤后的 {新客, 老客} 上做 `two_proportion`(不再混入全部)。
3. 首购周期漏斗:在过滤后逐窗口报告,但**明确周期是累计窗口**的口径 caveat。
4. **新增留存指标**(在 Finding 1 的 key_numbers + 结论):
   - `new_customer_dependence` = 新客 payers / (新客+老客 payers) — 新客依赖度。
   - `repeat_conversion_premium` = 老客转化 / 新客转化 - 1 — 老客转化溢价。
   结论追加:"新客贡献 X% 付费、老客转化为新客的 Y 倍"。

**测试(`tests/test_audience_structure.py` 增量):**
- 构造含 `全部` 行 + 180/365 重叠的 fixture,断言参与对比的 visitors **不含**全部行、且不把 180+365 相加(新客 visitors == 单窗口值,非两窗口之和)。
- 断言 `new_customer_dependence` 与 `repeat_conversion_premium` 出现在 key_numbers 且数值方向正确(老客转化>新客 → premium>0)。

### A2. `note_commercial` 转化零膨胀退化 bug

**问题:** `_conversion_finding` 对全部 1272 篇(75% 零成交)算 `conversion=成交/阅读`,中位数=0;"高曝光低转化"判据 `conversion < median(=0)` 永远为空 → 该 finding 恒定产出"0 篇",无效。

**修复:**
1. **披露零膨胀**:key_numbers 增 `notes_with_orders`、`converting_share`(= 有成交笔记 / 有阅读笔记);结论前置"仅 X% 笔记产生成交"。
2. **转化分布只在有阅读的子集上算**,并用**正基线**:baseline = Σ成交 / Σ阅读(加权整体转化率)。"高曝光低转化" 重定义为:阅读处于前 25% 分位 **且** 转化 < 该正基线(用 `wilson_interval` 上界 < baseline 守卫,避免小样本误报),不再用恒为 0 的中位数。
3. caveat 说明零膨胀与新判据。

**测试:** fixture 大量零成交笔记 + 少数高阅读低转化笔记,断言 `converting_share` 正确、`high_traffic_low_conv_count > 0` 且命中预期笔记。

---

## 工作项 B — 统计严谨性基建

### B1. `analytics/multiplicity.py` — Benjamini-Hochberg FDR

扫描成百上千个 item 找"高于基线"必然产生假阳性。新增:

```python
def benjamini_hochberg(pvalues: list[float], alpha: float = 0.05) -> list[bool]:
    """返回每个 p 值是否在 BH-FDR alpha 下显著(顺序与输入一致)。空/全 None 安全返回全 False。"""

def expected_false_positives(n_tests: int, alpha: float) -> float:
    """n_tests × alpha,用于报告"预计假阳性约 N 个"。"""

def one_sided_binomial_p(k: float, n: float, p0: float) -> float:
    """单侧二项检验 p 值:观测 k 次成功/n 试验,H0 比例 p0,H1: 观测率 > p0。
    用正态近似(n 大)守卫,n<=0 或 p0 越界安全返回 1.0。"""
```

用于 note/sku 退款异常:对每个候选 item 算"退款率 > 基线"的单侧 p,经 BH 过滤,只保留 FDR 存活项;结论报告"N 个显著(BH-FDR 5%,预计假阳性约 M 个)"。

**测试(`tests/test_analytics_multiplicity.py`):** 已知 p 值序列验证 BH 存活集(对照教科书例);全 1.0 → 全 False;空 → 空;`one_sided_binomial_p` 单调性(k↑→p↓)。

### B2. `analytics/timeseries.py` — 时序分解

91 个日度点足够做的分解,替换 core_business 现有"首尾方向":

```python
def week_over_week(series: list[tuple[str, float]]) -> list[dict]:
    """按 7 天桶聚合,返回每周合计 + 环比 delta/pct/direction。"""

def dow_seasonality(series: list[tuple[str, float]]) -> dict:
    """按星期(date 解析 weekday)分组均值,返回 {weekday: mean} + peak_dow + trough_dow。
    date 无法解析时安全返回空。"""

def changepoint(values: list[float]) -> dict:
    """最大均值漂移变点:找使前后段均值差绝对值最大的切分点,返回 {index, before_mean, after_mean, shift}。
    少于 4 点返回 {index: None}。纯 stdlib,无 numpy。"""
```

**测试(`tests/test_analytics_timeseries.py`):** 已知周分桶合计;工作日高/周末低的合成序列 → peak/trough 正确;阶跃序列 → changepoint index 命中阶跃位置。

---

## 工作项 C — 新增深度模块

### C1. `channel_structure_diagnosis` — 渠道健康诊断(商卡 vs 笔记)

**必需表:** `business_overview_daily`。**TASK_ID** `channel_structure_diagnosis`,**TITLE** `渠道结构与健康诊断`。

与 `core_business` 的分工:core_business 报 GMV/订单**份额快照**;本模块报两渠道的**健康对比**(转化、客单、退款、发货前后),回答"钱主要从哪个渠道来、哪个渠道更健康"。docstring 交叉引用。

**Findings:**
1. **渠道收入与规模对比**(always):note vs card 的 GMV、net_gmv(退款后)、orders、buyers、GMV 占比。结论点明主渠道及其占比(真实约商卡 64.5%)。表 `channel_scale`。
2. **渠道转化与客单对比**(gated on buyers/visitors 或 conversion 列):note vs card 支付转化率(优先真实计数 `笔记支付买家数`/`笔记商品访客数` 等,缺则用 `笔记支付转化率`/`商卡支付转化率` 列均值)、客单价(`笔记客单价`/`商卡客单价`)。转化差异用 `two_proportion`(有真实计数时),效应量门槛 gating。表 `channel_conversion`。
3. **渠道退款健康**(gated on refund_rate 列):note vs card 的 `refund_rate_pay`、发货前/后退款率(若 `笔记发货前退款率_支付时间` 等列在)。two_proportion 比较两渠道退款率(用退款单/成交单真实计数优先)。指出更高退款的渠道与发货前后主导。表 `channel_refund`。

**降级:** 缺 note/card 拆分列 → 相应 finding 记 limitation 并 NOT_JUDGABLE 或跳过;必需表缺 → `_missing_result`。

### C2. `refund_root_cause_diagnosis` — 退款根因诊断

**必需表:** `sku_performance`(主),`business_overview_daily`(补发货前后大盘)。**TASK_ID** `refund_root_cause_diagnosis`,**TITLE** `退款根因诊断`。

与 `refund_structure_diagnosis`(载体/层级/时间,基于 refund_overview)和 `sku_structure`(SKU 帕累托 + 高退款 SKU 清单)的分工:本模块做**归因分解**——按发货阶段、品类树、价格带拆解退款率,回答"退款主要出在哪个环节/品类/价位"。

**Findings:**
1. **发货前 vs 发货后分解**(gated):优先 `business_overview_daily` 的 `pre_ship_refund_rate_pay`/`post_ship_refund_rate_pay` 大盘均值(加权),否则 `sku_performance` 同名列聚合。指出主导阶段(真实:发货前 9.7% > 发货后 6.0%)与对应杠杆(发货前=物流/时效/悔单/价保;发货后=质量/描述不符)。表 `refund_by_ship_stage`。
2. **品类树退款分解**(gated on `category_l1`+refund):按 `category_l1`(有 l2 则二级)聚合退款率,用真实计数(Σ退款单/Σ成交单)+ `wilson_interval` 守卫,`min_n_guard` 过滤小样本,BH-FDR 标记显著高于大盘的品类。指出最高退款品类。表 `refund_by_category`。
3. **价格带退款分解**(gated on `aov`+refund):按 aov 分位数分 4 档价格带(用现有值分位,非硬编码阈值),报各带退款率与 GMV 占比,指出高退款价格带。表 `refund_by_price_band`。

**降级:** 各 finding 独立 gated;`sku_performance` 缺 → `_missing_result`。

---

## 工作项 D — 增强现有模块

### D1. `search_efficiency` — 点击漏损 vs 转化漏损拆分

**问题:** `_term_finding` 现用合并效率(payers/impressions)分类 opportunity/leak,把"点击"和"转化"两个漏点合并了,建议无法落地。

**增强:** 词分类增加两个子类型(在现有 opportunity/leak/average/small_sample 基础上,对 leak 细分):
- `click_leak`(高曝光低点击):`product_click_rate` 显著低于点击率基线 → 杠杆=封面/标题/词-货匹配。
- `conversion_leak`(高点击低转化):点击率正常但 `pay_conversion` 显著低于转化基线 → 杠杆=详情/价格/信任状。
term_rows 增 `leak_type` 列;key_numbers 增 `click_leak_count`/`conversion_leak_count`;结论与 recommended_action 按主导漏损类型给对应杠杆。保持向后兼容(原 `term_class` 保留)。

**测试:** 高曝光低点击词 → click_leak;高点击低转化词 → conversion_leak。

### D2. `sku_structure` — FDR + 价格带

- 高退款 SKU 清单:对候选算单侧二项 p,BH-FDR 过滤,key_numbers 增 `fdr_survivors`、`expected_false_positives`,结论标注 FDR。
- (价格带退款交叉挪到 C2 refund_root_cause,避免重复;此处仅加 FDR。)

**测试:** 大量噪声 SKU + 少数真高退款,断言 FDR 存活集不含纯噪声。

### D3. `core_business` — 时序分解增强

`_gmv_trend` 除现有首尾 direction 外,调用 `timeseries` 计算 wow / dow / changepoint,写入 `business_trend` 表与 key_numbers(`wow_last_pct`、`peak_dow`、`changepoint_date`)。结论追加"GMV 在 <changepoint 日期> 出现结构性变化 / 周内 <peak> 最高"。降级:date 不可解析时跳过新指标,保留原 direction。

---

## 工作项 E — 集成与发布

1. `analysis/registry.py`:注册 `channel_structure_diagnosis`、`refund_root_cause_diagnosis`。
2. `reporting/html.py`:`channel_structure` 归入"经营诊断"组;`refund_root_cause` 归入退款相关组。
3. `references/task_menu.md` + `skills/.../assets/xhs-ca/references/task_menu.md`:新增两行。
4. `SKILL.md`:模块清单提及两个新模块。
5. `task_templates/`:新增 `channel_structure_diagnosis.md`、`refund_root_cause_diagnosis.md`。
6. 全量 `pytest` + `ruff`;`sync-runtime` + 镜像套件(期望 3 skips by design)。
7. 真实库 `run auto` demo,核对新小节。
8. 提交(无署名 trailer)+ push + `npx skills update`。

## 自检清单

- [ ] 每个新/改模块绝不 raise、缺表缺列优雅降级。
- [ ] 观察性证据封顶 WEAK,每 Finding 带 confounders + 观察性 caveat。
- [ ] A1/A2 两个 bug 有针对性回归测试。
- [ ] FDR/时序 helper 有独立单测。
- [ ] coverage/run auto 自动纳入两个新模块(无需改 coverage,自动发现)。
- [ ] 镜像同步,镜像套件通过。
