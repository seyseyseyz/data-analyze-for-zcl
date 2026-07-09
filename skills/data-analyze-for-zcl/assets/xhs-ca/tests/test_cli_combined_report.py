"""CLI `run` composes multiple modules into ONE integrated report.

Running N tasks used to write N × (md + html) files. The integrated-report
pipeline already composes a list of results into a single document (that is how
`run all` works); these tests lock in that a *chosen subset* of modules also
lands in one report instead of fragmenting into per-slug files.
"""
from pathlib import Path

from typer.testing import CliRunner

from xhs_ceramics_analytics.cli import app
from xhs_ceramics_analytics.db.build import build_database


def _build_db(tmp_path: Path, fixture_dir: Path) -> None:
    state = tmp_path / ".xhs-ceramics-analytics"
    state.mkdir(parents=True, exist_ok=True)
    build_database(
        db_path=state / "analytics.duckdb",
        files=[
            fixture_dir / "business_overview_daily.csv",
            fixture_dir / "traffic_source.csv",
            fixture_dir / "search_overview.csv",
            fixture_dir / "search_terms.csv",
            fixture_dir / "shop_page_funnel.csv",
            fixture_dir / "shop_page_source.csv",
        ],
    )


def test_run_multiple_tasks_writes_single_integrated_report(tmp_path, fixture_dir):
    _build_db(tmp_path, fixture_dir)
    result = CliRunner().invoke(
        app,
        [
            "run",
            "data_quality_check",
            "core_business_diagnosis",
            "search_efficiency_diagnosis",
            "audience_structure_diagnosis",
            "--project-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    outputs = tmp_path / ".xhs-ceramics-analytics" / "outputs" / "20260101-000000-经营诊断报告"
    # Expressive default basename, and exactly two deliverables.
    assert (outputs / "经营诊断报告.md").exists()
    assert (outputs / "经营诊断报告.html").exists()
    assert sorted(p.name for p in outputs.iterdir()) == ["经营诊断报告.html", "经营诊断报告.md"]
    # No per-slug fragmentation.
    assert not (outputs / "core_business_diagnosis.md").exists()
    assert not (outputs / "data_quality_check.md").exists()
    # One document; data-quality gate plus all three analysis modules inside it.
    md = (outputs / "经营诊断报告.md").read_text(encoding="utf-8")
    assert md.count("# 小红书账号分析报告") == 1
    assert "## 数据质量检查" in md
    assert "## 核心经营结构诊断" in md
    assert "## 搜索效率诊断" in md
    assert "## 人群结构诊断" in md
    # Data quality is the appendix: it sinks below every analysis module even
    # though it was passed first on the command line.
    assert md.index("## 核心经营结构诊断") < md.index("## 数据质量检查")
    assert md.index("## 搜索效率诊断") < md.index("## 数据质量检查")
    assert md.index("## 人群结构诊断") < md.index("## 数据质量检查")


def test_run_combined_report_honors_name_option(tmp_path, fixture_dir):
    _build_db(tmp_path, fixture_dir)
    result = CliRunner().invoke(
        app,
        [
            "run",
            "core_business_diagnosis",
            "search_efficiency_diagnosis",
            "--name",
            "qianfan_diagnosis",
            "--project-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    outputs = tmp_path / ".xhs-ceramics-analytics" / "outputs" / "20260101-000000-qianfan_diagnosis"
    assert (outputs / "qianfan_diagnosis.md").exists()
    assert (outputs / "qianfan_diagnosis.html").exists()
    assert not (outputs / "report.md").exists()
    # --name also drives the document title, not just the filename. The file on
    # disk keeps the underscore (filesystem-friendly); the display title shows a
    # space so an underscore never reads as broken in the Chinese headline.
    md = (outputs / "qianfan_diagnosis.md").read_text(encoding="utf-8")
    assert md.startswith("# qianfan diagnosis\n")
    assert "# 小红书账号分析报告" not in md
    html = (outputs / "qianfan_diagnosis.html").read_text(encoding="utf-8")
    assert "<title>qianfan diagnosis</title>" in html
    assert "<h1>qianfan diagnosis</h1>" in html


def test_run_single_task_keeps_slug_named_output(tmp_path, fixture_dir):
    _build_db(tmp_path, fixture_dir)
    result = CliRunner().invoke(
        app,
        ["run", "core_business_diagnosis", "--project-root", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    outputs = (
        tmp_path / ".xhs-ceramics-analytics" / "outputs" / "20260101-000000-core_business_diagnosis"
    )
    assert (outputs / "core_business_diagnosis.md").exists()
    assert (outputs / "core_business_diagnosis.html").exists()
    assert not (outputs / "report.md").exists()


def test_run_rejects_unknown_task(tmp_path, fixture_dir):
    _build_db(tmp_path, fixture_dir)
    result = CliRunner().invoke(
        app,
        [
            "run",
            "core_business_diagnosis",
            "not_a_real_task",
            "--project-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code != 0
    assert "not_a_real_task" in result.output
