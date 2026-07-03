# 核心经营结构诊断 (core_business_diagnosis)

> Scaffold placeholder — full template written alongside the implementation.
> Design: docs/superpowers/specs/2026-07-03-core-business-diagnosis-design.md

## Purpose

整体经营快照 + 时间趋势 + 载体（笔记/商品卡）与渠道结构拆解 + 店铺页转化漏斗诊断。

## Required tables

- `business_overview_daily`（必需；缺失则 NOT_JUDGABLE）
- `traffic_source`、`shop_page_funnel`（可选，缺失则降级）
