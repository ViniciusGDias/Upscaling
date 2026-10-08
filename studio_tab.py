"""
studio_tab.py - Aba Studio Pipeline
Pipeline completo de producao: Transcricao -> Legendas -> Watermarks -> CTA -> Musica
Aprende e replica o estilo visual do canal Animax automaticamente.
Inclui revisor de legendas com corretor automatico de nomes de anime e estilizacao dinamica de cores.
"""

import os
import sys
import re
import json
import threading
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any
import customtkinter as ctk
from tkinter import filedialog, messagebox
import icon_manager
import subtitle_preview_helper

from subtitle_editor_dialog import SubtitleEditorDialog, STYLE_KEY_MAP, STYLE_OPTIONS, EFFECT_OPTIONS, EFFECT_KEY_MAP
from subtitle_corrector import apply_corrections_to_items, correct_phrase
from censorship_editor_dialog import CensorshipEditorDialog
from video_preview_player import VideoPreviewPlayer
from video_trimmer import (
    parse_time_to_seconds,
    format_seconds_to_time,
    parse_exclusion_intervals,
    calculate_keep_intervals,
    is_trim_active,
    trim_video_file
)

COLORS = {
    "bg_dark": "#09090b",
    "bg_card": "#111113",
    "bg_card_hover": "#18181b",
    "accent_primary": "#8b5cf6",
    "accent_secondary": "#a78bfa",
    "accent_studio": "#7c3aed",
    "accent_studio_hover": "#6d28d9",
    "success": "#22c55e",
    "warning": "#f59e0b",
    "error": "#ef4444",
    "text_primary": "#fafafa",
    "text_secondary": "#a1a1aa",
    "text_muted": "#a1a1aa",
    "border": "#27272a",
    "border_active": "#7c3aed",
    "console_bg": "#050505",
    "console_text": "#a1a1aa",
}


def get_style_file_path() -> Path:
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        if (exe_dir / "user_style.json").exists():
            return exe_dir / "user_style.json"
        if (Path(__file__).parent / "user_style.json").exists():
            return Path(__file__).parent / "user_style.json"
        return exe_dir / "user_style.json"
    file_p = Path(__file__).parent / "user_style.json"
    if file_p.exists():
        return file_p
    cwd_p = Path.cwd() / "user_style.json"
    if cwd_p.exists():
        return cwd_p
    return file_p


STYLE_FILE = get_style_file_path()


def _load_style():
    p = get_style_file_path()
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


