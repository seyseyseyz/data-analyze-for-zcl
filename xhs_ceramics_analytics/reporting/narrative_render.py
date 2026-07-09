# xhs_ceramics_analytics/reporting/narrative_render.py
"""Deterministic narrative renderer — fills {tN}, applies continuity edits, freezes, skeletons.

Python owns rounding: ``fill_sentence`` copies ``fact.rendered`` verbatim into each
``{tN}`` slot with zero numeric derivation, so a fabricated number is unrepresentable.
``apply_continuity_edits`` lets the Continuity pass rewrite prose only — the digit and
``{tN}`` multisets of every edit are invariant (the shipped merchant_voice ``{…}``
contract, generalized). ``render_frozen`` re-gates at render time (tamper evidence).
``skeleton_markdown`` is the 0-agent floor reusing the existing compositor. Pure; the
edit/hash guards raise ValueError by design (callers treat them as gate failures).
"""

import copy
import re
from typing import NamedTuple

from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.reporting.charts import render_chart_template
from xhs_ceramics_analytics.reporting.confidence_pill import confidence_pill_html
from xhs_ceramics_analytics.reporting.content_templates import content_templates_markdown
from xhs_ceramics_analytics.reporting.curated_view import render_view
from xhs_ceramics_analytics.reporting.factcheck_gate import (
    allowed_confidence_tag,
    run_gate,
)
from xhs_ceramics_analytics.reporting.first_screen import (
    first_screen_markdown,
    normalize_line,
)
from xhs_ceramics_analytics.reporting.html import (
    RAW_HTML_CLOSE,
    RAW_HTML_OPEN,
    render_markdown_document_html,
)
from xhs_ceramics_analytics.reporting.markdown import render_markdown
from xhs_ceramics_analytics.reporting.table_labels import table_label

_TOKEN_RE = re.compile(r"\{t\d+\}")
_DIGIT_RE = re.compile(r"\d")
_SKELETON_BANNER = "> **本报告为确定性骨架版：叙事层未通过事实校验，数字与表格仍完整可核。**"


def fill_sentence(sentence: str, number_tokens: list[dict], facts: dict) -> str:
    """Replace each {token_id} with facts[fact_id]['rendered']. No numeric derivation."""
    out = sentence
    for tok in number_tokens or []:
        fid = tok.get("fact_id")
        rendered = str((facts.get(fid) or {}).get("rendered", "—"))
        out = out.replace("{" + str(tok.get("token_id")) + "}", rendered)
    return out


def _all_claim_lists(bundle: dict):
    for section in bundle.get("sections") or []:
        yield section.get("claims") or []
    fs = bundle.get("first_screen") or {}
    for key in ("spine", "panel"):
        yield [c for c in (fs.get(key) or []) if isinstance(c, dict) and "sentence" in c]


def _claims_by_id(bundle: dict) -> dict[str, dict]:
    """Map claim_id → claim across the whole bundle (sections + first_screen).

    The index a curated view is badged against: its ``supports_claim`` resolves here
    so the confidence tag comes from the claim's trusted fact anchors, never from an
    agent-authored view field. Never raises."""
    index: dict[str, dict] = {}
    for claims in _all_claim_lists(bundle):
        for claim in claims or []:
            if isinstance(claim, dict):
                cid = claim.get("claim_id")
                if isinstance(cid, str) and cid:
                    index.setdefault(cid, claim)
    return index


def render_draft(bundle: dict, facts_json: dict) -> dict:
    """Return a new bundle where every claim carries a filled ``rendered_sentence``.

    An already-rendered sentence (e.g. one a Continuity pass polished before freezing)
    is preserved — it is only (re)filled when absent or still holding an unfilled {tN}.
    This lets a frozen bundle re-render at 0 LLM calls without reverting its edits.
    """
    bundle = copy.deepcopy(bundle)
    facts = facts_json.get("facts") or {}
    for claims in _all_claim_lists(bundle):
        for claim in claims:
            existing = str(claim.get("rendered_sentence") or "")
            if existing and not _TOKEN_RE.search(existing):
                continue  # already rendered (e.g. continuity-edited) — keep it verbatim
            claim["rendered_sentence"] = fill_sentence(
                str(claim.get("sentence") or ""), claim.get("number_tokens"), facts
            )
    return bundle


