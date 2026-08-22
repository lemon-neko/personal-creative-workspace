# 隐私与恢复

## 定位与状态

状态：🟡 一期可用。完整工作台只供作者本机使用，代码可保存到私有 GitHub，想法、知识、求职数据、附件、模型任务和备份全部位于仓库之外。

## 网络和浏览器边界

- 桌面固定监听 `127.0.0.1:8765`；移动固定监听 `127.0.0.1:8766`。
- 校验客户端、Host、Origin、CSRF 和代理转发头，拒绝 DNS 重绑定和跨站 POST。
- 不配置 CORS，不启用 OpenAPI、Swagger、ReDoc 或公网部署。
- 私人响应使用 `no-store`、CSP、禁止嵌入和 MIME 嗅探保护。

## 私有存储和上传

- 默认数据根位于 macOS Application Support，目录与文件权限为 `0700/0600`。
- Markdown 与附件使用跨进程锁、临时文件、`fsync` 和原子替换。
- 上传同时校验扩展名、文件签名、大小、数量、文件名和路径边界。
- 拒绝 HTML、SVG、宏文档、脚本、可执行文件和伪造扩展名。
- 私人附件只通过受保护路由访问，不进入 `/static`。

## Git、备份与恢复

- `.gitignore` 和安全守卫排除内容、数据库、Canvas、上传、模型任务、备份、`.env` 和密钥。
- AES-256 备份包含版本、清单和 SHA-256；口令不保存。
- 恢复先在临时目录验证版本和校验和，二次确认后才替换，并保留回滚快照。
- `.obsidian/`、API Key、设备会话、模型临时任务和旧备份不进入内容备份。
- 推荐开启 macOS FileVault，并定期完成一次隔离恢复演练。

## 当前限制与失败处理

- GitHub 仓库私有不能替代本地网络边界。
- 完全离线的已配对手机无法被远程擦除。
- 正式备份恢复仍需要作者本人输入口令和确认词。
- 发现敏感内容进入 Git 历史时，应先停止推送并单独评估，不能在普通功能修改中破坏性清理。

## 相关文档与测试

- [备份与恢复](../operations/backup-restore.md)
- [系统存储](../architecture/storage.md)
- 测试：`test_backup.py`、`test_database.py`、`test_recovery.py`、`test_app.py`
- 安全检查：`tools/security_guards.py`
