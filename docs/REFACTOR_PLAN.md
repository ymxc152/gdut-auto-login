# GDUT 自动登录：现状大纲与「单进程 + 托盘」改造计划

> 写作目的：记录当前代码结构，作为后续修改 / 优化升级的依据。
> 状态：**已实施（2026-10-06）**。P1–P3 全部完成，26 项单元测试通过，GUI 冒烟测试通过（隐藏启动 / 托盘启动 / 优雅退出）。

---

## 一、现状架构总览

```
┌────────────────────────────────────────────────────────────┐
│ Windows 计划任务（登录触发，隐藏）                           │
│   执行: GDUTAutoLogin.exe --monitor                         │
│         └── 后台监控进程（独立进程）                          │
│              ├── run_monitor() 死循环                        │
│              │     perform_check() → 探测/自动登录           │
│              │     更新检查 → Toast 通知                     │
│              │     日志维护 → events.db                      │
│              ├── 写 status.json（状态快照）                   │
│              └── 写 monitor.pid（PID 文件）                  │
└────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────┐
│ GUI 进程（用户双击 / 开始菜单）                               │
│   GDUTApp (tkinter)                                         │
│     ├── 每 2.5s 读 status.json + 校验 PID → 更新界面          │
│     ├── 手动“立即检查/重新连接”→ 自己调 perform_check()        │
│     ├── 设置页可 启动/停止/重启 后台（经计划任务 + taskkill）   │
│     └── 关闭窗口 = destroy（GUI 退出，后台继续跑）             │
└────────────────────────────────────────────────────────────┘
进程间无 RPC，全靠 status.json / monitor.pid / NamedMutex 协调。
```

### 关键现状结论（用户痛点的来源）

1. **双进程**：GUI 与监控是两个进程，靠计划任务拉起 `--monitor` 模式，状态靠 JSON 文件轮询同步。
2. **自启只拉后台**：开机计划任务只启动隐藏监控进程，不启动 GUI。
3. **无托盘**：没有任何托盘图标；关窗即销毁 GUI 进程。
4. **“后台服务”概念暴露给用户**：设置页有 启动/停止/重启后台 按钮，还要 PowerShell 调计划任务 + `taskkill /T /F`，既重又容易让用户困惑。
5. **无单实例保护（GUI 层）**：可以同时开多个 GUI 进程（只有监控进程有 Named Mutex）。

---

## 二、逐文件大纲（当前代码）

### `app.py`（6 行）
- 入口壳：`from gdut_autologin.__main__ import main` → `SystemExit(main())`。PyInstaller 打包目标。

### `gdut_autologin/__main__.py`（~90 行）
- `parse_args()`：`--monitor`、`--first-run`、`--migrate-from`、`--check-once`、`--self-test`、`--no-self-install`、`--apply-update`、`--post-update`、`--target`、`--wait-pid`、`--health-file`。
- `self_test()`：发布自检，输出 JSON。
- `main()` 分发：
  - `--apply-update` → `updates.apply_update`（更新安装器模式）
  - `--migrate-from` → 迁移旧数据
  - `--self-test` → 自检
  - `--monitor` → `service.run_monitor()`（**独立后台进程入口，本次要消灭**）
  - `--check-once` → 单次 `perform_check` 后退出
  - 冻结版且非 `--first-run` → `windows.self_install_if_needed()`（自安装后原进程退出，重新拉起安装后的 exe）
  - 最后 `GDUTApp(first_run=...).mainloop()`

### `gdut_autologin/constants.py`（~65 行）
- 身份：`APP_NAME / APP_ID / APP_VERSION(1.1.3) / TASK_NAME / MUTEX_MONITOR / MUTEX_ACTION`。
- 路径：`DATA_DIR`(%LOCALAPPDATA%/GDUTAutoLogin，可被环境变量覆盖)、`INSTALL_DIR/INSTALLED_EXE`、开始菜单快捷方式、`CONFIG/ACCOUNTS/STATE/STATUS/PID/DATABASE/UPDATE_*`。
- `GITHUB_REPO`、每日更新检查间隔。
- `DEFAULT_CONFIG`：adapter_name/mac、ip_prefixes(10.)、portal(10.0.3.2:801)、检查/重试/冷却间隔、通知、`autostart_enabled: True`、日志大小/保留、自动更新。

