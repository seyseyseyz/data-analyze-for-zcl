# Narrative Workflow 全链路可靠性强化 — 设计规格

**日期：** 2026-08-02

**状态：** Draft for review

**目标：** 修复本次 4–6 月经营诊断报告暴露的全部合理问题，使多 Agent 报告流程在文件命名、Schema、动态引用、补丁、调度、预检和最终交付上可校验、可恢复、可审计，并保持现有命令和历史运行目录兼容。

## 1. 背景与已确认事实

本次报告运行不是因事实数据不足而失败。最终 `_bundle` 的真实 gate 阻断只剩 4 个 `DANGLING_CALLBACK`，但流程没有 callback 定向修复能力，最终在 27 次 patch ingest 后进入 `gate_exhausted` 的确定性骨架版。

运行同时暴露了以下独立缺陷：

1. `narrative ingest --task-id ... --source result.json` 仍错误地要求结果文件名与 brief 文件名相同，实际执行只能创建同名软链接绕过。
2. Agent 只得到自然语言格式说明，缺少可执行的 Schema、枚举、当前轮次和控制器字段契约。结果出现 spine 结构错误、缺少 `causal_link`、非法 severity、非法 visual 字段、错误 round 和修改不可变证据等问题。
3. `domain_adjudication.json` 只约束 `spine_callbacks` 为字符串数组，没有约束字符串必须属于当前 spine 的真实 `link_id` 集合；错误直到最终 gate 才暴露。
4. patch 完成只代表结果已被 ingest，不证明目标真的改变、删除或保持了不可变字段。
5. gate exhaustion 路由 fallback 前没有持久化最后一次 gate report，`state.json._gate_failures` 因而保留了已经修复的旧错误。
6. Host 的并发槽位约为 5，而领域阶段有 6 个任务。批量 spawn 部分成功后抛错、已完成 Agent 未及时关闭、等待只在首个完成时返回，造成任务 ID 丢失、重复派发和大量人工恢复。
7. 输入目录名写 4–7 月，但有效数据范围是 2026-04-01 至 2026-06-30；数据含有店铺名 `PiGoo 手作瓷器`，最终却使用了中性名称；重复导出、去重结果、字段映射诊断和缺数阻断没有在分析前形成一个明确预检结论。
8. 最终 HTML 只有 1 个 SVG。现有“至少一个图”检查无法证明所有关键、可图示的领域都得到了有效视觉证据。

## 2. 设计原则

1. **控制器拥有协议，Agent 只拥有业务内容。** `task_id`、`candidate_id`、`section_id`、`target_id`、轮次和 blocker ID 由控制器生成或核对，Agent 不再负责猜测。
2. **静态 Schema 与动态上下文同时校验。** JSON Schema 负责封闭结构和枚举；运行时校验负责当前 spine ID、实体注册表、目标 claim/view、轮次和不可变证据。
3. **先拒绝局部错误，再推进全局状态。** validate 和 ingest 共用一条校验管线；校验失败不改变任务状态、章节、轮次或历史。
4. **可恢复而不是静默修饰。** 无效的可选 callback 可以安全丢弃并留审计记录；缺失的必需 callback 生成专门 patch。证据、数字和业务判断绝不自动改写。
5. **并发限制只影响调度，不影响报告语义。** 槽位不足不会触发 unsupported、fallback、重新授权或任务复制。
6. **交付证据强于控制器状态。** 只有精确 HTML 文件通过内容、标题、视觉、token、数量和路径检查，才能视为交付成功。
7. **源代码、仓库 bundle、已安装 runtime 同步验证。** 仓库修改先同步 bundle；真实安装态用可写 `XHS_CA_PROJECT_ROOT` 单独验证，避免源码通过而本地 skill 仍旧。

## 3. 总体架构

在现有 `narrative_workflow.py` 状态机外增加四个边界清晰的组件，不另建第二套工作流：

### 3.1 Task Contract Resolver

输入当前 state、stage 和 task，输出该任务唯一的可执行契约：

