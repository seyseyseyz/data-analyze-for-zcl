import json

import pytest
from typer.testing import CliRunner

from xhs_ceramics_analytics.cli import app
from xhs_ceramics_analytics.importing.inspection import inspect_inputs


def test_inspect_infers_period_store_and_dedupes_without_touching_sources(tmp_path):
    source_dir = tmp_path / "小红书千帆4-7月数据"
    source_dir.mkdir()
    (source_dir / "经营大盘.csv").write_text(
        "时间,支付金额,支付订单数,支付买家数,商品访客数,客单价\n"
        "20260401,1000,10,8,20,125\n"
        "20260501,1500,12,10,24,150\n"
        "20260630,1800,14,11,28,164\n",
        encoding="utf-8",
    )
    notes_text = (
        "笔记id,发布时间,笔记标题,阅读次数,点赞数,收藏数\n"
        "n1,2026-04-01,标题1,100,10,5\n"
        "n2,2026-06-30,标题2,200,20,8\n"
    )
    for index in range(3):
        (source_dir / f"笔记数据_{index}.csv").write_text(notes_text, encoding="utf-8")
    (source_dir / "流量来源.csv").write_text(
        "小红书号,账号名称,渠道,笔记类型,支付金额,支付订单数,支付人数,"
        "商品点击次数,商品点击人数,支付转化率（PV）,支付转化率（UV）\n"
        "x1,PiGoo 手作瓷器,综合搜索页,图文,500,3,2,75,60,0.04,0.03\n"
        "x2,PiGoo 手作瓷器,其他,视频,300,2,2,50,40,0.04,0.05\n"
        "x3,pigoo_ceramics,其他,图文,100,1,1,20,15,0.05,0.06\n",
        encoding="utf-8",
    )
    before = {path: path.read_bytes() for path in source_dir.iterdir()}

    inspection = inspect_inputs([source_dir])

    assert inspection["report_period"] == {
        "start": "2026-04-01",
        "end": "2026-06-30",
        "source_table": "business_overview_daily",
        "source_field": "date",
    }
    assert inspection["store"]["selected"] == "PiGoo 手作瓷器"
    notes = next(
        table for table in inspection["tables"] if table["table_name"] == "notes"
    )
    assert notes == {
        "table_name": "notes",
        "input_rows": 6,
        "accepted_rows": 2,
        "duplicate_rows": 4,
        "merged_rows": 0,
        "conflict_count": 0,
    }
    assert len(inspection["duplicate_file_groups"]) == 1
    assert len(inspection["duplicate_file_groups"][0]["files"]) == 3
    assert any("4-7月" in warning for warning in inspection["warnings"])
    assert set(inspection["coverage"]) == {"producible", "blocked"}
    assert {path: path.read_bytes() for path in source_dir.iterdir()} == before


def test_inspect_and_build_commands_write_machine_readable_manifests(tmp_path):
    source = tmp_path / "经营大盘.csv"
    source.write_text(
        "时间,支付金额,支付订单数,支付买家数,商品访客数,客单价\n"
        "20260401,1000,10,8,20,125\n",
        encoding="utf-8",
    )
    inspection_path = tmp_path / "inspection.json"
    runner = CliRunner()

    inspected = runner.invoke(
        app,
        ["inspect", str(source), "--out", str(inspection_path)],
    )
    assert inspected.exit_code == 0, inspected.output
    assert json.loads(inspection_path.read_text(encoding="utf-8"))["provisional"] is True

    built = runner.invoke(
        app,
        ["build", str(source), "--project-root", str(tmp_path)],
    )
    assert built.exit_code == 0, built.output
    manifest_path = tmp_path / ".xhs-ceramics-analytics" / "build_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["provisional"] is False
    assert manifest["report_period"]["start"] == "2026-04-01"


def test_build_rejects_inputs_changed_after_recorded_inspection(tmp_path):
    source = tmp_path / "经营大盘.csv"
    source.write_text(
        "时间,支付金额,支付订单数,支付买家数,商品访客数,客单价\n"
        "20260401,1000,10,8,20,125\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    inspected = runner.invoke(
        app,
        ["inspect", str(source), "--project-root", str(tmp_path)],
    )
    assert inspected.exit_code == 0, inspected.output
    source.write_text(
        "时间,支付金额,支付订单数,支付买家数,商品访客数,客单价\n"
        "20260401,9999,10,8,20,125\n",
        encoding="utf-8",
    )

    built = runner.invoke(
        app,
        ["build", str(source), "--project-root", str(tmp_path)],
    )

    assert built.exit_code == 1
    assert "changed since inspection" in built.output
    assert not (tmp_path / ".xhs-ceramics-analytics" / "analytics.duckdb").exists()


