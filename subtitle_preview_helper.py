"""
subtitle_preview_helper.py - Gerador de Pré-Visualização Visual de Legendas do Urahara Studio.
Renderiza simulações em tempo real de alta fidelidade para todos os estilos de legendas.
"""

from typing import Tuple, Dict, Any, Optional
from PIL import Image, ImageDraw, ImageFont
import customtkinter as ctk

STYLE_METADATA = {
    "smart_situational": {
        "title": "Inteligente Situacional (CapCut IA)",
        "badge": "IA ADAPTATIVA",
        "tagline": "Detecta o contexto emocional da fala e alterna cores (Amarelo, Ciano, Verde e Branco)",
        "words": [("ISSO", "#38bdf8", "#000000"), ("É", "#ffffff", "#000000"), ("SURREAL!", "#fde047", "#000000")],
        "glow": None
    },
    "cyberpunk_neon": {
        "title": "Cyberpunk Neon Glow (Novo)",
        "badge": "NEON GLOW",
        "tagline": "Núcleo Ciano brilhante envolto por halo e contorno Magenta vibrante",
        "words": [("NIGHT", "#00ffff", "#ea00ff"), ("CITY", "#00ffff", "#ea00ff"), ("RUNNER", "#00ffff", "#ea00ff")],
        "glow": "#ea00ff"
    },
    "manga_3d": {
        "title": "Manga 3D Impact (Novo)",
        "badge": "SHONEN 3D",
        "tagline": "Estilo Mangá com contorno espesso e projeção de sombra tridimensional",
        "words": [("PODER", "#ffffff", "#000000"), ("MÁXIMO!", "#ffffff", "#000000")],
        "glow": None,
        "is_3d": True
    },
    "shonen_gold": {
        "title": "Shonen Aura Gold (Novo)",
        "badge": "AURA GOLD",
        "tagline": "Dourado cintilante flamejante com halo quente de energia espiritual",
        "words": [("SUPER", "#ffe840", "#ff6600"), ("SAIYAJIN!", "#ffe840", "#ff6600")],
        "glow": "#ff8800"
    },
    "dark_synthwave": {
        "title": "Dark Synthwave (Novo)",
        "badge": "RETRO WAVE",
        "tagline": "Roxo elétrico estilo anos 80 com contorno amarelo retro-futurista",
        "words": [("SYNTH", "#ff40a8", "#ffff00"), ("WAVE", "#ff40a8", "#ffff00")],
        "glow": "#ffff00"
    },
    "diamond_ice": {
        "title": "Diamante Ice (Novo)",
        "badge": "ICE DIAMOND",
        "tagline": "Branco cristalino puro com borda e sombra azul gelo neon",
        "words": [("DIAMANTE", "#ffffff", "#00f0ff"), ("ICE", "#ffffff", "#00f0ff")],
        "glow": "#00f0ff"
    },
    "word_karaoke": {
        "title": "Karaoke Ativo (Palavra Acende)",
        "badge": "SINCRONIA TOTAL",
        "tagline": "A palavra atual se acende em destaque no segundo exato em que o dublador fala",
        "words": [("VOCÊ", "#94a3b8", "#000000"), ("[ESTÁ]", "#fde047", "#000000"), ("PRONTO?", "#94a3b8", "#000000")],
        "glow": "#facc15"
    },
    "word_by_word_contextual": {
        "title": "Palavra por Palavra - Contextual Pro (IA & Emoção)",
        "badge": "CONTEXTUAL PRO",
        "tagline": "Altera ênfase, tamanho e cor com precisão cinematográfica conforme a emoção da palavra",
        "words": [("PODER", "#ff3333", "#000000"), ("LENDÁRIO!", "#ffd515", "#000000")],
        "glow": "#ff3333"
    },
    "word_by_word_clean": {
        "title": "Palavra por Palavra - Branco Minimalista (Viral Clean)",
        "badge": "MINIMAL PRO",
        "tagline": "Branco cinematográfico com pop dinâmico suave de alta retenção (Sem poluição)",
        "words": [("FOCO", "#ffffff", "#000000"), ("TOTAL!", "#ffffff", "#000000")],
        "glow": None
    },
    "word_by_word_gold": {
        "title": "Palavra por Palavra - Ouro Nobre & Branco",
        "badge": "OURO NOBRE",
        "tagline": "Branco cinematográfico de elite com termos de glória e destaque em ouro imperial",
        "words": [("MOMENTO", "#ffffff", "#000000"), ("ÉPICO!", "#ffd515", "#000000")],
        "glow": "#ffd515"
    },
    "word_by_word_cyber": {
        "title": "Palavra por Palavra - Ciano Neon & Branco",
        "badge": "CYBER CIANO",
        "tagline": "Branco cristalino de alta nitidez com realces dinâmicos em ciano neon elétrico",
        "words": [("VELOCIDADE", "#ffffff", "#000000"), ("MÁXIMA!", "#00ffff", "#000000")],
        "glow": "#00ffff"
    },
    "word_by_word": {
        "title": "Palavra por Palavra - Colorido Clássico (TikTok)",
        "badge": "COLORIDO RETRÔ",
        "tagline": "Ciclo multicolorido tradicional de alta velocidade (Amarelo, Ciano, Verde e Coral)",
        "words": [("PALAVRA", "#fde047", "#000000"), ("COLORIDA!", "#38bdf8", "#000000")],
        "glow": None
    },
    "white_keyword_highlight": {
        "title": "Branco com Destaque Colorido",
        "badge": "DESTAQUE PRO",
        "tagline": "Texto branco nítido com nomes de animes e termos fortes destacados em amarelo",
        "words": [("O", "#ffffff", "#000000"), ("PODER", "#ffffff", "#000000"), ("DE", "#ffffff", "#000000"), ("GOKU!", "#fde047", "#000000")],
        "glow": None
    },
    "dynamic_animax": {
        "title": "Animax Dinâmico (Amarelo / Ciano)",
        "badge": "CANAL ANIMAX",
        "tagline": "Alternância dinâmica e vibrante de amarelo ouro e ciano em blocos",
        "words": [("MOMENTO", "#fde047", "#000000"), ("ÉPICO!", "#38bdf8", "#000000")],
        "glow": None
    },
    "yellow_gold": {
        "title": "Amarelo Ouro Viral",
        "badge": "CLÁSSICO VIRAL",
        "tagline": "Amarelo ouro de alto contraste e borda preta espessa",
        "words": [("AMARELO", "#fde047", "#000000"), ("OURO", "#fde047", "#000000")],
        "glow": None
    },
    "cyan_neon": {
        "title": "Ciano Neon",
        "badge": "NEON SOLID",
        "tagline": "Ciano elétrico com contorno preto nítido e visual futurista",
        "words": [("CIANO", "#38bdf8", "#000000"), ("NEON", "#38bdf8", "#000000")],
        "glow": None
    },
    "green_pop": {
        "title": "Verde Limão",
        "badge": "LIME POP",
        "tagline": "Verde limão energético com borda preta de alto impacto",
        "words": [("VERDE", "#4ade80", "#000000"), ("LIMÃO", "#4ade80", "#000000")],
        "glow": None
    },
    "classic_white": {
        "title": "Branco Clássico",
        "badge": "CINEMA CLEAN",
        "tagline": "Branco cinematográfico com contorno preto nítido e elegante",
        "words": [("BRANCO", "#ffffff", "#000000"), ("CLÁSSICO", "#ffffff", "#000000")],
        "glow": None
    },
}