def _digit_multiset(text: str) -> list[str]:
    return sorted(_DIGIT_RE.findall(text))


def _token_multiset(text: str) -> list[str]:
    return sorted(_TOKEN_RE.findall(text))


def apply_continuity_edits(bundle: dict, edits: list[dict]) -> dict:
    """Apply prose-only edits. old must occur once; digits/{tN} invariant. Raises on violation."""
    bundle = copy.deepcopy(bundle)
    index: dict[str, dict] = {}
    for claims in _all_claim_lists(bundle):
        for claim in claims:
            index[claim.get("claim_id")] = claim
    for edit in edits or []:
        cid = edit.get("claim_id")
        claim = index.get(cid)
        if claim is None:
            raise ValueError(f"continuity edit for unknown claim_id {cid}")
        old, new = str(edit.get("old")), str(edit.get("new"))
        text = str(claim.get("rendered_sentence") or "")
        if text.count(old) != 1:
            raise ValueError(f"continuity 'old' must occur exactly once in claim {cid}")
        if _digit_multiset(old) != _digit_multiset(new):
            raise ValueError(f"continuity edit changes the digit multiset in claim {cid}")
        if _token_multiset(old) != _token_multiset(new):
            raise ValueError(f"continuity edit changes the {{tN}} multiset in claim {cid}")
        claim["rendered_sentence"] = text.replace(old, new)
    return bundle


def _rendered(claim: dict) -> str:
    return str(claim.get("rendered_sentence") or claim.get("sentence") or "").strip()


# Confidence tiers, weakest→strongest, for the conservative modal tie-break below.
_TAG_RANK: dict[str, int] = {"弱": 1, "中": 2, "强": 3}


def _claim_anchors_fact(claim: dict, facts: dict) -> bool:
    """True if the claim binds at least one ``{tN}`` token to a fact present in the
    FactBook — i.e. it carries a real numeric anchor the confidence can derive from.
    A pure-prose / mechanism claim (no resolvable anchor) returns False so it neither
    contributes to nor suppresses the section pill. Never raises."""
    for tok in claim.get("number_tokens") or []:
        if isinstance(tok, dict) and tok.get("fact_id") in facts:
            return True
    return False


def _section_confidence(claims: object, facts: dict | None = None) -> str | None:
    """The one confidence tag that summarizes a section's claims — the modal tag, with
    a conservative (weaker-wins) tie-break.

    This replaces the per-sentence （强/中/弱）repetition ("每条结论后跟个弱"): the tag
    is now shown once as a section pill. The tag is derived deterministically from each
    claim's FactBook anchors via :func:`allowed_confidence_tag` — the SAME source the
    per-view badges use — so the section pill can never contradict the view badges
    below it (the "域头弱 / 视图强" split). It is NOT read from the agent-authored
    ``confidence`` field, which the gate only ever caps DOWNWARD (an agent's timid 弱
    would otherwise stick on the headline even when the evidence defensibly allows 强).
    Only claims that actually anchor a fact are counted, so a pure-prose section still
    renders no pill. Returns ``None`` when nothing anchors. Never raises.
    """
    facts = facts if isinstance(facts, dict) else {}
    counts: dict[str, int] = {}
    for claim in claims or []:
        if not isinstance(claim, dict) or not _rendered(claim):
            continue
        if not _claim_anchors_fact(claim, facts):
            continue
        tag = allowed_confidence_tag(claim, facts)
        if tag in _TAG_RANK:
            counts[tag] = counts.get(tag, 0) + 1
    if not counts:
        return None
    # Highest count wins; on a tie prefer the weaker tier (smaller rank) — never let a
    # single strong outlier lift a section's headline confidence above its typical claim.
    return max(counts, key=lambda t: (counts[t], -_TAG_RANK[t]))


