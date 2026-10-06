from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

import psutil

from .constants import (
    APP_NAME,
    EVENT_SHOW_WINDOW,
    EXECUTABLE,
    INSTALL_DIR,
    INSTALLED_EXE,
    IS_FROZEN,
    MUTEX_ACTION,
    MUTEX_APP,
    START_MENU_SHORTCUT,
    TASK_NAME,
)


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0)

WM_APP = 0x8000
WM_TRAYICON = WM_APP + 1
WM_TRAY_UPDATE = WM_APP + 2
WM_CLOSE = 0x0010
WM_NULL = 0x0000
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_LBUTTONDBLCLK = 0x0203
WM_USER = 0x0400

NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIM_SETVERSION = 4
NIF_MESSAGE = 0x01
NIF_ICON = 0x02
NIF_TIP = 0x04
NIF_INFO = 0x10
NIIF_INFO = 0x01

TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
TPM_NONOTIFY = 0x0080

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010

_user32 = ctypes.windll.user32
_user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.DefWindowProcW.restype = ctypes.c_longlong


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_ubyte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.WINFUNCTYPE(
            ctypes.c_longlong, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


def _tray_icon_handle() -> int:
    """Return a small HICON for the tray; prefer the executable's own icon."""
    if IS_FROZEN:
        hicon = wintypes.HICON()
        large = wintypes.HICON()
        count = ctypes.windll.shell32.ExtractIconExW(str(EXECUTABLE), 0, ctypes.byref(large), ctypes.byref(hicon), 1)
        if count > 0 and hicon:
            return hicon.value
        if count > 0 and large:
            return large.value
    assets = Path(__file__).resolve().parent.parent / "assets" / "app.ico"
    handle = ctypes.windll.user32.LoadImageW(
        None, str(assets), IMAGE_ICON, 16, 16, LR_LOADFROMFILE
    )
    if handle:
        return handle
    return ctypes.windll.user32.LoadIconW(None, 32512)  # IDI_APPLICATION fallback


def hidden_popen(arguments: list[str], **kwargs) -> subprocess.Popen:
    flags = kwargs.pop("creationflags", 0) | CREATE_NO_WINDOW
    return subprocess.Popen(arguments, creationflags=flags, **kwargs)


def hidden_run(arguments: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        arguments,
        creationflags=CREATE_NO_WINDOW,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def current_launch_command(mode: str = "--hidden") -> tuple[str, str]:
    if IS_FROZEN:
        return str(EXECUTABLE), mode
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return str(pythonw if pythonw.exists() else sys.executable), f'"{EXECUTABLE}" {mode}'


def current_launch_argv(mode: str = "--hidden") -> list[str]:
    executable, _arguments = current_launch_command(mode)
    if IS_FROZEN:
        return [executable, mode]
    return [executable, str(EXECUTABLE), mode]


def set_autostart(enabled: bool) -> None:
    """Register or remove the logon scheduled task that starts the app hidden."""
    if enabled:
        executable, arguments = current_launch_command("--hidden")
        environment = os.environ.copy()
        environment["GDUT_TASK_EXECUTABLE"] = executable
        environment["GDUT_TASK_ARGUMENTS"] = arguments
        environment["GDUT_TASK_NAME"] = TASK_NAME
        script = r"""
$action = New-ScheduledTaskAction -Execute $env:GDUT_TASK_EXECUTABLE -Argument $env:GDUT_TASK_ARGUMENTS
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -Hidden -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $env:GDUT_TASK_NAME -Action $action -Trigger $trigger -Settings $settings -Description 'GDUT auto login, starts hidden in tray.' -Force | Out-Null
"""
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            env=environment,
            creationflags=CREATE_NO_WINDOW,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "创建开机自启动任务失败")
    else:
        hidden_run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false -ErrorAction SilentlyContinue",
            ]
        )


def scheduled_task_info() -> tuple[bool, str]:
    """Return (task_exists, argument string) for the autostart task."""
    result = hidden_run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"$t=Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue; "
            "if($t){Write-Output ('EXISTS|' + (($t.Actions | ForEach-Object { $_.Arguments }) -join ' '))}",
        ]
    )
    output = result.stdout.strip()
    if output.startswith("EXISTS|"):
        return True, output[len("EXISTS|"):]
    return False, ""


def ensure_autostart_upgraded() -> None:
    """Re-register legacy autostart tasks (no args or --monitor) to --hidden."""
    exists, arguments = scheduled_task_info()
    if exists and "--hidden" not in arguments:
        set_autostart(True)


def show_notification(title: str, message: str) -> None:
    environment = os.environ.copy()
    environment["GDUT_TOAST_TITLE"] = title
    environment["GDUT_TOAST_MESSAGE"] = message
    script = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$nodes = $xml.GetElementsByTagName('text')
