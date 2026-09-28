"""
Módulo de Proteção Anti-Strike e Censura Inteligente (Anime Shield 2026).
- Censura de Palavrões: Mudo cirúrgico no áudio vocal + higienização de legendas com asteriscos.
- Censura Visual: Detecção com IA especializada em anime (Booru YOLO) para busto, decotes,
  seios expostos, roupas íntimas e partes sensíveis, aplicando Blur Suave com transição feathered.
"""

import os
import re
import cv2
import numpy as np
import pandas as pd
# Evita access violation de pyarrow no Windows durante leitura de CSVs pelo pandas
pd.options.mode.string_storage = 'python'

from pathlib import Path
from typing import Optional, Callable

# ── 1. DICIONÁRIO E HIGIENIZAÇÃO DE PALAVRÕES ────────────────────────────────
PROFANITY_MAP = {
    r"\bcaralhos\b": "C******S",
    r"\bcaralho\b": "C*****O",
    r"\bcaralha\b": "C*****A",
    r"\bfoda-se\b": "F***-SE",
    r"\bfodasse\b": "F***SSE",
    r"\bfodase\b": "F***SE",
    r"\bfudendo\b": "F*****O",
    r"\bfudeu\b": "F***U",
    r"\bfoder\b": "F***R",
    r"\bfoda\b": "F**A",
    r"\bfodas\b": "F***S",
    r"\bputaria\b": "P*****A",
    r"\bputas\b": "P***S",
    r"\bputa\b": "P***A",
    r"\bporras\b": "P****S",
    r"\bporra\b": "P***A",
    r"\bmerdas\b": "M****S",
    r"\bmerda\b": "M***A",
    r"\bbostas\b": "B****S",
    r"\bbosta\b": "B***A",
    r"\bcacete\b": "C****E",
    r"\bbucetas\b": "B*****S",
    r"\bbuceta\b": "B****A",
    r"\bpirocas\b": "P*****S",
    r"\bpiroca\b": "P****A",
    r"\brolas\b": "R***S",
    r"\brola\b": "R***A",
    r"\bpintos\b": "P****S",
    r"\bpinto\b": "P***O",
    r"\barrombados\b": "A*********S",
    r"\barrombado\b": "A********O",
    r"\barrombadas\b": "A*********S",
    r"\barrombada\b": "A********A",
    r"\bvagabundos\b": "V********S",
    r"\bvagabundo\b": "V*******O",
    r"\bvagabundas\b": "V********S",
    r"\bvagabunda\b": "V*******A",
    r"\bvadias\b": "V****S",
    r"\bvadia\b": "V***A",
    r"\bviados\b": "V****S",
    r"\bviado\b": "V***O",
    r"\bcu\b": "C*",
    r"\bpqp\b": "P*P",
    r"\btnc\b": "T*C",
    r"\bvtnc\b": "V**C",
    r"\bvsf\b": "V*F",
    r"\bfdp\b": "F*P"
}

import json

CUSTOM_PROFANITY_FILE = Path(__file__).resolve().parent / "custom_profanity.json"


