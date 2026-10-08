"""
Director AI - Core Intelligence Module
Analyzes long episodes/videos using AI, Whisper transcription, and anime/series lore grounding.
Identifies Top 3 viral moments or Smart Cortes (unbiased curation) with exact timestamps.
"""

import os
import sys
import json
import time
import re
import tempfile
import subprocess
from pathlib import Path
from typing import Callable, Optional, Dict, Any, List

import requests
from dotenv import load_dotenv

load_dotenv()


def _get_gemini_keys() -> List[str]:
    """Retrieve, deduplicate and prioritize Gemini API keys from .env."""
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)
    raw = os.getenv("GEMINI_API_KEY", "")
    if not raw:
        return []
    seen = set()
    keys = []
    for part in raw.replace(";", "\n").replace(",", "\n").splitlines():
        clean_k = part.strip().strip('"\'')
        if clean_k and "sua_chave" not in clean_k.lower() and clean_k not in seen:
            seen.add(clean_k)
            keys.append(clean_k)
    # Prioritize keys starting with AIzaSy (official Google AI Studio keys)
    keys.sort(key=lambda k: 0 if k.startswith("AIzaSy") else 1)
    return keys


def _get_api_key(name: str) -> str:
    """Get clean API key from environment."""
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)
    raw = os.getenv(name, "")
    if not raw or "sua_chave" in raw:
        return ""
    # Support comma, semicolon, or newline-separated multiple keys, take first valid line
    for part in raw.replace(";", "\n").replace(",", "\n").splitlines():
        clean_k = part.strip().strip('"\'')
        if clean_k and "sua_chave" not in clean_k.lower():
            # If requesting GROQ key, ignore if user accidentally pasted a Gemini key
            if name == "GROQ_API_KEY" and (clean_k.startswith("AQ.") or clean_k.startswith("AIzaSy")):
                continue
            return clean_k
    return ""


def _time_str_to_seconds(t_str: Any) -> float:
    """Convert MM:SS, HH:MM:SS, seconds or ranges to float seconds safely."""
    if t_str is None:
        return 0.0
    if isinstance(t_str, (int, float)):
        return float(t_str)
    raw = str(t_str).strip().strip('"\'')
    if not raw:
        return 0.0
    # Handle ranges like "04:15 -> 06:30", "04:15 - 06:30", "04:15 – 06:30"
    if "->" in raw or " - " in raw or "–" in raw:
        raw = re.split(r"->| - |–", raw)[0].strip()

    parts = raw.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        return float(re.sub(r"[^\d.]", "", raw) or 0.0)
    except Exception:
        return 0.0


def ranges_overlap(r1_start: float, r1_end: float, r2_start: float, r2_end: float, tolerance: float = 30.0) -> bool:
    """
    Returns True if two time ranges overlap by more than `tolerance` seconds.
    Used to detect duplicate cuts even when timestamps differ slightly.
    """
    overlap_start = max(r1_start, r2_start)
    overlap_end = min(r1_end, r2_end)
    return (overlap_end - overlap_start) > tolerance


def parse_duration_str(dur_val: Any) -> float:
    """Parse text durations like '3 min', '3m', '3m 00s', '180s', '03:00' to seconds."""
    if dur_val is None:
        return 0.0
    if isinstance(dur_val, (int, float)):
        return float(dur_val)
    s = str(dur_val).lower().strip().strip('"\'')
    if not s:
        return 0.0
    m_h = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hora|horas)", s)
    m_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|min|minuto|minutos)", s)
    m_s = re.search(r"(\d+(?:\.\d+)?)\s*(?:s|seg|segundo|segundos)", s)
    total = 0.0
    if m_h:
        total += float(m_h.group(1)) * 3600
    if m_m:
        total += float(m_m.group(1)) * 60
    if m_s:
        total += float(m_s.group(1))
    if total > 0:
        return total
    if ":" in s:
        return _time_str_to_seconds(s)
    try:
        return float(re.sub(r"[^\d.]", "", s) or 0.0)
    except Exception:
        return 0.0


