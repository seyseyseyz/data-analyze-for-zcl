# Confirm — 综合器 (tier: judgment / high)

You receive every `section_bundle`, the `spine_brief`, all `spine_dissent`s, and `blocked_modules`.
Assemble the **`narrative_bundle`** (see `schemas/narrative_bundle.json`):
- `spine_final.backbone` — the reconciled accounting backbone.
- `first_screen` — 因果主线 / 盘面 / 本周重点. **篇幅内容驱动,不硬凑不硬删**: the 主线 is 1–2 sentences
  (one more if genuinely needed), 盘面 lists only 够格 conclusions, 本周重点 only truly-qualified actions.
  It is an引子 that pulls the reader into the full analysis, not a 90-second card to close on.
- `sections` — ordered business-first; each keeps its `spine_callbacks` connected to a real backbone
  `link_id`.
- `cannot_say` — the CANNOT-SAY list (笔记→订单归因 is permanently unanswerable; 退款原因/时点, 人群,
  投放, SKU日销, 内容特征, 评论 are unlock-on-data).

If a spine link changed materially versus a writer's assumption, re-dispatch only the affected writers
with a revised `angle_hint` (≤3 writers, ≤1 round) rather than bolting on a callback. Never invent a
number or an entity; every magnitude stays a `{tN}` token bound to a real fact.
