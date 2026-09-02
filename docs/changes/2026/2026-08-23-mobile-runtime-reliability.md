---
date: 2026-08-23
status: completed
type: fix
areas:
  - mobile-pwa
  - local-runtime
interfaces:
  - app.runtime CLI
data_migration: none
compatibility: preserved
rollback: revert this fix and reinstall the previous LaunchAgent configuration
verification:
  - 199 pytest tests
  - Ruff
  - security guard
  - desktop loopback HTTP 200
  - Tailnet mobile HTTP 200
commit: pending
---

# 手机网关常驻修复

## 背景与目标

Tailscale 与 Serve 配置正常时，移动页面仍可能因为 8766 手机网关没有运行而无法访问。常驻配置还可能把虚拟环境 Python 的符号链接解析为基础解释器，导致后台进程缺少 Uvicorn 等项目依赖。

## 最终行为

- LaunchAgent 保留仓库 `.venv/bin/python` 入口，不再解析到基础解释器。
- 后台进程获得 Tailscale macOS CLI 所需的最小用户运行环境和受控 PATH。
- 安装依赖 `RunAtLoad` 启动服务，不再额外执行可能阻塞的同步 kickstart。
- 桌面与移动服务继续只监听各自的回环端口；移动访问仍只经过 Tailnet Serve，禁止 Funnel。

## 接口与数据

没有新增页面、外部接口或数据格式。修复只影响 `app.runtime` 生成和加载用户级 LaunchAgent 的方式，不迁移私人数据。

## 兼容与回滚

现有手机配对、会话、Markdown、SQLite 和 Tailscale Serve 配置保持不变。回滚代码后重新安装旧 LaunchAgent 即可；回滚不会删除内容或设备记录。

## 验证结果

- 完整 Pytest：199 项通过。
- Ruff、Git 安全守卫与应用工厂导入通过。
- 桌面回环入口返回 HTTP 200。
- Tailnet 私网手机入口返回 HTTP 200，未配对请求显示配对页。

## 同步文档

- [Android PWA](../../features/mobile-pwa.md)
- [常见故障](../../operations/troubleshooting.md)