def _seconds_to_time_str(secs: float) -> str:
    """Convert seconds to MM:SS or HH:MM:SS."""
    secs = max(0.0, secs)
    total_secs = int(round(secs))
    m, s = divmod(total_secs, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def parse_candidate_times(cand: dict, max_duration: float = 0.0) -> tuple[float, float, str, str, str]:
    """
    Safely extract timestamps and duration from candidate dict.
    Handles 'estimated_range' (e.g. '04:15 -> 07:15'), 'start_time', 'end_time', and text 'duration'.
    Clamps bounds to max_duration if provided.
    Returns: (start_sec, dur_sec, start_str, end_str, dur_str)
    """
    start_sec = None
    end_sec = None

    # 1. Check range fields first (e.g. estimated_range = "04:15 -> 07:15")
    for field in ["estimated_range", "time_range", "range", "timestamps"]:
        val = cand.get(field)
        if val and isinstance(val, str) and ("->" in val or " - " in val or "–" in val or " a " in val):
            parts = re.split(r"->| - |–| a ", val)
            if len(parts) >= 2:
                start_sec = _time_str_to_seconds(parts[0].strip())
                end_sec = _time_str_to_seconds(parts[1].strip())
                break

    # 2. Check if start_time itself contains a range
    raw_start = cand.get("start_time")
    if start_sec is None and isinstance(raw_start, str) and ("->" in raw_start or " - " in raw_start or "–" in raw_start):
        parts = re.split(r"->| - |–", raw_start)
        if len(parts) >= 2:
            start_sec = _time_str_to_seconds(parts[0].strip())
            end_sec = _time_str_to_seconds(parts[1].strip())

    # 3. Check individual fields
    if start_sec is None:
        start_sec = max(0.0, _time_str_to_seconds(cand.get("start_time")))
    if end_sec is None:
        raw_end = cand.get("end_time")
        end_sec = _time_str_to_seconds(raw_end) if raw_end is not None else 0.0

    # 4. Resolve duration accurately
    dur_sec = end_sec - start_sec if end_sec > start_sec else 0.0
    if dur_sec <= 0.0:
        parsed_dur = parse_duration_str(cand.get("duration"))
        if parsed_dur >= 5.0:
            dur_sec = parsed_dur
            end_sec = start_sec + dur_sec
        else:
            dur_sec = 60.0
            end_sec = start_sec + 60.0

    # 5. Clamp to max_duration if provided
    if max_duration > 0.0:
        if start_sec >= max_duration:
            start_sec = max(0.0, max_duration - dur_sec)
        if end_sec > max_duration:
            end_sec = max_duration
        dur_sec = max(1.0, end_sec - start_sec)

    start_str = _seconds_to_time_str(start_sec)
    end_str = _seconds_to_time_str(end_sec)
    dur_str = f"{int(dur_sec // 60)}m {int(dur_sec % 60):02d}s" if dur_sec >= 60 else f"{int(dur_sec)}s"
    return start_sec, dur_sec, start_str, end_str, dur_str


def extract_audio(video_path: str, ffmpeg_bin: str = "ffmpeg") -> str:
    """Extract 16kHz mono mp3 audio from video for fast transcription."""
    tmp_audio = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp_audio_path = tmp_audio.name
    tmp_audio.close()

    cmd = [
        ffmpeg_bin, "-i", video_path,
        "-vn", "-ar", "16000", "-ac", "1",
        "-ab", "64k", "-f", "mp3",
        tmp_audio_path, "-y"
    ]
    res = subprocess.run(
        cmd, capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    )
    if res.returncode != 0 or not os.path.exists(tmp_audio_path):
        raise RuntimeError("Falha ao extrair áudio do vídeo com FFmpeg.")
    return tmp_audio_path


def transcribe_audio_groq(audio_path: str, groq_key: str, on_log: Optional[Callable[[str], None]] = None) -> str:
    """Transcribe audio using Groq Whisper API (whisper-large-v3). Super fast (1-3s)."""
    if on_log:
        on_log("[WHISPER] Transcrevendo áudio com Whisper Large v3 (Groq)...")

    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {groq_key}"}

    file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    # Groq max file size is 25MB. 64k mp3 is ~0.48MB per minute (20 min = ~9.6MB).
    if file_size_mb > 24:
        raise ValueError(f"Áudio ({file_size_mb:.1f}MB) excede o limite de 25MB para o Groq.")

    with open(audio_path, "rb") as f:
        files = {"file": (os.path.basename(audio_path), f, "audio/mpeg")}
        data = {
            "model": "whisper-large-v3-turbo",
            "response_format": "verbose_json",
            "temperature": "0.0",
        }
        resp = requests.post(url, headers=headers, files=files, data=data, timeout=120)

    if resp.status_code != 200:
        raise RuntimeError(f"Erro no Groq Whisper ({resp.status_code}): {resp.text[:200]}")

    result = resp.json()
    segments = result.get("segments", [])
    if not segments:
        return result.get("text", "")

    lines = []
    for s in segments:
        start_str = _seconds_to_time_str(s.get("start", 0))
        end_str = _seconds_to_time_str(s.get("end", 0))
        text = s.get("text", "").strip()
        if text:
            lines.append(f"[{start_str} -> {end_str}] {text}")

    return "\n".join(lines)


def transcribe_audio_local(audio_path: str, on_log: Optional[Callable[[str], None]] = None) -> str:
    """Fallback local transcription with faster-whisper (CTranslate2, works without PyTorch)."""
    if on_log:
        on_log("[WHISPER] Transcrevendo com faster-whisper local (GPU/CPU)...")

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

    model = WhisperModel("base", device=device, compute_type=compute_type)
    segments, _ = model.transcribe(audio_path, beam_size=2)

    lines = []
    for s in segments:
        start_str = _seconds_to_time_str(s.start)
        end_str = _seconds_to_time_str(s.end)
        text = s.text.strip()
        if text:
            lines.append(f"[{start_str} -> {end_str}] {text}")

    return "\n".join(lines)


def transcribe_video_audio(audio_path: str, on_log: Optional[Callable[[str], None]] = None) -> str:
    """Smart transcriber: Groq Whisper API first, falls back to faster-whisper."""
    groq_key = _get_api_key("GROQ_API_KEY")
    if groq_key and groq_key.startswith("gsk_"):
        try:
            return transcribe_audio_groq(audio_path, groq_key, on_log)
        except Exception as e:
            if on_log:
                on_log(f"[AVISO] Groq Whisper falhou ({e}). Tentando transcrição local...")

    # Fallback local
    try:
        return transcribe_audio_local(audio_path, on_log)
    except Exception as e:
        if on_log:
            on_log(f"[AVISO] faster-whisper local falhou: {e}")
        return ""


def _safe_log(logger: Optional[Callable[[str], None]], msg: str) -> None:
    """Safely forward log message without failing on Windows console encoding."""
    if not logger:
        return
    try:
        logger(msg)
    except UnicodeEncodeError:
        try:
            clean_msg = msg.encode("ascii", errors="replace").decode("ascii")
            logger(clean_msg)
        except Exception:
            pass
    except Exception:
        pass


# Module-level rotation state and cooldown tracker
_current_gemini_key_idx: int = 0
_gemini_key_cooldowns: Dict[str, float] = {}


def call_ai_text(
    prompt: str,
    on_log: Optional[Callable[[str], None]] = None,
    log_cb: Optional[Callable[[str], None]] = None,
    max_tokens: Optional[int] = None,
    **kwargs
) -> str:
    """
    Call AI with resilient round-robin multi-key rotation and multi-tier fallbacks:
    Tier 1: Gemini REST API (Round-robin across all unique keys in .env, with 90s cooldown on 429/503)
            Models tried per key: gemini-flash-lite-latest, gemini-flash-latest, gemini-3-flash-preview, gemini-2.5-flash
    Tier 2: Groq Chat API (openai/gpt-oss-120b, qwen/qwen3.8-27b) with expanded 4096+ tokens
    Tier 3: OpenRouter API (nex-agi/nex-n2.5-pro:free, nex-agi/nex-n2.5-mini:free, etc.)
    """
    global _current_gemini_key_idx, _gemini_key_cooldowns
    _logger = on_log or log_cb
    gemini_keys = _get_gemini_keys()
    gem_max = max(max_tokens or 8192, 4096)

    # 1. TIER 1: GEMINI WITH STATEFUL ROUND-ROBIN & COOLDOWN
    if gemini_keys:
        now = time.time()
        # Clean expired cooldowns
        _gemini_key_cooldowns = {k: exp for k, exp in _gemini_key_cooldowns.items() if exp > now}

        total_keys = len(gemini_keys)
        # Order keys starting from current index
        start_idx = _current_gemini_key_idx % total_keys
        ordered_indices = [(start_idx + i) % total_keys for i in range(total_keys)]

        # Check if some keys are not on cooldown
        available_indices = [i for i in ordered_indices if gemini_keys[i] not in _gemini_key_cooldowns]
        # If all keys are on cooldown, try all ordered anyway (one might have cleared or quota reset)
        indices_to_try = available_indices if available_indices else ordered_indices

        user_model = os.getenv("GEMINI_MODEL", "").strip()
        # Normalizar nomes legados ou hipotéticos para modelos oficiais do Google AI Studio
        if "gemini-3." in user_model:
            user_model = "gemini-2.5-flash"

        base_models = [
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-flash-latest",
            "gemini-flash-lite-latest",
            "gemini-1.5-flash",
        ]
        gemini_models = []
        if user_model and user_model not in gemini_models:
            gemini_models.append(user_model)
        for m in base_models:
            if m not in gemini_models:
                gemini_models.append(m)

        for idx in indices_to_try:
            key = gemini_keys[idx]
            masked = key[:6] + "..." + key[-4:] if len(key) > 10 else "***"

            for model in gemini_models:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
                    payload = {
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "temperature": 0.3,
                            "maxOutputTokens": gem_max,
                            "responseMimeType": "application/json"
                        }
                    }
                    resp = requests.post(url, json=payload, timeout=20)

                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts:
                                # Advance round-robin index so next query uses next key
                                _current_gemini_key_idx = (idx + 1) % total_keys
                                _gemini_key_cooldowns.pop(key, None)
                                return parts[0].get("text", "")

                    elif resp.status_code == 404:
                        # Model not available on this specific key/tier, quickly try next model
                        continue

                    elif resp.status_code == 503:
                        # 503 = Temporary spike / model overloaded on Google's side.
                        # DO NOT abandon the key! Try the next model on this SAME key!
                        _safe_log(_logger, f"ℹ Gemini [{model}] com alta demanda (503). Tentando modelo alternativo...")
                        continue

                    elif resp.status_code == 429:
                        # 429 = Rate limit exceeded on this key. Put on cooldown and rotate to next key.
                        _gemini_key_cooldowns[key] = now + 60.0
                        _safe_log(_logger, f"⚠ Gemini cota por minuto atingida na chave {masked} (429). Rotacionando chave...")
                        break  # Break out of model loop for this key, go to next key

                    else:
                        continue

                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                    _safe_log(_logger, f"ℹ Timeout de conexão no modelo {model}. Tentando próximo...")
                    continue
                except Exception:
                    continue

    # 2. TIER 2: GROQ FALLBACK
    groq_key = _get_api_key("GROQ_API_KEY")
    if groq_key and groq_key.startswith("gsk_"):
        _safe_log(_logger, "⚠ Alternando para Groq (alta velocidade e capacidade)...")
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
        g_tokens = min(max(max_tokens or 4096, 4096), 8192)
        for model in ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"]:
            try:
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": g_tokens,
                    "response_format": {"type": "json_object"}
                }
                resp = requests.post(url, headers=headers, json=payload, timeout=60)
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"]
                    if content:
                        return content
            except Exception:
                continue

    # 3. TIER 3: OPENROUTER FALLBACK
    openrouter_key = _get_api_key("OPENROUTER_API_KEY")
    if openrouter_key:
        _safe_log(_logger, "⚠ Alternando para OpenRouter fallback...")
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {openrouter_key}", "Content-Type": "application/json"}
        o_tokens = min(max(max_tokens or 4096, 4096), 8192)
        for model in ["nex-agi/nex-n2.5-pro:free", "nex-agi/nex-n2.5-mini:free", "liquid/lfm-2.5-2.6b:free"]:
            try:
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": o_tokens,
                    "response_format": {"type": "json_object"}
                }
                resp = requests.post(url, headers=headers, json=payload, timeout=60)
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"]
                    if content:
                        return content
            except Exception:
                continue

    raise RuntimeError("Não foi possível conectar aos provedores de IA (Gemini, Groq ou OpenRouter). Verifique as chaves no arquivo .env.")