- `task_id`
- `brief_path`
- 默认 `result_path`
- `schema_path` 与 Schema ID
- `controller_fields`
- 当前 stage、round、section/lens/target/candidate
- Schema 中可枚举字段的允许值
- 动态允许值，例如 spine `link_id`、claim ID、view ID 和 blocker code
- 不可变字段及其输入摘要

`status --json` 的 pending/completed task 都公开这个契约。旧字段继续保留，因此旧 host 和旧运行目录仍可读取。

### 3.2 Validation Pipeline

新增只读命令：

```bash
xhs-ca narrative validate \
  --run-dir <run-dir> \
  --task-id <task-id> \
  --source <result.json>
```

管线顺序固定为：

1. 读取 task contract；
2. 提取 JSON；
3. 由控制器补齐缺失的 envelope 字段；
4. 若 Agent 回传的控制器字段与 task 冲突，拒绝结果；
5. 按精确 Schema 校验；
6. 执行动态引用、实体、token、round 和目标校验；
7. 计算预期 mutation；
8. 返回机器可读 diagnostics，不写 state。

`ingest` 必须复用同一管线。validate 通过而 ingest 因相同内容失败属于回归缺陷。

### 3.3 Dispatch Ledger

每个 task 增加持久化调度信息：

- `dispatch_status`: `pending | reserved | dispatched | result_ready | ingested | closed | failed`
- `agent_id`
- `result_path`
- `attempt`
- `reserved_at` / `completed_at`
- `last_error`

状态机提供以下 host 命令，host 每次只派发已保留任务：

```bash
xhs-ca narrative reserve --run-dir <run-dir> --capacity <N>
xhs-ca narrative record-dispatch --run-dir <run-dir> --task-id <id> \
  --agent-id <id> --result-path <path>
xhs-ca narrative record-agent-state --run-dir <run-dir> --task-id <id> \
  --status result_ready|closed|failed
xhs-ca narrative release --run-dir <run-dir> --task-id <id>
```

一次最多保留 `capacity - in_flight` 个；部分 spawn 成功时逐个登记已得到的 Agent ID，未成功项只能在没有 `agent_id` 时 release，任务不会丢失。`failed` 保留错误和 attempt，重新 reserve 时递增 attempt；`closed` 只能用于已经 ingest 或明确失败的任务。

Agent 完成后，host 先把结果写入 contract 的 `result_path`，validate、ingest，再关闭 Agent 并标记 `closed`。关闭是 host 外部动作；runtime 只记录事实，不声称能代替 Codex 关闭 Agent。

历史运行目录没有 ledger 时，按原 task status 推导 `pending` 或 `ingested`，不要求迁移。

### 3.4 Inspection Manifest

新增：

```bash
xhs-ca inspect <directory-or-files...> [--out inspection.json]
```

该命令只读源文件，复用现有 importer/header 识别逻辑，输出：

- 文件分类、sheet、行数和文件 hash；
- 实际最小/最大业务日期及目录名日期冲突；
- 店铺/账号候选及来源；
- 完全重复文件、重叠导出和预计去重键；
- 可识别字段、待审映射和口径冲突；
- 初步可产出任务及缺数建议。

build 完成后补充一份 `build_manifest.json`，记录实际输入行、接受行、重复行、映射结果、build hash 和最终 coverage。inspect 的“预计”结果不能冒充 build 的实际结果。

## 4. Ingest 与任务归属修复

`task_id` 是结果归属的最高优先级。提供有效 `task_id` 后：

- `--source` 可以是任意可读 JSON 文件；文件名不参与身份判断。
- `section_id`、`lens`、`target_id` 若同时提供，只作为一致性断言。
- 没有 `task_id` 时，为兼容旧调用，仍可按 brief/source 同名或唯一维度匹配，但歧义必须报错。
- 默认 result path 由 controller contract 生成，host 无须手工发明命名。

回归用例必须直接使用与 brief 不同名的 `result.json`，禁止在测试中用软链接掩盖问题。

