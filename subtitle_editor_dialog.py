"""
subtitle_editor_dialog.py - Janela Modal de Revisao e Edicao Rapida de Legendas
Permite ao usuario:
- Visualizar e corrigir falhas de transcricao (especialmente nomes de personagens de anime)
- Inserir novas falas perdidas ou remover falas desnecessarias
- Substituir palavras em massa ("Localizar e Substituir")
- Escolher o estilo de cores (Dinamico, Amarelo, Ciano, Verde, Branco) e efeito Pop
- Continuar a renderizacao diretamente com 1 clique!
"""

import customtkinter as ctk
import icon_manager
import subtitle_preview_helper
from typing import List, Dict, Any, Callable, Optional
from subtitle_corrector import correct_phrase, load_dictionary, add_correction_term
from censorship_manager import censor_text, mask_word, add_custom_profanity, load_custom_profanity


COLORS = {
    "bg_dark": "#0B0E14",
    "bg_card": "#151A23",
    "bg_card_hover": "#1E2533",
    "border": "#2A3447",
    "accent": "#00D4FF",
    "accent_hover": "#00AACC",
    "accent_green": "#10B981",
    "accent_green_hover": "#059669",
    "text_primary": "#FFFFFF",
    "text_secondary": "#A1A1AA",
    "error": "#EF4444",
    "warning": "#F59E0B",
}

STYLE_OPTIONS = [
    "Inteligente Situacional (CapCut IA)",
    "Palavra por Palavra - Contextual Pro (IA & Emoção)",
    "Palavra por Palavra - Branco Minimalista (Viral Clean)",
    "Palavra por Palavra - Ouro Nobre & Branco",
    "Palavra por Palavra - Ciano Neon & Branco",
    "Palavra por Palavra - Colorido Clássico (TikTok)",
    "Cyberpunk Neon Glow (Novo)",
    "Manga 3D Impact (Novo)",
    "Shonen Aura Gold (Novo)",
    "Dark Synthwave (Novo)",
    "Diamante Ice (Novo)",
    "Karaoke Ativo (Palavra Acende)",
    "Branco com Destaque Colorido",
    "Animax Dinâmico (Amarelo / Ciano)",
    "Amarelo Ouro Viral",
    "Ciano Neon",
    "Verde Limão",
    "Branco Clássico",
]

STYLE_KEY_MAP = {
    "Inteligente Situacional (CapCut IA)": "smart_situational",
    "Palavra por Palavra - Contextual Pro (IA & Emoção)": "word_by_word_contextual",
    "Palavra por Palavra - Branco Minimalista (Viral Clean)": "word_by_word_clean",
    "Palavra por Palavra - Ouro Nobre & Branco": "word_by_word_gold",
    "Palavra por Palavra - Ciano Neon & Branco": "word_by_word_cyber",
    "Palavra por Palavra - Colorido Clássico (TikTok)": "word_by_word",
    "Palavra por Palavra (TikTok)": "word_by_word",
    "Cyberpunk Neon Glow (Novo)": "cyberpunk_neon",
    "Manga 3D Impact (Novo)": "manga_3d",
    "Shonen Aura Gold (Novo)": "shonen_gold",
    "Dark Synthwave (Novo)": "dark_synthwave",
    "Diamante Ice (Novo)": "diamond_ice",
    "Karaoke Ativo (Palavra Acende)": "word_karaoke",
    "Branco com Destaque Colorido": "white_keyword_highlight",
    "Animax Dinâmico (Amarelo / Ciano)": "dynamic_animax",
    "Amarelo Ouro Viral": "yellow_gold",
    "Ciano Neon": "cyan_neon",
    "Verde Limão": "green_pop",
    "Branco Clássico": "classic_white",
}

EFFECT_OPTIONS = [
    "Esmaecer Suave (Anime Clássico)",
    "Glitch Shake (Cyberpunk)",
    "Neon Pulse & Glow",
    "3D Slam / Heavy Drop",
    "Onda Fluida / Kinetic Wave",
    "Pop / Zoom Bounce (Viral / CapCut)",
    "Deslizar de Baixo (Slide Up)",
    "Pop Rápido (Shonen)",
    "Texto Fixo (Sem Efeito)",
]

