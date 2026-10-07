from __future__ import annotations

import os
from pathlib import Path
import sys


APP_NAME = "GDUT 校园网自动登录"
APP_ID = "GDUTAutoLogin"
APP_VERSION = "1.2.3"
TASK_NAME = "GDUT Auto Login"
MUTEX_APP = "Local\\GDUT_AutoLogin_App_V1"
MUTEX_ACTION = "Local\\GDUT_AutoLogin_Action_V2"
EVENT_SHOW_WINDOW = "Local\\GDUT_AutoLogin_Show_V1"

IS_FROZEN = bool(getattr(sys, "frozen", False))
EXECUTABLE = Path(sys.executable).resolve() if IS_FROZEN else Path(sys.argv[0]).resolve()
LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
DATA_DIR = Path(os.environ.get("GDUT_AUTOLOGIN_DATA_DIR", LOCAL_APPDATA / APP_ID))
INSTALL_DIR = LOCAL_APPDATA / "Programs" / APP_ID
INSTALLED_EXE = INSTALL_DIR / "GDUTAutoLogin.exe"
START_MENU_DIR = Path(os.environ.get("APPDATA", DATA_DIR)) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
START_MENU_SHORTCUT = START_MENU_DIR / "GDUT 校园网自动登录.lnk"

CONFIG_PATH = DATA_DIR / "config.json"
ACCOUNTS_PATH = DATA_DIR / "accounts.json"
STATE_PATH = DATA_DIR / "state.json"
STATUS_PATH = DATA_DIR / "status.json"
DATABASE_PATH = DATA_DIR / "events.db"
UPDATE_DIR = DATA_DIR / "updates"
UPDATE_STATUS_PATH = UPDATE_DIR / "update-status.json"
GITHUB_REPO = "ymxc152/gdut-auto-login"
GITHUB_RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
UPDATE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60

DEFAULT_CONFIG = {
    "schema_version": 1,
    "adapter_name": "",
    "adapter_mac": "",
    "ip_prefixes": ["10."],
    "portal_host": "10.0.3.2",
    "portal_port": 801,
    "wlan_ac_ip": "172.16.254.2",
    "check_interval_seconds": 30,
    "retry_interval_seconds": 15,
    "login_cooldown_seconds": 60,
    "account_attempt_delay_seconds": 2,
    "notification_cooldown_seconds": 900,
    "notifications_enabled": True,
    "autostart_enabled": True,
    "auto_login_enabled": True,
    "close_to_tray_hinted": False,
    "log_max_mb": 20,
    "log_retention_days": 0,
    "auto_check_updates": True,
}


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

