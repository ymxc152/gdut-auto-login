from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

from .constants import APP_VERSION, EXECUTABLE, IS_FROZEN, INSTALLED_EXE, ensure_data_dir
from .gui import GDUTApp
from .network import list_adapters
from .service import perform_check
from .storage import EventDatabase, load_accounts, load_config, migrate_legacy_data
from .windows import acquire_single_instance, ensure_autostart_upgraded, request_show_existing, self_install_if_needed
from .updates import apply_update


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=not IS_FROZEN)
    parser.add_argument("--hidden", action="store_true", help="start minimized to the tray")
    parser.add_argument("--monitor", action="store_true", help="legacy alias for --hidden")
    parser.add_argument("--first-run", action="store_true")
    parser.add_argument("--migrate-from", type=Path)
    parser.add_argument("--check-once", action="store_true")
    parser.add_argument("--self-test", type=Path)
    parser.add_argument("--no-self-install", action="store_true")
    parser.add_argument("--apply-update", action="store_true")
    parser.add_argument("--post-update", action="store_true")
    parser.add_argument("--target", type=Path)
    parser.add_argument("--wait-pid", type=int, default=0)
    parser.add_argument("--health-file", type=Path)
    return parser.parse_args()


def self_test(destination: Path) -> int:
    try:
        ensure_data_dir()
        database = EventDatabase()
        result = {
            "ok": True,
            "version": APP_VERSION,
            "frozen": IS_FROZEN,
            "executable": str(EXECUTABLE),
            "adapter_count": len(list_adapters()),
            "account_count": len(load_accounts()),
            "database": str(database.path),
            "config_schema": load_config().get("schema_version"),
        }
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1


def main() -> int:
    args = parse_args()
    ensure_data_dir()
    if args.apply_update:
        if not args.target or not args.wait_pid or not args.health_file:
            return 2
        return apply_update(args.target, args.wait_pid, args.health_file)
    if args.migrate_from:
        migrate_legacy_data(args.migrate_from.resolve())
    if args.self_test:
        return self_test(args.self_test.resolve())
    if args.check_once:
        perform_check(login_if_needed=True, monitor_running=False)
        return 0
    if IS_FROZEN and not args.no_self_install and not args.first_run:
        if self_install_if_needed():
            return 0

    # Single instance: become primary or raise the existing window instead.
    lock = acquire_single_instance()
    for _attempt in range(3):
        if lock and lock.acquired:
            break
        request_show_existing()
        time.sleep(1.5)
        lock = acquire_single_instance()
    if not (lock and lock.acquired):
        return 0

    if lock and (not IS_FROZEN or EXECUTABLE == INSTALLED_EXE):
        ensure_autostart_upgraded()
    app = GDUTApp(first_run=args.first_run, start_hidden=args.hidden or args.monitor)
    if args.post_update and args.health_file:
        args.health_file.parent.mkdir(parents=True, exist_ok=True)
        args.health_file.write_text(
            json.dumps({"ok": True, "version": APP_VERSION}), encoding="utf-8"
        )
    try:
        app.mainloop()
    finally:
        lock.__exit__(None, None, None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
