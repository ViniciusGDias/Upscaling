"""
manga_fx_engine.py - Motor de Efeitos Visuais & Cenas Estilo Mangá (Anime FX Pro)
Gera proceduralmente os efeitos de alta fidelidade baseados nas referências reais (Baki & Sukuna):
  1. Corte de Katana (Slash de lâmina branca cortando a tela)
  2. Linhas de Velocidade Radiais Mangá (Speed Lines Carmesim/Vermelho e Preto)
  3. Recorte Estilo Mangá do Personagem (Arte em preto e branco de alto contraste + olhos brilhantes)
  4. Símbolos 3D de Anime Estilizados (Ex: '?' 3D Dourado/Branco - NUNCA emojis simples)
  5. Efeito Negativo / Neon Edge Invert Flash (0.4s-0.6s de inversão dramática)
  6. Efeito Aura de Energia (Glow pulsante dourado/ciano em volta)
"""

import os
import sys
import re
import math
import random
import tempfile
import numpy as np
from pathlib import Path
from typing import Tuple, List, Optional, Dict, Any
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
import cv2


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def get_asset_font(font_name: str = "Lovely-Scream-Queens.otf") -> str:
    """Retorna o caminho de uma fonte em assets ou fallback do sistema."""
    base = get_base_dir()
    p = base / "assets" / font_name
    if p.exists():
        return str(p)
    # Fallback para fontes comuns no Windows
    win_fonts = [
        r"C:\Windows\Fonts\impact.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
    ]
    for wf in win_fonts:
        if os.path.exists(wf):
            return wf
    return "arial.ttf"


def create_full_bleed_blurred_background(source_frame: Image.Image, width: int = 1080, height: int = 1920, blur_radius: int = 30) -> Image.Image:
    """
    Cria fundo desfocado preenchendo a tela inteira 1080x1920 (full bleed) com aspect ratio preservado,
    idêntico ao fundo do vídeo principal para evitar que faixas pretas apareçam atrás do header e rodapé.
    """
    bg_full = ImageOps.fit(source_frame, (width, height), method=Image.Resampling.LANCZOS)
    bg_blur = bg_full.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    dimmer = Image.new("RGBA", (width, height), (0, 0, 0, 70))
    return Image.alpha_composite(bg_blur.convert("RGBA"), dimmer)


# ==============================================================================
# 1. LINHAS DE VELOCIDADE RADIAIS MANGÁ (Manga Radial Speed Lines)
# ==============================================================================

