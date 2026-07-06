# Continuity — 全篇连读+统一嗓音 (tier: judgment / high)

You read the **already-filled** nine-section draft (numbers are in place) end to end and unify voice,
flow, and emphasis so it reads as ONE story, not nine stitched panels. Emit **`continuity_edit[]`**
(see `schemas/continuity_edit.json`): each `{claim_id, old, new}` rewrites prose ONLY.

Mechanical contract (enforced by Python `finalize`; a violation drops the edit):
- `old` must be a verbatim substring of that claim's rendered sentence and occur exactly once.
- `new` must contain the **same digit multiset** and the **same `{tN}` multiset** as `old` — you may
  reword around numbers, never change, add, or remove one.
- Never change a conclusion's direction, a confidence tag, or a caliber footnote.
- Never strip emoji — it is real merchant content.
Only emit an edit where it genuinely reads better; 宁缺毋滥.
