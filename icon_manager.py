"""
icon_manager.py - Gerenciador de Ícones Vetoriais Profissionais para o Urahara Studio.

Gera e gerencia ícones lineares de alta precisão (sem emojis) renderizados
diretamente via Pillow com supersampling 4x e interpolação Lanczos para CustomTkinter.
Zero dependência de fontes externas; funciona 100% offline e com alta definição (HiDPI).
"""

from __future__ import annotations
import math
from typing import Tuple, Dict
from PIL import Image, ImageDraw
import customtkinter as ctk

# Cache em memória para reaproveitamento instantâneo de ícones
_ICON_CACHE: Dict[Tuple[str, int, int, str], ctk.CTkImage] = {}

# Paleta padrão Urahara Studio
THEME_COLORS = {
    "primary": "#10b981",    # Emerald Green Kisuke
    "primary_dark": "#059669",
    "white": "#fafafa",      # Off-white linear
    "muted": "#71717a",      # Zinc 500
    "subtle": "#a1a1aa",     # Zinc 400
    "gold": "#f59e0b",       # Amber / Spiritual energy
    "danger": "#ef4444",     # Red alert
    "border": "#27272a",
    "void": "#09090b",
}


CANVAS_SIZE = 120  # Resolução canônica de desenho (5x do viewBox 24x24)
GRID = 24.0
SCALE_FACTOR = CANVAS_SIZE / GRID  # 5.0


def _pt(x: float, y: float) -> Tuple[float, float]:
    """Converte coordenadas [0..24] do viewBox para o canvas canônico."""
    return (x * SCALE_FACTOR, y * SCALE_FACTOR)


def _box(x1: float, y1: float, x2: float, y2: float) -> list[float]:
    """Converte bounding box [x1, y1, x2, y2] do viewBox para o canvas canônico."""
    return [x1 * SCALE_FACTOR, y1 * SCALE_FACTOR, x2 * SCALE_FACTOR, y2 * SCALE_FACTOR]