def generate_radial_speed_lines_frame(
    width: int = 1080,
    height: int = 1134,
    center: Optional[Tuple[int, int]] = None,
    num_rays: int = 100,
    inner_radius: int = 130,
    bg_color: Tuple[int, int, int] = (12, 14, 20),      # Preto / Grafite Noturno Mangá
    ray_color: Tuple[int, int, int] = (240, 240, 248),  # Speedlines brancas puras estilo Mangá P&B
    seed: Optional[int] = None
) -> Image.Image:
    """
    Gera um frame único de linhas de velocidade radiais (Speed Lines tradicionais estilo Mangá P&B).
    Traços monocromáticos brancos de alto contraste sobre fundo escuro.
    """
    if seed is not None:
        random.seed(seed)

    if center is None:
        center = (width // 2, int(height * 0.48))

    cx, cy = center
    max_radius = int(math.hypot(max(cx, width - cx), max(cy, height - cy))) + 80

    # Cria imagem base escura
    img = Image.new("RGBA", (width, height), (*bg_color, 255))
    draw = ImageDraw.Draw(img)

    # Gera raios angulares pontiagudos do centro para fora
    angles = np.linspace(0, 2 * math.pi, num_rays, endpoint=False)
    for ang in angles:
        ang_jitter = ang + random.uniform(-0.018, 0.018)
        r_inner = inner_radius + random.randint(-40, 60)
        r_outer = max_radius

        width_factor = random.uniform(0.014, 0.042)
        ang1 = ang_jitter - width_factor
        ang2 = ang_jitter + width_factor

        p1 = (cx + r_inner * math.cos(ang_jitter), cy + r_inner * math.sin(ang_jitter))
        p2 = (cx + r_outer * math.cos(ang1), cy + r_outer * math.sin(ang1))
        p3 = (cx + r_outer * math.cos(ang2), cy + r_outer * math.sin(ang2))

        # Variar cor sutilmente entre branco puro e cinza prateado de mangá
        r_col = min(255, max(180, ray_color[0] + random.randint(-30, 15)))
        g_col = min(255, max(180, ray_color[1] + random.randint(-30, 15)))
        b_col = min(255, max(190, ray_color[2] + random.randint(-20, 15)))
        ray_alpha = random.randint(160, 240)

        draw.polygon([p1, p2, p3], fill=(r_col, g_col, b_col, ray_alpha))

    # Vinheta escura no centro para dar foco ao personagem
    vignette = Image.new("L", (width, height), 0)
    v_draw = ImageDraw.Draw(vignette)
    for r in range(max_radius, 0, -25):
        alpha = int(255 * (1.0 - (r / max_radius) ** 1.6))
        v_draw.ellipse(
            (cx - r, cy - r, cx + r, cy + r),
            fill=alpha
        )
    vignette = vignette.filter(ImageFilter.GaussianBlur(radius=35))

    dark_overlay = Image.new("RGBA", (width, height), (0, 0, 5, 170))
    img = Image.composite(img, dark_overlay, vignette)

    return img


# ==============================================================================
# 2. CORTE DE KATANA (Katana Blade Slash Arc Animation)
# ==============================================================================

def generate_katana_slash_frame(
    progress: float,  # 0.0 a 1.0
    width: int = 1080,
    height: int = 1134,
    slash_angle_deg: float = -18.0
) -> Image.Image:
    """
    Gera um frame transparente do golpe da Katana cortando a tela.
    Lâmina curva branca brilhante com rastro de energia ciano/dourado.
    """
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    if progress <= 0.0 or progress >= 1.0:
        return img

    cy = int(height * 0.38)
    cx = int(width * 0.5)

    if progress < 0.4:
        scale = progress / 0.4
    else:
        scale = max(0.0, 1.0 - (progress - 0.4) / 0.6)

    blade_len = int(width * 1.15 * scale)
    blade_thickness = int(26 * scale)

    if blade_len <= 10 or blade_thickness <= 1:
        return img

    slash_canvas = Image.new("RGBA", (int(width * 1.4), int(height * 0.6)), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(slash_canvas)
    sc_w, sc_h = slash_canvas.size
    mid_x, mid_y = sc_w // 2, sc_h // 2

    x_coords = np.linspace(-blade_len // 2, blade_len // 2, 80)
    top_points = []
    bottom_points = []

    for x in x_coords:
        t = 1.0 - (2.0 * x / blade_len) ** 2
        t = max(0.0, t)
        half_thick = (blade_thickness * 0.5) * (t ** 0.6)
        curve_y = -35.0 * (1.0 - (2.0 * x / blade_len) ** 2)

        top_points.append((mid_x + x, mid_y + curve_y - half_thick))
        bottom_points.append((mid_x + x, mid_y + curve_y + half_thick))

    polygon_points = top_points + list(reversed(bottom_points))

    for glow_expand in (18, 10, 4):
        glow_canvas = Image.new("RGBA", slash_canvas.size, (0, 0, 0, 0))
        g_draw = ImageDraw.Draw(glow_canvas)
        g_col = (0, 235, 255, int(110 / (glow_expand / 4))) if glow_expand > 6 else (255, 255, 255, 190)
        g_draw.polygon(polygon_points, fill=g_col)
        glow_canvas = glow_canvas.filter(ImageFilter.GaussianBlur(radius=glow_expand))
        slash_canvas = Image.alpha_composite(slash_canvas, glow_canvas)

    s_draw.polygon(polygon_points, fill=(255, 255, 255, 255))

    rotated = slash_canvas.rotate(slash_angle_deg, resample=Image.BICUBIC, expand=True)

    rw, rh = rotated.size
    paste_x = cx - rw // 2
    paste_y = cy - rh // 2

    img.alpha_composite(rotated, (paste_x, paste_y))
    return img


# ==============================================================================
# 3. RECORTE ESTILO MANGÁ DO PERSONAGEM (Manga Inking & Segmentação Limpa)
# ==============================================================================

def extract_and_ink_manga_character(
    source_frame: Image.Image,
    target_width: int = 1080,
    target_height: int = 1134
) -> Image.Image:
    """
    Extrai o personagem do frame e converte para nanquim puro de mangá:
    - GrabCut automático para remover cenário e deixar fundo transparente
    - Suavização bilateral para pele de anime
    - Extração adaptativa de contornos de nanquim preto
    - 3 tons de retícula clássica de mangá shonen (Preto nanquim, Cinza retícula, Branco puro)
    - Olhos amarelos brilhantes estilo Baki (bk_055)
    """
    img_rgb = source_frame.resize((target_width, target_height), Image.Resampling.LANCZOS)
    cv_img = cv2.cvtColor(np.array(img_rgb), cv2.COLOR_RGB2BGR)
    h, w = cv_img.shape[:2]

    # 1. Segmentação do personagem com GrabCut
    mask = np.zeros(cv_img.shape[:2], np.uint8)
    bgdModel = np.zeros((1, 65), np.float64)
    fgdModel = np.zeros((1, 65), np.float64)
    # Foca no personagem central / inferior
    rect = (int(w * 0.04), int(h * 0.08), int(w * 0.92), int(h * 0.90))

    try:
        cv2.grabCut(cv_img, mask, rect, bgdModel, fgdModel, 3, cv2.GC_INIT_WITH_RECT)
        alpha_mask = np.where((mask == 2) | (mask == 0), 0, 255).astype('uint8')
        # Suaviza bordas do recorte
        alpha_mask = cv2.GaussianBlur(alpha_mask, (7, 7), 0)
    except Exception:
        # Fallback de máscara radial se o grabcut falhar
        Y, X = np.ogrid[:h, :w]
        dist = np.sqrt((X - w / 2) ** 2 + (Y - h * 0.55) ** 2)
        alpha_mask = np.clip((1.0 - dist / (w * 0.55)) * 255, 0, 255).astype('uint8')

    # 2. Tons de Nanquim e Retícula de Mangá
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    smooth = cv2.bilateralFilter(gray, 7, 50, 50)

    # Contornos de tinta preta
    edges = cv2.adaptiveThreshold(
        smooth, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=9,
        C=3
    )
    kernel = np.ones((2, 2), np.uint8)
    edges_ink = cv2.erode(edges, kernel, iterations=1)

    # Tonalização estilo Shonen Mangá
    manga_tones = np.zeros_like(gray)
    manga_tones[smooth < 80] = 20        # Preto nanquim
    manga_tones[(smooth >= 80) & (smooth < 180)] = 205  # Cinza retícula
    manga_tones[smooth >= 180] = 252    # Branco

    manga_comp = np.where(edges_ink == 0, 10, manga_tones)

    # 3. Monta RGBA com a máscara do personagem
    manga_rgba = cv2.cvtColor(manga_comp, cv2.COLOR_GRAY2BGRA)
    manga_rgba[:, :, 3] = alpha_mask

    pil_char = Image.fromarray(cv2.cvtColor(manga_rgba, cv2.COLOR_BGRA2RGBA))

    # 4. Olhos Amarelos Brilhantes (Yellow Glowing Eyes estilo Baki)
    glow_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(glow_layer)

    eye_roi_y1 = int(h * 0.28)
    eye_roi_y2 = int(h * 0.60)
    eye_roi = gray[eye_roi_y1:eye_roi_y2, :]

    _, eye_thresh = cv2.threshold(eye_roi, 215, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(eye_thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    valid_pts = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if 20 < area < 900:
            M = cv2.moments(cnt)
            if M["m00"] > 0:
                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"]) + eye_roi_y1
                valid_pts.append((cx, cy))

    if valid_pts:
        for ex, ey in valid_pts[:4]:
            r = 16
            g_draw.ellipse((ex - r, ey - r, ex + r, ey + r), fill=(255, 220, 30, 220))
        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=8))
        pil_char = Image.alpha_composite(pil_char, glow_layer)

    return pil_char


# ==============================================================================
# 4. SÍMBOLOS 3D DE ANIME ESTILIZADOS (3D Anime Graphic Symbols - NO BASIC EMOJIS)
# ==============================================================================

def generate_anime_3d_symbol(
    symbol_char: str = "?",
    width: int = 240,
    height: int = 240,
    primary_color: Tuple[int, int, int] = (255, 255, 255),
    shadow_color: Tuple[int, int, int] = (160, 140, 100),
    glow_color: Tuple[int, int, int] = (255, 215, 0),
    size: int = 170
) -> Image.Image:
    """
    Gera um símbolo estilizado 3D de anime com profundidade, relevo e aura dourada/branca.
    Exatamente como o '?' no frame sk_079 do Sukuna ("com uma costura na testa.. ?").
    NÃO usa emojis de celular básicos! É uma peça gráfica de computação visual.
    """
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    font_path = get_asset_font("Queens.otf")
    try:
        font = ImageFont.truetype(font_path, size=size)
    except Exception:
        font = ImageFont.load_default()

    dummy = Image.new("RGBA", (10, 10))
    d_draw = ImageDraw.Draw(dummy)
    bbox = d_draw.textbbox((0, 0), symbol_char, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    cx = (width - tw) // 2 - bbox[0]
    cy = (height - th) // 2 - bbox[1]

    # Glow dourado/branco atrás do símbolo
    glow_canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(glow_canvas)
    g_draw.text((cx, cy), symbol_char, font=font, fill=(*glow_color, 240))
    glow_canvas = glow_canvas.filter(ImageFilter.GaussianBlur(radius=16))
    canvas = Image.alpha_composite(canvas, glow_canvas)

    # Extrusão 3D
    draw = ImageDraw.Draw(canvas)
    depth_layers = 12
    for d in range(depth_layers, 0, -1):
        ox = cx + int(d * 0.9)
        oy = cy + int(d * 1.3)
        factor = d / depth_layers
        r = int(shadow_color[0] * (1.0 - factor * 0.4))
        g = int(shadow_color[1] * (1.0 - factor * 0.4))
        b = int(shadow_color[2] * (1.0 - factor * 0.4))
        draw.text((ox, oy), symbol_char, font=font, fill=(r, g, b, 255))

    # Contorno escuro
    outline_canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    o_draw = ImageDraw.Draw(outline_canvas)
    for ox, oy in [(-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1), (-1, 1), (1, -1)]:
        o_draw.text((cx + ox, cy + oy), symbol_char, font=font, fill=(20, 20, 20, 220))
    canvas = Image.alpha_composite(canvas, outline_canvas)

    # Face frontal branca luminosa
    draw = ImageDraw.Draw(canvas)
    draw.text((cx, cy), symbol_char, font=font, fill=(*primary_color, 255))

    # Highlight especular 3D
    highlight_canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    h_draw = ImageDraw.Draw(highlight_canvas)
    h_draw.text((cx - 1, cy - 2), symbol_char, font=font, fill=(255, 255, 255, 160))
    canvas = Image.alpha_composite(canvas, highlight_canvas)

    return canvas


# ==============================================================================
# 5. GERADOR COMPLETO DA CENA CLÍMAX MANGÁ (Manga Climax Composite)
# ==============================================================================

def create_manga_climax_card(
    character_frame: Image.Image,
    climax_text: str = "VOCÊ FALA DEMAIS",
    width: int = 1080,
    height: int = 1134,
    color_theme: str = "red"
) -> Image.Image:
    """
    Cria a cena completa no estilo do Baki (bk_055):
    - Speed lines radiais carmesim de fundo
    - Personagem em mangá nanquim preto & branco recortado perfeitamente
    - Texto gigante de impacto em sangue escorrendo / horror vermelho com borda preta
    """
    # 1. Fundo de speed lines
    speed_bg = generate_radial_speed_lines_frame(
        width=width,
        height=height,
        bg_color=(50, 4, 10),
        ray_color=(195, 15, 28)
    )

    # 2. Personagem nanquim com fundo transparente
    pil_char = extract_and_ink_manga_character(character_frame, target_width=width, target_height=height)

    # 3. Mescla personagem sobre o fundo de speed lines
    composite = Image.alpha_composite(speed_bg, pil_char)

    # 4. Texto dramático em estilo horror sangrento
    font_p = get_asset_font("Lovely-Scream-Queens.otf")
    text_size = 115
    try:
        font = ImageFont.truetype(font_p, size=text_size)
    except Exception:
        font = ImageFont.load_default()

    t_canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    t_draw = ImageDraw.Draw(t_canvas)

    words = climax_text.upper().strip().split()
    if len(words) > 3:
        mid = (len(words) + 1) // 2
        lines = [" ".join(words[:mid]), " ".join(words[mid:])]
    else:
        lines = [climax_text.upper().strip()]

    curr_y = int(height * 0.08)
    for line in lines:
        bbox = t_draw.textbbox((0, 0), line, font=font)
        lw = bbox[2] - bbox[0]
        lh = bbox[3] - bbox[1]
        lx = (width - lw) // 2

        # Borda preta grossa e pesada (7px)
        for ox in range(-7, 8):
            for oy in range(-7, 8):
                if ox * ox + oy * oy <= 49:
                    t_draw.text((lx + ox, curr_y + oy), line, font=font, fill=(0, 0, 0, 255))

        # Núcleo do texto em Vermelho Sangue Carmesim Brilhante (#F50F19)
        t_draw.text((lx, curr_y), line, font=font, fill=(245, 15, 25, 255))
        curr_y += lh + 18

    final_card = Image.alpha_composite(composite, t_canvas)
    return final_card


# ==============================================================================
# 6. MOTOR NEURAL DE RECORTE DE MANGÁ (AI Manga Segmentation & Stylization)
# ==============================================================================

def generate_ai_manga_assets(
    video_path: str,
    timestamp_sec: float,
    output_dir: str
) -> Optional[Dict[str, str]]:
    """
    Gera proceduralmente os assets de recorte de mangá profissional via Rede Neural (ISNet-Anime):
      - Segmentação neural do personagem sem borrões ou artefatos de GrabCut.
      - Nanquim japonês autêntico com extração neural de lineart (skytnt/anime-seg).
      - Retícula Shonen de meio-tom (screentone halftone dots).
      - Borda branca externa espessa (efeito adesivo de mangá / anime sticker).
      - Linhas de velocidade radiais (Speed Lines) centralizadas no personagem.
    Retorna caminhos para:
      {'character_path': str, 'speedlines_path': str}
    """
    os.makedirs(output_dir, exist_ok=True)
    if not os.path.exists(video_path):
        return None

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(timestamp_sec * fps))
    ret, raw_bgr = cap.read()
    cap.release()

    if not ret or raw_bgr is None:
        return None

    raw_rgb = cv2.cvtColor(raw_bgr, cv2.COLOR_BGR2RGB)
    raw_pil = Image.fromarray(raw_rgb)
    h, w = raw_rgb.shape[:2]

    try:
        from imgutils.segment import segment_rgba_with_isnetis
        from imgutils.edge import edge_image_with_lineart_anime

        # 1. Segmentação Neural do Personagem
        _, cutout_rgba = segment_rgba_with_isnetis(raw_pil)
        cutout_np = np.array(cutout_rgba)
        alpha = cutout_np[:, :, 3]

        # 2. Extração Neural de Lineart Anime
        lineart_pil = edge_image_with_lineart_anime(raw_pil)
        lineart_np = np.array(lineart_pil.convert("L"))

        # 3. Estilo Sukuna/Lisz: Preserva cores do anime + contorno de nanquim reforçado
        ink = lineart_np.astype(float) / 255.0
        ink_boosted = np.clip((ink - 0.20) / 0.80, 0.0, 1.0)
        color_ink = np.clip(raw_rgb.astype(float) * (ink_boosted[:, :, None] ** 0.85), 0, 255).astype(np.uint8)

        char_rgba = Image.fromarray(np.dstack([color_ink, alpha]))
        bbox = char_rgba.getbbox()
        char_cropped = char_rgba.crop(bbox) if bbox else char_rgba

        # 4. Construção do Adesivo com Aura Dourada Suave e Borda Branca 8px
        cw, ch = char_cropped.size
        pad = 60
        base = Image.new("RGBA", (cw + pad * 2, ch + pad * 2), (0, 0, 0, 0))
        base.paste(char_cropped, (pad, pad), char_cropped)
        alpha_mask = np.array(base)[:, :, 3]

        # Aura Dourada (Smooth falloff)
        kernel_aura = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31))
        dil_aura = cv2.dilate(alpha_mask, kernel_aura, iterations=2)
        aura_np = np.zeros((base.size[1], base.size[0], 4), dtype=np.uint8)
        aura_np[:, :, 0] = 255
        aura_np[:, :, 1] = 210
        aura_np[:, :, 2] = 20
        aura_np[:, :, 3] = np.where(dil_aura > 10, 220, 0)
        aura_pil = Image.fromarray(aura_np).filter(ImageFilter.GaussianBlur(radius=16))

        # Borda Branca de Adesivo (8px)
        kernel_white = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
        dil_white = cv2.dilate(alpha_mask, kernel_white, iterations=1)
        white_np = np.zeros((base.size[1], base.size[0], 4), dtype=np.uint8)
        white_np[:, :, 0:3] = 255
        white_np[:, :, 3] = np.where(dil_white > 20, 255, 0)
        white_pil = Image.fromarray(white_np).filter(ImageFilter.GaussianBlur(radius=1.5))

        # Borda Interna Preta (2px)
        kernel_black = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        dil_black = cv2.dilate(alpha_mask, kernel_black, iterations=1)
        black_np = np.zeros((base.size[1], base.size[0], 4), dtype=np.uint8)
        black_np[:, :, 0:3] = 20
        black_np[:, :, 3] = np.where(dil_black > 20, 255, 0)
        black_pil = Image.fromarray(black_np)

        sticker_comp = Image.new("RGBA", base.size, (0, 0, 0, 0))
        sticker_comp.paste(aura_pil, (0, 0), aura_pil)
        sticker_comp.paste(white_pil, (0, 0), white_pil)
        sticker_comp.paste(black_pil, (0, 0), black_pil)
        sticker_comp.paste(base, (0, 0), base)

        char_path = os.path.join(output_dir, f"ai_manga_char_{int(timestamp_sec*10)}.png")
        sticker_comp.save(char_path, "PNG")

        # 5. Speedlines / Fundo
        speed_img = generate_radial_speed_lines_frame(width=1080, height=1134)
        speed_path = os.path.join(output_dir, f"ai_speedlines_{int(timestamp_sec*10)}.png")
        speed_img.save(speed_path, "PNG")

        # 6. Corte de Katana
        slash_img = generate_katana_slash_frame(progress=0.42, width=1080, height=1134, slash_angle_deg=-16.0)
        slash_path = os.path.join(output_dir, f"ai_katana_slash_{int(timestamp_sec*10)}.png")
        slash_img.save(slash_path, "PNG")

        return {
            "character_path": char_path,
            "speedlines_path": speed_path,
            "slash_path": slash_path
        }

    except Exception as e:
        print(f"[MangaFX] Falha ao processar com IA: {e}")
        return None


def find_best_manga_take_with_quality_gate(
    video_path: str,
    target_t: float,
    start_sec: float,
    end_sec: float,
    min_coverage: float = 0.12
) -> Dict[str, Any]:
    """
    Quality Gate de Vídeo & Seleção do Melhor Take para Mangá:
    Varre os frames ao redor do momento de impacto (target_t), avaliando:
      1. Nitidez (Laplacian variance - elimina motion blur)
      2. Exposição e Luminância (evita quadros escuros demais ou lavados)
      3. Segmentação Neural de Personagem (ISNet-Anime)
      4. Presença de Rosto/Expressão (imgutils.detect.detect_faces)
    Gera um relatório de qualidade detalhado e seleciona com precisão matemática
    o take de melhor composição. Caso a cena não tenha personagem recortável nítido,
    o Quality Gate aprova automaticamente a modalidade de Painel de Cena (Scene Panel),
    evitando qualquer deformação ou círculo vazio.
    """
    cap = cv2.VideoCapture(video_path)
    v_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    total_v_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    max_dur = total_v_frames / v_fps if total_v_frames > 0 else 9999.0

    # Janela de varredura inteligente
    scan_start = max(0.0, start_sec - 1.2)
    scan_end = min(max_dur, max(end_sec + 0.6, start_sec + 1.8))

    candidate_times = []
    t = scan_start
    while t <= scan_end:
        candidate_times.append(round(t, 2))
        t += 0.25

    for pt in [target_t, start_sec, start_sec + 0.35]:
        pt_r = round(pt, 2)
        if 0 <= pt_r <= max_dur and pt_r not in candidate_times:
            candidate_times.append(pt_r)
    candidate_times.sort()

    from imgutils.segment import segment_rgba_with_isnetis
    try:
        from imgutils.detect import detect_faces
        has_face_detector = True
    except Exception:
        has_face_detector = False

    best_score = -999.0
    best_record = None

    print(f"\n================================================================================")
    print(f"[QUALITY GATE - ANIME FX] Avaliando candidatos para cena de Mangá")
    print(f"  • Alvo: {target_t:.2f}s | Janela de fala: {start_sec:.2f}s - {end_sec:.2f}s | Candidatos: {len(candidate_times)}")

    for ct in candidate_times:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(ct * v_fps))
        ret, frame_bgr = cap.read()
        if not ret or frame_bgr is None:
            continue

        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        frame_pil = Image.fromarray(frame_rgb)
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

        # 1. Nitidez (Laplacian Variance)
        lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        # 2. Luminância
        lum = float(np.mean(gray))

        # 3. Segmentação Neural
        try:
            _, c_rgba = segment_rgba_with_isnetis(frame_pil)
            c_np = np.array(c_rgba)
            c_alpha = c_np[:, :, 3]
            cov = float(np.sum(c_alpha > 35)) / float(frame_rgb.shape[0] * frame_rgb.shape[1])
        except Exception:
            c_alpha = np.zeros(gray.shape, dtype=np.uint8)
            cov = 0.0

        # 4. Detecção de Rosto
        has_face = False
        if has_face_detector and cov >= 0.10:
            try:
                faces = detect_faces(frame_pil)
                has_face = len(faces) > 0
            except Exception:
                has_face = False

        # 5. Score Ponderado de Qualidade (Prioridade Absoluta para Personagem em Destaque)
        sharp_score = min(50.0, lap_var / 4.0)
        if lap_var < 35.0:
            sharp_score -= 30.0

        # Personagem em cena é a prioridade máxima para o recorte mangá:
        if cov >= 0.08:
            cov_score = 70.0 + cov * 160.0  # Grande bônus para quem tem personagem recortável!
        elif cov >= 0.04:
            cov_score = 35.0 + cov * 100.0
        else:
            cov_score = -50.0  # Penaliza severamente telas vazias ou sem personagem

        if 40.0 <= lum <= 200.0:
            lum_score = 25.0
        elif lum < 24.0 or lum > 235.0:
            lum_score = -40.0
        else:
            lum_score = 5.0

        face_score = 45.0 if has_face else 0.0

        time_dist = abs(ct - target_t)
        time_bonus = max(0.0, 15.0 - (time_dist * 8.0))

        score = sharp_score + cov_score + lum_score + face_score + time_bonus

        record = {
            "time": ct,
            "score": score,
            "raw_pil": frame_pil,
            "raw_rgb": frame_rgb,
            "alpha": c_alpha,
            "coverage": cov,
            "laplacian_var": lap_var,
            "luminance": lum,
            "has_face": has_face
        }

        if score > best_score:
            best_score = score
            best_record = record

    cap.release()

    if best_record is None:
        print("[QUALITY GATE] Nenhum frame pôde ser extraído.")
        print(f"================================================================================\n")
        return {"status": "FALHA", "score": 0.0, "time": target_t}

    best_cov = best_record["coverage"]
    best_lap = best_record["laplacian_var"]

    if (best_cov >= 0.06 or best_record["has_face"]) and best_lap >= 30.0:
        status = "APROVADO_RECORTE_PERSONAGEM"
        motivo = f"Personagem em destaque ({best_cov*100:.1f}% área, nitidez {best_lap:.1f}, rosto={best_record['has_face']})"
    else:
        status = "APROVADO_PAINEL_CENA"
        motivo = f"Plano amplo/ação selecionado com máxima nitidez ({best_lap:.1f})"

    print(f"  • Take Selecionado: t={best_record['time']:.2f}s | Score: {best_score:.1f}/100")
    print(f"  • Nitidez: {best_lap:.1f} | Cobertura: {best_cov*100:.1f}% | Rosto: {best_record['has_face']} | Lum: {best_record['luminance']:.0f}")
    print(f"[QUALITY GATE] Status: [{status}] -> {motivo}")
    print(f"================================================================================\n")

    best_record["status"] = status
    return best_record


