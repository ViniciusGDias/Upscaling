"""
AI Upscaler - Real-ESRGAN Engine Module
Handles video upscaling using Real-ESRGAN neural network (CUDA-accelerated).

Pipeline:
  1. Extract frames from video (FFmpeg)
  2. Process each frame through Real-ESRGAN (GPU / CUDA)
  3. Re-assemble video from upscaled frames (FFmpeg)
  4. Merge original audio back

Requirements:
  pip install torch torchvision basicsr realesrgan facexlib gfpgan
"""

import subprocess
import os
import re
import json
import shutil
import threading
import tempfile
import sys
import types
from typing import Callable, Optional


# ── Compatibility patch: basicsr uses torchvision.transforms.functional_tensor
# which was removed in newer torchvision versions. We create a shim module. ──
def _apply_torchvision_compat_patch():
    """
    basicsr and realesrgan import `torchvision.transforms.functional_tensor`,
    a module that was removed in torchvision >= 0.16.
    This patch creates a stub that redirects calls to the current API.
    Must be called BEFORE importing basicsr or realesrgan.
    """
    try:
        import importlib
        importlib.import_module("torchvision.transforms.functional_tensor")
        return  # Already available — no patch needed
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        import torchvision.transforms.functional as F

        # Create a fake module with the functions that basicsr expects
        fake_module = types.ModuleType("torchvision.transforms.functional_tensor")

        # Map the most commonly needed functions from the new API location
        _funcs = [
            "rgb_to_grayscale", "adjust_brightness", "adjust_contrast",
            "adjust_hue", "adjust_saturation", "adjust_sharpness",
            "normalize", "resize", "pad", "crop", "center_crop",
            "hflip", "vflip", "rotate", "affine", "perspective",
            "gaussian_blur", "equalize", "invert", "posterize",
            "solarize", "autocontrast",
        ]
        for fn in _funcs:
            if hasattr(F, fn):
                setattr(fake_module, fn, getattr(F, fn))

        # Inject into sys.modules so that 'from torchvision.transforms.functional_tensor import X' works
        sys.modules["torchvision.transforms.functional_tensor"] = fake_module

        import torchvision.transforms as T_pkg
        T_pkg.functional_tensor = fake_module  # type: ignore

    except Exception:
        pass  # If patch fails, let the real import error surface later


_apply_torchvision_compat_patch()



# ── Available AI Models ───────────────────────────────────────────────────────

AI_MODELS = {
    "⚡ Real-CUGAN Anime 4x (Mais Rápido & Fiel)": {
        "engine": "realcugan",
        "name": "models-se",
        "scale": 4,
        "denoise": 0,
        "description": "⚡ Real-CUGAN 4x (Bilibili) — Até 3x mais rápido, preserva traço e textura",
    },
    "⚡ Real-CUGAN Anime 2x (Velocidade Máxima)": {
        "engine": "realcugan",
        "name": "models-se",
        "scale": 2,
        "denoise": 0,
        "description": "⚡ Real-CUGAN 2x — Velocidade máxima para animes 1080p -> 4K",
    },
    "⭐ Real-CUGAN Anime Pro 3x (Alta Fidelidade)": {
        "engine": "realcugan",
        "name": "models-pro",
        "scale": 3,
        "denoise": 0,
        "description": "⭐ Real-CUGAN Pro 3x — Qualidade máxima para anime com detalhes finos",
    },
    "🤖 Real-ESRGAN x4 Anime": {
        "engine": "realesrgan",
        "name": "RealESRGAN_x4plus_anime_6B",
        "scale": 4,
        "description": "Otimizado para animações, cartoon, jogos 2D | Fator: 4×",
        "tile": 400,
        "tile_pad": 10,
    },
    "🤖 Real-ESRGAN x4 (Geral — Foto Real)": {
        "engine": "realesrgan",
        "name": "RealESRGAN_x4plus",
        "scale": 4,
        "description": "Melhor para vídeos do mundo real (gameplay, câmera, filmes)",
        "tile": 400,
        "tile_pad": 10,
    },
    "🤖 Real-ESRNet x4 (Nítido)": {
        "engine": "realesrgan",
        "name": "RealESRNet_x4plus",
        "scale": 4,
        "description": "Mais nítido e menos 'pintado' — bom para vídeos com muito texto",
        "tile": 400,
        "tile_pad": 10,
    },
    "🤖 Real-ESRGAN x2 (Rápido)": {
        "engine": "realesrgan",
        "name": "RealESRGAN_x2plus",
        "scale": 2,
        "description": "Upscale 2x — mais rápido, bom para já ter resolução alta",
        "tile": 640,
        "tile_pad": 10,
    },
}


