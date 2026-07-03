# 人群结构诊断 (audience_structure_diagnosis)

> Scaffold placeholder — full template written alongside the implementation.
> Design: docs/superpowers/specs/2026-07-03-audience-structure-diagnosis-design.md

## Purpose

人群转化对比 + 首购周期漏斗 + 进店来源结构 + 人群构成。

## Required tables

- `shop_page_funnel`（必需；缺失则 NOT_JUDGABLE）
- `shop_page_source`、`audience_profile`（可选，缺失则降级；`audience_profile` 需手工录入）
