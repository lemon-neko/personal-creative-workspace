# 模型与成本

## 定位与状态

状态：✅ 已可用。`ModelGateway` 是知识拆卡、周回顾候选、公众号润色、简历解析、岗位定制、JD 提取和个人助手的唯一模型入口。

## Provider

| Provider | 行为 |
|---|---|
| `rules` | 确定性规则，零模型成本 |
| `local` | 仅接受 `localhost`、`127.0.0.1` 或 `::1` 的 OpenAI-compatible 服务 |
| `manual` | 复制七天临时任务包到 ChatGPT/Codex，再导入结构化结果 |
| `external` | 默认关闭，显式启用后仍需逐次确认 |

## 任务流程

```text
选择来源 → 外发预览 → Token/策略检查 → 选择 Provider → 校验候选 → 人工确认写入
```

页面加载、保存内容、定时任务和后台线程都不会调用模型。超出任务输入或输出上限时不会静默截断或自动拆批，而是要求作者缩小或脱敏材料。

简历任务包含：

- `resume-parse`：24K 输入、6K 输出，只生成结构化导入候选，不写主简历。
- `resume-tailor`：24K 输入、6K 输出，只返回允许字段的修改前后、理由和证据 ID；逐项确认后另存岗位子版本。

本地 JD 关键词匹配、字段编辑、实时预览和 PDF/HTML 导出不调用模型。

## 成本与隐私

- `/models` 展示 Provider 状态、任务和用量账本。
- 账本只记录任务类型、Provider、模型、估算/实际 Token、耗时、状态和费用。
- 账本不保存正文、完整提示词、响应、Cookie 或 API Key。
- 外部价格按每百万 Token 配置；本地和人工桥接费用记为零。
- ChatGPT/Codex 登录态和订阅凭证不会被应用读取。

## 当前限制与失败处理

- 本地端点非回环、外部 Provider 未启用、非法结果或来源虚构都会被拒绝。
- 模型结果始终是候选；未经确认不能修改知识、文章、档案事实或职位状态。
- 定时周回顾只能使用规则版。

## 相关文档与测试

- [个人决策助手](assistant.md)
- [系统架构](../architecture/README.md)
- 测试：`test_model_gateway.py`、`test_llm.py`、`test_assistant.py`
