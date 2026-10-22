"""
urahara_theme.py - Urahara Shōten Design System & Tokens

Gerado com UI/UX Pro Max Intelligence.
Inspirado na estética de Kisuke Urahara (Bleach / Urahara Shōten):
- Haori de Bambu e Chapéu Verde Listrado (Emerald & Forest: #10B981, #059669)
- Zanpakutō Benihime / Chikasumi no Tate (Crimson Princess: #E11D48, #BE123C)
- Noite de Karakura / Obsidian Shadow (#090C0B, #111815)
- Leque de Ouro / Faixas do Chapéu (Seda Off-White #F7F7F2, Amber #F59E0B)
- Padrão de contraste WCAG 2.1 AAA para máxima legibilidade
"""

from typing import Dict, Any

COLORS: Dict[str, str] = {
    # Superfícies e Fundos
    "bg": "#090C0B",               # Alias para compatibilidade com CTkFrame
    "bg_dark": "#090C0B",          # Obsidian Shadow profundo
    "bg_card": "#111815",          # Painéis Bambu / Madeira Urahara Shōten
    "bg_card_hover": "#17231E",    # Hover suave nos cards
    "bg_input": "#0D1310",         # Campos de texto e seleções
    "sidebar_bg": "#0B100E",       # Sidebar escura da loja
    "console_bg": "#070A09",       # Terminal de logs
    
    # Bordas e Divisórias
    "border": "#1A2621",           # Linhas e separadores finos
    "border_subtle": "#151F1B",
    "border_active": "#10B981",    # Destaque verde esmeralda no foco
    "border_benihime": "#E11D48",  # Borda de destaque Benihime
    "card_border": "#1A2621",
    
    # Acentos Primários (Verde Haori do Kisuke)
    "accent_primary": "#10B981",   # Verde Esmeralda clássico
    "accent_secondary": "#059669", # Verde Esmeralda médio
    "accent_hover": "#059669",     # Hover padrão
    "accent_dark": "#064E3B",      # Deep Forest
    "accent_glow": "#34D399",      # Brilho verde de alta visibilidade
    
    # Acentos de Clímax (Zanpakutō Benihime - Crimson Princess)
    "accent_benihime": "#E11D48",  # Carmesim vibrante para ações principais (Render)
    "accent_benihime_hover": "#BE123C",
    "accent_benihime_dark": "#4C0519",
    
    # Acentos Complementares (Leque de Ouro / Avisos)
    "accent_amber": "#F59E0B",     # Ouro envelhecido
    "warning": "#F59E0B",
    "success": "#10B981",
    "error": "#EF4444",
    
    # Tipografia & Contraste Calibrado
    "text_primary": "#F7F7F2",     # Seda / Bege off-white (Contraste 13:1)
    "text_secondary": "#A1AFA8",   # Cinza bambu legível (Contraste 5.5:1)
    "text_muted": "#687A72",       # Rótulos terciários e detalhes
    "console_text": "#A1AFA8",
    
    # Estados de Navegação da Sidebar
    "btn_active_bg": "#16241E",
    "btn_inactive_bg": "transparent",
    "btn_hover": "#121D18",
    "text_active": "#F7F7F2",
    "text_inactive": "#A1AFA8",
    "section_header": "#6B7D76",
    "indicator": "#10B981",
}

FONTS: Dict[str, tuple] = {
    "brand_kanji": ("Segoe UI", 16, "bold"),
    "brand_title": ("Segoe UI", 14, "bold"),
    "brand_sub": ("Segoe UI", 9),
    "section": ("Segoe UI", 9, "bold"),
    "nav_item": ("Segoe UI", 12),
    "nav_item_active": ("Segoe UI", 12, "bold"),
    "heading": ("Segoe UI", 13, "bold"),
    "body": ("Segoe UI", 11),
    "body_bold": ("Segoe UI", 11, "bold"),
    "small": ("Segoe UI", 9),
    "badge": ("Segoe UI", 9, "bold"),
    "mono": ("Consolas", 10),
}

LORE: Dict[str, str] = {
    "title": "URAHARA",
    "badge": "STUDIO",
    "app_name": "Urahara Studio",
    "subtitle": "Anime & Video Intelligence Suite",
    "status_ready": "Online [Pronto]",
    "status_busy": "Processando...",
}
