from pathlib import Path

import pytest

from xhs_ceramics_analytics.importing.mapping import (
    AmbiguousTableTypeError,
    guess_field_mapping,
    guess_table_type,
)
import pandas as pd

from xhs_ceramics_analytics.importing import profile as profile_module
from xhs_ceramics_analytics.importing.profile import FileProfile, profile_csv, profile_file


def test_profile_csv_detects_columns(fixture_dir):
    profile = profile_csv(fixture_dir / "notes.csv")
    assert profile.row_count == 3
    assert "note_id" in profile.columns
    assert profile.sample_rows[0]["note_id"] == "n1"


def test_profile_csv_normalizes_missing_sample_values(tmp_path):
    csv_path = tmp_path / "missing_values.csv"
    csv_path.write_text(
        "row_id,score,label\n"
        "1,10,filled\n"
        "2,,\n",
        encoding="utf-8",
    )

    profile = profile_csv(csv_path)

    assert profile.sample_rows[1]["score"] is None
    assert profile.sample_rows[1]["label"] is None


def test_profile_file_reads_excel_sheet_with_offset_header(tmp_path):
    excel_path = tmp_path / "qianfan_export.xlsx"
    with pd.ExcelWriter(excel_path) as writer:
        pd.DataFrame({"说明": ["本工作表不是明细"]}).to_excel(
            writer,
            sheet_name="说明",
            index=False,
        )
        pd.DataFrame(
            [
                ["导出时间", None, None, None, None],
                ["订单号", "支付时间", "规格ID", "商品数量", "支付金额"],
                ["o1", "2026-06-01 10:00:00", "s1", 2, 258],
            ]
        ).to_excel(writer, sheet_name="订单明细", index=False, header=False)

    profile = profile_file(excel_path)

    assert profile.table_name == "订单明细"
    assert profile.columns == ["订单号", "支付时间", "规格ID", "商品数量", "支付金额"]
    assert profile.row_count == 1
    assert profile.sample_rows[0]["订单号"] == "o1"


def test_profile_file_uses_openpyxl_probe_before_pandas_excel_read(tmp_path, monkeypatch):
    excel_path = tmp_path / "qianfan_export.xlsx"
    with pd.ExcelWriter(excel_path) as writer:
        pd.DataFrame(
            [
                ["导出时间", None, None, None, None],
                ["订单号", "支付时间", "规格ID", "商品数量", "支付金额"],
                ["o1", "2026-06-01 10:00:00", "s1", 2, 258],
            ]
        ).to_excel(writer, sheet_name="订单明细", index=False, header=False)
    read_excel_calls = []
    original_read_excel = pd.read_excel

    def recording_read_excel(*args, **kwargs):
        read_excel_calls.append(kwargs)
        return original_read_excel(*args, **kwargs)

    monkeypatch.setattr(profile_module.pd, "read_excel", recording_read_excel)

    profile = profile_file(excel_path)

    assert profile.sheet_name == "订单明细"
    assert profile.header_row == 1
    assert read_excel_calls
    assert all(call.get("header") != None for call in read_excel_calls)  # noqa: E711
    assert read_excel_calls[0]["sheet_name"] == "订单明细"
    assert read_excel_calls[0]["header"] == 1
    assert read_excel_calls[0]["engine"] == "openpyxl"


def test_guess_table_type_for_notes(fixture_dir):
    profile = profile_csv(fixture_dir / "notes.csv")
    assert guess_table_type(profile) == "notes"


def test_guess_table_type_rejects_unknown_columns():
    profile = FileProfile(
        path=Path("unknown.csv"),
        table_name="unknown_export",
        columns=["foo", "bar", "baz"],
        row_count=1,
        sample_rows=[],
    )

    with pytest.raises(ValueError, match="unknown_export"):
        guess_table_type(profile)


def test_guess_field_mapping_for_orders(fixture_dir):
    profile = profile_csv(fixture_dir / "orders.csv")
    mapping = guess_field_mapping(profile, "orders")
    assert mapping["order_id"] == "order_id"
    assert mapping["paid_time"] == "paid_time"
    assert mapping["sku_id"] == "sku_id"


def test_guess_field_mapping_for_chinese_qianfan_orders():
    profile = FileProfile(
        path=Path("orders.xlsx"),
        table_name="订单明细",
        columns=["订单号", "支付时间", "规格ID", "商品数量", "支付金额"],
        row_count=1,
        sample_rows=[],
    )

    assert guess_table_type(profile) == "orders"
    mapping = guess_field_mapping(profile, "orders")

    assert mapping["order_id"] == "订单号"
    assert mapping["paid_time"] == "支付时间"
    assert mapping["sku_id"] == "规格ID"
    assert mapping["quantity"] == "商品数量"
    assert mapping["paid_amount"] == "支付金额"


