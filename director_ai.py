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
        on_log("🎙️ Transcrevendo áudio com Whisper Large v3 (Groq)...")

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
        on_log("🎙️ Transcrevendo com faster-whisper local (GPU/CPU)...")

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
                on_log(f"⚠ Groq Whisper falhou ({e}). Tentando transcrição local...")

    # Fallback local
    try:
        return transcribe_audio_local(audio_path, on_log)
    except Exception as e:
        if on_log:
            on_log(f"⚠ faster-whisper local falhou: {e}")
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
        base_models = [
            "gemini-3.6-flash",
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-flash-lite-latest",
            "gemini-flash-latest",
            "gemini-2.5-flash"
        ]
        gemini_models = []
        if user_model:
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
    First queries official Anime/Dorama APIs (Kitsu, Jikan, TVMaze) so even brand new 
    animes have verified synopsis, studio, rating, and plot grounding.
    """
    if not context or len(context.strip()) < 3:
        return ""

    if on_log:
        on_log(f"🔍 Pesquisando lore e metadados sobre: {context}...")

    enriched_api = ""
    try:
        from metadata_enricher import get_enriched_context_for_prompt
        enriched_api = get_enriched_context_for_prompt(context)
        if enriched_api and on_log:
            on_log("✓ Metadados oficiais obtidos via API (Kitsu / TVMaze / MAL)")
    except Exception:
        pass

    api_block = f"\n{enriched_api}\n" if enriched_api else ""

    prompt = f"""Você é um especialista em animes, doramas e cultura pop.
O usuário quer mapear os melhores momentos e reações do público sobre o seguinte episódio: "{context}"
{api_block}
Sua tarefa:
Destaque em até 3 parágrafos curtos:
1. Quais foram as cenas exatas mais comentadas desse episódio (confrontos, revelações, mortes, beijos, reações de choque)?
2. Qual cena causou mais impacto emocional ou hype nas redes sociais (Reddit, Twitter, TikTok)?
3. Seja factual. Se souber os eventos, descreva-os. Se não souber eventos específicos, utilize os metadados acima para contextualizar.

Responda em formato JSON:
{{
  "lore": "Texto com o resumo dos momentos mais comentados deste episódio"
}}
"""
    try:
        raw = call_ai_text(prompt, on_log=None)
        data = json.loads(raw)
        lore = data.get("lore", "").strip()
        if enriched_api:
            if not lore or "Lore não encontrada" in lore:
                return enriched_api
            return f"{enriched_api}\n\n[MOMENTOS DE HYPE & COMUNIDADE]\n{lore}"
        if "Lore não encontrada" in lore:
            return ""
        return lore
    except Exception:
        return enriched_api or ""


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
    "shonen_action": """
[REGRAS DE GÊnerO: AÇÃO / SHONEN]
  • Busque momentos de confronto direto, frases de efeito marcantes ("eu vou te destruir", "você não é rival para mim"), demonstração de "aura" ou poder absurdo.
  • Priorize o momento exato em que o personagem revela seu poder máximo, não a fase de preparação longa.
  • Cortes devem focar no impacto físico, reversões de luta, reações de choque dos personagens que observam.
  • Faças icônicas de vilões ou heróis têm altíssimo replay value ("Deixa eu te dizer algo...").
""",
    "romance_drama": """
[REGRAS DE GÊnerO: ROMANCE / DRAMA / DORAMA]
  • Esqueça "aura" e "confronto físico". Busque tensão romântica: aproximação física, "quase beijos", toques acidentais, quebra de espaço pessoal.
  • VULNERABILIDADE E MICRO-EXPRESSÕES: Priorize reações íntimas (rubor, desviar o olhar, choro silencioso, ciúme contido). A emoção está no rosto, não na ação.
  • HOOK ROMÂNTICO: O vídeo deve começar com a confissão mais chocante, declaração direta de amor ou momento de vulnerabilidade áxima.
  • CORTE IMPLACAVEL DE "CLIMA": Obras de romance amam longos planos contemplativos. CORTE TODOS. Se há 10s de silêncio ou contemplão, reduza para 1s de contexto e conecte imediatamente com a próxima fala forte.
