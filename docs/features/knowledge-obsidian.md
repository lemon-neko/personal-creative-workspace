# 知识库与 Obsidian

## 定位与状态

状态：🟡 一期可用。正式知识只由 `KnowledgeCard` 和 `KnowledgeMap` 构成，Obsidian 是主要编辑界面，工作台负责校验、来源追踪、质量诊断和可视化。

## 页面入口

| 入口 | 能力 |
|---|---|
| `/knowledge` | 默认显示学科目录和最近卡片；原始来源、质量诊断和核心知识图按需展开 |
| `/knowledge/cards/{id}` | 知识卡、来源 Revision、关系与复核 |
| `/knowledge/maps/{id}` | 学科或主题地图及下级内容 |
| `/ideas/{id}/distill` | 从单条随想手工拆卡或创建模型候选任务 |
| `/settings/obsidian` | Vault 状态、模板、扫描、迁移预演和导航重建 |

## 正式结构

```text
知识首页
└── 学科地图 subject
    └── 主题地图 topic
        └── 原子知识卡
            └── 原始随想与来源 Revision
```

知识卡类型固定为 `concept`、`claim`、`question`、`method`、`observation`。新卡必须关联至少一条未归档随想并归入至少一个主题；学科由主题父级派生。主题允许多父级，但禁止循环。

## 核心流程

1. 作者从待沉淀随想中选择真正有复用价值的来源。
2. 手工拆卡，或让本地模型/人工桥接生成候选。
3. 作者编辑并确认原子结论、类型、主题和来源。
4. 系统创建独立知识卡并保存来源语义 Revision，不修改随想。
5. 来源后来变化时，卡片进入待复核；作者可以确认仍有效、修改卡片、形成新结论或建立冲突/替代关系。

关系支持 `related`、`extends`、`supports`、`contrasts`、`superseded_by`。历史观点不覆盖，明确替代时保留有效时间。

## Obsidian 协作

- Obsidian 直接把私有 `content/` 作为 Vault，不复制 Markdown。
- 内置 Templates 在 `knowledge/inbox/` 创建知识卡、主题或学科候选；工作台确认后补齐稳定 ID。
- 工作台保留未知 Properties，并用 Revision 阻止双端覆盖。
- `知识首页.md` 只连接学科，学科连接主题，主题连接知识卡，避免全连接中心节点。
- 核心图默认隐藏概念和来源；点击知识卡后才展开来源。

## 模型、联网与隐私

- 手工拆卡、图谱、扫描和质量诊断均不调用模型。
- 模型只生成候选，不直接写知识库。
- Vault 只在本机使用，不启用 Obsidian Sync、Local REST API 或来源不明的插件。
- `.obsidian/` 不进入 Git 或加密内容备份。

## 当前限制与失败处理

- 材料、周回顾和文章不进入新知识卡来源选择；材料需先创建随想。
- 历史知识卡中的文章来源仍能加载和追溯，但不会成为新流程推荐来源。
- 无来源卡、无主题卡、孤立地图、失效关系和异常替代链只显示诊断，不自动修正正文。
- 非法父级、循环关系和未知目标会被拒绝。

## 相关文档与测试

- [内容模型](../architecture/content-model.md)
- [私有知识库目录说明](../architecture/private-vault-folders.md)
- [知识沉淀指南](../guides/knowledge-workflow.md)
- 测试：`test_knowledge.py`、`test_knowledge_store.py`、`test_obsidian.py`
- 更新：[内容分层](../changes/2026/2026-08-22-content-layering.md)
