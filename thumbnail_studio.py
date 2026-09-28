"""
thumbnail_studio.py - Motor de Criação e Renderização de Thumbnails 9:16 (1080x1920)
Otimizado para YouTube Shorts e Instagram Reels:
- Enquadramento inteligente no formato estrito 9:16 (1080x1920)
- Foco customizável no personagem (Centro, Esquerda, Direita, Pan Manual ou Fundo Desfocado)
- Tipografia viral de alto impacto (Títulos CTR, Ganchos, Safe Zones)
"""

import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image, ImageDraw, ImageFont, ImageFilter


def extract_raw_frame(
    video_path: str,
    timestamp_sec: float = 1.5,
    output_path: Optional[str] = None,
    ffmpeg_bin: str = "ffmpeg"
) -> Optional[str]:
    """Extrai frame em resolução máxima do vídeo no segundo exato."""
    if not video_path or not os.path.exists(video_path):
        return None
    try:
        p = Path(video_path)
        if not output_path:
            output_path = str(p.parent / f"{p.stem}_raw_frame_{int(timestamp_sec*100):04d}ms.jpg")

        cmd = [
            ffmpeg_bin, "-y",
            "-ss", f"{timestamp_sec:.2f}",
            "-i", str(video_path),
            "-vframes", "1",
            "-q:v", "1",
            str(output_path)
        ]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path

        # Fallback para 0.5s se ultrapassar o fim do corte
        if timestamp_sec > 0.8:
            cmd[2] = "0.50"
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return output_path
    except Exception:
        pass
    return None


def get_available_font(preferred_size: int = 70) -> ImageFont.FreeTypeFont:
    """Busca fontes de alto impacto visual no sistema (Impact, Arial Black, Arial Bold)."""
    font_candidates = [
        "C:/Windows/Fonts/impact.ttf",
        "C:/Windows/Fonts/ariblk.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Impact.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
    ]
    for fp in font_candidates:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, preferred_size)
            except Exception:
                continue
    try:
        return ImageFont.truetype("arial.ttf", preferred_size)
    except Exception:
        return ImageFont.load_default()


