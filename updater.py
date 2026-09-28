"""
Updater - Version Verification & In-App Auto-Update System
Checks for new versions of Urahara via GitHub Releases and raw version.json manifest.
Allows downloading and installing updates directly inside the app with 1 click.
"""

import os
import sys
import re
import json
import time
import tempfile
import webbrowser
import requests
import threading
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, Callable, Tuple

CURRENT_VERSION = "1.0.3"
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
    Check if a newer version exists remotely and identifies direct binary assets for in-app download.
    Returns:
    {
        "has_update": bool,
        "current_version": str,
        "latest_version": str,
        "release_title": str,
        "changelog": list or str,
        "download_url": str,
        "direct_download_url": Optional[str],
        "asset_name": Optional[str],
        "asset_size": int,
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
        "direct_download_url": None,
        "asset_name": None,
        "asset_size": 0,
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

            # Look for downloadable binaries in assets (.exe or .zip)
            direct_url = None
            asset_name = None
            asset_size = 0
            for asset in data.get("assets", []):
                a_name = asset.get("name", "")
                a_name_lower = a_name.lower()
                if a_name_lower.endswith(".exe") or a_name_lower.endswith(".zip"):
                    direct_url = asset.get("browser_download_url")
                    asset_name = a_name
                    asset_size = asset.get("size", 0)
                    if "setup" in a_name_lower or "urahara" in a_name_lower:
                        break  # Prefere o instalador Setup se houver

            if parse_version_tuple(remote_ver) > parse_version_tuple(CURRENT_VERSION):
                result["has_update"] = True
                result["latest_version"] = remote_ver
                result["release_title"] = data.get("name", f"Versão {remote_ver}")
                body = data.get("body", "")
                result["changelog"] = body.splitlines() if body else ["Melhorias de desempenho e novas correções."]
                result["download_url"] = data.get("html_url", DEFAULT_DOWNLOAD_URL)
                result["direct_download_url"] = direct_url
                result["asset_name"] = asset_name
                result["asset_size"] = asset_size
                return result
            else:
                result["latest_version"] = remote_ver or CURRENT_VERSION
                return result
    except Exception:
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
                result["direct_download_url"] = data.get("direct_download_url") or data.get("setup_url")
                result["asset_name"] = data.get("asset_name") or f"Urahara_Setup_v{remote_ver}.exe"
                result["asset_size"] = data.get("asset_size", 0)
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


def download_update_asset(
    asset_url: str,
    dest_path: str,
    progress_callback: Optional[Callable[[float, int, int], None]] = None,
    cancel_event: Optional[threading.Event] = None
) -> Tuple[bool, str]:
    """
    Downloads update package directly inside the app with real-time stream progress.
    progress_callback receives (fraction 0.0-1.0, downloaded_bytes, total_bytes).
    Returns (success: bool, dest_path_or_err: str).
    """
    headers = {
        "User-Agent": f"{APP_NAME}-Updater/{CURRENT_VERSION}",
        "Accept": "*/*"
    }
    tmp_path = dest_path + ".download_tmp"
    try:
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
        resp = requests.get(asset_url, headers=headers, stream=True, timeout=25, allow_redirects=True)
        resp.raise_for_status()

        total_bytes = int(resp.headers.get("content-length", 0))
        downloaded = 0
        chunk_size = 64 * 1024  # 64 KB

        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if cancel_event and cancel_event.is_set():
                    f.close()
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                    return False, "Download cancelado pelo usuário."
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        frac = (downloaded / total_bytes) if total_bytes > 0 else 0.5
                        progress_callback(min(1.0, frac), downloaded, total_bytes)

        if os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except Exception:
                pass
        os.replace(tmp_path, dest_path)
        return True, dest_path
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        return False, str(e)


def apply_update_and_restart(update_file_path: str) -> Tuple[bool, str]:
    """
    Applies the downloaded update and restarts Urahara automatically without manual browser download.
    Handles installer executable (.exe) or zip archives (.zip).
    """
    p = Path(update_file_path)
    if not p.exists():
        return False, "Arquivo de atualização não encontrado."

    ext = p.suffix.lower()
    app_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent

    temp_dir = Path(tempfile.gettempdir())
    bat_path = temp_dir / f"urahara_updater_{int(time.time())}.bat"

    if ext == ".exe":
        # Instalador Executável (Setup do Urahara)
        bat_content = f"""@echo off
chcp 65001 >nul
title Urahara Studio - Atualizando...
echo ========================================================
echo       URAHARA STUDIO - ATUALIZACAO AUTOMATICA
echo ========================================================
echo Aguardando encerramento do processo anterior...
timeout /t 2 /nobreak >nul

echo Iniciando instalacao da nova versao...
start "" "{update_file_path}"
exit
"""
    elif ext == ".zip":
        # Pacote Zip de Atualização
        exe_target = app_dir / "Urahara.exe"
        bat_content = f"""@echo off
chcp 65001 >nul
title Urahara Studio - Atualizando...
echo ========================================================
echo       URAHARA STUDIO - ATUALIZACAO AUTOMATICA
echo ========================================================
echo Aguardando encerramento do processo anterior...
timeout /t 2 /nobreak >nul

echo Extraindo arquivos atualizados para: {app_dir}...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Path '{update_file_path}' -DestinationPath '{app_dir}' -Force"

if exist "{exe_target}" (
    echo Reiniciando Urahara Studio atualizado...
    start "" "{exe_target}"
) else (
    echo Atualizacao concluida!
)
del /f /q "{update_file_path}" 2>nul
del "%~f0" 2>nul
exit
"""
    else:
        return False, f"Formato de atualização não suportado: {ext}"

    try:
        with open(bat_path, "w", encoding="utf-8") as f:
            f.write(bat_content)

        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

        subprocess.Popen(["cmd.exe", "/c", str(bat_path)], creationflags=creationflags, close_fds=True)
        time.sleep(0.5)
        os._exit(0)
        return True, "Atualização disparada com sucesso."
    except Exception as e:
        return False, f"Erro ao disparar atualizador: {e}"


def open_download_page(url: Optional[str] = None):
    """Open the release or repo download page in the system browser."""
    target = url or DEFAULT_DOWNLOAD_URL
    try:
        webbrowser.open(target)
    except Exception:
        pass

