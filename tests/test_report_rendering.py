from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.reporting.html import render_html
from xhs_ceramics_analytics.reporting.markdown import render_markdown


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
