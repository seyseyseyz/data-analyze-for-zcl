# 退款结构诊断模块设计（refund_structure_diagnosis）

> **状态**: 设计草案，待 writing-plans。这是"报告模块并行化"子项目的**骨架模块**——后续 §2 核心经营 / §5 搜索 / §6 人群 三个模块将照此范式（模块契约、统计助手、降级矩阵、模板、测试）并行实现。

## 目标

新增分析任务 `refund_structure_diagnosis`：把总退款拆为**发货前 / 发货后（含仅退款）/ 退货**三层，定位漏点集中在哪一层与哪个载体（笔记/商卡），叠加时间趋势，并给出陶瓷品类的处方性杆杆建议；同时**两方面下钻**——**产品级**（哪些产品拉高退款、共有什么特征）与**笔记级**（哪些笔记退款高、共有什么特征）。全程内部相对基准，数据自足，缺表/缺列优雅降级。

## 决策记录（brainstorming 已确认）

- **并行策略**：骨架先行，退款打头；后三模块照此并行。
- **首要主题**：结构诊断 + 杆杆定位，主抓 `refund_overview`。
- **对比基准**：内部相对基准（各层/各载体互比 + `business_overview_daily` 时间趋势），**不依赖外部行业数**。
- **追加需求 1**：增加笔记级退款率分析，反思高退款笔记特征（Finding 4）。
- **追加需求 2**：增加产品级退款集中度分析，反思高退款产品特征（Finding 5）——"哪些产品和哪些笔记，两方面都需要"。

## 架构与契约

- **新文件** `xhs_ceramics_analytics/analysis/refund_structure_diagnosis.py`，导出 `def run(db_path: Path) -> AnalysisResult`。
- **注册**：`analysis/registry.py` 加 `import` + `TASKS["refund_structure_diagnosis"] = run` 一行。
- **模板**：`task_templates/refund_structure_diagnosis.md`（单源，经 `scripts/sync-runtime` 镜像到 `skills/data-analyze-for-zcl/assets/xhs-ca/task_templates/`）。
- **统计助手**：`analytics/confidence.py` 已有 `wilson_interval(k, n, z=1.96)`、`min_n_guard(n)`、`rate_band(lo, hi)`；`analytics/trends.py` 已有 `mom_change`、`direction_label`、`pct_change`。**新增** `two_proportion(k1, n1, k2, n2) -> dict`（两样本比例差异检验，返回 `{diff, z, significant, ci_overlap}`），设计为通用助手供后续搜索/人群模块复用。
- **无新 mart**（YAGNI）：全部 inline SQL，骨架保持精简；如后续模块证明需要共享视图再抽 `db/marts.py`。
- 复用现有 `db.duck.connect`、模块内 `_table_exists` / `_table_columns` / `_missing_result` helper（照 `account_baseline.py` 范式）。

## 数据来源与口径

| 用途 | 表 | 关键列（canonical） | 缺失行为 |
|------|----|--------------------|---------|
| 三层拆解 | `refund_overview`（聚合快照） | `refund_amount_pay`, `pre_ship_refund_amount`, `post_ship_refund_amount`, `shipped_refundonly_amount`, `return_refund_amount`, 对应 `*_orders`、`*_rate_pay`, `refund_users`；维度 `载体`(carrier) | 表缺 → 整模块 NOT_JUDGABLE |
| 载体对比 | `refund_overview` 的 `载体` 维度 | `refund_rate_pay` / `refund_orders_pay` per carrier | 维度缺失或单一载体 → 跳过 finding 2 |
| 时间趋势 | `business_overview_daily`（日粒度） | `refund_amount_pay`, `refund_rate`（或 `net_gmv_pay` 反算） | 表缺 → 跳过 finding 3 |
| 笔记级 | `notes` | `note_refund_rate_pay`, `note_refund_orders_pay`, `note_refund_amount_pay`, `title` | 表/列缺 → 跳过 finding 4 |
| 笔记特征 | `content_features`（LEFT JOIN notes on note_id） | `composition_type`, `scene_hint`, `copy_angle` | 缺 → finding 4 降级为"仅列高退款笔记，不做特征归因" |
| 产品级 | `sku_performance`（按 `product_id` 聚合） | `product_id`, `product_name`, `refund_amount_pay`, `refund_rate_pay`, `refund_orders_pay`, `net_gmv_pay` | 表/列缺 → 跳过 finding 5 |
| 产品特征 | `products`（LEFT JOIN on product_id）+ `skus`（价格带，可选） | `vessel_type`(器型), `series`, `category`；`skus.price` | 缺 → finding 5 降级为"仅列高退款产品，不做特征归因" |

