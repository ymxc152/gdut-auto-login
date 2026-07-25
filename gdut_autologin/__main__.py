from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .constants import APP_VERSION, EXECUTABLE, IS_FROZEN, ensure_data_dir
from .gui import GDUTApp
from .network import list_adapters
from .service import perform_check, run_monitor
from .storage import EventDatabase, load_accounts, load_config, migrate_legacy_data
from .windows import self_install_if_needed
from .updates import apply_update


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=not IS_FROZEN)
    parser.add_argument("--monitor", action="store_true")
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
    if args.monitor:
        return run_monitor()
    if args.check_once:
        perform_check(login_if_needed=True, monitor_running=False)
        return 0
    if IS_FROZEN and not args.no_self_install and not args.first_run:
        if self_install_if_needed():
            return 0
    app = GDUTApp(first_run=args.first_run)
    if args.post_update and args.health_file:
        args.health_file.parent.mkdir(parents=True, exist_ok=True)
        args.health_file.write_text(
            json.dumps({"ok": True, "version": APP_VERSION}), encoding="utf-8"
        )
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
