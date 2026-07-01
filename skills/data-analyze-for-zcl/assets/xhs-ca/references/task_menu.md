# Task Menu

Use this menu to choose the smallest task that answers the user's business question. Run `all` only when the user asks for a full operating review or the request spans most rows below.

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
