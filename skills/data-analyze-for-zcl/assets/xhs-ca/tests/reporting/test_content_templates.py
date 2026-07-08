"""领域内容模板库 (reusable ceramics content-creation templates) tests.

The old (Codex) report shipped a reusable content playbook — parameterized skeletons
like「开窑/上新 + 系列名 + 器型 + 时间」and「买前确认区:尺寸/容量/釉色随机/是否孤品」— which
merchants cited as directly actionable. This feature adds them as a static, reproducible
appendix: pure domain knowledge, carrying NO data and NO bare numbers (fill-in-the-blank
「占位」slots only), so it ships identically every run and never touches the numeric-trust
boundary. Host-neutral. Rendered as a 可复用内容模板 section before the cannot_say block.
"""
import re

from xhs_ceramics_analytics.reporting import content_templates as ct
from xhs_ceramics_analytics.reporting import narrative_render as nr


_HOST_TOKENS = ("claude", "codex", "gpt", "opus", "sonnet", "anthropic", "openai")


def test_library_is_nonempty_number_free_and_host_neutral():
    md = ct.content_templates_markdown()
    assert "## 可复用内容模板" in md
    # several distinct templates, each named
    assert len(ct.CONTENT_TEMPLATES) >= 6
    for tpl in ct.CONTENT_TEMPLATES:
        assert tpl.name and tpl.skeleton
    # NO bare numbers — the library is parameterized skeletons, never data
    assert not re.search(r"\d", md), "content templates must be digit-free"
    # host-neutral: no vendor/model names in shipped content
    low = md.lower()
    for tok in _HOST_TOKENS:
        assert tok not in low


def test_templates_render_into_bundle_before_cannot_say():
    bundle = {
        "facts_hash": "h",
        "headline": "标题。",
        "first_screen": {"spine": [], "panel": [], "actions": []},
        "sections": [{"section_id": "core", "title": "生意大盘", "claims": [], "curated_views": []}],
        "cannot_say": ["暂无法把订单归因到具体笔记。"],
    }
    md = nr.bundle_to_markdown(bundle, {"facts_hash": "h", "facts": {}})
    assert "## 可复用内容模板" in md
    assert "## 暂时答不了的问题" in md
    # the playbook precedes the open-questions caveat block
    assert md.index("## 可复用内容模板") < md.index("## 暂时答不了的问题")
    # a known template surfaces
    assert "买前确认区" in md


def test_templates_do_not_add_raw_html_blocks():
    # plain-markdown appendix — it must not introduce any raw-HTML passthrough sentinel
    bundle = {
        "facts_hash": "h",
        "first_screen": {"spine": [], "panel": [], "actions": []},
        "sections": [],
        "cannot_say": [],
    }
    md = nr.bundle_to_markdown(bundle, {"facts_hash": "h", "facts": {}})
    assert nr.RAW_HTML_OPEN not in md