def _mechanism_entry(entry: object) -> tuple[str, str]:
    """Normalize one ``mechanism`` entry to ``(claim_id, link)``.

    An entry is either a bare ``claim_id`` string or a dict with ``claim_id`` and an
    optional number-free ``link``/``connector`` connective. Anything else → ("", "")."""
    if isinstance(entry, str):
        return entry.strip(), ""
    if isinstance(entry, dict):
        cid = str(entry.get("claim_id") or "").strip()
        link = str(entry.get("link") or entry.get("connector") or "")
        return cid, link
    return "", ""


def _mechanism_link(link: object) -> str:
    """A ``mechanism`` connective is agent-authored free prose, so it must carry NO
    magnitude — numbers only ever come from the referenced (fact-validated) claim. Strip
    the raw-HTML sentinels, then drop the connective entirely if it holds any digit (the
    step still renders its claim sentence). Never raises."""
    txt = _strip_raw_html_markers(str(link or "")).strip()
    if not txt or _DIGIT_RE.search(txt):
        return ""
    return txt


def _mechanism_parts(bundle: dict) -> list[str]:
    """The 跨模块主线 block: an ordered chain of EXISTING claims (possibly across
    sections) that the synth agent selected to form one cross-module causal thesis.

    Each entry resolves to its claim's already-filled ``rendered_sentence`` — so the
    chain introduces no new numeric surface (the numbers were gate-validated inside their
    claims) and needs no gate change. An unresolvable claim_id drops its step; an empty
    chain renders nothing. Returns ``[]`` (no heading) when nothing resolves. Never raises.
    """
    entries = (bundle or {}).get("mechanism")
    if not isinstance(entries, (list, tuple)):
        return []
    index = _claims_by_id(bundle)
    headline_norm = normalize_line((bundle or {}).get("headline"))
    steps: list[str] = []
    for entry in entries:
        cid, link = _mechanism_entry(entry)
        claim = index.get(cid)
        if not isinstance(claim, dict):
            continue
        sentence = _strip_raw_html_markers(_rendered(claim)).replace("\n", " ").strip()
        if not sentence:
            continue
        # #8: the 跨模块主线 must not restate the headline verbatim — it already leads
        # the 首屏. A step that IS the headline is dropped (other steps stay).
        if headline_norm and normalize_line(sentence) == headline_norm:
            continue
        link_txt = _mechanism_link(link)
        steps.append(f"**{link_txt}** {sentence}" if link_txt else sentence)
    if not steps:
        return []
    # One multi-line part: consecutive ``N.`` lines group into a single <ol> in the
    # narrative md→HTML converter (a blank line would restart numbering at 1).
    ordered = "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
    return ["## 跨模块主线", ordered]


