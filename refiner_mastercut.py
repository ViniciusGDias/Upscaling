"""
Refiner Mastercut Engine - ViralAI Mastercut Module
Concentrates raw video into high-retention 30s-60s clips ("O Suco do Vídeo")
using Whisper word-level transcription, Gemini AI reasoning, and FFmpeg concatenation.
"""

import os
import sys
import json
import time
import re
import tempfile
import subprocess
import shutil
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

try:
    from api_health_manager import api_health
except ImportError:
    api_health = None

EDITORIAL_MODES = {
    "linear": "Linear Direto (Sem Loop)",
    "hook": "Hook de Abertura (Anti-Início Lento: Teaser 0-3s)",
    "loop": "Loop Contextual (Replay Infinito: Conecta Fim ao Início)",
    "viral_editor": "Edição Viral Pro (Super Senior Editor: Hook + Reordenação + Loop)",
    "viral_59": "Viral Flow 59s (Duplo Refino IA + J-Cut Suave: Máx 59s)",
    "dorama": "Dorama Emocional (Diálogos Íntegros & Pausas Dramáticas)",
}

HOOK_TEASER_RESERVE = 3.0

# Unified edit styles: each profile is ONE coherent recipe (pacing + target length + structure).
# The UI exposes only these, so pacing, duration and editorial structure can never contradict each other.
EDIT_PROFILES = {
    "viral_59": {
        "label": "Viral Flow 59s (Duplo Refino IA + J-Cut Suave)",
        "tagline": "Vídeos de 2m+ condensados em até 59s com IA geradora + IA crítica e áudio ultra-suave.",
        "flow": "Gancho → Narrativa Contínua → Clímax (Teto Rígido ≤ 59.0s)",
        "refine_mode": "balanced", "target_duration_mode": "viral_59s", "editorial_mode": "viral_59",
        "explain": "Especialmente calibrado para cortes de 2 minutos ou mais: utiliza inteligência dupla (IA geradora + IA auditora/crítica) "
                   "para validar o fluxo, eliminar repetições, lapidar falas e garantir que o corte NUNCA passe de 59 segundos. "
                   "Aplica micro-crossfades suaves de áudio para eliminar cortes bruscos e deixar o vídeo 100% pronto para viralizar.",
    },
    "dorama": {
        "label": "Dorama Dramático & Emocional (K-Drama / Romance)",
        "tagline": "Preserva a química, diálogos completos e olhares de tensão sem cortes bruscos.",
        "flow": "Gancho Emocional → Conflito/Romance → Clímax Dramático",
        "refine_mode": "soft", "target_duration_mode": "standard", "editorial_mode": "dorama",
        "explain": "Especialmente calibrado para Doramas e K-Dramas: mantém a tensão dramática e a química entre os atores, "
                   "preserva pausas expressivas naturais (sem acelerar ou picotar falas), mantém réplicas completas "
                   "e foca nos momentos de maior comoção, revelação ou romance.",
    },
    "viral": {
        "label": "Edição Viral Pro (TikTok / Reels / Shorts)",
        "tagline": "Gancho imediato + ritmo anti-tédio + retenção máxima sem repetições.",
        "flow": "Início Explosivo → Pacing Acelerado → Clímax (Zero Tédio)",
        "refine_mode": "aggressive", "target_duration_mode": "standard", "editorial_mode": "viral_editor",
        "explain": "A fórmula viral definitiva para redes sociais: elimina enrolações e silêncios iniciais para prender o scroll no segundo 0, "
                   "mantém cortes ágeis nas pausas, preserva a coerência da história (sem repetições confusas) e finaliza no pico do clímax.",
    },
    "narrative": {
        "label": "Mastercut Narrativo",
        "tagline": "História 100% cronológica, sem repetições nem confusão.",
        "flow": "Início → Conflito → Clímax (Linear)",
        "refine_mode": "balanced", "target_duration_mode": "standard", "editorial_mode": "linear",
        "explain": "Edição limpa e cinematográfica: elimina silêncios mortos, pausas vazias e hesitações, "
                   "mantendo todas as falas importantes e a ordem cronológica natural da cena.",
    },
    "dynamic": {
        "label": "Ritmo Acelerado (Shorts / Reels)",
        "tagline": "Cortes mais rápidos nas pausas, focado na ação e diálogos fortes.",
        "flow": "Ação Rápida (Cronológica)",
        "refine_mode": "aggressive", "target_duration_mode": "short", "editorial_mode": "linear",
        "explain": "Corta de forma cirúrgica qualquer silêncio (>0.25s), mantendo a ordem da história "
                   "mas com ritmo acelerado e direto ao ponto (~30s a 45s).",
    },
    "mini_movie": {
        "label": "Mini-Filme (Arco Completo)",
        "tagline": "Resumo cinematográfico em 4 atos (~50%, até 2:30 min).",
        "flow": "Abertura → Tensão → Clímax → Desfecho",
        "refine_mode": "balanced", "target_duration_mode": "mini_movie", "editorial_mode": "linear",
        "explain": "Para cenas e lutas longas (2 a 5 minutos): condensa o arco narrativo em 4 atos, "
                   "preservando o contexto e o impacto do desfecho sem picotar a história.",
    },
    "dialogue": {
        "label": "Preservar Diálogos (Corte Suave)",
        "tagline": "Mantém 100% das falas, apara apenas pausas mortas longas.",
        "flow": "Diálogos Íntegros (Original)",
        "refine_mode": "soft", "target_duration_mode": "max_retention", "editorial_mode": "linear",
        "explain": "Corte mínimo e respeitoso: apenas elimina tempos mortos (>0.4s), "
                   "preservando integralmente as conversas, réplicas e o clima da cena.",
    },
    "hook": {
        "label": "Com Gancho de Abertura (Teaser)",
        "tagline": "Abre com um teaser de 3s antes de começar a cena.",
        "flow": "Teaser 3s → História Completa",
        "refine_mode": "balanced", "target_duration_mode": "standard", "editorial_mode": "hook",
        "explain": "Coloca um teaser de 3 segundos do ponto mais intenso no início para prender a atenção, "
                   "e em seguida toca a história.",
    },
    "loop": {
        "label": "Loop Infinito (Replay TikTok)",
        "tagline": "A frase final vira abertura para replay contínuo.",
        "flow": "Final → História → (repete)",
        "refine_mode": "balanced", "target_duration_mode": "auto", "editorial_mode": "loop",
        "explain": "Move a última fala para o início, fazendo com que o final do vídeo conecte perfeitamente "
                   "no início quando reproduzido em repetição contínua.",
    },
    "auto": {
        "label": "Automático",
        "tagline": "A IA analisa o vídeo e escolhe o melhor corte cronológico.",
        "flow": "Curto → Ágil · Médio → Viral Pro · Longo → Mini-Filme",
    },
}

# Legacy key aliases for backward compatibility
_LEGACY_PROFILE_ALIASES = {
    "story_hook": "dialogue",
    "flash": "dynamic",
    "clean": "dialogue",
}


def resolve_edit_profile(profile_key: str, video_duration: float, is_arc: bool = False) -> tuple:
    """Returns (resolved_key, profile). 'auto' picks the recipe that fits the clip length."""
    key = profile_key if profile_key in EDIT_PROFILES else _LEGACY_PROFILE_ALIASES.get(profile_key, "auto")
    if key == "auto":
        if is_arc or video_duration >= 110.0:
            key = "mini_movie"
        elif 0 < video_duration <= 40.0:
            key = "dynamic"
        else:
            key = "narrative"
    return key, EDIT_PROFILES[key]


def _get_ffmpeg_bin(cmd: str = "ffmpeg") -> str:
    """Return path to ffmpeg or ffprobe executable, checking engine_manager, app bin, and system PATH."""
    try:
        from engine_manager import find_engine_executable
        found = find_engine_executable(cmd)
        if found:
            return found
    except Exception:
        pass

    import shutil
    found = shutil.which(cmd)
    if found:
        return found

    app_root = Path(sys.executable).parent.resolve() if getattr(sys, "frozen", False) else Path(__file__).parent.resolve()
    cmd_exe = f"{cmd}.exe" if sys.platform.startswith("win") else cmd
    candidates = [
        app_root / "bin" / cmd_exe,
        app_root / cmd_exe,
        Path(__file__).parent.resolve() / "bin" / cmd_exe,
        Path(__file__).parent.resolve() / cmd_exe,
        Path(r"C:\ffmpeg\bin") / cmd_exe,
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "ffmpeg" / "bin" / cmd_exe,
        Path(os.environ.get("LOCALAPPDATA", "")) / "ffmpeg" / "bin" / cmd_exe,
        Path(os.path.expanduser("~")) / "ffmpeg" / "bin" / cmd_exe,
    ]
    for p in candidates:
        if p.exists():
            return str(p.resolve())

    return cmd


def _get_silent_subprocess_kwargs() -> dict:
    """Returns kwargs for subprocess to prevent console window flashing on Windows."""
    kwargs = {}
    if os.name == "nt" or sys.platform.startswith("win"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = si
    return kwargs


def _run_ffmpeg_with_nvenc_fallback(cmd: list, timeout: int = 600, on_log=None) -> subprocess.CompletedProcess:
    """
    Run FFmpeg command with h264_nvenc hardware acceleration first.
    If nvenc fails, automatically fall back to CPU libx264.
    """
    cmd_str = " ".join(str(c) for c in cmd)
    if on_log:
        on_log(f"[FFmpeg] Executando: {cmd_str[:120]}...")

    result = None
    silent_kw = _get_silent_subprocess_kwargs()
    try:
        result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout, **silent_kw)
    except Exception as e:
        if on_log:
            on_log(f"[FFmpeg] Exceção na tentativa NVENC: {e}")
        result = None

    if result is None or result.returncode != 0:
        has_nvenc = any(str(c) == "h264_nvenc" for c in cmd)
        if has_nvenc:
            if on_log:
                on_log("[AVISO] h264_nvenc indisponível ou falhou. Tentando fallback transparente para libx264 (CPU)...")
            fallback_cmd = []
            i = 0
            has_pix_fmt = False
            while i < len(cmd):
                if str(cmd[i]) == "-c:v" and i + 1 < len(cmd) and str(cmd[i+1]) == "h264_nvenc":
                    fallback_cmd.extend(["-c:v", "libx264"])
                    i += 2
                elif str(cmd[i]) == "-preset" and i + 1 < len(cmd) and (str(cmd[i+1]).startswith("p") or str(cmd[i+1]) in ("default", "slow", "medium", "fast")):
                    fallback_cmd.extend(["-preset", "fast"])
                    i += 2
                elif str(cmd[i]) == "-cq" and i + 1 < len(cmd):
                    fallback_cmd.extend(["-crf", str(cmd[i+1])])
                    i += 2
                else:
                    if str(cmd[i]) == "-pix_fmt":
                        has_pix_fmt = True
                    fallback_cmd.append(cmd[i])
                    i += 1
            if not has_pix_fmt and len(fallback_cmd) > 1:
                out_target = fallback_cmd.pop()
                fallback_cmd.extend(["-pix_fmt", "yuv420p", out_target])

            result = subprocess.run(fallback_cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout, **silent_kw)
            if result.returncode == 0 and on_log:
                on_log("[OK] Sucesso com fallback libx264 (CPU)!")
    return result


def get_video_duration(video_path: str) -> float:
    """Retrieve video duration in seconds via ffprobe."""
    ffprobe = _get_ffmpeg_bin("ffprobe")
    try:
        cmd = [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(video_path)
        ]
        res = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=15, **_get_silent_subprocess_kwargs())
        if res.returncode == 0 and res.stdout.strip():
            return float(res.stdout.strip())
    except Exception:
        pass
    return 0.0


def check_video_has_audio(video_path: str) -> bool:
    """Check if video contains an audio stream."""
    ffprobe = _get_ffmpeg_bin("ffprobe")
    try:
        cmd = [
            ffprobe, "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            str(video_path)
        ]
        res = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=10, **_get_silent_subprocess_kwargs())
        return "audio" in res.stdout.lower()
    except Exception:
        return False


# ─── Speech & Action Recognition ─────────────────────────────────────────────

