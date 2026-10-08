"""
subtitle_preview_helper.py - Gerador de Pré-Visualização Visual e Animada de Legendas do Urahara Studio.
Renderiza simulações em tempo real de alta fidelidade e animações ao vivo (live kinetic preview)
para todos os presets de legendas (Kinetic Emotion e Tradicionais).
"""

import math
from typing import Tuple, Dict, Any, Optional, List
from PIL import Image, ImageDraw, ImageFont
import customtkinter as ctk

STYLE_METADATA = {
    # =========================================================================
    # PRESETS KINETIC EMOTION (ESTILO CAPCUT PRO / CINEMA 2026)
    # =========================================================================
    "kinetic_dramatic": {
        "title": "🎬 Kinetic Dramático (Fade & Clímax)",
        "badge": "FADE & CLÍMAX",
        "tagline": "Fade suave cinematográfico com impacto que explode em escala e ouro flamejante",
        "words": [("ESSA É A", "#ffffff", "#000000"), ("BANKAI!", "#ffd515", "#ff6600")],
        "glow": "#ff8800",
        "anim_type": "dramatic"
    },
    "kinetic_emotional": {
        "title": "💔 Kinetic Emocional (Slow Breathe)",
        "badge": "SLOW BREATHE",
        "tagline": "Fade longo e tom azul gelo que respira suavemente (cenas tristes e despedidas)",
        "words": [("LEMBRANÇAS", "#ffffff", "#002040"), ("ETERNAS", "#e0f5ff", "#002040")],
        "glow": "#38bdf8",
        "anim_type": "breathe"
    },
    "kinetic_horror": {
        "title": "😱 Kinetic Horror & Tensão (Glitch Sangue)",
        "badge": "HORROR SANGUE",
        "tagline": "Vermelho sangue com tremor glitch assustador e contorno sombrio para vilões",
        "words": [("O MEDO", "#b81818", "#000000"), ("TE CONSOME", "#b81818", "#000000")],
        "glow": "#500000",
        "anim_type": "horror"
    },
    "kinetic_hype": {
        "title": "🔥 Kinetic Hype Impact (Super Pop)",
        "badge": "HYPE IMPACT",
        "tagline": "Super pop agressivo em brasa (laranja, ouro e fogo) para lutas e momentos badass",
        "words": [("HYPER", "#ff8810", "#000000"), ("IMPACTO!", "#ffd400", "#000000")],
        "glow": "#ff8810",
        "anim_type": "hype"
    },
    "kinetic_glitch": {
        "title": "⚡ Kinetic Cyber Glitch (Distorção)",
        "badge": "CYBER GLITCH",
        "tagline": "Aberração cromática digital em ciano e magenta com distorção que se conserta",
        "words": [("CYBER", "#00ffff", "#ea00ff"), ("GLITCH", "#ea00ff", "#00ffff")],
        "glow": "#ea00ff",
        "anim_type": "glitch"
    },
    "kinetic_lyric": {
        "title": "🎤 Kinetic Lyric Beat (Bounce Rítmico)",
        "badge": "LYRIC BEAT",
        "tagline": "Estilo clipe musical: cada palavra salta no ritmo do beat enquanto as outras atenuam",
        "words": [("NO", "#94a3b8", "#000000"), ("RITMO", "#ffd515", "#000000"), ("DO BEAT", "#94a3b8", "#000000")],
        "glow": "#ffd515",
        "anim_type": "lyric"
    },
    "kinetic_minimal": {
        "title": "🤍 Kinetic Minimal Bold (Viral Clean)",
        "badge": "MINIMAL BOLD",
        "tagline": "Branco puro de alta retenção viral (MrBeast / Hormozi) com pop sutil sem poluição",
        "words": [("FOCO", "#ffffff", "#000000"), ("TOTAL", "#ffffff", "#000000")],
        "glow": None,
        "anim_type": "minimal"
    },
    "kinetic_elegant": {
        "title": "✨ Kinetic Ouro Nobre (Elegante & Fade)",
        "badge": "OURO NOBRE",
        "tagline": "Transição sofisticada em ouro imperial e slide suave para trailers e cinema premium",
        "words": [("MOMENTO", "#ffd515", "#000000"), ("ÉPICO", "#ffffff", "#000000")],
        "glow": "#ffd515",
        "anim_type": "slide_fade"
    },
    "kinetic_smooth": {
        "title": "🌊 Kinetic Fluido (Ondulação Suave)",
        "badge": "ONDA FLUIDA",
        "tagline": "Ondulação oceânica suave sem cortes bruscos para vlogs e narrativas calmas",
        "words": [("FLUIDEZ", "#38bdf8", "#000000"), ("TOTAL", "#ffffff", "#000000")],
        "glow": "#38bdf8",
        "anim_type": "wave"
    },
    "kinetic_shonen": {
        "title": "🗯️ Kinetic Shonen Power (Golpe & 💥)",
        "badge": "SHONEN POWER",
        "tagline": "Golpes de anime gigantes com tremor sísmico e emojis de impacto (💥⚡🔥)",
        "words": [("GOLPE", "#ffe840", "#ff0000"), ("FINAL! 💥", "#ffe840", "#ff0000")],
        "glow": "#ff8800",
        "anim_type": "shonen"
    },
    "kinetic_seinen": {
        "title": "🌙 Kinetic Seinen Dark (Sombrio & Misterioso)",
        "badge": "SEINEN DARK",
        "tagline": "Estilo maduro e psicológico (Death Note) em tons sombrios de suspense",
        "words": [("O DESTINO", "#c0d0e0", "#200020"), ("ESTÁ SELADO", "#c0d0e0", "#200020")],
        "glow": None,
        "anim_type": "seinen"
    },
    "kinetic_kawaii": {
        "title": "🌸 Kinetic Kawaii Pop (Pastel & Sparkles ✨)",
        "badge": "KAWAII POP",
        "tagline": "Tons pastel doces, elastic bounce e emojis fofos para comédia e romance (✨🌸)",
        "words": [("MUITO", "#ff99d6", "#300050"), ("FOFO! ✨", "#ffff80", "#300050")],
        "glow": "#ff99d6",
        "anim_type": "kawaii"
    },

    # =========================================================================
    # PRESETS TRADICIONAIS
    # =========================================================================
    "smart_situational": {
        "title": "Inteligente Situacional (CapCut IA)",
        "badge": "IA ADAPTATIVA",
        "tagline": "Detecta o contexto emocional da fala e alterna cores (Amarelo, Ciano, Verde e Branco)",
        "words": [("ISSO", "#38bdf8", "#000000"), ("É", "#ffffff", "#000000"), ("SURREAL!", "#fde047", "#000000")],
        "glow": None,
        "anim_type": "situational"
    },
    "cyberpunk_neon": {
        "title": "Cyberpunk Neon Glow (Novo)",
        "badge": "NEON GLOW",
        "tagline": "Núcleo Ciano brilhante envolto por halo e contorno Magenta vibrante",
        "words": [("NIGHT", "#00ffff", "#ea00ff"), ("CITY", "#00ffff", "#ea00ff"), ("RUNNER", "#00ffff", "#ea00ff")],
        "glow": "#ea00ff",
        "anim_type": "neon_pulse"
    },
    "manga_3d": {
        "title": "Manga 3D Impact (Novo)",
        "badge": "SHONEN 3D",
        "tagline": "Estilo Mangá com contorno espesso e projeção de sombra tridimensional",
        "words": [("PODER", "#ffffff", "#000000"), ("MÁXIMO!", "#ffffff", "#000000")],
        "glow": None,
        "is_3d": True,
        "anim_type": "slam_3d"
    },
    "shonen_gold": {
        "title": "Shonen Aura Gold (Novo)",
        "badge": "AURA GOLD",
        "tagline": "Dourado cintilante flamejante com halo quente de energia espiritual",
        "words": [("SUPER", "#ffe840", "#ff6600"), ("SAIYAJIN!", "#ffe840", "#ff6600")],
        "glow": "#ff8800",
        "anim_type": "shonen"
    },
    "dark_synthwave": {
        "title": "Dark Synthwave (Novo)",
        "badge": "RETRO WAVE",
        "tagline": "Roxo elétrico estilo anos 80 com contorno amarelo retro-futurista",
        "words": [("SYNTH", "#ff40a8", "#ffff00"), ("WAVE", "#ff40a8", "#ffff00")],
        "glow": "#ffff00",
        "anim_type": "neon_pulse"
    },
    "diamond_ice": {
        "title": "Diamante Ice (Novo)",
        "badge": "ICE DIAMOND",
        "tagline": "Branco cristalino puro com borda e sombra azul gelo neon",
        "words": [("DIAMANTE", "#ffffff", "#00f0ff"), ("ICE", "#ffffff", "#00f0ff")],
        "glow": "#00f0ff",
        "anim_type": "breathe"
    },
    "word_karaoke": {
        "title": "Karaoke Ativo (Palavra Acende)",
        "badge": "SINCRONIA TOTAL",
        "tagline": "A palavra atual se acende em destaque no segundo exato em que o dublador fala",
        "words": [("VOCÊ", "#94a3b8", "#000000"), ("[ESTÁ]", "#fde047", "#000000"), ("PRONTO?", "#94a3b8", "#000000")],
        "glow": "#facc15",
        "anim_type": "lyric"
    },
    "word_by_word_contextual": {
        "title": "Palavra por Palavra - Contextual Pro (IA & Emoção)",
        "badge": "CONTEXTUAL PRO",
        "tagline": "Altera ênfase, tamanho e cor com precisão cinematográfica conforme a emoção da palavra",
        "words": [("PODER", "#ff3333", "#000000"), ("LENDÁRIO!", "#ffd515", "#000000")],
        "glow": "#ff3333",
        "anim_type": "hype"
    },
    "word_by_word_clean": {
        "title": "Palavra por Palavra - Branco Minimalista (Viral Clean)",
        "badge": "MINIMAL PRO",
        "tagline": "Branco cinematográfico com pop dinâmico suave de alta retenção (Sem poluição)",
        "words": [("FOCO", "#ffffff", "#000000"), ("TOTAL!", "#ffffff", "#000000")],
        "glow": None,
        "anim_type": "minimal"
    },
    "word_by_word_gold": {
        "title": "Palavra por Palavra - Ouro Nobre & Branco",
        "badge": "OURO NOBRE",
        "tagline": "Branco cinematográfico de elite com termos de glória e destaque em ouro imperial",
        "words": [("MOMENTO", "#ffffff", "#000000"), ("ÉPICO!", "#ffd515", "#000000")],
        "glow": "#ffd515",
        "anim_type": "slide_fade"
    },
    "word_by_word_cyber": {
        "title": "Palavra por Palavra - Ciano Neon & Branco",
        "badge": "CYBER CIANO",
        "tagline": "Branco cristalino de alta nitidez com realces dinâmicos em ciano neon elétrico",
        "words": [("VELOCIDADE", "#ffffff", "#000000"), ("MÁXIMA!", "#00ffff", "#000000")],
        "glow": "#00ffff",
        "anim_type": "glitch"
    },
    "word_by_word": {
        "title": "Palavra por Palavra - Colorido Clássico (TikTok)",
        "badge": "COLORIDO RETRÔ",
        "tagline": "Ciclo multicolorido tradicional de alta velocidade (Amarelo, Ciano, Verde e Coral)",
        "words": [("PALAVRA", "#fde047", "#000000"), ("COLORIDA!", "#38bdf8", "#000000")],
        "glow": None,
        "anim_type": "lyric"
    },
    "white_keyword_highlight": {
        "title": "Branco com Destaque Colorido",
        "badge": "DESTAQUE PRO",
        "tagline": "Texto branco nítido com nomes de animes e termos fortes destacados em amarelo",
        "words": [("O", "#ffffff", "#000000"), ("PODER", "#ffffff", "#000000"), ("DE", "#ffffff", "#000000"), ("GOKU!", "#fde047", "#000000")],
        "glow": None,
        "anim_type": "situational"
    },
    "dynamic_animax": {
        "title": "Animax Dinâmico (Amarelo / Ciano)",
        "badge": "CANAL ANIMAX",
        "tagline": "Alternância dinâmica e vibrante de amarelo ouro e ciano em blocos",
        "words": [("MOMENTO", "#fde047", "#000000"), ("ÉPICO!", "#38bdf8", "#000000")],
        "glow": None,
        "anim_type": "situational"
    },
    "yellow_gold": {
        "title": "Amarelo Ouro Viral",
        "badge": "CLÁSSICO VIRAL",
        "tagline": "Amarelo ouro de alto contraste e borda preta espessa",
        "words": [("AMARELO", "#fde047", "#000000"), ("OURO", "#fde047", "#000000")],
        "glow": None,
        "anim_type": "situational"
    },
    "cyan_neon": {
        "title": "Ciano Neon",
        "badge": "NEON SOLID",
        "tagline": "Ciano elétrico com contorno preto nítido e visual futurista",
        "words": [("CIANO", "#38bdf8", "#000000"), ("NEON", "#38bdf8", "#000000")],
        "glow": None,
        "anim_type": "situational"
    },
    "green_pop": {
        "title": "Verde Limão",
        "badge": "LIME POP",
        "tagline": "Verde limão energético com borda preta de alto impacto",
        "words": [("VERDE", "#4ade80", "#000000"), ("LIMÃO", "#4ade80", "#000000")],
        "glow": None,
        "anim_type": "situational"
    },
    "classic_white": {
        "title": "Branco Clássico",
        "badge": "CINEMA CLEAN",
        "tagline": "Branco cinematográfico com contorno preto nítido e elegante",
        "words": [("BRANCO", "#ffffff", "#000000"), ("CLÁSSICO", "#ffffff", "#000000")],
        "glow": None,
        "anim_type": "situational"
    },
}