def bundle_to_markdown(
    bundle: dict,
    facts_json: dict,
    *,
    title: str | None = None,
    result_tables: dict | None = None,
) -> str:
    """Render the narrative bundle to markdown, inlining each section's curated views.

    ``result_tables`` is the already-computed ``result.tables`` the deterministic
    curated-view engine fills every displayed number from (the numeric-trust
    boundary). It defaults to ``{}`` so existing callers/tests keep working; with no
    tables the curated views are skipped and the report degrades to today's
    prose-only output. A single malformed/missing-table view drops silently — the
    report always renders.
    """
    tables = result_tables if isinstance(result_tables, dict) else {}
    claims_by_id = _claims_by_id(bundle)
    facts = facts_json.get("facts") if isinstance(facts_json, dict) else None
    facts = facts if isinstance(facts, dict) else {}
    parts: list[str] = []
    # Report-wide set of source tables already charted (by a curated view or an earlier
    # fallback) — the fallback consults it so no chart is duplicated across sections (#7).
    charted_tables: set[str] = set()
    if title:
        parts.append(f"# {_strip_raw_html_markers(str(title))}")
    parts.append(_strip_raw_html_markers(first_screen_markdown(bundle)).rstrip())
    # 跨模块主线: the synth agent's cross-section causal chain, rendered right after the
    # first screen so the reader meets the thesis before the per-domain detail. Omitted
    # entirely when no chain was authored / nothing resolves (backward compatible).
    parts.extend(_mechanism_parts(bundle))
    headline_norm = normalize_line(bundle.get("headline"))
    for section in bundle.get("sections") or []:
        heading = _strip_raw_html_markers(
            str(section.get("title") or section.get("section_id") or "").strip()
        )
        parts.append(f"## {heading}")
        # One per-section confidence pill (the modal tag) instead of a （强/中/弱）
        # after every sentence. Wrapped as a raw-HTML passthrough block so the .tag
        # chip survives the markdown→HTML conversion; the span is deterministic.
        pill_tag = _section_confidence(section.get("claims"), facts)
        pill_html = confidence_pill_html(pill_tag) if pill_tag else ""
        if pill_html:
            parts.append(_raw_html_block(pill_html))
        for claim in section.get("claims") or []:
            sentence = _strip_raw_html_markers(_rendered(claim))
            if not sentence:
                continue
            # #8: a section claim that is the headline verbatim is redundant — the hook
            # already led the 首屏. Drop only the exact echo; other claims are the detail.
            if headline_norm and normalize_line(sentence) == headline_norm:
                continue
            parts.append(sentence)
        if tables:
            view_parts, chart_count, charted = _curated_view_parts(
                section, tables, claims_by_id, facts
            )
            parts.extend(view_parts)
            charted_tables |= charted
            # Defense-in-depth: a CORE domain that produced no chart-template curated
            # view gets one deterministic chart auto-injected from the source table,
            # so the narrative reliably carries visuals instead of shipping prose-only.
            # The fallback skips any table already charted anywhere in the report (#7) so
            # it never emits a chart that duplicates one shown in another section.
            if chart_count == 0:
                parts.extend(_fallback_chart_parts(heading, tables, charted_tables))
    # 可复用内容模板: a static, number-free ceramics content playbook (领域内容模板库).
    # Deterministic and reproducible — appended after the data sections and before the
    # open-questions caveats, so the reader meets findings, then what-to-make, then gaps.
    parts.append(content_templates_markdown())
    cannot = [
        s
        for s in (_strip_raw_html_markers(str(c).strip()) for c in (bundle.get("cannot_say") or []))
        if s
    ]
    if cannot:
        parts.append("## 暂时答不了的问题")
        parts.extend(f"- {c}" for c in cannot)
    return "\n\n".join(parts) + "\n"


class _EvidenceCarrier:
    """Minimal Finding-shim carrying only ``evidence_strength`` for
    :func:`curated_view.derive_confidence` — used to forward a deterministically
    resolved strength without pulling a full Finding into the render path."""

    __slots__ = ("evidence_strength",)

    def __init__(self, evidence_strength: object) -> None:
        self.evidence_strength = evidence_strength


# The gate tag a claim's anchors allow, mapped back to the EvidenceStrength that
# ``derive_confidence`` re-projects to the same tag (强↔STRONG, 中↔MEDIUM, 弱↔WEAK) —
# so the curated view's badge equals the gate's allowed tag with no agent input.
_TAG_TO_EVIDENCE: dict[str, EvidenceStrength] = {
    "强": EvidenceStrength.STRONG,
    "中": EvidenceStrength.MEDIUM,
    "弱": EvidenceStrength.WEAK,
}


def _finding_for_view(spec: object, claims_by_id: dict[str, dict], facts: dict) -> object | None:
    """Resolve a view's confidence-bearing finding from its supporting claim's facts.

    Rule 5: confidence (强/中/弱) is derived deterministically from the FactBook —
    NEVER from an agent-authored field. We resolve the view's ``supports_claim`` to a
    real claim and take :func:`allowed_confidence_tag` (the same strongest-anchor tag
    the gate caps to). An agent-authored ``evidence_strength`` on the view spec is
    ignored, so it cannot forge a stronger badge than the evidence allows. A view with
    no resolvable claim degrades to the weakest tag (``None``). Never raises.
    """
    if not isinstance(spec, dict):
        return None
    claim = claims_by_id.get(str(spec.get("supports_claim") or ""))
    if not isinstance(claim, dict):
        return None
    tag = allowed_confidence_tag(claim, facts)
    return _EvidenceCarrier(_TAG_TO_EVIDENCE.get(tag, EvidenceStrength.WEAK))


