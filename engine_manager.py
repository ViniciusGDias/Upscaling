"""
Engine Manager - Dependency and Engine Verification & Auto-Downloader
Detects and automatically installs essential media engines:
- FFmpeg & FFprobe (Auto-download & extract to ./bin/ if missing)
- Real-CUGAN Vulkan (Anime upscaling engine)
- PyTorch & CUDA hardware acceleration
- Faster-Whisper & Demucs
"""

import os
import sys
import shutil
import zipfile
import tempfile
import threading
import urllib.request
import subprocess
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, Callable

APP_DIR = Path(__file__).parent.resolve()
BIN_DIR = APP_DIR / "bin"
BIN_DIR.mkdir(parents=True, exist_ok=True)

# Ensure BIN_DIR is in the runtime PATH
if str(BIN_DIR) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = f"{BIN_DIR};" + os.environ.get("PATH", "")


# Official Windows static FFmpeg release build URLs
FFMPEG_URLS = [
    # Gyan.dev essentials (compact, fast ~30MB download)
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    # BtbN GitHub latest build (full GPL fallback)
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
]


def find_engine_executable(name: str) -> Optional[str]:
    """Find executable in ./bin, current dir, or system PATH."""
    ext = ".exe" if sys.platform == "win32" else ""
    target = f"{name}{ext}"

    # 1. Check local bin/
    local_bin = BIN_DIR / target
    if local_bin.exists():
        return str(local_bin)

    # 2. Check app root
    local_root = APP_DIR / target
    if local_root.exists():
        return str(local_root)

    # 3. Check system PATH
    found = shutil.which(name)
    if found:
        return found

    # 4. Check common Windows fallback paths
    if sys.platform == "win32":
        common_paths = [
            Path(r"C:\ffmpeg\bin") / target,
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "ffmpeg" / "bin" / target,
            Path(os.environ.get("LOCALAPPDATA", "")) / "ffmpeg" / "bin" / target,
        ]
        for p in common_paths:
            if p.exists():
                return str(p)

    return None


def get_ffmpeg_version(ffmpeg_path: str) -> str:
    """Retrieve FFmpeg version string."""
    try:
        res = subprocess.run([ffmpeg_path, "-version"], capture_output=True, text=True, timeout=5)
        first_line = res.stdout.splitlines()[0] if res.stdout else ""
        return first_line.replace("ffmpeg version", "").strip().split()[0]
    except Exception:
        return "Disponível"


def check_all_engines() -> Dict[str, Dict[str, Any]]:
    """
    Verify all engines and return an inspection summary:
    {
        "ffmpeg": {"installed": bool, "path": str, "version": str},
        "realcugan": {"installed": bool, "path": str, "type": "Vulkan / NCNN"},
        "cuda": {"available": bool, "device_name": str, "vram_gb": float},
        "whisper": {"available": bool, "engine": "Faster-Whisper (CTranslate2)"},
        "demucs": {"available": bool}
    }
    """
    ffmpeg_exe = find_engine_executable("ffmpeg")
    ffprobe_exe = find_engine_executable("ffprobe")
    ffmpeg_ok = bool(ffmpeg_exe and ffprobe_exe)
    ffmpeg_ver = get_ffmpeg_version(ffmpeg_exe) if ffmpeg_exe else ""

    # Real-CUGAN
    cugan_exe = BIN_DIR / "realcugan" / "realcugan-ncnn-vulkan.exe"
    cugan_models = BIN_DIR / "realcugan" / "models-se"
    realcugan_ok = cugan_exe.exists() and cugan_models.exists()

    # PyTorch & CUDA
    cuda_ok = False
    device_name = "CPU"
    vram_gb = 0.0
    try:
        import torch
        if torch.cuda.is_available():
            cuda_ok = True
            device_name = torch.cuda.get_device_name(0)
            try:
                vram_gb = round(torch.cuda.get_device_properties(0).total_memory / (1024 ** 3), 1)
            except Exception:
                pass
    except Exception:
        pass

    # Whisper
    whisper_ok = False
    try:
        import faster_whisper
        whisper_ok = True
    except Exception:
        pass

    # Demucs
    demucs_ok = False
    try:
        import demucs
        demucs_ok = True
    except Exception:
        pass

    return {
        "ffmpeg": {
            "installed": ffmpeg_ok,
            "path": ffmpeg_exe or "",
            "version": ffmpeg_ver,
            "ffprobe_path": ffprobe_exe or ""
        },
        "realcugan": {
            "installed": realcugan_ok,
            "path": str(cugan_exe) if realcugan_ok else "",
            "type": "Vulkan / NCNN (GPU Universal)"
        },
        "cuda": {
            "available": cuda_ok,
            "device_name": device_name,
            "vram_gb": vram_gb
        },
        "whisper": {
            "available": whisper_ok,
            "engine": "Faster-Whisper (Local)" if whisper_ok else "Pendente"
        },
        "demucs": {
            "available": demucs_ok
        }
    }