def safe_lineart_anime(pil_img: Image.Image) -> Image.Image:
    """Extrai lineart de anime com fallback robusto contra falhas de modelo."""
    try:
        from imgutils.edge import edge_image_with_lineart_anime
        return edge_image_with_lineart_anime(pil_img)
    except Exception:
        gray = pil_img.convert("L")
        return gray.filter(ImageFilter.FIND_EDGES)


def detect_manga_feeling(text: str) -> str:
    """
    Detecta automaticamente a emoção e contexto dramático da fala para o clímax mangá:
    - 'fire': raiva, poder, explosão, ataque, grito de batalha, exclamação ('!'), intensidade.
    - 'typewriter': mistério, revelação, suspense, curiosidade, pergunta ('?'), sussurro, frieza.
    - 'slam': choque brutal, corte, espanto, katana slash, perigo iminente.
    - 'comedy': ironia, deboche, confusão cômica, surpresa engraçada.
    """
    t_clean = text.upper()
    fire_keywords = [
        "MOSTRA", "LOGO", "VAI", "AGORA", "MORRA", "DESTRUA", "PODER", "FORÇA",
        "BANKAI", "HAKI", "RASENGAN", "KAMEHAMEHA", "FOGO", "QUEIME", "EXPLODA",
        "CLÍMAX", "DESPERTOU", "ATAQUE", "LUTAR", "VOU TE", "CALA", "BOCA", "MATA"
    ]
    typewriter_keywords = [
        "COMO", "POR QUE", "QUEM", "ONDE", "SERÁ", "O QUE", "O QUÊ", "ACREDITO",
        "SEGREDO", "VERDADE", "PLANO", "ENTENDO", "SABIA", "OLHA", "VEJA", "ESCUTE",
        "REVELA", "DESCUBRA", "ISSO É", "TALVEZ", "NÃO PODE", "IMPOSSÍVEL", "?"
    ]
    comedy_keywords = [
        "BUGOU", "SOCORRO", "EITA", "DROGA", "MERDA", "OPA", "QUE ISSO", "DOIDO",
        "MALUCO", "ENGRAÇADO", "PIADA", "IDIOTA", "BURRO", "FUDEU"
    ]

    if any(k in t_clean for k in fire_keywords) or "!" in t_clean:
        return "fire"
    elif any(k in t_clean for k in typewriter_keywords) or "?" in t_clean:
        return "typewriter"
    elif any(k in t_clean for k in comedy_keywords):
        return "comedy"
    return "slam"


def get_feeling_font_path(feeling: str) -> str:
    """Retorna dinamicamente a fonte ideal do sistema ou assets baseada no feeling dramático."""
    if feeling in ("fire", "shonen_badge", "golden_god", "electric"):
        # Pincel Anime Japonês Furioso / Impacto Shonen
        return get_asset_font("Lovely-Scream-Queens.otf")
    elif feeling in ("typewriter", "manga_bubble"):
        # Fonte Nanquim Condensada / Técnica de Mangá
        for f in [r"C:\Windows\Fonts\impact.ttf", r"C:\Windows\Fonts\GOTHICB.TTF", r"C:\Windows\Fonts\ariblk.ttf"]:
            if os.path.exists(f): return f
        return get_asset_font("Lovely-Scream-Queens.otf")
    elif feeling in ("comedy", "offset_comic"):
        # Fonte Expressiva / Descontraída / Pop Art
        for f in [r"C:\Windows\Fonts\comicbd.ttf", r"C:\Windows\Fonts\RAVIE.TTF", r"C:\Windows\Fonts\JOKERMAN.TTF"]:
            if os.path.exists(f): return f
        return get_asset_font("Lovely-Scream-Queens.otf")
    else:  # slam / corte
        for f in [r"C:\Windows\Fonts\impact.ttf", r"C:\Windows\Fonts\ariblk.ttf"]:
            if os.path.exists(f): return f
        return get_asset_font("Lovely-Scream-Queens.otf")


