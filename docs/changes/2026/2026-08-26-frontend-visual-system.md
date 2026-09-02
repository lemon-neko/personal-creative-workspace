---
date: 2026-08-26
status: completed
type: refactor
areas:
  - frontend
  - accessibility
  - responsive-layout
interfaces:
  - none
data_migration: none
compatibility: preserved
rollback: revert the shared design-system stylesheet and base template inclusion
verification:
  - 233 unit and integration tests
  - 3 browser acceptance tests
  - desktop and 390px browser review
commit: pending
---

# 全站视觉系统升级

## 背景与目标

历史页面在功能持续扩展后出现暖色与冷色混用、卡片层级重复、按钮阴影偏重和窄屏导航拥挤等问题。本批次在不改变路由、表单、内容和数据行为的前提下，统一全站展示语言。

## 最终行为

- 全站采用冷灰中性色、单一羽白青和紧凑的编辑部控制台风格。
- 侧栏、页面标题、表单、按钮、信息面板、知识库、收入面板和公众号工作台使用统一的间距、圆角与交互状态。
- 首页减少装饰与重复标签，将快速记录、创作流和状态栏恢复为清晰的主次关系。
- 收入指标改为轻量数据带，知识库与设置页减少多余卡片感，公众号预览继续突出正文画布。
- 窄屏使用固定品牌栏与可横向滚动的单行导航，表单和主要操作自动变为适合触控的宽度。
- 增加跳转到主要内容、键盘焦点和减少动态效果支持。

## 接口与数据

没有新增或修改页面接口、数据模型、数据库迁移或私有内容。新增共享视觉覆盖层 `app/static/styles/design-system.css`，并由基础模板统一加载。

## 兼容与回滚

现有路由、导航名称、表单字段、HTMX 行为和业务样式文件全部保留。回滚时移除基础模板中的共享视觉样式引用，并恢复对应静态资源版本号即可，不涉及数据恢复。

## 验证结果

- 233 项单元与集成测试通过。
- 3 项浏览器验收测试通过。
- 人工检查工作台、知识库、收入、设置、发布列表和公众号预览。
- 人工检查桌面与 390 像素窄屏导航、表单和信息层级。
- 浏览器控制台无前端错误。

## 同步文档

- `docs/development/README.md`
- `docs/changes/README.md`