def download_and_install_ffmpeg(
    on_progress: Optional[Callable[[float, str], None]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_complete: Optional[Callable[[bool, str], None]] = None
):
    """
    Download prebuilt FFmpeg for Windows and extract ffmpeg.exe & ffprobe.exe into ./bin/
    Non-blocking when invoked inside a thread.
    """
    def _run():
        def _log(msg):
            if on_log:
                try:
                    on_log(msg)
                except Exception:
                    pass

        def _prog(pct, msg):
            if on_progress:
                try:
                    on_progress(pct, msg)
                except Exception:
                    pass

        _log("⬇️ Iniciando download automático do FFmpeg...")
        _prog(0.05, "Conectando ao servidor de download...")

        temp_zip = BIN_DIR / "ffmpeg_temp.zip"
        temp_extract = BIN_DIR / "_ffmpeg_extracted"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        downloaded = False
        last_error = ""

        for url in FFMPEG_URLS:
            try:
                _log(f"   Baixando de: {url.split('/')[2]}...")
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as response:
                    total_size = int(response.info().get("Content-Length", 0))
                    downloaded_bytes = 0
                    chunk_size = 1024 * 128  # 128 KB

                    with open(temp_zip, "wb") as out_file:
                        while True:
                            chunk = response.read(chunk_size)
                            if not chunk:
                                break
                            out_file.write(chunk)
                            downloaded_bytes += len(chunk)
                            if total_size > 0:
                                pct = 0.10 + (downloaded_bytes / total_size) * 0.65
                                mb_down = downloaded_bytes / (1024 * 1024)
                                mb_tot = total_size / (1024 * 1024)
                                _prog(pct, f"Baixando FFmpeg: {mb_down:.1f}MB / {mb_tot:.1f}MB ({int((downloaded_bytes / total_size)*100)}%)")
                            else:
                                mb_down = downloaded_bytes / (1024 * 1024)
                                _prog(0.40, f"Baixando FFmpeg: {mb_down:.1f}MB...")
                downloaded = True
                _log("✓ Download do arquivo ZIP concluído.")
                break
            except Exception as e:
                last_error = str(e)
                _log(f"⚠️ Falha no mirror: {e}. Tentando próximo...")
                continue

        if not downloaded:
            err_msg = f"Não foi possível baixar o FFmpeg automaticamente: {last_error}"
            _log(f"✕ {err_msg}")
            if on_complete:
                on_complete(False, err_msg)
            return

        try:
            _prog(0.80, "Extraindo executáveis do FFmpeg...")
            _log("📦 Extraindo ffmpeg.exe e ffprobe.exe...")

            if temp_extract.exists():
                shutil.rmtree(temp_extract, ignore_errors=True)
            temp_extract.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(temp_zip, "r") as zip_ref:
                # Find ffmpeg.exe and ffprobe.exe in the zip archive
                ffmpeg_target = None
                ffprobe_target = None
                for member in zip_ref.namelist():
                    name_lower = member.lower()
                    if name_lower.endswith("bin/ffmpeg.exe") or name_lower.endswith("/ffmpeg.exe") or name_lower == "ffmpeg.exe":
                        ffmpeg_target = member
                    elif name_lower.endswith("bin/ffprobe.exe") or name_lower.endswith("/ffprobe.exe") or name_lower == "ffprobe.exe":
                        ffprobe_target = member

                if not ffmpeg_target:
                    # Search anywhere in archive
                    for member in zip_ref.namelist():
                        if member.lower().endswith("ffmpeg.exe"):
                            ffmpeg_target = member
                            break

                if not ffprobe_target:
                    for member in zip_ref.namelist():
                        if member.lower().endswith("ffprobe.exe"):
                            ffprobe_target = member
                            break

                if not ffmpeg_target:
                    raise RuntimeError("ffmpeg.exe não encontrado dentro do arquivo ZIP baixado.")

                # Extract only what we need
                zip_ref.extract(ffmpeg_target, temp_extract)
                extracted_ffmpeg = temp_extract / ffmpeg_target
                shutil.copy2(extracted_ffmpeg, BIN_DIR / "ffmpeg.exe")
                _log("   ✓ ffmpeg.exe instalado em ./bin/")

                if ffprobe_target:
                    zip_ref.extract(ffprobe_target, temp_extract)
                    extracted_ffprobe = temp_extract / ffprobe_target
                    shutil.copy2(extracted_ffprobe, BIN_DIR / "ffprobe.exe")
                    _log("   ✓ ffprobe.exe instalado em ./bin/")

            # Clean up temporary zip and extracted folder
            try:
                temp_zip.unlink(missing_ok=True)
                shutil.rmtree(temp_extract, ignore_errors=True)
            except Exception:
                pass

            # Update PATH runtime
            if str(BIN_DIR) not in os.environ.get("PATH", ""):
                os.environ["PATH"] = f"{BIN_DIR};" + os.environ.get("PATH", "")

            _prog(1.0, "FFmpeg instalado e configurado com sucesso!")
            _log("🎉 FFmpeg pronto para uso em todo o aplicativo!")
            if on_complete:
                on_complete(True, "FFmpeg instalado com sucesso em ./bin/!")

        except Exception as e:
            err_msg = f"Erro ao extrair FFmpeg: {e}"
            _log(f"✕ {err_msg}")
            if on_complete:
                on_complete(False, err_msg)

    threading.Thread(target=_run, daemon=True).start()
