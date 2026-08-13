# 羽白工作台

只供作者本人使用的本地个人驾驶舱：接住想法，整理知识，推进创作、求职与学习，并通过私人 Tailnet 从 Android 随时记录。

项目采用 FastAPI、Jinja2、HTMX、Markdown 和 SQLite FTS5。代码可以存放在私有 GitHub 仓库；想法、材料、知识卡、简历、职位、模型任务和上传文件均保存在仓库之外。

当前处于 **本地单用户 Beta**。核心记录、安全边界和 Android 随手记已可用；分层知识库、求职闭环、视频交接处于一期可用阶段。完整成熟度、限制和近期优先级见 [PROJECT_STATUS.md](PROJECT_STATUS.md)。

## 当前能力

- **记录**：桌面单页工作台、Markdown 想法库、搜索筛选、状态流转、回收恢复和规则周回顾。
- **知识**：原始来源、知识卡、学科/主题地图、来源追踪、冲突历史、D3 星图和纯本地检索。
- **创作**：微信公众号正文排版、富文本复制、图片与公式处理、可选幻想栈润色和 OpenCut 视频交接。
- **求职**：候选人档案、私有文档、项目证据、简历版本、职位跟踪、技能差距和学习任务。
- **模型**：规则、本地模型、人工桥接和默认关闭的外部 API；所有外发先预览，Token 与费用只记元数据。
- **移动**：Android PWA 经 Tailscale Serve 私网记录文字与图片，支持一次性配对、离线队列和幂等同步。
- **安全**：仓库外私有数据、回环监听、CSRF/Host/代理头校验、安全响应头、Git 守卫和 AES-256 备份。

## 快速导航

| 区域 | 入口 | 用途 |
|---|---|---|
| 驾驶舱 | `/` | 随手记、内容流、周回顾、创作/求职/学习状态 |
| 想法与知识 | `/ideas`、`/knowledge`、`/library`、`/search` | 内容管理、知识网络、材料和本地统一检索 |
| 创作 | `/publish`、`/reviews`、`/video` | 微信排版、通用回顾和视频交接 |
| 求职与学习 | `/career`、`/learning` | 职位、简历、证据、技能差距和项目战役 |
| 模型与系统 | `/models`、`/settings`、`/trash` | 成本治理、迁移、备份、手机同步和回收站 |

## 安全边界

- 桌面服务固定监听 `127.0.0.1:8765`，不提供公网部署、账号或多用户能力。
- 可选 Android PWA 通过 Tailscale Serve 私网访问独立的 `127.0.0.1:8766` 移动网关；禁止使用 Funnel。
- 同时校验回环客户端、Host、代理头、CSRF 和请求来源。
- 所有页面禁止缓存、禁止嵌入，并设置 CSP 与 MIME 嗅探保护。
- 默认私有目录为 `~/Library/Application Support/personal-creative-workspace/`。
- 私有目录权限为 `0700`，Markdown、数据库、上传文件和模型任务为 `0600`。
- 上传不会进入 `/static`；URL 材料只保存，不会被后台抓取。
- CI 安全守卫拒绝私有目录、密钥和公网部署配置进入 Git。
- 私有 GitHub 仓库不等于私有服务。此前关联的 Vercel 项目、自动部署和公网域名必须保持关闭。

> 磁盘静态数据依赖 macOS FileVault。请确认 FileVault 已开启。

