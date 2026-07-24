from __future__ import annotations

from dataclasses import asdict, dataclass, field
import http.client
import json
import re
import socket
import subprocess
import time
from urllib.parse import urlencode

import psutil

from .storage import load_accounts, load_state, mask_account, ordered_accounts, save_state


@dataclass
class AdapterInfo:
    name: str
    mac: str
    status: str
    ipv4: list[str]
    physical: bool
    interface_index: int = 0
    description: str = ""
    profile_names: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_mac(value: str) -> str:
    return re.sub(r"[^0-9A-F]", "", str(value).upper())


def _windows_network_metadata() -> tuple[dict[str, dict], dict[int, list[str]]]:
    """Map Windows adapter MACs and active network profiles to interface indexes."""
    script = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[pscustomobject]@{
    adapters = @(Get-NetAdapter -ErrorAction SilentlyContinue | Select-Object Name, ifIndex, MacAddress, InterfaceDescription, HardwareInterface)
    profiles = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue | Select-Object Name, InterfaceIndex)
} | ConvertTo-Json -Depth 4 -Compress
"""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            capture_output=True,
            timeout=8,
        )
        if result.returncode != 0 or not result.stdout:
            return {}, {}
        payload = json.loads(result.stdout.decode("utf-8-sig"))
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError, json.JSONDecodeError):
        return {}, {}

    adapter_map: dict[str, dict] = {}
    for item in payload.get("adapters") or []:
        mac = normalize_mac(item.get("MacAddress", ""))
        if mac:
            adapter_map[mac] = item
    profile_map: dict[int, list[str]] = {}
    for item in payload.get("profiles") or []:
        try:
            index = int(item.get("InterfaceIndex", 0))
        except (TypeError, ValueError):
            continue
        name = str(item.get("Name", "")).strip()
        if index and name:
            profile_map.setdefault(index, []).append(name)
    return adapter_map, profile_map


def list_adapters() -> list[AdapterInfo]:
    addresses = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    metadata_by_mac, profiles_by_index = _windows_network_metadata()
    virtual_words = (
        "vmware",
        "virtualbox",
        "vethernet",
        "hyper-v",
        "loopback",
        "bluetooth",
        "虚拟",
        "蓝牙",
    )
    adapters: list[AdapterInfo] = []
    for name, interface_addresses in addresses.items():
        ipv4 = [item.address for item in interface_addresses if item.family == socket.AF_INET]
        mac = ""
        for item in interface_addresses:
            if item.family == getattr(psutil, "AF_LINK", object()):
                mac = item.address
                break
        metadata = metadata_by_mac.get(normalize_mac(mac), {})
        interface_index = int(metadata.get("ifIndex") or 0)
        lowered = name.lower()
        physical = bool(metadata.get("HardwareInterface")) if metadata else not any(
            word in lowered for word in virtual_words
        )
        is_up = bool(stats.get(name) and stats[name].isup)
        adapters.append(
            AdapterInfo(
                name=name,
                mac=mac,
                status="已连接" if is_up else "已断开",
                ipv4=ipv4,
                physical=physical,
                interface_index=interface_index,
                description=str(metadata.get("InterfaceDescription") or ""),
                profile_names=profiles_by_index.get(interface_index, []),
            )
        )
    return sorted(adapters, key=lambda item: (not item.physical, item.name.lower()))


def adapter_matches_keyword(adapter: AdapterInfo, keyword: str) -> bool:
    folded = keyword.strip().casefold()
    if not folded:
        return False
    values = [adapter.name, *adapter.profile_names]
    return any(folded in str(value).casefold() for value in values)


def select_adapter(config: dict) -> AdapterInfo | None:
    adapters = list_adapters()
    keyword = str(config.get("network_keyword", "gdut")) or "gdut"
    matching = [item for item in adapters if adapter_matches_keyword(item, keyword)]
    if not matching:
        return None
    configured_mac = normalize_mac(config.get("adapter_mac", ""))
    configured_name = str(config.get("adapter_name", "")).strip()
    if configured_mac:
        selected = next((item for item in matching if normalize_mac(item.mac) == configured_mac), None)
        if selected:
            return selected
    if configured_name:
        selected = next((item for item in matching if item.name.casefold() == configured_name.casefold()), None)
        if selected:
            return selected
    prefixes = tuple(config.get("ip_prefixes") or ["10."])
    candidates = [
        item
        for item in matching
        if item.status == "已连接" and any(ip.startswith(prefixes) for ip in item.ipv4)
    ]
    if len(candidates) == 1:
        return candidates[0]
    return matching[0] if len(matching) == 1 else None


def adapter_source_ip(adapter: AdapterInfo, config: dict) -> str:
    prefixes = tuple(config.get("ip_prefixes") or ["10."])
    return next((ip for ip in adapter.ipv4 if ip.startswith(prefixes)), "")


def http_get_bound(
    source_ip: str, host: str, port: int, path: str, timeout: float = 6
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection(
        host, port, timeout=timeout, source_address=(source_ip, 0)
    )
    try:
        connection.request(
            "GET",
            path,
            headers={"User-Agent": "Mozilla/5.0", "Connection": "close"},
        )
        response = connection.getresponse()
        body = response.read(64 * 1024)
        headers = {key.lower(): value for key, value in response.getheaders()}
        return response.status, headers, body
    finally:
        connection.close()


def probe_network(source_ip: str) -> tuple[bool, str]:
    checks = [
        ("www.gstatic.com", 80, "/generate_204", lambda status, body: status == 204),
        (
            "www.msftconnecttest.com",
            80,
            "/connecttest.txt",
            lambda status, body: status == 200 and body.strip() == b"Microsoft Connect Test",
        ),
    ]
    reachable = False
    for host, port, path, validator in checks:
        try:
            status, _headers, body = http_get_bound(source_ip, host, port, path)
            reachable = True
            if validator(status, body):
                return True, "online"
            if status in (301, 302, 303, 307, 308):
                return False, "portal_required"
        except OSError:
            continue
    return False, "network_error" if not reachable else "unexpected_response"


def parse_login_success(body: str) -> tuple[bool, str]:
    message = body[:300].replace("\r", " ").replace("\n", " ")
    match = re.search(r"\((\{.*\})\)\s*;?\s*$", body, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            result = data.get("result")
            message = str(data.get("msg") or data.get("message") or message)
            if result in (1, "1", True, "success"):
                return True, message
        except (json.JSONDecodeError, AttributeError):
            pass
    lowered = body.lower()
    indicators = ("认证成功", "登录成功", "已经在线", "已在线", '"result":1', "success")
    return any(item.lower() in lowered for item in indicators), message


def login_account(source_ip: str, config: dict, account: dict[str, str]) -> tuple[bool, str]:
    params = {
        "callback": "dr1003",
        "login_method": "1",
        "user_account": account["account"],
        "user_password": account["password"],
        "wlan_user_ip": source_ip,
        "wlan_user_ipv6": "",
        "wlan_user_mac": "000000000000",
        "wlan_ac_ip": config["wlan_ac_ip"],
        "wlan_ac_name": "",
        "jsVersion": "4.1.3",
        "terminal_type": "2",
        "lang": "zh-cn",
        "v": str(int(time.time() * 1000)),
    }
    path = "/eportal/portal/login?" + urlencode(params)
    try:
        status, _headers, raw_body = http_get_bound(
            source_ip,
            config["portal_host"],
            int(config["portal_port"]),
            path,
            timeout=8,
        )
        body = raw_body.decode("utf-8", errors="replace")
        success, message = parse_login_success(body)
        return success, message if message else f"HTTP {status}"
    except Exception as exc:
        return False, str(exc)


def try_authorized_accounts(source_ip: str, config: dict, logger) -> tuple[bool, str]:
    accounts = ordered_accounts(load_accounts())
    if not accounts:
        logger.error("尚未配置授权账号")
        return False, "尚未配置授权账号"
    delay = max(0, int(config.get("account_attempt_delay_seconds", 2)))
    for index, account in enumerate(accounts, start=1):
        masked = mask_account(account["account"])
        logger.info("正在尝试授权账号 %s（%d/%d）", masked, index, len(accounts))
        accepted, message = login_account(source_ip, config, account)
        if accepted:
            logger.info("认证入口已接受授权账号 %s", masked)
            for _ in range(3):
                time.sleep(3)
                online, _reason = probe_network(source_ip)
                if online:
                    state = load_state()
                    state.update(
                        {
                            "last_success_account": account["account"],
                            "last_success_at": time.time(),
                        }
                    )
                    save_state(state)
                    logger.info("网络已通过授权账号 %s 恢复", masked)
                    return True, masked
            logger.warning("账号 %s 已被接受，但联网检测仍未恢复", masked)
        else:
            logger.warning("授权账号 %s 登录失败：%s", masked, message)
        if index < len(accounts) and delay:
            time.sleep(delay)
    return False, ""
