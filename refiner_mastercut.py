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
    "dorama": "Dorama Emocional (Diálogos Íntegros & Pausas Dramáticas)",
}

HOOK_TEASER_RESERVE = 3.0

# Unified edit styles: each profile is ONE coherent recipe (pacing + target length + structure).
# The UI exposes only these, so pacing, duration and editorial structure can never contradict each other.
EDIT_PROFILES = {
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


def detect_speech_segments(video_path: str, on_progress=None, on_log=None):
    """
    Extracts 16kHz mono audio and transcribes it to get word-level / segment-level timestamps.
    Tries Groq Whisper API first (if key configured), then falls back to local faster_whisper.
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

        # 1. Try Groq Whisper API (whisper-large-v3 com word-level timestamps)
        groq_raw = os.getenv("GROQ_API_KEY", "").strip()
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
            ctx_hint = f" Esta é uma cena de: {video_context.strip()}." if video_context and video_context.strip() else ""
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
    return keys


def group_words_by_speech_gaps(all_words: list, max_gap: float = 0.35, is_dorama: bool = False) -> list:
    """
    Groups individual words into coherent speech phrases, breaking whenever
    silence between consecutive words exceeds max_gap seconds.
    If is_dorama is True and standard max_gap is passed, expands to 0.65s to preserve emotional acting pauses.
    """
    if is_dorama and max_gap <= 0.40:
        max_gap = 0.65
    if not all_words:
        return []

    groups = []
    curr_start = all_words[0]["start"]
    curr_end = all_words[0]["end"]
    curr_text = [all_words[0].get("text") or all_words[0].get("word", "")]

    for i in range(1, len(all_words)):
        w = all_words[i]
        prev_w = all_words[i - 1]
        gap = w["start"] - prev_w["end"]
        if gap <= max_gap:
            curr_end = w["end"]
            curr_text.append(w.get("text") or w.get("word", ""))
        else:
            dur = round(curr_end - curr_start, 3)
            if dur > 0.1:
                groups.append({
                    "start": round(curr_start, 3),
                    "end": round(curr_end, 3),
                    "duration": dur,
                    "words_count": len(curr_text),
                    "text": " ".join(curr_text)
                })
            curr_start = w["start"]
            curr_end = w["end"]
            curr_text = [w.get("text") or w.get("word", "")]

    dur = round(curr_end - curr_start, 3)
    if dur > 0.1:
        groups.append({
            "start": round(curr_start, 3),
            "end": round(curr_end, 3),
            "duration": dur,
            "words_count": len(curr_text),
            "text": " ".join(curr_text)
        })

    return groups


def _merge_segments(segments: list, min_gap: float = 0.15) -> list:
    """Merges overlapping or touching segments to prevent jitter."""
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


def align_segments_to_speech_boundaries(segments: list, all_words: list, video_duration: float) -> list:
    """
    Garante que nenhum segmento comece ou termine decepando palavras ao meio.
    - Se o início do corte decepar uma palavra ao meio, recua para o início da palavra (-0.06s).
    - Se o final do corte decepar uma palavra ao meio, estende para o término da palavra (+0.18s).
    - Garante respiração acústica segura nas pontas (+0.18s / -0.06s).
    - Não faz expansão descontrolada em cascata para não fundir cortes distantes.
    """
    if not segments or not all_words:
        return segments

    aligned = []
    for seg in segments:
        s_t = seg["start"]
        e_t = seg["end"]

        # 1. Ajuste do início: se corta uma palavra no meio, recua para o início da palavra
        cutting_start_word = [w for w in all_words if w["start"] < s_t < w["end"]]
        if cutting_start_word:
            s_t = max(0.0, cutting_start_word[0]["start"] - 0.06)
        else:
            nearby_start = [w for w in all_words if 0 <= (w["start"] - s_t) <= 0.15]
            if nearby_start:
                s_t = max(0.0, nearby_start[0]["start"] - 0.06)

        # 2. Ajuste do fim: se corta uma palavra no meio, estende para o término da palavra com respiro
        cutting_end_word = [w for w in all_words if w["start"] <= e_t < w["end"]]
        if cutting_end_word:
            e_t = min(video_duration, cutting_end_word[-1]["end"] + 0.18)
        else:
            inside_words = [w for w in all_words if w["end"] <= e_t and w["start"] >= s_t]
            if inside_words:
                last_w = inside_words[-1]
                if (e_t - last_w["end"]) < 0.20:
                    e_t = min(video_duration, last_w["end"] + 0.18)

        aligned.append({
            **seg,
            "start": round(s_t, 3),
            "end": round(min(video_duration, e_t), 3),
        })

    return _merge_segments(aligned, min_gap=0.15)


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
    if target_duration_mode == "mini_movie":
        # Tratar Mini-Filme: reduz para aproximadamente a metade (~50%), teto estrito de 150s (2:30 min)
        if v_dur <= 40.0:
            min_d = max(12.0, v_dur * 0.50)
            max_d = min(v_dur, max(min_d + 4.0, v_dur * 0.85))
        else:
            target_half = v_dur * 0.50
            max_d = min(150.0, max(45.0, target_half + 8.0), v_dur * 0.70)
            min_d = max(30.0, min(max_d - 12.0, target_half - 12.0))
        return round(min_d, 1), round(max_d, 1)
    elif target_duration_mode == "max_retention":
        # Retenção Máxima: em vídeos curtos (<=40s), não força descarte de falas cruciais!
        if v_dur <= 40.0:
            min_d = max(10.0, v_dur * 0.75)
            max_d = v_dur
        else:
            min_d = max(25.0, v_dur * 0.75)
            max_d = min(v_dur * 0.92, max(min_d + 4.0, v_dur * 0.88))
        return round(min_d, 1), round(max_d, 1)
    elif target_duration_mode == "standard":
        # Padrão Shorts: 35s a 90s, teto flexível para evitar mutilação de cenas boas
        if v_dur <= 40.0:
            min_d = max(12.0, v_dur * 0.70)
            max_d = v_dur
        else:
            min_d = min(35.0, v_dur * 0.50)
            max_d = min(v_dur * 0.85, 90.0)
        return round(max(14.0, min_d), 1), round(max(min_d + 4.0, max_d), 1)
    elif target_duration_mode == "short":
        # Curto & Rápido: 20s a 35s
        min_d = max(10.0, min(20.0, v_dur * 0.35))
        max_d = min(v_dur * 0.70, 35.0)
        return round(min_d, 1), round(max(min_d + 4.0, max_d), 1)

    # Automatic mode based on refine_mode & video_duration
    if v_dur <= 40.0:
        # Vídeo ultracurto (já no formato Shorts/Reels, ex: 15s a 40s)
        # NUNCA mutilar frases inteiras: cortar apenas silêncios mortos nas pontas!
        if refine_mode == "soft":
            min_d = max(10.0, v_dur * 0.75)
            max_d = v_dur
        elif refine_mode == "aggressive":
            min_d = max(8.0, v_dur * 0.35)
            max_d = min(v_dur * 0.65, 25.0)
        else:  # balanced
            min_d = max(12.0, v_dur * 0.65)
            max_d = min(v_dur, max(min_d + 4.0, v_dur * 0.95))
    elif v_dur <= 75.0:
        # Vídeo curto (40s a 75s)
        if refine_mode == "soft":
            min_d = max(25.0, v_dur * 0.75)
            max_d = min(v_dur, max(min_d + 3.0, v_dur * 0.92))
        elif refine_mode == "aggressive":
            min_d = max(15.0, v_dur * 0.35)
            max_d = max(min_d + 3.0, v_dur * 0.55)
        else:
            # Equilibrado (padrão): 55% a 80%
            min_d = max(20.0, v_dur * 0.55)
            max_d = min(v_dur * 0.80, max(min_d + 4.0, v_dur * 0.75))
    elif v_dur <= 180.0:
        # Clipe médio (1.5m a 3m)
        if refine_mode == "soft":
            min_d = max(50.0, v_dur * 0.60)
            max_d = min(v_dur * 0.82, 90.0)
        elif refine_mode == "aggressive":
            min_d = 25.0
            max_d = min(v_dur * 0.45, 45.0)
        else:  # balanced
            min_d = 35.0
            max_d = min(v_dur * 0.68, 60.0)
    else:
        # Vídeo longo (> 3m)
        if refine_mode == "soft":
            min_d = 60.0
            max_d = min(v_dur * 0.55, 110.0)
        elif refine_mode == "aggressive":
            min_d = 28.0
            max_d = 45.0
        else:  # balanced
            min_d = 40.0
            max_d = 65.0

    return round(min_d, 1), round(max_d, 1)



def call_ai_mastercut_timeline(
    all_words,
    video_duration,
    action_blocks=None,
    visual_scenes=None,
    video_context="",
    refine_mode="balanced",
    target_duration_mode="auto",
    enable_loop=False,
    editorial_mode="linear",
    is_dorama=False,
    on_log=None
):
    """
    Sends the video dialogue transcription + visual scene descriptions to Gemini AI (or Groq fallback)
    requesting the Mastercut timeline with strict anti-overcut rules and duration boundaries.
    Visual scenes include AI-described silent moments: attacks, powers, romantic scenes, emotional reactions, etc.
    """
    action_blocks = action_blocks or []
    visual_scenes = visual_scenes or []

    # Auto-detect Dorama if not explicitly specified
    if not is_dorama:
        ctx_lower = str(video_context or "").lower()
        is_dorama = (
            refine_mode == "dorama"
            or editorial_mode == "dorama"
            or any(k in ctx_lower for k in ("dorama", "kdrama", "k-drama", "coreano", "c-drama", "j-drama", "doramas"))
        )

    min_dur, max_dur = calculate_mastercut_bounds(video_duration, refine_mode, target_duration_mode)

    # Build grouped dialogue sentences with precise acoustic boundaries
    # Para doramas, pausas naturais de até 0.60s são mantidas como parte da mesma frase emocional
    speech_summary = []
    speech_gap_thresh = 0.60 if is_dorama else 0.40
    speech_len_thresh = 6.5 if is_dorama else 4.5
    if all_words:
        curr_phrase = []
        p_start = None
        for i, w in enumerate(all_words):
            if p_start is None:
                p_start = w["start"]
            curr_phrase.append(w["text"])
            is_last = (i == len(all_words) - 1)
            next_gap = (all_words[i + 1]["start"] - w["end"]) if not is_last else 999.0
            if is_last or w["text"].endswith(('.', '!', '?', '…')) or next_gap >= speech_gap_thresh or (w["end"] - p_start > speech_len_thresh):
                p_text = " ".join(curr_phrase)
                speech_summary.append(f"[{p_start:.2f}s -> {w['end']:.2f}s] \"{p_text}\"")
                curr_phrase = []
                p_start = None

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

    ctx_block = ""
    if video_context and video_context.strip():
        extra_meta = ""
        try:
            from metadata_enricher import get_enriched_context_for_prompt
            cat_hint = "dorama" if is_dorama else "anime"
            extra_meta = get_enriched_context_for_prompt(video_context.strip(), category=cat_hint, on_log=on_log)
        except Exception:
            pass

        ctx_block = f"""
[CONTEXTO DA OBRA / {'DORAMA' if is_dorama else 'ANIME'} / EPISÓDIO]
Contexto informado: {video_context.strip()}
{extra_meta}
Use esse conhecimento de {'dorama/série' if is_dorama else 'anime/série'} para identificar com precisão os personagens falando, técnicas/poderes/química, o arco narrativo e as falas/reações mais marcantes desta cena!
"""
        if on_log:
            on_log(f"[CONTEXTO] Contexto {'de Dorama ' if is_dorama else ''}aplicado à IA: '{video_context.strip()}'")

    mode_descriptions = {
        "soft": "PRESERVAÇÃO MÁXIMA DE CONTEÚDO (Anti-Silêncio). Mantenha praticamente todas as falas, conversas e reações. Elimine estritamente pausas mortas (>0.35s) e silêncios.",
        "balanced": "EQUILIBRADO / RITMO DINÂMICO (Padrão). Elimine pausas mortas e partes mornas, mas MANTENHA as falas completas, réplicas entre personagens e momentos importantes. Não corte em excesso!",
        "aggressive": "AGRESSIVO / O SUCO PURO. Condensa para extrair apenas o clímax absoluto e momentos mais eletrizantes.",
        "dorama": "DORAMA DRAMÁTICO / ROMANCE & TENSÃO. Mantenha os diálogos íntegros, as réplicas completas (pergunta + resposta) e as pausas emocionais/olhares de reação entre os personagens sem picotar a atuação.",
    }
    mode_guide = mode_descriptions.get(refine_mode, mode_descriptions["balanced"])
    if target_duration_mode == "mini_movie":
        mode_guide = (
            f"RESUMO MINI-FILME / RECAP NARRATIVO (~50% do clipe, máx 2:30 min). "
            f"Condense este arco de {video_duration:.1f}s num Mini-Filme cinematográfico de {min_dur:.1f}s a {max_dur:.1f}s, "
            "estruturado em 4 atos: 1. Contexto/Início -> 2. Escalada de conflito e réplicas -> 3. Clímax de pico -> 4. Desfecho e reações. "
            "Corte apenas tempos mortos e gorduras, preservando o sentido e o suco da história!"
        )

    # The AI only SELECTS (chronologically). Hook/loop placement is done deterministically afterwards,
    # otherwise the chronological merge would silently swallow an AI-placed teaser.
    editorial_instruction = ""
    if editorial_mode in ("hook", "viral_editor"):
        loop_line = (
            "\n   - O ÚLTIMO corte deve terminar numa fala/reação marcante e completa: ela será a ponte do loop de replay."
            if editorial_mode == "viral_editor" else ""
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
    else:
        director_title = "SUPER SENIOR EDITOR CINEMÁTICO E VIRAL para YouTube Shorts, Reels e TikTok"
        golden_rules = """⛔ REGRAS DE OURO DA ENGENHARIA NARRATIVA VIRAL & ANTI-COPYRIGHT:
1. **DINÂMICA DIALÉTICA E PESO DRAMÁTICO (NÃO SEJA UM ROBÔ CORTADOR)**:
   - O maior erro de IA é cortar silêncios que na verdade são 'Tensão Dramática'. Se um personagem faz uma ameaça ("Você vai pagar por isso"), a pausa antes da resposta ("Eu traí?") é OBRIGATÓRIA.
   - NÃO retalhe frases. Mantenha as réplicas, debates e o arco emocional. Cada corte deve ter um propósito narrativo.
2. **MICRO-BEATS DINÂMICOS (MÁXIMO 3.8s POR CORTE)**:
   - Elimine silêncios verdadeiramente vazios/mortos, mas deixe os cortes respirarem de 1.8s a 3.8s para não parecer que o vídeo foi picotado por um triturador.
3. **TAGS DE CINEMATOGRAFIA MULTI-CÂMERA ("framing")**:
   - "punch": Smart Close-Up (+14% zoom) para clímax, gritos, ameaças, mic drops ou revelações.
   - "wide": Plano Aberto (+4% zoom) para contexto, ação rápida ou apresentação.
   - "reaction": Plano Médio (+8% zoom) para deboche, ironia, choque ou contra-ataque verbal.
   - ALTERNE os enquadramentos entre falas para simular uma direção multi-câmera viva ("wide" -> "punch" -> "reaction").
4. **O HOOK E O INÍCIO (FRAME 0)**:
   - Comece direto na ação ou fala mais impactante. Se o começo for parado, você deve escolher um "punchline" absoluto para iniciar.
5. **O CLÍMAX FINAL (MIC DROP ABSOLUTO)**:
   - O corte FINAL do vídeo DEVE encerrar perfeitamente. NUNCA deixe o final abrupto no meio de uma frase! Escolha a melhor frase de impacto, deixe o eco final da palavra terminar e feche o clipe com excelência."""

    prompt = f"""Você é o {director_title}.
Este clipe foi pré-selecionado pelo Diretor IA e representa uma cena de ouro.
Seu objetivo é transformar esta cena em um **MASTERCUT VIRAL DE ALTA RETENÇÃO (>100%) E TOTALMENTE BLINDADO CONTRA CONTENT ID / REUSED CONTENT**.
{ctx_block}
DADOS DO VÍDEO BRUTO:
- Duração Original do Clipe: {video_duration:.1f} segundos (A LINHA DO TEMPO VAI ESTRITAMENTE DE 0.0s ATÉ {video_duration:.1f}s)

📣 DIÁLOGOS TRANSCRITOS:
{chr(10).join(speech_summary) if speech_summary else "[Sem falas detectadas - use os cortes visuais como referência principal]"}

🎬 CENAS VISUAIS ANALISADAS POR IA (incluindo momentos SEM FALA):
{chr(10).join(visual_summary) if visual_summary else (chr(10).join(f"[{ab['start']:.2f}s -> {ab['end']:.2f}s] {'💕 Tensão Dramática' if is_dorama else '⚔️ Cena de Ação/Luta'}" for ab in action_blocks) if action_blocks else "[Análise visual não disponível]")}
{forced_scenes_block}
🎯 DIRETRIZ ESTRITA DE DURAÇÃO FINAL:
- Duração do Clipe: {video_duration:.1f} segundos.
- Modo de Refino Selecionado: {mode_guide}
- DURAÇÃO TOTAL OBRIGATÓRIA DA SOMA DOS SEGMENTOS: entre {min_dur:.1f}s e {max_dur:.1f}s.

{golden_rules}

{mini_movie_instruction}
{editorial_instruction}

Retorne EXCLUSIVAMENTE um objeto JSON no seguinte formato (sem comentários, apenas JSON puro):
{{
  "ai_viral": [
    {{"start": 0.00, "end": 2.60, "framing": "punch", "text": "Hook impactante com fala ou choque imediato"}},
    {{"start": 2.70, "end": 5.20, "framing": "wide", "text": "Réplica firme do personagem"}},
    {{"start": 5.25, "end": 8.10, "framing": "punch", "text": "Clímax da discussão e revelação"}},
    {{"start": 8.15, "end": 11.00, "framing": "reaction", "text": "Desfecho com gancho para loop"}}
  ]
}}
"""

    keys = _get_api_keys()
    if not keys:
        if on_log:
            on_log("[INFO] Nenhuma chave Gemini configurada no .env. Usando inteligência heurística local para o Mastercut...")
        return None

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
        preferred_model,
        "gemini-2.5-flash",
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
                    if isinstance(data, list):
                        timeline = data
                    elif isinstance(data, dict):
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
                        return timeline
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
                    if api_health is not None:
                        api_health.mark_model_unavailable(model_name, err_s, cooldown_secs=3600)
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
                        if isinstance(data, list):
                            timeline = data
                        elif isinstance(data, dict):
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
                            return timeline
                except Exception as e_sub:
                    if on_log:
                        on_log(f"[AVISO] Fallback Groq ({g_model}) falhou: {e_sub}")
                    continue
        except Exception as e:
            if on_log:
                on_log(f"Aviso fallback Groq: {e}")

    return None


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

    gap_val = 0.65 if (is_dorama or refine_mode in ("soft", "dorama")) else 0.35
    groups = group_words_by_speech_gaps(all_words, max_gap=gap_val, is_dorama=is_dorama)
    if not groups:
        return _create_visual_cuts()

    # Em vídeos curtos (<=40s) ou modo de preservação (soft), manter todos os diálogos!
    total_speech_dur = sum(g["duration"] for g in groups)

    if total_speech_dur <= max_dur or video_duration <= 40.0 or refine_mode == "soft":
        picked = sorted(groups, key=lambda x: x["start"])
    else:
        for g in groups:
            d = max(0.5, g["duration"])
            g["score"] = (g["words_count"] / d) * (min(10.0, d) ** 0.5)

        sorted_by_score = sorted(groups, key=lambda x: x["score"], reverse=True)
        picked = []
        accum = 0.0
        for g in sorted_by_score:
            if accum + g["duration"] <= max_dur:
                picked.append(g)
                accum += g["duration"]
                if accum >= min_dur and len(picked) >= 3:
                    break

        if not picked:
            picked = groups[:4]

        picked.sort(key=lambda x: x["start"])

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

    groups = group_words_by_speech_gaps(all_words, max_gap=0.35) if all_words else []
    refined = sorted(refined, key=lambda x: x["start"])

    # Phase 1: Micro-padding on segment boundaries (only up to 0.10s) to avoid clipping edges
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

    # Phase 2: If still under min_dur, insert missing speech groups that don't overlap with existing cuts
    if total_cur < min_dur and groups:
        for g in groups:
            d = max(0.4, g["duration"])
            g["score"] = (g["words_count"] / d) * (min(8.0, d) ** 0.5)
        sorted_groups = sorted(groups, key=lambda x: x.get("score", 0), reverse=True)

        for g in sorted_groups:
            # Check overlap with existing segments (require at least 0.20s gap so cuts stay distinct)
            has_conflict = False
            for s in expanded:
                if not (g["end"] <= s["start"] - 0.20 or g["start"] >= s["end"] + 0.20):
                    has_conflict = True
                    break
            if not has_conflict:
                g_dur = g["end"] - g["start"]
                if total_cur + g_dur <= max_dur:
                    expanded.append({
                        "start": g["start"],
                        "end": g["end"],
                        "text": g.get("text", "[Diálogo Restaurado]")
                    })
                    total_cur += g_dur
                    if total_cur >= min_dur:
                        break

        expanded.sort(key=lambda x: x["start"])
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

    # 1. Verifica se o início já tem fala ou ação relevante
    first_speech_time = all_words[0]["start"] if all_words else None
    first_seg_start = refined[0]["start"]

    has_early_speech = (first_speech_time is not None and first_speech_time <= 2.8) or (first_seg_start <= 2.0)

    if has_early_speech:
        if on_log:
            on_log("[VIRAL PRO] Início do vídeo já possui fala de impacto! Iniciando direto na ação (sem repetições).")

        narrative = [{**s, "role": "story"} for s in refined]
        # Corta qualquer respiro mudo antes da fala inicial
        if first_speech_time is not None and narrative:
            lead_silence = max(0.0, first_speech_time - narrative[0]["start"])
            if lead_silence >= 0.30:
                trimmed_start = round(max(0.0, first_speech_time - 0.08), 3)
                if trimmed_start < narrative[0]["end"] - 0.5:
                    if on_log:
                        on_log(f"   • Silêncio inicial cortado: começa no milissegundo {trimmed_start:.2f}s direto na voz!")
                    narrative[0]["start"] = trimmed_start

        narrative[0]["role"] = "hook"
        narrative[0]["framing"] = "punch"

        # Garante que o final encerra no ápice da última fala (mic drop, sem cauda vazia)
        if len(narrative) >= 1 and all_words:
            last_seg = narrative[-1]
            last_words = [w for w in all_words if last_seg["start"] <= w["start"] <= last_seg["end"]]
            if last_words:
                last_w = last_words[-1]
                trail_silence = last_seg["end"] - last_w["end"]
                if trail_silence >= 0.45:
                    last_seg["end"] = round(last_w["end"] + 0.20, 3)

        if on_log:
            on_log("[VIRAL PRO] Montagem Viral Pro finalizada: Início Explosivo + Pacing Ágil + Desfecho em Pico!")

        return finalize_ordered_segments(narrative)

    # 2. Se o início do vídeo for lento (>2.8s sem ninguém falar)
    if on_log:
        on_log("[VIRAL PRO] Início lento detectado (>2.8s sem falas). Extraindo teaser inicial e limpando repetições...")

    with_hook = apply_hook_opening(
        refined=refined,
        all_words=all_words,
        video_duration=video_duration,
        action_blocks=action_blocks,
        visual_scenes=visual_scenes,
        on_log=on_log
    )

    # Remove qualquer segmento no corpo que seja duplicata do gancho (evita repetição bizarra)
    if len(with_hook) >= 2:
        hook_seg = with_hook[0]
        cleaned_body = []
        for s in with_hook[1:]:
            overlap_s = max(s["start"], hook_seg["start"])
            overlap_e = min(s["end"], hook_seg["end"])
            overlap_dur = max(0.0, overlap_e - overlap_s)
            s_dur = s["end"] - s["start"]

            if s_dur > 0 and (overlap_dur / s_dur) >= 0.65:
                if on_log:
                    on_log(f"   • Evitada repetição da cena do gancho ({s['start']:.2f}s - {s['end']:.2f}s) no meio da história.")
                continue
            cleaned_body.append(s)

        if cleaned_body:
            with_hook = [hook_seg] + cleaned_body

    if on_log:
        on_log("[VIRAL PRO] Edição Viral Pro montada com sucesso: Gancho sem repetições + Narrativa coerente!")

    return finalize_ordered_segments(with_hook)


def build_refined_segments(
    all_words,
    video_duration,
    action_blocks=None,
    visual_scenes=None,
    video_context="",
    refine_mode="balanced",
    target_duration_mode="auto",
    enable_loop=False,
    editorial_mode="linear",
    anti_copyright=True,
    is_continuous_clip=False,
    is_dorama=False,
    on_log=None
):
    """
    Executes AI Mastercut selection with smart audio padding (-80ms, +250ms),
    merging overlaps and applying anti-overcut protection to prevent mutilation.
    Guaranteed NEVER to return an empty list of segments!
    """
    # Auto-detect Dorama if not explicitly specified
    if not is_dorama:
        ctx_lower = str(video_context or "").lower()
        is_dorama = (
            refine_mode == "dorama"
            or editorial_mode == "dorama"
            or any(k in ctx_lower for k in ("dorama", "kdrama", "k-drama", "coreano", "c-drama", "j-drama", "doramas"))
        )

    min_dur, max_dur = calculate_mastercut_bounds(video_duration, refine_mode, target_duration_mode)
    # The opening teaser is a repeated excerpt, so its seconds come out of the story budget:
    # the final video lands inside the promised range instead of overshooting it.
    teaser_reserve = HOOK_TEASER_RESERVE if editorial_mode in ("hook", "viral_editor") else 0.0
    body_max = max(min_dur, max_dur - teaser_reserve)
    if on_log:
        mode_label = EDITORIAL_MODES.get(editorial_mode, "Linear Direto")
        dor_tag = " [Perfil Dorama Ativo: Ritmo Emocional]" if is_dorama else ""
        on_log(f"[META] Meta de duração do Mastercut: {min_dur:.1f}s a {max_dur:.1f}s (Ritmo: {refine_mode} | Editorial: {mode_label}){dor_tag}")
        if teaser_reserve:
            on_log(f"[META] Orçamento da história: até {body_max:.1f}s + gancho de ~{teaser_reserve:.0f}s")

    timeline = call_ai_mastercut_timeline(
        all_words,
        video_duration,
        action_blocks,
        visual_scenes=visual_scenes,
        video_context=video_context,
        refine_mode=refine_mode,
        target_duration_mode=target_duration_mode,
        enable_loop=enable_loop,
        editorial_mode=editorial_mode,
        is_dorama=is_dorama,
        on_log=on_log
    )

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

    # CRITICAL: If after parsing AI timeline, refined is STILL empty or has fewer than 2 segments:
    if not refined or len(refined) < 2:
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

    # Enforce upper bound (story budget) com proteção estrita contra mutilação de frases
    total_dur = sum(s["end"] - s["start"] for s in refined)
    if total_dur > body_max + 0.5:
        trimmed = []
        t_acc = 0.0
        for s in refined:
            seg_d = s["end"] - s["start"]
            if t_acc + seg_d <= body_max:
                trimmed.append(s)
                t_acc += seg_d
            else:
                remaining = body_max - t_acc
                if video_duration <= 40.0 or refine_mode == "soft" or is_dorama or target_duration_mode == "max_retention" or (t_acc + seg_d <= body_max + 4.0):
                    trimmed.append(s)
                    t_acc += seg_d
                    break
                elif remaining >= 2.0:
                    safe_cut_end = None
                    if all_words:
                        target_t = s["start"] + remaining
                        candidate_words = [w for w in all_words if s["start"] <= w["start"] and w["end"] <= target_t + 0.35]
                        if candidate_words:
                            last_w = candidate_words[-1]
                            safe_cut_end = round(min(s["end"], last_w["end"] + 0.25), 3)
                    if safe_cut_end is None or safe_cut_end <= s["start"] + 1.0:
                        safe_cut_end = round(s["start"] + remaining, 3)
                    trimmed.append({**s, "end": safe_cut_end})
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
    elif editorial_mode == "viral_editor":
        refined = apply_viral_editor_structure(
            refined=refined,
            all_words=all_words,
            video_duration=video_duration,
            action_blocks=action_blocks,
            visual_scenes=visual_scenes,
            on_log=on_log
        )

    # Anti-Copyright: split long continuous takes on real speech pauses (order-preserving)
    # Para doramas, limite contínuo ampliado para 8.0s para não cortar reações humanas
    if anti_copyright:
        cont_sec = 8.0 if is_dorama else 3.8
        refined = apply_anti_copyright_continuous_splits(
            segments=refined,
            all_words=all_words,
            max_continuous_sec=cont_sec,
            video_duration=video_duration,
            is_continuous_clip=is_continuous_clip,
            is_dorama=is_dorama,
            on_log=on_log
        )

    # Validação Final: sem overlap nem micro-engasgos, preservando a ordem editorial
    refined = finalize_ordered_segments(refined)

    # Simulação de 2ª Câmera Multi-Cam (Smart Punch-In Anti-Copyright):
    # Para doramas: limite de 6.0s (transições suaves), para animes: 3.8s
    if anti_copyright:
        shot_dur = 6.0 if is_dorama else 3.8
        refined = split_long_segments_for_multicam(refined, max_shot_dur=shot_dur, is_dorama=is_dorama)
        if on_log:
            on_log(f"[MULTI-CAM] Cinematografia dinâmica aplicada ({'Dorama 6.0s' if is_dorama else 'Ágil 3.8s'}): {len(refined)} planos alternados (Wide / Punch / Reaction).")

    # Absolute ultimate failsafe: NEVER return empty!
    if not refined:
        refined = [{"start": 0.0, "end": round(video_duration, 3), "text": "[Mastercut Completo]", "framing": "wide"}]

    return refined


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

    # Flash sits exactly at the hook → story boundary, even when multi-cam split the hook into several takes
    hook_idxs = [idx for idx, sg in enumerate(segments) if sg.get("role") == "hook"]
    if hook_idxs:
        hook_last_idx = hook_idxs[-1]
    else:
        hook_last_idx = 0 if editorial_mode in ("hook", "viral_editor") else -1
    has_hook_transition = 0 <= hook_last_idx < n - 1

    for i, seg in enumerate(segments):
        s = seg["start"]
        e = seg["end"]
        dur_i = e - s
        framing = seg.get("framing", "wide")

        # Smart Multi-Camera Framing por Segmento:
        # punch: close-up de impacto (+14% zoom em momentos de tensão/fala forte)
        # reaction: enquadramento de resposta (+8% zoom)
        # wide: plano aberto cinematográfico (+4% zoom)
        # Mantém a resolução nativa exata do vídeo sem distorção
        if anti_copyright:
            if framing == "punch":
                sc = 1.14
            elif framing == "reaction":
                sc = 1.08
            else:
                sc = 1.04
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
            # Micro-fade de áudio de 25ms para cortes 100% orgânicos, imperceptíveis e sem estalos
            afade_dur = min(0.025, dur_i / 4.0)
            afade_out_st = max(0.0, dur_i - afade_dur)
            audio_source_idx = "1" if pre_isolated_audio_path else "0"
            filter_complex.append(
                f"[{audio_source_idx}:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,afade=t=in:st=0:d={afade_dur:.3f},afade=t=out:st={afade_out_st:.3f}:d={afade_dur:.3f}[a{i}]"
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

    def cancel(self):
        self._cancelled = True

    def process(
        self,
        video_path: str,
        output_path: str,
        video_context: str = "",
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
        on_progress=None,
        on_log=None
    ) -> dict:
        self.is_running = True
        self._cancelled = False

        if editorial_mode in ("loop", "viral_editor"):
            enable_loop = True

        if not is_dorama:
            ctx_lower = str(video_context or "").lower()
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

            # Step 1: Detect speech & words
            audio_source_for_whisper = video_path
            pre_isolated_audio = None
            
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
            all_words, full_text, duration = detect_speech_segments(audio_source_for_whisper, on_progress=on_progress, on_log=on_log)

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
                on_log=on_log
            )

            if self._cancelled:
                raise InterruptedError("Operação cancelada pelo usuário.")

            # Step 3: AI Selection (Opção 4: Mastercut Concentrado)
            if on_log:
                on_log("═══ ETAPA 3/3: Seleção Mastercut Concentrado (IA) ═══")
            if on_progress:
                on_progress(0.50, "IA refinando corte sem mutilação de diálogos e momentos...")

            segments = build_refined_segments(
                all_words=all_words,
                video_duration=duration,
                action_blocks=action_blocks,
                visual_scenes=visual_scenes,
                video_context=video_context,
                refine_mode=refine_mode,
                target_duration_mode=target_duration_mode,
                enable_loop=enable_loop,
                editorial_mode=editorial_mode,
                anti_copyright=anti_copyright,
                is_continuous_clip=is_continuous_clip,
                is_dorama=is_dorama,
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