def test_guess_field_mapping_for_chinese_qianfan_notes_products_and_skus():
    note_profile = FileProfile(
        path=Path("notes.xlsx"),
        table_name="单篇笔记",
        columns=["笔记ID", "笔记创建时间", "笔记标题", "笔记阅读数", "点赞数", "收藏数"],
        row_count=1,
        sample_rows=[],
    )
    product_profile = FileProfile(
        path=Path("products.xlsx"),
        table_name="商品明细",
        columns=["商品ID", "商品名称", "商品类目", "器型", "系列"],
        row_count=1,
        sample_rows=[],
    )
    sku_profile = FileProfile(
        path=Path("skus.xlsx"),
        table_name="规格明细",
        columns=["规格ID", "商品ID", "规格名称", "销售价格"],
        row_count=1,
        sample_rows=[],
    )

    assert guess_table_type(note_profile) == "notes"
    assert guess_field_mapping(note_profile, "notes") == {
        "note_id": "笔记ID",
        "publish_time": "笔记创建时间",
        "title": "笔记标题",
        "reads": "笔记阅读数",
        "likes": "点赞数",
        "collects": "收藏数",
    }
    assert guess_table_type(product_profile) == "products"
    product_mapping = guess_field_mapping(product_profile, "products")
    assert product_mapping["product_id"] == "商品ID"
    assert product_mapping["product_name"] == "商品名称"
    assert product_mapping["vessel_type"] == "器型"
    assert product_mapping["series"] == "系列"
    assert guess_table_type(sku_profile) == "skus"
    sku_mapping = guess_field_mapping(sku_profile, "skus")
    assert sku_mapping["sku_id"] == "规格ID"
    assert sku_mapping["product_id"] == "商品ID"
    assert sku_mapping["sku_name"] == "规格名称"
    assert sku_mapping["price"] == "销售价格"


def test_guess_field_mapping_preserves_spaced_order_headers():
    profile = FileProfile(
        path=Path("orders.csv"),
        table_name="orders",
        columns=["Order ID", "Paid Time", "SKU ID", "Quantity", "Paid Amount"],
        row_count=1,
        sample_rows=[],
    )

    mapping = guess_field_mapping(profile, "orders")

    assert mapping["order_id"] == "Order ID"
    assert mapping["paid_time"] == "Paid Time"
    assert mapping["sku_id"] == "SKU ID"
    assert mapping["quantity"] == "Quantity"
    assert mapping["paid_amount"] == "Paid Amount"


def test_guess_field_mapping_does_not_reuse_source_columns():
    profile = FileProfile(
        path=Path("comments.csv"),
        table_name="comments",
        columns=["note_id", "comment_text"],
        row_count=1,
        sample_rows=[],
    )

    mapping = guess_field_mapping(profile, "comments")

    assert mapping["comment_text"] == "comment_text"
    assert "comment_time" not in mapping


def test_guess_table_type_detects_paid_traffic_export(tmp_path):
    profile = FileProfile(
        path=tmp_path / "ads.csv",
        table_name="ads",
        columns=["投放日期", "计划名称", "消耗", "曝光量", "点击量", "成交金额"],
        row_count=1,
        sample_rows=[],
    )

    assert guess_table_type(profile) == "ad_performance_daily"


def test_guess_field_mapping_maps_paid_traffic_headers(tmp_path):
    profile = FileProfile(
        path=tmp_path / "ads.csv",
        table_name="ads",
        columns=[
            "投放日期",
            "投放平台",
            "计划名称",
            "创意名称",
            "笔记ID",
            "SKU ID",
            "消耗",
            "曝光量",
            "点击量",
            "成交金额",
            "广告投产比",
        ],
        row_count=1,
        sample_rows=[],
    )

    mapping = guess_field_mapping(profile, "ad_performance_daily")

    assert mapping["date"] == "投放日期"
    assert mapping["platform_source"] == "投放平台"
    assert mapping["campaign_name_optional"] == "计划名称"
    assert mapping["creative_name_optional"] == "创意名称"
    assert mapping["note_id_optional"] == "笔记ID"
    assert mapping["sku_id_optional"] == "SKU ID"
    assert mapping["spend"] == "消耗"
    assert mapping["impressions"] == "曝光量"
    assert mapping["clicks"] == "点击量"
    assert mapping["gmv_optional"] == "成交金额"
    assert mapping["roas_optional"] == "广告投产比"


def _profile(columns):
    return FileProfile(
        path=None, table_name="t", columns=columns, row_count=1, sample_rows=[]
    )


def test_below_threshold_raises_plain_valueerror():
    with pytest.raises(ValueError) as excinfo:
        guess_table_type(_profile(["完全不相关的列名"]))
    assert not isinstance(excinfo.value, AmbiguousTableTypeError)


