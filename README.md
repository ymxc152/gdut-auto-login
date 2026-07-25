# GDUT 校园网自动登录

一个面向 Windows 10/11 x64 的 GDUT 校园网监测与自动认证桌面应用，同时支持有线和无线网络接口。

普通用户只需要下载一个 EXE。程序已经内置 Python、Tk 图形界面、psutil、SQLite 和全部运行依赖，不需要另外安装 Python，也不需要执行命令行脚本。

> 只能配置本人拥有或已获得明确授权使用的校园网账号。使用者必须遵守学校网络管理规定，不得扫描、猜测、借用或尝试未经授权的账号。

## 下载和安装

1. 从项目 Releases 下载 `GDUTAutoLogin-1.1.0-win64.exe`。
2. 双击 EXE。
3. 程序会自动安装到当前用户目录，不需要管理员权限。
4. 首次打开时，在中文界面选择名称、网络配置文件或无线 SSID 包含 `GDUT` 的接口。
5. 输入本人拥有或已获授权的校园网账号和密码。
6. 点击“保存并启动”。

安装完成后：

- 程序位于 `%LOCALAPPDATA%\Programs\GDUTAutoLogin`；
- 个人数据位于 `%LOCALAPPDATA%\GDUTAutoLogin`；
- 开始菜单中会出现“GDUT 校园网自动登录”；
- Windows 登录后会自动静默启动后台监控；
- 下载目录中的原始 EXE 可以删除。

## 无需安装运行环境

发布版采用 PyInstaller `--onefile --windowed` 构建，EXE 内已包含：

- Python 3.13 运行时；
- Tk/Tcl 图形界面运行库；
- psutil 网卡检测依赖；
- SQLite 数据库支持；
- Windows DPAPI 调用代码；
- 应用全部 Python 模块。

目标用户电脑不需要安装 Python、pip、psutil 或其他第三方组件。

## 图形界面

v1.1.0 使用现代化侧边栏布局，提供“概览、连接、账号、日志、更新、设置”六个页面。概览集中展示网络状态和最近活动；连接页面明确显示实际 GDUT 网络配置文件、接口、MAC 与绑定源 IP。

### 概览

显示：

- 当前网络状态；
- 识别到的 GDUT 有线或无线接口；
- 当前校园网 IPv4 地址；
- 后台监控是否运行；
- 最后检查时间；
- 上次成功账号的脱敏结果；
- 最近一次错误。

可以手动执行：

- 立即检查；
- 检查并在需要时重新登录；
- 启动后台监控；
- 停止后台监控。

### 账号

- 添加本人或已获授权的账号；
- 更新已有账号的密码；
- 删除不再使用的账号；
- 查看账号尝试顺序和上次成功账号；
- 所有账号在界面和日志中都会脱敏。

账号与密码整体使用 Windows DPAPI 加密。加密文件只能由创建它的 Windows 用户在原电脑上解密。

### 连接与设置

可以设置：

- GDUT 有线或无线网络接口；
- 网络正常时的检查间隔；
- 网卡异常时的重试间隔；
- 登录失败后的冷却时间；
- 是否发送 Windows 失败通知；
- 是否登录 Windows 后自动静默启动；
- 日志数据库容量上限；
- 日志保留时间。

程序先用不区分大小写的 `gdut` 关键字匹配网卡别名、Windows 网络配置文件名称或无线 SSID，再使用接口索引和物理 MAC 地址锁定接口。其他 Wi-Fi、VPN、虚拟机网卡或有线接口不会掩盖 GDUT 接口的认证状态。

### 日志

日志使用本地 SQLite 数据库保存，可以：

- 在图形界面直接查看；
- 按全部、今天、7 天、30 天或 90 天筛选；
- 按 INFO、WARNING、ERROR、CRITICAL 筛选；
- 导出为 UTF-8 CSV；
- 清空全部日志；
- 设置数据库容量上限；
- 设置保留全部、7 天、30 天、90 天或 180 天。

默认配置：

- 容量上限：20 MB；
- 保留时间：全部。

“保留全部”表示不按日期主动删除，但仍受容量上限保护。数据库超过容量上限时，会从最旧记录开始清理。

日志不会记录密码，账号会被脱敏。

## 后台运行方式

同一个 EXE 有两个角色：

```text
普通双击
  └─ 打开中文管理界面

Windows 开机任务
  └─ GDUTAutoLogin.exe --monitor
       └─ 无控制台、无主窗口、定时检查网络
```

后台任务使用无控制台的 Windows GUI 子系统运行。正常监控过程中不会弹出黑色命令行窗口，也不会因为关闭管理界面而停止。

默认每 30 秒检查一次指定网卡。检测到认证重定向或网络不可用时，程序会自动尝试恢复认证。全部授权账号均失败时，写入 CRITICAL 日志并发送 Windows 系统通知；通知具有冷却时间，不会持续弹出。

计划任务配置了异常重启，后台进程意外退出时 Windows 会尝试重新启动。

## 多网卡电脑

程序不会检查“电脑是否整体能上网”，而是把探测请求绑定到配置的 GDUT 网卡源 IP。

例如：

- Wi-Fi 可以上网；
- 名称或网络配置文件包含 GDUT 的接口已经失去认证；

此时程序仍会正确判断 GDUT 接口需要重新登录，而不会被其他接口的联网状态误导。

如果更换了 USB 网卡、扩展坞、有线接口或无线网卡，请先连接名称/SSID 包含 GDUT 的网络，再在“网络与设置”中重新选择接口并保存。

