from __future__ import annotations

from datetime import datetime
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .constants import APP_NAME, APP_VERSION, DATABASE_PATH
from .network import AdapterInfo, list_adapters
from .service import perform_check
from .storage import (
    EventDatabase,
    add_or_update_account,
    load_accounts,
    load_config,
    load_state,
    load_status,
    mask_account,
    remove_account,
    save_config,
)
from .windows import (
    schedule_self_removal,
    set_autostart,
    start_monitor,
    stop_monitor,
)


STATUS_COLORS = {
    "online": "#14804A",
    "portal_required": "#B26A00",
    "network_error": "#B42318",
    "unexpected_response": "#B42318",
    "adapter_missing": "#667085",
    "adapter_down": "#667085",
    "no_ip": "#B26A00",
    "login_failed": "#B42318",
    "busy": "#175CD3",
    "unknown": "#667085",
}

MIT_LICENSE_TEXT = """MIT License

Copyright (c) 2026 GDUT Auto Login contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""


def local_time(iso_value: str) -> str:
    if not iso_value:
        return "尚无记录"
    try:
        return datetime.fromisoformat(iso_value).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return iso_value


class AccountDialog(tk.Toplevel):
    def __init__(self, parent, title: str = "添加或更新授权账号"):
        super().__init__(parent)
        self.result: tuple[str, str] | None = None
        self.title(title)
        self.geometry("430x245")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        frame = ttk.Frame(self, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text="只可填写本人拥有或已获明确授权使用的校园网账号。",
            wraplength=380,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 16))
        ttk.Label(frame, text="账号").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Label(frame, text="密码").grid(row=2, column=0, sticky="w", pady=6)
        self.account_var = tk.StringVar()
        self.password_var = tk.StringVar()
        account_entry = ttk.Entry(frame, textvariable=self.account_var, width=34)
        password_entry = ttk.Entry(frame, textvariable=self.password_var, width=34, show="●")
        account_entry.grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=6)
        password_entry.grid(row=2, column=1, sticky="ew", padx=(12, 0), pady=6)
        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, columnspan=2, sticky="e", pady=(20, 0))
        ttk.Button(buttons, text="取消", command=self.destroy).pack(side="left", padx=6)
        ttk.Button(buttons, text="保存", command=self.save).pack(side="left")
        frame.columnconfigure(1, weight=1)
        account_entry.focus_set()
        self.bind("<Return>", lambda _event: self.save())
        self.bind("<Escape>", lambda _event: self.destroy())

    def save(self) -> None:
        account = self.account_var.get().strip()
        password = self.password_var.get()
        if not account or not password:
            messagebox.showwarning("信息不完整", "账号和密码不能为空。", parent=self)
            return
        self.result = (account, password)
        self.password_var.set("")
        self.destroy()


class FirstRunDialog(tk.Toplevel):
    def __init__(self, app: "GDUTApp"):
        super().__init__(app)
        self.app = app
        self.title("首次设置")
        self.geometry("600x470")
        self.resizable(False, False)
        self.transient(app)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        outer = ttk.Frame(self, padding=24)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="欢迎使用 GDUT 校园网自动登录", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="完成一次网卡与账号设置后，程序会自动建立静默开机任务。以后无需手动打开应用。",
            wraplength=540,
        ).pack(anchor="w", pady=(8, 22))

        ttk.Label(outer, text="GDUT 网络接口（支持有线和无线）").pack(anchor="w")
        self.adapter_var = tk.StringVar()
        self.adapter_combo = ttk.Combobox(
            outer, textvariable=self.adapter_var, state="readonly", width=72
        )
        self.adapter_combo.pack(fill="x", pady=(6, 18))
        self.adapters = self.app.refresh_adapter_values(self.adapter_combo)

        form = ttk.Frame(outer)
        form.pack(fill="x")
        ttk.Label(form, text="校园网账号").grid(row=0, column=0, sticky="w", pady=7)
        ttk.Label(form, text="密码").grid(row=1, column=0, sticky="w", pady=7)
        self.account_var = tk.StringVar()
        self.password_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.account_var, width=44).grid(
            row=0, column=1, sticky="ew", padx=(15, 0), pady=7
        )
        ttk.Entry(form, textvariable=self.password_var, show="●", width=44).grid(
            row=1, column=1, sticky="ew", padx=(15, 0), pady=7
        )
        form.columnconfigure(1, weight=1)

        self.autostart_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            outer,
            text="登录 Windows 后自动静默启动并定时检查网络",
            variable=self.autostart_var,
        ).pack(anchor="w", pady=(18, 4))
        ttk.Label(
            outer,
            text="账号密码只会保存到当前 Windows 用户的 DPAPI 加密文件中。",
            foreground="#667085",
        ).pack(anchor="w")

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", side="bottom")
        ttk.Button(buttons, text="稍后设置", command=self.cancel).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="保存并启动", command=self.finish).pack(side="right")

    def finish(self) -> None:
        selection = self.adapter_combo.current()
        account = self.account_var.get().strip()
        password = self.password_var.get()
        if selection < 0 or selection >= len(self.adapters):
            messagebox.showwarning("请选择接口", "请选择名称、网络配置文件或 SSID 包含 GDUT 的网络接口。", parent=self)
            return
        if not account or not password:
            messagebox.showwarning("请输入账号", "校园网账号和密码不能为空。", parent=self)
            return
        adapter = self.adapters[selection]
        keyword = str(load_config().get("network_keyword", "gdut")) or "gdut"
        names = [adapter.name, *adapter.profile_names]
        if not any(keyword.casefold() in value.casefold() for value in names):
            messagebox.showwarning(
                "没有识别到 GDUT 网络",
                "所选接口的网卡名称、网络配置文件或无线 SSID 中没有 GDUT 标识。请先连接 GDUT 网络后刷新。",
                parent=self,
            )
            return
        if not any(ip.startswith("10.") for ip in adapter.ipv4):
            if not messagebox.askyesno(
                "网卡地址需要确认",
                "所选接口当前没有 10.x.x.x 校园网地址。确定它就是已连接 GDUT 网络的接口吗？",
                parent=self,
            ):
                return
        config = load_config()
        config.update(
            {
                "adapter_name": adapter.name,
                "adapter_mac": adapter.mac,
                "autostart_enabled": self.autostart_var.get(),
            }
        )
        try:
            save_config(config)
            add_or_update_account(account, password)
            self.password_var.set("")
            if self.autostart_var.get():
                set_autostart(True)
                start_monitor()
            self.destroy()
            self.app.reload_all()
            self.app.run_check(login=True)
        except Exception as exc:
            messagebox.showerror("设置失败", str(exc), parent=self)

    def cancel(self) -> None:
        self.destroy()


class GDUTApp(tk.Tk):
    def __init__(self, first_run: bool = False):
        super().__init__()
        self.title(f"{APP_NAME}  {APP_VERSION}")
        self.geometry("1040x720")
        self.minsize(920, 620)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.database = EventDatabase()
        self.adapters: list[AdapterInfo] = []
        self._busy = False

        self.configure_style()
        self.build_layout()
        self.reload_all()
        self.after(1500, self.poll_status)
        needs_setup = not load_accounts() or not load_config().get("adapter_mac")
        if needs_setup:
            self.after(300, lambda: FirstRunDialog(self))
        elif first_run:
            self.after(300, self.finish_existing_install)

    def finish_existing_install(self) -> None:
        try:
            config = load_config()
            if config.get("autostart_enabled", True):
                set_autostart(True)
                start_monitor()
            messagebox.showinfo(
                "安装完成",
                "程序已安装到当前用户目录，并已启用静默后台监控。以后可以从开始菜单打开管理界面。",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("安装未完成", str(exc), parent=self)

    def configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Status.TLabel", font=("Microsoft YaHei UI", 24, "bold"))
        style.configure("Heading.TLabel", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Treeview", rowheight=28, font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))
        self.option_add("*Font", ("Microsoft YaHei UI", 9))

    def build_layout(self) -> None:
        header = ttk.Frame(self, padding=(22, 18, 22, 12))
        header.pack(fill="x")
        ttk.Label(header, text=APP_NAME, style="Title.TLabel").pack(side="left")
        ttk.Label(header, text=f"版本 {APP_VERSION}", foreground="#667085").pack(
            side="left", padx=(14, 0), pady=(8, 0)
        )

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        self.overview_tab = ttk.Frame(self.notebook, padding=22)
        self.accounts_tab = ttk.Frame(self.notebook, padding=22)
        self.settings_tab = ttk.Frame(self.notebook, padding=22)
        self.logs_tab = ttk.Frame(self.notebook, padding=18)
        self.about_tab = ttk.Frame(self.notebook, padding=24)
        self.notebook.add(self.overview_tab, text="  概览  ")
        self.notebook.add(self.accounts_tab, text="  账号  ")
        self.notebook.add(self.settings_tab, text="  网络与设置  ")
        self.notebook.add(self.logs_tab, text="  日志  ")
        self.notebook.add(self.about_tab, text="  关于  ")

        self.build_overview()
        self.build_accounts()
        self.build_settings()
        self.build_logs()
        self.build_about()

    def build_overview(self) -> None:
        status_frame = ttk.LabelFrame(self.overview_tab, text="当前网络状态", padding=20)
        status_frame.pack(fill="x")
        self.status_var = tk.StringVar(value="尚未检查")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, style="Status.TLabel")
        self.status_label.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 16))

        self.overview_vars = {
            "adapter": tk.StringVar(value="—"),
            "profile": tk.StringVar(value="—"),
            "ip": tk.StringVar(value="—"),
            "monitor": tk.StringVar(value="—"),
            "check": tk.StringVar(value="—"),
            "account": tk.StringVar(value="—"),
            "error": tk.StringVar(value="—"),
        }
        fields = [
            ("网卡", "adapter", 1, 0),
            ("网络配置文件/SSID", "profile", 1, 2),
            ("校园网 IP", "ip", 2, 0),
            ("后台监控", "monitor", 2, 2),
            ("最后检查", "check", 3, 0),
            ("上次成功账号", "account", 3, 2),
            ("最近问题", "error", 4, 0),
        ]
        for label, key, row, column in fields:
            ttk.Label(status_frame, text=label, foreground="#667085").grid(
                row=row, column=column, sticky="nw", padx=(0, 10), pady=7
            )
            ttk.Label(status_frame, textvariable=self.overview_vars[key], wraplength=330).grid(
                row=row,
                column=column + 1,
                columnspan=3 if key == "error" else 1,
                sticky="nw",
                padx=(0, 26),
                pady=7,
            )
        status_frame.columnconfigure(1, weight=1)
        status_frame.columnconfigure(3, weight=1)

        actions = ttk.Frame(self.overview_tab)
        actions.pack(fill="x", pady=18)
        self.check_button = ttk.Button(actions, text="立即检查", command=lambda: self.run_check(False))
        self.check_button.pack(side="left", padx=(0, 10))
        self.login_button = ttk.Button(actions, text="检查并重新登录", command=lambda: self.run_check(True))
        self.login_button.pack(side="left", padx=(0, 10))
        ttk.Button(actions, text="启动后台监控", command=self.start_background).pack(
            side="left", padx=(0, 10)
        )
        ttk.Button(actions, text="停止后台监控", command=self.stop_background).pack(side="left")

        tips = ttk.LabelFrame(self.overview_tab, text="说明", padding=16)
        tips.pack(fill="x")
        ttk.Label(
            tips,
            text=(
                "关闭本窗口不会停止后台网络监控。正常运行时不会弹出命令行窗口；"
                "只有自动恢复失败时才会按设置发送 Windows 通知。"
            ),
            wraplength=900,
        ).pack(anchor="w")

    def build_accounts(self) -> None:
        top = ttk.Frame(self.accounts_tab)
        top.pack(fill="x", pady=(0, 12))
        ttk.Label(top, text="已授权账号", style="Heading.TLabel").pack(side="left")
        ttk.Button(top, text="添加或更新", command=self.add_account).pack(side="right")
        ttk.Button(top, text="删除选中", command=self.delete_account).pack(side="right", padx=8)

        self.account_tree = ttk.Treeview(
            self.accounts_tab, columns=("index", "account", "preferred"), show="headings"
        )
        self.account_tree.heading("index", text="顺序")
        self.account_tree.heading("account", text="脱敏账号")
        self.account_tree.heading("preferred", text="状态")
        self.account_tree.column("index", width=90, anchor="center")
        self.account_tree.column("account", width=280, anchor="center")
        self.account_tree.column("preferred", width=220, anchor="center")
        self.account_tree.pack(fill="both", expand=True)
        ttk.Label(
            self.accounts_tab,
            text="密码通过 Windows DPAPI 加密，界面和日志均不会显示明文密码。",
            foreground="#667085",
        ).pack(anchor="w", pady=(12, 0))

    def build_settings(self) -> None:
        network_frame = ttk.LabelFrame(self.settings_tab, text="GDUT 网络接口（有线/无线）", padding=16)
        network_frame.pack(fill="x")
        self.adapter_var = tk.StringVar()
        self.adapter_combo = ttk.Combobox(
            network_frame, textvariable=self.adapter_var, state="readonly", width=92
        )
        self.adapter_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(network_frame, text="刷新网卡", command=self.refresh_settings_adapters).pack(
            side="left", padx=(10, 0)
        )
        keyword_frame = ttk.Frame(self.settings_tab)
        keyword_frame.pack(fill="x", pady=(10, 0))
        ttk.Label(keyword_frame, text="GDUT 网络标识（不区分大小写）").pack(side="left")
        self.network_keyword_var = tk.StringVar(value="gdut")
        ttk.Entry(keyword_frame, textvariable=self.network_keyword_var, width=18).pack(
            side="left", padx=(12, 0)
        )
        ttk.Label(
            keyword_frame,
            text="仅匹配网卡别名、网络配置文件或无线 SSID 中包含该文字的接口。",
            foreground="#667085",
        ).pack(side="left", padx=(12, 0))

        monitor_frame = ttk.LabelFrame(self.settings_tab, text="监测与提醒", padding=16)
        monitor_frame.pack(fill="x", pady=14)
        self.check_interval_var = tk.IntVar(value=30)
        self.retry_interval_var = tk.IntVar(value=15)
        self.login_cooldown_var = tk.IntVar(value=60)
        self.notifications_var = tk.BooleanVar(value=True)
        settings = [
            ("网络正常检查间隔（秒）", self.check_interval_var, 0),
            ("网卡异常重试间隔（秒）", self.retry_interval_var, 1),
            ("登录失败冷却时间（秒）", self.login_cooldown_var, 2),
        ]
        for label, variable, row in settings:
            ttk.Label(monitor_frame, text=label).grid(row=row, column=0, sticky="w", pady=6)
            ttk.Spinbox(monitor_frame, from_=5, to=3600, textvariable=variable, width=12).grid(
                row=row, column=1, sticky="w", padx=(18, 0), pady=6
            )
        ttk.Checkbutton(
            monitor_frame, text="自动登录全部失败时发送 Windows 通知", variable=self.notifications_var
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))

        log_frame = ttk.LabelFrame(self.settings_tab, text="日志保留策略", padding=16)
        log_frame.pack(fill="x")
        self.log_size_var = tk.StringVar(value="20 MB")
        self.log_retention_var = tk.StringVar(value="全部")
        ttk.Label(log_frame, text="日志数据库容量上限").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Combobox(
            log_frame,
            textvariable=self.log_size_var,
            values=("1 MB", "5 MB", "10 MB", "20 MB", "50 MB", "100 MB"),
            state="readonly",
            width=14,
        ).grid(row=0, column=1, sticky="w", padx=(18, 35), pady=6)
        ttk.Label(log_frame, text="日志保留时间").grid(row=0, column=2, sticky="w", pady=6)
        ttk.Combobox(
            log_frame,
            textvariable=self.log_retention_var,
            values=("全部", "7 天", "30 天", "90 天", "180 天"),
            state="readonly",
            width=14,
        ).grid(row=0, column=3, sticky="w", padx=(18, 0), pady=6)
        ttk.Label(
            log_frame,
            text="“全部”表示不按日期删除，但仍受容量上限保护；超出容量时会从最旧记录开始清理。",
            foreground="#667085",
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))

        startup_frame = ttk.Frame(self.settings_tab)
        startup_frame.pack(fill="x", pady=(16, 0))
        self.autostart_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            startup_frame,
            text="登录 Windows 后自动静默启动",
            variable=self.autostart_var,
        ).pack(side="left")
        ttk.Button(startup_frame, text="保存设置", command=self.save_settings).pack(side="right")

    def build_logs(self) -> None:
        filters = ttk.Frame(self.logs_tab)
        filters.pack(fill="x", pady=(0, 10))
        self.log_days_var = tk.StringVar(value="全部")
        self.log_level_var = tk.StringVar(value="全部")
        ttk.Label(filters, text="时间范围").pack(side="left")
        ttk.Combobox(
            filters,
            textvariable=self.log_days_var,
            values=("全部", "今天", "7 天", "30 天", "90 天"),
            state="readonly",
            width=10,
        ).pack(side="left", padx=(6, 16))
        ttk.Label(filters, text="级别").pack(side="left")
        ttk.Combobox(
            filters,
            textvariable=self.log_level_var,
            values=("全部", "INFO", "WARNING", "ERROR", "CRITICAL"),
            state="readonly",
            width=12,
        ).pack(side="left", padx=(6, 16))
        ttk.Button(filters, text="刷新", command=self.refresh_logs).pack(side="left")
        ttk.Button(filters, text="导出 CSV", command=self.export_logs).pack(side="right")
        ttk.Button(filters, text="清空日志", command=self.clear_logs).pack(side="right", padx=8)

        columns = ("time", "level", "message")
        self.log_tree = ttk.Treeview(self.logs_tab, columns=columns, show="headings")
        self.log_tree.heading("time", text="时间")
        self.log_tree.heading("level", text="级别")
        self.log_tree.heading("message", text="内容")
        self.log_tree.column("time", width=165, anchor="center")
        self.log_tree.column("level", width=95, anchor="center")
        self.log_tree.column("message", width=680, anchor="w")
        scrollbar = ttk.Scrollbar(self.logs_tab, orient="vertical", command=self.log_tree.yview)
        self.log_tree.configure(yscrollcommand=scrollbar.set)
        self.log_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.log_tree.tag_configure("WARNING", foreground="#B26A00")
        self.log_tree.tag_configure("ERROR", foreground="#B42318")
        self.log_tree.tag_configure("CRITICAL", foreground="#B42318")

    def build_about(self) -> None:
        ttk.Label(self.about_tab, text=APP_NAME, style="Title.TLabel").pack(anchor="w")
        ttk.Label(self.about_tab, text=f"版本 {APP_VERSION}", foreground="#667085").pack(
            anchor="w", pady=(4, 18)
        )
        text = (
            "本程序用于监测名称或网络配置文件包含 GDUT 的有线/无线接口，并在校园网认证失效时自动恢复。\n\n"
            "账号和密码使用 Windows DPAPI 加密，只能由当前电脑上的当前 Windows 用户解密。"
            "请仅配置本人拥有或已获明确授权使用的账号，并遵守学校网络管理规定。\n\n"
            "开源许可证：MIT License。软件按“原样”提供，不附带任何明示或暗示担保。"
        )
        ttk.Label(self.about_tab, text=text, wraplength=850, justify="left").pack(anchor="w")
        ttk.Button(self.about_tab, text="查看完整 MIT License", command=self.show_license).pack(
            anchor="w", pady=(14, 0)
        )
        ttk.Separator(self.about_tab).pack(fill="x", pady=24)
        ttk.Label(self.about_tab, text="程序数据目录", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(self.about_tab, text=str(DATABASE_PATH.parent), foreground="#667085").pack(
            anchor="w", pady=(5, 18)
        )
        ttk.Button(self.about_tab, text="卸载程序", command=self.uninstall_app).pack(anchor="w")

    def show_license(self) -> None:
        window = tk.Toplevel(self)
        window.title("MIT License")
        window.geometry("760x520")
        window.transient(self)
        frame = ttk.Frame(window, padding=14)
        frame.pack(fill="both", expand=True)
        text = tk.Text(frame, wrap="word", padx=12, pady=12, font=("Consolas", 9))
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.insert("1.0", MIT_LICENSE_TEXT)
        text.configure(state="disabled")
        text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def refresh_adapter_values(self, combo: ttk.Combobox) -> list[AdapterInfo]:
        adapters = list_adapters()
        values = [
            f"{item.name}  |  网络: {', '.join(item.profile_names) or '未识别'}  |  "
            f"{item.mac or '无 MAC'}  |  {', '.join(item.ipv4) or '无 IPv4'}  |  {item.status}"
            for item in adapters
        ]
        combo["values"] = values
        if values:
            config = load_config()
            keyword = str(config.get("network_keyword", "gdut")).casefold()
            configured_mac = str(config.get("adapter_mac", "")).replace("-", "").replace(":", "").upper()
            selected = 0
            for index, item in enumerate(adapters):
                normalized = item.mac.replace("-", "").replace(":", "").upper()
                if configured_mac and normalized == configured_mac:
                    selected = index
                    break
                names = [item.name, *item.profile_names]
                if not configured_mac and any(keyword in value.casefold() for value in names):
                    selected = index
                    break
            combo.current(selected)
        return adapters

    def refresh_settings_adapters(self) -> None:
        self.adapters = self.refresh_adapter_values(self.adapter_combo)

    def reload_all(self) -> None:
        self.refresh_accounts()
        self.load_settings()
        self.refresh_logs()
        self.update_status_display(load_status())

    def refresh_accounts(self) -> None:
        for item in self.account_tree.get_children():
            self.account_tree.delete(item)
        state = load_state()
        preferred = state.get("last_success_account")
        for index, item in enumerate(load_accounts(), start=1):
            self.account_tree.insert(
                "",
                "end",
                iid=item["account"],
                values=(index, mask_account(item["account"]), "上次成功" if item["account"] == preferred else ""),
            )

    def add_account(self) -> None:
        dialog = AccountDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            account, password = dialog.result
            try:
                added = add_or_update_account(account, password)
                self.refresh_accounts()
                messagebox.showinfo("保存成功", "账号已加密添加。" if added else "账号密码已更新。")
            except Exception as exc:
                messagebox.showerror("保存失败", str(exc))

    def delete_account(self) -> None:
        selection = self.account_tree.selection()
        if not selection:
            messagebox.showwarning("未选择账号", "请先选择要删除的账号。")
            return
        account = selection[0]
        if not messagebox.askyesno("确认删除", f"确定删除账号 {mask_account(account)} 吗？"):
            return
        remove_account(account)
        self.refresh_accounts()

    def load_settings(self) -> None:
        config = load_config()
        self.check_interval_var.set(int(config.get("check_interval_seconds", 30)))
        self.retry_interval_var.set(int(config.get("retry_interval_seconds", 15)))
        self.login_cooldown_var.set(int(config.get("login_cooldown_seconds", 60)))
        self.notifications_var.set(bool(config.get("notifications_enabled", True)))
        self.network_keyword_var.set(str(config.get("network_keyword", "gdut")))
        self.autostart_var.set(bool(config.get("autostart_enabled", True)))
        self.log_size_var.set(f"{int(config.get('log_max_mb', 20))} MB")
        retention = int(config.get("log_retention_days", 0))
        self.log_retention_var.set("全部" if retention == 0 else f"{retention} 天")
        self.refresh_settings_adapters()

    def save_settings(self) -> None:
        if self.adapter_combo.current() < 0 or self.adapter_combo.current() >= len(self.adapters):
            messagebox.showwarning("请选择接口", "请选择名称、网络配置文件或 SSID 包含 GDUT 的网络接口。")
            return
        try:
            adapter = self.adapters[self.adapter_combo.current()]
            config = load_config()
            keyword = self.network_keyword_var.get().strip() or "gdut"
            names = [adapter.name, *adapter.profile_names]
            if not any(keyword.casefold() in value.casefold() for value in names):
                messagebox.showwarning(
                    "网卡标识不匹配",
                    f"所选接口的网卡名称、网络配置文件和 SSID 中都不包含“{keyword}”，为避免使用错误网卡，设置未保存。",
                )
                return
            config.update(
                {
                    "adapter_name": adapter.name,
                    "adapter_mac": adapter.mac,
                    "network_keyword": keyword,
                    "check_interval_seconds": max(5, int(self.check_interval_var.get())),
                    "retry_interval_seconds": max(5, int(self.retry_interval_var.get())),
                    "login_cooldown_seconds": max(15, int(self.login_cooldown_var.get())),
                    "notifications_enabled": self.notifications_var.get(),
                    "autostart_enabled": self.autostart_var.get(),
                    "log_max_mb": int(self.log_size_var.get().split()[0]),
                    "log_retention_days": 0
                    if self.log_retention_var.get() == "全部"
                    else int(self.log_retention_var.get().split()[0]),
                }
            )
            save_config(config)
            set_autostart(self.autostart_var.get())
            if self.autostart_var.get():
                start_monitor()
            self.database.maintain(config["log_max_mb"], config["log_retention_days"])
            messagebox.showinfo("保存成功", "设置已经保存并立即生效。")
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))

    def selected_log_filters(self) -> tuple[int, str]:
        days_text = self.log_days_var.get()
        days = 0 if days_text == "全部" else (1 if days_text == "今天" else int(days_text.split()[0]))
        level = "" if self.log_level_var.get() == "全部" else self.log_level_var.get()
        return days, level

    def refresh_logs(self) -> None:
        if not hasattr(self, "log_tree"):
            return
        for item in self.log_tree.get_children():
            self.log_tree.delete(item)
        days, level = self.selected_log_filters()
        for event_id, timestamp, row_level, message in self.database.query(days, level):
            self.log_tree.insert(
                "",
                "end",
                iid=str(event_id),
                values=(local_time(timestamp), row_level, message),
                tags=(row_level,),
            )

    def export_logs(self) -> None:
        destination = filedialog.asksaveasfilename(
            title="导出日志",
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")],
            initialfile=f"GDUT日志-{datetime.now():%Y%m%d-%H%M%S}.csv",
        )
        if not destination:
            return
        days, level = self.selected_log_filters()
        count = self.database.export_csv(Path(destination), days, level)
        messagebox.showinfo("导出完成", f"已导出 {count} 条日志。")

    def clear_logs(self) -> None:
        if messagebox.askyesno("确认清空", "确定清空全部运行日志吗？此操作无法恢复。"):
            self.database.clear()
            self.refresh_logs()

    def run_check(self, login: bool) -> None:
        if self._busy:
            return
        self._busy = True
        self.check_button.configure(state="disabled")
        self.login_button.configure(state="disabled")
        self.status_var.set("正在检查……")

        def worker():
            try:
                result = perform_check(login_if_needed=login, monitor_running=True)
                self.after(0, lambda: self.check_finished(result, None))
            except Exception as exc:
                self.after(0, lambda: self.check_finished({}, exc))

        threading.Thread(target=worker, daemon=True).start()

    def check_finished(self, status: dict, error: Exception | None) -> None:
        self._busy = False
        self.check_button.configure(state="normal")
        self.login_button.configure(state="normal")
        if error:
            messagebox.showerror("检查失败", str(error))
        else:
            self.update_status_display(status)
            self.refresh_accounts()
            self.refresh_logs()

    def start_background(self) -> None:
        try:
            start_monitor()
            messagebox.showinfo("后台监控", "后台监控已经启动。")
            self.after(1000, self.poll_status)
        except Exception as exc:
            messagebox.showerror("启动失败", str(exc))

    def stop_background(self) -> None:
        if not messagebox.askyesno("停止后台监控", "确定暂时停止后台网络监控吗？"):
            return
        stop_monitor()
        self.after(800, self.poll_status)

    def poll_status(self) -> None:
        try:
            self.update_status_display(load_status())
        finally:
            self.after(2000, self.poll_status)

    def update_status_display(self, status: dict) -> None:
        state = status.get("state", "unknown")
        self.status_var.set(status.get("state_text") or "尚未检查")
        self.status_label.configure(foreground=STATUS_COLORS.get(state, "#667085"))
        self.overview_vars["adapter"].set(status.get("adapter_name") or "—")
        self.overview_vars["profile"].set(status.get("network_profile") or "—")
        self.overview_vars["ip"].set(status.get("source_ip") or "—")
        self.overview_vars["monitor"].set("正在运行" if status.get("monitor_running") else "未运行")
        self.overview_vars["check"].set(local_time(status.get("last_check_at", "")))
        self.overview_vars["account"].set(status.get("last_success_account") or "—")
        self.overview_vars["error"].set(status.get("last_error") or "—")

    def uninstall_app(self) -> None:
        if not messagebox.askyesno("卸载程序", "确定删除开机任务并卸载程序吗？"):
            return
        remove_data = messagebox.askyesno(
            "删除个人数据",
            "是否同时删除加密账号、设置和日志？\n\n选择“否”可在以后重新安装时继续使用。",
        )
        try:
            set_autostart(False)
            stop_monitor()
            schedule_self_removal(remove_data)
            messagebox.showinfo("正在卸载", "程序将在关闭后完成卸载。")
            self.destroy()
        except Exception as exc:
            messagebox.showerror("卸载失败", str(exc))