def fetch_episode_lore(context: str, on_log: Optional[Callable[[str], None]] = None) -> str:
    """
    Fetch cultural lore, fan reactions, and memorable peaks for the episode.
    Uses the Episode Intelligence Hub to get episode-specific data (fights, techniques,
    characters, synopsis) from Jikan v4, Fandom Wiki, and AniList, then enriches
    with AI-generated hype analysis.
    """
    if not context or len(context.strip()) < 3:
        return ""

    try:
        from ai_cache_hub import ai_cache
        cached_lore = ai_cache.get(context.strip().lower(), "anime_lore_v2")
        if cached_lore and isinstance(cached_lore, str):
            if on_log:
                on_log("[CACHE 24H] Lore e metadados recuperados do cache (0 tokens gastos)!")
            return cached_lore
    except Exception:
        ai_cache = None

    if on_log:
        on_log(f"[LORE] Pesquisando lore e metadados sobre: {context}...")

    # ── Episode Intelligence Hub (NEW: multi-source episode-specific data) ──
    enriched_api = ""
    try:
        from metadata_enricher import build_episode_intelligence
        enriched_api = build_episode_intelligence(context, on_log=on_log)
        if enriched_api and on_log:
            on_log("[OK] Inteligência do episódio montada (Jikan + Fandom Wiki + AniList)")
    except Exception as e:
        if on_log:
            on_log(f"[AVISO] Episode Intelligence Hub: {e} — tentando fallback...")
        try:
            from metadata_enricher import get_enriched_context_for_prompt
            enriched_api = get_enriched_context_for_prompt(context)
            if enriched_api and on_log:
                on_log("[OK] Metadados gerais obtidos via API (Kitsu / TVMaze / MAL)")
        except Exception:
            pass

    api_block = f"\n{enriched_api}\n" if enriched_api else ""

    # ── Identificação Canônica da Franquia para Precisão Factual ──
    canon_context = context.strip()
    low_ctx = canon_context.lower()
    if any(k in low_ctx for k in ["cavaleiros do zodiaco", "saint seiya", "cdz"]) and not any(k in low_ctx for k in ["lost canvas", "omega", "soul of gold", "netflix"]):
        canon_context = f"Cavaleiros do Zodíaco / Saint Seiya (Série Clássica de 1986) - {context}"
    elif any(k in low_ctx for k in ["samurai x", "kenshin"]) and "2023" not in low_ctx:
        canon_context = f"Samurai X / Rurouni Kenshin (Clássico) - {context}"
    elif "dbz" in low_ctx or "dragon ball z" in low_ctx:
        canon_context = f"Dragon Ball Z - {context}"

    prompt = f"""Você é a enciclopédia definitiva de animes, séries, doramas e cultura pop (equivalente ao Google IA / Gemini Search).
O usuário quer mapear com máxima precisão factual e detalhamento narrativo os MELHORES MOMENTOS e contexto do seguinte episódio: "{canon_context}"
{api_block}
Sua missão é gerar uma FICHA COMPLETA E ESTRUTURADA DO EPISÓDIO (no mesmo padrão da IA do Google):

1. VISÃO GERAL DO EPISÓDIO:
   • Título oficial do episódio (em Português e original)
   • Onde se passa (localização exata) e situação inicial dos personagens
   • Motivo do conflito / ameaça enviada

2. CRONOLOGIA DOS MELHORES MOMENTOS DO EPISÓDIO (Em ordem sequencial dos acontecimentos):
   Para CADA momento memorável do episódio (incluindo diálogos/debates filosóficos, discussões tensas, intervenções, ataques e lutas):
   • Nome da cena (ex: 'A Entrada de Máscara da Morte', 'A Lição de Filosofia do Mestre Ancião', 'Shiryu Intervém e o Chute no Elmo', 'O Cólera do Dragão Humilhado', 'A Chegada Imponente de Mu de Áries')
   • PRELÚDIO / CONVERSA: Como o diálogo ou confronto começa, quem provoca quem e o que gerou a tensão inicial.
   • AÇÃO / CLÍMAX: O que acontece no ápice da cena (o golpe, a demonstração de poder/cosmo, a revelação chocante).
   • DESFECHO & REAÇÃO: Como a cena termina imediatamente e qual a reação dos personagens envolvidos.
   • FALAS MARCANTES: Frases e citações icônicas ditas nessa cena.

3. IMPACTO DRAMÁTICO NO ENREDO:
   • Por que este episódio é crucial para a obra e como ele prepara os próximos arcos.

Responda em formato JSON:
{{
  "lore": "Texto estruturado completo contendo a Visão Geral, a Cronologia dos Melhores Momentos detalhada com Prelúdio/Ação/Desfecho de cada momento, e o Impacto no Enredo."
}}
"""
    final_lore = ""
    try:
        raw = call_ai_text(prompt, on_log=None, max_tokens=4096)
        lore = ""
        try:
            clean_raw = raw.strip()
            if "```json" in clean_raw:
                clean_raw = clean_raw.split("```json")[1].split("```")[0].strip()
            elif "```" in clean_raw:
                clean_raw = clean_raw.split("```")[1].split("```")[0].strip()
            data = json.loads(clean_raw)
            if isinstance(data, dict):
                lore = data.get("lore", "")
                if not lore:
                    # Se retornou campos estruturados no json
                    parts = []
                    if "titulo_pt_br" in data or "titulo" in data:
                        t = data.get("titulo_pt_br") or data.get("titulo")
                        parts.append(f"• Título: {t}")
                    if "sinopse" in data or "visao_geral" in data:
                        vg = data.get("visao_geral") or data.get("sinopse")
                        if isinstance(vg, dict):
                            parts.append(f"• Visão Geral: {vg.get('situacao_inicial', '')} (Local: {vg.get('localizacao', '')})")
                        else:
                            parts.append(f"• Visão Geral: {vg}")
                    if "melhores_momentos" in data and isinstance(data["melhores_momentos"], list):
                        parts.append("\n🏆 MELHORES MOMENTOS DO EPISÓDIO:")
                        for idx, m in enumerate(data["melhores_momentos"], 1):
                            t_m = m.get("titulo") or m.get("titulo_cena") or f"Momento {idx}"
                            dyn = m.get("dinamica") or {}
                            pre = dyn.get("inicio") or m.get("preludio_conversa", "")
                            act = dyn.get("escalada") or m.get("acao_climax", "")
                            end = dyn.get("desfecho") or m.get("desfecho_reacao", "")
                            falas = m.get("falas_marcantes", "")
                            parts.append(f"\n#{idx} {t_m}:")
                            if pre: parts.append(f"  - Contexto/Diálogo: {pre}")
                            if act: parts.append(f"  - Clímax/Ação: {act}")
                            if end: parts.append(f"  - Desfecho: {end}")
                            if falas: parts.append(f"  - Falas: {falas}")
                    if "impacto_no_enredo" in data:
                        parts.append(f"\n💡 IMPACTO NO ENREDO:\n{data['impacto_no_enredo']}")
                    lore = "\n".join(parts)
        except Exception:
            # Fallback direto se a IA respondeu em markdown
            lore = raw.strip()

        if enriched_api:
            if not lore or "Lore não encontrada" in lore:
                final_lore = enriched_api
            else:
                final_lore = f"{enriched_api}\n\n[CRONOLOGIA DOS MELHORES MOMENTOS & ENREDO]\n{lore}"
        elif "Lore não encontrada" in lore:
            final_lore = ""
        else:
            final_lore = lore
    except Exception as e:
        if on_log:
            on_log(f"[AVISO] Fallback lore: {e}")
        final_lore = enriched_api or ""

    if ai_cache and final_lore:
        ai_cache.set(context.strip().lower(), "anime_lore_v3", final_lore)

    return final_lore



# ─── Viral Knowledge Base (from reference ViralAI) ───────────────────────────

VIRAL_KNOWLEDGE_BASE = """
[BASE DE CONHECIMENTO VIRAL — ALGORITMO E PADRÕES]

ALGORITMO DAS PLATAFORMAS:
  • TikTok / YouTube Shorts / Reels priorizam: Watch Time, Completion Rate, Shares, Comments, Saves e Replays.
  • Vídeos que passam dos primeiros 3 segundos têm 70%+ de chance a mais de viralizar.
  • O algoritmo testa em "waves": ~200 pessoas → ~2.000 → ~20.000. A decisão de ampliar é tomada nas primeiras 24h.
  • Vídeos entre 30–60 segundos têm a melhor performance média de retenção.

PADRÕES VIRAIS COMPROVADOS:
  • HOOK nos primeiros 1–3 segundos (fala de impacto, revelação, choque visual, pergunta provocativa)
  • LOOP VALUE — o final do vídeo se conecta com o início para replay automático invisível
  • PATTERN INTERRUPT — quebrar expectativas a cada 3–5 segundos para manter atenção
  • CURIOSITY GAP — criar uma lacuna de curiosidade que só se resolve assistindo até o fim
  • EMOTIONAL TRIGGERS — surpresa, humor, nostalgia, inspiração, raiva, ternura
  • REPLAY VALUE — cenas que as pessoas reassistem para capturar detalhes (reversão, twist, timing)
"""

GENRE_RULES_DIRECTOR = {
    "general": """
[FOCO DE CONTEÚDO OBRIGATÓRIO: GERAL / CLÍMAX VIRAL (PADRÃO)]
  • OBJETIVO: Selecionar os momentos de maior retenção e impacto geral do episódio.
  • Priorize os pontos mais altos da narrativa: grandes revelações, viradas na história (plot twists), momentos surpreendentes ou o clímax emocional/visual.
  • O trecho deve ter apelo universal e forte valor de compartilhamento no TikTok, Reels e YouTube Shorts.
""",
    "action": """
[FOCO EXCLUSIVO E OBRIGATÓRIO: AÇÃO / BATALHAS / LUTAS]
🚨 TOLERÂNCIA ZERO PARA CENAS DE CONVERSA OU COMÉDIA PASTELÃO:
  • O usuário escolheu EXCLUSIVAMENTE AÇÃO. TODOS os cortes devem ser batalhas, lutas corporais, trocação de socos/espadas, poderes, ataques especiais e adrenalina máxima.
  • ⛔ NUNCA selecione momentos de alívio cômico, romance lento ou conversas pacíficas.
  • Se o episódio tiver pouca luta, encontre até o menor momento de ameaça física, perseguição ou confronto.
  • Preencha o campo "genre" com: "Ação / Batalha".
""",
    "comedy": """
[FOCO EXCLUSIVO E OBRIGATÓRIO: ENGRAÇADO / COMÉDIA / HUMOR]
🚨 TOLERÂNCIA ZERO PARA CENAS SÉRIAS, DRAMÁTICAS OU DE LUTA:
  • O usuário escolheu EXCLUSIVAMENTE HUMOR / ENGRAÇADO. TODOS os cortes devem ser 100% cômicos, engraçados, zoeiras, quebra de expectativa ou reações hilárias.
  • ⛔ É TERMINANTEMENTE PROIBIDO selecionar lutas sérias, tragédias, discussões sérias, mortes ou cenas dramáticas.
  • Foque na quebra repentina de expectativa (punchline), situações embaraçosas, mal-entendidos bizarros, caras e bocas cômicas e reações exageradas de espanto.
  • Se o episódio for sério, garimpe os raros momentos de alívio cômico, ironias, piadas visuais ou respostas sarcásticas.
  • Preencha o campo "genre" com: "Comédia / Humor".
""",
    "romance": """
[FOCO EXCLUSIVO E OBRIGATÓRIO: ROMANCE / QUÍMICA / TENSÃO AMOROSA]
🚨 TOLERÂNCIA ZERO PARA PANCADARIA OU PIADAS BESTAS:
  • O usuário escolheu EXCLUSIVAMENTE ROMANCE. TODOS os cortes devem focar em tensão romântica, intimidade, declarações, ciúmes ou carinho entre personagens.
  • ⛔ NUNCA selecione lutas violentas ou piadas desconexas.
  • Busque aproximação física, "quase beijos", toques acidentais, rubor facial e declarações íntimas.
  • Preencha o campo "genre" com: "Romance / Química".
""",
    "sensual": """
[FOCO EXCLUSIVO E OBRIGATÓRIO: SENSUAL / ECCHI / FANSERVICE]
🚨 TOLERÂNCIA ZERO PARA CENAS SEM APELO SENSUAL OU CHARME:
  • O usuário escolheu EXCLUSIVAMENTE SENSUAL / FANSERVICE. TODOS os cortes devem valorizar charme, beleza estética, sensualidade e tensão provocativa.
  • ⛔ NUNCA selecione cenas focadas em diálogos burocráticos ou lutas sem apelo visual de charme.
  • Busque poses provocantes, troca de roupas, banho, praia/águas termais e momentos provocantes.
  • Preencha o campo "genre" com: "Sensual / Fanservice".
""",
}

