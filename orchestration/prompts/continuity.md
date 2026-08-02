# Continuity — 全篇连读与统一嗓音 (tier: judgment / high)

你阅读已通过事实 gate 与视图 review 的完整成稿，消除重复、跳跃、术语漂移和九段拼接感。
输出严格的 **`continuity_edit`** runtime envelope（`schemas/continuity_edit.json`）：
`{"edits":[...]}`。每条 edit 只定向到一个 `claim_id` 的唯一字符串片段。

机械边界：

- `old` 必须在目标 claim 中逐字且仅出现一次。
- `new` 必须保持完全相同的数字 multiset 与 `{tN}` / `number_token` 绑定；不得新增、删除或改变
  任何业务数字。
- 不改变结论方向、置信度、因果许可、action 条件或 `fact_id` / `claim_id` / `table_id`。
- 注册表/确定性层唯一拥有 metric 名称、单位、口径、周期、`aggregation`、公式与 tooltip；不得
  用润色改写字段语义，也不得在正文补字段解释。
- 只在确实提升连读质量时输出 edit，宁缺毋滥。