def render_shorts_thumbnail(
    raw_frame_path: str,
    output_path: str,
    crop_mode: str = "center",   # "center", "left", "right", "pan", "blur_canvas"
    pan_x: float = 0.5,         # 0.0 (esquerda total) a 1.0 (direita total)
    overlay_text: str = "",
    text_position: str = "top",  # "top", "center"
    text_style: str = "yellow"   # "yellow", "white", "badge"
) -> str:
    """
    Renderiza uma capa vertical rigorosamente em 9:16 (1080x1920) para YouTube Shorts / Reels.
    
    crop_mode:
      - 'center': centraliza o corte no meio da tela
      - 'left': posiciona o corte na lateral esquerda (ideal para personagem na esquerda)
      - 'right': posiciona o corte na lateral direita (ideal para personagem na direita)
      - 'pan': usa pan_x (0.0 a 1.0) para enquadrar qualquer ponto do vídeo
      - 'blur_canvas': cria canvas 1080x1920 com fundo desfocado e vídeo nítido no centro (ótimo para animes)
    """
    if not os.path.exists(raw_frame_path):
        raise FileNotFoundError(f"Frame não encontrado: {raw_frame_path}")

    img = Image.open(raw_frame_path).convert("RGB")
    src_w, src_h = img.size
    target_w, target_h = 1080, 1920

    # 1. ENQUADRAMENTO E CORTE PARA 9:16 (1080x1920)
    if crop_mode == "blur_canvas":
        # Fundo: Imagem ampliada e com desfoque gaussiano cinematográfico
        bg_scale = max(target_w / src_w, target_h / src_h)
        bg_w = int(src_w * bg_scale)
        bg_h = int(src_h * bg_scale)
        bg = img.resize((bg_w, bg_h), Image.Resampling.LANCZOS)
        # Corta centro do fundo
        left = max(0, (bg_w - target_w) // 2)
        top = max(0, (bg_h - target_h) // 2)
        bg = bg.crop((left, top, left + target_w, top + target_h))
        bg = bg.filter(ImageFilter.GaussianBlur(radius=28))

        # Vinheta / Escurecimento suave no fundo para dar destaque
        dim = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 85))
        bg.paste(dim, (0, 0), dim)

        # Vídeo nítido no centro
        fg_scale = target_w / src_w
        fg_w = target_w
        fg_h = int(src_h * fg_scale)
        fg = img.resize((fg_w, fg_h), Image.Resampling.LANCZOS)
        fg_y = max(0, (target_h - fg_h) // 2)
        bg.paste(fg, (0, fg_y))
        final_img = bg
    else:
        # Modo Corte / Crop
        scale = max(target_w / src_w, target_h / src_h)
        scaled_w = int(src_w * scale)
        scaled_h = int(src_h * scale)
        scaled = img.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)

        # Cálculo do X de corte
        diff_x = scaled_w - target_w
        if diff_x > 0:
            if crop_mode == "left":
                crop_x = 0
            elif crop_mode == "right":
                crop_x = diff_x
            elif crop_mode == "center":
                crop_x = diff_x // 2
            else:  # pan manual
                clamped_pan = max(0.0, min(1.0, float(pan_x)))
                crop_x = int(diff_x * clamped_pan)
        else:
            crop_x = 0

        diff_y = scaled_h - target_h
        crop_y = max(0, diff_y // 2) if diff_y > 0 else 0

        final_img = scaled.crop((crop_x, crop_y, crop_x + target_w, crop_y + target_h))

    # 2. OVERLAY DE TEXTO DE ALTO CTR
    clean_text = (overlay_text or "").strip()
    if clean_text:
        # Formata texto em caixa alta e remove aspas desnecessárias
        display_text = clean_text.strip('"\'').upper()
        draw = ImageDraw.Draw(final_img)

        # Ajuste dinâmico de tamanho da fonte
        if len(display_text) > 60:
            base_size = 56
        elif len(display_text) > 35:
            base_size = 66
        else:
            base_size = 78

        font = get_available_font(base_size)

        # Word wrap para caber na largura máxima de 920px (80px de margem lateral)
        max_line_width = 920
        words = display_text.split()
        lines = []
        cur_line = []

        for w in words:
            test_line = " ".join(cur_line + [w])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            line_w = bbox[2] - bbox[0]
            if line_w <= max_line_width:
                cur_line.append(w)
            else:
                if cur_line:
                    lines.append(" ".join(cur_line))
                    cur_line = [w]
                else:
                    lines.append(w)
        if cur_line:
            lines.append(" ".join(cur_line))

        # Alturas das linhas
        line_heights = []
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            line_heights.append(bbox[3] - bbox[1] + 18)
        total_text_h = sum(line_heights)

        # Safe Zone no Shorts:
        # 'top': ~260px (visível sem ser cortado pelo topo do app nem botões)
        # 'center': centro vertical
        if text_position == "center":
            start_y = max(100, (target_h - total_text_h) // 2)
        else:
            start_y = 260

        # Renderização com contorno e sombras de alto impacto
        curr_y = start_y
        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            lw = bbox[2] - bbox[0]
            lh = bbox[3] - bbox[1]
            lx = (target_w - lw) // 2

            if text_style == "badge":
                # Faixa Vermelha (#DC2626) com texto branco
                pad_x, pad_y = 22, 10
                badge_box = [lx - pad_x, curr_y - pad_y, lx + lw + pad_x, curr_y + lh + pad_y]
                draw.rounded_rectangle(badge_box, radius=14, fill="#dc2626")
                draw.text((lx, curr_y), line, font=font, fill="#ffffff", stroke_width=4, stroke_fill="#000000")
            elif text_style == "white":
                # Texto Branco com contorno preto grosso e sombra
                draw.text((lx + 5, curr_y + 5), line, font=font, fill="#000000")
                draw.text((lx, curr_y), line, font=font, fill="#ffffff", stroke_width=7, stroke_fill="#000000")
            else:
                # Padrão Shorts Viral: Amarelo Intenso (#FFE500) com contorno preto espesso e sombra
                draw.text((lx + 5, curr_y + 5), line, font=font, fill="#000000")
                draw.text((lx, curr_y), line, font=font, fill="#ffe500", stroke_width=7, stroke_fill="#000000")

            curr_y += line_heights[i]

    # Garante diretório pai
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    final_img.save(output_path, "JPEG", quality=95)
    return output_path


def generate_shorts_thumbnail_pipeline(
    video_path: str,
    output_path: Optional[str] = None,
    timestamp_sec: float = 1.5,
    crop_mode: str = "center",
    pan_x: float = 0.5,
    overlay_text: str = "",
    text_position: str = "top",
    text_style: str = "yellow",
    ffmpeg_bin: str = "ffmpeg"
) -> Optional[str]:
    """Pipeline completo: extrai o frame bruto e gera a capa 1080x1920 estilizada."""
    if not video_path or not os.path.exists(video_path):
        return None

    p = Path(video_path)
    if not output_path:
        output_path = str(p.parent / f"{p.stem}_capa_shorts_1080x1920.jpg")

    # Extrai frame temporário
    temp_raw = str(p.parent / f"_temp_raw_frame_{p.stem}.jpg")
    raw = extract_raw_frame(video_path, timestamp_sec=timestamp_sec, output_path=temp_raw, ffmpeg_bin=ffmpeg_bin)
    if not raw or not os.path.exists(raw):
        return None

    try:
        res = render_shorts_thumbnail(
            raw_frame_path=raw,
            output_path=output_path,
            crop_mode=crop_mode,
            pan_x=pan_x,
            overlay_text=overlay_text,
            text_position=text_position,
            text_style=text_style
        )
        return res
    finally:
        if os.path.exists(temp_raw):
            try:
                os.remove(temp_raw)
            except Exception:
                pass
