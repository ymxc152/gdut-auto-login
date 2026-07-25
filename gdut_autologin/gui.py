from __future__ import annotations

from datetime import datetime
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

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
from .updates import (
    UpdateInfo,
    check_latest_release,
    download_update,
    launch_update_installer,
    load_update_status,
)
from .windows import schedule_self_removal, set_autostart, start_monitor, stop_monitor


BG = "#F4F7FB"
SIDEBAR = "#101828"
SIDEBAR_ACTIVE = "#1D2939"
CARD = "#FFFFFF"
TEXT = "#101828"
MUTED = "#667085"
PRIMARY = "#2563EB"
SUCCESS = "#12B76A"
WARNING = "#F79009"
DANGER = "#F04438"
BORDER = "#E4E7EC"

STATUS_COLORS = {
    "online": SUCCESS, "portal_required": WARNING, "network_error": DANGER,
    "unexpected_response": DANGER, "adapter_missing": MUTED, "adapter_down": MUTED,
    "no_ip": WARNING, "login_failed": DANGER, "busy": PRIMARY, "unknown": MUTED,
}


def local_time(value: str) -> str:
    if not value:
        return "尚无记录"
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value


def label(parent, text="", size=10, weight="normal", color=TEXT, **kwargs):
    return tk.Label(parent, text=text, font=("Microsoft YaHei UI", size, weight), fg=color,
                    bg=parent.cget("bg"), **kwargs)


class AccountDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.result = None
        self.title("添加或更新账号")
        self.geometry("450x285")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.configure(bg=CARD)
        body = tk.Frame(self, bg=CARD, padx=28, pady=24)
        body.pack(fill="both", expand=True)
        label(body, "添加授权账号", 17, "bold").pack(anchor="w")
        label(body, "信息仅保存在当前 Windows 用户的 DPAPI 加密文件中。", 9, color=MUTED,
              wraplength=390, justify="left").pack(anchor="w", pady=(5, 18))
        self.account = tk.StringVar()
        self.password = tk.StringVar()
        ttk.Entry(body, textvariable=self.account, font=("Microsoft YaHei UI", 10)).pack(fill="x", ipady=6)
        ttk.Entry(body, textvariable=self.password, show="●", font=("Microsoft YaHei UI", 10)).pack(fill="x", ipady=6, pady=10)
        row = tk.Frame(body, bg=CARD)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="保存", style="Primary.TButton", command=self.save).pack(side="right")
        ttk.Button(row, text="取消", command=self.destroy).pack(side="right", padx=8)
        self.bind("<Return>", lambda _e: self.save())
        self.bind("<Escape>", lambda _e: self.destroy())

    def save(self):
        account, password = self.account.get().strip(), self.password.get()
        if not account or not password:
            messagebox.showwarning("信息不完整", "账号和密码不能为空。", parent=self)
            return
        self.result = (account, password)
        self.password.set("")
        self.destroy()


class FirstRunDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("首次设置")
        self.geometry("620x510")
        self.resizable(False, False)
        self.transient(app)
        self.grab_set()
        self.configure(bg=CARD)
        body = tk.Frame(self, bg=CARD, padx=34, pady=30)
        body.pack(fill="both", expand=True)
        label(body, "欢迎使用 GDUT 自动登录", 20, "bold").pack(anchor="w")
        label(body, "选择已连接 GDUT 的有线或无线接口，保存后将静默监测网络。", color=MUTED).pack(anchor="w", pady=(6, 22))
        label(body, "GDUT 网络接口", 9, "bold").pack(anchor="w")
        self.adapter = ttk.Combobox(body, state="readonly")
        self.adapter.pack(fill="x", ipady=5, pady=(6, 16))
        self.adapters = app.fill_adapters(self.adapter)
        self.account, self.password = tk.StringVar(), tk.StringVar()
        label(body, "校园网账号", 9, "bold").pack(anchor="w")
        ttk.Entry(body, textvariable=self.account).pack(fill="x", ipady=5, pady=(5, 12))
        label(body, "密码", 9, "bold").pack(anchor="w")
        ttk.Entry(body, textvariable=self.password, show="●").pack(fill="x", ipady=5, pady=(5, 14))
        self.autostart = tk.BooleanVar(value=True)
        ttk.Checkbutton(body, text="登录 Windows 后自动静默启动", variable=self.autostart).pack(anchor="w")
        row = tk.Frame(body, bg=CARD)
        row.pack(fill="x", side="bottom")
        ttk.Button(row, text="保存并启动", style="Primary.TButton", command=self.finish).pack(side="right")
        ttk.Button(row, text="稍后设置", command=self.destroy).pack(side="right", padx=8)

    def finish(self):
        index = self.adapter.current()
        if index < 0 or not self.account.get().strip() or not self.password.get():
            messagebox.showwarning("设置未完成", "请选择 GDUT 接口并填写账号密码。", parent=self)
            return
        adapter = self.adapters[index]
        if not any("gdut" in value.casefold() for value in [adapter.name, *adapter.profile_names]):
            messagebox.showwarning("接口不匹配", "所选接口名称、网络配置文件或 SSID 中没有 GDUT。", parent=self)
            return
        config = load_config()
        config.update({"adapter_name": adapter.name, "adapter_mac": adapter.mac,
                       "autostart_enabled": self.autostart.get()})
        try:
            save_config(config)
            add_or_update_account(self.account.get().strip(), self.password.get())
            if self.autostart.get():
                set_autostart(True)
                start_monitor()
            self.destroy()
            self.app.reload_all()
            self.app.run_check(True)
        except Exception as exc:
            messagebox.showerror("设置失败", str(exc), parent=self)


