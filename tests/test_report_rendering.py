from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding, Subsection
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength
from xhs_ceramics_analytics.reporting.html import (
    _table_view,
    render_html,
    render_markdown_document_html,
)
from xhs_ceramics_analytics.reporting.markdown import render_markdown


def _priority_results():
    # Two actionable modules with different lever weights → deterministic ordering.
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


def test_markdown_renders_priority_table_ranked():
    md = render_markdown(_priority_results())
    assert "优先级" in md
    # Highest-lever module's weak link appears before the low-lever reference module.
    assert md.index("搜索承接是最弱环节") < md.index("基线稳定")
    assert "优先补详情页与承接内容。" in md


def test_markdown_priority_table_uses_four_human_columns():
    # B4/D2: the priority table is 4 plain-language columns; no 预期影响/可行性/证据 grid,
    # no statistical formula in the intro — just "从上到下就是本周先后顺序". The last
    # column is the 置信度 rating, NOT a band-composed "为什么值得先做" sentence (which
    # read verbatim-identical down every row on real data — a dead column).
    md = render_markdown(_priority_results())
    assert "| 先动顺序 | 哪个环节 | 具体先做什么 | 置信度 |" in md
    assert "为什么值得先做" not in md
    assert "从上到下就是本周先后顺序" in md
    assert "预期影响 × 可行性" not in md
    assert "| 预期影响 | 可行性 | 证据 |" not in md


def test_markdown_omits_priority_table_when_nothing_actionable():
    result = AnalysisResult(
        task_id="core_business_diagnosis",
        title="整体经营诊断",
        findings=[
            Finding(
                title="数据不足",
                conclusion="无法判断。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
            )
        ],
    )
    md = render_markdown([result])
    assert "先动哪里" not in md


def test_html_drops_technical_traceback_tier_and_meta_narrative():
    # #12/#8: the "技术追溯信息" tier and the meta-narrative prose that talks about
    # 程序模块/原始字段 are engineer-facing noise. HTML must not surface them; the
    # user table itself must still render (raw column names remain in the markdown
    # preview appendix, unaffected here).
    html = render_html(
        [
            AnalysisResult(
                task_id="core_business_diagnosis",
                title="经营诊断",
                findings=[
                    Finding(
                        title="店铺页转化漏斗诊断",
                        conclusion="点击→支付是最弱环节。",
                        evidence_strength=EvidenceStrength.WEAK,
                        key_numbers={"weakest_stage": "点击→支付"},
                        caveats=[],
                    )
                ],
                tables={
                    "shop_funnel_stages": [
                        {"funnel_stage": "访问→点击", "rate": 0.3, "denominator": 1000},
                        {"funnel_stage": "点击→支付", "rate": 0.1, "denominator": 300},
                    ]
                },
            )
        ]
    )
    assert "技术追溯" not in html
    assert "这里按业务问题分组" not in html
    assert "技术追溯信息里" not in html
    # the user-facing table still renders its Chinese column label + values
    assert "漏斗环节" in html
    assert "访问→点击" in html


def test_html_glossary_defines_new_and_returning_customers():
    # #16: 报告频繁用「新客/老客」，术语表必须给出挂钩首购窗口的定义。
    html = render_html(_priority_results())
    assert "新客" in html
    assert "老客" in html
    # 定义须点明首购窗口口径（365 天），与 real-export rollup 说明一致。
    assert "365" in html


def test_html_renders_priority_table_section():
    html = render_html(_priority_results())
    assert 'id="priority"' in html
    assert "优先补详情页与承接内容。" in html
    # Within the priority section itself, the high-lever module outranks the
    # low-lever reference module (guide highlights above use raw result order).
    start = html.index('id="priority"')
    section = html[start : html.index("</section>", start)]
    assert section.index("搜索承接是最弱环节") < section.index("基线稳定")


def test_html_priority_table_uses_four_human_columns():
    # B4/D2: 4 plain-language columns, no 预期影响/可行性 grid columns, human intro.
    # The 4th column is the 置信度 rating tag, not a band-composed "为什么值得先做"
    # sentence (identical down every row on real data — a dead column).
    html = render_html(_priority_results())
    start = html.index('id="priority"')
    section = html[start : html.index("</section>", start)]
    assert "先动顺序" in section
    assert "哪个环节" in section
    assert "具体先做什么" in section
    assert "<th>置信度</th>" in section
    assert "为什么值得先做" not in section
    assert "<th>预期影响</th>" not in section
    assert "<th>可行性</th>" not in section
    assert "从上到下就是本周先后顺序" in section


def test_html_promotes_how_to_read_to_first_class_section():
    # B4 / #2: "这份报告怎么读" is a first-class section reachable from the nav, no
    # longer a bento card buried inside 经营导读.
    html = render_html(_priority_results())
    assert 'id="how-to-read"' in html
    assert 'href="#how-to-read"' in html
    assert "这份报告怎么读" in html


def _weak_but_reliable_finding():
    # Observational (causal WEAK) yet backed by a large, precisely-measured sample.
    return Finding(
        title="发货前退款为主漏点",
        conclusion="发货前退款占比 61.9%。",
        evidence_strength=EvidenceStrength.WEAK,
        key_numbers={"dominant_share": 0.619},
        descriptive_reliability=DescriptiveReliability.HIGH,
    )


