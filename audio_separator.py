"""
Audio Separator - Engine module
Handles audio/video source separation using Demucs (Meta AI).
Separates vocals, drums, bass, and other instruments.
"""

import subprocess
import os
import sys
import re
import json
import threading
import shutil
from typing import Callable, Optional

from upscaler import find_ffmpeg, find_ffprobe, format_time, format_file_size


# Separation modes
SEPARATION_MODES = {
    "🎤 Só a Voz (Vocals)": "vocals",
    "🎵 Só o Instrumental (Sem voz)": "no_vocals",
    "🎤+🔊 Voz + Efeitos (Sem música)": "vocals_sfx",
    "🎵🥁🎸🎤 Separação Completa (4 stems)": "all",
}

# Quality / Model options
DEMUCS_MODELS = {
    "HT Demucs (Melhor qualidade)": "htdemucs",
    "HT Demucs FT (Fine-tuned)": "htdemucs_ft",
    "HT Demucs 6 stems": "htdemucs_6s",
}

# Output formats
OUTPUT_FORMATS = {
    "WAV (Sem perda)": "wav",
    "MP3 (320kbps)": "mp3",
    "FLAC (Comprimido sem perda)": "flac",
}


AUDIO_EXTENSIONS = (
    ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".opus",
)

VIDEO_EXTENSIONS = (
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv",
    ".webm", ".m4v", ".mpeg", ".mpg", ".3gp", ".ts",
)


def get_audio_info(filepath: str) -> Optional[dict]:
    """Get audio metadata using ffprobe."""
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

        # Find audio stream
        audio_stream = None
        has_video = False
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "audio" and audio_stream is None:
                audio_stream = stream
            if stream.get("codec_type") == "video":
                has_video = True

        if not audio_stream:
            return None

        format_info = data.get("format", {})

        # Parse sample rate
        sample_rate = int(audio_stream.get("sample_rate", 44100))
        channels = int(audio_stream.get("channels", 2))
        codec = audio_stream.get("codec_name", "unknown")
        duration = float(format_info.get("duration", 0))
        bitrate = int(format_info.get("bit_rate", 0))

        return {
            "sample_rate": sample_rate,
            "channels": channels,
            "codec": codec,
            "duration": duration,
            "bitrate": bitrate,
            "file_size": os.path.getsize(filepath),
            "filename": os.path.basename(filepath),
            "has_video": has_video,
        }
    except Exception as e:
        print(f"Error getting audio info: {e}")
        return None