## 5. Schema 与动态协议强化

### 5.1 封闭 Schema

所有 stage 继续使用 `additionalProperties: false`。Schema fixture 必须覆盖实际生成 brief 中展示的示例，保证示例本身可通过 Schema。

关键枚举直接从 Schema 提取并写入 task contract，例如：

- challenge severity：`blocker | major | note`
- view type/template 允许值
- review disposition 和 blocker code
- patch operation 和 round

brief 不再复制一份可能漂移的手写枚举，而是嵌入 contract 摘要及 Schema 路径。

### 5.2 控制器字段

Agent 可为兼容性回传控制器字段，但不是必需。处理规则：

- 缺失：控制器补齐；
- 相同：接受；
- 冲突：失败并返回 expected/actual；
- ingest 后的持久化结果总是使用控制器值。

### 5.3 Callback

`spine_callbacks` 的动态允许集合来自已裁决 spine 的真实 `link_id`：

- 空数组合法；
- 未知 ID 在 ingest 前被识别；
- 若 callback 只是可选交叉引用，控制器删除未知值、记录 `normalizations.jsonl`，不让它进入 gate；
- 若 spine contract 要求某 section 回应特定 link，缺失时创建 `callback_patch`，只允许从明确列出的 link ID 中选择或声明无法回应；
- callback patch 不得改 claim、数字 token、fact ID 或 view。

现有 `DANGLING_CALLBACK` 继续作为最终防线，但正常流程应在 ingest 前消除它。

### 5.4 实体与不可变证据

writer、adjudicator、synth 和 patch 的实体引用在推进前与冻结实体注册表比对。未知实体返回结构化 diagnostics 和允许值来源，不自动把近似名称映射为事实实体。

每个 patch task 保存目标前摘要：

- target 类型与 ID；
- mutable path；
- immutable evidence hash；
- gate/review blocker ID；
- patch round。

ingest 后重新计算摘要。只有目标发生预期变化或被明确 drop，且不可变 hash 不变时，task 才 completed；空操作、改错目标、错误轮次和证据漂移都保持 pending。

## 6. Gate、Patch 与降级语义

每次 gate 均在状态转换前原子写入：

```text
<run-dir>/gate_reports/gate-<attempt>.json
<run-dir>/gate_report.json  # 最新成功写入的副本
```

state 同步保存：

- `_gate_attempt`
- `_gate_failures`（必须等于最新 report）
- `_gate_report_path`
- `_gate_bundle_hash`

即使下一步是 `gate_exhausted` 或 `untargetable_gate_blocker`，也必须先写最新 report 和 state，再进入 fallback。确定性 fallback 不删除或覆盖失败证据。

Patch 路由按 blocker 类型分层：

1. view-only 错误：安全 drop 单个 view，并记录原因；
2. callback 错误：callback-specific patch 或安全删除未知可选 callback；
3. claim/实体/token 错误：claim-targeted patch；
4. 无法定位到唯一目标：立即标记 `untargetable_gate_blocker`，不制造重复无效 patch；
5. 每轮只重跑仍未解决的 blocker，已解决 blocker 不得出现在下一轮 task 中。

## 7. 调度恢复协议

Host 遵循以下循环，而不是一次性 spawn 整个阶段：

1. `status --json` 读取 pending、in-flight 和可用容量；
2. reserve 最多可用容量个 task；
3. 每 spawn 成功一个 Agent，立即持久化 `agent_id`；
4. 若 spawn 在批次中途失败，只释放没有 Agent ID 的 reservation；
5. wait 返回后，逐一检查所有 in-flight Agent，不只处理首个完成者；
6. 对完成结果执行 validate → ingest → close → ledger close；
7. 再 reserve 下一批，直到 stage 完成。

恢复时以 ledger 为准：

- 已有 `agent_id` 的 task 不重复 spawn；
- result path 已存在但未 ingest 的 task 先 validate/ingest；
- Agent 已完成但未 close 的 task 优先关闭释放槽位；
- reservation 超时且没有 `agent_id` 才能回收；
- 并发压力永远不改变授权或报告降级状态。

