from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding, Subsection
from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.reporting.html import (
    render_html,
    render_markdown_document_html,
)
from xhs_ceramics_analytics.reporting.markdown import render_markdown


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


def test_markdown_renders_seven_contract_elements_not_evidence_reason():
    md = render_markdown([AnalysisResult(task_id="x", title="X", findings=[_full_finding()])])
    assert "可能的混淆因素：" in md
    assert "季节性退货高峰" in md
    assert "下一步验证：" in md
    assert "方法与附录：" in md
    assert "建议动作：" in md
    # evidence_reason stays HTML-only:
    assert "仅HTML应出现的原因。" not in md


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
    assert "证据强度：强" in report
    assert "关键数字：" in report
    assert "建议动作：" in report
    assert "表格 `table_count`: 0 行" not in report
    assert "Evidence:" not in report
    assert "Proceed with analysis." in report


def test_render_markdown_does_not_render_html_only_evidence_reason():
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
                        evidence_reason="只给 HTML 报告展示的可信度原因。",
                    )
                ],
            )
        ]
    )

    assert "可信度原因" not in report
    assert "只给 HTML 报告展示的可信度原因" not in report


def test_cli_keeps_markdown_when_html_rendering_fails(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from xhs_ceramics_analytics.cli import app
    import xhs_ceramics_analytics.reporting.html as html_module

    def fail_html(_results):
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

    assert "## SKU 销量响应" in report
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
    assert "可以问 Codex 的问题" in html
    assert "<details" in html
    assert "<pre>" not in html
    assert (
        "font-family: 'SF Pro Display', 'Geist Sans', 'Helvetica Neue', 'Switzer', sans-serif;"
        in html
    )
    assert "border: 1px solid #EAEAEA" in html
    assert "linear-gradient" not in html
    assert "Lucide" not in html


def test_render_html_shows_evidence_reason_for_each_finding():
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
                        evidence_reason=(
                            "SKU 销售数据可用，但缺少显式 note-SKU 关联，"
                            "所以适合先做商品优先级判断。"
                        ),
                    )
                ],
            )
        ]
    )

    assert "可信度原因" in html
    assert "SKU 销售数据可用，但缺少显式 note-SKU 关联" in html
    assert refused_heading not in html


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
    assert "高可信度" in html
    assert "中可信度" in html
    assert "低可信度" in html
    assert "不可判断" in html
    assert refused_heading not in html


def test_render_html_explains_machine_field_names_for_non_experts():
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

    assert "SKU 编号" in html
    assert "具体商品规格的内部编号" in html
    assert "<code>sku_id</code>" in html
    assert "销售件数" in html
    assert "销售额" in html
    assert "机会类型" in html
    assert "已有销售反馈" in html
    assert "SKU 数量" in html
    assert "<th>sku_id</th>" not in html


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

    assert "商品：卖什么" in html
    assert "内容：发什么" in html
    assert "用户需求：用户在问什么" in html
    assert "实验：下周怎么验证" in html
    assert "数据可信度" in html
    assert "Module 1" not in html
    assert "data_quality_check" not in html


def test_render_html_uses_user_table_view_and_technical_details():
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

    user_view = html.split("技术追溯信息", maxsplit=1)[0]
    assert "用户视图" in html
    assert "共 1 行，当前展示 1 行" in html
    assert "技术追溯信息" in html
    assert "青釉咖啡杯 单只" in user_view
    assert "送礼角度" in user_view
    assert "实验标识" not in user_view
    assert "2026-07-01-09:00-s1-gift" in html


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


def test_evidence_chart_lands_in_guide_section():
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
    guide = html.split('id="guide"', 1)[1].split('id="actions"', 1)[0]
    assert 'class="chart"' in guide
    assert "<svg" in guide


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


def test_html_renders_all_eight_contract_elements():
    result = AnalysisResult(
        task_id="x",
        title="X",
        findings=[_full_finding()],
        subsections=[Subsection(title="买前确认区", body="高退款SKU清单", findings=[_full_finding()])],
        named_examples=[{"label": "鱼盘12寸", "detail": "退款率0.18"}],
    )
    html = render_html([result])
    assert "可信度原因：" in html          # evidence_reason (HTML-only, element 4)
    assert "仅HTML应出现的原因。" in html
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
    assert "table-details" in html