def _view_source_table(spec: object) -> str:
    """The bare source-table name a view draws from (``spec.source.table``), or ``""``.
    Used to record which tables a section charted so the fallback never repeats one."""
    if not isinstance(spec, dict):
        return ""
    source = spec.get("source")
    if not isinstance(source, dict):
        return ""
    return str(source.get("table") or "")


def _curated_view_parts(
    section: object, result_tables: dict, claims_by_id: dict[str, dict], facts: dict
) -> tuple[list[str], int, set[str]]:
    """Render one section's ``curated_views`` to inline markdown parts.

    Returns ``(parts, chart_count, charted_tables)`` where ``chart_count`` is how many
    rendered views actually carried a chart SVG — the signal :func:`bundle_to_markdown`
    uses to decide whether to auto-inject the deterministic fallback chart (only when it
    is 0) — and ``charted_tables`` is the set of source tables those charts drew from, so
    a later section's fallback never re-charts the same data (#7).

    Each passing view contributes: its title (a subheading), the deterministic table
    HTML and/or chart SVG (wrapped in raw-HTML passthrough markers so the narrative
    HTML converter emits them verbatim instead of escaping the angle brackets), the
    how_to_read caption, the why_it_matters hook, and the provenance stamp. A degraded
    view (bad spec / missing table / missing column) contributes nothing — the section
    keeps the prose rendered above it. Never raises: a pathological view is skipped.
    """
    if not isinstance(section, dict):
        return [], 0, set()
    views = section.get("curated_views")
    if not isinstance(views, (list, tuple)):
        return [], 0, set()
    parts: list[str] = []
    chart_count = 0
    charted_tables: set[str] = set()
    for spec in views:
        try:
            finding = _finding_for_view(spec, claims_by_id, facts)
            view = render_view(spec, result_tables, finding=finding)
        except Exception:  # never-raise: render_view is already defensive, stay so
            continue
        view_parts = _single_view_parts(view)
        if view_parts and str(getattr(view, "chart_svg", "") or "").strip():
            chart_count += 1
            table = _view_source_table(spec)
            if table:
                charted_tables.add(table)
        parts.extend(view_parts)
    return parts, chart_count, charted_tables


def _single_view_parts(view: object) -> list[str]:
    """Markdown parts for one rendered :class:`curated_view.CuratedView`. Empty when
    the view degraded or carries no renderable html — the section degrades silently."""
    if getattr(view, "degraded", True):
        return []
    table_html = getattr(view, "table_html", None) or None
    chart_svg = getattr(view, "chart_svg", None) or None
    if not table_html and not chart_svg:
        return []

    parts: list[str] = []
    # Every caption below is agent-authored prose and is marker-neutralized so it
    # cannot forge a raw-HTML passthrough sentinel (see _strip_raw_html_markers).
    # table_html / chart_svg are the DETERMINISTIC engine blocks and are the only
    # content allowed to carry real markers, added here by _raw_html_block.
    title = _strip_raw_html_markers(str(getattr(view, "title", "") or "").strip())
    if title:
        parts.append(f"### {title}")
    if table_html:
        parts.append(_raw_html_block(str(table_html)))
    if chart_svg:
        parts.append(_raw_html_block(str(chart_svg)))
    how_to_read = _strip_raw_html_markers(str(getattr(view, "how_to_read", "") or "").strip())
    if how_to_read:
        parts.append(how_to_read)
    why_it_matters = _strip_raw_html_markers(str(getattr(view, "why_it_matters", "") or "").strip())
    if why_it_matters:
        parts.append(f"**{why_it_matters}**")
    provenance = _strip_raw_html_markers(str(getattr(view, "provenance", "") or "").strip())
    if provenance:
        parts.append(f"> {provenance}")
    return parts