def _draw_vector_canvas(name: str, color: str) -> Image.Image:
    """Desenha o ícone vetorial no canvas canônico de 120x120px com margens seguras."""
    img = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Espessura de linha proporcional (~1.8px no grid 24x24 = ~9px no canvas 120px)
    lw = max(3, int(1.8 * SCALE_FACTOR))
    s = SCALE_FACTOR

    name_clean = name.lower().strip()

    if name_clean in ("upscale", "arrow_up"):
        d.line([_pt(4.5, 19.5), _pt(19.5, 19.5)], fill=color, width=lw)
        d.line([_pt(12, 16), _pt(12, 4.5)], fill=color, width=lw)
        d.line([_pt(6.5, 10), _pt(12, 4.5), _pt(17.5, 10)], fill=color, width=lw)

    elif name_clean in ("director", "clapper", "clapperboard"):
        d.rounded_rectangle(_box(3.5, 8, 20.5, 19.5), radius=int(2 * s), outline=color, width=lw)
        d.line([_pt(3.5, 8), _pt(20.5, 8)], fill=color, width=lw)
        d.polygon([_pt(3.5, 4.5), _pt(20.5, 4.5), _pt(20.5, 8), _pt(3.5, 8)], outline=color)
        d.line([_pt(7.5, 4.5), _pt(6.5, 8)], fill=color, width=lw)
        d.line([_pt(12.5, 4.5), _pt(11.5, 8)], fill=color, width=lw)
        d.line([_pt(17.5, 4.5), _pt(16.5, 8)], fill=color, width=lw)

    elif name_clean in ("scissors", "cut", "refiner"):
        d.ellipse(_box(4, 14, 9.5, 19.5), outline=color, width=lw)
        d.ellipse(_box(14.5, 14, 20, 19.5), outline=color, width=lw)
        d.line([_pt(8.5, 14.5), _pt(18.5, 4.5)], fill=color, width=lw)
        d.line([_pt(15.5, 14.5), _pt(5.5, 4.5)], fill=color, width=lw)
        d.ellipse(_box(11, 11, 13, 13), fill=color)

    elif name_clean in ("studio", "pipeline", "layers"):
        d.rounded_rectangle(_box(4, 4.5, 20, 8.5), radius=int(1.8 * s), outline=color, width=lw)
        d.rounded_rectangle(_box(4, 10, 20, 14), radius=int(1.8 * s), outline=color, width=lw)
        d.rounded_rectangle(_box(4, 15.5, 20, 19.5), radius=int(1.8 * s), outline=color, width=lw)

    elif name_clean in ("audio", "waveform", "sound"):
        bars = [(5, 10, 14), (8.5, 6, 18), (12, 4, 20), (15.5, 7, 17), (19, 10, 14)]
        bw = max(3, int(2.2 * s))
        for bx, top, bot in bars:
            d.line([_pt(bx, top), _pt(bx, bot)], fill=color, width=bw)

    elif name_clean in ("instagram", "camera"):
        d.rounded_rectangle(_box(4, 4, 20, 20), radius=int(4.5 * s), outline=color, width=lw)
        d.ellipse(_box(8.5, 8.5, 15.5, 15.5), outline=color, width=lw)
        d.ellipse(_box(16.5, 7, 18, 8.5), fill=color)

    elif name_clean in ("youtube", "video", "yt"):
        d.rounded_rectangle(_box(3.5, 5, 20.5, 19), radius=int(4 * s), outline=color, width=lw)
        d.polygon([_pt(10, 8.5), _pt(10, 15.5), _pt(15.5, 12)], fill=color)

    elif name_clean in ("search", "finder", "magnifier"):
        d.ellipse(_box(4, 4, 14.5, 14.5), outline=color, width=lw)
        d.line([_pt(13, 13), _pt(19.5, 19.5)], fill=color, width=max(3, int(2.4 * s)))

    elif name_clean in ("settings", "gear", "config"):
        cx, cy = 12 * s, 12 * s
        r_out = 7.2 * s
        r_hole = 2.8 * s
        d.ellipse([cx - r_out, cy - r_out, cx + r_out, cy + r_out], outline=color, width=lw)
        d.ellipse([cx - r_hole, cy - r_hole, cx + r_hole, cy + r_hole], outline=color, width=lw)
        for i in range(6):
            ang = i * (2 * math.pi / 6)
            x1 = cx + (r_out - 1 * s) * math.cos(ang)
            y1 = cy + (r_out - 1 * s) * math.sin(ang)
            x2 = cx + (r_out + 2.4 * s) * math.cos(ang)
            y2 = cy + (r_out + 2.4 * s) * math.sin(ang)
            d.line([(x1, y1), (x2, y2)], fill=color, width=max(3, int(2.4 * s)))

    elif name_clean in ("refresh", "sync", "reload"):
        d.arc(_box(4.5, 4.5, 19.5, 19.5), start=30, end=150, fill=color, width=lw)
        d.arc(_box(4.5, 4.5, 19.5, 19.5), start=210, end=330, fill=color, width=lw)
        d.polygon([_pt(18.5, 10.5), _pt(18.5, 15.5), _pt(14.5, 14)], fill=color)
        d.polygon([_pt(5.5, 13.5), _pt(5.5, 8.5), _pt(9.5, 10)], fill=color)

    elif name_clean in ("shield", "security", "protect"):
        d.polygon([
            _pt(12, 4), _pt(19, 6.5), _pt(19, 12),
            _pt(12, 20), _pt(5, 12), _pt(5, 6.5)
        ], outline=color)
        d.line([_pt(12, 4), _pt(12, 19.5)], fill=color, width=max(2, int(1.2 * s)))

    elif name_clean in ("play", "start"):
        d.polygon([_pt(8, 6), _pt(8, 18), _pt(18, 12)], fill=color)

    elif name_clean in ("folder", "dir", "browse"):
        d.polygon([
            _pt(4, 6.5), _pt(9, 6.5), _pt(11, 8.5), _pt(20, 8.5),
            _pt(20, 18.5), _pt(4, 18.5)
        ], outline=color)

    elif name_clean in ("trash", "delete", "clear"):
        d.line([_pt(5, 6.5), _pt(19, 6.5)], fill=color, width=lw)
        d.line([_pt(9, 4.5), _pt(15, 4.5)], fill=color, width=lw)
        d.rounded_rectangle(_box(6.5, 6.5, 17.5, 19.5), radius=int(1.8 * s), outline=color, width=lw)
        d.line([_pt(10, 9.5), _pt(10, 16.5)], fill=color, width=lw)
        d.line([_pt(14, 9.5), _pt(14, 16.5)], fill=color, width=lw)

    elif name_clean in ("sparkle", "ai", "magic", "star"):
        cx, cy = 12 * s, 12 * s
        points = [
            _pt(12, 4), (cx + 2.5 * s, cy - 2.5 * s),
            _pt(20, 12), (cx + 2.5 * s, cy + 2.5 * s),
            _pt(12, 20), (cx - 2.5 * s, cy + 2.5 * s),
            _pt(4, 12), (cx - 2.5 * s, cy - 2.5 * s)
        ]
        d.polygon(points, fill=color)

    elif name_clean in ("check", "ok", "success"):
        d.line([_pt(4.5, 12.5), _pt(9.5, 17), _pt(19.5, 6.5)], fill=color, width=max(3, int(2.4 * s)))

    elif name_clean in ("download", "install"):
        d.line([_pt(12, 4.5), _pt(12, 14.5)], fill=color, width=lw)
        d.line([_pt(7.5, 10.5), _pt(12, 14.5), _pt(16.5, 10.5)], fill=color, width=lw)
        d.line([_pt(5, 19), _pt(19, 19)], fill=color, width=lw)

    elif name_clean in ("clock", "time", "duration"):
        d.ellipse(_box(4, 4, 20, 20), outline=color, width=lw)
        d.line([_pt(12, 6.5), _pt(12, 12), _pt(16, 12)], fill=color, width=lw)

    elif name_clean in ("film", "strip", "fps"):
        d.rounded_rectangle(_box(4, 4.5, 20, 19.5), radius=int(1.8 * s), outline=color, width=lw)
        d.line([_pt(7.5, 4.5), _pt(7.5, 19.5)], fill=color, width=lw)
        d.line([_pt(16.5, 4.5), _pt(16.5, 19.5)], fill=color, width=lw)
        for py in (8, 12, 16):
            d.line([_pt(4, py), _pt(7.5, py)], fill=color, width=lw)
            d.line([_pt(16.5, py), _pt(20, py)], fill=color, width=lw)

    elif name_clean in ("eye", "view", "preview"):
        d.arc(_box(4, 5.5, 20, 20.5), start=210, end=330, fill=color, width=lw)
        d.arc(_box(4, 3.5, 20, 18.5), start=30, end=150, fill=color, width=lw)
        d.ellipse(_box(9.5, 9.5, 14.5, 14.5), fill=color)

    elif name_clean in ("copy", "clipboard"):
        d.rounded_rectangle(_box(8, 8, 20, 20), radius=int(1.5 * s), outline=color, width=lw)
        d.line([_pt(4, 16), _pt(4, 4), _pt(16, 4)], fill=color, width=lw)

    elif name_clean in ("image", "picture", "thumbnail", "photo"):
        d.rounded_rectangle(_box(4, 5, 20, 19), radius=int(2 * s), outline=color, width=lw)
        d.ellipse(_box(7.5, 8, 10.5, 11), fill=color)
        d.polygon([_pt(5.5, 17.5), _pt(10, 12.5), _pt(13.5, 15.5), _pt(16.5, 11.5), _pt(18.5, 14.5), _pt(18.5, 17.5)], fill=color)

    elif name_clean in ("lightning", "zap", "bolt", "energy"):
        d.polygon([_pt(13, 3.5), _pt(6, 12.5), _pt(11.5, 12.5), _pt(10.5, 20.5), _pt(18, 10.5), _pt(12.5, 10.5)], fill=color)

    elif name_clean in ("arrow_right", "chevron_right", "next"):
        d.line([_pt(9, 6), _pt(15, 12), _pt(9, 18)], fill=color, width=max(3, int(2.4 * s)))

    elif name_clean in ("tag", "label", "price"):
        d.polygon([_pt(4, 12), _pt(12, 4), _pt(19, 4), _pt(19, 11), _pt(11, 19), _pt(4, 12)], outline=color)
        d.ellipse(_box(14.5, 7, 16.5, 9), fill=color)

    elif name_clean in ("dot", "indicator"):
        d.ellipse(_box(7, 7, 17, 17), fill=color)

    else:
        d.ellipse(_box(4.5, 4.5, 19.5, 19.5), outline=color, width=lw)

    return img


