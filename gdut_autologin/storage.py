from __future__ import annotations

from contextlib import closing
import csv
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import shutil
import sqlite3
import threading

from .constants import (
    ACCOUNTS_PATH,
    CONFIG_PATH,
    DATABASE_PATH,
    DEFAULT_CONFIG,
    STATE_PATH,
    STATUS_PATH,
    ensure_data_dir,
)


def atomic_write_json(path: Path, value: object) -> None:
    ensure_data_dir()
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def load_json(path: Path, default: dict | None = None) -> dict:
    if not path.exists():
        return dict(default or {})
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else dict(default or {})
    except (OSError, json.JSONDecodeError):
        return dict(default or {})


def load_config() -> dict:
    config = DEFAULT_CONFIG.copy()
    config.update(load_json(CONFIG_PATH))
    return config


def save_config(config: dict) -> None:
    merged = DEFAULT_CONFIG.copy()
    merged.update(config)
    atomic_write_json(CONFIG_PATH, merged)


def load_state() -> dict:
    return load_json(STATE_PATH)


def save_state(state: dict) -> None:
    atomic_write_json(STATE_PATH, state)


def save_status(status: dict) -> None:
    status["updated_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write_json(STATUS_PATH, status)


def load_status() -> dict:
    return load_json(STATUS_PATH)


def load_accounts() -> list[dict[str, str]]:
    if not ACCOUNTS_PATH.exists():
        return []
    try:
        value = json.loads(ACCOUNTS_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("账号 JSON 文件无法读取或格式无效。") from exc
    if not isinstance(value, list):
        raise RuntimeError("账号 JSON 文件内容无效。")
    accounts = []
    for item in value:
        if isinstance(item, dict) and item.get("account") and item.get("password"):
            accounts.append({"account": str(item["account"]), "password": str(item["password"])})
    return accounts


def save_accounts(accounts: list[dict[str, str]]) -> None:
    atomic_write_json(ACCOUNTS_PATH, accounts)


def export_accounts_file(destination: Path) -> int:
    accounts = load_accounts()
    if not accounts:
        return 0
    exported = {
        "format": "gdut-auto-login-accounts",
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "accounts": accounts,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(exported, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return len(accounts)


def import_accounts_file(source: Path) -> tuple[int, int]:
    try:
        exported = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("账号文件无法读取或 JSON 格式无效。") from exc
    if (
        isinstance(exported, dict)
        and exported.get("format") == "gdut-auto-login-accounts"
        and exported.get("version") == 1
    ):
        imported_value = exported.get("accounts")
    elif isinstance(exported, list):
        imported_value = exported
    else:
        raise RuntimeError("这不是受支持的 GDUT 账号文件。")
    if not isinstance(imported_value, list):
        raise RuntimeError("账号文件内容无效。")
    imported: list[dict[str, str]] = []
    for item in imported_value:
        if not isinstance(item, dict):
            raise RuntimeError("账号文件内容无效。")
        account = str(item.get("account", "")).strip()
        password = str(item.get("password", ""))
        if not account or not password:
            raise RuntimeError("账号文件中存在空账号或空密码。")
        imported.append({"account": account, "password": password})

    accounts = load_accounts()
    positions = {item["account"]: index for index, item in enumerate(accounts)}
    added = 0
    updated_accounts: set[str] = set()
    for item in imported:
        position = positions.get(item["account"])
        if position is None:
            positions[item["account"]] = len(accounts)
            accounts.append(item)
            added += 1
        else:
            accounts[position] = item
            updated_accounts.add(item["account"])
    save_accounts(accounts)
    return added, len(updated_accounts)


def add_or_update_account(account: str, password: str) -> bool:
    accounts = load_accounts()
    for item in accounts:
        if item["account"] == account:
            item["password"] = password
            save_accounts(accounts)
            return False
    accounts.append({"account": account, "password": password})
    save_accounts(accounts)
    return True


def edit_account(original_account: str, account: str, password: str = "") -> bool:
    """Edit an existing account while preserving its position and password when left blank."""
    accounts = load_accounts()
    index = next(
        (position for position, item in enumerate(accounts) if item["account"] == original_account),
        -1,
    )
    if index < 0:
        return False
    if account != original_account and any(item["account"] == account for item in accounts):
        raise ValueError("该账号已经存在。")
    previous = accounts[index]
    accounts[index] = {
        "account": account,
        "password": password or previous["password"],
    }
    save_accounts(accounts)
    state = load_state()
    if state.get("last_success_account") == original_account:
        state["last_success_account"] = account
        save_state(state)
    return True


def remove_account(account: str) -> bool:
    accounts = load_accounts()
    remaining = [item for item in accounts if item["account"] != account]
    if len(remaining) == len(accounts):
        return False
    save_accounts(remaining)
    state = load_state()
    if state.get("last_success_account") == account:
        state.pop("last_success_account", None)
        save_state(state)
    return True


def mask_account(account: str) -> str:
    if len(account) <= 4:
        return "*" * len(account)
    return account[:2] + "*" * (len(account) - 4) + account[-2:]


def ordered_accounts(accounts: list[dict[str, str]]) -> list[dict[str, str]]:
    preferred = str(load_state().get("last_success_account", ""))
    start = next((i for i, item in enumerate(accounts) if item["account"] == preferred), 0)
    return accounts[start:] + accounts[:start]


class EventDatabase:
    def __init__(self, path: Path = DATABASE_PATH):
        ensure_data_dir()
        self.path = path
        self._lock = threading.Lock()
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def initialize(self) -> None:
        with closing(self.connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        level TEXT NOT NULL,
                        message TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC)"
                )

    def add(self, level: str, message: str) -> None:
        with self._lock, closing(self.connect()) as connection:
            with connection:
                connection.execute(
                    "INSERT INTO events(timestamp, level, message) VALUES (?, ?, ?)",
                    (datetime.now(timezone.utc).isoformat(), level, message),
                )

    def query(self, days: int = 0, level: str = "", limit: int = 2000) -> list[tuple]:
        clauses = []
        parameters: list[object] = []
        if days > 0:
            clauses.append("timestamp >= ?")
            parameters.append((datetime.now(timezone.utc) - timedelta(days=days)).isoformat())
        if level:
            clauses.append("level = ?")
            parameters.append(level)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        parameters.append(limit)
        with closing(self.connect()) as connection:
            return connection.execute(
                f"SELECT id, timestamp, level, message FROM events{where} ORDER BY id DESC LIMIT ?",
                parameters,
            ).fetchall()

    def clear(self) -> None:
        with self._lock, closing(self.connect()) as connection:
            with connection:
                connection.execute("DELETE FROM events")
        self._checkpoint()

    def export_csv(self, destination: Path, days: int = 0, level: str = "") -> int:
        rows = self.query(days=days, level=level, limit=1_000_000)
        with destination.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["时间（UTC）", "级别", "消息"])
            for _event_id, timestamp, row_level, message in reversed(rows):
                writer.writerow([timestamp, row_level, message])
        return len(rows)

    def maintain(self, max_mb: int, retention_days: int) -> None:
        with self._lock, closing(self.connect()) as connection:
            if retention_days > 0:
                with connection:
                    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
                    connection.execute("DELETE FROM events WHERE timestamp < ?", (cutoff,))
        self._checkpoint()
        maximum = max(1, int(max_mb)) * 1024 * 1024
        for _attempt in range(6):
            if self._total_size() <= maximum:
                break
            with self._lock, closing(self.connect()) as connection:
                count = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                if count <= 100:
                    break
                with connection:
                    connection.execute(
                        "DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY id ASC LIMIT ?)",
                        (max(100, count // 5),),
                    )
            self._vacuum()

    def _total_size(self) -> int:
        return sum(
            path.stat().st_size
            for path in (self.path, Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm"))
            if path.exists()
        )

    def _checkpoint(self) -> None:
        with closing(self.connect()) as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def _vacuum(self) -> None:
        self._checkpoint()
        with closing(sqlite3.connect(self.path, timeout=10, isolation_level=None)) as connection:
            connection.execute("VACUUM")


class DatabaseLogHandler(logging.Handler):
    def __init__(self, database: EventDatabase):
        super().__init__()
        self.database = database

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.database.add(record.levelname, self.format(record))
        except Exception:
            self.handleError(record)


def build_logger(name: str = "gdut-autologin") -> tuple[logging.Logger, EventDatabase]:
    database = EventDatabase()
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = DatabaseLogHandler(database)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger, database


def migrate_legacy_data(source_dir: Path) -> list[str]:
    """Import local data from the earlier script layout without bundling it."""
    ensure_data_dir()
    migrated: list[str] = []
    mappings = {
        "gdut_config.json": CONFIG_PATH,
        "gdut_state.json": STATE_PATH,
    }
    for source_name, destination in mappings.items():
        source = source_dir / source_name
        if source.exists() and not destination.exists():
            shutil.copy2(source, destination)
            migrated.append(source_name)
    legacy_log = source_dir / "login_log.txt"
    if legacy_log.exists():
        database = EventDatabase()
        marker = load_state().get("legacy_log_imported")
        if not marker:
            for line in legacy_log.read_text(encoding="utf-8-sig", errors="replace").splitlines():
                if line.strip():
                    database.add("INFO", f"旧版日志：{line.strip()}")
            state = load_state()
            state["legacy_log_imported"] = True
            save_state(state)
            migrated.append("login_log.txt")
    return migrated
