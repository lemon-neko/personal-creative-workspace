# 功能模块

本目录是“当前工作台能做什么”的权威来源。状态分为：✅ 已可用、🟡 一期可用、🧪 实验性、⏳ 未实现。阶段判断和近期优先级见 [项目状态](../../PROJECT_STATUS.md)。

| 状态 | 模块 | 主要入口 | 说明 |
|---|---|---|---|
| ✅ | [工作台与内容](workspace-content.md) | `/`、`/ideas`、`/reviews`、`/articles` | 随想、周回顾和文章分区管理，支持生命周期、回收和搜索 |
| 🧪 | [本地任务运行时](agent-runtime.md) | `/tasks`、`/runs` | 项目、任务、规则式角色、本地运行轨迹与私有产物确认 |
| 🟡 | [知识库与 Obsidian](knowledge-obsidian.md) | `/knowledge`、`/settings/obsidian` | 随想拆卡、知识地图、来源 Revision、核心图和零复制 Vault |
| ✅ / 🟡 | [公众号与视频](publishing-video.md) | `/publish`、`/video` | 文章专属微信排版，以及视频分镜与制作交接 |
| 🟡 | [求职与学习](career-learning.md) | `/career`、`/career/resumes`、`/learning` | 事实档案、简历工作室、岗位定制、职位、能力差距和 Agent 工程四阶段路线 |
| 🟡 | [收入面板](income.md) | `/income`、`/income/opportunities`、`/income/entries` | 四个固定方向、需求证据与反诈验证、手工账本和首个数字产品闭环 |
| 🟡 | [个人决策助手](assistant.md) | `/assistant` | 先预览再调用、来源可追溯、行动逐项确认 |
| ✅ | [模型与成本](model-cost.md) | `/models` | 规则、本地、人工和外部 Provider，Token 上限与费用账本 |
| 🟡 | [Android PWA](mobile-pwa.md) | 移动网关、`/settings/mobile` | Tailnet 私网记录、离线编辑、冲突合并和离线知识阅读 |
| 🟡 | [隐私与恢复](privacy-recovery.md) | `/settings`、`/settings/backups` | 本地边界、安全上传、Git 守卫、加密备份和隔离恢复 |

## 共同边界

- Mac 是唯一权威数据源，私人内容不进入仓库。
- `published` 在本项目中表示“已整理/已成稿/已确认”，不代表公网公开。
- 页面加载、保存、定时任务和后台线程不会自动调用模型。
- 原始来源不会被拆卡、总结、润色、发布或视频流程覆盖。
- 完整桌面工作台不提供公网部署、账号系统或第三方公共 API。
