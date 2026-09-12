"""
Video Upscaler - Engine module
Handles video upscaling using FFmpeg with various scaling algorithms.
Also re-exports AI upscaling utilities from ai_upscaler.
"""

import subprocess
import os
import re
import json
import threading
from dataclasses import dataclass
from typing import Callable, Optional

# Re-export AI models dict so app.py only needs to import from upscaler
try:
    from ai_upscaler import AI_MODELS, AIVideoUpscaler, check_realesrgan_available, install_dependencies as install_ai_dependencies
    AI_AVAILABLE = True
except ImportError:
    AI_MODELS = {}
    AI_AVAILABLE = False
    AIVideoUpscaler = None
    check_realesrgan_available = lambda: (False, "ai_upscaler.py não encontrado")
    install_ai_dependencies = None


@dataclass
class VideoInfo:
    """Stores metadata about a video file."""
    width: int
    height: int
    duration: float
    codec: str
    fps: float
    bitrate: int
    file_size: int  # in bytes
    filename: str

    @property
    def resolution_label(self) -> str:
        if self.height >= 2160:
            return "4K"
        elif self.height >= 1440:
            return "2K / QHD"
        elif self.height >= 1080:
            return "Full HD"
        elif self.height >= 720:
            return "HD"
        elif self.height >= 480:
            return "SD"
        else:
            return f"{self.width}x{self.height}"

    @property
    def file_size_label(self) -> str:
        size = self.file_size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


# Available target resolutions (base height)
RESOLUTIONS = {
    "Original": 0,
    "4K (2160p)": 2160,
    "2K QHD (1440p)": 1440,
    "Full HD (1080p)": 1080,
    "HD (720p)": 720,
}

# Scaling algorithms
ALGORITHMS = {
    "Lanczos (Melhor qualidade)": "lanczos",
    "Bicubic (Boa qualidade)": "bicubic",
    "Bilinear (Rápido)": "bilinear",
    "Spline (Balanceado)": "spline",
}

# Output quality presets
QUALITY_PRESETS = {
    "Ultra (Perfeito 4K)": {"crf": 16, "preset": "p6"},  # p6 é quase idêntico ao p7 mas muito mais rápido
    "Alta (Arquivo maior)": {"crf": 19, "preset": "p5"},
    "Média (Balanceado)": {"crf": 23, "preset": "p4"},
    "Baixa (Arquivo menor)": {"crf": 28, "preset": "p2"},
}

# Aspect ratios - (width_ratio, height_ratio) or None for original
ASPECT_RATIOS = {
    "Original": None,
    "16:9 (Widescreen)": (16, 9),
    "9:16 (Vertical/Reels)": (9, 16),
    "1:1 (Quadrado)": (1, 1),
    "4:3 (Clássico)": (4, 3),
    "21:9 (Ultrawide)": (21, 9),
}

# FPS options
FPS_OPTIONS = {
    "Original": None,
    "24 fps (Cinema)": 24,
    "30 fps": 30,
    "60 fps (Suave)": 60,
    "120 fps": 120,
}

# Sharpening options (unsharp filter)
SHARPEN_OPTIONS = {
    "Nenhum": None,
    "Leve (Suave)": "unsharp=3:3:0.5:3:3:0.0",
    "Médio (Recomendado)": "unsharp=5:5:0.8:5:5:0.0",
    "Forte (Detalhes)": "unsharp=7:7:1.2:7:7:0.0",
    "Extremo (Super Nitidez)": "unsharp=9:9:1.5:9:9:0.0",
}

# Color Enhancements (saturation, contrast, brightness)
COLOR_ENHANCEMENTS = {
    "Nenhum": None,
    "Falso HDR (Cores e Contraste)": "eq=saturation=1.25:contrast=1.15:gamma=1.05",
    "Cyberpunk (Neon)": "colorchannelmixer=rr=1.2:gg=0.8:bb=1.2,eq=saturation=1.3:contrast=1.1",
    "Quente (Pôr do Sol)": "colorchannelmixer=rr=1.1:bb=0.9,eq=saturation=1.2",
    "Frio (Inverno/Matrix)": "colorchannelmixer=rr=0.9:bb=1.1,eq=saturation=1.1",
    "Cinema (Saturação +15%)": "eq=saturation=1.15:contrast=1.1:brightness=0.0",
    "Vibrante (Saturação +30%)": "eq=saturation=1.3:contrast=1.15:brightness=0.02",
    "Vintage (Preto e Branco)": "hue=s=0,eq=contrast=1.2",
}

