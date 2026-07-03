# 搜索效率诊断 (search_efficiency_diagnosis)

> Scaffold placeholder — full template written alongside the implementation.
> Design: docs/superpowers/specs/2026-07-03-search-efficiency-diagnosis-design.md

## Purpose

载体搜索效率对比 + 搜索转化时间趋势 + 高机会/高流失搜索词识别。

## Required tables

- `search_overview`（必需；缺失则 NOT_JUDGABLE）
- `search_terms`（可选，缺失则降级）
