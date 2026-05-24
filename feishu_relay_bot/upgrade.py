"""
自升级：从 GitHub Releases 下载 wheel 并安装，然后退出进程。

安全约束：
  - 只允许从固定仓库列表下载（可配置）
  - 禁止安装任意 URL 的 wheel
  - 升级前校验下载文件大小（防止超大文件攻击）
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import urllib.request
from urllib.parse import urlparse

logger = logging.getLogger("feishu-relay-bot.upgrade")

# 允许升级的仓库白名单（owner/repo）
_ALLOWED_REPOS = [
    r.strip()
    for r in os.environ.get(
        "FEISHU_BOT_UPGRADE_REPOS",
        "Zenwh/feishu-relay-bot,Explorerxixixi/feishu-relay-bot",
    ).split(",")
    if r.strip()
]

# 最大允许下载 50 MB
_MAX_WHEEL_SIZE = 50 * 1024 * 1024

# target_version 允许的字符：仅 ASCII 字母、数字、点、连字符
_VERSION_RE = re.compile(r"^[A-Za-z0-9.-]+$")


def _validate_version(version: str) -> bool:
    if version == "latest":
        return True
    return bool(_VERSION_RE.match(version))


def _hostname_is_github(url: str) -> bool:
    """Return True only when the actual response origin is github.com or
    a known-github CDN sub-domain.  urllib follows redirects transparently,
    so we must inspect the final URL after urlopen has settled."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if not host:
            return False
        return host == "github.com" or host.endswith(".githubusercontent.com")
    except Exception:
        return False


def _resolve_wheel_url(version: str, repo: str) -> str | None:
    """从 GitHub Releases API 解析 .whl 下载 URL。"""
    github_api = f"https://api.github.com/repos/{repo}/releases"

    if not _validate_version(version):
        logger.error("拒绝升级：非法的 version 格式: %r", version)
        return None

    if version == "latest":
        url = f"{github_api}/latest"
    else:
        tag = f"v{version}"
        url = f"{github_api}/tags/{tag}"

    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        logger.error("查询 GitHub Release 失败: %s — %s", url, e)
        return None

    for asset in data.get("assets", []):
        if asset["name"].endswith(".whl"):
            return asset["browser_download_url"]

    logger.error("Release 中未找到 .whl 文件: %s", data.get("tag_name", "?"))
    return None


def _download_with_limit(url: str) -> bytes:
    """下载文件并限制大小。"""
    req = urllib.request.Request(url, headers={"Accept": "application/octet-stream"})
    data = b""
    with urllib.request.urlopen(req, timeout=120) as resp:
        final_url = resp.url
        if not _hostname_is_github(final_url):
            raise ValueError(
                f"拒绝下载：实际源站非 github.com 子域 ({final_url})"
            )
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            data += chunk
            if len(data) > _MAX_WHEEL_SIZE:
                raise ValueError(f"wheel 超过最大限制 {_MAX_WHEEL_SIZE} bytes")
    return data


def upgrade_and_exit(target_version: str = "latest", repo: str = ""):
    """
    从 GitHub Releases 下载新版本 wheel 安装，然后退出进程。
    systemd/supervisor 会自动拉起新版本。
    """
    logger.info("开始升级: target=%s repo=%s", target_version, repo or "default")

    # 确定仓库
    if not repo:
        repo = _ALLOWED_REPOS[0] if _ALLOWED_REPOS else ""
    if repo not in _ALLOWED_REPOS:
        logger.error("拒绝升级：仓库 %s 不在白名单 %s", repo, _ALLOWED_REPOS)
        return

    wheel_url = _resolve_wheel_url(target_version, repo)
    if not wheel_url:
        return

    try:
        wheel_data = _download_with_limit(wheel_url)
        logger.info("下载完成: %s (%d bytes)", wheel_url, len(wheel_data))

        # 保存到临时文件
        tmp_path = f"/tmp/feishu_relay_bot_upgrade_{hashlib.sha256(wheel_data).hexdigest()[:8]}.whl"
        with open(tmp_path, "wb") as f:
            f.write(wheel_data)

        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--force-reinstall", tmp_path],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            logger.info("升级成功，准备重启\n%s", result.stdout[-200:] if result.stdout else "")
        else:
            logger.error("升级失败 (code=%d):\n%s", result.returncode, result.stderr[-500:])
            return
    except subprocess.TimeoutExpired:
        logger.error("升级超时（120s）")
        return
    except Exception as e:
        logger.error("升级异常: %s", e)
        return

    logger.info("退出进程，等待 systemd 重启新版本 ...")
    sys.exit(0)
