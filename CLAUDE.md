# CLAUDE.md

## 项目定位

这是一个中文个人学习作品集，主要面向作者未来回顾，也保持公开分享的可读性。内容从 Markdown 学习碎片逐步整理为专题，并用 NumPy 源码、Notebook 和测试验证结论。页面层使用 FastAPI + Jinja2；公开页面只读，本地碎片工作台可以创建草稿与结构化周总结。

首个专题是 Transformer。不要重新引入独立静态站或把专题拆回多个平铺的教学功能页。

## 内容架构

- `content/notes/`：带 YAML front matter 的日常学习记录
- `content/topics/`：整理后的长篇专题
- `app/content.py`：记录解析、校验、排序和筛选
- `app/workspace.py`：碎片保存、结构化周总结和本地定时任务
- `app/publishing.py`：统一发布来源模型和平台富文本适配器
- `app/main.py`：FastAPI 应用工厂与页面路由
- `app/templates/`：Jinja2 页面与 HTMX partial
- `app/static/`：响应式样式和本地前端依赖
- `src/`：纯 NumPy 核心算法

记录字段为 `id`、`title`、`date`、`status`、`summary`、`tags` 和 `topic`。`status` 省略时默认为 `draft`；只有 `published` 会出现在公开索引。内容错误必须生成非致命诊断，不能阻塞其他文件。

## 开发命令

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
pytest tests/ -v
ruff check src/ app/ tests/
python -m src.attention
```

## 编码与产品原则

- `src/` 使用 NumPy；PyTorch 仅用于对照验证。
- 页面采用阅读优先的克制深色视觉，使用单一暖色强调。
- 新的学习内容优先进入 Markdown，不要硬编码到首页。
- HTMX 只用于渐进增强；无 JavaScript 时普通 GET 筛选必须仍可用。
- 工作台写入的内容必须保持 `draft`，自动汇总不得直接发布或覆盖原始碎片。
- 本地定时任务只在 FastAPI 进程运行时工作；云端定时执行应使用外部调度。
- 发布适配器只能转换或复制内容；不得保存平台密钥、绕过人工审核或直接发布。
- 公众号 HTML 使用行内样式和本地 MathJax，新增平台应实现独立渲染器，不修改 Markdown 字段。
- 首期不增加训练或实验 API，算法能力保留在 `src/`、Notebook 和示例中。
- 不增加数据库、身份验证、评论或外部同步，除非产品范围明确改变。
