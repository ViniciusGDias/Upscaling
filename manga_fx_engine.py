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
import threading

_ORT_GPU_LOCK = threading.Lock()
_TORCH_CUDA_AVAILABLE = False
_CUDA_DEVICE = None
_GPU_DEVICE_NAME = "CPU"


def _setup_gpu_runtime() -> None:
    """Configura caminhos de DLLs CUDA/cuDNN do PyTorch para liberar GPU no ONNX Runtime (imgutils) e Torch CUDA (inclusive no .exe)."""
    global _TORCH_CUDA_AVAILABLE, _CUDA_DEVICE, _GPU_DEVICE_NAME
    try:
        try:
            import whisper_hub
            whisper_hub._ensure_cuda_dll_paths()
        except Exception:
            pass

        if getattr(sys, "frozen", False) and os.name == "nt":
            import glob
            local_app = os.environ.get("LOCALAPPDATA", "")
            if local_app:
                for py_dir in sorted(glob.glob(os.path.join(local_app, "Programs", "Python", "Python*")), reverse=True):
                    sp = os.path.join(py_dir, "Lib", "site-packages")
                    if os.path.isdir(sp) and sp not in sys.path:
                        sys.path.append(sp)

        import torch
        if os.name == "nt":
            torch_lib = os.path.join(os.path.dirname(torch.__file__), "lib")
            site_pkgs = os.path.dirname(os.path.dirname(torch.__file__))
            candidate_dirs = [torch_lib]
            nvidia_root = os.path.join(site_pkgs, "nvidia")
            if os.path.isdir(nvidia_root):
                for sub in os.listdir(nvidia_root):
                    bdir = os.path.join(nvidia_root, sub, "bin")
                    if os.path.isdir(bdir):
                        candidate_dirs.append(bdir)
            cur_path = os.environ.get("PATH", "")
            for d in candidate_dirs:
                if os.path.isdir(d):
                    if d not in cur_path:
                        cur_path = d + os.pathsep + cur_path
                    if hasattr(os, "add_dll_directory"):
                        try:
                            os.add_dll_directory(d)
                        except Exception:
                            pass
            os.environ["PATH"] = cur_path

        if torch.cuda.is_available():
            _TORCH_CUDA_AVAILABLE = True
            _CUDA_DEVICE = torch.device("cuda")
            _GPU_DEVICE_NAME = torch.cuda.get_device_name(0)
    except Exception:
        _TORCH_CUDA_AVAILABLE = False
        _CUDA_DEVICE = None


_setup_gpu_runtime()


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
    Usa downscale-blur-upscale (16x mais rápido e visualmente idêntico).
    """
    small_w = max(135, width // 4)
    small_h = max(240, height // 4)
    bg_small = ImageOps.fit(source_frame, (small_w, small_h), method=Image.Resampling.BILINEAR)
    bg_blur_small = bg_small.filter(ImageFilter.GaussianBlur(radius=max(2, blur_radius // 4)))
    bg_blur = bg_blur_small.resize((width, height), Image.Resampling.BILINEAR)
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
    Quality Gate Editorial HQ & Seleção Inteligente de Quadros (Setup + Clímax):
    Varre os frames ao redor do momento de impacto (target_t) avaliando:
      1. Nitidez (Laplacian variance - elimina motion blur)
      2. Exposição, Contraste e Saturação (evita quadros escuros demais ou lavados)
      3. Detecção de Rosto/Expressão e Bounding Box dos Olhos (para enquadramento HQ preciso)
      4. Captura dupla (Setup Frame + Climax Frame) para Painéis Duplos de Mangá (2-Panel Split Page)
    100% focado em Quadros Editoriais de Mangá/HQ (ZERO recorte de silhueta/contorno).
    """
    cap = cv2.VideoCapture(video_path)
    v_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    total_v_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    max_dur = total_v_frames / v_fps if total_v_frames > 0 else 9999.0

    scan_start = max(0.0, start_sec - 0.8)
    scan_end = min(max_dur, max(end_sec + 0.4, start_sec + 1.5))

    candidate_times = []
    t = scan_start
    while t <= scan_end:
        candidate_times.append(round(t, 2))
        t += 0.30

    for pt in [target_t, start_sec, start_sec + 0.35, max(0.0, target_t - 0.45)]:
        pt_r = round(pt, 2)
        if 0 <= pt_r <= max_dur and pt_r not in candidate_times:
            candidate_times.append(pt_r)
    candidate_times.sort()

    try:
        from imgutils.detect import detect_faces
        has_face_detector = True
    except Exception:
        has_face_detector = False

    best_score = -999.0
    best_record = None
    all_records = []

    print(f"\n================================================================================")
    print(f"[QUALITY GATE - EDITORIAL HQ PANEL] Selecionando melhor quadro de Manga/Webtoon ({_GPU_DEVICE_NAME})")
    print(f"  * Alvo: {target_t:.2f}s | Janela de fala: {start_sec:.2f}s - {end_sec:.2f}s | Candidatos: {len(candidate_times)}")

    for ct in candidate_times:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(ct * v_fps))
        ret, frame_bgr = cap.read()
        if not ret or frame_bgr is None:
            continue

        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        frame_pil = Image.fromarray(frame_rgb)
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)

        # 1. Nitidez (Laplacian Variance) + Contraste Local (StdDev)
        lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        contrast_std = float(np.std(gray))

        # 2. Luminância e Saturação
        lum = float(np.mean(gray))
        sat = float(np.mean(hsv[:, :, 1]))

        # 4. Score Base de Qualidade Editorial HQ (antes do detector facial GPU)
        sharp_score = min(65.0, lap_var / 3.2)
        if lap_var < 30.0:
            sharp_score -= 35.0

        contrast_score = min(25.0, contrast_std * 0.45)

        if 38.0 <= lum <= 205.0:
            lum_score = 25.0
        elif lum < 22.0 or lum > 235.0:
            lum_score = -45.0
        else:
            lum_score = 5.0

        time_dist = abs(ct - target_t)
        time_bonus = max(0.0, 18.0 - (time_dist * 9.0))
        base_score = sharp_score + contrast_score + lum_score + time_bonus

        record = {
            "time": ct,
            "base_score": base_score,
            "score": base_score,
            "raw_pil": frame_pil,
            "raw_rgb": frame_rgb,
            "laplacian_var": lap_var,
            "contrast": contrast_std,
            "luminance": lum,
            "saturation": sat,
            "has_face": False,
            "face_box": None,
        }
        all_records.append(record)

    cap.release()

    # 3. Detecção Rápida de Rosto na GPU (apenas nos 4 quadros mais nítidos para máxima velocidade)
    if has_face_detector and all_records:
        top_for_face = sorted(
            [r for r in all_records if r["laplacian_var"] >= 28.0],
            key=lambda r: r["base_score"],
            reverse=True
        )[:4]
        for rec in top_for_face:
            try:
                fpil = rec["raw_pil"]
                orig_w, orig_h = fpil.size
                if orig_w > 640:
                    scale_f = 640.0 / float(orig_w)
                    det_pil = fpil.resize((640, max(1, int(orig_h * scale_f))), Image.Resampling.BILINEAR)
                else:
                    scale_f = 1.0
                    det_pil = fpil
                with _ORT_GPU_LOCK:
                    faces = detect_faces(det_pil)
                if faces:
                    rec["has_face"] = True
                    best_f = max(faces, key=lambda item: (item[0][2] - item[0][0]) * (item[0][3] - item[0][1]))
                    inv_s = 1.0 / scale_f
                    rec["face_box"] = tuple(int(v * inv_s) for v in best_f[0])
                    rec["score"] = rec["base_score"] + 40.0
            except Exception:
                pass

    for record in all_records:
        if record["score"] > best_score:
            best_score = record["score"]
            best_record = record

    if best_record is None:
        print("[QUALITY GATE] Nenhum frame pôde ser extraído.")
        print(f"================================================================================\n")
        return {"status": "FALHA", "score": 0.0, "time": target_t}

    # Seleciona um quadro complementar (Setup Frame) de 0.32s a 0.90s de distância para Painéis Duplos (hq_dual_split)
    setup_pil = best_record["raw_pil"]
    best_t = best_record["time"]
    setup_candidates = [
        r for r in all_records
        if abs(r["time"] - best_t) >= 0.30 and r["laplacian_var"] >= 24.0
    ]
    if setup_candidates:
        earlier = [r for r in setup_candidates if r["time"] < best_t]
        chosen_setup = max(earlier, key=lambda r: r["score"]) if earlier else max(setup_candidates, key=lambda r: r["score"])
        setup_pil = chosen_setup["raw_pil"]

    best_record["setup_pil"] = setup_pil
    best_record["status"] = "APROVADO_PAINEL_HQ"

    print(f"  * Quadro Climax: t={best_record['time']:.2f}s | Score: {best_score:.1f} | Nitidez: {best_record['laplacian_var']:.1f}")
    print(f"  * Contraste: {best_record['contrast']:.1f} | Saturacao: {best_record['saturation']:.1f} | Rosto: {best_record['has_face']} ({best_record['face_box']})")
    print(f"[QUALITY GATE] Status: [APROVADO_PAINEL_HQ] -> Enquadramento Editorial pronto!")
    print(f"================================================================================\n")

    return best_record


def safe_lineart_anime(pil_img: Image.Image) -> Image.Image:
    """Extrai lineart de anime na GPU (ONNX CUDA) com fallback robusto contra falhas de modelo."""
    try:
        from imgutils.edge import edge_image_with_lineart_anime
        with _ORT_GPU_LOCK:
            return edge_image_with_lineart_anime(pil_img)
    except Exception:
        gray = pil_img.convert("L")
        return gray.filter(ImageFilter.FIND_EDGES)


def detect_manga_feeling(text: str) -> str:
    """
    Detecta automaticamente a emoção e contexto dramático da fala para o clímax mangá:
    - 'fire': raiva, poder, explosão, ataque, grito de batalha, exclamação ('!'), intensidade.
    - 'domain_dark': vazio cósmico, escuridão, maldição, autoridade suprema, Sukuna/Gojo.
    - 'blade_stream': respiração shonen, espada, katana fluida, corte de água/vento, elegância marcial.
    - 'blood_ink': ódio visceral, berserk, fúria incontrolável, desespero, sangue.
    - 'cyber_glitch': tecnologia, scanline, erro de sistema, cyberpunk, Matrix.
    - 'comic_halftone': pop shonen reticulado, super-herói, impacto clássico mangá Jump.
    - 'emotional_tear': tristeza profunda, luto, lágrimas, perdão, despedida sensível.
    - 'typewriter': mistério, revelação, suspense, curiosidade, pergunta ('?'), sussurro, frieza.
    - 'slam': choque brutal, corte, espanto, katana slash, perigo iminente.
    - 'comedy': ironia, deboche, confusão cômica, surpresa engraçada.
    """
    t_clean = text.upper()
    emotional_keywords = [
        "DESCULPA", "PERDÃO", "ADEUS", "TRISTE", "CHORAR", "NUNCA MAIS", "MORREU", "LUTO",
        "DOR", "SAUDADE", "PROMETO", "ME PERDOE", "OBRIGADO POR TUDO", "LÁGRIMA", "LUTO"
    ]
    domain_keywords = [
        "DOMÍNIO", "VAZIO", "ESCURIDÃO", "MALDIÇÃO", "TREVAS", "REI", "DEUS", "ABISMO",
        "SUKUNA", "GOJO", "RYOIKI", "TENKAI", "UNIVERSO", "INFINITO"
    ]
    blade_keywords = [
        "RESPIRAÇÃO", "ESPADA", "LÂMINA", "CORTE", "ÁGUA", "FLUXO", "DANÇA", "ESTILO",
        "KATANA", "ZANPAKUTO", "SHIKAI", "FORMA", "GOLPE"
    ]
    blood_keywords = [
        "SANGUE", "DESGRAÇA", "CARNIFICINA", "ÓDIO", "VINGANÇA", "DESESPERO", "MONSTRO",
        "MATANÇA", "DESTRUIÇÃO", "BERSERK", "FÚRIA"
    ]
    cyber_keywords = [
        "SISTEMA", "ERRO", "CONECTAR", "HACK", "CÓDIGO", "FUTURO", "DROID", "CYBER",
        "MATRIZ", "DOWNLOAD", "OVERLOAD"
    ]
    halftone_keywords = [
        "HERÓI", "SUPER", "PUNCH", "SMASH", "SHONEN", "AVANTE", "JUSTIÇA", "VENCER"
    ]
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

    if any(k in t_clean for k in emotional_keywords):
        return "emotional_tear"
    elif any(k in t_clean for k in domain_keywords):
        return "domain_dark"
    elif any(k in t_clean for k in blade_keywords):
        return "blade_stream"
    elif any(k in t_clean for k in blood_keywords):
        return "blood_ink"
    elif any(k in t_clean for k in cyber_keywords):
        return "cyber_glitch"
    elif any(k in t_clean for k in halftone_keywords):
        return "comic_halftone"
    elif any(k in t_clean for k in fire_keywords) or "!" in t_clean:
        return "fire"
    elif any(k in t_clean for k in typewriter_keywords) or "?" in t_clean:
        return "typewriter"
    elif any(k in t_clean for k in comedy_keywords):
        return "comedy"
    return "slam"


