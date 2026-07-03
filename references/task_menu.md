# Task Menu

Use this menu to describe tasks to the user. **Do not hand-pick by guesswork** — run `xhs-ca coverage` first: it reports which tasks are producible on the built data and which are blocked (with the missing table/column). Default to running the whole producible set via `xhs-ca run auto` so the report mines the data to its full depth. Run `all` only when the user asks for a full operating review including degraded modules.

| 用户意图 | task_id | 必需数据 | 可选数据 | 输出 |
|---|---|---|---|---|
| 先看导出的表能不能分析 | `data_quality_check` | any imported CSV | all tables | 表可用性、空表、缺失限制 |
| 建账号经营基线 | `account_baseline` | `notes` | `orders`, `calendar_events` | 发布频率、阅读基础盘、弱/中/强证据 |
| 看笔记曝光到互动漏斗 | `note_funnel` | `notes` | `content_features` | 阅读率、点赞率、收藏率、评论率 |
| SKU 发文后销量有没有反应 / SKU 销量响应 | `sku_counterfactual_lift` | `notes`, `orders` or `daily_sku_sales`, `skus` | `note_sku_links`, `calendar_events` | 发布前后销量观察窗口、弱归因说明 |
| 看内容发布后的销量响应曲线 | `content_response_curve` | `notes`, `orders` or `daily_sku_sales`, `skus` | `note_sku_links` | d0-1、d1-3、d4-7、d8-14 响应窗口 |
| 哪类封面更值得拍 | `cover_style_effect` | `notes`, `content_features` | cover image folders | 封面构图分组表现和下一步测试 |
| 哪类文案角度更有效 | `copy_angle_effect` | `notes`, `content_features` | comments | 文案角度分组表现 |
| 商品和内容组合怎么搭 | `product_content_interaction` | `notes`, `content_features` | `skus`, `note_sku_links` | 封面/文案组合表现 |
| 哪些商品/SKU 值得优先推 | `product_opportunity_matrix` | `skus`, `orders` or `daily_sku_sales` | `products`, `notes`, `note_sku_links` | SKU 机会矩阵和优先级 |
| 评论里用户在问什么/要什么 | `comment_demand_mining` | `comments` | `notes`, `products` | 需求主题、异议、可转化内容点 |
| 内容组合怎么优化 | `content_portfolio_optimization` | `notes`, `content_features` | `orders`, `comments` | 内容组合保留、增加、减少建议 |
| 下周发什么 / 周实验计划 | `weekly_experiment_matrix` | `notes` | `orders`, `comments`, `content_features` | 7 天实验矩阵、假设和观察指标 |
| 哪些笔记适合重拍/重发 | `reshoot_repost_candidates` | `notes` | `content_features`, `orders` | 重拍候选、重发理由、改法 |
| 沉淀有效假设和经验 | `hypothesis_knowledge_base` | any prior task outputs or imported tables | all tables | 假设库、证据等级、下一次验证 |
| 周复盘 / 下周动作 / 完整经营结论 | `weekly_business_review` | `notes` | `orders`, `skus`, `comments`, `content_features`, `calendar_events` | 经营导读、关键变化、下周动作 |
| 看投放数据能不能分析 | `ad_data_quality_check` | `ad_performance_daily` | `notes`, `skus`, `products`, `daily_sku_sales` | 字段可用性、粒度、关联覆盖、补数建议 |
| 看投放消耗和投产效率 | `paid_traffic_efficiency` | `ad_performance_daily` | `notes`, `skus`, `products`, `daily_sku_sales`, `note_sku_links` | 投放消耗、点击效率、投产、预算动作建议 |
| 生意大盘怎么样 / 核心经营结构 | `core_business_diagnosis` | `business_overview_daily` | `business_overview_monthly` | GMV/客单/转化结构、时间趋势、观察性诊断 |
| 搜索流量效率怎么样 | `search_efficiency_diagnosis` | `search_overview` | `search_terms` | 搜索曝光/点击/转化效率、词效结构 |
| 进店人群结构如何 | `audience_structure_diagnosis` | `shop_page_funnel` | `shop_page_source` | 进店漏斗、来源结构、人群画像口径说明 |
| 退款结构与高退款点 | `refund_structure_diagnosis` | `refund_overview` | `notes`, `sku_performance` | 退款分层、载体两比例检验、时间趋势、笔记/商品级反映 |
| 笔记级商业效能（GMV 集中度/转化/退款） | `note_commercial_diagnosis` | `notes` | — | 笔记 GMV 帕累托、转化效率分布、笔记级退款异常 |
| SKU 结构与退款诊断 | `sku_structure_diagnosis` | `sku_performance` | — | SKU GMV 帕累托与类目结构、高退款 SKU、加购转化与客单价 |
| 渠道结构与健康诊断 | `channel_structure_diagnosis` | `business_overview_daily` | `traffic_source` | 载体/渠道规模结构、转化两比例检验、退款对比 |
| 退款根因诊断（发货环节/品类/价格带） | `refund_root_cause_diagnosis` | `sku_performance` | `refund_overview` | 发货前后退款拆解、分品类与分价格带退款集中度 |
