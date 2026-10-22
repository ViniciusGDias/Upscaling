"""
emoji_text_renderer.py - Motor de Tipografia de Alto Impacto com Suporte Nativo a Emojis Coloridos

Permite desenhar textos elegantes e virais (Impact, Arial Black, Lovely Scream Queens, etc.)
combinados perfeitamente com emojis coloridos reais (Segoe UI Emoji / Apple Color Emoji),
eliminando completamente os retângulos cinzas (tofu) de glifos não encontrados.
"""
from __future__ import annotations

import os
import re
from typing import List, Tuple, Optional, Any
from PIL import Image, ImageDraw, ImageFont

# Cache de fontes de emoji carregadas para performance máxima
_EMOJI_FONT_CACHE: dict[int, ImageFont.FreeTypeFont] = {}


def get_emoji_font(size: int = 60) -> Optional[ImageFont.FreeTypeFont]:
    """Carrega fonte vetorial com suporte nativo a emojis coloridos no sistema operacional."""
    size = max(12, int(size))
    if size in _EMOJI_FONT_CACHE:
        return _EMOJI_FONT_CACHE[size]

    candidates = [
        "C:/Windows/Fonts/seguiemj.ttf",
        "C:/Windows/Fonts/Segoe UI Emoji.ttf",
        "/System/Library/Fonts/Apple Color Emoji.ttc",
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                font = ImageFont.truetype(p, size)
                _EMOJI_FONT_CACHE[size] = font
                return font
            except Exception:
                continue

    try:
        font = ImageFont.truetype("seguiemj.ttf", size)
        _EMOJI_FONT_CACHE[size] = font
        return font
    except Exception:
        pass

    return None


def split_text_and_emojis(text: str) -> List[Tuple[str, bool]]:
    """
    Separa a string em segmentos alternados de texto comum e emojis.
    Retorna lista de tuplas (conteúdo, é_emoji).
    """
    if not text:
        return []

    # 1. Tenta biblioteca emoji (a mais precisa para sequências ZWJ, tons de pele e bandeiras)
    try:
        import emoji
        em_list = emoji.emoji_list(text)
        if em_list:
            chunks: List[Tuple[str, bool]] = []
            last_idx = 0
            for item in em_list:
                st = item["match_start"]
                ed = item["match_end"]
                if st > last_idx:
                    chunks.append((text[last_idx:st], False))
                chunks.append((text[st:ed], True))
                last_idx = ed
            if last_idx < len(text):
                chunks.append((text[last_idx:], False))
            return chunks
        else:
            return [(text, False)]
    except Exception:
        pass

    # 2. Fallback via regex de faixas Unicode de emojis
    try:
        emoji_pattern = re.compile(
            r"(\u00a9|\u00ae|[\u2000-\u3300]|\ud83c[\ud000-\udfff]|\ud83d[\ud000-\udfff]|\ud83e[\ud000-\udfff])+"
        )
        parts: List[Tuple[str, bool]] = []
        last_i = 0
        for m in emoji_pattern.finditer(text):
            if m.start() > last_i:
                parts.append((text[last_i:m.start()], False))
            parts.append((m.group(), True))
            last_i = m.end()
        if last_i < len(text):
            parts.append((text[last_i:], False))
        return parts if parts else [(text, False)]
    except Exception:
        return [(text, False)]


def measure_mixed_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    main_font: ImageFont.ImageFont,
    emoji_font: Optional[ImageFont.ImageFont] = None,
    spacing: int = 4
) -> Tuple[int, int]:
    """Mede largura e altura total do texto misturado com emojis."""
    segments = split_text_and_emojis(text)
    total_w = 0
    max_h = 0
    for chunk, is_em in segments:
        f = emoji_font if (is_em and emoji_font) else main_font
        b = draw.textbbox((0, 0), chunk, font=f)
        w = b[2] - b[0]
        h = b[3] - b[1]
        total_w += w + (spacing if is_em else 0)
        max_h = max(max_h, h)
    return total_w, max_h


def render_mixed_text(
    draw: ImageDraw.ImageDraw,
    pos: Tuple[int, int],
    text: str,
    main_font: ImageFont.ImageFont,
    emoji_font: Optional[ImageFont.ImageFont] = None,
    fill_color: Any = "#ffffff",
    stroke_color: Any = None,
    stroke_width: int = 0,
    shadow_color: Any = None,
    shadow_offset: Tuple[int, int] = (0, 0),
    spacing: int = 4
) -> int:
    """
    Renderiza texto composto por palavras estilizadas e emojis coloridos reais.
    Retorna a largura total desenhada.
    """
    segments = split_text_and_emojis(text)

    # 1. Camada de Sombra (apenas para texto comum para manter emojis limpos e nítidos)
    sx, sy = shadow_offset
    if shadow_color and (sx != 0 or sy != 0):
        cur_x = pos[0] + sx
        cur_y = pos[1] + sy
        for chunk, is_em in segments:
            if not is_em or not emoji_font:
                draw.text((cur_x, cur_y), chunk, font=main_font, fill=shadow_color)
                b = draw.textbbox((0, 0), chunk, font=main_font)
                cur_x += (b[2] - b[0])
            else:
                b = draw.textbbox((0, 0), chunk, font=emoji_font)
                cur_x += (b[2] - b[0]) + spacing

    # 2. Camada Principal (Texto com Stroke + Emojis com embedded_color)
    cur_x = pos[0]
    cur_y = pos[1]
    for chunk, is_em in segments:
        if not is_em or not emoji_font:
            if stroke_width > 0 and stroke_color:
                draw.text(
                    (cur_x, cur_y),
                    chunk,
                    font=main_font,
                    fill=fill_color,
                    stroke_width=stroke_width,
                    stroke_fill=stroke_color
                )
            else:
                draw.text((cur_x, cur_y), chunk, font=main_font, fill=fill_color)
            b = draw.textbbox((0, 0), chunk, font=main_font)
            cur_x += (b[2] - b[0])
        else:
            b = draw.textbbox((0, 0), chunk, font=emoji_font)
            # Offset vertical suave de +2px para balancear com fontes em caixa alta
            draw.text((cur_x, cur_y + 2), chunk, font=emoji_font, embedded_color=True)
            cur_x += (b[2] - b[0]) + spacing

    return cur_x - pos[0]