def render_manga_animated_typography(
    canvas: Image.Image,
    t_rel: float,
    dur: float,
    line1: str,
    line2: str,
    layout_mode: str = "center",
    box_y1: int = 420,
    box_h: int = 1134,
    width: int = 1080,
    pos_layout: str = "auto",
    text_style: Optional[str] = None
) -> Image.Image:
    """
    Renderiza tipografia de mangá ultra-destacada, contextual e INTEGRADA DENTRO DO QUADRO MANGÁ:
    - Modos de Legenda:
        1. 'shonen_badge': Faixa chanfrada estilo mangá com borda dupla, kanji e sombra nítida.
        2. 'manga_bubble': Balão pontiagudo de fala de ação (Spiky Manga Action Bubble).
        3. 'fire': Fogo Shonen (labareda laranja + glow carmesim + ouro solar).
        4. 'electric': Raio & Energia Espiritual / Reiatsu / Chakra (faíscas e arcos pulsantes).
        5. 'golden_god': Ouro Supremo / Divindade (aura dourada reluzente + brilhos especulares).
        6. 'offset_comic': Pop Art Comic Manga (sombra dura deslocada a 45º em ciano/magenta).
        7. 'slam': Slam com corte de lâmina de katana.
        8. 'typewriter': Digitação nanquim letra por letra com cursor neon.
        9. 'comedy': Bounce elástico com glow pop magenta.
    - Suporte dinâmico a pos_layout:
        - 'top': Topo interno do quadrinho (~475px).
        - 'bottom': Base com respiro (~1265px).
        - 'center': Centro dramático de impacto (~935px).
        - 'split': Linha 1 no Topo e Linha 2 na Base!
        - 'lateral_left' / 'lateral_right': Alinhamentos laterais dinâmicos.
    """
    def clean_manga_text(t: str) -> str:
        if not t:
            return ""
        cleaned = re.sub(r"[^\w\sÀ-úà-ú\-'!?]", "", t)
        return re.sub(r"\s+", " ", cleaned).strip().upper()

    disp_l1 = clean_manga_text(line1)
    disp_l2 = clean_manga_text(line2)
    active_lines = [l for l in [disp_l1, disp_l2] if l]

    if not active_lines:
        return canvas

    if canvas.mode != "RGBA":
        canvas = canvas.convert("RGBA")

    full_text = " ".join(active_lines)

    supported_styles = ("shonen_badge", "manga_bubble", "fire", "electric", "golden_god", "offset_comic", "slam", "typewriter", "comedy")
    if text_style and text_style in supported_styles:
        feeling = text_style
    else:
        feeling = detect_manga_feeling(full_text)

    font_path = get_feeling_font_path(feeling)
    center_x = width // 2

    # Posicionamento Vertical (Y) Seguro: 100% LIVRE da marca d'água superior (@ANIMAX_97 em y=460 a y=520)
    if pos_layout == "top":
        base_ty = 750  # Seguro, bem abaixo da watermark
    elif pos_layout == "center":
        base_ty = 980  # Ponto focal central de impacto
    elif pos_layout in ("lateral_left", "lateral_right"):
        base_ty = 1140 # Base lateral
    else:  # bottom, auto, split
        base_ty = 1140 # Base com respiro antes do CTA

    # CLAMP DE SEGURANÇA: NUNCA invade a watermark (mínimo y=700) e nunca desce no CTA (máximo y=1200)
    base_ty = max(700, min(1200, base_ty))

    # Animação de Entrada, Shake e Push-in de Câmera Contínuo (Zero Estático)
    p_rel = min(1.0, t_rel / 0.16)
    bounce = 1.0 + 0.35 * math.exp(-5.5 * p_rel) * math.cos(7.5 * p_rel) if t_rel < 0.16 else 1.0
    continuous_push = 1.0 + 0.07 * (t_rel / max(0.4, dur))
    shake_x = int(math.sin(t_rel * 40) * 2) if feeling in ("shonen_badge", "electric", "fire", "slam") else 0
    shake_y = int(math.cos(t_rel * 35) * 2) if feeling in ("shonen_badge", "electric", "fire", "slam") else 0

    # Tipografia Shonen Stacked: calcula tamanho de fonte e dimensões de cada linha
    max_len = max(len(l) for l in active_lines)
    base_sz = 68 if max_len > 28 else (78 if max_len > 20 else (92 if max_len > 12 else 108))
    sz = max(36, int(base_sz * bounce * continuous_push))

    try:
        f = ImageFont.truetype(font_path, size=sz)
    except Exception:
        f = ImageFont.load_default()

    # CLAMP UNIVERSAL RIGOROSO: Largura máxima de 840px
    max_w = 840
    max_tw = max(f.getbbox(l)[2] - f.getbbox(l)[0] for l in active_lines)
    if max_tw > max_w:
        sz = max(32, int(sz * (max_w / max_tw)))
        try:
            f = ImageFont.truetype(font_path, size=sz)
        except Exception:
            pass

    ascent, descent = f.getmetrics()
    line_h = ascent + descent
    gap = int(line_h * 0.28)
    total_h = len(active_lines) * line_h + max(0, len(active_lines) - 1) * gap

    start_y = base_ty - total_h // 2 + shake_y
    measured_lines = []
    curr_y = start_y
    for l in active_lines:
        bb = f.getbbox(l)
        tw = bb[2] - bb[0]
        if pos_layout == "lateral_left":
            line_tx = 50 + shake_x
        elif pos_layout == "lateral_right":
            line_tx = max(40, width - tw - 60) + shake_x
        else:
            line_tx = max(40, min(width - tw - 40, center_x - tw // 2)) + shake_x
        measured_lines.append({"text": l, "tx": line_tx, "ty": curr_y, "w": tw, "h": line_h})
        curr_y += line_h + gap

    outline_w = max(3, min(7, int(sz * 0.06)))

    def draw_lines_func(draw_obj, font_obj, dx=0, dy=0, fill_col=(255, 255, 255, 255)):
        for item in measured_lines:
            draw_obj.text((item["tx"] + dx, item["ty"] + dy), item["text"], font=font_obj, fill=fill_col)

    grp_x1 = min(m["tx"] for m in measured_lines)
    grp_x2 = max(m["tx"] + m["w"] for m in measured_lines)
    grp_y1 = measured_lines[0]["ty"]
    grp_y2 = measured_lines[-1]["ty"] + measured_lines[-1]["h"]
    grp_w = grp_x2 - grp_x1
    grp_h = grp_y2 - grp_y1
    bcx = (grp_x1 + grp_x2) // 2
    bcy = (grp_y1 + grp_y2) // 2

    def finish_typography_frame(target_canvas: Image.Image) -> Image.Image:
        """Aplica varredura de brilho especular (Metallic Sheen Sweep) contínua sobre as letras."""
        if dur > 0.4 and t_rel > 0.10 and feeling != "typewriter":
            sheen_t = min(1.0, max(0.0, (t_rel - 0.10) / max(0.3, dur * 0.75)))
            sheen_cx = int(grp_x1 - 80 + (grp_w + 160) * sheen_t)
            sheen_w = int(max(40, grp_w * 0.22))

            sheen_canvas = Image.new("RGBA", target_canvas.size, (0, 0, 0, 0))
            sh_draw = ImageDraw.Draw(sheen_canvas)
            sh_pts = [
                (sheen_cx - sheen_w // 2, grp_y1 - 35),
                (sheen_cx + sheen_w // 2, grp_y1 - 35),
                (sheen_cx + sheen_w // 2 - 45, grp_y2 + 35),
                (sheen_cx - sheen_w // 2 - 45, grp_y2 + 35)
            ]
            sh_draw.polygon(sh_pts, fill=(255, 255, 255, 130))
            sh_core_pts = [
                (sheen_cx - sheen_w // 5, grp_y1 - 35),
                (sheen_cx + sheen_w // 5, grp_y1 - 35),
                (sheen_cx + sheen_w // 5 - 45, grp_y2 + 35),
                (sheen_cx - sheen_w // 5 - 45, grp_y2 + 35)
            ]
            sh_draw.polygon(sh_core_pts, fill=(255, 255, 255, 220))
            sheen_blurred = sheen_canvas.filter(ImageFilter.GaussianBlur(radius=6))

            text_mask = Image.new("L", target_canvas.size, 0)
            draw_lines_func(ImageDraw.Draw(text_mask), f, 0, 0, fill_col=255)

            sheen_comp = Image.new("RGBA", target_canvas.size, (0, 0, 0, 0))
            sheen_comp.paste(sheen_blurred, (0, 0), text_mask)
            target_canvas = Image.alpha_composite(target_canvas, sheen_comp)
        return target_canvas

    # --------------------------------------------------------------------------
    # MODO: SHONEN BADGE (Faixa Chanfrada Estilo Mangá com Borda Dupla e Selo)
    # --------------------------------------------------------------------------
    if feeling == "shonen_badge":
        pad_x, pad_y = 28, 14
        bx1, by1 = grp_x1 - pad_x, grp_y1 - pad_y
        bx2, by2 = grp_x2 + pad_x, grp_y2 + pad_y
        pts = [(bx1 + 16, by1), (bx2, by1), (bx2 - 16, by2), (bx1, by2)]
        shadow_pts = [(x + 6, y + 8) for x, y in pts]

        badge_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        b_draw = ImageDraw.Draw(badge_layer)
        b_draw.polygon(shadow_pts, fill=(0, 0, 0, 200))
        b_draw.polygon(pts, fill=(10, 12, 18, 240))
        b_draw.line(pts + [pts[0]], fill=(230, 25, 45, 255), width=4)
        inner_pts = [(bx1 + 18, by1 + 4), (bx2 - 4, by1 + 4), (bx2 - 18, by2 - 4), (bx1 + 4, by2 - 4)]
        b_draw.line(inner_pts + [inner_pts[0]], fill=(255, 255, 255, 220), width=2)

        glow_badge = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ImageDraw.Draw(glow_badge).polygon(pts, fill=(255, 30, 60, 140))
        glow_badge = glow_badge.filter(ImageFilter.GaussianBlur(radius=18))

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        draw_lines_func(t_draw, f, 5, 6, fill_col=(0, 0, 0, 240))
        for ox in range(-outline_w, outline_w + 1):
            for oy in range(-outline_w, outline_w + 1):
                if ox * ox + oy * oy <= outline_w * outline_w:
                    draw_lines_func(t_draw, f, ox, oy, fill_col=(0, 0, 0, 255))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(255, 255, 255, 255))

        canvas = Image.alpha_composite(canvas, glow_badge)
        canvas = Image.alpha_composite(canvas, badge_layer)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: MANGA BUBBLE (Balão de Fala de Ação Explosiva / Spiky Dialogue Bubble)
    # --------------------------------------------------------------------------
    elif feeling == "manga_bubble":
        rx = (grp_w // 2) + 42
        ry = (grp_h // 2) + 26
        num_spikes = 16
        spike_pts = []
        for s_idx in range(num_spikes):
            ang = s_idx * (2 * math.pi / num_spikes)
            is_peak = (s_idx % 2 == 0)
            rad_mult = 1.25 if is_peak else 0.88
            px = bcx + int(rx * rad_mult * math.cos(ang))
            py = bcy + int(ry * rad_mult * math.sin(ang))
            spike_pts.append((px, py))

        bubble_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        b_draw = ImageDraw.Draw(bubble_layer)
        b_shadow_pts = [(x + 6, y + 8) for x, y in spike_pts]
        b_draw.polygon(b_shadow_pts, fill=(0, 0, 0, 210))
        b_draw.polygon(spike_pts, fill=(255, 255, 255, 250))
        b_draw.line(spike_pts + [spike_pts[0]], fill=(10, 10, 10, 255), width=7)

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        for ox in range(-2, 3):
            for oy in range(-2, 3):
                if ox * ox + oy * oy <= 4:
                    draw_lines_func(t_draw, f, ox, oy, fill_col=(255, 255, 255, 255))
        draw_lines_func(t_draw, f, 3, 4, fill_col=(0, 0, 0, 230))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(15, 15, 20, 255))

        canvas = Image.alpha_composite(canvas, bubble_layer)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: ELECTRIC (Raio & Energia Espiritual / Reiatsu / Chakra)
    # --------------------------------------------------------------------------
    elif feeling == "electric":
        glow_cyan_r = int(24 + 6 * math.sin(t_rel * 16))
        glow_cyan = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(glow_cyan), f, 0, 0, fill_col=(0, 240, 255, 240))
        glow_cyan = glow_cyan.filter(ImageFilter.GaussianBlur(radius=glow_cyan_r))

        glow_blue = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(glow_blue), f, 0, 0, fill_col=(0, 80, 255, 220))
        glow_blue = glow_blue.filter(ImageFilter.GaussianBlur(radius=10))

        spark_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        s_draw = ImageDraw.Draw(spark_layer)
        random.seed(int(t_rel * 25))
        for _ in range(5):
            sp_x = grp_x1 + random.randint(0, max(1, grp_w))
            sp_y = grp_y1 + random.randint(0, max(1, grp_h))
            dx1, dy1 = random.randint(-25, 25), random.randint(-20, 20)
            dx2, dy2 = dx1 + random.randint(-20, 20), dy1 + random.randint(-15, 15)
            s_draw.line([(sp_x, sp_y), (sp_x + dx1, sp_y + dy1), (sp_x + dx2, sp_y + dy2)], fill=(220, 255, 255, 230), width=3)
            s_draw.line([(sp_x, sp_y), (sp_x + dx1, sp_y + dy1), (sp_x + dx2, sp_y + dy2)], fill=(0, 230, 255, 160), width=6)
        spark_layer = spark_layer.filter(ImageFilter.GaussianBlur(radius=1))

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        draw_lines_func(t_draw, f, 5, 6, fill_col=(0, 0, 0, 240))
        for ox in range(-outline_w, outline_w + 1):
            for oy in range(-outline_w, outline_w + 1):
                if ox * ox + oy * oy <= outline_w * outline_w:
                    draw_lines_func(t_draw, f, ox, oy, fill_col=(0, 0, 0, 255))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(245, 255, 255, 255))

        canvas = Image.alpha_composite(canvas, glow_cyan)
        canvas = Image.alpha_composite(canvas, glow_blue)
        canvas = Image.alpha_composite(canvas, spark_layer)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: GOLDEN GOD (Ouro Supremo / Divindade / Realeza com Aura Reluzente)
    # --------------------------------------------------------------------------
    elif feeling == "golden_god":
        glow_gold = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(glow_gold), f, 0, -6, fill_col=(255, 170, 0, 240))
        glow_gold = glow_gold.filter(ImageFilter.GaussianBlur(radius=26))

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        draw_lines_func(t_draw, f, 6, 7, fill_col=(0, 0, 0, 245))
        for ox in range(-outline_w, outline_w + 1):
            for oy in range(-outline_w, outline_w + 1):
                if ox * ox + oy * oy <= outline_w * outline_w:
                    draw_lines_func(t_draw, f, ox, oy, fill_col=(0, 0, 0, 255))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(255, 215, 30, 255))
        draw_lines_func(t_draw, f, 0, -2, fill_col=(255, 255, 180, 210))

        sparkle_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        sp_draw = ImageDraw.Draw(sparkle_layer)
        sp_pts = [(grp_x1 + 10, grp_y1 + 10), (grp_x2 - 10, grp_y1 + 8), (bcx, grp_y2 - 6)]
        rot_ang = t_rel * 4.5
        for sx, sy in sp_pts:
            dx1, dy1 = int(12 * math.cos(rot_ang)), int(12 * math.sin(rot_ang))
            dx2, dy2 = int(12 * math.cos(rot_ang + math.pi / 2)), int(12 * math.sin(rot_ang + math.pi / 2))
            sp_draw.line([(sx - dx1, sy - dy1), (sx + dx1, sy + dy1)], fill=(255, 255, 255, 240), width=3)
            sp_draw.line([(sx - dx2, sy - dy2), (sx + dx2, sy + dy2)], fill=(255, 255, 255, 240), width=3)
            sp_draw.line([(sx - dx1//2, sy - dy1//2), (sx + dx1//2, sy + dy1//2)], fill=(255, 230, 100, 200), width=2)
            sp_draw.line([(sx - dx2//2, sy - dy2//2), (sx + dx2//2, sy + dy2//2)], fill=(255, 230, 100, 200), width=2)
        sparkle_layer = sparkle_layer.filter(ImageFilter.GaussianBlur(radius=1))

        canvas = Image.alpha_composite(canvas, glow_gold)
        canvas = Image.alpha_composite(canvas, txt_layer)
        canvas = Image.alpha_composite(canvas, sparkle_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: OFFSET COMIC (Pop Art Comic Mangá / Sombra Deslocada 3D)
    # --------------------------------------------------------------------------
    elif feeling == "offset_comic":
        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        for ox in range(-3, 4):
            for oy in range(-3, 4):
                draw_lines_func(t_draw, f, 7 + ox, 7 + oy, fill_col=(0, 210, 255, 255))
        for ox in range(-outline_w, outline_w + 1):
            for oy in range(-outline_w, outline_w + 1):
                if ox * ox + oy * oy <= outline_w * outline_w:
                    draw_lines_func(t_draw, f, ox, oy, fill_col=(0, 0, 0, 255))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(255, 245, 30, 255))

        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: FOGO SHONEN (Labaredas Subindo, Aura de Calor e Letras Ardentes)
    # --------------------------------------------------------------------------
    elif feeling == "fire":
        fire_glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(fire_glow), f, 0, -8, fill_col=(255, 25, 0, 240))
        fire_glow = fire_glow.filter(ImageFilter.GaussianBlur(radius=28))

        fire_flame = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        fl_alpha = int(210 + 45 * math.sin(t_rel * 25))
        fl_lift = int(-6 + 3 * math.sin(t_rel * 22))
        draw_lines_func(ImageDraw.Draw(fire_flame), f, 0, fl_lift, fill_col=(255, 140, 0, fl_alpha))
        fire_flame = fire_flame.filter(ImageFilter.GaussianBlur(radius=12))

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        draw_lines_func(t_draw, f, 6, 8, fill_col=(0, 0, 0, 245))
        for ox in range(-outline_w, outline_w + 1):
            for oy in range(-outline_w, outline_w + 1):
                if ox * ox + oy * oy <= outline_w * outline_w:
                    draw_lines_func(t_draw, f, ox, oy, fill_col=(0, 0, 0, 255))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(255, 235, 35, 255))

        canvas = Image.alpha_composite(canvas, fire_glow)
        canvas = Image.alpha_composite(canvas, fire_flame)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: DIGITAÇÃO NANQUIM (Typewriter Letra por Letra com Cursor Neon)
    # --------------------------------------------------------------------------
    elif feeling == "typewriter":
        type_dur = max(0.4, dur * 0.70)
        prog = min(1.0, t_rel / type_dur)

        full_joined = " ".join([m["text"] for m in measured_lines])
        num_chars = max(1, int(len(full_joined) * prog)) if t_rel < type_dur else len(full_joined)

        pad_x, pad_y = 22, 10
        box_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        b_draw = ImageDraw.Draw(box_layer)
        b_draw.rounded_rectangle(
            [grp_x1 - pad_x, grp_y1 - pad_y, grp_x2 + pad_x + 18, grp_y2 + pad_y],
            radius=14, fill=(10, 14, 22, 220), outline=(255, 255, 255, 230), width=3
        )

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)

        # Digita progressivamente cada linha
        chars_left = num_chars
        cursor_pos = (grp_x1, grp_y1)
        for item in measured_lines:
            ln_txt = item["text"]
            if chars_left <= 0:
                break
            cur_ln_slice = ln_txt[:chars_left]
            chars_left -= len(ln_txt) + 1
            bb_sl = f.getbbox(cur_ln_slice) if cur_ln_slice else (0, 0, 0, 0)
            sl_w = bb_sl[2] - bb_sl[0]
            cursor_pos = (item["tx"] + sl_w + 6, item["ty"])

            for ox in range(-7, 8):
                for oy in range(-7, 8):
                    if ox * ox + oy * oy <= 49:
                        t_draw.text((item["tx"] + ox, item["ty"] + oy), cur_ln_slice, font=f, fill=(0, 0, 0, 255))
            t_draw.text((item["tx"], item["ty"]), cur_ln_slice, font=f, fill=(255, 255, 255, 255))

        cursor_blink = int((t_rel * 6) % 2)
        if cursor_blink == 0 or t_rel < type_dur:
            cur_x, cur_y = cursor_pos
            b_draw.rectangle([cur_x, cur_y + 4, cur_x + 8, cur_y + sz - 4], fill=(0, 240, 255, 255))

        canvas = Image.alpha_composite(canvas, box_layer)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: COMÉDIA EXPRESSIVA (Bounce Elástico Amarelo/Roxo Vibrante)
    # --------------------------------------------------------------------------
    elif feeling == "comedy":
        glow_pop = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(glow_pop), f, 0, 0, fill_col=(255, 20, 140, 220))
        glow_pop = glow_pop.filter(ImageFilter.GaussianBlur(radius=18))

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        draw_lines_func(t_draw, f, 6, 7, fill_col=(0, 0, 0, 240))
        for ox in range(-outline_w, outline_w + 1):
            for oy in range(-outline_w, outline_w + 1):
                if ox * ox + oy * oy <= outline_w * outline_w:
                    draw_lines_func(t_draw, f, ox, oy, fill_col=(0, 0, 0, 255))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(255, 245, 60, 255))

        canvas = Image.alpha_composite(canvas, glow_pop)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: SLAM DE IMPACTO COM CORTE DE KATANA (Katana Slash & Crimson)
    # --------------------------------------------------------------------------
    else:
        glow_red = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(glow_red), f, 0, 0, fill_col=(255, 0, 50, 240))
        glow_red = glow_red.filter(ImageFilter.GaussianBlur(radius=22))

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        for d in range(1, max(2, outline_w)):
            draw_lines_func(t_draw, f, d, d, fill_col=(0, 0, 0, 220))
        for ox in range(-outline_w, outline_w + 1):
            for oy in range(-outline_w, outline_w + 1):
                if ox * ox + oy * oy <= outline_w * outline_w:
                    draw_lines_func(t_draw, f, ox, oy, fill_col=(0, 0, 0, 255))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(255, 45, 65, 255))

        canvas = Image.alpha_composite(canvas, glow_red)
        canvas = Image.alpha_composite(canvas, txt_layer)

        if 0.15 <= t_rel <= 0.38:
            slash_prog = (t_rel - 0.15) / 0.23
            slash_len = int((grp_w + 120) * slash_prog)
            slash_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            sl_draw = ImageDraw.Draw(slash_layer)
            sx1 = grp_x1 - 40
            sy1 = grp_y2 - 10
            sx2 = sx1 + slash_len
            sy2 = sy1 - int(slash_len * 0.28)
            sl_draw.line([sx1, sy1, sx2, sy2], fill=(255, 255, 255, 255), width=5)
            sl_draw.line([sx1, sy1, sx2, sy2], fill=(0, 230, 255, 180), width=12)
            slash_layer = slash_layer.filter(ImageFilter.GaussianBlur(radius=2))
            canvas = Image.alpha_composite(canvas, slash_layer)

        return finish_typography_frame(canvas)


def generate_sukuna_manga_segment_clip(
    video_path: str,
    start_sec: float,
    end_sec: float,
    output_clip_path: str,
    static_ui_img: Optional[Image.Image] = None,
    frame_t: Optional[float] = None,
    text_line1: Optional[str] = None,
    text_line2: Optional[str] = None,
    symbol: Optional[str] = None,
    pos_layout: str = "auto",
    text_style: Optional[str] = None
) -> Optional[str]:
    """
    Gera proceduralmente o clipe de 1080x1920 no formato Mangá P&B Lateral de Alta Ação:
      - Enquadramento lateral com conversão fidedigna de Mangá P&B (Nanquim + Retícula).
      - Borda sólida branca de sticker colecionável (14px) e sombra suave (ZERO aura amarela!).
      - Fundo do próprio anime desfocado cinematicamente (bokeh) com vinheta escura para contraste.
      - Impacto de entrada com Flash Branco de 3 frames (White Screen Flash).
      - Tipografia no topo em 2 linhas + símbolo 3D.
      - Push-in zoom cinematográfico constante (1.0x -> 1.07x).
    """
    try:
        W, H = 1080, 1920
        box_y1, box_y2 = 420, 1554
        box_h = box_y2 - box_y1
        fps = 30.0

        dur = max(0.5, end_sec - start_sec)
        phase_split = dur * 0.32
        total_frames = int(round(dur * fps))
        if frame_t is None:
            frame_t = start_sec + 0.35

        # 1. Quality Gate e Seleção do Melhor Take
        qg = find_best_manga_take_with_quality_gate(video_path, frame_t, start_sec, end_sec)

        if qg.get("status") == "APROVADO_PAINEL_CENA" or qg.get("raw_pil") is None:
            return generate_scene_manga_panel_segment_clip(
                video_path=video_path,
                start_sec=start_sec,
                end_sec=end_sec,
                output_clip_path=output_clip_path,
                static_ui_img=static_ui_img,
                frame_t=qg.get("time", frame_t),
                best_frame_pil=qg.get("raw_pil"),
                text_line1=text_line1,
                text_line2=text_line2,
                symbol=symbol,
                pos_layout=pos_layout,
                text_style=text_style
            )

        raw_pil = qg["raw_pil"]
        alpha = qg["alpha"]

        # 2. Conversão Fidedigna para Mangá P&B (Alto contraste de nanquim e tons de cinza)
        gray_char = ImageOps.autocontrast(raw_pil.convert("L"), cutoff=2)
        gray_np = np.array(gray_char)
        lineart_pil = safe_lineart_anime(raw_pil)
        lineart_np = np.array(lineart_pil.convert("L"))

        ink = lineart_np.astype(float) / 255.0
        ink_boosted = np.clip((ink - 0.15) / 0.85, 0.0, 1.0)
        manga_char_np = np.clip(gray_np.astype(float) * (ink_boosted ** 0.90), 0, 255).astype(np.uint8)

        char_rgba = Image.fromarray(np.dstack([manga_char_np, manga_char_np, manga_char_np, alpha]))
        bbox = char_rgba.getbbox()
        char_cropped = char_rgba.crop(bbox) if bbox else char_rgba

        # 3. Construção do Adesivo Colecionável Mangá P&B (Borda Branca Sólida 14px + Sombra Suave, ZERO aura amarela)
        cw, ch = char_cropped.size
        pad = 60
        base = Image.new("RGBA", (cw + pad * 2, ch + pad * 2), (0, 0, 0, 0))
        base.paste(char_cropped, (pad, pad), char_cropped)
        alpha_mask = np.array(base)[:, :, 3]

        # Borda Branca Sólida 14px
        kernel_white = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (27, 27))
        dil_white = cv2.dilate(alpha_mask, kernel_white, iterations=1)
        white_np = np.zeros((base.size[1], base.size[0], 4), dtype=np.uint8)
        white_np[:, :, 0:3] = 255
        white_np[:, :, 3] = np.where(dil_white > 15, 255, 0)
        white_pil = Image.fromarray(white_np).filter(ImageFilter.GaussianBlur(radius=1.5))

        # Sombra Drop Shadow Escura Profunda
        kernel_sh = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (39, 39))
        dil_sh = cv2.dilate(alpha_mask, kernel_sh, iterations=1)
        sh_np = np.zeros((base.size[1], base.size[0], 4), dtype=np.uint8)
        sh_np[:, :, 3] = np.where(dil_sh > 10, 180, 0)
        sh_pil = Image.fromarray(sh_np).filter(ImageFilter.GaussianBlur(radius=14))

        sticker_comp = Image.new("RGBA", base.size, (0, 0, 0, 0))
        sticker_comp.paste(sh_pil, (0, 0), sh_pil)
        sticker_comp.paste(white_pil, (0, 0), white_pil)
        sticker_comp.paste(base, (0, 0), base)

        # 4. Fundo Bokeh Full-Bleed 1080x1920 (Preserva fundo do vídeo sem faixas pretas)
        bg_full_blur = create_full_bleed_blurred_background(raw_pil, width=W, height=H, blur_radius=30)
        vignette = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        v_draw = ImageDraw.Draw(vignette)
        cx, cy = W // 2, (box_y1 + box_y2) // 2
        for r in range(box_h // 2 - 50, int(math.hypot(cx, cy)), 12):
            alpha_v = int(min(150, (r - (box_h // 2 - 50)) * 0.45))
            v_draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(5, 10, 15, alpha_v), width=15)
        bg_base = Image.alpha_composite(bg_full_blur, vignette)

        # 5. Escala do Personagem para o Enquadramento Lateral
        base_h = 860
        base_w = int(sticker_comp.width * (base_h / max(1, sticker_comp.height)))
        char_base = sticker_comp.resize((base_w, base_h), Image.Resampling.LANCZOS)

        char_x = 40
        char_y = box_y2 - base_h

        # 6. Tipografia Dinâmica
        disp_line1 = (text_line1 or "").strip().upper()
        disp_line2 = (text_line2 or "").strip().upper()

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(output_clip_path, fourcc, fps, (W, H))

        for i in range(total_frames):
            t_rel = i / fps

            canvas = bg_base.copy()

            # Push-in zoom no Personagem (1.0x -> 1.07x)
            zoom_factor = 1.0 + 0.07 * (t_rel / dur)
            cur_w = int(base_w * zoom_factor)
            cur_h = int(base_h * zoom_factor)
            cur_char = char_base.resize((cur_w, cur_h), Image.Resampling.BILINEAR)

            cur_x = char_x - int((cur_w - base_w) * 0.4)
            cur_y = box_y2 - cur_h
            canvas.paste(cur_char, (cur_x, cur_y), cur_char)

            # Tipografia Animada Mangá de Elite (Pop-in setup + erupção punchline)
            eff_layout = pos_layout if pos_layout != "auto" else "lateral_right"
            canvas = render_manga_animated_typography(
                canvas, t_rel, dur, disp_line1, disp_line2,
                layout_mode=eff_layout, box_y1=box_y1, box_h=box_h, width=W,
                pos_layout=pos_layout, text_style=text_style
            )

            # Impacto de Entrada: Flash Branco nos primeiros 3 frames (0.10s)
            if t_rel < 0.10:
                flash_alpha = int(255 * (1.0 - t_rel / 0.10))
                flash_img = Image.new("RGBA", (W, H), (255, 255, 255, flash_alpha))
                canvas = Image.alpha_composite(canvas, flash_img)

            # Corte de Katana na entrada
            if t_rel < 0.24:
                prog = t_rel / 0.24
                slash_img = generate_katana_slash_frame(prog, width=W, height=box_h, slash_angle_deg=-16.0)
                slash_canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                slash_canvas.paste(slash_img, (0, box_y1), slash_img)
                canvas = Image.alpha_composite(canvas, slash_canvas)

            # Corte de Katana na transição de fase
            if phase_split <= t_rel <= phase_split + 0.24:
                prog2 = (t_rel - phase_split) / 0.24
                slash_img2 = generate_katana_slash_frame(prog2, width=W, height=box_h, slash_angle_deg=22.0)
                slash_canvas2 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                slash_canvas2.paste(slash_img2, (0, box_y1), slash_img2)
                canvas = Image.alpha_composite(canvas, slash_canvas2)

            if static_ui_img:
                canvas = Image.alpha_composite(canvas, static_ui_img)

            bgr = cv2.cvtColor(np.array(canvas.convert("RGB")), cv2.COLOR_RGB2BGR)
            writer.write(bgr)

        writer.release()
        return output_clip_path

    except Exception as e:
        print(f"[SukunaMangaSegment] Erro: {e}")
        return None


def generate_scene_manga_panel_segment_clip(
    video_path: str,
    start_sec: float,
    end_sec: float,
    output_clip_path: str,
    static_ui_img: Optional[Image.Image] = None,
    frame_t: Optional[float] = None,
    best_frame_pil: Optional[Image.Image] = None,
    text_line1: Optional[str] = None,
    text_line2: Optional[str] = None,
    symbol: Optional[str] = "!",
    pos_layout: str = "auto",
    text_style: Optional[str] = None
) -> Optional[str]:
    """
    Modalidade Mangá de Cena / Painel de Quadrinho (Scene Manga Panel):
    Acionado quando a cena é um plano aberto, silhueta ou ação sem personagem isolado recortável.
    Aproveita o máximo do próprio vídeo: transforma o quadro da cena em um QUADRINHO DE MANGÁ P&B
    autêntico (Nanquim + Retícula de mangá + Moldura clássica japonesa + Zoom heroico).
    NUNCA gera um círculo vazio!
    """
    try:
        W, H = 1080, 1920
        box_y1, box_y2 = 420, 1554
        box_h = box_y2 - box_y1
        fps = 30.0

        dur = max(0.5, end_sec - start_sec)
        total_frames = int(round(dur * fps))
        if frame_t is None:
            frame_t = start_sec + 0.35

        if best_frame_pil is None:
            cap = cv2.VideoCapture(video_path)
            v_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0

            # Procura o frame mais nítido e expressivo da cena
            scan_t = max(0.0, start_sec - 1.5)
            best_score = -1.0

            while scan_t <= end_sec + 0.8:
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(scan_t * v_fps))
                ret, frame_bgr = cap.read()
                if ret and frame_bgr is not None:
                    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
                    score = cv2.Laplacian(gray, cv2.CV_64F).var()
                    if score > best_score:
                        best_score = score
                        best_frame_pil = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
                scan_t += 0.30
            cap.release()

        if best_frame_pil is None:
            return None

        # 1. Conversão em Arte Mangá P&B de Alto Contraste
        gray_scene = ImageOps.autocontrast(best_frame_pil.convert("L"), cutoff=2)
        lineart_scene = safe_lineart_anime(best_frame_pil).convert("L")
        ink = np.array(lineart_scene).astype(float) / 255.0
        ink_b = np.clip((ink - 0.15) / 0.85, 0.0, 1.0)
        manga_scene_np = np.clip(np.array(gray_scene).astype(float) * (ink_b ** 0.88), 0, 255).astype(np.uint8)
        manga_scene_pil = Image.fromarray(manga_scene_np).convert("RGB")

        # 2. Painel Centralizado com Proporção Preservada (ImageOps.fit sem esticar!) e Moldura Japonesa (980x860)
        panel_w, panel_h = 980, 860
        panel_crop = ImageOps.fit(manga_scene_pil, (panel_w, panel_h), method=Image.Resampling.LANCZOS).convert("RGBA")

        # Moldura de Mangá Autêntica: Borda externa branca 4px + borda interna nanquim 10px
        p_draw = ImageDraw.Draw(panel_crop)
        p_draw.rectangle([0, 0, panel_w, panel_h], outline=(255, 255, 255, 255), width=4)
        p_draw.rectangle([4, 4, panel_w - 4, panel_h - 4], outline=(10, 10, 10, 255), width=10)

        # 3. Fundo Dark Bokeh Cinematográfico Full-Bleed 1080x1920 (Preserva fundo do vídeo sem faixas pretas)
        bg_full_blur = create_full_bleed_blurred_background(best_frame_pil, width=W, height=H, blur_radius=30)
        vignette = Image.new("RGBA", (W, H), (8, 10, 16, 160))
        v_draw = ImageDraw.Draw(vignette)
        cx, cy = W // 2, (box_y1 + box_y2) // 2
        for r in range(box_h // 2 - 50, int(math.hypot(cx, cy)), 12):
            alpha_v = int(min(220, (r - (box_h // 2 - 50)) * 0.55))
            v_draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(0, 0, 0, alpha_v), width=15)
        bg_comp = Image.alpha_composite(bg_full_blur, vignette)

        # Sombra Drop Shadow Tridimensional para o Quadro de Mangá
        pad_sh = 40
        shadow_base = Image.new("RGBA", (panel_w + pad_sh * 2, panel_h + pad_sh * 2), (0, 0, 0, 0))
        ImageDraw.Draw(shadow_base).rectangle([pad_sh, pad_sh, pad_sh + panel_w, pad_sh + panel_h], fill=(0, 0, 0, 195))
        shadow_pil = shadow_base.filter(ImageFilter.GaussianBlur(radius=18))

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(output_clip_path, fourcc, fps, (W, H))

        panel_base_x = (W - panel_w) // 2
        panel_base_y = box_y1 + (box_h - panel_h) // 2

        for i in range(total_frames):
            t_rel = i / fps

            canvas = bg_comp.copy()

            # Push-in zoom no Painel de Mangá (1.0x -> 1.08x)
            p_zoom = 1.0 + 0.08 * (t_rel / dur)
            cur_pw = int(panel_w * p_zoom)
            cur_ph = int(panel_h * p_zoom)

            # Sombra dinâmica
            cur_shw = int((panel_w + pad_sh * 2) * p_zoom)
            cur_shh = int((panel_h + pad_sh * 2) * p_zoom)
            cur_sh = shadow_pil.resize((cur_shw, cur_shh), Image.Resampling.BILINEAR)
            cur_shx = (panel_base_x - int(pad_sh * p_zoom)) - (cur_pw - panel_w) // 2
            cur_shy = (panel_base_y - int(pad_sh * p_zoom)) - (cur_ph - panel_h) // 2 + 8
            canvas.paste(cur_sh, (cur_shx, cur_shy), cur_sh)

            cur_p = panel_crop.resize((cur_pw, cur_ph), Image.Resampling.BILINEAR)
            cur_px = panel_base_x - (cur_pw - panel_w) // 2
            cur_py = panel_base_y - (cur_ph - panel_h) // 2
            canvas.paste(cur_p, (cur_px, cur_py), cur_p)

            # Impacto de Entrada: Flash Branco nos primeiros 3 frames (0.10s)
            if t_rel < 0.10:
                flash_alpha = int(255 * (1.0 - t_rel / 0.10))
                flash_img = Image.new("RGBA", (W, H), (255, 255, 255, flash_alpha))
                canvas = Image.alpha_composite(canvas, flash_img)

            # Corte de Katana com brilho ciano/branco
            if 0.10 <= t_rel < 0.32:
                prog = (t_rel - 0.10) / 0.22
                slash_img = generate_katana_slash_frame(prog, width=W, height=box_h, slash_angle_deg=-20.0)
                slash_canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                slash_canvas.paste(slash_img, (0, box_y1), slash_img)
                canvas = Image.alpha_composite(canvas, slash_canvas)

            # Tipografia Animada Mangá de Elite (Pop-in setup + erupção punchline)
            canvas = render_manga_animated_typography(
                canvas, t_rel, dur, text_line1 or "", text_line2 or "",
                layout_mode="center", box_y1=box_y1, box_h=box_h, width=W,
                pos_layout=pos_layout, text_style=text_style
            )

            if static_ui_img:
                canvas = Image.alpha_composite(canvas, static_ui_img)

            bgr = cv2.cvtColor(np.array(canvas.convert("RGB")), cv2.COLOR_RGB2BGR)
            writer.write(bgr)

        writer.release()
        return output_clip_path

    except Exception as e:
        print(f"[SceneMangaPanelSegment] Erro: {e}")
        return None


def generate_luffy_manga_cutout_segment_clip(
    video_path: str,
    start_sec: float,
    end_sec: float,
    output_clip_path: str,
    static_ui_img: Optional[Image.Image] = None,
    frame_t: Optional[float] = None,
    text_line1: Optional[str] = None,
    text_line2: Optional[str] = None,
    symbol: Optional[str] = None,
    pos_layout: str = "auto",
    text_style: Optional[str] = None
) -> Optional[str]:
    """
    Modalidade Estilo One Piece / Luffy Bugou Hancock (Manga Cutout Climax):
      - Personagem com recorte neural ISNet e conversão clássica para Mangá P&B (Nanquim + Retícula).
      - Borda sólida branca estilo sticker colecionável (14px) com sombra suave.
      - Fundo cinematográfico Dark Bokeh do próprio anime com vinheta escura circular profunda (ZERO linhas vermelhas).
      - Impacto de entrada com Flash Branco de 3 frames (White Screen Flash de impacto de anime).
      - Tipografia de alta legibilidade em 2 linhas com posicionamento dinâmico variado.
    """
    try:
        W, H = 1080, 1920
        box_y1, box_y2 = 420, 1554
        box_h = box_y2 - box_y1
        fps = 30.0

        dur = max(0.5, end_sec - start_sec)
        total_frames = int(round(dur * fps))
        if frame_t is None:
            frame_t = start_sec + 0.35

        # 1. Quality Gate e Seleção do Melhor Take
        qg = find_best_manga_take_with_quality_gate(video_path, frame_t, start_sec, end_sec)

        if qg.get("status") == "APROVADO_PAINEL_CENA" or qg.get("raw_pil") is None:
            return generate_scene_manga_panel_segment_clip(
                video_path=video_path,
                start_sec=start_sec,
                end_sec=end_sec,
                output_clip_path=output_clip_path,
                static_ui_img=static_ui_img,
                frame_t=qg.get("time", frame_t),
                best_frame_pil=qg.get("raw_pil"),
                text_line1=text_line1,
                text_line2=text_line2,
                symbol=symbol,
                pos_layout=pos_layout,
                text_style=text_style
            )

        best_raw_pil = qg["raw_pil"]
        best_alpha = qg["alpha"]

        # 1. Conversão Fidedigna para Mangá P&B (Alto contraste de nanquim e tons de cinza)
        gray_char = ImageOps.autocontrast(best_raw_pil.convert("L"), cutoff=2)
        gray_np = np.array(gray_char)

        lineart_pil = safe_lineart_anime(best_raw_pil)
        lineart_np = np.array(lineart_pil.convert("L"))
        ink = lineart_np.astype(float) / 255.0
        ink_boosted = np.clip((ink - 0.15) / 0.85, 0.0, 1.0)
        manga_char_np = np.clip(gray_np.astype(float) * (ink_boosted ** 0.9), 0, 255).astype(np.uint8)

        char_rgba = Image.fromarray(np.dstack([manga_char_np, manga_char_np, manga_char_np, best_alpha]))
        bbox = char_rgba.getbbox()
        char_cropped = char_rgba.crop(bbox) if bbox else char_rgba

        # 2. Borda de Adesivo Branca (14px) + Sombra Projetada Suave (Estilo Luffy Bugou)
        cw, ch = char_cropped.size
        pad = 60
        base = Image.new("RGBA", (cw + pad * 2, ch + pad * 2), (0, 0, 0, 0))
        base.paste(char_cropped, (pad, pad), char_cropped)
        alpha_mask = np.array(base)[:, :, 3]

        # Borda Branca Sólida 14px
        kernel_white = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (27, 27))
        dil_white = cv2.dilate(alpha_mask, kernel_white, iterations=1)
        white_np = np.zeros((base.size[1], base.size[0], 4), dtype=np.uint8)
        white_np[:, :, 0:3] = 255
        white_np[:, :, 3] = np.where(dil_white > 15, 255, 0)
        white_pil = Image.fromarray(white_np).filter(ImageFilter.GaussianBlur(radius=1.5))

        # Sombra Drop Shadow Escura Profunda
        kernel_sh = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (39, 39))
        dil_sh = cv2.dilate(alpha_mask, kernel_sh, iterations=1)
        sh_np = np.zeros((base.size[1], base.size[0], 4), dtype=np.uint8)
        sh_np[:, :, 3] = np.where(dil_sh > 10, 180, 0)
        sh_pil = Image.fromarray(sh_np).filter(ImageFilter.GaussianBlur(radius=14))

        sticker_comp = Image.new("RGBA", base.size, (0, 0, 0, 0))
        sticker_comp.paste(sh_pil, (0, 0), sh_pil)
        sticker_comp.paste(white_pil, (0, 0), white_pil)
        sticker_comp.paste(base, (0, 0), base)

        # 3. Fundo Dark Bokeh Cinematográfico Full-Bleed 1080x1920 (Preserva fundo do vídeo sem faixas pretas)
        bg_full_blur = create_full_bleed_blurred_background(best_raw_pil, width=W, height=H, blur_radius=30)
        vignette = Image.new("RGBA", (W, H), (8, 10, 16, 145))
        v_draw = ImageDraw.Draw(vignette)
        cx, cy = W // 2, (box_y1 + box_y2) // 2
        for r in range(box_h // 2 - 50, int(math.hypot(cx, cy)), 12):
            alpha_v = int(min(220, (r - (box_h // 2 - 50)) * 0.55))
            v_draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(0, 0, 0, alpha_v), width=15)
        bg_base = Image.alpha_composite(bg_full_blur, vignette)

        # 4. Enquadramento Centralizado Heroico
        base_h = 920
        base_w = int(sticker_comp.width * (base_h / max(1, sticker_comp.height)))
        char_base = sticker_comp.resize((base_w, base_h), Image.Resampling.LANCZOS)
        char_center_x = (W - base_w) // 2
        char_y = box_y2 - base_h

        # 5. Tipografia de Impacto Centralizada
        disp_line1 = (text_line1 or "").strip().upper()
        disp_line2 = (text_line2 or "").strip().upper()

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(output_clip_path, fourcc, fps, (W, H))

        for i in range(total_frames):
            t_rel = i / fps

            canvas = bg_base.copy()

            # Push-in zoom no Personagem (1.0x -> 1.08x)
            zoom_factor = 1.0 + 0.08 * (t_rel / dur)
            cur_w = int(base_w * zoom_factor)
            cur_h = int(base_h * zoom_factor)
            cur_char = char_base.resize((cur_w, cur_h), Image.Resampling.BILINEAR)
            cur_x = char_center_x - int((cur_w - base_w) * 0.5)
            cur_y = box_y2 - cur_h
            canvas.paste(cur_char, (cur_x, cur_y), cur_char)

            # Tipografia Animada Mangá de Elite (Pop-in setup + erupção punchline)
            canvas = render_manga_animated_typography(
                canvas, t_rel, dur, disp_line1, disp_line2,
                layout_mode="center", box_y1=box_y1, box_h=box_h, width=W,
                pos_layout=pos_layout, text_style=text_style
            )

            # Impacto de Entrada: Flash Branco nos primeiros 3 frames (0.10s)
            if t_rel < 0.10:
                flash_alpha = int(255 * (1.0 - t_rel / 0.10))
                flash_img = Image.new("RGBA", (W, H), (255, 255, 255, flash_alpha))
                canvas = Image.alpha_composite(canvas, flash_img)

            # Corte de Katana suave com brilho ciano/branco
            if 0.10 <= t_rel < 0.32:
                prog = (t_rel - 0.10) / 0.22
                slash_img = generate_katana_slash_frame(prog, width=W, height=box_h, slash_angle_deg=-20.0)
                slash_canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                slash_canvas.paste(slash_img, (0, box_y1), slash_img)
                canvas = Image.alpha_composite(canvas, slash_canvas)

            if static_ui_img:
                canvas = Image.alpha_composite(canvas, static_ui_img)

            bgr = cv2.cvtColor(np.array(canvas.convert("RGB")), cv2.COLOR_RGB2BGR)
            writer.write(bgr)

        writer.release()
        return output_clip_path

    except Exception as e:
        print(f"[LuffyMangaCutoutSegment] Erro: {e}")
        return None


def generate_radial_power_manga_segment_clip(*args, **kwargs) -> Optional[str]:
    """Alias para generate_luffy_manga_cutout_segment_clip garantindo zero regressão."""
    return generate_luffy_manga_cutout_segment_clip(*args, **kwargs)


def generate_manga_eyes_panel_segment_clip(
    video_path: str,
    start_sec: float,
    end_sec: float,
    output_clip_path: str,
    static_ui_img: Optional[Image.Image] = None,
    frame_t: Optional[float] = None,
    text_line1: Optional[str] = None,
    text_line2: Optional[str] = None,
    symbol: Optional[str] = "?",
    pos_layout: str = "auto",
    text_style: Optional[str] = None
) -> Optional[str]:
    """
    Modalidade Tensão / Mistério / Close de Olhos (Cinematic Manga Strip Panel):
      - Faixa horizontal estilo painel de mangá recortando o foco dos olhos/expressão do personagem.
      - Efeito de retícula halftone e alto contraste em nanquim.
      - Símbolo 3D '?' com neon cyan pulsante e tipografia de suspense.
    """
    try:
        W, H = 1080, 1920
        box_y1, box_y2 = 420, 1554
        box_h = box_y2 - box_y1
        fps = 30.0

        dur = max(0.5, end_sec - start_sec)
        total_frames = int(round(dur * fps))
        if frame_t is None:
            frame_t = start_sec + 0.35

        cap = cv2.VideoCapture(video_path)
        v_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0

        candidate_times = [
            frame_t, start_sec, start_sec - 0.4, start_sec - 1.0,
            start_sec + 0.35, max(start_sec, end_sec - 0.25)
        ]

        from imgutils.edge import edge_image_with_lineart_anime

        best_raw_pil = None
        for ct in candidate_times:
            if ct < 0:
                continue
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(ct * v_fps))
            ret, frame_bgr = cap.read()
            if ret and frame_bgr is not None:
                cand_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                best_raw_pil = Image.fromarray(cand_rgb)
                break
        cap.release()

        if best_raw_pil is None:
            return None

        # Fundo Bokeh Cinematográfico Full-Bleed 1080x1920 (Preserva fundo do vídeo sem faixas pretas)
        bg_full_blur = create_full_bleed_blurred_background(best_raw_pil, width=W, height=H, blur_radius=30)
        bg_base = Image.alpha_composite(
            bg_full_blur,
            Image.new("RGBA", (W, H), (0, 5, 12, 160))
        )

        # Painel Horizontal Estilo Tira de Mangá (Comic Panel)
        panel_h = 480
        panel_y1 = box_y1 + (box_h - panel_h) // 2
        panel_y2 = panel_y1 + panel_h

        # Crop focado no terço superior/médio do personagem (região dos olhos)
        orig_w, orig_h = best_raw_pil.size
        crop_top = int(orig_h * 0.15)
        crop_bot = int(orig_h * 0.70)
        face_crop = best_raw_pil.crop((0, crop_top, orig_w, crop_bot))
        face_resized = face_crop.resize((W, panel_h), Image.Resampling.LANCZOS)

        # Efeito Mangá P&B de Alto Contraste com Linhas de Nanquim
        lineart_face = safe_lineart_anime(face_resized).convert("L")
        gray_face = face_resized.convert("L")
        enhanced_gray = ImageOps.autocontrast(gray_face, cutoff=2)
        # Fusão nanquim
        ink_face = Image.composite(enhanced_gray, Image.new("L", face_resized.size, 0), lineart_face)
        panel_img = ink_face.convert("RGBA")

        # Moldura de Mangá: Borda Preta 10px + Borda Branca 3px
        p_draw = ImageDraw.Draw(panel_img)
        p_draw.rectangle([0, 0, W, panel_h], outline=(255, 255, 255, 255), width=4)
        p_draw.rectangle([4, 4, W - 4, panel_h - 4], outline=(0, 0, 0, 255), width=8)

        # Tipografia de Tensão / Mistério
        disp_line1 = (text_line1 or "").strip().upper()
        disp_line2 = (text_line2 or "").strip().upper()

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(output_clip_path, fourcc, fps, (W, H))

        for i in range(total_frames):
            t_rel = i / fps

            canvas = bg_base.copy()

            # Push-in zoom no painel de olhos
            p_zoom = 1.0 + 0.06 * (t_rel / dur)
            pw = int(W * p_zoom)
            ph = int(panel_h * p_zoom)
            cur_panel = panel_img.resize((pw, ph), Image.Resampling.BILINEAR)
            px = (W - pw) // 2
            py = panel_y1 - (ph - panel_h) // 2
            canvas.paste(cur_panel, (px, py))

            # Tipografia Animada Mangá de Elite (Pop-in setup + erupção punchline)
            canvas = render_manga_animated_typography(
                canvas, t_rel, dur, disp_line1, disp_line2,
                layout_mode="center", box_y1=box_y1, box_h=box_h, width=W,
                pos_layout=pos_layout, text_style=text_style
            )

            if static_ui_img:
                canvas = Image.alpha_composite(canvas, static_ui_img)

            bgr = cv2.cvtColor(np.array(canvas.convert("RGB")), cv2.COLOR_RGB2BGR)
            writer.write(bgr)

        writer.release()
        return output_clip_path

    except Exception as e:
        print(f"[MangaEyesPanel] Erro: {e}")
        return None


def generate_manga_event_clip(
    video_path: str,
    event_dict: Dict[str, Any],
    output_clip_path: str,
    static_ui_img: Optional[Image.Image] = None
) -> Optional[str]:
    """
    Despachante Inteligente e Diversificado de Efeitos de Mangá:
    Roteia para a modalidade visual correspondente à análise de clímax:
      - 'radial_power': Speedlines radiais carmesim + personagem central + dual katana slash
      - 'manga_eyes_panel': Faixa horizontal de quadrinho com close nos olhos + halftone + símbolo 3D
      - 'lateral_sticker_punch': Sticker lateral colecionável de Mangá P&B com nanquim, borda branca sólida 14px, sombra suave e bokeh
    """
    etype = event_dict.get("event_type", "lateral_sticker_punch")
    st = float(event_dict["start"])
    et = float(event_dict["end"])
    ft = float(event_dict.get("frame_t", st + 0.35))
    l1 = event_dict.get("line1")
    l2 = event_dict.get("line2")
    sym = event_dict.get("symbol", "!")

    pos_layout = event_dict.get("pos_layout", "auto")
    text_style = event_dict.get("text_style", None)

    res = None
    try:
        if etype == "manga_eyes_panel":
            res = generate_manga_eyes_panel_segment_clip(
                video_path=video_path,
                start_sec=st,
                end_sec=et,
                output_clip_path=output_clip_path,
                static_ui_img=static_ui_img,
                frame_t=ft,
                text_line1=l1,
                text_line2=l2,
                symbol=sym,
                pos_layout=pos_layout,
                text_style=text_style
            )
        elif etype in ("luffy_manga_cutout", "radial_power", "haki_power"):
            res = generate_luffy_manga_cutout_segment_clip(
                video_path=video_path,
                start_sec=st,
                end_sec=et,
                output_clip_path=output_clip_path,
                static_ui_img=static_ui_img,
                frame_t=ft,
                text_line1=l1,
                text_line2=l2,
                symbol=sym,
                pos_layout=pos_layout,
                text_style=text_style
            )
        elif etype == "lateral_sticker_punch":
            res = generate_sukuna_manga_segment_clip(
                video_path=video_path,
                start_sec=st,
                end_sec=et,
                output_clip_path=output_clip_path,
                static_ui_img=static_ui_img,
                frame_t=ft,
                text_line1=l1,
                text_line2=l2,
                symbol=sym,
                pos_layout=pos_layout,
                text_style=text_style
            )
        else:
            # Padrão Oficial: Quadro de Mangá Autêntico (Scene Manga Panel)
            res = generate_scene_manga_panel_segment_clip(
                video_path=video_path,
                start_sec=st,
                end_sec=et,
                output_clip_path=output_clip_path,
                static_ui_img=static_ui_img,
                frame_t=ft,
                text_line1=l1,
                text_line2=l2,
                symbol=sym,
                pos_layout=pos_layout,
                text_style=text_style
            )
    except Exception as e:
        print(f"[generate_manga_event_clip] Erro no gerador primário ({etype}): {e}")
        res = None

    # Fallback de Segurança Máxima: Se o gerador primário não gerou o arquivo, aciona scene_manga_panel
    if not res or not os.path.exists(res):
        print(f"[generate_manga_event_clip] Acionando fallback seguro para scene_manga_panel ({st:.1f}s-{et:.1f}s)...")
        try:
            res = generate_scene_manga_panel_segment_clip(
                video_path=video_path,
                start_sec=st,
                end_sec=et,
                output_clip_path=output_clip_path,
                static_ui_img=static_ui_img,
                frame_t=ft,
                text_line1=l1,
                text_line2=l2,
                symbol=sym,
                pos_layout=pos_layout,
                text_style=text_style
            )
        except Exception as fe:
            print(f"[generate_manga_event_clip] Erro no fallback de mangá: {fe}")
            res = None

    return res


if __name__ == "__main__":
    print("manga_fx_engine.py carregado com sucesso.")

