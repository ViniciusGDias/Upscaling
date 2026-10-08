"""
Refiner Tab - UI component for the Refinador (Mastercut Concentrado) feature.
Allows generating a condensed 30s-60s cut with AI, previewing it immediately,
and transferring it directly to the Upscaling pipeline if approved.
"""

import os
import time
import threading
import subprocess
from pathlib import Path
import customtkinter as ctk
from tkinter import filedialog, messagebox

from refiner_mastercut import (
    MastercutPipeline,
    get_video_duration,
    check_video_has_audio,
    calculate_mastercut_bounds,
    EDIT_PROFILES,
    resolve_edit_profile,
)
from upscaler import (
    get_video_info,
    format_time,
    format_file_size,
)
import icon_manager

COLORS = {
    "bg_dark": "#09090b",
    "bg_card": "#121216",
    "bg_card_hover": "#18181e",
    "accent_primary": "#10b981",
    "accent_secondary": "#059669",
    "accent_refiner": "#10b981",
    "accent_refiner_hover": "#059669",
    "accent_studio": "#7c3aed",
    "accent_studio_hover": "#6d28d9",
    "success": "#10b981",
    "warning": "#f59e0b",
    "error": "#ef4444",
    "text_primary": "#fafafa",
    "text_secondary": "#a1a1aa",
    "text_muted": "#a1a1aa",
    "border": "#222228",
    "border_active": "#10b981",
    "console_bg": "#050505",
    "console_text": "#a1a1aa",
}