$nodes.Item(0).AppendChild($xml.CreateTextNode($env:GDUT_TOAST_TITLE)) | Out-Null
$nodes.Item(1).AppendChild($xml.CreateTextNode($env:GDUT_TOAST_MESSAGE)) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('GDUT Auto Login').Show($toast)
"""
    hidden_popen(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


class NamedMutex:
    def __init__(self, name: str, timeout_ms: int = 0):
        self.name = name
        self.timeout_ms = timeout_ms
        self.handle = None
        self.acquired = False

    def __enter__(self) -> "NamedMutex":
        self.handle = ctypes.windll.kernel32.CreateMutexW(None, False, self.name)
        if not self.handle:
            raise ctypes.WinError()
        result = ctypes.windll.kernel32.WaitForSingleObject(self.handle, self.timeout_ms)
        self.acquired = result in (0, 0x80)
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self.handle:
            if self.acquired:
                ctypes.windll.kernel32.ReleaseMutex(self.handle)
            ctypes.windll.kernel32.CloseHandle(self.handle)


def acquire_single_instance() -> NamedMutex:
    """Try to become the only running app instance."""
    lock = NamedMutex(MUTEX_APP, timeout_ms=0)
    lock.__enter__()
    if not lock.acquired:
        lock.__exit__(None, None, None)
        return None
    return lock


def request_show_existing() -> bool:
    """Ask a running instance to show its window. Returns True if signaled."""
    EVENT_MODIFY_STATE = 0x0002
    handle = ctypes.windll.kernel32.OpenEventW(EVENT_MODIFY_STATE, False, EVENT_SHOW_WINDOW)
    if not handle:
        return False
    ctypes.windll.kernel32.SetEvent(handle)
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


class ShowWindowWatcher:
    """Watch a named auto-reset event so a second launch can raise our window."""

    def __init__(self, on_show):
        self.on_show = on_show
        self.handle = ctypes.windll.kernel32.CreateEventW(None, False, False, EVENT_SHOW_WINDOW)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if not self.handle:
            return
        self._thread = threading.Thread(target=self._run, name="gdut-show-watcher", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            result = ctypes.windll.kernel32.WaitForSingleObject(self.handle, 1000)
            if result == 0:
                try:
                    self.on_show()
                except Exception:
                    pass

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self.handle:
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None


class TrayIcon:
    """System tray icon without third-party dependencies (pure Win32 via ctypes)."""

    def __init__(self, tooltip: str, on_activate, get_menu_items, on_command):
        self.tooltip = tooltip[:127]
        self._pending: list = []
        self.on_activate = on_activate
        self.get_menu_items = get_menu_items  # callable -> list[tuple[id, label, kind]]
        self.on_command = on_command
        self._hicon = 0
        self._hwnd = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._menu_items: list[tuple[int, str, str]] = []
        self._next_menu_id = 1000
        self._tip_lock = threading.Lock()

    # -- public API (call from any thread) --------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="gdut-tray", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3)

    def stop(self) -> None:
        self._stopped.set()
        if self._hwnd:
            ctypes.windll.user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
        if self._thread:
            self._thread.join(timeout=3)

    def set_tooltip(self, text: str) -> None:
        with self._tip_lock:
            self.tooltip = text[:127]
        if self._hwnd:
            ctypes.windll.user32.PostMessageW(self._hwnd, WM_TRAY_UPDATE, 0, 0)

    def show_balloon(self, title: str, message: str) -> None:
        def _show():
            nid = self._base_nid()
            nid.uFlags = NIF_INFO
            nid.szInfo = message[:255]
            nid.szInfoTitle = title[:63]
            nid.dwInfoFlags = NIIF_INFO
            nid.uTimeout = 5000
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

        self._post_to_thread(_show)

    # -- internals ---------------------------------------------------------
    def _post_to_thread(self, action) -> None:
        if self._hwnd:
            self._pending.append(action)
            ctypes.windll.user32.PostMessageW(self._hwnd, WM_TRAY_UPDATE, 0, 0)

    def _base_nid(self) -> NOTIFYICONDATAW:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = self._hicon
        return nid

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        shell32 = ctypes.windll.shell32

        self._hicon = _tray_icon_handle()

        wnd_proc = ctypes.WINFUNCTYPE(
            ctypes.c_longlong, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )(self._wnd_proc)

        class_name = "GDUTAutoLoginTrayWnd"
        hinstance = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = wnd_proc
        wc.lpszClassName = class_name
        wc.hInstance = hinstance
        if not user32.RegisterClassW(ctypes.byref(wc)):
            self._ready.set()
            return

        self._hwnd = user32.CreateWindowExW(
            0, class_name, APP_NAME, 0, 0, 0, 0, 0, None, None, hinstance, None
        )
        if not self._hwnd:
            self._ready.set()
            return

        nid = self._base_nid()
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.szTip = self.tooltip
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(nid))

        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_TRAY_UPDATE:
                while self._pending:
                    try:
                        self._pending.pop(0)()
                    except Exception:
                        pass
                with self._tip_lock:
                    nid2 = self._base_nid()
                    nid2.uFlags = NIF_TIP
                    nid2.szTip = self.tooltip
                    shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid2))
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        user32.DestroyWindow(self._hwnd)
        user32.UnregisterClassW(class_name, hinstance)

    def _wnd_proc(self, hwnd, message, wparam, lparam):
        user32 = ctypes.windll.user32
        if message == WM_TRAYICON:
            event = lparam & 0xFFFF
            if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK) and self.on_activate:
                try:
                    self.on_activate()
                except Exception:
                    pass
            elif event == WM_RBUTTONUP:
                self._show_menu(hwnd)
            return 0
        if message == WM_CLOSE:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _show_menu(self, hwnd) -> None:
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        self._menu_items = []
        try:
            items = self.get_menu_items() or []
        except Exception:
            items = []
        for label, kind in items:
            if kind == "sep":
                user32.AppendMenuW(menu, 0x0800, 0, None)  # MF_SEPARATOR
                continue
            menu_id = self._next_menu_id
            self._next_menu_id += 1
            self._menu_items.append((menu_id, label, kind))
            text = label
            flags = 0x00000000 if kind == "check" else 0x00000000  # MF_STRING = 0
            user32.AppendMenuW(menu, flags, menu_id, text)
            if kind == "check":
                user32.CheckMenuItem(menu, menu_id, 0x00000008)  # MF_CHECKED

        user32.SetForegroundWindow(hwnd)
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        chosen = user32.TrackPopupMenu(
            menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
            point.x, point.y, 0, hwnd, None,
        )
        user32.PostMessageW(hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        if chosen:
            for menu_id, label, kind in self._menu_items:
                if menu_id == chosen and self.on_command:
                    try:
                        self.on_command(label, kind)
                    except Exception:
                        pass
                    break


def action_mutex(timeout_ms: int = 0) -> NamedMutex:
    return NamedMutex(MUTEX_ACTION, timeout_ms=0)


def create_start_menu_shortcut() -> None:
    START_MENU_SHORTCUT.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["GDUT_SHORTCUT"] = str(START_MENU_SHORTCUT)
    environment["GDUT_EXE"] = str(INSTALLED_EXE)
    script = r"""
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($env:GDUT_SHORTCUT)
$shortcut.TargetPath = $env:GDUT_EXE
$shortcut.WorkingDirectory = Split-Path -Parent $env:GDUT_EXE
$shortcut.Description = 'GDUT 校园网自动登录'
$shortcut.Save()
"""
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        env=environment,
        creationflags=CREATE_NO_WINDOW,
        capture_output=True,
        timeout=20,
    )


def terminate_running_installed() -> int:
    """Stop any running instance of the installed exe (older version upgrade)."""
    if not IS_FROZEN:
        return 0
    try:
        installed = str(INSTALLED_EXE.resolve()).casefold()
    except OSError:
        return 0
    stopped = 0
    for process in psutil.process_iter(["pid", "exe"]):
        try:
            exe = str(process.info.get("exe") or "").casefold()
            if exe == installed and process.pid != os.getpid():
                process.terminate()
                stopped += 1
        except (psutil.Error, OSError, ValueError):
            continue
    if stopped:
        time.sleep(1.5)
    return stopped


def self_install_if_needed() -> bool:
    """Copy a downloaded one-file executable to a stable per-user location."""
    if not IS_FROZEN or EXECUTABLE == INSTALLED_EXE:
        return False
    terminate_running_installed()
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    temporary = INSTALLED_EXE.with_suffix(".new.exe")
    shutil.copy2(EXECUTABLE, temporary)
    for attempt in range(10):
        try:
            temporary.replace(INSTALLED_EXE)
            break
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.5)
    create_start_menu_shortcut()
    hidden_popen(
        [str(INSTALLED_EXE), "--first-run", "--migrate-from", str(EXECUTABLE.parent)],
        creationflags=DETACHED_PROCESS,
    )
    return True


def schedule_self_removal(remove_data: bool) -> None:
    from .constants import DATA_DIR

    environment = os.environ.copy()
    environment["GDUT_INSTALL_DIR"] = str(INSTALL_DIR)
    environment["GDUT_DATA_DIR"] = str(DATA_DIR)
    environment["GDUT_SHORTCUT"] = str(START_MENU_SHORTCUT)
    environment["GDUT_REMOVE_DATA"] = "1" if remove_data else "0"
    script = r"""
Start-Sleep -Seconds 2
Remove-Item -LiteralPath $env:GDUT_SHORTCUT -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $env:GDUT_INSTALL_DIR -Recurse -Force -ErrorAction SilentlyContinue
if($env:GDUT_REMOVE_DATA -eq '1') {
    Remove-Item -LiteralPath $env:GDUT_DATA_DIR -Recurse -Force -ErrorAction SilentlyContinue
}
"""
    hidden_popen(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
