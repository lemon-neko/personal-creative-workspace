# 羽白工作台文档

本文档体系面向作者本人、后续维护工程师和 AI Agent。功能事实按模块维护，公共设计、日常流程、运行方式和历史变更分别归档，避免同一事实散落在多篇长文中。

## 从这里开始

| 想了解 | 权威入口 |
|---|---|
| 当前有哪些功能、入口和边界 | [功能模块](features/README.md) |
| 系统边界、内容模型和存储方式 | [架构说明](architecture/README.md) |
| Obsidian 里每个文件夹放什么 | [私有知识库目录说明](architecture/private-vault-folders.md) |
| 日常如何记录、沉淀、创作和求职 | [操作指南](guides/README.md) |
| 如何安装、启动、迁移、备份和排障 | [运行维护](operations/README.md) |
| 如何修改代码、测试和安全扩展 | [开发说明](development/README.md) |
| 每个已完成批次改了什么 | [更新档案](changes/README.md) |
| 当前成熟度和近期优先级 | [项目状态](../PROJECT_STATUS.md) |

## 文档权威边界

- 项目定位、五分钟启动和安全摘要：根目录 [README](../README.md)。
- 功能事实、页面入口和已知限制：`features/`。
- 系统设计、内容语义和存储选择：`architecture/`。
- 作者日常操作步骤：`guides/`。
- 安装、移动网络、备份和故障恢复：`operations/`。
- 代码结构、验证与扩展约束：`development/` 和根目录 [AGENTS](../AGENTS.md)。
- 已实现批次的历史记录：`changes/`。
- 成熟度、当前验证环境和近期路线：根目录 [PROJECT_STATUS](../PROJECT_STATUS.md)。

功能批次完成后，应更新对应功能文档并新增一份更新档案；只有数据流、系统边界或操作方式发生变化时，才同步修改相应公共文档。