### `gdut_autologin/gui.py`（~1478 行，最大文件）
- **样式/控件助手**：配色常量、`text_label/flat_button/modern_entry/check_box/center_on_parent`、`ScrollablePanel`(canvas 滚动)、`SidebarNavItem`。
- **AccountDialog**：添加/编辑账号弹窗（回车确认、显示密码）。
- **FirstRunDialog**：首次设置三步（选网卡 → 账号 → 密码）+ 自启勾选；`finish()` 保存配置、`set_autostart()`、**`start_monitor()`（本次要改）**。
- **GDUTApp(tk.Tk)**：
  - 侧边栏 4 页：概览 / 账号 / 日志 / 设置。
  - 概览：状态点、立即检查、重新连接、统计卡（后台服务/上次账号/最后检查）、最近活动、连接详情。
  - 设置页：网卡选择、**“后台检查”卡（启动/停止/重启后台按钮）**、间隔输入、通知/自启/自动更新勾选、日志保留、更新卡。
  - 设置改动 450ms 防抖后 `apply_settings()` 自动保存；自启变化时调 `set_autostart`（并 start_monitor）。
  - `poll_status()` 每 2.5s 读 `status.json` + `monitor_process_running()` 刷新 UI。
  - `close_window()` = 防抖保存 + `destroy()`（**本次要改为隐藏到托盘**）。
  - 更新 UI：检查/下载（进度）/安装（`launch_update_installer` 后 destroy）。
  - 卸载：`set_autostart(False)` + `stop_monitor()` + `schedule_self_removal()`。

### `gdut_autologin/network.py`（~336 行，纯逻辑，与本次改造基本无关）
- `AdapterInfo`、`list_adapters()`（psutil + PowerShell `Get-NetAdapter/Get-NetConnectionProfile` + `netsh wlan show interfaces`）、`connected_physical_adapters()`、`select_adapter()`（MAC 优先，退回唯一连接）、`adapter_source_ip()`。
- `http_get_bound()`（绑定源 IP 的 HTTP GET）、`probe_network()`（gstatic 204 / msftconnecttest 判断是否在线或被劫持）、`parse_login_success()`、`login_account()`（eportal dr1003 JSONP）、`try_authorized_accounts()`（按上次成功账号优先轮询）。

### `gdut_autologin/service.py`（~197 行）
- `STATUS_TEXT / WAITING_STATES(adapter_missing|adapter_down|no_ip)`。
- `perform_check(login_if_needed, monitor_running)`：`MUTEX_ACTION` 防并发 → 选网卡 → 探测 → 需要时自动登录 → 写 `status.json`。
- `run_monitor()`（**独立监控进程主体，本次要改造为线程**）：`MUTEX_MONITOR` 单实例 → 写 `monitor.pid` → 死循环：检查、失败 Toast（带冷却）、每日更新检查 Toast、每 20 轮日志维护、按状态决定 sleep。

### `gdut_autologin/storage.py`（~390 行，与本次改造基本无关）
- `atomic_write_json/load_json`；config/state/status 读写。
- 账号 CRUD（明文 JSON）、导出/导入（可移植 JSON 格式）、`mask_account/ordered_accounts`。
- `EventDatabase`（SQLite WAL，容量+天数维护，checkpoint/vacuum）、`DatabaseLogHandler`、`build_logger`。
- `migrate_legacy_data()`。

### `gdut_autologin/windows.py`（~296 行，**改造核心之一**）
- `hidden_popen/hidden_run`（CREATE_NO_WINDOW）、`current_launch_command/argv`。
- `set_autostart(enabled)`：注册/注销 **登录触发的隐藏计划任务，当前目标是 `--monitor` 进程**（带 RestartCount=3、电池运行、无时限）。
- `scheduled_task_running()`：PowerShell 查任务状态。
- `monitor_process_running()`：读 `monitor.pid` → psutil 校验 cmdline 含 `--monitor`。
- `start_monitor()`：`Start-ScheduledTask`，失败则 DETACHED 直接拉 `--monitor`；轮询 PID 确认。
- `stop_monitor()`：`Stop-ScheduledTask` + `taskkill /PID /T /F`，删 PID，写 status。
- `restart_monitor()`。
- `show_notification()`：PowerShell WinRT Toast。
- `NamedMutex` / `action_mutex()`（ctypes 互斥量）。
- `create_start_menu_shortcut()`、`self_install_if_needed()`（下载版 exe → 复制到 Programs 目录 → 快捷方式 → 重启 `--first-run --migrate-from`）、`schedule_self_removal()`（卸载清理脚本）。