## 8. 预检、命名与去重

### 8.1 报告日期

目录名只作为提示，不能决定报告日期。确定性优先级为：用户显式指定并与数据相容的区间 → 已成功导入的经营大盘/订单主数据区间 → 所有入选任务共同覆盖的连续区间 → 无共同区间时使用各数据源覆盖范围并要求人工确认。inspection 始终列出每个来源的最小/最大日期；若目录名、显式区间或来源区间不一致，输出 warning。本次应从经营主数据推断为 `2026年4-6月`。

### 8.2 店铺名

使用以下确定性优先级：

1. 用户显式名称；
2. 导出中的店铺/账号字段；
3. 跨文件稳定一致的作者昵称；
4. 明确多数品牌名；
5. 中性 `店铺`。

低置信度候选不能覆盖更高优先级来源。inspection 记录候选、来源、频次和最终选择。本次数据应得到 `PiGoo 手作瓷器`，除非更高优先级输入明确覆盖。

### 8.3 重复与覆盖

去重结果必须区分：

- 重复文件；
- 同一业务主键的重复行；
- 时间区间重叠但业务行不同；
- 真正冲突的同键不同值。

build manifest 同时展示原始行数、接受行数、去重行数和冲突行数。本次 3 份笔记导出各 1,272 行、3 份经营导出各 91 行的去重事实必须在预检/构建摘要中可见，不能只存在于内部表。

### 8.4 映射与 coverage

inspect 不自动批准 fuzzy/conflict 映射。build 后仍执行现有字段映射风险门禁，并列出 5 个 mapping diagnostics。coverage 必须明确区分可产出任务和因广告、日粒度 SKU、内容特征、评论等缺失而阻断的任务，并输出 exact next-data-needed。

Skill 工作流顺序固定为：authorization → bootstrap → inspect → build → mapping/data-quality → coverage → facts → narrative。`doctor` 不能替代 bootstrap。

## 9. 视觉与最终交付质量

不设置装饰性“每领域图表配额”，也不以 SVG 数量代替判断。增加 `visual_coverage`：

- 每个领域列出 decision-critical claims；
- 标记其来源表是否 chartable；
- 记录保留 view、被拒原因或 `visual_omission_reason`；
- chartable 的关键 claim 必须有通过 gate/review 的有效 view，或有明确 omission；
- 任何关键 chartable 领域缺少有效 view 时，最终状态记录 `degradation_reason=visuals_missing`，交付摘要必须披露。

最终验证同时检查：

1. `.xhs-ceramics-analytics/outputs/` 下本次运行恰好一个用户可见 HTML；
2. 文件名与 `<店铺名><真实日期范围>经营诊断报告` 一致，平台名不前置；
3. HTML title、章节和正文不是 stale output；
4. 无未解析 `{tN}`、无内部路径或调试字段泄漏；
5. 每个保留 view 在 HTML 中有对应 SVG/table，数量与 spec 一致；
6. visual coverage 没有未披露缺口；
7. fallback、delivery_failed、visuals_missing 三种状态严格区分；
8. Markdown、facts、results、gate reports 和 state 仍为内部审计材料，不作为默认交付。

## 10. 运行隔离与兼容性

每个 build/facts/narrative 链路使用一个 `analysis_run_id` 和输入 hash。facts/results/inspection/build manifest/narrative state 必须记录同一 lineage；hash 或 run ID 不一致时 fail closed，禁止从旧输出目录拼装新报告。

兼容策略：

- 现有 `prepare`、`status`、`ingest`、`advance`、`finalize` 命令保留；
- 新字段均为 additive；
- 历史 state 缺字段时按 deterministic defaults 推导；
- 旧 source-name 匹配仅在没有 task ID 时保留；
- Schema 版本写入 task contract 和 state，缓存 key 包含 contract version；
- source runtime 与 `skills/data-analyze-for-zcl/assets/xhs-ca` 由 `sync-runtime` 保持字节一致；已安装 runtime 独立刷新验证。

