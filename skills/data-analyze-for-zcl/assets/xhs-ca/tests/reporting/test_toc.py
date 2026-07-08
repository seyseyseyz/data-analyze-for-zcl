"""Persistent (常驻) pure-CSS anchored table of contents shared by both HTML reports.

The single-file HTML contract forbids ``<script>`` (see
``test_report_rendering.test_html_report_has_no_script_or_external_refs``), so the
TOC is CSS-only: a sticky rail (a left column on wide viewports, a top strip on
narrow) plus in-page anchor links and ``scroll-behavior: smooth``. There is no
scroll-spy / active-section highlighting — that would require JavaScript, which
the single-file guarantee bans. ``build_toc_nav`` is a pure, never-raise builder
consumed by BOTH the fact-layer (Jinja) and narrative (hand-rolled) renderers.
"""
import re

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength
from xhs_ceramics_analytics.reporting import toc
from xhs_ceramics_analytics.reporting.html import (
    render_html,
    render_markdown_document_html,
)

_BANNED_HOST_TOKENS = ("claude", "codex", "gpt", "opus", "sonnet", "anthropic", "openai")


def _results():
    """Two modules: one domain-mapped (→ an analysis group) + one baseline, both
    actionable so the fact layer also emits the priority table."""
    return [
        AnalysisResult(
            task_id="account_baseline",
            title="账号基线",
            findings=[
                Finding(
                    title="基线稳定",
                    conclusion="账号发布节奏稳定。",
                    evidence_strength=EvidenceStrength.STRONG,
                    recommended_action="维持当前节奏。",
                    descriptive_reliability=DescriptiveReliability.HIGH,
                )
            ],
        ),
        AnalysisResult(
            task_id="core_business_diagnosis",
            title="整体经营诊断",
            findings=[
                Finding(
                    title="搜索承接是最弱环节",
                    conclusion="搜索点击多但成交少。",
                    evidence_strength=EvidenceStrength.STRONG,
                    recommended_action="优先补详情页与承接内容。",
                    descriptive_reliability=DescriptiveReliability.HIGH,
                )
            ],
        ),
    ]


# --- shared builder: nesting, escaping, never-raise --------------------------


def test_build_toc_nav_nests_sub_entries_under_preceding_top():
    nav = toc.build_toc_nav(
        [
            {"level": 2, "anchor": "a", "label": "大节A"},
            {"level": 3, "anchor": "a1", "label": "子节A1"},
            {"level": 3, "anchor": "a2", "label": "子节A2"},
            {"level": 2, "anchor": "b", "label": "大节B"},
        ]
    )
    assert 'class="toc-rail"' in nav
    assert 'href="#a"' in nav and 'href="#b"' in nav
    assert 'href="#a1"' in nav and 'href="#a2"' in nav
    assert 'class="toc-sub"' in nav
    assert "toc-link--top" in nav and "toc-link--sub" in nav
    # both A's subs render before top-level B (real nesting, not a flat list)
    assert nav.index("子节A2") < nav.index("大节B")


def test_build_toc_nav_escapes_labels_and_anchors():
    nav = toc.build_toc_nav([{"level": 2, "anchor": "x", "label": "<script>x</script>"}])
    assert "<script>x</script>" not in nav
    assert "&lt;script&gt;" in nav


def test_build_toc_nav_empty_returns_empty_string():
    assert toc.build_toc_nav([]) == ""


def test_build_toc_nav_garbage_never_raises():
    for bad in [None, "nope", 42, [None, 7, {}], [{"level": 3, "anchor": "", "label": ""}]]:
        assert isinstance(toc.build_toc_nav(bad), str)


def test_build_toc_nav_orphan_sub_is_promoted_to_top():
    # a level-3 with no preceding level-2 must still surface (defensive), not vanish
    nav = toc.build_toc_nav([{"level": 3, "anchor": "s", "label": "孤儿"}])
    assert 'href="#s"' in nav
    assert "孤儿" in nav


def test_toc_style_is_pure_css_no_script_or_external_refs():
    style = toc.TOC_STYLE
    assert "<script" not in style
    assert "http://" not in style and "https://" not in style
    assert "src=" not in style
    # borders reference the shared token, never the raw hex (guardrail parity)
    assert "1px solid #EAEAEA" not in style
    assert "var(--line)" in style
    # persistence + anchored-scroll primitives are present
    assert "position: sticky" in style
    assert "scroll-behavior: smooth" in style
    assert "scroll-margin-top" in style
    # host-neutral: no vendor name leaks into shipped CSS
    lowered = style.lower()
    for banned in _BANNED_HOST_TOKENS:
        assert banned not in lowered


# --- narrative renderer ------------------------------------------------------


