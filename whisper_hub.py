"""
whisper_hub.py - Motor Unificado de Transcrição (Groq Nuvem Otimizado + Faster-Whisper GPU Local large-v3)

Centraliza toda a transcrição de áudio/vídeo do aplicativo:
1. Cache persistente 24h (ai_cache_hub) compartilhado entre Studio, Refinador e Diretor IA.
2. Modo Groq Nuvem otimizado: comprime para MP3 64kbps mono 16kHz (1 única requisição para até ~50 min)
   e aplica retry com backoff curto para erros 429/5xx/timeout.
3. Fallback automático (ou modo 100% local) usando faster-whisper 'large-v3' acelerado por GPU CUDA
   (float16 -> int8_float16 -> int8 -> CPU), com cache do modelo em memória e vad_filter=True nativo.
"""

import os
import sys
import time
import shutil
import tempfile
import threading
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


_MODEL_LOCK = threading.Lock()
_DLL_DIR_HANDLES: List[Any] = []
_CUDA_PATHS_REGISTERED = False
_CACHED_MODEL_STATE: Dict[str, Any] = {
    "model_name": None,
    "device": None,
    "compute_type": None,
    "model": None,
}


def _ensure_cuda_dll_paths() -> None:
    """
    Registra diretórios de DLLs CUDA/cuDNN (ex: torch/lib, nvidia/*/bin, _internal)
    via os.add_dll_directory e PATH para que o faster-whisper / ctranslate2
    encontre cublas64_12.dll mesmo dentro do executável empacotado (.exe).
    """
    global _CUDA_PATHS_REGISTERED
    if _CUDA_PATHS_REGISTERED or os.name != "nt":
        return

    import glob

    candidates: List[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        candidates.extend([exe_dir, exe_dir / "_internal"])
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass))

    # 1. PyTorch local se importável diretamente
    try:
        import torch  # type: ignore
        t_lib = Path(torch.__file__).parent / "lib"
        if t_lib.is_dir():
            candidates.append(t_lib)
    except Exception:
        pass

    # 2. Raízes Python conhecidas (ex: venv, sys.prefix, AppData\Local\Programs\Python)
    site_roots: List[Path] = [Path(sys.prefix) / "Lib" / "site-packages"]
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        for py_dir in sorted(glob.glob(os.path.join(local_app, "Programs", "Python", "Python*")), reverse=True):
            site_roots.append(Path(py_dir) / "Lib" / "site-packages")

    py_exe = shutil.which("python")
    if py_exe:
        site_roots.append(Path(py_exe).parent / "Lib" / "site-packages")

    for sp in site_roots:
        if not sp.is_dir():
            continue
        t_lib = sp / "torch" / "lib"
        if t_lib.is_dir():
            candidates.append(t_lib)
        for nv_bin in glob.glob(str(sp / "nvidia" / "*" / "bin")):
            candidates.append(Path(nv_bin))

    cuda_path = os.environ.get("CUDA_PATH", "").strip()
    if cuda_path:
        candidates.append(Path(cuda_path) / "bin")

    seen = set()
    cur_path_parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    cur_path_norm = {os.path.normcase(os.path.normpath(p)) for p in cur_path_parts}

    for cand in candidates:
        try:
            resolved = cand.resolve()
        except Exception:
            resolved = cand
        if not resolved.is_dir():
            continue
        norm = os.path.normcase(os.path.normpath(str(resolved)))
        if norm in seen:
            continue
        seen.add(norm)
        if hasattr(os, "add_dll_directory"):
            try:
                _DLL_DIR_HANDLES.append(os.add_dll_directory(str(resolved)))
            except Exception:
                pass
        if norm not in cur_path_norm:
            cur_path_parts.insert(0, str(resolved))
            cur_path_norm.add(norm)

    os.environ["PATH"] = os.pathsep.join(cur_path_parts)
    _CUDA_PATHS_REGISTERED = True


def _silent_subprocess_kwargs() -> Dict[str, Any]:
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return {
            "creationflags": subprocess.CREATE_NO_WINDOW,
            "startupinfo": si,
        }
    return {}