### `gdut_autologin/updates.py`（~250 行）
- `UpdateInfo`、`check_latest_release()`（GitHub latest + sha256sums 资产匹配）。
- `download_update()`（SHA-256 校验、大小校验、进度回调）。
- `launch_update_installer()`：以 `--apply-update --wait-pid <当前GUI进程PID>` 拉起新版。
- `apply_update()`：**先 `stop_monitor()`** → 等旧 GUI 退出 → 备份/替换/快捷方式 → 拉新 GUI `--post-update` → 健康检查 → **`start_monitor()`**；失败回滚旧版。（本次要移除对 monitor 进程的依赖）

### `tests/test_app_core.py`（~314 行）
- 覆盖：网卡选择/合并、登录请求参数、JSONP 解析；账号存储/顺序/脱敏/导入导出；**FirstRunDialog.finish 断言 `set_autostart` + `start_monitor`**（需随改造更新）；EventDatabase；版本比较/校验和/替换重试；**MonitorControlTests（PID 文件逻辑，随删除而删/改）**；`perform_check` 等待态静默。

### `build.ps1` / `version_info.txt` / `requirements*.txt`
- PyInstaller `--onefile --windowed`（**无 --icon，无托盘图标资源**）；构建前跑 unittest；发布自检 + SHA256SUMS + 清理。
- 依赖仅 `psutil`；构建依赖仅 `pyinstaller`。

### `docs/`（现有）
- `DESIGN.md`：明确描述了“双进程、界面崩溃不影响监控”的旧设计（改造后需重写）。
- `USER_GUIDE.md`、`BUILD.md`。

---

## 三、新方案设计（待确认）

### 目标行为

| 用户动作 | 新行为 |
|---|---|
| 开机登录 | 计划任务拉起 **GUI 进程**（`--hidden`），隐藏到托盘自动工作 |
| 双击 exe（已有实例） | 单实例检测 → 把已运行实例的主窗口拉到前台 |
| 点窗口关闭 × | **隐藏到托盘**（首次给出气泡提示“已最小化到托盘”） |
| 托盘左键/双击 | 显示主窗口 |
| 托盘右键 | 菜单：打开主窗口 / 立即检查 / 开机自启（勾选） / **退出** |
| 托盘“退出” | 停止监控线程 → 移除托盘图标 → 进程优雅退出 |

### 架构变化

```
旧：GUI 进程 + 计划任务(--monitor 后台进程) + status.json/PID 轮询
新：单一 GUI 进程
     ├── Tk 主线程（UI + 事件循环）
     ├── MonitorThread（后台线程，复用 perform_check 逻辑与节奏）
     │     仍写 status.json / events.db（保持 --check-once、数据兼容）
     ├── TrayIcon（ctypes Shell_NotifyIconW，无新第三方依赖）
     └── 计划任务目标改为: GDUTAutoLogin.exe --hidden
```

- `status.json` 保留：同进程内轮询间隔可缩短，且 `--check-once` / 外部诊断仍可用。
- 互斥量保留：`MUTEX_MONITOR` 升级为“应用单实例”锁 + 命名 Event 用于第二实例唤起第一实例。
- 兼容升级：启动时发现旧版 `--monitor` 计划任务 → 自动重注册为 `--hidden`；发现残留 `monitor.pid` → 清理。

### UX 优化清单（并入本次）

1. 关闭=托盘化 + 首次气泡说明（避免“以为退了”或“以为没退”）。
2. 托盘图标悬停提示显示当前状态（如“已联网 · 已启用自动登录”）。
3. 单实例聚焦：重复启动直接弹窗而非静默。
4. 设置页去“后台服务”三按钮 → 一个“自动登录开关”（控制线程启停），文案从“后台服务”改为“自动登录”。
5. 状态刷新提速：同进程后轮询 2.5s → 1s（检查完成即时回调刷新，不等轮询）。
6. 退出时写“后台监控已停止”状态与日志，保证数据一致。
7. exe 增加应用图标（顺手补 `--icon`，托盘同源）。
8. 文档同步：README / DESIGN / USER_GUIDE / CHANGELOG（版本 1.2.0）。

---

## 四、任务清单（确认后按序执行）