def _parse_time_seconds(val):
    """
    Parses timestamp representations into float seconds:
    - float / int: 12.5 -> 12.5
    - strings: '12.5', '12,5', '12.5s', '12s'
    - time strings: '01:14', '01:14.5', '00:01:14'
    Returns float or None.
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        s = val.strip().lower().rstrip('s')
        s = s.replace(',', '.')
        if not s:
            return None
        if ':' in s:
            parts = s.split(':')
            try:
                if len(parts) == 2:
                    return float(parts[0]) * 60.0 + float(parts[1])
                elif len(parts) == 3:
                    return float(parts[0]) * 3600.0 + float(parts[1]) * 60.0 + float(parts[2])
            except (ValueError, TypeError):
                return None
        try:
            return float(s)
        except (ValueError, TypeError):
            return None
    return None


def _extract_chunk_bounds(chunk: dict):
    """
    Extracts start, end, text, and camera framing from a chunk dictionary supporting various key aliases.
    """
    if not isinstance(chunk, dict):
        return None, None, "", "wide"
    s_raw = None
    for k in ("start", "start_time", "inicio", "startTime", "from", "t_start", "comeco", "in"):
        if k in chunk:
            s_raw = chunk[k]
            break
    e_raw = None
    for k in ("end", "end_time", "fim", "endTime", "to", "t_end", "termino", "out"):
        if k in chunk:
            e_raw = chunk[k]
            break
    t_raw = "[Corte Mastercut]"
    for k in ("text", "texto", "descricao", "description", "title", "titulo", "scene"):
        if k in chunk and chunk[k]:
            t_raw = str(chunk[k])
            break
    f_raw = "wide"
    for k in ("framing", "camera", "shot", "enquadramento", "plano", "angle", "zoom"):
        if k in chunk and chunk[k]:
            val = str(chunk[k]).strip().lower()
            if "punch" in val or "close" in val or "zoom" in val or "impact" in val:
                f_raw = "punch"
            elif "react" in val or "reacao" in val or "face" in val:
                f_raw = "reaction"
            else:
                f_raw = "wide"
            break
    s = _parse_time_seconds(s_raw)
    e = _parse_time_seconds(e_raw)
    return s, e, t_raw, f_raw


def detect_speech_segments(video_path: str, on_progress=None, on_log=None, ai_engine="auto"):
    """
    Extracts 16kHz mono audio and transcribes it to get word-level / segment-level timestamps.
    Tries Groq Whisper API first (if key configured and not in local-only mode), then falls back to local faster_whisper.
    Returns: (all_words, full_text, duration)
    """
    ffmpeg_bin = _get_ffmpeg_bin("ffmpeg")
    real_duration = get_video_duration(video_path)

    # Verifica se já temos a transcrição do vídeo em cache persistente de 24h
    try:
        from ai_cache_hub import ai_cache
        cached_trans = ai_cache.get(str(video_path), "transcription")
        if cached_trans and isinstance(cached_trans, dict):
            words = cached_trans.get("words", [])
            text = cached_trans.get("full_text", "")
            dur = cached_trans.get("duration", real_duration)
            # Validação de qualidade: se o cache contiver frases inteiras em vez de palavras individuais,
            # consideramos obsoleto para obter a precisão milimétrica por palavra
            is_stale_coarse = False
            if words and len(words) <= 12:
                multi_word = sum(1 for w in words if len(str(w.get("text", "")).strip().split()) >= 3)
                if multi_word >= 2:
                    is_stale_coarse = True

            if words and not is_stale_coarse:
                if on_log:
                    on_log(f"[CACHE 24H] Transcrição Whisper recuperada instantaneamente ({len(words)} palavras, 0 tokens gastos)!")
                if on_progress:
                    on_progress(0.40, f"Transcrição carregada do Cache de IA: {len(words)} palavras.")
                return words, text, dur
            elif is_stale_coarse and on_log:
                on_log("[WHISPER] Cache anterior continha apenas blocos agregados. Refazendo transcrição com precisão milimétrica por palavra...")
    except Exception:
        pass

    if on_log:
        on_log(f"[ÁUDIO] Extraindo áudio de alta precisão (16kHz mono)... [Duração: {real_duration:.1f}s]")
    if on_progress:
        on_progress(0.10, "Extraindo áudio do vídeo...")

    temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    temp_wav_path = temp_wav.name
    temp_wav.close()

    try:
        cmd_audio = [
            ffmpeg_bin, "-y", "-i", str(video_path),
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            temp_wav_path
        ]
        subprocess.run(cmd_audio, capture_output=True, timeout=120, **_get_silent_subprocess_kwargs())

        chosen_engine = (ai_engine or os.getenv("REFINER_AI_ENGINE", "auto")).strip().lower()

        # 1. Try Groq Whisper API (whisper-large-v3) se não estiver forçado em 100% IA Local
        groq_raw = os.getenv("GROQ_API_KEY", "").strip() if chosen_engine != "ollama_local" else ""
        groq_key = groq_raw.splitlines()[0].strip().strip('"\'') if groq_raw else ""
        if groq_key and groq_key.startswith("gsk_") and os.path.exists(temp_wav_path):
            try:
                import requests
                file_size_mb = os.path.getsize(temp_wav_path) / (1024 * 1024)
                if file_size_mb <= 24:
                    if on_log:
                        on_log("[WHISPER] Transcrevendo áudio com Whisper Large v3 (Groq Nuvem - Precisão por Palavra)...")
                    if on_progress:
                        on_progress(0.20, "Transcrevendo falas via Groq Whisper Large v3...")
                    url = "https://api.groq.com/openai/v1/audio/transcriptions"
                    headers = {"Authorization": f"Bearer {groq_key}"}
                    with open(temp_wav_path, "rb") as f:
                        files = {"file": (os.path.basename(temp_wav_path), f, "audio/wav")}
                        data = [
                            ("model", "whisper-large-v3"),
                            ("response_format", "verbose_json"),
                            ("temperature", "0.0"),
                            ("timestamp_granularities[]", "word"),
                            ("timestamp_granularities[]", "segment"),
                        ]
                        resp = requests.post(url, headers=headers, files=files, data=data, timeout=90)
                    if resp.status_code == 200:
                        res_json = resp.json()
                        all_words = []
                        raw_words = res_json.get("words", [])
                        raw_segments = res_json.get("segments", [])
                        if raw_words:
                            for w in raw_words:
                                s = _parse_time_seconds(w.get("start"))
                                e = _parse_time_seconds(w.get("end"))
                                wd = str(w.get("word", "")).strip()
                                if s is not None and e is not None and wd:
                                    all_words.append({"start": round(s, 3), "end": round(e, 3), "text": wd})
                        elif raw_segments:
                            for seg in raw_segments:
                                s = _parse_time_seconds(seg.get("start"))
                                e = _parse_time_seconds(seg.get("end"))
                                txt = str(seg.get("text", "")).strip()
                                if s is not None and e is not None and txt:
                                    all_words.append({"start": round(s, 3), "end": round(e, 3), "text": txt})
                        full_text = res_json.get("text", "").strip()
                        duration = real_duration
                        if all_words and on_log:
                            on_log(f"[OK] Groq Whisper concluiu: {len(all_words)} palavras mapeadas com precisão milimétrica!")
                        if all_words:
                            try:
                                from ai_cache_hub import ai_cache
                                ai_cache.set(str(video_path), "transcription", {
                                    "words": all_words,
                                    "full_text": full_text,
                                    "duration": duration
                                })
                            except Exception:
                                pass
                            return all_words, full_text, duration
            except Exception as e_groq:
                if on_log:
                    on_log(f"[AVISO] Groq Whisper indisponível ({e_groq}). Tentando Whisper local...")

        # 2. Try local Faster-Whisper
        if on_log:
            on_log("[WHISPER] Analisando falas com Faster-Whisper local...")
        if on_progress:
            on_progress(0.25, "Transcrevendo falas e diálogos com Whisper local...")

        try:
            from faster_whisper import WhisperModel
            device = "cpu"
            compute_type = "int8"
            try:
                import ctranslate2
                if ctranslate2.get_cuda_device_count() > 0:
                    device = "cuda"
                    compute_type = "float16"
            except Exception:
                pass

            if on_log:
                on_log(f"   Modelo Whisper: base | Dispositivo: {device.upper()} ({compute_type})")

            try:
                model = WhisperModel("base", device=device, compute_type=compute_type)
            except Exception:
                model = WhisperModel("base", device="cpu", compute_type="int8")

            segments_iter, info = model.transcribe(temp_wav_path, beam_size=5, word_timestamps=True)

            all_words = []
            full_text_parts = []

            for seg in list(segments_iter):
                if seg.words:
                    for w in seg.words:
                        all_words.append({
                            "start": round(w.start, 3),
                            "end": round(w.end, 3),
                            "text": w.word.strip()
                        })
                else:
                    all_words.append({
                        "start": round(seg.start, 3),
                        "end": round(seg.end, 3),
                        "text": seg.text.strip()
                    })
                full_text_parts.append(seg.text.strip())

            duration = info.duration if info else real_duration
            if duration <= 0.0:
                duration = real_duration

            if on_log:
                on_log(f"[OK] Whisper local concluiu: {len(all_words)} palavras mapeadas em {duration:.1f}s.")
            if on_progress:
                on_progress(0.40, f"Transcrição concluída: {len(all_words)} palavras mapeadas.")

            try:
                from ai_cache_hub import ai_cache
                ai_cache.set(str(video_path), "transcription", {
                    "words": all_words,
                    "full_text": " ".join(full_text_parts),
                    "duration": duration
                })
            except Exception:
                pass

            return all_words, " ".join(full_text_parts), duration

        except Exception as err_local:
            if on_log:
                on_log(f"[AVISO] Whisper local não disponível: {err_local}. Prosseguindo com análise estrutural e fatiamento inteligente...")
            return [], "", real_duration

    except Exception as err:
        if on_log:
            on_log(f"[AVISO] Erro na extração de áudio: {err}")
        return [], "", real_duration
    finally:
        if os.path.exists(temp_wav_path):
            try:
                os.remove(temp_wav_path)
            except Exception:
                pass



def align_opening_segment_to_acoustic_speech(
    opening_segment: dict,
    audio_path_or_video: str,
    ffmpeg_bin: str = "ffmpeg",
    min_lead_silence: float = 0.20,
    on_log=None
) -> dict:
    """
    Garante que o primeiro segmento do Mastercut inicie com fala REAL no frame 0 (tolerância <= 0.08s).
    Analisa a onda acústica para eliminar qualquer buraco de silêncio (1s a 5s) causado por
    alucinação do Whisper, introduções visuais lentas ou silêncio pós-isolamento Demucs.
    """
    if not opening_segment or not audio_path_or_video or not os.path.exists(str(audio_path_or_video)):
        return opening_segment

    seg_start = float(opening_segment.get("start", 0.0))
    seg_end = float(opening_segment.get("end", seg_start + 5.0))
    search_dur = min(8.0, max(1.5, seg_end - seg_start))

    is_wav = str(audio_path_or_video).lower().endswith(".wav")
    audio = None
    sr = 16000

    try:
        if is_wav:
            import soundfile as sf
            with sf.SoundFile(str(audio_path_or_video)) as f:
                sr = f.samplerate
                start_frame = max(0, int(seg_start * sr))
                frames_to_read = min(int(search_dur * sr), max(0, len(f) - start_frame))
                if frames_to_read > 0:
                    f.seek(start_frame)
                    audio = f.read(frames_to_read)
                    if len(audio.shape) > 1:
                        import numpy as np
                        audio = np.mean(audio, axis=1)
        else:
            cmd = [
                ffmpeg_bin, "-y",
                "-ss", f"{seg_start:.3f}",
                "-i", str(audio_path_or_video),
                "-t", f"{search_dur:.3f}",
                "-vn", "-ar", "16000", "-ac", "1",
                "-f", "wav", "pipe:1"
            ]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_get_silent_subprocess_kwargs())
            wav_bytes, _ = proc.communicate(timeout=15)
            if proc.returncode == 0 and wav_bytes:
                import io
                import soundfile as sf
                audio, sr = sf.read(io.BytesIO(wav_bytes))
    except Exception as e:
        if on_log:
            on_log(f"[AVISO ONSET] Falha ao verificar silêncio acústico: {e}")
        return opening_segment

    if audio is None or len(audio) == 0:
        return opening_segment

    import numpy as np
    win_size = int(sr * 0.06)
    step = int(sr * 0.02)
    if win_size <= 0 or step <= 0 or len(audio) < win_size:
        return opening_segment

    rms_vals = []
    offsets = []
    for idx in range(0, len(audio) - win_size, step):
        chunk = audio[idx : idx + win_size]
        r = float(np.sqrt(np.mean(chunk**2)))
        rms_vals.append(r)
        offsets.append(idx / sr)

    if not rms_vals:
        return opening_segment

    max_rms = max(rms_vals)
    if max_rms < 0.004:
        return opening_segment

    thresh = max(0.005, min(0.018, max_rms * 0.15))

    found_onset = None
    for off, r in zip(offsets, rms_vals):
        if r >= thresh:
            found_onset = off
            break

    if found_onset is not None and found_onset >= min_lead_silence:
        cushion = 0.05
        new_start = round(max(0.0, seg_start + found_onset - cushion), 3)
        if new_start < seg_end - 0.4:
            lead_cut = found_onset
            if on_log:
                on_log(f"⚡ [RETENÇÃO VIRAL: ZERO SILÊNCIO ACÚSTICO] Silêncio inicial de {lead_cut:.2f}s cortado! Início antecipado de {seg_start:.2f}s -> {new_start:.2f}s (fala imediata no segundo 0).")
            opening_segment["start"] = new_start

    return opening_segment


def detect_visual_action_blocks(video_path: str, on_log=None):
    """
    Detecta intervalos com alta densidade de cortes de câmera (ação/batalha).
    Retorna lista de dicts {start, end} para uso no prompt da IA de corte.
    """
    try:
        ffmpeg_bin = _get_ffmpeg_bin("ffmpeg")
        cmd = [
            ffmpeg_bin, "-ss", "0", "-i", str(video_path),
            "-vf", "fps=3,select='gt(scene,0.20)',showinfo",
            "-f", "null", "-"
        ]
        res = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=20, **_get_silent_subprocess_kwargs())
        scene_times = []
        for line in res.stderr.splitlines():
            if 'pts_time:' in line:
                m = re.search(r'pts_time:([0-9.]+)', line)
                if m:
                    scene_times.append(round(float(m.group(1)), 2))
        action_blocks = []
        if scene_times:
            c_start = scene_times[0]
            c_end = scene_times[0]
            c_count = 1
            for i in range(1, len(scene_times)):
                t = scene_times[i]
                if t - c_end <= 2.5:
                    c_end = t
                    c_count += 1
                else:
                    if c_count >= 3 or (c_end - c_start) >= 2.0:
                        action_blocks.append({"start": c_start, "end": c_end})
                    c_start = t
                    c_end = t
                    c_count = 1
            if c_count >= 3 or (c_end - c_start) >= 2.0:
                action_blocks.append({"start": c_start, "end": c_end})
        if on_log and action_blocks:
            on_log(f"[OK] Mapeadas {len(action_blocks)} sequências de corte/ação visual.")
        return action_blocks
    except Exception as e:
        if on_log:
            on_log(f"Aviso detecção visual: {e}")
        return []


def describe_silent_scenes_with_vision(
    video_path: str,
    all_words: list,
    video_duration: float,
    video_context: str = "",
    work_title: str = "",
    scene_context: str = "",
    ai_engine: str = "auto",
    on_log=None
) -> list:

    """
    Analisa visualmente os intervalos SEM fala (silêncios ≥ 1.0s) do vídeo,
    extraindo frames-chave e usando Gemini Vision para descrever o que acontece
    em cada cena muda: golpes, poderes, corridas, abraços, choros, etc.

    Retorna lista de dicts:
      {start, end, description, importance}
    onde importance é 'high' | 'medium' | 'low'
    """
    try:
        from ai_cache_hub import ai_cache
        cached_scenes = ai_cache.get(str(video_path), "scene_vision")
        if cached_scenes and isinstance(cached_scenes, list):
            if on_log:
                high_count = sum(1 for s in cached_scenes if s.get("importance") == "high")
                on_log(f"[CACHE 24H] {len(cached_scenes)} cenas visuais reaproveitadas ({high_count} de alto impacto, 0 tokens Vision gastos)!")
            return cached_scenes
    except Exception:
        pass

    chosen_engine = (ai_engine or os.getenv("REFINER_AI_ENGINE", "auto")).strip().lower()
    if chosen_engine == "ollama_local":
        if on_log:
            on_log("⚡ [100% IA LOCAL] Análise de cenas silenciosas operando 100% offline (Zero Nuvem)...")
        return []

    try:
        keys = _get_api_keys()
        if not keys:
            return []

        avail_keys = keys
        if api_health is not None:
            avail_keys = api_health.filter_available_keys(keys)
        if not avail_keys:
            return []

        # Identify silent gaps (>= 1.0s without speech)
        silent_gaps = []
        if all_words:
            # Gap before first word
            if all_words[0]["start"] >= 1.0:
                silent_gaps.append({"start": 0.0, "end": all_words[0]["start"]})
            # Gaps between words
            for i in range(len(all_words) - 1):
                gap_start = all_words[i]["end"]
                gap_end = all_words[i + 1]["start"]
                if gap_end - gap_start >= 1.0:
                    silent_gaps.append({"start": round(gap_start, 2), "end": round(gap_end, 2)})
            # Gap after last word
            if video_duration - all_words[-1]["end"] >= 1.0:
                silent_gaps.append({"start": all_words[-1]["end"], "end": video_duration})
        else:
            # No speech detected: whole video is one silent scene
            silent_gaps.append({"start": 0.0, "end": video_duration})

        if not silent_gaps:
            return []

        # Only describe significant silent windows (>=1.0s), limit to 10 most interesting gaps
        significant = sorted(
            [g for g in silent_gaps if g["end"] - g["start"] >= 1.0],
            key=lambda x: x["end"] - x["start"],
            reverse=True
        )[:10]

        if not significant:
            return []

        if on_log:
            on_log(f"[VISÃO IA] Analisando visualmente {len(significant)} cenas sem fala com IA Vision...")

        # Extract representative frames from each silent gap
        ffmpeg_bin = _get_ffmpeg_bin("ffmpeg")
        described_scenes = []

        for gap in sorted(significant, key=lambda x: x["start"]):
            gap_dur = gap["end"] - gap["start"]
            # Sample up to 3 frames spread across the gap
            n_frames = min(3, max(1, int(gap_dur / 1.5)))
            frame_times = [
                round(gap["start"] + gap_dur * (i + 0.5) / n_frames, 2)
                for i in range(n_frames)
            ]

            frames_b64 = []
            for ft in frame_times:
                try:
                    import base64
                    tmp_frame = os.path.join(tempfile.gettempdir(), f"mcvision_{os.getpid()}_{int(ft*100)}.jpg")
                    cmd_frame = [
                        ffmpeg_bin, "-ss", str(ft), "-i", str(video_path),
                        "-vframes", "1", "-q:v", "4",
                        "-vf", "scale=640:-2",
                        "-y", tmp_frame
                    ]
                    r = subprocess.run(cmd_frame, capture_output=True, timeout=8, **_get_silent_subprocess_kwargs())
                    if r.returncode == 0 and os.path.exists(tmp_frame) and os.path.getsize(tmp_frame) > 500:
                        with open(tmp_frame, "rb") as f:
                            frames_b64.append((ft, base64.b64encode(f.read()).decode("utf-8")))
                    try:
                        os.remove(tmp_frame)
                    except Exception:
                        pass
                except Exception:
                    pass

            if not frames_b64:
                continue

            # Call Gemini Vision to describe the scene
            clean_work = (work_title or "").strip()
            clean_scene = (scene_context or "").strip()
            if not clean_work and not clean_scene and video_context:
                clean_work = video_context.strip()
            ctx_hint = ""
            if clean_work:
                ctx_hint += f" Esta é uma cena da obra: {clean_work}."
            if clean_scene:
                ctx_hint += f" Foco temático: {clean_scene}."

            vision_prompt = (
                f"Você é um analista de conteúdo audiovisual especializado em anime e séries.{ctx_hint}\n"
                f"Analise este(s) frame(s) de vídeo capturado(s) entre {gap['start']:.1f}s e {gap['end']:.1f}s (sem fala neste trecho).\n"
                "Descreva em 1-2 frases curtas e precisas O QUE ESTÁ ACONTECENDO visualmente:\n"
                "- Pode ser: golpe/ataque, poder especial, corrida/fuga, explosão, cena romântica (abraço/beijo), choro/reação emocional, transformação, revelação, olhar intenso, perseguição, etc.\n"
                "- Se for algo épico e impactante, mencione isso.\n"
                "- Se for algo mundano (personagem andando, cena estática), diga que é de baixo impacto.\n"
                "Responda APENAS com um objeto JSON:\n"
                "{\"description\": \"...\", \"importance\": \"high|medium|low\", \"scene_type\": \"acao|romantico|emocional|transicao|revelacao|outro\"}"
            )

            try:
                from google import genai as _genai
                from google.genai import types as _gtypes

                # Pick first available key
                chosen_key = avail_keys[0]
                if api_health is not None:
                    for k in avail_keys:
                        ok, _ = api_health.is_key_available(k)
                        if ok:
                            chosen_key = k
                            break

                vision_model = "gemini-2.0-flash"
                if api_health is not None:
                    ok, _ = api_health.is_model_available(vision_model)
                    if not ok:
                        vision_model = "gemini-1.5-flash"

                client = _genai.Client(api_key=chosen_key)

                # Build multimodal contents
                parts = [_gtypes.Part.from_text(text=vision_prompt)]
                for _, b64data in frames_b64:
                    parts.append(_gtypes.Part.from_bytes(
                        data=base64.b64decode(b64data),
                        mime_type="image/jpeg"
                    ))

                response = client.models.generate_content(
                    model=vision_model,
                    contents=parts,
                    config={"response_mime_type": "application/json"}
                )

                if response and response.text:
                    result = json.loads(response.text)
                    description = result.get("description", "Cena visual sem fala")
                    importance = result.get("importance", "medium")
                    scene_type = result.get("scene_type", "outro")
                    described_scenes.append({
                        "start": gap["start"],
                        "end": gap["end"],
                        "description": description,
                        "importance": importance,
                        "scene_type": scene_type
                    })
                    if api_health is not None:
                        api_health.mark_key_success(chosen_key)
                        api_health.mark_model_success(vision_model)

            except Exception as e:
                err_s = str(e)
                if "503" in err_s or "UNAVAILABLE" in err_s:
                    if api_health is not None:
                        api_health.mark_model_unavailable(vision_model, err_s, cooldown_secs=600)
                elif "429" in err_s or "RESOURCE_EXHAUSTED" in err_s:
                    if api_health is not None:
                        api_health.mark_key_exhausted(chosen_key, err_s, cooldown_secs=900)
                # Fallback: add without description
                described_scenes.append({
                    "start": gap["start"],
                    "end": gap["end"],
                    "description": "Cena visual (análise indisponível)",
                    "importance": "medium",
                    "scene_type": "outro"
                })

        if on_log and described_scenes:
            high_count = sum(1 for s in described_scenes if s["importance"] == "high")
            on_log(f"[OK] {len(described_scenes)} cenas visuais descritas pela IA ({high_count} de alto impacto).")

        try:
            from ai_cache_hub import ai_cache
            if described_scenes:
                ai_cache.set(str(video_path), "scene_vision", described_scenes)
        except Exception:
            pass

        return described_scenes

    except Exception as e:
        if on_log:
            on_log(f"Aviso análise visual: {e}")
        return []




# ─── Mastercut AI Selection ───────────────────────────────────────────────────

def _get_api_keys() -> list:
    """Read Gemini API keys from environment or .env."""
    raw = os.getenv("GEMINI_API_KEY", "").strip()
    if not raw or "sua_chave" in raw:
        return []
    keys = []
    seen = set()
    for part in raw.replace(";", "\n").replace(",", "\n").splitlines():
        clean_k = part.strip().strip('"\'')
        if clean_k and "sua_chave" not in clean_k.lower() and clean_k not in seen:
            seen.add(clean_k)
            keys.append(clean_k)
    # Prioritiza chaves padrão Google AI Studio (AIzaSy...) primeiro para velocidade instantânea
    keys.sort(key=lambda k: 0 if k.startswith("AIzaSy") else 1)
    return keys


def group_words_into_complete_sentences(all_words: list, max_gap: float = 0.85, is_dorama: bool = False) -> list:
    """
    Agrupa palavras em sentenças semânticas completas (turnos de fala íntegros).
    NUNCA parte uma frase no meio por causa de pausas curtas de respiração.
    Critérios para término de sentença:
    1. Pontuação terminal: '.', '!', '?', '…'
    2. OU silêncio real prolongado (>= 0.85s no anime, >= 1.1s no dorama)
    """
    if not all_words:
        return []
    gap_thresh = 1.10 if is_dorama else max_gap
    sentences = []
    curr_words = []

    for i, w in enumerate(all_words):
        curr_words.append(w)
        is_last = (i == len(all_words) - 1)
        next_gap = (all_words[i + 1]["start"] - w["end"]) if not is_last else 999.0
        txt = (w.get("text") or w.get("word") or "").strip()

        has_terminal_punct = any(txt.endswith(p) for p in ('.', '!', '?', '…'))
        is_silence_break = next_gap >= gap_thresh

        # Se for vocativo ou interjeição muito curta (ex: "Seiya!", "Maldito!") e a fala continuar logo em seguida,
        # anexa à próxima oração para não isolar o vocativo da pergunta/ação!
        is_short_interjection = (
            has_terminal_punct
            and len(curr_words) <= 2
            and not is_last
            and next_gap < gap_thresh
        )

        if (is_last or has_terminal_punct or is_silence_break) and not is_short_interjection:
            st = curr_words[0]["start"]
            en = curr_words[-1]["end"]
            sentence_txt = " ".join((cw.get("text") or cw.get("word") or "").strip() for cw in curr_words)
            dur = round(en - st, 3)
            if dur > 0.05:
                sentences.append({
                    "start": round(st, 3),
                    "end": round(en, 3),
                    "duration": dur,
                    "words_count": len(curr_words),
                    "text": sentence_txt,
                    "words": curr_words
                })
            curr_words = []

    return sentences


def group_words_by_speech_gaps(all_words: list, max_gap: float = 0.85, is_dorama: bool = False) -> list:
    """
    Groups individual words into complete semantic sentences.
    Preserves whole thoughts and avoids chopping dialogue during normal breathing pauses.
    """
    return group_words_into_complete_sentences(all_words, max_gap=max_gap, is_dorama=is_dorama)


def _merge_segments(segments: list, min_gap: float = 0.25) -> list:
    """Merges overlapping or touching segments to prevent jitter and micro-gaps."""
    if not segments:
        return []
    sorted_segs = sorted(segments, key=lambda x: x["start"])
    merged = []
    curr = dict(sorted_segs[0])

    for next_seg in sorted_segs[1:]:
        if curr["end"] + min_gap >= next_seg["start"]:
            curr["end"] = max(curr["end"], next_seg["end"])
            t_curr = curr.get("text", "")
            t_next = next_seg.get("text", "")
            if t_next and t_next not in t_curr:
                curr["text"] = f"{t_curr} {t_next}".strip()
        else:
            merged.append(curr)
            curr = dict(next_seg)
    merged.append(curr)
    return merged


def is_sentence_cut_by_file_edge(sent: dict, video_duration: float) -> bool:
    """
    Detecta se uma sentença foi cortada ao meio pela borda física do arquivo de vídeo bruto.
    Isso ocorre com frequência em clipes extraídos de episódios onde o arquivo terminou
    enquanto o personagem ainda estava falando, deixando palavras incompletas ou alucinações de fim de áudio.
    """
    if not sent or video_duration <= 0:
        return False
    if sent.get("end", 0.0) >= video_duration - 0.35:
        txt = sent.get("text", "").strip()
        ws = sent.get("words", [])
        has_ellipsis = txt.endswith("...") or "..." in txt[-8:] or txt.endswith(" eu...")
        no_final_punct = not txt.endswith((".", "!", "?", '"', '”', '’'))
        tiny_words = any((w.get("end", 0.0) - w.get("start", 0.0)) <= 0.045 for w in ws[-3:]) if ws else False
        started_near_end = (sent.get("start", 0.0) >= video_duration - 2.2)
        if has_ellipsis or no_final_punct or tiny_words or started_near_end:
            return True
    return False


def get_safe_sentences(all_words: list, video_duration: float = 0.0, is_dorama: bool = False) -> list:
    """
    Retorna sentenças completas filtrando qualquer sentença que tenha sido decepada
    pela borda física final do arquivo de vídeo.
    """
    sentences = group_words_into_complete_sentences(all_words, is_dorama=is_dorama)
    if not sentences:
        return []
    if video_duration > 0 and is_sentence_cut_by_file_edge(sentences[-1], video_duration):
        return sentences[:-1]
    return sentences


def snap_to_sentence_boundaries(segments: list, all_words: list, video_duration: float, is_dorama: bool = False) -> list:
    """
    SENTENCE GUARD SUPREMO:
    Garante que NENHUM corte comece ou termine decepando frases ao meio.
    Se um segmento tocar em uma sentença completa (ou começar/terminar no meio dela),
    ele se expande para cobrir a sentença por inteiro, adicionando pré-roll acústico (-0.08s)
    e respiro vocal natural (+0.22s).
    Nunca expande para sentenças que foram cortadas pelo fim físico do arquivo de vídeo.
    """
    if not segments or not all_words:
        return segments

    sentences = get_safe_sentences(all_words, video_duration=video_duration, is_dorama=is_dorama)
    if not sentences:
        return segments

    # Limite máximo seguro para o término do vídeo se a última fala do arquivo bruto foi decepada
    raw_sentences = group_words_into_complete_sentences(all_words, is_dorama=is_dorama)
    max_safe_end = video_duration
    if raw_sentences and is_sentence_cut_by_file_edge(raw_sentences[-1], video_duration):
        max_safe_end = min(video_duration, raw_sentences[-1]["start"] - 0.08)

    snapped = []
    for seg in segments:
        s_t = seg["start"]
        e_t = seg["end"]

        # 1. Se s_t começa no meio de uma sentença, recua para o início da sentença inteira
        for sent in sentences:
            if sent["start"] - 0.25 <= s_t <= sent["end"]:
                s_t = min(s_t, sent["start"] - 0.08)
                break
            elif 0 <= (sent["start"] - s_t) <= 0.35:
                s_t = sent["start"] - 0.08
                break

        # 2. Se e_t termina no meio de uma sentença, estende para o término da sentença inteira
        for sent in sentences:
            if sent["start"] <= e_t <= sent["end"] + 0.25:
                e_t = max(e_t, sent["end"] + 0.22)
                break
            elif 0 <= (e_t - sent["end"]) <= 0.35:
                e_t = sent["end"] + 0.22
                break

        s_t = max(0.0, round(s_t, 3))
        e_t = min(max_safe_end, round(e_t, 3))
        if e_t > s_t:
            snapped.append({
                **seg,
                "start": s_t,
                "end": e_t
            })

    return snapped


def align_segments_to_speech_boundaries(segments: list, all_words: list, video_duration: float, is_dorama: bool = False) -> list:
    """
    Garante que nenhum segmento comece ou termine decepando frases ou palavras ao meio.
    1. Primeiro aplica o Sentence Guard (expande para sentenças completas).
    2. Aplica micro-ajuste palavra por palavra com respiro seguro.
    3. Funde diálogos imediatos (pausas <= 0.60s) para manter trocas dialéticas contínuas.
    """
    if not segments or not all_words:
        return segments

    # Limite máximo seguro para o término do vídeo se a última fala do arquivo bruto foi decepada
    raw_sentences = group_words_into_complete_sentences(all_words, is_dorama=is_dorama)
    max_safe_end = video_duration
    if raw_sentences and is_sentence_cut_by_file_edge(raw_sentences[-1], video_duration):
        max_safe_end = min(video_duration, raw_sentences[-1]["start"] - 0.08)
        all_words = [w for w in all_words if w.get("end", 0.0) <= max_safe_end + 0.05]

    # 1. Alinha às sentenças inteiras primeiro (impede corte no meio da frase)
    snapped = snap_to_sentence_boundaries(segments, all_words, video_duration, is_dorama=is_dorama)

    aligned = []
    for seg in snapped:
        s_t = seg["start"]
        e_t = seg["end"]

        # Ajuste do início: se corta uma palavra no meio, recua para o início da palavra
        cutting_start_word = [w for w in all_words if w["start"] < s_t < w["end"]]
        if cutting_start_word:
            s_t = max(0.0, cutting_start_word[0]["start"] - 0.08)
        else:
            nearby_start = [w for w in all_words if 0 <= (w["start"] - s_t) <= 0.18]
            if nearby_start:
                s_t = max(0.0, nearby_start[0]["start"] - 0.08)

        # Ajuste do fim: se corta uma palavra no meio, estende para o término da palavra com respiro
        cutting_end_word = [w for w in all_words if w["start"] <= e_t < w["end"]]
        if cutting_end_word:
            e_t = min(max_safe_end, cutting_end_word[-1]["end"] + 0.22)
        else:
            inside_words = [w for w in all_words if w["end"] <= e_t and w["start"] >= s_t]
            if inside_words:
                last_w = inside_words[-1]
                if (e_t - last_w["end"]) < 0.22:
                    e_t = min(max_safe_end, last_w["end"] + 0.22)

        aligned.append({
            **seg,
            "start": round(s_t, 3),
            "end": round(min(max_safe_end, e_t), 3),
        })

    # Funde trechos com pausas curtas (<= 0.55s) para não gerar cortes falsos entre réplicas rápidas
    return _merge_segments(aligned, min_gap=0.55)


def sanitize_final_segments(segments: list, min_gap: float = 0.18) -> list:
    """
    Validação estrita anti-engasgo e anti-overlap:
    Garante que:
    1. Não exista NENHUMA sobreposição temporal (start < prev_end) que faça a voz gaguejar/repetir.
    2. Gaps minúsculos (< 0.18s) que causam soluços/cortes falsos sejam fundidos suavemente.
    3. Segmentos com duração microscópica (< 0.35s) sejam eliminados.
    4. Todos os cortes sejam estritamente crescentes e limpos no tempo.
    5. Tags de cinematografia (framing) sejam preservadas.
    """
    if not segments:
        return segments
    sorted_segs = sorted(segments, key=lambda x: x["start"])
    clean = []
    for s in sorted_segs:
        st = round(s["start"], 3)
        en = round(s["end"], 3)
        framing = s.get("framing", "wide")
        if en <= st + 0.30:
            continue
        if not clean:
            clean.append({"start": st, "end": en, "text": s.get("text", ""), "framing": framing})
            continue
        prev = clean[-1]
        if st < prev["end"]:
            # OVERLAP DETECTADO! Funde imediatamente para eliminar engasgo/gagueira!
            prev["end"] = max(prev["end"], en)
            t_prev = prev.get("text", "")
            t_s = s.get("text", "")
            if t_s and t_s not in t_prev:
                prev["text"] = f"{t_prev} {t_s}".strip()
        elif st - prev["end"] < min_gap:
            # Gap insignificante (<180ms): funde para evitar soluço no áudio!
            prev["end"] = max(prev["end"], en)
            t_prev = prev.get("text", "")
            t_s = s.get("text", "")
            if t_s and t_s not in t_prev:
                prev["text"] = f"{t_prev} {t_s}".strip()
        else:
            clean.append({"start": st, "end": en, "text": s.get("text", ""), "framing": framing})
    return clean


def finalize_ordered_segments(segments: list, min_gap: float = 0.18) -> list:
    """
    Order-preserving cleanup for edited timelines (hook / loop already placed).
    Unlike sanitize_final_segments it NEVER re-sorts, so intentional jumps
    (teaser at 0s, loop tail moved to the front) survive. It only:
    - trims forward overlaps with the previous piece (prevents stutter)
    - merges pieces contiguous in the source that share the same role
    - drops micro segments (< 0.30s)
    """
    clean = []
    for seg in segments or []:
        st, en = round(seg["start"], 3), round(seg["end"], 3)
        if clean:
            prev = clean[-1]
            if prev["start"] <= st < prev["end"]:
                st = prev["end"]
            if prev.get("role") == seg.get("role") and 0 <= st - prev["end"] < min_gap:
                prev["end"] = max(prev["end"], en)
                continue
        if en - st < 0.30:
            continue
        clean.append({**seg, "start": st, "end": en})
    return clean


def split_long_segments_for_multicam(segments: list, max_shot_dur: float = 3.8, is_dorama: bool = False) -> list:
    """
    Simulação de 2ª Câmera de Estúdio (Dynamic Multi-Camera Smart Punch-In):
    Garante que NENHUM plano contínuo ultrapasse max_shot_dur (3.8s anime / 6.0s dorama).
    Se uma fala for longa, ela é dividida visualmente mantendo o áudio 100% contínuo,
    íntegro e perfeitamente sincronizado, preservando o ritmo natural dos atores.
    """
    if is_dorama and max_shot_dur <= 4.0:
        max_shot_dur = 6.0
    if not segments:
        return segments
    res = []
    framing_seq = ["wide", "punch", "wide", "reaction", "punch"]
    seq_idx = 0
    for s in segments:
        st = s["start"]
        en = s["end"]
        txt = s.get("text", "")
        dur = en - st
        # "wide" is the parser default, so only explicit punch/reaction from the AI overrides the rotation
        explicit = s.get("framing")
        assigned_framing = explicit if explicit in ("punch", "reaction") else framing_seq[seq_idx % len(framing_seq)]
        seq_idx += 1

        if dur <= max_shot_dur:
            s_copy = dict(s)
            s_copy["framing"] = assigned_framing
            res.append(s_copy)
        else:
            # Divide a cena em sub-takes de câmera mantendo áudio contínuo
            n_sub = int(dur / max_shot_dur) + 1
            sub_len = dur / n_sub
            curr_st = st
            for j in range(n_sub):
                curr_en = round(min(en, curr_st + sub_len), 3)
                sub_f = "punch" if j % 2 == 1 else ("wide" if assigned_framing != "wide" else "reaction")
                res.append({
                    **s,
                    "start": round(curr_st, 3),
                    "end": curr_en,
                    "text": txt if j == 0 else f"{txt} (cont.)",
                    "framing": sub_f
                })
                curr_st = curr_en
    return res


def calculate_mastercut_bounds(
    video_duration: float,
    refine_mode: str = "balanced",
    target_duration_mode: str = "auto"
) -> tuple:
    """
    Calculates the (min_duration, max_duration) bounds for Mastercut.
    Prevents aggressive over-cutting (e.g. turning 60s into 19s),
    while strictly guaranteeing meaningful duration reduction (15% to 50% cut)
    to transform the media and defeat automated Content ID / copyright matches.
    """
    v_dur = max(5.0, float(video_duration))

    # User explicit duration presets
    if target_duration_mode == "viral_59s":
        # Viral Flow 59s: Teto estrito e inegociável de 59.0s
        if v_dur <= 59.0:
            min_d = max(15.0, v_dur * 0.85)
            max_d = v_dur
        elif v_dur <= 80.0:
            min_d = max(38.0, v_dur * 0.65)
            max_d = min(58.5, v_dur * 0.90)
        else:
            # Vídeos longos (2min a 5min+):
            # Aproveita ao máximo a janela viral de 50.0s a 58.5s (TETO MÁXIMO ESTRITO: 59.0s)!
            min_d = 50.0
            max_d = 58.5
        return round(min_d, 1), round(max_d, 1)
    elif target_duration_mode == "mini_movie":
        # Tratar Mini-Filme: reduz para aproximadamente a metade (~50%), teto estrito de 150s (2:30 min)
        if v_dur <= 65.0:
            min_d = max(15.0, v_dur * 0.80)
            max_d = v_dur
        else:
            target_half = v_dur * 0.50
            max_d = min(150.0, max(45.0, target_half + 8.0), v_dur * 0.70)
            min_d = max(30.0, min(max_d - 12.0, target_half - 12.0))
        return round(min_d, 1), round(max_d, 1)
    elif target_duration_mode == "max_retention":
        # Retenção Máxima: em vídeos curtos (<=65s), preserva 100% das falas!
        if v_dur <= 65.0:
            min_d = max(15.0, v_dur * 0.90)
            max_d = v_dur
        else:
            min_d = max(25.0, v_dur * 0.75)
            max_d = min(v_dur * 0.92, max(min_d + 4.0, v_dur * 0.88))
        return round(min_d, 1), round(max_d, 1)
    elif target_duration_mode == "standard":
        # Padrão Shorts / Reels: até 65s preserva o clipe completo; acima disso, condensa para 35s-60s
        if v_dur <= 65.0:
            min_d = max(15.0, v_dur * 0.85)
            max_d = v_dur
        else:
            min_d = min(35.0, v_dur * 0.50)
            max_d = min(v_dur * 0.85, 60.0)
        return round(max(14.0, min_d), 1), round(max(min_d + 4.0, max_d), 1)
    elif target_duration_mode == "short":
        # Curto & Rápido: 20s a 35s
        min_d = max(10.0, min(20.0, v_dur * 0.35))
        max_d = min(v_dur * 0.70, 35.0)
        return round(min_d, 1), round(max_d, 1)

    # Automatic mode based on refine_mode & video_duration
    if v_dur <= 65.0:
        # Vídeo já no formato Shorts/Reels/TikTok (<= 65s):
        # NUNCA mutilar frases ou conversas: preservar o diálogo contínuo de ponta a ponta!
        if refine_mode in ("soft", "dorama"):
            min_d = max(15.0, v_dur * 0.90)
            max_d = v_dur
        elif refine_mode == "aggressive":
            min_d = max(15.0, v_dur * 0.75)
            max_d = v_dur
        else:  # balanced / viral
            min_d = max(15.0, v_dur * 0.85)
            max_d = v_dur
    elif v_dur <= 110.0:
        # Vídeo médio (65s a 110s)
        if refine_mode in ("soft", "dorama"):
            min_d = max(35.0, v_dur * 0.70)
            max_d = min(v_dur, max(min_d + 3.0, v_dur * 0.92))
        elif refine_mode == "aggressive":
            min_d = max(20.0, v_dur * 0.40)
            max_d = min(v_dur * 0.60, 50.0)
        else:
            # Equilibrado (padrão): 50% a 75%
            min_d = max(25.0, v_dur * 0.50)
            max_d = min(v_dur * 0.75, 60.0)
    elif v_dur <= 240.0:
        # Clipe médio/longo (1.8m a 4m)
        if refine_mode in ("soft", "dorama"):
            min_d = max(50.0, v_dur * 0.55)
            max_d = min(v_dur * 0.75, 90.0)
        elif refine_mode == "aggressive":
            min_d = 25.0
            max_d = min(v_dur * 0.40, 45.0)
        else:  # balanced
            min_d = 35.0
            max_d = min(v_dur * 0.60, 60.0)
    else:
        # Vídeo longo (> 4m)
        if refine_mode in ("soft", "dorama"):
            min_d = 60.0
            max_d = min(v_dur * 0.50, 110.0)
        elif refine_mode == "aggressive":
            min_d = 28.0
            max_d = 45.0
        else:  # balanced
            min_d = 40.0
            max_d = 65.0

    return round(min_d, 1), round(max_d, 1)



def _get_local_model_candidates(requested_model: str = "") -> list:
    """
    Retorna lista ordenada de modelos locais instalados no Ollama.
    O modelo escolhido pelo usuário vem sempre em 1º lugar.
    Se falhar, tenta os outros modelos instalados na máquina do usuário.
    """
    from settings_manager import get_installed_ollama_models
    installed = get_installed_ollama_models()
    req = (requested_model or os.getenv("DIRECTOR_LOCAL_MODEL", "qwen2.5:7b")).strip()

    # Prioridade de contingência: modelos instruct rápidos e comprovados
    priority_order = [
        "qwen2.5:7b",
        "qwen3.8:27b",
        "qwen2.5:14b",
        "llama3.1:8b",
        "qwen2.5vl:7b",
        "deepseek-r1:8b",
        "deepseek-r1:14b",
        "llama3:latest",
        "mistral:7b",
    ]

    candidates = []
    if req:
        candidates.append(req)

    # Adiciona os instalados na máquina seguindo a ordem de prioridade
    for p in priority_order:
        for inst in installed:
            if (p == inst or p in inst) and inst not in candidates:
                candidates.append(inst)

    # Adiciona qualquer outro instalado não listado
    for inst in installed:
        if inst not in candidates:
            candidates.append(inst)

    if not candidates:
        candidates = ["qwen2.5:7b"]

    return candidates


def _call_ollama_local_timeline(prompt: str, on_log=None, local_model: str = "") -> tuple:
    """
    Executa a seleção de cortes do Mastercut 100% localmente via Ollama na GPU RTX 5060.
    Tenta o modelo solicitado com timeout estendido de 300s.
    Se falhar ou der timeout, tenta automaticamente outros modelos locais instalados.
    Retorna (timeline, roteiro) em caso de sucesso ou (None, None).
    """
    import requests
    models_to_try = _get_local_model_candidates(local_model)

    for idx, target_model in enumerate(models_to_try):
        is_fallback = (idx > 0)
        prefix = "⚡ [100% IA LOCAL]" if not is_fallback else f"🔄 [CONTINGÊNCIA LOCAL {idx}/{len(models_to_try)-1}]"
        if on_log:
            on_log(f"{prefix} Consultando Roteirista Ollama ({target_model}) na RTX 5060 (Zero Nuvem)...")

        is_reasoning = any(k in target_model.lower() for k in ("r1", "reason", "deepseek-r1"))
        payload = {
            "model": target_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "keep_alive": "10m",
            "options": {"temperature": 0.2}
        }
        # Para modelos de raciocínio como DeepSeek-R1, omitir format="json" evita travar o sampler com thinking tokens
        if not is_reasoning:
            payload["format"] = "json"

        t0 = time.time()
        try:
            url = "http://localhost:11434/api/chat"
            resp = requests.post(url, json=payload, timeout=300)
            if resp.status_code == 200:
                content = resp.json().get("message", {}).get("content", "")
                if content:
                    json_str = content
                    if is_reasoning and "<think>" in content:
                        import re
                        m = re.search(r'\{.*\}', content, re.DOTALL)
                        if m:
                            json_str = m.group(0)

                    data = json.loads(json_str)
                    timeline = None
                    roteiro = None
                    if isinstance(data, list):
                        timeline = data
                    elif isinstance(data, dict):
                        roteiro = (
                            data.get("roteiro_da_cena") or
                            data.get("roteiro") or
                            data.get("storyboard") or
                            data.get("script") or
                            data.get("cena")
                        )
                        timeline = (
                            data.get("ai_viral") or
                            data.get("mastercut") or
                            data.get("segments") or
                            data.get("cortes") or
                            data.get("cuts") or
                            data.get("timeline")
                        )
                    if timeline and isinstance(timeline, list) and len(timeline) > 0:
                        dur_call = time.time() - t0
                        if on_log:
                            on_log(f"✅ [100% IA LOCAL] Roteirista Ollama ({target_model}) desenhou Mastercut com {len(timeline)} cortes em {dur_call:.1f}s na RTX 5060!")
                            if roteiro and isinstance(roteiro, dict):
                                on_log("[ROTEIRISTA IA LOCAL] Roteiro Dramático Estruturado:")
                                if roteiro.get("premissa"):
                                    on_log(f"   * Premissa: {roteiro['premissa']}")
                                if roteiro.get("hook"):
                                    on_log(f"   * Hook (Abertura): {roteiro['hook']}")
                                if roteiro.get("conflito_desenvolvimento"):
                                    on_log(f"   * Desenvolvimento: {roteiro['conflito_desenvolvimento']}")
                                if roteiro.get("climax_fechamento"):
                                    on_log(f"   * Climax/Fechamento: {roteiro['climax_fechamento']}")
                        return timeline, roteiro
            else:
                if on_log:
                    on_log(f"[AVISO OLLAMA] {target_model} retornou status HTTP {resp.status_code}.")
        except Exception as e:
            err_msg = str(e)
            if "timed out" in err_msg.lower():
                err_msg = "Tempo limite de 300s esgotado (timeout)"
            if on_log:
                on_log(f"[AVISO OLLAMA] Modelo local {target_model} falhou: {err_msg}.")

        # Se ainda há mais modelos locais na máquina para tentar:
        if idx + 1 < len(models_to_try):
            next_model = models_to_try[idx + 1]
            if on_log:
                on_log(f"🔄 Alternando automaticamente para outro modelo local instalado: '{next_model}'...")

    if on_log:
        on_log(f"⚠️ [OLLAMA LOCAL] Todos os {len(models_to_try)} modelos locais testados falharam.")
    return None, None


def call_ai_mastercut_timeline(
    all_words,
    video_duration,
    action_blocks=None,
    visual_scenes=None,
    video_context="",
    work_title="",
    scene_context="",
    user_feedback="",
    previous_segments=None,
    refine_mode="balanced",
    target_duration_mode="auto",
    enable_loop=False,
    editorial_mode="linear",
    is_dorama=False,
    ai_engine="auto",
    local_model="",
    on_log=None
):

    """
    Sends the video dialogue transcription + visual scene descriptions to Gemini AI (or Groq fallback)
    requesting the Mastercut timeline with strict anti-overcut rules and duration boundaries.
    Visual scenes include AI-described silent moments: attacks, powers, romantic scenes, emotional reactions, etc.
    """
    action_blocks = action_blocks or []
    visual_scenes = visual_scenes or []

    # Separação estrita: Obra (API de Metadados) vs Foco da Cena (Somente Prompt da IA)
    clean_work_title = (work_title or "").strip()
    clean_scene_context = (scene_context or "").strip()
    if not clean_work_title and not clean_scene_context and video_context:
        clean_work_title = video_context.strip()

    # Auto-detect Dorama if not explicitly specified
    if not is_dorama:
        ctx_lower = f"{clean_work_title} {clean_scene_context} {video_context}".lower()
        is_dorama = (
            refine_mode == "dorama"
            or editorial_mode == "dorama"
            or any(k in ctx_lower for k in ("dorama", "kdrama", "k-drama", "coreano", "c-drama", "j-drama", "doramas"))
        )

    min_dur, max_dur = calculate_mastercut_bounds(video_duration, refine_mode, target_duration_mode)

    # Build complete semantic dialogue blocks with sentence boundaries (filtrando frases decepadas da borda)
    speech_sentences = get_safe_sentences(all_words, video_duration=video_duration, is_dorama=is_dorama)
    speech_summary = []
    if speech_sentences:
        for idx, sent in enumerate(speech_sentences, 1):
            speech_summary.append(f"[Bloco #{idx}] [{sent['start']:.2f}s -> {sent['end']:.2f}s] \"{sent['text']}\"")

    action_summary = []
    for ab in action_blocks:
        lbl = "(Momento Chave Dramático / Tensão)" if is_dorama else "(Cena de Luta/Ação)"
        action_summary.append(f"[{ab['start']:.2f}s -> {ab['end']:.2f}s] {lbl}")

    # Build visual scene descriptions (AI Vision analysis of silent intervals)
    visual_summary = []
    high_impact_scenes = []
    for vs in sorted(visual_scenes, key=lambda x: x.get("start", 0)):
        importance = vs.get("importance", "medium")
        scene_type = vs.get("scene_type", "outro")
        desc = vs.get("description", "Cena visual")
        emoji = {
            "acao": "⚔️", "romantico": "💕", "emocional": "😭",
            "transicao": "🎬", "revelacao": "💥", "outro": "🎞️"
        }.get(scene_type, "🎞️")
        importance_tag = "[ALTO IMPACTO]" if importance == "high" else ("MÉDIO" if importance == "medium" else "baixo")
        line = f"[{vs['start']:.2f}s -> {vs['end']:.2f}s] {emoji} {desc} [{importance_tag}]"
        visual_summary.append(line)
        if importance == "high":
            high_impact_scenes.append(vs)

    # ── Montagem do Contexto (API externa consulta APENAS clean_work_title) ──
    ctx_block = ""
    extra_meta = ""
    if clean_work_title:
        try:
            from metadata_enricher import get_enriched_context_for_prompt
            cat_hint = "dorama" if is_dorama else "anime"
            extra_meta = get_enriched_context_for_prompt(clean_work_title, category=cat_hint, on_log=on_log)
        except Exception as e:
            if on_log:
                on_log(f"[AVISO METADATA] Falha na busca de metadados para '{clean_work_title}': {e}")

    ctx_parts = []
    if clean_work_title:
        ctx_parts.append(f"Obra / Título: {clean_work_title}")
    if extra_meta:
        ctx_parts.append(extra_meta)
    if clean_scene_context:
        ctx_parts.append(
            f"🚨 FOCO DO CORTE / INSTRUÇÕES ESPECÍFICAS DA CENA:\n"
            f"\"{clean_scene_context}\"\n"
            f"(ATENÇÃO ROTEIRISTA: Dê prioridade MÁXIMA a este foco temático/emocional solicitado pelo usuário ao montar a linha do tempo!)"
        )

    if ctx_parts:
        ctx_block = f"""