def get_feeling_font_path(feeling: str) -> str:
    """Retorna dinamicamente a fonte ideal do sistema ou assets baseada no feeling dramático."""
    if feeling in ("fire", "shonen_badge", "golden_god", "electric", "domain_dark", "blade_stream", "blood_ink"):
        # Pincel Anime Japonês Furioso / Impacto Shonen
        return get_asset_font("Lovely-Scream-Queens.otf")
    elif feeling in ("typewriter", "manga_bubble", "cyber_glitch"):
        # Fonte Nanquim Condensada / Técnica de Mangá
        for f in [r"C:\Windows\Fonts\impact.ttf", r"C:\Windows\Fonts\GOTHICB.TTF", r"C:\Windows\Fonts\ariblk.ttf"]:
            if os.path.exists(f): return f
        return get_asset_font("Lovely-Scream-Queens.otf")
    elif feeling in ("comedy", "offset_comic", "comic_halftone"):
        # Fonte Expressiva / Descontraída / Pop Art
        for f in [r"C:\Windows\Fonts\comicbd.ttf", r"C:\Windows\Fonts\RAVIE.TTF", r"C:\Windows\Fonts\JOKERMAN.TTF"]:
            if os.path.exists(f): return f
        return get_asset_font("Lovely-Scream-Queens.otf")
    elif feeling in (
        "emotional_tear", "dramatic_silence", "silver_grief", "midnight_sorrow",
        "fading_echo", "broken_promise", "cold_solitude",
        "sakura_bloom", "golden_romance", "heart_pulse",
        "velvet_kiss", "starlight_crush", "sweet_blush", "eternal_vow"
    ):
        # Fonte Cinematográfica / Nobre / Sensível / Romântica
        for f in [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf"]:
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

    supported_styles = (
        "shonen_badge", "manga_bubble", "fire", "electric", "golden_god",
        "offset_comic", "slam", "typewriter", "comedy",
        "domain_dark", "blade_stream", "blood_ink", "cyber_glitch", "comic_halftone", "emotional_tear",
        "dramatic_silence", "silver_grief", "midnight_sorrow",
        "sakura_bloom", "golden_romance", "heart_pulse"
    )
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

    # Animação Dinâmica Específica por Feeling (Referência: Jitter Motion Templates)
    bounce = 1.0
    slide_up_y = 0
    slide_x = 0
    blur_snap_r = 0

    if feeling in ("blade_stream", "slam"):
        # TEMPLATE 1: KINETIC SLASH SLICE & SNAP
        # Entra cortando em diagonal veloz com estalo de lâmina
        if t_rel < 0.20:
            p = t_rel / 0.20
            slide_x = int(-40.0 * math.exp(-7.0 * p) * math.cos(4.0 * p))
            slide_up_y = int(28.0 * math.exp(-7.0 * p) * math.cos(4.0 * p))
            bounce = 1.0 + 0.26 * math.exp(-6.0 * p) * math.cos(8.0 * p)
            blur_snap_r = int(6.0 * (1.0 - p))
    elif feeling in ("domain_dark", "blood_ink", "cursed_aura", "abyssal_void"):
        # TEMPLATE 2: HEAVY IMPACT METEOR DROP
        # Queda vertical pesada de cima para baixo com tremor ao cravamento
        if t_rel < 0.24:
            p = t_rel / 0.24
            slide_up_y = int(-42.0 * math.exp(-6.0 * p))
            bounce = 1.0 + 0.40 * math.exp(-5.5 * p) * math.cos(7.5 * p)
            blur_snap_r = int(8.0 * (1.0 - p))
    elif feeling in (
        "golden_god", "emotional_tear", "dramatic_silence", "silver_grief",
        "midnight_sorrow", "fading_echo", "broken_promise", "cold_solitude"
    ):
        # TEMPLATE 3: SMOOTH MASKED SLIDE-UP & CELESTIAL/SERENE RISE
        # Subida suave aveludada com expansão e foco cristalino (zero tremor brusco)
        if t_rel < 0.28:
            p = t_rel / 0.28
            slide_up_y = int(32.0 * math.exp(-4.5 * p))
            bounce = 1.0 + 0.10 * math.exp(-4.0 * p) * math.cos(4.5 * p)
            blur_snap_r = int(8.0 * (1.0 - p))
    elif feeling in (
        "sakura_bloom", "golden_romance", "heart_pulse",
        "velvet_kiss", "starlight_crush", "sweet_blush", "eternal_vow"
    ):
        # TEMPLATE 3B: ROMANTIC FLOAT & HEARTBEAT PULSE
        # Entrada flutuante delicada com pulsação orgânica suave
        if t_rel < 0.26:
            p = t_rel / 0.26
            slide_up_y = int(26.0 * math.exp(-4.8 * p))
            bounce = 1.0 + 0.11 * math.exp(-4.2 * p) * math.cos(4.5 * p)
            blur_snap_r = int(6.0 * (1.0 - p))
        else:
            bounce = 1.0 + 0.025 * math.sin(t_rel * 8.0)
    elif feeling in ("electric", "cyber_glitch"):
        # TEMPLATE 4: KINETIC GLITCH JUMP & ABERRATION
        # Saltos em micro-degraus estroboscópicos e snap de foco imediato
        if t_rel < 0.18:
            p = t_rel / 0.18
            steps = [(-16, 6), (12, -8), (-8, 4), (6, -2), (0, 0)]
            st_idx = min(len(steps) - 1, int(p * len(steps)))
            slide_x, slide_up_y = steps[st_idx]
            bounce = 1.0 + 0.18 * math.sin(p * math.pi * 3)
            blur_snap_r = int(7.0 * (1.0 - p))
    elif feeling in ("comic_halftone", "offset_comic"):
        # TEMPLATE 5: ELASTIC SPRING POP OVERSHOOT (POP DE GIBI)
        # Escala elástica acentuada de gibi (0.4x -> 1.35x -> 1.0x)
        if t_rel < 0.22:
            p = t_rel / 0.22
            bounce = 1.0 + 0.48 * math.exp(-5.5 * p) * math.cos(8.5 * p)
            slide_up_y = int(18.0 * math.exp(-6.0 * p))
    elif feeling in ("shonen_badge", "fire"):
        # TEMPLATE 6: EXPLOSIVE SLAM EXPANSION
        # Slam explosivo frontal com tremor ardente
        if t_rel < 0.20:
            p = t_rel / 0.20
            bounce = 1.0 + 0.38 * math.exp(-6.5 * p) * math.cos(9.0 * p)
            slide_up_y = int(22.0 * math.exp(-6.0 * p))
    elif feeling == "manga_bubble":
        # TEMPLATE 7: WOBBLE POP COM LEVE EXPANSÃO
        if t_rel < 0.22:
            p = t_rel / 0.22
            bounce = 1.0 + 0.35 * math.exp(-5.0 * p) * math.cos(7.5 * p)
            slide_up_y = int(14.0 * math.exp(-5.0 * p))
    else:
        # Padrão equilibrado Jitter Spring
        if t_rel < 0.20:
            p = t_rel / 0.20
            bounce = 1.0 + 0.30 * math.exp(-6.0 * p) * math.cos(8.0 * p)
            slide_up_y = int(24.0 * math.exp(-6.0 * p))

    continuous_push = 1.0 + 0.06 * (t_rel / max(0.4, dur))

    # Shake com amortecimento sutil (apenas para impactos pesados)
    is_heavy_impact = feeling in ("shonen_badge", "electric", "fire", "slam", "domain_dark", "blood_ink")
    shake_decay = math.exp(-3.0 * min(1.0, t_rel / 0.35)) if is_heavy_impact else 0.0
    shake_x = int(math.sin(t_rel * 45) * 3.5 * shake_decay) if is_heavy_impact else 0
    shake_y = int(math.cos(t_rel * 40) * 3.0 * shake_decay) if is_heavy_impact else 0

    # Tipografia Shonen Stacked: calcula tamanho de fonte e dimensões de cada linha
    max_len = max(len(l) for l in active_lines)
    base_sz = 68 if max_len > 28 else (78 if max_len > 20 else (92 if max_len > 12 else 108))
    sz = max(36, int(base_sz * bounce * continuous_push))

    if not hasattr(render_manga_animated_typography, "_font_cache"):
        render_manga_animated_typography._font_cache = {}
    f_cache = render_manga_animated_typography._font_cache

    def _get_f(f_sz: int):
        key = (font_path, f_sz)
        if key not in f_cache:
            try:
                f_cache[key] = ImageFont.truetype(font_path, size=f_sz)
            except Exception:
                f_cache[key] = ImageFont.load_default()
        return f_cache[key]

    f = _get_f(sz)

    # CLAMP UNIVERSAL RIGOROSO: Largura máxima de 840px
    max_w = 840
    max_tw = max(f.getbbox(l)[2] - f.getbbox(l)[0] for l in active_lines)
    if max_tw > max_w:
        sz = max(32, int(sz * (max_w / max_tw)))
        f = _get_f(sz)

    ascent, descent = f.getmetrics()
    line_h = ascent + descent
    gap = int(line_h * 0.28)
    total_h = len(active_lines) * line_h + max(0, len(active_lines) - 1) * gap

    start_y = base_ty - total_h // 2 + shake_y + slide_up_y
    measured_lines = []
    curr_y = start_y
    for l in active_lines:
        bb = f.getbbox(l)
        tw = bb[2] - bb[0]
        if pos_layout == "lateral_left":
            line_tx = 50 + shake_x + slide_x
        elif pos_layout == "lateral_right":
            line_tx = max(40, width - tw - 60) + shake_x + slide_x
        else:
            line_tx = max(40, min(width - tw - 40, center_x - tw // 2)) + shake_x + slide_x
        measured_lines.append({"text": l, "tx": line_tx, "ty": curr_y, "w": tw, "h": line_h})
        curr_y += line_h + gap

    outline_w = max(3, min(7, int(sz * 0.06)))

    def draw_lines_func(draw_obj, font_obj, dx=0, dy=0, fill_col=(255, 255, 255, 255), stroke_w=0, stroke_col=(0, 0, 0, 255)):
        for item in measured_lines:
            if stroke_w > 0:
                draw_obj.text((item["tx"] + dx, item["ty"] + dy), item["text"], font=font_obj, fill=fill_col, stroke_width=stroke_w, stroke_fill=stroke_col)
            else:
                draw_obj.text((item["tx"] + dx, item["ty"] + dy), item["text"], font=font_obj, fill=fill_col)

    grp_x1 = min(m["tx"] for m in measured_lines)
    grp_x2 = max(m["tx"] + m["w"] for m in measured_lines)
    grp_y1 = measured_lines[0]["ty"]
    grp_y2 = measured_lines[-1]["ty"] + measured_lines[-1]["h"]
    grp_w = grp_x2 - grp_x1
    grp_h = grp_y2 - grp_y1

    # Otimização ROI (12x mais rápido): processa GaussianBlur e camadas RGBA apenas na região do texto
    pad_roi_x = max(145, int(grp_w * 0.28) + 95)
    pad_roi_y = max(130, int(grp_h * 0.40) + 95)
    if feeling in ("slam", None) and 0.15 <= t_rel <= 0.38:
        pad_roi_y = max(pad_roi_y, int((grp_w + 120) * 0.32) + 45)
    roi_x1 = max(0, grp_x1 - pad_roi_x)
    roi_y1 = max(0, grp_y1 - pad_roi_y)
    roi_x2 = min(canvas.width, grp_x2 + pad_roi_x)
    roi_y2 = min(canvas.height, grp_y2 + pad_roi_y)

    orig_full_canvas = canvas
    canvas = orig_full_canvas.crop((roi_x1, roi_y1, roi_x2, roi_y2))
    for item in measured_lines:
        item["tx"] -= roi_x1
        item["ty"] -= roi_y1
    grp_x1 -= roi_x1
    grp_x2 -= roi_x1
    grp_y1 -= roi_y1
    grp_y2 -= roi_y1
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

        if blur_snap_r > 0:
            cb_x1 = max(0, grp_x1 - 40)
            cb_y1 = max(0, grp_y1 - 40)
            cb_x2 = min(target_canvas.width, grp_x2 + 40)
            cb_y2 = min(target_canvas.height, grp_y2 + 40)
            if cb_x2 > cb_x1 and cb_y2 > cb_y1:
                crop_box = (cb_x1, cb_y1, cb_x2, cb_y2)
                sub = target_canvas.crop(crop_box).filter(ImageFilter.GaussianBlur(radius=blur_snap_r))
                target_canvas.paste(sub, (crop_box[0], crop_box[1]))

        orig_full_canvas.paste(target_canvas, (roi_x1, roi_y1))
        return orig_full_canvas

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
        draw_lines_func(t_draw, f, 0, 0, fill_col=(255, 255, 255, 255), stroke_w=outline_w, stroke_col=(0, 0, 0, 255))

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
        draw_lines_func(t_draw, f, 3, 4, fill_col=(0, 0, 0, 230))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(15, 15, 20, 255), stroke_w=2, stroke_col=(255, 255, 255, 255))

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
        draw_lines_func(t_draw, f, 0, 0, fill_col=(245, 255, 255, 255), stroke_w=outline_w, stroke_col=(0, 0, 0, 255))

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
        draw_lines_func(t_draw, f, 0, 0, fill_col=(255, 215, 30, 255), stroke_w=outline_w, stroke_col=(0, 0, 0, 255))
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
        draw_lines_func(t_draw, f, 7, 7, fill_col=(0, 210, 255, 255), stroke_w=3, stroke_col=(0, 210, 255, 255))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(255, 245, 30, 255), stroke_w=outline_w, stroke_col=(0, 0, 0, 255))

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
        draw_lines_func(t_draw, f, 0, 0, fill_col=(255, 235, 35, 255), stroke_w=outline_w, stroke_col=(0, 0, 0, 255))

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
            t_draw.text((item["tx"], item["ty"]), cur_ln_slice, font=f, fill=(255, 255, 255, 255), stroke_width=7, stroke_fill=(0, 0, 0, 255))

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
        draw_lines_func(t_draw, f, 0, 0, fill_col=(255, 245, 60, 255), stroke_w=outline_w, stroke_col=(0, 0, 0, 255))

        canvas = Image.alpha_composite(canvas, glow_pop)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: DOMAIN DARK (Expansão de Domínio / Nanquim Cósmico Ultravioleta)
    # --------------------------------------------------------------------------
    elif feeling == "domain_dark":
        glow_pulse = int(28 + 8 * math.sin(t_rel * 14))
        glow_purple = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(glow_purple), f, 0, 0, fill_col=(147, 51, 234, 240))
        glow_purple = glow_purple.filter(ImageFilter.GaussianBlur(radius=glow_pulse))

        glow_core = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(glow_core), f, 0, 0, fill_col=(192, 132, 252, 220))
        glow_core = glow_core.filter(ImageFilter.GaussianBlur(radius=8))

        # Partículas de energia cósmica flutuante
        cosmic_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        c_draw = ImageDraw.Draw(cosmic_layer)
        random.seed(int(t_rel * 20))
        for _ in range(6):
            px = grp_x1 + random.randint(-15, max(1, grp_w + 15))
            py = grp_y1 + random.randint(-15, max(1, grp_h + 15))
            prad = random.randint(3, 7)
            c_draw.ellipse([px - prad, py - prad, px + prad, py + prad], fill=(216, 180, 254, 210))
        cosmic_layer = cosmic_layer.filter(ImageFilter.GaussianBlur(radius=2))

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        draw_lines_func(t_draw, f, 6, 8, fill_col=(10, 5, 20, 250))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(168, 85, 247, 240), stroke_w=outline_w + 1, stroke_col=(0, 0, 0, 255))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(255, 255, 255, 255), stroke_w=2, stroke_col=(168, 85, 247, 240))

        canvas = Image.alpha_composite(canvas, glow_purple)
        canvas = Image.alpha_composite(canvas, glow_core)
        canvas = Image.alpha_composite(canvas, cosmic_layer)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: BLADE STREAM (Lâmina de Água / Respiração Shonen Fluida)
    # --------------------------------------------------------------------------
    elif feeling == "blade_stream":
        glow_cyan = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(glow_cyan), f, 0, 0, fill_col=(6, 182, 212, 240))
        glow_cyan = glow_cyan.filter(ImageFilter.GaussianBlur(radius=24))

        # Arco de água cortando sob as palavras
        water_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        w_draw = ImageDraw.Draw(water_layer)
        w_pts = [
            (grp_x1 - 40, grp_y2 + 8),
            (bcx, grp_y2 - 6),
            (grp_x2 + 40, grp_y2 + 12)
        ]
        w_draw.line(w_pts, fill=(186, 230, 253, 230), width=6)
        w_draw.line(w_pts, fill=(6, 182, 212, 170), width=14)
        water_layer = water_layer.filter(ImageFilter.GaussianBlur(radius=3))

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        draw_lines_func(t_draw, f, 5, 7, fill_col=(5, 15, 30, 250))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(240, 253, 255, 255), stroke_w=outline_w, stroke_col=(8, 20, 45, 255))
        draw_lines_func(t_draw, f, 0, -2, fill_col=(255, 255, 255, 230))

        canvas = Image.alpha_composite(canvas, glow_cyan)
        canvas = Image.alpha_composite(canvas, water_layer)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: BLOOD INK (Berserk Rage / Nanquim Carmesim Espirrado)
    # --------------------------------------------------------------------------
    elif feeling == "blood_ink":
        glow_blood = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(glow_blood), f, 0, 0, fill_col=(185, 28, 28, 240))
        glow_blood = glow_blood.filter(ImageFilter.GaussianBlur(radius=26))

        # Respingos de nanquim agressivo
        splat_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        sp_draw = ImageDraw.Draw(splat_layer)
        random.seed(int(t_rel * 18))
        for _ in range(8):
            sp_x = grp_x1 + random.randint(-10, max(1, grp_w + 10))
            sp_y = grp_y1 + random.randint(-10, max(1, grp_h + 10))
            sp_r = random.randint(4, 9)
            sp_draw.ellipse([sp_x - sp_r, sp_y - sp_r, sp_x + sp_r, sp_y + sp_r], fill=(153, 27, 27, 220))
        splat_layer = splat_layer.filter(ImageFilter.GaussianBlur(radius=1))

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        draw_lines_func(t_draw, f, 7, 8, fill_col=(15, 0, 0, 255))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(239, 68, 68, 255), stroke_w=outline_w + 1, stroke_col=(0, 0, 0, 255))
        draw_lines_func(t_draw, f, 0, -2, fill_col=(254, 202, 202, 210))

        canvas = Image.alpha_composite(canvas, glow_blood)
        canvas = Image.alpha_composite(canvas, splat_layer)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: CYBER GLITCH (Scanlines Holográficas & RGB Split Aberration)
    # --------------------------------------------------------------------------
    elif feeling == "cyber_glitch":
        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)

        # RGB Split: deslocamento ciano/magenta nos primeiros 0.22s
        glitch_shift = int(4.0 * math.exp(-6.0 * min(1.0, t_rel / 0.22))) if t_rel < 0.22 else 1
        draw_lines_func(t_draw, f, -glitch_shift, 0, fill_col=(255, 0, 80, 220))
        draw_lines_func(t_draw, f, glitch_shift, 0, fill_col=(0, 240, 255, 220))

        # Texto base nítido
        draw_lines_func(t_draw, f, 0, 0, fill_col=(240, 245, 255, 255), stroke_w=outline_w, stroke_col=(5, 10, 15, 255))

        # Scanlines horizontais futuristas
        scan_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        sc_draw = ImageDraw.Draw(scan_layer)
        for y_scan in range(grp_y1 - 10, grp_y2 + 10, 4):
            sc_draw.line([(grp_x1 - 20, y_scan), (grp_x2 + 20, y_scan)], fill=(0, 0, 0, 110), width=1)

        canvas = Image.alpha_composite(canvas, txt_layer)
        canvas = Image.alpha_composite(canvas, scan_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: COMIC HALFTONE (Pop Reticulado Clássico Shonen Jump)
    # --------------------------------------------------------------------------
    elif feeling == "comic_halftone":
        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)

        # Sombra dura deslocada a 45 graus
        draw_lines_func(t_draw, f, 9, 9, fill_col=(0, 0, 0, 255))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(250, 204, 21, 255), stroke_w=outline_w, stroke_col=(0, 0, 0, 255))

        # Retícula de pontos pop nas letras
        ht_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        h_draw = ImageDraw.Draw(ht_layer)
        for hx in range(grp_x1 - 10, grp_x2 + 10, 6):
            for hy in range(grp_y1 - 10, grp_y2 + 10, 6):
                h_draw.ellipse([hx, hy, hx + 2, hy + 2], fill=(245, 158, 11, 160))
        ht_blurred = ht_layer.filter(ImageFilter.GaussianBlur(radius=0.5))

        canvas = Image.alpha_composite(canvas, txt_layer)
        canvas = Image.alpha_composite(canvas, ht_blurred)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: EMOTIONAL TEAR (Cenas Tristes / Lágrima / Cristal Azul-Gelo)
    # --------------------------------------------------------------------------
    elif feeling == "emotional_tear":
        pad_x, pad_y = 30, 14
        box_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        b_draw = ImageDraw.Draw(box_layer)
        b_draw.rounded_rectangle(
            [grp_x1 - pad_x, grp_y1 - pad_y, grp_x2 + pad_x, grp_y2 + pad_y],
            radius=16, fill=(10, 16, 28, 205), outline=(186, 230, 253, 190), width=2
        )

        glow_soft = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(glow_soft), f, 0, 0, fill_col=(125, 211, 252, 155))
        glow_soft = glow_soft.filter(ImageFilter.GaussianBlur(radius=24))

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        draw_lines_func(t_draw, f, 0, 0, fill_col=(248, 250, 252, 255), stroke_w=4, stroke_col=(6, 12, 24, 240))

        canvas = Image.alpha_composite(canvas, glow_soft)
        canvas = Image.alpha_composite(canvas, box_layer)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: DRAMATIC SILENCE (Silêncio Dramático / Reflexão Pura Cinematográfica)
    # --------------------------------------------------------------------------
    elif feeling == "dramatic_silence":
        glow_mist = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(glow_mist), f, 0, 0, fill_col=(148, 163, 184, 150))
        glow_mist = glow_mist.filter(ImageFilter.GaussianBlur(radius=28))

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        draw_lines_func(t_draw, f, 4, 6, fill_col=(5, 8, 16, 235))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(241, 245, 249, 255), stroke_w=outline_w, stroke_col=(12, 18, 28, 250))
        draw_lines_func(t_draw, f, 0, -2, fill_col=(255, 255, 255, 220))

        canvas = Image.alpha_composite(canvas, glow_mist)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: SILVER GRIEF (Prata Melancólico & Poeira de Luz / Luto)
    # --------------------------------------------------------------------------
    elif feeling == "silver_grief":
        glow_silver = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(glow_silver), f, 0, 0, fill_col=(186, 230, 253, 145))
        glow_silver = glow_silver.filter(ImageFilter.GaussianBlur(radius=24))

        mote_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        m_draw = ImageDraw.Draw(mote_layer)
        random.seed(99)
        for m_idx in range(7):
            mx = grp_x1 + int((m_idx + 0.5) * (grp_w / 7.0)) + int(8 * math.sin(t_rel * 2.5 + m_idx))
            my = grp_y2 - int(((t_rel * 28 + m_idx * 17) % max(24, grp_h + 24)))
            mr = 3 if m_idx % 2 == 0 else 2
            m_draw.ellipse([mx - mr, my - mr, mx + mr, my + mr], fill=(224, 242, 254, 175))
        mote_layer = mote_layer.filter(ImageFilter.GaussianBlur(radius=1))

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        draw_lines_func(t_draw, f, 5, 6, fill_col=(8, 12, 20, 240))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(203, 213, 225, 255), stroke_w=outline_w, stroke_col=(15, 23, 42, 255))
        draw_lines_func(t_draw, f, 0, -2, fill_col=(248, 250, 252, 240))

        canvas = Image.alpha_composite(canvas, glow_silver)
        canvas = Image.alpha_composite(canvas, mote_layer)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: MIDNIGHT SORROW (Azul Meia-Noite Profundo / Despedida)
    # --------------------------------------------------------------------------
    elif feeling == "midnight_sorrow":
        pad_x, pad_y = 26, 12
        badge_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        b_draw = ImageDraw.Draw(badge_layer)
        b_draw.rounded_rectangle(
            [grp_x1 - pad_x, grp_y1 - pad_y, grp_x2 + pad_x, grp_y2 + pad_y],
            radius=12, fill=(8, 15, 32, 215), outline=(56, 189, 248, 185), width=2
        )

        glow_night = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(glow_night), f, 0, 0, fill_col=(30, 64, 175, 180))
        glow_night = glow_night.filter(ImageFilter.GaussianBlur(radius=22))

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        draw_lines_func(t_draw, f, 0, 0, fill_col=(224, 242, 254, 255), stroke_w=4, stroke_col=(4, 8, 18, 245))

        canvas = Image.alpha_composite(canvas, glow_night)
        canvas = Image.alpha_composite(canvas, badge_layer)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: SAKURA BLOOM (Romance Shoujo / Rosa Sakura & Pérola)
    # --------------------------------------------------------------------------
    elif feeling == "sakura_bloom":
        glow_pink = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(glow_pink), f, 0, 0, fill_col=(244, 114, 182, 215))
        glow_pink = glow_pink.filter(ImageFilter.GaussianBlur(radius=24))

        petal_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        p_draw = ImageDraw.Draw(petal_layer)
        random.seed(77)
        for p_idx in range(6):
            px = grp_x1 - 12 + int((p_idx + 0.4) * ((grp_w + 24) / 6.0)) + int(10 * math.cos(t_rel * 3.0 + p_idx))
            py = grp_y1 - 8 + int(((t_rel * 24 + p_idx * 19) % max(24, grp_h + 18)))
            p_draw.ellipse([px - 5, py - 3, px + 5, py + 3], fill=(251, 207, 232, 210))
        petal_layer = petal_layer.filter(ImageFilter.GaussianBlur(radius=1))

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        draw_lines_func(t_draw, f, 5, 6, fill_col=(45, 10, 28, 240))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(253, 242, 248, 255), stroke_w=outline_w, stroke_col=(65, 14, 38, 255))
        draw_lines_func(t_draw, f, 0, -2, fill_col=(255, 255, 255, 240))

        canvas = Image.alpha_composite(canvas, glow_pink)
        canvas = Image.alpha_composite(canvas, petal_layer)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: GOLDEN ROMANCE (Luz Dourada do Pôr do Sol & Estrelas)
    # --------------------------------------------------------------------------
    elif feeling == "golden_romance":
        glow_warm = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(glow_warm), f, 0, 0, fill_col=(251, 146, 60, 205))
        glow_warm = glow_warm.filter(ImageFilter.GaussianBlur(radius=24))

        sparkle_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        sp_draw = ImageDraw.Draw(sparkle_layer)
        sp_pts = [(grp_x1 + 8, grp_y1 + 6), (grp_x2 - 8, grp_y1 + 6), (bcx, grp_y2 - 4)]
        rot_ang = t_rel * 3.0
        for sx, sy in sp_pts:
            dx1, dy1 = int(10 * math.cos(rot_ang)), int(10 * math.sin(rot_ang))
            dx2, dy2 = int(10 * math.cos(rot_ang + math.pi / 2)), int(10 * math.sin(rot_ang + math.pi / 2))
            sp_draw.line([(sx - dx1, sy - dy1), (sx + dx1, sy + dy1)], fill=(255, 251, 235, 230), width=2)
            sp_draw.line([(sx - dx2, sy - dy2), (sx + dx2, sy + dy2)], fill=(255, 251, 235, 230), width=2)

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        draw_lines_func(t_draw, f, 5, 6, fill_col=(40, 16, 10, 240))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(254, 243, 199, 255), stroke_w=outline_w, stroke_col=(55, 20, 12, 255))
        draw_lines_func(t_draw, f, 0, -2, fill_col=(255, 255, 255, 230))

        canvas = Image.alpha_composite(canvas, glow_warm)
        canvas = Image.alpha_composite(canvas, txt_layer)
        canvas = Image.alpha_composite(canvas, sparkle_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: HEART PULSE (Batimento Emocional Rubi & Quartzo Rosa)
    # --------------------------------------------------------------------------
    elif feeling == "heart_pulse":
        pad_x, pad_y = 28, 12
        badge_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        b_draw = ImageDraw.Draw(badge_layer)
        b_draw.rounded_rectangle(
            [grp_x1 - pad_x, grp_y1 - pad_y, grp_x2 + pad_x, grp_y2 + pad_y],
            radius=18, fill=(45, 10, 24, 210), outline=(251, 113, 133, 210), width=2
        )

        glow_ruby = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(glow_ruby), f, 0, 0, fill_col=(225, 29, 72, 185))
        glow_ruby = glow_ruby.filter(ImageFilter.GaussianBlur(radius=22))

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        draw_lines_func(t_draw, f, 0, 0, fill_col=(255, 241, 242, 255), stroke_w=4, stroke_col=(28, 6, 14, 245))

        canvas = Image.alpha_composite(canvas, glow_ruby)
        canvas = Image.alpha_composite(canvas, badge_layer)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: FADING ECHO (Eco Desbotado / Lavanda-Gelo & Sombra Dupla Fantasma)
    # --------------------------------------------------------------------------
    elif feeling == "fading_echo":
        glow_echo = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(glow_echo), f, 0, 0, fill_col=(165, 180, 252, 145))
        glow_echo = glow_echo.filter(ImageFilter.GaussianBlur(radius=24))

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        # Eco fantasma deslocado sutilmente
        echo_dx = int(10 + 4 * math.sin(t_rel * 4.0))
        draw_lines_func(t_draw, f, echo_dx, -6, fill_col=(199, 210, 254, 75))
        draw_lines_func(t_draw, f, 5, 6, fill_col=(10, 12, 24, 240))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(224, 231, 255, 255), stroke_w=outline_w, stroke_col=(15, 23, 42, 255))
        draw_lines_func(t_draw, f, 0, -2, fill_col=(255, 255, 255, 235))

        canvas = Image.alpha_composite(canvas, glow_echo)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: BROKEN PROMISE (Promessa Partida / Azul-Ardósia & Pérola)
    # --------------------------------------------------------------------------
    elif feeling == "broken_promise":
        pad_x, pad_y = 26, 12
        box_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        b_draw = ImageDraw.Draw(box_layer)
        b_draw.rectangle(
            [grp_x1 - pad_x, grp_y1 - pad_y, grp_x2 + pad_x, grp_y2 + pad_y],
            fill=(15, 23, 42, 215), outline=(148, 163, 184, 200), width=2
        )
        b_draw.line([(grp_x1 - pad_x + 8, grp_y1 - pad_y + 4), (grp_x2 + pad_x - 8, grp_y2 + pad_y - 4)], fill=(226, 232, 240, 55), width=2)

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        draw_lines_func(t_draw, f, 0, 0, fill_col=(241, 245, 249, 255), stroke_w=4, stroke_col=(9, 13, 22, 245))

        canvas = Image.alpha_composite(canvas, box_layer)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: COLD SOLITUDE (Solidão Gélida / Ciano-Inverno & Marinho Abissal)
    # --------------------------------------------------------------------------
    elif feeling == "cold_solitude":
        glow_frost = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(glow_frost), f, 0, 0, fill_col=(103, 232, 249, 160))
        glow_frost = glow_frost.filter(ImageFilter.GaussianBlur(radius=22))

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        draw_lines_func(t_draw, f, 5, 7, fill_col=(4, 12, 24, 245))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(207, 250, 254, 255), stroke_w=outline_w, stroke_col=(8, 47, 73, 255))
        draw_lines_func(t_draw, f, 0, -2, fill_col=(255, 255, 255, 240))

        canvas = Image.alpha_composite(canvas, glow_frost)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: VELVET KISS (Beijo de Veludo / Carmim-Rosé & Creme Nobre)
    # --------------------------------------------------------------------------
    elif feeling == "velvet_kiss":
        glow_velvet = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(glow_velvet), f, 0, 0, fill_col=(244, 63, 94, 195))
        glow_velvet = glow_velvet.filter(ImageFilter.GaussianBlur(radius=24))

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        draw_lines_func(t_draw, f, 5, 6, fill_col=(40, 6, 18, 245))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(255, 228, 230, 255), stroke_w=outline_w, stroke_col=(136, 19, 55, 255))
        draw_lines_func(t_draw, f, 0, -2, fill_col=(255, 255, 255, 240))

        canvas = Image.alpha_composite(canvas, glow_velvet)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: STARLIGHT CRUSH (Brilho Estelar / Champanhe & Violeta Pastel)
    # --------------------------------------------------------------------------
    elif feeling == "starlight_crush":
        glow_star = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(glow_star), f, 0, 0, fill_col=(216, 180, 254, 195))
        glow_star = glow_star.filter(ImageFilter.GaussianBlur(radius=24))

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        draw_lines_func(t_draw, f, 5, 6, fill_col=(30, 10, 48, 240))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(254, 249, 195, 255), stroke_w=outline_w, stroke_col=(88, 28, 135, 255))
        draw_lines_func(t_draw, f, 0, -2, fill_col=(255, 255, 255, 240))

        canvas = Image.alpha_composite(canvas, glow_star)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: SWEET BLUSH (Rubor Doce / Coral-Pêssego & Marfim)
    # --------------------------------------------------------------------------
    elif feeling == "sweet_blush":
        pad_x, pad_y = 26, 12
        badge_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        b_draw = ImageDraw.Draw(badge_layer)
        b_draw.rounded_rectangle(
            [grp_x1 - pad_x, grp_y1 - pad_y, grp_x2 + pad_x, grp_y2 + pad_y],
            radius=20, fill=(55, 16, 24, 205), outline=(253, 186, 116, 215), width=2
        )

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        draw_lines_func(t_draw, f, 0, 0, fill_col=(255, 237, 213, 255), stroke_w=4, stroke_col=(35, 10, 16, 245))

        canvas = Image.alpha_composite(canvas, badge_layer)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: ETERNAL VOW (Juramento Eterno / Pérola & Ouro Rosé Imperial)
    # --------------------------------------------------------------------------
    elif feeling == "eternal_vow":
        glow_vow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(glow_vow), f, 0, 0, fill_col=(253, 164, 175, 195))
        glow_vow = glow_vow.filter(ImageFilter.GaussianBlur(radius=24))

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        draw_lines_func(t_draw, f, 5, 6, fill_col=(36, 12, 20, 245))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(255, 251, 235, 255), stroke_w=outline_w, stroke_col=(120, 53, 15, 255))
        draw_lines_func(t_draw, f, 0, -2, fill_col=(255, 255, 255, 245))

        canvas = Image.alpha_composite(canvas, glow_vow)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: CURSED AURA (Aura Amaldiçoada / Violeta Abissal & Fogo Negro)
    # --------------------------------------------------------------------------
    elif feeling == "cursed_aura":
        glow_curse = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(glow_curse), f, 0, 0, fill_col=(126, 34, 206, 235))
        glow_curse = glow_curse.filter(ImageFilter.GaussianBlur(radius=26))

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        draw_lines_func(t_draw, f, 6, 8, fill_col=(5, 0, 12, 255))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(233, 213, 255, 255), stroke_w=outline_w + 1, stroke_col=(8, 4, 16, 255))
        draw_lines_func(t_draw, f, 0, -2, fill_col=(192, 132, 252, 235))

        canvas = Image.alpha_composite(canvas, glow_curse)
        canvas = Image.alpha_composite(canvas, txt_layer)
        return finish_typography_frame(canvas)

    # --------------------------------------------------------------------------
    # MODO: ABYSSAL VOID (Vazio Abissal / Prata-Cinza & Nanquim Puro Seinen)
    # --------------------------------------------------------------------------
    elif feeling == "abyssal_void":
        glow_void = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines_func(ImageDraw.Draw(glow_void), f, 0, 0, fill_col=(148, 163, 184, 175))
        glow_void = glow_void.filter(ImageFilter.GaussianBlur(radius=24))

        txt_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        t_draw = ImageDraw.Draw(txt_layer)
        draw_lines_func(t_draw, f, 7, 8, fill_col=(0, 0, 0, 255))
        draw_lines_func(t_draw, f, 0, 0, fill_col=(226, 232, 240, 255), stroke_w=outline_w + 1, stroke_col=(5, 5, 8, 255))
        draw_lines_func(t_draw, f, 0, -2, fill_col=(255, 255, 255, 245))

        canvas = Image.alpha_composite(canvas, glow_void)
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
        draw_lines_func(t_draw, f, 0, 0, fill_col=(255, 45, 65, 255), stroke_w=outline_w, stroke_col=(0, 0, 0, 255))

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