### Phase 1：单进程化（核心重构）
- [x] T1 `service.py`：把 `run_monitor()` 死循环抽出为 `MonitorThread(threading.Thread)`：`stop_event`、单轮 `tick()`（检查/通知/维护/自适应 sleep 拆成可测方法）；保留 `perform_check` 不动。
- [x] T2 `gui.py`：`GDUTApp` 启动/停止 `MonitorThread`；`poll_status()` 改读内存 status（仍落盘）；`run_check` 复用同一线程锁；概览“后台服务”统计卡改文案。
- [x] T3 `windows.py`：`set_autostart()` 注册目标改为 `<exe> --hidden`（开发态 pythonw + 脚本）；新增 `ensure_autostart_upgraded()`（旧 `--monitor` 任务自动重注册）；删除 `start_monitor/stop_monitor/restart_monitor/scheduled_task_running/monitor_process_running/_record_monitor_running` 与 PID 逻辑。
- [x] T4 `__main__.py`：`--monitor` 参数改为兼容别名（= `--hidden`）或直接移除；`--hidden` 传递给 `GDUTApp(start_hidden=True)`；移除 PID 相关引用。
- [x] T5 `updates.py`：`apply_update()` 移除 stop/start_monitor，仅等待旧 GUI 进程退出（现有 wait-pid 机制已够）。
- [x] T6 `constants.py`：删 `PID_PATH`/`MUTEX_MONITOR` 改名复用为单实例锁；版本号 1.1.3 → 1.2.0（同步 `version_info.txt`、`build.ps1` 发布文件名）。
- [x] T7 单实例 + 唤起：`windows.py` 增 `acquire_single_instance()`（Mutex）与 `request_show_existing()`（命名 Event）；`gui.py` 起 Watcher 线程等 Event → `deiconify()`。
- [x] T8 测试更新：删/改 `MonitorControlTests`、`FirstRunTests`（改为断言不启动独立进程），新增 `MonitorThread` tick 节奏与 stop 测试、`--hidden` 参数测试。

### Phase 2：系统托盘
- [x] T9 `windows.py`：纯 ctypes `TrayIcon` 类（Shell_NotifyIconW + 隐藏消息窗口独立线程 + WM_TRAYICON 回调 + TrackPopupMenu 右键菜单；左键/双击默认=显示窗口）。无新依赖。
- [x] T10 图标资源：新增 `assets/app.ico`（占位可由脚本生成），`build.ps1` 加 `--icon`；托盘图标：冻结版从 exe 提取（`ExtractIconEx`），开发态从仓库加载。
- [x] T11 `gui.py` 接入：`close_window()` → `withdraw()` + 首次气泡；托盘菜单（打开/立即检查/开机自启勾选/退出）；退出流程（停线程 → RemoveIcon → destroy）；托盘 hover 文案随状态刷新。
- [x] T12 `--hidden` 启动路径：`GDUTApp` 构造前 `withdraw()`（无账号首次设置仍弹窗）；托盘气泡“已隐藏到任务栏，右键图标可退出”。

### Phase 3：UX 与文档收尾
- [x] T13 设置页重做“自动登录”卡：开关（线程启停）+ 间隔；删除启动/停止/重启按钮与“后台服务”文案。
- [x] T14 状态刷新优化：检查完成即时刷新 UI；轮询 2.5s → 1s。
- [x] T15 文档：`DESIGN.md` 重写进程模型、`USER_GUIDE.md` 更新用法（关闭/托盘/退出）、`README.md` 功能列表、`CHANGELOG.md` 1.2.0 条目。
- [x] T16 全量回归：`python -m unittest`、`build.ps1` 构建 + 冻结自检、手工验证清单（开机自启、关窗隐藏、托盘退出、更新升级、卸载清理）。

### 风险与对策
- **托盘 ctypes 细节多**（消息窗口/菜单回收/Explorer 重启重建）：TrayIcon 独立成类 + TaskbarCreated 消息监听重建图标。
- **线程与 Tk 非线程安全**：监控线程只写数据/状态文件，UI 一律经 `after()` 回主线程刷新（沿用现有模式）。
- **老用户升级**：保留 `--monitor` 作为兼容别名一版；启动时自动升级计划任务并清理 `monitor.pid`。
- **更新流程回归点**：`apply_update` 现在等的是 GUI 进程退出，托盘化后必须确保托盘“退出”才退出进程（关窗不再退出），否则新版替换会失败——更新前 UI 引导用户确认退出。

---

## 五、需要你确认的问题

1. 托盘实现：**方案 A 纯 ctypes 零依赖（推荐，包体不变）** vs 方案 B 引入 `pystray + Pillow`（开发快，依赖+2，包体增大）。
2. 设置页是否保留“暂停自动登录”开关（只停登录检查线程，进程仍驻留托盘）？默认：保留。
3. 旧版兼容：`--monitor` 保留一个版本作为 `--hidden` 别名 + 自动升级计划任务，可以吗？默认：可以。
4. 版本号按 **1.2.0** 走，可以吗？
5. 关闭窗口是否需要“记住选择”（下次直接隐藏 or 弹确认）？默认：不弹确认，直接隐藏（首次气泡提示一次）。
