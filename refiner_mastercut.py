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
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _get_ffmpeg_bin(cmd: str = "ffmpeg") -> str:
    """Return path to ffmpeg or ffprobe executable."""
    import shutil
    found = shutil.which(cmd)
    if found:
        return found
    base_dir = Path(__file__).parent.resolve()
    cmd_exe = f"{cmd}.exe" if sys.platform.startswith("win") else cmd
    local_bin = base_dir / cmd_exe
    if local_bin.exists():
        return str(local_bin)
    for p in base_dir.glob(f"**/{cmd_exe}"):
        if p.exists():
            return str(p.resolve())
    return cmd


def _run_ffmpeg_with_nvenc_fallback(cmd: list, timeout: int = 600, on_log=None) -> subprocess.CompletedProcess:
    """
    Run FFmpeg command with h264_nvenc hardware acceleration first.
    If nvenc fails, automatically fall back to CPU libx264.
    """
    cmd_str = " ".join(str(c) for c in cmd)
    if on_log:
        on_log(f"[FFmpeg] Executando: {cmd_str[:120]}...")

    result = None
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        if on_log:
            on_log(f"[FFmpeg] Exceção na tentativa NVENC: {e}")
        result = None

    if result is None or result.returncode != 0:
        has_nvenc = any(str(c) == "h264_nvenc" for c in cmd)
        if has_nvenc:
            if on_log:
                on_log("⚠️ h264_nvenc indisponível ou falhou. Tentando fallback transparente para libx264 (CPU)...")
            fallback_cmd = []
            i = 0
            has_pix_fmt = False
            while i < len(cmd):
                if str(cmd[i]) == "-c:v" and i + 1 < len(cmd) and str(cmd[i+1]) == "h264_nvenc":
                    fallback_cmd.extend(["-c:v", "libx264"])
                    i += 2
                elif str(cmd[i]) == "-preset" and i + 1 < len(cmd) and str(cmd[i+1]) == "p4":
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

            result = subprocess.run(fallback_cmd, capture_output=True, text=True, timeout=timeout)
            if result.returncode == 0 and on_log:
                on_log("✓ Sucesso com fallback libx264 (CPU)!")
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
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
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
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return "audio" in res.stdout.lower()
    except Exception:
        return False


# ─── Speech & Action Recognition ─────────────────────────────────────────────

def detect_speech_segments(video_path: str, on_progress=None, on_log=None):
    """
    Extracts 16kHz mono audio and runs faster_whisper to get word-level timestamps.
    Returns: (all_words, full_text, duration)
    """
    ffmpeg_bin = _get_ffmpeg_bin("ffmpeg")
    real_duration = get_video_duration(video_path)

    if on_log:
        on_log(f"🎙️ Extraindo áudio de alta precisão (16kHz mono)... [Duração: {real_duration:.1f}s]")
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
        subprocess.run(cmd_audio, capture_output=True, timeout=120)

        if on_log:
            on_log("🧠 Analisando falas com Faster-Whisper (CUDA / CPU)...")
        if on_progress:
            on_progress(0.25, "Transcrevendo falas e diálogos com Whisper...")

        from faster_whisper import WhisperModel
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
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
            on_log(f"✓ Whisper concluiu: {len(all_words)} palavras mapeadas em {duration:.1f}s.")
        if on_progress:
            on_progress(0.40, f"Transcrição concluída: {len(all_words)} palavras mapeadas.")

        return all_words, " ".join(full_text_parts), duration

    except Exception as err:
        if on_log:
            on_log(f"⚠️ Erro ao transcrever com Whisper: {err}")
        return [], "", real_duration
    finally:
        if os.path.exists(temp_wav_path):
            try:
                os.remove(temp_wav_path)
            except Exception:
                pass


