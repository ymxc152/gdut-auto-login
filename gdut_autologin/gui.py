from __future__ import annotations

from datetime import datetime
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .constants import APP_NAME, APP_VERSION
from .network import AdapterInfo, connected_physical_adapters, list_adapters
from .service import MonitorThread, perform_check
from .storage import (
    EventDatabase,
    add_or_update_account,
    edit_account,
    export_accounts_file,
    import_accounts_file,
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
from .windows import (
    ShowWindowWatcher,
    TrayIcon,
    schedule_self_removal,
    set_autostart,
)


BG = "#F5F7FA"
SIDEBAR = "#172033"
SIDEBAR_ACTIVE = "#2B3954"
SIDEBAR_HOVER = "#202C43"
CARD = "#FFFFFF"
TEXT = "#172033"
MUTED = "#697386"
PRIMARY = "#3B6FF5"
PRIMARY_HOVER = "#2F5FD7"
SOFT_BLUE = "#EEF3FF"
SUCCESS = "#1C9B67"
WARNING = "#D97706"
DANGER = "#D94A4A"
BORDER = "#E5EAF1"

STATUS_COLORS = {
    "online": SUCCESS,
    "portal_required": WARNING,
    "network_error": DANGER,
    "unexpected_response": DANGER,
    "adapter_missing": MUTED,
    "adapter_down": MUTED,
    "no_ip": MUTED,
    "login_failed": DANGER,
    "paused": MUTED,
    "busy": PRIMARY,
    "unknown": MUTED,
}


def local_time(value: str) -> str:
    if not value:
        return "尚无记录"
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value


def text_label(parent, text="", size=10, weight="normal", color=TEXT, **kwargs):
    return tk.Label(
        parent,
        text=text,
        font=("Microsoft YaHei UI", size, weight),
        fg=color,
        bg=parent.cget("bg"),
        **kwargs,
    )


def flat_button(parent, text, command, kind="secondary", width=None):
    palette = {
        "primary": (PRIMARY, "white", PRIMARY_HOVER),
        "secondary": ("#EEF1F6", TEXT, "#E2E7EF"),
        "quiet": (parent.cget("bg"), MUTED, "#EEF1F6"),
        "danger": ("#FFF0F0", DANGER, "#FFE1E1"),
    }
    background, foreground, active = palette[kind]
    return tk.Button(
        parent,
        text=text,
        command=command,
        width=width,
        bg=background,
        fg=foreground,
        activebackground=active,
        activeforeground=foreground,
        disabledforeground="#A5ADBA",
        relief="flat",
        borderwidth=0,
        cursor="hand2",
        padx=14,
        pady=8,
        font=("Microsoft YaHei UI", 9, "bold" if kind == "primary" else "normal"),
    )


def modern_entry(parent, variable, show="", width=None):
    return tk.Entry(
        parent,
        textvariable=variable,
        show=show,
        width=width,
        relief="flat",
        borderwidth=0,
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=PRIMARY,
        bg="white",
        fg=TEXT,
        insertbackground=TEXT,
        font=("Microsoft YaHei UI", 10),
    )


def check_box(parent, text, variable):
    return tk.Checkbutton(
        parent,
        text=text,
        variable=variable,
        bg=parent.cget("bg"),
        fg=TEXT,
        activebackground=parent.cget("bg"),
        activeforeground=TEXT,
        selectcolor=parent.cget("bg"),
        highlightthickness=0,
        borderwidth=0,
        font=("Microsoft YaHei UI", 9),
    )


def center_on_parent(
    window: tk.Toplevel, parent: tk.Misc, width: int | None = None, height: int | None = None
) -> None:
    window.update_idletasks()
    width = width or max(window.winfo_width(), window.winfo_reqwidth())
    height = height or max(window.winfo_height(), window.winfo_reqheight())
    x = parent.winfo_rootx() + max(0, (parent.winfo_width() - width) // 2)
    y = parent.winfo_rooty() + max(0, (parent.winfo_height() - height) // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")


class ScrollablePanel(tk.Frame):
    def __init__(self, parent, background=CARD, show_scrollbar: bool = True):
        super().__init__(parent, bg=background)
        self.show_scrollbar = show_scrollbar
        self._wheel_bound_widgets: set[str] = set()
        self.canvas = tk.Canvas(self, bg=background, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(
            self, orient="vertical", command=self.canvas.yview, style="Modern.Vertical.TScrollbar"
        )
        self.inner = tk.Frame(self.canvas, bg=background)
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind(
            "<Configure>", self._content_changed
        )
        self.canvas.bind("<Configure>", self._canvas_changed)
        self.canvas.bind("<MouseWheel>", self._wheel)

    def _wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def _content_changed(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._bind_mousewheel_tree(self.inner)
        self.after_idle(self._update_scrollbar)

    def _canvas_changed(self, event):
        self.canvas.itemconfigure(self.window_id, width=event.width)
        self.after_idle(self._update_scrollbar)

    def _update_scrollbar(self):
        if not self.show_scrollbar:
            if self.scrollbar.winfo_ismapped():
                self.scrollbar.pack_forget()
            return
        if self.inner.winfo_reqheight() > self.canvas.winfo_height() + 2:
            if not self.scrollbar.winfo_ismapped():
                self.scrollbar.pack(side="right", fill="y")
        elif self.scrollbar.winfo_ismapped():
            self.scrollbar.pack_forget()

    def _bind_mousewheel_tree(self, widget: tk.Misc):
        widget_name = str(widget)
        if widget_name not in self._wheel_bound_widgets:
            widget.bind("<MouseWheel>", self._wheel, add="+")
            self._wheel_bound_widgets.add(widget_name)
        for child in widget.winfo_children():
            self._bind_mousewheel_tree(child)

    def clear(self):
        for child in self.inner.winfo_children():
            child.destroy()


class SidebarNavItem(tk.Frame):
    def __init__(self, parent, icon: str, title: str, command):
        super().__init__(parent, bg=SIDEBAR, cursor="hand2")
        self.command = command
        self.active = False
        self.icon_label = tk.Label(
            self,
            text=icon,
            width=2,
            anchor="center",
            bg=SIDEBAR,
            fg="#C7CFDD",
            font=("Segoe MDL2 Assets", 11),
            cursor="hand2",
        )
        self.icon_label.pack(side="left", padx=(13, 9), pady=12)
        self.title_label = tk.Label(
            self,
            text=title,
            anchor="w",
            bg=SIDEBAR,
            fg="#C7CFDD",
            font=("Microsoft YaHei UI", 9),
            cursor="hand2",
        )
        self.title_label.pack(side="left", fill="x", expand=True, padx=(0, 12), pady=12)
        for widget in (self, self.icon_label, self.title_label):
            widget.bind("<Button-1>", lambda _event: self.command())
            widget.bind("<Enter>", self._enter)
            widget.bind("<Leave>", self._leave)

    def _paint(self, background: str, foreground: str):
        self.configure(bg=background)
        self.icon_label.configure(bg=background, fg=foreground)
        self.title_label.configure(bg=background, fg=foreground)

    def _enter(self, _event=None):
        if not self.active:
            self._paint(SIDEBAR_HOVER, "white")

    def _leave(self, _event=None):
        self.after_idle(self._restore_if_pointer_left)

    def _restore_if_pointer_left(self):
        pointer_x, pointer_y = self.winfo_pointerxy()
        inside = (
            self.winfo_rootx() <= pointer_x < self.winfo_rootx() + self.winfo_width()
            and self.winfo_rooty() <= pointer_y < self.winfo_rooty() + self.winfo_height()
        )
        if not inside and not self.active:
            self._paint(SIDEBAR, "#C7CFDD")

    def set_active(self, active: bool):
        self.active = active
        self._paint(SIDEBAR_ACTIVE if active else SIDEBAR, "white" if active else "#C7CFDD")


class AccountDialog(tk.Toplevel):
    def __init__(self, parent, original_account: str = ""):
        super().__init__(parent)
        self.original_account = original_account
        self.result: tuple[str, str] | None = None
        self.title("编辑账号" if original_account else "添加账号")
        self.geometry("470x430")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.configure(bg=CARD)

        body = tk.Frame(self, bg=CARD, padx=32, pady=28)
        body.pack(fill="both", expand=True)
        text_label(body, "编辑账号" if original_account else "添加校园网账号", 18, "bold").pack(
            anchor="w"
        )
        text_label(
            body,
            "修改账号后点击保存即可。" if original_account else "请输入你的校园网账号和密码。",
            9,
            color=MUTED,
        ).pack(anchor="w", pady=(5, 22))

        self.account = tk.StringVar(value=original_account)
        self.password = tk.StringVar()
        self.show_password = tk.BooleanVar(value=False)
        self.error = tk.StringVar()

        text_label(body, "校园网账号", 9, "bold").pack(anchor="w")
        self.account_entry = modern_entry(body, self.account)
        self.account_entry.pack(fill="x", ipady=9, pady=(7, 16))
        text_label(body, "校园网密码", 9, "bold").pack(anchor="w")
        self.password_entry = modern_entry(body, self.password, show="●")
        self.password_entry.pack(fill="x", ipady=9, pady=(7, 5))
        text_label(
            body,
            "留空表示保留原密码" if original_account else "请输入校园网密码",
            8,
            color=MUTED,
        ).pack(anchor="w")
        check_box(body, "显示密码", self.show_password).pack(anchor="w", pady=(9, 0))
        self.show_password.trace_add(
            "write",
            lambda *_args: self.password_entry.configure(
                show="" if self.show_password.get() else "●"
            ),
        )
        tk.Label(
            body,
            textvariable=self.error,
            bg=CARD,
            fg=DANGER,
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", pady=(8, 0))

        actions = tk.Frame(body, bg=CARD)
        actions.pack(fill="x", side="bottom")
        primary_text = "确认保存" if original_account else "确认添加"
        flat_button(actions, primary_text, self.save, "primary", width=10).pack(side="right")
        flat_button(actions, "取消", self.destroy, "quiet", width=8).pack(side="right", padx=8)
        self.bind("<Return>", lambda _event: self.save())
        self.bind("<Escape>", lambda _event: self.destroy())
        self.after_idle(lambda: center_on_parent(self, parent, 470, 430))
        self.after_idle(self.account_entry.focus_set)

    def save(self):
        account = self.account.get().strip()
        password = self.password.get()
        if not account:
            self.error.set("请输入校园网账号。")
            self.account_entry.focus_set()
            return
        if not self.original_account and not password:
            self.error.set("请输入校园网密码。")
            self.password_entry.focus_set()
            return
        self.result = (account, password)
        self.password.set("")
        self.destroy()


class FirstRunDialog(tk.Toplevel):
    def __init__(self, app: "GDUTApp"):
        super().__init__(app)
        self.app = app
        self.title("首次设置")
        self.geometry("620x590")
        self.resizable(False, False)
        self.transient(app)
        self.grab_set()
        self.configure(bg=CARD)

        body = tk.Frame(self, bg=CARD, padx=36, pady=30)
        body.pack(fill="both", expand=True)
        text_label(body, "欢迎使用 GDUT 自动登录", 20, "bold").pack(anchor="w")
        text_label(body, "完成下面三项设置，程序就会常驻系统托盘自动工作。", 9, color=MUTED).pack(
            anchor="w", pady=(5, 22)
        )
        text_label(body, "1. 选择已连接的网络接口", 9, "bold").pack(anchor="w")
        text_label(
            body,
            "请选择 IPv4 地址以 10. 开头的接口；有线校园网可能显示为“未知的网络”。",
            8,
            color=MUTED,
        ).pack(anchor="w", pady=(4, 0))
        self.adapter = ttk.Combobox(body, state="readonly", style="Modern.TCombobox")
        self.adapter.pack(fill="x", ipady=7, pady=(7, 16))
        self.adapters = app.fill_adapters(self.adapter)

        self.account = tk.StringVar()
        self.password = tk.StringVar()
        self.show_password = tk.BooleanVar(value=False)
        self.error = tk.StringVar()
        text_label(body, "2. 输入校园网账号", 9, "bold").pack(anchor="w")
        modern_entry(body, self.account).pack(fill="x", ipady=8, pady=(7, 14))
        text_label(body, "3. 输入校园网密码", 9, "bold").pack(anchor="w")
        self.password_entry = modern_entry(body, self.password, show="●")
        self.password_entry.pack(fill="x", ipady=8, pady=(7, 6))
        check_box(body, "显示密码", self.show_password).pack(anchor="w", pady=(0, 10))
        self.show_password.trace_add(
            "write",
            lambda *_args: self.password_entry.configure(
                show="" if self.show_password.get() else "●"
            ),
        )
        self.autostart = tk.BooleanVar(value=True)
        check_box(body, "开机自动启动，隐藏到托盘运行", self.autostart).pack(anchor="w")
        tk.Label(
            body,
            textvariable=self.error,
            bg=CARD,
            fg=DANGER,
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", pady=(8, 0))
        actions = tk.Frame(body, bg=CARD)
        actions.pack(fill="x", side="bottom")
        flat_button(actions, "确认启用", self.finish, "primary", width=10).pack(side="right")
        flat_button(actions, "稍后设置", self.destroy, "quiet").pack(side="right", padx=8)
        self.bind("<Return>", lambda _event: self.finish())
        self.bind("<Escape>", lambda _event: self.destroy())
        self.after_idle(lambda: center_on_parent(self, app, 620, 590))

    def finish(self):
        index = self.adapter.current()
        account, password = self.account.get().strip(), self.password.get()
        if index < 0:
            self.error.set("请先选择网络接口。")
            return
        if not account:
            self.error.set("请输入校园网账号。")
            return
        if not password:
            self.error.set("请输入校园网密码。")
            return
        adapter = self.adapters[index]
        config = load_config()
        config.update(
            {
                "adapter_name": adapter.name,
                "adapter_mac": adapter.mac,
                "autostart_enabled": self.autostart.get(),
            }
        )
        try:
            save_config(config)
            add_or_update_account(account, password)
            self.password.set("")
            set_autostart(self.autostart.get())
            self.destroy()
            self.app.reload_all()
            self.app.run_check(True)
        except Exception as exc:
            self.error.set(f"保存失败：{exc}")


class GDUTApp(tk.Tk):
    NAV = [
        ("overview", "概览", "\ue80f"),
        ("accounts", "账号", "\ue77b"),
        ("logs", "日志", "\ue8fd"),
        ("settings", "设置", "\ue713"),
    ]

    def __init__(self, first_run: bool = False, start_hidden: bool = False):
        super().__init__()
        self.title(f"{APP_NAME}  {APP_VERSION}")
        self.geometry("1120x740")
        self.minsize(960, 650)
        self.configure(bg=BG)
        self.database = EventDatabase()
        self.adapters: list[AdapterInfo] = []
        self._busy = False
        self._monitor_busy = False
        self._auto_login_enabled = bool(load_config().get("auto_login_enabled", True))
        self._loading_settings = False
        self._settings_apply_after: str | None = None
        self._update_info: UpdateInfo | None = None
        self._tray: TrayIcon | None = None
        self._tray_tooltip = ""
        self._status_queue: queue.Queue = queue.Queue()
        self.monitor = MonitorThread()
        self.monitor.on_status = self._status_queue.put
        self.pages: dict[str, tk.Frame] = {}
        self.nav_buttons: dict[str, SidebarNavItem] = {}
        self._configure_style()
        self._build_shell()
        self.protocol("WM_DELETE_WINDOW", self.close_window)
        self.show_page("overview")
        self.reload_all()
        self.after(1000, self.poll_status)
        self._show_watcher = ShowWindowWatcher(lambda: self.after(0, self.show_window))
        self._show_watcher.start()
        self._setup_tray()
        self.monitor.start()
        if not load_accounts() or not load_config().get("adapter_mac"):
            self.after(300, lambda: FirstRunDialog(self))
        elif first_run:
            self.after(300, self.finish_install)
        elif start_hidden:
            self.withdraw()

    def _configure_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        self.option_add("*Font", ("Microsoft YaHei UI", 9))
        style.configure(
            "Modern.TCombobox",
            fieldbackground="white",
            background="white",
            foreground=TEXT,
            arrowcolor=MUTED,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=(10, 6),
            arrowsize=22,
        )
        style.map(
            "Modern.TCombobox",
            fieldbackground=[("readonly", "white")],
            foreground=[("readonly", TEXT), ("focus", TEXT)],
            selectbackground=[("readonly", "white")],
            selectforeground=[("readonly", TEXT)],
            bordercolor=[("focus", PRIMARY)],
        )
        style.configure(
            "Modern.Horizontal.TProgressbar",
            troughcolor="#E9EDF4",
            background=PRIMARY,
            borderwidth=0,
        )
        style.configure(
            "Modern.Vertical.TScrollbar",
            troughcolor=CARD,
            background="#C9D1DE",
            bordercolor=CARD,
            arrowcolor=MUTED,
            lightcolor="#C9D1DE",
            darkcolor="#C9D1DE",
        )

    def _build_shell(self):
        sidebar = tk.Frame(self, bg=SIDEBAR, width=205)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar, bg=SIDEBAR, padx=22, pady=25)
        brand.pack(fill="x")
        text_label(brand, "GDUT", 20, "bold", "white").pack(anchor="w")
        text_label(brand, "校园网助手", 9, color="#A7B0C0").pack(anchor="w", pady=(2, 0))

        nav = tk.Frame(sidebar, bg=SIDEBAR, padx=10)
        nav.pack(fill="x", pady=8)
        for key, title, icon in self.NAV:
            item = SidebarNavItem(
                nav, icon, title, lambda page=key: self.show_page(page)
            )
            item.pack(fill="x", pady=3)
            self.nav_buttons[key] = item

        footer = tk.Frame(sidebar, bg=SIDEBAR, padx=22, pady=22)
        footer.pack(side="bottom", fill="x")
        self.sidebar_status = text_label(footer, "●  正在读取状态", 9, color="#A7B0C0")
        self.sidebar_status.pack(anchor="w")
        text_label(footer, f"v{APP_VERSION}", 8, color="#7D8798").pack(anchor="w", pady=(6, 0))

        self.content = tk.Frame(self, bg=BG)
        self.content.pack(side="left", fill="both", expand=True)
        for key, *_ in self.NAV:
            self.pages[key] = tk.Frame(self.content, bg=BG, padx=28, pady=24)
        self._build_overview()
        self._build_accounts()
        self._build_logs()
        self._build_settings()

    def show_page(self, key: str):
        for page in self.pages.values():
            page.pack_forget()
        self.pages[key].pack(fill="both", expand=True)
        for name, item in self.nav_buttons.items():
            item.set_active(name == key)
        if key == "accounts":
            self.refresh_accounts()
        elif key == "logs":
            self.refresh_logs()
        elif key == "settings":
            self.refresh_settings_adapters(prefer_active=True)
            self.render_update_status(load_update_status())

    def page_header(self, page, title: str, subtitle: str):
        text_label(page, title, 22, "bold").pack(anchor="w")
        if subtitle:
            text_label(page, subtitle, 9, color=MUTED).pack(anchor="w", pady=(4, 18))
        else:
            tk.Frame(page, bg=BG, height=16).pack(fill="x")

    def card(self, parent, padx=20, pady=18):
        return tk.Frame(
            parent,
            bg=CARD,
            highlightbackground=BORDER,
            highlightthickness=1,
            padx=padx,
            pady=pady,
        )

    def _build_overview(self):
        page = self.pages["overview"]
        self.page_header(page, "网络概览", "")
        hero = self.card(page, 24, 22)
        hero.pack(fill="x")
        top = tk.Frame(hero, bg=CARD)
        top.pack(fill="x")
        self.status_dot = text_label(top, "●", 24, color=MUTED)
        self.status_dot.pack(side="left", padx=(0, 12))
        status_group = tk.Frame(top, bg=CARD)
        status_group.pack(side="left")
        self.status_var = tk.StringVar(value="尚未检查")
        tk.Label(
            status_group,
            textvariable=self.status_var,
            font=("Microsoft YaHei UI", 20, "bold"),
            fg=TEXT,
            bg=CARD,
        ).pack(anchor="w")
        self.status_hint = text_label(status_group, "等待首次网络检测", 9, color=MUTED)
        self.status_hint.pack(anchor="w", pady=(3, 0))
        actions = tk.Frame(top, bg=CARD)
        actions.pack(side="right")
        self.check_button = flat_button(actions, "立即检查", lambda: self.run_check(False))
        self.check_button.pack(side="left", padx=(0, 8))
        self.login_button = flat_button(
            actions, "重新连接", lambda: self.run_check(True, force=True), "primary"
        )
        self.login_button.pack(side="left")

        stats = tk.Frame(page, bg=BG)
        stats.pack(fill="x", pady=14)
        self.stat_vars = {key: tk.StringVar(value="—") for key in ("monitor", "account", "check")}
        for index, (title, key) in enumerate(
            (("自动登录", "monitor"), ("上次账号", "account"), ("最后检查", "check"))
        ):
            box = self.card(stats, 17, 14)
            box.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 7, 0))
            text_label(box, title, 8, color=MUTED).pack(anchor="w")
            tk.Label(
                box,
                textvariable=self.stat_vars[key],
                font=("Microsoft YaHei UI", 11, "bold"),
                fg=TEXT,
                bg=CARD,
            ).pack(anchor="w", pady=(6, 0))
            stats.columnconfigure(index, weight=1)

        columns = tk.Frame(page, bg=BG)
        columns.pack(fill="both", expand=True)
        columns.columnconfigure(0, weight=5)
        columns.columnconfigure(1, weight=4)
        columns.rowconfigure(0, weight=1)

        recent = self.card(columns, 18, 16)
        recent.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        text_label(recent, "最近活动", 11, "bold").pack(anchor="w", pady=(0, 9))
        self.recent_list = tk.Frame(recent, bg=CARD)
        self.recent_list.pack(fill="both", expand=True)

        connection = self.card(columns, 18, 16)
        connection.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        text_label(connection, "GDUT 连接", 11, "bold").pack(anchor="w", pady=(0, 8))
        self.connection_vars = {
            key: tk.StringVar(value="—") for key in ("adapter", "profile", "ip", "error")
        }
        for title, key in (
            ("网络", "profile"),
            ("接口", "adapter"),
            ("源 IP", "ip"),
            ("最近问题", "error"),
        ):
            row = tk.Frame(connection, bg=CARD)
            row.pack(fill="x", pady=7)
            text_label(row, title, 8, color=MUTED).pack(anchor="w")
            tk.Label(
                row,
                textvariable=self.connection_vars[key],
                bg=CARD,
                fg=TEXT,
                font=("Microsoft YaHei UI", 9, "bold" if key == "ip" else "normal"),
                wraplength=330,
                justify="left",
            ).pack(anchor="w", pady=(2, 0))

    def _build_accounts(self):
        page = self.pages["accounts"]
        self.page_header(page, "账号", "双击账号即可编辑")
        toolbar = tk.Frame(page, bg=BG)
        toolbar.pack(fill="x", pady=(0, 10))
        self.account_count = text_label(toolbar, "0 个账号", 9, color=MUTED)
        self.account_count.pack(side="left", pady=8)
        flat_button(toolbar, "添加账号", self.add_account, "primary").pack(side="right")
        flat_button(toolbar, "导入账号", self.import_accounts).pack(side="right", padx=8)
        flat_button(toolbar, "导出账号", self.export_accounts).pack(side="right")
        account_card = self.card(page, 0, 0)
        account_card.pack(fill="both", expand=True)
        self.account_list = ScrollablePanel(account_card)
        self.account_list.pack(fill="both", expand=True, padx=1, pady=1)

    def _build_logs(self):
        page = self.pages["logs"]
        self.page_header(page, "日志", "")
        filters = tk.Frame(page, bg=BG)
        filters.pack(fill="x", pady=(0, 10))
        self.log_search = tk.StringVar()
        self.log_level = tk.StringVar(value="全部级别")
        self.log_days = tk.StringVar(value="最近 7 天")
        search = modern_entry(filters, self.log_search, width=28)
        search.pack(side="left", ipady=7)
        search.insert(0, "")
        search.bind("<KeyRelease>", lambda _event: self.refresh_logs())
        level = ttk.Combobox(
            filters,
            textvariable=self.log_level,
            values=("全部级别", "INFO", "WARNING", "ERROR", "CRITICAL"),
            state="readonly",
            width=12,
            style="Modern.TCombobox",
        )
        level.pack(side="left", padx=8)
        days = ttk.Combobox(
            filters,
            textvariable=self.log_days,
            values=("今天", "最近 7 天", "最近 30 天", "全部时间"),
            state="readonly",
            width=13,
            style="Modern.TCombobox",
        )
        days.pack(side="left")
        level.bind("<<ComboboxSelected>>", lambda _event: self.refresh_logs())
        days.bind("<<ComboboxSelected>>", lambda _event: self.refresh_logs())
        flat_button(filters, "刷新", self.refresh_logs).pack(side="left", padx=8)
        flat_button(filters, "清空日志", self.clear_logs, "danger").pack(side="right")
        self.log_count = text_label(filters, "", 8, color=MUTED)
        self.log_count.pack(side="right", padx=(0, 10), pady=8)

        log_card = self.card(page, 0, 0)
        log_card.pack(fill="both", expand=True)
        self.log_list = ScrollablePanel(log_card)
        self.log_list.pack(fill="both", expand=True, padx=1, pady=1)

    def _build_settings(self):
        page = self.pages["settings"]
        self.page_header(page, "设置", "网络、自动登录、日志与更新")
        actions = tk.Frame(page, bg=BG)
        actions.pack(side="bottom", fill="x", pady=(10, 0))
        self.settings_feedback = tk.StringVar()
        self.settings_feedback_label = tk.Label(
            actions,
            textvariable=self.settings_feedback,
            bg=BG,
            fg=SUCCESS,
            font=("Microsoft YaHei UI", 9),
        )
        self.settings_feedback_label.pack(side="left", pady=8)
        flat_button(actions, "卸载", self.uninstall_app, "quiet").pack(side="right")
        scroll = ScrollablePanel(page, background=BG, show_scrollbar=False)
        scroll.pack(fill="both", expand=True)
        body = scroll.inner

        network = self.card(body)
        network.pack(fill="x", pady=(0, 12))
        text_label(network, "网络接口", 11, "bold").pack(anchor="w")
        text_label(
            network,
            "显示所有已连接的物理网卡；校园网通常使用 10.x.x.x 地址。",
            8,
            color=MUTED,
        ).pack(anchor="w", pady=(3, 0))
        network_row = tk.Frame(network, bg=CARD)
        network_row.pack(fill="x", pady=(10, 0))
        self.adapter_combo = ttk.Combobox(
            network_row, state="readonly", style="Modern.TCombobox"
        )
        self.adapter_combo.pack(side="left", fill="x", expand=True)
        flat_button(
            network_row,
            "刷新",
            lambda: self.refresh_settings_adapters(prefer_active=True),
        ).pack(
            side="left", padx=(8, 0)
        )
        monitor = self.card(body)
        monitor.pack(fill="x", pady=(0, 12))
        text_label(monitor, "自动登录", 11, "bold").pack(anchor="w")
        text_label(
            monitor,
            "程序驻留系统托盘，定期检查校园网状态，掉线时自动重新认证。",
            8,
            color=MUTED,
        ).pack(anchor="w", pady=(3, 12))
        values = tk.Frame(monitor, bg=CARD)
        values.pack(fill="x")
        self.check_interval = tk.IntVar()
        self.retry_interval = tk.IntVar()
        self.login_cooldown = tk.IntVar()
        for index, (title, variable) in enumerate(
            (
                ("正常检查（秒）", self.check_interval),
                ("断开重试（秒）", self.retry_interval),
                ("失败冷却（秒）", self.login_cooldown),
            )
        ):
            group = tk.Frame(values, bg=CARD)
            group.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 12, 0))
            text_label(group, title, 8, color=MUTED).pack(anchor="w")
            modern_entry(group, variable).pack(fill="x", ipady=7, pady=(5, 0))
            values.columnconfigure(index, weight=1)
        toggles = tk.Frame(monitor, bg=CARD)
        toggles.pack(fill="x", pady=(12, 0))
        self.auto_login = tk.BooleanVar()
        self.notifications = tk.BooleanVar()
        self.autostart = tk.BooleanVar()
        self.auto_updates = tk.BooleanVar()
        check_box(toggles, "启用自动登录", self.auto_login).pack(side="left")
        check_box(toggles, "连接失败时通知", self.notifications).pack(side="left", padx=18)
        check_box(toggles, "开机自动启动", self.autostart).pack(side="left")
        check_box(toggles, "自动检查更新", self.auto_updates).pack(side="left", padx=18)

        logs = self.card(body)
        logs.pack(fill="x", pady=(0, 12))
        text_label(logs, "日志保留", 11, "bold").pack(anchor="w", pady=(0, 10))
        log_row = tk.Frame(logs, bg=CARD)
        log_row.pack(fill="x")
        self.log_size = tk.StringVar()
        self.log_retention = tk.StringVar()
        text_label(log_row, "容量", 8, color=MUTED).pack(side="left")
        ttk.Combobox(
            log_row,
            textvariable=self.log_size,
            values=("5 MB", "10 MB", "20 MB", "50 MB", "100 MB"),
            state="readonly",
            width=11,
            style="Modern.TCombobox",
        ).pack(side="left", padx=(8, 22))
        text_label(log_row, "时间", 8, color=MUTED).pack(side="left")
        ttk.Combobox(
            log_row,
            textvariable=self.log_retention,
            values=("全部", "7 天", "30 天", "90 天", "180 天"),
            state="readonly",
            width=11,
            style="Modern.TCombobox",
        ).pack(side="left", padx=8)

        update = self.card(body)
        update.pack(fill="x", pady=(0, 12))
        update_header = tk.Frame(update, bg=CARD)
        update_header.pack(fill="x")
        self.update_title = text_label(update_header, f"软件更新 · v{APP_VERSION}", 11, "bold")
        self.update_title.pack(side="left")
        self.install_slot = tk.Frame(update_header, bg=CARD)
        self.install_slot.pack(side="right")
        self.install_button = flat_button(
            self.install_slot, "下载并安装", self.download_and_install, "primary"
        )
        self.update_button = flat_button(update_header, "检查更新", self.check_updates)
        self.update_button.pack(side="right")
        self.update_message = text_label(
            update, "尚未检查更新", 8, color=MUTED, wraplength=720, justify="left"
        )
        self.update_message.pack(anchor="w", pady=(7, 8))
        self.update_progress = ttk.Progressbar(
            update, mode="determinate", style="Modern.Horizontal.TProgressbar"
        )

        self.adapter_combo.bind("<<ComboboxSelected>>", self.schedule_settings_apply)
        for variable in (
            self.check_interval,
            self.retry_interval,
            self.login_cooldown,
            self.auto_login,
            self.notifications,
            self.autostart,
            self.auto_updates,
            self.log_size,
            self.log_retention,
        ):
            variable.trace_add("write", self.schedule_settings_apply)


    def fill_adapters(
        self, combo: ttk.Combobox, prefer_active: bool = False
    ) -> list[AdapterInfo]:
        config = load_config()
        adapters = connected_physical_adapters(list_adapters())
        combo["values"] = [
            f"{item.name} · {', '.join(item.profile_names) or '未识别网络'} · "
            f"{', '.join(item.ipv4) or '无 IPv4'}"
            for item in adapters
        ]
        if adapters:
            configured = str(config.get("adapter_mac", "")).replace("-", "").replace(":", "").upper()
            selected = 0
            for index, adapter in enumerate(adapters):
                mac = adapter.mac.replace("-", "").replace(":", "").upper()
                if configured and mac == configured:
                    selected = index
                    break
            else:
                if prefer_active or not configured:
                    for index, adapter in enumerate(adapters):
                        if any(ip.startswith("10.") for ip in adapter.ipv4):
                            selected = index
                            break
            combo.current(selected)
        else:
            combo.set("")
        return adapters

    def refresh_settings_adapters(self, prefer_active: bool = False):
        self.adapters = self.fill_adapters(self.adapter_combo, prefer_active=prefer_active)
        selected = self.adapter_combo.current()
        if 0 <= selected < len(self.adapters):
            adapter = self.adapters[selected]
            network_name = next(iter(adapter.profile_names), adapter.name)
            self.settings_feedback.set(f"已刷新并选中 {network_name}")
        else:
            self.settings_feedback.set("当前没有已连接的物理网卡")
        self.settings_feedback_label.configure(fg=MUTED)
        if prefer_active and 0 <= selected < len(self.adapters):
            selected_mac = self.adapters[selected].mac.replace("-", "").replace(":", "").upper()
            configured_mac = str(load_config().get("adapter_mac", "")).replace("-", "").replace(":", "").upper()
            if selected_mac != configured_mac:
                self.schedule_settings_apply()

    def reload_all(self):
        self.refresh_accounts()
        self.load_settings()
        self.refresh_logs()
        self.update_status_display(load_status())
        self.render_update_status(load_update_status())

    def refresh_accounts(self):
        if not hasattr(self, "account_list"):
            return
        self.account_list.clear()
        accounts = load_accounts()
        preferred = load_state().get("last_success_account")
        self.account_count.configure(text=f"{len(accounts)} 个账号")
        if not accounts:
            empty = tk.Frame(self.account_list.inner, bg=CARD, pady=55)
            empty.pack(fill="x")
            text_label(empty, "还没有账号", 13, "bold", color=MUTED).pack()
            text_label(empty, "点击右上角“添加账号”开始使用", 9, color=MUTED).pack(pady=(5, 0))
            return
        for index, item in enumerate(accounts, 1):
            account = item["account"]
            row = tk.Frame(self.account_list.inner, bg=CARD, padx=20, pady=15)
            row.pack(fill="x")
            if index > 1:
                separator = tk.Frame(row, bg=BORDER, height=1)
                separator.place(x=0, y=-15, relwidth=1)
            avatar = tk.Label(
                row,
                text=str(index),
                width=3,
                height=1,
                bg=SOFT_BLUE,
                fg=PRIMARY,
                font=("Microsoft YaHei UI", 10, "bold"),
            )
            avatar.pack(side="left", padx=(0, 14))
            info = tk.Frame(row, bg=CARD)
            info.pack(side="left", fill="x", expand=True)
            account_label = text_label(info, mask_account(account), 11, "bold")
            account_label.pack(anchor="w")
            status = "上次连接成功" if account == preferred else "可用账号"
            status_label = text_label(
                info, f"{status} · 双击编辑", 8, color=SUCCESS if account == preferred else MUTED
            )
            status_label.pack(anchor="w", pady=(3, 0))
            flat_button(row, "删除", lambda value=account: self.delete_account(value), "danger").pack(
                side="right"
            )
            flat_button(row, "编辑", lambda value=account: self.open_account_editor(value)).pack(
                side="right", padx=8
            )
            for widget in (row, avatar, info, account_label, status_label):
                widget.bind("<Double-Button-1>", lambda _event, value=account: self.open_account_editor(value))

    def add_account(self):
        dialog = AccountDialog(self)
        self.wait_window(dialog)
        if not dialog.result:
            return
        account, password = dialog.result
        try:
            add_or_update_account(account, password)
            self.refresh_accounts()
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)

    def export_accounts(self):
        if not load_accounts():
            messagebox.showinfo("导出账号", "当前没有可导出的账号。", parent=self)
            return
        if not messagebox.askyesno(
            "导出账号",
            "导出的 JSON 文件包含明文账号和密码，仅应分享给可信的人。\n\n是否继续？",
            parent=self,
        ):
            return
        destination = filedialog.asksaveasfilename(
            parent=self,
            title="导出账号",
            defaultextension=".json",
            initialfile=datetime.now().strftime("GDUT-accounts-%Y%m%d-%H%M%S.json"),
            filetypes=(("JSON 账号文件", "*.json"),),
        )
        if not destination:
            return
        try:
            count = export_accounts_file(Path(destination))
            messagebox.showinfo(
                "导出完成",
                f"已导出 {count} 个账号。",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc), parent=self)

    def import_accounts(self):
        source = filedialog.askopenfilename(
            parent=self,
            title="导入账号",
            filetypes=(("JSON 账号文件", "*.json"),),
        )
        if not source:
            return
        try:
            added, updated = import_accounts_file(Path(source))
            self.refresh_accounts()
            messagebox.showinfo(
                "导入完成",
                f"新增 {added} 个账号，更新 {updated} 个同名账号。",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc), parent=self)

    def open_account_editor(self, original_account: str):
        dialog = AccountDialog(self, original_account)
        self.wait_window(dialog)
        if not dialog.result:
            return
        account, password = dialog.result
        try:
            if not edit_account(original_account, account, password):
                raise ValueError("账号不存在，可能已被删除。")
            self.refresh_accounts()
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)

    def delete_account(self, account: str):
        if messagebox.askyesno("删除账号", f"确定删除 {mask_account(account)} 吗？", parent=self):
            remove_account(account)
            self.refresh_accounts()

    def load_settings(self):
        self._loading_settings = True
        try:
            config = load_config()
            self.check_interval.set(int(config.get("check_interval_seconds", 30)))
            self.retry_interval.set(int(config.get("retry_interval_seconds", 15)))
            self.login_cooldown.set(int(config.get("login_cooldown_seconds", 60)))
            self.auto_login.set(bool(config.get("auto_login_enabled", True)))
            self._auto_login_enabled = self.auto_login.get()
            self.notifications.set(bool(config.get("notifications_enabled", True)))
            self.autostart.set(bool(config.get("autostart_enabled", True)))
            self.auto_updates.set(bool(config.get("auto_check_updates", True)))
            self.log_size.set(f"{int(config.get('log_max_mb', 20))} MB")
            days = int(config.get("log_retention_days", 0))
            self.log_retention.set("全部" if not days else f"{days} 天")
            self.refresh_settings_adapters(prefer_active=True)
        finally:
            self._loading_settings = False
        selected = self.adapter_combo.current()
        if 0 <= selected < len(self.adapters):
            selected_mac = self.adapters[selected].mac.replace("-", "").replace(":", "").upper()
            configured_mac = str(config.get("adapter_mac", "")).replace("-", "").replace(":", "").upper()
            if selected_mac != configured_mac:
                self.schedule_settings_apply()
        self.settings_feedback.set("修改后自动保存")
        self.settings_feedback_label.configure(fg=MUTED)

    def schedule_settings_apply(self, *_args):
        if self._loading_settings:
            return
        if self._settings_apply_after:
            try:
                self.after_cancel(self._settings_apply_after)
            except tk.TclError:
                pass
        self.settings_feedback.set("正在自动保存……")
        self.settings_feedback_label.configure(fg=MUTED)
        self._settings_apply_after = self.after(450, self.apply_settings)

    def apply_settings(self):
        self._settings_apply_after = None
        index = self.adapter_combo.current()
        config = load_config()
        try:
            previous_autostart = bool(config.get("autostart_enabled", True))
            previous_log_size = int(config.get("log_max_mb", 20))
            previous_log_retention = int(config.get("log_retention_days", 0))
            if 0 <= index < len(self.adapters):
                adapter = self.adapters[index]
                config.update(
                    {
                        "adapter_name": adapter.name,
                        "adapter_mac": adapter.mac,
                    }
                )
            config.update(
                {
                    "check_interval_seconds": max(5, int(self.check_interval.get())),
                    "retry_interval_seconds": max(5, int(self.retry_interval.get())),
                    "login_cooldown_seconds": max(15, int(self.login_cooldown.get())),
                    "notifications_enabled": self.notifications.get(),
                    "auto_login_enabled": self.auto_login.get(),
                    "autostart_enabled": self.autostart.get(),
                    "auto_check_updates": self.auto_updates.get(),
                    "log_max_mb": int(self.log_size.get().split()[0]),
                    "log_retention_days": 0
                    if self.log_retention.get() == "全部"
                    else int(self.log_retention.get().split()[0]),
                }
            )
            save_config(config)
            self._auto_login_enabled = bool(config.get("auto_login_enabled", True))
            if previous_autostart != self.autostart.get():
                set_autostart(self.autostart.get())
            if (
                previous_log_size != config["log_max_mb"]
                or previous_log_retention != config["log_retention_days"]
            ):
                self.database.maintain(config["log_max_mb"], config["log_retention_days"])
            self.settings_feedback.set("设置已自动保存")
            self.settings_feedback_label.configure(fg=SUCCESS)
            self.after(1800, self.reset_settings_feedback)
        except Exception as exc:
            self.settings_feedback.set(f"自动保存失败：{exc}")
            self.settings_feedback_label.configure(fg=DANGER)

    def reset_settings_feedback(self):
        if not self._monitor_busy:
            self.settings_feedback.set("修改后自动保存")
            self.settings_feedback_label.configure(fg=MUTED)

    def close_window(self):
        if self._settings_apply_after:
            try:
                self.after_cancel(self._settings_apply_after)
            except tk.TclError:
                pass
            self._settings_apply_after = None
            self.apply_settings()
        self.withdraw()
        self._hint_close_to_tray()

    def show_window(self):
        self.deiconify()
        self.lift()
        try:
            self.focus_force()
        except tk.TclError:
            pass

    def quit_app(self):
        if self._settings_apply_after:
            try:
                self.after_cancel(self._settings_apply_after)
            except tk.TclError:
                pass
            self._settings_apply_after = None
            self.apply_settings()
        try:
            if self.monitor.is_alive():
                self.monitor.stop()
                self.monitor.join(timeout=2)
        except Exception:
            pass
        try:
            from .service import base_status
            from .storage import save_status
            status = base_status()
            status.update({"monitor_running": False, "state_text": "自动登录已停止"})
            save_status(status)
        except Exception:
            pass
        try:
            if self._tray:
                self._tray.stop()
        except Exception:
            pass
        try:
            self._show_watcher.stop()
        except Exception:
            pass
        self.destroy()

    def _setup_tray(self):
        try:
            self._tray = TrayIcon(
                tooltip=f"{APP_NAME}",
                on_activate=lambda: self.after(0, self.show_window),
                get_menu_items=self._tray_menu_items,
                on_command=self._on_tray_command,
            )
            self._tray.start()
        except Exception:
            self._tray = None

    def _tray_menu_items(self):
        autostart = bool(load_config().get("autostart_enabled", True))
        return [
            ("打开主窗口", "cmd"),
            ("立即检查", "cmd"),
            ("", "sep"),
            ("开机自启", "check" if autostart else "cmd"),
            ("", "sep"),
            ("退出", "cmd"),
        ]

    def _on_tray_command(self, label: str, kind: str):
        if label == "打开主窗口":
            self.after(0, self.show_window)
        elif label == "立即检查":
            self.after(0, lambda: self.run_check(True))
        elif label == "开机自启":
            self.after(0, self.toggle_autostart)
        elif label == "退出":
            self.after(0, self.quit_app)

    def toggle_autostart(self):
        config = load_config()
        enabled = not bool(config.get("autostart_enabled", True))
        try:
            set_autostart(enabled)
        except Exception as exc:
            messagebox.showerror("开机自启设置失败", str(exc), parent=self)
            return
        config["autostart_enabled"] = enabled
        save_config(config)
        self.load_settings()

    def _hint_close_to_tray(self):
        if not self._tray:
            return
        config = load_config()
        if config.get("close_to_tray_hinted", False):
            return
        self._tray.show_balloon(
            "仍在后台运行",
            "GDUT 自动登录已隐藏到任务栏托盘，右键托盘图标可打开或退出。",
        )
        config["close_to_tray_hinted"] = True
        save_config(config)

    def _update_tray_tooltip(self, status: dict):
        if not self._tray:
            return
        enabled = self.monitor.is_alive() and self._auto_login_enabled
        suffix = "自动登录已启用" if enabled else "自动登录已暂停"
        text = f"{status.get('state_text') or '尚未检查'} · {suffix}"
        if text != self._tray_tooltip:
            self._tray_tooltip = text
            self._tray.set_tooltip(f"{APP_NAME}\n{text}")

    def _on_monitor_status(self, status: dict):
        self.update_status_display(status)

    def selected_log_filters(self) -> tuple[int, str]:
        day_map = {"今天": 1, "最近 7 天": 7, "最近 30 天": 30, "全部时间": 0}
        level = "" if self.log_level.get() == "全部级别" else self.log_level.get()
        return day_map.get(self.log_days.get(), 7), level

    def clear_logs(self):
        if not messagebox.askyesno(
            "清空日志",
            "确定清空全部日志吗？此操作不会影响账号、设置或自动登录。",
            parent=self,
        ):
            return
        try:
            self.database.clear()
            self.refresh_logs()
        except Exception as exc:
            messagebox.showerror("清空失败", str(exc), parent=self)

    def refresh_logs(self):
        if not hasattr(self, "log_list"):
            return
        self.log_list.clear()
        days, level = self.selected_log_filters()
        search = self.log_search.get().casefold().strip()
        rows = [
            row
            for row in self.database.query(days, level, limit=500)
            if not search or search in row[3].casefold()
        ]
        self.log_count.configure(text=f"{len(rows)} 条")
        if not rows:
            empty = tk.Frame(self.log_list.inner, bg=CARD, pady=55)
            empty.pack(fill="x")
            text_label(empty, "没有符合条件的日志", 11, "bold", color=MUTED).pack()
        level_names = {
            "INFO": ("信息", PRIMARY, SOFT_BLUE),
            "WARNING": ("提醒", WARNING, "#FFF6E8"),
            "ERROR": ("错误", DANGER, "#FFF0F0"),
            "CRITICAL": ("严重", DANGER, "#FFF0F0"),
        }
        for index, (_event_id, timestamp, row_level, message) in enumerate(rows):
            row = tk.Frame(self.log_list.inner, bg=CARD, padx=18, pady=13)
            row.pack(fill="x")
            if index:
                separator = tk.Frame(row, bg=BORDER, height=1)
                separator.place(x=0, y=-13, relwidth=1)
            name, color, badge_bg = level_names.get(row_level, (row_level, MUTED, "#F2F4F7"))
            badge = tk.Label(
                row,
                text=name,
                width=5,
                bg=badge_bg,
                fg=color,
                font=("Microsoft YaHei UI", 8, "bold"),
                pady=4,
            )
            badge.pack(side="left", padx=(0, 13))
            text_label(row, message, 9, wraplength=610, justify="left").pack(
                side="left", fill="x", expand=True
            )
            text_label(row, local_time(timestamp), 8, color=MUTED).pack(side="right", padx=(12, 0))
        self._refresh_recent(rows[:5] if rows else self.database.query(limit=5))

    def _refresh_recent(self, rows):
        if not hasattr(self, "recent_list"):
            return
        for child in self.recent_list.winfo_children():
            child.destroy()
        if not rows:
            text_label(self.recent_list, "暂无活动", 9, color=MUTED).pack(anchor="w", pady=8)
            return
        for _event_id, timestamp, level, message in rows[:5]:
            row = tk.Frame(self.recent_list, bg=CARD)
            row.pack(fill="x", pady=6)
            color = DANGER if level in ("ERROR", "CRITICAL") else WARNING if level == "WARNING" else PRIMARY
            text_label(row, "●", 8, color=color).pack(side="left", padx=(0, 8))
            text_label(row, message, 8, wraplength=380, justify="left").pack(side="left", fill="x", expand=True)
            text_label(row, local_time(timestamp)[5:16], 7, color=MUTED).pack(side="right", padx=(8, 0))

    def run_check(self, login: bool, force: bool = False):
        if self._busy:
            return
        self._busy = True
        self.check_button.configure(state="disabled")
        self.login_button.configure(state="disabled")
        self.status_var.set("正在检查……")

        def worker():
            try:
                result, error = perform_check(
                    login_if_needed=login,
                    monitor_running=True,
                    force_login=force,
                ), None
            except Exception as exc:
                result, error = {}, exc
            self.after(0, lambda: self.check_finished(result, error))

        threading.Thread(target=worker, daemon=True).start()

    def check_finished(self, status: dict, error: Exception | None):
        self._busy = False
        self.check_button.configure(state="normal")
        self.login_button.configure(state="normal")
        if error:
            self.status_var.set("检查失败")
            self.status_hint.configure(text=str(error))
        else:
            self.update_status_display(status)
            self.refresh_accounts()
            self.refresh_logs()

    def poll_status(self):
        try:
            while True:
                self._on_monitor_status(self._status_queue.get_nowait())
        except queue.Empty:
            pass
        self.update_status_display(load_status())
        self.after(1500, self.poll_status)

    def update_status_display(self, status: dict):
        state = status.get("state", "unknown")
        color = STATUS_COLORS.get(state, MUTED)
        state_text = status.get("state_text") or "尚未检查"
        self.status_var.set(state_text)
        self.status_dot.configure(fg=color)
        self.status_hint.configure(text=status.get("network_profile") or "等待所选网络接口连接")
        self.sidebar_status.configure(text=f"●  {state_text}", fg=color)
        monitor_active = self.monitor.is_alive() and self._auto_login_enabled
        self.stat_vars["monitor"].set("已启用" if monitor_active else "已暂停")
        self._update_tray_tooltip(status)
        self.stat_vars["account"].set(status.get("last_success_account") or "—")
        self.stat_vars["check"].set(local_time(status.get("last_check_at", "")))
        for key, value in (
            ("adapter", status.get("adapter_name")),
            ("profile", status.get("network_profile")),
            ("ip", status.get("source_ip")),
            ("error", status.get("last_error")),
        ):
            self.connection_vars[key].set(value or "—")

    def check_updates(self):
        self.update_button.configure(state="disabled")
        self.update_message.configure(text="正在检查更新……", fg=MUTED)
        self.update_progress.configure(mode="indeterminate")
        if not self.update_progress.winfo_ismapped():
            self.update_progress.pack(fill="x", pady=(2, 0))
        self.update_progress.start(10)

        def worker():
            info = check_latest_release()
            self.after(0, lambda: self.finish_update_check(info))

        threading.Thread(target=worker, daemon=True).start()

    def finish_update_check(self, info: UpdateInfo):
        self.update_progress.stop()
        self.update_progress.configure(mode="determinate", value=0)
        self.update_progress.pack_forget()
        self.update_button.configure(state="normal")
        self._update_info = info
        self.render_update_status(info.__dict__)

    def render_update_status(self, data: dict):
        if not data or not hasattr(self, "update_title"):
            return
        latest = data.get("latest_version", APP_VERSION)
        error = data.get("error", "")
        self.update_title.configure(text=f"软件更新 · v{APP_VERSION}")
        if error:
            self.update_message.configure(text=error, fg=DANGER)
            self.install_button.pack_forget()
        elif data.get("available"):
            self.update_message.configure(text=f"发现新版本 {latest}", fg=TEXT)
            self.install_button.configure(state="normal")
            if not self.install_button.winfo_ismapped():
                self.install_button.pack(padx=(8, 0))
        else:
            self.update_message.configure(
                text=f"已是最新版本 · {local_time(data.get('checked_at', ''))}", fg=SUCCESS
            )
            self.install_button.pack_forget()

    def download_and_install(self):
        info = self._update_info
        if not info or not info.available:
            self.check_updates()
            return
        if not messagebox.askyesno(
            "下载更新",
            f"下载版本 {info.latest_version} 并在校验通过后安装吗？",
            parent=self,
        ):
            return
        self.install_button.configure(state="disabled")
        self.update_message.configure(text="正在下载新版……", fg=MUTED)
        self.update_progress.configure(mode="determinate", value=0)
        if not self.update_progress.winfo_ismapped():
            self.update_progress.pack(fill="x", pady=(2, 0))

        def progress(done, total):
            value = done * 100 / total if total else 0
            self.after(0, lambda: self.update_progress.configure(value=value))

        def worker():
            try:
                path, error = download_update(info, progress), None
            except Exception as exc:
                path, error = None, exc
            self.after(0, lambda: self.download_finished(path, error))

        threading.Thread(target=worker, daemon=True).start()

    def download_finished(self, path: Path | None, error: Exception | None):
        if error:
            self.update_progress.pack_forget()
            self.update_message.configure(text=str(error), fg=DANGER)
            self.install_button.configure(state="normal")
            return
        self.update_progress.pack_forget()
        self.update_message.configure(text="校验通过，正在安装更新……", fg=SUCCESS)
        launch_update_installer(path)
        self.quit_app()

    def finish_install(self):
        """Finish installation silently; the live status on the overview is the feedback."""
        try:
            config = load_config()
            if config.get("autostart_enabled", True):
                set_autostart(True)
            self.after(700, lambda: self.update_status_display(load_status()))
        except Exception as exc:
            self.status_var.set("自动登录启动失败")
            self.status_hint.configure(text=str(exc))

    def uninstall_app(self):
        if not messagebox.askyesno("卸载程序", "确定卸载程序吗？", parent=self):
            return
        remove_data = messagebox.askyesno(
            "删除个人数据",
            "是否同时删除账号、设置和日志？选择“否”可在以后继续使用。",
            parent=self,
        )
        try:
            set_autostart(False)
            schedule_self_removal(remove_data)
            self.quit_app()
        except Exception as exc:
            messagebox.showerror("卸载失败", str(exc), parent=self)
