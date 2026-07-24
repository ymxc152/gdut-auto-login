# 设计说明

## 目标

应用面向不具备 Python 环境的普通 Windows 用户，发布物必须是一个可直接双击的 x64 EXE，并同时满足图形化管理和长期静默监控。

## 进程模型

同一个 EXE 根据参数进入不同模式：

- 无参数：管理界面；
- `--first-run`：完成首次安装后的设置界面；
- `--monitor`：隐藏后台监控；
- `--check-once`：执行一次网络检查；
- `--self-test PATH`：执行发布自检并输出 JSON。

后台监控和图形界面分离。关闭界面不会停止监控；界面崩溃也不会影响计划任务中的监控进程。

## 自安装

下载的 EXE 首次运行时：

1. 停止旧版本后台任务；
2. 复制自身到 `%LOCALAPPDATA%\Programs\GDUTAutoLogin`；
3. 创建开始菜单快捷方式；
4. 从原 EXE 所在目录迁移旧版数据（如果存在）；
5. 启动已安装位置的 EXE；
6. 创建当前用户的隐藏登录触发计划任务。

选择用户目录可以避免管理员权限和 UAC 提权。

## 数据模型

### config.json

保存网卡 MAC、网卡名称、探测间隔、认证入口、日志上限和通知设置，不保存密码。

### accounts.dat

整个账号列表序列化为 JSON 后，通过 Windows DPAPI `CryptProtectData` 加密，再以 Base64 保存。

### events.db

SQLite 数据库，使用 WAL 模式。日志表包含 UTC 时间、级别和消息。界面显示时转换为本地时间。

维护策略同时考虑：

- 按保留天数删除；
- 按数据库总容量删除最旧记录；
- WAL checkpoint；
- 必要时 VACUUM 回收空间。

### status.json

后台监控写入的轻量状态快照。GUI 每两秒读取一次，无需长期持有数据库连接或建立本地网络服务。

## GDUT 接口识别

程序读取 `Get-NetAdapter` 和 `Get-NetConnectionProfile`，把 Windows 网络配置文件或无线 SSID 映射到接口索引。`gdut` 关键字使用 Unicode `casefold()` 匹配，因此不区分大小写。

匹配范围包括：

- 网卡别名；
- Windows 网络配置文件名称；
- 已连接无线网络的 SSID。

只有包含 GDUT 标识的接口才有资格参与检测。匹配后再使用接口索引、物理 MAC 和源 IPv4 地址锁定具体接口。有线和无线接口使用同一套逻辑。

检查请求、登录请求和登录后的复检都通过 `source_address=(selected_ip, 0)` 绑定同一个源 IP，避免其他联网接口影响结果。

当 GDUT 接口不存在、链路断开或没有符合前缀的 IPv4 地址时，程序停止本轮操作，不会切换到其他网卡进行探测或认证。

## 并发控制

- 监控进程使用 Windows Named Mutex 保证单实例；
- 网络检查和登录操作使用第二个 Named Mutex，避免 GUI 与后台任务同时提交认证请求；
- 配置和状态使用临时文件加原子替换写入；
- SQLite 使用 WAL 和短连接，降低 GUI 与监控并发读写冲突。

## 日志安全

- 密码从不写入日志；
- 账号在日志中脱敏；
- 认证响应只记录必要摘要；
- 用户可以在界面清空或导出日志；
- 数据默认只保存在当前用户 LocalAppData。

## 发布模型

PyInstaller 使用：

- `--onefile`：单文件发布；
- `--windowed`：不创建控制台窗口；
- Windows 版本资源：显示产品名和版本；
- 构建后自检：在独立空数据目录运行；
- SHA-256：生成 Release 校验文件。

公开发布前还应增加 Authenticode 签名。签名必须在最终 EXE 生成后、计算发布哈希之前完成。
