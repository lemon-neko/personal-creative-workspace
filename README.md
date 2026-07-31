# 羽白的幻想栈

一个本地优先的个人想法工作台。它负责接住突然冒出来的念头，让技术、生活、观察和写作碎片在同一个地方慢慢长大。

根路径是作者工作台；只有明确设为 `published` 的内容才会进入公开阅读区。所有数据仍是仓库内的 Markdown，不依赖数据库，也不会自动发送到外部平台。

## 本地运行

```bash
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1
```

然后访问 `http://127.0.0.1:8000`。

> 当前没有登录系统。请保持服务绑定在 `127.0.0.1`，不要直接暴露到公网。

## 页面

- `/`：极简随手记、今日记录和最近想法
- `/ideas`：搜索、筛选、编辑、公开、归档和回收
- `/reviews`：手动或定时生成周回顾草稿
- `/publish`：微信公众号忠实排版与可选风格润色
- `/garden`：只展示 `published` 内容的公开阅读区
- `/trash`：恢复或确认永久删除
- `/settings`：本地存储和模型配置状态

## 内容格式

工作台会在 `content/items/` 中创建 Markdown：

```markdown
---
id: idea-20260731-120000-abc123
title: 自动或手动填写的标题
created_at: "2026-07-31T12:00:00+08:00"
updated_at: "2026-07-31T12:00:00+08:00"
status: draft
kind: thought
summary: 自动生成的摘要
tags:
  - 观察
category: 路上
---

正文从这里开始。
```

约定：

| 字段 | 可选值或说明 |
|---|---|
| `status` | `draft`、`published`、`archived` |
| `kind` | `thought`、`weekly-review`、`article` |
| `category` | 可选自由文本 |
| `parent_id` | 可选；风格候选稿保存为文章时关联原始内容 |

正文是快速记录时唯一必填项。标题缺省时由第一句自动生成。字段错误会显示为内容诊断，不影响其他 Markdown 加载。

## 周回顾

周回顾聚合当前自然周的记录：

- 配置模型时，提炼重复主题、想法关联、矛盾和后续问题。
- 未配置模型或调用失败时，回退为稳定的规则清单。
- 同一周只生成一次，始终保存为草稿，不覆盖原始内容。
- 定时任务仅在 FastAPI 服务运行期间执行。

## 幻想栈风格润色

忠实公众号排版无需模型。可选润色使用 OpenAI-compatible `chat/completions` 接口：

```bash
export LLM_BASE_URL="https://your-provider.example/v1"
export LLM_API_KEY="..."
export LLM_MODEL="your-model"
uvicorn app.main:app --reload --host 127.0.0.1
```

润色页提供“自动判断、观察随想、概念拆解”三种模式。模型只生成候选稿和配图位置建议；只有点击“保存为文章草稿”才会创建新的 `kind: article` Markdown，并通过 `parent_id` 关联来源。

公众号主题来自“羽白的幻想栈”样本：清爽白底、青蓝章节标题、点线分隔、大留白、短段落与固定作者署名。富文本复制同时写入 HTML 和纯文本；公式会在浏览器中尝试转换为 PNG，图片需要粘贴后确认公众号重新托管。

首期不接入公众号草稿箱，不保存公众号凭证，不自动发布，也不自动抓取或生成表情包。

## 开发验证

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
pytest -q
ruff check app tests
python -c "from app.main import app; print(app.title)"
```

历史知识内容和旧教学材料已从当前版本移除，仍可通过 Git 历史恢复。