# Aliases de compatibilidade
GENRE_RULES_DIRECTOR["shonen_action"] = GENRE_RULES_DIRECTOR["action"]
GENRE_RULES_DIRECTOR["romance_drama"] = GENRE_RULES_DIRECTOR["romance"]
GENRE_RULES_DIRECTOR["engraçado"] = GENRE_RULES_DIRECTOR["comedy"]
GENRE_RULES_DIRECTOR["comédia"] = GENRE_RULES_DIRECTOR["comedy"]
GENRE_RULES_DIRECTOR["humor"] = GENRE_RULES_DIRECTOR["comedy"]
GENRE_RULES_DIRECTOR["ação"] = GENRE_RULES_DIRECTOR["action"]
GENRE_RULES_DIRECTOR["sensual"] = GENRE_RULES_DIRECTOR["sensual"]

SNIPER_TIMESTAMP_RULES = """
[REGRA DE OURO DOS TIMESTAMPS (FLUXO SNIPER)]
1. ANCORAGEM NA TRANSCRIÇÃO: Todos os timestamps devem ser derivados da transcrição fornecida. Encontre a fala correspondente e use exatamente os tempos listados. NÃO estime ou adivinhe.
2. LEGENDAS NATIVAS: Se o vídeo tiver legendas coladas na tela (hardsubs) e a transcrição estiver dessincronizada, baseie-se na legenda visual — não na transcrição de áudio.
3. CONDENSAÇÃO: Remova silêncios e barrigas. Se a fala A termina em 04:14 e a fala B crucial começa em 04:29, registre dois trechos separados e deixe o sistema unir, eliminando os 15s de tempo morto.
4. NUNCA corte uma fala pela metade. Sempre que possível, comece no início de uma palavra e termine no fim de uma fala completa.
"""

MINI_MOVIE_KNOWLEDGE_BASE = """
[BASE DE CONHECIMENTO: MINI-FILMES & ARCOS NARRATIVOS (2 A 5 MINUTOS)]

FORMATO MINI-FILME / RESUMO CINEMATOGRÁFICO:
  • Este modo NÃO é para Shorts de 30-60 segundos.
  • Este modo identifica blocos narrativos LONGOS de 2 a 5 minutos (120s a 300s) com início, desenvolvimento, clímax e desfecho dramático.
  • Esse trecho será posteriormente enviado para a aba Refinador, onde será condensado no resumo perfeito de até 2:30 min.
  • Por isso, o trecho bruto selecionado aqui PRECISA ter entre 2 e 5 minutos para conter todo o contexto da história!
  • ⛔ QUALQUER CORTE MENOR QUE 2 MINUTOS (120s) É ESTITAMENTE PROIBIDO.
"""

MINI_MOVIE_TIMESTAMP_RULES = """
[REGRAS DE TIMESTAMPS PARA MINI-FILME (2 A 5 MINUTOS)]
1. DURAÇÃO OBRIGATÓRIA: Cada trecho DEVE ter NO MÍNIMO 2 MINUTOS (120s) e NO MÁXIMO 5 MINUTOS (300s).
   ⛔ NUNCA sugira trechos de 30s, 45s, 1m ou 1m15s. Qualquer corte menor que 120 segundos é INVÁLIDO.
2. CONTINUIDADE NARRATIVA COMPLETA:
   - INÍCIO: O momento onde o conflito ou conversa começa a se desenhar (dê contexto!).
   - DESENVOLVIMENTO: As provocações, revelações e troca de falas.
   - CLÍMAX: O golpe, confissão ou revelação principal.
   - DESFECHO: As consequências imediatas e reações dos personagens ao clímax.
3. ANCORAGEM: Utilize os timestamps da transcrição para marcar o início e o fim desse arco contínuo.
"""


