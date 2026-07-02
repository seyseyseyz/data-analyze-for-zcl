# data_quality_check

**Slug**: `data_quality_check`  |  **Module**: `xhs_ceramics_analytics/analysis/data_quality.py`  |  **Registry**: registry.py:27

## Purpose

检查当前 DuckDB 数据库中已导入的表及其行数，快速判断后续分析任务能否正常执行。此任务仅统计"表是否存在"及"行数是否为零"，不做列级空值检查、重复 ID 检测、日期范围校验或未映射列报告。

## Required tables & fields

- 无特定表要求。任务通过 `SHOW TABLES` 枚举数据库中所有已加载表，对每张表执行 `SELECT COUNT(*)` 统计行数。
- 若数据库为空（无任何表），任务仍正常运行，结果为 NOT_JUDGABLE。

## Method

1. 通过 `connect(db_path)` 打开 DuckDB 连接（data_quality.py:9）。
2. 执行 `SHOW TABLES` 获取所有表名（line 16）。
3. 对每个表名，使用 `_quote_identifier` 安全转义后执行 `SELECT COUNT(*) FROM "<table>"` 获取行数（line 14）。
4. 将 `{table, rows}` 字典列表赋给 `rows`，作为输出表 `table_row_counts`（lines 11-17）。
5. 从 `rows` 中筛选行数为 0 的表名列表 `missing`（line 20）。
6. 判定证据强度：`rows` 非空则 STRONG，否则 NOT_JUDGABLE（line 32）。
7. 若 `missing` 非空，附加告警说明后续分析可能降级（lines 35-37）。

## Key formulas

- `rows = COUNT(*) FROM "<table>"`（对 SHOW TABLES 返回的每张表）  (data_quality.py:14)
- `table_count = len(rows)`  (data_quality.py:34)
- `missing = [t for t in rows if t["rows"] == 0]`  (data_quality.py:20)

## Thresholds & evidence

| 条件 | 证据强度 | 代码位置 |
| --- | --- | --- |
| `rows` 列表非空（至少检测到一张表） | Strong | data_quality.py:31-33 |
| `rows` 列表为空（SHOW TABLES 无返回） | Not-judgable | data_quality.py:31-33 |
| 存在行数为 0 的表 | Strong（不降级，仅追加 caveat） | data_quality.py:35-37 |

## Output

- **Result frame `table_row_counts`**:
  - `table` — DuckDB 中表名（字符串，来自 SHOW TABLES）
  - `rows` — 该表的行数（整数，来自 COUNT(*)）

- **Finding**:
  - title: `导入表可用`
  - evidence_strength: STRONG 或 NOT_JUDGABLE
  - key_numbers: `{"table_count": <int>}`
  - caveats: 当存在空表时输出 `["部分表为空，相关分析会降级为弱判断或不可判断。"]`，否则空列表
  - recommended_action: 无

## Sample output section

```markdown
## 数据质量检查

### 导入表可用

已检测到 7 张表。空表：无。

证据强度：强

关键数字：
- `table_count`: 7

表格 `table_row_counts`：7 行

| table | rows |
| --- | --- |
| notes | 24 |
| products | 8 |
| skus | 15 |
| orders | 63 |
| content_features | 24 |
```

## Common failure modes

- 数据库中完全无表（SHOW TABLES 返回空）→ table_count=0，evidence=NOT_JUDGABLE，conclusion 显示"已检测到 0 张表。空表：无。" → 建议先运行 `build-database` 导入 CSV。
- 某张表存在但行数为 0 → 该表出现在 `missing` 列表中，caveat 提示后续分析可能降级 → 检查源 CSV 是否为空或导入过程是否有映射问题。
- DuckDB 文件路径不存在或无法打开 → DuckDB 底层抛出异常（无显式 guard）→ 确认路径和文件权限。
- 表名含特殊字符（双引号等）→ `_quote_identifier` 会转义处理，正常运行。
- 列级空值 / 重复 ID / 未映射列等问题 → 本任务不检查（仅做行数统计），需人工或其他工具验证。

## Fixtures

- `tests/fixtures/notes.csv`
- `tests/fixtures/products.csv`
- `tests/fixtures/skus.csv`
- `tests/fixtures/orders.csv`
- `tests/fixtures/content_features.csv`
- `tests/fixtures/comments.csv`
- `tests/fixtures/calendar_events.csv`

Minimum viable fixture set for this task: 任意一个非空 CSV 即可（任务只需 SHOW TABLES + COUNT(*)）。全部 7 个 CSV 用于完整集成测试。

## Cross-links

- Depends on: 无（此为数据管线第一步）
- Feeds: [weekly_business_review](./weekly_business_review.md)（weekly_review.py 引用 data_quality_check 结果作为 data_quality section）
- Reference: [../references/data_contract.md](../references/data_contract.md), [../references/evidence_strength.md](../references/evidence_strength.md)
