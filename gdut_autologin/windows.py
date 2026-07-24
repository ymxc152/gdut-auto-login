from __future__ import annotations

import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from .constants import (
    EXECUTABLE,
    INSTALL_DIR,
    INSTALLED_EXE,
    IS_FROZEN,
    MUTEX_ACTION,
    START_MENU_SHORTCUT,
    TASK_NAME,
)


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0)


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


def current_launch_command(mode: str = "--monitor") -> tuple[str, str]:
    if IS_FROZEN:
        return str(EXECUTABLE), mode
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return str(pythonw if pythonw.exists() else sys.executable), f'"{EXECUTABLE}" {mode}'


def current_launch_argv(mode: str = "--monitor") -> list[str]:
    executable, _arguments = current_launch_command(mode)
    if IS_FROZEN:
        return [executable, mode]
    return [executable, str(EXECUTABLE), mode]


def set_autostart(enabled: bool) -> None:
    if enabled:
        executable, arguments = current_launch_command("--monitor")
        environment = os.environ.copy()
        environment["GDUT_TASK_EXECUTABLE"] = executable
        environment["GDUT_TASK_ARGUMENTS"] = arguments
        environment["GDUT_TASK_NAME"] = TASK_NAME
        script = r"""
$action = New-ScheduledTaskAction -Execute $env:GDUT_TASK_EXECUTABLE -Argument $env:GDUT_TASK_ARGUMENTS
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -Hidden -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $env:GDUT_TASK_NAME -Action $action -Trigger $trigger -Settings $settings -Description 'GDUT wired network silent monitor.' -Force | Out-Null
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
                f"Stop-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue; "
                f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false -ErrorAction SilentlyContinue",
            ]
        )


def scheduled_task_running() -> bool:
    result = hidden_run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"$t=Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue; if($t){{$t.State}}",
        ]
    )
    return result.stdout.strip().lower() == "running"


def start_monitor() -> None:
    result = hidden_run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"Start-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue",
        ]
    )
    time.sleep(0.5)
    if not scheduled_task_running():
        hidden_popen(current_launch_argv("--monitor"), creationflags=DETACHED_PROCESS)


def stop_monitor() -> None:
    hidden_run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"Stop-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue",
        ]
    )
    from .constants import PID_PATH

    if PID_PATH.exists():
        try:
            pid = int(PID_PATH.read_text(encoding="ascii").strip())
            hidden_run(["taskkill.exe", "/PID", str(pid), "/F"], timeout=10)
        except (OSError, ValueError):
            pass


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


def action_mutex(timeout_ms: int = 0) -> NamedMutex:
    return NamedMutex(MUTEX_ACTION, timeout_ms)


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


def self_install_if_needed() -> bool:
    """Copy a downloaded one-file executable to a stable per-user location."""
    if not IS_FROZEN or EXECUTABLE == INSTALLED_EXE:
        return False
    stop_monitor()
    time.sleep(1)
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