def find_realcugan_bin() -> Optional[str]:
    """Find realcugan-ncnn-vulkan executable."""
    from pathlib import Path
    base = Path(__file__).parent
    candidates = [
        base / "bin" / "realcugan" / "realcugan-ncnn-vulkan.exe",
        base / "realcugan-ncnn-vulkan.exe",
    ]
    for p in candidates:
        if p.is_file():
            return str(p.resolve())
    import shutil
    return shutil.which("realcugan-ncnn-vulkan")


def check_realesrgan_available() -> tuple[bool, str]:
    """
    Check if AI dependencies are installed (Real-CUGAN or Real-ESRGAN).
    Returns (available: bool, message: str)
    """
    cugan_bin = find_realcugan_bin()

    missing = []
    try:
        import torch
        cuda_ok = torch.cuda.is_available()
    except ImportError:
        missing.append("torch")
        cuda_ok = False

    try:
        import basicsr
    except ImportError:
        missing.append("basicsr")

    try:
        from realesrgan import RealESRGANer
    except ImportError:
        missing.append("realesrgan")

    if cugan_bin and os.path.isfile(cugan_bin):
        if not missing and cuda_ok:
            return True, "Real-CUGAN (Vulkan) & Real-ESRGAN (CUDA) prontos ✓"
        return True, "Real-CUGAN pronto com aceleração Vulkan ✓"

    if missing:
        return False, f"Dependências faltando: {', '.join(missing)}. Execute: pip install {' '.join(missing)}"
    if not cuda_ok:
        return False, "PyTorch instalado, mas CUDA não disponível. Verifique os drivers NVIDIA."

    return True, "Real-ESRGAN disponível com CUDA ✓"