def _get_feeling_accent_palette(feeling: Optional[str]) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    """Retorna (cor_primaria_rgb, cor_secundaria_rgb) de acordo com o feeling dramático da cena."""
    f = (feeling or "slam").lower()
    palettes = {
        "domain_dark": ((170, 55, 255), (90, 20, 180)),
        "blade_stream": ((0, 235, 255), (0, 180, 150)),
        "golden_god": ((255, 210, 45), (255, 145, 0)),
        "blood_ink": ((235, 20, 45), (140, 0, 20)),
        "electric": ((0, 240, 255), (40, 110, 255)),
        "cyber_glitch": ((0, 255, 200), (255, 0, 128)),
        "fire": ((255, 95, 20), (255, 200, 30)),
        "shonen_badge": ((240, 35, 55), (255, 200, 40)),
        "comic_halftone": ((255, 215, 0), (255, 50, 90)),
        "offset_comic": ((0, 235, 255), (255, 40, 150)),
        "emotional_tear": ((125, 211, 252), (56, 189, 248)),
        "dramatic_silence": ((203, 213, 225), (148, 163, 184)),
        "silver_grief": ((186, 230, 253), (100, 116, 139)),
        "midnight_sorrow": ((56, 189, 248), (30, 64, 175)),
        "fading_echo": ((165, 180, 252), (129, 140, 248)),
        "broken_promise": ((148, 163, 184), (71, 85, 105)),
        "cold_solitude": ((103, 232, 249), (14, 116, 144)),
        "sakura_bloom": ((244, 114, 182), (251, 207, 232)),
        "golden_romance": ((251, 191, 36), (244, 114, 182)),
        "heart_pulse": ((251, 113, 133), (225, 29, 72)),
        "velvet_kiss": ((244, 63, 94), (251, 113, 133)),
        "starlight_crush": ((216, 180, 254), (254, 240, 138)),
        "sweet_blush": ((253, 186, 116), (251, 146, 60)),
        "eternal_vow": ((253, 164, 175), (254, 243, 199)),
        "cursed_aura": ((168, 85, 247), (88, 28, 135)),
        "abyssal_void": ((203, 213, 225), (71, 85, 105)),
        "typewriter": ((0, 230, 210), (20, 120, 140)),
        "manga_bubble": ((255, 255, 255), (235, 40, 60)),
        "comedy": ((255, 80, 200), (255, 220, 40)),
        "slam": ((255, 50, 70), (0, 220, 255)),
    }
    return palettes.get(f, ((255, 55, 75), (0, 220, 255)))


