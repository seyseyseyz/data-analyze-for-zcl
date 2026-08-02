from xhs_ceramics_analytics.reporting.data_gaps import data_gap_markdown


def test_groups_blocked_tasks_by_data_package_without_internal_slugs():
    markdown = data_gap_markdown(
        [
            {"slug": "ad_data_quality_check", "reason": "缺少 ad_performance_daily 表。"},
            {"slug": "paid_traffic_efficiency", "reason": "缺少 ad_performance_daily 表。"},
            {"slug": "cover_style_effect", "reason": "缺少 content_features 表。"},
            {"slug": "copy_angle_effect", "reason": "缺少 content_features 表。"},
        ]
    )

    assert markdown.startswith("## 缺哪些数据，补齐后能分析什么")
    assert markdown.count("广告投放明细") == 1
    assert markdown.count("笔记内容标签（封面、场景、文案）") == 1
    assert "广告从曝光、点击到成交的每一步" in markdown
    assert "比较不同封面风格的表现" in markdown
    assert "比较不同文案表达角度的表现" in markdown
    assert "paid_traffic_efficiency" not in markdown
    assert "content_features" not in markdown


def test_renders_nothing_when_no_modules_are_blocked():
    assert data_gap_markdown([]) == ""


def test_unknown_blocker_uses_reason_without_exposing_machine_slug():
    markdown = data_gap_markdown(
        [{"slug": "future_internal_task", "reason": "缺少线下门店核销明细。"}]
    )

    assert "其他待补数据" in markdown
    assert "缺少线下门店核销明细" in markdown
    assert "future_internal_task" not in markdown


def test_uses_plain_merchant_language_and_explains_business_abbreviations():
    markdown = data_gap_markdown(
        [
            "paid_traffic_efficiency",
            "product_opportunity_matrix",
            "core_business_diagnosis",
        ]
    )

    assert "| 要补什么数据 | 至少要包含哪些内容 | 补齐后能看懂什么 |" in markdown
    assert "商品与规格（SKU）资料及每日销售明细" in markdown
    assert "成交额（GMV）" in markdown
    assert "千次曝光成本、单次点击成本、投入产出效率" in markdown
    assert "补完后更新报告，就能得到右侧对应的分析" in markdown
    assert "CPM/CPC/投产效率" not in markdown
    assert "重跑对应模块" not in markdown
    assert "数据粒度" not in markdown


def test_lists_supported_optional_capabilities_when_result_fields_are_missing():
    markdown = data_gap_markdown(
        [],
        result_tables={
            "note_funnel": [
                {
                    "impressions": None,
                    "to_live_count_optional": None,
                    "to_live_gmv_optional": None,
                    "to_shop_home_count_optional": None,
                    "to_shop_home_gmv_optional": None,
                    "video_seconds_optional": None,
                    "avg_read_seconds_optional": None,
                    "completion_rate_pv_optional": None,
                    "follow_clicks_optional": None,
                    "danmu_count_optional": None,
                    "add_to_cart_units_optional": None,
                }
            ],
            "table_row_counts": [{"table": "notes", "rows": 12}],
        },
    )

    assert "### 可选增强数据：补充后可以看得更细" in markdown
    assert "笔记引流到直播间的数据" in markdown
    assert "进直播间次数、直播间支付金额" in markdown
    assert "哪些笔记为直播间带来访问和成交" in markdown
    assert "笔记曝光数据" in markdown
    assert "视频观看质量数据" in markdown
    assert "活动日历" in markdown
    assert "笔记与商品规格的明确对应关系" in markdown
    assert "退款原因明细" in markdown
    assert "直播总览" not in markdown


def test_does_not_report_live_referral_missing_when_real_zero_values_exist():
    markdown = data_gap_markdown(
        [],
        result_tables={
            "note_funnel": [
                {
                    "to_live_count_optional": 0,
                    "to_live_gmv_optional": 0.0,
                }
            ],
            "table_row_counts": [
                {"table": table, "rows": 1}
                for table in ("notes", "calendar_events", "note_sku_links", "refund_reasons")
            ],
        },
    )

    assert "笔记引流到直播间的数据" not in markdown


def test_optional_source_table_capabilities_disappear_when_tables_exist():
    result_tables = {
        "table_row_counts": [
            {"table": table, "rows": 1}
            for table in ("notes", "calendar_events", "note_sku_links", "refund_reasons")
        ]
    }

    assert data_gap_markdown([], result_tables=result_tables) == ""
