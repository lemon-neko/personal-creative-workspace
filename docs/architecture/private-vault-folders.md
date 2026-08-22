# 私有知识库目录说明

本文说明 Obsidian 打开的私有 `content/` Vault 中，每个文件夹保存什么、由谁维护，以及是否适合手动编辑。Vault 是工作台与 Obsidian 共用的唯一 Markdown 内容源，不是仓库目录。

## 根目录总览

```text
content/
├── sources/                 # 输入、随想和材料
├── knowledge/               # 正式知识卡、地图和可重建索引
├── outputs/                 # 文章与周回顾
├── assets/                  # Markdown 图片和附件
├── archive/                 # 已归档的 ContentItem
├── trash/                   # 工作台回收站
├── items/                   # 旧版兼容目录，等待迁移
├── _templates/              # Obsidian 内置 Templates 使用的模板
├── .obsidian/               # 本机 Obsidian 配置
└── 知识首页.md              # 工作台生成的知识导航入口
```

目录为空通常是正常状态。工作台只会在真正创建对应内容时写入文件。

## `sources`：输入与原始记录

```text
sources/
├── inbox/                   # Obsidian 普通笔记收件箱
├── thoughts/                # 已纳入工作台的随想
└── materials/               # 书籍、文章、URL、文档等材料记录
```

### `sources/inbox`

- 用于在 Obsidian 中快速新建还没有工作台 front matter 的普通 Markdown。
- 文件不会自动进入知识图、模型任务或正式创作流。
- 回到 `/settings/obsidian` 扫描并确认导入后，工作台补齐稳定 ID、类型、状态、摘要和时间，再原子移动到 `sources/thoughts/`。
- 适合手动新建和编辑。

### `sources/thoughts`

- 保存已进入工作台的 `kind: thought` 随想，是新知识卡允许使用的正式来源。
- 可以在 Obsidian 中编辑现有正文、标题、标签、分类和自定义 Properties。
- 不要删除稳定 `id`、`kind`、`status` 等工作台字段，也不要手动移动或重命名正式文件。
- 新随想优先从工作台或 `sources/inbox/` 创建，避免手写不完整 front matter。

### `sources/materials`

- 保存阅读材料、URL 和本地文档的来源记录，不保存上传文档本体。
- 材料不能直接成为新知识卡；需要沉淀时先从材料创建随想，再从随想拆卡。
- URL 只作为记录保存，工作台不会后台抓取或访问。

## `knowledge`：正式知识

```text
knowledge/
├── inbox/                   # 知识卡或地图模板草稿
├── cards/                   # 已确认的原子知识卡
├── maps/                    # 学科地图和主题地图
└── indexes/
    └── obsidian/            # 可重建的 Obsidian 辅助索引
```

### `knowledge/inbox`

- 使用 `_templates/` 中的知识卡、主题地图或学科地图模板创建草稿。
- 可以手动编辑，但不能直接当作正式知识使用。
- 工作台扫描后会校验来源、主题、父级和循环关系；确认导入后才进入 `cards/` 或 `maps/`。

### `knowledge/cards`

- 保存已经人工确认的原子知识卡。
- 卡片类型为概念、判断、问题、方法或观察。
- 新卡必须关联至少一条未归档随想、至少一个主题，并记录来源 Revision。
- 可以在 Obsidian 中编辑正文、概念和关系，但应保留稳定 ID、来源和工作台管理字段。
- 不要直接把普通长文放入该目录；一张卡应只表达一个可独立理解的结论。

### `knowledge/maps`

- 同时保存 `subject` 学科地图和 `topic` 主题地图。
- 学科表示稳定领域，主题围绕一个核心问题组织知识卡。
- 主题可以有多个父学科，但不能形成循环。
- 新地图优先从 `knowledge/inbox/` 模板创建并由工作台确认。

### `knowledge/indexes`

- 保存工作台生成、可以删除并重建的辅助索引。
- `indexes/obsidian/` 用于 Obsidian 导航和历史兼容，不是正式知识正文。
- 不应手动编辑，也不应把个人笔记放到这里。

## `outputs`：独立创作与回顾

```text
outputs/
├── articles/                # 独立文章草稿和成稿
└── reviews/                 # 周回顾
```

### `outputs/articles`

- 保存 `kind: article` 的独立文章。
- 文章可以参考随想和知识卡，但不要求建立强关联，也不进入正式知识图。
- 只有这里的未归档文章可以进入微信公众号排版和视频工作台。
- 可以在 Obsidian 编辑现有文章；创建和状态切换优先使用工作台文章页面。