def load_custom_profanity() -> list[str]:
    """Carrega lista de termos ou palavrões personalizados definidos pelo usuário."""
    if not CUSTOM_PROFANITY_FILE.exists():
        return []
    try:
        with open(CUSTOM_PROFANITY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return [str(x).strip().lower() for x in data if str(x).strip()]
            return []
    except Exception:
        return []


def add_custom_profanity(word: str) -> bool:
    """Adiciona um novo termo/palavrão manual à lista persistente."""
    w = word.strip().lower()
    if not w:
        return False
    current = load_custom_profanity()
    if w not in current:
        current.append(w)
        try:
            with open(CUSTOM_PROFANITY_FILE, "w", encoding="utf-8") as f:
                json.dump(current, f, ensure_ascii=False, indent=2)
            _refresh_profanity_patterns()
            return True
        except Exception:
            return False
    return False


def remove_custom_profanity(word: str) -> bool:
    """Remove um termo personalizado da lista persistente."""
    w = word.strip().lower()
    current = load_custom_profanity()
    if w in current:
        current.remove(w)
        try:
            with open(CUSTOM_PROFANITY_FILE, "w", encoding="utf-8") as f:
                json.dump(current, f, ensure_ascii=False, indent=2)
            _refresh_profanity_patterns()
            return True
        except Exception:
            return False
    return False


def mask_word(word: str) -> str:
    """Gera versão com asteriscos preservando primeira e última letra (ex: m***a)."""
    clean = re.sub(r"[^\w-]", "", word)
    if not clean:
        return "***"
    if len(clean) <= 2:
        masked = clean[0] + "*"
    else:
        masked = clean[0] + ("*" * (len(clean) - 2)) + clean[-1]
    if word.isupper():
        return masked.upper()
    return masked


def _get_active_profanity_patterns() -> list[tuple[str, str]]:
    """Gera lista de tuplas (regex_pattern, replacement) combinando nativos e termos manuais."""
    patterns = [(pat, repl) for pat, repl in PROFANITY_MAP.items()]
    custom = load_custom_profanity()
    for cw in custom:
        pat = rf"\b{re.escape(cw)}\b"
        repl = mask_word(cw)
        patterns.append((pat, repl))
    patterns.sort(key=lambda x: len(x[0]), reverse=True)
    return patterns


_CACHED_PATTERNS = _get_active_profanity_patterns()


def _refresh_profanity_patterns():
    global _CACHED_PATTERNS
    _CACHED_PATTERNS = _get_active_profanity_patterns()


def censor_text(text: str) -> tuple[str, bool]:
    """Substitui palavrões e termos ofensivos por asteriscos formatados."""
    censored = text
    found = False
    for pat, repl in _CACHED_PATTERNS:
        if re.search(pat, censored, re.IGNORECASE):
            found = True
            censored = re.sub(pat, repl, censored, flags=re.IGNORECASE)
    return censored, found


def find_profanity_intervals(words_with_timestamps: list[dict]) -> list[tuple[float, float, str]]:
    """
    Identifica o timestamp exato (início e fim) de cada palavra com palavrão
    para que o áudio possa ser mutado cirurgicamente.
    Suporta tanto lista de palavras avulsas quanto itens de legendas com 'words' internas.
    """
    custom_words = set(load_custom_profanity())
    raw_intervals = []

    def check_word_dict(w_dict: dict):
        raw = w_dict.get("word") or w_dict.get("text") or ""
        clean = re.sub(r"[^\w\s-]", "", raw).strip().lower()
        is_profane = False

        # 1. Flag explícita da interface
        if w_dict.get("censored") or w_dict.get("mute"):
            is_profane = True
        # 2. Asteriscos no texto
        elif "*" in raw:
            is_profane = True
        # 3. Termos manuais do usuário
        elif clean in custom_words or any(cw == clean for cw in custom_words):
            is_profane = True
        else:
            # 4. Padrões do dicionário
            for pat, _ in _CACHED_PATTERNS:
                if re.search(pat, clean, re.IGNORECASE):
                    is_profane = True
                    break

        if is_profane:
            s = max(0.0, float(w_dict.get("start", 0.0)) - 0.04)
            e = float(w_dict.get("end", 0.0)) + 0.05
            if e > s:
                raw_intervals.append((s, e, raw))

    for item in words_with_timestamps:
        if "words" in item and isinstance(item["words"], list) and len(item["words"]) > 0:
            for w in item["words"]:
                check_word_dict(w)
        else:
            check_word_dict(item)

    if not raw_intervals:
        return []

    # Ordena e funde intervalos sobrepostos
    raw_intervals.sort(key=lambda x: x[0])
    merged = []
    curr_s, curr_e, curr_words = raw_intervals[0]

    for next_s, next_e, next_w in raw_intervals[1:]:
        if next_s <= curr_e + 0.08:
            curr_e = max(curr_e, next_e)
            curr_words += f" + {next_w}"
        else:
            merged.append((round(curr_s, 2), round(curr_e, 2), curr_words))
            curr_s, curr_e, curr_words = next_s, next_e, next_w

    merged.append((round(curr_s, 2), round(curr_e, 2), curr_words))
    return merged


def build_audio_mute_filter(mute_intervals: list[tuple[float, float, str]], in_label: str = "[0:a]", out_label: str = "[vocal]") -> str:
    """
    Gera expressão de filtro FFmpeg para silenciar (volume=0) cirurgicamente
    apenas os segundos em que palavrões são pronunciados.
    """
    if not mute_intervals:
        return f"{in_label}volume=1.0{out_label}"

    conditions = [f"between(t,{s:.2f},{e:.2f})" for s, e, _ in mute_intervals]
    joined_conds = "+".join(conditions)
    return f"{in_label}volume=eval=frame:volume='if({joined_conds}, 0.0, 1.0)'{out_label}"


# ── 2. DETECÇÃO E CENSURA VISUAL EM ANIMES ──────────────────────────────────
# Classes sensíveis que disparam moderação em YouTube Shorts / TikTok / Reels:
# Classes sensíveis que disparam moderação em YouTube Shorts / TikTok / Reels:
# Apenas regiões anatômicas sensíveis (poses neutras como 'split' de salto foram removidas)
ANIME_SENSITIVE_LABELS = {
    "bust",     # Busto feminino, decotes profundos, biquíni superior, sutiã
    "boob",     # Seios expostos / mamilos femininos
    "sideb",    # Sideboob feminino exposto
    "nopan",    # Região íntima feminina / calcinha / biquíni inferior
    "butt",     # Nádegas femininas / calcinha traseira
    "ass",      # Nádegas femininas nuas
}


def is_female_sensitive_box(
    frame: np.ndarray,
    box: tuple[int, int, int, int],
    label: str
) -> bool:
    """
    Verifica se a região anatômica detectada pertence exclusivamente a uma
    personagem feminina (seios, decotes, sutiã, biquíni, calcinha).
    Personagens masculinos com peitoral/torso exposto (como Luffy, Goku, Zoro)
    são identificados e preservados sem nenhuma censura.
    """
    x1, y1, x2, y2 = box
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0 or crop.shape[0] < 10 or crop.shape[1] < 10:
        return False

    try:
        from PIL import Image
        from imgutils.tagging import get_wd14_tags

        pil_crop = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
        _, gen, _ = get_wd14_tags(pil_crop, general_threshold=0.15)

        boy = max(gen.get("1boy", 0.0), gen.get("male", 0.0), gen.get("male_focus", 0.0))
        girl = max(gen.get("1girl", 0.0), gen.get("female", 0.0))
        clv = gen.get("cleavage", 0.0)
        brs = gen.get("breasts", 0.0)

        # Se for personagem masculino evidente e sem decote feminino -> Não censura (preserva Luffy, etc.)
        if boy > 0.35 and boy > girl and clv < 0.20:
            return False

        # Se tiver evidência feminina evidente (1girl, decote, seios femininos) -> Censura
        if girl > 0.25 or clv > 0.20 or (brs > 0.35 and boy < 0.30):
            return True

        # Roupas íntimas femininas / biquíni inferior (nopan)
        if label == "nopan" and boy < 0.35:
            return True

        # Nádegas femininas
        if label in ["butt", "ass"] and boy < 0.30:
            return True

        return False
    except Exception:
        return False


def detect_anime_sensitive_timeline(
    video_path: str,
    fps_sample: float = 4.0,
    conf_threshold: float = 0.35,
    on_log: Optional[Callable[[str], None]] = None
) -> list[dict]:
    """
    Varre o vídeo em taxa amostral otimizada (ex: 4 FPS) usando Booru YOLO,
    filtrando com IA para censurar exclusivamente personagens femininas.
    """
    def log(msg: str):
        if on_log:
            on_log(msg)

    try:
        from imgutils.detect import detect_with_booru_yolo
    except ImportError:
        log("AVISO: dghs-imgutils não disponível para detecção de anime.")
        return []

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps
    step_frames = max(1, int(fps / fps_sample))

    log(f"Iniciando escaneamento Anime Shield Feminino ({duration:.1f}s, amostra {fps_sample:.1f} FPS)...")

    detections = []
    skipped_male_count = 0
    frame_idx = 0
    from PIL import Image

    while True:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret or frame_idx >= total_frames:
            break

        timestamp = frame_idx / fps
        try:
            pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            results = detect_with_booru_yolo(pil_img, conf_threshold=conf_threshold)
            heads = [r[0] for r in results if r[1] == "head"]
            sensitive = [r for r in results if r[1] in ANIME_SENSITIVE_LABELS]
            if sensitive:
                for box, label, score in sensitive:
                    # Filtra estritamente para apenas personagens femininas
                    if is_female_sensitive_box(frame, box, label):
                        bx1, by1, bx2, by2 = box
                        # Escudo de proteção de rosto: o topo do busto não pode subir até a cabeça
                        for hx1, hy1, hx2, hy2 in heads:
                            if not (bx2 < hx1 or bx1 > hx2) and hy2 > by1 - 40:
                                by1 = max(by1, hy2 + 2)

                        if by2 > by1 + 10:
                            detections.append({
                                "time": timestamp,
                                "frame": frame_idx,
                                "box": (bx1, by1, bx2, by2),
                                "label": label,
                                "score": score
                            })
                    else:
                        skipped_male_count += 1
        except Exception:
            pass

        frame_idx += step_frames

    cap.release()
    log(f"Escaneamento concluído: {len(detections)} detecções femininas censuradas ({skipped_male_count} masculinas preservadas).")
    return detections


def apply_soft_blur_to_box(
    frame: np.ndarray,
    box: tuple[int, int, int, int],
    blur_strength: str = "medium",
    padding: float = 0.12,
    head_box: Optional[tuple[int, int, int, int]] = None
) -> np.ndarray:
    """
    Aplica Gaussian Blur com máscara suave (feathered) elíptica na região indicada.
    Preserva a estética do anime sem criar retângulos pretos agressivos.
    Protegido contra invasão no rosto: expansão vertical superior desativada.
    """
    h_f, w_f = frame.shape[:2]
    x1, y1, x2, y2 = box
    w = x2 - x1
    h = y2 - y1

    if w <= 4 or h <= 4:
        return frame

    # Padding horizontal e inferior (NÃO expande para cima para não pegar no rosto/queixo)
    pad_x = int(w * padding)
    pad_y_top = 0  # 0% de expansão superior: o rosto permanece 100% livre
    pad_y_bottom = int(h * padding)

    nx1 = max(0, x1 - pad_x)
    ny1 = max(0, y1 - pad_y_top)
    nx2 = min(w_f, x2 + pad_x)
    ny2 = min(h_f, y2 + pad_y_bottom)

    # Se houver cabeça detectada nesta região, o topo do blur NUNCA ultrapassa o queixo
    if head_box:
        hx1, hy1, hx2, hy2 = head_box
        if not (nx2 < hx1 or nx1 > hx2):
            ny1 = max(ny1, hy2)

    roi = frame[ny1:ny2, nx1:nx2]
    if roi.size == 0 or roi.shape[0] < 5 or roi.shape[1] < 5:
        return frame

    # Intensidade do Blur
    if blur_strength == "light":
        ksize = (41, 41)
        sigma = 18
    elif blur_strength == "strong":
        ksize = (81, 81)
        sigma = 45
    else: # medium
        ksize = (61, 61)
        sigma = 30

    # Garante tamanho de kernel ímpar
    kw = ksize[0] if ksize[0] % 2 != 0 else ksize[0] + 1
    kh = ksize[1] if ksize[1] % 2 != 0 else ksize[1] + 1
    blurred_roi = cv2.GaussianBlur(roi, (kw, kh), sigma)

    # Máscara elíptica com suavização para transição invisível nas bordas
    mask = np.zeros((ny2 - ny1, nx2 - nx1), dtype=np.float32)
    cx = (nx2 - nx1) // 2
    cy = (ny2 - ny1) // 2
    axes = (max(2, cx), max(2, cy))
    cv2.ellipse(mask, (cx, cy), axes, 0, 0, 360, 1.0, -1)

    # Suaviza a transição da máscara
    feather_k = min(kw, max(15, int(min(cx, cy) * 0.5) * 2 + 1))
    mask = cv2.GaussianBlur(mask, (feather_k, feather_k), 10)
    mask = np.expand_dims(mask, axis=-1)

    # Mistura alfa
    blended = (roi.astype(np.float32) * (1.0 - mask) + blurred_roi.astype(np.float32) * mask).astype(np.uint8)
    frame[ny1:ny2, nx1:nx2] = blended
    return frame


def process_video_visual_censorship(
    input_path: str,
    output_path: str,
    detections: list[dict],
    blur_strength: str = "medium",
    persistence_seconds: float = 0.45,
    on_progress: Optional[Callable[[float, str], None]] = None
) -> bool:
    """
    Renderiza o vídeo aplicando o blur suave com persistência temporal e suporte a intervalos manuais.
    """
    if not detections:
        return False

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        return False

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # Agrupa detecções por intervalos de tempo ou usa intervalos prontos
    time_windows = []
    for d in detections:
        if "start" in d and "end" in d:
            time_windows.append((float(d["start"]), float(d["end"]), tuple(d["box"])))
        else:
            t = float(d["time"])
            box = tuple(d["box"])
            time_windows.append((max(0.0, t - 0.10), t + persistence_seconds, box))


    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    tmp_out = str(Path(output_path).with_suffix(".tmp.mp4"))
    writer = cv2.VideoWriter(tmp_out, fourcc, fps, (width, height))

    frame_num = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        current_time = frame_num / fps

        # Localiza boxes ativas neste segundo
        active_boxes = [box for s, e, box in time_windows if s <= current_time <= e]
        if active_boxes:
            # Agrupa boxes muito próximas ou aplica em cada uma
            for box in active_boxes:
                frame = apply_soft_blur_to_box(frame, box, blur_strength=blur_strength)

        writer.write(frame)
        frame_num += 1

        if on_progress and frame_num % 30 == 0:
            pct = min(1.0, frame_num / max(1, total_frames))
            on_progress(pct, f"Aplicando Censura Visual Suave... {int(pct*100)}%")

    cap.release()
    writer.release()

    # Copia áudio do vídeo original usando FFmpeg para manter sincronia perfeita
    import subprocess
    from subtitle_renderer import _find_ffmpeg
    ffmpeg = _find_ffmpeg()

    cmd = [
        ffmpeg, "-y",
        "-i", tmp_out,
        "-i", input_path,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-map", "0:v:0",
        "-map", "1:a:0?",
        "-c:a", "copy",
        output_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

    try:
        if os.path.exists(tmp_out):
            os.remove(tmp_out)
    except Exception:
        pass

    return res.returncode == 0
