# 手机安装与 Tailnet

## 前提

Mac 和 Android 必须加入同一个私人 Tailnet，并且 Tailnet 不与不受信任成员共享。移动功能默认关闭。

## 配置 Serve

```bash
tailscale serve --bg http://127.0.0.1:8766
tailscale serve status
```

状态应显示 Tailnet HTTPS 地址代理到 `127.0.0.1:8766`。禁止启用 Funnel。

## 启用和启动

1. 打开桌面“设置 → 手机同步”。
2. 填写 Tailscale Serve 提供的主机名，不包含路径。
3. 显式启用移动功能。
4. 启动移动网关：

```bash
.venv/bin/python -m app.mobile_launcher
```

启动器会拒绝 Tailscale 未登录、Serve 目标错误、主机不一致、Funnel 开启或数据权限异常。

## 配对与安装

1. 桌面设置页生成十分钟有效的一次性配对码。
2. 手机 Chrome 打开 Tailnet HTTPS 地址并提交配对码。
3. 浏览器菜单选择“安装应用”或“添加到主屏幕”。
4. 后续从桌面图标进入；设备被撤销后需要重新配对。

手机默认打开「日常工作」。在平时使用的桌面浏览器打开工作台「日常工作」，等待同步后在手机点「刷新」。

首次联网进入「随手记 → 我的随想」会下载未归档随想快照。离线修改在恢复网络后携带 Revision 同步；若 Mac 或 Obsidian 已修改同一文件，必须人工合并。

## 日常检查

- 桌面 8765 和移动 8766 都应运行。
- Tailscale Serve 必须指向 8766，Funnel 必须关闭。
- 手机日常看板只读。桌面日常工作页在前台时约每分钟同步一次，手机刷新后显示最近同步时间。
- 丢失手机时先撤销设备，并使用 Android 系统远程锁定或擦除。

移动功能边界见 [Android PWA](../features/mobile-pwa.md)。