_PREVIEW_CACHE: Dict[str, ctk.CTkImage] = {}
_ANIM_FRAME_CACHE: Dict[str, List[ctk.CTkImage]] = {}


def _get_font(size: int):
    """Obtém fonte negrito suportada pelo sistema."""
    for fn in ("segouib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(fn, size)
        except Exception:
            pass
    return ImageFont.load_default()


def render_subtitle_preview_image(style_key: str, width: int = 440, height: int = 70) -> ctk.CTkImage:
    """Renderiza um mockup estático do estilo de legenda em alta definição."""
    cache_key = f"{style_key}_{width}_{height}"
    if cache_key in _PREVIEW_CACHE:
        return _PREVIEW_CACHE[cache_key]

    meta = STYLE_METADATA.get(style_key, STYLE_METADATA["smart_situational"])
    scale = 2
    w, h = width * scale, height * scale

    img = Image.new("RGBA", (w, h), (14, 14, 18, 255))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=8 * scale, outline=(39, 39, 42, 255), width=scale)

    font_size = int(16 * scale)
    font = _get_font(font_size)

    words_data = meta.get("words", [("AMOSTRA", "#ffffff", "#000000")])
    glow_color = meta.get("glow")
    is_3d = meta.get("is_3d", False)

    spacing = int(10 * scale)
    word_boxes = []
    total_text_w = 0
    for w_text, fill_c, stroke_c in words_data:
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

    for w_text, fill_c, stroke_c, tw, th in word_boxes:
        pos = (cur_x, center_y)
        if glow_color:
            glow_lw = int(4 * scale)
            d.text(pos, w_text, font=font, fill=glow_color, stroke_width=glow_lw, stroke_fill=glow_color)
        if is_3d:
            for offset in range(3 * scale, 0, -1):
                d.text((cur_x + offset, center_y + offset), w_text, font=font, fill="#000000", stroke_width=int(2 * scale), stroke_fill="#000000")
        stroke_w = int(2.5 * scale)
        d.text(pos, w_text, font=font, fill=fill_c, stroke_width=stroke_w, stroke_fill=stroke_c)
        cur_x += int(tw + spacing)

    img_resized = img.resize((width, height), Image.Resampling.LANCZOS)
    ctk_img = ctk.CTkImage(light_image=img_resized, dark_image=img_resized, size=(width, height))
    _PREVIEW_CACHE[cache_key] = ctk_img
    return ctk_img