### `outputs/reviews`

- 保存 `kind: weekly-review` 的中性周期汇总。
- 周回顾不直接进入正式知识库或公众号。
- 出现值得长期保留的结论时，先另建随想再拆卡；需要公开表达时，独立创建文章。

## 生命周期与附件目录

### `archive`

- 保存状态为 `archived` 的随想、文章或周回顾。
- 归档时工作台把文件从原类型目录移动到这里；恢复状态时再移回对应目录。
- 不建议在 Obsidian 中手动移动、删除或新增文件，以免生命周期和索引状态不一致。
- 默认从 Obsidian Graph View 排除。

### `trash`

- 工作台的可恢复回收站，可能包含来自任意内容类型的 Markdown。
- “移入回收站”只移动文件；明确输入永久删除确认词后才真正删除。
- 不要直接清空或手动恢复，应通过 `/trash` 操作，以便检查重名和原目标目录。
- 默认从 Obsidian Graph View 排除。

### `assets`

- 保存 Markdown 正文引用的 PNG、JPEG、WebP 等私有图片。
- 建议在 Obsidian 将附件目录设置为 `assets`，链接使用 `assets/文件名`。
- 工作台通过受保护 `/assets/{name}` 路由显示，不会把文件放入公开 `/static`。
- 删除图片前先确认没有随想、文章或知识卡仍在引用。

## 兼容和生成内容

### `items`

- 这是旧版工作台的兼容目录，不是当前新增内容的目标位置。
- 工作台仍会读取其中 Markdown，避免升级后内容突然消失。
- 不要继续在这里新建文件；使用生命周期迁移命令先 dry-run，再把内容复制到 `sources/thoughts/`、`outputs/articles/` 或 `outputs/reviews/`。
- 迁移完成并校验后，旧目录会改名为带时间的 `legacy-items-*` 回滚副本，不会自动删除。

### `_templates`

- 保存工作台初始化的知识卡、主题地图和学科地图模板。
- 供 Obsidian 内置 Templates 使用，不需要安装社区插件。
- 可以查看模板，但结构调整应通过工作台版本更新完成，避免和导入校验规则不一致。

### `.obsidian`

- 保存本机 Obsidian 界面、插件和 Vault 配置。
- 不属于工作台知识正文，不进入 Git 或加密内容备份。
- 当前方案不依赖 Obsidian Sync、Local REST API 或社区插件。

### `知识首页.md`

- 工作台生成的正式知识入口，只连接第一层学科地图。
- 学科再连接主题，主题再连接知识卡，避免首页成为连接所有文件的巨大中心节点。
- 不建议手动维护；在 `/settings/obsidian` 执行“重建分层导航”会覆盖生成内容。

## 哪些目录可以手动操作

| 目录 | 新建 | 编辑现有文件 | 移动或删除 |
|---|---|---|---|
| `sources/inbox` | 可以 | 可以 | 导入前可以 |
| `sources/thoughts` | 建议通过工作台 | 可以 | 通过工作台 |
| `sources/materials` | 建议通过材料库 | 可以 | 通过工作台 |
| `knowledge/inbox` | 可以，配合模板 | 可以 | 导入前可以 |
| `knowledge/cards` | 通过拆卡或收件箱 | 可以 | 通过工作台 |
| `knowledge/maps` | 通过模板收件箱 | 可以 | 通过工作台 |
| `outputs/articles` | 建议通过文章页 | 可以 | 通过工作台 |
| `outputs/reviews` | 通过周回顾页 | 可以 | 通过工作台 |
| `assets` | 可以添加附件 | 不适用 | 删除前检查引用 |
| `archive`、`trash` | 不要 | 不建议 | 只通过工作台 |
| `items` | 不要 | 迁移前可修复坏文件 | 使用迁移流程 |
| `knowledge/indexes`、`知识首页.md` | 不要 | 不要 | 由工作台重建 |

## 推荐的 Obsidian 设置

- 新普通笔记目录：`sources/inbox`
- 新附件目录：`assets`
- 模板目录：`_templates`
- 链接格式：Markdown
- 自动更新内部链接：开启
- Graph View 排除：`trash`、`archive`、`items`、`outputs/reviews`、`knowledge/inbox`、`knowledge/indexes`、`_templates`

内容层之间的语义关系见 [内容模型](content-model.md)，具体拆卡步骤见 [知识沉淀指南](../guides/knowledge-workflow.md)。