_PREVIEW_CACHE: Dict[str, ctk.CTkImage] = {}


def render_subtitle_preview_image(style_key: str, width: int = 440, height: int = 70) -> ctk.CTkImage:
    """Renderiza um mockup visual do estilo de legenda em alta definição."""
    cache_key = f"{style_key}_{width}_{height}"
    if cache_key in _PREVIEW_CACHE:
        return _PREVIEW_CACHE[cache_key]

    meta = STYLE_METADATA.get(style_key, STYLE_METADATA["smart_situational"])
    scale = 2  # Supersampling 2x para nitidez
    w, h = width * scale, height * scale

    # Fundo do mockup: simula tela de vídeo escura com vinheta suave
    img = Image.new("RGBA", (w, h), (14, 14, 18, 255))
    d = ImageDraw.Draw(img)

    # Borda sutil do container
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=8 * scale, outline=(39, 39, 42, 255), width=scale)

    # Tenta usar Segoe UI Bold ou Arial Bold para renderizar as palavras de amostra
    font_size = int(17 * scale)
    try:
        font = ImageFont.truetype("segouib.ttf", font_size)
    except Exception:
        try:
            font = ImageFont.truetype("arialbd.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

    words_data = meta.get("words", [("AMOSTRA", "#ffffff", "#000000")])
    glow_color = meta.get("glow")
    is_3d = meta.get("is_3d", False)

    # Calcula largura total das palavras para centralizar
    spacing = int(10 * scale)
    word_boxes = []
    total_text_w = 0
    for w_text, fill_c, stroke_c in words_data:
        # getbbox
        try:
            bbox = font.getbbox(w_text)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
        except Exception:
            tw = len(w_text) * font_size * 0.6
            th = font_size
        word_boxes.append((w_text, fill_c, stroke_c, tw, th))
        total_text_w += tw

    total_text_w += spacing * (len(word_boxes) - 1)
    start_x = (w - total_text_w) // 2
    cur_x = start_x
    center_y = h // 2 - int(10 * scale)

    # Renderiza cada palavra com contornos e halos
    for w_text, fill_c, stroke_c, tw, th in word_boxes:
        pos = (cur_x, center_y)

        # 1. Glow Halo se aplicável
        if glow_color:
            glow_lw = int(4 * scale)
            d.text(pos, w_text, font=font, fill=glow_color, stroke_width=glow_lw, stroke_fill=glow_color)

        # 2. Sombra 3D Extrudada se aplicável
        if is_3d:
            for offset in range(3 * scale, 0, -1):
                d.text((cur_x + offset, center_y + offset), w_text, font=font, fill="#000000", stroke_width=int(2 * scale), stroke_fill="#000000")

        # 3. Contorno principal e preenchimento
        stroke_w = int(2.5 * scale)
        d.text(pos, w_text, font=font, fill=fill_c, stroke_width=stroke_w, stroke_fill=stroke_c)

        cur_x += int(tw + spacing)

    # Downsampling Lanczos para o CTkImage
    img_resized = img.resize((width, height), Image.Resampling.LANCZOS)
    ctk_img = ctk.CTkImage(light_image=img_resized, dark_image=img_resized, size=(width, height))
    _PREVIEW_CACHE[cache_key] = ctk_img
    return ctk_img


def get_style_info(style_key: str) -> Dict[str, Any]:
    """Retorna metadados formatados para exibição na UI."""
    return STYLE_METADATA.get(style_key, STYLE_METADATA["smart_situational"])
