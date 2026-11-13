---
date: 2026-11-11
status: completed
type: feature
areas:
  - workbench
  - planner
interfaces:
  - GET /?day=YYYY-MM-DD
data_migration: none
compatibility: existing day links and schedule data preserved
rollback: revert this batch
verification:
  - Chromium month navigation, leap day and calendar drag
commit: pending
---

## 日常工作月历

### 背景与目标

扩大日历的浏览范围，并在待安排区说明它和当天时间轴的关系。

### 最终行为

日历展示所选月份，支持翻月、点击日期和拖动待办。右侧显示所选日期的全天事项和时间轴。「待安排」列出未单独排程、且未列入所选日期的未完成事项。

### 接口与数据

沿用日期参数和现有排程数据结构。

### 兼容与回滚

原日期链接继续定位同一天。回退本批次即可恢复周日历。

### 验证结果

浏览器检查闰年日期、翻月、拖拽和窄屏。

### 同步文档

- [阶段行动](../../features/focus.md)
- [日常工作指南](../../guides/focus-workflow.md)