def test_markdown_folds_two_axes_into_single_reader_confidence():
    # Observational (causal WEAK) but large, precisely-measured sample → reliability
    # drives the single reader-facing 置信度 up to 高; the two statistical axes are
    # never shown side by side.
    md = render_markdown(
        [AnalysisResult(task_id="x", title="X", findings=[_weak_but_reliable_finding()])]
    )
    assert "置信度：高" in md
    assert "证据强度" not in md  # raw causal-axis label no longer surfaced
    assert "描述可靠性" not in md  # raw reliability-axis label no longer surfaced


def test_markdown_confidence_falls_back_to_softened_evidence_when_not_scored():
    finding = Finding(
        title="t",
        conclusion="c",
        evidence_strength=EvidenceStrength.WEAK,
    )
    md = render_markdown([AnalysisResult(task_id="x", title="X", findings=[finding])])
    # No reliability estimate → WEAK causal softens to 低, not the old "弱".
    assert "置信度：低" in md
    assert "证据强度" not in md
    assert "描述可靠性" not in md


def test_html_renders_single_confidence_chip_driven_by_reliability():
    html = render_html(
        [AnalysisResult(task_id="x", title="X", findings=[_weak_but_reliable_finding()])]
    )
    assert "置信度 高" in html
    assert "描述可靠性" not in html


def _full_finding():
    return Finding(
        title="退款率偏高",
        conclusion="鱼盘SKU退款率显著高于账号均值。",
        evidence_strength=EvidenceStrength.MEDIUM,
        key_numbers={"refund_rate_pay": 0.18},
        caveats=["样本较小"],
        recommended_action="在详情页加买前确认区。",
        evidence_reason="仅HTML应出现的原因。",
        confounders=["季节性退货高峰"],
        next_test="下周只改详情页做对照。",
        appendix="口径：退款率为支付时间口径。",
    )


def test_markdown_folds_evidence_reason_into_methodology_appendix():
    md = render_markdown([AnalysisResult(task_id="x", title="X", findings=[_full_finding()])])
    assert "可能的混淆因素：" in md
    assert "季节性退货高峰" in md
    assert "下一步验证：" in md
    assert "方法与附录：" in md
    assert "建议动作：" in md
    # 病根 C: evidence_reason (methodology) now folds into 方法与附录 alongside appendix,
    # in markdown too — the old "HTML-only" split is gone.
    assert "仅HTML应出现的原因。" in md
    assert "口径：退款率为支付时间口径。" in md


def test_markdown_renders_subsections_and_named_examples():
    result = AnalysisResult(
        task_id="x",
        title="X",
        findings=[],
        subsections=[Subsection(title="买前确认区", body="高退款SKU清单", findings=[_full_finding()])],
        named_examples=[{"label": "鱼盘12寸", "detail": "退款率0.18"}],
    )
    md = render_markdown([result])
    assert "#### 买前确认区" in md
    assert "高退款SKU清单" in md
    assert "命名示例：" in md
    assert "鱼盘12寸" in md


def test_render_markdown_uses_custom_title_when_provided():
    result = AnalysisResult(task_id="x", title="X", findings=[_full_finding()])
    default = render_markdown([result])
    named = render_markdown([result], title="千帆经营诊断报告")
    assert default.startswith("# 小红书账号分析报告\n")
    assert named.startswith("# 千帆经营诊断报告\n")
    assert "# 小红书账号分析报告" not in named


def test_render_html_uses_custom_title_when_provided():
    result = AnalysisResult(task_id="x", title="X", findings=[_full_finding()])
    default = render_html([result])
    named = render_html([result], title="千帆经营诊断报告")
    assert "<title>小红书账号分析报告</title>" in default
    assert "<title>千帆经营诊断报告</title>" in named
    assert "<h1>千帆经营诊断报告</h1>" in named


def test_render_markdown_uses_chinese_report_labels():
    report = render_markdown(
        [
            AnalysisResult(
                task_id="data_quality_check",
                title="Data Quality Check",
                findings=[
                    Finding(
                        title="Imported tables are available",
                        conclusion="Detected standard tables.",
                        evidence_strength=EvidenceStrength.STRONG,
                        key_numbers={"table_count": 7},
                        caveats=[],
                        recommended_action="Proceed with analysis.",
                    )
                ],
            )
        ]
    )
    assert "# 小红书账号分析报告" in report
    assert "置信度：高" in report
    assert "关键数字：" in report
    assert "建议动作：" in report
    assert "表格 `table_count`: 0 行" not in report
    assert "Evidence:" not in report
    assert "Proceed with analysis." in report


def test_markdown_key_numbers_carry_field_help():
    # #9/#18: markdown 与 HTML 对齐 —— 每个关键数字后跟中文口径说明，
    # 让读者无需查术语表就懂这个数字是什么。
    report = render_markdown(
        [
            AnalysisResult(
                task_id="core_business_diagnosis",
                title="经营诊断",
                findings=[
                    Finding(
                        title="增长归因（GMV 桥）",
                        conclusion="GMV 主要由流量拉动。",
                        evidence_strength=EvidenceStrength.WEAK,
                        key_numbers={"dominant_factor": "流量"},
                        caveats=[],
                    )
                ],
            )
        ]
    )
    # dominant_factor 的 help 文本应出现在关键数字行里（括号内）。
    assert "主导因子：流量（" in report
    assert "贡献最大" in report


