"""
subtitle_renderer.py - Renderizador de legendas + overlays estilo Animax/CapCut
Pipeline visual de alta fidelidade calibrado com base nos projetos reais do CapCut:
  - Fundo desfocado (Gaussian blur sigma=30, sem barras pretas)
  - Video central ampliado em 187% (1080x1134 centralizado de y=420 a y=1554)
  - Header Twitter/Animax com avatar PNG no tamanho padrao de 270px + selo verificado + @animax_97
  - Titulo do video em fonte Lovely Scream Queens / Queens, com borda preta grossa
  - Watermark @ANIMAX_97 ampliada (62px), alta nitidez e contraste
  - Legendas ASS avancadas estilo CapCut / TikTok:
      * Inteligente Situacional (IA escolhe o melhor estilo por frase: grito, pergunta, karaoke, punchline)
      * Karaoke Ativo (a palavra que o personagem fala acende em amarelo ouro e a frase fica branca)
      * Palavra por Palavra (1-2 palavras grandes por vez com zoom bounce estilo TikTok)
      * Branco com Palavra-Chave em Destaque Colorido
      * Animax Dinamico Alternado (Linha 1 Amarelo, Linha 2 Ciano)
      * Paletas solidas: Amarelo Ouro, Ciano Neon, Verde Limao, Branco
  - CTA inferior com foguete 🚀: "FINALMENTE O ALGORITIMO TE TROUXE / PRO CANAL CERTO! 🚀 SE INSCREVE"
  - Mixagem de audio com musica de fundo (volume configuravel)
"""

import os
import sys
import json
import math
import shutil
import tempfile
import subprocess
import re
from pathlib import Path
from typing import Optional, Callable, List, Dict, Any, Tuple
from PIL import Image, ImageDraw, ImageFont

from subtitle_corrector import apply_corrections_to_items, correct_phrase


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def get_style_file_path() -> Path:
    base = get_base_dir()
    candidate = base / "user_style.json"
    if candidate.exists():
        return candidate
    cwd_candidate = Path.cwd() / "user_style.json"
    if cwd_candidate.exists():
        return cwd_candidate
    return candidate


STYLE_FILE = get_style_file_path()


def _find_ffmpeg() -> str:
    base = get_base_dir()
    candidates = [
        base / "bin" / "ffmpeg.exe",
        Path("bin/ffmpeg.exe"),
        Path("ffmpeg"),
    ]
    for c in candidates:
        if shutil.which(str(c)):
            return str(c)
        if Path(str(c)).is_file():
            return str(c)
    return "ffmpeg"


def _find_ffprobe() -> str:
    ffmpeg = _find_ffmpeg()
    ffprobe_name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
    if "ffmpeg" in ffmpeg:
        probe_cand = Path(ffmpeg).parent / ffprobe_name
        if probe_cand.exists():
            return str(probe_cand)
    if shutil.which("ffprobe"):
        return "ffprobe"
    return "ffprobe"


def get_media_duration(file_path: str) -> float:
    """Retorna a duracao exata do video/audio em segundos via ffprobe."""
    if not file_path or not Path(file_path).exists():
        return 0.0
    ffprobe = _find_ffprobe()
    cmd = [
        ffprobe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        dur = float(res.stdout.strip())
        return max(0.0, dur)
    except Exception:
        return 0.0


def detect_speech_segments(audio_path: str, min_silence_dur: float = 0.5, silence_thresh_db: float = -26.0) -> List[tuple[float, float]]:
    """
    Detecta pausas no audio para isolar blocos de fala e evitar alucinacao / drift temporal do Whisper:
    - Retorna lista de tuplas (start_sec, end_sec) contendo os trechos com som/fala ativa.
    """
    if not audio_path or not Path(audio_path).exists():
        return []

    ffmpeg = _find_ffmpeg()
    cmd = [
        ffmpeg, "-i", str(audio_path),
        "-af", f"silencedetect=noise={silence_thresh_db}dB:d={min_silence_dur}",
        "-f", "null", "-"
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except Exception:
        total_dur = get_media_duration(audio_path)
        return [(0.0, total_dur)] if total_dur > 0 else []

    silences = []
    for line in res.stderr.splitlines():
        if "silence_start:" in line:
            m = re.search(r"silence_start:\s*([0-9.]+)", line)
            if m:
                silences.append({"start": float(m.group(1))})
        elif "silence_end:" in line:
            m = re.search(r"silence_end:\s*([0-9.]+)", line)
            if m and silences:
                silences[-1]["end"] = float(m.group(1))

    total_dur = get_media_duration(audio_path)
    if not silences:
        return [(0.0, total_dur)] if total_dur > 0 else []

    speech_segments = []
    cur_t = 0.0
    for s in silences:
        s_start = s["start"]
        s_end = s.get("end", total_dur)
        if s_start > cur_t + 0.35:
            speech_segments.append((round(cur_t, 2), round(s_start, 2)))
        cur_t = s_end

    if cur_t < total_dur - 0.35:
        speech_segments.append((round(cur_t, 2), round(total_dur, 2)))

    return speech_segments if speech_segments else [(0.0, total_dur)]


def detect_audio_levels(media_path: str) -> dict:
    """
    Analisa os níveis médios e de pico de um arquivo de áudio ou vídeo via volumedetect do FFmpeg.
    Retorna {'mean_volume': float, 'max_volume': float} em dBFS.
    Execução ultrarrápida (geralmente < 0.5s).
    """
    if not media_path or not Path(media_path).exists():
        return {"mean_volume": -20.0, "max_volume": 0.0}

    ffmpeg = _find_ffmpeg()
    cmd = [
        ffmpeg, "-i", str(media_path),
        "-vn", "-af", "volumedetect",
        "-f", "null", "-"
    ]
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )
        mean_match = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", p.stderr)
        max_match = re.search(r"max_volume:\s*([-\d.]+)\s*dB", p.stderr)
        mean_v = float(mean_match.group(1)) if mean_match else -20.0
        max_v = float(max_match.group(1)) if max_match else 0.0
        return {"mean_volume": mean_v, "max_volume": max_v}
    except Exception:
        return {"mean_volume": -20.0, "max_volume": 0.0}


def calculate_proportional_music_volume(
    video_mean_db: float,
    music_mean_db: float,
    user_vol_pct: float,
    music_max_db: float = 0.0
) -> tuple[float, float]:
    """
    Calcula o ganho base da música mantendo correspondência direta 1:1 com o slider do usuário
    (ex: 15% -> 0.15 de ganho linear) com proteção anti-clipping inteligente, e retorna
    o threshold ideal para o detector de voz do compressor sidechain (ducking).
    """
    p = user_vol_pct if user_vol_pct <= 1.0 else user_vol_pct / 100.0
    p = max(0.01, min(1.0, p))

    # O ganho linear base é diretamente proporcional à escolha do usuário
    # Se a música tiver pico perto de 0dBFS, garante headroom seguro para não clipar na mixagem
    max_safe_peak = 10.0 ** (-0.5 / 20.0) # ~0.94 (-0.5dBFS)
    current_peak = 10.0 ** (music_max_db / 20.0) if music_max_db < 0 else 1.0
    if p * current_peak > max_safe_peak:
        linear_gain = max_safe_peak / current_peak
    else:
        linear_gain = p

    # Threshold calibrado para o detector de voz vocal_detect (highpass 200 + lowpass 3500)
    # Threshold 0.05 garante disparo suave e consistente nas falas sem soterrar a música
    th_linear = 0.05

    return round(linear_gain, 4), round(th_linear, 4)


def load_style() -> dict:
    p = get_style_file_path()
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "subtitle": {
            "font_name": "Lovely Scream Queens",
            "size_px": 76,
            "style_preset": "smart_situational",
            "pop_animation": True,
            "stroke_color": "#000000",
            "stroke_width_px": 6,
            "position_y_percent": 50,
            "max_words_per_line": 3,
            "capitalization": "upper"
        },
        "watermark_text": {
            "text": "@ANIMAX_97",
            "size_px": 62,
            "opacity": 0.38,
            "color": "#FFFFFF"
        },
        "channel_header": {
            "name": "Animax",
            "verified": True,
            "handle": "@animax_97",
            "profile_png": "assets/Perfil_1.png",
            "size_px": 270
        },
        "title_overlay": {
            "size_px": 50,
            "color": "#FFFFFF",
            "stroke_color": "#000000",
            "stroke_width_px": 6
        },
        "cta_bar": {
            "line1": "FINALMENTE O ALGORITIMO TE TROUXE",
            "line2": "PRO CANAL CERTO! 🚀 SE INSCREVE"
        },
        "video_style": {
            "scale_percent": 187,
            "blur_strength": 30,
            "fps": 60
        }
    }


