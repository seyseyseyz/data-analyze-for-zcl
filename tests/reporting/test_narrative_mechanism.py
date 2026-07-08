"""跨模块主线 (cross-module causal thesis) render tests.

The old (Codex) report's most-cited strength was a crisp cross-module causal chain
("6 月流量变多 → 成交效率下滑 → 客单价下滑 → GMV 不升反降") that stitched findings from
different domains into one thesis. This feature adds a bundle-level ``mechanism``: an
ORDERED list of references to EXISTING claim_ids (possibly across sections), each with an
optional number-free ``link`` connective. The renderer resolves each reference to its
already-filled ``rendered_sentence`` — so the chain introduces NO new numeric surface
(numbers stay fact-validated inside the referenced claims) and needs no gate change.
Only the agent-authored connective is forced number-free + marker-neutralized.
"""
from xhs_ceramics_analytics.reporting import narrative_render as nr
from xhs_ceramics_analytics.reporting.html import RAW_HTML_OPEN


def _facts():
    return {"facts_hash": "h", "facts": {}}


def _claim(cid, section_id, sentence, conf="强"):
    return {
        "claim_id": cid,
        "section_id": section_id,
        "claim_kind": "mechanism",
        "sentence": sentence,
        "rendered_sentence": sentence,
        "number_tokens": [],
        "entity_refs": [],
        "confidence": conf,
    }


def _bundle(mechanism):
    return {
        "facts_hash": "h",
        "headline": "标题。",
        "first_screen": {"spine": [], "panel": [], "actions": []},
        "sections": [
            {
                "section_id": "core",
                "title": "生意大盘",
                "claims": [_claim("c1", "core", "6 月总访客比 5 月增加。")],
                "curated_views": [],
            },
            {
                "section_id": "refund",
                "title": "退款与售后",
                "claims": [_claim("c2", "refund", "客单价同期下滑。", conf="中")],
                "curated_views": [],
            },
        ],
        "cannot_say": [],
        "mechanism": mechanism,
    }


def test_mechanism_renders_ordered_chain_across_sections():
    md = nr.bundle_to_markdown(
        _bundle([{"claim_id": "c1"}, {"claim_id": "c2", "link": "结果"}]), _facts()
    )
    assert "## 跨模块主线" in md
    # both referenced claims — from DIFFERENT sections — appear in the chain
    assert "6 月总访客比 5 月增加。" in md
    assert "客单价同期下滑。" in md
    # rendered as a proper ordered list (numbers convey the causal sequence)
    assert "1. " in md
    assert "2. " in md
    # the number-free connective is surfaced (bolded) on its step
    assert "结果" in md


def test_mechanism_link_with_digit_is_dropped_but_claim_kept():
    # A connective that smuggled a magnitude ("6月内") must not ship as agent prose —
    # numbers only ever come from the referenced (fact-validated) claim sentence.
    md = nr.bundle_to_markdown(
        _bundle([{"claim_id": "c2", "link": "6月内"}]), _facts()
    )
    assert "客单价同期下滑。" in md
    assert "6月内" not in md


def test_mechanism_marker_neutralized_in_link():
    md = nr.bundle_to_markdown(
        _bundle([{"claim_id": "c1", "link": f"{RAW_HTML_OPEN}因此"}]), _facts()
    )
    # the forged passthrough sentinel is neutralized (the only real markers are the
    # deterministic confidence pills, so a bare RAW_HTML_OPEN is expected — but never
    # one glued to the agent's connective, which would open a raw block mid-prose)
    assert f"{RAW_HTML_OPEN}因此" not in md
    assert "因此" in md
    assert "6 月总访客比 5 月增加。" in md


def test_mechanism_drops_unresolvable_and_renders_nothing_when_empty():
    # unknown claim_id → step dropped; if nothing resolves, no heading at all
    md = nr.bundle_to_markdown(_bundle([{"claim_id": "nope"}, "also_missing"]), _facts())
    assert "## 跨模块主线" not in md


def test_mechanism_absent_is_backward_compatible():
    bundle = _bundle([])
    del bundle["mechanism"]
    md = nr.bundle_to_markdown(bundle, _facts())
    assert "## 跨模块主线" not in md
    # the rest of the report still renders
    assert "生意大盘" in md


def test_mechanism_accepts_bare_string_claim_ids():
    md = nr.bundle_to_markdown(_bundle(["c1", "c2"]), _facts())
    assert "## 跨模块主线" in md
    assert "6 月总访客比 5 月增加。" in md
    assert "客单价同期下滑。" in md