def _smart_crop_to_panel(
    pil_img: Image.Image,
    target_w: int,
    target_h: int,
    face_box: Optional[Tuple[int, int, int, int]] = None,
    zoom_bias: float = 1.0
) -> Image.Image:
    """
    Faz o enquadramento inteligente (Smart Crop Editorial) preservando 100% da proporção (zero esticamento)
    e centralizando no rosto/olhos detectados quando disponível.
    """
    src_w, src_h = pil_img.size
    if src_w <= 0 or src_h <= 0:
        return pil_img.resize((target_w, target_h), Image.Resampling.LANCZOS)

    target_aspect = target_w / float(target_h)
    src_aspect = src_w / float(src_h)

    if src_aspect > target_aspect:
        crop_h = src_h
        crop_w = int(round(crop_h * target_aspect))
    else:
        crop_w = src_w
        crop_h = int(round(crop_w / target_aspect))

    if zoom_bias > 1.0:
        crop_w = max(64, int(round(crop_w / zoom_bias)))
        crop_h = max(64, int(round(crop_h / zoom_bias)))

    if face_box and len(face_box) == 4:
        fx0, fy0, fx1, fy1 = face_box
        fcx = (fx0 + fx1) // 2
        fcy = int(fy0 + (fy1 - fy0) * 0.42)  # Foco na linha dos olhos
    else:
        fcx = src_w // 2
        fcy = int(src_h * 0.42)

    x1 = max(0, min(src_w - crop_w, fcx - crop_w // 2))
    y1 = max(0, min(src_h - crop_h, fcy - crop_h // 2))
    cropped = pil_img.crop((x1, y1, x1 + crop_w, y1 + crop_h))
    return cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)


def _render_editorial_art_surface(
    raw_pil: Image.Image,
    panel_w: int,
    panel_h: int,
    panel_style: str = "hq_shonen_panel",
    feeling: Optional[str] = None,
    face_box: Optional[Tuple[int, int, int, int]] = None,
    zoom_bias: float = 1.0
) -> Image.Image:
    """
    Converte um quadro do anime em Arte Editorial de Mangá/HQ de altíssima definição:
      - 'hq_shonen_panel': Nanquim Japonês P&B + Retícula Halftone 45° + Selective Color Pop nas cores vibrantes (olhos/poderes/fogo).
      - 'hq_color_webtoon': Cel-Shading Colorido estilo Solo Leveling / Manhwa Deluxe + Lineart Nanquim + Vibrance Boost.
      - 'hq_noir_crimson': Seinen Dark / Sin City Noir (Pretos profundos + Brancos puros + Duotone de destaque dramático).
      - 'hq_diagonal_impact': Estilo Híbrido Shonen/Webtoon de alto impacto contrastado.
      - 'hq_eyes_strip': Close-up focado nos olhos/expressão com nanquim + brilho ocular preservado.
    """
    cropped_pil = _smart_crop_to_panel(raw_pil, panel_w, panel_h, face_box=face_box, zoom_bias=zoom_bias).convert("RGB")
    rgb_np = np.array(cropped_pil)
    bgr_np = cv2.cvtColor(rgb_np, cv2.COLOR_RGB2BGR)

    # Lineart de Nanquim Fina e Nítida (ONNX CUDA) + Retícula Halftone 45° acelerada por GPU (Torch CUDA)
    lineart_pil = safe_lineart_anime(cropped_pil).convert("L")
    gray_pil = ImageOps.autocontrast(cropped_pil.convert("L"), cutoff=2)

    if _TORCH_CUDA_AVAILABLE and _CUDA_DEVICE is not None:
        try:
            import torch
            with torch.no_grad():
                ink_t = torch.from_numpy(np.array(lineart_pil, dtype=np.float32)).to(_CUDA_DEVICE) / 255.0
                ink_boost_t = torch.clamp((ink_t - 0.14) / 0.86, 0.0, 1.0) ** 0.88

                yy_t = torch.arange(panel_h, device=_CUDA_DEVICE, dtype=torch.float32).unsqueeze(1).expand(panel_h, panel_w)
                xx_t = torch.arange(panel_w, device=_CUDA_DEVICE, dtype=torch.float32).unsqueeze(0).expand(panel_h, panel_w)
                rot_u_t = (xx_t * 0.7071 + yy_t * 0.7071) / 5.2
                rot_v_t = (-xx_t * 0.7071 + yy_t * 0.7071) / 5.2
                dots_t = 0.5 + 0.25 * (torch.sin(rot_u_t * math.pi) + torch.cos(rot_v_t * math.pi))

                gray_t = torch.from_numpy(np.array(gray_pil, dtype=np.float32)).to(_CUDA_DEVICE) / 255.0
                midtone_t = (gray_t > 0.18) & (gray_t < 0.78)
                halftoned_t = torch.where(
                    midtone_t,
                    torch.clamp(gray_t * 0.82 + (gray_t > dots_t * 0.88).float() * 0.22, 0.0, 1.0),
                    torch.where(gray_t <= 0.18, gray_t * 0.45, torch.clamp(gray_t * 1.08, 0.0, 1.0))
                )
                ink_boost = ink_boost_t.cpu().numpy()
                dots = dots_t.cpu().numpy()
                gray_f = gray_t.cpu().numpy()
                halftoned_gray = halftoned_t.cpu().numpy()
        except Exception:
            ink_np = np.array(lineart_pil).astype(np.float32) / 255.0
            ink_boost = np.clip((ink_np - 0.14) / 0.86, 0.0, 1.0) ** 0.88
            yy, xx = np.mgrid[0:panel_h, 0:panel_w]
            rot_u = (xx * 0.7071 + yy * 0.7071) / 5.2
            rot_v = (-xx * 0.7071 + yy * 0.7071) / 5.2
            dots = 0.5 + 0.25 * (np.sin(rot_u * math.pi) + np.cos(rot_v * math.pi))
            gray_f = np.array(gray_pil).astype(np.float32) / 255.0
            midtone_mask = (gray_f > 0.18) & (gray_f < 0.78)
            halftoned_gray = np.where(
                midtone_mask,
                np.clip(gray_f * 0.82 + (gray_f > dots * 0.88).astype(np.float32) * 0.22, 0.0, 1.0),
                np.where(gray_f <= 0.18, gray_f * 0.45, np.clip(gray_f * 1.08, 0.0, 1.0))
            )
    else:
        ink_np = np.array(lineart_pil).astype(np.float32) / 255.0
        ink_boost = np.clip((ink_np - 0.14) / 0.86, 0.0, 1.0) ** 0.88
        yy, xx = np.mgrid[0:panel_h, 0:panel_w]
        rot_u = (xx * 0.7071 + yy * 0.7071) / 5.2
        rot_v = (-xx * 0.7071 + yy * 0.7071) / 5.2
        dots = 0.5 + 0.25 * (np.sin(rot_u * math.pi) + np.cos(rot_v * math.pi))
        gray_f = np.array(gray_pil).astype(np.float32) / 255.0
        midtone_mask = (gray_f > 0.18) & (gray_f < 0.78)
        halftoned_gray = np.where(
            midtone_mask,
            np.clip(gray_f * 0.82 + (gray_f > dots * 0.88).astype(np.float32) * 0.22, 0.0, 1.0),
            np.where(gray_f <= 0.18, gray_f * 0.45, np.clip(gray_f * 1.08, 0.0, 1.0))
        )

    manga_bw_u8 = np.clip(halftoned_gray * ink_boost * 255.0, 0, 255).astype(np.uint8)
    manga_bw_rgb = np.dstack([manga_bw_u8, manga_bw_u8, manga_bw_u8])

    accent_rgb, secondary_rgb = _get_feeling_accent_palette(feeling)

    if panel_style == "hq_color_webtoon":
        # Estilo Solo Leveling / Webtoon Color Deluxe: Bilateral Cel-Shading + Saturação + Nanquim
        smooth_bgr = cv2.bilateralFilter(bgr_np, d=7, sigmaColor=55, sigmaSpace=55)
        hsv = cv2.cvtColor(smooth_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.32, 0, 255)
        hsv[:, :, 2] = np.clip((hsv[:, :, 2] - 128.0) * 1.18 + 132.0, 0, 255)
        vivid_rgb = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB).astype(np.float32)

        # Aplica textura de retícula sutil apenas nas sombras profundas + traço de nanquim
        shadow_dots = np.where((gray_f < 0.35) & (gray_f < dots * 0.55), 0.78, 1.0)[:, :, None]
        webtoon_np = np.clip(vivid_rgb * shadow_dots * (ink_boost[:, :, None] ** 0.75), 0, 255).astype(np.uint8)
        return Image.fromarray(webtoon_np).convert("RGBA")

    elif panel_style == "hq_noir_crimson":
        # Estilo Seinen Dark / Sin City Noir: Pretos abissais, brancos cortantes e duotone dramático
        noir_lum = np.clip((gray_f - 0.22) / 0.65, 0.0, 1.0)
        noir_ink = noir_lum * (ink_boost ** 1.05)

        hsv = cv2.cvtColor(bgr_np, cv2.COLOR_BGR2HSV).astype(np.float32)
        sat_norm = hsv[:, :, 1] / 255.0
        val_norm = hsv[:, :, 2] / 255.0
        accent_mask = np.clip((sat_norm - 0.38) * 2.8, 0.0, 1.0) * np.clip(val_norm * 1.3, 0.0, 1.0)

        base_noir = np.dstack([noir_ink * 245, noir_ink * 245, noir_ink * 250])
        acc_layer = np.zeros_like(base_noir)
        acc_layer[:, :, 0] = accent_rgb[0] * np.clip(val_norm * 1.2, 0.2, 1.0)
        acc_layer[:, :, 1] = accent_rgb[1] * np.clip(val_norm * 1.2, 0.2, 1.0)
        acc_layer[:, :, 2] = accent_rgb[2] * np.clip(val_norm * 1.2, 0.2, 1.0)

        blend = (base_noir * (1.0 - accent_mask[:, :, None] * 0.82) + acc_layer * (accent_mask[:, :, None] * 0.82))
        blend = np.clip(blend * (ink_boost[:, :, None] ** 0.85), 0, 255).astype(np.uint8)
        return Image.fromarray(blend).convert("RGBA")

    elif panel_style == "hq_rain_melancholy":
        # Quadro Editorial Melancólico (Chuva & Prata Azul-Frio): Desaturação fria + Retícula Suave + Nanquim Delicado
        smooth_bgr = cv2.bilateralFilter(bgr_np, d=7, sigmaColor=45, sigmaSpace=45)
        hsv = cv2.cvtColor(smooth_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 0.42, 0, 255)
        desat_rgb = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB).astype(np.float32)

        silver_blue_bw = np.dstack([
            halftoned_gray * 215.0,
            halftoned_gray * 230.0,
            np.clip(halftoned_gray * 252.0 + 8.0, 0, 255)
        ])
        melancholy_mix = (silver_blue_bw * 0.62 + desat_rgb * 0.38) * (ink_boost[:, :, None] ** 0.82)
        return Image.fromarray(np.clip(melancholy_mix, 0, 255).astype(np.uint8)).convert("RGBA")

    elif panel_style == "hq_soft_memory":
        # Quadro Editorial Memória / Flashback Emocional: Tom Marfim/Sépia-Prateado Suave + Nanquim Fino
        smooth_bgr = cv2.bilateralFilter(bgr_np, d=7, sigmaColor=50, sigmaSpace=50)
        hsv = cv2.cvtColor(smooth_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 0.48, 0, 255)
        soft_rgb = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB).astype(np.float32)

        ivory_bw = np.dstack([
            np.clip(halftoned_gray * 248.0 + 5.0, 0, 255),
            np.clip(halftoned_gray * 240.0 + 3.0, 0, 255),
            halftoned_gray * 228.0
        ])
        memory_mix = (ivory_bw * 0.58 + soft_rgb * 0.42) * (ink_boost[:, :, None] ** 0.78)
        return Image.fromarray(np.clip(memory_mix, 0, 255).astype(np.uint8)).convert("RGBA")

    elif panel_style == "hq_romance_glow":
        # Quadro Editorial Shoujo / Webtoon Romance: Cel-Shading Luminoso + Tons Quentes Rosé/Ouro + Nanquim Suave
        smooth_bgr = cv2.bilateralFilter(bgr_np, d=7, sigmaColor=60, sigmaSpace=60)
        hsv = cv2.cvtColor(smooth_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.18, 0, 255)
        hsv[:, :, 2] = np.clip((hsv[:, :, 2] - 115.0) * 1.12 + 128.0, 0, 255)
        rom_rgb = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB).astype(np.float32)

        # Realce quente Rosé/Pêssego sutil nas luzes altas
        rom_rgb[:, :, 0] = np.clip(rom_rgb[:, :, 0] * 1.05 + 6.0, 0, 255)
        rom_rgb[:, :, 1] = np.clip(rom_rgb[:, :, 1] * 1.01 + 2.0, 0, 255)
        rom_rgb[:, :, 2] = np.clip(rom_rgb[:, :, 2] * 1.03 + 4.0, 0, 255)
        rom_inked = np.clip(rom_rgb * (ink_boost[:, :, None] ** 0.72), 0, 255).astype(np.uint8)
        return Image.fromarray(rom_inked).convert("RGBA")

    elif panel_style == "hq_pop_halftone":
        # Quadro Editorial Pop Vibrante (Comédia / Animada / Hype): Cores Ultra Vivas + Retícula Pop
        smooth_bgr = cv2.bilateralFilter(bgr_np, d=7, sigmaColor=55, sigmaSpace=55)
        hsv = cv2.cvtColor(smooth_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.42, 0, 255)
        hsv[:, :, 2] = np.clip((hsv[:, :, 2] - 120.0) * 1.22 + 134.0, 0, 255)
        pop_rgb = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB).astype(np.float32)

        pop_dots = np.where((gray_f < 0.42) & (gray_f < dots * 0.65), 0.80, 1.0)[:, :, None]
        pop_np = np.clip(pop_rgb * pop_dots * (ink_boost[:, :, None] ** 0.78), 0, 255).astype(np.uint8)
        return Image.fromarray(pop_np).convert("RGBA")

    elif panel_style == "hq_golden_eclipse":
        # Quadro Editorial Eclipse Dourado / Imperial: Contraste Obsidiana + Luzes Champanhe/Ouro + Nanquim
        smooth_bgr = cv2.bilateralFilter(bgr_np, d=7, sigmaColor=50, sigmaSpace=50)
        hsv = cv2.cvtColor(smooth_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 0.88, 0, 255)
        warm_rgb = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB).astype(np.float32)

        gold_bw = np.dstack([
            np.clip(halftoned_gray * 255.0 + 8.0, 0, 255),
            np.clip(halftoned_gray * 238.0 + 2.0, 0, 255),
            halftoned_gray * 195.0
        ])
        eclipse_mix = (gold_bw * 0.48 + warm_rgb * 0.52) * (ink_boost[:, :, None] ** 0.82)
        return Image.fromarray(np.clip(eclipse_mix, 0, 255).astype(np.uint8)).convert("RGBA")

    else:
        # Estilo Shonen Jump Lead Panel (P&B Nanquim + Retícula + Selective Color Pop nos poderes/olhos vibrantes!)
        hsv = cv2.cvtColor(bgr_np, cv2.COLOR_BGR2HSV).astype(np.float32)
        sat_norm = hsv[:, :, 1] / 255.0
        val_norm = hsv[:, :, 2] / 255.0

        # Preserva parcialmente cores ultra-saturadas e luminosas (chamas, olhos brilhantes, raios, sangue)
        pop_mask = np.clip((sat_norm - 0.45) * 2.4, 0.0, 0.78) * np.clip((val_norm - 0.25) * 1.6, 0.0, 1.0)
        hsv_boost = hsv.copy()
        hsv_boost[:, :, 1] = np.clip(hsv_boost[:, :, 1] * 1.35, 0, 255)
        color_boost_rgb = cv2.cvtColor(hsv_boost.astype(np.uint8), cv2.COLOR_HSV2RGB).astype(np.float32)
        color_inked = color_boost_rgb * (ink_boost[:, :, None] ** 0.80)

        shonen_np = (
            manga_bw_rgb.astype(np.float32) * (1.0 - pop_mask[:, :, None]) +
            color_inked * pop_mask[:, :, None]
        )
        return Image.fromarray(np.clip(shonen_np, 0, 255).astype(np.uint8)).convert("RGBA")