def build_candidates_prompt(
    mode: str,
    context: str,
    lore: str,
    transcript: str,
    video_duration_str: str = "",
    cut_mode: str = "context",
    excluded_ranges: Optional[List[str]] = None,
    genre: str = "general"
) -> str:
    """Build the director curation prompt for Top 3 or Smart Cortes with cut mode and content type support."""
    raw_g = str(genre or "general").lower()
    if any(k in raw_g for k in ["engraçado", "engracado", "comédia", "comedia", "comedy", "humor"]):
        genre = "comedy"
    elif any(k in raw_g for k in ["ação", "acao", "action", "luta", "batalha"]):
        genre = "action"
    elif any(k in raw_g for k in ["romance", "química", "quimica", "love"]):
        genre = "romance"
    elif any(k in raw_g for k in ["sensual", "ecchi", "fanservice"]):
        genre = "sensual"
    else:
        genre = "general"

    lore_section = f"\n[LORE DO EPISÓDIO E REAÇÕES DOS FÃS]\n{lore}\n" if lore else ""
    ctx_section = f"\n[CONTEXTO DA OBRA / EPISÓDIO]\n{context}\n" if context else ""
    genre_rules = GENRE_RULES_DIRECTOR.get(genre, GENRE_RULES_DIRECTOR.get("general", ""))
    if video_duration_str:
        dur_section = f"""
[DURAÇÃO REAL DO ARQUIVO DE VÍDEO]: {video_duration_str}
ATENÇÃO CRÍTICA SOBRE OS TIMESTAMPS:
- Todos os cortes DEVEM obrigatoriamente estar contidos dentro do vídeo atual (entre 00:00 e {video_duration_str}).
- NUNCA gere timestamps após {video_duration_str}. Se o vídeo dura {video_duration_str}, o fim do corte jamais pode exceder esse tempo!
"""
    else:
        dur_section = ""

    if excluded_ranges:
        fmt_excl = "\n".join(f"  - {r}" for r in excluded_ranges)
        excluded_section = f"""
[TRECHOS JÁ GERADOS — PROIBIDO REPETIR EM HIPÓTESE ALGUMA]
⛔ O usuário JÁ VIU os seguintes trechos e quer cortes COMPLETAMENTE DIFERENTES.
⛔ PROIBIDO repetir, reformular, renomear ou sugerir qualquer trecho que se SOBREPONHA com os abaixo.
⛔ Um corte que começa apenas 1 minuto antes ou depois de um trecho já gerado E cobre a mesma cena É UMA REPETIÇÃO.
⛔ Se você repetir um trecho já gerado, o resultado inteiro será descartado.

TRECHOS JÁ GERADOS (TODOS PROIBIDOS):
{fmt_excl}

✅ Explore partes do vídeo que ainda NÃO foram mostradas. Vá para outros momentos, outras cenas, outras emoções.
"""
    else:
        excluded_section = ""


    if cut_mode == "narrative_arc":
        cut_mode_rules = """
[MODO DE CORTE: MINI-FILME / ARCO NARRATIVO (2 A 5 MINUTOS)]

OBJETIVO: Identificar blocos contextualizados e épicos de 2 a 5 minutos (120 a 300 segundos) que funcionem como um MINI-FILME ou ARCO NARRATIVO COMPLETO.
Esse trecho será condensado no Refinador Mastercut para gerar um resumo cinematográfico de até 2:30 min com o suco da história.

🚨 REGRA CRÍTICA DE DURAÇÃO (NÃO NEGOCIÁVEL):
  • Duração mínima obrigatória: 2 minutos (120s).
  • Duração máxima permitida: 5 minutos (300s).
  • ⛔ CORTES MENORES QUE 2 MINUTOS SÃO PROIBIDOS NESTE MODO E SERÃO DESCARTADOS.

ESTRUTURA DO ARCO:
  • Abertura contextualizada (setup do dilema/confronto)
  • Escalada de tensão e diálogos marcantes
  • Clímax épico central
  • Desfecho e reações imediatas

FORMATO OBRIGATÓRIO DO TÍTULO:
  • "title": "[Nome do Arco/Mini-Filme] — [Descrição detalhada do dilema, personagens e impacto final]"
"""

    elif cut_mode == "continuous":
        cut_mode_rules = """
[MODO DE CORTE: CONTÍNUO — CENA ÚNICA SEM EDIÇÃO INTERNA]

OBJETIVO: Identificar trechos que funcionem como UMA ÚNICA CENA FLUÍDA (30 a 75 segundos), sem cortes internos.
Ideal para diálogos corridos, piadas completas ou momentos de ação direta sem falhas de fala ou alucinações.

⚠️ LIMITES OBRIGATÓRIOS DESTE MODO — NÃO NEGOCIÁVEIS:
  ✗ NUNCA sugira cortes com duração superior a 75 segundos (1m 15s) neste modo.
  ✗ NUNCA use "Arco Narrativo" no campo genre. Este modo é para cenas curtas e fluidas.
  ✗ A cena deve ter emoção uniforme do início ao fim — sem trechos mortos ou silêncios longos no meio.
  • Duração ideal: 30–60s para Shorts/Reels. Até 75s se a cena justificar.

FORMATO OBRIGATÓRIO DO TÍTULO:
  • "title": "[Gancho/Título da Cena] — [Descrição detalhada de quem está na cena e o que acontece]"
"""

    elif cut_mode == "multi_part":
        cut_mode_rules = """
[MODO DE CORTE: SÉRIE EM PARTES (MULTI-PARTES: PARTE 1, PARTE 2, PARTE 3)]

OBJETIVO: Identificar uma GRANDE SEQUÊNCIA DRAMÁTICA OU BATALHA do episódio e dividi-la em uma sequência interligada de 2 a 4 Shorts (60 a 90 segundos por parte).
Perfeito para TikTok e Reels em série ("Parte 1", "Parte 2", etc.), gerando maratona no perfil e altíssimo engajamento.

ESTRUTURA DAS PARTES:
  • PARTE 1: A Construção do Dilema / Provocação / Ameaça. Termina exatamente quando a batalha começa ou a revelação é anunciada (cliffhanger).
  • PARTE 2: O Confronto Direto / Clímax Intermediário / Troca de golpes e acusações. Termina no momento de maior perigo ou virada.
  • PARTE 3: A Resolução Épica / A Queda / O Desfecho chocante e reações imediatas dos personagens.

FORMATO OBRIGATÓRIO DO TÍTULO:
  • "title": "[Nome da Saga/Confronto] - Parte 1/3 — [Descrição do que acontece especificamente nesta parte]"
  • O campo 'description' deve explicar como esta parte se conecta com a próxima.
  • Duração de cada parte: 60s a 90s.
"""

    elif cut_mode == "dynamic_montage":
        cut_mode_rules = """
[MODO DE CORTE: MONTAGEM ÁGIL / SEM BARRIGA (ALTA RETENÇÃO)]

OBJETIVO: Identificar trechos de 45 a 70 segundos com ZERO barriga e alta densidade de acontecimentos.
Elimine cenas lentas, andanças e pausas mortas. Foque em ritmo acelerado, troca rápida de falas ou clímax ininterrupto.

CRITÉRIOS DE CORTE DINÂMICO:
  • Começa imediatamente na primeira fala ou golpe decisivo.
  • Densidade máxima: cada segundo deve conter fala relevante, reação expressiva ou ação visual impactante.
  • Termina exatamente no pico de energia ou na punchline da cena.
  • Duração ideal: 45–60 segundos. Máximo: 70 segundos.

FORMATO OBRIGATÓRIO DO TÍTULO:
  • "title": "[Título de Alta Energia] — [Descrição clara dos acontecimentos dinâmicos e personagens]"
"""

    elif cut_mode == "verbal_duel":
        cut_mode_rules = """
[MODO DE CORTE: DUELO VERBAL & REVELAÇÃO (CONFRONTO PSICOLÓGICO)]

OBJETIVO: Identificar trechos de 40 a 80 segundos focados EXCLUSIVAMENTE em embates intelectuais, bate-boca, humilhações, confissões ou revelações chocantes de segredos.
Ignore lutas físicas puras e foque na intensidade dramática das palavras e no choque dos personagens.

ELEMENTOS OBRIGATÓRIOS:
  • Confronto cara a cara ou discurso intimidador.
  • Reação visual de choque, medo, quebra de ego ou triunfo psicológico.
  • Fala icônica que mereça ser citada ou comentada nos Shorts.
  • Duração: 40 a 80 segundos.

FORMATO OBRIGATÓRIO DO TÍTULO:
  • "title": "[Frase Marcante / Choque] — [Descrição do conflito entre os personagens e a revelação feita]"
"""

    else:  # context (default)
        cut_mode_rules = """
[MODO DE CORTE: CONTEXTO COMPLETO — CENA NARRATIVA COM INÍCIO, MEIO E FIM (60s A 150s)]

OBJETIVO: Identificar trechos de 60 a 150 segundos (1m a 2m 30s) que capturem TODO O CONTEXTO DA CENA (conversa, debate filosófico, escalada de tensão ou luta completa).
⛔ PROIBIDO CORTAR PELA METADE: O espectador precisa entender quem está falando, por que a discussão começou e como a cena terminou!

🚨 REGRA SUPREMA DE INTEGRIDADE DA CENA (ANTI-DECAPITAÇÃO DE CONTEXTO):
  1. SETUP & CONTEXTO DA CONVERSA (Início):
     - NUNCA comece no frame exato de um golpe ou no meio de um grito sem contexto anterior.
     - Comece na fala que introduz o conflito (a chegada do personagem, a provocação do vilão, o debate moral/filosófico ou o motivo da disputa).
  2. ESCALADA & CLÍMAX (Desenvolvimento):
     - Cubra as réplicas verbais afiadas, o aumento de cosmo/tensão ou a troca de golpes que leva ao pico de ação.
  3. DESFECHO & REAÇÃO (Finalização):
     - Mostre o desfecho do momento (o golpe bloqueado, a revelação feita, a chegada de um aliado ou o recuo) e a reação dos personagens.
  • Duração ideal: 60 a 120 segundos para diálogos e confrontos diretos; até 150 segundos (2m 30s) para lutas e debates complexos com fala prévia.

FORMATO OBRIGATÓRIO DO TÍTULO:
  • "title": "[Título Chamativo] — [Descrição detalhada da conversa/luta, personagens e desfecho]"
"""

    if cut_mode == "narrative_arc":
        kb_block = MINI_MOVIE_KNOWLEDGE_BASE
        rules_block = MINI_MOVIE_TIMESTAMP_RULES
        json_example = """{
  "candidates": [
    {
      "id": "corte_01",
      "title": "O Despertar do Hichigo — Ichigo perde o controle e massacra Ulquiorra no topo de Las Noches",
      "estimated_range": "08:30 -> 12:15",
      "start_time": "08:30",
      "end_time": "12:15",
      "duration": "3m 45s",
      "genre": "Mini-Filme / Arco Narrativo",
      "quality_score": 9.8,
      "viral_potential": "Altíssimo (Mini-Filme 3m 45s)",
      "description": "Ichigo desperta sua forma Vasto Lorde após o chamado desesperado de Orihime; ele anula os ataques de Ulquiorra com Cero devastador e muda o rumo da guerra.",
      "quality_reasoning": "História completa com início, virada dramática, clímax colossal e impacto emocional arrebatador."
    }
  ]
}"""
        if mode == "top3":
            task_rules = f"""TAREFA: Você é um Diretor de Cinema e Curador Especialista em Arcos Narrativos e Mini-Filmes (2 a 5 minutos).
Analise a transcrição de ponta a ponta e selecione rigorosamente os TOP 3 ARCOS NARRATIVOS DE 2 A 5 MINUTOS (120s a 300s).

🚨 REGRA DE DURAÇÃO (NÃO NEGOCIÁVEL):
- CADA CORTE DEVE TER DURAÇÃO TOTAL ENTRE 2 MINUTOS (120s) E 5 MINUTOS (300s).
- ⛔ NUNCA sugira trechos com menos de 2 minutos (ex: 40s, 1m, 1m15s são PROIBIDOS).
- Exemplos de durações válidas: 08:30 -> 12:00 (3m 30s), 14:00 -> 17:30 (3m 30s), 19:15 -> 23:15 (4m 00s).

{cut_mode_rules}
{genre_rules}

RETORNE EXATAMENTE 3 ARCOS NARRATIVOS, ordenados do mais épico para o menor."""
        else:  # smart
            task_rules = f"""TAREFA: Você é um Diretor de Cinema e Curador Sênior Especialista em Arcos Narrativos e Mini-Filmes (2 a 5 minutos).
Sua missão: analisar a transcrição timestamp a timestamp e identificar todos os blocos dramáticos e arcos narrativos completos de 2 A 5 MINUTOS (120 A 300 SEGUNDOS).

🚨 REGRA SUPREMA DE DURAÇÃO (INQUEBRÁVEL):
- CADA CORTE DEVE TER DURAÇÃO TOTAL ENTRE 2 MINUTOS (120s) E 5 MINUTOS (300s).
- ⛔ NUNCA sugira cortes com menos de 2 minutos (ex: 40s, 1m, 1m15s são PROIBIDOS e serão descartados).
- ⛔ NUNCA sugira cortes com mais de 5 minutos (300s).
- O trecho precisa conter a introdução do momento, os diálogos de construção, o clímax emocionante e as consequências imediatas.

{cut_mode_rules}
{genre_rules}

=== PROCESSO DE ANÁLISE PARA MINI-FILMES ===
1. Mapeie os grandes acontecimentos do episódio (batalhas, revelações, despedidas, sacrifícios).
2. Para cada grande momento, expanda o bloco de tempo para trás (para incluir a motivação e os diálogos iniciais) e para a frente (para incluir o clímax e o impacto emocional), garantindo de 2 a 5 minutos por trecho.
3. Retorne no mínimo 4 e até 6 arcos narrativos completos do episódio.
4. Ordene do arco mais épico/impactante para o menor."""

    else:
        kb_block = VIRAL_KNOWLEDGE_BASE
        rules_block = SNIPER_TIMESTAMP_RULES
        json_example = """{
  "candidates": [
    {
      "id": "corte_01",
      "title": "A Revelação de Aizen — Ele para a lâmina de Ichigo com um único dedo e choca a todos",
      "estimated_range": "04:15 -> 05:25",
      "start_time": "04:15",
      "end_time": "05:25",
      "duration": "1m 10s",
      "genre": "Tensão / Revelação",
      "quality_score": 9.5,
      "viral_potential": "Altíssimo (Nota 9.5/10)",
      "description": "Ichigo avança com toda sua velocidade no Bankai, mas Aizen interrompe a trilha sonora e segura a Zangetsu apenas com o dedo indicador.",
      "quality_reasoning": "Quebra de expectativa brutal nos primeiros 3 segundos com retenção máxima até a última fala."
    }
  ]
}"""
        if genre != "general":
            crit_5 = f"""5. FILTRO ESTRITO DE GÊNERO [{genre.upper()}]:
   - O usuário exigiu EXCLUSIVAMENTE cortes do gênero: {genre.upper()}.
   - ⛔ PROIBIDO misturar com outros tipos de cena! NÃO inclua cenas fora deste gênero.
   - Todos os cortes selecionados DEVEM ser 100% focados em {genre.upper()}."""
        else:
            crit_5 = "5. DIVERSIDADE: Não retorne três cenas do mesmo tipo. Misture ação com emoção ou comédia."

        if mode == "top3":
            task_rules = f"""TAREFA: Você é um Diretor de Conteúdo e Editor Profissional especializado em cortes virais para TikTok, Reels e YouTube Shorts.
Analise a transcrição de ponta a ponta e selecione rigorosamente os TOP 3 momentos com maior potencial de viralizar deste episódio.

{cut_mode_rules}
{genre_rules}

CRITÉRIOS DOS TOP 3:
1. HOOK PODEROSO: Os primeiros 3 segundos do corte precisam ser fortes o bastante para parar o scroll. Priorize cenas que começam com uma fala marcante, uma reação expressiva ou um beat de ação claro.
2. PICO DE IMPACTO: O momento de maior expressão do foco selecionado.
3. RETENÇÃO ATÉ O FIM: O trecho deve manter tensão, emoção ou humor até os últimos segundos.
4. NOTA DE QUALIDADE (0 a 10): Notas 9-10 somente para cenas verdadeiramente históricas/épicas do episódio. Seja honesto.
{crit_5}
6. REGRA DO TÍTULO OBRIGATÓRIA: O campo 'title' DEVE OBRIGATORIAMENTE seguir o padrão: "[Título Chamativo] — [Descrição detalhada da ação, personagens e clímax]". Títulos curtos ou genéricos são PROIBIDOS.
7. RETORNE EXATAMENTE 3 CANDIDATOS, ordenados do maior potencial para o menor."""
        else:  # smart
            if genre != "general":
                crit_smart = f"""  • FILTRO EXCLUSIVO DE GÊNERO [{genre.upper()}]:
    - TODOS os candidatos selecionados DEVEM ser estritamente do gênero {genre.upper()}.
    - ⛔ NÃO inclua momentos de outras categorias. NÃO diversifique para outros gêneros."""
            else:
                crit_smart = "  • Evite incluir mais de 2 cenas da mesma categoria (diversifique o conteúdo)."

            task_rules = f"""TAREFA: Você é um Editor Sênior de Conteúdo e Diretor de Vídeo com 10+ anos de experiência na curadoria dos MELHORES MOMENTOS de animes, doramas e séries.

Sua missão: analisar a transcrição timestamp a timestamp e identificar com precisão cirúrgica os MELHORES MOMENTOS DO EPISÓDIO, preservando TODO O CONTEXTO de cada cena (a conversa preparatória, a escalada dramática/luta e o desfecho).

{cut_mode_rules}
{genre_rules}

=== PROCESSO DE ANÁLISE SMART (siga rigorosamente esta ordem mental) ===

PASSO 1 — ALINHAMENTO COM O LORE E OS MELHORES MOMENTOS DO EPISÓDIO:
Consulte a seção [LORE DO EPISÓDIO E REAÇÕES DOS FÃS] acima. Ela contém a cronologia exata dos melhores momentos do episódio mapeada pela inteligência de pesquisa (ex: discussões filosóficas, confrontos de poderes, técnicas marcantes e aparições surpresa).
Localize na transcrição EXATAMENTE onde cada um desses momentos icônicos acontece.

PASSO 2 — PRESERVAÇÃO INTEGRAL DO CONTEXTO (REGRA ANTI-DECAPITAÇÃO):
⛔ NUNCA CORTE UMA CENA PELA METADE:
  • Se for uma CONVERSA / DEBATE (ex: Mestre Ancião repreendendo Máscara da Morte):
    - O corte DEVE começar na fala que inicia o diálogo ou provocação.
    - DEVE incluir a troca de argumentos e a lição moral ou réplica até o fim da conversa.
  • Se for uma LUTA / CONFRONTO (ex: Shiryu atacando Máscara da Morte e o Cólera do Dragão sendo bloqueado com 1 dedo):
    - O corte DEVE começar na fala ou momento em que a decisão de lutar é tomada (ex: a defesa do mestre e o chute no elmo).
    - DEVE cobrir toda a elevação de poder e disparo da técnica.
    - DEVE terminar na reação de espanto pós-golpe e consequência imediata.
  • Se o diálogo inicial e a luta formarem uma sequência inseparável, mantenha o bloco contínuo (60s a 150s) para que o corte seja plenamente compreensível e épico!

PASSO 3 — ANÁLISE DAS 3 DIMENSÕES DE CADA CANDIDATO:
  • CONTEXTO & HOOK INICIAL: A fala ou provocação de abertura estabelece claramente o que está em jogo?
  • DESENVOLVIMENTO: A tensão cresce e mantém a atenção sem pular falas essenciais?
  • CLÍMAX & PAYOFF: O momento ápice é entregue com impacto e seguido pela reação imediata?

PASSO 4 — REGRA DO TÍTULO DESCRITIVO (MANDATÓRIO):
Todo corte DEVE ter o campo 'title' no formato: "[Título Chamativo] — [Descrição detalhada da conversa/luta, personagens e clímax da cena]".
Exemplo: "A Lição do Mestre Ancião — Dohko confronta Máscara da Morte e ensina o verdadeiro significado da justiça".
Exemplo: "A Humilhação de Câncer — Shiryu dispara o Cólera do Dragão mas Máscara da Morte para com apenas um dedo".
⛔ NUNCA use títulos curtos ou vagos como 'A Batalha' ou 'Corte 1'.

PASSO 5 — SELEÇÃO FINAL:
  • Inclua os melhores momentos que correspondam aos ápices do episódio.
{crit_smart}
  • Mínimo: 3 a 5 candidatos dependendo do episódio. Máximo: 8 candidatos.
  • Ordene do maior potencial/impacto para o menor.

CRITÉRIO DE DESEMPATE: Prefira cenas com DIÁLOGO ICÔNICO e LUTA COMPLETA — são as cenas que geram o maior número de compartilhamentos e retenção."""

    genre_alert = ""
    if genre != "general":
        genre_alert = f"""
🚨 ALERTA SUPREMO DE GÊNERO [{genre.upper()}]:
O usuário escolheu EXCLUSIVAMENTE o gênero [{genre.upper()}].
TODOS OS CORTES DEVEM SER RIGOROSAMENTE DESSE GÊNERO. NÃO RETORNE CENAS DE OUTROS GÊNEROS.
Preencha o campo "genre" em cada candidato com a descrição de {genre.upper()}.
"""

    return f"""{kb_block}{ctx_section}{dur_section}{excluded_section}{lore_section}
{task_rules}
{rules_block}

[TRANSCRIÇÃO DE ÁUDIO COM TIMESTAMPS DO VÍDEO]
{transcript if transcript else "Transcrição indisponível. Baseie-se no lore do episódio e nos momentos clássicos."}

{genre_alert}
REGRAS OBRIGATÓRIAS:
- Retorne EXATAMENTE no formato JSON especificado abaixo.
- Os tempos devem ser no formato MM:SS (ex: "04:15") ou HH:MM:SS para vídeos com mais de 1 hora.
- Calcule a duração aproximada de cada corte e preencha tanto 'estimated_range' quanto 'start_time' e 'end_time'.
- O campo 'title' DEVE conter OBRIGATORIAMENTE o formato: "[Título Chamativo] — [Descrição detalhada da cena, personagens e acontecimento]".
- O campo 'description' deve detalhar o desenrolar da cena e o impacto dramático em 1 ou 2 frases.
- NÃO repita nenhum trecho listado em [TRECHOS JÁ GERADOS — PROIBIDO REPETIR].
- Responda APENAS com o JSON, sem nenhum texto adicional.

FORMATO JSON OBRIGATÓRIO:
{json_example}
"""