def detect_visual_action_blocks(video_path: str, on_log=None):
    """Detect intervals with high density of visual camera cuts (action/battle sequences)."""
    try:
        ffmpeg_bin = _get_ffmpeg_bin("ffmpeg")
        cmd = [
            ffmpeg_bin, "-ss", "0", "-i", str(video_path),
            "-vf", "fps=3,select='gt(scene,0.20)',showinfo",
            "-f", "null", "-"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
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
            on_log(f"✓ Mapeadas {len(action_blocks)} sequências de corte/ação visual.")
        return action_blocks
    except Exception as e:
        if on_log:
            on_log(f"Aviso detecção visual: {e}")
        return []


# ─── Mastercut AI Selection ───────────────────────────────────────────────────

def _get_api_keys() -> list:
    """Read Gemini API keys from environment or .env."""
    raw = os.getenv("GEMINI_API_KEY", "").strip()
    if not raw or raw == "sua_chave_aqui":
        return []
    keys = [k.strip() for k in raw.replace(";", ",").split(",") if k.strip() and k.strip() != "sua_chave_aqui"]
    return keys


def group_words_by_speech_gaps(all_words: list, max_gap: float = 0.35) -> list:
    """
    Groups individual words into coherent speech phrases, breaking whenever
    silence between consecutive words exceeds max_gap seconds.
    """
    if not all_words:
        return []

    groups = []
    curr_start = all_words[0]["start"]
    curr_end = all_words[0]["end"]
    curr_text = [all_words[0]["text"]]

    for i in range(1, len(all_words)):
        w = all_words[i]
        prev_w = all_words[i - 1]
        gap = w["start"] - prev_w["end"]
        if gap <= max_gap:
            curr_end = w["end"]
            curr_text.append(w["text"])
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
            curr_text = [w["text"]]

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


def calculate_mastercut_bounds(
    video_duration: float,
    refine_mode: str = "balanced",
    target_duration_mode: str = "auto"
) -> tuple:
    """
    Calculates the (min_duration, max_duration) bounds for Mastercut.
    Prevents aggressive over-cutting (e.g. turning a 60s clip into 19s).
    """
    v_dur = max(5.0, float(video_duration))

    # User explicit duration presets
    if target_duration_mode == "max_retention":
        min_d = max(18.0, v_dur * 0.78)
        max_d = min(v_dur, max(min_d + 3.0, v_dur * 0.95))
        return round(min_d, 1), round(max_d, 1)
    elif target_duration_mode == "standard":
        min_d = min(38.0, v_dur * 0.62)
        max_d = min(v_dur, 60.0)
        return round(max(20.0, min_d), 1), round(max_d, 1)
    elif target_duration_mode == "short":
        min_d = min(25.0, v_dur * 0.40)
        max_d = min(v_dur, 40.0)
        return round(max(15.0, min_d), 1), round(max_d, 1)

    # Automatic mode based on refine_mode & video_duration
    if v_dur <= 75.0:
        # Short video (e.g. 50s-75s from Director AI or user clip)
        if refine_mode == "soft":
            # Soft: Keep almost everything (75% to 92%), cut only silence
            min_d = v_dur * 0.75
            max_d = min(v_dur, v_dur * 0.92)
        elif refine_mode == "aggressive":
            # Aggressive: 35% to 58%
            min_d = max(18.0, v_dur * 0.35)
            max_d = min(v_dur, v_dur * 0.58)
        else:
            # Balanced (default): 60% to 82% (for 60s -> ~38s to 50s - NEVER 19s!)
            min_d = max(28.0, v_dur * 0.62)
            max_d = min(v_dur, max(min_d + 6.0, v_dur * 0.82))
    elif v_dur <= 180.0:
        # Medium clip (1.5m to 3m)
        if refine_mode == "soft":
            min_d = max(55.0, v_dur * 0.60)
            max_d = min(v_dur, 95.0)
        elif refine_mode == "aggressive":
            min_d = 28.0
            max_d = 45.0
        else: # balanced
            min_d = 40.0
            max_d = 65.0
    else:
        # Long video (> 3m, arcos narrativos ou episódios)
        if refine_mode == "soft":
            min_d = 65.0
            max_d = 120.0
        elif refine_mode == "aggressive":
            min_d = 30.0
            max_d = 48.0
        else: # balanced
            min_d = 45.0
            max_d = 70.0

    return round(min_d, 1), round(max_d, 1)


def call_ai_mastercut_timeline(
    all_words,
    video_duration,
    action_blocks=None,
    video_context="",
    refine_mode="balanced",
    target_duration_mode="auto",
    on_log=None
):
    """
    Sends the video dialogue transcription to Gemini AI (or Groq fallback)
    requesting the Mastercut timeline with strict anti-overcut rules and duration boundaries.
    """
    action_blocks = action_blocks or []
    min_dur, max_dur = calculate_mastercut_bounds(video_duration, refine_mode, target_duration_mode)

    # Build grouped dialogue sentences
    speech_summary = []
    if all_words:
        curr_phrase = []
        p_start = all_words[0]["start"]
        for w in all_words:
            curr_phrase.append(w["text"])
            if w["text"].endswith(('.', '!', '?', '…', ',')) or (w["end"] - p_start > 3.5):
                p_text = " ".join(curr_phrase)
                speech_summary.append(f"[{p_start:.2f}s -> {w['end']:.2f}s] \"{p_text}\"")
                curr_phrase = []
                p_start = w["end"]
        if curr_phrase:
            p_text = " ".join(curr_phrase)
            speech_summary.append(f"[{p_start:.2f}s -> {all_words[-1]['end']:.2f}s] \"{p_text}\"")

    action_summary = []
    for ab in action_blocks:
        action_summary.append(f"[{ab['start']:.2f}s -> {ab['end']:.2f}s] (Cena de Luta/Ação)")

    ctx_block = ""
    if video_context and video_context.strip():
        extra_meta = ""
        try:
            from metadata_enricher import get_enriched_context_for_prompt
            extra_meta = get_enriched_context_for_prompt(video_context.strip(), on_log=on_log)
        except Exception:
            pass

        ctx_block = f"""
[CONTEXTO DA OBRA / ANIME / EPISÓDIO]
Contexto informado: {video_context.strip()}
{extra_meta}
Use esse conhecimento de anime/série para identificar com precisão os personagens falando, técnicas/poderes, o arco narrativo e as falas/reações mais marcantes desta cena!
"""
        if on_log:
            on_log(f"🏷️ Contexto aplicado à IA: '{video_context.strip()}'")

    mode_descriptions = {
        "soft": "PRESERVAÇÃO MÁXIMA DE CONTEÚDO (Anti-Silêncio). Mantenha praticamente todas as falas, conversas e reações. Elimine estritamente pausas mortas (>0.35s) e silêncios.",
        "balanced": "EQUILIBRADO / RITMO DINÂMICO (Padrão). Elimine pausas mortas e partes mornas, mas MANTENHA as falas completas, réplicas entre personagens e momentos importantes. Não corte em excesso!",
        "aggressive": "AGRESSIVO / O SUCO PURO. Condensa para extrair apenas o clímax absoluto e momentos mais eletrizantes.",
    }
    mode_guide = mode_descriptions.get(refine_mode, mode_descriptions["balanced"])

    prompt = f"""Você é o EDITOR CHEFE SUPREMO DE CINEMA E CONTEÚDO VIRAL.
Seu objetivo é criar o **MASTERCUT CONCENTRADO ("O SUCO DO VÍDEO")** deste vídeo.
{ctx_block}
DADOS DO VÍDEO BRUTO:
- Duração Original: {video_duration:.1f} segundos (analise de 0.0s até {video_duration:.1f}s)
- Diálogos Transcritos Completos:
{chr(10).join(speech_summary) if speech_summary else "[Sem falas detectadas - use cortes visuais]"}
- Cenas de Ação/Luta Mapeadas:
{chr(10).join(action_summary) if action_summary else "[Nenhuma cena de ação isolada]"}

🎯 DIRETRIZ ESTRITA DE DURAÇÃO FINAL:
- Duração do Vídeo Original: {video_duration:.1f} segundos.
- Modo de Refino Selecionado: {mode_guide}
- DURAÇÃO TOTAL OBRIGATÓRIA DA SOMA DOS SEGMENTOS: entre {min_dur:.1f}s e {max_dur:.1f}s.

⛔ REGRAS CRÍTICAS ANTI-MUTILAÇÃO / ANTI-CORTE EXCESSIVO:
1. **PISO MÍNIMO INVIOLÁVEL**: É TERMINANTEMENTE PROIBIDO retornar um tempo total inferior a {min_dur:.1f}s!
   Se o vídeo original tem {video_duration:.1f}s, você NUNCA deve gerar apenas 15s, 19s ou 25s jogando fora momentos cruciais.
2. **COMO REFINAR SEM PERDER O SENTIDO**:
   - Um bom Mastercut acelera o ritmo CORTANDO SILÊNCIOS MORTOS (>0.35s entre falas) e andanças vazias.
   - NÃO corte diálogos no meio, não tire réplicas entre personagens e não descarte reações épicas.
   - Mantenha a narrativa coesa, com início/gancho, conflito/desenvolvimento e clímax.
3. **DIVISÃO DINÂMICA**: Divida a timeline em múltiplos cortes cirúrgicos (3 a 7 segmentos) que juntos preencham a duração entre {min_dur:.1f}s e {max_dur:.1f}s.

Retorne EXCLUSIVAMENTE um objeto JSON no seguinte formato (sem comentários, apenas JSON puro):
{{
  "ai_viral": [
    {{"start": 1.50, "end": 14.80, "text": "Abertura com diálogo de impacto e gancho"}},
    {{"start": 16.20, "end": 28.50, "text": "Desenvolvimento do conflito e réplicas de falas"}},
    {{"start": 30.10, "end": 42.40, "text": "Clímax da cena com impacto dramático e ação"}},
    {{"start": 44.00, "end": 54.50, "text": "Desfecho épico e reação final dos personagens"}}
  ]
}}
"""

    keys = _get_api_keys()
    if not keys:
        if on_log:
            on_log("ℹ️ Nenhuma chave Gemini configurada no .env. Usando inteligência heurística local para o Mastercut...")
        return None

    # Try Gemini models
    models_to_try = [
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-2.5-flash-lite",
    ]

    from google import genai
    for key in keys:
        try:
            client = genai.Client(api_key=key)
        except Exception:
            continue

        for model_name in models_to_try:
            try:
                if on_log:
                    on_log(f"🧠 Consultando IA ({model_name}) para selecionar os melhores momentos do Mastercut...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config={"response_mime_type": "application/json"}
                )
                text = response.text
                if text:
                    data = json.loads(text)
                    if isinstance(data, dict):
                        timeline = data.get("ai_viral", data.get("mastercut", []))
                        if timeline and isinstance(timeline, list) and len(timeline) > 0:
                            if on_log:
                                on_log(f"✓ IA ({model_name}) desenhou Mastercut com {len(timeline)} cortes estratégicos!")
                            return timeline
            except Exception as e:
                err_s = str(e)
                if "429" in err_s or "RESOURCE_EXHAUSTED" in err_s:
                    continue
                if "404" in err_s or "NOT_FOUND" in err_s:
                    continue
                if on_log:
                    on_log(f"Aviso modelo {model_name}: {e}")

    # Fallback to Groq if configured
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        try:
            import requests
            if on_log:
                on_log("🔄 Tentando modelo de fallback Groq (qwen/llama)...")
            headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt + "\nResponda em formato JSON."}],
                "temperature": 0.2,
                "response_format": {"type": "json_object"}
            }
            resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=60)
            if resp.status_code == 200:
                content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                data = json.loads(content)
                timeline = data.get("ai_viral", data.get("mastercut", []))
                if timeline:
                    if on_log:
                        on_log(f"✓ Sucesso via Groq Fallback! {len(timeline)} cortes encontrados.")
                    return timeline
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
    on_log=None
):
    """
    Local heuristic fallback when no LLM is available or connected.
    Finds dialogue segments with minimum silence (>0.35s cut), prioritizing natural speech continuity.
    """
    if on_log:
        on_log("⚡ Construindo Mastercut inteligente via algoritmo de densidade de diálogo e corte de silêncio...")

    if not all_words:
        # Video with no speech detected: divide into 3-4 visual segments
        seg_len = min(15.0, max(8.0, min_dur / 3.0))
        return [
            {"start": round(video_duration * 0.05, 3), "end": round(video_duration * 0.05 + seg_len, 3), "text": "[Abertura Visual]"},
            {"start": round(video_duration * 0.45, 3), "end": round(video_duration * 0.45 + seg_len, 3), "text": "[Desenvolvimento Central]"},
            {"start": round(max(0, video_duration - seg_len - 1.0), 3), "end": round(video_duration - 1.0, 3), "text": "[Clímax Final]"},
        ]

    groups = group_words_by_speech_gaps(all_words, max_gap=0.35)
    if not groups:
        return []

    # If short video or soft mode, preserve all valid speech groups!
    total_speech_dur = sum(g["duration"] for g in groups)

    if total_speech_dur <= max_dur:
        # Keep all speech groups chronologically
        picked = sorted(groups, key=lambda x: x["start"])
    else:
        # Need to trim less dense groups to fit max_dur
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

    return [{"start": g["start"], "end": g["end"], "text": g["text"]} for g in picked]


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
    this intelligently restores adjacent dialogue and missing key scenes until min_dur is reached,
    preventing mutilation of important moments while keeping dead silences cut.
    """
    if not refined:
        return refined

    total_cur = sum(s["end"] - s["start"] for s in refined)
    if total_cur >= min_dur:
        return refined

    dur_before = total_cur
    if on_log:
        on_log(f"⚠️ Atenção: Corte inicial somou apenas {dur_before:.1f}s (abaixo do piso de {min_dur:.1f}s).")
        on_log(f"🛡️ Proteção Anti-Corte ativada: restaurando diálogos e momentos importantes...")

    groups = group_words_by_speech_gaps(all_words, max_gap=0.40) if all_words else []
    refined = sorted(refined, key=lambda x: x["start"])

    # Phase 1: Expand existing segments to include closely adjacent speech (< 1.5s gap)
    expanded = []
    for seg in refined:
        s_t = seg["start"]
        e_t = seg["end"]

        for g in groups:
            # Group ends right before segment start
            if 0 < (s_t - g["end"]) < 1.5:
                s_t = min(s_t, g["start"])
            # Group starts right after segment end
            if 0 < (g["start"] - e_t) < 1.5:
                e_t = max(e_t, g["end"])

        expanded.append({
            "start": round(max(0.0, s_t), 3),
            "end": round(min(video_duration, e_t), 3),
            "text": seg.get("text", "")
        })

    expanded = _merge_segments(expanded)
    total_cur = sum(s["end"] - s["start"] for s in expanded)

    # Phase 2: If still under min_dur, bring in missing speech groups that don't overlap
    if total_cur < min_dur and groups:
        for g in groups:
            overlap = False
            for s in expanded:
                if not (g["end"] <= s["start"] or g["start"] >= s["end"]):
                    overlap = True
                    break
            if not overlap:
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

        expanded = _merge_segments(expanded)
        total_cur = sum(s["end"] - s["start"] for s in expanded)

    # Phase 3: If STILL under min_dur (e.g. video has very little speech), pad segment boundaries
    if total_cur < min_dur and len(expanded) > 0:
        needed = min_dur - total_cur
        per_seg_add = needed / len(expanded)
        final_list = []
        for s in expanded:
            pad = per_seg_add / 2.0
            new_s = max(0.0, s["start"] - pad)
            new_e = min(video_duration, s["end"] + pad)
            final_list.append({
                "start": round(new_s, 3),
                "end": round(new_e, 3),
                "text": s.get("text", "")
            })
        expanded = _merge_segments(final_list)
        total_cur = sum(s["end"] - s["start"] for s in expanded)

    if on_log:
        on_log(f"✓ Proteção concluída: {dur_before:.1f}s ➔ {total_cur:.1f}s (momentos essenciais preservados com fluidez)!")

    return expanded


def build_refined_segments(
    all_words,
    video_duration,
    action_blocks=None,
    video_context="",
    refine_mode="balanced",
    target_duration_mode="auto",
    on_log=None
):
    """
    Executes AI Mastercut selection with smart audio padding (-80ms, +250ms),
    merging overlaps and applying anti-overcut protection to prevent mutilation.
    """
    min_dur, max_dur = calculate_mastercut_bounds(video_duration, refine_mode, target_duration_mode)
    if on_log:
        on_log(f"🎯 Meta de duração do Mastercut: {min_dur:.1f}s a {max_dur:.1f}s (Modo: {refine_mode})")

    timeline = call_ai_mastercut_timeline(
        all_words,
        video_duration,
        action_blocks,
        video_context=video_context,
        refine_mode=refine_mode,
        target_duration_mode=target_duration_mode,
        on_log=on_log
    )

    if not timeline or len(timeline) < 2:
        timeline = build_heuristic_mastercut(
            all_words,
            video_duration,
            min_dur=min_dur,
            max_dur=max_dur,
            refine_mode=refine_mode,
            on_log=on_log
        )

    refined = []
    for chunk in timeline:
        if not isinstance(chunk, dict):
            continue
        s_t = float(chunk.get("start", 0))
        e_t = float(chunk.get("end", 0))

        # Smart Padding: -80ms start (natural breath), +250ms end (preserves word ending)
        s_t = max(0.0, s_t - 0.080)
        e_t = min(video_duration, e_t + 0.250)
        s_t_r = round(s_t, 3)
        e_t_r = round(e_t, 3)

        if e_t_r > s_t_r and s_t_r < video_duration:
            refined.append({
                "start": s_t_r,
                "end": e_t_r,
                "text": chunk.get("text", "[Corte Mastercut]")
            })

    # Merge overlapping segments
    refined = _merge_segments(refined)

    # Apply Anti-Overcut Protection (prevents 60s -> 19s mutilation)
    refined = protect_against_overcutting(
        refined=refined,
        all_words=all_words,
        video_duration=video_duration,
        min_dur=min_dur,
        max_dur=max_dur,
        on_log=on_log
    )

    # Enforce upper bound (max_dur + 2s tolerance)
    total_dur = sum(s["end"] - s["start"] for s in refined)
    if total_dur > max_dur + 2.0:
        trimmed = []
        t_acc = 0.0
        for s in refined:
            seg_d = s["end"] - s["start"]
            if t_acc + seg_d <= max_dur:
                trimmed.append(s)
                t_acc += seg_d
            else:
                remaining = max_dur - t_acc
                if remaining >= 3.0:
                    trimmed.append({"start": s["start"], "end": round(s["start"] + remaining, 3), "text": s.get("text", "")})
                break
        if trimmed:
            refined = trimmed

    return refined


# ─── FFmpeg Video Assembly ────────────────────────────────────────────────────

def render_mastercut_video(
    source_path: str,
    segments: list,
    output_path: str,
    vocal_isolation: bool = True,
    anti_copyright: bool = False,
    on_progress=None,
    on_log=None
) -> dict:
    """
    Concatenates the Mastercut segments using FFmpeg filter_complex with NVENC acceleration.
    Returns stats dict on completion.
    """
    if not segments:
        raise ValueError("Nenhum segmento fornecido para montagem do Mastercut.")

    ffmpeg_bin = _get_ffmpeg_bin("ffmpeg")
    has_audio = check_video_has_audio(source_path)
    video_duration = get_video_duration(source_path)

    # Detect resolution
    video_width, video_height = 1920, 1080
    try:
        ffprobe_bin = _get_ffmpeg_bin("ffprobe")
        probe_res = subprocess.run(
            [ffprobe_bin, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(source_path)],
            capture_output=True, text=True, timeout=10
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
    concat_v_inputs = []
    concat_a_inputs = []

    for i, seg in enumerate(segments):
        s = seg["start"]
        e = seg["end"]
        filter_complex.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}]")
        concat_v_inputs.append(f"[v{i}]")
        if has_audio:
            filter_complex.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}]")
            concat_a_inputs.append(f"[a{i}]")

    video_post_filters = ""
    audio_post_filters = ",aformat=channel_layouts=stereo"

    if anti_copyright:
        scaled_w = int(video_width * 1.05)
        scaled_h = int(video_height * 1.05)
        scaled_w -= (scaled_w % 2)
        scaled_h -= (scaled_h % 2)
        video_post_filters = f",setpts=PTS/1.05,hflip,eq=contrast=1.04:saturation=1.03:gamma=1.01,scale=w={scaled_w}:h={scaled_h},crop={video_width}:{video_height}"
        audio_post_filters += ",atempo=1.05"

    if vocal_isolation:
        audio_post_filters += ",highpass=f=80,lowpass=f=7500,afftdn=nr=14:nf=-25"

    curr_v_stream = "raw_v"
    if has_audio:
        filter_complex.append(f"{''.join(concat_v_inputs)}concat=n={n}:v=1:a=0[raw_v]")
        filter_complex.append(f"{''.join(concat_a_inputs)}concat=n={n}:v=0:a=1[raw_a]")
        filter_complex.append(f"[{curr_v_stream}]null{video_post_filters}[outv]")
        filter_complex.append(f"[raw_a]anull{audio_post_filters}[outa]")
        filter_str = ";\n".join(filter_complex)

        cmd = [
            ffmpeg_bin, "-y", "-i", str(source_path),
            "-filter_complex", filter_str,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(output_path)
        ]
    else:
        filter_complex.append(f"{''.join(concat_v_inputs)}concat=n={n}:v=1:a=0[raw_v]")
        filter_complex.append(f"[{curr_v_stream}]null{video_post_filters}[outv]")
        filter_str = ";\n".join(filter_complex)

        cmd = [
            ffmpeg_bin, "-y", "-i", str(source_path),
            "-filter_complex", filter_str,
            "-map", "[outv]",
            "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "18",
            "-an", "-movflags", "+faststart",
            str(output_path)
        ]

    if on_log:
        on_log(f"🎬 Renderizando Mastercut com {n} cortes selecionados...")
    if on_progress:
        on_progress(0.70, f"Renderizando Mastercut com {n} cortes via FFmpeg...")

    res = _run_ffmpeg_with_nvenc_fallback(cmd, timeout=600, on_log=on_log)

    out_file = Path(output_path)
    if res.returncode != 0 or not out_file.exists() or out_file.stat().st_size == 0:
        err_msg = res.stderr[-400:] if res and res.stderr else "Erro desconhecido"
        raise RuntimeError(f"FFmpeg falhou ao renderizar Mastercut: {err_msg}")

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
        "segments": segments
    }

    if on_log:
        on_log(f"✅ Mastercut concluído! {video_duration:.1f}s ➔ {final_dur:.1f}s ({time_saved_pct}% tempo economizado)")
    if on_progress:
        on_progress(1.0, "Mastercut gerado com sucesso!")

    return stats


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
        anti_copyright: bool = False,
        refine_mode: str = "balanced",
        target_duration_mode: str = "auto",
        on_progress=None,
        on_log=None
    ) -> dict:
        self.is_running = True
        self._cancelled = False

        try:
            # Step 1: Detect speech & words
            if on_log:
                on_log("═══ ETAPA 1/3: Mapeamento de Diálogos (Whisper) ═══")
            all_words, full_text, duration = detect_speech_segments(video_path, on_progress=on_progress, on_log=on_log)

            if self._cancelled:
                raise InterruptedError("Operação cancelada pelo usuário.")

            # Step 2: Detect visual action
            action_blocks = detect_visual_action_blocks(video_path, on_log=on_log)

            if self._cancelled:
                raise InterruptedError("Operação cancelada pelo usuário.")

            # Step 3: AI Selection (Opção 4: Mastercut Concentrado)
            if on_log:
                on_log("═══ ETAPA 2/3: Seleção Mastercut Concentrado (IA) ═══")
            if on_progress:
                on_progress(0.50, "IA refinando corte sem mutilação de diálogos e momentos...")

            segments = build_refined_segments(
                all_words=all_words,
                video_duration=duration,
                action_blocks=action_blocks,
                video_context=video_context,
                refine_mode=refine_mode,
                target_duration_mode=target_duration_mode,
                on_log=on_log
            )

            if self._cancelled:
                raise InterruptedError("Operação cancelada pelo usuário.")

            if not segments:
                raise ValueError("Não foi possível identificar segmentos válidos para o Mastercut.")

            # Step 4: Video Assembly
            if on_log:
                on_log("═══ ETAPA 3/3: Renderização e Concatenação FFmpeg ═══")
            stats = render_mastercut_video(
                source_path=video_path,
                segments=segments,
                output_path=output_path,
                vocal_isolation=vocal_isolation,
                anti_copyright=anti_copyright,
                on_progress=on_progress,
                on_log=on_log
            )

            return stats

        finally:
            self.is_running = False
