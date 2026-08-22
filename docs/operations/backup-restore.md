# 备份与恢复

## 加密导出

1. 进入“设置 → 加密备份”。
2. 输入不会被应用保存的口令。
3. 生成 AES-256 加密包、数据版本、文件清单和 SHA-256。
4. 把备份复制到可信离线位置，并与 Mac 分开保存。

备份包含 Markdown、SQLite 一致性快照、上传文档和视频项目；不包含 API Key、会话密钥、模型临时任务、`.obsidian/`、已有备份或移动离线副本。

## 恢复预演

1. 选择备份并输入口令，先只执行解密、版本和冲突检查。
2. 系统验证清单与 SHA-256。
3. 恢复到不存在或为空的隔离目录，检查 Markdown、数据库、附件和知识导航。
4. 只有再次输入严格确认词后才允许替换日常数据。
5. 替换前保留可回滚快照；恢复后重新配对手机并重新登记 Obsidian Vault。

错误口令、内容篡改、版本不兼容和清单缺失必须安全失败。

## 恢复锚点

恢复锚点只包含数量、迁移版本和聚合校验和，不包含正文：

```bash
.venv/bin/python -m app.recovery inventory \
  --output /absolute/private/location/recovery-anchor.json
```

隔离恢复：

```bash
.venv/bin/python -m app.recovery exercise /absolute/path/backup.zip \
  --target /absolute/path/isolated-restore \
  --confirm ISOLATED-RESTORE
```

命令在终端安全询问口令，不接受命令行明文口令。首次正式使用前至少完成一次真实隔离恢复演练。

安全边界见 [隐私与恢复](../features/privacy-recovery.md)。