def _decorate_editorial_border_and_speedlines(
    panel_rgba: Image.Image,
    feeling: Optional[str] = None,
    style_variant: str = "hq_shonen_panel"
) -> Image.Image:
    """
    Adiciona acabamento gráfico de Revista de Mangá / Graphic Novel:
      - Linhas de velocidade (Speedlines) sutis nas bordas/cantos do quadro
      - Moldura Tripla Editorial (Borda externa vibrante / Borda branca limpa / Borda interna de nanquim 10px)
      - Cantos chanfrados ou selos técnicos discretos
    """
    pw, ph = panel_rgba.size
    out = panel_rgba.copy().convert("RGBA")
    accent_rgb, secondary_rgb = _get_feeling_accent_palette(feeling)

    # 1. Acabamento Editorial de Bordas / Atmosfera Interna (Adaptado ao Tema do Quadro)
    sl_layer = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    sl_draw = ImageDraw.Draw(sl_layer)
    cx, cy = pw // 2, ph // 2
    max_r = math.hypot(cx, cy)
    inner_clear_r = min(pw, ph) * 0.43
    rng = random.Random(42 + pw + ph)

    if style_variant == "hq_rain_melancholy":
        # Chuva Fina Cinematográfica de Mangá Dramático nas margens (preservando o rosto central limpo)
        for _ in range(54):
            rx = rng.randint(18, pw - 18)
            ry = rng.randint(18, ph - 90)
            if math.hypot(rx - cx, ry - cy) < inner_clear_r * 0.82:
                continue
            r_len = rng.randint(45, 95)
            sl_draw.line(
                [(rx, ry), (rx - int(r_len * 0.16), ry + r_len)],
                fill=(186, 230, 253, rng.randint(45, 85)),
                width=1
            )
    elif style_variant == "hq_soft_memory":
        # Linhas Verticais Sutis de Memória/Emoção (Tatesen) no topo e base do quadro
        for tx in range(24, pw - 24, 14):
            t_len = rng.randint(28, 68)
            sl_draw.line([(tx, 16), (tx, 16 + t_len)], fill=(226, 232, 240, 50), width=1)
            sl_draw.line([(tx, ph - 16 - t_len), (tx, ph - 16)], fill=(226, 232, 240, 50), width=1)
    elif style_variant == "hq_romance_glow":
        # Brilhos Shoujo / Webtoon Romance nos cantos + feixes de luz delicados
        num_rays = 48
        for idx in range(num_rays):
            ang = (2.0 * math.pi * idx) / num_rays + rng.uniform(-0.015, 0.015)
            r_start = inner_clear_r * rng.uniform(0.96, 1.18)
            x1 = cx + int(r_start * math.cos(ang))
            y1 = cy + int(r_start * math.sin(ang))
            x2 = cx + int(max_r * 1.15 * math.cos(ang))
            y2 = cy + int(max_r * 1.15 * math.sin(ang))
            sl_draw.line([(x1, y1), (x2, y2)], fill=(255, 228, 236, 48 if idx % 2 == 0 else 28), width=1)
        for sx, sy in [(48, 48), (pw - 48, 48), (48, ph - 48), (pw - 48, ph - 48)]:
            sl_draw.line([(sx - 10, sy), (sx + 10, sy)], fill=(255, 255, 255, 180), width=2)
            sl_draw.line([(sx, sy - 10), (sx, sy + 10)], fill=(255, 255, 255, 180), width=2)
    else:
        num_rays = 72 if style_variant != "hq_eyes_strip" else 48
        for idx in range(num_rays):
            ang = (2.0 * math.pi * idx) / num_rays + rng.uniform(-0.015, 0.015)
            r_start = inner_clear_r * rng.uniform(0.92, 1.18)
            x1 = cx + int(r_start * math.cos(ang))
            y1 = cy + int(r_start * math.sin(ang))
            x2 = cx + int(max_r * 1.15 * math.cos(ang))
            y2 = cy + int(max_r * 1.15 * math.sin(ang))
            if style_variant in ("hq_color_webtoon", "hq_noir_crimson", "hq_pop_halftone"):
                col = (*accent_rgb, 65 if idx % 3 == 0 else 35)
            else:
                col = (10, 12, 16, 85) if idx % 2 == 0 else (255, 255, 255, 55)
            sl_draw.line([(x1, y1), (x2, y2)], fill=col, width=2 if idx % 3 == 0 else 1)

    out = Image.alpha_composite(out, sl_layer)

    # 2. Moldura Tripla Editorial HQ (100% Fiel à Arquitetura de Quadro)
    b_draw = ImageDraw.Draw(out)
    if style_variant in ("hq_rain_melancholy", "hq_soft_memory"):
        outer_col = (203, 213, 225, 255)
        mid_col = (12, 18, 28, 255)
        inner_col = (186, 230, 253, 210)
    elif style_variant == "hq_romance_glow":
        outer_col = (251, 207, 232, 255)
        mid_col = (35, 12, 24, 255)
        inner_col = (254, 243, 199, 225)
    elif style_variant in ("hq_color_webtoon", "hq_noir_crimson", "hq_pop_halftone", "hq_golden_eclipse"):
        outer_col = (*accent_rgb, 255)
        mid_col = (10, 12, 18, 255)
        inner_col = (*secondary_rgb, 220)
    else:
        outer_col = (255, 255, 255, 255)
        mid_col = (10, 12, 18, 255)
        inner_col = (255, 255, 255, 210)

    b_draw.rectangle([0, 0, pw - 1, ph - 1], outline=outer_col, width=5)
    b_draw.rectangle([5, 5, pw - 6, ph - 6], outline=mid_col, width=9)
    b_draw.rectangle([14, 14, pw - 15, ph - 15], outline=inner_col, width=2)

    return out