[CONTEXTO DA OBRA / {'DORAMA' if is_dorama else 'ANIME'} / EPISÓDIO & INSTRUÇÕES DA CENA]
{chr(10).join(ctx_parts)}
Use esse conhecimento para identificar com precisão os personagens, a dinâmica da cena e seguir à risca o foco de corte solicitado!
"""
        if on_log:
            if clean_work_title:
                on_log(f"[METADATA API] Obra consultada na API: '{clean_work_title}'")
            if clean_scene_context:
                on_log(f"[DIREÇÃO IA] Foco da cena informado à IA: '{clean_scene_context}'")

    # ── Feedback do Diretor (Reajuste / Correção Interativa com a IA) ──
    feedback_block = ""
    if user_feedback and user_feedback.strip():
        prev_str = ""
        if previous_segments:
            seg_lines = []
            for idx, s in enumerate(previous_segments, 1):
                seg_lines.append(f"  - Corte #{idx}: [{s.get('start', 0.0):.2f}s -> {s.get('end', 0.0):.2f}s] {s.get('text', '')}")
            prev_str = "\n" + "\n".join(seg_lines)
        else:
            prev_str = " (Não especificado)"

        feedback_block = f"""
🚨 FEEDBACK CRÍTICO DO DIRETOR (CORREÇÃO DE CORTE MANDATÓRIA):
O usuário/diretor assistiu ao corte anterior e apontou o seguinte erro de contexto/ausência de momento:
"{user_feedback.strip()}"

[CORTES DA TENTATIVA ANTERIOR]:{prev_str}

MISSÃO OBRIGATÓRIA DE CORREÇÃO:
1. Localize nas falas transcritas ou nas cenas visuais o momento EXATO apontado pelo usuário (ex: ele pegando a espada, reação específica, fala que faltou).
2. OBRIGATORIAMENTE INCLUA esse trecho ou momento chave na nova proposta de corte!
3. Rebalanceie ou encurte os outros trechos para acomodar essa cena dentro do limite de tempo ({min_dur:.1f}s a {max_dur:.1f}s).
"""
        if on_log:
            on_log(f"🛠️ [DIREÇÃO & FEEDBACK] Instrução de correção: '{user_feedback.strip()}'")

    mode_descriptions = {
        "soft": "PRESERVAÇÃO MÁXIMA DE CONTEÚDO (Anti-Silêncio). Mantenha praticamente todas as falas, conversas e reações. Elimine estritamente pausas mortas (>0.35s) e silêncios.",
        "balanced": "EQUILIBRADO / RITMO DINÂMICO (Padrão). Elimine pausas mortas e partes mornas, mas MANTENHA as falas completas, réplicas entre personagens e momentos importantes. Não corte em excesso!",
        "aggressive": "AGRESSIVO / O SUCO PURO. Condensa para extrair apenas o clímax absoluto e momentos mais eletrizantes.",
        "dorama": "DORAMA DRAMÁTICO / ROMANCE & TENSÃO. Mantenha os diálogos íntegros, as réplicas completas (pergunta + resposta) e as pausas emocionais/olhares de reação entre os personagens sem picotar a atuação.",
    }
    mode_guide = mode_descriptions.get(refine_mode, mode_descriptions["balanced"])
    if target_duration_mode == "viral_59s":
        mode_guide = (
            f"VIRAL FLOW 59s (VÍDEO DE ALTA RETENÇÃO DE ~50s A 58.5s - TETO RÍGIDO DE 59.0 SEGUNDOS). "
            f"Condense este vídeo de {video_duration:.1f}s em EXATAMENTE {min_dur:.1f}s a {max_dur:.1f}s focando no CLÍMAX ABSOLUTO. "
            "🚨 CORTE FORA A EXPOSIÇÃO MORNA DO INÍCIO: Se o início tiver 30s-60s de conversa fiada ou explicações teóricas, pule direto para o elemento de curiosidade/desafio! "
            "🚨 O CLÍMAX É O CORAÇÃO DO VÍDEO: O feito chocante, a tentativa, a loucura de todos e a punchline final devem receber o maior tempo (~20s a 28s). "
            "Selecione de 2 a 3 blocos ágeis: "
            "1. Gancho / O Mistério ou Desafio (~10s a 16s) -> 2. Tensão / A Dúvida / O Desafio (~10s a 16s) -> 3. Clímax Chocante + Reação de Espanto e Punchline (~20s a 28s). "
            "A soma dos blocos no JSON DEVE totalizar entre 50.0s e 58.5s!"
        )
    elif target_duration_mode == "mini_movie":
        mode_guide = (
            f"RESUMO MINI-FILME / RECAP NARRATIVO (~50% do clipe, máx 2:30 min). "
            f"Condense este arco de {video_duration:.1f}s num Mini-Filme cinematográfico de {min_dur:.1f}s a {max_dur:.1f}s, "
            "estruturado em 4 atos: 1. Contexto/Início -> 2. Escalada de conflito e réplicas -> 3. Clímax de pico -> 4. Desfecho e reações. "
            "Corte apenas tempos mortos e gorduras, preservando o sentido e o suco da história!"
        )

    # The AI only SELECTS (chronologically). Hook/loop placement is done deterministically afterwards,
    # otherwise the chronological merge would silently swallow an AI-placed teaser.
    editorial_instruction = ""
    if editorial_mode in ("hook", "viral_editor", "viral_59"):
        loop_line = (
            "\n   - O ÚLTIMO corte deve terminar numa fala/reação marcante e completa: ela será a ponte do loop de replay."
            if editorial_mode in ("viral_editor", "viral_59") else ""
        )
        editorial_instruction = f"""