def _parse_ai_candidates_json(raw_response: str, on_log: Optional[Callable[[str], None]] = None) -> List[Dict[str, Any]]:
    """
    Robust JSON parser for Director candidates.
    Handles:
    1. Direct list: [{"id": "corte_01", ...}]
    2. Dict with 'candidates': {"candidates": [...]}
    3. Dict with any list: {"cortes": [...]} or {"items": [...]}
    4. Markdown code blocks (```json ... ```)
    5. Regex extraction for list [...] or dict {...}
    """
    if not raw_response or not isinstance(raw_response, str):
        return []

    clean = raw_response.strip()
    if "```json" in clean:
        clean = clean.split("```json")[1].split("```")[0].strip()
    elif "```" in clean:
        clean = clean.split("```")[1].split("```")[0].strip()

    try:
        data = json.loads(clean)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            if "candidates" in data and isinstance(data["candidates"], list):
                return [x for x in data["candidates"] if isinstance(x, dict)]
            for v in data.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    return v
            return []
    except Exception as e:
        if on_log:
            on_log(f"[AVISO] Tentando extração avançada de candidatos JSON ({e})...")

    # Fallback 1: Direct JSON list [...]
    match_list = re.search(r'\[\s*\{.*\}\s*\]', raw_response, re.DOTALL)
    if match_list:
        try:
            data = json.loads(match_list.group(0))
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
        except Exception:
            pass

    # Fallback 2: JSON object {...}
    match_dict = re.search(r'\{.*\}', raw_response, re.DOTALL)
    if match_dict:
        try:
            data = json.loads(match_dict.group(0))
            if isinstance(data, dict):
                if "candidates" in data and isinstance(data["candidates"], list):
                    return [x for x in data["candidates"] if isinstance(x, dict)]
                for v in data.values():
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        return v
        except Exception:
            pass

    return []