def get_torch_device() -> str:
    """Return 'cuda' if available, else 'cpu'."""
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _find_ffmpeg() -> Optional[str]:
    """Find FFmpeg executable."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        if result.returncode == 0:
            return "ffmpeg"
    except FileNotFoundError:
        pass

    if os.name == 'nt':
        for path in [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            os.path.join(os.environ.get('PROGRAMFILES', ''), 'ffmpeg', 'bin', 'ffmpeg.exe'),
            os.path.join(os.environ.get('LOCALAPPDATA', ''), 'ffmpeg', 'bin', 'ffmpeg.exe'),
            os.path.join(os.path.expanduser('~'), 'ffmpeg', 'bin', 'ffmpeg.exe'),
        ]:
            if os.path.isfile(path):
                return path
    return None


def _find_ffprobe() -> Optional[str]:
    """Find FFprobe executable."""
    try:
        result = subprocess.run(
            ["ffprobe", "-version"], capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        if result.returncode == 0:
            return "ffprobe"
    except FileNotFoundError:
        pass

    if os.name == 'nt':
        for path in [
            r"C:\ffmpeg\bin\ffprobe.exe",
            os.path.join(os.environ.get('PROGRAMFILES', ''), 'ffmpeg', 'bin', 'ffprobe.exe'),
            os.path.join(os.environ.get('LOCALAPPDATA', ''), 'ffmpeg', 'bin', 'ffprobe.exe'),
            os.path.join(os.path.expanduser('~'), 'ffmpeg', 'bin', 'ffprobe.exe'),
        ]:
            if os.path.isfile(path):
                return path
    return None


def _get_video_fps_and_duration(filepath: str) -> tuple[float, float, int, int]:
    """
    Get video FPS, duration, width and height using ffprobe.
    Returns (fps, duration_seconds, width, height)
    """
    ffprobe = _find_ffprobe()
    if not ffprobe:
        return 30.0, 0.0, 0, 0

    try:
        cmd = [
            ffprobe, "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", filepath
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        data = json.loads(result.stdout)

        video_stream = None
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                video_stream = stream
                break

        if not video_stream:
            return 30.0, 0.0, 0, 0

        fps_str = video_stream.get("r_frame_rate", "30/1")
        if "/" in fps_str:
            num, den = fps_str.split("/")
            fps = float(num) / float(den) if float(den) != 0 else 30.0
        else:
            fps = float(fps_str)

        duration = float(data.get("format", {}).get("duration", 0))
        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))

        return fps, duration, width, height
    except Exception:
        return 30.0, 0.0, 0, 0


def _count_frames_in_dir(directory: str) -> int:
    """Count PNG frames in a directory."""
    return len([f for f in os.listdir(directory) if f.endswith('.png')])


class AIVideoUpscaler:
    """
    Handles AI-powered video upscaling using Real-ESRGAN.

    Pipeline:
      1. Extract frames from input video using FFmpeg
      2. Run Real-ESRGAN on each frame (GPU accelerated)
      3. Re-encode to video using FFmpeg (HEVC/h265)
      4. Merge original audio
    """

    def __init__(self):
        self._cancelled = False
        self._proc = None  # Subprocess handle (e.g. Real-CUGAN)
        self._upsampler = None  # Cached RealESRGANer instance

    def cancel(self):
        """Request cancellation."""
        self._cancelled = True
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def _load_model(
        self,
        model_key: str,
        on_log: Optional[Callable[[str], None]] = None,
    ):
        """Load the Real-ESRGAN model. Caches after first load."""
        def _log(msg):
            if on_log:
                on_log(msg)

        model_info = AI_MODELS.get(model_key)
        if not model_info:
            raise ValueError(f"Modelo desconhecido: {model_key}")

        # Import here so the rest of the app doesn't fail if not installed
        import torch
        from basicsr.archs.rrdbnet_arch import RRDBNet
        from realesrgan import RealESRGANer
        from realesrgan.archs.srvgg_arch import SRVGGNetCompact

        model_name = model_info["name"]
        scale = model_info["scale"]
        tile_pad = model_info["tile_pad"]
        device = get_torch_device()

        # ── Auto-select tile size based on available VRAM ─────────────────
        # In a 4x model, each tile is multiplied by 4 in width & height.
        # Tile 1024 creates 4096x4096 tensors which exceed 8GB VRAM and trigger
        # Windows Shared GPU Memory (PCIe RAM paging), slowing it down 20x!
        # Optimal tile size to keep everything 100% in fast VRAM: 400-512px.
        if scale >= 4:
            tile = 400 if device == "cuda" else 256
        else:
            tile = 640 if device == "cuda" else 256

        if device == "cuda" and torch.cuda.is_available():
            try:
                vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
                if vram_gb >= 16:
                    tile = 800 if scale >= 4 else 1024
                elif vram_gb >= 12:
                    tile = 512 if scale >= 4 else 800
                elif vram_gb >= 8:
                    tile = 448 if scale >= 4 else 640
                else:
                    tile = 320 if scale >= 4 else 480
                _log(f"🚀 VRAM {vram_gb:.1f}GB — tile size calibrado: {tile}px (100% VRAM sem paginação)")
            except Exception:
                pass

        _log(f"🧠 Carregando modelo: {model_name}")
        _log(f"   Dispositivo: {device.upper()} | Tile: {tile if tile > 0 else 'sem tiling (frame completo)'}")

        # Build the architecture based on model name
        if model_name == "RealESRGAN_x4plus":
            model = RRDBNet(
                num_in_ch=3, num_out_ch=3, num_feat=64,
                num_block=23, num_grow_ch=32, scale=4
            )
        elif model_name == "RealESRGAN_x4plus_anime_6B":
            model = RRDBNet(
                num_in_ch=3, num_out_ch=3, num_feat=64,
                num_block=6, num_grow_ch=32, scale=4
            )
        elif model_name == "RealESRNet_x4plus":
            model = RRDBNet(
                num_in_ch=3, num_out_ch=3, num_feat=64,
                num_block=23, num_grow_ch=32, scale=4
            )
        elif model_name == "RealESRGAN_x2plus":
            model = RRDBNet(
                num_in_ch=3, num_out_ch=3, num_feat=64,
                num_block=23, num_grow_ch=32, scale=2
            )
        else:
            raise ValueError(f"Arquitetura desconhecida para: {model_name}")

        # Auto-download model weights from GitHub
        model_url = _get_model_url(model_name)

        upsampler = RealESRGANer(
            scale=scale,
            model_path=model_url,
            model=model,
            tile=tile,
            tile_pad=tile_pad,
            pre_pad=0,
            half=(device == "cuda"),   # FP16 on GPU for speed
            device=device,
        )

        _log(f"   ✓ Modelo carregado!")
        return upsampler, scale

    def upscale(
        self,
        input_path: str,
        output_path: str,
        model_key: str,
        target_width: int = 0,
        target_height: int = 0,
        encoder: str = "nvidia",
        crf: int = 18,
        preset: str = "p5",
        target_fps: Optional[int] = None,
        sharpen_filter: Optional[str] = None,
        color_filter: Optional[str] = None,
        denoise_filter: Optional[str] = None,
        anti_copyright_filter: Optional[str] = None,
        anti_copyright_audio: Optional[str] = None,
        on_progress: Optional[Callable[[float, str], None]] = None,
        on_complete: Optional[Callable[[bool, str], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ):
        """
        Main entry point: upscale video with Real-ESRGAN.
        Runs in a background thread.
        """
        self._cancelled = False

        def _log(msg: str):
            if on_log:
                on_log(msg)

        def _run():
            tmp_frames_dir = None
            tmp_upscaled_dir = None
            tmp_video = None

            try:
                ffmpeg = _find_ffmpeg()
                if not ffmpeg:
                    if on_complete:
                        on_complete(False, "FFmpeg não encontrado!")
                    return

                # ── Step 0: Get video info ──────────────────────────────────
                _log("📋 Analisando vídeo de entrada...")
                fps, duration, src_w, src_h = _get_video_fps_and_duration(input_path)
                output_fps = target_fps if target_fps is not None else fps
                _log(f"   Resolução: {src_w}×{src_h} | FPS: {fps:.2f} | Duração: {duration:.1f}s")

                if on_progress:
                    on_progress(0, "Iniciando IA...")
                
                # ── Step 1: Check engine & Load model ───────────────────────
                _log("─────────────────────────")
                model_cfg = AI_MODELS.get(model_key, {})
                engine = model_cfg.get("engine", "realesrgan")
                ai_scale = model_cfg.get("scale", 4)
                upsampler = None

                if engine == "realesrgan":
                    try:
                        upsampler, ai_scale = self._load_model(model_key, on_log)
                    except ImportError as e:
                        if on_complete:
                            on_complete(False, f"Dependência faltando: {e}. Execute: pip install basicsr realesrgan")
                        return
                    except Exception as e:
                        if on_complete:
                            on_complete(False, f"Erro ao carregar modelo: {e}")
                        return
                else:
                    cugan_bin = find_realcugan_bin()
                    if not cugan_bin or not os.path.isfile(cugan_bin):
                        if on_complete:
                            on_complete(False, "Binário realcugan-ncnn-vulkan.exe não encontrado em bin/realcugan.")
                        return
                    _log(f"⚡ Motor de IA: Real-CUGAN (Bilibili AI Lab)")
                    _log(f"   Modelo: {model_key} | Escala: {ai_scale}× | Hardware: Vulkan (RTX 5060)")

                if self._cancelled:
                    if on_complete:
                        on_complete(False, "Cancelado.")
                    return

                # ── Step 2: Extract frames ──────────────────────────────────
                _log("─────────────────────────")
                _log("🎞️ Extraindo frames do vídeo...")

                tmp_dir = tempfile.mkdtemp(prefix="ai_upscale_")
                tmp_frames_dir = os.path.join(tmp_dir, "frames")
                tmp_upscaled_dir = os.path.join(tmp_dir, "upscaled")
                os.makedirs(tmp_frames_dir, exist_ok=True)
                os.makedirs(tmp_upscaled_dir, exist_ok=True)

                # Build denoise filter for frame extraction if needed
                extract_cmd = [
                    ffmpeg, "-i", input_path,
                ]
                if denoise_filter:
                    extract_cmd += ["-vf", denoise_filter]
                extract_cmd += [
                    "-q:v", "1",          # Maximum PNG quality
                    os.path.join(tmp_frames_dir, "frame_%08d.png"),
                    "-y",
                ]

                if on_progress:
                    on_progress(2, "Extraindo frames...")

                result = subprocess.run(
                    extract_cmd, capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                if result.returncode != 0:
                    if on_complete:
                        on_complete(False, "Erro ao extrair frames do vídeo.")
                    return

                total_frames = _count_frames_in_dir(tmp_frames_dir)
                _log(f"   ✓ {total_frames} frames extraídos")

                if total_frames == 0:
                    if on_complete:
                        on_complete(False, "Nenhum frame encontrado no vídeo.")
                    return

                if self._cancelled:
                    if on_complete:
                        on_complete(False, "Cancelado.")
                    return

                # ── Step 3: AI upscale frames ───────────────────────────────
                _log("─────────────────────────")

                if engine == "realcugan":
                    _log(f"⚡ Processando {total_frames} frames com Real-CUGAN (Vulkan / GPU)...")
                    _log(f"   Modo de alta velocidade com multithreading ativo")

                    cugan_bin = find_realcugan_bin()
                    cugan_dir = os.path.dirname(os.path.abspath(cugan_bin))
                    model_name = model_cfg.get("name", "models-se")
                    model_path = os.path.join(cugan_dir, model_name)
                    denoise_lvl = model_cfg.get("denoise", 0)

                    cmd_cugan = [
                        cugan_bin,
                        "-i", tmp_frames_dir,
                        "-o", tmp_upscaled_dir,
                        "-s", str(ai_scale),
                        "-n", str(denoise_lvl),
                        "-m", model_path,
                        "-g", "0",
                        "-j", "2:2:2",
                        "-v",
                    ]

                    proc = subprocess.Popen(
                        cmd_cugan,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                    )
                    self._proc = proc

                    completed_frames = 0
                    last_log_pct = 0

                    for line in proc.stdout:
                        if self._cancelled:
                            proc.terminate()
                            break
                        if "done" in line:
                            completed_frames += 1
                            frame_pct = min(1.0, completed_frames / max(1, total_frames))
                            total_pct = 5 + frame_pct * 88
                            status = f"Real-CUGAN: frame {completed_frames}/{total_frames}"
                            if on_progress:
                                on_progress(total_pct, status)
                            log_pct = int(frame_pct * 10) * 10
                            if log_pct > last_log_pct:
                                last_log_pct = log_pct
                                _log(f"▓ {log_pct}%  |  Frame {completed_frames}/{total_frames} (Real-CUGAN)")

                    proc.wait()
                    self._proc = None

                    if self._cancelled:
                        _log("⚠ Upscaling cancelado pelo usuário.")
                        if on_complete:
                            on_complete(False, "Cancelado pelo usuário.")
                        return

                    if proc.returncode != 0:
                        if on_complete:
                            on_complete(False, f"Erro no processamento Real-CUGAN (código {proc.returncode}).")
                        return

                    _log("   ✓ Todos os frames processados pelo Real-CUGAN!")

                else:
                    _log(f"🤖 Processando {total_frames} frames com IA (Real-ESRGAN)...")
                    _log(f"   Isso pode demorar — GPU: {get_torch_device().upper()}")

                    import cv2
                    import numpy as np

                    frame_files = sorted([
                        f for f in os.listdir(tmp_frames_dir) if f.endswith('.png')
                    ])

                    last_log_pct = 0
                    for i, frame_file in enumerate(frame_files):
                        if self._cancelled:
                            break

                        frame_path = os.path.join(tmp_frames_dir, frame_file)
                        out_path = os.path.join(tmp_upscaled_dir, frame_file)

                        img = cv2.imread(frame_path, cv2.IMREAD_COLOR)
                        if img is None:
                            _log(f"⚠ Não foi possível ler: {frame_file}")
                            continue

                        try:
                            output, _ = upsampler.enhance(img, outscale=ai_scale)
                        except RuntimeError as e:
                            if "out of memory" in str(e).lower():
                                _log("⚠ VRAM insuficiente — reduzindo tile size...")
                                upsampler.tile = 256
                                try:
                                    output, _ = upsampler.enhance(img, outscale=ai_scale)
                                except Exception as e2:
                                    _log(f"✕ Falha no frame {frame_file}: {e2}")
                                    output = img
                            else:
                                _log(f"✕ Erro no frame {frame_file}: {e}")
                                output = img

                        cv2.imwrite(out_path, output, [cv2.IMWRITE_PNG_COMPRESSION, 1])

                        frame_pct = (i + 1) / total_frames
                        total_pct = 5 + frame_pct * 88
                        status = f"IA: frame {i+1}/{total_frames}"
                        if on_progress:
                            on_progress(total_pct, status)

                        log_pct = int(frame_pct * 10) * 10
                        if log_pct > last_log_pct:
                            last_log_pct = log_pct
                            _log(f"▓ {log_pct}%  |  Frame {i+1}/{total_frames}")

                    if self._cancelled:
                        _log("⚠ Upscaling cancelado pelo usuário.")
                        if on_complete:
                            on_complete(False, "Cancelado pelo usuário.")
                        return

                    del upsampler
                    try:
                        import torch
                        torch.cuda.empty_cache()
                    except Exception:
                        pass
                    _log("   ✓ Todos os frames processados pela IA!")

                # ── Step 4: Re-assemble video ───────────────────────────────
                _log("─────────────────────────")
                _log("🎬 Recompilando vídeo com os frames upscalados...")
                if on_progress:
                    on_progress(93, "Recompilando vídeo...")

                # Build post-AI filter chain (resizing, sharpening, color, anti-copyright)
                post_filters = []

                # If target resolution is specified and differs from the upscaled frame resolution:
                sample_frames = [f for f in os.listdir(tmp_upscaled_dir) if f.endswith('.png')]
                if sample_frames and target_width > 0 and target_height > 0:
                    try:
                        import cv2
                        sample_img = cv2.imread(os.path.join(tmp_upscaled_dir, sample_frames[0]))
                        if sample_img is not None:
                            cur_h, cur_w = sample_img.shape[:2]
                            if cur_w != target_width or cur_h != target_height:
                                post_filters.append(f"scale={target_width}:{target_height}:flags=lanczos")
                                _log(f"📐 Calibrando resolução final para {target_width}×{target_height} (Lanczos)")
                    except Exception:
                        pass

                if sharpen_filter:
                    post_filters.append(sharpen_filter)
                if color_filter:
                    post_filters.append(color_filter)
                if anti_copyright_filter:
                    post_filters.append(anti_copyright_filter)
                # Always convert to 10-bit
                post_filters.append("format=p010le")

                vf_string = ",".join(post_filters) if post_filters else None

                # Temporary video without audio
                tmp_video = os.path.join(tmp_dir, "tmp_video.mp4")

                # Build FFmpeg encode command
                encode_cmd = [
                    ffmpeg,
                    "-framerate", str(output_fps),
                    "-i", os.path.join(tmp_upscaled_dir, "frame_%08d.png"),
                ]
                if vf_string:
                    encode_cmd += ["-vf", vf_string]

                # Encoder
                if encoder == "nvidia":
                    encode_cmd += [
                        "-c:v", "hevc_nvenc",
                        "-rc", "vbr",
                        "-cq", str(crf),
                        "-b:v", "0",
                        "-preset", preset,
                        "-profile:v", "main10",
                        "-spatial_aq", "1",
                        "-temporal_aq", "1",
                    ]
                elif encoder == "amd":
                    encode_cmd += ["-c:v", "hevc_amf", "-rc", "cqp", "-qp_p", str(crf)]
                elif encoder == "intel":
                    encode_cmd += ["-c:v", "hevc_qsv", "-global_quality", str(crf)]
                else:
                    encode_cmd += ["-c:v", "libx265", "-crf", str(crf), "-preset", "slow"]

                encode_cmd += ["-an", "-y", tmp_video]

                result = subprocess.run(
                    encode_cmd, capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                if result.returncode != 0:
                    err_msg = result.stderr.decode(errors='replace') if result.stderr else "Erro desconhecido"
                    _log(f"✕ Erro ao recompilar: {err_msg[-300:]}")
                    if on_complete:
                        on_complete(False, "Erro ao recompilar o vídeo.")
                    return

                # ── Step 5: Merge audio ─────────────────────────────────────
                _log("🔊 Mesclando áudio original...")
                if on_progress:
                    on_progress(97, "Mesclando áudio...")

                audio_cmd = [
                    ffmpeg,
                    "-i", tmp_video,
                    "-i", input_path,
                    "-c:v", "copy",
                ]

                if anti_copyright_audio:
                    audio_cmd += ["-c:a", "aac", "-b:a", "320k", "-af", anti_copyright_audio]
                else:
                    audio_cmd += ["-c:a", "copy"]

                audio_cmd += [
                    "-map", "0:v:0",
                    "-map", "1:a?",        # ? = don't fail if no audio
                    "-shortest",
                    "-y", output_path,
                ]

                result = subprocess.run(
                    audio_cmd, capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                if result.returncode != 0:
                    # Fallback: use video without audio
                    _log("⚠ Erro ao mesclar áudio — salvando sem áudio...")
                    shutil.copy2(tmp_video, output_path)

                # ── Done ────────────────────────────────────────────────────
                if on_progress:
                    on_progress(100, "Concluído!")

                from upscaler import format_file_size
                output_size = os.path.getsize(output_path)
                size_label = format_file_size(output_size)
                _log(f"─────────────────────────")
                _log(f"✓ Upscaling com IA concluído! Tamanho: {size_label}")

                if on_complete:
                    on_complete(True, f"Upscaling com IA concluído! Tamanho: {size_label}")

            except Exception as e:
                import traceback
                _log(f"✕ Erro inesperado: {e}")
                _log(traceback.format_exc())
                if on_complete:
                    on_complete(False, f"Erro inesperado: {e}")
            finally:
                # Clean up temp files
                if tmp_frames_dir and os.path.exists(os.path.dirname(tmp_frames_dir)):
                    try:
                        shutil.rmtree(os.path.dirname(tmp_frames_dir), ignore_errors=True)
                    except Exception:
                        pass

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()


def _get_model_url(model_name: str) -> str:
    """
    Return a local path if the model is already cached, otherwise return the
    correct working GitHub release download URL.

    Tested working URLs (as of 2026-09):
      RealESRGAN_x4plus      -> v0.1.0
      RealESRGAN_x4plus_anime_6B -> v0.2.2.4  (v0.2.1 returns 404!)
      RealESRNet_x4plus      -> v0.1.1
      RealESRGAN_x2plus      -> v0.2.1
    """
    urls = {
        "RealESRGAN_x4plus":
            "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
        "RealESRGAN_x4plus_anime_6B":
            "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
        "RealESRNet_x4plus":
            "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.1/RealESRNet_x4plus.pth",
        "RealESRGAN_x2plus":
            "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth",
    }

    url = urls.get(model_name, urls["RealESRGAN_x4plus"])

    # ── Check common local cache locations first ──────────────────────────
    # realesrgan / basicsr auto-download to site-packages/weights or ~/.cache/realesrgan
    import site
    cache_dirs = []
    for sp in site.getsitepackages():
        cache_dirs.append(os.path.join(sp, "weights"))
    cache_dirs.append(os.path.join(os.path.expanduser("~"), ".cache", "realesrgan"))
    cache_dirs.append(os.path.join(os.path.expanduser("~"), ".cache", "basicsr"))

    filename = f"{model_name}.pth"
    for d in cache_dirs:
        local = os.path.join(d, filename)
        if os.path.isfile(local) and os.path.getsize(local) > 1024 * 1024:  # > 1 MB = valid file
            return local

    return url


def install_dependencies(on_log: Optional[Callable[[str], None]] = None) -> bool:
    """
    Install Real-ESRGAN Python dependencies via pip.
    Returns True if successful.
    """
    def _log(msg):
        if on_log:
            on_log(msg)

    packages = [
        "torch torchvision --index-url https://download.pytorch.org/whl/cu128",
        "basicsr",
        "realesrgan",
        "opencv-python",
        "facexlib",
        "gfpgan",
    ]

    _log("📦 Instalando dependências de IA...")

    for pkg in packages:
        _log(f"   Instalando: {pkg.split()[0]}...")
        try:
            result = subprocess.run(
                f"pip install {pkg}",
                shell=True, capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            if result.returncode != 0:
                _log(f"   ✕ Erro: {result.stderr[-200:]}")
                return False
            _log(f"   ✓ {pkg.split()[0]} instalado")
        except Exception as e:
            _log(f"   ✕ Exceção: {e}")
            return False

    _log("✓ Todas as dependências instaladas!")
    return True
