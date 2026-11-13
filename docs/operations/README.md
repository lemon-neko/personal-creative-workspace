# 运行维护

## 运行要求

- macOS，建议开启 FileVault。
- Python 3.13 是主验证版本，CI 保留 Python 3.11 兼容验证。
- Android PWA 可选，需要 Mac 和 Android 加入同一个私人 Tailnet。
- Obsidian 可选，只使用内置 Templates、Properties、Backlinks 和 Graph View。
- 日常运行不需要 Node.js、云数据库或模型 API Key。

## 安装与桌面启动

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/python -m app
```

浏览器访问 <http://127.0.0.1:8765>。启动器固定绑定回环地址，不要使用 `0.0.0.0`、局域网地址、反向代理或公网平台运行完整工作台。

开发和测试应使用源码仓库之外的临时数据目录。启动器会拒绝位于源码目录内的数据根。

```bash
WORKSPACE_DATA_DIR="$(mktemp -d)" .venv/bin/python -m app
```

默认私有数据根为：

```text
~/Library/Application Support/personal-creative-workspace/
```

## 环境变量

| 变量 | 默认 | 用途 |
|---|---|---|
| `WORKSPACE_DATA_DIR` | macOS Application Support | 覆盖私有数据根 |
| `LOCAL_LLM_BASE_URL` | 空 | 本地回环 OpenAI-compatible 端点 |
| `LOCAL_LLM_API_KEY` | 空 | 本地端点可选鉴权 |
| `LOCAL_LLM_MODEL` | 空 | 本地模型名 |
| `LLM_BASE_URL` | 空 | 外部 OpenAI-compatible 端点 |
| `LLM_API_KEY` | 空 | 外部 API Key |
| `LLM_MODEL` | 空 | 外部模型名 |
| `MODEL_ALLOW_EXTERNAL` | 关闭 | 显式允许外部 Provider |
| `MODEL_INPUT_PRICE_PER_M` | 设置页价格 | 每百万输入 Token 价格 |
| `MODEL_OUTPUT_PRICE_PER_M` | 设置页价格 | 每百万输出 Token 价格 |
| `OPENCUT_REPO_DIR` | 本地工作区下的 OpenCut | OpenCut 检查与交接提示 |
| `WECHAT_APP_ID` | 空 | 公众号 AppID；仅作为钥匙串之外的后端兼容配置 |
| `WECHAT_APP_SECRET` | 空 | 公众号 AppSecret；仅后端读取，不进入页面、数据库或日志 |

不要把真实密钥写入被 Git 跟踪的 `.env`。日常运行优先在 `/settings/wechat` 写入 macOS 钥匙串；环境变量适合临时启动，且不会自动写入 LaunchAgent。

## 本机常驻运行

```bash
.venv/bin/python -m app.runtime install
.venv/bin/python -m app.runtime install --mobile
.venv/bin/python -m app.runtime status
.venv/bin/python -m app.runtime restart --mobile
.venv/bin/python -m app.runtime uninstall --mobile
```

`/settings/runtime` 只读展示 LaunchAgent、端口、Tailnet、数据权限和日志时间。LaunchAgent 不保存 API Key，日志达到限制时轮转。

更新 Python 代码与模板后，执行 `.venv/bin/python -m app.runtime restart`，并检查实际页面能够正常打开；桌面启动器不启用自动重载，浏览器刷新不能代替服务重启。仅涉及桌面功能时无需使用 `--mobile`。

## Obsidian 初始化

1. 在 Obsidian 把私有 `content/` 打开为 Vault。
2. 在 `/settings/obsidian` 初始化模板并重建导航。
3. 启用内置 Templates，把模板目录设为 `_templates`。
4. 附件目录设为 `assets`，使用 Markdown 链接并开启内部链接自动更新。
5. 不启用 Obsidian Sync、Local REST API 或来源不明的社区插件。

## 私有数据迁移

仓库旧目录迁移先预演，再执行：

```bash
.venv/bin/python -m app.migrate_private_data
.venv/bin/python -m app.migrate_private_data --apply
```

旧 `content/items/` 生命周期迁移：

```bash
.venv/bin/python -m app.migrate_vault
.venv/bin/python -m app.migrate_vault --apply
```

迁移幂等且不覆盖冲突。Obsidian 旧知识结构整理在设置页预演和确认，应用前会创建私有快照。

## 延伸文档

- [手机安装与 Tailnet](mobile-tailscale.md)
- [备份与恢复](backup-restore.md)
- [常见故障](troubleshooting.md)
- [测试与 CI](../development/testing.md)

- [桌面插件安装、切换与恢复](workbench-plugins.md)