def enforce_cut_mode_durations(
    candidates: List[Dict[str, Any]],
    cut_mode: str,
    video_duration: float = 0.0,
    on_log: Optional[Callable[[str], None]] = None,
) -> List[Dict[str, Any]]:
    """
    Enforces strict cut_mode duration rules on candidates.
    If cut_mode == 'narrative_arc' and a candidate duration < 120s,
    intelligently expands the window around the climax scene so it spans 2.5 to 3.5 minutes.
    """
    if not candidates:
        return []

    for cand in candidates:
        max_dur = video_duration if video_duration > 0 else 0.0
        start_sec, dur_sec, _, _, _ = parse_candidate_times(cand, max_duration=max_dur)

        if cut_mode == "narrative_arc":
            # Must be strictly between 120s (2m) and 300s (5m)
            if dur_sec < 120.0:
                target_dur = 180.0  # 3 minutes default sweet spot
                if max_dur > 0 and target_dur > max_dur:
                    target_dur = max_dur

                deficit = target_dur - dur_sec
                expand_back = deficit * 0.50
                expand_fwd = deficit * 0.50

                new_start = max(0.0, start_sec - expand_back)
                new_end = start_sec + dur_sec + expand_fwd

                if max_dur > 0 and new_end > max_dur:
                    new_end = max_dur
                    new_start = max(0.0, new_end - target_dur)

                new_dur = new_end - new_start
                st_str = _seconds_to_time_str(new_start)
                et_str = _seconds_to_time_str(new_end)
                dur_str = f"{int(new_dur // 60)}m {int(new_dur % 60):02d}s"

                cand["start_time"] = st_str
                cand["end_time"] = et_str
                cand["duration"] = dur_str
                cand["estimated_range"] = f"{st_str} -> {et_str}"
                cand.pop("time_range", None)
                cand.pop("range", None)
                cand.pop("timestamps", None)

                genre = cand.get("genre", "")
                if "Arco" not in genre and "Mini-Filme" not in genre:
                    cand["genre"] = f"Mini-Filme / {genre}" if genre else "Mini-Filme / Arco Narrativo"

                if on_log:
                    title = cand.get("title", "Trecho")
                    on_log(f"   * Trecho '{title}' expandido para formato Mini-Filme: {st_str} -> {et_str} ({dur_str})")

            elif dur_sec > 300.0:
                new_end = start_sec + 300.0
                if max_dur > 0 and new_end > max_dur:
                    new_end = max_dur
                new_dur = new_end - start_sec
                st_str = _seconds_to_time_str(start_sec)
                et_str = _seconds_to_time_str(new_end)
                dur_str = f"{int(new_dur // 60)}m {int(new_dur % 60):02d}s"

                cand["end_time"] = et_str
                cand["duration"] = dur_str
                cand["estimated_range"] = f"{st_str} -> {et_str}"

        elif cut_mode == "continuous":
            if dur_sec > 75.0:
                new_end = start_sec + 75.0
                if max_dur > 0 and new_end > max_dur:
                    new_end = max_dur
                new_dur = new_end - start_sec
                et_str = _seconds_to_time_str(new_end)
                dur_str = f"{int(new_dur // 60)}m {int(new_dur % 60):02d}s" if new_dur >= 60 else f"{int(new_dur)}s"
                cand["end_time"] = et_str
                cand["duration"] = dur_str
                cand["estimated_range"] = f"{_seconds_to_time_str(start_sec)} -> {et_str}"

        elif cut_mode == "multi_part":
            if dur_sec > 90.0:
                new_end = start_sec + 90.0
                if max_dur > 0 and new_end > max_dur:
                    new_end = max_dur
                new_dur = new_end - start_sec
                et_str = _seconds_to_time_str(new_end)
                dur_str = f"{int(new_dur // 60)}m {int(new_dur % 60):02d}s" if new_dur >= 60 else f"{int(new_dur)}s"
                cand["end_time"] = et_str
                cand["duration"] = dur_str
                cand["estimated_range"] = f"{_seconds_to_time_str(start_sec)} -> {et_str}"

        elif cut_mode == "dynamic_montage":
            if dur_sec > 70.0:
                new_end = start_sec + 70.0
                if max_dur > 0 and new_end > max_dur:
                    new_end = max_dur
                new_dur = new_end - start_sec
                et_str = _seconds_to_time_str(new_end)
                dur_str = f"{int(new_dur // 60)}m {int(new_dur % 60):02d}s" if new_dur >= 60 else f"{int(new_dur)}s"
                cand["end_time"] = et_str
                cand["duration"] = dur_str
                cand["estimated_range"] = f"{_seconds_to_time_str(start_sec)} -> {et_str}"

        elif cut_mode == "verbal_duel":
            if dur_sec > 80.0:
                new_end = start_sec + 80.0
                if max_dur > 0 and new_end > max_dur:
                    new_end = max_dur
                new_dur = new_end - start_sec
                et_str = _seconds_to_time_str(new_end)
                dur_str = f"{int(new_dur // 60)}m {int(new_dur % 60):02d}s" if new_dur >= 60 else f"{int(new_dur)}s"
                cand["end_time"] = et_str
                cand["duration"] = dur_str
                cand["estimated_range"] = f"{_seconds_to_time_str(start_sec)} -> {et_str}"

        elif cut_mode == "context":
            # Permite cenas completas com contexto de conversa e luta de 60s até 150s (2m 30s)
            if dur_sec > 150.0:
                new_end = start_sec + 150.0
                if max_dur > 0 and new_end > max_dur:
                    new_end = max_dur
                new_dur = new_end - start_sec
                et_str = _seconds_to_time_str(new_end)
                dur_str = f"{int(new_dur // 60)}m {int(new_dur % 60):02d}s" if new_dur >= 60 else f"{int(new_dur)}s"
                cand["end_time"] = et_str
                cand["duration"] = dur_str
                cand["estimated_range"] = f"{_seconds_to_time_str(start_sec)} -> {et_str}"
            elif dur_sec < 45.0 and start_sec >= 10.0:
                # Pre-padding inteligente: se o corte veio muito curto (<45s), expande até 10s para trás
                # para garantir que a fala introdutória ou provocação que gerou o clímax não seja comida
                pad = min(12.0, start_sec)
                new_start = start_sec - pad
                new_dur = (start_sec + dur_sec) - new_start
                st_str = _seconds_to_time_str(new_start)
                et_str = _seconds_to_time_str(start_sec + dur_sec)
                dur_str = f"{int(new_dur // 60)}m {int(new_dur % 60):02d}s" if new_dur >= 60 else f"{int(new_dur)}s"
                cand["start_time"] = st_str
                cand["end_time"] = et_str
                cand["duration"] = dur_str
                cand["estimated_range"] = f"{st_str} -> {et_str}"

        # Always ensure duration and estimated_range are clean and present
        if not cand.get("duration"):
            _, _, st_val, et_val, calc_dur = parse_candidate_times(cand, max_duration=max_dur)
            cand["duration"] = calc_dur
            if not cand.get("estimated_range"):
                cand["estimated_range"] = f"{st_val} -> {et_val}"

    return candidates