## 本地启动

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m app
```

访问 <http://127.0.0.1:8765>。不要使用 `--host 0.0.0.0`。

临时指定数据目录：

```bash
WORKSPACE_DATA_DIR=/absolute/private/path .venv/bin/python -m app
```

## Android 随手记

手机端是可安装的 PWA，只负责新增文字、标签、分类和最多 5 张图片，以及查看最近记录。它和桌面端共用 Mac 上的同一份 Markdown 与私有配图，不同步 SQLite，也没有编辑、删除、求职、模型、备份或文档下载权限。

1. 在 Mac 与 Android 安装 Tailscale，并登录同一个未共享给陌生人的私人 Tailnet。
2. 配置 Tailscale Serve，仅把 HTTPS 地址代理到移动网关：

   ```bash
   tailscale serve --bg http://127.0.0.1:8766
   ```

3. 在桌面工作台打开“设置 → 手机同步”，填写 Tailscale 提供的 `.ts.net` 主机名并启用。
4. 启动移动网关：

   ```bash
   .venv/bin/python -m app.mobile_launcher
   ```

   启动器会验证 Tailscale 已登录、Serve 指向 `127.0.0.1:8766` 且没有启用 Funnel；任一条件不满足都会拒绝启动。

5. 在桌面端生成十分钟有效的一次性配对码，使用 Android 浏览器打开 Tailscale HTTPS 地址完成配对，再选择“安装应用”或“添加到主屏幕”。已配对后直接从桌面图标进入，不需要反复输入网址。

Mac 离线时，PWA 使用 IndexedDB 暂存未同步的文字与图片；恢复连接后利用幂等键同步，服务端成功回执后删除手机队列。同一条重试不会生成重复 Markdown。离线副本依赖 Android 锁屏和设备磁盘加密，不应在未加锁设备上使用。

移动会话使用 `Secure`、`HttpOnly`、`SameSite=Strict` Cookie，服务端仅保存令牌哈希；可在设置页随时撤销设备。移动数据库、会话密钥、配对码和幂等账本不进入 Git 或加密内容备份。不要启用 Tailscale Funnel，也不要将 8766 暴露到局域网或公网。

当前 Mac 端仍需保持桌面服务与移动网关运行。开机常驻尚未实现，状态与后续优先级见 [PROJECT_STATUS.md](PROJECT_STATUS.md)。

## 信息架构

- `/`：高频操作驾驶舱。
- `/ideas`：原始想法、文章和周回顾管理。
- `/knowledge`：学科地图、主题地图、原子知识卡与跨学科星图。
- `/knowledge/cards/{id}`：知识卡、原始来源和替代历史。
- `/knowledge/maps/{id}`：支持多父级的学科或主题地图。
- `/library`：材料收件箱、阅读队列和页面内阅读抽屉。
- `/search`：本地统一检索；页面内按 `Cmd+K` 可快速打开。
- `/publish`、`/reviews`、`/video`：创作、公众号适配、通用周回顾与视频交接。
- `/career`：档案、文档、项目证据、简历、职位与技能差距。
- `/learning`：技能、学习任务和项目战役。
- `/models`：Provider 状态、硬上限、Token/费用账本与人工任务。
- `/settings`：私有目录、迁移、加密备份与安全边界。
- `/settings/mobile`：移动网关、一次性配对码和 Android 设备撤销。

`/garden` 已删除。底层 `published` 只用于兼容旧内容，界面显示为“已成稿”，不会生成公网页面。

## 私有数据分层

物理目录只表达内容生命周期，逻辑层级由多父级知识地图和关系图表达：

```text
~/Library/Application Support/personal-creative-workspace/
├── content/
│   ├── sources/
│   │   ├── thoughts/          # 原始想法与观察
│   │   └── materials/         # 材料、来源与阅读状态
│   ├── knowledge/
│   │   ├── cards/             # 人工确认后的原子知识卡
│   │   ├── maps/              # 学科地图与主题地图
│   │   └── indexes/           # 可删除、可重建索引
│   ├── outputs/
│   │   ├── articles/          # 文章草稿与成稿
│   │   └── reviews/           # 周回顾
│   ├── assets/                # 受保护配图
│   ├── archive/
│   └── trash/
├── documents/                 # 随机存储名的私有上传
├── video-projects/             # OpenCut 私有交接包
├── workspace.db               # 求职关系、FTS5 与模型账本
├── mobile.db                  # 设备、会话哈希与幂等回执（不进入备份）
├── mobile.secret              # 移动令牌哈希密钥（不进入备份）
├── working/
│   └── model-tasks/            # 7 天后清理，不进入备份
└── backups/
```

原始想法不会因为总结或拆卡而改变。知识卡必须至少关联一个来源；新旧观点冲突时使用 `contrasts`，明确替代时记录 `superseded_by` 和有效截止时间，旧卡正文继续保留。

## 生命周期目录迁移

旧 `content/items/*.md` 不会自动迁移。先在设置页打开“目录迁移预演”，或执行：

```bash
.venv/bin/python -m app.migrate_vault
```

确认目标、冲突和 SHA-256 后再执行：

```bash
.venv/bin/python -m app.migrate_vault --apply
```

迁移会按 `kind` 分流至 thoughts、articles 或 reviews，复制后逐一校验，再把旧目录改名为 `legacy-items-时间戳` 作为回滚副本。冲突不会覆盖。

如果数据尚在旧仓库的 `content/`，先使用 `app.migrate_private_data` 复制到私有根，再执行生命周期迁移。两个命令默认均为 dry-run。

## 模型成本治理

所有模型能力统一经过 `ModelGateway`，Provider 固定为：

1. `rules`：默认策略，不调用网络，定时周回顾只允许该模式。
2. `local`：只接受 `localhost`、`127.0.0.1` 或 `::1` 的 OpenAI-compatible 服务。
3. `manual`：生成可复制任务包，由作者手动交给 ChatGPT/Codex，再粘贴 JSON 返回。
4. `external`：默认关闭；即使配置密钥，也必须逐次预览并确认外发材料。

人工任务保存在 `working/model-tasks/`，7 天后清理，不进入备份。导入结果会先校验结构、来源 ID、关系目标与数量上限；只有再次点击“确认写入”才产生知识卡、周回顾、文章、档案或技能差距，原始来源从不被覆盖。

五类任务硬上限：

| 任务 | 来源上限 | 输入 Token | 输出 Token |
|---|---:|---:|---:|
| 知识拆卡 | 8 | 12,000 | 2,000 |
| 周回顾 | 100 | 12,000 | 3,000 |
| 公众号候选 | 1 | 24,000 | 6,000 |
| 简历档案 | 1 | 24,000 | 2,000 |
| JD 技能 | 1 | 24,000 | 2,000 |

超限内容不会自动截断或拆批。模型账本只记录任务类型、Provider、模型、估算/实际 Token、耗时、状态与费用，不记录正文、提示词、响应或密钥。

### 本地模型

兼容 Ollama、LM Studio 等 OpenAI-compatible 回环端点：

```bash
export LOCAL_LLM_BASE_URL="http://127.0.0.1:11434/v1"
export LOCAL_LLM_MODEL="local-model"
# LOCAL_LLM_API_KEY 可选
```

工作台不安装模型，也不会自动下载权重。

### 外部模型

```bash
export LLM_BASE_URL="https://provider.example/v1"
export LLM_API_KEY="provider-key"
export LLM_MODEL="model-name"
export MODEL_ALLOW_EXTERNAL=1
```

外部调用默认被阻断。价格可在 `/models` 按每百万 Token 保存；环境变量 `MODEL_INPUT_PRICE_PER_M` 与 `MODEL_OUTPUT_PRICE_PER_M` 可覆盖本地价格。ChatGPT/Codex 登录态、Cookie 和订阅凭证不会被应用读取或自动操作。

## 本地检索与材料库

统一搜索使用 SQLite FTS5、中文子串回退、标签和图关系，全程不调用模型或 Embedding API。索引可以删除并从 Markdown、知识卡、材料、求职、学习和视频数据重建。

材料库支持笔记、URL 和本地文档引用。URL 只保存；打开链接必须由作者显式点击。阅读抽屉可在当前页面查看材料、更新阅读状态并创建带来源说明的新想法。

## 加密备份

设置页生成 AES-256 加密 ZIP，包含 Markdown、SQLite 快照、上传文档和视频交接包，不包含密钥、CSRF 令牌、模型临时任务或旧备份。恢复前完成口令、版本、清单和 SHA-256 校验；替换前会保留可回滚快照。

## OpenCut 视频创作

OpenCut 作为独立项目运行，默认目录 `/Users/yubai/workspace/OpenCut`，可通过 `OPENCUT_REPO_DIR` 覆盖。工作台只在私有目录生成 `manifest.yaml`、`brief.md` 和素材副本，不会把文章或配图写入 OpenCut 源码仓库。

## 开发验证

```bash
WORKSPACE_DATA_DIR=/tmp/pcw-test-runtime .venv/bin/pytest -q
.venv/bin/ruff check app tests tools
.venv/bin/python tools/security_guards.py
WORKSPACE_DATA_DIR=/tmp/pcw-import .venv/bin/python -c "from app.main import app; print(app.title)"
```

CI 只使用虚构测试数据。

## 暂不包含

- 外部 Embedding API、Neo4j 或向量数据库。
- 后台自动调用模型、自动抓取 URL 或自动生成知识卡。
- 招聘网站抓取、自动投递、邮件与外部笔记同步。
- 公网部署、账号系统和第三方云数据同步；Android 仅通过私人 Tailnet 回写 Mac 主库。