**分母反推**：`refund_overview` 直接给 rate，不给支付订单基数。各层 rate 的样本量 `n = round(refund_orders / refund_rate)`（`rate > 0` 时），过 `min_n_guard` 守卫后用于 `wilson_interval` 与 `two_proportion`。这是全程自足的关键技巧。

## Findings（8 元素契约：title/conclusion/evidence_strength/key_numbers/caveats/recommended_action/evidence_reason/confounders/next_test/appendix）

### Finding 1 — 主漏点层级
- 计算三层各自占**总退款金额**的份额与各层退款率；找出份额最大的层级。
- 该层退款率配 `wilson_interval`（基于反推 n）与 `rate_band` 标注。
- `key_numbers`: `{layer, layer_share, layer_refund_rate, ci_low, ci_high, total_refund_amount}`。
- `recommended_action`: 由**杆杆映射**（见下）给出该层对应的整改方向。
- `evidence_strength = score_evidence(n, has_controls=False, confounder_count>=1)` → 观察性，上限 WEAK。

### Finding 2 — 载体退款率对比（笔记 vs 商卡）
- 对两载体 `refund_rate_pay` 做 `two_proportion`（k=refund_orders, n=反推支付订单）。
- 结论说明差异是否显著、哪个载体退款更高、幅度多少。
- `key_numbers`: `{carrier_high, rate_note, rate_card, diff, significant}`。
- 单一载体或维度缺失 → 不产出此 finding，`limitations` 记一条。

### Finding 3 — 退款率时间趋势
- 取 `business_overview_daily` 日粒度 `refund_rate`（缺则 `refund_amount_pay / gmv`），按日排序，`mom_change` + `direction_label` 给方向与幅度。
- `key_numbers`: `{trend_direction, pct_change, first_period, last_period}`。
- `business_overview_daily` 缺 → 不产出，`limitations` 记一条。

### Finding 4 — 笔记退款反思
- **4a 高退款笔记识别**：按 `note_refund_rate_pay` 排序；退款率高于**内部基准**（全体加权均值）且反推 n 过 `min_n_guard` 的笔记进入"高退款队列"（Wilson 下界 > 均值，避免小样本误报）。
- **4b 特征反思**（`content_features` 存在时）：对高退款队列 vs 其余笔记，比较 `composition_type` / `scene_hint` / `copy_angle` 的分布，找出在高退款队列中**过度代表**的特征值。
- 结论：以假设生成口吻陈述（"高退款笔记更多集中在 X 构图 / Y 场景 / Z 文案角度"），**明确非因果**。
- `key_numbers`: `{high_refund_note_count, baseline_rate, top_feature}`；`next_test`: 建议对疑似特征做 A/B 或重拍验证。
- `content_features` 缺 → 只产出 4a（高退款笔记清单），caveats 注明无法归因特征。

### Finding 5 — 产品退款反思
- **5a 高退款产品识别**：`sku_performance` 按 `product_id` 聚合（`refund_amount = SUM(refund_amount_pay)`；`refund_rate = SUM(refund_orders)/SUM(反推支付订单)` 或按 gmv 加权）。Pareto 排序找出贡献退款金额最多的头部产品；退款率高于**内部基准**（全体加权均值）且反推 n 过 `min_n_guard` 的产品进入"高退款队列"（Wilson 下界 > 均值，避免小样本误报）。
- **5b 特征反思**（`products` 存在时，LEFT JOIN on product_id）：对高退款队列 vs 其余产品，比较 `vessel_type`(器型) / `series` / `category` 的分布，找出在高退款队列中**过度代表**的特征值；`skus` 存在时可加价格带维度。
- 结论：假设生成口吻（"高退款集中在 X 器型 / Y 系列 / Z 价格带"），**明确非因果**。
- `key_numbers`: `{high_refund_product_count, top_products_amount_share, baseline_rate, top_feature}`；`recommended_action`: 结合层级杆杆给出"下架/改造/换供应"方向；`next_test`: 建议对疑似器型/系列做质量抽检或详情页尺寸描述修订后复测。
- `products` 缺 → 只产出 5a（高退款产品清单 + Pareto），caveats 注明无法归因特征。

## 陶瓷杆杆映射（处方性 domain lookup）

模块内常量 `_LAYER_LEVERS: dict[str, str]`：
- `pre_ship`（发货前退款高）→ 下单后拦截话术 / 库存与发货时效 / 价格波动预期管理。
- `post_ship`（发货后仅退款高）→ 物流破损与时效 / 客服响应 / 签收提醒。
- `return`（退货退款高）→ 商品质量 / 尺寸色差 / 描述相符度（陶瓷重点：开裂、色差、规格与实物一致性）。

映射结果注入 Finding 1 的 `recommended_action` 与 `caveats`。