## 11. 测试与评估

### 11.1 单元与契约测试

1. 有 `task_id` 时可 ingest 任意文件名，无软链接。
2. task contract 正确公开 result/schema/enums/controller fields/round/dynamic IDs。
3. `narrative validate` 完全只读，和 ingest 使用同一诊断结果。
4. 所有生成 brief fixture 的示例通过正式 JSON Schema。
5. 非法 severity、visual 字段、round 和 envelope 冲突在 state mutation 前失败。
6. callback 只能使用当前 spine ID；未知可选 callback 被审计删除，必需 callback 生成定向 patch。
7. patch 空操作、错误目标或不可变证据变化不会 completed。
8. gate exhaustion 前最后一次 report 已持久化，state failures 与其一致。
9. 旧 state 和旧调用方式仍能读取/推进。

### 11.2 调度测试

模拟 6 个任务、并发容量 5：

- 首批仅 reserve 5 个；
- 部分 spawn 成功后失败不丢任务；
- 已登记 task 不重复派发；
- 完成/关闭后第 6 个进入下一批；
- 最终 6 个 task 各 ingest 一次且仅一次。

### 11.3 数据预检测试

使用本次导出的脱敏 fixture 验证：

- 文件夹 4–7 月但实际日期推断为 4–6 月；
- 店铺推断为 `PiGoo 手作瓷器`；
- 重复导出的原始/去重计数清晰可见；
- mapping diagnostics、可产出/阻断任务和 next-data-needed 可追溯；
- inspect 不写源文件、不自动批准风险映射。

### 11.4 真实回放与交付验收

用本次 facts/results 回放完整 quality-v2：

1. callback 不再导致 fallback；
2. 流程进入 review/continuity/finalization；
3. 最新 gate report 与 state 一致；
4. 标题和文件名使用 `PiGoo 手作瓷器` 与 2026 年 4–6 月；
5. 每个关键 chartable 领域有有效视觉或显式 degradation；
6. 最终只交付一个完整、自包含 HTML；
7. exact HTML 经内容和视觉抽查，不以 controller green 代替检查。

## 12. 实施顺序

1. 先补 ingest、gate persistence 和 callback 的失败测试，修复当前确定性故障。
2. 抽出 task contract/validation pipeline，再让 status、brief、validate、ingest 共用。
3. 增加 patch effect verification 和 callback-specific patch。
4. 增加 dispatch ledger 与 capacity planner，更新 runbook 和 SKILL host 循环。
5. 增加 inspect/build manifest、命名、去重和 lineage。
6. 增加 visual coverage 与最终交付验证。
7. 同步 bundle、刷新 installed runtime，执行单元、集成、真实数据回放和最终 HTML 检查。

## 13. 非目标

- 不让 runtime 直接调用或关闭 Codex Agent；它只提供可靠的 host 协议和持久化 ledger。
- 不自动批准不确定字段映射，不改写用户源数据。
- 不把近似实体自动映射为事实实体。
- 不新增与本次失败无关的分析算法、指标或 UI 重构。
- 不要求为了凑数量生成无决策价值的图表。

## 14. 完成定义

只有以下证据全部成立，才可认为本次“所有问题、全部合理优化”完成：

1. 第 11 节所有新增测试通过，现有全量测试无回归；
2. source/bundle/installed runtime 行为一致；
3. 本次真实数据回放不因已确认的四类 callback 进入 fallback；
4. inspection 正确说明日期、店铺、去重、映射和 coverage；
5. 最新 gate diagnostics 可恢复且不陈旧；
6. 6-task/5-capacity 调度验证无丢失、重复或误降级；
7. 最终单 HTML 通过精确路径、标题、内容、视觉和 degradation 检查；
8. 需求—证据矩阵逐项有当前运行证据，不以意图、代码存在或窄测试替代完成证明。