""",
    "comedy": """
[REGRAS DE GÊnerO: COMÉDIA / SLICE OF LIFE]
  • Foque na quebra de expectativa (punchline) e nas reações exageradas.
  • O timing do corte é crítico: corte IMEDIATAMENTE após a reação cômica para maximizar o impacto.
  • Expresseões faciais exageradas e reações de personagens secundários têm altíssimo valor de compartilhamento.
  • Evite incluir o "setup" muito longo da piada; entre direto na punchline com 1–2 segundos mínimos de contexto.
""",
}

SNIPER_TIMESTAMP_RULES = """
[REGRA DE OURO DOS TIMESTAMPS (FLUXO SNIPER)]
1. ANCORAGEM NA TRANSCRIÇÃO: Todos os timestamps devem ser derivados da transcrição fornecida. Encontre a fala correspondente e use exatamente os tempos listados. NÃO estime ou adivinhe.
2. LEGENDAS NATIVAS: Se o vídeo tiver legendas coladas na tela (hardsubs) e a transcrição estiver dessincronizada, baseie-se na legenda visual — não na transcrição de áudio.
3. CONDENSAÇÃO: Remova silêncios e barrigas. Se a fala A termina em 04:14 e a fala B crucial começa em 04:29, registre dois trechos separados e deixe o sistema unir, eliminando os 15s de tempo morto.
4. NUNCA corte uma fala pela metade. Sempre que possível, comece no início de uma palavra e termine no fim de uma fala completa.
"""


def build_candidates_prompt(
    mode: str,
    context: str,
    lore: str,
    transcript: str,
    video_duration_str: str = "",
    cut_mode: str = "context",
    excluded_ranges: Optional[List[str]] = None,
    genre: str = "shonen_action"
) -> str:
    """Build the director curation prompt for Top 3 or Smart Cortes with cut mode and genre support."""
    lore_section = f"\n[LORE DO EPISÓDIO E REAÇÕES DOS FÃS]\n{lore}\n" if lore else ""
    ctx_section = f"\n[CONTEXTO DA OBRA / EPISÓDIO]\n{context}\n" if context else ""
    genre_rules = GENRE_RULES_DIRECTOR.get(genre, GENRE_RULES_DIRECTOR["shonen_action"])
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
[MODO DE CORTE: ARCO NARRATIVO — HISTÓRIA COMPLETA PARA COMPRESSÃO]

OBJETIVO: Identificar um bloco coeso de 3 a 20 minutos que contenha um arco dramático completo. Esse arco será depois comprimido num vídeo de 1 a 2 minutos na etapa de Mastercut.

ESTRUTURA OBRIGATÓRIA DO ARCO ESCOLHIDO:
  • ABERTURA: Evento que desencadeia o conflito central (não pode começar no meio de um diálogo sem contexto).
  • DESENVOLVIMENTO: A tensão deve escalar progressivamente.
  • CLÍMAX: Momento de pico claro — confronto decisivo, revelação, virada emocional.
  • RESOLUÇÃO (opcional): Reação ou consequência imediata após o clímax.

CRITÉRIOS DE SELEÇÃO:
  • Prefira arcos com conflito humano/emocional claro — são mais comprimiíveis sem perder sentido.
  • O arco deve fazer sentido sozinho, mesmo sem o contexto do episódio completo.
  • Duração mínima: 3 minutos. Duração máxima: 20 minutos.

CAMPOS JSON:
  • genre: mencione o tipo do arco (ex: "Arco Narrativo: Batalha Final e Sacrifício").
  • description: descreva o arco em 2 frases — o que acontece e qual é o pico emocional.
"""

    elif cut_mode == "continuous":
        cut_mode_rules = """
[MODO DE CORTE: CONTÍNUO — CENA ÚNICA SEM EDIÇÃO INTERNA]

OBJETIVO: Identificar trechos que funcionem como UMA ÚNICA CENA FLUÍDA (30 a 90 segundos), sem corte interno.

⚠️ LIMITES OBRIGATÓRIOS DESTE MODO — NÃO NEGOCIÁVEIS:
  ✗ NUNCA sugira cortes com duração superior a 90 segundos (1m 30s) neste modo.
  ✗ NUNCA use "Arco Narrativo" no campo genre. Este modo é para cenas curtas e fluidas.
  ✗ NUNCA selecione um trecho de 2, 3 ou mais minutos.
  ✓ genre deve descrever o tipo da cena: ex. "Ação / Confronto", "Comédia / Reação", "Emoção / Confissão".

REGRAS DE INÍCIO E FIM NATURAIS:
  • INÍCIO: Primeira palavra de uma fala marcante; beat de ação claro; reação facial expressiva.
  • FIM: Última palavra de uma fala completa; pausa dramática pós-clímax; fade/black; reação final de personagem.
  • A cena deve ter emoção uniforme do início ao fim — sem trechos "mortos" no meio.
  • Duração ideal: 30–60s para Shorts/Reels. Até 90s se a cena justificar.
"""

    else:  # context (default)
        cut_mode_rules = """
[MODO DE CORTE: CONTEXTO — MINI-HISTÓRIA COM NARRATIVA IN MEDIA RES]

OBJETIVO: Identificar trechos de 45 segundos a 2 minutos que contem uma MINI-HISTÓRIA COMPLETA usando a estrutura "In Media Res" para máxima retenção.

⚠️ LIMITES OBRIGATÓRIOS DESTE MODO — NÃO NEGOCIÁVEIS:
  ✗ NUNCA sugira cortes com duração superior a 2 minutos (2m 00s).
  ✗ NUNCA use "Arco Narrativo" no campo genre.
  ✓ genre deve descrever o tipo emocional da cena: ex. "Tensão / Confronto", "Drama / Revelação".

ESTRUTURA IN MEDIA RES (A REGRA DE OURO DA RETENÇÃO):
  1. GANCHO IN MEDIA RES (0–3s): Começa EXATAMENTE no milissegundo da fala de maior impacto, revelação bombástica ou clímax visual — criando a dúvida imediata: 'Como a história chegou aqui?'.
  2. CONTEXTO CONDENSADO (3s–20s): Volte no tempo. Mostre o setup mínimo necessário para o espectador entender o conflito. CORTE A GORDURA: remova silêncios, andanças e falas inúteis. Emende a fala A com a fala C se B for irrelevante.
  3. ESCALADA (20s–45s): Mostre a tensão subindo. Reações dos personagens, confronto se intensificando.
  4. PAYOFF/CLÍMAX (45s–60s): O momento principal explode com todo o contexto construído. O espectador entende o peso do que está acontecendo.
  5. LOOP VALUE: O encerramento deve criar uma "pergunta no ar" ou "deixa" que se conecte com o gancho inicial, estimulando o replay.

REGRAS DE CONDENSAÇÃO (SEJA IMPIEDOSO):
  • NUNCA selecione 40s contínuos de uma mesma cena se houver "barriga" (silêncios, encaradas sem fala, transições lentas).
  • CONDENSE: Pegue a frase de ameaça e emende diretamente com a reação, pulando os 15s de silêncio entre elas.
  • O resultado deve parecer um "Trailer Emocional" hiper-focado: emoção de 20 minutos em 50 segundos.
  • Duração ideal: 45–90s. Até 2 minutos se a narrativa justificar.
"""


    if mode == "top3":
        task_rules = f"""TAREFA: Você é um Diretor de Conteúdo e Editor Profissional especializado em cortes virais para TikTok, Reels e YouTube Shorts.
Analise a transcrição de ponta a ponta e selecione rigorosamente os TOP 3 momentos com maior potencial de viralizar deste episódio.

{cut_mode_rules}
{genre_rules}

CRITÉRIOS DOS TOP 3:
1. HOOK PODEROSO: Os primeiros 3 segundos do corte precisam ser fortes o bastante para parar o scroll. Priorize cenas que começam com uma fala marcante, uma reação expressiva ou um beat de ação claro.
2. PICO DE IMPACTO: Clímax, confrontos decisivos, revelações chocantes, mortes, comédia de timing perfeito, romance intenso.
3. RETENÇÃO ATÉ O FIM: O trecho deve manter tensão, emoção ou humor até os últimos segundos.
4. NOTA DE QUALIDADE (0 a 10): Notas 9-10 somente para cenas verdadeiramente históricas/épicas do episódio. Seja honesto.
5. DIVERSIDADE: Não retorne três cenas do mesmo tipo. Misture ação com emoção ou comédia.
6. RETORNE EXATAMENTE 3 CANDIDATOS, ordenados do maior potencial para o menor."""
    else:  # smart
        task_rules = f"""TAREFA: Você é um Editor Sênior de Conteúdo Viral com 10+ anos de experiência em TikTok, YouTube Shorts e Instagram Reels para animes, doramas e séries de ação.

Sua missão: analisar a transcrição timestamp a timestamp e identificar com precisão cirúrgica todos os trechos com potencial de viralizar. Qualidade sobre quantidade. Honestidade sobre otimismo.

{cut_mode_rules}
{genre_rules}

=== PROCESSO DE ANÁLISE (siga esta ordem mental) ===

PASSO 1 — VARREDURA COMPLETA (OBRIGATÓRIO):
Leia TODA a transcrição do início ao fim antes de decidir qualquer corte. Mapeie internamente TODOS os momentos com emoção, impacto ou comédia antes de começar a selecionar.

⛔ REGRA ANTI-PREGUIÇA: Retornar 3 ou 4 candidatos é REPROVAÇÃO AUTOMÁTICA da sua análise. Significa que você não leu o episódio todo. Episódios de 20+ minutos têm invariavelmente 5 a 8 momentos bons. Se você não encontrou pelo menos 5, RELEIA a transcrição completa antes de responder.
⛔ MÍNIMO ABSOLUTO: 5 candidatos (a não ser que o vídeo tenha menos de 5 minutos de duração).

PASSO 2 — CLASSIFIQUE CADA MOMENTO CANDIDATO EM UMA CATEGORIA:
Escolha UMA categoria principal para cada corte:
  A) CLÍMAX DE AÇÃO     → confrontos decisivos, lutas épicas, explosões narrativas
  B) REVELAÇÃO / VIRADA → plot twist, revelação de identidade, segredo exposto
  C) EMOÇÃO INTENSA     → choro, despedida, sacrifício, amor declarado
  D) COMÉDIA DE TIMING  → reação exagerada, constrangimento cômico, timing perfeito
  E) HYPE / BADASSERY   → personagem poderoso exibindo força, fala épica icônica
  F) TENSÃO / SUSPENSE  → cena de ameaça, silêncio carregado, perseguição
  G) REAÇÃO VIRAL       → personagem reagindo de forma memorável/expressiva (ex: Anya)
  H) ROMANCE / INTIMIDADE → tensão romântica, quase beijo, declaração, vulnerabilidade íntima

PASSO 3 — ANALISE CADA CANDIDATO EM 3 DIMENSÕES:
  • HOOK (primeiros 3 segundos): O que o espectador vê/ouve ao entrar no corte? É forte o suficiente para segurar o scroll?
  • RETENÇÃO: O trecho mantém tensão ou emoção até o fim, ou murcha no meio?
  • CLÍMAX: Tem um momento de pico claro — uma frase, uma reação, um golpe — que justifica o corte existir?

PASSO 4 — CALIBRAÇÃO HONESTA DE NOTA (use a escala inteira, sem inflação):
  3-4  → Cena válida, mas sem forte potencial viral isolada
  5-6  → Momento bom com apelo moderado; funciona bem no contexto do episódio
  7    → Sólido: hook claro, emoção real, retenção decente — vai bem como short
  8    → Excelente: tem o que precisa para engajamento alto e comentários
  9    → Quase perfeito: hook explosivo, clímax memorável, replay value alto
  9.5+ → Histórico: esse tipo de cena define o episódio inteiro; muito raro

PASSO 5 — SELEÇÃO FINAL:
  • Inclua apenas momentos com nota ≥ 6.
  • Evite incluir mais de 2 cenas da mesma categoria (diversifique o conteúdo).
  • Não inclua cenas com hooks fracos (abertura num silêncio vazio, fala de transição, cena de exposição sem emoção).
  • Mínimo: 5 candidatos. Máximo: 8 candidatos.
  • Se você tem menos de 5, você NÃO terminou a varredura. Volte ao Passo 1.
  • Ordene do maior potencial para o menor.

CRITÉRIO DE DESEMPATE: Prefira cenas com FALA ICÔNICA ou REAÇÃO EXPRESSIVA — elas geram comentários e compartilhamentos."""

    return f"""{VIRAL_KNOWLEDGE_BASE}{ctx_section}{dur_section}{excluded_section}{lore_section}
{task_rules}
{SNIPER_TIMESTAMP_RULES}

[TRANSCRIÇÃO DE ÁUDIO COM TIMESTAMPS DO VÍDEO]
{transcript if transcript else "Transcrição indisponível. Baseie-se no lore do episódio e nos momentos clássicos."}

REGRAS OBRIGATÓRIAS:
- Retorne EXATAMENTE no formato JSON especificado abaixo.
- Os tempos devem ser no formato MM:SS (ex: "04:15") ou HH:MM:SS para vídeos com mais de 1 hora.
- Calcule a duração aproximada de cada corte e preencha tanto 'estimated_range' quanto 'start_time' e 'end_time'.
- NÃO repita nenhum trecho listado em [TRECHOS JÁ GERADOS — PROIBIDO REPETIR].
- Responda APENAS com o JSON, sem nenhum texto adicional.

FORMATO JSON OBRIGATÓRIO:
{{
  "candidates": [
    {{
      "id": "corte_01",
      "title": "Título atraente e instigante para o momento",
      "estimated_range": "04:15 -> 06:30",
      "start_time": "04:15",
      "end_time": "06:30",
      "duration": "2m 15s",
      "genre": "Ação / Clímax",
      "quality_score": 9,
      "viral_potential": "Altíssimo (Nota 9/10)",
      "description": "Explicação resumida do que acontece na cena.",
      "quality_reasoning": "Justificativa crítica de por que esse trecho viraliza."
    }}
  ]
}}
"""


