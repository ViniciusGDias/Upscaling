"""
Updater - Version Verification & Remote Release Notification System
Checks for new versions of Video Studio Pro via GitHub Releases and raw version.json manifest.
Provides non-intrusive notification and direct download links to the end user.
"""

import os
import re
import json
import webbrowser
import requests
import threading
from typing import Dict, Any, Optional, Callable

CURRENT_VERSION = "1.0.1"
APP_NAME = "Urahara"
GITHUB_REPO = "ViniciusGDias/Upscaling"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RAW_VERSION = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/version.json"
DEFAULT_DOWNLOAD_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"


def parse_version_tuple(v_str: str) -> tuple:
    """Parse version string like 'v1.2.0' or '1.0' into a comparable tuple of integers."""
    clean = re.sub(r"[^\d.]", "", v_str.strip())
    parts = clean.split(".")
    res = []
    for p in parts:
        try:
            res.append(int(p))
        except ValueError:
            res.append(0)
    # Ensure at least 3 components (e.g. 1.0 -> 1.0.0)
    while len(res) < 3:
        res.append(0)
    return tuple(res)


def check_for_updates(timeout: int = 8) -> Dict[str, Any]:
    """
    Check if a newer version exists remotely.
    Returns:
    {
        "has_update": bool,
        "current_version": str,
        "latest_version": str,
        "release_title": str,
        "changelog": list or str,
        "download_url": str,
        "error": Optional[str]
    }
    """
    result = {
        "has_update": False,
        "current_version": CURRENT_VERSION,
        "latest_version": CURRENT_VERSION,
        "release_title": "",
        "changelog": [],
        "download_url": DEFAULT_DOWNLOAD_URL,
        "error": None
    }

    headers = {
        "User-Agent": f"{APP_NAME}-Updater/{CURRENT_VERSION}",
        "Accept": "application/json"
    }

    # 1. Try GitHub Releases API first
    try:
        resp = requests.get(GITHUB_RELEASES_API, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            tag_name = data.get("tag_name", "")
            remote_ver = tag_name.lstrip("vV")
            if parse_version_tuple(remote_ver) > parse_version_tuple(CURRENT_VERSION):
                result["has_update"] = True
                result["latest_version"] = remote_ver
                result["release_title"] = data.get("name", f"Versão {remote_ver}")
                body = data.get("body", "")
                result["changelog"] = body.splitlines() if body else ["Melhorias de desempenho e novas correções."]
                result["download_url"] = data.get("html_url", DEFAULT_DOWNLOAD_URL)
                return result
            else:
                result["latest_version"] = remote_ver or CURRENT_VERSION
                return result
    except Exception as e:
        # Fallback to raw version.json
        pass

    # 2. Try raw version.json from repository main branch
    try:
        resp2 = requests.get(GITHUB_RAW_VERSION, headers=headers, timeout=timeout)
        if resp2.status_code == 200:
            data = resp2.json()
            remote_ver = data.get("version", "").lstrip("vV")
            if parse_version_tuple(remote_ver) > parse_version_tuple(CURRENT_VERSION):
                result["has_update"] = True
                result["latest_version"] = remote_ver
                result["release_title"] = f"Versão {remote_ver}"
                result["changelog"] = data.get("changelog", ["Nova versão disponível."])
                result["download_url"] = data.get("download_url", DEFAULT_DOWNLOAD_URL)
                return result
            else:
                result["latest_version"] = remote_ver or CURRENT_VERSION
                return result
    except Exception as e:
        result["error"] = str(e)

    return result


def check_for_updates_async(callback: Callable[[Dict[str, Any]], None], timeout: int = 8):
    """Run version check in a background thread and call callback with result."""
    def _worker():
        res = check_for_updates(timeout=timeout)
        try:
            callback(res)
        except Exception:
            pass

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t


def open_download_page(url: Optional[str] = None):
    """Open the release or repo download page in the system browser."""
    target = url or DEFAULT_DOWNLOAD_URL
    try:
        webbrowser.open(target)
    except Exception:
        pass