# Denoising options (hqdn3d filter)
DENOISE_OPTIONS = {
    "Nenhum": None,
    "Leve (Limpar grãos)": "hqdn3d=1.5:1.5:3:3",
    "Forte (Imagem lisa)": "hqdn3d=4:4:6:6",
}

# Available Encoders (Hardware Acceleration)
ENCODERS = {
    "NVIDIA (Aceleração NVENC)": "nvidia",
    "AMD (Aceleração AMF)": "amd",
    "Intel (Aceleração QSV)": "intel",
    "CPU (Software - Lento)": "cpu",
}

# Anti-Copyright subtle modifications (bypasses Content ID)
ANTI_COPYRIGHT_OPTIONS = {
    "Nenhum": None,
    "Sutil (Recomendado)": {
        "video": "noise=alls=1:allf=t+u,hue=h=0.02", # Tiny noise + invisible hue shift
        "audio": "atempo=1.02" # 2% speed up
    },
    "Forte (Maior segurança)": {
        "video": "noise=alls=2:allf=t+u,hue=h=-0.04,eq=brightness=0.01",
        "audio": "atempo=1.04" # 4% speed up
    }
}



def compute_target_dimensions(
    base_height: int,
    aspect_ratio: tuple | None,
    original_width: int = 0,
    original_height: int = 0,
) -> tuple[int, int]:
    """
    Compute target width and height from base resolution and aspect ratio.
    
    For landscape ratios (16:9, 4:3, 21:9): base_height is the height.
    For portrait ratios (9:16): base_height becomes the width (shorter side).
    For 1:1: both sides equal base_height.
    For Original: preserves the source aspect ratio.
    """
    if base_height <= 0:
        # Original resolution requested
        if aspect_ratio is None:
            target_w = original_width if original_width > 0 else 1920
            target_h = original_height if original_height > 0 else 1080
        else:
            ratio_w, ratio_h = aspect_ratio
            ref_h = original_height if original_height > 0 else 1080
            ref_w = original_width if original_width > 0 else 1920
            if ratio_w >= ratio_h:
                target_h = ref_h
                target_w = round(ref_h * ratio_w / ratio_h)
            else:
                target_w = min(ref_w, ref_h)
                target_h = round(target_w * ratio_h / ratio_w)
    elif aspect_ratio is None:
        # Keep original aspect ratio
        if original_width > 0 and original_height > 0:
            short_side = min(original_width, original_height)
            scale = base_height / short_side
            target_w = round(original_width * scale)
            target_h = round(original_height * scale)
        else:
            # Fallback to 16:9
            target_w = round(base_height * 16 / 9)
            target_h = base_height
    else:
        ratio_w, ratio_h = aspect_ratio
        if ratio_w >= ratio_h:
            # Landscape or square: height = base
            target_h = base_height
            target_w = round(base_height * ratio_w / ratio_h)
        else:
            # Portrait: width = base (shorter side)
            target_w = base_height
            target_h = round(base_height * ratio_h / ratio_w)

    # Ensure even dimensions (required by h264)
    target_w += target_w % 2
    target_h += target_h % 2
    return target_w, target_h


