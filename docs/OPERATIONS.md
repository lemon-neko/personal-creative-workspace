# 运行与维护

本文是本地安装、启动、配置、迁移、备份和排障的权威来源。隐私原则和禁止事项见 [安全说明](SECURITY.md)。

## 运行要求

- macOS，建议开启 FileVault。
- Python 3.13 为推荐和主验证版本；CI 额外保留 Python 3.11 兼容验证。
- Android PWA 可选，需要 Mac 和 Android 加入同一个私人 Tailnet。
- Obsidian 可选，只使用内置 Templates、Properties、Backlinks 和 Graph View。
- 完整运行不需要 Node.js、前端构建系统、云数据库或模型 API Key。

## 安装与桌面启动

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/python -m app
```

`requirements.txt` 保留兼容范围，`requirements.lock` 是日常运行和 CI 的可复现安装入口。

桌面地址：<http://127.0.0.1:8765>。

启动器固定监听回环地址。不要使用 `0.0.0.0`、局域网地址、反向代理或公网平台启动完整工作台。

### 使用临时数据目录

开发、测试和迁移演练必须使用临时目录：

```bash
WORKSPACE_DATA_DIR=/tmp/pcw-sandbox .venv/bin/python -m app
```

生产式本地数据默认位于：

```text
~/Library/Application Support/personal-creative-workspace/
```

目录首次创建后权限应为 `0700`，其中私有文件应为 `0600`。

## 环境变量

| 变量 | 默认值 | 用途 |
|---|---|---|
| `WORKSPACE_DATA_DIR` | macOS Application Support 目录 | 覆盖私有数据根目录 |
| `LOCAL_LLM_BASE_URL` | 空 | 本地 OpenAI-compatible 回环端点 |
| `LOCAL_LLM_API_KEY` | 空 | 本地端点可选鉴权，不写入仓库 |
| `LOCAL_LLM_MODEL` | 空 | 本地模型名称 |
| `LLM_BASE_URL` | 空 | 外部 OpenAI-compatible 端点 |
| `LLM_API_KEY` | 空 | 外部 API Key |
| `LLM_MODEL` | 空 | 外部模型名称 |
| `MODEL_ALLOW_EXTERNAL` | 关闭 | 设为 `1`、`true` 或 `yes` 才允许外部 Provider |
| `MODEL_INPUT_PRICE_PER_M` | 设置页价格 | 每百万输入 Token 的价格覆盖值 |
| `MODEL_OUTPUT_PRICE_PER_M` | 设置页价格 | 每百万输出 Token 的价格覆盖值 |
| `OPENCUT_REPO_DIR` | `~/workspace/OpenCut` | 本地 OpenCut 仓库位置，仅用于检查和交接提示 |

不要把这些变量写入被 Git 跟踪的 `.env`。设置页会展示模型目标地址并区分本地与外部服务。

## Android PWA 与 Tailscale

### 1. 建立私人 Tailnet

在 Mac 和 Android 安装 Tailscale，登录同一个不与陌生人共享的账号或 Tailnet。确认两台设备都在线。

### 2. 配置 Serve

只将 Tailnet HTTPS 代理到移动网关：

```bash
tailscale serve --bg http://127.0.0.1:8766
tailscale serve status
```

状态应显示一个 `.ts.net` HTTPS 地址代理到 `127.0.0.1:8766`。不要启用 Funnel。

### 3. 启用移动配置

1. 打开桌面“设置 → 手机同步”。
2. 填写 Tailscale Serve 提供的主机名，不包含路径。
3. 显式启用移动功能。

### 4. 启动移动网关

```bash
.venv/bin/python -m app.mobile_launcher
```

启动器会拒绝以下状态：Tailscale 未登录、Serve 未指向 `127.0.0.1:8766`、Serve 主机与设置不一致、Funnel 已启用或私有目录权限异常。

### 5. 配对与安装

1. 桌面设置页生成十分钟有效的一次性配对码。
2. 手机 Chrome 打开 Tailnet HTTPS 地址并提交配对码。
3. 浏览器菜单选择“安装应用”或“添加到主屏幕”。
4. 后续从桌面图标进入，不需要再次输入地址；设备被撤销后需要重新配对。

移动网关与桌面服务需要同时保持运行。可以使用下文的用户级 `launchd` 管理命令常驻运行。

## 本机常驻运行

安装桌面服务：

```bash
.venv/bin/python -m app.runtime install
```

同时安装移动网关：

```bash
.venv/bin/python -m app.runtime install --mobile
```

查询、重启或卸载：

```bash
.venv/bin/python -m app.runtime status
.venv/bin/python -m app.runtime restart --mobile
.venv/bin/python -m app.runtime uninstall --mobile
```

`/settings/runtime` 只读展示 LaunchAgent、端口、Tailscale Serve/Funnel、数据权限和最近日志时间。LaunchAgent 不保存 API Key；日志超过 5 MB 时在安装或重启前轮转一份历史文件。

## Obsidian 设置

1. 在 Obsidian 打开私有 `content/` 作为 Vault。
2. 进入工作台 `/settings/obsidian` 初始化模板并重建导航。
3. 在 Obsidian 启用内置 Templates，模板目录设为 `_templates`。
4. 附件目录设为 `assets`，使用 Markdown 链接并开启自动更新内部链接。
5. 建议在 Graph View 排除 `trash`、`archive`、`outputs/reviews`、`knowledge/inbox`、`knowledge/indexes` 和 `_templates`。

不要启用 Obsidian Sync、Local REST API 或来源不明的社区插件。`.obsidian/` 不进入 Git 或加密备份。

## 私有数据迁移

### 从仓库旧目录复制到私有根

默认只预演：

```bash
.venv/bin/python -m app.migrate_private_data
```

确认目标、冲突和 SHA-256 后再执行：

```bash
.venv/bin/python -m app.migrate_private_data --apply
```

迁移幂等，不自动删除旧文件。

### 生命周期目录迁移

旧 `content/items/*.md` 按类型迁入 thoughts、articles 或 reviews：

```bash
.venv/bin/python -m app.migrate_vault
.venv/bin/python -m app.migrate_vault --apply
```

应用前执行 dry-run；冲突不覆盖。成功后旧目录会改名保留为回滚副本。

### Obsidian 旧知识结构整理

在 `/settings/obsidian` 完成，不使用命令行：

1. 查看覆盖、冲突、未拆卡和文件重命名预览。
2. 处理文件名冲突。
3. 输入页面确认词后应用。
4. 系统先在私有迁移目录建立快照；可恢复最近一次整理前版本。

## 加密备份与恢复

### 导出

1. 进入“设置 → 加密备份”。
2. 输入不会被保存的备份口令。
3. 生成 AES-256 加密包和清单。
4. 把备份复制到受信任的离线位置，并与 Mac 分开保存。

备份包含 Markdown、SQLite 一致性快照、上传文档和视频项目；不包含模型密钥、会话密钥、临时任务、`.obsidian/` 或旧备份。

### 恢复

1. 先选择备份并输入口令，只执行检查和冲突预览。
2. 系统验证数据版本、清单和 SHA-256。
3. 只有再次输入恢复确认词后才替换数据。
4. 替换前保留可回滚快照。
5. 恢复后重新配对手机并重新登记 Obsidian Vault。

错误口令、内容篡改、版本不兼容或清单缺失必须安全失败。首次正式使用前至少完成一次隔离目录恢复演练。

### 恢复锚点与隔离演练

先生成不包含正文、只包含数量、迁移版本和聚合校验和的恢复锚点：

```bash
.venv/bin/python -m app.recovery inventory \
  --output /absolute/private/location/recovery-anchor.json
```

再把下载的加密包恢复到一个不存在或为空的新目录：

```bash
.venv/bin/python -m app.recovery exercise /absolute/path/backup.zip \
  --target /absolute/path/isolated-restore \
  --confirm ISOLATED-RESTORE
```

命令会在终端安全询问口令，不接受命令行明文口令。核对 Markdown、数据库版本、附件和知识导航后再决定是否切换日常数据；工具不会自动替换当前数据根。

## 开发与 CI 验证

```bash
WORKSPACE_DATA_DIR=/tmp/pcw-test-runtime .venv/bin/pytest -q
.venv/bin/ruff check app tests tools
.venv/bin/python tools/security_guards.py
WORKSPACE_DATA_DIR=/tmp/pcw-import .venv/bin/python -c "from app.asgi import app; print(app.title)"
```

CI 以 Python 3.13 为主并保留 Python 3.11 兼容测试，另有独立 Ruff 和私有数据守卫。Python 3.13 任务还会检查高风险模块逐个达到 80% 覆盖率，并执行 Playwright 桌面与移动关键流程。

## 常见故障

### 页面显示“拒绝跨站请求”

- 确认使用 `http://127.0.0.1:8765`，不要混用 `localhost`、局域网 IP 和其他端口。
- 刷新原始表单页面后重新提交，避免使用旧 CSRF 页面。
- 手机端确认使用配置的 Tailnet HTTPS 主机，而不是 `127.0.0.1:8766`。

### 8765 或 8766 已被占用

先确认占用者确实是旧羽白工作台进程，再正常停止旧进程并重新启动。不要盲目结束其他 Python 服务。

### 移动启动提示 Serve 主机不一致

- 执行 `tailscale serve status` 查看实际 HTTPS 主机和目标端口。
- 回到桌面手机设置保存同一个 `.ts.net` 主机。
- 确认代理目标为 `http://127.0.0.1:8766`，且 Funnel 关闭。

### 手机配对后仍被拒绝

- 确认 Mac 与手机在同一私人 Tailnet。
- 重新生成未过期的一次性配对码。
- 使用系统 Chrome 或已安装 PWA，不要从微信内置浏览器提交。
- 检查设备是否已在桌面设置中被撤销。

### Obsidian 文件出现格式诊断

- 普通新笔记应先放入 `sources/inbox/`，知识模板应放入 `knowledge/inbox/`。
- 正式文件必须保留工作台 front matter 中的稳定 ID、类型和状态。
- 不手动移动或重命名正式文件；使用工作台的迁移预演和确认流程。
- 修复正文后重新执行“扫描外部修改”，不要删除原文件绕过诊断。

### 知识图为空或关系不完整

- 检查知识卡是否为非归档状态，并关联有效主题和来源。
- 在 Obsidian 设置页扫描修改并重建分层导航。
- 概念不会显示为图节点；来源需要点击知识卡后才会展开。