## 通用兼容降级矩阵

| 缺失场景 | 行为 |
|---------|------|
| `refund_overview` 表缺 | `_missing_result("缺少 refund_overview 表。")`，整模块 NOT_JUDGABLE |
| 某退款层列缺（如无退货列） | 跳过该层，其份额不计入拆解，`caveats` 标注 |
| 载体维度缺失或单一 | 跳过 Finding 2 |
| `business_overview_daily` 缺 | 跳过 Finding 3 |
| `notes` 表 / `note_refund_*` 列缺 | 跳过 Finding 4 |
| `content_features` 缺 | Finding 4 仅出 4a，不做特征归因 |
| `sku_performance` 表 / 退款列缺 | 跳过 Finding 5 |
| `products` 缺 | Finding 5 仅出 5a，不做特征归因 |
| 反推 n 未过 `min_n_guard` | 对应 rate 不产 CI，证据降级并 caveat |

任何单表缺失都**不 raise**——保留其余 findings。这是"通用兼容"的硬要求。

## 输出表（`AnalysisResult.tables`）

- `refund_layer_breakdown` — 列：`layer`, `refund_amount`, `share`, `refund_rate`, `ci_low`, `ci_high`, `n`。
- `carrier_refund_comparison` — 列：`carrier`, `refund_rate`, `refund_orders`, `n`（+ 结论里的 diff/significant）。
- `refund_trend` — 列：`period`, `refund_rate`, `refund_amount`（缺源不建表）。
- `high_refund_notes` — 列：`note_id`, `title`, `note_refund_rate`, `n`, `composition_type`, `scene_hint`, `copy_angle`（后三列 content_features 缺时为 NULL）。
- `product_refund_concentration` — 列：`product_id`, `product_name`, `refund_amount`, `amount_share`, `refund_rate`, `ci_low`, `ci_high`, `n`, `vessel_type`, `series`, `category`（后三列 products 缺时为 NULL）。

## 证据与诚实度

- 全部 `has_controls=False`（观察性），`score_evidence` 上限为 WEAK；`confounder_count>=1`（促销、季节、品类结构）。
- 每个 finding 的 `caveats` 明示：不可归因、样本区间为聚合快照、内部相对基准非行业基准。
- `AnalysisResult.limitations` 汇总所有被跳过的 finding 原因（缺表/缺列/单载体）。

## 测试范式（后三模块照抄）

`tests/test_refund_structure_diagnosis.py`：
1. **happy-path**：golden fixture（`refund_overview.csv` + `business_overview_daily.csv` + `notes.csv` + `content_features.csv` + `sku_performance.csv` + `products.csv`）→ 断言 5 个 finding 齐全、主漏点层级正确、载体检验有结论、趋势方向、高退款笔记队列非空、高退款产品 Pareto 与特征反思非空。
2. **降级分支**（各一测试）：仅 refund_overview（只出 finding 1，其余进 limitations）；单载体（跳过 finding 2）；无 business_overview_daily（跳过 finding 3）；无 content_features（finding 4 仅 4a）；无 products（finding 5 仅 5a）；无 sku_performance（跳过 finding 5）。
3. **NOT_JUDGABLE**：无 refund_overview → `_missing_result`。
4. **`two_proportion` 单测**：已知 k/n 组合验证 diff/z/significant/ci_overlap（含 n=0 守卫）。
5. **golden 断言**：`tests/fixtures` 现有退款/概览/sku fixture 已带 Required 列（ingestion-hardening 已补），必要时为 notes/content_features 补 `note_refund_*` 与特征列、为 sku_performance/products 补退款率与器型/系列列。

## 骨架锁定的共享触点（供后三模块复制）

1. 模块文件形态：`analysis/<slug>.py` + `run(db_path)` + `_table_exists`/`_table_columns`/`_missing_result`。
2. 注册：`registry.py` 一行（并行实现时为最后串行接线步，避免 index.lock 竞争）。
3. 统计助手集中在 `analytics/`（本模块新增的 `two_proportion` 可复用）。
4. 模板格式：`task_templates/<slug>.md`（Purpose/Required/Method/Key formulas/Thresholds/Output/Sample/Failure modes/Fixtures/Cross-links）。
5. 测试范式：happy-path + 每条降级分支 + helper 单测 + golden 断言。

## 非目标（YAGNI）

- 不引入外部行业基准阈值（可后续加可选 config，本期纯内部相对）。
- 不建新 DuckDB mart（产品聚合走 inline SQL）。
- 不做因果归因或退款预测——产品/笔记特征反思均为假设生成，非因果。
- 不做单 SKU（规格）级下钻，产品级止步于 `product_id` 聚合（SKU 拆分归后续任务）。