class StudioPipelineTab(ctk.CTkFrame):
    """Aba Studio Pipeline - producao automatizada com estilo Animax."""

    def __init__(self, parent, settings_manager=None, **kwargs):
        super().__init__(parent, fg_color=COLORS["bg_dark"], **kwargs)
        self.settings_manager = settings_manager
        self._processing = False
        self._cancel_flag = False
        def_music = ""
        def_assets_music = Path(__file__).resolve().parent / "assets" / "default_music.mp3"
        if def_assets_music.exists():
            def_music = str(def_assets_music)

        self.music_path = ctk.StringVar(value=def_music)
        self.title_text = ctk.StringVar(value="")
        self.include_subtitles = ctk.BooleanVar(value=True)
        self.include_watermark = ctk.BooleanVar(value=True)
        self.include_cta = ctk.BooleanVar(value=True)
        self.include_music = ctk.BooleanVar(value=bool(def_music))
        self.include_blur_sides = ctk.BooleanVar(value=True)
        self.review_subtitles = ctk.BooleanVar(value=True)
        self.subtitle_style_label = ctk.StringVar(value=STYLE_OPTIONS[0])
        self.subtitle_pop = ctk.StringVar(value=EFFECT_OPTIONS[0])
        self.music_start = ctk.StringVar(value="00:00")
        self.anti_copyright = ctk.BooleanVar(value=True)
        self.anti_copyright_mode = ctk.StringVar(value="Avançado (Pitch + EQ + Estéreo)")
        self.music_auto_ducking = ctk.BooleanVar(value=False)
        self.music_ducking_mode = ctk.StringVar(value="Cinema & Anime (Ultra Fluido -6dB)")
        self.censor_profanity = ctk.BooleanVar(value=True)
        self.censor_visual = ctk.BooleanVar(value=True)
        self.censor_blur_strength = ctk.StringVar(value="Médio (Recomendado)")
        self.censor_mode = ctk.StringVar(value="Interativo (Revisar & Ajustar Áreas)")
        self.custom_censor_regions: List[Dict[str, Any]] = []

        # Variáveis de Corte e Aparo de Vídeo (Início, Fim e Meio)
        self.trim_enabled = ctk.BooleanVar(value=False)
        self.trim_start = ctk.StringVar(value="0.0")
        self.trim_cut_end = ctk.StringVar(value="0.0")
        self.trim_end_at = ctk.StringVar(value="")
        self.trim_exclude = ctk.StringVar(value="")
        self.original_video_duration = 0.0
        self._active_trimmed_path: Optional[str] = None

        self.input_path = ctk.StringVar(value="")
        self.output_dir = ctk.StringVar(value="")

        self._anim_timer = None
        self._anim_frames = []
        self._anim_frame_idx = 0

        # Traces para atualização em tempo real do resumo de cortes
        self.trim_enabled.trace_add("write", lambda *a: self._update_trim_summary())
        self.trim_start.trace_add("write", lambda *a: self._update_trim_summary())
        self.trim_cut_end.trace_add("write", lambda *a: self._update_trim_summary())
        self.trim_end_at.trace_add("write", lambda *a: self._update_trim_summary())
        self.trim_exclude.trace_add("write", lambda *a: self._update_trim_summary())
        self.input_path.trace_add("write", lambda *a: self._on_input_path_changed())

        self._build_ui()

    def _build_ui(self):
        # Action buttons pinned at bottom for instant access
        btn_bar = ctk.CTkFrame(self, fg_color="transparent")
        btn_bar.pack(side="bottom", fill="x", padx=16, pady=(4, 16))
        btn_bar.grid_columnconfigure(0, weight=1)

        self.start_btn = ctk.CTkButton(
            btn_bar,
            text="INICIAR PIPELINE (1-CLIQUE)",
            image=icon_manager.get_icon("play", size=(16, 16), color="#09090b"), compound="left",
            height=48,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=COLORS["accent_studio"],
            hover_color=COLORS["accent_studio_hover"],
            command=self._start_pipeline
        )
        self.start_btn.grid(row=0, column=0, padx=(0, 8), pady=0, sticky="ew")

        self.review_btn = ctk.CTkButton(
            btn_bar,
            text="Transcrever & Revisar",
            image=icon_manager.get_icon("sparkle", size=(14, 14), color=COLORS["accent_studio"]), compound="left",
            height=48,
            width=200,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_card_hover"],
            border_width=1,
            border_color=COLORS["accent_studio"],
            text_color=COLORS["accent_secondary"],
            command=self._start_transcribe_and_review
        )
        self.review_btn.grid(row=0, column=1, padx=(0, 8), pady=0)

        self.cancel_btn = ctk.CTkButton(
            btn_bar, text="Cancelar", width=110, height=48,
            fg_color=COLORS["bg_card"], hover_color=COLORS["bg_card_hover"],
            text_color=COLORS["error"], font=ctk.CTkFont(size=14),
            command=self._cancel, state="disabled"
        )
        self.cancel_btn.grid(row=0, column=2, pady=0)

        # Scrollable area containing header, controls, and log
        self.scroll = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["accent_studio"]
        )
        self.scroll.pack(side="top", fill="both", expand=True)
        self.scroll.grid_columnconfigure(0, weight=1)

        # Header
        header = ctk.CTkFrame(self.scroll, fg_color=COLORS["bg_card"], corner_radius=12)
        header.grid(row=0, column=0, padx=16, pady=(12, 8), sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(header, text="Studio Pipeline", font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=COLORS["accent_secondary"]).grid(row=0, column=0, padx=20, pady=(14, 2), sticky="w")
        ctk.CTkLabel(header, text="Producao automatica com seu estilo Animax - legendas dinamicas, watermarks e muito mais",
                     font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).grid(row=1, column=0, columnspan=2,
                                                                                            padx=20, pady=(0, 14), sticky="w")

        # Style status
        style = _load_style()
        if style:
            meta = style.get("_meta", {})
            status_text = f"Estilo aprendido: {meta.get('analyzed_segments', 0)} segmentos | Fonte: {style.get('subtitle', {}).get('font_name', 'N/A')}"
            status_color = COLORS["success"]
        else:
            status_text = "Estilo calibrado ativo (Animax 187% Zoom + Watermark 62px)"
            status_color = COLORS["success"]

        self.style_status_label = ctk.CTkLabel(header, text=status_text, font=ctk.CTkFont(size=11),
                                                text_color=status_color)
        self.style_status_label.grid(row=0, column=1, padx=20, pady=(14, 2), sticky="e")

        train_btn = ctk.CTkButton(header, text="Treinar IA", width=110, height=32,
                                   image=icon_manager.get_icon("sparkle", size=(13, 13), color="#09090b"), compound="left",
                                   fg_color=COLORS["accent_studio"], hover_color=COLORS["accent_studio_hover"],
                                   font=ctk.CTkFont(size=12, weight="bold"),
                                   command=self._run_training)
        train_btn.grid(row=1, column=1, padx=20, pady=(0, 14), sticky="e")

        # Input/Output section
        io_frame = ctk.CTkFrame(self.scroll, fg_color=COLORS["bg_card"], corner_radius=12)
        io_frame.grid(row=1, column=0, padx=16, pady=8, sticky="ew")
        io_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(io_frame, text="Arquivo de Entrada", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=COLORS["text_primary"]).grid(row=0, column=0, columnspan=3, padx=16, pady=(14, 4), sticky="w")

        self.input_entry = ctk.CTkEntry(io_frame, textvariable=self.input_path, height=38,
                                         placeholder_text="Selecione o video MP4...",
                                         fg_color=COLORS["bg_dark"], border_color=COLORS["border"])
        self.input_entry.grid(row=1, column=0, columnspan=2, padx=(16, 4), pady=(0, 8), sticky="ew")
        ctk.CTkButton(io_frame, text="Abrir", width=85, height=38,
                       image=icon_manager.get_icon("folder", size=(14, 14), color="#09090b"), compound="left",
                       fg_color=COLORS["accent_studio"], hover_color=COLORS["accent_studio_hover"],
                       command=self._browse_input).grid(row=1, column=2, padx=(0, 16), pady=(0, 8))

        ctk.CTkLabel(io_frame, text="Titulo do Video", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=COLORS["text_primary"]).grid(row=2, column=0, columnspan=3, padx=16, pady=(4, 4), sticky="w")
        self.title_entry = ctk.CTkEntry(io_frame, textvariable=self.title_text, height=38,
                                         placeholder_text="Ex: A Anya foi BOMBÁSTICA! (aparece no topo do video)",
                                         fg_color=COLORS["bg_dark"], border_color=COLORS["border"])
        self.title_entry.grid(row=3, column=0, columnspan=3, padx=16, pady=(0, 10), sticky="ew")

        # Cache Control Row
        cache_row = ctk.CTkFrame(io_frame, fg_color=COLORS["bg_dark"], corner_radius=10)
        cache_row.grid(row=4, column=0, columnspan=3, padx=16, pady=(0, 10), sticky="ew")
        cache_row.grid_columnconfigure(0, weight=1)

        cache_left = ctk.CTkFrame(cache_row, fg_color="transparent")
        cache_left.grid(row=0, column=0, padx=12, pady=6, sticky="w")

        self.cache_status_badge = ctk.CTkLabel(
            cache_left,
            text="[CACHE 24H: PRONTO]",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLORS["accent_secondary"]
        )
        self.cache_status_badge.pack(side="left")

        ctk.CTkLabel(
            cache_left,
            text="(reutiliza transcrições e análises para economizar tokens)",
            font=ctk.CTkFont(size=10),
            text_color=COLORS["text_secondary"]
        ).pack(side="left", padx=4)

        self.clear_cache_btn = ctk.CTkButton(
            cache_row,
            text="Forçar Nova Geração (Limpar Cache)",
            image=icon_manager.get_icon("trash", size=(13, 13), color=COLORS["warning"]), compound="left",
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_card_hover"],
            border_width=1,
            border_color=COLORS["border"],
            text_color=COLORS["warning"],
            command=self._clear_cache_for_video
        )
        self.clear_cache_btn.grid(row=0, column=1, padx=(4, 12), pady=6, sticky="e")

        # Trim & Cut Section (Cortar Inicio / Final / Meio)
        trim_card = ctk.CTkFrame(io_frame, fg_color=COLORS["bg_dark"], corner_radius=10)
        trim_card.grid(row=5, column=0, columnspan=3, padx=16, pady=(0, 14), sticky="ew")
        trim_card.grid_columnconfigure((1, 3, 5), weight=1)

        # Linha 0: Switch de Ativação + Presets Rápidos
        header_trim = ctk.CTkFrame(trim_card, fg_color="transparent")
        header_trim.grid(row=0, column=0, columnspan=6, padx=14, pady=(10, 6), sticky="ew")
        header_trim.grid_columnconfigure(0, weight=1)

        ctk.CTkSwitch(
            header_trim,
            text="Cortar Trechos Indesejados (Início / Fim / Meio)",
            variable=self.trim_enabled,
            progress_color=COLORS["accent_studio"],
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_primary"]
        ).grid(row=0, column=0, sticky="w")

        # Presets rápidos de corte
        presets_bar = ctk.CTkFrame(header_trim, fg_color="transparent")
        presets_bar.grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(presets_bar, text="Atalhos:", font=ctk.CTkFont(size=11), text_color=COLORS["text_secondary"]).pack(side="left", padx=(0, 6))
        ctk.CTkButton(presets_bar, text="-2s Fim", width=62, height=24, font=ctk.CTkFont(size=10, weight="bold"),
                       fg_color=COLORS["bg_card"], hover_color=COLORS["bg_card_hover"],
                       command=lambda: self._quick_set_cut_end(2.0)).pack(side="left", padx=2)
        ctk.CTkButton(presets_bar, text="-3s Fim", width=62, height=24, font=ctk.CTkFont(size=10),
                       fg_color=COLORS["bg_card"], hover_color=COLORS["bg_card_hover"],
                       command=lambda: self._quick_set_cut_end(3.0)).pack(side="left", padx=2)
        ctk.CTkButton(presets_bar, text="-5s Fim", width=62, height=24, font=ctk.CTkFont(size=10),
                       fg_color=COLORS["bg_card"], hover_color=COLORS["bg_card_hover"],
                       command=lambda: self._quick_set_cut_end(5.0)).pack(side="left", padx=2)
        ctk.CTkButton(presets_bar, text="Limpar", width=56, height=24, font=ctk.CTkFont(size=10),
                       fg_color=COLORS["bg_card"], hover_color=COLORS["bg_card_hover"],
                       text_color=COLORS["error"],
                       command=self._reset_trim).pack(side="left", padx=(4, 0))

        # Linha 1: Campos de entrada (Cortar Início, Cortar Final, Excluir Meio)
        inputs_row = ctk.CTkFrame(trim_card, fg_color="transparent")
        inputs_row.grid(row=1, column=0, columnspan=6, padx=14, pady=(2, 6), sticky="ew")
        inputs_row.grid_columnconfigure((1, 3, 5), weight=1)

        # 1. Pular início
        ctk.CTkLabel(inputs_row, text="Cortar Início:", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=COLORS["text_secondary"]).grid(row=0, column=0, padx=(0, 4), sticky="w")
        self.trim_start_entry = ctk.CTkEntry(inputs_row, textvariable=self.trim_start, width=70, height=28,
                                              font=ctk.CTkFont(family="Consolas", size=11),
                                              placeholder_text="0.0",
                                              fg_color=COLORS["bg_card"], border_color=COLORS["border"])
        self.trim_start_entry.grid(row=0, column=1, padx=(0, 12), sticky="ew")

        # 2. Cortar do final
        ctk.CTkLabel(inputs_row, text="Cortar do Fim:", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=COLORS["text_secondary"]).grid(row=0, column=2, padx=(0, 4), sticky="w")
        self.trim_cut_end_entry = ctk.CTkEntry(inputs_row, textvariable=self.trim_cut_end, width=70, height=28,
                                                font=ctk.CTkFont(family="Consolas", size=11),
                                                placeholder_text="2.0",
                                                fg_color=COLORS["bg_card"], border_color=COLORS["border"])
        self.trim_cut_end_entry.grid(row=0, column=3, padx=(0, 12), sticky="ew")

        # 3. Excluir do meio
        ctk.CTkLabel(inputs_row, text="Excluir do Meio:", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=COLORS["text_secondary"]).grid(row=0, column=4, padx=(0, 4), sticky="w")
        self.trim_exclude_entry = ctk.CTkEntry(inputs_row, textvariable=self.trim_exclude, height=28,
                                                font=ctk.CTkFont(family="Consolas", size=11),
                                                placeholder_text="Ex: 00:15-00:18 ou 15-18",
                                                fg_color=COLORS["bg_card"], border_color=COLORS["border"])
        self.trim_exclude_entry.grid(row=0, column=5, sticky="ew")

        # Linha 2: Resumo em tempo real e dica
        summary_row = ctk.CTkFrame(trim_card, fg_color="transparent")
        summary_row.grid(row=2, column=0, columnspan=6, padx=14, pady=(2, 10), sticky="ew")
        summary_row.grid_columnconfigure(0, weight=1)

        self.trim_summary_label = ctk.CTkLabel(
            summary_row,
            text="Duração do vídeo: Nenhum vídeo selecionado.",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLORS["text_secondary"]
        )
        self.trim_summary_label.grid(row=0, column=0, sticky="w")

        hint_label = ctk.CTkLabel(
            summary_row,
            text="Dica: Digite '2' em Cortar do Fim para remover os 2s finais. Em Excluir do Meio, use '00:15-00:18'.",
            font=ctk.CTkFont(size=10),
            text_color=COLORS["text_muted"]
        )
        hint_label.grid(row=1, column=0, sticky="w", pady=(2, 0))

        # Steps section
        steps_frame = ctk.CTkFrame(self.scroll, fg_color=COLORS["bg_card"], corner_radius=12)
        steps_frame.grid(row=2, column=0, padx=16, pady=8, sticky="ew")
        steps_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        ctk.CTkLabel(steps_frame, text="Etapas do Pipeline", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=COLORS["text_primary"]).grid(row=0, column=0, columnspan=4, padx=16, pady=(14, 8), sticky="w")

        # Step toggles
        self._build_step_toggle(steps_frame, 1, 0, "Legendas IA", "Transcricao automatica\nWhisper + Cores CapCut", self.include_subtitles, "#00FFFF")
        self._build_step_toggle(steps_frame, 1, 1, "Blur Lateral", "Fundo desfocado\nestilo Animax (187%)", self.include_blur_sides, "#7c3aed")
        self._build_step_toggle(steps_frame, 1, 2, "Watermarks", "@ANIMAX_97 (62px)\n+ Foto perfil circular", self.include_watermark, "#f59e0b")
        self._build_step_toggle(steps_frame, 1, 3, "CTA Bar", "Barra de Inscrição\n'Se inscreve no canal'", self.include_cta, "#22c55e")

        # Row 2: Player de Vídeo Embutido (Acima das legendas para conferência)
        player_container = ctk.CTkFrame(steps_frame, fg_color=COLORS["bg_dark"], corner_radius=10, border_width=1, border_color=COLORS["border"])
        player_container.grid(row=2, column=0, columnspan=4, padx=16, pady=(6, 8), sticky="ew")
        player_container.grid_columnconfigure(0, weight=1)

        p_header = ctk.CTkFrame(player_container, fg_color="transparent")
        p_header.grid(row=0, column=0, padx=14, pady=(8, 2), sticky="ew")
        p_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            p_header,
            text="🎬 Player de Vídeo (Conferência de Legendas & Cortes):",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["accent_secondary"]
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            p_header,
            text="Assista ao vídeo e confira as falas em tempo real",
            font=ctk.CTkFont(size=10),
            text_color=COLORS["text_secondary"]
        ).grid(row=0, column=1, sticky="e")

        self.preview_player = VideoPreviewPlayer(
            player_container,
            max_width=440,
            max_height=240
        )
        self.preview_player.grid(row=1, column=0, padx=10, pady=(2, 10))

        # Row 3: Subtitle Style & Review Bar
        sub_bar = ctk.CTkFrame(steps_frame, fg_color=COLORS["bg_dark"], corner_radius=8)
        sub_bar.grid(row=3, column=0, columnspan=4, padx=16, pady=(6, 8), sticky="ew")
        sub_bar.grid_columnconfigure(0, weight=1)

        ctk.CTkCheckBox(
            sub_bar,
            text="Revisar Falas / Nomes antes de renderizar",
            variable=self.review_subtitles,
            fg_color=COLORS["accent_studio"],
            font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=0, column=0, padx=14, pady=8, sticky="w")

        ctk.CTkLabel(sub_bar, text="Estilo:", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=COLORS["text_secondary"]).grid(row=0, column=1, padx=(10, 4), pady=8)

        self.style_dropdown = ctk.CTkOptionMenu(
            sub_bar,
            values=STYLE_OPTIONS,
            variable=self.subtitle_style_label,
            command=self._on_style_changed,
            width=290,
            height=28,
            fg_color=COLORS["bg_card"],
            button_color=COLORS["border"],
            dropdown_fg_color=COLORS["bg_card"]
        )
        self.style_dropdown.grid(row=0, column=2, padx=4, pady=8)

        ctk.CTkLabel(sub_bar, text="Efeito:", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=COLORS["text_secondary"]).grid(row=0, column=3, padx=(10, 4), pady=8, sticky="e")

        self.effect_dropdown = ctk.CTkOptionMenu(
            sub_bar,
            values=EFFECT_OPTIONS,
            variable=self.subtitle_pop,
            width=230,
            height=28,
            fg_color=COLORS["bg_card"],
            button_color=COLORS["border"],
            dropdown_fg_color=COLORS["bg_card"]
        )
        self.effect_dropdown.grid(row=0, column=4, padx=(4, 14), pady=8, sticky="e")

        # Row 1: Live Subtitle Style Preview Card
        self.preview_card = ctk.CTkFrame(sub_bar, fg_color=COLORS["bg_card"], corner_radius=6, border_width=1, border_color=COLORS["border"])
        self.preview_card.grid(row=1, column=0, columnspan=5, padx=14, pady=(0, 10), sticky="ew")
        self.preview_card.grid_columnconfigure(2, weight=1)

        self.lbl_preview_badge = ctk.CTkLabel(
            self.preview_card,
            text="IA ADAPTATIVA",
            font=ctk.CTkFont(size=9, weight="bold"),
            fg_color=COLORS["accent_studio"],
            text_color="#ffffff",
            corner_radius=4,
            width=115,
            height=24
        )
        self.lbl_preview_badge.grid(row=0, column=0, padx=(10, 8), pady=8)

        self.lbl_preview_img = ctk.CTkLabel(
            self.preview_card,
            text="",
            image=None
        )
        self.lbl_preview_img.grid(row=0, column=1, padx=6, pady=6, sticky="w")

        self.lbl_preview_desc = ctk.CTkLabel(
            self.preview_card,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_secondary"],
            anchor="w"
        )
        self.lbl_preview_desc.grid(row=0, column=2, padx=(8, 10), pady=8, sticky="ew")

        self.lbl_anim_live = ctk.CTkLabel(
            self.preview_card,
            text="● AO VIVO",
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=COLORS["success"]
        )
        self.lbl_anim_live.grid(row=0, column=3, padx=(0, 14), pady=8, sticky="e")

        # Inicializa o preview da legenda
        self._on_style_changed()

        # Row 4: Music section
        music_frame = ctk.CTkFrame(steps_frame, fg_color=COLORS["bg_dark"], corner_radius=8)
        music_frame.grid(row=4, column=0, columnspan=4, padx=16, pady=(4, 14), sticky="ew")
        music_frame.grid_columnconfigure(2, weight=1)

        # Linha 0: Toggle + Arquivo MP3 + Botao
        ctk.CTkSwitch(music_frame, text="Música de Fundo", variable=self.include_music,
                      progress_color=COLORS["accent_studio"], font=ctk.CTkFont(size=12, weight="bold"),
                      text_color=COLORS["text_primary"]).grid(row=0, column=0, padx=16, pady=(10, 6))
        self.music_entry = ctk.CTkEntry(music_frame, textvariable=self.music_path, height=32,
                                         placeholder_text="Selecione MP3/WAV...",
                                         fg_color=COLORS["bg_card"], border_color=COLORS["border"])
        self.music_entry.grid(row=0, column=1, columnspan=2, padx=(0, 4), pady=(10, 6), sticky="ew")
        ctk.CTkButton(music_frame, text="MP3", width=60, height=32,
                      fg_color=COLORS["bg_card_hover"],
                      command=self._browse_music).grid(row=0, column=3, padx=(0, 16), pady=(10, 6))

        # Linha 1: Ponto de Inicio (Pular Intro) + Slider de Volume
        row1_frame = ctk.CTkFrame(music_frame, fg_color="transparent")
        row1_frame.grid(row=1, column=0, columnspan=4, padx=16, pady=(2, 6), sticky="ew")
        row1_frame.grid_columnconfigure(4, weight=1)

        ctk.CTkLabel(row1_frame, text="Iniciar aos:", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=COLORS["text_secondary"]).grid(row=0, column=0, padx=(0, 4), sticky="w")
        self.music_start_entry = ctk.CTkEntry(row1_frame, textvariable=self.music_start, width=72, height=28,
                                               font=ctk.CTkFont(family="Consolas", size=11),
                                               placeholder_text="00:10",
                                               fg_color=COLORS["bg_card"], border_color=COLORS["border"])
        self.music_start_entry.grid(row=0, column=1, padx=(0, 6), sticky="w")
        ctk.CTkLabel(row1_frame, text="(pula intro)", font=ctk.CTkFont(size=11),
                     text_color=COLORS["text_muted"]).grid(row=0, column=2, padx=(0, 18), sticky="w")

        def _set_preset_vol(val):
            self.music_volume_slider.set(val)
            _update_vol_label(val)

        def _update_vol_label(v):
            val = int(float(v))
            if self.music_auto_ducking.get():
                self.music_volume_label.configure(text=f"Clímax: {val}%")
                if hasattr(self, 'music_ducking_menu'):
                    self.music_ducking_menu.configure(state="normal")
                if hasattr(self, 'ducking_hint_label'):
                    self.ducking_hint_label.configure(text="Auto Ducking Fluido: Música calibrada com base no vídeo, transição suave (1.2s) sem cortes secos.")
            else:
                self.music_volume_label.configure(text=f"Vol Fixo: {val}%")
                if hasattr(self, 'music_ducking_menu'):
                    self.music_ducking_menu.configure(state="disabled")
                if hasattr(self, 'ducking_hint_label'):
                    self.ducking_hint_label.configure(text="Modo Fixo (Constante): Volume equilibrado ao vídeo (Voice Carve EQ) — sem oscilar na fala.")

        self._update_vol_label = _update_vol_label

        self.music_volume_label = ctk.CTkLabel(row1_frame, text="Vol Fixo: 15%", font=ctk.CTkFont(size=11, weight="bold"),
                                                text_color=COLORS["text_secondary"])
        self.music_volume_label.grid(row=0, column=3, padx=(0, 8), sticky="w")
        self.music_volume_slider = ctk.CTkSlider(row1_frame, from_=0, to=100, number_of_steps=20,
                                                  progress_color=COLORS["accent_studio"])
        self.music_volume_slider.set(15)
        self.music_volume_slider.configure(command=_update_vol_label)
        self.music_volume_slider.grid(row=0, column=4, sticky="ew")

        # Botoes de Presets Rapidos de Volume
        preset_frame = ctk.CTkFrame(row1_frame, fg_color="transparent")
        preset_frame.grid(row=0, column=5, padx=(8, 0), sticky="e")
        ctk.CTkButton(preset_frame, text="12% Suave", width=70, height=24,
                      font=ctk.CTkFont(size=10), fg_color=COLORS["bg_card"],
                      command=lambda: _set_preset_vol(12)).pack(side="left", padx=2)
        ctk.CTkButton(preset_frame, text="15% Ideal (Voz)", width=86, height=24,
                      font=ctk.CTkFont(size=10, weight="bold"), fg_color=COLORS["accent_studio"],
                      command=lambda: _set_preset_vol(15)).pack(side="left", padx=2)
        ctk.CTkButton(preset_frame, text="22% Alto", width=64, height=24,
                      font=ctk.CTkFont(size=10), fg_color=COLORS["bg_card"],
                      command=lambda: _set_preset_vol(22)).pack(side="left", padx=2)

        # Linha 2: Protecao Anti-Copyright 2026 (Bypass Content ID)
        row2_frame = ctk.CTkFrame(music_frame, fg_color="transparent")
        row2_frame.grid(row=2, column=0, columnspan=4, padx=16, pady=(2, 4), sticky="ew")
        row2_frame.grid_columnconfigure(2, weight=1)

        ctk.CTkSwitch(row2_frame, text="Anti-Copyright 2026", variable=self.anti_copyright,
                      progress_color=COLORS["accent_studio"], font=ctk.CTkFont(size=12, weight="bold"),
                      text_color=COLORS["text_primary"]).grid(row=0, column=0, padx=(0, 10), sticky="w")

        self.anti_cp_menu = ctk.CTkOptionMenu(
            row2_frame,
            values=[
                "Leve (Micro-Pitch)",
                "Avançado (Pitch + EQ + Estéreo)",
                "Agressivo (Bypass Máximo)"
            ],
            variable=self.anti_copyright_mode,
            width=230,
            height=28,
            fg_color=COLORS["bg_card"],
            button_color=COLORS["border"],
            dropdown_fg_color=COLORS["bg_card"]
        )
        self.anti_cp_menu.grid(row=0, column=1, padx=(0, 8), sticky="w")

        ctk.CTkLabel(
            row2_frame,
            text="Altera micro-afinação (+3.8%), tempo e fase estéreo para impedir Content ID do YouTube/TikTok.",
            font=ctk.CTkFont(size=10),
            text_color=COLORS["text_secondary"]
        ).grid(row=0, column=2, padx=(8, 0), sticky="w")

        # Linha 3: Auto Ducking Opcional (Desmarcado por padrao para quem prefere volume estavel sem oscilar)
        row3_frame = ctk.CTkFrame(music_frame, fg_color="transparent")
        row3_frame.grid(row=3, column=0, columnspan=4, padx=16, pady=(2, 8), sticky="ew")
        row3_frame.grid_columnconfigure(2, weight=1)

        ctk.CTkSwitch(row3_frame, text="Auto Ducking (Variar com a fala)", variable=self.music_auto_ducking,
                      command=lambda: _update_vol_label(self.music_volume_slider.get()),
                      progress_color=COLORS["accent_studio"], font=ctk.CTkFont(size=12, weight="bold"),
                      text_color=COLORS["text_primary"]).grid(row=0, column=0, padx=(0, 10), sticky="w")

        self.music_ducking_menu = ctk.CTkOptionMenu(
            row3_frame,
            values=[
                "Cinema & Anime (Ultra Fluido -6dB)",
                "Equilibrado (Transição Suave -9dB)",
                "Foco Total na Voz (Voz Firme -12dB)"
            ],
            variable=self.music_ducking_mode,
            width=245,
            height=28,
            state="disabled",
            fg_color=COLORS["bg_card"],
            button_color=COLORS["border"],
            dropdown_fg_color=COLORS["bg_card"]
        )
        self.music_ducking_menu.grid(row=0, column=1, padx=(0, 8), sticky="w")

        self.ducking_hint_label = ctk.CTkLabel(
            row3_frame,
            text="Modo Fixo (Constante): Volume equilibrado ao vídeo (Voice Carve EQ) — sem oscilar na fala.",
            font=ctk.CTkFont(size=10),
            text_color=COLORS["text_secondary"]
        )
        self.ducking_hint_label.grid(row=0, column=2, padx=(8, 0), sticky="w")

        # Row 5: Protecao Anti-Strike & Censura Inteligente (Anime Shield 2026)
        safety_frame = ctk.CTkFrame(steps_frame, fg_color=COLORS["bg_dark"], corner_radius=8)
        safety_frame.grid(row=5, column=0, columnspan=4, padx=16, pady=(4, 14), sticky="ew")
        safety_frame.grid_columnconfigure((0, 1), weight=1)

        # Header do Shield
        shield_row0 = ctk.CTkFrame(safety_frame, fg_color="transparent")
        shield_row0.grid(row=0, column=0, columnspan=2, padx=16, pady=(10, 4), sticky="ew")
        ctk.CTkLabel(shield_row0, text="Anime Shield 2026 — Proteção Anti-Strike & Censura",
                     font=ctk.CTkFont(size=12, weight="bold"), text_color=COLORS["text_primary"]).pack(side="left")
        ctk.CTkLabel(shield_row0, text="(Evita desmonetização e shadowban no Shorts/TikTok/Reels)",
                     font=ctk.CTkFont(size=11), text_color=COLORS["text_muted"]).pack(side="left", padx=10)

        # Linha 1: Switches
        shield_row1 = ctk.CTkFrame(safety_frame, fg_color="transparent")
        shield_row1.grid(row=1, column=0, columnspan=2, padx=16, pady=(2, 10), sticky="ew")
        shield_row1.grid_columnconfigure((0, 1, 2), weight=1)

        ctk.CTkSwitch(shield_row1, text="Censurar Palavrões (Mudo + Legendas)", variable=self.censor_profanity,
                      progress_color=COLORS["accent_studio"], font=ctk.CTkFont(size=12),
                      text_color=COLORS["text_primary"]).grid(row=0, column=0, padx=(0, 15), sticky="w")

        ctk.CTkSwitch(shield_row1, text="Censura Visual (Blur em Busto & Partes Íntimas)", variable=self.censor_visual,
                      progress_color=COLORS["accent_studio"], font=ctk.CTkFont(size=12),
                      text_color=COLORS["text_primary"]).grid(row=0, column=1, padx=(0, 15), sticky="w")

        blur_menu_frame = ctk.CTkFrame(shield_row1, fg_color="transparent")
        blur_menu_frame.grid(row=0, column=2, sticky="e")
        ctk.CTkLabel(blur_menu_frame, text="Blur:", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=COLORS["text_secondary"]).pack(side="left", padx=(0, 6))
        ctk.CTkOptionMenu(
            blur_menu_frame,
            values=["Suave", "Médio (Recomendado)", "Forte"],
            variable=self.censor_blur_strength,
            width=180,
            height=28,
            fg_color=COLORS["bg_card"],
            button_color=COLORS["border"],
            dropdown_fg_color=COLORS["bg_card"]
        ).pack(side="left")

        # Linha 2: Modo e Botao de Ajuste Interativo/Manual
        shield_row2 = ctk.CTkFrame(safety_frame, fg_color="transparent")
        shield_row2.grid(row=2, column=0, columnspan=2, padx=16, pady=(0, 10), sticky="ew")
        shield_row2.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(shield_row2, text="Modo:", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=COLORS["text_secondary"]).grid(row=0, column=0, padx=(0, 8), sticky="w")

        self.censor_mode_menu = ctk.CTkOptionMenu(
            shield_row2,
            values=[
                "Interativo (Revisar & Ajustar Áreas)",
                "100% Automático (IA Anime Shield)",
                "Manual (Definir Intervalos)"
            ],
            variable=self.censor_mode,
            width=270,
            height=28,
            fg_color=COLORS["bg_card"],
            button_color=COLORS["border"],
            dropdown_fg_color=COLORS["bg_card"]
        )
        self.censor_mode_menu.grid(row=0, column=1, padx=(0, 10), sticky="w")

        self.edit_censor_btn = ctk.CTkButton(
            shield_row2,
            text="Ajustar Censura Visual...",
            image=icon_manager.get_icon("shield", size=(14, 14)), compound="left",
            height=28,
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_card_hover"],
            border_width=1,
            border_color=COLORS["accent_studio"],
            text_color=COLORS["accent_secondary"],
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._open_censorship_editor
        )
        self.edit_censor_btn.grid(row=0, column=2, padx=(8, 0), sticky="e")

        # Console
        console_frame = ctk.CTkFrame(self.scroll, fg_color=COLORS["bg_card"], corner_radius=12)
        console_frame.grid(row=3, column=0, padx=16, pady=(8, 16), sticky="nsew")
        console_frame.grid_rowconfigure(1, weight=1)
        console_frame.grid_columnconfigure(0, weight=1)

        top_bar = ctk.CTkFrame(console_frame, fg_color="transparent")
        top_bar.grid(row=0, column=0, padx=16, pady=(14, 4), sticky="ew")
        top_bar.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(top_bar, text="Log de Processamento", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=COLORS["text_primary"]).grid(row=0, column=0, sticky="w")

        self.progress_bar = ctk.CTkProgressBar(top_bar, height=6, progress_color=COLORS["accent_secondary"],
                                                fg_color=COLORS["bg_dark"])
        self.progress_bar.set(0)
        self.progress_bar.grid(row=1, column=0, columnspan=3, pady=(6, 0), sticky="ew")

        self.progress_label = ctk.CTkLabel(top_bar, text="Pronto", font=ctk.CTkFont(size=11),
                                            text_color=COLORS["text_secondary"])
        self.progress_label.grid(row=0, column=1, padx=8, sticky="e")

        self.console = ctk.CTkTextbox(console_frame, height=140, fg_color=COLORS["console_bg"],
                                       text_color=COLORS["console_text"],
                                       font=ctk.CTkFont(family="Consolas", size=11),
                                       state="disabled", wrap="word")
        self.console.grid(row=1, column=0, padx=16, pady=(4, 8), sticky="nsew")

    def _build_step_toggle(self, parent, row, col, title, desc, var, color):
        frame = ctk.CTkFrame(parent, fg_color=COLORS["bg_dark"], corner_radius=10)
        frame.grid(row=row, column=col, padx=6, pady=4, sticky="nsew")
        ctk.CTkSwitch(frame, text=title, variable=var, progress_color=color,
                       font=ctk.CTkFont(size=12, weight="bold"),
                       text_color=COLORS["text_primary"]).pack(padx=12, pady=(12, 4), anchor="w")
        ctk.CTkLabel(frame, text=desc, font=ctk.CTkFont(size=10),
                     text_color=COLORS["text_secondary"], justify="left").pack(padx=12, pady=(0, 12), anchor="w")

    def _on_style_changed(self, choice=None):
        """Atualiza a pré-visualização visual e animada do estilo de legenda em tempo real."""
        try:
            if getattr(self, "_anim_timer", None):
                try:
                    self.after_cancel(self._anim_timer)
                except Exception:
                    pass
                self._anim_timer = None

            style_label = self.subtitle_style_label.get()
            style_key = STYLE_KEY_MAP.get(style_label, "smart_situational")
            meta = subtitle_preview_helper.get_style_info(style_key)
            self.lbl_preview_badge.configure(text=meta.get("badge", "ESTILO"))
            self.lbl_preview_desc.configure(text=meta.get("tagline", ""))

            self._anim_frames = subtitle_preview_helper.get_preview_animation_frames(style_key, width=320, height=44, num_frames=14)
            self._anim_frame_idx = 0
            if self._anim_frames:
                self.lbl_preview_img.configure(image=self._anim_frames[0])
                self.lbl_preview_img.image = self._anim_frames[0]
                self._tick_preview_animation()
            else:
                p_img = subtitle_preview_helper.render_subtitle_preview_image(style_key, width=320, height=44)
                self.lbl_preview_img.configure(image=p_img)
                self.lbl_preview_img.image = p_img
        except Exception:
            pass

    def _tick_preview_animation(self):
        try:
            if not self.winfo_exists():
                return
            if not getattr(self, "_anim_frames", None):
                return
            self._anim_frame_idx = (self._anim_frame_idx + 1) % len(self._anim_frames)
            frame = self._anim_frames[self._anim_frame_idx]
            self.lbl_preview_img.configure(image=frame)
            self.lbl_preview_img.image = frame
            self._anim_timer = self.after(90, self._tick_preview_animation)
        except Exception:
            pass

    def _clear_cache_for_video(self):
        p = self.input_path.get().strip()
        if not p:
            messagebox.showinfo("Cache de IA", "Selecione um vídeo primeiro para limpar o cache.")
            return
        try:
            from ai_cache_hub import ai_cache
            ai_cache.invalidate(p)
            self._log(f"[CACHE] Cache de IA limpo para o vídeo: {Path(p).name}!")
            self._log("[IA] A próxima execução consultará a IA do zero (novas legendas, títulos e análises).")
            if hasattr(self, 'cache_status_badge'):
                self.cache_status_badge.configure(
                    text="[CACHE: LIMPO] (Geração do zero)",
                    text_color=COLORS["warning"]
                )
            messagebox.showinfo(
                "Cache Limpo",
                f"O cache deste vídeo foi limpo com sucesso!\n\n"
                f"A próxima vez que rodar a IA ou transcrever, uma nova versão será gerada do zero."
            )
        except Exception as e:
            self._log(f"Aviso ao limpar cache: {e}")

    def _browse_input(self):
        path = filedialog.askopenfilename(
            title="Selecione o video",
            filetypes=[("Video MP4", "*.mp4"), ("Todos", "*.*")]
        )
        if path:
            self.input_path.set(path)
            stem = Path(path).stem
            for bad_part in ["_mastercut", "_upscaled", "_original", "_final", "_part1", "_part2"]:
                stem = stem.replace(bad_part, "")
            stem = stem.replace("_", " ").strip()
            if not self.title_text.get():
                self.title_text.set(stem[:50].upper())
            self._on_input_path_changed()

    def _on_input_path_changed(self, *args):
        p = self.input_path.get().strip()
        if p and Path(p).exists():
            try:
                from subtitle_renderer import get_media_duration
                self.original_video_duration = get_media_duration(p)
            except Exception:
                self.original_video_duration = 0.0

            # Reutiliza título viral gerado pelo Diretor ou YouTube Shorts se o campo estiver vazio
            try:
                from ai_cache_hub import ai_cache
                has_cached_trans = ai_cache.has(p, "transcription") or ai_cache.has(p, "director_transcript")
                if hasattr(self, 'cache_status_badge'):
                    if has_cached_trans:
                        self.cache_status_badge.configure(
                            text="[CACHE 24H: ATIVO] (Falas prontas)",
                            text_color=COLORS["success"]
                        )
                    else:
                        self.cache_status_badge.configure(
                            text="[CACHE 24H: PRONTO]",
                            text_color=COLORS["accent_secondary"]
                        )

                viral_m = ai_cache.get(p, "viral_metadata")
                if viral_m and isinstance(viral_m, dict) and viral_m.get("title"):
                    curr_title = self.title_text.get().strip()
                    stem = Path(p).stem
                    for bad_part in ["_mastercut", "_upscaled", "_original", "_final", "_part1", "_part2"]:
                        stem = stem.replace(bad_part, "")
                    stem_clean = stem.replace("_", " ").strip().upper()
                    if not curr_title or curr_title == stem_clean[:50]:
                        self.title_text.set(str(viral_m["title"])[:65].upper())
                        self._log(f"[CACHE] Título viral importado automaticamente: {viral_m['title']}")
            except Exception:
                pass

            if hasattr(self, "preview_player"):
                self.preview_player.load_video(p)
        else:
            self.original_video_duration = 0.0
            if hasattr(self, "cache_status_badge"):
                self.cache_status_badge.configure(
                    text="[CACHE 24H: PRONTO]",
                    text_color=COLORS["accent_secondary"]
                )
            if hasattr(self, "preview_player"):
                self.preview_player.stop()
        self._update_trim_summary()

    def _update_trim_summary(self):
        if not hasattr(self, 'trim_summary_label'):
            return
        total_dur = self.original_video_duration
        if total_dur <= 0.0:
            self.trim_summary_label.configure(
                text="Duração do vídeo: Nenhum vídeo selecionado.",
                text_color=COLORS["text_secondary"]
            )
            return

        t_start = parse_time_to_seconds(self.trim_start.get())
        cut_end = parse_time_to_seconds(self.trim_cut_end.get())
        end_at_val = self.trim_end_at.get().strip()
        end_at = parse_time_to_seconds(end_at_val) if end_at_val else None
        excl = parse_exclusion_intervals(self.trim_exclude.get())

        is_enabled = self.trim_enabled.get()
        if not is_enabled:
            self.trim_summary_label.configure(
                text=f"Duração do vídeo: {total_dur:.1f}s ({format_seconds_to_time(total_dur)}) — [Corte Desativado]",
                text_color=COLORS["text_secondary"]
            )
            return

        keep, final_dur, removed_dur = calculate_keep_intervals(
            total_duration=total_dur,
            trim_start=t_start,
            cut_from_end=cut_end,
            end_at=end_at,
            exclude_intervals=excl
        )

        if final_dur <= 0.0:
            self.trim_summary_label.configure(
                text="[AVISO] ATENÇÃO: Os cortes removeriam 100% do vídeo! Ajuste os valores.",
                text_color=COLORS["error"]
            )
        elif removed_dur <= 0.05 and len(keep) == 1:
            self.trim_summary_label.configure(
                text=f"Duração do vídeo: {total_dur:.1f}s — Nenhum segundo cortado ainda.",
                text_color=COLORS["accent_secondary"]
            )
        else:
            details = []
            if t_start > 0:
                details.append(f"início: -{t_start:.1f}s")
            if cut_end > 0:
                details.append(f"final: -{cut_end:.1f}s")
            if end_at and end_at > 0:
                details.append(f"fim fixo: {end_at:.1f}s")
            if excl:
                details.append(f"{len(excl)} trecho(s) do meio")

            detail_str = f" ({', '.join(details)})" if details else ""
            self.trim_summary_label.configure(
                text=f"Original: {total_dur:.1f}s -> Vídeo Cortado: {final_dur:.1f}s (removidos {removed_dur:.1f}s){detail_str}",
                text_color=COLORS["success"]
            )

    def _quick_set_cut_end(self, seconds: float):
        self.trim_enabled.set(True)
        self.trim_cut_end.set(f"{seconds:.1f}")
        self._update_trim_summary()

    def _reset_trim(self):
        self.trim_start.set("0.0")
        self.trim_cut_end.set("0.0")
        self.trim_end_at.set("")
        self.trim_exclude.set("")
        self.trim_enabled.set(False)
        self._update_trim_summary()

    def _prepare_pipeline_video(self, raw_input_path: str) -> str:
        if not self.trim_enabled.get():
            return raw_input_path

        from subtitle_renderer import get_media_duration
        total_dur = self.original_video_duration or get_media_duration(raw_input_path)
        if total_dur <= 0.0:
            return raw_input_path

        t_start = parse_time_to_seconds(self.trim_start.get())
        cut_end = parse_time_to_seconds(self.trim_cut_end.get())
        end_at_val = self.trim_end_at.get().strip()
        end_at = parse_time_to_seconds(end_at_val) if end_at_val else None
        excl = parse_exclusion_intervals(self.trim_exclude.get())

        if not is_trim_active(total_dur, t_start, cut_end, end_at, excl):
            return raw_input_path

        keep, final_dur, removed_dur = calculate_keep_intervals(
            total_dur, t_start, cut_end, end_at, excl
        )
        if not keep:
            self._log("[AVISO] Configuração de corte removeria todo o vídeo. Prosseguindo com vídeo original.")
            return raw_input_path

        self._log("=" * 50)
        self._log("[CORTE CIRÚRGICO] Aplicando corte cirúrgico de vídeo (Início / Fim / Meio)...")
        self._log(f"[CORTE CIRÚRGICO] Duração original: {total_dur:.2f}s -> Duração resultante: {final_dur:.2f}s (removidos {removed_dur:.2f}s)")
        if t_start > 0:
            self._log(f"  • Pular início: primeiros {t_start:.2f}s descartados.")
        if cut_end > 0:
            self._log(f"  • Cortar do final: últimos {cut_end:.2f}s descartados.")
        if end_at and end_at > 0:
            self._log(f"  • Terminar exatamente aos: {end_at:.2f}s.")
        if excl:
            for s, e in excl:
                self._log(f"  • Trecho do meio excluído: {s:.2f}s até {e:.2f}s ({e - s:.2f}s removidos).")

        import tempfile
        tmp_trimmed = tempfile.NamedTemporaryFile(suffix="_trimmed.mp4", delete=False)
        tmp_trimmed.close()

        self._set_progress(5, "Aparando trechos do vídeo...")
        ok = trim_video_file(raw_input_path, tmp_trimmed.name, keep, on_log=self._log)
        if ok and os.path.exists(tmp_trimmed.name) and os.path.getsize(tmp_trimmed.name) > 1000:
            self._log("[OK] Vídeo recortado com sucesso! Sincronizando transcrição e legendas com a nova duração.")
            self._active_trimmed_path = tmp_trimmed.name
            return tmp_trimmed.name
        else:
            self._log("[AVISO] Falha ao aparar vídeo. Prosseguindo com o vídeo original.")
            return raw_input_path

    def _browse_music(self):
        path = filedialog.askopenfilename(
            title="Selecione a musica de fundo",
            filetypes=[("Audio", "*.mp3 *.wav *.m4a *.aac"), ("Todos", "*.*")]
        )
        if path:
            self.music_path.set(path)
            self.include_music.set(True)

    def _log(self, msg):
        def _append():
            self.console.configure(state="normal")
            self.console.insert("end", msg + "\n")
            self.console.see("end")
            self.console.configure(state="disabled")
        self.after(0, _append)

    def _set_progress(self, pct, label=""):
        def _update():
            self.progress_bar.set(pct / 100)
            if label:
                self.progress_label.configure(text=label)
        self.after(0, _update)

    def _run_training(self):
        def _train():
            self._log("Iniciando analise dos projetos CapCut...")
            self._log("Isso pode levar 1-2 minutos (inclui analise visual com Gemini Vision)...")
            try:
                import os as _os
                gemini_key = _os.environ.get("GEMINI_API_KEY", "").strip()
                if "," in gemini_key:
                    gemini_key = gemini_key.split(",")[0].strip()
                if not gemini_key:
                    self._log("Aviso: Chave Gemini nao encontrada - analise visual sera pulada")
                    self._log("Configure sua chave em: Configuracoes > Chaves API")
                from style_analyzer import run_analysis
                run_analysis(on_log=self._log, gemini_api_key=gemini_key or None)
                style = _load_style()
                if style:
                    meta = style.get("_meta", {})
                    status = f"Estilo aprendido: {meta.get('analyzed_segments', 0)} segmentos | Fonte: {style.get('subtitle', {}).get('font_name', 'N/A')}"
                    self.after(0, lambda: self.style_status_label.configure(
                        text=status, text_color=COLORS["success"]))
                    self._log("Treinamento concluido com sucesso!")
            except Exception as e:
                self._log(f"Erro no treinamento: {e}")
        threading.Thread(target=_train, daemon=True).start()

    def _transcribe_audio(self, input_path: str) -> List[Dict[str, Any]]:
        """Extrai audio e transcreve com Groq Whisper retornando timestamps de palavras sincronizados com cache 24h."""
        from subtitle_renderer import _find_ffmpeg, detect_speech_segments, clean_and_repair_whisper_words, get_media_duration
        from settings_manager import load_app_settings
        import tempfile
        import requests

        total_dur = get_media_duration(input_path)

        # 1. Verifica cache persistente 24h compartilhado entre abas
        try:
            from ai_cache_hub import ai_cache
            cached_trans = ai_cache.get(input_path, "transcription")
            if cached_trans and isinstance(cached_trans, dict):
                raw_c_words = cached_trans.get("words", [])
                if raw_c_words:
                    norm_words = []
                    for w in raw_c_words:
                        txt = w.get("word") if "word" in w else w.get("text", "")
                        norm_words.append({
                            "word": txt,
                            "text": txt,
                            "start": float(w.get("start", 0.0)),
                            "end": float(w.get("end", 0.0))
                        })
                    repaired = clean_and_repair_whisper_words(norm_words, max_duration=total_dur if total_dur > 0 else None)
                    if repaired:
                        self._log(f"[CACHE 24H] Transcrição Whisper recuperada instantaneamente ({len(repaired)} palavras, 0 tokens gastos)!")
                        if hasattr(self, 'cache_status_badge'):
                            self.cache_status_badge.configure(
                                text=f"[CACHE ATIVO: {len(repaired)} palavras]",
                                text_color=COLORS["success"]
                            )
                        return repaired
        except Exception:
            pass

        settings = load_app_settings()
        groq_key = settings.get("groq_key", "") or os.environ.get("GROQ_API_KEY", "").strip()
        if not groq_key:
            self._log("Aviso: Chave Groq nao encontrada em Configuracoes.")
            return []

        ffmpeg_bin = _find_ffmpeg()
        tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_wav.close()

        try:
            self._log("Extraindo faixa de voz para Whisper...")
            subprocess.run([
                ffmpeg_bin, "-i", input_path,
                "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                "-y", tmp_wav.name
            ], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

            # Segmentação VAD para isolar trechos de fala e eliminar drift temporal causado por música/cenas de ação
            speech_segments = detect_speech_segments(tmp_wav.name, min_silence_dur=0.6, silence_thresh_db=-26.0)
            headers = {"Authorization": f"Bearer {groq_key}"}

            if len(speech_segments) > 1:
                self._log(f"Segmentação VAD ativa: {len(speech_segments)} blocos de diálogo identificados.")
                all_words = []
                for s_idx, (st, en) in enumerate(speech_segments):
                    dur = en - st
                    if dur < 0.35:
                        continue
                    seg_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                    seg_wav.close()
                    try:
                        subprocess.run([
                            ffmpeg_bin, "-ss", f"{st:.2f}", "-t", f"{dur:.2f}", "-i", tmp_wav.name,
                            "-c:a", "copy", "-y", seg_wav.name
                        ], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

                        with open(seg_wav.name, "rb") as f:
                            files = {"file": (f"seg_{s_idx}.wav", f, "audio/wav")}
                            data = {
                                "model": "whisper-large-v3",
                                "response_format": "verbose_json",
                                "timestamp_granularities[]": "word",
                                "language": "pt",
                                "temperature": "0.0"
                            }
                            resp = requests.post(
                                "https://api.groq.com/openai/v1/audio/transcriptions",
                                headers=headers,
                                files=files,
                                data=data,
                                timeout=45
                            )
                        if resp.status_code == 200:
                            raw_words = resp.json().get("words", [])
                            for w in raw_words:
                                all_words.append({
                                    "word": w.get("word", ""),
                                    "start": round(st + float(w.get("start", 0.0)), 3),
                                    "end": round(st + float(w.get("end", 0.0)), 3)
                                })
                        else:
                            self._log(f"Aviso no segmento {s_idx} ({resp.status_code}): {resp.text[:100]}")
                    finally:
                        Path(seg_wav.name).unlink(missing_ok=True)

                if all_words:
                    repaired = clean_and_repair_whisper_words(all_words, max_duration=total_dur if total_dur > 0 else None)
                    self._log(f"Transcrição VAD concluída: {len(repaired)} palavras sincronizadas com precisão!")
                    try:
                        from ai_cache_hub import ai_cache
                        ai_cache.set(input_path, "transcription", {
                            "words": repaired,
                            "full_text": " ".join([w.get("word", "") for w in repaired]),
                            "duration": total_dur
                        })
                        if hasattr(self, 'cache_status_badge'):
                            self.cache_status_badge.configure(
                                text=f"[CACHE ATIVO: {len(repaired)} palavras]",
                                text_color=COLORS["success"]
                            )
                    except Exception:
                        pass
                    return repaired

            # Transcrição direta com modelo de alta precisão whisper-large-v3
            self._log("Enviando requisicao Whisper Groq (whisper-large-v3)...")
            with open(tmp_wav.name, "rb") as f:
                files = {"file": (Path(tmp_wav.name).name, f, "audio/wav")}
                data = {
                    "model": "whisper-large-v3",
                    "response_format": "verbose_json",
                    "timestamp_granularities[]": "word",
                    "language": "pt",
                    "temperature": "0.0"
                }
                resp = requests.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=60
                )

            if resp.status_code == 200:
                trans_json = resp.json()
                raw_words = trans_json.get("words", [])
                if raw_words:
                    words = [{"word": w.get("word", ""), "start": w.get("start", 0.0), "end": w.get("end", 0.0)} for w in raw_words]
                    repaired = clean_and_repair_whisper_words(words, max_duration=total_dur if total_dur > 0 else None)
                    self._log(f"Transcricao: {len(repaired)} palavras detectadas!")
                    try:
                        from ai_cache_hub import ai_cache
                        ai_cache.set(input_path, "transcription", {
                            "words": repaired,
                            "full_text": " ".join([w.get("word", "") for w in repaired]),
                            "duration": total_dur
                        })
                        if hasattr(self, 'cache_status_badge'):
                            self.cache_status_badge.configure(
                                text=f"[CACHE ATIVO: {len(repaired)} palavras]",
                                text_color=COLORS["success"]
                            )
                    except Exception:
                        pass
                    return repaired
                else:
                    self._log("Transcricao sem palavras detalhadas.")
            else:
                self._log(f"Erro na API Groq ({resp.status_code}): {resp.text[:150]}")
        finally:
            Path(tmp_wav.name).unlink(missing_ok=True)

        return []

    def _start_transcribe_and_review(self):
        """Disparado pelo botao 'Transcrever & Revisar'."""
        input_path = self.input_path.get().strip()
        if not input_path or not Path(input_path).exists():
            messagebox.showerror("Erro", "Selecione um arquivo de video valido primeiro.")
            return

        self._processing = True
        self.start_btn.configure(state="disabled")
        self.review_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")

        def _worker():
            try:
                from subtitle_renderer import group_whisper_words, get_media_duration

                # Prepara o vídeo recortado antes de transcrever (garantindo timing perfeito)
                work_video = self._prepare_pipeline_video(input_path)

                self._log("=" * 50)
                self._log("TRANSCREVENDO PARA REVISÃO...")
                self._set_progress(15, "Transcrevendo audio...")

                video_dur = get_media_duration(work_video)
                if video_dur > 0:
                    self._log(f"Duração exata do vídeo: {video_dur:.2f}s (teto máximo para legendas).")

                raw_words = self._transcribe_audio(work_video)
                if not raw_words:
                    self._log("Nenhuma fala detectada pelo Whisper ou erro de API.")
                    self.after(0, lambda: messagebox.showwarning("Aviso", "Nenhuma fala detectada para revisar."))
                    return

                chunks = group_whisper_words(raw_words, max_duration=video_dur if video_dur > 0 else None)
                # Auto-corrige nomes de anime imediatamente
                corrected_chunks = apply_corrections_to_items(chunks)
                self._log(f"Dicionario de Anime aplicado em {len(corrected_chunks)} falas.")

                self._set_progress(30, "Pronto para revisao")
                curr_style_key = STYLE_KEY_MAP.get(self.subtitle_style_label.get(), "dynamic_animax")
                curr_pop = self.subtitle_pop.get()

                m_path = self.music_path.get().strip() if self.include_music.get() else None
                m_vol = self.music_volume_slider.get() / 100.0
                m_start = self.music_start.get().strip()

                def _on_sub_approved(items, s_key, pop, final_m_vol=None):
                    if final_m_vol is not None:
                        val_pct = int(final_m_vol * 100)
                        self.music_volume_slider.set(val_pct)
                        if hasattr(self, '_update_vol_label'):
                            self._update_vol_label(val_pct)
                    self._on_subtitles_approved(work_video, items, s_key, pop, final_m_vol)

                def _on_vol_changed_in_modal(new_vol):
                    val_pct = int(new_vol * 100)
                    self.music_volume_slider.set(val_pct)
                    if hasattr(self, '_update_vol_label'):
                        self._update_vol_label(val_pct)

                anti_cp = self.anti_copyright.get()
                anti_mode_map = {
                    "Avançado (Pitch + EQ + Estéreo)": "advanced",
                    "Agressivo (Anti-Bloqueio Máximo)": "aggressive",
                    "Sutil (Apenas Harmônicos)": "subtle",
                }
                anti_mode_key = anti_mode_map.get(self.anti_copyright_mode.get(), "advanced")
                ducking_map = {
                    "Cinema & Anime (Ultra Fluido -6dB)": "cinema",
                    "Equilibrado (Recomendado -9dB)": "balanced",
                    "Forte (Voz em Destaque -14dB)": "aggressive",
                }
                ducking_key = ducking_map.get(self.music_ducking_mode.get(), "cinema")
                ducking_active = self.music_auto_ducking.get()

                # Abre a janela modal na thread principal passando o vídeo de trabalho e a música de fundo com ducking e anti-copyright
                self.after(0, lambda: SubtitleEditorDialog(
                    parent=self.winfo_toplevel(),
                    items=corrected_chunks,
                    on_confirm=_on_sub_approved,
                    current_style=curr_style_key,
                    current_pop=curr_pop,
                    video_duration=video_dur if video_dur > 0 else None,
                    video_path=work_video,
                    music_path=m_path,
                    music_volume=m_vol,
                    music_start=m_start,
                    music_auto_ducking=ducking_active,
                    ducking_mode=ducking_key,
                    anti_copyright=anti_cp,
                    anti_copyright_mode=anti_mode_key,
                    on_music_volume_change=_on_vol_changed_in_modal
                ))
            except Exception as e:
                self._log(f"Erro na revisao: {e}")
            finally:
                self._processing = False
                self.after(0, lambda: self.start_btn.configure(state="normal"))
                self.after(0, lambda: self.review_btn.configure(state="normal"))
                self.after(0, lambda: self.cancel_btn.configure(state="disabled"))

        threading.Thread(target=_worker, daemon=True).start()

    def _open_censorship_editor(self):
        """Abre a janela modal interativa para visualizar e ajustar a censura visual."""
        input_path = self.input_path.get().strip()
        if not input_path or not Path(input_path).exists():
            messagebox.showerror("Erro", "Selecione um arquivo de vídeo válido primeiro.")
            return

        blur_val = self.censor_blur_strength.get()
        blur_key = "medium"
        if "Suave" in blur_val:
            blur_key = "light"
        elif "Forte" in blur_val:
            blur_key = "strong"

        # Se já temos regiões customizadas salvas, abre direto com elas
        if self.custom_censor_regions:
            CensorshipEditorDialog(
                parent=self.winfo_toplevel(),
                video_path=input_path,
                initial_detections=self.custom_censor_regions,
                blur_strength=blur_key,
                on_confirm=self._on_censorship_approved
            )
            return

        # Se o modo for Manual, abre direto vazio para o usuário adicionar os pontos desejados
        if "Manual" in self.censor_mode.get():
            CensorshipEditorDialog(
                parent=self.winfo_toplevel(),
                video_path=input_path,
                initial_detections=[],
                blur_strength=blur_key,
                on_confirm=self._on_censorship_approved
            )
            return

        # Caso contrário, faz escaneamento rápido com IA para abrir já com as caixas detectadas
        self._set_progress(10, "Escaneando vídeo para ajuste de censura...")
        self._log("Iniciando escaneamento Anime Shield para o Editor Interativo...")

        def _scan_worker():
            try:
                from censorship_manager import detect_anime_sensitive_timeline
                dets = detect_anime_sensitive_timeline(input_path, fps_sample=4.0, conf_threshold=0.35, on_log=self._log)
                self.after(0, lambda: CensorshipEditorDialog(
                    parent=self.winfo_toplevel(),
                    video_path=input_path,
                    initial_detections=dets,
                    blur_strength=blur_key,
                    on_confirm=self._on_censorship_approved
                ))
            except Exception as e:
                self._log(f"Aviso ao escanear para o editor: {e}")
                self.after(0, lambda: CensorshipEditorDialog(
                    parent=self.winfo_toplevel(),
                    video_path=input_path,
                    initial_detections=[],
                    blur_strength=blur_key,
                    on_confirm=self._on_censorship_approved
                ))
            finally:
                self.after(0, lambda: self._set_progress(0, "Pronto"))

        threading.Thread(target=_scan_worker, daemon=True).start()

    def _on_censorship_approved(self, regions: list, blur_strength: str):
        self.custom_censor_regions = regions
        self._log(f"Anime Shield: {len(regions)} regiões de censura salvas e configuradas para o vídeo!")
        messagebox.showinfo("Censura Salva", f"{len(regions)} regiões de censura configuradas com sucesso!\nElas serão aplicadas na renderização.")

    def _start_pipeline(self):
        """Inicia o pipeline a partir do botao principal."""
        input_path = self.input_path.get().strip()
        if not input_path or not Path(input_path).exists():
            messagebox.showerror("Erro", "Selecione um arquivo de video valido.")
            return

        # Se o usuario optou por revisar as legendas, abre o revisor
        if self.review_subtitles.get() and self.include_subtitles.get():
            self._start_transcribe_and_review()
            return

        # Modo 1-Clique Direto: processa tudo
        self._processing = True
        self._cancel_flag = False
        self.start_btn.configure(state="disabled")
        self.review_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")

        threading.Thread(target=self._pipeline_direct_thread, args=(input_path,), daemon=True).start()

    def _on_subtitles_approved(self, input_path: str, edited_items: List[Dict[str, Any]], style_key: str, pop_enabled: Any, final_music_vol: Optional[float] = None):
        """Callback chamado quando o usuario clica em 'GERAR VÍDEO FINAL' no editor modal."""
        self._log(f"Legendas confirmadas pelo usuario ({len(edited_items)} falas). Estilo: {style_key}")

        self._processing = True
        self._cancel_flag = False
        self.start_btn.configure(state="disabled")
        self.review_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")

        threading.Thread(
            target=self._render_thread,
            args=(input_path, edited_items, style_key, pop_enabled, final_music_vol),
            daemon=True
        ).start()

    def _pipeline_direct_thread(self, input_path: str):
        """Fluxo 1-clique sem parada de revisao."""
        try:
            from subtitle_renderer import group_whisper_words, get_media_duration

            self._log("=" * 50)
            self._log("STUDIO PIPELINE - MODO DIRETO 1-CLIQUE")
            self._log("=" * 50)

            # Prepara o vídeo recortado antes de transcrever
            work_video = self._prepare_pipeline_video(input_path)

            items = []
            if self.include_subtitles.get():
                self._set_progress(10, "Transcrevendo audio...")
                raw_words = self._transcribe_audio(work_video)
                if raw_words:
                    video_dur = get_media_duration(work_video)
                    chunks = group_whisper_words(raw_words, max_duration=video_dur if video_dur > 0 else None)
                    items = apply_corrections_to_items(chunks)
                    self._log(f"Dicionario de Anime aplicado automaticamente em {len(items)} falas.")

            style_key = STYLE_KEY_MAP.get(self.subtitle_style_label.get(), "dynamic_animax")
            pop_enabled = self.subtitle_pop.get()

            self._render_thread(work_video, items, style_key, pop_enabled)

        except Exception as e:
            self._log(f"Erro inesperado no pipeline: {e}")
            self._processing = False
            self.after(0, lambda: self.start_btn.configure(state="normal"))
            self.after(0, lambda: self.review_btn.configure(state="normal"))
            self.after(0, lambda: self.cancel_btn.configure(state="disabled"))

    def _render_thread(self, input_path: str, items: List[Dict[str, Any]], subtitle_style: str, subtitle_pop: Any, final_music_vol: Optional[float] = None):
        """Executa a renderizacao FFmpeg final com os itens de legenda aprovados."""
        try:
            from subtitle_renderer import render_video_with_style

            self._log("Renderizando video final com overlays Animax (187% Zoom, Watermark 62px)...")
            self._set_progress(35, "Renderizando video...")

            # O nome de saída sempre preserva o caminho e pasta do vídeo original selecionado
            orig_p = Path(self.input_path.get().strip() or input_path)
            output_path = str(orig_p.parent / f"{orig_p.stem}_studio_final.mp4")

            music_path = self.music_path.get().strip() if self.include_music.get() else None
            if final_music_vol is not None:
                music_vol = max(0.0, min(1.0, float(final_music_vol)))
            else:
                music_vol = self.music_volume_slider.get() / 100.0
            music_start = self.music_start.get().strip()
            anti_cp = self.anti_copyright.get()

            anti_mode_map = {
                "Leve (Micro-Pitch)": "light",
                "Avançado (Pitch + EQ + Estéreo)": "advanced",
                "Agressivo (Bypass Máximo)": "aggressive"
            }
            anti_mode_key = anti_mode_map.get(self.anti_copyright_mode.get(), "advanced")

            ducking_map = {
                "Cinema & Anime (Ultra Fluido -6dB)": "cinema",
                "Equilibrado (Transição Suave -9dB)": "balanced",
                "Foco Total na Voz (Voz Firme -12dB)": "aggressive",
                "Cinema & Anime (Recomendado)": "cinema",
                "Equilibrado (Padrão)": "balanced",
                "Foco Total na Voz (Agressivo)": "aggressive",
            }
            ducking_key = ducking_map.get(self.music_ducking_mode.get(), "cinema")

            raw_censor = self.censor_blur_strength.get()
            if "suave" in raw_censor.lower():
                censor_blur_key = "light"
            elif "forte" in raw_censor.lower():
                censor_blur_key = "strong"
            else:
                censor_blur_key = "medium"

            ok = render_video_with_style(
                input_path=input_path,
                output_path=output_path,
                title_text=self.title_text.get().strip(),
                words_with_timestamps=items if items else None,
                music_path=music_path,
                music_volume=music_vol,
                music_start=music_start,
                anti_copyright=anti_cp,
                anti_copyright_mode=anti_mode_key,
                music_auto_ducking=self.music_auto_ducking.get(),
                ducking_mode=ducking_key,
                subtitle_style=subtitle_style,
                subtitle_pop=subtitle_pop,
                censor_profanity=self.censor_profanity.get(),
                censor_visual=self.censor_visual.get(),
                censor_blur_strength=censor_blur_key,
                custom_censor_regions=self.custom_censor_regions if self.custom_censor_regions else None,
                include_watermark_png=self.include_watermark.get(),
                include_cta=self.include_cta.get(),
                include_blur_sides=self.include_blur_sides.get(),
                on_log=self._log,
                on_progress=lambda p, l: self._set_progress(35 + int(p * 0.65), l),
            )

            if ok:
                self._log("=" * 50)
                self._log("PIPELINE CONCLUIDO COM SUCESSO!")
                self._log(f"Arquivo gerado: {output_path}")
                self._set_progress(100, "Concluido!")
                self.after(0, lambda: messagebox.showinfo(
                    "Studio Pipeline",
                    f"Video finalizado com sucesso!\n\n{output_path}"
                ))
            else:
                self._log("Falha na renderizacao. Verifique as mensagens de erro acima.")
                self._set_progress(0, "Erro")

        except Exception as e:
            self._log(f"Erro na renderizacao: {e}")
            import traceback
            self._log(traceback.format_exc())
        finally:
            if self._active_trimmed_path and os.path.exists(self._active_trimmed_path):
                try:
                    os.remove(self._active_trimmed_path)
                except Exception:
                    pass
                self._active_trimmed_path = None
            self._processing = False
            self.after(0, lambda: self.start_btn.configure(state="normal"))
            self.after(0, lambda: self.review_btn.configure(state="normal"))
            self.after(0, lambda: self.cancel_btn.configure(state="disabled"))

    def _cancel(self):
        self._cancel_flag = True
        self._log("Cancelamento solicitado...")

    def load_video_from_path(self, path):
        """Permite outras abas enviarem video para o Studio."""
        self.input_path.set(path)
        stem = Path(path).stem
        for bad_part in ["_mastercut", "_upscaled", "_original", "_final", "_part1", "_part2"]:
            stem = stem.replace(bad_part, "")
        stem = stem.replace("_", " ").strip()
        if not self.title_text.get():
            self.title_text.set(stem[:50].upper())
        self._log(f"Video carregado do pipeline: {Path(path).name}")

    def destroy(self):
        if getattr(self, "_anim_timer", None):
            try:
                self.after_cancel(self._anim_timer)
            except Exception:
                pass
            self._anim_timer = None
        super().destroy()