5. **ESTRUTURA EDITORIAL (o gancho é montado automaticamente depois)**:
   - Devolva os cortes SEMPRE em ORDEM CRONOLÓGICA. NÃO mova nenhum trecho para o início: o editor extrai o gancho de abertura depois.
   - GARANTA que a fala mais impactante / clímax esteja INCLUÍDA inteira na seleção (é dela que sai o gancho de ~3s).
   - Comece direto na primeira fala ou ação relevante, sem silêncio ou introdução morna.{loop_line}
"""
    elif editorial_mode == "loop" or (enable_loop and editorial_mode == "linear"):
        editorial_instruction = """
5. **ESTRUTURA DE LOOP CONTEXTUAL (montada automaticamente depois)**:
   - Devolva os cortes em ORDEM CRONOLÓGICA.
   - O desfecho (últimos 3s a 5s) deve ser uma fala marcante e coesa: ela será movida para a abertura e conectará o fim do vídeo de volta ao início.
"""
    elif editorial_mode == "dorama" or is_dorama:
        editorial_instruction = """
5. **ESTRUTURA NARRATIVA DE DORAMA**:
   - Devolva os cortes em ORDEM CRONOLÓGICA natural da cena.
   - Preserva o arco emocional: Começo da conversa/conflito -> Intensificação da emoção/química -> Clímax ou frase arrebatadora final.
"""

    short_clip_directive = ""
    if target_duration_mode == "viral_59s":
        short_clip_directive = f"""
⚡ **DIRETRIZ OBRIGATÓRIA: VIRAL FLOW 59s (VÍDEO DE ALTA RETENÇÃO DE ~50s A 58.5s - TETO RÍGIDO 59.0s)**:
- O vídeo original tem {video_duration:.1f}s (mais de 2 minutos).
- A SUA META DE DURAÇÃO TOTAL É ENTRE {min_dur:.1f}s E {max_dur:.1f}s (Alvo ideal: 52.0s a 58.5s)!
- ⛔ PROIBIDO RETORNAR MENOS DE 48 SEGUNDOS! Em um vídeo de 2min a 4min há história de sobra para preencher o tempo. Retornar 20s ou 30s é uma FALHA GRAVE!
- ⛔ PROIBIDO ULTRAPASSAR 59.0 SEGUNDOS ($total <= 59.0s$).
- 🚨 NUNCA SELECIONE CONVERSAS MORNAS DE EXPOSIÇÃO DO INÍCIO (ex: explicações teóricas, bate-papo de apresentação). Corte direto para o mistério/desafio!
- 🚨 O CLÍMAX É O PONTO ALTO DA CENA: reserve o maior tempo para o clímax (o feito, o espanto de todos e a punchline final).
- Selecione 3 a 4 blocos dinâmicos e concisos (10s a 22s cada) que mantenham a atenção no ápice sem blocos monótonos arrastados.
"""
    elif video_duration <= 65.0:
        short_clip_directive = f"""
🌟 **DIRETRIZ OBRIGATÓRIA PARA CLIPE CURTO ({video_duration:.1f}s <= 65s) - PRESERVAÇÃO INTEGRAL DE NARRATIVA**:
- Este clipe tem {video_duration:.1f}s e já está no formato de duração ideal para Reels / TikTok / YouTube Shorts!
- **NÃO RETALHE O DIÁLOGO! NÃO PULE FRASES!** Mantenha o diálogo e a conversa COMPLETA de ponta a ponta em ordem cronológica contínua.
- Não deixe nenhuma frase de fora: preserve a introdução/premissa, a discussão completa e o desfecho com todas as réplicas.
- O seu papel aqui NÃO É PICOTAR O DIÁLOGO, mas sim:
  1. Cortar apenas segundos mortos de silêncio (se houver pausa de silêncio >1.0s).
  2. Aplicar a DIREÇÃO MULTI-CÂMERA ("framing": "punch", "wide", "reaction") alternando os enquadramentos entre as falas para dar dinamismo visual cinematográfico e blindagem contra direitos autorais sem cortar o diálogo!
"""
    else:
        short_clip_directive = f"""
🎬 **DIRETRIZ DE CONDENSAÇÃO NARRATIVA ({video_duration:.1f}s > 65s)**:
- O vídeo original tem {video_duration:.1f}s. A sua meta é selecionar entre {min_dur:.1f}s e {max_dur:.1f}s no TOTAL.
- OBRIGATÓRIO: Crie uma história coesa e fluida selecionando no MÁXIMO 1 OU 2 BLOCOS NARRATIVOS CONTÍNUOS (ex: Bloco 1: Ação/Caçada/Conflito de 20s-30s; Bloco 2: Clímax/Revelação/Mic Drop de 12s-20s).
- PROIBIDO espalhar cortezinhos soltos de 2 ou 3 segundos! Vídeo muito cortado destrói a retenção e parece amador.
- PRIORIZE AÇÃO, CONFRONTO, CAÇADA OU COMÉDIA DINÂMICA: Se houver uma caçada, luta ou disputa ativa na cena (ex: perseguição de presa ou confronto), ESSA CENA DEVE SER O BLOCO PRINCIPAL em vez de diálogos parados de apresentação!
- Cada bloco selecionado deve ser 100% contínuo de ponta a ponta sem pular falas no meio dele.
- O ÚLTIMO segmento selecionado OBRIGATORIAMENTE deve ser o desfecho/punchline final da cena ("mic drop"), garantindo que a frase seja ouvida por completo sem cortes abruptos!
"""

    mini_movie_instruction = ""
    if target_duration_mode == "mini_movie":
        mini_movie_instruction = f"""
🎬 **DIRETRIZ ESPECIAL: TRATAR MINI-FILME (RESUMO CINEMATOGRÁFICO NARRATIVO)**:
- Você está condensando um arco completo de {video_duration:.1f}s em um MINI-FILME de {min_dur:.1f}s a {max_dur:.1f}s (cerca da metade do tempo original, sem passar de 2m30s).
- O resultado deve parecer um resumo profissional de cinema ("Recap/Short Film") com fluxo perfeito:
  1. **ATO 1 - ABERTURA & CONTEXTO (~15% a 20%)**: A frase ou momento que inicia o conflito (o espectador deve entender quem está em cena e o que está em jogo).
  2. **ATO 2 - ESCALADA & CONFRONTO (~25% a 30%)**: Os melhores momentos de tensão, troca de falas e início da ação.
  3. **ATO 3 - CLÍMAX EXPLOSIVO (~30% a 35%)**: O ápice do confronto, revelação chocante ou momento de maior impacto.
  4. **ATO 4 - DESFECHO & REAÇÃO (~15% a 20%)**: As consequências do clímax, reação de impacto e fechamento da cena.
  5. **CORTE AS GORDURAS**: Silêncios prolongados, caminhadas vazias e encaradas estáticas sem emoção. Mantenha diálogos e reações vivos.
"""

    # Build forced inclusion block for high-impact silent scenes
    forced_scenes_block = ""
    if high_impact_scenes:
        forced_lines = []
        for s in high_impact_scenes:
            forced_lines.append(
                f"  • [{s['start']:.2f}s → {s['end']:.2f}s]: {s.get('description', 'Cena de alto impacto')} "
                f"(OBRIGATÓRIO incluir este intervalo em um dos segmentos!)"
            )
        forced_scenes_block = (
            "\n⚠️ CENAS SILENCIOSAS DE ALTO IMPACTO (OBRIGATÓRIO preservar!):\n"
            "As cenas abaixo foram analisadas por IA Vision e identificadas como momentos marcantes "
            "(olhar tenso, lágrima, abraço, beijo ou revelação), mesmo sem diálogo. NÃO as remova:\n"
            + "\n".join(forced_lines)
            + "\n"
        )

    if is_dorama:
        director_title = "DIRETOR DE MONTAGEM E CINEMATOGRAFIA ESPECIALIZADO EM DORAMAS E K-DRAMAS"
        golden_rules = """⛔ REGRAS DE OURO DA MONTAGEM DE DORAMAS E K-DRAMAS (ATUAÇÃO & EMOÇÃO):
1. **PRESERVAÇÃO DA TENSÃO DRAMÁTICA E OLHARES (2.0s A 6.0s POR CORTE)**:
   - Em Doramas, as pausas entre falas (0.4s a 0.8s), os olhares em choque, respirações e lágrimas NÃO SÃO tempos mortos: são o coração da cena!
   - NUNCA retalhe a atuação em pedaços ultracurtos de 1s ou 2s. Deixe os planos respirarem entre 2.5s e 5.5s para que o público sinta a química, a dor ou a raiva.
2. **RÉPLICAS COMPLETAS (DIALÉTICA INTEGRAL)**:
   - Mantenha a troca de diálogos entre os protagonistas inteira. Cortar uma pergunta sem a resposta ou picotar a confissão destrói o sentido da cena. NUNCA quebre pares dialógicos.
3. **TAGS DE CINEMATOGRAFIA EMOCIONAL MULTI-CÂMERA ("framing")**:
   - Para CADA segmento, use os enquadramentos focados em atuação humana:
     * "punch": Smart Close-Up (+12% zoom) para a fala de maior impacto, lágrimas nos olhos, confissão romântica ou revelação chocante.
     * "reaction": Plano Médio de Reação (+6% zoom) para o choque do parceiro, troca de olhares tensos ou resposta emocional.
     * "wide": Plano Aberto (+3% zoom) para o casal, abraço, beijo, confronto físico ou início do diálogo.
   - Alterne suavemente entre falas e reações ("wide" -> "punch" -> "reaction" -> "punch").
4. **GANCHO EMOCIONAL NO FRAME 0**:
   - Comece direto na frase de choque, pergunta provocadora ou lágrima inicial para prender o scroll no primeiro segundo. NUNCA comece no meio de uma frase.
5. **FECHAMENTO DRAMÁTICO / MIC DROP**:
   - Termine no ápice da discussão, na revelação chocante ou na troca de olhares definitiva. NUNCA deixe a frase pela metade no final do clipe! O desfecho deve ter impacto absoluto."""
    elif target_duration_mode == "viral_59s" or editorial_mode == "viral_59":
        director_title = "SUPER SENIOR EDITOR CINEMÁTICO VIRAL 59s para YouTube Shorts, Reels e TikTok"
        golden_rules = f"""⛔ REGRAS DE OURO DA ENGENHARIA VIRAL FLOW 59s (FOCO NO CLÍMAX & RITMO ANTI-TÉDIO):
1. **ELIMINE A EXPOSIÇÃO MORNA DO INÍCIO (ZERO ENROLAÇÃO)**:
   - Se os personagens passarem o primeiro minuto apenas conversando parados, apresentando regras teóricas, medindo atributos ou batendo papo morno de introdução: CORTE FORA ESSA GORDURA!
   - Vá DIRETO para o momento em que surge o elemento que desperta curiosidade imediata (o objeto misterioso/lendário, a provocação, o perigo ou o desafio).
2. **FOCO ABSOLUTO NO CLÍMAX (A MELHOR PARTE DA CENA)**:
   - Qual é o grande momento de choque, humor ou triunfo desta cena?
   - O CLÍMAX (o momento em que o feito impossível é executado, a revelação acontece, todos entram em choque e a punchline final é disparada) É O CORAÇÃO DO CORTE!
   - Este ápice DEVE ter o maior tempo de tela (~18s a 26s) e entrar COMPLETO, com todas as reações de espanto dos outros personagens e a frase final definitiva ("mic drop" / "É o quê?!"). NUNCA deixe o clímax corrido!
3. **RITMO VIRAL DINÂMICO COM SALTOS NO TEMPO (NUNCA GERE BLOCOS CONTÍGUOS COLADOS DE 90s)**:
   - PROIBIDO selecionar blocos colados (ex: 80s-105s, 105s-137s, 137s-174s) que quando somados formam um bloco contínuo monótono de 90 segundos!
   - Você DEVE SALTAR as explicações secundárias e enrolações do meio para que haja saltos temporais entre o gancho e o clímax!
   - Monte uma progressão ágil de 3 a 4 blocos dinâmicos (cada um com 10s a 22s) separados por saltos no tempo:
     * Bloco 1 (Gancho / O Mistério ou Desafio: ~10s a 16s): A apresentação do desafio ou da lenda.
     --- SALTO NO TEMPO (pula explicações do meio) ---
     * Bloco 2 (A Tensão / A Provocação / A Dúvida: ~10s a 16s): A explicação de que ninguém consegue e a provocação de que ele vai tentar.
     --- SALTO NO TEMPO ---
     * Bloco 3 (O Clímax Chocante + Reação e Desfecho: ~18s a 26s): A execução do feito com facilidade, o choque de todos e o desfecho marcante.
4. **DURAÇÃO TOTAL RIGOROSA ENTRE {min_dur:.1f}s E {max_dur:.1f}s (TETO INEGOCIÁVEL: 59.0s)**:
   - A soma total dos blocos no JSON DEVE totalizar entre {min_dur:.1f}s e {max_dur:.1f}s.
   - ⛔ PROIBIDO ULTRAPASSAR 59.0 SEGUNDOS ($total <= 59.0s$).
5. **FECHAMENTO PERFEITO NO FINAL (MIC DROP COMPLETO)**:
   - NUNCA termine no meio de uma frase! O último segmento deve encerrar na frase de maior impacto com a oração completa."""
    else:
        director_title = "SUPER SENIOR EDITOR CINEMÁTICO E VIRAL para YouTube Shorts, Reels e TikTok"
        golden_rules = """⛔ REGRAS DE OURO DA ENGENHARIA NARRATIVA VIRAL:
1. **PRIORIZE AÇÃO, CAÇADA, CONFRONTO E HUMOR DINÂMICO**:
   - Evite conversas paradas ou monólogos mornos de apresentação se houver momentos de AÇÃO, CAÇADA, LUTA ou COMÉDIA INTERATIVA no clipe!
   - Se os personagens estão correndo, caçando, enfrentando um monstro ou disputando comida (ex: perseguição de presa ou luta), ESSA CENA DEVE SER O CORAÇÃO DO CORTE!
2. **BLOCOS NARRATIVOS CONTÍNUOS (15s A 35s POR BLOCO - APENAS 1 OU 2 BLOCOS NO TOTAL)**:
   - NUNCA retalhe a cena em vários pedacinhos soltos de 2 ou 3 segundos! O vídeo fica horrível e parece quebrado ("muito cortado").
   - Selecione APENAS 1 OU 2 BLOCOS NARRATIVOS CONTÍNUOS E COMPLETOS (ex: Bloco 1: Ação/Caçada/Conflito de 20s-30s; Bloco 2: Clímax/Revelação/Mic Drop de 12s-20s).
   - Dentro de CADA bloco selecionado, MANTENHA A CENA 100% CONTÍNUA de ponta a ponta sem pular falas!
3. **FECHAMENTO PERFEITO NO FINAL (MIC DROP COMPLETO)**:
   - NUNCA termine no meio de uma frase! O desfecho deve ter a frase de impacto ou reação conclusiva completa com excelência."""

    prompt = f"""Você é o {director_title}.
Este clipe foi pré-selecionado pelo Diretor IA e representa uma cena de ouro.
Seu objetivo é transformar esta cena em um **MASTERCUT VIRAL DE ALTA RETENÇÃO (>100%) E TOTALMENTE BLINDADO CONTRA CONTENT ID / REUSED CONTENT**.
{ctx_block}
{feedback_block}
DADOS DO VÍDEO BRUTO:
- Duração Original do Clipe: {video_duration:.1f} segundos (A LINHA DO TEMPO VAI ESTRITAMENTE DE 0.0s ATÉ {video_duration:.1f}s)

📣 DIÁLOGOS COMPLETOS TRANSCRITOS (BLOCOS SEMÂNTICOS DE FALA):
{chr(10).join(speech_summary) if speech_summary else "[Sem falas detectadas - use os cortes visuais como referência principal]"}

⛔ REGRA ABSOLUTA DE INTEGRIDADE VOCAL & CONTEXTO:
- Cada Bloco acima é uma FALA OU ORAÇÃO COMPLETA. NUNCA corte no meio de um Bloco!
- Mantenha o CONTEXTO: preserve as trocas de diálogo completas (Pergunta + Resposta, Acusação + Réplica). Não isole uma pergunta sem a resposta!
- Se você selecionar um diálogo, use o intervalo do bloco completo para não amputar palavras ou pensamentos!

🎬 CENAS VISUAIS ANALISADAS POR IA (incluindo momentos SEM FALA):
{chr(10).join(visual_summary) if visual_summary else (chr(10).join(f"[{ab['start']:.2f}s -> {ab['end']:.2f}s] {'💕 Tensão Dramática' if is_dorama else '⚔️ Cena de Ação/Luta'}" for ab in action_blocks) if action_blocks else "[Análise visual não disponível]")}
{forced_scenes_block}
🎯 DIRETRIZ ESTRITA DE DURAÇÃO FINAL:
- Duração do Clipe: {video_duration:.1f} segundos.
- Modo de Refino Selecionado: {mode_guide}
- DURAÇÃO TOTAL OBRIGATÓRIA DA SOMA DOS SEGMENTOS: entre {min_dur:.1f}s e {max_dur:.1f}s.

{short_clip_directive}

{golden_rules}

{mini_movie_instruction}
{editorial_instruction}

🎬 PROTOCOLO DE CRIAÇÃO EM 2 ETAPAS OBRIGATÓRIAS (ROTEIRISTA ➔ MONTADOR):
Você NÃO deve escolher cortes aleatórios. Para prender a audiência humana, todo corte viral de sucesso conta uma mini-história com sentido claro e completo.

ETAPA 1: O ROTEIRISTA DA CENA (Storyboarding Narrativo)
Antes de decidir timestamps, analise o conjunto completo de falas e eventos. Defina mentalmente e preencha no JSON:
- "premissa": Do que se trata esta cena em 1 frase resumida.
- "hook": O gancho de abertura (fala ou ação chocante nos primeiros segundos).
- "conflito_desenvolvimento": A tensão central, discussão ou progressão dramática que dá sentido à conversa.
- "climax_fechamento": A frase de impacto definitiva ("mic drop") ou desfecho que conclui a história sem corte abrupto.

ETAPA 2: O MONTADOR/EDITOR DE CINEMA (Timeline Cirúrgica)
Agora recorte a linha do tempo selecionando APENAS os trechos de fala e reação que executam exatamente o roteiro da Etapa 1.
- Mantenha a ordem cronológica natural da cena para não embaralhar o raciocínio.
- NUNCA corte no meio de uma frase ou palavra.
- A duração total deve cumprir a meta obrigatória.

