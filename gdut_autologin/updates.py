from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .constants import (
    APP_VERSION,
    EXECUTABLE,
    GITHUB_RELEASES_URL,
    INSTALLED_EXE,
    UPDATE_DIR,
    UPDATE_STATUS_PATH,
)


USER_AGENT = f"GDUTAutoLogin/{APP_VERSION} (+https://github.com/ymxc152/gdut-auto-login)"


@dataclass
class UpdateInfo:
    current_version: str = APP_VERSION
    latest_version: str = APP_VERSION
    available: bool = False
    release_url: str = ""
    notes: str = ""
    published_at: str = ""
    exe_name: str = ""
    exe_url: str = ""
    exe_size: int = 0
    checksums_url: str = ""
    checked_at: str = ""
    downloaded_path: str = ""
    error: str = ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def version_tuple(value: str) -> tuple[int, ...]:
    match = re.search(r"(\d+(?:\.\d+)+)", value or "")
    return tuple(int(part) for part in match.group(1).split(".")) if match else (0,)


def save_update_status(info: UpdateInfo | dict) -> None:
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    value = asdict(info) if isinstance(info, UpdateInfo) else info
    temporary = UPDATE_STATUS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(UPDATE_STATUS_PATH)


def load_update_status() -> dict:
    try:
        value = json.loads(UPDATE_STATUS_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _fetch(url: str, timeout: int = 20) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def check_latest_release() -> UpdateInfo:
    info = UpdateInfo(checked_at=_utc_now())
    try:
        release = json.loads(_fetch(GITHUB_RELEASES_URL).decode("utf-8"))
        tag = str(release.get("tag_name", ""))
        info.latest_version = re.sub(r"^[vV]", "", tag) or APP_VERSION
        info.available = version_tuple(info.latest_version) > version_tuple(APP_VERSION)
        info.release_url = str(release.get("html_url", ""))
        info.notes = str(release.get("body", ""))
        info.published_at = str(release.get("published_at", ""))
        expected = f"GDUTAutoLogin-{info.latest_version}-win64.exe".casefold()
        for asset in release.get("assets", []):
            name = str(asset.get("name", ""))
            if name.casefold() == expected:
                info.exe_name = name
                info.exe_url = str(asset.get("browser_download_url", ""))
                info.exe_size = int(asset.get("size", 0) or 0)
            elif name.casefold() == "sha256sums.txt":
                info.checksums_url = str(asset.get("browser_download_url", ""))
        if info.available and (not info.exe_url or not info.checksums_url):
            info.error = "新版发布缺少 EXE 或 SHA256SUMS.txt，已拒绝下载。"
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        info.error = f"检查更新失败：{exc}"
    save_update_status(info)
    return info


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_hash(checksum_text: str, filename: str) -> str:
    for line in checksum_text.splitlines():
        parts = line.strip().replace(" *", "  ").split()
        if len(parts) >= 2 and Path(parts[-1]).name.casefold() == filename.casefold():
            value = parts[0].lower()
            if re.fullmatch(r"[0-9a-f]{64}", value):
                return value
    raise RuntimeError("校验文件中没有找到新版 EXE 的 SHA-256。")


def download_update(info: UpdateInfo, progress=None) -> Path:
    if not info.available or not info.exe_url or not info.checksums_url:
        raise RuntimeError(info.error or "当前没有可下载的更新。")
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    destination = UPDATE_DIR / info.exe_name
    partial = destination.with_suffix(destination.suffix + ".part")
    checksum_text = _fetch(info.checksums_url).decode("utf-8-sig")
    expected_hash = _expected_hash(checksum_text, info.exe_name)
    request = Request(info.exe_url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60) as response, partial.open("wb") as handle:
        total = int(response.headers.get("Content-Length", info.exe_size) or 0)
        received = 0
        while True:
            block = response.read(1024 * 256)
            if not block:
                break
            handle.write(block)
            received += len(block)
            if progress:
                progress(received, total)
    if info.exe_size and partial.stat().st_size != info.exe_size:
        partial.unlink(missing_ok=True)
        raise RuntimeError("下载文件大小与发布信息不一致。")
    actual_hash = file_sha256(partial)
    if actual_hash != expected_hash:
        partial.unlink(missing_ok=True)
        raise RuntimeError("SHA-256 校验失败，下载文件可能损坏或被篡改。")
    partial.replace(destination)
    info.downloaded_path = str(destination)
    save_update_status(info)
    return destination


def launch_update_installer(downloaded: Path, target: Path | None = None) -> None:
    target = target or INSTALLED_EXE
    health_file = UPDATE_DIR / f"health-{int(time.time())}.json"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(
        [str(downloaded), "--apply-update", "--target", str(target), "--wait-pid", str(os.getpid()),
         "--health-file", str(health_file)],
        creationflags=flags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _replace_with_retry(source: Path, target: Path, attempts: int = 40) -> None:
    for attempt in range(attempts):
        try:
            source.replace(target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.25)


def apply_update(target: Path, wait_pid: int, health_file: Path) -> int:
    from .windows import create_start_menu_shortcut

    result_path = UPDATE_DIR / "last-install-result.json"
    target = target.resolve()
    if target != INSTALLED_EXE.resolve():
        return 2
    backup = target.with_suffix(".previous.exe")
    staged = target.with_suffix(".new.exe")
    try:
        for _ in range(120):
            try:
                os.kill(wait_pid, 0)
            except OSError:
                break
            time.sleep(0.25)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(EXECUTABLE, staged)
        if target.exists():
            shutil.copy2(target, backup)
        _replace_with_retry(staged, target)
        create_start_menu_shortcut()
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen([str(target), "--post-update", "--health-file", str(health_file)], creationflags=flags)
        healthy = False
        for _ in range(80):
            if health_file.exists():
                try:
                    healthy = bool(json.loads(health_file.read_text(encoding="utf-8")).get("ok"))
                except (OSError, json.JSONDecodeError):
                    healthy = False
                if healthy:
                    break
            time.sleep(0.25)
        if not healthy:
            raise RuntimeError("新版启动自检超时。")
        result = {"ok": True, "version": APP_VERSION, "updated_at": _utc_now(), "backup": str(backup)}
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0
    except Exception as exc:
        try:
            if backup.exists():
                shutil.copy2(backup, staged)
                _replace_with_retry(staged, target)
                subprocess.Popen([str(target)], creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        finally:
            result = {"ok": False, "error": str(exc), "updated_at": _utc_now()}
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1