def test_render_markdown_folds_evidence_reason_into_appendix():
    report = render_markdown(
        [
            AnalysisResult(
                task_id="product_opportunity_matrix",
                title="商品机会矩阵",
                findings=[
                    Finding(
                        title="SKU 机会已排序",
                        conclusion="青釉咖啡杯 单只适合继续测试。",
                        evidence_strength=EvidenceStrength.MEDIUM,
                        evidence_reason="SKU 销售可用但缺显式关联，先做优先级判断。",
                    )
                ],
            )
        ]
    )

    # No inline "可信度原因" label anymore; methodology folds into 方法与附录.
    assert "可信度原因" not in report
    assert "方法与附录：" in report
    assert "SKU 销售可用但缺显式关联，先做优先级判断。" in report


def test_cli_keeps_markdown_when_html_rendering_fails(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from xhs_ceramics_analytics.cli import app
    import xhs_ceramics_analytics.reporting.html as html_module

    def fail_html(_results, title=None, assistant=None):
        raise RuntimeError("chart dependency exploded")

    monkeypatch.setattr(html_module, "render_html", fail_html)
    output_dir = tmp_path / ".xhs-ceramics-analytics" / "outputs"
    output_dir.mkdir(parents=True)
    stale_html = output_dir / "data_quality_check.html"
    stale_html.write_text("stale html", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["run", "data_quality_check", "--project-root", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert (output_dir / "data_quality_check.md").exists()
    assert not stale_html.exists()
    errors = output_dir / "render_errors.txt"
    assert errors.exists()
    assert "chart dependency exploded" in errors.read_text(encoding="utf-8")
    assert "HTML rendering failed" in result.stderr


def test_render_markdown_uses_reader_friendly_sku_lift_title():
    report = render_markdown(
        [
            AnalysisResult(
                task_id="sku_counterfactual_lift",
                title="SKU Counterfactual Lift",
                findings=[
                    Finding(
                        title="笔记锚定的 SKU 销量响应窗口",
                        conclusion="已生成发布前后销量观察窗口。",
                        evidence_strength=EvidenceStrength.WEAK,
                    )
                ],
            )
        ]
    )

    assert "### SKU 销量响应" in report
    assert "反事实提升" not in report


def test_render_html_escapes_unsafe_markdown_content():
    html = render_html(
        [
            AnalysisResult(
                task_id="unsafe_content",
                title="Unsafe Content",
                findings=[
                    Finding(
                        title="Escaped content",
                        conclusion="<script>alert(1)</script>",
                        evidence_strength=EvidenceStrength.WEAK,
                    )
                ],
            )
        ]
    )

    assert "<!doctype html>" in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_render_markdown_document_html_wraps_custom_report():
    html = render_markdown_document_html(
        "\n".join(
            [
                "# 经营诊断报告",
                "",
                "## 关键结论",
                "",
                "自定义整合报告也要交付 HTML。",
                "",
                "| 模块 | 状态 |",
                "| --- | --- |",
                "| 店铺漏斗 | 可判断 |",
                "",
                "<script>alert(1)</script>",
            ]
        )
    )

    assert "<!doctype html>" in html
    assert "<title>经营诊断报告</title>" in html
    assert "<h1>经营诊断报告</h1>" in html
    assert "<h2>关键结论</h2>" in html
    assert "<table>" in html
    assert "<td>店铺漏斗</td>" in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_cli_render_html_converts_custom_markdown_report(tmp_path):
    from typer.testing import CliRunner

    from xhs_ceramics_analytics.cli import app

    markdown_path = tmp_path / "经营诊断报告.md"
    markdown_path.write_text("# 经营诊断报告\n\n自定义整合报告。\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["render-html", str(markdown_path)])

    html_path = tmp_path / "经营诊断报告.html"
    assert result.exit_code == 0
    assert html_path.exists()
    html = html_path.read_text(encoding="utf-8")
    assert "<!doctype html>" in html
    assert "<h1>经营诊断报告</h1>" in html
    assert f"Wrote report: {html_path}" in result.stdout


def test_cli_render_html_removes_stale_output_when_conversion_fails(tmp_path):
    from typer.testing import CliRunner

    from xhs_ceramics_analytics.cli import app

    stale_html = tmp_path / "经营诊断报告.html"
    stale_html.write_text("old report", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "render-html",
            str(tmp_path / "missing.md"),
            "--output",
            str(stale_html),
        ],
    )

    assert result.exit_code != 0
    assert not stale_html.exists()


def test_render_html_builds_reader_friendly_editorial_report():
    html = render_html(
        [
            AnalysisResult(
                task_id="product_opportunity_matrix",
                title="商品机会矩阵",
                findings=[
                    Finding(
                        title="SKU 机会已排序",
                        conclusion="青釉咖啡杯 单只 当前销售反馈最好，适合继续测试。",
                        evidence_strength=EvidenceStrength.MEDIUM,
                        key_numbers={"sku_count": 3, "top_sku_units": 7},
                        caveats=["需要显式 note-SKU 关联后，内容表现象限会更可靠。"],
                        recommended_action="下周继续给青釉咖啡杯 单只安排受控内容档期。",
                    )
                ],
                tables={
                    "product_opportunities": [
                        {
                            "sku_id": "s1",
                            "sku_name": "青釉咖啡杯 单只",
                            "units": 7,
                            "gmv": 903,
                        }
                    ]
                },
            )
        ]
    )

    assert 'class="report-shell"' in html
    assert "经营导读" in html
    assert "下周行动计划" in html
    assert "详细分析" in html
    assert "数据附录" in html
    assert "可以问分析助手的问题" in html
    assert "<details" in html
    assert "<pre>" not in html
    # CJK-aware system stacks (no external webfonts — the single-file report
    # forbids http(s) refs), driven by design tokens: Latin resolves to an
    # editorial serif for headings, CJK to Songti/思源宋体.
    assert "font-family: var(--font-sans);" in html
    assert "font-family: var(--font-serif);" in html
    assert "'PingFang SC'" in html
    assert "--line: #EAEAEA;" in html
    assert "border: 1px solid var(--line)" in html
    # Borders are tokenized, never hard-coded to the raw hex anymore.
    assert "1px solid #EAEAEA" not in html
    # radial-gradient is allowed (ambient light spots); linear-gradient is not.
    assert "linear-gradient" not in html
    assert "Lucide" not in html


def test_html_report_body_is_static_not_scroll_revealed():
    html = render_html(_priority_results())

    # Dense business reports should read like documents, not scroll choreography.
    # Keep interaction feedback, but do not attach scroll-driven reveal animation
    # to article-like report content such as finding cards and section panels.
    assert "animation-timeline: view()" not in html
    assert ".finding-card,\n      .chart,\n      .section-panel" not in html
    assert ".finding-card:hover" in html


def test_render_html_moves_evidence_reason_from_card_to_appendix():
    # 病根 A + C: the analyst-vocabulary "可信度原因" inline line is gone from the card;
    # the methodology text itself is not lost — it folds into 方法与附录 (appendix).
    html = render_html(
        [
            AnalysisResult(
                task_id="product_opportunity_matrix",
                title="商品机会矩阵",
                findings=[
                    Finding(
                        title="SKU 机会已排序",
                        conclusion="青釉咖啡杯 单只适合继续测试。",
                        evidence_strength=EvidenceStrength.MEDIUM,
                        evidence_reason=(
                            "SKU 销售数据可用，但缺少显式 note-SKU 关联，"
                            "所以适合先做商品优先级判断。"
                        ),
                    )
                ],
            )
        ]
    )

    assert "可信度原因" not in html  # inline analyst label gone
    assert "方法与附录" in html  # methodology folds into the appendix instead
    assert "SKU 销售数据可用，但缺少显式 note-SKU 关联" in html
    assert "置信度 中" in html  # MEDIUM causal, no reliability → softened to 中


def test_render_html_explains_all_evidence_levels_in_reader_guide():
    refused_heading = "不能" + "说明什么"
    html = render_html(
        [
            AnalysisResult(
                task_id="product_opportunity_matrix",
                title="商品机会矩阵",
                findings=[
                    Finding(
                        title="SKU 机会已排序",
                        conclusion="青釉咖啡杯 单只适合继续测试。",
                        evidence_strength=EvidenceStrength.MEDIUM,
                    )
                ],
            )
        ]
    )

    assert "这份报告怎么读" in html
    assert "高置信度" in html
    assert "中置信度" in html
    assert "低置信度" in html
    assert "暂不下定论" in html
    assert refused_heading not in html


def test_render_html_shows_chinese_labels_and_hides_machine_field_names():
    html = render_html(
        [
            AnalysisResult(
                task_id="product_opportunity_matrix",
                title="商品机会矩阵",
                findings=[
                    Finding(
                        title="SKU 机会已排序",
                        conclusion="青釉咖啡杯 单只 当前销售反馈最好。",
                        evidence_strength=EvidenceStrength.MEDIUM,
                        key_numbers={"sku_count": 3, "top_sku_units": 7},
                    )
                ],
                tables={
                    "product_opportunities": [
                        {
                            "sku_id": "s1",
                            "sku_name": "青釉咖啡杯 单只",
                            "units": 7,
                            "gmv": 903,
                            "opportunity_type": "sales_response_present",
                        }
                    ]
                },
            )
        ]
    )

    # #12: 读者视图只呈现中文列名与已翻译的取值；原始机器字段名(sku_id/
    # opportunity_type)不再叠一层「技术追溯」，只在 markdown 表格预览附录里留证。
    assert "销售件数" in html
    assert "销售额" in html
    assert "机会类型" in html
    assert "已有销售反馈" in html  # opportunity_type 取值翻译成业务语言
    assert "SKU 数量" in html  # key_numbers 字段标签
    # 原始机器列名彻底不在 HTML 泄漏——不作表头，也不作技术追溯脚注。
    assert "sku_id" not in html
    assert "opportunity_type" not in html
    assert "技术追溯" not in html


def test_render_html_prioritizes_business_findings_over_data_quality():
    html = render_html(
        [
            AnalysisResult(
                task_id="data_quality_check",
                title="数据质量检查",
                findings=[
                    Finding(
                        title="导入表已检查",
                        conclusion="底层表结构可用于继续分析。",
                        evidence_strength=EvidenceStrength.STRONG,
                    )
                ],
            ),
            AnalysisResult(
                task_id="product_opportunity_matrix",
                title="商品机会矩阵",
                findings=[
                    Finding(
                        title="SKU 机会已排序",
                        conclusion="青釉咖啡杯 单只销售反馈最好，适合优先测试。",
                        evidence_strength=EvidenceStrength.MEDIUM,
                    )
                ],
                tables={
                    "product_opportunities": [
                        {
                            "sku_name": "青釉咖啡杯 单只",
                            "units": 7,
                            "gmv": 903,
                            "opportunity_type": "sales_response_present",
                        }
                    ]
                },
            ),
        ]
    )

    guide = html.split('id="actions"', maxsplit=1)[0]
    assert "商品机会" in guide
    assert "青釉咖啡杯 单只" in guide
    assert "导入表已检查" not in guide


def test_render_html_groups_analysis_by_business_question():
    html = render_html(
        [
            AnalysisResult(
                task_id="product_opportunity_matrix",
                title="商品机会矩阵",
                findings=[
                    Finding(
                        title="SKU 机会已排序",
                        conclusion="商品机会已经按销售反馈排序。",
                        evidence_strength=EvidenceStrength.MEDIUM,
                    )
                ],
            ),
            AnalysisResult(
                task_id="copy_angle_effect",
                title="文案角度效果",
                findings=[
                    Finding(
                        title="文案角度已排序",
                        conclusion="送礼角度表现较好。",
                        evidence_strength=EvidenceStrength.WEAK,
                    )
                ],
            ),
            AnalysisResult(
                task_id="comment_demand_mining",
                title="评论需求挖掘",
                findings=[
                    Finding(
                        title="评论需求分组已提取",
                        conclusion="用户主要在问价格和购买入口。",
                        evidence_strength=EvidenceStrength.WEAK,
                    )
                ],
            ),
            AnalysisResult(
                task_id="weekly_experiment_matrix",
                title="每周实验矩阵",
                findings=[
                    Finding(
                        title="七天实验计划已生成",
                        conclusion="下周可以按矩阵执行。",
                        evidence_strength=EvidenceStrength.WEAK,
                    )
                ],
            ),
            AnalysisResult(
                task_id="data_quality_check",
                title="数据质量检查",
                findings=[],
            ),
        ]
    )

    # #19: 报告按 6 个业务主题域分组，域标题即 domains.DOMAINS 的标题（不含冒号副标）。
    assert "商品结构" in html
    assert "流量与内容" in html
    assert "用户与需求" in html
    assert "实验与下周行动" in html
    assert "Module 1" not in html
    assert "data_quality_check" not in html


def _two_refund_results():
    return [
        AnalysisResult(
            task_id="refund_root_cause_diagnosis",
            title="退款根因诊断",
            findings=[
                Finding(
                    title="发货前退款为主漏点",
                    conclusion="发货前退款占比 61.9%。",
                    evidence_strength=EvidenceStrength.WEAK,
                    descriptive_reliability=DescriptiveReliability.HIGH,
                    recommended_action="核对发货时效与库存口径。",
                )
            ],
        ),
        AnalysisResult(
            task_id="refund_structure_diagnosis",
            title="退款结构诊断",
            findings=[
                Finding(
                    title="退款集中在两个 SKU",
                    conclusion="两个 SKU 贡献大部分退款。",
                    evidence_strength=EvidenceStrength.WEAK,
                    descriptive_reliability=DescriptiveReliability.LOW,
                    recommended_action="复核这两个 SKU 的详情页与实物一致性。",
                )
            ],
        ),
    ]


def test_render_html_places_both_refund_modules_under_one_domain():
    # #19: 退款结构与退款根因合并进「退款与售后」同一个域，不再各自散落。
    html = render_html(_two_refund_results())
    # Scope to the analysis body — the hero copy also lists domain names in prose.
    analysis = html.split('id="analysis"', 1)[1].split('id="appendix"', 1)[0]
    assert "退款与售后" in analysis
    # exactly one 退款与售后 domain panel heading, and both refund modules live inside it.
    assert analysis.count("<h3>退款与售后</h3>") == 1
    assert "退款根因诊断" in analysis
    assert "退款结构诊断" in analysis


def test_render_html_folds_secondary_domain_results_under_one_headline():
    # #19/#2: 域内只留一条 headline 大卡，其余折进 <details class="domain-more">，
    # 读者先看该域最该动的那条，展开才看其余。
    html = render_html(_two_refund_results())
    assert 'class="domain-more"' in html
    # headline 大卡恰一条：域内第二个模块进折叠区。
    assert html.count('class="result-block result-headline"') == 1


def test_render_html_drops_reshoot_repost_highlight_card():
    # #2: 重拍/重发是弱证据假设，不该被抬成经营导读的高亮大卡。
    html = render_html(
        [
            AnalysisResult(
                task_id="reshoot_repost_candidates",
                title="重拍与重发候选",
                findings=[
                    Finding(
                        title="高收藏笔记重拍候选已排序",
                        conclusion="候选笔记已排序。",
                        evidence_strength=EvidenceStrength.WEAK,
                    )
                ],
                tables={
                    "reshoot_candidates": [
                        {
                            "title": "青釉杯上手体验",
                            "collect_rate": 0.05,
                            "reason": "收藏率高但读量偏低",
                        }
                    ]
                },
            )
        ]
    )
    assert "重拍机会：先复用「" not in html


def test_timeseries_table_forced_collapsed_even_when_short():
    # #17: 时序趋势表(表名 _trend 结尾,或首列是日期)读者要看的是折线图,不是逐行数字。
    # 即便行数 <10,也强制折叠,让图表先行,不再默认展开一张长条趋势表。
    trend_rows = [{"stage": "读", "rate": 0.5}, {"stage": "赞", "rate": 0.3}]
    assert _table_view("refund_rate_trend", trend_rows)["open"] is False

    dated_rows = [{"date": "2026-04-01", "gmv": 100.0}, {"date": "2026-04-02", "gmv": 120.0}]
    assert _table_view("business_daily", dated_rows)["open"] is False

    # 对照:普通短表照旧默认展开。
    plain_rows = [{"carrier": "note", "gmv": 100.0}]
    assert _table_view("carrier_structure", plain_rows)["open"] is True


def test_render_html_user_table_view_omits_technical_columns_entirely():
    html = render_html(
        [
            AnalysisResult(
                task_id="weekly_experiment_matrix",
                title="每周实验矩阵",
                findings=[],
                tables={
                    "experiment_plan": [
                        {
                            "date": "2026-07-01",
                            "slot_time": "09:00",
                            "sku_id": "s1",
                            "sku_name": "青釉咖啡杯 单只",
                            "copy_angle": "gift",
                            "experiment_seed": "2026-07-01-09:00-s1-gift",
                            "success_metric": "collect_rate",
                        }
                    ]
                },
            )
        ]
    )

    # #12: HTML 只保留用户视图；技术列(experiment_seed 等机器标识)不再叠一层
    # 「技术追溯信息」，在 HTML 里彻底不呈现，只在 markdown 表格预览附录里留证。
    assert "用户视图" in html
    assert "共 1 行，当前展示 1 行" in html
    assert "技术追溯信息" not in html
    # 业务列名与已翻译取值照常呈现
    assert "青釉咖啡杯 单只" in html
    assert "送礼角度" in html  # copy_angle=gift 翻译成业务语言
    # 技术列的中文标签与原始 seed 值都不再进入 HTML
    assert "实验标识" not in html
    assert "2026-07-01-09:00-s1-gift" not in html


def test_render_html_formats_numbers_for_business_readers():
    html = render_html(
        [
            AnalysisResult(
                task_id="reshoot_repost_candidates",
                title="重拍与重发候选",
                findings=[
                    Finding(
                        title="高收藏笔记重拍候选已排序",
                        conclusion="候选笔记已经排序。",
                        evidence_strength=EvidenceStrength.WEAK,
                        key_numbers={
                            "collect_rate": 0.041666666,
                            "relative_lift": -0.333333333,
                            "gmv": 903.0,
                            "needs_more_data": False,
                        },
                    )
                ],
                tables={
                    "reshoot_candidates": [
                        {
                            "rank": 1,
                            "title": "青釉杯上手体验",
                            "reads": 120,
                            "collects": 5,
                            "collect_rate": 0.041666666,
                            "read_gap_to_max": 0.333333333,
                        }
                    ]
                },
            )
        ]
    )

    assert "4.17%" in html
    assert "下降 33.3%" in html
    assert "903" in html
    assert "否" in html
    assert "0.041666666" not in html
    assert "0.333333333" not in html


def test_render_html_assistant_name_defaults_neutral_and_is_overridable():
    result = AnalysisResult(task_id="x", title="X", findings=[])
    # default: no vendor brand leaks into reader-facing copy
    default_html = render_html([result])
    assert "可以问分析助手的问题" in default_html
    assert "Codex" not in default_html
    # override flows into every reader-facing spot (nav + heading + lede)
    named_html = render_html([result], assistant="小助手")
    assert "可以问小助手的问题" in named_html
    assert "小助手 追问" in named_html
    assert "分析助手" not in named_html


def test_render_html_opens_short_tables_and_collapses_longer_ones():
    short = AnalysisResult(
        task_id="x",
        title="X",
        findings=[],
        tables={"t": [{"a": i} for i in range(9)]},  # < 10 rows → open
    )
    # exactly 10 rows is the boundary: readable but no longer auto-opened
    boundary = AnalysisResult(
        task_id="y",
        title="Y",
        findings=[],
        tables={"t": [{"a": i} for i in range(10)]},
    )
    assert '<details class="table-details" open>' in render_html([short])
    boundary_html = render_html([boundary])
    assert '<details class="table-details" open>' not in boundary_html
    assert '<details class="table-details">' in boundary_html


def test_render_html_dynamic_codex_questions_use_report_content():
    html = render_html(
        [
            AnalysisResult(
                task_id="product_opportunity_matrix",
                title="商品机会矩阵",
                findings=[],
                tables={
                    "product_opportunities": [
                        {
                            "sku_name": "青釉咖啡杯 单只",
                            "units": 7,
                            "gmv": 903,
                        }
                    ]
                },
            ),
            AnalysisResult(
                task_id="copy_angle_effect",
                title="文案角度效果",
                findings=[],
                tables={
                    "copy_effects": [
                        {
                            "copy_angle": "gift",
                            "notes": 3,
                            "avg_reads": 260,
                            "avg_collects": 20,
                        }
                    ]
                },
            ),
        ]
    )

    assert "为什么「青釉咖啡杯 单只」应该优先测试？" in html
    assert "「送礼角度」文案角度下周应该怎么测？" in html


def test_render_html_labels_paid_traffic_fields():
    result = AnalysisResult(
        task_id="paid_traffic_efficiency",
        title="投放效率分析",
        findings=[
            Finding(
                title="投放消耗和投产效率已汇总",
                conclusion="已汇总 1 个投放对象。",
                evidence_strength=EvidenceStrength.MEDIUM,
                key_numbers={"spend": 120, "roas_calc": 6},
                recommended_action="优先小幅增加高投产对象预算。",
            )
        ],
        tables={
            "paid_traffic_efficiency": [
                {
                    "campaign_name_optional": "青釉杯投放",
                    "spend": 120,
                    "impressions": 6000,
                    "clicks": 180,
                    "ctr_calc": 0.03,
                    "cpc_calc": 0.6667,
                    "gmv_optional": 720,
                    "roas_calc": 6,
                    "budget_action": "increase",
                }
            ]
        },
    )

    html = render_html([result])

    assert "投放消耗" in html
    assert "点击率" in html
    assert "投产比" in html
    assert "增加预算" in html


def test_evidence_chart_lands_in_how_to_read_section():
    html = render_html(
        [
            AnalysisResult(
                task_id="cover_style_effect",
                title="封面风格效果",
                findings=[
                    Finding(
                        title="封面风格效果已比较",
                        conclusion="生活方式类封面表现更好。",
                        evidence_strength=EvidenceStrength.MEDIUM,
                    )
                ],
                tables={
                    "cover_effects": [
                        {"composition_type": "flatlay", "notes": 5,
                         "avg_reads": 1200.0, "avg_collects": 48.0},
                        {"composition_type": "lifestyle", "notes": 4,
                         "avg_reads": 800.0, "avg_collects": 60.0},
                    ]
                },
            )
        ]
    )
    start = html.index('id="how-to-read"')
    section = html[start : html.index("</section>", start)]
    assert 'class="chart"' in section
    assert "<svg" in section


def test_task_charts_land_in_analysis_section():
    html = render_html(
        [
            AnalysisResult(
                task_id="cover_style_effect",
                title="封面风格效果",
                findings=[
                    Finding(
                        title="封面风格效果已比较",
                        conclusion="生活方式类封面表现更好。",
                        evidence_strength=EvidenceStrength.MEDIUM,
                    )
                ],
                tables={
                    "cover_effects": [
                        {"composition_type": "flatlay", "notes": 5,
                         "avg_reads": 1200.0, "avg_collects": 48.0},
                        {"composition_type": "lifestyle", "notes": 4,
                         "avg_reads": 800.0, "avg_collects": 60.0},
                    ]
                },
            )
        ]
    )
    analysis = html.split('id="analysis"', 1)[1]
    assert 'class="chart"' in analysis


def test_html_report_has_no_script_or_external_refs():
    html = render_html(
        [
            AnalysisResult(
                task_id="cover_style_effect",
                title="封面风格效果",
                findings=[
                    Finding(
                        title="封面风格效果已比较",
                        conclusion="生活方式类封面表现更好。",
                        evidence_strength=EvidenceStrength.MEDIUM,
                    )
                ],
                tables={
                    "cover_effects": [
                        {"composition_type": "flatlay", "notes": 5,
                         "avg_reads": 1200.0, "avg_collects": 48.0},
                        {"composition_type": "lifestyle", "notes": 4,
                         "avg_reads": 800.0, "avg_collects": 60.0},
                    ]
                },
            )
        ]
    )
    assert "<script" not in html
    assert "http://" not in html
    assert "https://" not in html
    assert "src=" not in html


def test_section_keeps_table_when_a_chart_builder_raises(monkeypatch):
    from xhs_ceramics_analytics.reporting import charts

    def boom(*args, **kwargs):
        raise RuntimeError("chart exploded")

    monkeypatch.setitem(charts._BUILDERS, "cover_style_effect", boom)

    html = render_html(
        [
            AnalysisResult(
                task_id="cover_style_effect",
                title="封面风格效果",
                findings=[
                    Finding(
                        title="封面风格效果已比较",
                        conclusion="生活方式类封面表现更好。",
                        evidence_strength=EvidenceStrength.MEDIUM,
                    )
                ],
                tables={
                    "cover_effects": [
                        {"composition_type": "flatlay", "notes": 5,
                         "avg_reads": 1200.0, "avg_collects": 48.0},
                        {"composition_type": "lifestyle", "notes": 4,
                         "avg_reads": 800.0, "avg_collects": 60.0},
                    ]
                },
            )
        ]
    )
    # the render still completes and the drill-down table for the section survives
    assert "封面风格效果" in html
    # assert on the actual rendered <details> element, not the bare substring
    # "table-details" (which also appears in the template's static CSS and would be
    # tautological); its presence proves the section's drill-down table survived.
    # Match the opening tag prefix — small tables render it with an ``open`` attribute.
    assert '<details class="table-details"' in html


def test_html_renders_all_contract_elements():
    result = AnalysisResult(
        task_id="x",
        title="X",
        findings=[_full_finding()],
        subsections=[Subsection(title="买前确认区", body="高退款SKU清单", findings=[_full_finding()])],
        named_examples=[{"label": "鱼盘12寸", "detail": "退款率0.18"}],
    )
    html = render_html([result])
    assert "置信度 中" in html               # single reader confidence chip (element 4)
    assert "仅HTML应出现的原因。" in html     # evidence_reason folds into 方法与附录
    assert "方法与附录" in html
    assert "可能的混淆因素" in html          # element 5
    assert "下一步验证：" in html            # element 7
    assert "方法与附录：" in html            # element 8
    assert "买前确认区" in html              # subsection
    assert "命名示例" in html and "鱼盘12寸" in html


def test_html_omits_empty_contract_fields():
    lean = Finding(title="t", conclusion="c", evidence_strength=EvidenceStrength.WEAK)
    html = render_html([AnalysisResult(task_id="x", title="X", findings=[lean])])
    assert "可能的混淆因素" not in html
    assert "下一步验证：" not in html
    assert "方法与附录：" not in html
    # a finding with no tables renders no drill-down element (the substring
    # "table-details" alone appears in the static CSS, so assert on the element)
    assert '<details class="table-details"' not in html


def test_named_examples_render_consistently_across_markdown_and_html():
    # markdown accepts label/name and detail/note synonyms; the HTML renderer must
    # accept the same keys, otherwise name/note-authored examples silently vanish
    # from the canonical HTML report.
    result = AnalysisResult(
        task_id="x",
        title="X",
        findings=[],
        named_examples=[{"name": "鱼盘12寸", "note": "退款率0.18"}],
    )
    md = render_markdown([result])
    html = render_html([result])
    for text in ("鱼盘12寸", "退款率0.18"):
        assert text in md
        assert text in html


def _dq_and_core():
    dq = AnalysisResult(
        task_id="data_quality_check",
        title="数据质量检查",
        findings=[
            Finding(
                title="导入完整",
                conclusion="标准表齐全。",
                evidence_strength=EvidenceStrength.STRONG,
            )
        ],
    )
    core = AnalysisResult(
        task_id="core_business_diagnosis",
        title="核心经营结构诊断",
        findings=[
            Finding(
                title="整体经营快照与趋势",
                conclusion="GMV环比走弱。",
                evidence_strength=EvidenceStrength.MEDIUM,
            )
        ],
    )
    return dq, core


def test_data_quality_section_renders_last_in_markdown():
    # Pass data-quality FIRST; the compositor must still sink it below the
    # business diagnosis so the reader hits conclusions before the data appendix.
    dq, core = _dq_and_core()
    md = render_markdown([dq, core])
    # 模块降为 ###；数据质量落在末尾附录域，业务结论在前。
    assert md.index("### 核心经营结构诊断") < md.index("### 数据质量检查")
    assert md.index("## 生意大盘") < md.index("附录：数据质量与口径说明")


def test_markdown_groups_modules_under_business_domains():
    # #19: markdown 与 HTML 用同一份域分组——域标题是一级 ##，模块降为 ###，
    # 退款两模块在「退款与售后」同一域下。
    results = [
        AnalysisResult(
            task_id="refund_root_cause_diagnosis",
            title="退款根因诊断",
            findings=[
                Finding(
                    title="发货前退款为主漏点",
                    conclusion="发货前退款占比高。",
                    evidence_strength=EvidenceStrength.WEAK,
                )
            ],
        ),
        AnalysisResult(
            task_id="refund_structure_diagnosis",
            title="退款结构诊断",
            findings=[
                Finding(
                    title="退款集中在两个 SKU",
                    conclusion="两个 SKU 贡献大部分退款。",
                    evidence_strength=EvidenceStrength.WEAK,
                )
            ],
        ),
        AnalysisResult(
            task_id="core_business_diagnosis",
            title="整体经营诊断",
            findings=[
                Finding(
                    title="GMV 走势",
                    conclusion="GMV 稳定。",
                    evidence_strength=EvidenceStrength.MEDIUM,
                )
            ],
        ),
    ]
    md = render_markdown(results)
    assert "## 生意大盘" in md
    assert "## 退款与售后" in md
    # 生意大盘域排在退款域之前（DOMAINS 顺序）。
    assert md.index("## 生意大盘") < md.index("## 退款与售后")
    # 两个退款模块都在退款域标题之后、下一个域之前。
    refund_start = md.index("## 退款与售后")
    tail = md[refund_start:]
    assert "### 退款根因诊断" in tail
    assert "### 退款结构诊断" in tail
    # 模块降为 ###，不再是一级 ## 标题（用换行锚定，避免 ### 命中 ## 子串）。
    assert "\n## 退款根因诊断" not in md
    assert "\n### 退款根因诊断" in md


def test_data_quality_is_the_final_html_group_and_diagnosis_leads():
    from xhs_ceramics_analytics.reporting.html import _analysis_groups, _result_view

    results = [
        AnalysisResult(task_id="data_quality_check", title="数据质量检查", findings=[]),
        AnalysisResult(task_id="core_business_diagnosis", title="整体经营诊断", findings=[]),
    ]
    views = [_result_view(result) for result in results]
    groups = _analysis_groups(results, views)
    titles = [str(group["title"]) for group in groups]
    # 业务域领先（生意大盘），数据质量附录收尾。
    assert titles[0] == "生意大盘"
    assert titles[-1].startswith("附录")
    # core_business 落在首个域的 headline，data_quality 落在附录组。
    assert groups[0]["headline_result"]["task_id"] == "core_business_diagnosis"
    appendix = groups[-1]
    appendix_views = [appendix["headline_result"], *appendix["secondary_results"]]
    appendix_ids = {v["task_id"] for v in appendix_views if v}
    assert "data_quality_check" in appendix_ids