def test_tie_between_products_and_skus_is_ambiguous():
    # "商品ID" alone hits products.product_id AND skus.product_id → 0.25 vs 0.25,
    # SAME raw hit count (1 each) → a genuine collision, still ambiguous.
    with pytest.raises(AmbiguousTableTypeError):
        guess_table_type(_profile(["商品ID"]))


def test_partial_notes_file_still_classifies_as_notes():
    # Regression guard (pre-existing test_final_review_regressions.py depends on this):
    # a column-sparse but valid notes export must NOT trip the ambiguity margin.
    # notes matches 2 signature columns (note_id + publish_time) while comments
    # matches only 1 (note_id self-matches its own target name), so on normalized
    # coverage notes 2/6 == comments 1/3 — a 0.00 gap < MARGIN — yet notes clearly
    # explains MORE real columns. The raw-hit tie-break must resolve this to notes,
    # not raise AmbiguousTableTypeError (which Task 3 would divert into needs_data,
    # leaving the notes table unbuilt and breaking account_baseline).
    assert guess_table_type(_profile(["note_id", "publish_time"])) == "notes"


def test_classifies_business_overview_daily():
    profile = _profile(["时间", "支付金额", "支付订单数", "支付买家数", "客单价",
                        "退款后支付金额（支付时间）", "退款率（支付时间）"])
    assert guess_table_type(profile) == "business_overview_daily"
    mapping = guess_field_mapping(profile, "business_overview_daily")
    assert mapping["date"] == "时间"
    assert mapping["net_gmv_pay"] == "退款后支付金额（支付时间）"
    assert mapping["refund_rate_pay"] == "退款率（支付时间）"


def test_classifies_sku_performance_and_catalog_still_skus():
    perf = _profile(["规格ID", "规格名称", "商品ID", "一级品类", "加购人数",
                     "支付金额", "客单价", "退款后支付金额（支付时间）", "退款率（支付时间）"])
    assert guess_table_type(perf) == "sku_performance"
    catalog = _profile(["规格ID", "商品ID", "规格名称", "销售价格"])
    assert guess_table_type(catalog) == "skus"


def test_notes_enriched_commerce_aliases():
    profile = _profile(["笔记id", "发布时间", "笔记标题", "阅读次数", "点赞数", "收藏数",
                        "笔记类型", "笔记支付金额", "笔记商品点击次数", "笔记商品点击人数"])
    assert guess_table_type(profile) == "notes"
    mapping = guess_field_mapping(profile, "notes")
    assert mapping["note_type"] == "笔记类型"
    assert mapping["note_gmv"] == "笔记支付金额"
    assert mapping["product_clicks"] == "笔记商品点击次数"
    assert mapping["product_click_users"] == "笔记商品点击人数"


def test_classifies_search_overview_and_terms():
    overview = _profile(["日期", "载体", "支付金额", "支付订单数", "支付买家数",
                         "商卡曝光人数", "商品点击人数", "商品点击率", "支付转化率"])
    assert guess_table_type(overview) == "search_overview"
    terms = _profile(["搜索词", "支付金额", "支付订单数", "支付买家数",
                      "商卡曝光人数", "商品点击人数", "商品点击率", "支付转化率"])
    assert guess_table_type(terms) == "search_terms"


def test_classifies_shop_page_funnel_and_source():
    funnel = _profile(["时间", "人群类型", "首购周期", "店铺页访问人数",
                       "商品点击人数", "店铺页支付人数", "访问点击转化率", "点击支付率", "访问支付率"])
    assert guess_table_type(funnel) == "shop_page_funnel"
    source = _profile(["时间", "人群类型", "首购周期", "来源页面",
                       "店铺页支付金额", "店铺页访问人数", "进店支付转化率", "人均支付金额"])
    assert guess_table_type(source) == "shop_page_source"


def test_classifies_refund_overview_and_traffic_source():
    # use the real export headers verbatim (incl. the （支付时间） caliber suffix on
    # 退款人数) so the alias mapping is actually exercised — a bare 退款人数 header
    # would silently pass classification while leaving refund_users un-canonicalized.
    refund = _profile(["统计时间", "账号类型", "账号名称", "载体", "退款金额（支付时间）",
                       "发货前退款金额（支付时间）", "退货退款金额（支付时间）", "退款人数（支付时间）"])
    assert guess_table_type(refund) == "refund_overview"
    # the required canonical refund_users column must map from the real header
    assert guess_field_mapping(refund, "refund_overview")["refund_users"] == "退款人数（支付时间）"
    traffic = _profile(["小红书号", "账号名称", "渠道", "笔记类型", "支付金额",
                        "支付订单数", "支付人数", "商品点击次数", "商品点击人数"])
    assert guess_table_type(traffic) == "traffic_source"