def _strip_raw_html_markers(text: str) -> str:
    """Neutralize the raw-HTML passthrough sentinels in agent-authored prose.

    The narrative HTML converter (``reporting.html._markdown_document_body``) treats
    a standalone ``RAW_HTML_OPEN`` line as the start of an UNESCAPED verbatim block —
    the mechanism that inlines the deterministic curated table/chart HTML. Its only
    legitimate producer is :func:`_raw_html_block`. If any agent-authored string (a
    claim sentence, headline, caption, title, or cannot_say line) carried the marker,
    a forged line would flip the converter into passthrough and let a following
    ``<script>`` — or a fabricated number — ship raw, an XSS bypass and a breach of
    the numeric-trust boundary. Removing the marker tokens from all agent prose makes
    the sentinels non-forgeable: the only markers reaching the transport are the ones
    :func:`_raw_html_block` wraps around engine HTML. Never raises.
    """
    return str(text).replace(RAW_HTML_OPEN, "").replace(RAW_HTML_CLOSE, "")


def _raw_html_block(html: str) -> str:
    """Wrap already-safe deterministic HTML so the narrative HTML converter passes it
    through verbatim (see reporting.html.RAW_HTML_OPEN)."""
    return f"{RAW_HTML_OPEN}\n{html}\n{RAW_HTML_CLOSE}"


class _FallbackChart(NamedTuple):
    table: str  # source table name in result_tables (bare, as the engine keys it)
    template: str  # a chart template in charts._CHART_TEMPLATES
    x: str  # x-axis column
    y: str  # y-axis column
    title: str  # subheading shown above the auto-injected chart
    caption: str  # neutral, non-interpretive caption (carries no conclusion/tier)


# Per-domain deterministic chart fallback. Keyed by the domain title, which the
# narrative bundle uses verbatim as each section's title/section_id (see
# reporting.domains.DOMAINS). Each domain lists ORDERED candidates; the first whose
# source table exists in result_tables and renders a non-empty SVG is injected — and
# ONLY when the section produced zero chart-template curated views, so an agent-authored
# chart is never doubled. Numbers are filled by render_chart_template straight from the
# source-table cells (the numeric-trust boundary); nothing here is agent-authored. Only
# the five data-bearing core domains are mapped — action/appendix domains have no chart.
_FALLBACK_CHARTS: dict[str, tuple[_FallbackChart, ...]] = {
    "生意大盘": (
        _FallbackChart(
            "business_trend", "trend_line", "date", "gmv", "GMV 走势", "每日 GMV 走势。"
        ),
    ),
    "流量与内容": (
        _FallbackChart(
            "channel_scale", "share_bar", "carrier_zh", "gmv_share", "渠道结构", "各渠道 GMV 占比。"
        ),
        _FallbackChart(
            "search_conversion_trend",
            "trend_line",
            "period",
            "avg_pay_conversion",
            "搜索支付转化走势",
            "搜索承接的支付转化走势。",
        ),
    ),
    "商品结构": (
        _FallbackChart(
            "sku_category_l2_mix",
            "share_bar",
            "category_l2",
            "gmv_share",
            "品类 GMV 分布",
            "各二级品类 GMV 占比。",
        ),
        _FallbackChart(
            "sku_category_mix",
            "share_bar",
            "category_l1",
            "gmv_share",
            "品类 GMV 分布",
            "各一级品类 GMV 占比。",
        ),
    ),
    "用户与需求": (
        _FallbackChart(
            "audience_conversion_comparison",
            "share_bar",
            "audience_type",
            "conversion",
            "新老客转化对比",
            "新老客支付转化对比。",
        ),
        _FallbackChart(
            "audience_gmv_contribution",
            "share_bar",
            "audience_type",
            "gmv_share",
            "新老客 GMV 贡献",
            "新老客 GMV 占比。",
        ),
    ),
    "退款与售后": (
        _FallbackChart(
            "refund_by_ship_stage",
            "share_bar",
            "stage_zh",
            "rate",
            "退款环节分布",
            "发货前后退款率对比。",
        ),
        _FallbackChart(
            "refund_by_category",
            "share_bar",
            "category_l1",
            "refund_rate",
            "各品类退款率",
            "各一级品类退款率。",
        ),
    ),
}