## 更新

后台服务默认每天检查一次项目 GitHub Release。发现新版后只发送通知，不会在用户不知情时安装。

在“更新”页面可完成：

1. 检查最新稳定版本和发布说明；
2. 从项目 GitHub Release 下载对应 EXE 与 `SHA256SUMS.txt`；
3. 校验下载大小和 SHA-256，失败时拒绝执行；
4. 用户明确确认后停止旧后台任务并备份旧 EXE；
5. 替换程序，启动新版并等待健康自检；
6. 新版启动失败或超时则恢复备份并重新打开旧版。

账号、配置和日志都位于独立的数据目录，更新不会覆盖个人数据。当前发行版没有 Authenticode 证书，因此更新器不会静默安装未知新版；Windows 仍可能显示 SmartScreen“未知发布者”。

## 卸载

打开应用，在“关于”页面点击“卸载程序”。

可以选择：

- 只删除程序和开机任务，保留账号、设置与日志；
- 同时删除所有个人数据。

卸载不需要管理员权限。

## 数据和隐私

| 路径 | 内容 |
| --- | --- |
| `%LOCALAPPDATA%\Programs\GDUTAutoLogin` | 安装后的 EXE |
| `%LOCALAPPDATA%\GDUTAutoLogin\config.json` | 网卡、间隔和日志设置，不含密码 |
| `%LOCALAPPDATA%\GDUTAutoLogin\accounts.dat` | DPAPI 加密账号与密码 |
| `%LOCALAPPDATA%\GDUTAutoLogin\state.json` | 上次成功账号等状态 |
| `%LOCALAPPDATA%\GDUTAutoLogin\status.json` | 最近网络状态 |
| `%LOCALAPPDATA%\GDUTAutoLogin\events.db` | SQLite 运行日志 |

注意：

- DPAPI 数据不能直接迁移到另一台电脑或另一个 Windows 用户；
- 更换电脑后应重新添加账号；
- 日志未加密，但不会记录密码，账号会脱敏；
- 公开源代码仓库不得包含本机账号、网卡配置或日志数据库。

## Windows SmartScreen 和代码签名

当前本地构建的 EXE 没有 Authenticode 代码签名。首次下载时 Windows SmartScreen 可能显示“未知发布者”。

正式公开发布时强烈建议：

1. 使用可信 CA 签发的代码签名证书；
2. 使用 SHA-256 签名；
3. 使用可信时间戳服务；
4. 在 Release 页面同时发布 SHA-256 校验值；
5. 每个版本都从干净环境重新构建和测试。

示例签名命令：

```powershell
signtool sign /fd SHA256 /td SHA256 /tr https://timestamp.example.com /a .\GDUTAutoLogin-1.1.0-win64.exe
```

仓库不会包含私钥或证书密码。代码签名证书必须由发布者自行安全保管。

## 校验下载文件

Release 同时提供 `SHA256SUMS.txt`。用户可以执行：

```powershell
Get-FileHash .\GDUTAutoLogin-1.1.0-win64.exe -Algorithm SHA256
```

结果应与 `SHA256SUMS.txt` 完全一致。

## 从源代码构建

开发环境：

- Windows 10/11 x64；
- Python 3.10 或更高版本；
- 建议使用与正式发布一致的 Python 版本。

构建：

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

构建脚本会自动：

1. 安装运行依赖；
2. 安装 PyInstaller；
3. 执行自动测试；
4. 生成无控制台单文件 EXE；
5. 在独立空数据目录运行打包后自检；
6. 生成 SHA-256 校验文件。

输出位置：

```text
release/GDUTAutoLogin-1.1.0-win64.exe
release/SHA256SUMS.txt
```

## 测试

```powershell
python -m unittest discover -s tests -v
python app.py --self-test .\self-test.json
```

打包后的 EXE 还支持发布自检参数：

```powershell
.\GDUTAutoLogin-1.1.0-win64.exe --self-test .\self-test.json
```

自检会验证冻结运行环境、配置数据库、psutil 网卡枚举和应用模块加载，不会自动提交任何个人数据。

## 已考虑的发布问题

- 单 EXE 运行环境打包；
- 无管理员权限安装；
- 安装路径稳定，下载文件可删除；
- 开机静默启动；
- 后台崩溃重启；
- 多网卡源 IP 绑定；
- DPAPI 凭据保护；
- SQLite 日志容量和时间清理；
- CSV 日志导出；
- 配置与程序分离，升级不覆盖数据；
- 单实例监控和跨进程操作锁；
- 失败通知冷却；
- 开始菜单快捷方式；
- 图形化卸载和可选数据清理；
- 干净数据目录的打包后自检；
- SHA-256 发布校验；
- SmartScreen 与代码签名说明。

尚未启用的功能：

- 云端同步账号；
- 跨电脑迁移 DPAPI 凭据；
- macOS/Linux 支持；
- 未签名构建自动绕过 SmartScreen。

这些功能涉及发布服务器、签名密钥或不同平台的系统能力，不应在缺少可靠安全设计时默认启用。

## 开源许可证

项目采用 [MIT License](LICENSE)。中文理解说明见 [LICENSE.zh-CN.md](LICENSE.zh-CN.md)。如存在差异，以英文 `LICENSE` 为准。

MIT License 允许使用、复制、修改、分发、商业使用和再许可，但分发时必须保留版权声明、许可证文本和免责声明。

MIT License 只授予软件著作权层面的许可，不授予任何校园网账号、网络资源或认证系统的访问权限。
