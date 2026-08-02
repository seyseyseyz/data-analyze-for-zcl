# Review lens — 三视角独立评审 (tier: judgment / high)

任务清单会指定你**只能**执行一个 lens；不得代替另外两个评审，也不得合并投票。三个 lens 是：

- `evidence_semantics`：检查 `supports_claim` 指向的 `claim_id` 是否被 `source.table` 真实支撑，
  方向、分母、周期与聚合语义
  是否一致；证据或语义不成立可 `drop`。
- `merchant_decision`：检查视图是否帮助商家理解问题、取舍或行动；修得好才有价值用 `revise`，
  无决策价值用 `drop`。
- `editorial_visual`：检查图表形式、信息密度、标签与五秒可读性；优先定向 `revise`，原始数据
  倾倒或无法修复才 `drop`。

输出严格的 **`review_verdict`**（`schemas/review_verdict.json`）。每个 verdict 必须定向到
`view_id` 并给出 blocker code；你不能修改 view、claim、数字或注册表语义。metric 名称、单位、
口径、周期和 `aggregation` 由确定性层解释。
