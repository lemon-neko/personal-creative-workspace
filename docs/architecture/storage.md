# 存储架构

## 私有数据目录

```text
~/Library/Application Support/personal-creative-workspace/
├── content/
│   ├── sources/
│   │   ├── inbox/
│   │   ├── thoughts/
│   │   └── materials/
│   ├── knowledge/
│   │   ├── inbox/
│   │   ├── cards/
│   │   ├── maps/
│   │   └── indexes/
│   ├── outputs/
│   │   ├── articles/
│   │   └── reviews/
│   ├── assets/
│   ├── archive/
│   ├── trash/
│   ├── _templates/
│   ├── 知识首页.md
│   └── .obsidian/
├── documents/
├── video-projects/
├── workspace.db
├── mobile.db
├── mobile.secret
├── working/model-tasks/
└── backups/
```

## Markdown

Markdown 是随想、材料记录、周回顾、文章、知识卡和知识地图的唯一正文来源。解析器关闭原始 HTML，坏文件产生独立诊断，未知 Obsidian Properties 在工作台写回时必须保留。

工作台生成的 Obsidian 关联区块不计入正文、搜索、模型、回顾、公众号或视频输入。图片使用 `assets/文件名` 的可移植路径，网页端安全映射到受保护路由。

## SQLite

`workspace.db` 保存求职、学习、搜索索引、模型账本、助手摘要/决策和 Obsidian 状态等结构化信息。它不保存 Markdown 正文副本。

`mobile.db` 独立保存设备、会话哈希和幂等回执，不与桌面或手机同步数据库文件。

主库使用 `schema_migrations`，移动库使用 `mobile_schema_migrations`。升级前建立快照，迁移和版本登记位于同一事务；未知高版本必须拒绝启动，而不是尝试降级。

## 附件与临时数据

- 上传文档和图片使用随机存储名、真实签名校验和受保护下载路由。
- 视频项目及交接包位于 `video-projects/`。
- 人工模型桥接正文位于 `working/model-tasks/`，七天后清理且不进入备份。
- `.obsidian/`、API Key、设备会话和已有备份不进入新的加密内容备份。

## 权限与一致性

- 私有根目录权限为 `0700`，文件为 `0600`。
- 权威文件写入使用锁、临时文件、`fsync` 和原子替换。
- 附件与 Markdown 作为一次逻辑事务保存，正文失败时清理本次新增附件。
- FTS5 索引可删除和重建，不能反向覆盖权威内容。
- 测试和开发必须显式使用临时 `WORKSPACE_DATA_DIR`，不能读取作者默认数据根。

运行、迁移和备份步骤见 [运行维护](../operations/README.md)。
Obsidian Vault 内每个目录的用途和手动操作边界见 [私有知识库目录说明](private-vault-folders.md)。