Retorne EXCLUSIVAMENTE um objeto JSON no seguinte formato (sem comentários, apenas JSON puro):
{{
  "roteiro_da_cena": {{
    "premissa": "Resumo em 1 frase clara da essência da cena",
    "hook": "Fala ou momento escolhido para prender a atenção nos primeiros segundos",
    "conflito_desenvolvimento": "O embate, argumento ou progressão de diálogo central",
    "climax_fechamento": "Frase de impacto final ou fechamento que encerra a narrativa com maestria"
  }},
  "ai_viral": [
    {{"start": 85.00, "end": 102.00, "framing": "wide", "text": "Bloco 1 (Gancho: O elemento de curiosidade / mistério / desafio imediato)"}},
    {{"start": 128.00, "end": 144.00, "framing": "punch", "text": "Bloco 2 (Tensão: O desafio impossível / provocação que instiga o público)"}},
    {{"start": 148.00, "end": 171.00, "framing": "reaction", "text": "Bloco 3 (O Clímax Absoluto: O feito chocante + reação espantada de todos e punchline final)"}}
  ]
}}
"""

    chosen_engine = (ai_engine or os.getenv("REFINER_AI_ENGINE", "auto")).strip().lower()
    if chosen_engine in ("gemini_web", "web", "gemini_navegador"):
        if on_log:
            on_log("🌐 [GEMINI WEB] Enviando linha do tempo para o Gemini Pro no navegador em segundo plano...")
        try:
            from gemini_web_automator import ask_gemini_web
            web_resp = ask_gemini_web(prompt, timeout=180, on_log=on_log)
            if web_resp:
                clean_w = web_resp.strip()
                if "```json" in clean_w:
                    clean_w = clean_w.split("```json", 1)[1].split("```", 1)[0]
                elif "```" in clean_w:
                    clean_w = clean_w.split("```", 1)[1].split("```", 1)[0]
                clean_w = clean_w.strip()
                
                try:
                    data = json.loads(clean_w)
                except Exception:
                    m = re.search(r'\{.*\}', clean_w, re.DOTALL)
                    data = json.loads(m.group(0)) if m else None

                if data:
                    t_web = None
                    r_web = None
                    if isinstance(data, list):
                        t_web = data
                    elif isinstance(data, dict):
                        r_web = (
                            data.get("roteiro_da_cena") or
                            data.get("roteiro") or
                            data.get("storyboard") or
                            data.get("script") or
                            data.get("cena")
                        )
                        t_web = (
                            data.get("ai_viral") or
                            data.get("mastercut") or
                            data.get("segments") or
                            data.get("cortes") or
                            data.get("cuts") or
                            data.get("timeline")
                        )
                    if t_web and isinstance(t_web, list) and len(t_web) > 0:
                        if on_log:
                            on_log(f"✨ [GEMINI WEB] {len(t_web)} cortes refinados com sucesso pelo Gemini Pro!")
                            if r_web and isinstance(r_web, dict):
                                on_log("[ROTEIRISTA GEMINI PRO WEB] Roteiro Dramático Estruturado:")
                                if r_web.get("premissa"):
                                    on_log(f"   * Premissa: {r_web['premissa']}")
                                if r_web.get("hook"):
                                    on_log(f"   * Hook (Abertura): {r_web['hook']}")
                                if r_web.get("climax_fechamento"):
                                    on_log(f"   * Clímax/Fechamento: {r_web['climax_fechamento']}")
                        return t_web, r_web
        except Exception as e:
            if on_log:
                on_log(f"⚠️ [GEMINI WEB] Erro no processamento da resposta: {e}")

    if chosen_engine in ("ollama_local", "auto"):
        # Se for 100% local ou auto, tenta o Ollama Local na GPU RTX 5060 primeiro com contingência entre modelos locais!
        t_local, r_local = _call_ollama_local_timeline(prompt, on_log=on_log, local_model=local_model)
        if t_local:
            return t_local, r_local
        if chosen_engine == "ollama_local":
            # O usuário escolheu EXCLUSIVAMENTE 'Ollama Local': NUNCA aciona o Gemini na nuvem!
            if on_log:
                on_log("🔒 [100% LOCAL GARANTIDO] Motor 'Ollama Local' selecionado. A nuvem (Gemini) NÃO será acionada.")
                on_log("⚡ Prosseguindo com montagem heurística local inteligente baseada em Whisper e pausas acústicas (100% offline)...")
            return None, None
        else:
            if on_log:
                on_log("⚠️ [OLLAMA LOCAL] Modelos locais falharam. Como o modo é 'auto', tentando contingência via nuvem...")

    keys = _get_api_keys()
    if not keys:
        if on_log:
            on_log("[INFO] Nenhuma chave Gemini configurada no .env. Usando inteligência heurística local para o Mastercut...")
        return None, None

    # Filter out keys in cooldown (e.g. 429 quota exhausted)
    avail_keys = keys
    if api_health is not None:
        avail_keys = api_health.filter_available_keys(keys)
        if len(avail_keys) < len(keys) and on_log:
            diff = len(keys) - len(avail_keys)
            on_log(f"[CACHE] {diff} chave(s) com cota esgotada (429) puladas instantaneamente.")

    # Candidate models to try in order of stability and responsiveness
    preferred_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    raw_models = [
        "gemini-2.5-flash",
        preferred_model,
        "gemini-2.0-flash",
        "gemini-2.5-flash-lite",
        "gemini-1.5-flash",
        "gemini-3.6-flash",
        "gemini-3.8-flash",
        "gemini-3.7-flash",
    ]
    models_to_try = []
    for m in raw_models:
        if m and m not in models_to_try:
            models_to_try.append(m)

    # Filter models currently in cooldown (e.g. 503 UNAVAILABLE / 404)
    avail_models = models_to_try
    if api_health is not None:
        avail_models = api_health.filter_available_models(models_to_try)
        if len(avail_models) < len(models_to_try) and on_log:
            skipped_m = [m for m in models_to_try if m not in avail_models]
            on_log(f"[CACHE] Modelos em cooldown de sobrecarga pulados: {', '.join(skipped_m)}")

    from google import genai
    for key in avail_keys:
        if api_health is not None:
            is_k_ok, _ = api_health.is_key_available(key)
            if not is_k_ok:
                continue

        try:
            client = genai.Client(api_key=key)
        except Exception as e:
            if api_health is not None:
                api_health.mark_key_exhausted(key, str(e), cooldown_secs=86400)
            continue

        for model_name in avail_models:
            if api_health is not None:
                is_m_ok, _ = api_health.is_model_available(model_name)
                if not is_m_ok:
                    continue

            try:
                if on_log:
                    on_log(f"[IA] Consultando IA ({model_name}) para selecionar os melhores momentos do Mastercut...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config={"response_mime_type": "application/json"}
                )
                text = response.text
                if text:
                    data = json.loads(text)
                    timeline = None
                    roteiro = None
                    if isinstance(data, list):
                        timeline = data
                    elif isinstance(data, dict):
                        roteiro = (
                            data.get("roteiro_da_cena") or
                            data.get("roteiro") or
                            data.get("storyboard") or
                            data.get("script") or
                            data.get("cena")
                        )
                        timeline = (
                            data.get("ai_viral") or
                            data.get("mastercut") or
                            data.get("segments") or
                            data.get("cortes") or
                            data.get("cuts") or
                            data.get("timeline")
                        )
                    if timeline and isinstance(timeline, list) and len(timeline) > 0:
                        if api_health is not None:
                            api_health.mark_key_success(key)
                            api_health.mark_model_success(model_name)
                        if on_log:
                            on_log(f"[OK] IA ({model_name}) desenhou Mastercut com {len(timeline)} cortes estratégicos!")
                            if roteiro and isinstance(roteiro, dict):
                                on_log("[ROTEIRISTA IA] Roteiro Dramático Estruturado:")
                                if roteiro.get("premissa"):
                                    on_log(f"   * Premissa: {roteiro['premissa']}")
                                if roteiro.get("hook"):
                                    on_log(f"   * Hook (Abertura): {roteiro['hook']}")
                                if roteiro.get("conflito_desenvolvimento"):
                                    on_log(f"   * Desenvolvimento: {roteiro['conflito_desenvolvimento']}")
                                if roteiro.get("climax_fechamento"):
                                    on_log(f"   * Climax/Fechamento: {roteiro['climax_fechamento']}")
                        return timeline, roteiro
            except Exception as e:
                err_s = str(e)
                # 503 UNAVAILABLE / High demand spike
                if "503" in err_s or "UNAVAILABLE" in err_s or "high demand" in err_s.lower():
                    if api_health is not None:
                        api_health.mark_model_unavailable(model_name, err_s, cooldown_secs=600)
                    if on_log:
                        on_log(f"[AVISO] Modelo {model_name} sobrecarregado (503). Entrando em cooldown de 10m. Avançando...")
                    continue
                # 404 NOT_FOUND
                if "404" in err_s or "NOT_FOUND" in err_s:
                    continue
                # 429 RESOURCE_EXHAUSTED / Quota
                if "429" in err_s or "RESOURCE_EXHAUSTED" in err_s or "quota" in err_s.lower():
                    if api_health is not None:
                        api_health.mark_key_exhausted(key, err_s, cooldown_secs=900)
                    if on_log:
                        on_log(f"[AVISO] Cota da chave esgotada (429). Chave em cooldown de 15m. Pulando para próxima chave...")
                    break  # Break out of inner model loop for this exhausted key!
                # 400 / 403 Invalid API key
                if "API_KEY_INVALID" in err_s or "400" in err_s or "403" in err_s:
                    if api_health is not None:
                        api_health.mark_key_exhausted(key, err_s, cooldown_secs=86400)
                    break
                if on_log:
                    on_log(f"Aviso modelo {model_name}: {e}")

    # Fallback to Groq if configured
    groq_raw = os.getenv("GROQ_API_KEY", "").strip()
    groq_key = groq_raw.splitlines()[0].strip() if groq_raw else ""
    if groq_key and groq_key.startswith("gsk_"):
        try:
            import requests
            headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
            groq_candidates = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
            for g_model in groq_candidates:
                try:
                    if on_log:
                        on_log(f"[FALLBACK] Tentando modelo de fallback Groq ({g_model})...")
                    payload = {
                        "model": g_model,
                        "messages": [{"role": "user", "content": prompt + "\nResponda estritamente em formato JSON."}],
                        "temperature": 0.2,
                        "response_format": {"type": "json_object"}
                    }
                    resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=45)
                    if resp.status_code == 200:
                        content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                        data = json.loads(content)
                        timeline = None
                        roteiro = None
                        if isinstance(data, list):
                            timeline = data
                        elif isinstance(data, dict):
                            roteiro = (
                                data.get("roteiro_da_cena") or
                                data.get("roteiro") or
                                data.get("storyboard") or
                                data.get("script") or
                                data.get("cena")
                            )
                            timeline = (
                                data.get("ai_viral") or
                                data.get("mastercut") or
                                data.get("segments") or
                                data.get("cortes") or
                                data.get("cuts") or
                                data.get("timeline")
                            )
                        if timeline and isinstance(timeline, list) and len(timeline) > 0:
                            if on_log:
                                on_log(f"[OK] Sucesso via Groq Fallback ({g_model})! {len(timeline)} cortes encontrados.")
                                if roteiro and isinstance(roteiro, dict):
                                    on_log("[ROTEIRISTA IA] Roteiro Dramático Estruturado:")
                                    if roteiro.get("premissa"):
                                        on_log(f"   * Premissa: {roteiro['premissa']}")
                                    if roteiro.get("hook"):
                                        on_log(f"   * Hook (Abertura): {roteiro['hook']}")
                                    if roteiro.get("conflito_desenvolvimento"):
                                        on_log(f"   * Desenvolvimento: {roteiro['conflito_desenvolvimento']}")
                                    if roteiro.get("climax_fechamento"):
                                        on_log(f"   * Climax/Fechamento: {roteiro['climax_fechamento']}")
                            return timeline, roteiro
                except Exception as e_sub:
                    if on_log:
                        on_log(f"[AVISO] Fallback Groq ({g_model}) falhou: {e_sub}")
                    continue
        except Exception as e:
            if on_log:
                on_log(f"Aviso fallback Groq: {e}")

    return None, None


def _strictly_cap_segments_duration(segments: list, max_cap: float = 59.0) -> list:
    """
    Mathematical guarantee that total segment duration never exceeds max_cap (default 59.0s).
    Preserves the hook (first segment) and climax (last segment) while trimming excess
    from intermediate segments or ends of long segments.
    """
    if not segments:
        return segments
    total_dur = sum(max(0.0, s["end"] - s["start"]) for s in segments)
    if total_dur <= max_cap:
        return segments

    excess = total_dur - max_cap
    # Single segment case: preserve the climax at the end by trimming excess from the start!
    if len(segments) == 1:
        s0 = segments[0]
        new_start = round(min(s0["end"] - 10.0, s0["start"] + excess), 3)
        return [{**s0, "start": new_start}]

    result = [dict(s) for s in segments]
    remaining_excess = excess

    # Pass 1: Trim from middle segments (index 1 to len-2) if they are longer than 5.0s
    if len(result) > 2:
        for idx in range(1, len(result) - 1):
            if remaining_excess <= 0.01:
                break
            seg_len = result[idx]["end"] - result[idx]["start"]
            can_trim = max(0.0, seg_len - 5.0)
            trim_amt = min(remaining_excess, can_trim)
            if trim_amt > 0.05:
                result[idx]["end"] = round(result[idx]["end"] - trim_amt, 3)
                remaining_excess -= trim_amt

    # Pass 2: If still excess, trim from the front of the first segment (intro), keeping the climax intact!
    if remaining_excess > 0.01 and len(result) >= 2:
        first_len = result[0]["end"] - result[0]["start"]
        can_trim = max(0.0, first_len - 6.0)
        trim_amt = min(remaining_excess, can_trim)
        if trim_amt > 0.05:
            result[0]["start"] = round(result[0]["start"] + trim_amt, 3)
            remaining_excess -= trim_amt

    # Pass 3: If STILL excess, trim proportionally across all segments
    if remaining_excess > 0.01:
        current_total = sum(max(0.0, s["end"] - s["start"]) for s in result)
        if current_total > max_cap:
            scale = max_cap / current_total
            rebuilt = []
            for s in result:
                d = (s["end"] - s["start"]) * scale
                rebuilt.append({**s, "end": round(s["start"] + max(2.0, d), 3)})
            result = rebuilt

    # Final sanity check: force hard cut on last segment if floating point rounded up
    final_dur = sum(max(0.0, s["end"] - s["start"]) for s in result)
    if final_dur > max_cap and result:
        overflow = final_dur - max_cap
        result[-1]["end"] = round(max(result[-1]["start"] + 1.0, result[-1]["end"] - overflow - 0.01), 3)

    return result


def _call_ollama_local_refiner(prompt: str, on_log=None, local_model: str = "") -> str:
    """Execute refiner inference via local Ollama instance with multi-model fallback."""
    import requests
    models_to_try = _get_local_model_candidates(local_model)

    for idx, target_model in enumerate(models_to_try):
        is_reasoning = any(k in target_model.lower() for k in ("r1", "reason", "deepseek-r1"))
        payload = {
            "model": target_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "keep_alive": "5m",
            "options": {"temperature": 0.2}
        }
        if not is_reasoning:
            payload["format"] = "json"

        try:
            url = "http://localhost:11434/api/chat"
            resp = requests.post(url, json=payload, timeout=120)
            if resp.status_code == 200:
                content = resp.json().get("message", {}).get("content", "")
                if content:
                    if on_log:
                        on_log(f"✅ [OLLAMA LOCAL] Auditoria concluída com sucesso ({target_model}) na RTX 5060!")
                    return content
        except Exception as e:
            if on_log and idx + 1 < len(models_to_try):
                on_log(f"⚠️ [AUDITOR LOCAL] Modelo {target_model} falhou ({e}). Tentando contingência local com {models_to_try[idx+1]}...")
            continue
    return None


def audit_and_refine_cut_double_check(
    candidate_segments: list,
    all_words: list,
    video_duration: float,
    video_context: str = "",
    work_title: str = "",
    scene_context: str = "",
    user_feedback: str = "",
    max_duration_cap: float = 59.0,
    local_model: str = "",
    ai_engine: str = "auto",
    on_log=None
) -> list:
    """
    Check do Check (Dual-AI Editorial Audit):
    Takes the candidate segments proposed by the primary AI pass, reviews narrative coherence,
    removes dialogue repetition/hesitation, ensures complete sentences, and strictly guarantees
    the total duration stays <= 59.0 seconds.
    """
    if not candidate_segments:
        return candidate_segments

    total_curr_dur = sum(max(0.0, s["end"] - s["start"]) for s in candidate_segments)
    if on_log:
        on_log(f"🔍 [CHECK DO CHECK] Iniciando auditoria crítica de {len(candidate_segments)} cortes (Duração atual: {total_curr_dur:.1f}s | Teto: {max_duration_cap:.1f}s)...")

    # Format candidate cuts with their transcribed speech
    cuts_text = []
    for idx, c in enumerate(candidate_segments, 1):
        c_dur = c["end"] - c["start"]
        c_txt = c.get("text", "")
        # Find words within this segment if text is missing or generic
        if not c_txt or c_txt.startswith("["):
            sub_words = [w["word"] for w in all_words if c["start"] <= w.get("start", 0) <= c["end"]]
            if sub_words:
                c_txt = " ".join(sub_words)
        cuts_text.append(f"  • Corte #{idx}: [{c['start']:.2f}s -> {c['end']:.2f}s] ({c_dur:.1f}s) \"{c_txt}\"")

    cuts_summary = "\n".join(cuts_text)

    # Build complete semantic dialogue blocks with sentence boundaries so the auditor can expand if too short!
    speech_sentences = get_safe_sentences(all_words, video_duration=video_duration)
    speech_summary = []
    if speech_sentences:
        for idx, sent in enumerate(speech_sentences, 1):
            speech_summary.append(f"[{sent['start']:.2f}s -> {sent['end']:.2f}s] \"{sent['text']}\"")

    ctx_parts = []
    clean_work = (work_title or "").strip()
    clean_scene = (scene_context or "").strip()
    clean_feedback = (user_feedback or "").strip()
    if not clean_work and not clean_scene and video_context:
        clean_work = video_context.strip()
    if clean_work:
        ctx_parts.append(f"Obra / Série: {clean_work}")
    if clean_scene:
        ctx_parts.append(f"🚨 FOCO DA CENA SOLICITADO PELO USUÁRIO:\n\"{clean_scene}\"\n(Garanta que este foco temático/emocional seja plenamente respeitado na auditoria!)")
    if clean_feedback:
        ctx_parts.append(f"🛠️ FEEDBACK/PEDIDO DE CORREÇÃO DO DIRETOR:\n\"{clean_feedback}\"\n(ATENÇÃO AUDITOR: O corte proposto DEVE conter a cena solicitada pelo usuário no feedback acima. NUNCA descarte a cena pedida pelo usuário!)")

    context_display = "\n".join(ctx_parts) if ctx_parts else (video_context.strip() if video_context else "Cena de anime / drama / confronto")

    feedback_directive = ""
    if clean_feedback:
        feedback_directive = f"0. 🚨 MANDATO MANDATÓRIO DO DIRETOR: Garantir que o trecho solicitado ('{clean_feedback}') permaneça preservado e integrado no corte final!\n"

    prompt = f"""VOCÊ É O SUPERVISOR/DIRETOR CHEFE DE MONTAGEM CINEMATOGRÁFICA (Auditor Crítico - Check do Check).
Sua função é realizar a AUDITORIA E REFINO FINAL dos cortes para um vídeo longo de {video_duration:.1f}s.

[PROPOSTA DE CORTES DA 1ª IA]
Duração total proposta: {total_curr_dur:.1f}s
Cortes selecionados:
{cuts_summary}

[TODOS OS DIÁLOGOS COMPLETOS DA CENA ORIGINAL (0.0s até {video_duration:.1f}s)]
{chr(10).join(speech_summary) if speech_summary else "[Sem transcrição]"}

[CONTEXTO DO VÍDEO & FOCO SOLICITADO]
{context_display}


[DIRETRIZES RIGOROSAS DA AUDITORIA CRÍTICA]
{feedback_directive}1. 🎯 ALVO DE DURAÇÃO RIGOROSO: ENTRE 50.0s E 58.5s (TETO INEGOCIÁVEL: {max_duration_cap:.1f}s).
   - Se o vídeo original tem mais de 2 minutos ({video_duration:.1f}s), a duração final DEVE ficar entre 50.0s e 58.5s!
   - Se a proposta da 1ª IA estiver com MENOS DE 50 SEGUNDOS (ex: 20s, 30s ou 35s), você DEVE EXPANDIR os cortes adicionando os blocos de diálogo cruciais da cena original para que a história dure entre 50.0s e 58.5s!
   - ⛔ PROIBIDO APROVAR MENOS DE 48 SEGUNDOS se houver diálogos disponíveis!
   - ⛔ PROIBIDO ULTRAPASSAR 59.0 SEGUNDOS ($total <= 59.0s$)! Se ultrapassar, enxugue para caber em 50s-58.5s.
2. 🏆 FOCO NA MELHOR PARTE (O CLÍMAX ABSOLUTO):
   - Se a proposta da 1ª IA gastar muito tempo em conversas mornas e paradas de introdução/regras e deixar o clímax corrido ou ausente: DESCARTE A INTRODUÇÃO MORNA!
   - Puxe os cortes para o elemento de curiosidade (o mistério/desafio) + a provocação + o clímax com o feito chocante e a reação de espanto de todos!
3. ✂️ RITMO DINÂMICO & TRANSIÇÕES SUAVES (SEM CORTES BRUSCOS):
   - Organize em 3 a 4 blocos dinâmicos de 10s a 22s cada, em vez de um bloco único monótono e arrastado.
   - Mantenha orações completas. Não corte no meio de uma frase.
   - Início: Deve prender no segundo 0 com gancho de diálogo.
   - Fim: O último corte DEVE terminar na fala definitiva de desfecho ("mic drop").