def find_ffplay() -> Optional[str]:
    """Find FFplay executable."""
    try:
        result = subprocess.run(
            ["ffplay", "-version"],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        if result.returncode == 0:
            return "ffplay"
    except FileNotFoundError:
        pass

    if os.name == 'nt':
        common_paths = [
            os.path.join(os.environ.get('PROGRAMFILES', ''), 'ffmpeg', 'bin', 'ffplay.exe'),
            os.path.join(os.environ.get('LOCALAPPDATA', ''), 'ffmpeg', 'bin', 'ffplay.exe'),
            os.path.join(os.path.expanduser('~'), 'ffmpeg', 'bin', 'ffplay.exe'),
            r"C:\ffmpeg\bin\ffplay.exe",
        ]
        for path in common_paths:
            if os.path.isfile(path):
                return path

    return None


def find_ffmpeg() -> Optional[str]:
    """Find FFmpeg executable in system PATH or common locations."""
    # Try system PATH first
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        if result.returncode == 0:
            return "ffmpeg"
    except FileNotFoundError:
        pass

    # Common Windows locations
    if os.name == 'nt':
        common_paths = [
            os.path.join(os.environ.get('PROGRAMFILES', ''), 'ffmpeg', 'bin', 'ffmpeg.exe'),
            os.path.join(os.environ.get('LOCALAPPDATA', ''), 'ffmpeg', 'bin', 'ffmpeg.exe'),
            os.path.join(os.path.expanduser('~'), 'ffmpeg', 'bin', 'ffmpeg.exe'),
            r"C:\ffmpeg\bin\ffmpeg.exe",
        ]
        for path in common_paths:
            if os.path.isfile(path):
                return path

    return None


def find_ffprobe() -> Optional[str]:
    """Find FFprobe executable."""
    try:
        result = subprocess.run(
            ["ffprobe", "-version"],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        if result.returncode == 0:
            return "ffprobe"
    except FileNotFoundError:
        pass

    if os.name == 'nt':
        common_paths = [
            os.path.join(os.environ.get('PROGRAMFILES', ''), 'ffmpeg', 'bin', 'ffprobe.exe'),
            os.path.join(os.environ.get('LOCALAPPDATA', ''), 'ffmpeg', 'bin', 'ffprobe.exe'),
            os.path.join(os.path.expanduser('~'), 'ffmpeg', 'bin', 'ffprobe.exe'),
            r"C:\ffmpeg\bin\ffprobe.exe",
        ]
        for path in common_paths:
            if os.path.isfile(path):
                return path

    return None


def get_video_info(filepath: str) -> Optional[VideoInfo]:
    """Get video metadata using ffprobe."""
    ffprobe = find_ffprobe()
    if not ffprobe:
        return None

    try:
        cmd = [
            ffprobe,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            filepath
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )

        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)

        # Find video stream
        video_stream = None
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                video_stream = stream
                break

        if not video_stream:
            return None

        format_info = data.get("format", {})

        # Parse FPS from r_frame_rate (e.g., "30000/1001")
        fps_str = video_stream.get("r_frame_rate", "30/1")
        if "/" in fps_str:
            num, den = fps_str.split("/")
            fps = float(num) / float(den) if float(den) != 0 else 30.0
        else:
            fps = float(fps_str)

        return VideoInfo(
            width=int(video_stream.get("width", 0)),
            height=int(video_stream.get("height", 0)),
            duration=float(format_info.get("duration", 0)),
            codec=video_stream.get("codec_name", "unknown"),
            fps=round(fps, 2),
            bitrate=int(format_info.get("bit_rate", 0)),
            file_size=os.path.getsize(filepath),
            filename=os.path.basename(filepath)
        )
    except Exception as e:
        print(f"Error getting video info: {e}")
        return None


class VideoUpscaler:
    """Handles the video upscaling process using FFmpeg."""

    def __init__(self):
        self.ffmpeg_path = find_ffmpeg()
        self.ffplay_path = find_ffplay()
        self.process: Optional[subprocess.Popen] = None
        self._cancelled = False

    @property
    def is_available(self) -> bool:
        return self.ffmpeg_path is not None

    def cancel(self):
        """Cancel the current upscaling process."""
        self._cancelled = True
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass

    def upscale(
        self,
        input_path: str,
        output_path: str,
        target_width: int,
        target_height: int,
        algorithm: str = "lanczos",
        encoder: str = "nvidia",
        crf: int = 23,
        preset: str = "medium",
        aspect_ratio: tuple | None = None,
        target_fps: int | None = None,
        sharpen_filter: str | None = None,
        color_filter: str | None = None,
        denoise_filter: str | None = None,
        anti_copyright: str = "Nenhum",
        on_progress: Optional[Callable[[float, str], None]] = None,
        on_complete: Optional[Callable[[bool, str], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ):
        """
        Upscale a video file.
        
        Args:
            input_path: Path to input video
            output_path: Path for output video
            target_width: Target width in pixels
            target_height: Target height in pixels
            algorithm: Scaling algorithm (lanczos, bicubic, bilinear, spline)
            encoder: Encoder string (nvidia, amd, intel, cpu)
            crf: Constant Rate Factor (quality, lower = better)
            preset: Encoding preset (slow, medium, fast)
            aspect_ratio: Target aspect ratio as (w, h) tuple, or None for original
            target_fps: Target FPS, or None to keep original
            sharpen_filter: FFmpeg unsharp filter string, or None
            color_filter: Vibrance/Saturation filter string, or None
            denoise_filter: Denoise filter string, or None
            on_progress: Callback(progress_percent, status_message)
            on_complete: Callback(success, message)
            on_log: Callback(log_message) for real-time console output
        """
        self._cancelled = False

        def _log(msg: str):
            if on_log:
                on_log(msg)

        def _read_stderr(proc):
            """Read stderr in a separate thread to capture FFmpeg output."""
            try:
                for line in proc.stderr:
                    line = line.strip()
                    if line:
                        _log(f"  {line}")
            except Exception:
                pass

        def _run():
            try:
                if not self.ffmpeg_path:
                    if on_complete:
                        on_complete(False, "FFmpeg não encontrado!")
                    return

                # Get video duration for progress calculation
                _log("Obtendo informações do vídeo...")
                video_info = get_video_info(input_path)
                duration = video_info.duration if video_info else 0

                if duration > 0:
                    _log(f"Duração: {format_time(duration)} | {video_info.width}x{video_info.height}")
                else:
                    _log("⚠ Não foi possível determinar a duração do vídeo")

                # ── Build filter chain ──
                filters = []

                # 1. Crop for aspect ratio change (if needed)
                if aspect_ratio is not None and video_info:
                    ratio_w, ratio_h = aspect_ratio
                    target_ratio = ratio_w / ratio_h
                    source_ratio = video_info.width / video_info.height

                    if abs(target_ratio - source_ratio) > 0.01:
                        if target_ratio > source_ratio:
                            # Target is wider → crop height
                            crop_h = int(video_info.width / target_ratio)
                            crop_w = video_info.width
                        else:
                            # Target is taller → crop width
                            crop_w = int(video_info.height * target_ratio)
                            crop_h = video_info.height
                        # Ensure even
                        crop_w -= crop_w % 2
                        crop_h -= crop_h % 2
                        filters.append(f"crop={crop_w}:{crop_h}")
                        _log(f"Crop: {crop_w}×{crop_h} (ajuste de proporção)")

                # 2. Scale to target resolution
                filters.append(f"scale={target_width}:{target_height}:flags={algorithm}")

                # 3. FPS change
                if target_fps is not None:
                    filters.append(f"fps={target_fps}")
                    _log(f"FPS: {target_fps}")

                # 4. Sharpening
                if sharpen_filter:
                    filters.append(sharpen_filter)
                    _log(f"Sharpening: Aplicado")

                # 5. Denoise (Melhor antes da cor)
                if denoise_filter:
                    filters.insert(0, denoise_filter)
                    _log(f"Denoise: Aplicado")

                # 6. Color Enhancement
                if color_filter:
                    filters.append(color_filter)
                    _log(f"Cores: Melhoradas")

                # 7. Convert to 10-bit for perfect quality (prevents banding)
                filters.append("format=p010le")

                # Anti-Copyright Video Filters
                ac_options = ANTI_COPYRIGHT_OPTIONS.get(anti_copyright)
                if ac_options and ac_options.get("video"):
                    filters.append(ac_options["video"])
                    _log(f"Filtro Anti-Copyright: {anti_copyright}")

                vf_string = ",".join(filters)
                _log(f"Filtros: {vf_string}")

                # Build FFmpeg command based on selected encoder
                if encoder == "nvidia":
                    cmd = [
                        self.ffmpeg_path,
                        "-hwaccel", "cuda", # Força a decodificação no hardware da NVIDIA
                        "-i", input_path,
                        "-vf", vf_string,
                        "-c:v", "hevc_nvenc",
                        "-rc", "vbr",
                        "-cq", str(crf),
                        "-b:v", "0",
                        "-preset", preset,
                        "-profile:v", "main10",
                        "-spatial_aq", "1",
                        "-temporal_aq", "1"
                    ]
                elif encoder == "amd":
                    amf_preset = "quality" if preset in ["p6", "p5"] else ("balanced" if preset == "p4" else "speed")
                    cmd = [
                        self.ffmpeg_path,
                        "-i", input_path,
                        "-vf", vf_string,
                        "-c:v", "hevc_amf",
                        "-rc", "cqp",
                        "-qp_p", str(crf),
                        "-qp_i", str(crf),
                        "-quality", amf_preset
                    ]
                elif encoder == "intel":
                    qsv_preset = "veryslow" if preset in ["p6", "p5"] else ("medium" if preset == "p4" else "fast")
                    cmd = [
                        self.ffmpeg_path,
                        "-i", input_path,
                        "-vf", vf_string,
                        "-c:v", "hevc_qsv",
                        "-global_quality", str(crf),
                        "-preset", qsv_preset
                    ]
                else: # cpu
                    cpu_preset = "slow" if preset in ["p6", "p5"] else ("medium" if preset == "p4" else "fast")
                    cmd = [
                        self.ffmpeg_path,
                        "-i", input_path,
                        "-vf", vf_string,
                        "-c:v", "libx265",
                        "-crf", str(crf),
                        "-preset", cpu_preset
                    ]

                # Apply Anti-Copyright audio filter if selected
                if ac_options and ac_options.get("audio"):
                    cmd.extend([
                        "-c:a", "aac",
                        "-b:a", "320k",
                        "-af", ac_options["audio"]
                    ])
                else:
                    cmd.extend([
                        "-c:a", "copy"
                    ])

                cmd.extend([
                    "-progress", "pipe:1",
                    "-stats_period", "0.5",
                    "-y",  # Overwrite output
                    output_path
                ])

                _log(f"Executando FFmpeg...")
                if on_progress:
                    on_progress(0, "Iniciando upscaling...")

                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )

                # Read stderr in background thread (FFmpeg encoding info)
                stderr_thread = threading.Thread(
                    target=_read_stderr, args=(self.process,), daemon=True
                )
                stderr_thread.start()

                # Parse progress from FFmpeg stdout (-progress pipe:1)
                current_time = 0
                frame_count = 0
                speed = ""
                last_progress_log = 0

                for line in self.process.stdout:
                    if self._cancelled:
                        break

                    line = line.strip()
                    if not line:
                        continue

                    if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                        try:
                            val = line.split("=")[1]
                            if val and val != "N/A":
                                time_val = int(val)
                                if time_val > 0:
                                    # out_time_us is in microseconds, out_time_ms in milliseconds
                                    if "us" in line.split("=")[0]:
                                        current_time = time_val / 1_000_000
                                    else:
                                        current_time = time_val / 1_000_000
                                    
                                    if duration > 0:
                                        progress = min((current_time / duration) * 100, 99.9)
                                        pos_label = format_time(current_time)
                                        total_label = format_time(duration)
                                        status = f"Processando: {pos_label} / {total_label}"
                                        if speed:
                                            status += f"  ({speed})"
                                        if on_progress:
                                            on_progress(progress, status)

                                        # Log every ~5% progress
                                        progress_5 = int(progress // 5)
                                        if progress_5 > last_progress_log:
                                            last_progress_log = progress_5
                                            _log(f"▓ {progress:.1f}%  |  {pos_label} / {total_label}  |  {speed}")
                        except (ValueError, IndexError):
                            pass

                    elif line.startswith("frame="):
                        try:
                            val = line.split("=")[1]
                            if val and val != "N/A":
                                frame_count = int(val)
                        except (ValueError, IndexError):
                            pass

                    elif line.startswith("speed="):
                        try:
                            speed = line.split("=")[1].strip()
                        except (ValueError, IndexError):
                            pass

                    elif line.startswith("progress=end"):
                        _log(f"▓ 100%  |  Encoding finalizado  |  Frames: {frame_count}")
                        if on_progress:
                            on_progress(100, "Finalizando...")

                self.process.wait()
                stderr_thread.join(timeout=5)

                if self._cancelled:
                    if os.path.exists(output_path):
                        try:
                            os.remove(output_path)
                        except Exception:
                            pass
                    _log("⚠ Upscaling cancelado pelo usuário")
                    if on_complete:
                        on_complete(False, "Upscaling cancelado pelo usuário.")
                    return

                if self.process.returncode == 0:
                    output_size = os.path.getsize(output_path)
                    size_label = format_file_size(output_size)
                    _log(f"✓ Arquivo salvo: {size_label}")
                    if on_complete:
                        on_complete(True, f"Upscaling concluído! Tamanho: {size_label}")
                else:
                    _log(f"✕ FFmpeg retornou código de erro: {self.process.returncode}")
                    if on_complete:
                        on_complete(False, f"FFmpeg retornou erro (código {self.process.returncode})")

            except Exception as e:
                _log(f"✕ Exceção: {str(e)}")
                if on_complete:
                    on_complete(False, f"Erro: {str(e)}")
            finally:
                self.process = None

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()


    def compare_videos(self, input_path: str, output_path: str):
        """Launch ffplay with the original as primary input for robust seeking and audio."""
        if not self.ffplay_path:
            return False

        def _esc_filter_path(p: str) -> str:
            """
            Properly escape Windows paths for FFmpeg filters.
            Filters like 'movie' have their own escaping rules for colons and backslashes.
            """
            # 1. Replace backslashes with forward slashes
            p = p.replace('\\', '/')
            # 2. Escape colons (must be C\: for movie filter)
            p = p.replace(':', '\\:')
            # 3. Escape single quotes if any
            p = p.replace("'", "'\\\\''")
            return p

        # Use the original video as lead to ensure seeking and audio work out-of-the-box
        # We load the upscaled video via the movie filter
        esc_upscaled = _esc_filter_path(output_path)
        
        # Scale both to 720p height for side-by-side comparison
        filter_chain = (
            f"movie='{esc_upscaled}'[ups]; "
            f"[in]scale=-1:720[orig]; "
            f"[ups]scale=-1:720[ups_scaled]; "
            f"[orig][ups_scaled]hstack"
        )

        cmd = [
            self.ffplay_path,
            "-i", input_path,
            "-vf", filter_chain,
            "-window_title", "Comparação: Esquerda (Antes) | Direita (Depois)  [Espaço=Pausar | Click na barra=Buscar]",
            "-autoexit"
        ]

        try:
            # We use CREATE_NO_WINDOW to prevent a terminal from appearing
            subprocess.Popen(
                cmd,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            return True
        except Exception as e:
            print(f"Error launching comparison: {e}")
            return False

    def preview_video(
        self,
        input_path: str,
        target_width: int,
        target_height: int,
        algorithm: str = "lanczos",
        aspect_ratio: tuple | None = None,
        target_fps: int | None = None,
        sharpen_filter: str | None = None,
        color_filter: str | None = None,
        denoise_filter: str | None = None,
        anti_copyright: str = "Nenhum",
    ):
        """Preview the video with the selected filters applied using ffplay."""
        if not self.ffplay_path:
            return False

        video_info = get_video_info(input_path)

        filters = []
        if aspect_ratio is not None and video_info:
            ratio_w, ratio_h = aspect_ratio
            target_ratio = ratio_w / ratio_h
            source_ratio = video_info.width / video_info.height

            if abs(target_ratio - source_ratio) > 0.01:
                if target_ratio > source_ratio:
                    crop_h = int(video_info.width / target_ratio)
                    crop_w = video_info.width
                else:
                    crop_w = int(video_info.height * target_ratio)
                    crop_h = video_info.height
                crop_w -= crop_w % 2
                crop_h -= crop_h % 2
                filters.append(f"crop={crop_w}:{crop_h}")

        # Para preview, podemos limitar a 1080p ou 720p se ficar muito lento, 
        # mas vamos tentar a resolução pedida ou limitar a tela.
        # Usamos apenas scale normal para preview pois scale_cuda precisaria do decodificador cuda configurado
        filters.append(f"scale={target_width}:{target_height}:flags={algorithm}")

        if target_fps is not None:
            filters.append(f"fps={target_fps}")

        if sharpen_filter:
            filters.append(sharpen_filter)

        if denoise_filter:
            filters.insert(0, denoise_filter)

        if color_filter:
            filters.append(color_filter)
            
        vf_string = ",".join(filters) if filters else ""

        # Calcular tamanho da janela para não abrir em tela cheia (máx 1280x720)
        window_w = 1280
        window_h = 720
        if target_height > 0:
            target_ratio = target_width / target_height
            if target_ratio > (1280 / 720):
                window_w = 1280
                window_h = int(1280 / target_ratio)
            else:
                window_h = 720
                window_w = int(720 * target_ratio)

        cmd = [
            self.ffplay_path,
            "-i", input_path,
            "-x", str(window_w),
            "-y", str(window_h),
            "-window_title", "Pré-visualização (Espaço = Pausar | Esc = Sair)"
        ]

        # Anti-Copyright Video Filters
        ac_options = ANTI_COPYRIGHT_OPTIONS.get(anti_copyright)
        if ac_options and ac_options.get("video"):
            filters.append(ac_options["video"])
            
        vf_string = ",".join(filters) if filters else ""
        
        if vf_string:
            cmd.extend(["-vf", vf_string])

        # Anti-Copyright Audio Filter for preview
        if ac_options and ac_options.get("audio"):
            cmd.extend(["-af", ac_options["audio"]])

        try:
            subprocess.Popen(
                cmd,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            return True
        except Exception as e:
            print(f"Error launching preview: {e}")
            return False


def format_time(seconds: float) -> str:
    """Format seconds into HH:MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_file_size(size_bytes: int) -> str:
    """Format file size in human readable format."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"