def _resolve_asset_path(filename: str) -> str:
    base = get_base_dir()
    candidates = [
        base / "assets" / filename,
        base / filename,
        Path("assets") / filename,
        Path("D:/Old Animax") / filename,
        Path("C:/Users/Vinicius/Desktop/Animax") / filename,
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return filename


def create_static_overlay(
    title_text: str,
    output_png_path: str,
    style: Optional[dict] = None,
    width: int = 1080,
    height: int = 1920
) -> str:
    """
    Renderiza imagem PNG 1080x1920 transparente com todos os elementos graficos estaticos:
    - Foto de perfil circular ampliada (tamanho padrao 270px)
    - Nome Animax + selo de verificado + @animax_97
    - 3 pontos (...)
    - Titulo do video com quebra automatica e borda preta
    - Watermark @ANIMAX_97 ampliada (62px)
    - Texto CTA inferior com emoji de foguete 🚀
    """
    if style is None:
        style = load_style()

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_queens = _resolve_asset_path("Queens.otf")
    font_alt = _resolve_asset_path("Lovely-Scream-Queens.otf")
    font_path = font_queens if Path(font_queens).exists() else font_alt

    # 1. Foto de perfil circular (tamanho padrao calibrado 225px)
    req_profile = style.get("channel_header", {}).get("profile_png", "assets/Perfil_1.png")
    profile_path = _resolve_asset_path(req_profile)
    if not Path(profile_path).exists():
        p_cand = Path(req_profile)
        if p_cand.exists():
            profile_path = str(p_cand)
        else:
            profile_path = _resolve_asset_path(Path(req_profile).name)

    px, py = 15, 88
    size = style.get("channel_header", {}).get("size_px", 225)
    if size > 240:
        size = 225

    if Path(profile_path).exists():
        try:
            p_img = Image.open(profile_path).convert("RGBA")
            pw, ph = p_img.size
            if pw != ph:
                min_side = min(pw, ph)
                p_img = p_img.crop(((pw - min_side) // 2, (ph - min_side) // 2, (pw + min_side) // 2, (ph + min_side) // 2))
            p_img = p_img.resize((size, size), Image.Resampling.LANCZOS)
            mask = Image.new("L", (size, size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, size, size), fill=255)
            img.paste(p_img, (px, py), mask)
        except Exception:
            pass

    # 2. Header Twitter/Animax
    try:
        font_name = ImageFont.truetype("arialbd.ttf", 40)
        font_handle = ImageFont.truetype("arial.ttf", 28)
        font_dots = ImageFont.truetype("arialbd.ttf", 40)
    except Exception:
        font_name = ImageFont.load_default()
        font_handle = font_name
        font_dots = font_name

    tx = px + size + 20
    ty_name = py + 35
    ty_handle = ty_name + 46

    channel_name = style.get("channel_header", {}).get("name", "Animax")
    draw.text((tx + 2, ty_name + 2), channel_name, fill=(0, 0, 0, 220), font=font_name)
    draw.text((tx, ty_name), channel_name, fill=(255, 255, 255, 255), font=font_name)

    # Selo verificado (dinâmico por perfil)
    is_verified = bool(style.get("channel_header", {}).get("verified", True))
    if is_verified:
        bbox = draw.textbbox((tx, ty_name), channel_name, font=font_name)
        check_x = bbox[2] + 18
        check_y = ty_name + 18
        check_r = 13
        draw.ellipse((check_x - check_r - 1, check_y - check_r - 1, check_x + check_r + 1, check_y + check_r + 1), fill=(0, 0, 0, 200))
        draw.ellipse((check_x - check_r, check_y - check_r, check_x + check_r, check_y + check_r), fill=(255, 255, 255, 255))
        draw.line([(check_x - 6, check_y), (check_x - 2, check_y + 5), (check_x + 6, check_y - 4)], fill=(0, 0, 0, 255), width=3)

    # Handle (ex: @animax_97, @vinny.animes, @ViniAnime__s)
    handle_txt = style.get("channel_header", {}).get("handle", "@animax_97")
    draw.text((tx + 2, ty_handle + 2), handle_txt, fill=(0, 0, 0, 220), font=font_handle)
    draw.text((tx, ty_handle), handle_txt, fill=(200, 200, 205, 255), font=font_handle)

    # 3 pontos no canto superior direito
    draw.text((width - 88, ty_name - 3), "···", fill=(0, 0, 0, 200), font=font_dots)
    draw.text((width - 90, ty_name - 5), "···", fill=(220, 220, 220, 255), font=font_dots)

    from emoji_text_renderer import get_emoji_font, measure_mixed_text, render_mixed_text

    def draw_stroked_text(pos, text, font, fill_color, stroke_color, stroke_width):
        draw.text(pos, text, font=font, fill=fill_color, stroke_width=stroke_width, stroke_fill=stroke_color)

    def _balance_wrap_title(text: str, font: Any, emoji_font: Optional[Any] = None, max_line_w: int = 940) -> list[str]:
        words = text.split()
        if not words:
            return []
        w_full, _ = measure_mixed_text(draw, text, font, emoji_font)
        if w_full <= max_line_w:
            return [text]

        # Encontra melhor divisao balanceada para 2 linhas
        best_split = None
        min_diff = 999999
        for i in range(1, len(words)):
            l1 = " ".join(words[:i])
            l2 = " ".join(words[i:])
            w1, _ = measure_mixed_text(draw, l1, font, emoji_font)
            w2, _ = measure_mixed_text(draw, l2, font, emoji_font)
            if w1 <= max_line_w and w2 <= max_line_w:
                diff = abs(w1 - w2)
                if diff < min_diff:
                    min_diff = diff
                    best_split = [l1, l2]
        if best_split:
            return best_split

        # Fallback para 3 linhas
        lines, curr = [], []
        for w in words:
            cand = " ".join(curr + [w])
            cw, _ = measure_mixed_text(draw, cand, font, emoji_font)
            if cw <= max_line_w:
                curr.append(w)
            else:
                if curr:
                    lines.append(" ".join(curr))
                    curr = [w]
                else:
                    lines.append(w)
                    curr = []
        if curr:
            lines.append(" ".join(curr))
        return lines

    # 3. Titulo do video (calibrado com referencia do video 3: letra maior, 1 linha quando cabe, 2 linhas no topo desfocado, emojis nativos)
    t_lines = []
    line_h = 66
    y_start = 350
    if title_text:
        title_upper = title_text.upper().strip()
        base_size = style.get("title_overlay", {}).get("size_px", 60)
        try:
            base_size = float(base_size)
            if base_size < 50:
                base_size = 60.0
        except Exception:
            base_size = 60.0
        scale = base_size / 60.0

        sz_single = max(54, int(round(60 * scale)))
        sz_multi = max(48, int(round(52 * scale)))
        sz_three = max(42, int(round(46 * scale)))

        emoji_single = get_emoji_font(int(sz_single * 0.88))
        emoji_multi = get_emoji_font(int(sz_multi * 0.88))
        emoji_three = get_emoji_font(int(sz_three * 0.88))

        try:
            font_single = ImageFont.truetype(font_path, sz_single)
        except Exception:
            font_single = font_name

        single_w, single_h = measure_mixed_text(draw, title_upper, font_single, emoji_single)

        max_line_w = 960
        if single_w <= max_line_w:
            t_lines = [title_upper]
            title_font = font_single
            emoji_title_font = emoji_single
            line_h = max(60, int(round(66 * scale)))
            y_start = 350
        else:
            try:
                font_multi = ImageFont.truetype(font_path, sz_multi)
            except Exception:
                font_multi = font_name
            t_lines = _balance_wrap_title(title_upper, font_multi, emoji_multi, max_line_w=940)
            if len(t_lines) <= 2:
                title_font = font_multi
                emoji_title_font = emoji_multi
                line_h = max(54, int(round(58 * scale)))
                y_start = 325
            else:
                try:
                    font_three = ImageFont.truetype(font_path, sz_three)
                except Exception:
                    font_three = font_name
                t_lines = _balance_wrap_title(title_upper, font_three, emoji_three, max_line_w=940)
                title_font = font_three
                emoji_title_font = emoji_three
                line_h = max(48, int(round(52 * scale)))
                y_start = 310

        # Cor do título dinâmica configurada no perfil (ex: Branco Animax, Azul Vinny, Vermelho ViniAnimes)
        raw_title_color = style.get("title_overlay", {}).get("color", "#FFFFFF")
        def _parse_rgba(c_val):
            if isinstance(c_val, (list, tuple)):
                return tuple(c_val)
            if isinstance(c_val, str) and c_val.startswith("#"):
                h = c_val.lstrip("#")
                if len(h) == 6:
                    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
            return (255, 255, 255, 255)

        title_fill_color = _parse_rgba(raw_title_color)

        for idx, line in enumerate(t_lines):
            t_w, _ = measure_mixed_text(draw, line, title_font, emoji_title_font)
            curr_y = y_start + (idx * line_h)
            lx = (width - t_w) // 2
            render_mixed_text(
                draw,
                (lx, curr_y),
                line,
                main_font=title_font,
                emoji_font=emoji_title_font,
                fill_color=title_fill_color,
                stroke_color=(0, 0, 0, 255),
                stroke_width=6
            )

    # 4. Watermark configurável pelo perfil - Ampliada para 62px conforme calibração
    wm_text = style.get("watermark_text", {}).get("text", "@ANIMAX_97")
    wm_size = style.get("watermark_text", {}).get("size_px", 62)
    wm_opacity_float = float(style.get("watermark_text", {}).get("opacity", 0.38))
    wm_alpha = int(255 * max(0.10, min(1.0, wm_opacity_float)))
    try:
        wm_font = ImageFont.truetype(font_path, wm_size)
    except Exception:
        wm_font = font_name

    wm_bbox = draw.textbbox((0, 0), wm_text, font=wm_font)
    wm_w = wm_bbox[2] - wm_bbox[0]
    wm_y = 460
    if title_text and t_lines:
        last_title_bottom = y_start + ((len(t_lines) - 1) * line_h) + (line_h // 2)
        wm_y = max(460, last_title_bottom + 25)
    draw_stroked_text(((width - wm_w) / 2, wm_y), wm_text, wm_font, (255, 255, 255, wm_alpha), (0, 0, 0, int(wm_alpha * 0.65)), 3)

    # 5. CTA Inferior flexível (1, 2 ou 3 linhas) com suporte universal a emojis
    cta_style = style.get("cta_bar", {})
    raw_lines = cta_style.get("lines")
    if not raw_lines:
        raw_lines = [
            cta_style.get("line1", "FINALMENTE O ALGORITMO TE TROUXE"),
            cta_style.get("line2", "PRO CANAL CERTO! 🚀 SE INSCREVE")
        ]
        if cta_style.get("line3"):
            raw_lines.append(cta_style.get("line3"))
    cta_lines = [str(l).strip() for l in raw_lines if l and str(l).strip()]

    if len(cta_lines) == 3:
        cta_font_sz, cta_emoji_sz = 40, 34
        start_cta_y, cta_step = 1565, 58
    elif len(cta_lines) == 1:
        cta_font_sz, cta_emoji_sz = 46, 40
        start_cta_y, cta_step = 1620, 0
    else:  # 2 linhas padrão Animax
        cta_font_sz, cta_emoji_sz = 44, 38
        start_cta_y, cta_step = 1590, 65

    try:
        cta_font = ImageFont.truetype(font_path, cta_font_sz)
    except Exception:
        cta_font = font_name
    cta_emoji_font = get_emoji_font(cta_emoji_sz)

    for c_idx, c_txt in enumerate(cta_lines):
        c_w, _ = measure_mixed_text(draw, c_txt, cta_font, cta_emoji_font)
        c_y = start_cta_y + (c_idx * cta_step)
        render_mixed_text(
            draw,
            ((width - c_w) // 2, c_y),
            c_txt,
            main_font=cta_font,
            emoji_font=cta_emoji_font,
            fill_color=(255, 255, 255, 255),
            stroke_color=(0, 0, 0, 255),
            stroke_width=6
        )

    img.save(output_png_path, "PNG")
    return output_png_path


def clean_and_repair_whisper_words(words: List[Dict[str, Any]], max_duration: Optional[float] = None) -> List[Dict[str, Any]]:
    """
    Higieniza e repara timestamps brutos do Whisper:
    1. Remove retrocessos no tempo (inversoes temporais / loops de alucinacao do Whisper).
    2. Garante monotonicidade estrita (cada palavra comeca apos ou junto da anterior).
    3. Clampa estritamente na duracao maxima do video (nunca ultrapassa a duracao real do video).
    4. Corrige duracoes irreais de silaba humana (minimo 80ms).
    """
    if not words:
        return []

    cleaned = []
    last_end = 0.0

    for w in words:
        w_text = (w.get("word") or w.get("text") or "").strip()
        if not w_text:
            continue
        s = float(w.get("start", 0.0))
        e = float(w.get("end", 0.0))

        # Se o start retrocede no tempo em relacao ao que ja foi falado (alucinacao Whisper)
        if s < last_end - 0.35:
            s = last_end + 0.05
            e = max(e, s + 0.15)
        elif s < last_end:
            s = last_end

        # Clamping na duracao do video
        if max_duration and max_duration > 0:
            if s >= max_duration - 0.08:
                continue
            if e > max_duration:
                e = max_duration

        # Garante duracao minima audivel de silaba humana
        if e - s < 0.08:
            if max_duration and s + 0.12 > max_duration:
                e = max_duration
            else:
                e = s + 0.12

        # Se for palavra monossílaba curta (ex: 'O', 'A', 'É', 'Que', 'De') com duração inflada (>0.65s),
        # o Whisper alucinou o início no silêncio/música anterior. Corrige para a emissão real da sílaba.
        if len(w_text) <= 3 and (e - s) > 0.65:
            s = max(s, round(e - 0.25, 3))

        cleaned.append({"word": w_text, "start": round(s, 3), "end": round(e, 3)})
        last_end = max(last_end, e)

    return cleaned



_WEAK_TAIL_WORDS = {
    "o", "a", "os", "as", "um", "uma", "de", "da", "do", "das", "dos", "e", "que",
    "para", "pra", "com", "no", "na", "nos", "nas", "em", "se", "eu", "meu", "minha",
    "meus", "minhas", "seu", "sua", "te", "me", "por", "pelo", "pela", "ao", "mas", "nem",
}


def group_whisper_words(
    words: List[Dict[str, Any]],
    max_duration: Optional[float] = None,
    max_words_per_line: int = 3,
    max_chunk_sec: float = 1.9
) -> List[Dict[str, Any]]:
    """Agrupa palavras do Whisper em falas dinâmicas e curtas (2-3 palavras), respeitando pontuação e sem terminar em palavra fraca."""
    if not words:
        return []

    words = clean_and_repair_whisper_words(words, max_duration=max_duration)

    def _flush(chunk: List[Dict[str, Any]]) -> Dict[str, Any]:
        c_end = chunk[-1]["end"]
        if max_duration and max_duration > 0:
            c_end = min(c_end, max_duration)
        return {
            "start": chunk[0]["start"],
            "end": c_end,
            "text": " ".join(item["word"] for item in chunk),
            "words": list(chunk),
        }

    chunks: List[Dict[str, Any]] = []
    current: List[Dict[str, Any]] = []

    for w in words:
        word_text = (w.get("word") or w.get("text") or "").strip()
        if not word_text:
            continue
        entry = {"word": word_text, "start": float(w.get("start", 0.0)), "end": float(w.get("end", 0.0))}

        if current:
            prev = current[-1]
            gap = entry["start"] - prev["end"]
            sentence_end = prev["word"].endswith((".", "!", "?", "...", ";"))
            soft_break = prev["word"].endswith(",")
            chunk_chars = sum(len(c["word"]) for c in current) + len(current) - 1
            too_long = len(current) >= max_words_per_line or (entry["end"] - current[0]["start"]) >= max_chunk_sec or chunk_chars >= 18
            weak_tail = re.sub(r"[^\wà-ú]", "", prev["word"].lower()) in _WEAK_TAIL_WORDS

            should_break = sentence_end or gap >= 0.5 or (soft_break and len(current) >= 2)
            if too_long and not weak_tail:
                should_break = True
            # Hard ceiling: nunca deixa acumular 4 palavras ou 22 caracteres na horizontal mesmo com weak_tail
            if len(current) >= 4 or chunk_chars >= 22 or (too_long and gap >= 0.3):
                should_break = True
            elif weak_tail and not sentence_end and gap < 0.9:
                should_break = False

            if should_break:
                chunks.append(_flush(current))
                current = []

        current.append(entry)

    if current:
        chunks.append(_flush(current))

    return chunks


# ==============================================================================
# MOTOR PROFISSIONAL DE ESTILOS DE LEGENDAS (CAPCUT / TIKTOK VIRAL ANTI-COLISÃO)
# ==============================================================================

# Cores ASS puras (sem chaves): &H00<BB><GG><RR>&
TAG_YELLOW       = r"\c&H0000D4FF&"   # #FFD400 (Amarelo / Ouro vibrante)
TAG_CYAN         = r"\c&H00FFFF00&"   # #00FFFF (Ciano neon)
TAG_GREEN        = r"\c&H0066FF00&"   # #00FF66 (Verde limao pop)
TAG_WHITE        = r"\c&H00FFFFFF&"   # #FFFFFF (Branco puro)
TAG_RED          = r"\c&H003333FF&"   # #FF3333 (Vermelho / Coral impacto)
TAG_NEON_MAGENTA = r"\c&H00FF00EA&"   # #EA00FF (Magenta neon elétrico)
TAG_NEON_PURPLE  = r"\c&H00FF40A8&"   # #A840FF (Roxo synthwave)
TAG_GOLD_AURA    = r"\c&H0000E5FF&"   # #FFE500 (Dourado Super Saiyajin)
TAG_ICE_BLUE     = r"\c&H00FFF5E0&"   # #E0F5FF (Azul gelo diamante)

# Cores Cinematográficas Refinadas (Nível Profissional 2026)
TAG_CRIMSON_FIRE   = r"\c&H002030E8&"   # #E83020 (Vermelho carmesim de impacto/ação)
TAG_EMBER_ORANGE   = r"\c&H001088FF&"   # #FF8810 (Laranja brasa cintilante)
TAG_IMPERIAL_GOLD  = r"\c&H0015D5FF&"   # #FFD515 (Ouro nobre imperial)
TAG_CHAMPAGNE_GOLD = r"\c&H0060E5FF&"   # #FFE560 (Dourado champagne elegante)
TAG_CRYSTAL_CYAN   = r"\c&H00FFF040&"   # #40F0FF (Ciano cristalino elétrico)
TAG_DIAMOND_ICE    = r"\c&H00FFF5E0&"   # #E0F5FF (Azul diamante gelo puro)
TAG_PASTEL_PINK    = r"\c&H00D699FF&"   # #FF99D6 (Rosa pastel chiclete / kawaii)
TAG_PASTEL_LAVENDER= r"\c&H00FFB0E0&"   # #E0B0FF (Lavanda pastel suave)
TAG_PASTEL_YELLOW  = r"\c&H0080FFFF&"   # #FFFF80 (Amarelo pastel iluminado)
TAG_SEINEN_DARK    = r"\c&H00E0D0C0&"   # #C0D0E0 (Azul acinzentado misterioso / seinen)
TAG_HORROR_BLOOD   = r"\c&H001818B8&"   # #B81818 (Vermelho sangue profundo / horror)

# Animações ASS Profissionais (Anime Clássico & Viral Moderno)
TAG_FADE_IN_OUT    = r"\fad(120,120)"
TAG_SLIDE_UP       = r"\fad(90,90)\t(0,80,\fscy112)\t(80,140,\fscy100)"
TAG_POP_BOUNCE     = r"\t(0,60,\fscx114\fscy114)\t(60,130,\fscx100\fscy100)"
TAG_POP_IMPACT     = r"\t(0,50,\fscx124\fscy124)\t(50,120,\fscx112\fscy112)"
TAG_POP_QUICK      = r"\t(0,40,\fscx115\fscy115)\t(40,90,\fscx100\fscy100)"
TAG_GLITCH_SHAKE   = r"\fad(30,30)\t(0,25,\fscx108\frz2\blur3)\t(25,55,\fscx96\frz-2\blur1)\t(55,85,\fscx100\frz0\blur0)"
TAG_NEON_PULSE     = r"\fad(80,80)\t(0,90,\fscx106\fscy106\blur6)\t(90,180,\fscx100\fscy100\blur2)"
TAG_3D_SLAM        = r"\fad(45,45)\t(0,55,\fscx135\fscy135\frx15)\t(55,120,\fscx100\fscy100\frx0)"
TAG_KINETIC_WAVE   = r"\fad(90,90)\t(0,75,\fscy112\frz1)\t(75,150,\fscy100\frz-1)\t(150,210,\frz0)"
TAG_CENTER_POS     = r"\an5\pos(540,1380)"

def get_pos_tag(pos_y: int = 1380) -> str:
    """Retorna tag de posicionamento ASS centralizada horizontalmente no Y dinâmico calculado."""
    return rf"\an5\pos(540,{pos_y})"

# Micro-Animações de Alta Precisão para Palavra por Palavra (Kinetic Reels)
TAG_WORD_POP_PUNCH = r"\t(0,50,\fscx122\fscy122)\t(50,120,\fscx112\fscy112)"
TAG_WORD_POP_FOCUS = r"\t(0,40,\fscx114\fscy114)\t(40,90,\fscx104\fscy104)"
TAG_WORD_POP_CLEAN = r"\t(0,35,\fscx108\fscy108)\t(35,80,\fscx100\fscy100)"

def resolve_animation_tag(anim_param: Any, is_impact: bool = False) -> str:
    """
    Resolve o efeito visual das legendas:
    - 'fade' / 'esmaecer': \\fad(120,120) (Efeito suave clássico de anime)
    - 'glitch': Tremor e micro-deslocamento cibernético
    - 'pulse' / 'neon': Pulso de brilho e escala
    - 'slam' / '3d': Pancada pesada 3D vinda de cima
    - 'wave' / 'onda': Ondulação fluida
    - 'pop' / 'bounce': Salto dinamico (TikTok / CapCut)
    - 'slide' / 'deslizar': Deslizar suave subindo
    - 'quick': Pop rapido
    - False / 'none' / 'fixo': Sem efeito
    """
    if anim_param is False or anim_param is None:
        return ""
    if anim_param is True:
        return TAG_POP_IMPACT if is_impact else TAG_FADE_IN_OUT

    s = str(anim_param).lower().strip()
    if "glitch" in s:
        return TAG_GLITCH_SHAKE
    elif "pulse" in s or "pulso" in s:
        return TAG_NEON_PULSE
    elif "slam" in s or "pancada" in s or "drop" in s:
        return TAG_3D_SLAM
    elif "wave" in s or "onda" in s:
        return TAG_KINETIC_WAVE
    elif "fade" in s or "esmaecer" in s:
        if is_impact:
            return r"\fad(60,60)\t(0,50,\fscx114\fscy114)\t(50,110,\fscx100\fscy100)"
        return TAG_FADE_IN_OUT
    elif "slide" in s or "deslizar" in s:
        return TAG_SLIDE_UP
    elif "quick" in s or "rapido" in s or "rápido" in s:
        return TAG_POP_QUICK
    elif "pop" in s or "bounce" in s:
        return TAG_POP_IMPACT if is_impact else TAG_POP_BOUNCE
    elif "nenhum" in s or "fixo" in s or "none" in s:
        return ""
    return TAG_FADE_IN_OUT

PALETTE = [TAG_YELLOW, TAG_CYAN, TAG_GREEN, TAG_WHITE, TAG_RED]

# Particulas curtas que devem ser agrupadas no modo Palavra por Palavra
SHORT_PARTICLES = {
    "E", "É", "O", "A", "OS", "AS", "DE", "DO", "DA", "DOS", "DAS",
    "EM", "NO", "NA", "NOS", "NAS", "UM", "UMA", "UNS", "UMAS",
    "SE", "QUE", "COM", "ME", "TE", "PRA", "PRO", "POR"
}

# Vocabulários Semânticos para Análise Contextual de Alta Precisão
ACTION_IMPACT_WORDS = {
    "NÃO", "NAO", "NUNCA", "JAMAIS", "MORRA", "MORTE", "MORRER", "MATAR", "BANKAI",
    "EXPLOSÃO", "EXPLOSAO", "BOMBA", "FOGO", "CHAMAS", "DESTRUIR", "DESTRUIÇÃO", "DESTRUICAO",
    "PODER", "LUTA", "LUTAR", "ATAQUE", "GOLPE", "SOCO", "CHUTE", "ESPADA", "FUJA", "FUGIR",
    "CORRE", "CORRA", "PERIGO", "CUIDADO", "AGORA", "BASTA", "PARE", "PARAR", "RÁPIDO", "RAPIDO",
    "FORÇA", "FORCA", "INIMIGO", "VINGANÇA", "VINGANCA", "SANGUE", "ACABOU", "VAI", "BORA",
    "VENCEU", "DERROTA", "DETONE", "ESMAGUE", "CORTE", "DESGRAÇADO", "DESGRACADO",
    "INACREDITÁVEL", "INACREDITAVEL", "SOCORRO", "GIGANTE", "IMPACTO", "CLÍMAX", "CLIMAX",
    "DEMÔNIO", "DEMONIO", "MONSTRO", "EXPLODE", "EXPLODIU", "DISPARA", "CHEGA", "CALA"
}

GLORY_NOBLE_WORDS = {
    "REI", "RAINHA", "CAPITÃO", "CAPITAO", "DEUS", "DEUSA", "MESTRE", "LUFFY", "ICHIGO",
    "ZORO", "SANJI", "AIZEN", "BLEACH", "ANIMAX", "MONACA", "OURO", "TESOURO", "MILHÕES",
    "MILHOES", "MILHÃO", "MILHAO", "PRIMEIRO", "PRIMEIRA", "MELHOR", "ÉPICO", "EPICO",
    "LENDÁRIO", "LENDARIO", "SHIRAHOSHI", "NETUNO", "ABSOLUTO", "SUPER", "SUPREMO",
    "UNIVERSO", "MUNDO", "NÍVEL", "NIVEL", "VITÓRIA", "VITORIA", "CAMPEÃO", "CAMPEAO",
    "INCRÍVEL", "INCRIVEL", "FANTÁSTICO", "FANTASTICO", "CANAL", "INSCREVE", "ALGORITIMO",
    "VERDADEIRO", "PERFEITO", "GENIAL", "LÍDER", "LIDER", "HERÓI", "HEROI", "FORTE"
}

EMOTION_CHILL_WORDS = {
    "MEDO", "CHORO", "CHORAR", "LÁGRIMA", "LAGRIMA", "LÁGRIMAS", "LAGRIMAS", "DOR",
    "TRISTE", "TRISTEZA", "SAUDADE", "CORAÇÃO", "CORACAO", "AMOR", "SILÊNCIO", "SILENCIO",
    "FRIO", "GELADO", "ESCURO", "SOMBRA", "ALMA", "ESPÍRITO", "ESPIRITO", "SEGREDO",
    "DESTINO", "SOLIDÃO", "SOLIDAO", "ESPERANÇA", "ESPERANCA", "PESADELO", "VAZIO",
    "CALMA", "SENTIR", "SENTIMENTO", "SEREIA", "PUDIM", "CORAL", "PAI", "MÃE", "MAE",
    "IRMÃO", "IRMAO", "IRMÃOS", "IRMAOS", "TREMER", "TRISTE", "CHORANDO"
}

SCREAM_WORDS = ACTION_IMPACT_WORDS

QUESTION_WORDS = {
    "QUEM", "O QUE", "POR QUE", "PORQUE", "COMO", "ONDE", "QUANDO", "SERÁ", "AFINAL",
    "QUAL", "SERA", "REALMENTE", "CERTEZA", "POSSÍVEL", "POSSIVEL", "IMPOSSÍVEL", "IMPOSSIVEL",
    "ACHA", "SABE", "VERDADE"
}

STRONG_NOUNS = {
    "PUDIM", "CORAL", "SEREIA", "NETUNO", "LUFFY", "SANJI", "SHIRAHOSHI",
    "AIZEN", "ICHIGO", "ZORO", "GIGANTE", "MEDO", "CHORA", "ALGORITIMO",
    "CANAL", "INSCREVE", "PESSOA", "PAI", "IRMÃOS", "REI"
}

# ==============================================================================
# VOCABULÁRIO SEMÂNTICO EMOCIONAL MULTI-CORES (IA EMOTION SENTIMENT ENGINE)
# ==============================================================================
TAG_EMOTION_PURPLE  = r"\c&H00D020A0&"  # Roxo Místico / Melancolia / Tristeza profunda
TAG_EMOTION_BLUE    = r"\c&H00F06020&"  # Azul Índigo / Solidão / Frio / Luto
TAG_EMOTION_RED     = r"\c&H001810EA&"  # Vermelho Carmesim Fogo / Ódio / Desapontamento / Fúria
TAG_EMOTION_ORANGE  = r"\c&H00008CFF&"  # Laranja Alerta / Tensão / Chamas / Perigo
TAG_EMOTION_MAGENTA = r"\c&H00C020FF&"  # Rosa Choque / Amor / Afeto / Segredo / Mistério
TAG_EMOTION_GREEN   = r"\c&H0030FF60&"  # Verde Esmeralda / Vida / Esperança / Proteção
TAG_EMOTION_CYAN    = r"\c&H00FFFF00&"  # Ciano Elétrico / Magia / Gelo / Técnicas / Shinigami
TAG_EMOTION_GOLD    = r"\c&H0000D4FF&"  # Ouro Imperial / Glória / Heróis / Reis / Honra

SEMANTIC_SADNESS_WORDS = {
    "TRISTE", "TRISTEZA", "CHORAR", "CHORO", "CHORANDO", "LÁGRIMAS", "LAGRIMAS",
    "SOZINHO", "SOLIDÃO", "SOLIDAO", "ABANDONADO", "ABANDONO", "CULPA", "CULPADO",
    "PERDÃO", "PERDAO", "ADEUS", "LEMBRANÇAS", "LEMBRANCAS", "ESQUECER", "SAUDADE",
    "LUTO", "PESAR", "ESCURIDÃO", "ESCURIDAO", "VAZIO", "PERDIDO", "DESESPERO",
    "DESESPERADO", "SILÊNCIO", "SILENCIO", "DOR", "SOFRIMENTO", "LAMENTAÇÃO",
    "LAMENTACAO", "ARREPENDIMENTO", "RUÍNA", "RUINA", "ANGÚSTIA", "ANGUSTIA",
    "DESTRUÍDO", "DESTRUIDO", "ACABADO", "MELANCOLIA", "PESADELO"
}

SEMANTIC_WRATH_CRITIC_WORDS = {
    "ÓDIO", "ODIO", "DESAPONTAMENTO", "DECEPÇÃO", "DECEPCAO", "CRÍTICA", "CRITICA",
    "VERGONHA", "COVARDE", "TRAIDOR", "TRAIÇÃO", "TRAICAO", "MENTIRA", "MENTIROSO",
    "DESGRAÇADO", "DESGRACADO", "VERME", "LIXO", "INÚTIL", "INUTIL", "NOJO",
    "REVOLTA", "RAIVA", "FÚRIA", "FURIA", "VINGANÇA", "VINGANCA", "MORTE", "MORTES",
    "MORTO", "MORTOS", "MORRA", "MORRAM", "MORRER", "MORREU", "MATAR", "MATOU",
    "MATARAM", "ASSASSINO", "SANGUE", "CRUEL", "MONSTRO", "AMEAÇA", "AMEACA",
    "PERIGO", "VILÃO", "VILAO", "DESTRUIÇÃO", "DESTRUICAO", "DESTRUIR", "CADÁVER",
    "CADAVER", "INFERNO", "TORTURA", "INIMIGO", "INIMIGOS", "FERIDO", "FERIMENTOS",
    "HUMILHAÇÃO", "HUMILHACAO", "RIDÍCULO", "RIDICULO", "PENA", "MISERÁVEL", "MISERAVEL"
}

SEMANTIC_ALERT_FIRE_WORDS = {
    "CUIDADO", "ATENÇÃO", "ATENCAO", "FOGO", "CHAMAS", "EXPLOSÃO", "EXPLOSAO",
    "QUEIMAR", "RÁPIDO", "RAPIDO", "CORRA", "CORRE", "FUJA", "FUGIR", "ALERTA",
    "SURPRESA", "INACREDITÁVEL", "INACREDITAVEL", "IMPOSSÍVEL", "IMPOSSIVEL",
    "PRESSA", "SOCORRO", "EMERGÊNCIA", "EMERGENCIA", "TENSÃO", "TENSAO", "IMPACTO",
    "TEMPESTADE", "RELÂMPAGO", "RELAMPAGO", "RAIO", "FAÍSCA", "FAISCA", "QUEIMANDO"
}

SEMANTIC_LOVE_MYSTERY_WORDS = {
    "CORAÇÃO", "CORACAO", "AMOR", "SENTIMENTO", "DESTINO", "ALMA", "SONHO",
    "DESEJO", "PROMESSA", "LAÇOS", "LACOS", "SEGREDO", "MISTÉRIO", "MISTERIO",
    "MILAGRE", "FOFO", "QUERIDO", "QUERIDA", "AMIGO", "AMIGOS", "AMIZADE",
    "LINDO", "LINDA", "BELEZA", "CARINHO", "PAIXÃO", "PAIXAO", "ESPECIAL", "JUNTOS"
}

SEMANTIC_LIFE_HOPE_WORDS = {
    "VIVO", "VIVOS", "VIDA", "VIDAS", "SALVAR", "SALVOU", "SALVOS", "CURA",
    "CURAR", "PROTEGER", "PROTEÇÃO", "PROTECAO", "BEM", "PAZ", "ESPERANÇA",
    "ESPERANCA", "SOBREVIVER", "RENASCER", "LUZ", "PURO", "CURADO", "HARMONIA"
}

SEMANTIC_POWER_TECH_WORDS = {
    "CAPITÃO", "CAPITAO", "CAPITÃES", "CAPITAES", "TENENTE", "DIVISÃO", "DIVISAO",
    "DIVISÕES", "DIVISOES", "ESQUADRÃO", "ESQUADRAO", "COMANDANTE", "SEREITEI",
    "SOUL", "SOCIETY", "SHINIGAMI", "BANKAI", "SHIKAI", "HAKI", "CHAKRA", "KI",
    "REIATSU", "PODER", "PODERES", "FORÇA", "FORCA", "MAGIA", "ENCANTO", "FEITIÇO",
    "FEITICO", "HURRICANE", "GELO", "COLOSSAL", "SUPREMO", "ABSOLUTO", "ABSORÇÃO",
    "ABSORCAO", "EVASÃO", "EVASAO", "DESPERTAR", "BATALHA", "COMBATE", "GUERRA",
    "ESPADA", "ZANPAKUTO", "ZANPAKUTOU"
}

SEMANTIC_GLORY_HERO_WORDS = {
    "SASAKIBE", "YAMAMOTO", "ICHIGO", "RUKIA", "RÚQUIA", "RENJI", "AIZEN", "SUKUNA",
    "GOJO", "LUFFY", "ZORO", "SANJI", "SHANKS", "ACE", "NARUTO", "SASUKE", "GOKU",
    "VEGETA", "HUMANO", "HUMANOS", "MESTRE", "SENHOR", "LÍDER", "LIDER", "REI",
    "DEUS", "HONRA", "ORGULHO", "VITÓRIA", "VITORIA", "CAMPEÃO", "CAMPEAO", "HERÓI",
    "HEROI", "LENDÁRIO", "LENDARIO", "ÉPICO", "EPICO", "TRIUNFO"
}


def get_semantic_color_tags(word_clean: str, pop_animation: bool = True) -> Tuple[str, str]:
    """
    Classifica a emoção de uma palavra e retorna:
    (active_tag, base_color_tag)
    Cores emocionais variadas:
    - Roxo / Azul: Tristeza, melancolia, dor, solidão, luto, lágrimas
    - Vermelho: Ódio, desapontamento, crítica, decepção, ofensas, fúria, perigo
    - Laranja: Alerta, urgência, surpresa, fogo, impacto
    - Rosa / Magenta: Amor, laços, segredo, mistério, destino, sentimento
    - Verde: Vida, cura, proteção, paz, esperança
    - Ciano: Poderes, técnicas, shinigami, bankai, gelo
    - Dourado / Amarelo: Glória, heróis, reis, honra, vitória
    - Branco: Neutro / diálogo padrão
    """
    w = word_clean.upper().strip()

    if w in SEMANTIC_SADNESS_WORDS:
        base = TAG_EMOTION_PURPLE
        anim = r"\t(0,35,\fscx114\fscy114)\t(35,80,\fscx100\fscy100)" if pop_animation else ""
        active = f"{TAG_EMOTION_BLUE}{anim}"
    elif w in SEMANTIC_WRATH_CRITIC_WORDS:
        base = TAG_EMOTION_RED
        shake = r"\t(0,25,\frz2\fscx122\fscy122)\t(25,50,\frz-2\fscx105\fscy105)\t(50,80,\frz0\fscx100\fscy100)" if pop_animation else ""
        active = rf"\c&H002010FF&{shake}"
    elif w in SEMANTIC_ALERT_FIRE_WORDS:
        base = TAG_EMOTION_ORANGE
        pop = r"\t(0,35,\fscx120\fscy120)\t(35,80,\fscx100\fscy100)" if pop_animation else ""
        active = rf"\c&H0000B5FF&{pop}"
    elif w in SEMANTIC_LOVE_MYSTERY_WORDS:
        base = TAG_EMOTION_MAGENTA
        pop = r"\t(0,35,\fscx118\fscy118)\t(35,80,\fscx100\fscy100)" if pop_animation else ""
        active = rf"\c&H00E040FF&{pop}"
    elif w in SEMANTIC_LIFE_HOPE_WORDS:
        base = TAG_EMOTION_GREEN
        pop = r"\t(0,35,\fscx118\fscy118)\t(35,80,\fscx100\fscy100)" if pop_animation else ""
        active = rf"\c&H0080FF20&{pop}"
    elif w in SEMANTIC_POWER_TECH_WORDS:
        base = TAG_EMOTION_CYAN
        pop = r"\t(0,35,\fscx120\fscy120)\t(35,80,\fscx100\fscy100)" if pop_animation else ""
        active = rf"\c&H00FFFF30&{pop}"
    elif w in SEMANTIC_GLORY_HERO_WORDS:
        base = TAG_EMOTION_GOLD
        pop = r"\t(0,35,\fscx120\fscy120)\t(35,80,\fscx100\fscy100)" if pop_animation else ""
        active = rf"\c&H0000E6FF&{pop}"
    else:
        base = TAG_WHITE
        pop = r"\t(0,35,\fscx118\fscy118)\t(35,80,\fscx100\fscy100)" if pop_animation else ""
        active = rf"{TAG_YELLOW}{pop}"

    return active, base


def ass_block(*tags: str) -> str:
    """Combina tags ASS dentro de um UNICO par limpo de chaves {...} evitando vazamento de codigo."""
    clean = "".join(t.strip() for t in tags if t and t.strip())
    return f"{{{clean}}}" if clean else ""


def sanitize_text(text: str) -> str:
    """Remove caracteres que possam corromper ou vazar no parser de legendas ASS."""
    t = text.replace("{", "").replace("}", "").replace("\\N", " ").replace("\\n", " ")
    return re.sub(r'\s+', ' ', t).strip()


def _ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


format_ass_time = _ts


def sanitize_timeline(events: List[Dict[str, Any]], safety_gap: float = 0.01, max_duration: Optional[float] = None) -> List[Dict[str, Any]]:
    """
    Garante matematicamente que nenhum evento sobreponha outro no tempo
    e nenhum evento ultrapasse a duracao real do video.
    Suporta multi-camadas (Layer 0 e Layer 1 para efeitos de Aura/Bloom perfeitamente sincronizados).
    """
    if not events:
        return []

    from collections import defaultdict
    by_layer = defaultdict(list)
    for ev in events:
        by_layer[ev.get("layer", 0)].append(ev)

    result = []
    for layer, layer_events in by_layer.items():
        layer_events = sorted(layer_events, key=lambda x: x["start"])
        clean_events = []

        for ev in layer_events:
            s = max(0.0, float(ev["start"]))
            e = max(s + 0.05, float(ev["end"]))

            if max_duration and max_duration > 0:
                if s >= max_duration - 0.05:
                    continue
                if e > max_duration:
                    e = max_duration

            if clean_events:
                prev = clean_events[-1]
                if prev["end"] > s:
                    if s > prev["start"] + 0.05:
                        prev["end"] = max(prev["start"] + 0.05, s - safety_gap)
                    else:
                        s = prev["end"] + safety_gap
                        e = max(e, s + 0.05)
                        if max_duration and max_duration > 0 and e > max_duration:
                            e = max_duration

            if e > s:
                ev_copy = dict(ev)
                ev_copy["start"] = s
                ev_copy["end"] = e
                ev_copy["layer"] = layer
                clean_events.append(ev_copy)

        result.extend(clean_events)

    return sorted(result, key=lambda x: (x["start"], x.get("layer", 0)))


def split_words_balanced(words: List[str], max_chars_per_line: int = 18) -> int:
    """
    Calcula o índice de quebra ideal para equilibrar 2 linhas com comprimentos visuais similares
    (justificação visual perfeita, evitando frases gigantescas em uma única linha horizontal).
    """
    if len(words) <= 1:
        return len(words)

    total_chars = sum(len(w) for w in words) + len(words) - 1
    # Se a frase for bem curta (<= max_chars_per_line) e com até 2 palavras, mantém em 1 linha
    if total_chars <= max_chars_per_line and len(words) <= 2:
        return len(words)

    best_idx = 1
    best_score = 999999
    for k in range(1, len(words)):
        l1_len = sum(len(w) for w in words[:k]) + k - 1
        l2_len = sum(len(w) for w in words[k:]) + (len(words) - k) - 1
        diff = abs(l1_len - l2_len)
        penalty = 0
        if l1_len > max_chars_per_line:
            penalty += (l1_len - max_chars_per_line) * 2
        if l2_len > max_chars_per_line:
            penalty += (l2_len - max_chars_per_line) * 2
        score = diff + penalty
        if score < best_score:
            best_score = score
            best_idx = k

    return best_idx


def wrap_words_to_lines(words: List[str], max_chars_per_line: int = 18) -> str:
    """Quebra palavras em no máximo 2 linhas equilibradas, proporcionais e justificadas visualmente."""
    if len(words) <= 1:
        return " ".join(words)
    mid = split_words_balanced(words, max_chars_per_line=max_chars_per_line)
    if mid >= len(words):
        return " ".join(words)
    return " ".join(words[:mid]) + r"\N" + " ".join(words[mid:])


def _interpolate_words(text: str, start: float, end: float) -> List[Dict[str, Any]]:
    """Gera timestamps distribuidos caso falte minutagem por palavra."""
    words = sanitize_text(text).split()
    if not words:
        return []
    total_dur = max(0.25, end - start)
    step = total_dur / len(words)
    res = []
    for i, w in enumerate(words):
        res.append({
            "word": w,
            "start": start + i * step,
            "end": start + (i + 1) * step
        })
    return res


def _find_keyword_index(words: List[str]) -> int:
    """Localiza a palavra de maior peso semantico."""
    if not words:
        return 0
    scores = []
    for i, w in enumerate(words):
        w_clean = re.sub(r'[^A-Za-z0-9ÁÉÍÓÚÂÊÎÔÛÃÕÇáéíóúâêîôûãõç]', '', w).upper()
        score = len(w_clean)
        if len(w_clean) <= 2:
            score = 0
        if w_clean in STRONG_NOUNS:
            score += 25
        scores.append((score, i))
    scores.sort(key=lambda x: x[0], reverse=True)
    return scores[0][1]


def build_karaoke_dialogues(item: Dict[str, Any], pop_animation: bool = True) -> List[Dict[str, Any]]:
    """
    Modo Karaoke Ativo CapCut:
    - O bloco da frase permanece estavel e perfeitamente ancorado no centro.
    - A palavra que esta sendo falada acende em Amarelo/Verde com salto dinamico.
    - Zero oscilacao de layout ou vazamento de tags.
    """
    raw_text = sanitize_text(item.get("text") or item.get("word") or "").upper()
    words = raw_text.split()
    if not words:
        return []

    start = float(item.get("start", 0.0))
    end = float(item.get("end", 0.0))
    w_list = item.get("words")
    if not w_list or len(w_list) != len(words):
        w_list = _interpolate_words(raw_text, start, end)

    events = []
    mid = split_words_balanced(words, max_chars_per_line=18)

    for i, w_obj in enumerate(w_list):
        w_s = float(w_obj.get("start", start))
        w_e = float(w_obj.get("end", end))

        formatted_words = []
        for j, w in enumerate(words):
            w_clean = re.sub(r'[^A-Za-z0-9ÁÉÍÓÚÂÊÎÔÛÃÕÇáéíóúâêîôûãõç]', '', w).upper()
            active_tag, base_col = get_semantic_color_tags(w_clean, pop_animation=pop_animation)
            if j == i:
                formatted_words.append(f"{ass_block(active_tag)}{w}{ass_block(TAG_WHITE)}")
            else:
                if base_col != TAG_WHITE:
                    formatted_words.append(f"{ass_block(base_col)}{w}{ass_block(TAG_WHITE)}")
                else:
                    formatted_words.append(w)

        if mid < len(words):
            line1 = " ".join(formatted_words[:mid])
            line2 = " ".join(formatted_words[mid:])
            content = f"{line1}\\N{line2}"
        else:
            content = " ".join(formatted_words)

        full_text = f"{ass_block(TAG_CENTER_POS, TAG_WHITE)}{content}"
        events.append({
            "start": w_s,
            "end": w_e,
            "text": full_text
        })

    return sanitize_timeline(events)


def classify_cluster_word_by_word(
    cluster_text: str,
    sentence_text: str,
    consecutive_neutral: int,
    mode: str = "contextual",
    pop_animation: Any = True,
    cluster_index: int = 0
) -> Tuple[str, str, str, bool]:
    """
    Classifica a ênfase visual (cor, micro-animação e escala/borda ASS) para o modo Palavra por Palavra:
    Retorna: (color_tag, anim_tag, extra_tags, is_neutral)
    """
    clean_txt = re.sub(r'[^A-Za-z0-9ÁÉÍÓÚÂÊÎÔÛÃÕÇáéíóúâêîôûãõç]', '', cluster_text).upper()
    words_in_cluster = clean_txt.split()
    first_w = words_in_cluster[0] if words_in_cluster else clean_txt

    # Se animação estiver desligada pelo usuário
    anim_enabled = bool(pop_animation and str(pop_animation).lower().strip() not in ("none", "nenhum", "fixo", "false"))

    # Modo 100% Branco Minimalista (Viral Clean / Alex Hormozi / MrBeast)
    if mode in ("clean", "minimal", "white"):
        is_impact = ("!" in cluster_text or any(w in ACTION_IMPACT_WORDS for w in [clean_txt, first_w]))
        anim = (TAG_WORD_POP_PUNCH if is_impact else TAG_WORD_POP_CLEAN) if anim_enabled else ""
        extra = r"\bord8\fscx116\fscy116" if is_impact else r"\bord6"
        return TAG_WHITE, anim, extra, False

    # Modo Ouro Nobre & Branco
    if mode == "gold":
        is_highlight = (
            "!" in cluster_text or
            bool(re.search(r'\d', cluster_text)) or
            any(w in GLORY_NOBLE_WORDS or w in ACTION_IMPACT_WORDS for w in [clean_txt, first_w])
        )
        if is_highlight:
            anim = TAG_WORD_POP_FOCUS if anim_enabled else ""
            return TAG_IMPERIAL_GOLD, anim, r"\bord6\fscx114\fscy114\blur2", False
        else:
            anim = TAG_WORD_POP_CLEAN if anim_enabled else ""
            return TAG_WHITE, anim, r"\bord6", True

    # Modo Ciano Neon & Branco
    if mode == "cyber":
        is_highlight = (
            "!" in cluster_text or "?" in cluster_text or
            any(w in QUESTION_WORDS or w in ACTION_IMPACT_WORDS or w in STRONG_NOUNS for w in [clean_txt, first_w])
        )
        if is_highlight:
            anim = TAG_WORD_POP_FOCUS if anim_enabled else ""
            return TAG_CRYSTAL_CYAN, anim, r"\bord6\fscx114\fscy114", False
        else:
            anim = TAG_WORD_POP_CLEAN if anim_enabled else ""
            return TAG_WHITE, anim, r"\bord6", True

    # Modo Multicolorido Clássico / Retrô (antigo comportamento cíclico caso o usuário ainda queira)
    if mode in ("classic", "rainbow", "legacy"):
        col = PALETTE[cluster_index % len(PALETTE)]
        anim = resolve_animation_tag(pop_animation) if anim_enabled else ""
        return col, anim, r"\bord6", False

    # =========================================================================
    # =========================================================================
    # Modo Padrão de Elite: CONTEXTUAL DINÂMICO INTELIGENTE (IA & EMOÇÃO)
    # =========================================================================

    # 1. TRISTEZA / DOR / LUTO / MELANCOLIA (Roxo Místico / Púrpura)
    if any(w in SEMANTIC_SADNESS_WORDS for w in [clean_txt, first_w]):
        anim = (r"\fad(30,30)\t(0,40,\fscx112\fscy112)\t(40,90,\fscx100\fscy100)") if anim_enabled else ""
        return TAG_EMOTION_PURPLE, anim, r"\bord6\fscx112\fscy112\blur2", False

    # 2. ÓDIO / DESAPONTAMENTO / CRÍTICA / OFENSA / FÚRIA (Vermelho Carmesim Fogo)
    if any(w in SEMANTIC_WRATH_CRITIC_WORDS for w in [clean_txt, first_w]):
        anim = TAG_WORD_POP_PUNCH if anim_enabled else ""
        return TAG_EMOTION_RED, anim, r"\bord8\fscx124\fscy124", False

    # 3. ALERTA / TENSÃO / URGÊNCIA / FOGO (Laranja Âmbar)
    if any(w in SEMANTIC_ALERT_FIRE_WORDS for w in [clean_txt, first_w]):
        anim = TAG_WORD_POP_PUNCH if anim_enabled else ""
        return TAG_EMOTION_ORANGE, anim, r"\bord7\fscx120\fscy120", False

    # 4. AMOR / AFETO / LAÇOS / DESTINO (Rosa Choque / Magenta)
    if any(w in SEMANTIC_LOVE_MYSTERY_WORDS for w in [clean_txt, first_w]):
        anim = TAG_WORD_POP_FOCUS if anim_enabled else ""
        return TAG_EMOTION_MAGENTA, anim, r"\bord6\fscx114\fscy114", False

    # 5. VIDA / CURA / PAZ / ESPERANÇA (Verde Esmeralda)
    if any(w in SEMANTIC_LIFE_HOPE_WORDS for w in [clean_txt, first_w]):
        anim = TAG_WORD_POP_FOCUS if anim_enabled else ""
        return TAG_EMOTION_GREEN, anim, r"\bord6\fscx114\fscy114", False

    # 6. AÇÃO / IMPACTO / CLÍMAX / GRITO / PERIGO (Carmesim Fogo + Super Punch)
    if "!" in cluster_text or any(w in ACTION_IMPACT_WORDS for w in [clean_txt, first_w]):
        anim = TAG_WORD_POP_PUNCH if anim_enabled else ""
        return TAG_CRIMSON_FIRE, anim, r"\bord8\fscx122\fscy122", False

    # 7. GLÓRIA / NOBREZA / PODER / NÚMEROS / NOMES ÉPICOS (Ouro Imperial + Aura)
    if bool(re.search(r'\d', cluster_text)) or any(w in GLORY_NOBLE_WORDS or w in SEMANTIC_GLORY_HERO_WORDS for w in [clean_txt, first_w]):
        anim = TAG_WORD_POP_FOCUS if anim_enabled else ""
        return TAG_IMPERIAL_GOLD, anim, r"\bord6\fscx114\fscy114\blur2", False

    # 8. PERGUNTA / DÚVIDA / REVELAÇÃO (Ciano Elétrico Refinado)
    if "?" in cluster_text or any(clean_txt.startswith(qw) for qw in QUESTION_WORDS) or any(w in SEMANTIC_POWER_TECH_WORDS for w in [clean_txt, first_w]):
        anim = TAG_SLIDE_UP if anim_enabled else ""
        return TAG_CRYSTAL_CYAN, anim, r"\bord6\fscx112\fscy112", False

    # 5. RITMO / CADÊNCIA CONTROLADA ("meio que aleatória" inteligente para alta retenção)
    # Se já tiver 3 ou mais palavras neutras seguidas, dá um realce sutil na palavra de destaque
    if consecutive_neutral >= 3 and len(clean_txt) >= 4:
        # Alternância rítmica sofisticada entre Champagne Gold e White Glow Punch
        if (cluster_index // 2) % 2 == 0:
            anim = TAG_WORD_POP_FOCUS if anim_enabled else ""
            return TAG_CHAMPAGNE_GOLD, anim, r"\bord6\fscx112\fscy112", False
        else:
            anim = TAG_WORD_POP_FOCUS if anim_enabled else ""
            return TAG_WHITE, anim, r"\bord7\fscx114\fscy114\blur1", False

    # 6. BASE NEUTRA: Branco puro cinematográfico ultra-nítido e profissional
    anim = TAG_WORD_POP_CLEAN if anim_enabled else ""
    return TAG_WHITE, anim, r"\bord6", True


def build_word_by_word_dialogues(
    item: Dict[str, Any],
    pop_animation: bool = True,
    mode: str = "contextual",
    global_idx: int = 0
) -> List[Dict[str, Any]]:
    """
    Modo Palavra por Palavra Profissional de Alta Retenção:
    - Agrupa partículas e preposições curtas para fluidez e naturalidade na leitura.
    - Sincronia 100% sequencial com zero sobreposição.
    - Suporta modos:
        * contextual: IA semântica que adapta cor, escala e ênfase conforme contexto e emoção.
        * clean: Branco minimalista viral puro (Alex Hormozi / MrBeast).
        * gold: Branco elegante com ênfase em Ouro Imperial.
        * cyber: Branco cristalino com ênfase em Ciano Neon.
        * classic: Modo tradicional colorido cíclico.
    """
    raw_text = sanitize_text(item.get("text") or item.get("word") or "").upper()
    words = raw_text.split()
    if not words:
        return []

    start = float(item.get("start", 0.0))
    end = float(item.get("end", 0.0))
    w_list = item.get("words")
    if not w_list or len(w_list) != len(words):
        w_list = _interpolate_words(raw_text, start, end)

    clusters = []
    idx = 0
    while idx < len(w_list):
        curr = w_list[idx]
        w_txt = curr.get("word", "").upper().strip()
        c_start = float(curr.get("start", start))
        c_end = float(curr.get("end", end))

        if w_txt in SHORT_PARTICLES and idx + 1 < len(w_list):
            nxt = w_list[idx + 1]
            n_txt = nxt.get("word", "").upper().strip()
            n_end = float(nxt.get("end", end))
            clusters.append({
                "text": f"{w_txt} {n_txt}",
                "start": c_start,
                "end": n_end
            })
            idx += 2
        else:
            clusters.append({
                "text": w_txt,
                "start": c_start,
                "end": c_end
            })
            idx += 1

    events = []
    consecutive_neutral = 0
    for i, cl in enumerate(clusters):
        c_color, anim, extra, is_neutral = classify_cluster_word_by_word(
            cluster_text=cl["text"],
            sentence_text=raw_text,
            consecutive_neutral=consecutive_neutral,
            mode=mode,
            pop_animation=pop_animation,
            cluster_index=i + global_idx
        )
        if is_neutral:
            consecutive_neutral += 1
        else:
            consecutive_neutral = 0

        text = f"{ass_block(TAG_CENTER_POS, c_color, anim, extra)}{cl['text']}"
        events.append({
            "start": cl["start"],
            "end": cl["end"],
            "text": text
        })

    return sanitize_timeline(events)


def build_smart_situational_dialogues(item: Dict[str, Any], pop_animation: bool = True, idx: int = 0) -> List[Dict[str, Any]]:
    """
    Modo Inteligente Situacional (CapCut IA):
    Analisa tom de fala, pontuacao e ritmo semantico para aplicar o formato ideal:
    - Gritos/Impactos: Pop Impact em Coral/Vermelho ou Dourado.
    - Perguntas/Misterio: Contraste Amarelo Ouro e Ciano Neon.
    - Falas Rapidas: Palavra por Palavra dinamico.
    - Frases Curtas: Punchline vibrante.
    - Narrativa/Dialogos: Karaoke Ativo com palavra iluminada.
    """
    raw_text = sanitize_text(item.get("text") or item.get("word") or "").upper()
    words = raw_text.split()
    if not words:
        return []

    start = float(item.get("start", 0.0))
    end = float(item.get("end", 0.0))
    dur = max(0.2, end - start)
    pace = dur / max(1, len(words))

    # 1. Grito ou Impacto Climax
    if "!" in raw_text or any(sw in raw_text for sw in SCREAM_WORDS):
        wrapped = wrap_words_to_lines(words)
        anim = resolve_animation_tag(pop_animation, is_impact=True)
        col = TAG_RED if idx % 2 == 0 else TAG_YELLOW
        text = f"{ass_block(TAG_CENTER_POS, col, anim)}{wrapped}"
        return sanitize_timeline([{"start": start, "end": end, "text": text}])

    # 2. Pergunta ou Duvida
    if "?" in raw_text or any(words[0].startswith(qw) for qw in QUESTION_WORDS if words):
        anim = resolve_animation_tag(pop_animation)
        mid = split_words_balanced(words, max_chars_per_line=18)
        if mid < len(words):
            l1 = " ".join(words[:mid])
            l2 = " ".join(words[mid:])
            text = f"{ass_block(TAG_CENTER_POS, anim)}{ass_block(TAG_YELLOW)}{l1}\\N{ass_block(TAG_CYAN)}{l2}"
        else:
            text = f"{ass_block(TAG_CENTER_POS, anim)}{ass_block(TAG_YELLOW)}{' '.join(words)}"
        return sanitize_timeline([{"start": start, "end": end, "text": text}])

    # 3. Fala muito acelerada
    if pace < 0.28 and len(words) >= 4:
        return build_word_by_word_dialogues(item, pop_animation=pop_animation, mode="contextual", global_idx=idx)

    # 4. Punchline curta (1 a 3 palavras)
    if len(words) <= 3:
        anim = resolve_animation_tag(pop_animation)
        total_len = sum(len(w) for w in words) + len(words) - 1
        if len(words) == 1:
            col = PALETTE[idx % len(PALETTE)]
            text = f"{ass_block(TAG_CENTER_POS, col, anim)}{words[0]}"
        elif len(words) == 2 and total_len <= 18:
            text = f"{ass_block(TAG_CENTER_POS, anim)}{ass_block(TAG_YELLOW)}{words[0]} {ass_block(TAG_CYAN)}{words[1]}"
        else:
            mid = split_words_balanced(words, max_chars_per_line=18)
            if mid < len(words):
                l1 = " ".join(words[:mid])
                l2 = " ".join(words[mid:])
                text = f"{ass_block(TAG_CENTER_POS, anim)}{ass_block(TAG_YELLOW)}{l1}\\N{ass_block(TAG_CYAN)}{l2}"
            else:
                text = f"{ass_block(TAG_CENTER_POS, anim)}{ass_block(TAG_YELLOW)}{' '.join(words)}"
        return sanitize_timeline([{"start": start, "end": end, "text": text}])

    # 5. Dialogo normal / narrativa -> Karaoke Ativo
    return build_karaoke_dialogues(item, pop_animation=pop_animation)


def build_keyword_highlight_dialogues(item: Dict[str, Any], pop_animation: bool = True, idx: int = 0) -> List[Dict[str, Any]]:
    """Frase limpa em branco com substantivo/termo chave em destaque colorido."""
    raw_text = sanitize_text(item.get("text") or item.get("word") or "").upper()
    words = raw_text.split()
    if not words:
        return []

    start = float(item.get("start", 0.0))
    end = float(item.get("end", 0.0))
    kw_idx = _find_keyword_index(words)
    kw_color = TAG_YELLOW if idx % 2 == 0 else TAG_CYAN
    anim = resolve_animation_tag(pop_animation)

    parts = []
    for j, w in enumerate(words):
        if j == kw_idx:
            parts.append(f"{ass_block(kw_color)}{w}{ass_block(TAG_WHITE)}")
        else:
            parts.append(w)

    mid = split_words_balanced(words, max_chars_per_line=18)
    if mid < len(words):
        line1 = " ".join(parts[:mid])
        line2 = " ".join(parts[mid:])
        body = f"{line1}\\N{line2}"
    else:
        body = " ".join(parts)

    full_text = f"{ass_block(TAG_CENTER_POS, TAG_WHITE, anim)}{body}"
    return sanitize_timeline([{"start": start, "end": end, "text": full_text}])


def build_dynamic_animax_dialogues(item: Dict[str, Any], pop_animation: bool = True, idx: int = 0) -> List[Dict[str, Any]]:
    """Estilo classico Animax: 2 linhas em amarelo ouro e ciano eletrico com revelação progressiva palavra por palavra."""
    raw_text = sanitize_text(item.get("text") or item.get("word") or "").upper()
    words = raw_text.split()
    if not words:
        return []

    start = float(item.get("start", 0.0))
    end = float(item.get("end", 0.0))
    w_list = item.get("words")
    if not w_list or len(w_list) != len(words):
        w_list = _interpolate_words(raw_text, start, end)

    c1, c2 = (TAG_YELLOW, TAG_CYAN) if idx % 2 == 0 else (TAG_CYAN, TAG_YELLOW)
    mid = split_words_balanced(words, max_chars_per_line=18)

    events = []
    for i, w_obj in enumerate(w_list):
        w_s = float(w_obj.get("start", start))
        w_e = float(w_obj.get("end", end))

        # Apenas as palavras faladas até agora (0..i) surgem na tela
        visible = words[:i + 1]
        formatted = []
        for j, w in enumerate(visible):
            anim = resolve_animation_tag(pop_animation) if (j == i) else ""
            col = c1 if j < mid else c2
            if j == i:
                formatted.append(f"{ass_block(col, anim)}{w}{ass_block(TAG_WHITE)}")
            else:
                formatted.append(f"{ass_block(col)}{w}{ass_block(TAG_WHITE)}")

        if mid < len(words) and i >= mid:
            l1 = " ".join(formatted[:mid])
            l2 = " ".join(formatted[mid:])
            content = f"{l1}\\N{l2}"
        else:
            content = " ".join(formatted)

        full_text = f"{ass_block(TAG_CENTER_POS)}{content}"
        events.append({"start": w_s, "end": w_e, "text": full_text})

    return sanitize_timeline(events)


def build_solid_color_dialogues(item: Dict[str, Any], color_tag: str, pop_animation: bool = True) -> List[Dict[str, Any]]:
    """Linha em cor unica com quebra equilibrada."""
    raw_text = sanitize_text(item.get("text") or item.get("word") or "").upper()
    words = raw_text.split()
    if not words:
        return []

    start = float(item.get("start", 0.0))
    end = float(item.get("end", 0.0))
    anim = resolve_animation_tag(pop_animation)
    wrapped = wrap_words_to_lines(words)
    text = f"{ass_block(TAG_CENTER_POS, color_tag, anim)}{wrapped}"
    return sanitize_timeline([{"start": start, "end": end, "text": text}])


def build_cyberpunk_neon_dialogues(item: Dict[str, Any], pop_animation: bool = True, idx: int = 0) -> List[Dict[str, Any]]:
    """Estilo Cyberpunk Neon Glow: Núcleo Ciano com Halo Magenta Glow e Sombra Noturna."""
    raw_text = sanitize_text(item.get("text") or item.get("word") or "").upper()
    words = raw_text.split()
    if not words:
        return []
    start = float(item.get("start", 0.0))
    end = float(item.get("end", 0.0))
    anim = resolve_animation_tag(pop_animation)
    neon_tags = r"\c&H00FFFF00&\3c&H00FF00EA&\blur6\bord6\shad3\4c&H00200020&"
    wrapped = wrap_words_to_lines(words)
    text = f"{ass_block(TAG_CENTER_POS, neon_tags, anim)}{wrapped}"
    return sanitize_timeline([{"start": start, "end": end, "text": text}])


def build_manga_3d_dialogues(item: Dict[str, Any], pop_animation: bool = True, idx: int = 0) -> List[Dict[str, Any]]:
    """Estilo Manga 3D Impact: Sombra 3D Extrudada direcional com contorno espesso de anime."""
    raw_text = sanitize_text(item.get("text") or item.get("word") or "").upper()
    words = raw_text.split()
    if not words:
        return []
    start = float(item.get("start", 0.0))
    end = float(item.get("end", 0.0))
    anim = resolve_animation_tag(pop_animation)
    manga_tags = r"\c&H00FFFFFF&\3c&H00000000&\bord7\xshad5\yshad5\4c&H00000000&\frz-1"
    wrapped = wrap_words_to_lines(words)
    text = f"{ass_block(TAG_CENTER_POS, manga_tags, anim)}{wrapped}"
    return sanitize_timeline([{"start": start, "end": end, "text": text}])


def build_shonen_gold_dialogues(item: Dict[str, Any], pop_animation: bool = True, idx: int = 0) -> List[Dict[str, Any]]:
    """Estilo Shonen Aura Gold: Dourado cintilante flamejante com halo quente de energia."""
    raw_text = sanitize_text(item.get("text") or item.get("word") or "").upper()
    words = raw_text.split()
    if not words:
        return []
    start = float(item.get("start", 0.0))
    end = float(item.get("end", 0.0))
    anim = resolve_animation_tag(pop_animation)
    gold_tags = r"\c&H0000E5FF&\3c&H000033CC&\blur4\bord5\shad3\4c&H00000000&"
    wrapped = wrap_words_to_lines(words)
    text = f"{ass_block(TAG_CENTER_POS, gold_tags, anim)}{wrapped}"
    return sanitize_timeline([{"start": start, "end": end, "text": text}])


def build_dark_synthwave_dialogues(item: Dict[str, Any], pop_animation: bool = True, idx: int = 0) -> List[Dict[str, Any]]:
    """Estilo Dark Synthwave: Roxo elétrico e borda ciano neon retro-futurista."""
    raw_text = sanitize_text(item.get("text") or item.get("word") or "").upper()
    words = raw_text.split()
    if not words:
        return []
    start = float(item.get("start", 0.0))
    end = float(item.get("end", 0.0))
    anim = resolve_animation_tag(pop_animation)
    synth_tags = r"\c&H00FF40A8&\3c&H00FFFF00&\bord5\shad4\4c&H00180020&"
    wrapped = wrap_words_to_lines(words)
    text = f"{ass_block(TAG_CENTER_POS, synth_tags, anim)}{wrapped}"
    return sanitize_timeline([{"start": start, "end": end, "text": text}])


def build_diamond_ice_dialogues(item: Dict[str, Any], pop_animation: bool = True, idx: int = 0) -> List[Dict[str, Any]]:
    """Estilo Diamante Ice: Branco puro com contorno azul gelo neon e sombra fria."""
    raw_text = sanitize_text(item.get("text") or item.get("word") or "").upper()
    words = raw_text.split()
    if not words:
        return []
    start = float(item.get("start", 0.0))
    end = float(item.get("end", 0.0))
    anim = resolve_animation_tag(pop_animation)
    ice_tags = r"\c&H00FFFFFF&\3c&H00FFF5E0&\blur3\bord5\shad3\4c&H00301800&"
    wrapped = wrap_words_to_lines(words)
    text = f"{ass_block(TAG_CENTER_POS, ice_tags, anim)}{wrapped}"
    return sanitize_timeline([{"start": start, "end": end, "text": text}])


# ==============================================================================
# PRESETS KINETIC EMOTION (ALTA FIDELIDADE CINEMATOGRÁFICA / CAPCUT PRO)
# ==============================================================================

def build_kinetic_dramatic_dialogues(item: Dict[str, Any], pop_animation: bool = True, idx: int = 0) -> List[Dict[str, Any]]:
    """
    Kinetic Dramático (Fade & Clímax):
    - Transição suave de entrada e saída.
    - Clímax / Impacto explode em escala e cor Dourado Fogo com halo cintilante.
    """
    raw_text = sanitize_text(item.get("text") or item.get("word") or "").upper()
    words = raw_text.split()
    if not words:
        return []

    start = float(item.get("start", 0.0))
    end = float(item.get("end", 0.0))
    has_impact = "!" in raw_text or any(w in ACTION_IMPACT_WORDS or w in SCREAM_WORDS for w in words)

    if has_impact:
        anim = r"\fad(120,80)\t(0,60,\fscx126\fscy126)\t(60,130,\fscx106\fscy106)"
        dram_tags = r"\c&H0015D5FF&\3c&H001080FF&\blur3\bord6\shad3"
    else:
        anim = r"\fad(160,160)"
        dram_tags = r"\c&H00FFFFFF&\3c&H00000000&\bord5\shad2"

    wrapped = wrap_words_to_lines(words)
    text = f"{ass_block(TAG_CENTER_POS, dram_tags, anim)}{wrapped}"
    return sanitize_timeline([{"start": start, "end": end, "text": text}])


def build_kinetic_emotional_dialogues(item: Dict[str, Any], pop_animation: bool = True, idx: int = 0) -> List[Dict[str, Any]]:
    """
    Kinetic Emocional (Slow Breathe):
    - Fade longo, tom frio azul gelo diamante, escala delicada que respira lentamente.
    """
    raw_text = sanitize_text(item.get("text") or item.get("word") or "").upper()
    words = raw_text.split()
    if not words:
        return []

    start = float(item.get("start", 0.0))
    end = float(item.get("end", 0.0))
    anim = r"\fad(200,200)\t(0,100,\fscx98\fscy98)\t(100,220,\fscx94\fscy94)"
    emo_tags = r"\c&H00FFF5E0&\3c&H00503020&\blur2\bord4\shad2"
    wrapped = wrap_words_to_lines(words)
    text = f"{ass_block(TAG_CENTER_POS, emo_tags, anim)}{wrapped}"
    return sanitize_timeline([{"start": start, "end": end, "text": text}])


def build_kinetic_horror_dialogues(item: Dict[str, Any], pop_animation: bool = True, idx: int = 0) -> List[Dict[str, Any]]:
    """
    Kinetic Horror & Tensão (Glitch Sangue):
    - Vermelho sangue profundo, tremor assustador de ângulo (frz) e blur perturbador.
    """
    raw_text = sanitize_text(item.get("text") or item.get("word") or "").upper()
    words = raw_text.split()
    if not words:
        return []

    start = float(item.get("start", 0.0))
    end = float(item.get("end", 0.0))
    has_impact = "!" in raw_text or any(w in ACTION_IMPACT_WORDS for w in words)

    if has_impact:
        anim = r"\fad(40,40)\t(0,30,\frz3\fscx120\fscy120\blur4)\t(30,65,\frz-3\fscx108\fscy108\blur2)\t(65,100,\frz0\fscx112\fscy112\blur1)"
        tags = r"\c&H001818B8&\3c&H00000030&\bord7\shad4\4c&H00000080&"
    else:
        anim = r"\fad(60,60)\t(0,35,\frz2\blur3)\t(35,70,\frz-2\blur1)\t(70,110,\frz0\blur0)"
        tags = r"\c&H001818B8&\3c&H00000000&\bord6\shad3"

    wrapped = wrap_words_to_lines(words)
    text = f"{ass_block(TAG_CENTER_POS, tags, anim)}{wrapped}"
    return sanitize_timeline([{"start": start, "end": end, "text": text}])


def build_kinetic_hype_dialogues(item: Dict[str, Any], pop_animation: bool = True, idx: int = 0) -> List[Dict[str, Any]]:
    """
    Kinetic Hype Impact (Super Pop):
    - Ritmo acelerado, clusters curtos, super escala agressiva e cores em brasa (Laranja / Amarelo / Vermelho).
    """
    raw_text = sanitize_text(item.get("text") or item.get("word") or "").upper()
    words = raw_text.split()
    if not words:
        return []

    start = float(item.get("start", 0.0))
    end = float(item.get("end", 0.0))
    w_list = item.get("words")
    if not w_list or len(w_list) != len(words):
        w_list = _interpolate_words(raw_text, start, end)

    clusters = []
    i = 0
    while i < len(w_list):
        curr = w_list[i]
        c_txt = curr.get("word", "").upper().strip()
        c_s = float(curr.get("start", start))
        c_e = float(curr.get("end", end))
        if i + 1 < len(w_list) and (c_txt in SHORT_PARTICLES or len(c_txt) <= 3):
            nxt = w_list[i + 1]
            n_txt = nxt.get("word", "").upper().strip()
            n_e = float(nxt.get("end", end))
            clusters.append({"text": f"{c_txt} {n_txt}", "start": c_s, "end": n_e})
            i += 2
        else:
            clusters.append({"text": c_txt, "start": c_s, "end": c_e})
            i += 1

    hype_palette = [TAG_EMBER_ORANGE, TAG_YELLOW, TAG_CRIMSON_FIRE]
    events = []
    for c_i, cl in enumerate(clusters):
        c_color = hype_palette[(idx + c_i) % len(hype_palette)]
        anim = r"\t(0,35,\fscx132\fscy132)\t(35,95,\fscx108\fscy108)"
        tags = f"{c_color}\\bord8\\shad3\\4c&H00000000&"
        text = f"{ass_block(TAG_CENTER_POS, tags, anim)}{cl['text']}"
        events.append({"start": cl["start"], "end": cl["end"], "text": text})

    return sanitize_timeline(events)


def build_kinetic_glitch_dialogues(item: Dict[str, Any], pop_animation: bool = True, idx: int = 0) -> List[Dict[str, Any]]:
    """
    Kinetic Cyber Glitch (Distorção):
    - Aberração cromática cibernética com stretch horizontal e distorção angular.
    """
    raw_text = sanitize_text(item.get("text") or item.get("word") or "").upper()
    words = raw_text.split()
    if not words:
        return []

    start = float(item.get("start", 0.0))
    end = float(item.get("end", 0.0))
    anim = r"\fad(30,30)\t(0,25,\fscx120\fscy90\frz2\blur4)\t(25,60,\fscx92\fscy112\frz-2\blur1)\t(60,100,\fscx100\fscy100\frz0\blur0)"
    col = TAG_CYAN if idx % 2 == 0 else TAG_NEON_MAGENTA
    glitch_tags = f"{col}\\3c&H00FF00EA&\\blur4\\bord6\\shad3\\4c&H00200020&"
    wrapped = wrap_words_to_lines(words)
    text = f"{ass_block(TAG_CENTER_POS, glitch_tags, anim)}{wrapped}"
    return sanitize_timeline([{"start": start, "end": end, "text": text}])


def build_kinetic_lyric_dialogues(item: Dict[str, Any], pop_animation: bool = True, idx: int = 0) -> List[Dict[str, Any]]:
    """
    Kinetic Lyric Beat (Bounce Rítmico):
    - Estilo clipe de música: palavra atual salta no beat e brilha em dourado/branco, palavras secundárias atenuadas.
    """
    raw_text = sanitize_text(item.get("text") or item.get("word") or "").upper()
    words = raw_text.split()
    if not words:
        return []

    start = float(item.get("start", 0.0))
    end = float(item.get("end", 0.0))
    w_list = item.get("words")
    if not w_list or len(w_list) != len(words):
        w_list = _interpolate_words(raw_text, start, end)

    events = []
    mid = (len(words) + 1) // 2 if len(words) > 3 else len(words)

    for i, w_obj in enumerate(w_list):
        w_s = float(w_obj.get("start", start))
        w_e = float(w_obj.get("end", end))

        formatted_words = []
        blur_tag = r"\blur2"
        dim_tag = r"\alpha&H45&"
        undim_tag = r"\alpha&H00&"
        bord_tag = r"\bord6"
        for j, w in enumerate(words):
            if j == i:
                anim = r"\t(0,40,\fscy126\fscx94)\t(40,95,\fscy102\fscx100)"
                col = TAG_CHAMPAGNE_GOLD
                blk_active = ass_block(col, anim, blur_tag)
                blk_white = ass_block(TAG_WHITE)
                formatted_words.append(f"{blk_active}{w}{blk_white}")
            else:
                blk_dim = ass_block(dim_tag)
                blk_undim = ass_block(undim_tag)
                formatted_words.append(f"{blk_dim}{w}{blk_undim}")

        if len(words) > 3:
            line1 = " ".join(formatted_words[:mid])
            line2 = " ".join(formatted_words[mid:])
            content = f"{line1}\\N{line2}"
        else:
            content = " ".join(formatted_words)

        blk_base = ass_block(TAG_CENTER_POS, TAG_WHITE, bord_tag)
        full_text = f"{blk_base}{content}"
        events.append({"start": w_s, "end": w_e, "text": full_text})

    return sanitize_timeline(events)


def build_kinetic_minimal_dialogues(item: Dict[str, Any], pop_animation: bool = True, idx: int = 0) -> List[Dict[str, Any]]:
    """
    Kinetic Minimal Bold (Viral Clean / Alex Hormozi):
    - Branco cinematográfico puro, impacto em escala sem cores distrativas.
    """
    return build_word_by_word_dialogues(item, pop_animation=pop_animation, mode="clean", global_idx=idx)


def build_kinetic_elegant_dialogues(item: Dict[str, Any], pop_animation: bool = True, idx: int = 0) -> List[Dict[str, Any]]:
    """
    Kinetic Ouro Nobre (Elegante & Fade):
    - Slide suave ascendente, ouro imperial + branco nobre com halo sutil.
    """
    raw_text = sanitize_text(item.get("text") or item.get("word") or "").upper()
    words = raw_text.split()
    if not words:
        return []

    start = float(item.get("start", 0.0))
    end = float(item.get("end", 0.0))
    anim = r"\fad(120,120)\t(0,70,\fscy108)\t(70,140,\fscy100)"
    eleg_tags = r"\c&H0015D5FF&\3c&H001050A0&\blur3\bord5\shad2"
    wrapped = wrap_words_to_lines(words)
    text = f"{ass_block(TAG_CENTER_POS, eleg_tags, anim)}{wrapped}"
    return sanitize_timeline([{"start": start, "end": end, "text": text}])


def build_kinetic_smooth_dialogues(item: Dict[str, Any], pop_animation: bool = True, idx: int = 0) -> List[Dict[str, Any]]:
    """
    Kinetic Fluido (Ondulação Suave):
    - Ondulação suave estilo onda oceânica, transição relaxada.
    """
    raw_text = sanitize_text(item.get("text") or item.get("word") or "").upper()
    words = raw_text.split()
    if not words:
        return []

    start = float(item.get("start", 0.0))
    end = float(item.get("end", 0.0))
    anim = TAG_KINETIC_WAVE
    smooth_tags = r"\c&H00FFF5E0&\3c&H00A04000&\blur2\bord5\shad2"
    wrapped = wrap_words_to_lines(words)
    text = f"{ass_block(TAG_CENTER_POS, smooth_tags, anim)}{wrapped}"
    return sanitize_timeline([{"start": start, "end": end, "text": text}])


def build_kinetic_shonen_dialogues(item: Dict[str, Any], pop_animation: bool = True, idx: int = 0) -> List[Dict[str, Any]]:
    """
    Kinetic Shonen Power (Golpe & 💥):
    - Estilo anime de ação máxima: zoom épico, tremor sísmico e inclusão de emojis de impacto em ataques.
    """
    raw_text = sanitize_text(item.get("text") or item.get("word") or "").upper()
    words = raw_text.split()
    if not words:
        return []

    start = float(item.get("start", 0.0))
    end = float(item.get("end", 0.0))
    is_attack = "!" in raw_text or any(w in ACTION_IMPACT_WORDS or w in SCREAM_WORDS for w in words)

    if is_attack:
        anim = r"\t(0,25,\frz2\fscx140\fscy140)\t(25,55,\frz-2\fscx120\fscy120)\t(55,90,\frz0\fscx115\fscy115)"
        shonen_tags = r"\c&H0000E5FF&\3c&H000020B0&\blur4\bord8\shad4\4c&H00000000&"
        wrapped = wrap_words_to_lines(words) + " 💥"
    else:
        anim = resolve_animation_tag(pop_animation, is_impact=False)
        shonen_tags = r"\c&H00FFFFFF&\3c&H00000000&\bord6\shad3"
        wrapped = wrap_words_to_lines(words)

    text = f"{ass_block(TAG_CENTER_POS, shonen_tags, anim)}{wrapped}"
    return sanitize_timeline([{"start": start, "end": end, "text": text}])


def build_kinetic_seinen_dialogues(item: Dict[str, Any], pop_animation: bool = True, idx: int = 0) -> List[Dict[str, Any]]:
    """
    Kinetic Seinen Dark (Sombrio & Misterioso):
    - Estilo psicológico maduro (Death Note / Berserk). Tons ardósia escuro, fade lento e clima de suspense.
    """
    raw_text = sanitize_text(item.get("text") or item.get("word") or "").upper()
    words = raw_text.split()
    if not words:
        return []

    start = float(item.get("start", 0.0))
    end = float(item.get("end", 0.0))
    anim = r"\fad(160,160)"
    seinen_tags = r"\c&H00E0D0C0&\3c&H00451835&\bord5\shad3\4c&H00100508&"
    wrapped = wrap_words_to_lines(words)
    text = f"{ass_block(TAG_CENTER_POS, seinen_tags, anim)}{wrapped}"
    return sanitize_timeline([{"start": start, "end": end, "text": text}])


def build_kinetic_kawaii_dialogues(item: Dict[str, Any], pop_animation: bool = True, idx: int = 0) -> List[Dict[str, Any]]:
    """
    Kinetic Kawaii Pop (Pastel & Sparkles ✨):
    - Cores pastel doces (rosa, lavanda, amarelo), salto elástico tipo gelatina e emojis fofos.
    """
    raw_text = sanitize_text(item.get("text") or item.get("word") or "").upper()
    words = raw_text.split()
    if not words:
        return []

    start = float(item.get("start", 0.0))
    end = float(item.get("end", 0.0))
    anim = r"\t(0,65,\fscx115\fscy122)\t(65,135,\fscx100\fscy100)"
    kawaii_tags = r"\c&H00D5A5FF&\3c&H00602080&\blur2\bord5\shad2"
    wrapped = wrap_words_to_lines(words)
    if idx % 2 == 0:
        wrapped += " ✨"
    else:
        wrapped += " 🌸"
    text = f"{ass_block(TAG_CENTER_POS, kawaii_tags, anim)}{wrapped}"
    return sanitize_timeline([{"start": start, "end": end, "text": text}])


class DialogueLayout(dict):
    """
    Estrutura de Metadados de Layout Dinâmico (Padrão Elite Lisz / Otakuroom):
    - Suporta acesso como dict, atributo de objeto (.pos_x, .pos_y, .angle, etc.)
    - Converte transparentemente para int(self) retornando pos_y para 100% de retrocompatibilidade.
    """
    def __init__(
        self,
        pos_x: int = 540,
        pos_y: int = 1020,
        angle: float = 0.0,
        font: str = "Arial Black",
        size: int = 78,
        color_theme: str = "gold",
        align: int = 5,
        is_manga: bool = False
    ):
        super().__init__(
            pos_x=pos_x,
            pos_y=pos_y,
            angle=angle,
            font=font,
            size=size,
            color_theme=color_theme,
            align=align,
            is_manga=is_manga
        )
        self.pos_x = pos_x
        self.pos_y = pos_y
        self.angle = angle
        self.font = font
        self.size = size
        self.color_theme = color_theme
        self.align = align
        self.is_manga = is_manga

    def __int__(self) -> int:
        return int(self.pos_y)

    def __index__(self) -> int:
        return int(self.pos_y)


def build_anime_fx_pro_dialogues(
    item: Dict[str, Any],
    pop_animation: bool = True,
    idx: int = 0,
    pos_y: Any = 1020
) -> List[Dict[str, Any]]:
    """
    Anime FX Pro (Padrão de Elite: Dinâmico, Centralizado e Cinematográfico):
    - Posição Base Padrão: Centralizada no sweet-spot de ação (X=540, Y=1020).
    - Deslocamento Lateral Inteligente: Move para a esquerda (X=380) ou direita (X=700) acompanhando
      os personagens e alternando em diálogos rápidos estilo mangá.
    - Diagonal de Ação / Grito (\frz -6.5° a +5.5°): Dá vida e impacto aos momentos épicos.
    - Troca Dinâmica de Fontes:
        * 'Arial Black' para falas limpas, rápidas e narrativas.
        * 'Lovely Scream Queens' (Pincel Anime Japonês) para gritos, ataques, exclamações e clímax.
    - Escala Dinâmica:
        * 76-80px para diálogos normais.
        * 84-88px para perguntas e revelações.
        * 96-108px para palavras de impacto solo e gritos.
    - Karaoke Ativo: Frase completa nítida, com palavra falada saltando com pop elástico:
        * Dourado/Amarelo Ouro (#FFD400) em falas padrão.
        * Vermelho Sangue Carmesim (#EA1018) com micro-jitter em perigo, ameaças e gritos.
        * Ciano Elétrico Neon (#00FFFF) em termos de poder, habilidades e perguntas.
    """
    raw_text = sanitize_text(item.get("text") or item.get("word") or "").strip()
    clean_txt = re.sub(r'[𐀀-]', '', raw_text).strip().upper()
    words = clean_txt.split()
    if not words:
        return []

    start = float(item.get("start", 0.0))
    end = float(item.get("end", 0.0))
    words_clean = [re.sub(r'[^A-Z0-9ÁÉÍÓÚÂÊÎÔÛÃÕÇ]', '', w) for w in words]

    w_list = item.get("words")
    if not w_list or len(w_list) != len(words):
        w_list = _interpolate_words(clean_txt, start, end)

    has_threat = ("!" in clean_txt or any(w in ("MORRAM", "MORRA", "MATAR", "MORTE", "SANGUE", "DEMAIS", "VERME", "LIXO", "INÚTIL", "INUTIL", "ACABOU", "ZUMBIS", "MONSTRO") for w in words_clean))
    has_power = any(w in ("ESMAGADOR", "DESTRUIÇÃO", "DESTRUICAO", "PODER", "FORÇA", "FORCA", "SUPREMO", "COLOSSAL", "ABSOLUTO", "ABSORÇÃO", "ABSORCAO", "EVASÃO", "EVASAO") for w in words_clean)

    # Extrai propriedades dinâmicas do layout ou usa fallback inteligente
    layout = pos_y if (isinstance(pos_y, dict) or hasattr(pos_y, "pos_x")) else None
    if layout:
        cur_pos_x = getattr(layout, "pos_x", layout.get("pos_x", 540))
        cur_pos_y = getattr(layout, "pos_y", layout.get("pos_y", 1020))
        cur_angle = getattr(layout, "angle", layout.get("angle", 0.0))
        cur_font = getattr(layout, "font", layout.get("font", "Arial Black"))
        cur_size = getattr(layout, "size", layout.get("size", 78))
        cur_theme = getattr(layout, "color_theme", layout.get("color_theme", "gold"))
        cur_align = getattr(layout, "align", layout.get("align", 5))
        is_manga_climax = getattr(layout, "is_manga", layout.get("is_manga", False)) or (cur_pos_y == 600)
    else:
        int_y = int(pos_y) if isinstance(pos_y, (int, float)) else 1020
        is_manga_climax = (int_y == 600)
        cur_pos_x = 540
        # Se veio o antigo default 1380, centraliza no sweet spot (1020)
        cur_pos_y = 600 if is_manga_climax else (1020 if int_y == 1380 else int_y)
        cur_angle = 0.0
        cur_font = "Lovely Scream Queens" if is_manga_climax else "Arial Black"
        cur_size = 94 if is_manga_climax else 78
        cur_theme = "blood_red" if has_threat else ("cyan" if has_power else "gold")
        cur_align = 5

    # Micro-animação dinâmica de entrada variada por índice e contexto emocional:
    if has_threat or "!" in clean_txt:
        # Slam de impacto com tremor sísmico para gritos e frases fortes
        entry_anim = r"\fad(30,30)\t(0,25,\fscx128\fscy128\frz-5)\t(25,55,\fscx108\fscy108\frz4)\t(55,85,\fscx100\fscy100\frz-2)" if pop_animation else ""
    elif "?" in clean_txt:
        # Pulso ciano neon com leve elevação e dispersão para mistério
        entry_anim = r"\fad(40,40)\t(0,35,\fscx116\fscy116\blur3)\t(35,75,\fscx100\fscy100\blur0)" if pop_animation else ""
    else:
        # Alternância de micro-movimentações cinematográficas para as falas gerais:
        anim_pattern = idx % 3
        if anim_pattern == 0:
            # Elastic bounce com overshoot suave
            entry_anim = r"\fad(35,35)\t(0,35,\fscx116\fscy116)\t(35,70,\fscx96\fscy96)\t(70,100,\fscx100\fscy100)" if pop_animation else ""
        elif anim_pattern == 1:
            # Kinetic zoom suave com dissolução de foco
            entry_anim = r"\fad(35,35)\t(0,35,\fscx112\fscy112\blur2)\t(35,75,\fscx100\fscy100\blur0)" if pop_animation else ""
        else:
            # Fast pop energético com assentamento rápido
            entry_anim = r"\fad(30,30)\t(0,30,\fscx118\fscy118)\t(30,65,\fscx100\fscy100)" if pop_animation else ""

    # Monta tags de estilo ASS
    frz_tag = f"\\frz{cur_angle:.1f}" if abs(cur_angle) > 0.1 else ""
    outline_val = 7 if (cur_font == "Lovely Scream Queens" or cur_size >= 90) else 5
    pos_tag = rf"\fn{cur_font}\fs{cur_size}\an{cur_align}\pos({cur_pos_x},{cur_pos_y}){frz_tag}\bord{outline_val}\3c&H00000000&\shad3\4c&H00000000&{entry_anim}"

    # Quebra em 2 linhas dinâmicas e equilibradas para evitar invasão das bordas e justificar visualmente
    mid = split_words_balanced(words, max_chars_per_line=18)

    events = []
    for i, w_obj in enumerate(w_list):
        w_s = float(w_obj.get("start", start))
        w_e = float(w_obj.get("end", end))
        active_word_clean = words_clean[i] if i < len(words_clean) else ""

        # Revelação Progressiva Palavra por Palavra com Sentimento Emocional IA:
        formatted_words = []
        for j in range(i + 1):
            w = words[j]
            curr_clean = words_clean[j] if j < len(words_clean) else ""

            active_tag, word_base_col = get_semantic_color_tags(curr_clean, pop_animation=pop_animation)

            if j == i:
                # Palavra ativa sendo falada no momento com Pop ou Shake emocional
                if is_manga_climax:
                    col = r"\c&H0000E6FF&"
                    pop = r"\t(0,35,\fscx125\fscy125)\t(35,80,\fscx100\fscy100)" if pop_animation else ""
                    formatted_words.append(f"{ass_block(col, pop)}{w}{ass_block(TAG_WHITE)}")
                else:
                    formatted_words.append(f"{ass_block(active_tag)}{w}{ass_block(word_base_col if word_base_col != TAG_WHITE else TAG_WHITE)}")
            else:
                # Palavra anterior já falada: Preserva a cor semântica base
                if word_base_col != TAG_WHITE:
                    formatted_words.append(f"{ass_block(word_base_col)}{w}{ass_block(TAG_WHITE)}")
                else:
                    formatted_words.append(w)

        if mid < len(words) and i >= mid:
            l1 = " ".join(formatted_words[:mid])
            l2 = " ".join(formatted_words[mid:])
            content = f"{l1}\\N{l2}"
        else:
            content = " ".join(formatted_words)

        full_text = f"{ass_block(pos_tag)}{content}"
        events.append({
            "start": w_s,
            "end": w_e,
            "text": full_text
        })

    return sanitize_timeline(events)


def generate_dialogue_events(
    item: Dict[str, Any],
    style_preset: str = "smart_situational",
    dialogue_index: int = 0,
    pop_animation: bool = True,
    pos_y: Any = 1020
) -> List[Dict[str, Any]]:
    """Roteia cada item para o gerador especializado correspondente."""
    if style_preset in ("anime_fx_pro", "anime_fx", "manga_fx"):
        return build_anime_fx_pro_dialogues(item, pop_animation=pop_animation, idx=dialogue_index, pos_y=pos_y)
    # Presets Kinetic Emotion
    elif style_preset in ("kinetic_dramatic", "dramatic"):
        return build_kinetic_dramatic_dialogues(item, pop_animation=pop_animation, idx=dialogue_index)
    elif style_preset in ("kinetic_emotional", "emotional"):
        return build_kinetic_emotional_dialogues(item, pop_animation=pop_animation, idx=dialogue_index)
    elif style_preset in ("kinetic_horror", "horror"):
        return build_kinetic_horror_dialogues(item, pop_animation=pop_animation, idx=dialogue_index)
    elif style_preset in ("kinetic_hype", "hype"):
        return build_kinetic_hype_dialogues(item, pop_animation=pop_animation, idx=dialogue_index)
    elif style_preset in ("kinetic_glitch", "cyber_glitch"):
        return build_kinetic_glitch_dialogues(item, pop_animation=pop_animation, idx=dialogue_index)
    elif style_preset in ("kinetic_lyric", "lyric"):
        return build_kinetic_lyric_dialogues(item, pop_animation=pop_animation, idx=dialogue_index)
    elif style_preset in ("kinetic_minimal", "minimal_bold"):
        return build_kinetic_minimal_dialogues(item, pop_animation=pop_animation, idx=dialogue_index)
    elif style_preset in ("kinetic_elegant", "elegant_gold"):
        return build_kinetic_elegant_dialogues(item, pop_animation=pop_animation, idx=dialogue_index)
    elif style_preset in ("kinetic_smooth", "smooth_wave"):
        return build_kinetic_smooth_dialogues(item, pop_animation=pop_animation, idx=dialogue_index)
    elif style_preset in ("kinetic_shonen", "shonen_power"):
        return build_kinetic_shonen_dialogues(item, pop_animation=pop_animation, idx=dialogue_index)
    elif style_preset in ("kinetic_seinen", "seinen_dark"):
        return build_kinetic_seinen_dialogues(item, pop_animation=pop_animation, idx=dialogue_index)
    elif style_preset in ("kinetic_kawaii", "kawaii_pop"):
        return build_kinetic_kawaii_dialogues(item, pop_animation=pop_animation, idx=dialogue_index)
    # Presets Tradicionais
    elif style_preset == "smart_situational":
        return build_smart_situational_dialogues(item, pop_animation=pop_animation, idx=dialogue_index)
    elif style_preset in ("cyberpunk_neon", "neon"):
        return build_cyberpunk_neon_dialogues(item, pop_animation=pop_animation, idx=dialogue_index)
    elif style_preset in ("manga_3d", "3d"):
        return build_manga_3d_dialogues(item, pop_animation=pop_animation, idx=dialogue_index)
    elif style_preset in ("shonen_gold", "gold_aura"):
        return build_shonen_gold_dialogues(item, pop_animation=pop_animation, idx=dialogue_index)
    elif style_preset in ("dark_synthwave", "synthwave"):
        return build_dark_synthwave_dialogues(item, pop_animation=pop_animation, idx=dialogue_index)
    elif style_preset in ("diamond_ice", "ice"):
        return build_diamond_ice_dialogues(item, pop_animation=pop_animation, idx=dialogue_index)
    elif style_preset in ("word_karaoke", "karaoke"):
        return build_karaoke_dialogues(item, pop_animation=pop_animation)
    elif style_preset in ("word_by_word_contextual", "word_by_word_dynamic"):
        return build_word_by_word_dialogues(item, pop_animation=pop_animation, mode="contextual", global_idx=dialogue_index)
    elif style_preset in ("word_by_word_clean", "word_by_word_minimal", "word_by_word_white"):
        return build_word_by_word_dialogues(item, pop_animation=pop_animation, mode="clean", global_idx=dialogue_index)
    elif style_preset in ("word_by_word_gold",):
        return build_word_by_word_dialogues(item, pop_animation=pop_animation, mode="gold", global_idx=dialogue_index)
    elif style_preset in ("word_by_word_cyber",):
        return build_word_by_word_dialogues(item, pop_animation=pop_animation, mode="cyber", global_idx=dialogue_index)
    elif style_preset in ("word_by_word", "rapid"):
        return build_word_by_word_dialogues(item, pop_animation=pop_animation, mode="classic", global_idx=dialogue_index)
    elif style_preset == "white_keyword_highlight":
        return build_keyword_highlight_dialogues(item, pop_animation=pop_animation, idx=dialogue_index)
    elif style_preset == "yellow_gold":
        return build_solid_color_dialogues(item, TAG_YELLOW, pop_animation=pop_animation)
    elif style_preset == "cyan_neon":
        return build_solid_color_dialogues(item, TAG_CYAN, pop_animation=pop_animation)
    elif style_preset == "green_pop":
        return build_solid_color_dialogues(item, TAG_GREEN, pop_animation=pop_animation)
    elif style_preset == "classic_white":
        return build_solid_color_dialogues(item, TAG_WHITE, pop_animation=pop_animation)
    else:
        # Default: dynamic_animax
        return build_dynamic_animax_dialogues(item, pop_animation=pop_animation, idx=dialogue_index)


def analyze_dialogue_positions(
    video_path: Optional[str],
    sub_list: List[Dict[str, Any]],
    box_y_offset: int = 420,
    box_h: int = 1134,
    box_w: int = 1080,
    manga_interval: Optional[Tuple[float, float]] = None,
    manga_intervals: Optional[List[Tuple[float, float]]] = None
) -> List[DialogueLayout]:
    """
    Motor de Posicionamento e Tipografia Dinâmica Elite (Lisz / Otakuroom Style):
    - Posição Base Padrão: Centralizada no sweet-spot de foco de ação (X=540, Y=1020).
    - Deslocamento Lateral (Esquerda / Direita):
        * Se o personagem estiver na direita, legenda se posiciona à esquerda (X=380, Y=1000).
        * Se o personagem estiver na esquerda, legenda se posiciona à direita (X=700, Y=1000).
        * Em bate-voltas rápidos de diálogo (<1.6s), alterna lateralmente criando ritmo visual de mangá.
    - Diagonal de Ação / Grito / Impacto:
        * Aplica rotação (\frz -6.5° ou +5.5°) com fonte de pincel 'Lovely Scream Queens' e escala ampliada (98-108px).
    - Tipografia Dinâmica:
        * Falas normais/narrativas: 'Arial Black' sólida com contorno preto 5px e sombra 3px.
        * Gritos, poderes, exclamações e clímax: 'Lovely Scream Queens' épica.
    - Tamanho Dinâmico:
        * 78px para frases padrão.
        * 84px para perguntas e revelações.
        * 104-108px para palavras de impacto solo e gritos.
    - Clímax de Mangá: Força Y=600 no topo limpo para nunca colidir com o recorte de personagem!
    """
    if not sub_list:
        return []

    active_intervals = list(manga_intervals) if manga_intervals else ([manga_interval] if manga_interval else [])
    layouts: List[DialogueLayout] = []

    SCREAM_PATTERNS = {
        "MORRA", "MORRAM", "MATAR", "MORTE", "SANGUE", "DEMAIS", "VERME", "LIXO", 
        "INUTIL", "INÚTIL", "ACABOU", "MONSTRO", "ZUMBIS", "DESAPAREÇA", "DESAPARECA", 
        "CHEGA", "NUNCA", "MALDIÇÃO", "MALDICAO", "CUIDADO", "FOGO", "EXPLOSÃO", "EXPLOSAO"
    }
    POWER_PATTERNS = {
        "ESMAGADOR", "DESTRUIÇÃO", "DESTRUICAO", "PODER", "FORÇA", "FORCA", 
        "SUPREMO", "COLOSSAL", "ABSOLUTO", "ABSORÇÃO", "ABSORCAO", "EVASÃO", "EVASAO",
        "HAKI", "GOLPE", "ATAQUE", "LIBERAR", "CAÇAR", "CACAR"
    }

    cap = None
    fps = 24.0
    face_cascade = None
    cv2 = None
    if video_path and os.path.exists(video_path):
        try:
            import cv2 as _cv2
            cv2 = _cv2
            cap = cv2.VideoCapture(video_path)
            fps = cap.get(cv2.CAP_PROP_FPS) or 24.0

            # Procura o arquivo haarcascade em múltiplos caminhos possíveis
            base_dir = os.path.dirname(os.path.abspath(__file__))
            cascade_candidates = [
                os.path.join(base_dir, "haarcascade_frontalface_default.xml"),
                os.path.join(base_dir, "_internal", "haarcascade_frontalface_default.xml"),
                os.path.join(base_dir, "_internal", "cv2", "data", "haarcascade_frontalface_default.xml"),
                os.path.join(base_dir, "cv2", "data", "haarcascade_frontalface_default.xml"),
            ]
            cv2_data = getattr(cv2, "data", None)
            if cv2_data is not None and hasattr(cv2_data, "haarcascades"):
                cascade_candidates.append(os.path.join(cv2_data.haarcascades, "haarcascade_frontalface_default.xml"))
            if getattr(sys, "frozen", False):
                meipass = getattr(sys, "_MEIPASS", "")
                if meipass:
                    cascade_candidates.extend([
                        os.path.join(meipass, "haarcascade_frontalface_default.xml"),
                        os.path.join(meipass, "cv2", "data", "haarcascade_frontalface_default.xml"),
                    ])

            for cand in cascade_candidates:
                if os.path.exists(cand):
                    try:
                        clf = cv2.CascadeClassifier(cand)
                        if clf is not None and not clf.empty():
                            face_cascade = clf
                            break
                    except Exception:
                        pass
        except Exception:
            cap = None
            face_cascade = None

    tilt_toggle = False
    side_toggle = False

    for idx, item in enumerate(sub_list):
        st = float(item.get("start", 0.0))
        et = float(item.get("end", st + 1.0))
        raw_text = sanitize_text(item.get("text") or item.get("word") or "").strip()
        clean_txt = re.sub(r'[^\w\sÁÉÍÓÚÂÊÎÔÛÃÕÇ!?-]', '', raw_text).upper()
        words = clean_txt.split()
        words_clean = [re.sub(r'[^A-Z0-9ÁÉÍÓÚÂÊÎÔÛÃÕÇ]', '', w) for w in words]

        has_exclamation = ("!" in raw_text)
        has_question = ("?" in raw_text)
        has_threat_word = any(w in SCREAM_PATTERNS for w in words_clean)
        has_power_word = any(w in POWER_PATTERNS for w in words_clean)
        is_single_word = (len(words) == 1)
        is_short_punch = (len(words) <= 2)

        # Análise visual do quadro para detectar posição dos personagens
        face_x_center = 0.5
        face_y_center = 0.5
        has_face = False
        face_is_huge = False

        if cv2 is not None and cap is not None and face_cascade is not None and not face_cascade.empty():
            try:
                mid_t = (st + et) / 2.0
                frame_no = int(mid_t * fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
                ret, frame = cap.read()
                if ret and frame is not None:
                    h, w = frame.shape[:2]
                    src_aspect = w / max(1, h)
                    box_aspect = box_w / box_h

                    if src_aspect >= box_aspect:
                        new_w = int(h * box_aspect)
                        cx = max(0, (w - new_w) // 2)
                        crop = frame[:, cx:cx+new_w]
                    else:
                        new_h = int(w / box_aspect)
                        cy = max(0, (h - new_h) // 2)
                        crop = frame[cy:cy+new_h, :]

                    crop_h, crop_w = crop.shape[:2]
                    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40))

                    if len(faces) > 0:
                        faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
                        fx, fy, fw, fh = faces[0]
                        face_x_center = (fx + fw / 2.0) / float(crop_w)
                        face_y_center = (fy + fh / 2.0) / float(crop_h)
                        has_face = True
                        if fw > crop_w * 0.45 or fh > crop_h * 0.45:
                            face_is_huge = True
            except Exception:
                pass

        # Decisão de Posição, Rotação e Tipografia (Padrão de Elite: Estável, Centralizado e Cinematográfico):
        # Caso 1: Grito / Ameaça / Exclamação forte de batalha -> Diagonal com Lovely Scream Queens
        if has_exclamation or has_threat_word or (has_power_word and is_short_punch):
            angle = -6.0 if tilt_toggle else 5.0
            tilt_toggle = not tilt_toggle
            font = "Lovely Scream Queens"
            size = 106 if is_short_punch else 98
            pos_x = 540
            pos_y = 1000
            theme = "blood_red" if (has_threat_word or "!" in raw_text) else "gold"
            align = 5

        # Caso 2: Poder solo ou revelação de habilidade ("EVASÃO", "ABSORÇÃO", "BANKAI", "HAKI") -> Lovely Scream Queens
        elif has_power_word or (is_single_word and any(w in POWER_PATTERNS for w in words_clean)):
            angle = -3.5 if tilt_toggle else 0.0
            tilt_toggle = not tilt_toggle
            font = "Lovely Scream Queens"
            size = 104
            pos_x = 540
            pos_y = 1020
            theme = "cyan" if has_power_word else "gold"
            align = 5

        # Caso 3: Pergunta / Dúvida ("?", "O QUÊ?", "COMO?") -> Ciano Neon com foco elevado e micro-tilt
        elif has_question:
            angle = 2.0 if tilt_toggle else -2.0
            tilt_toggle = not tilt_toggle
            font = "Arial Black"
            size = 84 if is_short_punch else 78
            pos_x = 540
            pos_y = 990
            theme = "cyan"
            align = 5

        # Caso 4: Rosto grande cobrindo a região central inferior -> Eleva para o topo limpo
        elif has_face and face_is_huge and (box_y_offset + face_y_center * box_h) >= 950 and (box_y_offset + face_y_center * box_h) <= 1250:
            angle = -1.5 if tilt_toggle else 1.5
            tilt_toggle = not tilt_toggle
            font = "Arial Black"
            size = 78
            pos_x = 540
            pos_y = 750
            theme = "gold"
            align = 5

        # Caso 5: Padrão Animado Dinâmico (Micro-inclinações orgânicas e ritmo visual vivo)
        else:
            # Alternância orgânica de micro-rotação (-2.4° a +2.4°) para ritmo visual cinematográfico vivo
            tilt_angles = [-2.2, 2.0, -1.8, 2.4, -2.0, 1.6]
            angle = tilt_angles[idx % len(tilt_angles)]
            font = "Arial Black"
            size = 78 if len(words) >= 4 else 82

            # Para falas curtas (bate-volta rápido / diálogos curtos), alterna ligeiramente o foco lateral
            if len(words) <= 3:
                side_offsets = [0, -35, 35, -25, 25]
                pos_x = 540 + side_offsets[idx % len(side_offsets)]
            else:
                pos_x = 540

            # Sutil micro-variação de respiro vertical para a legenda ter cadência e nunca parecer estática
            y_variations = [1020, 1010, 1025]
            pos_y = y_variations[idx % len(y_variations)]
            theme = "gold"
            align = 5

        layouts.append(DialogueLayout(
            pos_x=pos_x,
            pos_y=pos_y,
            angle=angle,
            font=font,
            size=size,
            color_theme=theme,
            align=align,
            is_manga=False
        ))

    if cap is not None:
        cap.release()

    return layouts


def suppress_manga_interval_events(
    events: List[Dict[str, Any]],
    manga_intervals: List[Tuple[float, float]]
) -> List[Dict[str, Any]]:
    """
    Remove ou ajusta eventos de legenda ASS durante intervalos ativos de mangá.
    Como o recorte de mangá já queima a tipografia estilizada de impacto no próprio vídeo,
    não pode haver legenda ASS duplicada na tela durante o clímax mangá.
    Preserva 100% dos diálogos que ocorrem antes ou depois do recorte.
    """
    if not manga_intervals or not events:
        return events

    clean_intervals = sorted([(float(s), float(e)) for s, e in manga_intervals if float(e) > float(s)])
    filtered: List[Dict[str, Any]] = []

    for ev in events:
        s = float(ev["start"])
        e = float(ev["end"])
        if e <= s:
            continue

        keep = True
        cur_ev = dict(ev)

        for m_s, m_e in clean_intervals:
            # Caso A: Evento totalmente antes do mangá
            if e <= m_s:
                continue

            # Caso B: Evento totalmente depois do mangá
            if s >= m_e:
                continue

            # Caso C: Evento totalmente contido dentro do mangá (é a própria fala da punchline destacada no card)
            if s >= m_s - 0.05 and e <= m_e + 0.05:
                keep = False
                break

            # Caso D: Evento começou antes do mangá e termina dentro ou depois
            if s < m_s:
                # Corta o fim para coincidir exatamente com a entrada do mangá
                cur_ev["end"] = round(m_s, 2)
                e = cur_ev["end"]
                # Se tem sub-palavras Whisper, preserva apenas as faladas antes de m_s
                sub_w = cur_ev.get("words")
                if sub_w:
                    valid_w = [w for w in sub_w if float(w.get("start", 0)) < m_s]
                    if valid_w:
                        cur_ev["words"] = valid_w
                        cur_ev["text"] = " ".join(str(w.get("word") or w.get("text") or "").strip() for w in valid_w)
                if cur_ev["end"] <= cur_ev["start"] + 0.08:
                    keep = False
                    break

            # Caso E: Evento começou dentro do mangá e continua depois
            elif s < m_e and e > m_e:
                cur_ev["start"] = round(m_e, 2)
                s = cur_ev["start"]
                sub_w = cur_ev.get("words")
                if sub_w:
                    valid_w = [w for w in sub_w if float(w.get("end", 0)) > m_e]
                    if valid_w:
                        cur_ev["words"] = valid_w
                        cur_ev["text"] = " ".join(str(w.get("word") or w.get("text") or "").strip() for w in valid_w)
                if cur_ev["end"] <= cur_ev["start"] + 0.08:
                    keep = False
                    break

        if keep and cur_ev["end"] > cur_ev["start"] + 0.08:
            filtered.append(cur_ev)

    return filtered



def generate_ass_subtitles(
    items: List[Dict[str, Any]],
    output_ass_path: str,
    video_w: int = 1080,
    video_h: int = 1920,
    style_preset: str = "smart_situational",
    pop_animation: bool = True,
    font_size: int = 76,
    censor_profanity: bool = True,
    max_duration: Optional[float] = None,
    skip_item_indices: Optional[List[int]] = None,
    video_path: Optional[str] = None,
    manga_interval: Optional[Tuple[float, float]] = None,
    manga_intervals: Optional[List[Tuple[float, float]]] = None,
) -> str:
    """
    Gera arquivo de legendas .ass profissional com anti-colisao e zero vazamento:
    - smart_situational (Inteligente por situacao)
    - word_karaoke (Karaoke com palavra ativa iluminada)
    - word_by_word (Palavra por palavra ultra-dinamica)
    - white_keyword_highlight (Branco com palavra-chave colorida)
    - dynamic_animax (2 cores alternadas)
    - yellow_gold, cyan_neon, green_pop, classic_white
    - Higienizacao de palavras inadequadas / palavroes (se censor_profanity=True)
    - max_duration: garante que nenhuma fala ultrapasse a duracao real do video
    """
    active_manga_intervals = list(manga_intervals) if manga_intervals else ([manga_interval] if manga_interval else [])

    # Se os itens sao palavras soltas (Whisper), agrupa em frases/dialogos naturais
    if items and ("words" not in items[0]) and (len((items[0].get("text") or items[0].get("word") or "").split()) <= 1 or ("word" in items[0] and "text" not in items[0])):
        sub_list = group_whisper_words(items, max_duration=max_duration)
    else:
        sub_list = items

    sub_list = apply_corrections_to_items(sub_list)

    if censor_profanity:
        try:
            from censorship_manager import censor_text
            cleaned = []
            for it in sub_list:
                it_c = dict(it)
                txt = it_c.get("text") or it_c.get("word") or ""
                c_txt, _ = censor_text(txt)
                it_c["text"] = c_txt
                if "word" in it_c:
                    it_c["word"] = c_txt
                if "words" in it_c and isinstance(it_c["words"], list):
                    cw_list = []
                    for w_it in it_c["words"]:
                        w_c = dict(w_it)
                        w_txt = w_c.get("text") or w_c.get("word") or ""
                        c_w, _ = censor_text(w_txt)
                        w_c["text"] = c_w
                        if "word" in w_c:
                            w_c["word"] = c_w
                        cw_list.append(w_c)
                    it_c["words"] = cw_list
                cleaned.append(it_c)
            sub_list = cleaned
        except Exception:
            pass

    font_name = "Lovely Scream Queens"
    if "word_by_word" in style_preset or style_preset in ("rapid", "kinetic_hype", "kinetic_shonen"):
        font_size = 84
    elif style_preset in ("anime_fx_pro", "anime_fx", "manga_fx"):
        font_name = "Arial Black"
        font_size = 78
    elif style_preset in ("kinetic_emotional", "kinetic_seinen"):
        font_size = 72
    elif style_preset in ("kinetic_kawaii", "kinetic_elegant"):
        font_size = 78

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {video_w}",
        f"PlayResY: {video_h}",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,6,0,5,20,20,0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    positions = analyze_dialogue_positions(video_path, sub_list, manga_intervals=active_manga_intervals)
    all_raw_events = []
    for idx, item in enumerate(sub_list):
        if skip_item_indices and idx in skip_item_indices:
            continue
        # Evita gerar eventos ASS se o item estiver contido no intervalo de mangá ativo
        it_s = float(item.get("start", 0.0))
        it_e = float(item.get("end", 0.0))
        if active_manga_intervals and any(m_s - 0.15 <= it_s and it_e <= m_e + 0.15 for m_s, m_e in active_manga_intervals):
            continue

        pos_y = positions[idx] if idx < len(positions) else 1020
        evs = generate_dialogue_events(
            item,
            style_preset=style_preset,
            dialogue_index=idx,
            pop_animation=pop_animation,
            pos_y=pos_y
        )
        all_raw_events.extend(evs)

    # Sanitizacao global para garantir ZERO sobreposicao em todo o video e clamping exato no fim do video
    final_clean_events = sanitize_timeline(all_raw_events, max_duration=max_duration)

    # Filtragem definitiva para garantir que NENHUMA legenda regular duplique na tela durante o recorte mangá
    if active_manga_intervals:
        final_clean_events = suppress_manga_interval_events(final_clean_events, active_manga_intervals)

    for ev in final_clean_events:
        lines.append(f"Dialogue: {ev.get('layer', 0)},{_ts(ev['start'])},{_ts(ev['end'])},Default,,0,0,0,,{ev['text']}")

    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return output_ass_path


def parse_time_to_seconds(time_str: Any) -> float:
    """Converte strings como '10', '10s', '0:15', '01:30' ou float em segundos."""
    if not time_str:
        return 0.0
    if isinstance(time_str, (int, float)):
        return max(0.0, float(time_str))
    s = str(time_str).strip().lower().rstrip('s')
    if not s:
        return 0.0
    parts = s.split(':')
    try:
        if len(parts) == 1:
            return max(0.0, float(parts[0]))
        elif len(parts) == 2:
            return max(0.0, float(parts[0]) * 60 + float(parts[1]))
        elif len(parts) == 3:
            return max(0.0, float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2]))
    except Exception:
        return 0.0
    return 0.0


def get_anti_copyright_dsp(mode: str = "advanced") -> str:
    """
    Retorna a cadeia de filtros de audio DSP profissional Anti-Copyright 2026:
    Burlar o Content ID do YouTube, TikTok Sound Match e Meta Rights Manager:
    
    - 'light': Micro-pitch (+3%) e micro-tempo (1.02x). Quase imperceptivel, para faixas com pouca restricao.
    - 'advanced': (Recomendado) Pitch (+3.8%), tempo (1.025x), equalizacao spectral notch (-3dB em 1.2kHz, +2.2dB em 2.8kHz)
                  dispersao estereo de fase (stereowiden) e compressao harmonica. Quebra os hashes de constelacao de picos (FFT).
    - 'aggressive': Pitch (+5%), tempo (1.035x), multi-band EQ com corte/reforco pronunciado, dispersao estereo e compressao quente.
    """
    m = mode.lower().strip()
    if "light" in m or "leve" in m:
        return "rubberband=pitch=1.03:tempo=1.02"
    elif "aggress" in m or "agressiv" in m:
        return (
            "rubberband=pitch=1.05:tempo=1.035,"
            "equalizer=f=600:t=q:w=1:g=-2.5,"
            "equalizer=f=1400:t=q:w=1.2:g=3.0,"
            "equalizer=f=3200:t=q:w=1.5:g=-3.5,"
            "highpass=f=40,"
            "stereowiden=delay=22:feedback=0.28:crossfeed=0.25,"
            "acompressor=threshold=-18dB:ratio=3.0:attack=10:release=180:makeup=2.1"
        )
    else:
        # Default: advanced
        return (
            "rubberband=pitch=1.038:tempo=1.025,"
            "equalizer=f=1200:t=q:w=1.2:g=-3.0,"
            "equalizer=f=2800:t=q:w=1.5:g=2.2,"
            "highpass=f=35,"
            "stereowiden=delay=16:feedback=0.22:crossfeed=0.2,"
            "acompressor=threshold=-16dB:ratio=2.2:attack=15:release=200:makeup=2.8"
        )


def render_video_with_style(
    input_path: str,
    output_path: str,
    title_text: str = "",
    words_with_timestamps: Optional[list] = None,
    music_path: Optional[str] = None,
    music_volume: float = 0.22,
    music_start: str = "00:00",
    anti_copyright: bool = True,
    anti_copyright_mode: str = "advanced",
    music_auto_ducking: bool = True,
    ducking_mode: str = "cinema",
    subtitle_style: str = "smart_situational",
    subtitle_pop: bool = True,
    censor_profanity: bool = True,
    censor_visual: bool = False,
    censor_method: str = "blur",
    censor_blur_strength: str = "medium",
    custom_censor_regions: Optional[list] = None,
    include_watermark_png: bool = True,
    include_cta: bool = True,
    include_blur_sides: bool = True,
    include_anime_fx: bool = True,
    use_local_ai: bool = True,
    local_ai_model: str = "qwen2.5:7b",
    manga_theme: str = "geral",
    on_log: Optional[Callable] = None,
    on_progress: Optional[Callable] = None,
    style: Optional[dict] = None,
) -> bool:
    """
    Renderiza o video final com o pipeline completo do estilo Animax:
    - Fundo com blur suave (gblur sigma=30) cobrindo 1080x1920
    - Video 187% zoom centralizado (1080x1134 de y=420 a y=1554)
    - Header Twitter/Animax com avatar calibrado (225px) + selo verificado
    - Titulo elevado na faixa superior
    - Legendas dinamicas / situacionais / palavras / Anime FX Pro
    - Cenas Mangá (Baki & Sukuna) com Katana Slash e Linhas de Velocidade
    - Protecao anti-copyright no audio
    - Censura inteligente (palavroes no audio/legendas + blur visual ou zoom em animes)
    """
    def log(msg: str):
        if on_log:
            on_log(msg)

    ffmpeg = _find_ffmpeg()
    ffprobe = _find_ffprobe()
    if style is None:
        style = load_style()
    tmp_dir = tempfile.mkdtemp(prefix="animax_render_")

    try:
        # Censura Visual Automatica ou Manual (Busto, decotes, partes intimas em animes)
        if censor_visual:
            try:
                from censorship_manager import detect_anime_sensitive_timeline, process_video_visual_censorship
                if custom_censor_regions:
                    log(f"Shield Anime: Aplicando {len(custom_censor_regions)} regiões de censura personalizadas/manuais...")
                    dets = custom_censor_regions
                else:
                    log("Shield Anime 2026: Escaneando cenas sensíveis (busto, decotes, partes íntimas)...")
                    dets = detect_anime_sensitive_timeline(input_path, fps_sample=4.0, conf_threshold=0.35, on_log=log)

                if dets:
                    desc_method = "Zoom de Foco no Rosto" if "zoom" in str(censor_method).lower() else "Blur Suave"
                    log(f"Shield Anime: {len(dets)} detecções encontradas. Aplicando {desc_method}...")
                    censored_raw = os.path.join(tmp_dir, "censored_raw.mp4")
                    ok_cens = process_video_visual_censorship(
                        input_path, censored_raw, dets,
                        blur_strength=censor_blur_strength,
                        censor_method=censor_method,
                        persistence_seconds=0.45,
                        on_progress=lambda p, m: log(f"Censura visual: {int(p*100)}%") if on_progress else None
                    )
                    if ok_cens and os.path.exists(censored_raw):
                        input_path = censored_raw
                        log(f"Vídeo base higienizado com {desc_method} nas regiões sensíveis.")
                else:
                    log("Shield Anime: Nenhuma cena sensível detectada no vídeo.")
            except Exception as e:
                log(f"Aviso na censura visual: {e}")

        # Obter resolucao do video original
        in_w, in_h = 1280, 720
        probe_cmd = [
            ffprobe, "-v", "quiet",
            "-print_format", "json",
            "-show_streams", input_path
        ]
        try:
            res = subprocess.run(probe_cmd, capture_output=True, text=True,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            data = json.loads(res.stdout)
            v_st = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
            in_w = int(v_st.get("width", 1280))
            in_h = int(v_st.get("height", 720))
        except Exception:
            pass

        log(f"Resolucao de entrada detectada: {in_w}x{in_h}")

        # Gerar Overlay Estatico (Header 225px, Titulo, Watermark 62px, CTA com foguete)
        overlay_png = os.path.join(tmp_dir, "overlay.png")
        create_static_overlay(title_text=title_text, output_png_path=overlay_png, style=style)
        log("Overlay visual estatico gerado com sucesso (Avatar 225px + Watermark 62px).")

        video_dur = get_media_duration(input_path)

        # Anime FX Pro - Recorte de Mangá Neural (ISNet-Anime) + Speedlines + Anti-Copyright
        anime_fx_inputs = []
        neg_enable_str = None
        manga_clips = []
        manga_intervals = []

        if include_anime_fx and words_with_timestamps:
            try:
                import anime_fx_analyzer

                if words_with_timestamps and ("words" not in words_with_timestamps[0]) and (len((words_with_timestamps[0].get("text") or words_with_timestamps[0].get("word") or "").split()) <= 1 or ("word" in words_with_timestamps[0] and "text" not in words_with_timestamps[0])):
                    analysis_items = group_whisper_words(words_with_timestamps, max_duration=video_dur)
                else:
                    analysis_items = words_with_timestamps
                fx_schedule = anime_fx_analyzer.analyze_transcript_for_anime_fx(
                    analysis_items,
                    video_dur,
                    log_callback=log,
                    use_local_ai=use_local_ai,
                    local_ai_model=local_ai_model,
                    video_path=input_path,
                    manga_theme=manga_theme,
                )

                # 1. Recortes de Mangá Clímax Diversificados (Acelerados na GPU CUDA + Paralelismo Multi-Thread)
                events_to_process = fx_schedule.get("manga_events", [])
                if not events_to_process and fx_schedule.get("manga_climax"):
                    events_to_process = [fx_schedule["manga_climax"]]

                if events_to_process:
                    import concurrent.futures
                    import manga_fx_engine
                    gpu_label = getattr(manga_fx_engine, "_GPU_DEVICE_NAME", "GPU CUDA")
                    max_workers = min(4, max(1, len(events_to_process)))
                    log(f"⚡ [GPU CUDA] Gerando {len(events_to_process)} recortes de Mangá em paralelo ({max_workers} workers | {gpu_label})...")
                    base_ui_img = Image.open(overlay_png).convert("RGBA") if os.path.exists(overlay_png) else None

                    def _render_single_manga_clip(task_tuple):
                        idx_ev, ev_item = task_tuple
                        ms = float(ev_item["start"])
                        me_sec = float(ev_item["end"])
                        etp = ev_item.get("event_type", "lateral_sticker_punch")
                        ml1 = ev_item.get("line1", "")
                        ml2 = ev_item.get("line2", "")
                        log(f"Anime FX Pro [GPU]: Gerando Mangá [{etp}] ({idx_ev+1}/{len(events_to_process)}) em {ms:.1f}s-{me_sec:.1f}s ('{ml1}' / '{ml2}')...")
                        try:
                            ui_copy = base_ui_img.copy() if base_ui_img is not None else None
                            seg_path = os.path.join(tmp_dir, f"ai_manga_segment_{idx_ev}.mp4")
                            r_clip = manga_fx_engine.generate_manga_event_clip(
                                video_path=input_path,
                                event_dict=ev_item,
                                output_clip_path=seg_path,
                                static_ui_img=ui_copy
                            )
                            return (idx_ev, ms, me_sec, etp, r_clip, None)
                        except Exception as ex_m:
                            return (idx_ev, ms, me_sec, etp, None, ex_m)

                    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
                        rendered_results = list(pool.map(_render_single_manga_clip, enumerate(events_to_process)))

                    rendered_results.sort(key=lambda x: x[0])
                    for ev_idx, m_s, m_e, etype, res_clip, err_m in rendered_results:
                        if err_m is not None:
                            log(f"Aviso ao gerar Manga AI [{etype}]: {err_m}")
                        elif res_clip and os.path.exists(res_clip):
                            manga_clips.append({
                                "clip": res_clip,
                                "start": m_s,
                                "end": m_e,
                                "type": etype
                            })
                            manga_intervals.append((m_s, m_e))
                            anime_fx_inputs.extend(["-itsoffset", f"{m_s:.3f}", "-i", res_clip])
                            log(f"Anime FX Pro [GPU]: Segmento de Mangá [{etype}] ({ev_idx+1}/{len(events_to_process)}) pronto!")
                        else:
                            log(f"Aviso Anime FX Pro: Não foi possível gerar clipe para [{etype}] ({m_s:.1f}s-{m_e:.1f}s).")

                # 2. Flash Negativo / Invert Pulse (0.18s de alta tensão sem pausar o vídeo)
                if fx_schedule.get("negative_flashes"):
                    neg_conds = [f"between(t,{ev['start']:.3f},{ev['start']+ev['duration']:.3f})" for ev in fx_schedule["negative_flashes"]]
                    neg_enable_str = "+".join(neg_conds)
                    log(f"Anime FX Pro: {len(fx_schedule['negative_flashes'])} flashes negativos aplicados no vídeo.")

            except Exception as e:
                log(f"Aviso no motor Anime FX Pro: {e}")

        # Gerar legendas ASS se fornecidas
        ass_path = None
        if words_with_timestamps:
            ass_path = os.path.join(tmp_dir, "subs.ass")
            generate_ass_subtitles(
                words_with_timestamps,
                ass_path,
                style_preset=subtitle_style,
                pop_animation=subtitle_pop,
                font_size=78,
                censor_profanity=censor_profanity,
                max_duration=video_dur if video_dur > 0 else None,
                skip_item_indices=None,
                video_path=input_path,
                manga_intervals=manga_intervals if manga_intervals else None
            )
            log(f"Arquivo de legendas ASS gerado com sucesso (Estilo: {subtitle_style} | Duração vídeo: {video_dur:.1f}s).")

        # Enquadramento Animax CapCut universal (Janela central: 1080x1134 de y=420 a y=1554)
        # Blindagem Anti-Copyright Visual: Micro-motion contínuo imperceptível (2.8% drift senoidal)
        # Destrói o pHash e a matriz DCT estática do Content ID sem alterar cores, grão ou nitidez.
        BOX_W = 1080
        BOX_H = 1134
        y_overlay = 420

        src_aspect = in_w / max(1, in_h)
        box_aspect = BOX_W / BOX_H  # ~0.9524
        DRIFT_MARGIN = 1.028

        if src_aspect >= box_aspect:
            scaled_h = int(BOX_H * DRIFT_MARGIN)
            if scaled_h % 2 != 0:
                scaled_h += 1
            scaled_w = int(scaled_h * src_aspect)
            if scaled_w % 2 != 0:
                scaled_w += 1
            crop_expr = f"crop={BOX_W}:{BOX_H}:x='({scaled_w}-{BOX_W})/2 + 10*sin(t*0.28)':y='({scaled_h}-{BOX_H})/2 + 8*cos(t*0.22)'"
            fg_base_str = f"[0:v]scale={scaled_w}:{scaled_h},{crop_expr}"
        else:
            scaled_w = int(BOX_W * DRIFT_MARGIN)
            if scaled_w % 2 != 0:
                scaled_w += 1
            scaled_h = int(scaled_w / src_aspect)
            if scaled_h % 2 != 0:
                scaled_h += 1
            crop_expr = f"crop={BOX_W}:{BOX_H}:x='({scaled_w}-{BOX_W})/2 + 8*sin(t*0.28)':y='({scaled_h}-{BOX_H})/2 + 10*cos(t*0.22)'"
            fg_base_str = f"[0:v]scale={scaled_w}:{scaled_h},{crop_expr}"

        fg_filter = fg_base_str
        if neg_enable_str:
            fg_filter += f",negate=enable='{neg_enable_str}'"
        fg_filter += "[fg]"

        # Filtros de Video
        font_dir = str(get_base_dir() / "assets").replace("\\", "/").replace(":", r"\:")
        blur_strength = style.get("video_style", {}).get("blur_strength", 30)

        if include_blur_sides:
            fast_sigma = max(4, int(round(blur_strength / 3.0)))
            bg_filter = (
                f"[0:v]scale=360:640:force_original_aspect_ratio=increase,crop=360:640,"
                f"gblur=sigma={fast_sigma},scale=1080:1920:flags=bilinear[bg]"
            )
            overlay_fg = f"[bg][fg]overlay=0:{y_overlay}[v1]"
        else:
            bg_filter = "color=c=black:s=1080x1920:d=1[bg]"
            overlay_fg = f"[bg][fg]overlay=0:{y_overlay}:shortest=1[v1]"

        vf_parts = [
            bg_filter,
            fg_filter,
            overlay_fg
        ]

        curr_v = "[v1]"

        # Camada de Recortes de Mangá Clímax Diversificados (Radial Speedlines, Eyes Panel, Sticker Punch)
        for k, clip_info in enumerate(manga_clips):
            inp_idx = 2 + k
            m_s = clip_info["start"]
            m_e = clip_info["end"]
            vf_parts.append(f"{curr_v}[{inp_idx}:v]overlay=0:0:enable='between(t,{m_s:.3f},{m_e:.3f})':eof_action=pass[v_manga_{k}]")
            curr_v = f"[v_manga_{k}]"

        # Overlay Estático (Header 225px, Titulo, Watermark 62px, CTA)
        vf_parts.append(f"{curr_v}[1:v]overlay=0:0[v2]")

        if ass_path:
            ass_escaped = ass_path.replace("\\", "/").replace(":", r"\:")
            vf_parts.append(f"[v2]subtitles=filename='{ass_escaped}':fontsdir='{font_dir}'[vout]")
        else:
            vf_parts.append("[v2]copy[vout]")

        vf = ";".join(vf_parts)

        # Montagem dos Inputs e Audio
        inputs = ["-i", input_path, "-i", overlay_png, *anime_fx_inputs]
        has_music = bool(music_path and Path(music_path).exists())

        # Censura de Audio (Mudo cirurgico em palavras inadequadas)
        vocal_filter = "[0:a]volume=1.0[vocal]"
        if censor_profanity and words_with_timestamps:
            try:
                from censorship_manager import find_profanity_intervals, build_audio_mute_filter
                mutes = find_profanity_intervals(words_with_timestamps)
                if mutes:
                    log(f"Censura de Áudio: {len(mutes)} palavras inadequadas silenciadas cirurgicamente.")
                    vocal_filter = build_audio_mute_filter(mutes, in_label="[0:a]", out_label="[vocal]")
            except Exception as e:
                log(f"Aviso censura audio: {e}")

        if has_music:
            music_ss = parse_time_to_seconds(music_start)
            if music_ss > 0:
                inputs += ["-stream_loop", "-1", "-ss", f"{music_ss:.2f}", "-i", music_path]
                log(f"Musica iniciada no minuto/segundo selecionado: {music_ss:.1f}s (pulo de introducao).")
            else:
                inputs += ["-stream_loop", "-1", "-i", music_path]

            music_input_idx = inputs.count("-i") - 1

            # Calibração Proporcional: volume da música calibrado com base no volume médio do vídeo
            try:
                vid_stats = detect_audio_levels(input_path)
                mus_stats = detect_audio_levels(str(music_path))
                v_mean = vid_stats.get("mean_volume", -20.0)
                m_mean = mus_stats.get("mean_volume", -12.0)
                m_max = mus_stats.get("max_volume", 0.0)
                calibrated_gain, th_linear = calculate_proportional_music_volume(
                    v_mean, m_mean, music_volume, music_max_db=m_max
                )
                effective_music_vol = calibrated_gain
                log(f"Calibração de Áudio Inteligente: Vídeo={v_mean:.1f}dB | Música={m_mean:.1f}dB (Pico: {m_max:.1f}dB) -> Ganho Base={effective_music_vol:.4f} | Detector={th_linear:.4f}")
            except Exception as e:
                effective_music_vol = max(0.02, min(0.35, music_volume * 0.8))
                th_linear = 0.08
                log(f"Aviso calibração proporcional de áudio (usando fallback seguro): {e}")

            if anti_copyright:
                dsp = get_anti_copyright_dsp(mode=anti_copyright_mode)
                bgm_prep = f"[{music_input_idx}:a]{dsp},volume={effective_music_vol}"
                log(f"Protecao Anti-Copyright 2026 aplicada na musica (Modo: {anti_copyright_mode}).")
            else:
                bgm_prep = f"[{music_input_idx}:a]volume={effective_music_vol}"

            if music_auto_ducking:
                # Presets de Auto Ducking Ultra Fluido (Padrão Broadcast / Zero Pumping):
                # - cinema: Transição aveludada (-6dB a -7dB), release longo (1200ms) sem cortes bruscos
                # - balanced: Transição estável (-8dB a -9dB), release equilibrado (1000ms)
                # - aggressive: Foco total na voz (-11dB a -12dB), release firme (850ms)
                ducking_presets = {
                    "cinema": {"ratio": 1.35, "threshold": 0.05, "attack": 80, "release": 900, "knee": 3.0, "name": "Cinema & Anime (Fluido -3dB a -4dB)"},
                    "balanced": {"ratio": 1.55, "threshold": 0.045, "attack": 60, "release": 750, "knee": 2.5, "name": "Equilibrado (Suave -5dB a -6dB)"},
                    "aggressive": {"ratio": 1.85, "threshold": 0.04, "attack": 40, "release": 600, "knee": 2.0, "name": "Foco na Voz (-8dB)"},
                }
                params = ducking_presets.get(ducking_mode, ducking_presets["cinema"])
                rat = params["ratio"]
                att = params["attack"]
                rel = params["release"]
                kne = params["knee"]
                p_name = params["name"]

                af = (
                    f"{vocal_filter};"
                    f"[vocal]asplit=2[vocal_mix][vocal_sc];"
                    f"[vocal_sc]highpass=f=200,lowpass=f=3500[vocal_voice];"
                    f"{bgm_prep}[bgm_raw];"
                    f"[bgm_raw][vocal_voice]sidechaincompress=threshold={th_linear}:ratio={rat}:attack={att}:release={rel}:knee={kne}[bgm];"
                    f"[vocal_mix][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,alimiter=limit=0.98[aout]"
                )
                log(f"Auto Ducking Fluido ativado [{p_name}]: Música calibrada proporcional ao vídeo, transição suave ({rel}ms) sem bombeamento.")
            else:
                # Modo Constante na Medida Certa (Foco no Diálogo, volume estável sem oscilar)
                # Aplicamos Voice Carve (-2.0dB em 1.5kHz) para garantir que as falas fiquem cristalinas
                bgm_filter = f"{bgm_prep},equalizer=f=1500:width_type=o:width=1.5:g=-2.0[bgm]"
                af = (
                    f"{vocal_filter};"
                    f"{bgm_filter};"
                    f"[vocal][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,alimiter=limit=0.98[aout]"
                )
                log(f"Volume de Música Constante (Calibrado ao Vídeo): Estável na medida certa, sem oscilações.")
        else:
            if vocal_filter != "[0:a]volume=1.0[vocal]":
                af = vocal_filter.replace("[vocal]", "[aout]")
            else:
                af = "[0:a]volume=1.0[aout]"

        cmd_nvenc = [
            ffmpeg,
            "-hwaccel", "auto",
            *inputs,
            "-filter_complex", f"{vf};{af}",
            "-map", "[vout]",
            "-map", "[aout]",
            "-map_metadata", "-1",
            "-map_chapters", "-1",
            "-fflags", "+bitexact",
            "-c:v", "h264_nvenc",
            "-preset", "p4",
            "-rc", "vbr",
            "-cq", "18",
            "-b:v", "0",
            "-spatial_aq", "1",
            "-temporal_aq", "1",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-r", "60",
            "-y",
            output_path
        ]

        cmd_cpu = [
            ffmpeg,
            *inputs,
            "-filter_complex", f"{vf};{af}",
            "-map", "[vout]",
            "-map", "[aout]",
            "-map_metadata", "-1",
            "-map_chapters", "-1",
            "-fflags", "+bitexact",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "17",
            "-c:a", "aac",
            "-b:a", "192k",
            "-r", "60",
            "-y",
            output_path
        ]

        log("⚡ [GPU NVENC] Iniciando renderização acelerada na Placa de Vídeo (h264_nvenc 60 FPS)...")
        if on_progress:
            on_progress(20, "Renderizando na GPU (NVENC)...")

        p = subprocess.run(
            cmd_nvenc,
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )

        if p.returncode != 0:
            log("Aviso: NVENC indisponível ou ocupado — acionando fallback automático para CPU (libx264)...")
            p = subprocess.run(
                cmd_cpu,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            )

        if p.returncode != 0:
            err = p.stderr[-800:] if p.stderr else "Erro desconhecido"
            log(f"Erro FFmpeg: {err}")
            return False

        if on_progress:
            on_progress(100, "Concluido!")

        log(f"Renderizacao concluida com sucesso: {output_path}")
        return True

    except Exception as e:
        log(f"Erro no pipeline de renderizacao: {e}")
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    print("subtitle_renderer.py - modulo carregado com sucesso.")