def analyze_episode(
    video_path: str,
    context: str = "",
    mode: str = "top3",
    cut_mode: str = "context",
    video_duration: float = 0.0,
    ffmpeg_bin: str = "ffmpeg",
    on_progress: Optional[Callable[[float, str], None]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    excluded_ranges: Optional[List[str]] = None,
    content_type: str = "general"
) -> tuple:
    """
    Main Director AI pipeline:
    1. Extract audio
    2. Transcribe with Whisper
    3. Search Lore
    4. AI analyzes episode and returns candidates based on mode, cut_mode and content_type
    Returns: (candidates, transcript, lore)
    """
    def _log(msg):
        if on_log:
            on_log(msg)

    def _prog(pct, msg):
        if on_progress:
            on_progress(pct, msg)

    mode_label = "Top 3 do Episódio" if mode == "top3" else "Smart Cortes (Curadoria Sincera)"
    cut_mode_label = {
        "context": "Contexto Completo (Conversa & Luta 1 a 2.5 min)",
        "continuous": "Contínuo (Sem cortes internos)",
        "narrative_arc": "Mini-Filme / Arco Narrativo (2 a 5 min)",
        "multi_part": "Série em Partes (Multi-Partes 1, 2, 3)",
        "dynamic_montage": "Corte Dinâmico (Montagem Ágil)",
        "verbal_duel": "Duelo Verbal & Revelação",
    }.get(cut_mode, cut_mode)

    type_label_map = {
        "general": "Geral (Padrão Viral)",
        "action": "Ação (Batalhas & Lutas)",
        "comedy": "Engraçado (Comédia & Humor)",
        "romance": "Romance (Química & Tensão)",
        "sensual": "Sensual (Ecchi & Fanservice)"
    }
    content_type_label = type_label_map.get(content_type, content_type)

    try:
        from ai_cache_hub import ai_cache
    except Exception:
        ai_cache = None

    # 0. Checagem de Cache de Cortes Prontos (0 TOKENS GASTOS)
    # Se o usuário já gerou cortes com esta configuração para este vídeo, carrega imediatamente
    cache_key = f"director_cuts_{mode}_{cut_mode}_{content_type}"
    if ai_cache and not excluded_ranges:
        cached_candidates = ai_cache.get(video_path, cache_key)
        if cached_candidates and isinstance(cached_candidates, list) and len(cached_candidates) > 0:
            _prog(100, "Concluído (recuperado do cache)!")
            _log(f"[CACHE 24H] {len(cached_candidates)} cortes carregados do cache para [{cut_mode_label}]! (0 TOKENS GASTOS)")
            _log("   💡 Dica: Se quiser novos cortes alternativos, use o botão 'Novos Cortes' ou 'Limpar Cache (IA)'.")
            cached_trans = ai_cache.get(video_path, "director_transcript") or ""
            cached_lore = ai_cache.get(video_path, "anime_lore") or ""
            return cached_candidates, cached_trans, cached_lore

    _prog(5, "Extraindo áudio do episódio...")
    _log("[DIRETOR IA] Iniciando análise...")
    _log(f"   Vídeo: {os.path.basename(video_path)}")
    if context:
        _log(f"   Contexto fornecido: {context}")
    _log(f"   Curadoria: {mode_label}")
    _log(f"   Modo de Corte: {cut_mode_label}")
    _log(f"   Foco do Conteúdo: {content_type_label}")

    # 1 & 2. Transcribe falas (check cache first)
    _prog(15, "Verificando transcrição de áudio...")
    transcript = ""
    if ai_cache:
        cached_dt = ai_cache.get(video_path, "director_transcript")
        if cached_dt and isinstance(cached_dt, str):
            transcript = cached_dt
            _log("[CACHE 24H] Transcrição do episódio recuperada do cache (0 tokens gastos)!")
        else:
            cached_trans = ai_cache.get(video_path, "transcription")
            if cached_trans and isinstance(cached_trans, dict):
                words = cached_trans.get("words", [])
                if words:
                    lines = []
                    curr = []
                    st = None
                    for w in words:
                        s = float(w.get("start", 0.0))
                        e = float(w.get("end", 0.0))
                        txt = w.get("word") if "word" in w else w.get("text", "")
                        if st is None:
                            st = s
                        curr.append(txt)
                        if len(curr) >= 8 or (txt and txt[-1] in ".!?"):
                            lines.append(f"[{_seconds_to_time_str(st)} -> {_seconds_to_time_str(e)}] {' '.join(curr)}")
                            curr = []
                            st = None
                    if curr and st is not None:
                        lines.append(f"[{_seconds_to_time_str(st)} -> {_seconds_to_time_str(e)}] {' '.join(curr)}")
                    transcript = "\n".join(lines)
                    _log("[CACHE 24H] Falas e diálogos sincronizados a partir do cache Whisper!")

    if not transcript:
        # 1. Extract audio
        audio_path = None
        try:
            _prog(20, "Extraindo áudio do episódio...")
            audio_path = extract_audio(video_path, ffmpeg_bin=ffmpeg_bin)
            _log("[OK] Áudio extraído com sucesso")
        except Exception as e:
            _log(f"[AVISO] Erro na extração de áudio: {e}")

        # 2. Transcribe
        _prog(35, "Transcrevendo falas e timestamps...")
        if audio_path and os.path.exists(audio_path):
            transcript = transcribe_video_audio(audio_path, on_log=_log)
            if transcript and ai_cache:
                ai_cache.set(video_path, "director_transcript", transcript)
            try:
                os.remove(audio_path)
            except Exception:
                pass

    if transcript:
        lines_count = len(transcript.splitlines())
        _log(f"[OK] Transcrição concluída ({lines_count} falas mapeadas com timestamps)")
    else:
        _log("[AVISO] Transcrição não gerou falas (vídeo mudo ou sem suporte). Prosseguindo com análise contextual...")

    # 3. Lore & Hype
    _prog(50, "Pesquisando lore e reações da internet...")
    lore = ""
    if context:
        lore = fetch_episode_lore(context, on_log=_log)
        if lore:
            _log("[OK] Lore e momentos mais comentados recuperados da internet")

    # 4. AI Curation
    _prog(70, "Diretor IA analisando os melhores momentos...")
    _log(f"[IA] Avaliando picos de retenção no modo [{cut_mode_label}]...")

    dur_str = _seconds_to_time_str(video_duration) if video_duration > 0 else ""
    prompt = build_candidates_prompt(
        mode=mode,
        context=context,
        lore=lore,
        transcript=transcript,
        video_duration_str=dur_str,
        cut_mode=cut_mode,
        excluded_ranges=excluded_ranges or [],
        genre=content_type
    )

    raw_response = call_ai_text(prompt, on_log=_log, max_tokens=8192)

    _prog(90, "Formatando candidatos...")
    candidates = _parse_ai_candidates_json(raw_response, on_log=_log)

    # Enforce strict cut_mode bounds (e.g. 2-5m for narrative_arc)
    candidates = enforce_cut_mode_durations(candidates, cut_mode=cut_mode, video_duration=video_duration, on_log=_log)

    if ai_cache and candidates:
        cache_key = f"director_cuts_{mode}_{cut_mode}_{content_type}"
        ai_cache.set(video_path, cache_key, candidates)

    _prog(100, "Concluído!")
    _log(f"[CONCLUÍDO] {len(candidates)} candidatos identificados pelo Diretor.")
    return candidates, transcript, lore


def analyze_episode_reroll(
    context: str,
    transcript: str,
    lore: str,
    mode: str = "top3",
    cut_mode: str = "context",
    video_duration: float = 0.0,
    excluded_ranges: Optional[List[str]] = None,
    on_progress: Optional[Callable[[float, str], None]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    content_type: str = "general"
) -> List[Dict[str, Any]]:
    """
    Fast re-roll: reuses cached transcript and lore to ask the AI for NEW cuts,
    explicitly excluding previously shown time ranges. Skips audio extraction and
    re-transcription, making this ~5x faster than a full analysis.
    """
    def _log(msg):
        if on_log:
            on_log(msg)

    def _prog(pct, msg):
        if on_progress:
            on_progress(pct, msg)

    type_label_map = {
        "general": "Geral (Padrão Viral)",
        "action": "Ação (Batalhas & Lutas)",
        "comedy": "Engraçado (Comédia & Humor)",
        "romance": "Romance (Química & Tensão)",
        "sensual": "Sensual (Ecchi & Fanservice)"
    }
    content_type_label = type_label_map.get(content_type, content_type)
    cut_mode_label = {
        "context": "Contexto Completo (Conversa & Luta 1 a 2.5 min)",
        "continuous": "Contínuo (Sem cortes internos)",
        "narrative_arc": "Mini-Filme / Arco Narrativo (2 a 5 min)",
        "multi_part": "Série em Partes (Multi-Partes 1, 2, 3)",
        "dynamic_montage": "Corte Dinâmico (Montagem Ágil)",
        "verbal_duel": "Duelo Verbal & Revelação",
    }.get(cut_mode, cut_mode)

    excl_display = ", ".join(excluded_ranges) if excluded_ranges else "nenhum"
    _log(f"[NOVOS CORTES] Gerando novos cortes (Modo: {cut_mode_label} | Foco: {content_type_label} | Excluídos: {excl_display})...")
    _prog(30, "Construindo novo prompt com trechos excluídos...")

    dur_str = _seconds_to_time_str(video_duration) if video_duration > 0 else ""
    prompt = build_candidates_prompt(
        mode=mode,
        context=context,
        lore=lore,
        transcript=transcript,
        video_duration_str=dur_str,
        cut_mode=cut_mode,
        excluded_ranges=excluded_ranges or [],
        genre=content_type
    )

    _prog(60, "IA buscando novos trechos alternativos...")
    raw_response = call_ai_text(prompt, on_log=_log, max_tokens=8192)

    _prog(90, "Formatando novos candidatos...")
    candidates = _parse_ai_candidates_json(raw_response, on_log=_log)

    # Enforce strict cut_mode bounds (e.g. 2-5m for narrative_arc)
    candidates = enforce_cut_mode_durations(candidates, cut_mode=cut_mode, video_duration=video_duration, on_log=_log)

    _prog(100, "Novos cortes gerados!")
    _log(f"[CONCLUÍDO] {len(candidates)} novos cortes alternativos identificados.")
    return candidates


def cut_clip_fast(
    video_path: str,
    start_time: Any,
    end_time: Any = None,
    output_path: str = "",
    duration_sec: Optional[Any] = None,
    duration: Optional[Any] = None,
    ffmpeg_bin: str = "ffmpeg"
) -> tuple[bool, str]:
    """
    Cut video clip fast.
    Supports either (start_time, end_time) OR (start_time, duration) OR (start_time, end_time, duration).
    First tries instantaneous stream copy (-c copy).
    If copy fails (container incompatibility, ASS subtitles, audio codecs),
    falls back to ultra-fast encoding (-preset ultrafast).
    Returns: (success: bool, error_msg: str)
    """
    video_path = str(video_path).strip().strip('"\'')
    if not os.path.isfile(video_path):
        return False, f"Arquivo de vídeo de entrada não encontrado: {video_path}"

    start_sec = max(0.0, _time_str_to_seconds(start_time))

    dur_val = duration_sec if duration_sec is not None else duration
    if dur_val is not None and float(dur_val) > 0:
        dur_sec = float(dur_val)
        end_sec = start_sec + dur_sec
    elif end_time is not None:
        end_val = _time_str_to_seconds(end_time)
        if end_val > start_sec:
            end_sec = end_val
            dur_sec = end_sec - start_sec
        elif 0.0 < end_val <= 7200.0 and start_sec >= end_val:
            # Caller passed duration as end_time parameter! (e.g. start=255s, dur=180s)
            dur_sec = end_val
            end_sec = start_sec + dur_sec
        else:
            dur_sec = 60.0
            end_sec = start_sec + 60.0
    else:
        dur_sec = 60.0
        end_sec = start_sec + 60.0

    # Ensure output directory exists
    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # Clean existing failed output
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except Exception:
            pass

    # 1. Fast stream copy (instant, 0.2s)
    # -map 0:v:0 -map 0:a:0? avoids copying incompatible subtitle/data streams into MP4
    cmd_copy = [
        ffmpeg_bin,
        "-ss", str(round(start_sec, 3)),
        "-i", video_path,
        "-t", str(round(dur_sec, 3)),
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-c", "copy",
        "-sn", "-dn",
        "-map_metadata", "-1",
        "-map_chapters", "-1",
        "-avoid_negative_ts", "make_zero",
        output_path,
        "-y"
    ]
    res = subprocess.run(
        cmd_copy, capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    )
    if res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
        return True, ""

    # 2. Fallback: Ultra-fast re-encode (guaranteed to work with any MKV, subtitles, strange codecs)
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except Exception:
            pass

    cmd_encode = [
        ffmpeg_bin,
        "-ss", str(round(start_sec, 3)),
        "-i", video_path,
        "-t", str(round(dur_sec, 3)),
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-sn", "-dn",
        "-map_metadata", "-1",
        "-map_chapters", "-1",
        "-avoid_negative_ts", "make_zero",
        output_path,
        "-y"
    ]
    res2 = subprocess.run(
        cmd_encode, capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    )
    if res2.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
        return True, ""

    err_msg = ""
    if res2.stderr:
        err_msg = res2.stderr.decode('utf-8', errors='replace')[-500:]
    elif res.stderr:
        err_msg = res.stderr.decode('utf-8', errors='replace')[-500:]
    else:
        err_msg = "FFmpeg não conseguiu gerar o arquivo de corte."

    return False, err_msg


def preview_clip_ffplay(
    video_path: str,
    start_time: Any,
    end_time: Any = None,
    duration: Optional[Any] = None,
    ffplay_bin: str = "ffplay"
) -> bool:
    """
    Open FFplay directly at the specified segment.
    """
    video_path = str(video_path).strip().strip('"\'')
    start_sec = max(0.0, _time_str_to_seconds(start_time))
    if duration is not None and float(duration) > 0:
        dur_sec = float(duration)
    elif end_time is not None:
        end_val = _time_str_to_seconds(end_time)
        if end_val > start_sec:
            dur_sec = end_val - start_sec
        elif 0.0 < end_val <= 7200.0 and start_sec >= end_val:
            dur_sec = end_val
        else:
            dur_sec = 60.0
    else:
        dur_sec = 60.0

    dur_sec = max(1.0, dur_sec)

    cmd = [
        ffplay_bin,
        "-ss", str(round(start_sec, 3)),
        "-t", str(round(dur_sec, 3)),
        "-autoexit",
        video_path
    ]
    try:
        subprocess.Popen(cmd)
        return True
    except Exception:
        return False