def test_build_rejects_inputs_changed_while_database_is_building(tmp_path, monkeypatch):
    source = tmp_path / "经营大盘.csv"
    source.write_text(
        "时间,支付金额,支付订单数,支付买家数,商品访客数,客单价\n"
        "20260401,1000,10,8,20,125\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    inspected = runner.invoke(
        app,
        ["inspect", str(source), "--project-root", str(tmp_path)],
    )
    assert inspected.exit_code == 0, inspected.output

    from xhs_ceramics_analytics.db import build as build_module

    real_build = build_module.build_database

    def build_then_change(db_path, files, **kwargs):
        real_build(db_path, files, **kwargs)
        source.write_text(
            "时间,支付金额,支付订单数,支付买家数,商品访客数,客单价\n"
            "20260401,9999,10,8,20,125\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(build_module, "build_database", build_then_change)

    built = runner.invoke(
        app,
        ["build", str(source), "--project-root", str(tmp_path)],
    )

    assert built.exit_code == 1
    assert "changed during build" in built.output
    state = tmp_path / ".xhs-ceramics-analytics"
    assert not (state / "analytics.duckdb").exists()
    assert not (state / "build_manifest.json").exists()


def test_build_rejects_files_added_to_input_directory_during_build(tmp_path, monkeypatch):
    source_dir = tmp_path / "exports"
    source_dir.mkdir()
    source = source_dir / "经营大盘.csv"
    source.write_text(
        "时间,支付金额,支付订单数,支付买家数,商品访客数,客单价\n"
        "20260401,1000,10,8,20,125\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    inspected = runner.invoke(
        app,
        ["inspect", str(source_dir), "--project-root", str(tmp_path)],
    )
    assert inspected.exit_code == 0, inspected.output
    from xhs_ceramics_analytics.db import build as build_module

    real_build = build_module.build_database

    def build_then_add_file(db_path, files, **kwargs):
        real_build(db_path, files, **kwargs)
        (source_dir / "评论数据.csv").write_text(
            "笔记id,评论时间,评论内容\nn1,2026-04-01 10:00:00,想要链接\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(build_module, "build_database", build_then_add_file)

    built = runner.invoke(
        app,
        ["build", str(source_dir), "--project-root", str(tmp_path)],
    )

    assert built.exit_code == 1
    assert "input set changed during build" in built.output


def test_build_passes_project_mapping_overrides_to_staged_database(tmp_path, monkeypatch):
    source = tmp_path / "经营大盘.csv"
    source.write_text(
        "时间,支付金额,支付订单数,支付买家数,商品访客数,客单价\n"
        "20260401,1000,10,8,20,125\n",
        encoding="utf-8",
    )
    state = tmp_path / ".xhs-ceramics-analytics"
    state.mkdir()
    overrides_path = state / "mapping_overrides.yaml"
    overrides_path.write_text("{}\n", encoding="utf-8")
    from xhs_ceramics_analytics.db import build as build_module

    observed = {}
    real_build = build_module.build_database

    def capture_overrides(db_path, files, **kwargs):
        observed["overrides_path"] = kwargs.get("overrides_path")
        observed["files"] = list(files)
        return real_build(db_path, files, **kwargs)

    monkeypatch.setattr(build_module, "build_database", capture_overrides)

    built = CliRunner().invoke(
        app,
        ["build", str(source), "--project-root", str(tmp_path)],
    )

    assert built.exit_code == 0, built.output
    assert observed["overrides_path"].name == overrides_path.name
    assert observed["overrides_path"] != overrides_path
    assert observed["files"] != [source]
    assert [path.name for path in observed["files"]] == [source.name]


def test_build_rejects_mapping_overrides_changed_after_inspection(tmp_path):
    source = tmp_path / "经营大盘.csv"
    source.write_text(
        "时间,支付金额,支付订单数,支付买家数,商品访客数,客单价\n"
        "20260401,1000,10,8,20,125\n",
        encoding="utf-8",
    )
    state = tmp_path / ".xhs-ceramics-analytics"
    state.mkdir()
    overrides_path = state / "mapping_overrides.yaml"
    overrides_path.write_text("{}\n", encoding="utf-8")
    runner = CliRunner()
    inspected = runner.invoke(
        app,
        ["inspect", str(source), "--project-root", str(tmp_path)],
    )
    assert inspected.exit_code == 0, inspected.output
    overrides_path.write_text("business_overview_daily: {}\n", encoding="utf-8")

    built = runner.invoke(
        app,
        ["build", str(source), "--project-root", str(tmp_path)],
    )

    assert built.exit_code == 1
    assert "mapping overrides changed since inspection" in built.output


def test_inspect_rejects_inputs_changed_while_database_is_building(tmp_path, monkeypatch):
    source = tmp_path / "经营大盘.csv"
    source.write_text(
        "时间,支付金额,支付订单数,支付买家数,商品访客数,客单价\n"
        "20260401,1000,10,8,20,125\n",
        encoding="utf-8",
    )
    from xhs_ceramics_analytics.importing import inspection as inspection_module

    real_build = inspection_module.build_database

    def build_then_change(db_path, files, **kwargs):
        real_build(db_path, files, **kwargs)
        source.write_text(
            "时间,支付金额,支付订单数,支付买家数,商品访客数,客单价\n"
            "20260401,9999,10,8,20,125\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(inspection_module, "build_database", build_then_change)

    with pytest.raises(ValueError, match="changed during inspection"):
        inspect_inputs([source])


def test_build_command_rejects_an_empty_input_directory(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    runner = CliRunner()

    built = runner.invoke(
        app,
        ["build", str(empty), "--project-root", str(tmp_path)],
    )

    assert built.exit_code == 1
    assert "no input files found" in built.output


def test_inspect_deduplicates_identical_plain_union_exports(tmp_path):
    source_dir = tmp_path / "exports"
    source_dir.mkdir()
    comments = (
        "笔记id,评论时间,评论内容\n"
        "n1,2026-04-01 10:00:00,想要链接\n"
    )
    (source_dir / "评论数据_a.csv").write_text(comments, encoding="utf-8")
    (source_dir / "评论数据_b.csv").write_text(comments, encoding="utf-8")

    inspection = inspect_inputs([source_dir])

    summary = next(
        table for table in inspection["tables"] if table["table_name"] == "comments"
    )
    assert summary == {
        "table_name": "comments",
        "input_rows": 2,
        "accepted_rows": 1,
        "duplicate_rows": 1,
        "merged_rows": 0,
        "conflict_count": 0,
    }
    assert len(inspection["duplicate_file_groups"]) == 1


def test_inspection_matches_same_named_duplicate_files_one_manifest_row_each(tmp_path):
    source_dir = tmp_path / "exports"
    first_dir = source_dir / "first"
    second_dir = source_dir / "second"
    first_dir.mkdir(parents=True)
    second_dir.mkdir(parents=True)
    comments = (
        "笔记id,评论时间,评论内容\n"
        "n1,2026-04-01 10:00:00,想要链接\n"
    )
    (first_dir / "评论数据.csv").write_text(comments, encoding="utf-8")
    (second_dir / "评论数据.csv").write_text(comments, encoding="utf-8")

    inspection = inspect_inputs([source_dir])

    entries = [
        item for item in inspection["files"] if item["name"] == "评论数据.csv"
    ]
    assert len(entries) == 2
    assert [item["input_rows"] for item in entries] == [1, 1]


def test_inspection_separates_complementary_merges_from_exact_duplicates(tmp_path):
    source_dir = tmp_path / "exports"
    source_dir.mkdir()
    (source_dir / "笔记数据_a.csv").write_text(
        "笔记id,发布时间,笔记标题,阅读次数,点赞数,收藏数\n"
        "n1,2026-04-01,标题1,100,,\n",
        encoding="utf-8",
    )
    (source_dir / "笔记数据_b.csv").write_text(
        "笔记id,发布时间,笔记标题,阅读次数,点赞数,收藏数\n"
        "n1,2026-04-01,标题1,,10,5\n",
        encoding="utf-8",
    )

    inspection = inspect_inputs([source_dir])
    summary = next(
        table for table in inspection["tables"] if table["table_name"] == "notes"
    )

    assert summary["input_rows"] == 2
    assert summary["accepted_rows"] == 1
    assert summary["duplicate_rows"] == 0
    assert summary["merged_rows"] == 1