def get_preview_animation_frames(style_key: str, width: int = 320, height: int = 44, num_frames: int = 14) -> List[ctk.CTkImage]:
    """
    Gera sequência de frames animados para pré-visualização ao vivo do estilo.
    Executa a micro-animação (bounce, glitch, fade, onda, etc.) em loop suave.
    """
    cache_key = f"{style_key}_{width}_{height}_{num_frames}"
    if cache_key in _ANIM_FRAME_CACHE:
        return _ANIM_FRAME_CACHE[cache_key]

    meta = STYLE_METADATA.get(style_key, STYLE_METADATA["smart_situational"])
    anim_type = meta.get("anim_type", "situational")
    words_data = meta.get("words", [("AMOSTRA", "#ffffff", "#000000")])
    glow_color = meta.get("glow")
    is_3d = meta.get("is_3d", False)

    scale = 2
    w, h = width * scale, height * scale
    base_font_size = int(15 * scale)
    base_font = _get_font(base_font_size)

    frames = []

    for f_idx in range(num_frames):
        t = f_idx / float(num_frames)  # 0.0 a 1.0

        # Fundo do frame
        img = Image.new("RGBA", (w, h), (14, 14, 18, 255))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=6 * scale, outline=(42, 42, 48, 255), width=scale)

        # Calcula dinâmica de movimento e escala conforme o tipo de animação
        w_scales = [1.0] * len(words_data)
        w_y_offsets = [0.0] * len(words_data)
        w_x_offsets = [0.0] * len(words_data)
        w_alphas = [1.0] * len(words_data)
        glitch_active = False

        if anim_type == "dramatic":
            # Palavra 1 surge com fade; Palavra 2 explode em escala dramática no meio
            if t < 0.35:
                w_alphas[0] = min(1.0, t * 3.0)
                w_alphas[1] = 0.2
                w_scales[1] = 0.95
            elif t < 0.65:
                w_alphas[0] = 1.0
                w_alphas[1] = 1.0
                # Impacto explosivo com overshoot
                dt = (t - 0.35) / 0.30
                w_scales[1] = 1.25 - 0.20 * dt
                w_y_offsets[1] = -int(3 * scale * math.sin(dt * math.pi))
            else:
                w_alphas[0] = 1.0
                w_alphas[1] = 1.0
                w_scales[1] = 1.05

        elif anim_type == "breathe":
            # Pulso lento e relaxado de respiração
            pulse = math.sin(t * 2 * math.pi)
            for i in range(len(words_data)):
                w_scales[i] = 1.0 + 0.05 * pulse
                w_y_offsets[i] = -int(1.5 * scale * pulse)

        elif anim_type == "horror":
            # Tremor assustador de ângulo e micro-vibração
            jitter = math.sin(t * 20.0)
            for i in range(len(words_data)):
                w_x_offsets[i] = int(2.5 * scale * jitter)
                w_y_offsets[i] = int(1.5 * scale * math.cos(t * 25.0))
                w_scales[i] = 1.0 + 0.04 * math.sin(t * 12.0)

        elif anim_type == "hype":
            # Pop agressivo rápido alternando entre as palavras
            step = int(t * len(words_data) * 1.5) % len(words_data)
            for i in range(len(words_data)):
                if i == step:
                    sub_t = (t * len(words_data) * 1.5) % 1.0
                    w_scales[i] = 1.28 - 0.20 * sub_t
                    w_y_offsets[i] = -int(4 * scale * (1.0 - sub_t))
                else:
                    w_scales[i] = 1.0

        elif anim_type == "glitch":
            # Aberração cromática em momentos chave
            if 0.20 <= t <= 0.35 or 0.70 <= t <= 0.85:
                glitch_active = True
                for i in range(len(words_data)):
                    w_x_offsets[i] = int(3.5 * scale * math.sin(t * 30.0))
            else:
                for i in range(len(words_data)):
                    w_scales[i] = 1.0

        elif anim_type == "lyric":
            # Cada palavra salta no ritmo do beat sequencialmente
            active_idx = int(t * len(words_data)) % len(words_data)
            for i in range(len(words_data)):
                if i == active_idx:
                    sub_t = (t * len(words_data)) % 1.0
                    w_scales[i] = 1.18
                    w_y_offsets[i] = -int(5 * scale * math.sin(sub_t * math.pi))
                    w_alphas[i] = 1.0
                else:
                    w_alphas[i] = 0.5
                    w_scales[i] = 0.96

        elif anim_type == "minimal":
            # Pop clean com overshoot suave
            pop_t = math.sin(t * math.pi)
            for i in range(len(words_data)):
                w_scales[i] = 1.0 + 0.12 * pop_t

        elif anim_type == "slide_fade":
            # Desliza de baixo subindo suavemente
            slide_t = min(1.0, t * 1.5)
            y_shift = int(6 * scale * (1.0 - slide_t))
            for i in range(len(words_data)):
                w_y_offsets[i] = y_shift
                w_alphas[i] = min(1.0, slide_t * 1.2)

        elif anim_type == "wave":
            # Ondulação senoidal fluida contínua
            for i in range(len(words_data)):
                w_y_offsets[i] = int(4 * scale * math.sin(t * 2 * math.pi + i * 1.5))

        elif anim_type == "shonen":
            # Tremor de poder sísmico e super escala na palavra de golpe
            if t < 0.4:
                w_scales[0] = 1.05
                w_scales[-1] = 0.95
            else:
                dt = (t - 0.4) / 0.6
                tremor = math.sin(dt * 24.0) * (1.0 - dt)
                w_x_offsets[-1] = int(3.0 * scale * tremor)
                w_scales[-1] = 1.30 - 0.20 * dt
                w_y_offsets[-1] = -int(3 * scale * math.sin(dt * math.pi))

        elif anim_type == "kawaii":
            # Elastic jelly bounce (escala X e Y invertidas)
            bounce = math.sin(t * 2 * math.pi)
            for i in range(len(words_data)):
                w_scales[i] = 1.0 + 0.10 * bounce
                w_y_offsets[i] = -int(3.5 * scale * abs(bounce))

        else:
            # Padrão situacional / neon: leve pulso de brilho
            pulse = math.sin(t * 2 * math.pi)
            for i in range(len(words_data)):
                w_scales[i] = 1.0 + 0.04 * pulse

        # Medição das larguras com a escala dinâmica
        word_render_info = []
        total_w = 0
        spacing = int(8 * scale)

        for i, (w_text, fill_c, stroke_c) in enumerate(words_data):
            sc = w_scales[i]
            cur_font_size = max(10, int(base_font_size * sc))
            cur_font = _get_font(cur_font_size)
            try:
                bbox = cur_font.getbbox(w_text)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
            except Exception:
                tw = int(len(w_text) * cur_font_size * 0.6)
                th = cur_font_size
            word_render_info.append((w_text, fill_c, stroke_c, cur_font, tw, th, w_x_offsets[i], w_y_offsets[i], w_alphas[i]))
            total_w += tw

        total_w += spacing * (len(word_render_info) - 1)
        cur_x = (w - total_w) // 2
        base_y = (h // 2) - int(8 * scale)

        # Desenha palavras
        for w_text, fill_c, stroke_c, cur_font, tw, th, xo, yo, alpha in word_render_info:
            pos = (cur_x + xo, base_y + yo)

            # Efeito glitch: desenha sombras coloridas deslocadas (magenta / ciano)
            if glitch_active:
                d.text((pos[0] - int(3 * scale), pos[1]), w_text, font=cur_font, fill="#ea00ff", stroke_width=int(2 * scale), stroke_fill="#ea00ff")
                d.text((pos[0] + int(3 * scale), pos[1]), w_text, font=cur_font, fill="#00ffff", stroke_width=int(2 * scale), stroke_fill="#00ffff")

            # Glow
            if glow_color and alpha > 0.4:
                d.text(pos, w_text, font=cur_font, fill=glow_color, stroke_width=int(4 * scale), stroke_fill=glow_color)

            # Sombra 3D se ativo
            if is_3d:
                for off in range(3 * scale, 0, -1):
                    d.text((pos[0] + off, pos[1] + off), w_text, font=cur_font, fill="#000000", stroke_width=int(2 * scale), stroke_fill="#000000")

            # Contorno e texto principal
            actual_fill = fill_c
            if alpha < 0.95:
                # Atenua cor se alpha baixo
                actual_fill = "#71717a" if fill_c == "#ffffff" else fill_c

            stroke_w = int(2.5 * scale)
            d.text(pos, w_text, font=cur_font, fill=actual_fill, stroke_width=stroke_w, stroke_fill=stroke_c)

            cur_x += tw + spacing

        # Redimensiona para o tamanho final da UI
        img_resized = img.resize((width, height), Image.Resampling.LANCZOS)
        ctk_frame = ctk.CTkImage(light_image=img_resized, dark_image=img_resized, size=(width, height))
        frames.append(ctk_frame)

    _ANIM_FRAME_CACHE[cache_key] = frames
    return frames


def get_style_info(style_key: str) -> Dict[str, Any]:
    """Retorna metadados formatados para exibição na UI."""
    return STYLE_METADATA.get(style_key, STYLE_METADATA["smart_situational"])