def generate_editorial_hq_panel_clip(
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
    text_style: Optional[str] = None,
    panel_style: str = "hq_shonen_panel"
) -> Optional[str]:
    """
    Motor Editorial HQ de Nova Geração (100% Quadros de Mangá/Webtoon — ZERO Recorte de Contorno):
    Suporta 6 arquiteturas visuais distintas de nível revista/webtoon:
      1. 'hq_shonen_panel': Quadro Clássico Shonen Jump (Nanquim P&B + Retícula 45° + Selective Color Pop + Moldura Tripla).
      2. 'hq_color_webtoon': Quadro Colorido Solo Leveling / Manhwa Deluxe (Cel-Shading + Lineart Nanquim + Borda Neon).
      3. 'hq_diagonal_impact': Quadro de Ação Inclinado em Paralelogramo (-3.2°) com Corte de Katana na Diagonal.
      4. 'hq_eyes_strip': Faixa Horizontal Cinematográfica Close-Up nos Olhos/Expressão (Smart Face-Centered Strip).
      5. 'hq_dual_split': Página Dupla de Mangá (2-Panel Split Page: Setup P&B no topo + Clímax Colorido na base + Calha Diagonal).
      6. 'hq_noir_crimson': Quadro Seinen Dark / Sin City Noir (Contraste Abissal + Duotone Carmesim/Violeta/Ouro).
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

        if best_frame_pil is not None and panel_style not in ("hq_dual_split", "hq_triple_cascade"):
            climax_pil = best_frame_pil
            setup_pil = best_frame_pil
            face_box = None
        else:
            qg = find_best_manga_take_with_quality_gate(video_path, frame_t, start_sec, end_sec)
            climax_pil = best_frame_pil if best_frame_pil is not None else qg.get("raw_pil")
            if climax_pil is None:
                return None
            setup_pil = qg.get("setup_pil") or climax_pil
            face_box = qg.get("face_box")

        disp_line1 = (text_line1 or "").strip().upper()
        disp_line2 = (text_line2 or "").strip().upper()
        full_text = f"{disp_line1} {disp_line2}".strip()
        eff_feeling = text_style if text_style else detect_manga_feeling(full_text)
        accent_rgb, secondary_rgb = _get_feeling_accent_palette(eff_feeling)

        is_sad_mood = (
            panel_style in ("hq_rain_melancholy", "hq_soft_memory")
            or eff_feeling in (
                "emotional_tear", "dramatic_silence", "silver_grief",
                "midnight_sorrow", "fading_echo", "broken_promise", "cold_solitude"
            )
        )
        is_romance_mood = (
            panel_style == "hq_romance_glow"
            or eff_feeling in (
                "sakura_bloom", "golden_romance", "heart_pulse",
                "velvet_kiss", "starlight_crush", "sweet_blush", "eternal_vow"
            )
        )
        is_gentle_mood = is_sad_mood or is_romance_mood

        # Fundo Cinematográfico Full-Bleed 1080x1920 100% Uniforme (ZERO elipses ou formas redondas atrás do quadro!)
        bg_full_blur = create_full_bleed_blurred_background(climax_pil, width=W, height=H, blur_radius=32)
        ambient_tint = Image.new("RGBA", (W, H), (8, 10, 16, 130))
        bg_comp = Image.alpha_composite(bg_full_blur, ambient_tint)

        # Construção do Quadro Editorial de acordo com o `panel_style`
        if panel_style == "hq_eyes_strip":
            panel_w, panel_h = 1000, 520
            eyes_surf_style = (
                "hq_rain_melancholy" if is_sad_mood
                else ("hq_romance_glow" if is_romance_mood else "hq_shonen_panel")
            )
            art_rgba = _render_editorial_art_surface(
                climax_pil, panel_w, panel_h,
                panel_style=eyes_surf_style, feeling=eff_feeling,
                face_box=face_box, zoom_bias=1.35
            )
            panel_master = _decorate_editorial_border_and_speedlines(art_rgba, feeling=eff_feeling, style_variant="hq_eyes_strip")

        elif panel_style == "hq_dual_split":
            panel_w, panel_h = 980, 900
            top_h = 445
            bot_h = panel_h - top_h
            top_surf_style = "hq_soft_memory" if is_gentle_mood else "hq_shonen_panel"
            bot_surf_style = (
                "hq_rain_melancholy" if is_sad_mood
                else ("hq_romance_glow" if is_romance_mood else "hq_color_webtoon")
            )
            # Painel Superior: Setup
            top_art = _render_editorial_art_surface(
                setup_pil, panel_w, top_h + 40,
                panel_style=top_surf_style, feeling=eff_feeling,
                face_box=None, zoom_bias=1.0
            )
            # Painel Inferior: Clímax em Close-Up
            bot_art = _render_editorial_art_surface(
                climax_pil, panel_w, bot_h + 40,
                panel_style=bot_surf_style, feeling=eff_feeling,
                face_box=face_box, zoom_bias=1.22
            )
            page_canvas = Image.new("RGBA", (panel_w, panel_h), (12, 12, 16, 255))
            page_canvas.paste(top_art.crop((0, 0, panel_w, top_h + 25)), (0, 0))

            # Máscara diagonal para o painel inferior (calha inclinada autêntica de mangá)
            slant_dy = 34
            bot_mask = Image.new("L", (panel_w, panel_h), 0)
            ImageDraw.Draw(bot_mask).polygon([
                (0, top_h + slant_dy),
                (panel_w, top_h - slant_dy),
                (panel_w, panel_h),
                (0, panel_h)
            ], fill=255)
            bot_placed = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
            bot_placed.paste(bot_art.crop((0, 0, panel_w, bot_h + 40)), (0, top_h - 40))
            page_canvas = Image.composite(bot_placed, page_canvas, bot_mask)

            # Calha Diagonal (Gutter) Preta + Branca + Filete de Cor
            g_draw = ImageDraw.Draw(page_canvas)
            g_draw.line([(0, top_h + slant_dy), (panel_w, top_h - slant_dy)], fill=(10, 12, 16, 255), width=22)
            g_draw.line([(0, top_h + slant_dy), (panel_w, top_h - slant_dy)], fill=(255, 255, 255, 255), width=8)
            g_draw.line([(0, top_h + slant_dy), (panel_w, top_h - slant_dy)], fill=(*accent_rgb, 255), width=3)

            panel_master = _decorate_editorial_border_and_speedlines(page_canvas, feeling=eff_feeling, style_variant="hq_dual_split")

        elif panel_style == "hq_triple_cascade":
            # Página Editorial Tripla (3-Panel Escalation Strip: Setup -> Zoom -> Clímax)
            panel_w, panel_h = 980, 920
            h1, h2 = 240, 260
            h3 = panel_h - h1 - h2
            top_surf_style = "hq_soft_memory" if is_gentle_mood else "hq_shonen_panel"
            mid_surf_style = (
                "hq_rain_melancholy" if is_sad_mood
                else ("hq_romance_glow" if is_romance_mood else "hq_shonen_panel")
            )
            bot_surf_style = (
                "hq_rain_melancholy" if is_sad_mood
                else ("hq_romance_glow" if is_romance_mood else "hq_color_webtoon")
            )
            art1 = _render_editorial_art_surface(setup_pil, panel_w, h1, panel_style=top_surf_style, feeling=eff_feeling, face_box=None, zoom_bias=1.0)
            art2 = _render_editorial_art_surface(climax_pil, panel_w, h2, panel_style=mid_surf_style, feeling=eff_feeling, face_box=face_box, zoom_bias=1.16)
            art3 = _render_editorial_art_surface(climax_pil, panel_w, h3, panel_style=bot_surf_style, feeling=eff_feeling, face_box=face_box, zoom_bias=1.30)

            page_canvas = Image.new("RGBA", (panel_w, panel_h), (12, 12, 16, 255))
            page_canvas.paste(art1, (0, 0))
            page_canvas.paste(art2, (0, h1))
            page_canvas.paste(art3, (0, h1 + h2))

            g_draw = ImageDraw.Draw(page_canvas)
            for gy in (h1, h1 + h2):
                g_draw.line([(0, gy), (panel_w, gy)], fill=(10, 12, 16, 255), width=18)
                g_draw.line([(0, gy), (panel_w, gy)], fill=(255, 255, 255, 255), width=6)
                g_draw.line([(0, gy), (panel_w, gy)], fill=(*accent_rgb, 255), width=2)

            panel_master = _decorate_editorial_border_and_speedlines(page_canvas, feeling=eff_feeling, style_variant="hq_dual_split")

        elif panel_style == "hq_diagonal_impact":
            base_pw, base_ph = 940, 820
            art_rgba = _render_editorial_art_surface(
                climax_pil, base_pw, base_ph,
                panel_style="hq_color_webtoon" if eff_feeling in ("fire", "electric", "golden_god", "blade_stream") else "hq_shonen_panel",
                feeling=eff_feeling, face_box=face_box, zoom_bias=1.10
            )
            framed = _decorate_editorial_border_and_speedlines(art_rgba, feeling=eff_feeling, style_variant="hq_color_webtoon")
            panel_master = framed.rotate(-3.0, resample=Image.Resampling.BICUBIC, expand=True)
            panel_w, panel_h = panel_master.size

        else:
            panel_w, panel_h = 980, 860
            art_rgba = _render_editorial_art_surface(
                climax_pil, panel_w, panel_h,
                panel_style=panel_style, feeling=eff_feeling,
                face_box=face_box, zoom_bias=1.06
            )
            panel_master = _decorate_editorial_border_and_speedlines(art_rgba, feeling=eff_feeling, style_variant=panel_style)

        # Sombra 3D e Aura Sutil ao redor do Quadro Editorial
        pad_sh = 44
        shadow_base = Image.new("RGBA", (panel_w + pad_sh * 2, panel_h + pad_sh * 2), (0, 0, 0, 0))
        sh_draw = ImageDraw.Draw(shadow_base)
        sh_draw.rectangle([pad_sh - 4, pad_sh - 4, pad_sh + panel_w + 4, pad_sh + panel_h + 4], fill=(*accent_rgb, 75))
        sh_draw.rectangle([pad_sh + 6, pad_sh + 10, pad_sh + panel_w + 6, pad_sh + panel_h + 10], fill=(0, 0, 0, 215))
        shadow_pil = shadow_base.filter(ImageFilter.GaussianBlur(radius=18))

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(output_clip_path, fourcc, fps, (W, H))

        panel_base_x = (W - panel_w) // 2
        panel_base_y = box_y1 + (box_h - panel_h) // 2

        # Ajusta automaticamente pos_layout para não cobrir o rosto nem a calha central
        eff_pos_layout = pos_layout
        if eff_pos_layout == "auto":
            if panel_style == "hq_eyes_strip":
                eff_pos_layout = "bottom"
            elif panel_style == "hq_dual_split":
                eff_pos_layout = "bottom"
            elif face_box and face_box[1] < climax_pil.height * 0.45:
                eff_pos_layout = "bottom"
            else:
                eff_pos_layout = "top"

        # Pré-carrega tensores na GPU (Torch CUDA) para pipeline 100% GPU (Zero cópias 1080x1920 na CPU!)
        use_gpu_compositor = False
        bg_rgba_t = None
        sh_nchw_t = None
        pm_nchw_t = None
        ui_rgba_t = None
        ui_alpha_t = None
        if _TORCH_CUDA_AVAILABLE and _CUDA_DEVICE is not None:
            try:
                import torch
                import torch.nn.functional as F_nn
                with torch.no_grad():
                    bg_rgba_t = torch.from_numpy(np.array(bg_comp, dtype=np.float32)).to(_CUDA_DEVICE)
                    sh_nchw_t = torch.from_numpy(np.array(shadow_pil, dtype=np.float32)).permute(2, 0, 1).unsqueeze(0).to(_CUDA_DEVICE)
                    pm_nchw_t = torch.from_numpy(np.array(panel_master, dtype=np.float32)).permute(2, 0, 1).unsqueeze(0).to(_CUDA_DEVICE)
                    if static_ui_img is not None:
                        ui_np = np.array(static_ui_img.convert("RGBA"), dtype=np.float32)
                        ui_rgba_t = torch.from_numpy(ui_np[:, :, :3]).to(_CUDA_DEVICE)
                        ui_alpha_t = (torch.from_numpy(ui_np[:, :, 3:4]).to(_CUDA_DEVICE)) * (1.0 / 255.0)
                    use_gpu_compositor = True
            except Exception:
                use_gpu_compositor = False

        def _gpu_paste_rgba(dst_hw4, src_hw4, px: int, py: int):
            sh, sw = src_hw4.shape[0], src_hw4.shape[1]
            dh, dw = dst_hw4.shape[0], dst_hw4.shape[1]
            dx1 = max(0, px)
            dy1 = max(0, py)
            dx2 = min(dw, px + sw)
            dy2 = min(dh, py + sh)
            if dx2 <= dx1 or dy2 <= dy1:
                return
            sx1 = dx1 - px
            sy1 = dy1 - py
            sx2 = sx1 + (dx2 - dx1)
            sy2 = sy1 + (dy2 - dy1)
            src_sub = src_hw4[sy1:sy2, sx1:sx2]
            dst_sub = dst_hw4[dy1:dy2, dx1:dx2]
            alpha = src_sub[:, :, 3:4] * (1.0 / 255.0)
            dst_sub[:, :, :3] = dst_sub[:, :, :3] * (1.0 - alpha) + src_sub[:, :, :3] * alpha
            dst_sub[:, :, 3:4] = 255.0

        # Cache de quadros tipográficos para reutilizar quando a quantização temporal coincide
        typo_gpu_cache = {}
        empty_typo_base = Image.new("RGBA", (W, H), (0, 0, 0, 0))

        for i in range(total_frames):
            t_rel = i / fps

            # Animação de Entrada do Quadro (Suave em temas tristes/românticos, Snap em ação)
            entry_pop = 1.0
            if is_gentle_mood:
                if t_rel < 0.20:
                    p_in = t_rel / 0.20
                    entry_pop = 0.97 + 0.03 * math.sin(p_in * math.pi * 0.5)
                p_zoom = entry_pop * (1.0 + 0.045 * (t_rel / dur))
            else:
                if t_rel < 0.14:
                    p_in = t_rel / 0.14
                    entry_pop = 0.94 + 0.06 * math.sin(p_in * math.pi * 0.5)
                p_zoom = entry_pop * (1.0 + 0.07 * (t_rel / dur))

            cur_pw = int(panel_w * p_zoom)
            cur_ph = int(panel_h * p_zoom)

            cur_shw = int((panel_w + pad_sh * 2) * p_zoom)
            cur_shh = int((panel_h + pad_sh * 2) * p_zoom)
            cur_shx = (panel_base_x - int(pad_sh * p_zoom)) - (cur_pw - panel_w) // 2
            cur_shy = (panel_base_y - int(pad_sh * p_zoom)) - (cur_ph - panel_h) // 2 + 6

            cur_px = panel_base_x - (cur_pw - panel_w) // 2
            cur_py = panel_base_y - (cur_ph - panel_h) // 2

            if use_gpu_compositor:
                with torch.no_grad():
                    frame_t_rgba = bg_rgba_t.clone()
                    sh_resized = F_nn.interpolate(sh_nchw_t, size=(cur_shh, cur_shw), mode="bilinear", align_corners=False)[0].permute(1, 2, 0)
                    _gpu_paste_rgba(frame_t_rgba, sh_resized, cur_shx, cur_shy)

                    pm_resized = F_nn.interpolate(pm_nchw_t, size=(cur_ph, cur_pw), mode="bilinear", align_corners=False)[0].permute(1, 2, 0)
                    _gpu_paste_rgba(frame_t_rgba, pm_resized, cur_px, cur_py)

                    if is_gentle_mood:
                        if t_rel < 0.14:
                            fl_a = (95.0 * (1.0 - t_rel / 0.14)) / 255.0
                            fl_col = torch.tensor([accent_rgb[0], accent_rgb[1], accent_rgb[2]], device=_CUDA_DEVICE, dtype=torch.float32)
                            frame_t_rgba[:, :, :3] = frame_t_rgba[:, :, :3] * (1.0 - fl_a) + fl_col * fl_a
                    else:
                        if t_rel < 0.09:
                            fl_a = (210.0 * (1.0 - t_rel / 0.09)) / 255.0
                            frame_t_rgba[:, :, :3] = frame_t_rgba[:, :, :3] * (1.0 - fl_a) + 255.0 * fl_a

                    # Corte de Katana Dinâmico na Entrada (composto direto na GPU)
                    if not is_gentle_mood and 0.08 <= t_rel < 0.30:
                        prog = (t_rel - 0.08) / 0.22
                        slash_ang = -4.0 if panel_style == "hq_dual_split" else (-18.0 if panel_style != "hq_diagonal_impact" else 16.0)
                        slash_img = generate_katana_slash_frame(prog, width=W, height=box_h, slash_angle_deg=slash_ang)
                        slash_t = torch.from_numpy(np.array(slash_img, dtype=np.float32)).to(_CUDA_DEVICE)
                        _gpu_paste_rgba(frame_t_rgba, slash_t, 0, box_y1)

                    # Tipografia Animada Mangá composta direto na GPU (com quantização inteligente após o pop inicial)
                    if disp_line1 or disp_line2:
                        t_key = i if t_rel < 0.28 else (8 + (i // 2))
                        t_quant = t_rel if t_rel < 0.28 else ((i // 2) * 2) / fps
                        if t_key not in typo_gpu_cache:
                            typo_canvas = render_manga_animated_typography(
                                empty_typo_base.copy(), t_quant, dur, disp_line1, disp_line2,
                                layout_mode="center", box_y1=box_y1, box_h=box_h, width=W,
                                pos_layout=eff_pos_layout, text_style=eff_feeling
                            )
                            bb_typo = typo_canvas.getbbox()
                            if bb_typo:
                                tx1, ty1, tx2, ty2 = bb_typo
                                sub_np = np.array(typo_canvas.crop((tx1, ty1, tx2, ty2)), dtype=np.float32)
                                typo_gpu_cache[t_key] = (tx1, ty1, torch.from_numpy(sub_np).to(_CUDA_DEVICE))
                            else:
                                typo_gpu_cache[t_key] = None
                        cached_typo = typo_gpu_cache.get(t_key)
                        if cached_typo is not None:
                            tx1, ty1, typo_sub_t = cached_typo
                            _gpu_paste_rgba(frame_t_rgba, typo_sub_t, tx1, ty1)

                    if ui_rgba_t is not None and ui_alpha_t is not None:
                        frame_t_rgba[:, :, :3] = frame_t_rgba[:, :, :3] * (1.0 - ui_alpha_t) + ui_rgba_t * ui_alpha_t

                    bgr = frame_t_rgba[:, :, [2, 1, 0]].clamp_(0, 255).to(torch.uint8).cpu().numpy()
                    writer.write(bgr)
                continue

            canvas = bg_comp.copy()
            cur_sh = shadow_pil.resize((cur_shw, cur_shh), Image.Resampling.BILINEAR)
            canvas.paste(cur_sh, (cur_shx, cur_shy), cur_sh)
            cur_p = panel_master.resize((cur_pw, cur_ph), Image.Resampling.BILINEAR)
            canvas.paste(cur_p, (cur_px, cur_py), cur_p)

            if is_gentle_mood:
                if t_rel < 0.14:
                    flash_alpha = int(95 * (1.0 - t_rel / 0.14))
                    flash_img = Image.new("RGBA", (W, H), (*accent_rgb, flash_alpha))
                    canvas = Image.alpha_composite(canvas, flash_img)
            else:
                if t_rel < 0.09:
                    flash_alpha = int(210 * (1.0 - t_rel / 0.09))
                    flash_img = Image.new("RGBA", (W, H), (255, 255, 255, flash_alpha))
                    canvas = Image.alpha_composite(canvas, flash_img)

            # Corte de Katana Dinâmico na Entrada (Apenas quando NÃO for cena triste/romântica)
            if not is_gentle_mood and 0.08 <= t_rel < 0.30:
                prog = (t_rel - 0.08) / 0.22
                slash_ang = -4.0 if panel_style == "hq_dual_split" else (-18.0 if panel_style != "hq_diagonal_impact" else 16.0)
                slash_img = generate_katana_slash_frame(prog, width=W, height=box_h, slash_angle_deg=slash_ang)
                slash_canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                slash_canvas.paste(slash_img, (0, box_y1), slash_img)
                canvas = Image.alpha_composite(canvas, slash_canvas)

            # Tipografia Animada Mangá de Elite
            canvas = render_manga_animated_typography(
                canvas, t_rel, dur, disp_line1, disp_line2,
                layout_mode="center", box_y1=box_y1, box_h=box_h, width=W,
                pos_layout=eff_pos_layout, text_style=eff_feeling
            )

            if static_ui_img:
                canvas = Image.alpha_composite(canvas, static_ui_img)

            bgr = cv2.cvtColor(np.array(canvas.convert("RGB")), cv2.COLOR_RGB2BGR)
            writer.write(bgr)

        writer.release()
        return output_clip_path

    except Exception as e:
        print(f"[EditorialHQPanel] Erro ({panel_style}): {e}")
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
    text_style: Optional[str] = None,
    panel_style: str = "hq_shonen_panel"
) -> Optional[str]:
    """Renderiza Quadro Editorial de Mangá/HQ (Shonen Jump / Webtoon / Split Page)."""
    return generate_editorial_hq_panel_clip(
        video_path=video_path,
        start_sec=start_sec,
        end_sec=end_sec,
        output_clip_path=output_clip_path,
        static_ui_img=static_ui_img,
        frame_t=frame_t,
        best_frame_pil=best_frame_pil,
        text_line1=text_line1,
        text_line2=text_line2,
        symbol=symbol,
        pos_layout=pos_layout,
        text_style=text_style,
        panel_style=panel_style,
    )


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
    """Redireciona antigos recortes laterais para o Quadro Diagonal de Impacto HQ (Zero recorte de silhueta)."""
    return generate_editorial_hq_panel_clip(
        video_path=video_path,
        start_sec=start_sec,
        end_sec=end_sec,
        output_clip_path=output_clip_path,
        static_ui_img=static_ui_img,
        frame_t=frame_t,
        text_line1=text_line1,
        text_line2=text_line2,
        symbol=symbol,
        pos_layout=pos_layout,
        text_style=text_style,
        panel_style="hq_diagonal_impact",
    )


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
    """Redireciona antigos recortes radiais para o Quadro Colorido Webtoon Deluxe HQ (Zero recorte de silhueta)."""
    return generate_editorial_hq_panel_clip(
        video_path=video_path,
        start_sec=start_sec,
        end_sec=end_sec,
        output_clip_path=output_clip_path,
        static_ui_img=static_ui_img,
        frame_t=frame_t,
        text_line1=text_line1,
        text_line2=text_line2,
        symbol=symbol,
        pos_layout=pos_layout,
        text_style=text_style,
        panel_style="hq_color_webtoon",
    )


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
    """Renderiza a Faixa Cinematográfica Close-Up nos Olhos/Expressão (Smart Face-Centered Strip)."""
    return generate_editorial_hq_panel_clip(
        video_path=video_path,
        start_sec=start_sec,
        end_sec=end_sec,
        output_clip_path=output_clip_path,
        static_ui_img=static_ui_img,
        frame_t=frame_t,
        text_line1=text_line1,
        text_line2=text_line2,
        symbol=symbol,
        pos_layout=pos_layout,
        text_style=text_style,
        panel_style="hq_eyes_strip",
    )


def generate_manga_event_clip(
    video_path: str,
    event_dict: Dict[str, Any],
    output_clip_path: str,
    static_ui_img: Optional[Image.Image] = None
) -> Optional[str]:
    """
    Despachante Editorial HQ de Efeitos de Mangá/Webtoon:
    Roteia dinamicamente para as 6 arquiteturas de Quadros Editoriais HQ (ZERO recorte de silhueta):
      - 'hq_shonen_panel' (ou 'scene_manga_panel'): Quadro Clássico Shonen Jump (Nanquim + Halftone + Selective Color)
      - 'hq_color_webtoon' (ou 'radial_power'): Quadro Colorido Solo Leveling / Manhwa Deluxe
      - 'hq_diagonal_impact' (ou 'lateral_sticker_punch'): Quadro de Ação Inclinado + Katana Slash
      - 'hq_eyes_strip' (ou 'manga_eyes_panel'): Faixa Close-Up nos Olhos/Rosto
      - 'hq_dual_split': Página Dupla de Mangá (Setup P&B + Clímax Colorido)
      - 'hq_noir_crimson': Quadro Seinen Dark / Sin City Noir Duotone
    """
    etype = event_dict.get("event_type", "hq_shonen_panel")
    panel_style = event_dict.get("panel_style") or etype
    st = float(event_dict["start"])
    et = float(event_dict["end"])
    ft = float(event_dict.get("frame_t", st + 0.35))
    l1 = event_dict.get("line1")
    l2 = event_dict.get("line2")
    sym = event_dict.get("symbol", "!")

    pos_layout = event_dict.get("pos_layout", "auto")
    text_style = event_dict.get("text_style", None)

    style_map = {
        "hq_shonen_panel": "hq_shonen_panel",
        "scene_manga_panel": "hq_shonen_panel",
        "hq_color_webtoon": "hq_color_webtoon",
        "radial_power": "hq_color_webtoon",
        "luffy_manga_cutout": "hq_color_webtoon",
        "haki_power": "hq_color_webtoon",
        "hq_diagonal_impact": "hq_diagonal_impact",
        "lateral_sticker_punch": "hq_diagonal_impact",
        "hq_eyes_strip": "hq_eyes_strip",
        "manga_eyes_panel": "hq_eyes_strip",
        "hq_dual_split": "hq_dual_split",
        "hq_noir_crimson": "hq_noir_crimson",
        "hq_rain_melancholy": "hq_rain_melancholy",
        "hq_soft_memory": "hq_soft_memory",
        "hq_romance_glow": "hq_romance_glow",
        "hq_pop_halftone": "hq_pop_halftone",
        "hq_triple_cascade": "hq_triple_cascade",
        "hq_golden_eclipse": "hq_golden_eclipse",
    }
    resolved_panel_style = style_map.get(panel_style, "hq_shonen_panel")

    res = None
    try:
        res = generate_editorial_hq_panel_clip(
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
            text_style=text_style,
            panel_style=resolved_panel_style,
        )
    except Exception as e:
        print(f"[generate_manga_event_clip] Erro no gerador editorial ({resolved_panel_style}): {e}")
        res = None

    if not res or not os.path.exists(res):
        print(f"[generate_manga_event_clip] Acionando fallback seguro hq_shonen_panel ({st:.1f}s-{et:.1f}s)...")
        try:
            res = generate_editorial_hq_panel_clip(
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
                text_style=text_style,
                panel_style="hq_shonen_panel",
            )
        except Exception as fe:
            print(f"[generate_manga_event_clip] Erro no fallback de mangá: {fe}")
            res = None

    return res


if __name__ == "__main__":
    print("manga_fx_engine.py carregado com sucesso.")