def _draw_icon(name: str, width: int, height: int, color: str, scale: int = 2) -> Image.Image:
    """Compatibilidade retroativa: desenha o canvas canônico e redimensiona."""
    canvas_img = _draw_vector_canvas(name, color)
    out_w = max(width * scale, 32)
    out_h = max(height * scale, 32)
    return canvas_img.resize((out_w, out_h), Image.Resampling.LANCZOS)


def get_icon(name: str, size: Tuple[int, int] = (18, 18), color: str = "#fafafa") -> ctk.CTkImage:
    """
    Retorna uma instância reutilizável de ctk.CTkImage para o ícone especificado.
    Renderiza em canvas vetorial canônico com supersampling Lanczos 2x para nitidez HiDPI perfeita.
    """
    w, h = size
    cache_key = (name.lower().strip(), w, h, color)
    if cache_key in _ICON_CACHE:
        return _ICON_CACHE[cache_key]

    canvas_img = _draw_vector_canvas(name, color)

    # Gera buffer com o dobro da resolução lógica para renderização perfeita em monitores com escalonamento (125%/150%)
    out_w = max(w * 2, 32)
    out_h = max(h * 2, 32)
    img_2x = canvas_img.resize((out_w, out_h), Image.Resampling.LANCZOS)

    ctk_img = ctk.CTkImage(light_image=img_2x, dark_image=img_2x, size=(w, h))
    _ICON_CACHE[cache_key] = ctk_img
    return ctk_img


# Dicionário mapeando os nomes limpos das abas aos seus ícones vetoriais
TAB_ICONS = {
    "Upscaling": "upscale",
    "Diretor IA": "director",
    "Refinador Mastercut": "scissors",
    "Studio Pipeline": "studio",
    "Separação de Áudio": "audio",
    "Instagram Shorts": "instagram",
    "YouTube Shorts": "youtube",
    "Anime Finder": "search",
    "Configurações": "settings",
}
