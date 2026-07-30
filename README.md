# 羽白学习手记

> 面向未来自己的 AI / 编程学习作品集：记录问题，用代码验证，再整理成可以复用的专题。

这个仓库同时保存学习内容和对应的可运行实现。日常思考先写成 Markdown，确认值得保留后发布到学习记录；围绕同一问题积累的记录会进一步整理成专题。

首个专题是「从零理解 Transformer」，包含 Self-Attention、Transformer Block、字符级 MiniGPT 和梯度分析。网站保持只读，源码、Notebook 与测试负责保存可运行的验证过程。

## 本地运行

```bash
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

然后访问 `http://127.0.0.1:8000`。站点包含：

- **首页**：平台定位、当前专题和最近发布记录
- **学习记录**：按日期排列，可按标签或专题筛选
- **Transformer 专题**：注意力、MiniGPT 与梯度的结构化总结
- **关于**：内容工作流与 Markdown 格式说明

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
│   ├── templates/              # Jinja2 页面与 HTMX partial
│   └── static/                 # CSS、页面脚本与本地 HTMX
├── content/
│   ├── notes/                  # 日常学习记录
│   └── topics/                 # 整理后的专题文章
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
- 首期页面只读，不提供训练、实验 API 或进程内模型状态。
- 首期不引入数据库、登录、网页编辑器、评论或外部同步。

作者：lemon-neko · MIT License