class GDUTApp(tk.Tk):
    NAV = [("overview", "概览", "⌂"), ("connection", "连接", "◉"), ("accounts", "账号", "♙"),
           ("logs", "日志", "≡"), ("updates", "更新", "↻"), ("settings", "设置", "⚙")]

    def __init__(self, first_run=False):
        super().__init__()
        self.title(f"{APP_NAME}  {APP_VERSION}")
        self.geometry("1180x760")
        self.minsize(1000, 680)
        self.configure(bg=BG)
        self.database = EventDatabase()
        self.adapters: list[AdapterInfo] = []
        self._busy = False
        self._update_info: UpdateInfo | None = None
        self.pages, self.nav_buttons = {}, {}
        self._configure_style()
        self._build_shell()
        self.show_page("overview")
        self.reload_all()
        self.after(1200, self.poll_status)
        if not load_accounts() or not load_config().get("adapter_mac"):
            self.after(300, lambda: FirstRunDialog(self))
        elif first_run:
            self.after(300, self.finish_install)

    def _configure_style(self):
        style = ttk.Style(self)
        try: style.theme_use("clam")
        except tk.TclError: pass
        self.option_add("*Font", ("Microsoft YaHei UI", 9))
        style.configure("TButton", padding=(14, 8), borderwidth=0)
        style.configure("Primary.TButton", foreground="white", background=PRIMARY)
        style.map("Primary.TButton", background=[("active", "#1D4ED8"), ("disabled", "#98A2B3")])
        style.configure("Treeview", rowheight=34, borderwidth=0, fieldbackground=CARD, background=CARD)
        style.configure("Treeview.Heading", padding=8, font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("TEntry", padding=5)

    def _build_shell(self):
        sidebar = tk.Frame(self, bg=SIDEBAR, width=220)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar, bg=SIDEBAR, padx=22, pady=24)
        brand.pack(fill="x")
        label(brand, "GDUT", 19, "bold", "white").pack(anchor="w")
        label(brand, "校园网连接助手", 9, color="#98A2B3").pack(anchor="w")
        nav = tk.Frame(sidebar, bg=SIDEBAR, padx=10)
        nav.pack(fill="x", pady=8)
        for key, title, icon in self.NAV:
            button = tk.Button(nav, text=f"  {icon}    {title}", anchor="w", bg=SIDEBAR, fg="#D0D5DD",
                               activebackground=SIDEBAR_ACTIVE, activeforeground="white", relief="flat",
                               borderwidth=0, padx=14, pady=12, font=("Microsoft YaHei UI", 10),
                               command=lambda k=key: self.show_page(k))
            button.pack(fill="x", pady=2)
            self.nav_buttons[key] = button
        footer = tk.Frame(sidebar, bg=SIDEBAR, padx=22, pady=22)
        footer.pack(side="bottom", fill="x")
        self.sidebar_status = label(footer, "●  正在读取状态", 9, color="#98A2B3")
        self.sidebar_status.pack(anchor="w")
        label(footer, f"v{APP_VERSION}", 8, color="#667085").pack(anchor="w", pady=(6, 0))
        self.content = tk.Frame(self, bg=BG)
        self.content.pack(side="left", fill="both", expand=True)
        for key, *_ in self.NAV:
            page = tk.Frame(self.content, bg=BG, padx=30, pady=26)
            self.pages[key] = page
        self._build_overview(); self._build_connection(); self._build_accounts()
        self._build_logs(); self._build_updates(); self._build_settings()

    def show_page(self, key):
        for page in self.pages.values(): page.pack_forget()
        self.pages[key].pack(fill="both", expand=True)
        for name, button in self.nav_buttons.items():
            button.configure(bg=SIDEBAR_ACTIVE if name == key else SIDEBAR,
                             fg="white" if name == key else "#D0D5DD")
        if key == "logs": self.refresh_logs()
        if key == "updates": self.render_update_status(load_update_status())

    def page_header(self, page, title, subtitle):
        label(page, title, 22, "bold").pack(anchor="w")
        label(page, subtitle, 9, color=MUTED).pack(anchor="w", pady=(4, 20))

    def card(self, parent, padx=20, pady=18):
        frame = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1, padx=padx, pady=pady)
        return frame

    def _build_overview(self):
        page = self.pages["overview"]
        self.page_header(page, "网络概览", "GDUT 接口状态、认证与后台服务一目了然")
        hero = self.card(page, 26, 24); hero.pack(fill="x")
        top = tk.Frame(hero, bg=CARD); top.pack(fill="x")
        self.status_dot = label(top, "●", 24, color=MUTED); self.status_dot.pack(side="left", padx=(0, 12))
        status_text = tk.Frame(top, bg=CARD); status_text.pack(side="left")
        self.status_var = tk.StringVar(value="尚未检查")
        tk.Label(status_text, textvariable=self.status_var, font=("Microsoft YaHei UI", 20, "bold"), fg=TEXT, bg=CARD).pack(anchor="w")
        self.status_hint = label(status_text, "等待首次网络检测", 9, color=MUTED); self.status_hint.pack(anchor="w", pady=(3, 0))
        actions = tk.Frame(top, bg=CARD); actions.pack(side="right")
        self.check_button = ttk.Button(actions, text="立即检查", command=lambda: self.run_check(False)); self.check_button.pack(side="left", padx=6)
        self.login_button = ttk.Button(actions, text="检查并恢复", style="Primary.TButton", command=lambda: self.run_check(True)); self.login_button.pack(side="left")
        stats = tk.Frame(page, bg=BG); stats.pack(fill="x", pady=16)
        self.stat_vars = {k: tk.StringVar(value="—") for k in ("monitor", "account", "check")}
        for index, (title, key) in enumerate((("后台服务", "monitor"), ("上次成功账号", "account"), ("最后检查", "check"))):
            box = self.card(stats, 18, 15); box.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 8, 0))
            label(box, title, 9, color=MUTED).pack(anchor="w")
            tk.Label(box, textvariable=self.stat_vars[key], font=("Microsoft YaHei UI", 12, "bold"), fg=TEXT, bg=CARD).pack(anchor="w", pady=(7, 0))
            stats.columnconfigure(index, weight=1)
        recent = self.card(page); recent.pack(fill="both", expand=True)
        label(recent, "最近活动", 12, "bold").pack(anchor="w", pady=(0, 10))
        self.recent_list = tk.Frame(recent, bg=CARD); self.recent_list.pack(fill="both", expand=True)

    def _build_connection(self):
        page = self.pages["connection"]
        self.page_header(page, "连接详情", "所有探测与登录请求都绑定到这个 GDUT 接口的源 IP")
        box = self.card(page, 24, 22); box.pack(fill="x")
        self.connection_vars = {k: tk.StringVar(value="—") for k in ("adapter", "profile", "ip", "mac", "error")}
        for row, (title, key) in enumerate((("接口", "adapter"), ("网络配置文件 / SSID", "profile"), ("绑定源 IP", "ip"), ("MAC 地址", "mac"), ("最近问题", "error"))):
            label(box, title, 9, color=MUTED).grid(row=row, column=0, sticky="nw", pady=10, padx=(0, 35))
            tk.Label(box, textvariable=self.connection_vars[key], font=("Microsoft YaHei UI", 10, "bold" if key == "ip" else "normal"), fg=TEXT, bg=CARD, wraplength=650, justify="left").grid(row=row, column=1, sticky="nw", pady=10)
        label(page, "安全边界", 12, "bold").pack(anchor="w", pady=(22, 8))
        note = self.card(page)
        note.pack(fill="x")
        label(note, "只有接口名称、网络配置文件或无线 SSID 包含“gdut”（不区分大小写），且取得校园网 IP 时才会执行检测和认证。未匹配时程序停止操作，不会借用其他网卡。", 9, color=MUTED, wraplength=820, justify="left").pack(anchor="w")

    def _build_accounts(self):
        page = self.pages["accounts"]
        self.page_header(page, "账号管理", "账号密码独立加密保存；列表顺序用于授权账号的故障切换")
        toolbar = tk.Frame(page, bg=BG); toolbar.pack(fill="x", pady=(0, 10))
        ttk.Button(toolbar, text="添加或更新", style="Primary.TButton", command=self.add_account).pack(side="right")
        ttk.Button(toolbar, text="删除选中", command=self.delete_account).pack(side="right", padx=8)
        box = self.card(page, 1, 1); box.pack(fill="both", expand=True)
        self.account_tree = ttk.Treeview(box, columns=("order", "account", "status"), show="headings")
        for key, title, width in (("order", "顺序", 90), ("account", "脱敏账号", 300), ("status", "状态", 220)):
            self.account_tree.heading(key, text=title); self.account_tree.column(key, width=width, anchor="center")
        self.account_tree.pack(fill="both", expand=True)
        label(page, "密码不会显示在界面、日志或导出文件中。请仅使用本人或已明确授权的校园网账号。", 9, color=MUTED).pack(anchor="w", pady=(10, 0))

    def _build_logs(self):
        page = self.pages["logs"]
        self.page_header(page, "运行日志", "搜索、筛选并导出网络检测和认证记录")
        bar = tk.Frame(page, bg=BG); bar.pack(fill="x", pady=(0, 10))
        self.log_search = tk.StringVar(); self.log_level = tk.StringVar(value="全部"); self.log_days = tk.StringVar(value="全部")
        entry = ttk.Entry(bar, textvariable=self.log_search, width=30); entry.pack(side="left", ipady=3)
        entry.bind("<KeyRelease>", lambda _e: self.refresh_logs())
        ttk.Combobox(bar, textvariable=self.log_level, values=("全部", "INFO", "WARNING", "ERROR", "CRITICAL"), state="readonly", width=12).pack(side="left", padx=8)
        ttk.Combobox(bar, textvariable=self.log_days, values=("全部", "今天", "7 天", "30 天", "90 天"), state="readonly", width=10).pack(side="left")
        ttk.Button(bar, text="刷新", command=self.refresh_logs).pack(side="left", padx=8)
        ttk.Button(bar, text="导出 CSV", command=self.export_logs).pack(side="right")
        box = self.card(page, 1, 1); box.pack(fill="both", expand=True)
        self.log_tree = ttk.Treeview(box, columns=("time", "level", "message"), show="headings")
        for key, title, width in (("time", "时间", 165), ("level", "级别", 90), ("message", "消息", 580)):
            self.log_tree.heading(key, text=title); self.log_tree.column(key, width=width, anchor="w")
        self.log_tree.pack(fill="both", expand=True)

    def _build_updates(self):
        page = self.pages["updates"]
        self.page_header(page, "更新中心", "通过 GitHub Release 获取新版，并使用 SHA-256 验证完整性")
        box = self.card(page, 24, 22); box.pack(fill="x")
        row = tk.Frame(box, bg=CARD); row.pack(fill="x")
        self.update_title = label(row, f"当前版本 {APP_VERSION}", 17, "bold"); self.update_title.pack(side="left")
        self.update_button = ttk.Button(row, text="检查更新", style="Primary.TButton", command=self.check_updates); self.update_button.pack(side="right")
        self.update_message = label(box, "尚未检查更新", 10, color=MUTED, wraplength=780, justify="left"); self.update_message.pack(anchor="w", pady=(10, 14))
        self.update_progress = ttk.Progressbar(box, mode="determinate"); self.update_progress.pack(fill="x")
        self.install_button = ttk.Button(box, text="下载并安装", command=self.download_and_install, state="disabled")
        self.install_button.pack(anchor="e", pady=(14, 0))
        safety = self.card(page); safety.pack(fill="x", pady=16)
        label(safety, "安全更新流程", 12, "bold").pack(anchor="w")
        label(safety, "1  从项目 GitHub Release 下载  →  2  核对文件大小和 SHA-256  →  3  由你确认安装  →  4  备份旧版并替换  →  5  新版自检，失败自动回滚", 9, color=MUTED, wraplength=850, justify="left").pack(anchor="w", pady=(9, 0))
        label(safety, "当前发行版没有商业代码签名证书，因此不会静默安装未知新版；Windows 仍可能显示 SmartScreen 提示。", 9, color=WARNING, wraplength=850, justify="left").pack(anchor="w", pady=(10, 0))

    def _build_settings(self):
        page = self.pages["settings"]
        self.page_header(page, "设置", "选择 GDUT 接口，调整后台检查、通知和日志策略")
        canvas = tk.Canvas(page, bg=BG, highlightthickness=0); canvas.pack(fill="both", expand=True)
        body = tk.Frame(canvas, bg=BG); window = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        network = self.card(body); network.pack(fill="x")
        label(network, "GDUT 网络接口", 12, "bold").pack(anchor="w")
        row = tk.Frame(network, bg=CARD); row.pack(fill="x", pady=(10, 0))
        self.adapter_combo = ttk.Combobox(row, state="readonly"); self.adapter_combo.pack(side="left", fill="x", expand=True, ipady=4)
        ttk.Button(row, text="刷新", command=self.refresh_settings_adapters).pack(side="left", padx=(8, 0))
        self.keyword = tk.StringVar(value="gdut")
        row2 = tk.Frame(network, bg=CARD); row2.pack(fill="x", pady=(12, 0))
        label(row2, "网络标识（不区分大小写）", 9, color=MUTED).pack(side="left")
        ttk.Entry(row2, textvariable=self.keyword, width=16).pack(side="left", padx=12)
        monitor = self.card(body); monitor.pack(fill="x", pady=14)
        label(monitor, "后台与提醒", 12, "bold").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        self.check_interval, self.retry_interval, self.login_cooldown = tk.IntVar(), tk.IntVar(), tk.IntVar()
        for col, (title, var) in enumerate((("正常检查（秒）", self.check_interval), ("接口重试（秒）", self.retry_interval), ("登录冷却（秒）", self.login_cooldown))):
            label(monitor, title, 9, color=MUTED).grid(row=1, column=col, sticky="w", padx=(0, 28))
            ttk.Spinbox(monitor, from_=5, to=3600, textvariable=var, width=12).grid(row=2, column=col, sticky="w", pady=(5, 10))
        self.notifications, self.autostart, self.auto_updates = tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar()
        ttk.Checkbutton(monitor, text="失败时发送 Windows 通知", variable=self.notifications).grid(row=3, column=0, sticky="w")
        ttk.Checkbutton(monitor, text="开机静默启动", variable=self.autostart).grid(row=3, column=1, sticky="w")
        ttk.Checkbutton(monitor, text="每天自动检查更新", variable=self.auto_updates).grid(row=3, column=2, sticky="w")
        logs = self.card(body); logs.pack(fill="x")
        label(logs, "日志策略", 12, "bold").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        self.log_size, self.log_retention = tk.StringVar(), tk.StringVar()
        label(logs, "容量上限", 9, color=MUTED).grid(row=1, column=0, sticky="w")
        ttk.Combobox(logs, textvariable=self.log_size, values=("5 MB", "10 MB", "20 MB", "50 MB", "100 MB"), state="readonly", width=12).grid(row=1, column=1, padx=(10, 30))
        label(logs, "保留时间", 9, color=MUTED).grid(row=1, column=2, sticky="w")
        ttk.Combobox(logs, textvariable=self.log_retention, values=("全部", "7 天", "30 天", "90 天", "180 天"), state="readonly", width=12).grid(row=1, column=3, padx=10)
        bottom = tk.Frame(body, bg=BG); bottom.pack(fill="x", pady=14)
        ttk.Button(bottom, text="保存设置", style="Primary.TButton", command=self.save_settings).pack(side="right")
        ttk.Button(bottom, text="卸载", command=self.uninstall_app).pack(side="left")
        label(bottom, f"数据目录：{DATABASE_PATH.parent}", 8, color=MUTED).pack(side="left", padx=12)

    def fill_adapters(self, combo):
        adapters = list_adapters()
        combo["values"] = [f"{a.name}  |  网络: {', '.join(a.profile_names) or '未识别'}  |  IP: {', '.join(a.ipv4) or '无'}  |  {a.status}" for a in adapters]
        if adapters:
            config, selected = load_config(), 0
            configured = str(config.get("adapter_mac", "")).replace("-", "").replace(":", "").upper()
            keyword = str(config.get("network_keyword", "gdut")).casefold()
            for i, adapter in enumerate(adapters):
                mac = adapter.mac.replace("-", "").replace(":", "").upper()
                if (configured and mac == configured) or (not configured and any(keyword in n.casefold() for n in [adapter.name, *adapter.profile_names])):
                    selected = i; break
            combo.current(selected)
        return adapters

    def refresh_settings_adapters(self): self.adapters = self.fill_adapters(self.adapter_combo)

    def reload_all(self):
        self.refresh_accounts(); self.load_settings(); self.refresh_logs(); self.update_status_display(load_status())

    def refresh_accounts(self):
        if not hasattr(self, "account_tree"): return
        self.account_tree.delete(*self.account_tree.get_children())
        preferred = load_state().get("last_success_account")
        for index, item in enumerate(load_accounts(), 1):
            self.account_tree.insert("", "end", iid=item["account"], values=(index, mask_account(item["account"]), "上次成功" if item["account"] == preferred else "备用"))

    def add_account(self):
        dialog = AccountDialog(self); self.wait_window(dialog)
        if dialog.result:
            try:
                added = add_or_update_account(*dialog.result); self.refresh_accounts()
                messagebox.showinfo("保存成功", "账号已加密添加。" if added else "账号密码已更新。")
            except Exception as exc: messagebox.showerror("保存失败", str(exc))

    def delete_account(self):
        selected = self.account_tree.selection()
        if not selected: return messagebox.showwarning("未选择", "请先选择账号。")
        if messagebox.askyesno("确认删除", f"确定删除账号 {mask_account(selected[0])} 吗？"):
            remove_account(selected[0]); self.refresh_accounts()

    def load_settings(self):
        config = load_config()
        self.check_interval.set(int(config.get("check_interval_seconds", 30)))
        self.retry_interval.set(int(config.get("retry_interval_seconds", 15)))
        self.login_cooldown.set(int(config.get("login_cooldown_seconds", 60)))
        self.notifications.set(bool(config.get("notifications_enabled", True)))
        self.autostart.set(bool(config.get("autostart_enabled", True)))
        self.auto_updates.set(bool(config.get("auto_check_updates", True)))
        self.keyword.set(str(config.get("network_keyword", "gdut")))
        self.log_size.set(f"{int(config.get('log_max_mb', 20))} MB")
        days = int(config.get("log_retention_days", 0)); self.log_retention.set("全部" if not days else f"{days} 天")
        self.refresh_settings_adapters()

    def save_settings(self):
        index = self.adapter_combo.current()
        if index < 0 or index >= len(self.adapters): return messagebox.showwarning("请选择接口", "请先选择 GDUT 网络接口。")
        adapter, keyword = self.adapters[index], self.keyword.get().strip() or "gdut"
        if not any(keyword.casefold() in n.casefold() for n in [adapter.name, *adapter.profile_names]):
            return messagebox.showwarning("接口不匹配", f"所选接口名称、配置文件和 SSID 均不包含“{keyword}”。")
        try:
            config = load_config(); config.update({
                "adapter_name": adapter.name, "adapter_mac": adapter.mac, "network_keyword": keyword,
                "check_interval_seconds": max(5, self.check_interval.get()), "retry_interval_seconds": max(5, self.retry_interval.get()),
                "login_cooldown_seconds": max(15, self.login_cooldown.get()), "notifications_enabled": self.notifications.get(),
                "autostart_enabled": self.autostart.get(), "auto_check_updates": self.auto_updates.get(),
                "log_max_mb": int(self.log_size.get().split()[0]),
                "log_retention_days": 0 if self.log_retention.get() == "全部" else int(self.log_retention.get().split()[0]),
            })
            save_config(config); set_autostart(self.autostart.get())
            if self.autostart.get(): start_monitor()
            self.database.maintain(config["log_max_mb"], config["log_retention_days"])
            messagebox.showinfo("保存成功", "设置已经保存并立即生效。")
        except Exception as exc: messagebox.showerror("保存失败", str(exc))

    def selected_log_filters(self):
        text = self.log_days.get(); days = 0 if text == "全部" else (1 if text == "今天" else int(text.split()[0]))
        return days, "" if self.log_level.get() == "全部" else self.log_level.get()

    def refresh_logs(self):
        if not hasattr(self, "log_tree"): return
        self.log_tree.delete(*self.log_tree.get_children())
        days, level = self.selected_log_filters(); search = self.log_search.get().casefold().strip()
        for event_id, timestamp, row_level, message in self.database.query(days, level):
            if search and search not in message.casefold(): continue
            self.log_tree.insert("", "end", iid=str(event_id), values=(local_time(timestamp), row_level, message))
        if hasattr(self, "recent_list"):
            for child in self.recent_list.winfo_children(): child.destroy()
            for _id, timestamp, level_name, message in self.database.query(limit=5):
                row = tk.Frame(self.recent_list, bg=CARD); row.pack(fill="x", pady=5)
                color = DANGER if level_name in ("ERROR", "CRITICAL") else WARNING if level_name == "WARNING" else PRIMARY
                label(row, "●", 9, color=color).pack(side="left", padx=(0, 9))
                label(row, message, 9, wraplength=590, justify="left").pack(side="left")
                label(row, local_time(timestamp), 8, color=MUTED).pack(side="right")

    def export_logs(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV 文件", "*.csv")], initialfile=f"GDUT日志-{datetime.now():%Y%m%d-%H%M%S}.csv")
        if path:
            days, level = self.selected_log_filters(); count = self.database.export_csv(Path(path), days, level)
            messagebox.showinfo("导出完成", f"已导出 {count} 条日志。")

    def run_check(self, login):
        if self._busy: return
        self._busy = True; self.check_button.configure(state="disabled"); self.login_button.configure(state="disabled"); self.status_var.set("正在检查……")
        def worker():
            try: result, error = perform_check(login_if_needed=login, monitor_running=True), None
            except Exception as exc: result, error = {}, exc
            self.after(0, lambda: self.check_finished(result, error))
        threading.Thread(target=worker, daemon=True).start()

    def check_finished(self, status, error):
        self._busy = False; self.check_button.configure(state="normal"); self.login_button.configure(state="normal")
        if error: messagebox.showerror("检查失败", str(error))
        else: self.update_status_display(status); self.refresh_accounts(); self.refresh_logs()

    def poll_status(self):
        self.update_status_display(load_status()); self.after(2500, self.poll_status)

    def update_status_display(self, status):
        state = status.get("state", "unknown"); color = STATUS_COLORS.get(state, MUTED)
        self.status_var.set(status.get("state_text") or "尚未检查")
        self.status_dot.configure(fg=color)
        self.status_hint.configure(text=(status.get("network_profile") or "等待连接 GDUT 网络"))
        self.sidebar_status.configure(text=f"●  {status.get('state_text') or '尚未检查'}", fg=color)
        self.stat_vars["monitor"].set("正在运行" if status.get("monitor_running") else "未运行")
        self.stat_vars["account"].set(status.get("last_success_account") or "—")
        self.stat_vars["check"].set(local_time(status.get("last_check_at", "")))
        for key, value in (("adapter", status.get("adapter_name")), ("profile", status.get("network_profile")),
                           ("ip", status.get("source_ip")), ("mac", status.get("adapter_mac")), ("error", status.get("last_error"))):
            self.connection_vars[key].set(value or "—")

    def check_updates(self):
        self.update_button.configure(state="disabled"); self.update_message.configure(text="正在连接 GitHub 检查更新……"); self.update_progress.configure(mode="indeterminate"); self.update_progress.start(10)
        def worker():
            info = check_latest_release(); self.after(0, lambda: self.finish_update_check(info))
        threading.Thread(target=worker, daemon=True).start()

    def finish_update_check(self, info):
        self.update_progress.stop(); self.update_progress.configure(mode="determinate", value=0); self.update_button.configure(state="normal")
        self._update_info = info; self.render_update_status(info.__dict__)

    def render_update_status(self, data):
        if not data: return
        latest, error = data.get("latest_version", APP_VERSION), data.get("error", "")
        self.update_title.configure(text=f"当前 {APP_VERSION}  ·  最新 {latest}")
        if error:
            self.update_message.configure(text=error, fg=DANGER); self.install_button.configure(state="disabled")
        elif data.get("available"):
            self.update_message.configure(text=f"版本 {latest} 已发布。下载后将核对 SHA-256，安装前需要你确认。", fg=TEXT)
            self.install_button.configure(state="normal")
        else:
            self.update_message.configure(text=f"已是最新版本。上次检查：{local_time(data.get('checked_at', ''))}", fg=SUCCESS)
            self.install_button.configure(state="disabled")

    def download_and_install(self):
        info = self._update_info
        if not info or not info.available: return self.check_updates()
        if not messagebox.askyesno("确认下载", f"将从项目 GitHub Release 下载版本 {info.latest_version}，完成 SHA-256 校验后安装。继续吗？"):
            return
        self.install_button.configure(state="disabled"); self.update_message.configure(text="正在下载新版……", fg=TEXT)
        def progress(done, total):
            value = done * 100 / total if total else 0
            self.after(0, lambda: self.update_progress.configure(value=value))
        def worker():
            try: path, error = download_update(info, progress), None
            except Exception as exc: path, error = None, exc
            self.after(0, lambda: self.download_finished(path, error))
        threading.Thread(target=worker, daemon=True).start()

    def download_finished(self, path, error):
        if error:
            self.update_message.configure(text=str(error), fg=DANGER); self.install_button.configure(state="normal"); return
        if not messagebox.askyesno("校验通过", "新版已下载并通过 SHA-256 校验。现在安装吗？程序将关闭，失败时会恢复旧版。"):
            self.update_message.configure(text=f"已下载到 {path}，稍后可再次安装。", fg=SUCCESS); self.install_button.configure(state="normal"); return
        launch_update_installer(path); self.destroy()

    def finish_install(self):
        try:
            config = load_config()
            if config.get("autostart_enabled", True): set_autostart(True); start_monitor()
            messagebox.showinfo("安装完成", "已安装到当前用户目录，并启用静默后台监控。")
        except Exception as exc: messagebox.showerror("安装未完成", str(exc))

    def uninstall_app(self):
        if not messagebox.askyesno("卸载程序", "确定删除开机任务并卸载程序吗？"): return
        remove_data = messagebox.askyesno("删除个人数据", "是否同时删除加密账号、设置和日志？选择“否”可供以后恢复。")
        try:
            set_autostart(False); stop_monitor(); schedule_self_removal(remove_data); self.destroy()
        except Exception as exc: messagebox.showerror("卸载失败", str(exc))
