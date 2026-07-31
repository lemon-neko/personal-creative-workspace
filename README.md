# 羽白学习手记

> 面向未来自己的 AI / 编程学习作品集：记录问题，用代码验证，再整理成可以复用的专题。

这个仓库同时保存学习内容和对应的可运行实现。日常思考既可以直接写成 Markdown，也可以通过碎片工作台快速记录；确认值得保留后发布到学习记录，围绕同一问题积累的记录会进一步整理成专题。

首个专题是「从零理解 Transformer」，包含 Self-Attention、Transformer Block、字符级 MiniGPT 和梯度分析。公开页面保持只读，本地碎片工作台允许写入草稿；源码、Notebook 与测试负责保存可运行的验证过程。

## 本地运行

```bash
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

然后访问 `http://127.0.0.1:8000`。站点包含：

- **首页**：平台定位、当前专题和最近发布记录
- **碎片工作台**：快速记录草稿、生成本周结构化汇总、设置本地执行时间
- **发布适配**：将记录、周总结或专题转换为公众号富文本
- **学习记录**：按日期排列，可按标签或专题筛选
- **Transformer 专题**：注意力、MiniGPT 与梯度的结构化总结
- **关于**：内容工作流与 Markdown 格式说明

## 碎片工作台

访问 `http://127.0.0.1:8000/workspace`，可以：

- 将标题、正文、标签和专题快速保存到 `content/notes/`
- 自动补充日期、唯一 ID、摘要和 `draft` 状态
- 将当前自然周的草稿与已发布记录整理成一份结构化周总结
- 设置每周执行时间；FastAPI 服务运行时会检查并生成当周草稿

自动汇总采用确定性的结构化模板，负责收拢记录、专题线索和复盘问题，不会自动发布内容。后续可以在生成步骤接入 AI 进行观点提炼。

## 转换为微信公众号文章

从学习记录、专题或碎片工作台点击“转换为公众号”，进入发布预览页：

1. 检查固定技术笔记主题下的标题、段落、代码与公式。
2. 点击“一键复制富文本”。
3. 粘贴到微信公众号编辑器。
4. 检查公式和图片，再由作者人工发布。

转换器使用行内样式生成公众号富文本，不依赖外部 CDN。公式由本地 MathJax 渲染，并在复制或下载前尝试转换为 PNG；失败时保留可读的 LaTeX。Markdown 图片会保留，但粘贴后需要确认目标平台是否已经重新托管。

首期只实现 `wechat` 适配器和人工复制流程，不保存公众号 AppID/AppSecret、不调用草稿箱或发布接口，也不进行 AI 改写。以后增加知乎、掘金等平台时，只需要实现新的平台渲染器，不需要修改 Markdown 内容模型。

## 写一条学习记录

在 `content/notes/` 新建 Markdown 文件：

```markdown
---
id: unique-note-id
title: 记录标题
date: 2026-07-30
status: draft
summary: 一句话说明这次记录解决了什么问题
tags:
  - Transformer
  - NumPy
topic: transformer
---

正文从这里开始。
```

字段约定：

| 字段 | 说明 |
|---|---|
| `id` | 仓库内唯一、稳定的记录标识 |
| `title` | 记录标题 |
| `date` | `YYYY-MM-DD` 格式日期 |
| `status` | `draft` 或 `published`；省略时默认为 `draft` |
| `summary` | 用于首页和时间线的一句话摘要 |
| `tags` | 用于筛选的文本列表 |
| `topic` | 关联专题的稳定标识 |

只有 `published` 内容会出现在站点。字段错误的文件会进入页面底部的内容诊断，不会阻止其他记录加载。

## 仓库结构

```text
lemon-neko-scratch-ai/
├── app/
│   ├── main.py                 # FastAPI 应用、页面路由
│   ├── content.py              # Markdown 解析、校验、筛选、渲染
│   ├── workspace.py            # 碎片保存、周总结与本地定时任务
│   ├── publishing.py           # 发布来源模型与平台适配器
│   ├── templates/              # Jinja2 页面与 HTMX partial
│   └── static/                 # CSS、页面脚本与本地 HTMX
├── content/
│   ├── notes/                  # 日常学习记录
│   ├── topics/                 # 整理后的专题文章
│   └── workspace.yaml          # 本地周总结执行时间
├── src/                        # NumPy 核心实现
├── notebooks/                  # 推导与实验 Notebook
├── examples/                   # 可独立运行的示例
└── tests/                      # 模型与内容层测试
```

## 开发与验证

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
pytest tests/ -v
ruff check src/ app/ tests/
python -m src.attention
python examples/train_minigpt.py
```

核心原则：

- `src/` 保持 NumPy from-scratch 实现；PyTorch 仅作为可选对照。
- 学习文字、代码、测试和实验在同一仓库中接受版本管理。
- 页面使用 FastAPI + Jinja2 服务端渲染，HTMX 只增强学习记录筛选。
- 公开内容页面只读；工作台只为本地 Markdown 草稿工作流服务。
- 发布适配只转换和复制内容，不持久化导出历史或平台凭证。
- 不提供训练、实验 API 或进程内模型状态。
- 不引入数据库、登录、评论或外部同步。

作者：lemon-neko · MIT License
