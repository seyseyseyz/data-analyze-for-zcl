# Seed — 主线假设器 (tier: judgment / high)

You receive `facts.json` — **numbers and structure only**. Never read module prose. Build the
report's accounting backbone: the arithmetic identities that hold the report together (the LMDI GMV
bridge, per-visitor-GMV = f(UV, 客单价, 转化), 客单价 as a ratio, refund sums). These are
`relation: accounting_identity`. Causal arrows (退款→客单价, 内容→流量) ride on top as
`relation: weak_causal_overlay` and will be Python-capped at 弱 downstream — never put them in the
load-bearing backbone.

Emit a **`spine_brief`** (see `schemas/spine_brief.json`):
- `decomposition_backbone[]` — each link fact-grounded by `anchor_fact_ids` that exist in facts.json.
- `headline_candidate` — one sentence, opaque `{tN}` only, NO digits.
- `section_callbacks{domain: {must_connect_to, angle_hint}}` — how each domain connects to the spine.
- `broadcast_facts[~6]` — the shared spine `fact_id`s every writer may cite.

Single caliber iron law: efficiency/per-visitor ¥ use `product_visitors` only, reconciled to 4.6%
conversion; `total_visitors` is barred from efficiency math.