def check_demucs_installed() -> bool:
    """Check if demucs is installed."""
    try:
        import demucs
        return True
    except ImportError:
        pass
    try:
        result = subprocess.run(
            ["demucs", "--help"],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        return result.returncode == 0
    except Exception:
        return False


def install_demucs(on_log: Optional[Callable] = None) -> bool:
    """Install demucs via pip."""
    try:
        if on_log:
            on_log("📦 Instalando Demucs (Meta AI)... Isso pode demorar alguns minutos.")
            on_log("  → Baixando PyTorch + Demucs + dependências...")

        # Find usable pip or python executable
        pip_cmd = shutil.which("pip")
        if pip_cmd:
            cmd = [pip_cmd, "install", "-U", "demucs"]
        else:
            py_cmd = shutil.which("python") or shutil.which("py")
            if py_cmd:
                cmd = [py_cmd, "-m", "pip", "install", "-U", "demucs"]
            else:
                cmd = [sys.executable, "-m", "pip", "install", "-U", "demucs"]

        result = subprocess.run(
            cmd,
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            timeout=600,  # 10 minute timeout
        )

        if result.returncode == 0:
            if on_log:
                on_log("✓ Demucs instalado com sucesso!")
            return True
        else:
            if on_log:
                on_log(f"✕ Erro ao instalar: {result.stderr[-500:]}")
            return False
    except subprocess.TimeoutExpired:
        if on_log:
            on_log("✕ Timeout na instalação. Tente manualmente: pip install demucs")
        return False
    except Exception as e:
        if on_log:
            on_log(f"✕ Erro: {str(e)}")
        return False


class AudioSeparator:
    """Handles audio source separation using Demucs."""

    def __init__(self):
        self.ffmpeg_path = find_ffmpeg()
        self.process: Optional[subprocess.Popen] = None
        self._cancelled = False
        self._demucs_available = None  # Lazy check

    @property
    def is_demucs_available(self) -> bool:
        if self._demucs_available is None:
            self._demucs_available = check_demucs_installed()
        return self._demucs_available

    def refresh_demucs_check(self):
        """Force re-check of demucs availability."""
        self._demucs_available = check_demucs_installed()

    def cancel(self):
        """Cancel the current separation process."""
        self._cancelled = True
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass

    def extract_audio_from_video(
        self,
        video_path: str,
        output_wav: str,
        on_log: Optional[Callable] = None,
    ) -> bool:
        """Extract audio track from video file to WAV for processing."""
        if not self.ffmpeg_path:
            return False

        cmd = [
            self.ffmpeg_path,
            "-i", video_path,
            "-vn",  # No video
            "-acodec", "pcm_s16le",
            "-ar", "44100",
            "-ac", "2",
            "-y",
            output_wav
        ]

        try:
            if on_log:
                on_log("🎞️ Extraindo áudio do vídeo...")

            result = subprocess.run(
                cmd, capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            if result.returncode == 0:
                if on_log:
                    on_log("✓ Áudio extraído com sucesso")
                return True
            else:
                if on_log:
                    on_log(f"✕ Erro na extração: {result.stderr[-300:]}")
                return False
        except Exception as e:
            if on_log:
                on_log(f"✕ Erro: {str(e)}")
            return False

    def convert_output(
        self,
        input_wav: str,
        output_path: str,
        output_format: str,
        on_log: Optional[Callable] = None,
    ) -> bool:
        """Convert WAV output to desired format (mp3, flac, etc.)."""
        if not self.ffmpeg_path or output_format == "wav":
            # Just copy/rename if WAV
            if output_format == "wav" and input_wav != output_path:
                shutil.copy2(input_wav, output_path)
            return True

        if output_format == "mp3":
            cmd = [
                self.ffmpeg_path,
                "-i", input_wav,
                "-codec:a", "libmp3lame",
                "-b:a", "320k",
                "-y",
                output_path
            ]
        elif output_format == "flac":
            cmd = [
                self.ffmpeg_path,
                "-i", input_wav,
                "-codec:a", "flac",
                "-y",
                output_path
            ]
        else:
            return False

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            return result.returncode == 0
        except Exception:
            return False

    def _mix_stems(
        self,
        stem_paths: list[str],
        output_path: str,
        on_log: Optional[Callable] = None,
    ) -> bool:
        """Mix multiple stems together using FFmpeg."""
        if not self.ffmpeg_path or not stem_paths:
            return False

        if len(stem_paths) == 1:
            shutil.copy2(stem_paths[0], output_path)
            return True

        # Build FFmpeg command for mixing multiple audio files
        cmd = [self.ffmpeg_path]
        for path in stem_paths:
            cmd.extend(["-i", path])

        # amix filter to mix all inputs
        cmd.extend([
            "-filter_complex",
            f"amix=inputs={len(stem_paths)}:duration=longest:normalize=0",
            "-y",
            output_path
        ])

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            if result.returncode != 0 and on_log:
                on_log(f"⚠ Erro ao mixar stems: {result.stderr[-200:]}")
            return result.returncode == 0
        except Exception as e:
            if on_log:
                on_log(f"✕ Erro ao mixar: {str(e)}")
            return False

    def separate(
        self,
        input_path: str,
        output_dir: str,
        mode: str = "vocals",
        model: str = "htdemucs",
        output_format: str = "wav",
        on_progress: Optional[Callable[[float, str], None]] = None,
        on_complete: Optional[Callable[[bool, str], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ):
        """
        Separate audio sources from a file using Demucs Python API.

        Uses demucs.api.Separator directly and saves with soundfile,
        bypassing torchaudio.save (which has torchcodec DLL issues on Windows).
        """
        self._cancelled = False

        def _log(msg: str):
            if on_log:
                on_log(msg)

        def _run():
            temp_dir = None
            try:
                # Check demucs
                if not self.is_demucs_available:
                    _log("Demucs não encontrado. Iniciando instalação automática...")
                    success = install_demucs(on_log=_log if on_log else None)
                    if not success:
                        if on_complete:
                            on_complete(False, "Falha ao instalar Demucs. Instale manualmente: pip install demucs")
                        return
                    self.refresh_demucs_check()

                # Determine if we need to extract audio from video
                ext = os.path.splitext(input_path)[1].lower()
                is_video = ext in VIDEO_EXTENSIONS

                # Working directory for temp files
                temp_dir = os.path.join(output_dir, "_temp_separation")
                os.makedirs(temp_dir, exist_ok=True)

                # If video, extract audio first
                if is_video:
                    audio_input = os.path.join(temp_dir, "extracted_audio.wav")
                    success = self.extract_audio_from_video(input_path, audio_input, on_log=_log if on_log else None)
                    if not success:
                        if on_complete:
                            on_complete(False, "Não foi possível extrair áudio do vídeo.")
                        return
                else:
                    audio_input = input_path

                # Get audio info
                audio_info = get_audio_info(audio_input)
                if audio_info:
                    duration_str = format_time(audio_info["duration"])
                    _log(f"Duração: {duration_str} | {audio_info['sample_rate']}Hz | {audio_info['channels']}ch")
                else:
                    _log("⚠ Não foi possível obter info do áudio")

                if on_progress:
                    on_progress(5, "Carregando modelo Demucs...")

                _log(f"🧠 Modelo: {model}")
                _log(f"📊 Modo: {mode}")

                # ── Use Demucs Python API directly (v4.0.1) ──
                import torch
                import soundfile as sf
                from demucs.pretrained import get_model  # type: ignore
                from demucs.apply import apply_model  # type: ignore
                from demucs.separate import load_track  # type: ignore

                _log("Carregando modelo de IA...")
                demucs_model = get_model(model)
                demucs_model.eval()

                # Use GPU if available
                device = "cuda" if torch.cuda.is_available() else "cpu"
                _log(f"Dispositivo: {device.upper()}")
                demucs_model.to(device)

                if on_progress:
                    on_progress(15, "Carregando áudio...")

                _log("Carregando áudio...")
                wav = load_track(audio_input, demucs_model.audio_channels, demucs_model.samplerate)
                ref = wav.mean(0)
                wav = (wav - ref.mean()) / ref.std()

                if on_progress:
                    on_progress(20, "Separando fontes com IA...")

                _log("Executando separação (isso pode levar um momento)...")
                sources = apply_model(
                    demucs_model, wav[None], device=device,
                    progress=True, split=True
                )
                sources = sources * ref.std() + ref.mean()

                # sources shape: (1, num_sources, channels, samples)
                # demucs_model.sources: list of source names e.g. ['drums', 'bass', 'other', 'vocals']
                sources = sources[0]  # remove batch dim
                stem_names = demucs_model.sources

                if self._cancelled:
                    _log("⚠ Separação cancelada pelo usuário")
                    if on_complete:
                        on_complete(False, "Separação cancelada pelo usuário.")
                    return

                if on_progress:
                    on_progress(80, "Salvando arquivos...")

                _log(f"Stems disponíveis: {stem_names}")

                # Save each stem to temp WAV using soundfile
                samplerate = demucs_model.samplerate
                saved_stems = {}
                for i, stem_name in enumerate(stem_names):
                    wav_path = os.path.join(temp_dir, f"{stem_name}.wav")
                    audio_np = sources[i].cpu().numpy().T  # (channels, samples) → (samples, channels)
                    sf.write(wav_path, audio_np, samplerate)
                    saved_stems[stem_name] = wav_path
                    _log(f"  Stem salvo: {stem_name}")

                if on_progress:
                    on_progress(90, "Organizando arquivos de saída...")

                # Get base name for output files
                orig_basename = os.path.splitext(os.path.basename(input_path))[0]
                out_ext = f".{output_format}"
                output_files = []

                if mode == "vocals":
                    if "vocals" in saved_stems:
                        out_path = os.path.join(output_dir, f"{orig_basename}_vocals{out_ext}")
                        self.convert_output(saved_stems["vocals"], out_path, output_format, on_log=_log if on_log else None)
                        output_files.append(out_path)
                        _log(f"✓ Voz salva: {os.path.basename(out_path)}")

                elif mode == "no_vocals":
                    # Mix all stems except vocals
                    non_vocal = [p for k, p in saved_stems.items() if k != "vocals"]
                    if non_vocal:
                        mixed_path = os.path.join(temp_dir, "instrumental.wav")
                        self._mix_stems(non_vocal, mixed_path, on_log=_log if on_log else None)
                        out_path = os.path.join(output_dir, f"{orig_basename}_instrumental{out_ext}")
                        self.convert_output(mixed_path, out_path, output_format, on_log=_log if on_log else None)
                        output_files.append(out_path)
                        _log(f"✓ Instrumental salvo: {os.path.basename(out_path)}")

                elif mode == "vocals_sfx":
                    # Save vocals separately
                    if "vocals" in saved_stems:
                        out_path = os.path.join(output_dir, f"{orig_basename}_vocals{out_ext}")
                        self.convert_output(saved_stems["vocals"], out_path, output_format, on_log=_log if on_log else None)
                        output_files.append(out_path)
                        _log(f"✓ Voz salva: {os.path.basename(out_path)}")

                    # Mix vocals + other (SFX) — no drums, no bass
                    sfx_stems = [saved_stems[k] for k in ("vocals", "other") if k in saved_stems]
                    if sfx_stems:
                        mixed_path = os.path.join(temp_dir, "vocals_sfx.wav")
                        self._mix_stems(sfx_stems, mixed_path, on_log=_log if on_log else None)
                        out_path = os.path.join(output_dir, f"{orig_basename}_voz_efeitos{out_ext}")
                        self.convert_output(mixed_path, out_path, output_format, on_log=_log if on_log else None)
                        output_files.append(out_path)
                        _log(f"✓ Voz + Efeitos salvo: {os.path.basename(out_path)}")

                elif mode == "all":
                    stem_labels = {
                        "vocals": "vocals", "drums": "drums",
                        "bass": "bass", "other": "other",
                        "guitar": "guitar", "piano": "piano",
                    }
                    for stem_name, stem_path in saved_stems.items():
                        label = stem_labels.get(stem_name, stem_name)
                        out_path = os.path.join(output_dir, f"{orig_basename}_{label}{out_ext}")
                        self.convert_output(stem_path, out_path, output_format, on_log=_log if on_log else None)
                        output_files.append(out_path)
                        _log(f"✓ {label.capitalize()} salvo: {os.path.basename(out_path)}")

                if on_progress:
                    on_progress(100, "Concluído!")

                # Report
                total_size = sum(os.path.getsize(f) for f in output_files if os.path.exists(f))
                _log(f"─────────────────────────")
                _log(f"✓ Separação concluída!")
                _log(f"  {len(output_files)} arquivo(s) gerado(s)")
                _log(f"  Tamanho total: {format_file_size(total_size)}")

                if on_complete:
                    on_complete(True, f"Separação concluída! {len(output_files)} arquivo(s) salvo(s) em {output_dir}")

            except Exception as e:
                _log(f"✕ Exceção: {str(e)}")
                if on_complete:
                    on_complete(False, f"Erro: {str(e)}")
            finally:
                self.process = None
                # Cleanup temp
                if temp_dir and os.path.isdir(temp_dir):
                    try:
                        shutil.rmtree(temp_dir, ignore_errors=True)
                    except Exception:
                        pass

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