class RefinerMastercutTab(ctk.CTkFrame):
    """Self-contained UI tab for Refinador Mastercut Concentrado."""

    def __init__(self, parent, main_app=None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.main_app = main_app
        self.pipeline = MastercutPipeline()

        self.input_path = ""
        self.output_path = ""
        self.current_video_info = None
        self.last_result = None
        self.is_processing = False
        self._start_time = 0.0
        self._current_cut_origin = None

        self._build_ui()

    def _build_ui(self):
        self.scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["accent_refiner"],
        )
        self.scroll.pack(fill="both", expand=True)

        self._build_header()
        self._build_file_section()
        self._build_info_section()
        self._build_continuous_origin_section()
        self._build_settings_section()
        self._build_output_section()
        self._build_action_section()
        self._build_progress_section()
        self._build_result_section()

    # ── Header ────────────────────────────────────────────────────────────

    def _build_header(self):
        header = ctk.CTkFrame(self.scroll, fg_color="transparent")
        header.pack(fill="x", pady=(0, 14))

        row = ctk.CTkFrame(header, fg_color="transparent")
        row.pack(fill="x")

        ctk.CTkLabel(
            row, text="Refinador Mastercut",
            font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"),
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        ctk.CTkLabel(
            row, text=" Opção 4: Mastercut ",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=COLORS["text_secondary"],
            fg_color=COLORS["bg_card"],
            corner_radius=4, padx=6, pady=2,
        ).pack(side="left", padx=(10, 0))

        desc = (
            "Condensa o vídeo bruto no 'Suco do Vídeo' de alta retenção (30s–60s) ou em Mini-Filmes (até 2:30 min).\n"
            "Mapeia cada palavra e diálogo via IA Whisper para cortar pausas mortas com precisão cirúrgica sem mutilar falas."
        )
        ctk.CTkLabel(
            header, text=desc,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_secondary"],
            justify="left", anchor="w",
        ).pack(fill="x", pady=(6, 0))

        ctk.CTkFrame(header, fg_color=COLORS["border"], height=1).pack(fill="x", pady=(10, 0))

    # ── File Selection ────────────────────────────────────────────────────

    def _build_file_section(self):
        card = ctk.CTkFrame(
            self.scroll, fg_color=COLORS["bg_card"],
            corner_radius=12, border_width=1, border_color=COLORS["border"],
        )
        card.pack(fill="x", pady=(0, 10))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=14)

        t_row = ctk.CTkFrame(inner, fg_color="transparent")
        t_row.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            t_row, text="Vídeo de Entrada",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(side="left")

        sync_btn = ctk.CTkButton(
            t_row, text="Sincronizar com Upscaling",
            image=icon_manager.get_icon("refresh", size=(14, 14), color=COLORS["accent_refiner"]),
            compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color=COLORS["bg_dark"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["accent_refiner"],
            height=26, corner_radius=6,
            command=self._sync_from_main_app,
        )
        sync_btn.pack(side="right")

        f_row = ctk.CTkFrame(inner, fg_color="transparent")
        f_row.pack(fill="x")

        self.file_entry = ctk.CTkEntry(
            f_row,
            placeholder_text="Selecione ou arraste um vídeo...",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_dark"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            height=36, corner_radius=8,
        )
        self.file_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        browse_btn = ctk.CTkButton(
            f_row, text="Buscar Vídeo",
            image=icon_manager.get_icon("folder", size=(14, 14), color="#fafafa"), compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=COLORS["bg_dark"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            height=36, corner_radius=8, width=120,
            command=self._browse_file,
        )
        browse_btn.pack(side="right")

    # ── Video Info ────────────────────────────────────────────────────────

    def _build_info_section(self):
        self.info_card = ctk.CTkFrame(
            self.scroll, fg_color=COLORS["bg_card"],
            corner_radius=12, border_width=1, border_color=COLORS["border"],
        )
        # Not packed initially, shown when video is loaded

        inner = ctk.CTkFrame(self.info_card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=12)

        ctk.CTkLabel(
            inner, text="Informações do Vídeo",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLORS["text_secondary"], anchor="w",
        ).pack(fill="x", pady=(0, 8))

        grid = ctk.CTkFrame(inner, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        self.info_labels = {}
        fields = [
            ("duration", "Duração", "00:00"),
            ("resolution", "Resolução", "—"),
            ("fps", "FPS", "—"),
            ("size", "Tamanho", "—"),
            ("copyright_risk", "Risco Copyright", "🟢 Seguro"),
        ]
        for col, (key, title, val) in enumerate(fields):
            f = ctk.CTkFrame(grid, fg_color=COLORS["bg_dark"], corner_radius=8, border_width=1, border_color=COLORS["border"])
            f.grid(row=0, column=col, sticky="nsew", padx=3)
            ctk.CTkLabel(
                f, text=title,
                font=ctk.CTkFont(family="Segoe UI", size=10),
                text_color=COLORS["text_secondary"],
            ).pack(pady=(6, 1))
            val_color = "#10b981" if key == "copyright_risk" else COLORS["text_primary"]
            lbl = ctk.CTkLabel(
                f, text=val,
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                text_color=val_color,
            )
            lbl.pack(pady=(0, 6))
            self.info_labels[key] = lbl

    # ── Continuous Cut Origin Banner ──────────────────────────────────────

    def _build_continuous_origin_section(self):
        self.continuous_origin_card = ctk.CTkFrame(
            self.scroll, fg_color="#181308",
            corner_radius=12, border_width=1, border_color="#f59e0b",
        )
        # Inicialmente oculto, visível quando vídeo for identificado como corte contínuo do Diretor IA

        inner = ctk.CTkFrame(self.continuous_origin_card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=12)

        top_row = ctk.CTkFrame(inner, fg_color="transparent")
        top_row.pack(fill="x")

        ctk.CTkLabel(
            top_row, text="🛡️ Trecho Contínuo de Episódio Detectado (Diretor IA)",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color="#fbbf24", anchor="w",
        ).pack(side="left")

        ctk.CTkButton(
            top_row, text="Limpar Marcação do Cache",
            image=icon_manager.get_icon("trash", size=(12, 12), color="#fca5a5"), compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color="#27180c", hover_color="#3b1d11",
            border_width=1, border_color="#78350f",
            text_color="#fca5a5",
            height=26, corner_radius=6,
            command=self._clear_continuous_origin_cache,
        ).pack(side="right")

        self.continuous_origin_desc = ctk.CTkLabel(
            inner,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#fde68a",
            justify="left", anchor="w",
            wraplength=720,
        )
        self.continuous_origin_desc.pack(fill="x", pady=(4, 0))

    # ── Settings ──────────────────────────────────────────────────────────

    def _build_settings_section(self):
        card = ctk.CTkFrame(
            self.scroll, fg_color=COLORS["bg_card"],
            corner_radius=12, border_width=1, border_color=COLORS["border"],
        )
        card.pack(fill="x", pady=(0, 10))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=14)

        ctk.CTkLabel(
            inner, text="Ajustes do Mastercut",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", pady=(0, 12))

        # Context (Anime / Series name)
        ctx_row = ctk.CTkFrame(inner, fg_color="transparent")
        ctx_row.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            ctx_row, text="Contexto / Nome da Obra (Opcional):",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_secondary"], anchor="w",
        ).pack(fill="x", pady=(0, 4))

        self.context_entry = ctk.CTkEntry(
            ctx_row,
            placeholder_text="Ex: Pousando no Amor Ep 10, Vincenzo Ep 4, Jujutsu Kaisen 2 Ep 17...",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_dark"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            height=34, corner_radius=8,
        )
        self.context_entry.pack(fill="x")

        # ─── DOMINANT UNIFIED EDIT PROFILE ───
        profile_row = ctk.CTkFrame(inner, fg_color="transparent")
        profile_row.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(
            profile_row, text="Estilo Editorial Dominante:",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", pady=(0, 4))

        self.profile_values_map = {
            "viral": "⚡ Edição Viral Pro (TikTok / Reels / Shorts: Alta Retenção)",
            "dorama": "🎭 Dorama Dramático (K-Drama: Diálogos Íntegros + Tensão Emocional)",
            "narrative": "🎬 Mastercut Narrativo (100% Cronológico, Sem Repetições)",
            "dynamic": "🚀 Ritmo Acelerado (Shorts / Reels: Cortes Ágeis nas Pausas)",
            "mini_movie": "🎬 Mini-Filme (Arco Completo em 4 Atos, até 2:30 min)",
            "dialogue": "🧼 Preservar Diálogos (Corte Suave: Mantém 100% das Conversas)",
            "hook": "🎯 Com Gancho de Abertura (Teaser de 3s no Início)",
            "loop": "🔁 Loop Infinito (Replay Contínuo TikTok / Shorts)",
            "auto": "🤖 Automático (IA Escolhe o Melhor Corte)",
        }
        self.profile_keys_by_label = {v: k for k, v in self.profile_values_map.items()}

        self.edit_profile_var = ctk.StringVar(value=self.profile_values_map["viral"])
        self.edit_profile_menu = ctk.CTkOptionMenu(
            profile_row,
            variable=self.edit_profile_var,
            values=list(self.profile_values_map.values()),
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=COLORS["bg_dark"], button_color=COLORS["bg_dark"],
            button_hover_color=COLORS["bg_card_hover"],
            dropdown_fg_color=COLORS["bg_card"], dropdown_hover_color=COLORS["bg_card_hover"],
            dropdown_text_color=COLORS["text_primary"],
            text_color=COLORS["text_primary"],
            height=38, corner_radius=8,
            command=self._on_setting_changed,
        )
        self.edit_profile_menu.pack(fill="x")

        # Backward compatibility aliases for other tabs/scripts
        self.refine_mode_var = ctk.StringVar(value="Equilibrado (Dinâmico - Padrão)")
        self.target_duration_var = ctk.StringVar(value="Padrão Shorts / Reels (~40s a 60s)")
        self.editorial_mode_var = ctk.StringVar(value="Linear Direto (Sem Loop)")
        self.loop_mode_var = self.editorial_mode_var

        # Dynamic Explanatory Card for Selected Edit Style
        self.style_card = ctk.CTkFrame(
            inner, fg_color=COLORS["bg_dark"],
            corner_radius=8, border_width=1, border_color=COLORS["border"],
        )
        self.style_card.pack(fill="x", pady=(4, 10))

        style_inner = ctk.CTkFrame(self.style_card, fg_color="transparent")
        style_inner.pack(fill="x", padx=14, pady=10)

        # Flow badge row
        self.flow_badge_label = ctk.CTkLabel(
            style_inner,
            text="✨ Gancho → História → Loop",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLORS["accent_primary"], anchor="w",
        )
        self.flow_badge_label.pack(fill="x", pady=(0, 2))

        # Description text
        self.style_desc_label = ctk.CTkLabel(
            style_inner,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_secondary"], justify="left", anchor="w",
            wraplength=700,
        )
        self.style_desc_label.pack(fill="x", pady=(0, 4))

        # Duration & Anti-cut Live Guarantee Hint Label
        self.hint_label = ctk.CTkLabel(
            style_inner,
            text="Proteção Anti-Corte: Carregue um vídeo para ver a estimativa exata de retenção e duração final.",
            font=ctk.CTkFont(family="Segoe UI", size=11, slant="italic"),
            text_color="#10b981",
            justify="left", anchor="w",
            wraplength=700,
        )
        self.hint_label.pack(fill="x")

        # Toggles row: Vocal Isolation + Anti-Copyright
        toggles_row = ctk.CTkFrame(inner, fg_color="transparent")
        toggles_row.pack(fill="x", pady=(4, 0))

        self.vocal_isolation_var = ctk.BooleanVar(value=True)
        self.vocal_cb = ctk.CTkCheckBox(
            toggles_row,
            text="Clareza Vocal de Estúdio",
            variable=self.vocal_isolation_var,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLORS["accent_primary"], hover_color=COLORS["accent_secondary"],
            border_color=COLORS["border"], corner_radius=4,
        )
        self.vocal_cb.pack(side="left", padx=(0, 12))

        self.demucs_isolation_var = ctk.BooleanVar(value=False)
        self.demucs_cb = ctk.CTkCheckBox(
            toggles_row,
            text="Isolar Voz com IA Demucs (Remove Instrumental)",
            variable=self.demucs_isolation_var,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLORS["accent_primary"], hover_color=COLORS["accent_secondary"],
            border_color=COLORS["border"], corner_radius=4,
        )
        self.demucs_cb.pack(side="left", padx=(0, 12))

        self.anti_copyright_var = ctk.BooleanVar(value=True)
        self.anti_copyright_mode_var = ctk.StringVar(value="🛡️ Blindagem Máxima YouTube (Anti-Toei)")

        ac_frame = ctk.CTkFrame(toggles_row, fg_color="transparent")
        ac_frame.pack(side="left")

        self.anti_copy_cb = ctk.CTkCheckBox(
            ac_frame,
            text="Anti-Copyright:",
            variable=self.anti_copyright_var,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color=COLORS["accent_primary"], hover_color=COLORS["accent_secondary"],
            border_color=COLORS["border"], corner_radius=4,
            command=self._on_anti_copyright_toggle
        )
        self.anti_copy_cb.pack(side="left", padx=(0, 6))

        self.anti_copy_menu = ctk.CTkOptionMenu(
            ac_frame,
            values=[
                "🛡️ Blindagem Máxima YouTube (Anti-Toei)",
                "📱 Padrão (TikTok / Reels / Leve)"
            ],
            variable=self.anti_copyright_mode_var,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            height=28, width=245, corner_radius=6,
            fg_color=COLORS["bg_card"], button_color=COLORS["accent_primary"],
            button_hover_color=COLORS["accent_secondary"]
        )
        self.anti_copy_menu.pack(side="left")

        # Linha Rápida: Blindar Vídeo Pronto (1-Clique)
        shield_quick_row = ctk.CTkFrame(inner, fg_color="transparent")
        shield_quick_row.pack(fill="x", pady=(10, 0))

        ctk.CTkLabel(
            shield_quick_row,
            text="⚡ Já tem o vídeo pronto (editado ou upscalado)?",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_secondary"]
        ).pack(side="left", padx=(0, 8))

        self.shield_standalone_quick_btn = ctk.CTkButton(
            shield_quick_row,
            text="🛡️ Blindar Vídeo Pronto para YouTube (1-Clique)",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#064e3b", hover_color="#047857",
            border_width=1, border_color="#10b981",
            text_color="#34d399",
            height=30, corner_radius=6,
            command=self._start_standalone_shield
        )
        self.shield_standalone_quick_btn.pack(side="left")

    # ── Output Section ────────────────────────────────────────────────────

    def _build_output_section(self):
        card = ctk.CTkFrame(
            self.scroll, fg_color=COLORS["bg_card"],
            corner_radius=12, border_width=1, border_color=COLORS["border"],
        )
        card.pack(fill="x", pady=(0, 10))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=14)

        ctk.CTkLabel(
            inner, text="Destino do Vídeo Refinado",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", pady=(0, 8))

        o_row = ctk.CTkFrame(inner, fg_color="transparent")
        o_row.pack(fill="x")

        self.output_entry = ctk.CTkEntry(
            o_row,
            placeholder_text="Caminho do arquivo final será gerado automaticamente...",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_dark"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            height=36, corner_radius=8,
        )
        self.output_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        browse_btn = ctk.CTkButton(
            o_row, text="Salvar Como...",
            image=icon_manager.get_icon("download", size=(14, 14), color=COLORS["text_secondary"]),
            compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_dark"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"],
            height=36, corner_radius=8, width=125,
            command=self._browse_output,
        )
        browse_btn.pack(side="right")

    # ── Action Buttons ────────────────────────────────────────────────────

    def _build_action_section(self):
        row = ctk.CTkFrame(self.scroll, fg_color="transparent")
        row.pack(fill="x", pady=(0, 10))

        self.generate_btn = ctk.CTkButton(
            row, text="Gerar Mastercut Concentrado",
            image=icon_manager.get_icon("sparkle", size=(18, 18), color="#ffffff"),
            compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=COLORS["accent_primary"], hover_color=COLORS["accent_secondary"],
            text_color="#ffffff",
            height=46, corner_radius=10,
            command=self._start_mastercut,
        )
        self.generate_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.shield_standalone_btn = ctk.CTkButton(
            row, text="Blindar Vídeo Pronto",
            image=icon_manager.get_icon("shield", size=(16, 16), color="#10b981"),
            compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=COLORS["bg_card"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color="#10b981",
            height=46, corner_radius=10, width=175,
            command=self._start_standalone_shield,
        )
        self.shield_standalone_btn.pack(side="left", padx=(0, 8))

        self.clear_cache_btn = ctk.CTkButton(
            row, text="Limpar Cache IA",
            image=icon_manager.get_icon("trash", size=(16, 16), color="#ef4444"),
            compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=COLORS["bg_card"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["warning"],
            height=46, corner_radius=10, width=150,
            command=self._clear_cache_for_video,
        )
        self.clear_cache_btn.pack(side="left", padx=(0, 8))

        self.cancel_btn = ctk.CTkButton(
            row, text="Cancelar",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=COLORS["bg_card"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"],
            height=46, corner_radius=10, width=120,
            command=self._cancel_mastercut,
            state="disabled",
        )
        self.cancel_btn.pack(side="right")

    # ── Progress Section ──────────────────────────────────────────────────

    def _build_progress_section(self):
        self.progress_card = ctk.CTkFrame(
            self.scroll, fg_color=COLORS["bg_card"],
            corner_radius=12, border_width=1, border_color=COLORS["border"],
        )
        self.progress_card.pack(fill="x", pady=(4, 12))

        p_inner = ctk.CTkFrame(self.progress_card, fg_color="transparent")
        p_inner.pack(fill="x", padx=16, pady=14)

        header_p = ctk.CTkFrame(p_inner, fg_color="transparent")
        header_p.pack(fill="x", pady=(0, 6))

        self.status_label = ctk.CTkLabel(
            header_p, text="Aguardando início...",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        )
        self.status_label.pack(side="left", fill="x", expand=True)

        self.progress_bar = ctk.CTkProgressBar(
            p_inner, height=10, corner_radius=5,
            fg_color=COLORS["bg_dark"], progress_color=COLORS["accent_primary"],
        )
        self.progress_bar.pack(fill="x", pady=(0, 8))
        self.progress_bar.set(0)

        # Log box - Terminal
        self.log_box = ctk.CTkTextbox(
            p_inner, height=125, corner_radius=8,
            fg_color=COLORS["console_bg"], text_color=COLORS["console_text"],
            font=ctk.CTkFont(family="Consolas", size=11),
            border_width=1, border_color=COLORS["border"],
        )
        self.log_box.pack(fill="x")
        self.log_box.configure(state="disabled")

    # ── Result & Preview Section ──────────────────────────────────────────

    def _build_result_section(self):
        self.result_card = ctk.CTkFrame(
            self.scroll, fg_color=COLORS["bg_card"],
            corner_radius=12, border_width=1, border_color="#10b981",
        )

        r_inner = ctk.CTkFrame(self.result_card, fg_color="transparent")
        r_inner.pack(fill="x", padx=16, pady=14)

        # Header success
        h_row = ctk.CTkFrame(r_inner, fg_color="transparent")
        h_row.pack(fill="x")

        ctk.CTkLabel(
            h_row, text="Mastercut Gerado com Sucesso!",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color="#10b981", anchor="w",
        ).pack(side="left")

        ctk.CTkButton(
            h_row, text="Subir ao Topo",
            image=icon_manager.get_icon("upscale", size=(12, 12)),
            compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLORS["bg_dark"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"],
            height=26, corner_radius=6,
            command=lambda: self.scroll._parent_canvas.yview_moveto(0.0),
        ).pack(side="right")

        self.stats_label = ctk.CTkLabel(
            r_inner, text="Duração: 00:00 -> 00:00 (-0.0%) | 0 cortes",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_secondary"], anchor="w",
        )
        self.stats_label.pack(fill="x", pady=(4, 12))

        # Action buttons row: Preview + Send to Studio + Send to Upscaler + Folder
        btn_row = ctk.CTkFrame(r_inner, fg_color="transparent")
        btn_row.pack(fill="x")

        self.preview_btn = ctk.CTkButton(
            btn_row, text="Pré-visualizar",
            image=icon_manager.get_icon("play", size=(16, 16), color="#fafafa"),
            compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=COLORS["bg_dark"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            height=42, corner_radius=10,
            command=self._preview_video,
        )
        self.preview_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.send_to_studio_btn = ctk.CTkButton(
            btn_row, text="Enviar ao Studio",
            image=icon_manager.get_icon("studio", size=(16, 16), color="#fafafa"),
            compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=COLORS["accent_studio"], hover_color=COLORS["accent_studio_hover"],
            text_color="#fafafa",
            height=42, corner_radius=10,
            command=self._send_to_studio,
        )
        self.send_to_studio_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.send_to_upscaler_btn = ctk.CTkButton(
            btn_row, text="Usar no Upscaler",
            image=icon_manager.get_icon("upscale", size=(16, 16), color="#09090b"),
            compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=COLORS["accent_primary"], hover_color=COLORS["accent_secondary"],
            text_color="#09090b",
            height=42, corner_radius=10,
            command=self._send_to_upscaler,
        )
        self.send_to_upscaler_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.open_folder_btn = ctk.CTkButton(
            btn_row, text="Pasta",
            image=icon_manager.get_icon("folder", size=(16, 16), color="#a1a1aa"),
            compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_dark"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"],
            height=42, corner_radius=10, width=90,
            command=self._open_output_folder,
        )
        self.open_folder_btn.pack(side="right")

    # ── Logic & Event Handlers ────────────────────────────────────────────

    def _sync_from_main_app(self):
        """Syncs the currently loaded video from the main Upscaling tab."""
        if self.main_app and self.main_app.input_path:
            self._load_video(self.main_app.input_path)
        else:
            messagebox.showinfo("Aviso", "Nenhum vídeo carregado na aba Upscaling ainda.\nSelecione um vídeo clicando em 'Buscar Vídeo'.")

    def _browse_file(self):
        filetypes = [
            ("Vídeos", "*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.m4v *.ts"),
            ("Todos os arquivos", "*.*"),
        ]
        filepath = filedialog.askopenfilename(
            title="Selecionar Vídeo para o Mastercut",
            filetypes=filetypes,
        )
        if filepath:
            self._load_video(filepath)

    def _load_video(self, filepath: str):
        self.input_path = filepath
        self.file_entry.delete(0, "end")
        self.file_entry.insert(0, filepath)

        info = get_video_info(filepath)
        if info:
            self.current_video_info = info
            self.info_labels["duration"].configure(text=format_time(info.duration))
            self.info_labels["resolution"].configure(text=f"{info.width}×{info.height}")
            self.info_labels["fps"].configure(text=f"{info.fps:.1f}")
            self.info_labels["size"].configure(text=info.file_size_label)

            if not self.info_card.winfo_ismapped():
                self.info_card.pack(fill="x", pady=(0, 10))

            # Auto-tune edit profile according to clip duration ONLY if on auto
            cur_key = self._get_current_profile_key()
            if cur_key == "auto":
                if info.duration >= 110.0:
                    self.set_profile_by_key("mini_movie")
                elif info.duration <= 40.0:
                    self.set_profile_by_key("dynamic")

            self._update_duration_hint()

        # Auto-populate output path
        input_p = Path(filepath)
        default_out = str(input_p.parent / f"{input_p.stem}_mastercut_{int(time.time())}.mp4")
        self.output_entry.delete(0, "end")
        self.output_entry.insert(0, default_out)

        # Checa se o arquivo é um corte contínuo gerado pelo Diretor IA
        self._check_and_apply_cut_origin(filepath)

    def _check_and_apply_cut_origin(self, filepath: str):
        """Consulta o cache persistente do AICacheHub para verificar se o vídeo é corte contínuo."""
        try:
            from ai_cache_hub import ai_cache
            origin = ai_cache.get_cut_origin(filepath)
            if origin and origin.get("is_continuous"):
                dur = origin.get("continuous_duration", 0.0) or (self.current_video_info.duration if self.current_video_info else 0.0)
                ep = origin.get("source_episode", "Episódio")
                title = origin.get("title", "")
                title_str = f" ('{title}')" if title else ""

                msg = (
                    f"Origem Identificada: Trecho contínuo de {dur:.1f}s extraído de '{ep}'{title_str}.\n"
                    "O Diretor IA salvou este corte como contínuo bruto. A proteção Anti-Copyright 2026 "
                    "(Zoom Dinâmico com Respiração, Granulação Cinematográfica e Micro-EQ Anti-SoundMatch) foi ativada automaticamente!"
                )
                self.continuous_origin_desc.configure(text=msg)
                if hasattr(self, "continuous_origin_card") and not self.continuous_origin_card.winfo_ismapped():
                    self.continuous_origin_card.pack(fill="x", pady=(0, 10))

                self.anti_copyright_var.set(True)
                self._current_cut_origin = origin
                if "copyright_risk" in self.info_labels:
                    self.info_labels["copyright_risk"].configure(text="🟡 Risco Alto (>20s)", text_color="#fbbf24")
                return
            elif origin:
                if "copyright_risk" in self.info_labels:
                    self.info_labels["copyright_risk"].configure(text="🟢 Seguro (Dinâmico)", text_color="#10b981")
            else:
                dur = self.current_video_info.duration if self.current_video_info else 0.0
                if dur >= 20.0:
                    if "copyright_risk" in self.info_labels:
                        self.info_labels["copyright_risk"].configure(text="🟡 Vídeo Longo (>20s)", text_color="#fbbf24")
                else:
                    if "copyright_risk" in self.info_labels:
                        self.info_labels["copyright_risk"].configure(text="🟢 Seguro (<20s)", text_color="#10b981")
        except Exception:
            pass

        self._current_cut_origin = None
        if hasattr(self, "continuous_origin_card") and self.continuous_origin_card.winfo_ismapped():
            self.continuous_origin_card.pack_forget()

    def _clear_continuous_origin_cache(self):
        """Remove a marcação persistente de corte contínuo do cache ("até eu tirar")."""
        if not self.input_path:
            return
        try:
            from ai_cache_hub import ai_cache
            ai_cache.remove_cut_origin(self.input_path)
            self._current_cut_origin = None
            if hasattr(self, "continuous_origin_card") and self.continuous_origin_card.winfo_ismapped():
                self.continuous_origin_card.pack_forget()
            if "copyright_risk" in self.info_labels:
                self.info_labels["copyright_risk"].configure(text="🟢 Seguro (Manual)", text_color="#10b981")
            self._log(f"[CACHE] Marcação de corte contínuo removida para: {Path(self.input_path).name}")
            messagebox.showinfo(
                "Marcação Removida",
                "A marcação de corte contínuo deste vídeo foi removida do cache persistente com sucesso!\n"
                "A proteção agora responderá aos ajustes manuais da tela."
            )
        except Exception as e:
            messagebox.showwarning("Aviso", f"Não foi possível remover do cache: {e}")

    def set_profile_by_key(self, key: str):
        """Programmatically switch edit profile (e.g. from Director Tab or auto-detection)."""
        if hasattr(self, "profile_values_map") and key in self.profile_values_map:
            val = self.profile_values_map[key]
            if hasattr(self, "edit_profile_var"):
                self.edit_profile_var.set(val)
            self._sync_profile_to_legacy_vars()
            self._update_duration_hint()

    def _get_current_profile_key(self) -> str:
        val = self.edit_profile_var.get() if hasattr(self, "edit_profile_var") else ""
        if hasattr(self, "profile_keys_by_label") and val in self.profile_keys_by_label:
            return self.profile_keys_by_label[val]
        for k, v in getattr(self, "profile_values_map", {}).items():
            if k in val.lower() or val in v:
                return k
        return "viral"

    def _get_resolved_profile(self) -> tuple:
        dur = self.current_video_info.duration if self.current_video_info else 0.0
        is_continuous = bool(self._current_cut_origin and self._current_cut_origin.get("is_continuous"))
        raw_key = self._get_current_profile_key()
        return resolve_edit_profile(raw_key, dur, is_arc=is_continuous)

    def _sync_profile_to_legacy_vars(self):
        resolved_key, profile = self._get_resolved_profile()
        if hasattr(self, "refine_mode_var"):
            self.refine_mode_var.set(profile.get("refine_mode", "balanced"))
        if hasattr(self, "target_duration_var"):
            self.target_duration_var.set(profile.get("target_duration_mode", "standard"))
        if hasattr(self, "editorial_mode_var"):
            self.editorial_mode_var.set(profile.get("editorial_mode", "viral_editor"))

    def _get_refine_mode_key(self) -> str:
        resolved_key, profile = self._get_resolved_profile()
        return profile.get("refine_mode", "balanced")

    def _get_target_duration_key(self) -> str:
        resolved_key, profile = self._get_resolved_profile()
        return profile.get("target_duration_mode", "standard")

    def _get_editorial_mode_key(self) -> str:
        resolved_key, profile = self._get_resolved_profile()
        return profile.get("editorial_mode", "viral_editor")

    def _on_setting_changed(self, *args):
        # Support external scripts or tabs setting target_duration_var directly
        if hasattr(self, "target_duration_var"):
            td_val = self.target_duration_var.get()
            if "Mini-Filme" in td_val and self._get_current_profile_key() != "mini_movie":
                if hasattr(self, "profile_values_map"):
                    self.edit_profile_var.set(self.profile_values_map["mini_movie"])
        self._sync_profile_to_legacy_vars()
        self._update_duration_hint()

    def _update_duration_hint(self):
        if not hasattr(self, "hint_label"):
            return

        dur = self.current_video_info.duration if self.current_video_info else 0.0
        is_continuous = bool(self._current_cut_origin and self._current_cut_origin.get("is_continuous"))
        raw_key = self._get_current_profile_key()
        resolved_key, profile = resolve_edit_profile(raw_key, dur, is_arc=is_continuous)

        flow_str = profile.get("flow", "Gancho → História → Loop")
        label_str = profile.get("label", "Viral Pro")
        tagline = profile.get("tagline", "")
        explain = profile.get("explain", "")

        if raw_key == "auto":
            badge_text = f"🤖 [Modo Automático Ativo] ➔ Escolheu: '{label_str}' ({flow_str})"
        else:
            badge_text = f"✨ Fluxo Narrativo: {flow_str}"

        if hasattr(self, "flow_badge_label"):
            self.flow_badge_label.configure(text=badge_text)

        desc_text = f"{tagline}\n{explain}" if tagline else explain
        if hasattr(self, "style_desc_label"):
            self.style_desc_label.configure(text=desc_text)

        if dur <= 0.0:
            self.hint_label.configure(
                text="Proteção Anti-Corte: Carregue um vídeo para ver a estimativa exata de retenção e duração final."
            )
            return

        ref_m = profile.get("refine_mode", "balanced")
        dur_m = profile.get("target_duration_mode", "auto")
        min_d, max_d = calculate_mastercut_bounds(dur, refine_mode=ref_m, target_duration_mode=dur_m)
        reduction_min = round((1.0 - (max_d / dur)) * 100.0) if dur > 0 else 0
        reduction_max = round((1.0 - (min_d / dur)) * 100.0) if dur > 0 else 0

        if resolved_key == "dorama":
            hint_msg = (
                f"⏱️ Previsão Dorama: {min_d:.1f}s a {max_d:.1f}s (~{100 - reduction_max}% a {100 - reduction_min}% preservado). "
                f"Vídeo original: {format_time(dur)}. 🎭 Proteção de Pausas Ativa: respiração, diálogos completos e olhares de reação preservados."
            )
        else:
            hint_msg = (
                f"⏱️ Previsão de Duração: {min_d:.1f}s a {max_d:.1f}s (Economia estimada: {reduction_min}% a {reduction_max}%). "
                f"Vídeo original: {format_time(dur)}. Proteção Anti-Corte ativa: sem engasgos, com cortes limpos em pausas naturais."
            )
        self.hint_label.configure(text=hint_msg)

    def _browse_output(self):
        filetypes = [("Vídeo MP4", "*.mp4"), ("Todos os arquivos", "*.*")]
        initialdir = ""
        initialfile = ""
        cur = self.output_entry.get().strip()
        if cur:
            p = Path(cur)
            initialdir = str(p.parent)
            initialfile = p.name
        elif self.input_path:
            p = Path(self.input_path)
            initialdir = str(p.parent)
            initialfile = f"{p.stem}_mastercut.mp4"

        filepath = filedialog.asksaveasfilename(
            title="Salvar Vídeo Mastercut Como",
            filetypes=filetypes,
            defaultextension=".mp4",
            initialdir=initialdir,
            initialfile=initialfile,
        )
        if filepath:
            self.output_path = filepath
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, filepath)

    def _clear_cache_for_video(self):
        if not self.input_path:
            messagebox.showinfo("Cache de IA", "Selecione um vídeo primeiro para limpar o cache.")
            return
        try:
            from ai_cache_hub import ai_cache
            ai_cache.invalidate(self.input_path)
            self._log(f"[CACHE IA] Cache limpo para o vídeo: {Path(self.input_path).name}!")
            self._log("[INFO] A próxima execução analisará falas e cenas visuais do zero.")
            messagebox.showinfo("Cache Limpo", "Cache de IA deste vídeo foi limpo com sucesso!\nA próxima execução gerará tudo do zero.")
        except Exception as e:
            self._log(f"Aviso cache: {e}")

    def _log(self, text: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    # ── Pipeline Execution ────────────────────────────────────────────────

    def _start_mastercut(self):
        if not self.input_path or not os.path.exists(self.input_path):
            messagebox.showwarning("Aviso", "Por favor, selecione um vídeo de entrada válido.")
            return

        out_val = self.output_entry.get().strip()
        if not out_val:
            messagebox.showwarning("Aviso", "Por favor, defina o local onde o Mastercut será salvo.")
            return

        self.output_path = out_val
        self._run_refine()

    def _run_refine(self):
        self.is_processing = True
        self._start_time = time.time()
        self.generate_btn.configure(state="disabled", text="Processando Mastercut...")
        self.cancel_btn.configure(state="normal", text_color=COLORS["text_primary"])
        self.status_label.configure(text="Iniciando pipeline...")
        self.progress_bar.set(0.0)

        if not self.progress_card.winfo_ismapped():
            self.progress_card.pack(fill="x", pady=(4, 12))

        if self.result_card.winfo_ismapped():
            self.result_card.pack_forget()

        resolved_key, profile = self._get_resolved_profile()
        refine_mode = profile.get("refine_mode", "balanced")
        target_dur = profile.get("target_duration_mode", "standard")
        editorial_mode = profile.get("editorial_mode", "viral_editor")
        enable_loop = editorial_mode in ("loop", "viral_editor")
        profile_label = profile.get("label", "Viral Pro")
        flow_label = profile.get("flow", "")

        self._clear_log()
        self._log(f"════════ Refinador: Mastercut Concentrado ════════")
        self._log(f"Entrada:    {self.input_path}")
        self._log(f"Saída:      {self.output_path}")
        self._log(f"Estilo:     {profile_label} [{flow_label}]")
        self._log(f"Diretriz:   Ritmo: {refine_mode} | Alvo: {target_dur} | Editorial: {editorial_mode}")

        vocal_iso = self.vocal_isolation_var.get()
        demucs_iso = self.demucs_isolation_var.get()
        if not self.anti_copyright_var.get():
            anti_copy = "off"
        else:
            mode_text = self.anti_copyright_mode_var.get().lower()
            if "tiktok" in mode_text or "padrão" in mode_text or "padrao" in mode_text:
                anti_copy = "tiktok"
            else:
                anti_copy = "youtube_max"
        is_continuous_clip = bool(self._current_cut_origin and self._current_cut_origin.get("is_continuous"))
        video_ctx = self.context_entry.get().strip() if hasattr(self, 'context_entry') else ""

        is_dorama = (
            resolved_key == "dorama"
            or refine_mode == "dorama"
            or editorial_mode == "dorama"
            or any(k in video_ctx.lower() for k in ("dorama", "kdrama", "k-drama", "coreano", "c-drama", "j-drama", "doramas"))
        )

        if is_dorama:
            self._log("🎭 [MODO DORAMA] Calibragem de Atuação Ativa: Preservação de Pausas Dramáticas (até 0.8s) + Diálogos Íntegros + Multi-Cam Suave (6.0s).")

        if is_continuous_clip:
            orig_dur = self._current_cut_origin.get("continuous_duration", 0.0)
            orig_ep = self._current_cut_origin.get("source_episode", "")
            self._log(f"[ORIGEM CACHE] Trecho Contínuo detectado do Diretor IA (~{orig_dur:.1f}s de '{orig_ep}')!")
            self._log("[ANTI-COPYRIGHT 2026] Blindagem Ativa: Multi-Câmera Inteligente (Planos <=3.8s Wide/Punch) + Film Luma Grade + Micro-Pitch DSP.")
        elif anti_copy == "youtube_max":
            self._log(f"[SEGURANÇA YOUTUBE] Blindagem Anti-Copyright Máxima (Anti-Toei): ATIVADA (Flip Horizontal + Multi-Cam + Color Shift + 1.04x DSP)")
        elif anti_copy == "tiktok":
            cam_info = "<=6.0s" if is_dorama else "<=3.8s"
            self._log(f"[SEGURANÇA TIKTOK] Proteção Anti-Copyright Padrão: ATIVADA (Multi-Câmera {cam_info} + Film Luma + 1.02x DSP)")
        else:
            self._log("[AVISO] Proteção Anti-Copyright: DESATIVADA")

        if video_ctx:
            self._log(f"Contexto: {video_ctx}")
        if demucs_iso:
            self._log("[AI] Isolamento com IA Demucs: ATIVADO (Removerá 100% do instrumental)")

        def _worker():
            try:
                stats = self.pipeline.process(
                    video_path=self.input_path,
                    output_path=self.output_path,
                    video_context=video_ctx,
                    vocal_isolation=vocal_iso,
                    demucs_isolation=demucs_iso,
                    anti_copyright=anti_copy,
                    refine_mode=refine_mode,
                    target_duration_mode=target_dur,
                    enable_loop=enable_loop,
                    editorial_mode=editorial_mode,
                    is_continuous_clip=is_continuous_clip,
                    is_dorama=is_dorama,
                    profile_label=f"{profile_label} ({flow_label})" if flow_label else profile_label,
                    on_progress=lambda p, msg: self.after(0, self._on_progress_update, p, msg),
                    on_log=lambda msg: self.after(0, self._log, msg),
                )
                self.after(0, self._on_process_success, stats)
            except InterruptedError:
                self.after(0, self._on_process_cancelled)
            except Exception as e:
                self.after(0, self._on_process_error, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_progress_update(self, frac: float, msg: str):
        self.progress_bar.set(frac)
        self.status_label.configure(text=msg)

    def _on_process_success(self, stats: dict):
        self.is_processing = False
        self.last_result = stats
        self.generate_btn.configure(state="normal", text="Gerar Mastercut Concentrado (30s-60s)")
        self.cancel_btn.configure(state="disabled", text_color=COLORS["text_muted"])

        dur_before = format_time(stats["duration_before"])
        dur_after = format_time(stats["duration_after"])
        pct = stats["time_saved_percent"]
        segs = stats["segments_count"]
        size = stats["size_mb"]
        ed_label = stats.get("editorial_mode_label") or ("Loop Contextual" if stats.get("enable_loop") else "")
        ed_badge = f" | {ed_label}" if ed_label else ""

        self.stats_label.configure(
            text=f"Duração: {dur_before} -> {dur_after} ({pct}% economizado) | {segs} cortes | Tamanho: {size} MB{ed_badge}"
        )
        self.result_card.pack(fill="x", pady=(0, 10))
        self.after(150, lambda: self.scroll._parent_canvas.yview_moveto(0.55))
        self._log(f"[OK] Concluído com sucesso em {time.time() - self._start_time:.1f}s!")

    def _on_process_cancelled(self):
        self.is_processing = False
        self.generate_btn.configure(state="normal", text="Gerar Mastercut Concentrado (30s-60s)")
        self.cancel_btn.configure(state="disabled", text_color=COLORS["text_muted"])
        self.status_label.configure(text="Cancelado pelo usuário.")
        self._log("Processamento cancelado.")

    def _on_process_error(self, err_msg: str):
        self.is_processing = False
        self.generate_btn.configure(state="normal", text="Gerar Mastercut Concentrado (30s-60s)")
        self.cancel_btn.configure(state="disabled", text_color=COLORS["text_muted"])
        self.status_label.configure(text="Erro no processamento.")
        self._log(f"[ERRO]: {err_msg}")
        messagebox.showerror("Erro no Mastercut", f"Ocorreu um erro ao gerar o Mastercut:\n\n{err_msg}")

    def _cancel_mastercut(self):
        if self.is_processing:
            if messagebox.askyesno("Cancelar", "Deseja cancelar o processo do Mastercut?"):
                self.pipeline.cancel()
                self._log("Cancelando...")

    def _preview_video(self):
        """Opens the generated video immediately in default system media player."""
        if self.output_path and os.path.exists(self.output_path):
            try:
                os.startfile(self.output_path)
            except Exception as e:
                messagebox.showerror("Erro ao Abrir Vídeo", f"Não foi possível abrir o player:\n{e}")
        else:
            messagebox.showwarning("Aviso", "Arquivo de vídeo não encontrado.")

    def _send_to_studio(self):
        """Transfers the generated mastercut video directly into the Studio Pipeline tab."""
        if not self.output_path or not os.path.exists(self.output_path):
            messagebox.showwarning("Aviso", "Vídeo não encontrado para enviar.")
            return

        if self.main_app and hasattr(self.main_app, "studio_tab"):
            # Set input path in studio tab (auto-loads duration, preview player, AI cache)
            self.main_app.studio_tab.input_path.set(self.output_path)
            # Switch tab to Studio Pipeline
            self.main_app.tabview.set("Studio Pipeline")
            if hasattr(self.main_app, "_set_status"):
                self.main_app._set_status("[OK] Vídeo carregado no Studio Pipeline! Pronto para aplicar enquadramento, zoom 187% e legendas.", COLORS["accent_studio"])
        else:
            messagebox.showinfo("Sucesso", f"Vídeo salvo em:\n{self.output_path}")

    def _send_to_upscaler(self):
        """Transfers the generated mastercut video into the main Upscaling tab."""
        if not self.output_path or not os.path.exists(self.output_path):
            messagebox.showwarning("Aviso", "Vídeo não encontrado para enviar.")
            return

        if self.main_app:
            # Load video into main app
            self.main_app._load_video(self.output_path)
            # Switch tab to Upscaling
            self.main_app.tabview.set("Upscaling")
            self.main_app._set_status("[OK] Vídeo do Mastercut carregado! Escolha as melhorias e inicie o upscaling.", COLORS["success"])
        else:
            messagebox.showinfo("Sucesso", f"Vídeo salvo em:\n{self.output_path}")

    def _open_output_folder(self):
        if self.output_path and os.path.exists(self.output_path):
            folder = os.path.dirname(os.path.abspath(self.output_path))
            subprocess.run(["explorer", folder])
        elif self.input_path and os.path.exists(self.input_path):
            folder = os.path.dirname(os.path.abspath(self.input_path))
            subprocess.run(["explorer", folder])

    def _on_anti_copyright_toggle(self):
        """Habilita ou desabilita o seletor de modo anti-copyright."""
        if hasattr(self, "anti_copy_menu"):
            if self.anti_copyright_var.get():
                self.anti_copy_menu.configure(state="normal")
            else:
                self.anti_copy_menu.configure(state="disabled")

    def _start_standalone_shield(self):
        """
        Permite blindar qualquer vídeo existente em 1 clique
        (ex: vídeo que já passou pelo upscaler antes de entrar no Studio)
        sem refazer todo o corte do Mastercut.
        """
        initial_file = self.input_path if self.input_path and os.path.exists(self.input_path) else ""
        initial_dir = os.path.dirname(initial_file) if initial_file else ""

        src_path = filedialog.askopenfilename(
            title="Selecione o Vídeo para Blindar (Widescreen)",
            initialdir=initial_dir,
            filetypes=[("Vídeos MP4/MKV", "*.mp4 *.mkv *.mov *.avi"), ("Todos os arquivos", "*.*")]
        )
        if not src_path or not os.path.exists(src_path):
            return

        src_p = Path(src_path)
        default_out = str(src_p.parent / f"{src_p.stem}_youtube_safe.mp4")

        out_path = filedialog.asksaveasfilename(
            title="Salvar Vídeo Blindado Como...",
            initialdir=str(src_p.parent),
            initialfile=Path(default_out).name,
            filetypes=[("Vídeo MP4", "*.mp4")]
        )
        if not out_path:
            return

        if not out_path.endswith(".mp4"):
            out_path += ".mp4"

        mode_str = self.anti_copyright_mode_var.get().lower()
        ac_mode = "tiktok" if ("tiktok" in mode_str or "padrão" in mode_str or "padrao" in mode_str) else "youtube_max"

        self.generate_btn.configure(state="disabled")
        self.shield_standalone_btn.configure(state="disabled")
        self.cancel_btn.configure(state="disabled")
        self.progress_bar.set(0.0)
        self.status_label.configure(text="Iniciando blindagem ultra-rápida via FFmpeg NVENC...")

        self._log("\n" + "═"*55)
        self._log(f"🛡️ [BLINDAGEM 1-CLIQUE] Iniciando blindagem para YouTube em: {src_p.name}")
        self._log(f"   • Modo Selecionado: {'Blindagem Máxima YouTube (Anti-Toei)' if ac_mode == 'youtube_max' else 'Padrão TikTok/Reels'}")
        self._log("═"*55)

        def _worker():
            try:
                from refiner_mastercut import apply_standalone_anti_copyright_shield
                res_out = apply_standalone_anti_copyright_shield(
                    input_path=src_path,
                    output_path=out_path,
                    mode=ac_mode,
                    on_progress=lambda p, msg: self.after(0, self._on_progress_update, p, msg),
                    on_log=lambda msg: self.after(0, self._log, msg)
                )
                def _on_success():
                    self.output_path = res_out
                    self.output_entry.delete(0, "end")
                    self.output_entry.insert(0, res_out)
                    self._log(f"\n🎉 [PRONTO] Vídeo 100% blindado gerado com sucesso!")
                    self._log(f"📁 Arquivo: {res_out}")
                    self._log(f"💡 Dica: Agora você já pode importar este vídeo no Studio para aplicar o formato 9:16 e legendas!")
                    messagebox.showinfo("Blindagem Concluída", f"Vídeo blindado com sucesso!\n\nArquivo salvo em:\n{res_out}\n\nPronto para envio ao YouTube ou para importar no Studio.")
                self.after(0, _on_success)
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda: self._log(f"[ERRO] Falha ao blindar vídeo: {err_msg}"))
                self.after(0, lambda: messagebox.showerror("Erro na Blindagem", f"Falha ao blindar vídeo:\n{err_msg}"))
            finally:
                def _reset_ui():
                    self.generate_btn.configure(state="normal")
                    self.shield_standalone_btn.configure(state="normal")
                    self.progress_bar.set(0.0)
                    self.status_label.configure(text="Pronto.")
                self.after(0, _reset_ui)

        threading.Thread(target=_worker, daemon=True).start()