def test_narrative_html_has_persistent_toc_rail_with_resolving_anchors():
    md = "\n".join(
        [
            "# 报告标题",
            "",
            "## 生意大盘",
            "",
            "正文一。",
            "",
            "### GMV 增长拆解",
            "",
            "正文二。",
            "",
            "## 流量与内容",
            "",
            "正文三。",
        ]
    )
    html = render_markdown_document_html(md)
    assert 'class="toc-rail"' in html
    assert "生意大盘" in html and "流量与内容" in html
    # a level-3 heading becomes a nested sub-entry
    assert 'class="toc-sub"' in html
    # every TOC anchor resolves to a heading id actually present in the document
    anchors = set(re.findall(r'href="#([^"]+)"', html))
    heading_ids = set(re.findall(r'<h[1-6] id="([^"]+)"', html))
    assert anchors
    assert anchors <= heading_ids


def test_narrative_html_toc_is_persistent_and_smooth_with_no_script():
    html = render_markdown_document_html("# T\n\n## 一\n\n正文。\n")
    assert "position: sticky" in html
    assert "scroll-behavior: smooth" in html
    assert "<script" not in html
    assert "http://" not in html and "https://" not in html


def test_narrative_html_without_subheadings_degrades_without_rail():
    # only an h1 title, no h2/h3 → nothing to index; doc still renders, no empty rail
    html = render_markdown_document_html("# 只有标题\n\n一段正文，没有二级标题。\n")
    assert "一段正文" in html
    assert 'class="toc-rail"' not in html


def test_narrative_html_toc_label_strips_markdown_emphasis():
    html = render_markdown_document_html("# T\n\n## **重点**小节\n\n正文。\n")
    # the rail label is clean text, not literal markdown asterisks
    nav = html.split("</nav>", 1)[0]
    assert "重点小节" in nav
    assert "**" not in nav


def test_narrative_html_toc_label_preserves_literal_asterisk_content():
    # a lone '*' (multiplication / dimension) is genuine content, not emphasis:
    # it must survive in the rail exactly as in the rendered heading body.
    html = render_markdown_document_html("# T\n\n## 定价 3*2 元的策略\n\n正文。\n")
    nav = html.split("</nav>", 1)[0]
    assert "定价 3*2 元的策略" in nav


def test_narrative_html_toc_label_uses_inline_code_text_not_backticks():
    # inline code renders as its inner text in the rail (mirroring the <code> body),
    # and a lone backtick in content is never silently deleted.
    html = render_markdown_document_html("# T\n\n## 用 `note_id` 字段\n\n正文。\n")
    nav = html.split("</nav>", 1)[0]
    assert "用 note_id 字段" in nav
    assert "`" not in nav


# --- fact-layer renderer -----------------------------------------------------


def test_fact_layer_has_persistent_toc_rail():
    html = render_html(_results())
    assert 'class="toc-rail"' in html
    assert 'href="#how-to-read"' in html
    assert 'href="#analysis"' in html
    assert "position: sticky" in html
    # the old scrolling topbar nav is gone
    assert 'class="toc"' not in html


def test_fact_layer_toc_lists_analysis_domains_as_sub_entries():
    html = render_html(_results())
    assert 'class="toc-sub"' in html
    sub_anchors = re.findall(r'toc-link--sub" href="#([^"]+)"', html)
    assert sub_anchors  # at least one domain sub-entry
    for anchor in sub_anchors:
        assert anchor.startswith("analysis-")
        assert f'id="{anchor}"' in html  # resolves to a real section-panel


def test_fact_layer_toc_includes_priority_and_assistant_label():
    html = render_html(_results(), assistant="小助手")
    assert 'href="#priority"' in html
    assert "小助手 追问" in html
    assert "分析助手" not in html


def test_fact_layer_toc_keeps_no_script_and_tokenized_borders():
    html = render_html(_results())
    assert "<script" not in html
    assert "http://" not in html and "https://" not in html
    assert "1px solid #EAEAEA" not in html


# --- host neutrality: no vendor token in the SHIPPED HTML --------------------
# The CSS-string guard (test_toc_style_is_pure_css_...) only covers TOC_STYLE.
# These assert the *rendered* single-file reports carry no host token anywhere —
# markup, class names, or copy. This is the regression net for leaks like the
# legacy ``codex-list`` CSS class that shipped in every fact-layer report. The
# default assistant label ("分析助手") is used because an assistant override is
# explicit user input, not something we control.


def test_fact_layer_rendered_html_is_host_neutral():
    lowered = render_html(_results()).lower()
    for banned in _BANNED_HOST_TOKENS:
        assert banned not in lowered, f"host token {banned!r} leaked into fact-layer HTML"


def test_narrative_rendered_html_is_host_neutral():
    md = "# 报告标题\n\n## 生意大盘\n\n正文一。\n\n### 拆解\n\n正文二。\n"
    lowered = render_markdown_document_html(md).lower()
    for banned in _BANNED_HOST_TOKENS:
        assert banned not in lowered, f"host token {banned!r} leaked into narrative HTML"