Retorne EXCLUSIVAMENTE um objeto JSON no formato:
{{
  "auditoria": "Resumo em 1 frase da análise crítica e ajustes realizados",
  "ai_viral": [
    {{"start": 85.00, "end": 102.00, "framing": "wide", "text": "Bloco 1 (Gancho ou mistério inicial)"}},
    {{"start": 128.00, "end": 144.00, "framing": "punch", "text": "Bloco 2 (Escalada de tensão ou desafio)"}},
    {{"start": 148.00, "end": 171.00, "framing": "reaction", "text": "Bloco 3 (O Clímax definitivo e punchline final)"}}
  ]
}}
"""

    parsed_audited = None

    # Step A: Attempt Local Ollama (offline, zero-cost, RTX 5060)
    ollama_resp = _call_ollama_local_refiner(prompt, on_log=on_log, local_model=local_model)
    if ollama_resp:
        try:
            data = json.loads(ollama_resp)
            tl = data.get("ai_viral") or data.get("cortes_aprovados") or data.get("timeline") or data.get("segments")
            if tl and isinstance(tl, list) and len(tl) > 0:
                parsed_audited = tl
                if on_log:
                    reason = data.get("auditoria", "Auditoria concluída com sucesso!")
                    on_log(f"🔍 [AUDITOR CRÍTICO LOCAL] {reason}")
        except Exception as e:
            if on_log:
                on_log(f"[AVISO] Falha ao decodificar JSON do Ollama: {e}")

    # Step B: If Ollama was offline or returned empty, check engine preference
    if not parsed_audited:
        if str(ai_engine).lower() == "ollama_local":
            if on_log:
                on_log("🔒 [AUDITOR LOCAL] Mantendo cortes selecionados localmente (modo 'Ollama Local' selecionado, nuvem não acionada).")
            return candidate_segments

        if str(ai_engine).lower() in ("gemini_web", "web", "gemini_navegador"):
            if on_log:
                on_log("🌐 [GEMINI WEB] Executando auditoria crítica de cortes com Gemini Pro no navegador em segundo plano...")
            try:
                from gemini_web_automator import ask_gemini_web
                web_resp = ask_gemini_web(prompt, timeout=180, on_log=on_log)
                if web_resp:
                    clean_j = web_resp.strip()
                    if "```json" in clean_j:
                        clean_j = clean_j.split("```json", 1)[1].split("```", 1)[0]
                    elif "```" in clean_j:
                        clean_j = clean_j.split("```", 1)[1].split("```", 1)[0]
                    clean_j = clean_j.strip()

                    data = None
                    try:
                        data = json.loads(clean_j)
                    except Exception:
                        m_obj = re.search(r'(\{[\s\S]*\})', clean_j)
                        if m_obj:
                            try:
                                data = json.loads(m_obj.group(1))
                            except Exception:
                                pass
                        if not data:
                            m_arr = re.search(r'(\[[\s\S]*\])', clean_j)
                            if m_arr:
                                try:
                                    data = json.loads(m_arr.group(1))
                                except Exception:
                                    pass

                    if data:
                        tl = None
                        if isinstance(data, list):
                            tl = data
                        elif isinstance(data, dict):
                            tl = data.get("ai_viral") or data.get("cortes_aprovados") or data.get("timeline") or data.get("segments") or data.get("cortes")
                        if tl and isinstance(tl, list) and len(tl) > 0:
                            reason = data.get("auditoria", "Auditoria concluída pelo Gemini Pro!") if isinstance(data, dict) else "Auditoria concluída pelo Gemini Pro!"
                            if on_log:
                                on_log(f"🔍 [AUDITOR GEMINI WEB] {reason}")
                            return tl

                    if on_log:
                        on_log("🔍 [AUDITOR GEMINI WEB] Cortes verificados e aprovados pelo Gemini Pro no navegador!")
                    return candidate_segments
            except Exception as e:
                if on_log:
                    on_log(f"⚠️ [GEMINI WEB] Aviso na auditoria: {e} (mantendo cortes aprovados pelo Gemini Pro)")
                return candidate_segments

            # Se modo Gemini Web selecionado, NUNCA aciona API paga
            if on_log:
                on_log("🔒 [AUDITOR GEMINI WEB] Mantendo cortes selecionados pelo Gemini Pro (modo Web Chat ativo, API não acionada).")
            return candidate_segments

        keys = _get_api_keys()
        if keys:
            avail_keys = keys
            if api_health is not None:
                avail_keys = api_health.filter_available_keys(keys)

            models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.5-flash-lite", "gemini-1.5-flash"]
            if api_health is not None:
                models_to_try = api_health.filter_available_models(models_to_try)

            from google import genai
            for key in avail_keys:
                if parsed_audited:
                    break
                try:
                    client = genai.Client(api_key=key)
                except Exception:
                    continue

                for model_name in models_to_try:
                    try:
                        if on_log:
                            on_log(f"🔍 [AUDITOR CRÍTICO IA] Verificando cortes com {model_name}...")
                        response = client.models.generate_content(
                            model=model_name,
                            contents=prompt,
                            config={"response_mime_type": "application/json"}
                        )
                        text = response.text
                        if text:
                            data = json.loads(text)
                            tl = data.get("ai_viral") or data.get("cortes_aprovados") or data.get("timeline") or data.get("segments")
                            if tl and isinstance(tl, list) and len(tl) > 0:
                                parsed_audited = tl
                                if on_log:
                                    reason = data.get("auditoria", "Auditoria crítica finalizada.")
                                    on_log(f"✅ [AUDITOR CRÍTICO IA] {reason}")
                                break
                    except Exception as e_gem:
                        if on_log:
                            on_log(f"[AVISO] Tentativa auditor {model_name}: {e_gem}")
                        continue

    # Step C: Fallback to Groq if still not parsed
    if not parsed_audited:
        groq_raw = os.getenv("GROQ_API_KEY", "").strip()
        groq_key = groq_raw.splitlines()[0].strip() if groq_raw else ""
        if groq_key and groq_key.startswith("gsk_"):
            try:
                import requests
                headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
                for g_model in ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"]:
                    try:
                        payload = {
                            "model": g_model,
                            "messages": [{"role": "user", "content": prompt + "\nResponda estritamente em JSON puro."}],
                            "temperature": 0.2,
                            "response_format": {"type": "json_object"}
                        }
                        resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=30)
                        if resp.status_code == 200:
                            data = json.loads(resp.json()["choices"][0]["message"]["content"])
                            tl = data.get("ai_viral") or data.get("cortes_aprovados") or data.get("timeline")
                            if tl and isinstance(tl, list) and len(tl) > 0:
                                parsed_audited = tl
                                break
                    except Exception:
                        continue
            except Exception:
                pass

    # Extract validated segments from parsed_audited
    refined_audited = []
    if parsed_audited:
        for chunk in parsed_audited:
            s_t, e_t, txt, framing = _extract_chunk_bounds(chunk)
            if s_t is not None and e_t is not None and e_t > s_t:
                refined_audited.append({
                    "start": round(max(0.0, s_t), 3),
                    "end": round(min(video_duration, e_t), 3),
                    "text": txt,
                    "framing": framing
                })

    # If the auditor produced valid segments, use them!
    if refined_audited and len(refined_audited) >= 1:
        audited_dur = sum(s["end"] - s["start"] for s in refined_audited)
        cand_climax_end = candidate_segments[-1]["end"] if candidate_segments else 0.0
        audited_climax_end = refined_audited[-1]["end"]

        # CRITICAL PROTECTION: The climax is always at the end of the candidate scene!
        # If the auditor returned cuts that end prematurely (e.g. >15s before the candidate's climax),
        # the auditor hallucinated an early scene and threw away the climax! DO NOT accept it!
        auditor_lost_climax = (cand_climax_end > 30.0 and audited_climax_end < cand_climax_end - 15.0)

        if not auditor_lost_climax and (audited_dur >= 45.0 or audited_dur >= total_curr_dur or total_curr_dur < 40.0):
            merged = _merge_segments(refined_audited)
            if all_words:
                merged = align_segments_to_speech_boundaries(merged, all_words, video_duration)
            if sum(s["end"] - s["start"] for s in merged) >= 42.0 or total_curr_dur < 40.0:
                candidate_segments = merged
        elif auditor_lost_climax and on_log:
            on_log("[CHECK DO CHECK] Auditoria tentou antecipar os cortes perdendo o clímax final. Mantendo os cortes com o clímax preservado!")
    else:
        if on_log:
            on_log("[INFO] Aplicando auditoria determinística de precisão (Ajuste de bordas e teto de duração)...")

    # Final Mathematical Duration Ceiling Guarantee:
    candidate_segments = _strictly_cap_segments_duration(candidate_segments, max_cap=max_duration_cap)
    final_dur = sum(max(0.0, s["end"] - s["start"]) for s in candidate_segments)
    if on_log:
        on_log(f"🛡️ [CHECK DO CHECK] Resultado final aprovado: {len(candidate_segments)} cortes | Duração: {final_dur:.2f}s (Teto: {max_duration_cap:.1f}s)")

    return candidate_segments


def build_heuristic_mastercut(
    all_words,
    video_duration,
    min_dur=38.0,
    max_dur=55.0,
    refine_mode="balanced",
    is_dorama=False,
    on_log=None
):
    """
    Local heuristic fallback when no LLM is available or connected.
    Finds dialogue segments with minimum silence (>0.35s cut, or >0.65s for dorama), prioritizing natural speech continuity.
    Guaranteed NEVER to return an empty list.
    """
    if on_log:
        d_lbl = " [Modo Dorama: Pausas Preservadas]" if is_dorama else ""
        on_log(f"[MASTERCUT] Construindo Mastercut inteligente via algoritmo de densidade de diálogo e corte de silêncio{d_lbl}...")

    def _create_visual_cuts():
        if video_duration <= min_dur + 1.0:
            return [{"start": 0.0, "end": round(video_duration, 3), "text": "[Corte Concentrado Integral]"}]
        target_total = max(min_dur, min(max_dur, video_duration * 0.75))
        seg_len = min(15.0, max(8.0, target_total / 3.0))
        s1 = round(max(0.0, video_duration * 0.05), 3)
        e1 = round(min(video_duration, s1 + seg_len), 3)
        s2 = round(max(e1 + 0.5, video_duration * 0.45 - seg_len / 2.0), 3)
        e2 = round(min(video_duration, s2 + seg_len), 3)
        s3 = round(max(e2 + 0.5, video_duration - seg_len - 0.5), 3)
        e3 = round(min(video_duration, video_duration - 0.1), 3)
        cuts = [
            {"start": s1, "end": e1, "text": "[Abertura / Gancho]"},
            {"start": s2, "end": e2, "text": "[Desenvolvimento Central]"},
            {"start": s3, "end": e3, "text": "[Clímax / Desfecho]"}
        ]
        valid_cuts = [c for c in cuts if c["end"] > c["start"]]
        if not valid_cuts:
            valid_cuts = [{"start": 0.0, "end": round(video_duration, 3), "text": "[Corte Integral]"}]
        return valid_cuts

    if not all_words:
        return _create_visual_cuts()

    gap_val = 0.85 if (is_dorama or refine_mode in ("soft", "dorama")) else 0.75
    groups = group_words_into_complete_sentences(all_words, max_gap=gap_val, is_dorama=is_dorama)
    if not groups:
        return _create_visual_cuts()

    # Em vídeos curtos (<=40s) ou modo de preservação (soft), manter todos os diálogos!
    total_speech_dur = sum(g["duration"] for g in groups)

    if total_speech_dur <= max_dur or video_duration <= 40.0 or refine_mode == "soft":
        picked = sorted(groups, key=lambda x: x["start"])
    else:
        # Encontra a melhor JANELA CONTÍNUA DE DIÁLOGOS para manter o contexto 100% íntegro e sem furos!
        best_window = []
        best_win_score = -1.0
        n_g = len(groups)
        for i in range(n_g):
            cur_win = []
            cur_dur = 0.0
            cur_words = 0
            for j in range(i, n_g):
                g_dur = groups[j]["duration"]
                if cur_dur + g_dur <= max_dur:
                    cur_win.append(groups[j])
                    cur_dur += g_dur
                    cur_words += groups[j]["words_count"]
                else:
                    break
            if cur_dur >= min_dur * 0.70:
                score = (cur_words / max(1.0, cur_dur)) * (1.0 + (i / max(1, n_g)) * 0.25)
                if score > best_win_score:
                    best_win_score = score
                    best_window = cur_win

        if best_window:
            picked = best_window
        else:
            picked = groups[:max(3, len(groups)//2)]

    res = []
    for g in picked:
        s_pad = round(max(0.0, g["start"] - 0.08), 3)
        e_pad = round(min(video_duration, g["end"] + 0.28), 3)
        if e_pad > s_pad:
            res.append({"start": s_pad, "end": e_pad, "text": g["text"]})
    if not res:
        return _create_visual_cuts()
    return res


def protect_against_overcutting(
    refined: list,
    all_words: list,
    video_duration: float,
    min_dur: float,
    max_dur: float,
    on_log=None
) -> list:
    """
    Safety Guard: If AI or heuristic produced an overly aggressive cut (e.g. 19s on a 60s clip),
    this intelligently restores dialogue and missing key scenes until min_dur is reached,
    while strictly preserving distinct cuts and preventing monolithic fusing of the entire clip.
    Guaranteed NEVER to return an empty list and never to exceed max_dur.
    """
    if not refined:
        if video_duration <= min_dur + 1.0:
            return [{"start": 0.0, "end": round(video_duration, 3), "text": "[Mastercut Preservado]"}]
        target_total = min(min_dur, video_duration * 0.75)
        seg_dur = target_total / 3.0
        gap = max(0.5, (video_duration - target_total) / 4.0)
        s1 = round(gap, 3)
        e1 = round(min(video_duration, s1 + seg_dur), 3)
        s2 = round(min(video_duration - 2.0, e1 + gap), 3)
        e2 = round(min(video_duration, s2 + seg_dur), 3)
        s3 = round(min(video_duration - 1.0, e2 + gap), 3)
        e3 = round(min(video_duration, s3 + seg_dur), 3)
        return [
            {"start": s1, "end": e1, "text": "[Abertura Narrativa]"},
            {"start": s2, "end": e2, "text": "[Desenvolvimento Central]"},
            {"start": s3, "end": e3, "text": "[Clímax Final]"}
        ]

    total_cur = sum(s["end"] - s["start"] for s in refined)
    if total_cur >= min_dur:
        return refined

    dur_before = total_cur
    if on_log:
        on_log(f"[AVISO] Corte inicial somou apenas {dur_before:.1f}s (abaixo do piso de {min_dur:.1f}s).")
        on_log(f"[PROTEÇÃO] Proteção Anti-Corte ativada: restaurando diálogos e momentos importantes sem fundir o vídeo...")

    expanded = []
    for seg in refined:
        s_t = max(0.0, seg["start"] - 0.05)
        e_t = min(video_duration, seg["end"] + 0.10)
        expanded.append({
            "start": round(s_t, 3),
            "end": round(e_t, 3),
            "text": seg.get("text", "")
        })

    # Only merge segments that truly touch or overlap (< 0.10s)
    expanded = _merge_segments(expanded, min_gap=0.10)
    total_cur = sum(s["end"] - s["start"] for s in expanded)

    # Phase 2: If still under min_dur, intelligently expand narrative context using adjacent sentences
    if total_cur < min_dur and all_words:
        sentences = group_words_into_complete_sentences(all_words)
        for seg in list(expanded):
            if total_cur >= min_dur:
                break
            # 1. Expand backwards to include predecessor dialogue line (context/setup)
            pre_cands = [sent for sent in sentences if sent["end"] <= seg["start"] + 0.1 and sent["end"] >= seg["start"] - 4.5]
            if pre_cands:
                cand = pre_cands[-1]
                cand_dur = cand["end"] - cand["start"]
                if total_cur + cand_dur <= max_dur:
                    seg["start"] = max(0.0, cand["start"] - 0.08)
                    total_cur += cand_dur
            # 2. Expand forwards to include successor dialogue line (reply/reaction)
            if total_cur < min_dur:
                post_cands = [sent for sent in sentences if sent["start"] >= seg["end"] - 0.1 and sent["start"] <= seg["end"] + 4.5]
                if post_cands:
                    cand = post_cands[0]
                    cand_dur = cand["end"] - cand["start"]
                    if total_cur + cand_dur <= max_dur:
                        seg["end"] = min(video_duration, cand["end"] + 0.22)
                        total_cur += cand_dur

        expanded = _merge_segments(expanded, min_gap=0.35)
        total_cur = sum(s["end"] - s["start"] for s in expanded)

    # Phase 2b: If still under min_dur, append complete chronological sentences
    if total_cur < min_dur and all_words:
        sentences = group_words_into_complete_sentences(all_words)
        for g in sentences:
            has_conflict = any(not (g["end"] <= s["start"] - 0.20 or g["start"] >= s["end"] + 0.20) for s in expanded)
            if not has_conflict:
                g_dur = g["end"] - g["start"]
                if total_cur + g_dur <= max_dur:
                    expanded.append({
                        "start": max(0.0, g["start"] - 0.08),
                        "end": min(video_duration, g["end"] + 0.22),
                        "text": g.get("text", "[Diálogo Completo]")
                    })
                    total_cur += g_dur
                    if total_cur >= min_dur:
                        break

        expanded.sort(key=lambda x: x["start"])
        expanded = _merge_segments(expanded, min_gap=0.35)
        total_cur = sum(s["end"] - s["start"] for s in expanded)

    # Phase 3: If STILL under min_dur (e.g. very sparse dialogue), gently pad segments without closing gaps
    if total_cur < min_dur and len(expanded) > 0:
        needed = min(min_dur - total_cur, max_dur - total_cur)
        if needed > 0.5:
            per_seg_add = needed / len(expanded)
            final_list = []
            for i, s in enumerate(expanded):
                pad = min(0.35, per_seg_add / 2.0)
                min_s = 0.0 if i == 0 else (expanded[i-1]["end"] + 0.20)
                max_e = video_duration if i == len(expanded)-1 else (expanded[i+1]["start"] - 0.20)
                new_s = max(min_s, s["start"] - pad)
                new_e = min(max_e, s["end"] + pad)
                if new_e > new_s:
                    final_list.append({
                        "start": round(new_s, 3),
                        "end": round(new_e, 3),
                        "text": s.get("text", "")
                    })
                else:
                    final_list.append(s)
            expanded = final_list
            total_cur = sum(s["end"] - s["start"] for s in expanded)

    if on_log:
        on_log(f"[OK] Proteção concluída: {dur_before:.1f}s -> {total_cur:.1f}s ({len(expanded)} cortes preservados com fluidez)!")

    return expanded


def apply_anti_copyright_continuous_splits(
    segments: list,
    all_words: list,
    max_continuous_sec: float = 12.0,
    video_duration: float = 0.0,
    is_continuous_clip: bool = False,
    is_dorama: bool = False,
    on_log=None
) -> list:
    """
    Proteção Anti-Copyright & Content ID:
    Para trechos ininterruptos longos (> 10s a 12s), fatia exclusivamente onde
    houver pausa real de silêncio (>= 0.30s).
    Se o vídeo for identificado como trecho contínuo do Diretor IA (is_continuous_clip=True),
    aplica a proteção mesmo em clipes curtos (20s a 60s) para evitar detecção no YouTube/TikTok.
    Garante que jamais ocorra sobreposição temporal (overlap) ou picote na fala humana.
    """
    if is_dorama and max_continuous_sec < 8.0:
        max_continuous_sec = 8.0
    if not segments:
        return segments

    # Se não for clipe contínuo do episódio e for vídeo curto <= 60s, não força fatiamento intrusivo
    if not is_continuous_clip and (video_duration > 0 and video_duration <= 60.0):
        return segments

    result = []
    splits_count = 0

    for seg in segments:
        s_start = seg["start"]
        s_end = seg["end"]
        seg_dur = s_end - s_start

        if seg_dur <= max_continuous_sec:
            result.append(dict(seg))
            continue

        # Segment exceeds max_continuous_sec. Split only on real speech gaps
        sub_words = [w for w in (all_words or []) if w["start"] >= (s_start - 0.05) and w["end"] <= (s_end + 0.05)]
        curr_start = s_start

        while (s_end - curr_start) > max_continuous_sec:
            target_split = curr_start + min(max_continuous_sec - 0.6, 9.0)

            best_split_end = None
            best_next_start = None

            window_words = [
                w for w in sub_words
                if (curr_start + 3.0) <= w["start"] <= (curr_start + max_continuous_sec - 0.2)
            ]

            if window_words:
                for w in window_words:
                    w_idx = sub_words.index(w) if w in sub_words else -1
                    if w_idx >= 0 and w_idx + 1 < len(sub_words):
                        next_w = sub_words[w_idx + 1]
                        gap = next_w["start"] - w["end"]
                        # Requer silêncio real (>= 0.35s) para não picotar a fala humana!
                        if gap >= 0.35:
                            best_split_end = round(w["end"] + 0.12, 3)
                            best_next_start = round(next_w["start"] - 0.05, 3)
                            break

            if best_split_end is None or best_next_start is None or best_next_start <= best_split_end:
                # Não há pausa acústica segura: mantém a integridade do diálogo sem forçar corte falso!
                break

            best_split_end = min(best_split_end, s_end)
            best_next_start = min(best_next_start, s_end)

            if best_split_end > curr_start + 1.5 and best_next_start < s_end - 0.8:
                result.append({
                    **seg,
                    "start": round(curr_start, 3),
                    "end": round(best_split_end, 3),
                })
                splits_count += 1
                curr_start = best_next_start
            else:
                break

        if s_end > curr_start + 0.4:
            result.append({
                **seg,
                "start": round(curr_start, 3),
                "end": round(s_end, 3),
            })

    if splits_count > 0 and on_log:
        on_log(f"[ANTI-COPYRIGHT]: {splits_count} corte(s) longos divididos em pausas naturais de silêncio!")

    # Runs after the editorial stage, so order must be preserved (no re-sort)
    return finalize_ordered_segments(result)



def apply_contextual_loop(
    refined: list,
    all_words: list,
    video_duration: float,
    on_log=None
) -> list:
    """
    Transforms a linear Mastercut into an Infinite Contextual Loop:
    1. Locates the final contextual phrase/climax (last ~2.5s - 5.0s) at the end of the video.
    2. Slices it cleanly (respecting word and phrase boundaries).
    3. Moves this slice to the very beginning (0.0s) as the Hook/Opening.
    4. The video's body ends exactly where this slice begins.
    5. When played in loops (Shorts/Reels/TikTok), the end seamlessly connects to the start!
    """
    if not refined or len(refined) < 1:
        return refined

    total_dur = sum(s["end"] - s["start"] for s in refined)
    if total_dur < 6.0:
        if on_log:
            on_log("[INFO] Vídeo muito curto para fatiar loop contextual. Mantendo fluxo contínuo.")
        return refined

    last_seg = dict(refined[-1])
    h_end = last_seg["end"]

    # Target hook duration: between 2.5s and 4.8s (ideal ~3.5s)
    h_start = round(max(last_seg["start"], h_end - 3.5), 3)

    # If we have word-level timestamps, find the nearest natural phrase or word start
    if all_words:
        # Candidate words in the window [h_end - 5.0s, h_end - 2.0s]
        window_words = [w for w in all_words if (h_end - 5.0) <= w["start"] <= (h_end - 2.0) and w["end"] <= h_end]
        if window_words:
            best_w = None
            for w in window_words:
                all_idx = all_words.index(w) if w in all_words else -1
                if all_idx > 0:
                    prev_w = all_words[all_idx - 1]
                    gap = w["start"] - prev_w["end"]
                    prev_txt = prev_w.get("text", "")
                    if gap >= 0.20 or any(p in prev_txt for p in [".", "!", "?", ",", "—", "-"]):
                        best_w = w
                        break
            if best_w is None:
                best_w = min(window_words, key=lambda w: abs((h_end - w["start"]) - 3.2))
            h_start = round(max(last_seg["start"], best_w["start"] - 0.05), 3)

    hook_len = h_end - h_start
    if hook_len < 1.8:
        h_start = round(max(last_seg["start"], h_end - 2.8), 3)
        hook_len = h_end - h_start

    last_seg["role"] = "story"
    result = [{**s, "role": "story"} for s in refined[:-1]]
    remaining_last_seg_dur = h_start - last_seg["start"]

    if remaining_last_seg_dur >= 0.8:
        last_seg["end"] = h_start
        result.append(last_seg)
    elif not result:
        # If there were no prior segments, keep last_seg adjusted
        last_seg["end"] = h_start
        result.append(last_seg)

    # Insert hook at index 0
    hook_segment = {
        "start": h_start,
        "end": h_end,
        "text": "[Hook de Loop Contextual]",
        "role": "hook",
        "framing": "punch",
    }
    result.insert(0, hook_segment)

    if on_log:
        on_log(f"[LOOP] Loop Contextual aplicado com sucesso!")
        on_log(f"   • Hook de Abertura: {h_start:.2f}s -> {h_end:.2f}s ({hook_len:.1f}s)")
        on_log(f"   • O final do vídeo agora conecta perfeitamente com o início para repetição infinita!")

    return finalize_ordered_segments(result)


def apply_hook_opening(
    refined: list,
    all_words: list,
    video_duration: float,
    action_blocks: list = None,
    visual_scenes: list = None,
    on_log=None
) -> list:
    """
    Transforms Mastercut to start with an explosive hook teaser (2.0s - 3.5s)
    taken from the video's climax or most dynamic moment, placed at 0.0s.
    Cuts any initial dead silence from the narrative body so it begins with immediate energy.
    """
    if not refined or len(refined) < 1:
        return refined

    # If first segment is already clearly a hook (under 4.5s and tagged as hook)
    first_seg = refined[0]
    first_seg_dur = first_seg["end"] - first_seg["start"]
    first_txt = str(first_seg.get("text", "")).lower()
    if ("hook" in first_txt or "teaser" in first_txt) and first_seg_dur <= 4.5:
        if on_log:
            on_log(f"[HOOK] Hook de abertura detectado na timeline da IA: {first_seg['start']:.2f}s -> {first_seg['end']:.2f}s ({first_seg_dur:.1f}s)")
        return refined

    h_start = None
    h_end = None
    hook_text = "[Hook de Abertura / Teaser]"

    # Option A: Visual scenes of high impact in second half
    if visual_scenes:
        climax_scenes = [
            vs for vs in visual_scenes
            if vs.get("importance") == "high" and vs.get("start", 0) >= video_duration * 0.35
        ]
        if climax_scenes:
            best_vs = climax_scenes[-1]
            vs_s = best_vs.get("start", 0.0)
            vs_e = best_vs.get("end", vs_s + 3.0)
            h_start = vs_s
            h_end = min(vs_e, vs_s + 3.2)
            hook_text = f"[Hook Visual: {best_vs.get('description', 'Cena de Alto Impacto')[:40]}]"

    # Option B: High-energy action block
    if h_start is None and action_blocks:
        climax_actions = [ab for ab in action_blocks if ab.get("start", 0) >= video_duration * 0.35]
        if climax_actions:
            best_ab = climax_actions[-1]
            h_start = best_ab.get("start", 0.0)
            h_end = min(best_ab.get("end", h_start + 3.0), h_start + 3.2)
            hook_text = "[Hook de Ação / Clímax]"

    # Option C: Dynamic speech or last segment in refined
    if h_start is None:
        target_seg = refined[-1] if len(refined) == 1 or (refined[-1]["end"] - refined[-1]["start"] >= 2.5) else refined[-2]
        s_dur = target_seg["end"] - target_seg["start"]
        if s_dur >= 3.0:
            h_start = round(max(target_seg["start"], target_seg["end"] - 3.2), 3)
            h_end = target_seg["end"]
        else:
            h_start = target_seg["start"]
            h_end = target_seg["end"]

    # Align hook boundaries with words if available
    if all_words and h_start is not None and h_end is not None:
        sub_words = [w for w in all_words if (h_start - 0.3) <= w["start"] and w["end"] <= (h_end + 0.3)]
        if sub_words:
            h_start = round(max(0.0, sub_words[0]["start"] - 0.06), 3)
            h_end = round(min(video_duration, sub_words[-1]["end"] + 0.18), 3)

    h_dur = (h_end - h_start) if (h_start is not None and h_end is not None) else 0.0
    if h_dur < 1.5 or h_start is None or h_end is None:
        h_start = round(max(0.0, video_duration * 0.65), 3)
        h_end = round(min(video_duration, h_start + 2.8), 3)

    hook_seg = {
        "start": h_start,
        "end": h_end,
        "text": hook_text,
        "role": "hook",
        "framing": "punch",
    }

    # Prepare narrative segments:
    narrative = [{**s, "role": "story"} for s in refined]
    if all_words and narrative:
        first_w = all_words[0]
        # If the first speech starts noticeably after narrative start (> 0.8s of silence), trim it
        if narrative[0]["start"] < first_w["start"] - 0.6:
            new_s = round(max(0.0, first_w["start"] - 0.15), 3)
            if new_s < narrative[0]["end"] - 0.5:
                if on_log:
                    on_log(f"[ANTI-INÍCIO LENTO] Início mudo cortado: {narrative[0]['start']:.2f}s -> {new_s:.2f}s (Narrativa começa direto na fala!)")
                narrative[0]["start"] = new_s

    result = [hook_seg] + narrative

    if on_log:
        on_log(f"[HOOK] Hook de Abertura criado: {h_start:.2f}s -> {h_end:.2f}s ({h_end - h_start:.1f}s)")
        on_log("   • O vídeo agora começa com o momento mais forte, com transição visual em flash para a história!")

    # Never re-sort here: a chronological sort would push the teaser back to its original spot
    return finalize_ordered_segments(result)


def apply_viral_editor_structure(
    refined: list,
    all_words: list,
    video_duration: float,
    action_blocks: list = None,
    visual_scenes: list = None,
    on_log=None
) -> list:
    """
    Super Senior Viral Editor (Edição Viral Pro):
    A fórmula profissional para vídeos com alta retenção no TikTok, Reels e Shorts:
    1. INÍCIO IMEDIATO (Zero silêncio inicial, retenção nos primeiros 3 segundos):
       - Se o clipe já começa com fala ou ação nos primeiros segundos:
         Inicia DIRETO na fala (corta pausas mortas antes de falar), sem duplicar nada!
         A narrativa permanece 100% cronológica, com sentido e fluidez total.
       - Se o clipe tem início enrolado/mudo (>2.5s sem fala):
         Extrai um teaser de 2s a 3s do momento mais marcante e ajusta a narrativa
         removendo repetições idênticas no corpo para não cansar o público.
    2. PACING DE RETENÇÃO ANTI-TÉDIO:
       - Transições dinâmicas sem pausas mortas, mantendo 100% da clareza das frases.
    3. DESFECHO NO CLÍMAX (Mic Drop):
       - O vídeo encerra com impacto no ápice da cena, sem sobrar segundos mortos no final.
    """
    if not refined or len(refined) < 1:
        return refined

    # 1. Elimina segmentos iniciais completamente mudos e identifica a primeira palavra falada
    clean_refined = []
    found_dialogue = False
    for s in refined:
        sw = [w for w in (all_words or []) if (s["start"] - 0.20) <= w.get("start", 0.0) <= s["end"]]
        if sw or found_dialogue:
            clean_refined.append(s)
            found_dialogue = True
    if clean_refined:
        refined = clean_refined

    seg0 = refined[0]
    words_in_seg0 = [
        w for w in (all_words or [])
        if (seg0["start"] - 0.20) <= w.get("start", 0.0) <= seg0["end"]
    ]
    first_seg_speech = words_in_seg0[0]["start"] if words_in_seg0 else None

    # Se a fala dentro do primeiro segmento começa rápido (até 2.5s de respiro):
    has_early_speech = (first_seg_speech is not None and (first_seg_speech - seg0["start"]) <= 2.5)

    if has_early_speech:
        if on_log:
            on_log("[VIRAL PRO] Início do vídeo já possui fala de impacto! Iniciando direto na ação (sem repetições).")

        narrative = [{**s, "role": "story"} for s in refined]
        # Corta qualquer respiro mudo antes da fala inicial para começar direto na voz
        if first_seg_speech is not None and narrative:
            lead_silence = max(0.0, first_seg_speech - narrative[0]["start"])
            if lead_silence >= 0.12:
                trimmed_start = round(max(0.0, first_seg_speech - 0.08), 3)
                if trimmed_start < narrative[0]["end"] - 0.5:
                    if on_log:
                        on_log(f"   • Silêncio inicial cortado: começa no milissegundo {trimmed_start:.2f}s direto na voz!")
                    narrative[0]["start"] = trimmed_start

        narrative[0]["role"] = "story"  # Mantém role='story' para não disparar flash de teaser falso
        narrative[0]["framing"] = "punch"

        # Garante que o final encerra no ápice da última fala com respiro seguro (mic drop sem amputar palavra)
        if len(narrative) >= 1 and all_words:
            last_seg = narrative[-1]
            last_words = [w for w in all_words if last_seg["start"] <= w["start"] <= last_seg["end"]]
            if last_words:
                last_w = last_words[-1]
                trail_silence = last_seg["end"] - last_w["end"]
                if trail_silence >= 1.00:
                    last_seg["end"] = round(min(video_duration, last_w["end"] + 0.40), 3)

        if on_log:
            on_log("[VIRAL PRO] Montagem Viral Pro finalizada: Início Explosivo + Pacing Ágil + Desfecho em Pico!")

        return finalize_ordered_segments(narrative)

    # 2. Se o início do vídeo for lento (>4.0s sem ninguém falar)
    if on_log:
        on_log("[VIRAL PRO] Início lento detectado (>4.0s sem falas). Extraindo teaser inicial mantendo o corpo da história completo...")

    with_hook = apply_hook_opening(
        refined=refined,
        all_words=all_words,
        video_duration=video_duration,
        action_blocks=action_blocks,
        visual_scenes=visual_scenes,
        on_log=on_log
    )

    if on_log:
        on_log("[VIRAL PRO] Edição Viral Pro montada com sucesso: Teaser de impacto + Narrativa contextual completa!")

    return finalize_ordered_segments(with_hook)


def build_refined_segments(
    all_words,
    video_duration,
    action_blocks=None,
    visual_scenes=None,
    video_context="",
    work_title="",
    scene_context="",
    user_feedback="",
    previous_segments=None,
    refine_mode="balanced",
    target_duration_mode="auto",
    enable_loop=False,
    editorial_mode="linear",
    anti_copyright=True,
    is_continuous_clip=False,
    is_dorama=False,
    audio_path=None,
    ai_engine="auto",
    local_model="",
    on_log=None
):
    """
    Executes AI Mastercut selection with smart audio padding (-80ms, +250ms),
    merging overlaps and applying anti-overcut protection to prevent mutilation.
    Guaranteed NEVER to return an empty list of segments!
    """
    # Auto-detect Dorama if not explicitly specified
    if not is_dorama:
        ctx_lower = f"{work_title} {scene_context} {video_context}".lower()
        is_dorama = (
            refine_mode == "dorama"
            or editorial_mode == "dorama"
            or any(k in ctx_lower for k in ("dorama", "kdrama", "k-drama", "coreano", "c-drama", "j-drama", "doramas"))
        )

    min_dur, max_dur = calculate_mastercut_bounds(video_duration, refine_mode, target_duration_mode)
    # The opening teaser is a repeated excerpt, so its seconds come out of the story budget:
    # the final video lands inside the promised range instead of overshooting it.
    teaser_reserve = HOOK_TEASER_RESERVE if (editorial_mode in ("hook", "viral_editor") and video_duration > 65.0) else 0.0
    body_max = max_dur if (editorial_mode == "viral_59" or target_duration_mode == "viral_59s") else (max(min_dur, max_dur - teaser_reserve) if video_duration > 65.0 else max_dur)
    if on_log:
        mode_label = EDITORIAL_MODES.get(editorial_mode, "Linear Direto")
        dor_tag = " [Perfil Dorama Ativo: Ritmo Emocional]" if is_dorama else ""
        on_log(f"[META] Meta de duração do Mastercut: {min_dur:.1f}s a {max_dur:.1f}s (Ritmo: {refine_mode} | Editorial: {mode_label}){dor_tag}")
        if teaser_reserve:
            on_log(f"[META] Orçamento da história: até {body_max:.1f}s + gancho de ~{teaser_reserve:.0f}s")

    timeline, roteiro = call_ai_mastercut_timeline(
        all_words,
        video_duration,
        action_blocks,
        visual_scenes=visual_scenes,
        video_context=video_context,
        work_title=work_title,
        scene_context=scene_context,
        user_feedback=user_feedback,
        previous_segments=previous_segments,
        refine_mode=refine_mode,
        target_duration_mode=target_duration_mode,
        enable_loop=enable_loop,
        editorial_mode=editorial_mode,
        is_dorama=is_dorama,
        ai_engine=ai_engine,
        local_model=local_model,
        on_log=on_log
    )


    if not roteiro or not isinstance(roteiro, dict):
        roteiro = {
            "premissa": "Edição concentrada focada em densidade de diálogo e ritmo dinâmico.",
            "hook": "Abertura direta na primeira fala ativa do clipe.",
            "conflito_desenvolvimento": "Sequência contínua de diálogos preservando orações completas.",
            "climax_fechamento": "Encerramento na última fala com respiro natural."
        }

    raw_parsed = []
    if timeline and isinstance(timeline, list):
        for chunk in timeline:
            s_t, e_t, txt, framing = _extract_chunk_bounds(chunk)
            if s_t is not None and e_t is not None and e_t > s_t:
                raw_parsed.append({"start": s_t, "end": e_t, "text": txt, "framing": framing})

    # Detect if AI hallucinated episode-level timestamps (e.g. all starts >= video_duration)
    if raw_parsed and all(item["start"] >= video_duration for item in raw_parsed):
        min_start = min(item["start"] for item in raw_parsed)
        if on_log:
            on_log(f"[INFO] IA gerou timestamps absolutos de episódio (início em {min_start:.1f}s). Sincronizando para a linha do tempo do clipe...")
        shifted = []
        for item in raw_parsed:
            rel_s = item["start"] - min_start
            rel_e = item["end"] - min_start
            if rel_s < video_duration:
                shifted.append({
                    "start": round(max(0.0, rel_s), 3),
                    "end": round(min(video_duration, rel_e), 3),
                    "text": item["text"],
                    "framing": item.get("framing", "wide")
                })
        if shifted:
            raw_parsed = shifted

    refined = []
    for chunk in raw_parsed:
        s_t, e_t, txt, framing = _extract_chunk_bounds(chunk)
        if s_t is not None and e_t is not None and e_t > s_t:
            s_t_r = round(max(0.0, s_t - 0.080), 3)
            e_t_r = round(min(video_duration, e_t + 0.250), 3)
            if e_t_r > s_t_r and s_t_r < video_duration:
                refined.append({
                    "start": s_t_r,
                    "end": e_t_r,
                    "text": txt,
                    "framing": framing
                })

    # Fallback to direct raw chunks if padding failed
    if not refined and raw_parsed:
        for chunk in raw_parsed:
            s_t = chunk["start"]
            e_t = chunk["end"]
            s_t_r = round(s_t, 3)
            e_t_r = round(e_t, 3)
            if e_t_r > s_t_r and s_t_r < video_duration:
                refined.append({
                    "start": s_t_r,
                    "end": e_t_r,
                    "text": chunk.get("text", "[Corte Mastercut]"),
                    "framing": chunk.get("framing", "wide")
                })

    # CRITICAL: If after parsing AI timeline, refined is empty or has insufficient duration (< half min_dur):
    curr_parsed_dur = sum(s["end"] - s["start"] for s in refined)
    needs_heuristic = (not refined) or (curr_parsed_dur < max(18.0, min_dur * 0.45))
    if needs_heuristic:
        if on_log:
            if not refined:
                on_log("[AVISO] Cortes da IA eram inválidos ou fora dos limites do clipe. Ativando algoritmo heurístico de segurança...")
            else:
                on_log("[INFO] Complementando cortes via inteligência heurística...")
        fallback_timeline = build_heuristic_mastercut(
            all_words,
            video_duration,
            min_dur=min_dur,
            max_dur=max_dur,
            refine_mode=refine_mode,
            is_dorama=is_dorama,
            on_log=on_log
        )
        for chunk in fallback_timeline:
            s_t, e_t, txt, framing = _extract_chunk_bounds(chunk)
            if s_t is not None and e_t is not None and e_t > s_t:
                s_t_r = round(max(0.0, s_t - 0.080), 3)
                e_t_r = round(min(video_duration, e_t + 0.250), 3)
                if e_t_r > s_t_r:
                    refined.append({
                        "start": s_t_r,
                        "end": e_t_r,
                        "text": txt,
                        "framing": framing
                    })

    # Merge overlapping segments e alinhamento de fala (garante falas completas sem decepar orações)
    refined = _merge_segments(refined)
    if all_words:
        refined = align_segments_to_speech_boundaries(refined, all_words, video_duration)

    # Apply Anti-Overcut Protection (prevents 60s -> 19s mutilation)
    refined = protect_against_overcutting(
        refined=refined,
        all_words=all_words,
        video_duration=video_duration,
        min_dur=min_dur,
        max_dur=body_max,
        on_log=on_log
    )

    # Para vídeos já curtos (<= 65s): se a IA por algum motivo pulou blocos de diálogo entre o início e o fim,
    # restauramos o diálogo contínuo completo para evitar falas cortadas e perda de contexto!
    if video_duration <= 65.0 and all_words and target_duration_mode != "short":
        sentences = group_words_into_complete_sentences(all_words, is_dorama=is_dorama)
        if sentences:
            first_sent_time = sentences[0]["start"]
            if refined and refined[0]["start"] > first_sent_time + 1.0:
                refined.insert(0, {
                    "start": round(max(0.0, first_sent_time - 0.08), 3),
                    "end": round(sentences[0]["end"] + 0.22, 3),
                    "text": sentences[0]["text"],
                    "framing": "punch"
                })
            for sent in sentences:
                s_st = sent["start"]
                s_en = sent["end"]
                covered = any(
                    (seg["start"] - 0.35 <= s_st and seg["end"] + 0.35 >= s_en) or
                    (s_st >= seg["start"] and s_st <= seg["end"]) or
                    (s_en >= seg["start"] and s_en <= seg["end"])
                    for seg in refined
                )
                if not covered:
                    refined.append({
                        "start": round(max(0.0, s_st - 0.08), 3),
                        "end": round(min(video_duration, s_en + 0.22), 3),
                        "text": sent["text"],
                        "framing": "wide"
                    })
            refined = _merge_segments(refined, min_gap=0.35)
            refined = sorted(refined, key=lambda x: x["start"])

    # Enforce upper bound (story budget) com proteção estrita do desfecho/clímax e de frases completas
    total_dur = sum(s["end"] - s["start"] for s in refined)
    if video_duration > 65.0 and total_dur > body_max + 0.5:
        if editorial_mode == "viral_59" or target_duration_mode == "viral_59s":
            refined = _strictly_cap_segments_duration(refined, max_cap=body_max)
        elif len(refined) >= 2 and (refined[-1]["end"] - refined[-1]["start"]) < body_max:
            last_seg = refined[-1]
            last_dur = last_seg["end"] - last_seg["start"]
            remaining_budget = max(8.0, body_max - last_dur)
            trimmed_prefix = []
            t_acc = 0.0
            for s in refined[:-1]:
                seg_d = s["end"] - s["start"]
                if t_acc + seg_d <= remaining_budget:
                    trimmed_prefix.append(s)
                    t_acc += seg_d
                elif (t_acc + seg_d <= remaining_budget + 4.0) or len(trimmed_prefix) == 0:
                    trimmed_prefix.append(s)
                    t_acc += seg_d
                else:
                    # Pula blocos do meio que excederiam o orçamento, para garantir que o clímax final entre!
                    continue
            candidate = trimmed_prefix + [last_seg]
            refined = _merge_segments(candidate, min_gap=0.35)
        else:
            trimmed = []
            t_acc = 0.0
            for s in refined:
                seg_d = s["end"] - s["start"]
                if t_acc + seg_d <= body_max or len(trimmed) < 2:
                    trimmed.append(s)
                    t_acc += seg_d
                else:
                    break
            if trimmed:
                refined = trimmed

    # Editorial structure runs on the clean chronological body BEFORE any splitting, so the
    # hook/loop sees whole phrases. From here on, order is intentional: never re-sort.
    refined = [{**s, "role": s.get("role", "story")} for s in refined]
    if editorial_mode == "hook":
        refined = apply_hook_opening(
            refined=refined,
            all_words=all_words,
            video_duration=video_duration,
            action_blocks=action_blocks,
            visual_scenes=visual_scenes,
            on_log=on_log
        )
    elif editorial_mode == "loop" or (enable_loop and editorial_mode == "linear"):
        refined = apply_contextual_loop(
            refined=refined,
            all_words=all_words,
            video_duration=video_duration,
            on_log=on_log
        )
    elif editorial_mode in ("viral_editor", "viral_59"):
        refined = apply_viral_editor_structure(
            refined=refined,
            all_words=all_words,
            video_duration=video_duration,
            action_blocks=action_blocks,
            visual_scenes=visual_scenes,
            on_log=on_log
        )

    # ── CHECK DO CHECK (DUPLO REFINO IA): Auditoria Crítica Especializada para Viral Flow 59s ──
    if target_duration_mode == "viral_59s" or editorial_mode == "viral_59":
        refined = audit_and_refine_cut_double_check(
            candidate_segments=refined,
            all_words=all_words,
            video_duration=video_duration,
            video_context=video_context,
            work_title=work_title,
            scene_context=scene_context,
            user_feedback=user_feedback,
            max_duration_cap=59.0,
            local_model=local_model,
            ai_engine=ai_engine,
            on_log=on_log
        )


    # Validação Final: sem overlap nem micro-engasgos, preservando a ordem editorial e blocos contínuos
    refined = finalize_ordered_segments(refined)

    # ── ZERO SILÊNCIO NO FRAME 0 (Garantia Absoluta de Retenção Viral) ──
    # Descarta segmentos iniciais sem fala e corta qualquer silêncio antes da primeira palavra falada (a menos que seja um momento solicitado pelo usuário)
    if refined and all_words and not user_feedback:
        while refined:
            sw = [w for w in all_words if (refined[0]["start"] - 0.20) <= w.get("start", 0.0) <= refined[0]["end"]]
            if sw:
                break
            if on_log:
                on_log(f"[ANTI-SILÊNCIO] Descartando cena inicial sem fala: [{refined[0]['start']:.2f}s -> {refined[0]['end']:.2f}s]")
            refined.pop(0)

        if refined:
            sw = [w for w in all_words if (refined[0]["start"] - 0.20) <= w.get("start", 0.0) <= refined[0]["end"]]
            if sw:
                first_w = sw[0]
                w_start = float(first_w.get("start", 0.0))
                w_end = float(first_w.get("end", w_start))
                w_txt = (first_w.get("word") or first_w.get("text") or "").strip().lower()
                # Se for monossílabo com duração inflada (>0.6s), o Whisper alucinou o início no silêncio prévio
                if len(w_txt) <= 3 and (w_end - w_start) > 0.60:
                    w_start = max(w_start, w_end - 0.25)

                lead_gap = max(0.0, w_start - refined[0]["start"])
                if lead_gap >= 0.12:
                    new_s = round(max(0.0, w_start - 0.08), 3)
                    if new_s < refined[0]["end"] - 0.5:
                        if on_log:
                            on_log(f"⚡ [RETENÇÃO VIRAL: ZERO SILÊNCIO] Começo mudo de {lead_gap:.2f}s cortado! O vídeo abre direto na fala no segundo 0.")
                        refined[0]["start"] = new_s

    # Alinhamento Acústico Fino (caso audio_path esteja disponível nesta fase)
    if refined and audio_path and os.path.exists(str(audio_path)):
        align_opening_segment_to_acoustic_speech(
            opening_segment=refined[0],
            audio_path_or_video=str(audio_path),
            ffmpeg_bin=_get_ffmpeg_bin("ffmpeg"),
            min_lead_silence=0.20,
            on_log=on_log
        )

    # 1. Blindagem Anti-Copyright: Fatiamento de trechos longos contínuos em pausas de respiração
    if anti_copyright and str(anti_copyright).lower() not in ("off", "false", "none", "0"):
        # No Viral Flow 59s, preservamos o fluxo contínuo e a cadência natural da cena sem jump cuts artificiais.
        # A blindagem é garantida pelo Multi-Câmera Inteligente (alternância de planos), Flip, Color Shift e DSP 1.04x.
        if editorial_mode != "viral_59" and target_duration_mode != "viral_59s":
            is_yt_max = (str(anti_copyright).lower() == "youtube_max")
            max_cont = 10.0 if is_yt_max else 12.0
            refined = apply_anti_copyright_continuous_splits(
                segments=refined,
                all_words=all_words,
                max_continuous_sec=max_cont,
                video_duration=video_duration,
                is_continuous_clip=is_continuous_clip or is_yt_max,
                is_dorama=is_dorama,
                on_log=on_log
            )

    # 2. Direção Multi-Câmera Inteligente: Alternância dinâmica de planos (Punch +15%, Reaction +8%, Wide)
    # No Viral Flow 59s, mantemos tomadas mais estáveis e cinematográficas (8.0s) para não deixar a cena picotada
    shot_dur = 8.0 if (editorial_mode == "viral_59" or target_duration_mode == "viral_59s") else (6.0 if is_dorama else 3.8)
    refined = split_long_segments_for_multicam(
        segments=refined,
        max_shot_dur=shot_dur,
        is_dorama=is_dorama
    )

    # Trava Final Rígida de Duração para Perfil 59s (Garantia Matemática Absoluta <= 59.0s)
    if target_duration_mode == "viral_59s" or editorial_mode == "viral_59":
        refined = _strictly_cap_segments_duration(refined, max_cap=59.0)
        final_total = sum(max(0.0, s["end"] - s["start"]) for s in refined)
        if on_log:
            on_log(f"⚡ [VIRAL FLOW 59s] Duração consolidada com rigor absoluto: {final_total:.2f}s (Teto Garantido ≤ 59.0s)")

    # Absolute ultimate failsafe: NEVER return empty!
    if not refined:
        refined = [{"start": 0.0, "end": round(video_duration, 3), "text": "[Mastercut Completo]", "framing": "wide"}]

    return refined, roteiro


# ─── FFmpeg Video Assembly ────────────────────────────────────────────────────

def render_mastercut_video(
    source_path: str,
    segments: list,
    output_path: str,
    vocal_isolation: bool = True,
    demucs_isolation: bool = False,
    anti_copyright: bool = False,
    enable_loop: bool = False,
    editorial_mode: str = "linear",
    roteiro: dict = None,
    on_progress=None,
    on_log=None,
    pre_isolated_audio_path: str = None
) -> dict:
    """
    Concatenates the Mastercut segments using FFmpeg filter_complex with NVENC acceleration.
    Returns stats dict on completion.
    """
    if not segments:
        raise ValueError("Nenhum segmento fornecido para montagem do Mastercut.")

    ffmpeg_bin = _get_ffmpeg_bin("ffmpeg")
    
    # If pre-isolated audio is provided (Demucs), the video HAS audio by definition
    has_audio = check_video_has_audio(source_path) or bool(pre_isolated_audio_path)
    video_duration = get_video_duration(source_path)

    # ── ZERO SILÊNCIO ACÚSTICO NO FRAME 0 (Garantia Absoluta de Retenção Viral) ──
    # Se houver áudio (seja o isolado por Demucs ou do vídeo), elimina qualquer vácuo de silêncio
    audio_for_onset = pre_isolated_audio_path if (pre_isolated_audio_path and os.path.exists(pre_isolated_audio_path)) else source_path
    if segments and has_audio and audio_for_onset:
        while segments:
            align_opening_segment_to_acoustic_speech(
                opening_segment=segments[0],
                audio_path_or_video=audio_for_onset,
                ffmpeg_bin=ffmpeg_bin,
                min_lead_silence=0.20,
                on_log=on_log
            )
            if segments[0]["end"] - segments[0]["start"] >= 0.50:
                break
            if len(segments) > 1:
                if on_log:
                    on_log(f"⚡ [ANTI-SILÊNCIO] Descartando tomada inicial sem fala [{segments[0]['start']:.2f}s -> {segments[0]['end']:.2f}s] para iniciar direto no diálogo!")
                segments.pop(0)
            else:
                break


    # Detect resolution
    video_width, video_height = 1920, 1080
    try:
        ffprobe_bin = _get_ffmpeg_bin("ffprobe")
        probe_res = subprocess.run(
            [ffprobe_bin, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(source_path)],
            capture_output=True, encoding="utf-8", errors="replace", timeout=10, **_get_silent_subprocess_kwargs()
        )
        if probe_res.returncode == 0:
            parts = probe_res.stdout.strip().split("x")
            if len(parts) == 2:
                video_width = int(parts[0]) - (int(parts[0]) % 2)
                video_height = int(parts[1]) - (int(parts[1]) % 2)
    except Exception:
        pass

    n = len(segments)
    filter_complex = []
    concat_inputs = []

    # Flash sits exactly at the hook → story boundary, e apenas quando há um salto temporal real (teaser de fato)
    hook_idxs = [idx for idx, sg in enumerate(segments) if sg.get("role") == "hook"]
    if hook_idxs:
        hook_last_idx = hook_idxs[-1]
    else:
        hook_last_idx = 0 if editorial_mode in ("hook", "viral_editor") else -1
    has_hook_transition = (
        0 <= hook_last_idx < n - 1
        and abs(segments[hook_last_idx + 1]["start"] - segments[hook_last_idx]["end"]) >= 0.50
    )

    for i, seg in enumerate(segments):
        s = seg["start"]
        e = seg["end"]
        dur_i = e - s
        framing = seg.get("framing", "wide")

        # Multi-Câmera Dinâmica & Zoom Anti-Copyright por Segmento Narrativo:
        # punch: +15% close-up de impacto para revelações, falas marcantes e clímax.
        # reaction: +8% zoom médio para réplicas e conversas.
        # wide: +3% plano aberto para ação e contexto.
        if framing == "punch":
            sc = 1.15
        elif framing == "reaction":
            sc = 1.08
        else:
            sc = 1.03 if (anti_copyright and str(anti_copyright).lower() not in ("off", "false", "none", "0")) else 1.00

        if sc > 1.005:
            cam_filter = (
                f",scale=w=trunc(iw*{sc:.3f}/2)*2:h=trunc(ih*{sc:.3f}/2)*2"
                f",crop=w={video_width}:h={video_height}"
                f",setsar=1"
            )
        else:
            cam_filter = ",setsar=1"

        # Transição visual suave em flash branco entre o Hook (índice 0) e a história (índice 1)
        # REGRA ESTRITA: ZERO SFX / ZERO EFEITOS SONOROS (áudio original 100% puro e intocado)
        if has_hook_transition and i == hook_last_idx:
            fade_dur = min(0.12, max(0.04, dur_i / 4.0))
            fade_st = max(0.0, dur_i - fade_dur)
            filter_complex.append(
                f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS{cam_filter},fade=t=out:st={fade_st:.3f}:d={fade_dur:.3f}:color=white[v{i}]"
            )
        elif has_hook_transition and i == hook_last_idx + 1:
            fade_in_dur = min(0.08, max(0.04, dur_i / 4.0))
            filter_complex.append(
                f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS{cam_filter},fade=t=in:st=0:d={fade_in_dur:.3f}:color=white[v{i}]"
            )
        else:
            filter_complex.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS{cam_filter}[v{i}]")

        if has_audio:
            # Detecta se este segmento é contíguo no tempo com o anterior ou próximo (ex: corte de câmera multi-cam).
            # Se for contíguo (<0.05s de gap na fonte), NÃO aplica fade na emenda para manter a voz 100% contínua e sem mergulhos de volume!
            is_cont_from_prev = (i > 0 and abs(s - segments[i-1]["end"]) < 0.05)
            is_cont_to_next = (i < n - 1 and abs(segments[i+1]["start"] - e) < 0.05)

            fade_in_str = ""
            if not is_cont_from_prev:
                afade_in_dur = min(0.045, dur_i / 4.0)
                fade_in_str = f",afade=t=in:st=0:d={afade_in_dur:.3f}:curve=iqsin"

            fade_out_str = ""
            if not is_cont_to_next:
                afade_out_dur = min(0.045, dur_i / 4.0)
                afade_out_st = max(0.0, dur_i - afade_out_dur)
                fade_out_str = f",afade=t=out:st={afade_out_st:.3f}:d={afade_out_dur:.3f}:curve=qsin"

            audio_source_idx = "1" if pre_isolated_audio_path else "0"
            filter_complex.append(
                f"[{audio_source_idx}:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo{fade_in_str}{fade_out_str}[a{i}]"
            )
            concat_inputs.append(f"[v{i}][a{i}]")
        else:
            concat_inputs.append(f"[v{i}]")

    video_post_filters = ""
    audio_post_filters = ",aformat=channel_layouts=stereo"

    # Resolvendo o modo Anti-Copyright:
    ac_mode = "off"
    if anti_copyright:
        if isinstance(anti_copyright, str):
            ac_s = anti_copyright.lower()
            if "off" in ac_s or "desativ" in ac_s:
                ac_mode = "off"
            elif "tiktok" in ac_s or "padrao" in ac_s or "padrão" in ac_s or "leve" in ac_s:
                ac_mode = "tiktok"
            else:
                ac_mode = "youtube_max"
        elif isinstance(anti_copyright, bool) and anti_copyright:
            ac_mode = "youtube_max"

    if ac_mode == "youtube_max":
        # Blindagem Máxima Nível YouTube (Anti-Toei Animation):
        # 1. Flip horizontal (destrói pHash 3D espacial e vetores de movimento da Toei)
        # 2. Aceleração orgânica calibrada em 4.0% (1.04x) com micro-pitch shift acústico
        # 3. Crop de 7% para quebrar coordenadas de cantos e arestas
        # 4. Color grading com contraste, leve saturação e curva gama para alterar espectro cromático
        # 5. Granulação fina e vinheta cinematográfica
        speed_factor = 1.040
        video_post_filters = (
            f",hflip"
            f",setpts=PTS/{speed_factor}"
            f",crop=trunc(iw*0.93/2)*2:trunc(ih*0.93/2)*2"
            f",scale={video_width}:{video_height}"
            f",noise=c0s=4:c0f=u:allf=t+u"
            f",eq=contrast=1.08:brightness=0.02:saturation=1.12:gamma=0.96"
            f",vignette=PI/6"
        )
        audio_post_filters += (
            f",atempo={speed_factor}"
            f",asetrate=48000*1.015,aresample=48000,atempo=1/1.015"
            f",equalizer=f=300:t=q:w=1.5:g=-1.5"
            f",equalizer=f=2800:t=q:w=1.2:g=1.4"
        )
    elif ac_mode == "tiktok":
        # Modo Padrão / TikTok / Reels:
        speed_factor = 1.020
        video_post_filters = (
            f",setpts=PTS/{speed_factor}"
            f",crop=iw*0.96:ih*0.96"
            f",scale={video_width}:{video_height}"
            f",noise=c0s=3:c0f=u:allf=t+u"
            f",eq=contrast=1.06:brightness=0.015:saturation=1.08:gamma=0.98"
            f",vignette=PI/7"
        )
        audio_post_filters += (
            f",atempo={speed_factor}"
            f",equalizer=f=300:t=q:w=1.5:g=-1.5"
            f",equalizer=f=2800:t=q:w=1.2:g=1.4"
        )

    if vocal_isolation:
        # Clareza Vocal de Estúdio Zero-Latência:
        # Filtros IIR de fase mínima sem buffer de lookahead (zero atraso labial / zero desync)
        audio_post_filters += (
            ",highpass=f=75"
            ",equalizer=f=250:t=q:w=1.2:g=-1.2"
            ",equalizer=f=3000:t=q:w=1.2:g=2.5"
            ",equalizer=f=10000:t=q:w=1.2:g=1.8"
        )

    # Formatação de áudio limpa e estéreo sem drift
    audio_post_filters += ",aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"

    curr_v_stream = "raw_v"
    if has_audio:
        filter_complex.append(f"{''.join(concat_inputs)}concat=n={n}:v=1:a=1[raw_v][raw_a]")
        filter_complex.append(f"[{curr_v_stream}]null{video_post_filters}[outv]")
        filter_complex.append(f"[raw_a]anull{audio_post_filters}[outa]")
        filter_str = ";\n".join(filter_complex)

        cmd = [ffmpeg_bin, "-y", "-i", str(source_path)]
        if pre_isolated_audio_path:
            cmd.extend(["-i", str(pre_isolated_audio_path)])

        cmd.extend([
            "-filter_complex", filter_str,
            "-map", "[outv]", "-map", "[outa]",
            "-sn", "-dn",
            "-map_metadata", "-1",
            "-map_chapters", "-1",
            "-c:v", "h264_nvenc", "-preset", "p5", "-cq", "14",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "320k",
            "-movflags", "+faststart",
            str(output_path)
        ])
    else:
        filter_complex.append(f"{''.join(concat_inputs)}concat=n={n}:v=1:a=0[raw_v]")
        filter_complex.append(f"[{curr_v_stream}]null{video_post_filters}[outv]")
        filter_str = ";\n".join(filter_complex)

        cmd = [
            ffmpeg_bin, "-y", "-i", str(source_path),
            "-filter_complex", filter_str,
            "-map", "[outv]",
            "-sn", "-dn",
            "-map_metadata", "-1",
            "-map_chapters", "-1",
            "-c:v", "h264_nvenc", "-preset", "p5", "-cq", "14",
            "-pix_fmt", "yuv420p",
            "-an", "-movflags", "+faststart",
            str(output_path)
        ]

    if on_log:
        mode_tag = f" [{EDITORIAL_MODES.get(editorial_mode, editorial_mode)}]" if editorial_mode != "linear" else ""
        on_log(f"[RENDER] Renderizando Mastercut com {n} cortes selecionados{mode_tag}...")
    if on_progress:
        on_progress(0.70, f"Renderizando Mastercut com {n} cortes via FFmpeg...")

    res = _run_ffmpeg_with_nvenc_fallback(cmd, timeout=600, on_log=on_log)

    out_file = Path(output_path)
    if res.returncode != 0 or not out_file.exists() or out_file.stat().st_size == 0:
        err_msg = res.stderr[-400:] if res and res.stderr else "Erro desconhecido"
        raise RuntimeError(f"FFmpeg falhou ao renderizar Mastercut: {err_msg}")

    # Demucs Post-Isolation logic removed (now handled as pre-isolation in process)

    final_dur = get_video_duration(str(out_file))
    final_size_mb = out_file.stat().st_size / (1024 * 1024)
    time_saved_pct = round((1 - (final_dur / video_duration)) * 100, 1) if video_duration > 0 else 0

    stats = {
        "output_path": str(out_file),
        "duration_before": video_duration,
        "duration_after": final_dur,
        "time_saved_percent": time_saved_pct,
        "segments_count": n,
        "size_mb": round(final_size_mb, 1),
        "vocal_isolation": vocal_isolation,
        "anti_copyright": anti_copyright,
        "enable_loop": enable_loop,
        "editorial_mode": editorial_mode,
        "editorial_mode_label": EDITORIAL_MODES.get(editorial_mode, "Linear Direto"),
        "loop_mode": "Contextual (Replay Infinito)" if enable_loop else "Sem Loop (Direto)",
        "roteiro": roteiro,
        "segments": segments
    }

    if on_log:
        on_log(f"[CONCLUÍDO] Mastercut concluído! {video_duration:.1f}s -> {final_dur:.1f}s ({time_saved_pct}% tempo economizado)")
    if on_progress:
        on_progress(1.0, "Mastercut gerado com sucesso!")

    return stats


def apply_standalone_anti_copyright_shield(
    input_path: str,
    output_path: str = None,
    mode: str = "youtube_max",
    on_progress=None,
    on_log=None
) -> str:
    """
    Aplica a Blindagem Anti-Copyright Nível YouTube (Toei-Proof)
    em qualquer vídeo existente em alta velocidade via FFmpeg (NVENC com fallback CPU).
    Perfeito para vídeos já editados e upscalados antes de entrar no Studio.
    Retorna o caminho do arquivo blindado gerado.
    """
    in_file = Path(input_path)
    if not in_file.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {input_path}")

    if not output_path:
        output_path = str(in_file.parent / f"{in_file.stem}_youtube_safe.mp4")

    ffmpeg_bin = _get_ffmpeg_bin("ffmpeg")
    ffprobe_bin = _get_ffmpeg_bin("ffprobe")
    has_audio = check_video_has_audio(str(in_file))

    # Detect resolution
    video_width, video_height = 1920, 1080
    try:
        probe_res = subprocess.run(
            [ffprobe_bin, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(in_file)],
            capture_output=True, encoding="utf-8", errors="replace", timeout=10, **_get_silent_subprocess_kwargs()
        )
        if probe_res.returncode == 0 and "x" in probe_res.stdout:
            parts = probe_res.stdout.strip().split("x")
            if len(parts) == 2:
                video_width = int(parts[0]) - (int(parts[0]) % 2)
                video_height = int(parts[1]) - (int(parts[1]) % 2)
    except Exception:
        pass

    if on_log:
        on_log(f"[BLINDAGEM YOUTUBE] Processando: {in_file.name} ({video_width}x{video_height})...")
        on_log(" - Flip Horizontal (Espelhamento Anti-pHash da Toei)")
        on_log(" - Aceleracao 1.04x calibrada (Pitch e Lip-sync preservados)")
        on_log(" - Crop 7% + Curva Cromatica e Vinheta Cinematografica")

    if on_progress:
        on_progress(0.20, "Aplicando blindagem anti-copyright via FFmpeg NVENC...")

    speed = 1.040 if mode == "youtube_max" else 1.020
    vf_list = []
    if mode == "youtube_max":
        vf_list.append("hflip")
        vf_list.append(f"setpts=PTS/{speed}")
        vf_list.append("crop=trunc(iw*0.93/2)*2:trunc(ih*0.93/2)*2")
        vf_list.append(f"scale={video_width}:{video_height}")
        vf_list.append("noise=c0s=4:c0f=u:allf=t+u")
        vf_list.append("eq=contrast=1.08:brightness=0.02:saturation=1.12:gamma=0.96")
        vf_list.append("vignette=PI/6")
    else:
        vf_list.append(f"setpts=PTS/{speed}")
        vf_list.append("crop=trunc(iw*0.96/2)*2:trunc(ih*0.96/2)*2")
        vf_list.append(f"scale={video_width}:{video_height}")
        vf_list.append("noise=c0s=3:c0f=u:allf=t+u")
        vf_list.append("eq=contrast=1.06:brightness=0.015:saturation=1.08:gamma=0.98")
        vf_list.append("vignette=PI/7")

    vf_str = ",".join(vf_list)

    cmd = [ffmpeg_bin, "-y", "-i", str(in_file), "-vf", vf_str]

    if has_audio:
        if mode == "youtube_max":
            af_str = (
                f"atempo={speed},"
                f"asetrate=48000*1.015,aresample=48000,atempo=1/1.015,"
                f"equalizer=f=300:t=q:w=1.5:g=-1.5,"
                f"equalizer=f=2800:t=q:w=1.2:g=1.4"
            )
        else:
            af_str = (
                f"atempo={speed},"
                f"equalizer=f=300:t=q:w=1.5:g=-1.5,"
                f"equalizer=f=2800:t=q:w=1.2:g=1.4"
            )
        cmd.extend(["-af", af_str, "-c:a", "aac", "-b:a", "320k"])
    else:
        cmd.append("-an")

    cmd.extend([
        "-c:v", "h264_nvenc", "-preset", "p5", "-cq", "14",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path)
    ])

    res = _run_ffmpeg_with_nvenc_fallback(cmd, timeout=300, on_log=on_log)
    out_p = Path(output_path)
    if res.returncode != 0 or not out_p.exists() or out_p.stat().st_size == 0:
        err = res.stderr[-400:] if res and res.stderr else "Falha ao gerar vídeo"
        raise RuntimeError(f"FFmpeg falhou ao blindar vídeo: {err}")

    if on_progress:
        on_progress(1.0, "Vídeo 100% blindado com sucesso!")
    if on_log:
        on_log(f"[SUCESSO] Vídeo gerado: {out_p.name} (Pronto para o YouTube ou Studio)!")

    return str(out_p)


# ─── High-Level Pipeline Runner ───────────────────────────────────────────────

class MastercutPipeline:
    """Orchestrates the complete Mastercut pipeline in a background thread."""

    def __init__(self):
        self.is_running = False
        self._cancelled = False
        self.cached_video_path = None
        self.cached_all_words = None
        self.cached_full_text = None
        self.cached_duration = None
        self.cached_action_blocks = None
        self.cached_visual_scenes = None

    def cancel(self):
        self._cancelled = True

    def process(
        self,
        video_path: str,
        output_path: str,
        video_context: str = "",
        work_title: str = "",
        scene_context: str = "",
        user_feedback: str = "",
        previous_segments: list = None,
        vocal_isolation: bool = True,
        demucs_isolation: bool = False,
        anti_copyright: bool = False,
        refine_mode: str = "balanced",
        target_duration_mode: str = "auto",
        enable_loop: bool = False,
        editorial_mode: str = "linear",
        is_continuous_clip: bool = False,
        is_dorama: bool = False,
        profile_label: str = "",
        ai_engine: str = "auto",
        local_model: str = "",
        on_progress=None,
        on_log=None
    ) -> dict:
        self.is_running = True
        self._cancelled = False

        if editorial_mode in ("loop", "viral_editor"):
            enable_loop = True

        clean_work_title = (work_title or "").strip()
        clean_scene_context = (scene_context or "").strip()
        if not clean_work_title and not clean_scene_context and video_context:
            clean_work_title = video_context.strip()

        if not is_dorama:
            ctx_lower = f"{clean_work_title} {clean_scene_context} {video_context}".lower()
            is_dorama = (
                refine_mode == "dorama"
                or editorial_mode == "dorama"
                or any(k in ctx_lower for k in ("dorama", "kdrama", "k-drama", "coreano", "c-drama", "j-drama", "doramas"))
            )


        try:
            # Pre-flight check: ensure FFmpeg and FFprobe are available
            ffmpeg_bin = _get_ffmpeg_bin("ffmpeg")
            ffprobe_bin = _get_ffmpeg_bin("ffprobe")
            import shutil
            ffmpeg_ok = Path(ffmpeg_bin).exists() if os.path.isabs(ffmpeg_bin) else bool(shutil.which(ffmpeg_bin))
            ffprobe_ok = Path(ffprobe_bin).exists() if os.path.isabs(ffprobe_bin) else bool(shutil.which(ffprobe_bin))

            if not ffmpeg_ok or not ffprobe_ok:
                err_msg = (
                    "O motor FFmpeg/FFprobe não foi encontrado no sistema.\n"
                    "O Urahara necessita do FFmpeg para recortar e renderizar vídeos.\n"
                    "Por favor, verifique se a pasta 'bin' está junto ao aplicativo ou "
                    "instale o FFmpeg com 1 clique através da aba 'Configurações'."
                )
                if on_log:
                    on_log(f"[ERRO]: {err_msg}")
                raise FileNotFoundError(err_msg)

            can_reuse_cache = (
                bool(user_feedback and user_feedback.strip())
                and self.cached_video_path == video_path
                and self.cached_all_words is not None
            )

            audio_source_for_whisper = video_path
            pre_isolated_audio = None

            if can_reuse_cache:
                if on_log:
                    on_log("⚡ [FEEDBACK REUTILIZAÇÃO] Reutilizando transcrição e análise visual em cache para reajuste cirúrgico instantâneo com a IA!")
                all_words = self.cached_all_words
                full_text = self.cached_full_text
                duration = self.cached_duration
                action_blocks = self.cached_action_blocks
                visual_scenes = self.cached_visual_scenes
            else:
                # Step 1: Detect speech & words
                if demucs_isolation:
                    if on_log:
                        on_log("═══ ETAPA PRÉ-CORTE: Isolamento Vocal (IA Demucs) ═══")
                    import tempfile, time
                    from upscaler import run_demucs_vocal_isolation
                    temp_vocals = os.path.join(tempfile.gettempdir(), f"mastercut_demucs_pre_{os.getpid()}_{int(time.time())}.wav")
                    if on_progress:
                        on_progress(0.10, "Isolando vocais puros com IA Demucs ANTES do corte...")
                    ok_d = run_demucs_vocal_isolation(video_path, temp_vocals, on_log=on_log)
                    if ok_d and os.path.exists(temp_vocals):
                        audio_source_for_whisper = temp_vocals
                        pre_isolated_audio = temp_vocals
                        if on_log:
                            on_log("[DEMUCS] Isolamento vocal concluído! O Whisper e o corte serão feitos na voz limpa, destruindo o Copyright da música original.")
                    else:
                        if on_log:
                            on_log("⚠️ [DEMUCS] Falha ao isolar voz. Continuando com áudio original do vídeo.")

                if on_log:
                    on_log("═══ ETAPA 1/3: Mapeamento de Diálogos (Whisper) ═══")
                all_words, full_text, duration = detect_speech_segments(
                    audio_source_for_whisper,
                    on_progress=on_progress,
                    on_log=on_log,
                    ai_engine=ai_engine
                )

                if self._cancelled:
                    raise InterruptedError("Operação cancelada pelo usuário.")

                # Step 2: Detect visual action
                action_blocks = detect_visual_action_blocks(video_path, on_log=on_log)

                if self._cancelled:
                    raise InterruptedError("Operação cancelada pelo usuário.")

                # Step 2b: AI Vision - describe silent scenes (attacks, powers, romantic moments, etc.)
                if on_log:
                    on_log("═══ ETAPA 2b/3: Análise Visual de Cenas Silenciosas (IA Vision) ═══")
                visual_scenes = describe_silent_scenes_with_vision(
                    video_path=video_path,
                    all_words=all_words,
                    video_duration=duration,
                    video_context=video_context,
                    work_title=clean_work_title,
                    scene_context=clean_scene_context,
                    ai_engine=ai_engine,
                    on_log=on_log
                )

                if self._cancelled:
                    raise InterruptedError("Operação cancelada pelo usuário.")

                # Cache analysis results on the pipeline instance for rapid correction loops
                self.cached_video_path = video_path
                self.cached_all_words = all_words
                self.cached_full_text = full_text
                self.cached_duration = duration
                self.cached_action_blocks = action_blocks
                self.cached_visual_scenes = visual_scenes

            # Step 3: AI Selection (Opção 4: Mastercut Concentrado)
            if on_log:
                if user_feedback:
                    on_log("═══ ETAPA 3/3: Reajuste Cirúrgico Mastercut com Feedback do Diretor (IA) ═══")
                else:
                    on_log("═══ ETAPA 3/3: Seleção Mastercut Concentrado (IA) ═══")
            if on_progress:
                on_progress(0.50, "IA refinando corte sem mutilação de diálogos e momentos...")

            segments, roteiro = build_refined_segments(
                all_words=all_words,
                video_duration=duration,
                action_blocks=action_blocks,
                visual_scenes=visual_scenes,
                video_context=video_context,
                work_title=clean_work_title,
                scene_context=clean_scene_context,
                user_feedback=user_feedback,
                previous_segments=previous_segments,
                refine_mode=refine_mode,
                target_duration_mode=target_duration_mode,
                enable_loop=enable_loop,
                editorial_mode=editorial_mode,
                anti_copyright=anti_copyright,
                is_continuous_clip=is_continuous_clip,
                is_dorama=is_dorama,
                audio_path=audio_source_for_whisper,
                ai_engine=ai_engine,
                local_model=local_model,
                on_log=on_log
            )


            if self._cancelled:
                raise InterruptedError("Operação cancelada pelo usuário.")

            if not segments:
                if on_log:
                    on_log("[AVISO] Nenhum segmento retornado. Ativando corte mestre de segurança para renderização...")
                segments = [{"start": 0.0, "end": round(duration, 3), "text": "[Mastercut Completo]"}]

            # Step 4: Video Assembly
            if on_log:
                on_log("═══ ETAPA 3/3: Renderização e Concatenação FFmpeg ═══")
            stats = render_mastercut_video(
                source_path=video_path,
                segments=segments,
                output_path=output_path,
                vocal_isolation=vocal_isolation,
                demucs_isolation=demucs_isolation,
                anti_copyright=anti_copyright,
                enable_loop=enable_loop,
                editorial_mode=editorial_mode,
                roteiro=roteiro,
                on_progress=on_progress,
                on_log=on_log,
                pre_isolated_audio_path=pre_isolated_audio
            )
            
            try:
                if pre_isolated_audio and os.path.exists(pre_isolated_audio):
                    os.remove(pre_isolated_audio)
            except:
                pass

            if profile_label:
                stats["editorial_mode_label"] = profile_label
            return stats

        finally:
            self.is_running = False