EFFECT_KEY_MAP = {
    "Esmaecer Suave (Anime Clássico)": "fade",
    "Glitch Shake (Cyberpunk)": "glitch",
    "Neon Pulse & Glow": "pulse",
    "3D Slam / Heavy Drop": "slam",
    "Onda Fluida / Kinetic Wave": "wave",
    "Pop / Zoom Bounce (Viral / CapCut)": "pop",
    "Deslizar de Baixo (Slide Up)": "slide",
    "Pop Rápido (Shonen)": "quick",
    "Texto Fixo (Sem Efeito)": "none",
}


def sec_to_str(seconds: float) -> str:
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m:02d}:{s:04.1f}"


def str_to_sec(text: str) -> float:
    try:
        if ":" in text:
            parts = text.split(":")
            return int(parts[0]) * 60 + float(parts[1])
        return float(text)
    except Exception:
        return 0.0


class SubtitleEditorDialog(ctk.CTkToplevel):
    """Janela moderna para inspecionar e editar legendas antes da renderizacao."""

    def __init__(
        self,
        parent,
        items: List[Dict[str, Any]],
        on_confirm: Callable[[List[Dict[str, Any]], str, Any], None],
        current_style: str = "dynamic_animax",
        current_pop: Any = "Esmaecer Suave (Anime Clássico)",
        video_duration: Optional[float] = None,
        **kwargs
    ):
        super().__init__(parent, **kwargs)
        self.title("Revisão de Legendas & Nomes de Anime")
        self.geometry("860x720")
        self.minsize(740, 560)
        self.configure(fg_color=COLORS["bg_dark"])

        self.on_confirm = on_confirm
        self.items = [dict(it) for it in items]
        self.video_duration = video_duration
        self.rows = []

        self.transient(parent)
        self.grab_set()

        self._build_ui(current_style, current_pop)
        self._populate_items()

    def _build_ui(self, current_style: str, current_pop: Any):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # 1. Header Frame
        header = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], corner_radius=10)
        header.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Revisão Rápida de Legendas",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=COLORS["accent"]
        ).grid(row=0, column=0, padx=16, pady=(12, 2), sticky="w")

        sub_hint = "Corrija nomes de personagens, troque palavras ou ajuste o tempo das falas."
        if self.video_duration and self.video_duration > 0:
            sub_hint += f"  •  Duração do Vídeo: {sec_to_str(self.video_duration)} (as legendas não ultrapassam este tempo)"

        ctk.CTkLabel(
            header,
            text=sub_hint,
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"]
        ).grid(row=1, column=0, padx=16, pady=(0, 12), sticky="w")

        # 2. Toolbar (Find & Replace + Style Preset + Pop Effect)
        toolbar = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], corner_radius=10)
        toolbar.grid(row=1, column=0, padx=16, pady=4, sticky="ew")
        toolbar.grid_columnconfigure(3, weight=1)

        # Find & Replace
        ctk.CTkLabel(toolbar, text="Substituir:", font=ctk.CTkFont(size=11, weight="bold"), text_color=COLORS["text_primary"]).grid(row=0, column=0, padx=(14, 4), pady=10)
        self.find_entry = ctk.CTkEntry(toolbar, width=110, height=30, placeholder_text="Ex: sandy", fg_color=COLORS["bg_dark"], border_color=COLORS["border"])
        self.find_entry.grid(row=0, column=1, padx=4, pady=10)

        ctk.CTkLabel(toolbar, text="Por:", font=ctk.CTkFont(size=11, weight="bold"), text_color=COLORS["text_primary"]).grid(row=0, column=2, padx=(8, 4), pady=10)
        self.replace_entry = ctk.CTkEntry(toolbar, width=110, height=30, placeholder_text="Ex: Sanji", fg_color=COLORS["bg_dark"], border_color=COLORS["border"])
        self.replace_entry.grid(row=0, column=3, padx=4, pady=10, sticky="w")

        ctk.CTkButton(
            toolbar,
            text="Trocar em Todos",
            width=110,
            height=30,
            fg_color=COLORS["bg_card_hover"],
            hover_color=COLORS["border"],
            command=self._replace_all
        ).grid(row=0, column=4, padx=6, pady=10)

        # Style Options Dropdown
        ctk.CTkLabel(toolbar, text="Cores:", font=ctk.CTkFont(size=11, weight="bold"), text_color=COLORS["text_primary"]).grid(row=0, column=5, padx=(10, 4), pady=10)
        
        rev_map = {}
        for opt in STYLE_OPTIONS:
            k = STYLE_KEY_MAP.get(opt)
            if k and k not in rev_map:
                rev_map[k] = opt
        init_style_label = rev_map.get(current_style, STYLE_OPTIONS[0])

        self.style_var = ctk.StringVar(value=init_style_label)
        self.style_menu = ctk.CTkOptionMenu(
            toolbar,
            values=STYLE_OPTIONS,
            variable=self.style_var,
            command=self._on_style_changed,
            width=290,
            height=30,
            fg_color=COLORS["bg_card_hover"],
            button_color=COLORS["border"],
            dropdown_fg_color=COLORS["bg_card"]
        )
        self.style_menu.grid(row=0, column=6, padx=(4, 14), pady=10)

        # Row 1: Live Subtitle Style Preview Card inside Editor Dialog
        self.preview_card = ctk.CTkFrame(toolbar, fg_color=COLORS["bg_dark"], corner_radius=6, border_width=1, border_color=COLORS["border"])
        self.preview_card.grid(row=1, column=0, columnspan=7, padx=14, pady=(0, 10), sticky="ew")
        self.preview_card.grid_columnconfigure(2, weight=1)

        self.lbl_preview_badge = ctk.CTkLabel(
            self.preview_card,
            text="IA ADAPTATIVA",
            font=ctk.CTkFont(size=9, weight="bold"),
            fg_color=COLORS["accent"],
            text_color="#000000",
            corner_radius=4,
            width=115,
            height=22
        )
        self.lbl_preview_badge.grid(row=0, column=0, padx=(10, 8), pady=6)

        self.lbl_preview_img = ctk.CTkLabel(
            self.preview_card,
            text="",
            image=None
        )
        self.lbl_preview_img.grid(row=0, column=1, padx=6, pady=4, sticky="w")

        self.lbl_preview_desc = ctk.CTkLabel(
            self.preview_card,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_secondary"],
            anchor="w"
        )
        self.lbl_preview_desc.grid(row=0, column=2, padx=(8, 14), pady=6, sticky="ew")

        self._on_style_changed()

        # Row 2: Seção de Censura de Palavrões e Termos Feios
        censor_toolbar_row = ctk.CTkFrame(toolbar, fg_color="transparent")
        censor_toolbar_row.grid(row=2, column=0, columnspan=7, padx=14, pady=(0, 10), sticky="ew")

        ctk.CTkLabel(
            censor_toolbar_row,
            text="🔇 Censurar Palavrão (Áudio & Legenda):",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#f87171"
        ).pack(side="left", padx=(0, 6))

        self.profanity_entry = ctk.CTkEntry(
            censor_toolbar_row,
            width=150,
            height=28,
            placeholder_text="Digite palavra feia...",
            fg_color=COLORS["bg_dark"],
            border_color=COLORS["border"]
        )
        self.profanity_entry.pack(side="left", padx=4)

        ctk.CTkButton(
            censor_toolbar_row,
            text="Censurar no Vídeo",
            width=135,
            height=28,
            fg_color="#451a1a",
            hover_color="#dc2626",
            text_color="#fca5a5",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._censor_typed_word_in_all
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            censor_toolbar_row,
            text="⚡ Auto-Detectar Palavrões",
            width=175,
            height=28,
            fg_color=COLORS["bg_card_hover"],
            hover_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(size=11),
            command=self._auto_detect_all_profanities
        ).pack(side="left", padx=6)

        self.lbl_censor_status = ctk.CTkLabel(
            censor_toolbar_row,
            text="",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#10b981"
        )
        self.lbl_censor_status.pack(side="left", padx=8)

        # 3. Subtitles Scrollable List
        self.scroll_frame = ctk.CTkScrollableFrame(self, fg_color=COLORS["bg_card"], corner_radius=10)
        self.scroll_frame.grid(row=2, column=0, padx=16, pady=8, sticky="nsew")
        self.scroll_frame.grid_columnconfigure(1, weight=1)

        # 4. Action / Footer Bar
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, padx=16, pady=(4, 16), sticky="ew")
        footer.grid_columnconfigure(3, weight=1)

        # Seletor de Efeitos Visuais (Esmaecer, Pop, Slide, Fixo)
        ctk.CTkLabel(
            footer,
            text="Efeito:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLORS["text_primary"]
        ).grid(row=0, column=0, padx=(4, 4), pady=6, sticky="w")

        init_eff_label = EFFECT_OPTIONS[0]
        if isinstance(current_pop, str):
            for opt in EFFECT_OPTIONS:
                if current_pop.lower() in opt.lower() or opt.lower() in current_pop.lower():
                    init_eff_label = opt
                    break
        elif current_pop is False:
            init_eff_label = "Texto Fixo (Sem Efeito)"
        elif current_pop is True:
            init_eff_label = "Esmaecer Suave (Anime Clássico)"

        self.effect_var = ctk.StringVar(value=init_eff_label)
        self.effect_menu = ctk.CTkOptionMenu(
            footer,
            values=EFFECT_OPTIONS,
            variable=self.effect_var,
            width=235,
            height=34,
            fg_color=COLORS["bg_card"],
            button_color=COLORS["border"],
            dropdown_fg_color=COLORS["bg_card"]
        )
        self.effect_menu.grid(row=0, column=1, padx=(2, 10), pady=6, sticky="w")

        ctk.CTkButton(
            footer,
            text="+ Adicionar Fala",
            width=130,
            height=40,
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_card_hover"],
            text_color=COLORS["accent"],
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._add_row
        ).grid(row=0, column=2, padx=4, pady=6)

        ctk.CTkButton(
            footer,
            text="Cancelar",
            width=100,
            height=44,
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_card_hover"],
            text_color=COLORS["text_secondary"],
            command=self.destroy
        ).grid(row=0, column=4, padx=(0, 10), pady=6)

        ctk.CTkButton(
            footer,
            text="GERAR VÍDEO FINAL",
            image=icon_manager.get_icon("play", size=(16, 16), color="#09090b"), compound="left",
            height=44,
            width=220,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=COLORS["accent_green"],
            hover_color=COLORS["accent_green_hover"],
            command=self._confirm_and_render
        ).grid(row=0, column=5, padx=0, pady=6)

    def _populate_items(self):
        # Clear any existing rows
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        self.rows.clear()

        for idx, it in enumerate(self.items):
            self._render_row(idx, it)

    def _render_row(self, idx: int, it: Dict[str, Any]):
        r_frame = ctk.CTkFrame(self.scroll_frame, fg_color=COLORS["bg_dark"], corner_radius=8)
        r_frame.pack(fill="x", pady=4, padx=4)
        r_frame.grid_columnconfigure(1, weight=1)

        # Top row: Timestamps + Text Entry + Palavras Button + Delete Button
        top_row = ctk.CTkFrame(r_frame, fg_color="transparent")
        top_row.pack(fill="x", padx=4, pady=4)
        top_row.grid_columnconfigure(1, weight=1)

        # Timestamps
        time_frame = ctk.CTkFrame(top_row, fg_color="transparent")
        time_frame.grid(row=0, column=0, padx=6, pady=2)

        start_v = ctk.StringVar(value=sec_to_str(float(it.get("start", 0.0))))
        end_v = ctk.StringVar(value=sec_to_str(float(it.get("end", 0.0))))

        s_entry = ctk.CTkEntry(time_frame, textvariable=start_v, width=64, height=28,
                                font=ctk.CTkFont(family="Consolas", size=11), fg_color=COLORS["bg_card"])
        s_entry.pack(side="left", padx=2)

        ctk.CTkLabel(time_frame, text="->", text_color=COLORS["text_secondary"]).pack(side="left", padx=2)

        e_entry = ctk.CTkEntry(time_frame, textvariable=end_v, width=64, height=28,
                                font=ctk.CTkFont(family="Consolas", size=11), fg_color=COLORS["bg_card"])
        e_entry.pack(side="left", padx=2)

        # Text
        text_v = ctk.StringVar(value=it.get("text") or it.get("word") or "")
        t_entry = ctk.CTkEntry(top_row, textvariable=text_v, height=34,
                                font=ctk.CTkFont(size=12, weight="bold"),
                                fg_color=COLORS["bg_card"], border_color=COLORS["border"])
        t_entry.grid(row=0, column=1, padx=6, pady=2, sticky="ew")

        # Botão Palavras / Censurar
        btn_words = ctk.CTkButton(
            top_row,
            text="🔇 Palavras",
            width=85,
            height=30,
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_card_hover"],
            text_color="#f59e0b",
            font=ctk.CTkFont(size=10, weight="bold"),
            command=lambda: self._toggle_words_panel(row_data)
        )
        btn_words.grid(row=0, column=2, padx=4, pady=2)

        # Delete button
        del_btn = ctk.CTkButton(
            top_row,
            text="X",
            width=30,
            height=30,
            fg_color="transparent",
            hover_color=COLORS["error"],
            text_color=COLORS["text_secondary"],
            command=lambda f=r_frame: self._delete_row(f)
        )
        del_btn.grid(row=0, column=3, padx=(2, 6), pady=2)

        # Container expansível de chips de palavras da frase
        words_panel = ctk.CTkFrame(r_frame, fg_color=COLORS["bg_card"], corner_radius=6)

        row_data = {
            "frame": r_frame,
            "top_row": top_row,
            "words_panel": words_panel,
            "words_panel_open": False,
            "btn_words": btn_words,
            "start_v": start_v,
            "end_v": end_v,
            "text_v": text_v,
            "orig_item": it,
            "word_buttons": [],
        }
        self.rows.append(row_data)

        # Se já tiver palavra censurada, abre automaticamente o painel de palavras
        words_list = it.get("words", [])
        has_censored = any(w.get("censored") or ("*" in str(w.get("word", ""))) for w in words_list)
        if has_censored:
            self._toggle_words_panel(row_data, force_state=True)

    def _toggle_words_panel(self, row_data: dict, force_state: Optional[bool] = None):
        is_open = not row_data["words_panel_open"] if force_state is None else force_state
        row_data["words_panel_open"] = is_open

        panel = row_data["words_panel"]
        if is_open:
            panel.pack(fill="x", padx=10, pady=(0, 6))
            row_data["btn_words"].configure(text="▲ Palavras", fg_color=COLORS["bg_card_hover"])
            self._render_words_chips(row_data)
        else:
            panel.pack_forget()
            row_data["btn_words"].configure(text="🔇 Palavras", fg_color=COLORS["bg_card"])

    def _render_words_chips(self, row_data: dict):
        panel = row_data["words_panel"]
        for w in panel.winfo_children():
            w.destroy()

        header_f = ctk.CTkFrame(panel, fg_color="transparent")
        header_f.pack(fill="x", padx=8, pady=(4, 2))
        ctk.CTkLabel(
            header_f,
            text="Palavras faladas (clique na palavra para alternar censura com asteriscos e mudo cirúrgico):",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=COLORS["text_secondary"]
        ).pack(side="left")

        chips_f = ctk.CTkFrame(panel, fg_color="transparent")
        chips_f.pack(fill="x", padx=8, pady=(2, 6))

        it = row_data["orig_item"]
        words_list = it.get("words", [])
        if not words_list:
            txt = row_data["text_v"].get()
            s = str_to_sec(row_data["start_v"].get())
            e = str_to_sec(row_data["end_v"].get())
            from subtitle_renderer import _interpolate_words
            words_list = _interpolate_words(txt, s, e)
            it["words"] = words_list

        row_data["word_buttons"].clear()
        for w_idx, w in enumerate(words_list):
            w_text = w.get("word") or w.get("text") or ""
            is_censored = bool(w.get("censored")) or ("*" in w_text)

            btn_color = "#ef4444" if is_censored else COLORS["bg_card_hover"]
            btn_txt = f"{w_text} 🔇" if is_censored else w_text

            btn = ctk.CTkButton(
                chips_f,
                text=btn_txt,
                height=26,
                font=ctk.CTkFont(size=11, weight="bold" if is_censored else "normal"),
                fg_color=btn_color,
                hover_color="#dc2626" if is_censored else "#451a1a",
                command=lambda r=row_data, idx=w_idx: self._toggle_word_censorship(r, idx)
            )
            btn.pack(side="left", padx=2, pady=2)
            row_data["word_buttons"].append(btn)

    def _toggle_word_censorship(self, row_data: dict, word_idx: int):
        it = row_data["orig_item"]
        words_list = it.get("words", [])
        if word_idx >= len(words_list):
            return

        w = words_list[word_idx]
        is_currently_censored = bool(w.get("censored")) or ("*" in str(w.get("word", "")))

        if not is_currently_censored:
            if "original_word" not in w:
                w["original_word"] = w.get("word") or w.get("text") or ""
            w["censored"] = True
            masked = mask_word(w["original_word"])
            w["word"] = masked
            w["text"] = masked
        else:
            w["censored"] = False
            orig = w.get("original_word", w.get("word", ""))
            w["word"] = orig
            w["text"] = orig

        new_phrase = " ".join([word.get("word") or word.get("text") or "" for word in words_list])
        row_data["text_v"].set(new_phrase)
        self._render_words_chips(row_data)

    def _censor_typed_word_in_all(self):
        target = self.profanity_entry.get().strip().lower()
        if not target:
            return

        add_custom_profanity(target)
        count = 0
        import re

        for row_data in self.rows:
            it = row_data["orig_item"]
            words_list = it.get("words", [])
            row_changed = False

            if words_list:
                for w in words_list:
                    raw_w = (w.get("original_word") or w.get("word") or "").lower()
                    clean_w = re.sub(r"[^\w-]", "", raw_w)
                    if clean_w == target or target in clean_w:
                        if "original_word" not in w:
                            w["original_word"] = w.get("word") or w.get("text") or ""
                        w["censored"] = True
                        masked = mask_word(w["original_word"])
                        w["word"] = masked
                        w["text"] = masked
                        row_changed = True
                        count += 1
                if row_changed:
                    new_phrase = " ".join([word.get("word") or word.get("text") or "" for word in words_list])
                    row_data["text_v"].set(new_phrase)
                    self._toggle_words_panel(row_data, force_state=True)
            else:
                txt = row_data["text_v"].get()
                new_txt, n = re.subn(rf"\b{re.escape(target)}\b", mask_word(target), txt, flags=re.IGNORECASE)
                if n > 0:
                    row_data["text_v"].set(new_txt)
                    count += n

        self.lbl_censor_status.configure(text=f"✓ '{target}' censurada ({count}x) no áudio e legenda!")
        self.profanity_entry.delete(0, "end")

    def _auto_detect_all_profanities(self):
        count = 0
        for row_data in self.rows:
            it = row_data["orig_item"]
            words_list = it.get("words", [])
            row_changed = False

            if words_list:
                for w in words_list:
                    raw_w = (w.get("original_word") or w.get("word") or "")
                    censored_text, is_p = censor_text(raw_w)
                    if is_p:
                        if "original_word" not in w:
                            w["original_word"] = raw_w
                        w["censored"] = True
                        w["word"] = censored_text
                        w["text"] = censored_text
                        row_changed = True
                        count += 1
                if row_changed:
                    new_phrase = " ".join([word.get("word") or word.get("text") or "" for word in words_list])
                    row_data["text_v"].set(new_phrase)
                    self._toggle_words_panel(row_data, force_state=True)
            else:
                txt = row_data["text_v"].get()
                censored_text, is_p = censor_text(txt)
                if is_p:
                    row_data["text_v"].set(censored_text)
                    count += 1

        self.lbl_censor_status.configure(text=f"✓ Auto-detecção: {count} palavra(s) censurada(s)!")

    def _on_style_changed(self, choice=None):
        """Atualiza o banner de pré-visualização em tempo real na janela de revisão."""
        try:
            style_label = self.style_var.get()
            style_key = STYLE_KEY_MAP.get(style_label, "smart_situational")
            meta = subtitle_preview_helper.get_style_info(style_key)
            self.lbl_preview_badge.configure(text=meta.get("badge", "ESTILO"))
            self.lbl_preview_desc.configure(text=meta.get("tagline", ""))
            p_img = subtitle_preview_helper.render_subtitle_preview_image(style_key, width=320, height=44)
            self.lbl_preview_img.configure(image=p_img)
            self.lbl_preview_img.image = p_img
        except Exception:
            pass

    def _delete_row(self, frame):
        self.rows = [r for r in self.rows if r["frame"] != frame]
        frame.destroy()

    def _add_row(self):
        last_end = 0.0
        if self.rows:
            last_end = str_to_sec(self.rows[-1]["end_v"].get()) + 0.05

        new_item = {
            "start": last_end,
            "end": last_end + 1.8,
            "text": "NOVA FALA"
        }
        self.items.append(new_item)
        self._render_row(len(self.items) - 1, new_item)

    def _replace_all(self):
        find_w = self.find_entry.get().strip()
        replace_w = self.replace_entry.get().strip()
        if not find_w:
            return

        # Save to persistent anime dictionary for future videos
        add_correction_term(find_w, replace_w)

        count = 0
        for r in self.rows:
            curr_text = r["text_v"].get()
            import re
            new_text, n = re.subn(rf"\b{re.escape(find_w)}\b", replace_w, curr_text, flags=re.IGNORECASE)
            if n > 0:
                r["text_v"].set(new_text)
                count += n

    def _confirm_and_render(self):
        from subtitle_renderer import _interpolate_words
        final_items = []
        for r in self.rows:
            txt = r["text_v"].get().strip()
            if not txt:
                continue
            s = str_to_sec(r["start_v"].get())
            e = max(str_to_sec(r["end_v"].get()), s + 0.15)
            
            # Clamping estrito na duracao do video (nunca ultrapassa o video)
            if self.video_duration and self.video_duration > 0:
                s = min(s, max(0.0, self.video_duration - 0.15))
                e = min(e, self.video_duration)

            orig = r.get("orig_item", {})
            orig_words = orig.get("words", [])
            new_split = txt.split()

            orig_s = float(orig.get("start", s))
            orig_e = float(orig.get("end", e))
            orig_dur = max(0.05, orig_e - orig_s)
            new_dur = max(0.10, e - s)

            if orig_words and len(new_split) == len(orig_words):
                # REESCALA PROPORCIONALMENTE todas as palavras internas para o novo intervalo [s, e]!
                updated_words = []
                for w_idx, w_txt in enumerate(new_split):
                    old_w_start = float(orig_words[w_idx].get("start", orig_s))
                    old_w_end = float(orig_words[w_idx].get("end", orig_e))

                    # Proporcao relativa da palavra dentro do bloco original
                    ratio_s = (old_w_start - orig_s) / orig_dur
                    ratio_e = (old_w_end - orig_s) / orig_dur
                    ratio_s = max(0.0, min(1.0, ratio_s))
                    ratio_e = max(ratio_s + 0.05, min(1.0, ratio_e))

                    new_w_start = s + ratio_s * new_dur
                    new_w_end = s + ratio_e * new_dur

                    is_censored = bool(orig_words[w_idx].get("censored")) or ("*" in w_txt)

                    updated_words.append({
                        "word": w_txt,
                        "start": round(new_w_start, 3),
                        "end": round(new_w_end, 3),
                        "censored": is_censored
                    })
                final_items.append({
                    "start": s,
                    "end": e,
                    "text": txt,
                    "words": updated_words
                })
            else:
                interp = _interpolate_words(txt, s, e)
                for iw in interp:
                    w_t = iw.get("word", "")
                    if "*" in w_t:
                        iw["censored"] = True
                final_items.append({
                    "start": s,
                    "end": e,
                    "text": txt,
                    "words": interp
                })

        selected_style_label = self.style_var.get()
        selected_style_key = STYLE_KEY_MAP.get(selected_style_label, "smart_situational")
        selected_effect = self.effect_var.get()

        self.destroy()
        if self.on_confirm:
            self.on_confirm(final_items, selected_style_key, selected_effect)