def _fallback_provenance(table: str) -> str:
    """Provenance stamped under an auto-injected chart, naming its source table by the
    same human :func:`table_label` the curated views and appendix use. The internal
    "事实层 result_tables · 自动补图" wording is deliberately gone — it named an
    implementation layer, not anything a merchant recognizes."""
    return f"> 来源:{table_label(table)}"


# The set of tables the fallback can actually chart — the definition of "the fact layer
# had chartable data" that the visuals_missing degradation signal keys off.
_CHARTABLE_TABLES: frozenset[str] = frozenset(
    cand.table for cands in _FALLBACK_CHARTS.values() for cand in cands
)


def has_chartable_tables(result_tables: object) -> bool:
    """True when ``result_tables`` holds at least one non-empty table the fallback knows
    how to chart. Lets the finalizer tell a real visual gap (chartable data existed but
    no chart shipped → ``visuals_missing``) apart from honestly thin data. Never raises."""
    try:
        if not isinstance(result_tables, dict):
            return False
        for name in _CHARTABLE_TABLES:
            rows = result_tables.get(name)
            if isinstance(rows, (list, tuple)) and any(isinstance(r, dict) for r in rows):
                return True
        return False
    except Exception:
        return False


def _fallback_chart_parts(
    domain_title: str, result_tables: dict, charted_tables: set[str] | None = None
) -> list[str]:
    """One deterministic chart for a core domain whose section produced no chart view.

    Walks the domain's ordered candidates and emits the first whose source table renders
    a non-empty SVG (via :func:`render_chart_template`, so every number comes from the
    table cells — the numeric-trust boundary). The caption is neutral and carries no
    conclusion or evidence tier — a fallback visual asserts nothing beyond the source
    data. A candidate whose table already appears in ``charted_tables`` is skipped so the
    fallback never duplicates a chart shown in another section (#7); the table it does
    chart is recorded there. Returns ``[]`` for an unmapped domain or when no candidate
    table is usable. Never raises: a pathological table drops the fallback silently."""
    seen = charted_tables if isinstance(charted_tables, set) else set()
    try:
        for cand in _FALLBACK_CHARTS.get(domain_title, ()):  # unmapped domain → ()
            if cand.table in seen:  # already charted elsewhere → never duplicate it
                continue
            rows = result_tables.get(cand.table)
            if not isinstance(rows, (list, tuple)) or not rows:
                continue
            svg = render_chart_template(cand.template, list(rows), {"x": cand.x, "y": cand.y})
            if not str(svg).strip():
                continue
            parts = [f"### {cand.title}", _raw_html_block(str(svg))]
            if cand.caption:
                parts.append(cand.caption)
            parts.append(_fallback_provenance(cand.table))
            seen.add(cand.table)  # record so a later fallback won't repeat this chart
            return parts
        return []
    except Exception:
        return []


def render_frozen(frozen: dict, facts_json: dict) -> tuple[str, str]:
    """Render (md, html) from a frozen narrative. Re-gates + checks facts_hash (tamper evidence)."""
    if frozen.get("facts_hash") != facts_json.get("facts_hash"):
        raise ValueError("frozen facts_hash does not match the supplied facts.json")
    bundle = frozen.get("narrative_bundle") or {}
    report = run_gate(bundle, facts_json)
    if report.status != "PASS":
        raise ValueError(f"frozen narrative fails the render-time gate: {report.hard_failures}")
    drafted = render_draft(report.bundle, facts_json)
    md = bundle_to_markdown(drafted, facts_json)
    html = render_markdown_document_html(md)
    return md, html


def skeleton_markdown(results, *, title: str | None = None) -> str:
    """Deterministic 0-agent floor: banner + the existing compositor's markdown."""
    body = render_markdown(results, title=title)
    return f"{_SKELETON_BANNER}\n\n{body}"
