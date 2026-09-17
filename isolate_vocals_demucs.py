"""
Urahara - Dedicated High-Performance Vocal Isolator (Demucs AI)
Extracts 100% pure human voice using Meta AI Demucs neural network,
completely removing background music, pianos, synths, drums, and instrumental tracks.
Runs on NVIDIA CUDA GPU (RTX series) or CPU.
"""

import sys
import os
import time
import json
import shutil
import tempfile
import subprocess
from pathlib import Path

# Ensure UTF-8 output
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def find_ffmpeg_bin() -> str:
    """Find bundled or system ffmpeg."""
    candidates = [
        Path(__file__).parent / "bin" / "ffmpeg.exe",
        Path(__file__).parent / "_internal" / "bin" / "ffmpeg.exe",
        Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    found = shutil.which("ffmpeg")
    return found if found else "ffmpeg"


def isolate_vocals(
    input_file: str,
    output_wav: str,
    model_name: str = "htdemucs",
    on_log=None,
    on_progress=None,
) -> bool:
    """
    Isolates pure vocals from an audio or video file, completely removing all
    background instruments (piano, guitars, drums, orchestra).
    """
    def _log(msg: str):
        if on_log:
            on_log(msg)
        else:
            print(f"[DEMUCS] {msg}", flush=True)

    def _prog(pct: float, status: str):
        if on_progress:
            on_progress(pct, status)
        else:
            print(f"[PROGRESS] {pct:.1f}% | {status}", flush=True)

    _log(f"Iniciando isolamento de voz por IA (Meta Demucs v4)...")
    _prog(5, "Iniciando IA Demucs...")

    temp_dir = Path(tempfile.mkdtemp(prefix="urahara_vocal_"))
    try:
        ffmpeg = find_ffmpeg_bin()
        input_path = Path(input_file).resolve()
        
        # Step 1: Extract 44.1kHz stereo audio to WAV if needed
        ext = input_path.suffix.lower()
        if ext != ".wav":
            _log("Extraindo áudio do arquivo...")
            extracted_wav = temp_dir / "extracted_source.wav"
            cmd_extract = [
                ffmpeg,
                "-i", str(input_path),
                "-vn",
                "-acodec", "pcm_s16le",
                "-ar", "44100",
                "-ac", "2",
                "-y",
                str(extracted_wav)
            ]
            res = subprocess.run(
                cmd_extract,
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if res.returncode != 0 or not extracted_wav.exists():
                _log(f"Erro ao extrair áudio com FFmpeg: {res.stderr.decode('utf-8', errors='ignore')[-300:]}")
                return False
            audio_source = extracted_wav
        else:
            audio_source = input_path

        _prog(15, "Carregando rede neural Demucs...")
        _log("Carregando pesos da rede neural Demucs...")

        import torch
        import soundfile as sf
        from demucs.pretrained import get_model
        from demucs.apply import apply_model

        device = "cuda" if torch.cuda.is_available() else "cpu"
        device_name = torch.cuda.get_device_name(0) if device == "cuda" else "Processador (CPU)"
        _log(f"Aceleração de Hardware: {device_name} [{device.upper()}]")

        t_load = time.time()
        model = get_model(model_name)
        model.eval()
        model.to(device)
        _log(f"Modelo {model_name} carregado em {time.time() - t_load:.2f}s")

        _prog(30, "Processando trilha de áudio...")
        _log("Carregando e normalizando áudio via soundfile...")
        import numpy as np

        audio_data, sr = sf.read(str(audio_source), dtype="float32")
        # Ensure 2 channels (stereo)
        if audio_data.ndim == 1:
            audio_data = np.stack([audio_data, audio_data], axis=1)
        elif audio_data.shape[1] > 2:
            audio_data = audio_data[:, :2]

        # Resample if sample rate doesn't match model samplerate (44100)
        target_sr = model.samplerate
        if sr != target_sr:
            _log(f"Convertendo taxa de amostragem de {sr}Hz para {target_sr}Hz...")
            import scipy.signal
            num_target_samples = int(len(audio_data) * target_sr / sr)
            audio_data = scipy.signal.resample(audio_data, num_target_samples)

        # Convert (samples, channels) -> torch (channels, samples)
        wav = torch.from_numpy(audio_data.T).float()
        ref = wav.mean(0)
        wav = (wav - ref.mean()) / (ref.std() + 1e-8)

        _prog(45, "Isolando voz e deletando instrumental/piano...")
        _log("Executando separação espectral (removendo 100% de piano, sintetizadores e música)...")
        t_sep = time.time()
        with torch.no_grad():
            sources = apply_model(model, wav[None], device=device, split=True, progress=False)

        sources = sources * ref.std() + ref.mean()
        sources = sources[0]  # Shape: (stems, channels, samples)

        if "vocals" not in model.sources:
            _log("Erro: O modelo carregado não possui stem 'vocals'.")
            return False

        vocal_idx = model.sources.index("vocals")
        vocal_audio = sources[vocal_idx].cpu().numpy().T  # (samples, channels)

        _prog(85, "Salvando voz cristalina isolada...")
        _log(f"Separação neural concluída em {time.time() - t_sep:.2f}s! Gravando arquivo...")

        output_path = Path(output_wav).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(output_path), vocal_audio, model.samplerate)

        _prog(100, "Voz isolada com sucesso!")
        _log(f"✓ Vocal isolado com sucesso salvo em: {output_path.name}")
        return True

    except Exception as e:
        _log(f"✕ Erro durante o isolamento vocal: {e}")
        import traceback
        _log(traceback.format_exc())
        return False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    """CLI entry point for subprocess execution."""
    if len(sys.argv) < 3:
        print("Usage: python isolate_vocals_demucs.py <input_file> <output_wav> [model_name]")
        sys.exit(1)

    input_f = sys.argv[1]
    output_f = sys.argv[2]
    model_f = sys.argv[3] if len(sys.argv) > 3 else "htdemucs"

    success = isolate_vocals(input_f, output_f, model_name=model_f)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