def _find_ffmpeg_bin(name: str = "ffmpeg") -> str:
    exe_name = f"{name}.exe" if os.name == "nt" else name
    candidates: List[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        candidates.extend([
            exe_dir / exe_name,
            exe_dir / "bin" / exe_name,
            exe_dir / "_internal" / exe_name,
        ])
    base_dir = Path(__file__).parent
    candidates.extend([
        base_dir / exe_name,
        base_dir / "bin" / exe_name,
    ])
    for cand in candidates:
        if cand.exists():
            return str(cand)
    found = shutil.which(name)
    return found if found else name


def get_media_duration_seconds(media_path: str) -> float:
    """Retorna a duração do arquivo de mídia em segundos via ffprobe."""
    ffprobe_bin = _find_ffmpeg_bin("ffprobe")
    try:
        res = subprocess.run(
            [
                ffprobe_bin, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(media_path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            **_silent_subprocess_kwargs(),
        )
        val = res.stdout.strip()
        return float(val) if val else 0.0
    except Exception:
        return 0.0


def _extract_audio_file(
    media_path: str,
    fmt: str = "mp3",
    on_log: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """
    Extrai áudio 16kHz mono do vídeo/áudio de entrada.
    - fmt='mp3': 64kbps (~0.48 MB/min), ideal para enviar à Groq em 1 única requisição.
    - fmt='wav': pcm_s16le, ideal para leitura instantânea pelo faster-whisper local.
    """
    ffmpeg_bin = _find_ffmpeg_bin("ffmpeg")
    suffix = ".mp3" if fmt == "mp3" else ".wav"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp_path = tmp.name
    tmp.close()

    if fmt == "mp3":
        cmd = [
            ffmpeg_bin, "-y", "-i", str(media_path),
            "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k",
            tmp_path,
        ]
    else:
        cmd = [
            ffmpeg_bin, "-y", "-i", str(media_path),
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            tmp_path,
        ]

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            timeout=180,
            **_silent_subprocess_kwargs(),
        )
        if res.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            return tmp_path
    except Exception as exc:
        if on_log:
            on_log(f"[AVISO] Falha ao extrair áudio ({fmt}): {exc}")

    try:
        Path(tmp_path).unlink(missing_ok=True)
    except Exception:
        pass
    return None


def unload_local_whisper_model() -> None:
    """Libera o modelo faster-whisper da VRAM quando necessário."""
    with _MODEL_LOCK:
        _CACHED_MODEL_STATE["model"] = None
        _CACHED_MODEL_STATE["model_name"] = None
        _CACHED_MODEL_STATE["device"] = None
        _CACHED_MODEL_STATE["compute_type"] = None
        try:
            import gc
            gc.collect()
        except Exception:
            pass


def _candidate_device_configs() -> List[Tuple[str, str]]:
    _ensure_cuda_dll_paths()
    has_cuda = False
    try:
        import ctranslate2
        has_cuda = ctranslate2.get_cuda_device_count() > 0
    except Exception:
        has_cuda = False

    candidates: List[Tuple[str, str]] = []
    if has_cuda:
        candidates.extend([
            ("cuda", "float16"),
            ("cuda", "int8_float16"),
            ("cuda", "int8"),
        ])
    candidates.append(("cpu", "int8"))
    return candidates


def get_local_whisper_model(
    model_name: str = "large-v3",
    on_log: Optional[Callable[[str], None]] = None,
    force_device: Optional[str] = None,
    force_compute_type: Optional[str] = None,
) -> Tuple[Any, str, str]:
    """
    Carrega e mantém em cache na memória o modelo faster-whisper.
    Prioriza GPU CUDA (float16 -> int8_float16 -> int8) e faz fallback para CPU (int8).
    """
    _ensure_cuda_dll_paths()
    with _MODEL_LOCK:
        cached = _CACHED_MODEL_STATE.get("model")
        c_dev = str(_CACHED_MODEL_STATE.get("device") or "")
        c_ctype = str(_CACHED_MODEL_STATE.get("compute_type") or "")
        if cached is not None and _CACHED_MODEL_STATE.get("model_name") == model_name:
            if (not force_device or c_dev == force_device) and (not force_compute_type or c_ctype == force_compute_type):
                if on_log:
                    on_log(f"⚡ [WHISPER LOCAL] Usando modelo '{model_name}' já em cache ({c_dev.upper()} {c_ctype})!")
                return cached, c_dev, c_ctype

        from faster_whisper import WhisperModel

        if force_device and force_compute_type:
            candidates = [(force_device, force_compute_type)]
        else:
            candidates = _candidate_device_configs()

        last_err: Optional[Exception] = None
        for device, compute_type in candidates:
            try:
                if on_log:
                    on_log(
                        f"⚡ [WHISPER LOCAL] Carregando modelo '{model_name}' "
                        f"em {device.upper()} ({compute_type})..."
                    )
                model = WhisperModel(model_name, device=device, compute_type=compute_type)
                _CACHED_MODEL_STATE["model_name"] = model_name
                _CACHED_MODEL_STATE["device"] = device
                _CACHED_MODEL_STATE["compute_type"] = compute_type
                _CACHED_MODEL_STATE["model"] = model
                return model, device, compute_type
            except Exception as exc:
                last_err = exc
                if on_log:
                    on_log(f"[AVISO] Falha ao iniciar '{model_name}' em {device}/{compute_type}: {exc}")

        raise RuntimeError(f"Não foi possível carregar faster-whisper '{model_name}': {last_err}")


def _run_faster_whisper_transcribe(
    model: Any,
    audio_path: str,
    model_name: str,
    device: str,
    compute_type: str,
    language: Optional[str],
    on_log: Optional[Callable[[str], None]],
) -> Dict[str, Any]:
    transcribe_kwargs: Dict[str, Any] = {
        "beam_size": 5,
        "word_timestamps": True,
        "vad_filter": True,
        "vad_parameters": {"min_silence_duration_ms": 500},
        "condition_on_previous_text": False,
    }
    if language:
        transcribe_kwargs["language"] = language

    if on_log:
        on_log(f"🎙️ [WHISPER LOCAL] Transcrevendo com '{model_name}' ({device.upper()} {compute_type}, VAD ativo)...")

    t0 = time.time()
    segments_iter, info = model.transcribe(str(audio_path), **transcribe_kwargs)

    words: List[Dict[str, Any]] = []
    segments: List[Dict[str, Any]] = []
    full_text_parts: List[str] = []

    for seg in segments_iter:
        seg_text = (seg.text or "").strip()
        if seg_text:
            segments.append({
                "start": round(float(seg.start), 3),
                "end": round(float(seg.end), 3),
                "text": seg_text,
            })
            full_text_parts.append(seg_text)

        if getattr(seg, "words", None):
            for w in seg.words:
                w_txt = (w.word or "").strip()
                if not w_txt:
                    continue
                words.append({
                    "word": w_txt,
                    "text": w_txt,
                    "start": round(float(w.start), 3),
                    "end": round(float(w.end), 3),
                })
        elif seg_text:
            words.append({
                "word": seg_text,
                "text": seg_text,
                "start": round(float(seg.start), 3),
                "end": round(float(seg.end), 3),
            })

    elapsed = time.time() - t0
    duration = float(getattr(info, "duration", 0.0) or 0.0)
    full_text = " ".join(full_text_parts).strip()

    if on_log:
        on_log(
            f"[OK] Whisper Local '{model_name}' ({device.upper()}) concluiu em {elapsed:.1f}s: "
            f"{len(words)} palavras mapeadas!"
        )

    return {
        "words": words,
        "segments": segments,
        "full_text": full_text,
        "duration": duration,
        "source": f"local_{device}",
    }


def transcribe_local_whisper(
    audio_path: str,
    model_name: str = "large-v3",
    language: Optional[str] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    Transcreve áudio usando faster-whisper local com Silero VAD nativo (vad_filter=True)
    para máxima velocidade e precisão de timestamps sem alucinações em silêncios.
    Inclui fallback automático durante a inferência (CUDA float16 -> int8_float16 -> CPU int8).
    """
    _ensure_cuda_dll_paths()

    # Tenta modelo em cache primeiro (se existir), depois percorre os candidatos de fallback
    attempted: List[Tuple[str, str]] = []
    with _MODEL_LOCK:
        cached = _CACHED_MODEL_STATE.get("model")
        c_dev = str(_CACHED_MODEL_STATE.get("device") or "")
        c_ctype = str(_CACHED_MODEL_STATE.get("compute_type") or "")
        has_cached = cached is not None and _CACHED_MODEL_STATE.get("model_name") == model_name and c_dev and c_ctype

    candidates = _candidate_device_configs()
    if has_cached and (c_dev, c_ctype) in candidates:
        candidates = [(c_dev, c_ctype)] + [c for c in candidates if c != (c_dev, c_ctype)]

    last_err: Optional[Exception] = None
    for device, compute_type in candidates:
        if (device, compute_type) in attempted:
            continue
        attempted.append((device, compute_type))
        try:
            model, used_dev, used_ctype = get_local_whisper_model(
                model_name=model_name,
                on_log=on_log,
                force_device=device,
                force_compute_type=compute_type,
            )
            return _run_faster_whisper_transcribe(
                model=model,
                audio_path=audio_path,
                model_name=model_name,
                device=used_dev,
                compute_type=used_ctype,
                language=language,
                on_log=on_log,
            )
        except Exception as exc:
            last_err = exc
            unload_local_whisper_model()
            if on_log:
                on_log(f"[AVISO] Whisper Local '{model_name}' falhou em {device.upper()} ({compute_type}): {exc}")

    raise RuntimeError(f"Todas as tentativas de Whisper Local '{model_name}' falharam: {last_err}")


def transcribe_groq_whisper(
    audio_path: str,
    groq_key: str,
    model_name: str = "whisper-large-v3",
    language: Optional[str] = None,
    timeout: int = 60,
    max_retries: int = 2,
    on_log: Optional[Callable[[str], None]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Transcreve áudio via Groq Whisper API com envio compacto (MP3) e retry automático
    em erros 429 / 5xx / timeout antes de acionar fallback local.
    """
    import requests

    if not groq_key or not groq_key.strip().startswith("gsk_"):
        return None

    clean_key = groq_key.strip().splitlines()[0].strip().strip("\"'")
    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {clean_key}"}

    file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    if file_size_mb > 24.0:
        if on_log:
            on_log(f"[WHISPER GROQ] Arquivo ({file_size_mb:.1f} MB) excede limite de 24 MB.")
        return None

    mime_type = "audio/mpeg" if str(audio_path).lower().endswith(".mp3") else "audio/wav"

    for attempt in range(max_retries + 1):
        try:
            with open(audio_path, "rb") as f:
                files = {"file": (os.path.basename(audio_path), f, mime_type)}
                data: List[Tuple[str, str]] = [
                    ("model", model_name),
                    ("response_format", "verbose_json"),
                    ("temperature", "0.0"),
                    ("timestamp_granularities[]", "word"),
                    ("timestamp_granularities[]", "segment"),
                ]
                if language:
                    data.append(("language", language))

                resp = requests.post(
                    url,
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=timeout,
                )

            if resp.status_code == 200:
                res_json = resp.json()
                words: List[Dict[str, Any]] = []
                segments: List[Dict[str, Any]] = []

                for seg in res_json.get("segments", []) or []:
                    txt = str(seg.get("text", "")).strip()
                    if txt:
                        segments.append({
                            "start": round(float(seg.get("start", 0.0)), 3),
                            "end": round(float(seg.get("end", 0.0)), 3),
                            "text": txt,
                        })

                raw_words = res_json.get("words", []) or []
                if raw_words:
                    for w in raw_words:
                        wd = str(w.get("word", "")).strip()
                        if not wd:
                            continue
                        words.append({
                            "word": wd,
                            "text": wd,
                            "start": round(float(w.get("start", 0.0)), 3),
                            "end": round(float(w.get("end", 0.0)), 3),
                        })
                elif segments:
                    for seg in segments:
                        words.append({
                            "word": seg["text"],
                            "text": seg["text"],
                            "start": seg["start"],
                            "end": seg["end"],
                        })

                full_text = str(res_json.get("text", "")).strip()
                if not full_text and segments:
                    full_text = " ".join(s["text"] for s in segments)

                return {
                    "words": words,
                    "segments": segments,
                    "full_text": full_text,
                    "duration": float(res_json.get("duration", 0.0) or 0.0),
                    "source": "groq",
                }

            retryable = resp.status_code in (429, 500, 502, 503, 504)
            if retryable and attempt < max_retries:
                wait_s = min(6.0, 2.0 * (attempt + 1))
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait_s = min(6.0, max(1.0, float(retry_after)))
                    except Exception:
                        pass
                if on_log:
                    on_log(
                        f"[WHISPER GROQ] HTTP {resp.status_code} (tentativa {attempt + 1}/{max_retries + 1}). "
                        f"Aguardando {wait_s:.0f}s..."
                    )
                time.sleep(wait_s)
                continue

            if on_log:
                on_log(f"[AVISO] Groq Whisper retornou HTTP {resp.status_code}: {resp.text[:140]}")
            return None

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            if attempt < max_retries:
                wait_s = 2.0 * (attempt + 1)
                if on_log:
                    on_log(f"[WHISPER GROQ] Timeout/Conexão ({exc}). Tentando novamente em {wait_s:.0f}s...")
                time.sleep(wait_s)
                continue
            if on_log:
                on_log(f"[AVISO] Groq Whisper falhou após {max_retries + 1} tentativas: {exc}")
            return None
        except Exception as exc:
            if on_log:
                on_log(f"[AVISO] Erro inesperado no Groq Whisper: {exc}")
            return None

    return None


def _get_configured_whisper_mode() -> str:
    mode = os.getenv("WHISPER_MODE", "").strip().lower()
    if mode in ("auto", "local_gpu", "cloud"):
        return mode
    try:
        from settings_manager import load_app_settings
        cfg = load_app_settings()
        val = str(cfg.get("whisper_mode", "auto")).strip().lower()
        if val in ("auto", "local_gpu", "cloud"):
            return val
    except Exception:
        pass
    return "auto"


def _get_groq_key() -> str:
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        try:
            from settings_manager import load_app_settings
            key = str(load_app_settings().get("groq_key", "") or "").strip()
        except Exception:
            pass
    return key.splitlines()[0].strip().strip("\"'") if key else ""


def transcribe_audio_smart(
    media_path: str,
    mode: Optional[str] = None,
    language: Optional[str] = None,
    groq_model: str = "whisper-large-v3",
    local_model: str = "large-v3",
    use_cache: bool = True,
    cache_key_path: Optional[str] = None,
    require_word_timestamps: bool = True,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[float, str], None]] = None,
) -> Dict[str, Any]:
    """
    Ponto único de transcrição inteligente:
    - Consulta cache 24h (ai_cache_hub).
    - Em modo 'local_gpu' (ou se Groq falhar/estiver indisponível): executa faster-whisper 'large-v3' na GPU CUDA.
    - Em modo 'auto': tenta Groq em MP3 leve (1 requisição) com retry curto e cai automaticamente para GPU local 'large-v3'.
    """
    real_duration = get_media_duration_seconds(media_path)
    cache_target = str(cache_key_path or media_path)

    # 1. Cache persistente 24h
    if use_cache:
        try:
            from ai_cache_hub import ai_cache
            cached = ai_cache.get(cache_target, "transcription")
            if cached and isinstance(cached, dict):
                c_words = cached.get("words", [])
                c_segs = cached.get("segments", [])
                c_text = cached.get("full_text", "")
                c_dur = float(cached.get("duration", real_duration) or real_duration)

                is_stale_coarse = False
                if require_word_timestamps and c_words and len(c_words) <= 12:
                    multi_word = sum(
                        1 for w in c_words
                        if len(str(w.get("text") or w.get("word") or "").strip().split()) >= 3
                    )
                    if multi_word >= 2:
                        is_stale_coarse = True

                if c_words and not is_stale_coarse:
                    if on_log:
                        on_log(
                            f"[CACHE 24H] Transcrição Whisper recuperada instantaneamente "
                            f"({len(c_words)} palavras, 0 tokens gastos)!"
                        )
                    if on_progress:
                        on_progress(0.40, f"Transcrição carregada do Cache: {len(c_words)} palavras.")
                    return {
                        "words": c_words,
                        "segments": c_segs,
                        "full_text": c_text,
                        "duration": c_dur,
                        "source": "cache",
                    }
        except Exception:
            pass

    active_mode = (mode or _get_configured_whisper_mode()).strip().lower()
    groq_key = _get_groq_key()

    result: Optional[Dict[str, Any]] = None
    temp_files: List[str] = []

    try:
        # 2. Tenta Groq Nuvem se não estiver forçado em modo local_gpu
        if active_mode != "local_gpu" and groq_key and groq_key.startswith("gsk_"):
            if on_log:
                on_log(f"[WHISPER] Extraindo áudio compacto para Groq ({groq_model})...")
            if on_progress:
                on_progress(0.15, "Extraindo áudio para transcrição...")

            mp3_path = _extract_audio_file(media_path, fmt="mp3", on_log=on_log)
            if mp3_path:
                temp_files.append(mp3_path)
                if on_progress:
                    on_progress(0.25, f"Transcrevendo via Groq ({groq_model})...")
                if on_log:
                    on_log(f"[WHISPER] Enviando áudio para Groq ({groq_model})...")
                result = transcribe_groq_whisper(
                    audio_path=mp3_path,
                    groq_key=groq_key,
                    model_name=groq_model,
                    language=language,
                    timeout=60,
                    max_retries=2,
                    on_log=on_log,
                )
                if result and result.get("words"):
                    if on_log:
                        on_log(
                            f"[OK] Groq Whisper concluiu: {len(result['words'])} palavras "
                            f"mapeadas com precisão milimétrica!"
                        )
                else:
                    result = None
                    if on_log:
                        on_log("[AVISO] Groq Whisper indisponível ou sem retorno. Acionando GPU Local...")

        # 3. Fallback Automático ou Modo 100% GPU Local (faster-whisper large-v3)
        if result is None:
            if on_progress:
                on_progress(0.25, f"Transcrevendo na GPU Local (Whisper {local_model})...")
            wav_path = _extract_audio_file(media_path, fmt="wav", on_log=on_log)
            if wav_path:
                temp_files.append(wav_path)
                try:
                    result = transcribe_local_whisper(
                        audio_path=wav_path,
                        model_name=local_model,
                        language=language,
                        on_log=on_log,
                    )
                except Exception as exc_local:
                    if on_log:
                        on_log(f"[AVISO] Whisper Local '{local_model}' falhou: {exc_local}")
                    result = None

        if result and (result.get("words") or result.get("segments")):
            final_dur = float(result.get("duration") or 0.0) or real_duration
            result["duration"] = final_dur
            if use_cache:
                try:
                    from ai_cache_hub import ai_cache
                    ai_cache.set(cache_target, "transcription", {
                        "words": result["words"],
                        "segments": result["segments"],
                        "full_text": result["full_text"],
                        "duration": final_dur,
                    })
                except Exception:
                    pass
            if on_progress:
                on_progress(0.40, f"Transcrição concluída: {len(result['words'])} palavras.")
            return result

        return {
            "words": [],
            "segments": [],
            "full_text": "",
            "duration": real_duration,
            "source": "none",
        }
    finally:
        for tf in temp_files:
            try:
                Path(tf).unlink(missing_ok=True)
            except Exception:
                pass

