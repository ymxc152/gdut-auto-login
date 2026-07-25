from __future__ import annotations

from datetime import datetime, timezone
import os
import time

from .constants import MUTEX_MONITOR, PID_PATH, UPDATE_CHECK_INTERVAL_SECONDS
from .network import adapter_source_ip, probe_network, select_adapter, try_authorized_accounts
from .storage import (
    build_logger,
    load_config,
    load_state,
    mask_account,
    save_status,
)
from .windows import NamedMutex, action_mutex, show_notification
from .updates import check_latest_release


STATUS_TEXT = {
    "online": "网络正常",
    "portal_required": "需要校园网认证",
    "network_error": "无法访问网络",
    "unexpected_response": "网络响应异常",
    "adapter_missing": "等待所选网络接口连接",
    "adapter_down": "等待所选网络接口连接",
    "no_ip": "等待所选网络接口获取 10 网段地址",
    "login_failed": "自动登录失败",
    "busy": "正在执行其他网络操作",
}

WAITING_STATES = frozenset(("adapter_missing", "adapter_down", "no_ip"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def base_status() -> dict:
    state = load_state()
    preferred = str(state.get("last_success_account", ""))
    return {
        "monitor_running": False,
        "state": "unknown",
        "state_text": "尚未检查",
        "adapter_name": "",
        "adapter_mac": "",
        "network_profile": "",
        "source_ip": "",
        "last_check_at": "",
        "last_success_account": mask_account(preferred) if preferred else "",
        "last_error": "",
    }


def perform_check(login_if_needed: bool = True, monitor_running: bool = False) -> dict:
    logger, _database = build_logger("gdut-action")
    with action_mutex(timeout_ms=1000) as lock:
        if not lock.acquired:
            status = base_status()
            status.update(
                {
                    "monitor_running": monitor_running,
                    "state": "busy",
                    "state_text": STATUS_TEXT["busy"],
                }
            )
            save_status(status)
            return status

        config = load_config()
        status = base_status()
        status["monitor_running"] = monitor_running
        status["last_check_at"] = utc_now()
        adapter = select_adapter(config)
        if adapter is None:
            status.update({"state": "adapter_missing", "state_text": STATUS_TEXT["adapter_missing"]})
            save_status(status)
            return status
        status.update({"adapter_name": adapter.name, "adapter_mac": adapter.mac})
        status["network_profile"] = ", ".join(adapter.profile_names)
        if adapter.status != "已连接":
            status.update({"state": "adapter_down", "state_text": STATUS_TEXT["adapter_down"]})
            save_status(status)
            return status
        source_ip = adapter_source_ip(adapter, config)
        status["source_ip"] = source_ip
        if not source_ip:
            status.update({"state": "no_ip", "state_text": STATUS_TEXT["no_ip"]})
            save_status(status)
            return status

        online, reason = probe_network(source_ip)
        if online:
            status.update({"state": "online", "state_text": STATUS_TEXT["online"]})
            save_status(status)
            return status
        status.update({"state": reason, "state_text": STATUS_TEXT.get(reason, reason)})
        if not login_if_needed:
            save_status(status)
            return status

        logger.warning("GDUT 网卡 %s（%s）需要重新认证", adapter.name, source_ip)
        success, masked = try_authorized_accounts(source_ip, config, logger)
        if success:
            status.update(
                {
                    "state": "online",
                    "state_text": STATUS_TEXT["online"],
                    "last_success_account": masked,
                    "last_error": "",
                }
            )
        else:
            status.update(
                {
                    "state": "login_failed",
                    "state_text": STATUS_TEXT["login_failed"],
                    "last_error": "所有已配置授权账号均无法恢复网络",
                }
            )
            logger.critical("所有已配置授权账号均失败，网络仍不可用")
        save_status(status)
        return status


def run_monitor() -> int:
    logger, database = build_logger("gdut-monitor")
    with NamedMutex(MUTEX_MONITOR, timeout_ms=0) as instance:
        if not instance.acquired:
            return 0
        PID_PATH.parent.mkdir(parents=True, exist_ok=True)
        PID_PATH.write_text(str(os.getpid()), encoding="ascii")
        logger.info("后台网络监控已启动")
        last_notification = 0.0
        last_update_check = 0.0
        notified_update_version = ""
        maintenance_counter = 0
        try:
            while True:
                config = load_config()
                status = perform_check(login_if_needed=True, monitor_running=True)
                now = time.monotonic()
                if (
                    status.get("state") not in WAITING_STATES
                    and config.get("auto_check_updates", True)
                    and now - last_update_check >= UPDATE_CHECK_INTERVAL_SECONDS
                ):
                    last_update_check = now
                    update = check_latest_release()
                    if (
                        update.available
                        and not update.error
                        and update.latest_version != notified_update_version
                        and config.get("notifications_enabled", True)
                    ):
                        notified_update_version = update.latest_version
                        show_notification(
                            "GDUT 自动登录有新版本",
                            f"版本 {update.latest_version} 已发布。打开管理界面确认下载并安装。",
                        )
                if (
                    status.get("state") == "login_failed"
                    and config.get("notifications_enabled", True)
                    and now - last_notification >= int(config.get("notification_cooldown_seconds", 900))
                ):
                    last_notification = now
                    show_notification(
                        "GDUT 校园网登录失败",
                        "所有已配置授权账号均无法恢复网络，请检查账号状态或手动登录。",
                    )
                maintenance_counter += 1
                if maintenance_counter >= 20:
                    maintenance_counter = 0
                    database.maintain(
                        int(config.get("log_max_mb", 20)),
                        int(config.get("log_retention_days", 0)),
                    )
                state = status.get("state")
                if state == "online":
                    sleep_seconds = int(config.get("check_interval_seconds", 30))
                elif state in WAITING_STATES:
                    sleep_seconds = int(config.get("retry_interval_seconds", 15))
                else:
                    sleep_seconds = int(config.get("login_cooldown_seconds", 60))
                time.sleep(max(5, sleep_seconds))
        except Exception as exc:
            logger.exception("后台监控异常退出：%s", exc)
            return 1
        finally:
            try:
                PID_PATH.unlink(missing_ok=True)
            except OSError:
                pass
            status = base_status()
            status.update({"monitor_running": False, "state_text": "后台监控已停止"})
            save_status(status)
