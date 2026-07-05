export const meta = {
  name: 'report-writer',
  description: 'Claude Code accelerator for the L3 merchant-narrative DAG: seed → ≤6 domain writers → synthesizer. Reads the neutral orchestration/ contract; deterministic gate/render run as xhs-ca subcommands outside this script.',
  phases: [
    { title: 'Seed', detail: '主线假设器：facts.json 数字与结构 → spine_brief' },
    { title: 'Fan', detail: '≤6 域写手并行 → section_bundle' },
    { title: 'Confirm', detail: '综合器 → narrative_bundle' },
  ],
}

// Uses the Workflow API — agent(...)/parallel(...)/log(...) — like merchant_voice_workflow.js.
// The SOURCE OF TRUTH for every role's instructions is orchestration/prompts/<role>.md and the
// handoff shapes are orchestration/schemas/*.json. This script is an OPTIONAL accelerator: each agent
// is told to Read the neutral prompt file and follow it, so the contract lives in one place. Model
// choice is role tier + reasoning effort only — never a model id — so the same DAG runs on any host.
//
// `args` is { facts_path, domains: [{section_id, slice_note}], seed_note? } supplied by the caller.

const FACTS = (args && args.facts_path) || '.xhs-ceramics-analytics/facts.json'
const DOMAINS = ((args && args.domains) || []).slice(0, 6) // Fan is capped at 6 writers.

// Embedded structured-output schemas. Canonical copies live in orchestration/schemas/*.json; kept
// minimal here because the Workflow API needs a JS object at agent({schema}) and cannot read a file
// at script runtime. The gate (xhs-ca gate) is the real validator; these just shape agent output.
const SPINE_BRIEF_SCHEMA = {
  type: 'object', additionalProperties: true,
  required: ['decomposition_backbone', 'headline_candidate', 'broadcast_facts'],
  properties: {
    decomposition_backbone: { type: 'array', items: { type: 'object' } },
    headline_candidate: { type: 'string' },
    section_callbacks: { type: 'object' },
    broadcast_facts: { type: 'array', items: { type: 'string' } },
  },
}
const SECTION_BUNDLE_SCHEMA = {
  type: 'object', additionalProperties: true,
  required: ['section_id', 'title', 'claims'],
  properties: {
    section_id: { type: 'string' },
    title: { type: 'string' },
    claims: { type: 'array', items: { type: 'object' } },
    spine_callbacks: { type: 'array', items: { type: 'string' } },
    spine_dissent: { type: ['string', 'null'] },
  },
}
const NARRATIVE_BUNDLE_SCHEMA = {
  type: 'object', additionalProperties: true,
  required: ['facts_hash', 'headline', 'first_screen', 'spine_final', 'sections', 'cannot_say'],
  properties: {
    facts_hash: { type: 'string' },
    headline: { type: 'string' },
    first_screen: { type: 'object' },
    spine_final: { type: 'object' },
    sections: { type: 'array', items: { type: 'object' } },
    cannot_say: { type: 'array', items: { type: 'string' } },
  },
}

function seedPrompt() {
  return `Read orchestration/prompts/seed.md and follow it exactly (tier: judgment/high).
Read the facts file at ${FACTS} — numbers and structure ONLY, never module prose.
Emit a spine_brief per orchestration/schemas/spine_brief.json. ${(args && args.seed_note) || ''}`
}

function writerPrompt(domain) {
  return `Read orchestration/prompts/writer.md and follow it exactly (tier: draft/medium).
You write ONLY the "${domain.section_id}" section. Read ${FACTS} for your domain slice and the
broadcast spine facts. ${domain.slice_note || ''}
Sentences carry opaque {tN} tokens ONLY — never a digit. Emit a section_bundle per
orchestration/schemas/section_bundle.json.`
}

function synthesizerPrompt(spine, sections) {
  return `Read orchestration/prompts/synthesizer.md and follow it exactly (tier: judgment/high).
spine_brief:
${JSON.stringify(spine, null, 1)}
section_bundles:
${JSON.stringify(sections, null, 1)}
Assemble one narrative_bundle per orchestration/schemas/narrative_bundle.json. 首屏篇幅内容驱动，
不硬凑不硬删。Never invent a number or entity; every magnitude stays a {tN} token.`
}

const spine = await agent(seedPrompt(), {
  label: 'seed', phase: 'Seed', effort: 'high', schema: SPINE_BRIEF_SCHEMA,
})

const sections = (await parallel(
  DOMAINS.map((d) => () =>
    agent(writerPrompt(d), {
      label: `writer:${d.section_id}`, phase: 'Fan', effort: 'medium', schema: SECTION_BUNDLE_SCHEMA,
    })
  )
)).filter(Boolean)

const narrative = await agent(synthesizerPrompt(spine, sections), {
  label: 'synthesizer', phase: 'Confirm', effort: 'high', schema: NARRATIVE_BUNDLE_SCHEMA,
})

log(`report-writer: seed + ${sections.length} writers → narrative_bundle assembled. ` +
    `Next (outside this script): xhs-ca gate → render-draft → Continuity → finalize → render-frozen.`)
return { spine, sections, narrative }