def analyze_episode(
    video_path: str,
    context: str = "",
    mode: str = "top3",
    cut_mode: str = "context",
    video_duration: float = 0.0,
    ffmpeg_bin: str = "ffmpeg",
    on_progress: Optional[Callable[[float, str], None]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    excluded_ranges: Optional[List[str]] = None
) -> tuple:
    """
    Main Director AI pipeline:
    1. Extract audio
    2. Transcribe with Whisper
    3. Search Lore
    4. AI analyzes episode and returns candidates based on mode and cut_mode
    Returns: (candidates, transcript, lore)
    """
    def _log(msg):
        if on_log:
            on_log(msg)

    def _prog(pct, msg):
        if on_progress:
            on_progress(pct, msg)

    mode_label = "🏆 Top 3 do Episódio" if mode == "top3" else "🧠 Smart Cortes (Curadoria Sincera)"
    cut_mode_label = {
        "context": "Contexto (Mini-História)",
        "continuous": "Contínuo (Sem cortes internos)",
        "narrative_arc": "Arco Narrativo (3-20 min)"
    }.get(cut_mode, cut_mode)

    _prog(5, "Extraindo áudio do episódio...")
    _log("🎬 Iniciando análise com Diretor IA...")
    _log(f"   Vídeo: {os.path.basename(video_path)}")
    if context:
        _log(f"   Contexto fornecido: {context}")
    _log(f"   Curadoria: {mode_label}")
    _log(f"   Modo de Corte: {cut_mode_label}")

    # 1. Extract audio
    audio_path = None
    try:
        audio_path = extract_audio(video_path, ffmpeg_bin=ffmpeg_bin)
        _log("✓ Áudio extraído com sucesso")
    except Exception as e:
        _log(f"⚠ Erro na extração de áudio: {e}")

    # 2. Transcribe
    _prog(20, "Transcrevendo falas e timestamps...")
    transcript = ""
    if audio_path and os.path.exists(audio_path):
        transcript = transcribe_video_audio(audio_path, on_log=_log)
        try:
            os.remove(audio_path)
        except Exception:
            pass

    if transcript:
        lines_count = len(transcript.splitlines())
        _log(f"✓ Transcrição concluída ({lines_count} falas mapeadas com timestamps)")
    else:
        _log("⚠ Transcrição não gerou falas (vídeo mudo ou sem suporte). Prosseguindo com análise contextual...")

    # 3. Lore & Hype
    _prog(50, "Pesquisando lore e reações da internet...")
    lore = ""
    if context:
        lore = fetch_episode_lore(context, on_log=_log)
        if lore:
            _log("✓ Lore e momentos mais comentados recuperados da internet")

    # 4. AI Curation
    _prog(70, "Diretor IA analisando os melhores momentos...")
    _log(f"🧠 IA avaliando picos de retenção no modo [{cut_mode_label}]...")

    dur_str = _seconds_to_time_str(video_duration) if video_duration > 0 else ""
    prompt = build_candidates_prompt(
        mode=mode,
        context=context,
        lore=lore,
        transcript=transcript,
        video_duration_str=dur_str,
        cut_mode=cut_mode,
        excluded_ranges=excluded_ranges or []
    )

    raw_response = call_ai_text(prompt, on_log=_log, max_tokens=8192)

    _prog(90, "Formatando candidatos...")
    try:
        # Extract JSON substring if surrounded by markdown code blocks
        clean_json = raw_response.strip()
        if "```json" in clean_json:
            clean_json = clean_json.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_json:
            clean_json = clean_json.split("```")[1].split("```")[0].strip()

        data = json.loads(clean_json)
        candidates = data.get("candidates", [])
    except Exception as e:
        _log(f"✕ Falha ao decodificar JSON da IA: {e}")
        # Try finding json object with regex
        match = re.search(r'\{.*\}', raw_response, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                candidates = data.get("candidates", [])
            except Exception:
                candidates = []
        else:
            candidates = []

    _prog(100, "Concluído!")
    _log(f"✨ Concluído! {len(candidates)} candidatos identificados pelo Diretor.")
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
    on_log: Optional[Callable[[str], None]] = None
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

    excl_display = ", ".join(excluded_ranges) if excluded_ranges else "nenhum"
    _log(f"🔄 Gerando novos cortes (trechos excluídos: {excl_display})...")
    _prog(30, "Construindo novo prompt com trechos excluídos...")

    dur_str = _seconds_to_time_str(video_duration) if video_duration > 0 else ""
    prompt = build_candidates_prompt(
        mode=mode,
        context=context,
        lore=lore,
        transcript=transcript,
        video_duration_str=dur_str,
        cut_mode=cut_mode,
        excluded_ranges=excluded_ranges or []
    )

    _prog(60, "IA buscando novos trechos alternativos...")
    raw_response = call_ai_text(prompt, on_log=_log, max_tokens=8192)

    _prog(90, "Formatando novos candidatos...")
    try:
        clean_json = raw_response.strip()
        if "```json" in clean_json:
            clean_json = clean_json.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_json:
            clean_json = clean_json.split("```")[1].split("```")[0].strip()

        data = json.loads(clean_json)
        candidates = data.get("candidates", [])
    except Exception as e:
        _log(f"✕ Falha ao decodificar JSON da IA: {e}")
        match = re.search(r'\{.*\}', raw_response, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                candidates = data.get("candidates", [])
            except Exception:
                candidates = []
        else:
            candidates = []

    _prog(100, "Novos cortes gerados!")
    _log(f"✨ {len(candidates)} novos cortes alternativos identificados.")
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
        "-sn",
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
        "-c:a", "aac",
        "-b:a", "192k",
        "-sn",
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

