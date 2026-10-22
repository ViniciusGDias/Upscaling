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

import urahara_theme

COLORS = {
    **urahara_theme.COLORS,
    "accent_refiner": urahara_theme.COLORS["accent_primary"],
    "accent_refiner_hover": urahara_theme.COLORS["accent_hover"],
    "accent_studio": urahara_theme.COLORS["accent_benihime"],
    "accent_studio_hover": urahara_theme.COLORS["accent_benihime_hover"],
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
        self.after(600, self._check_ollama_status_async)


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

        # ─── CAMPO 1: NOME DA OBRA / TÍTULO (Busca de Metadados / Lore na API) ───
        title_row = ctk.CTkFrame(inner, fg_color="transparent")
        title_row.pack(fill="x", pady=(0, 10))

        title_header = ctk.CTkFrame(title_row, fg_color="transparent")
        title_header.pack(fill="x", pady=(0, 3))

        ctk.CTkLabel(
            title_header, text="🎬 Nome da Obra / Título:",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(side="left")

        ctk.CTkLabel(
            title_header, text="(Busca Personagens e Lore na API)",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=COLORS["text_secondary"], anchor="w",
        ).pack(side="left", padx=(6, 0))

        self.work_title_entry = ctk.CTkEntry(
            title_row,
            placeholder_text="Ex: Mashle, Jujutsu Kaisen, Pousando no Amor, Vincenzo, Bleach...",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_dark"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            height=34, corner_radius=8,
        )
        self.work_title_entry.pack(fill="x")

        # ─── CAMPO 2: ESTILO DE CLÍMAX & FOCO RÁPIDO (Enviado Somente à IA) ───
        climax_row = ctk.CTkFrame(inner, fg_color="transparent")
        climax_row.pack(fill="x", pady=(0, 10))

        climax_header = ctk.CTkFrame(climax_row, fg_color="transparent")
        climax_header.pack(fill="x", pady=(0, 3))

        ctk.CTkLabel(
            climax_header, text="🎯 Tipo de Clímax / Foco da Cena:",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(side="left")

        ctk.CTkLabel(
            climax_header, text="(Enviado SOMENTE à IA • Zero busca na API)",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color="#10b981", anchor="w",
        ).pack(side="left", padx=(6, 0))

        self.climax_values_map = {
            "auto": "🤖 Automático (A IA identifica o momento de maior clímax da cena)",
            "action": "💥 Ação Épica & Golpe Final (Confronto, poder máximo e vitória)",
            "comedy": "😂 Comédia & Trapalhada (Reações hilárias e quebra cômica)",
            "shock": "😱 Choque & 'É o quê?!' (Feito impossível / revelação inacreditável)",
            "taunt": "🔥 Provocação & Resposta Ácida (Aura de superioridade e deboche)",
            "drama": "😭 Emoção & Drama Profundo (Tensão dramática, lágrimas ou despedida)",
            "romance": "💕 Romance & Tensão (Quase-beijo, declaração ou troca de olhares)",
            "threat": "⚔️ Tensão / Ameaça Iminente (Encarada séria, perigo e contagem)",
            "custom": "✍️ Personalizado (Definir apenas pelo texto abaixo)",
        }
        self.climax_keys_by_label = {v: k for k, v in self.climax_values_map.items()}

        self.climax_type_var = ctk.StringVar(value=self.climax_values_map["auto"])
        self.climax_type_menu = ctk.CTkOptionMenu(
            climax_row,
            variable=self.climax_type_var,
            values=list(self.climax_values_map.values()),
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            height=32, corner_radius=8,
            fg_color=COLORS["bg_dark"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["accent_primary"],
            text_color=COLORS["text_primary"],
            dropdown_fg_color=COLORS["bg_card"],
            dropdown_hover_color=COLORS["bg_card_hover"],
            dropdown_text_color=COLORS["text_primary"],
            command=self._on_climax_type_change,
        )
        self.climax_type_menu.pack(fill="x")

        # ─── CAMPO 3: DETALHES ADICIONAIS DA CENA (Opcional) ───
        scene_row = ctk.CTkFrame(inner, fg_color="transparent")
        scene_row.pack(fill="x", pady=(0, 12))

        scene_header = ctk.CTkFrame(scene_row, fg_color="transparent")
        scene_header.pack(fill="x", pady=(0, 3))

        ctk.CTkLabel(
            scene_header, text="💡 Detalhes Específicos da Cena (Opcional):",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_secondary"], anchor="w",
        ).pack(side="left")

        self.scene_context_entry = ctk.CTkEntry(
            scene_row,
            placeholder_text="Opcional: Ex: foco na cena da varinha no chão, choque dos magos com 'É o quê?!'...",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_dark"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            height=34, corner_radius=8,
        )
        self.scene_context_entry.pack(fill="x")

        # Alias de compatibilidade
        self.context_entry = self.scene_context_entry



        # ─── MOTOR DE IA (100% LOCAL VS NUVEM HÍBRIDA) ───
        ai_engine_row = ctk.CTkFrame(inner, fg_color="transparent")
        ai_engine_row.pack(fill="x", pady=(0, 10))

        ai_header_row = ctk.CTkFrame(ai_engine_row, fg_color="transparent")
        ai_header_row.pack(fill="x", pady=(0, 4))

        ctk.CTkLabel(
            ai_header_row, text="Motor de Inteligência Artificial:",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(side="left")

        self.ollama_status_badge = ctk.CTkLabel(
            ai_header_row, text="Verificando Ollama...",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=COLORS["text_secondary"],
            fg_color=COLORS["bg_dark"],
            corner_radius=4, padx=6, pady=1,
        )
        self.ollama_status_badge.pack(side="right")

        self.ai_engine_values_map = {
            "gemini_web": "🌐 Gemini Web (Navegador Pro / Tokens Ilimitados do Web Chat)",
            "ollama_local": "🖥️ 100% IA Local (Ollama Qwen 2.5 7B + RTX 5060 / Zero Custos)",
            "cloud": "☁️ Nuvem Híbrida (Google Gemini 2.5 Flash + Groq Whisper)",
            "auto": "🤖 Automático (Ollama Local se Ativo, senão Nuvem)",
        }
        self.ai_engine_keys_by_label = {v: k for k, v in self.ai_engine_values_map.items()}

        from settings_manager import load_app_settings
        saved_settings = load_app_settings()
        default_engine = saved_settings.get("refiner_ai_engine", "auto")
        if default_engine not in self.ai_engine_values_map:
            default_engine = "auto"

        self.ai_engine_var = ctk.StringVar(value=self.ai_engine_values_map[default_engine])
        self.ai_engine_menu = ctk.CTkOptionMenu(
            ai_engine_row,
            variable=self.ai_engine_var,
            values=list(self.ai_engine_values_map.values()),
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            height=32, corner_radius=8,
            fg_color=COLORS["bg_dark"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["accent_primary"],
            text_color=COLORS["text_primary"],
            dropdown_fg_color=COLORS["bg_card"],
            dropdown_hover_color=COLORS["bg_card_hover"],
            dropdown_text_color=COLORS["text_primary"],
            command=self._on_ai_engine_change,
        )
        self.ai_engine_menu.pack(fill="x")

        # ─── SELETOR DE MODELO LOCAL OLLAMA (Dinâmico / Modelos de Elite) ───
        from settings_manager import get_all_selectable_ollama_models, get_installed_ollama_models
        self.local_models_list = get_all_selectable_ollama_models()
        self.local_model_keys_by_label = {label: code for code, label in self.local_models_list}
        self.local_model_labels_by_code = {code: label for code, label in self.local_models_list}

        self.local_model_row = ctk.CTkFrame(inner, fg_color="transparent")
        if default_engine not in ("cloud", "gemini_web"):
            self.local_model_row.pack(fill="x", pady=(4, 10))

        lm_header = ctk.CTkFrame(self.local_model_row, fg_color="transparent")
        lm_header.pack(fill="x", pady=(0, 2))

        ctk.CTkLabel(
            lm_header, text="🧠 Modelo de IA Local (Ollama na GPU RTX 5060):",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#10b981", anchor="w"
        ).pack(side="left")

        # Seleciona o melhor modelo instalado disponível (prioriza qwen3.8:27b, depois qwen2.5:7b)
        installed_now = get_installed_ollama_models()
        def_code = "qwen2.5:7b"
        if any("qwen3.8" in m for m in installed_now):
            def_code = "qwen3.8:27b"
        elif any("qwen2.5:7b" in m for m in installed_now):
            def_code = "qwen2.5:7b"
        elif installed_now:
            def_code = installed_now[0]

        cur_saved_model = saved_settings.get("director_local_model", def_code)
        def_label = self.local_model_labels_by_code.get(cur_saved_model, self.local_models_list[0][1])

        self.local_model_var = ctk.StringVar(value=def_label)
        self.local_model_menu = ctk.CTkOptionMenu(
            self.local_model_row,
            variable=self.local_model_var,
            values=[label for _, label in self.local_models_list],
            font=ctk.CTkFont(family="Segoe UI", size=11),
            height=30, corner_radius=8,
            fg_color=COLORS["bg_dark"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["accent_primary"],
            text_color=COLORS["text_primary"],
            dropdown_fg_color=COLORS["bg_card"],
            dropdown_hover_color=COLORS["bg_card_hover"],
            dropdown_text_color=COLORS["text_primary"],
        )
        self.local_model_menu.pack(fill="x")

        # Linha para Automação do Gemini Web (Login no Gemini Pro)
        self.row_gemini_web = ctk.CTkFrame(inner, fg_color="transparent")
        ctk.CTkButton(
            self.row_gemini_web,
            text="🔑 Conectar Conta Google (Login no Gemini Pro)",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#1e1b4b",
            hover_color="#312e81",
            text_color="#a5b4fc",
            border_width=1,
            border_color="#4338ca",
            height=28,
            corner_radius=8,
            command=self._on_connect_gemini_web
        ).pack(fill="x", pady=(2, 6))

        if default_engine == "gemini_web":
            self.row_gemini_web.pack(fill="x", pady=(2, 6))

        # ─── DOMINANT UNIFIED EDIT PROFILE ───
        profile_row = ctk.CTkFrame(inner, fg_color="transparent")
        profile_row.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(
            profile_row, text="Estilo Editorial Dominante:",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", pady=(0, 4))

        self.profile_values_map = {
            "viral_59": "⚡ Viral Flow 59s (Duplo Refino IA + J-Cut Suave: Máx 59s)",
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
        self.stats_label.pack(fill="x", pady=(4, 8))

        # Script Storyboard Card (Roteiro Narrativo da Cena)
        self.script_card = ctk.CTkFrame(
            r_inner,
            fg_color=COLORS["bg_dark"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=8
        )
        s_header = ctk.CTkFrame(self.script_card, fg_color="transparent")
        s_header.pack(fill="x", padx=12, pady=(8, 4))
        ctk.CTkLabel(
            s_header,
            text="🎬 Roteiro Narrativo da Cena (Roteirista IA)",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color="#38bdf8",
            anchor="w"
        ).pack(side="left")

        self.script_body_label = ctk.CTkLabel(
            self.script_card,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_secondary"],
            justify="left",
            anchor="w",
            wraplength=640
        )
        self.script_body_label.pack(fill="x", padx=12, pady=(0, 10))
        self.script_card.pack_forget()

        # Feedback & Direction Correction Card (Ajustar corte / Adicionar momentos faltantes)
        self.correction_card = ctk.CTkFrame(
            r_inner,
            fg_color=COLORS["bg_dark"],
            border_width=1,
            border_color="#f59e0b",
            corner_radius=10
        )
        self.correction_card.pack(fill="x", pady=(0, 12))

        c_header = ctk.CTkFrame(self.correction_card, fg_color="transparent")
        c_header.pack(fill="x", padx=14, pady=(10, 4))

        ctk.CTkLabel(
            c_header,
            text="🎬 Direção da Cena: Ajustar ou Adicionar Momento com a IA",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color="#f59e0b",
            anchor="w"
        ).pack(side="left")

        ctk.CTkLabel(
            self.correction_card,
            text="Faltou algum momento ou ficou fora de contexto (ex: 'faltou mostrar ele pegando a espada')? Fale para a IA e ela reajustará o corte em segundos reaproveitando a análise:",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_secondary"],
            justify="left",
            anchor="w",
            wraplength=640
        ).pack(fill="x", padx=14, pady=(0, 8))

        c_input_row = ctk.CTkFrame(self.correction_card, fg_color="transparent")
        c_input_row.pack(fill="x", padx=14, pady=(0, 10))

        self.correction_entry = ctk.CTkEntry(
            c_input_row,
            placeholder_text="Ex: Faltou mostrar ele pegando a espada aos ~45s antes do ataque, traga isso pro corte...",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_card"],
            border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            height=38,
            corner_radius=8
        )
        self.correction_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.correction_entry.bind("<Return>", lambda e: self._start_feedback_correction())

        self.apply_correction_btn = ctk.CTkButton(
            c_input_row,
            text="⚡ Corrigir Corte com IA",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color="#f59e0b",
            hover_color="#d97706",
            text_color="#09090b",
            height=38,
            corner_radius=8,
            command=self._start_feedback_correction
        )
        self.apply_correction_btn.pack(side="right")

        # Action buttons row: Preview + Send to Studio + Send to Upscaler + Folder
        self.result_btn_row = ctk.CTkFrame(r_inner, fg_color="transparent")
        self.result_btn_row.pack(fill="x")
        btn_row = self.result_btn_row

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
                title = origin.get("title", "") or origin.get("anime", "") or origin.get("source_title", "")
                title_str = f" ('{title}')" if title else ""

                if title and hasattr(self, "work_title_entry") and not self.work_title_entry.get().strip():
                    self.work_title_entry.delete(0, "end")
                    self.work_title_entry.insert(0, title)

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

    def _on_ai_engine_change(self, val):
        key = self.ai_engine_keys_by_label.get(val, "auto")
        from settings_manager import save_app_settings
        save_app_settings(refiner_ai_engine=key)
        self._check_ollama_status_async()

    def _on_climax_type_change(self, val):
        """Atualiza a dica do campo de texto caso o usuário troque o tipo de clímax."""
        key = getattr(self, "climax_keys_by_label", {}).get(val, "auto")
        hints = {
            "auto": "Opcional: Ex: foco na cena da varinha no chão, choque dos magos...",
            "action": "Opcional: Ex: clímax no momento do ataque especial ou soco final...",
            "comedy": "Opcional: Ex: clímax na punchline cômica ou expressão do personagem...",
            "shock": "Opcional: Ex: clímax no momento em que ele puxa a varinha e todos gritam 'É o quê?!'...",
            "taunt": "Opcional: Ex: focar na fala debochada e cara de desdém...",
            "drama": "Opcional: Ex: clímax na revelação triste ou despedida...",
            "romance": "Opcional: Ex: clímax na aproximação dos rostos ou confissão...",
            "threat": "Opcional: Ex: clímax no momento em que o vilão se aproxima...",
            "custom": "Digite as instruções do foco da cena aqui...",
        }
        if hasattr(self, "scene_context_entry"):
            hint = hints.get(key, "Opcional: detalhe o foco do corte...")
            self.scene_context_entry.configure(placeholder_text=hint)

    def _check_ollama_status_async(self):
        def _checker():
            text = "⚪ Ollama Offline"
            text_color = "#a1a1aa"
            fg_color = "#1f2937"
            models = []
            try:
                import requests
                r = requests.get("http://localhost:11434/api/tags", timeout=1.5)
                if r.status_code == 200:
                    models = [m.get("name", "") for m in r.json().get("models", [])]
                    preferred = "qwen3.8:27b" if any("qwen3.8" in m for m in models) else ("qwen2.5:7b" if any("qwen2.5:7b" in m for m in models) else (models[0] if models else "Ativo"))
                    text = f"🟢 Ollama Ativo ({preferred} na GPU)"
                    text_color = "#10b981"
                    fg_color = "#064e3b"
            except Exception:
                pass

            try:
                if hasattr(self, "ollama_status_badge") and self.winfo_exists():
                    self.after(0, lambda: self._apply_ollama_status(text, text_color, fg_color, models))
            except Exception:
                pass

        threading.Thread(target=_checker, daemon=True).start()

    def _apply_ollama_status(self, text, text_color, fg_color, installed_models=None):
        try:
            if hasattr(self, "ollama_status_badge") and self.winfo_exists():
                self.ollama_status_badge.configure(
                    text=text,
                    text_color=text_color,
                    fg_color=fg_color
                )
            if installed_models and hasattr(self, "local_model_menu"):
                from settings_manager import get_all_selectable_ollama_models
                self.local_models_list = get_all_selectable_ollama_models()
                self.local_model_keys_by_label = {label: code for code, label in self.local_models_list}
                self.local_model_labels_by_code = {code: label for code, label in self.local_models_list}
                all_labels = [label for _, label in self.local_models_list]
                self.local_model_menu.configure(values=all_labels)
        except Exception:
            pass

    def _on_ai_engine_change(self, value=None):
        """Shows or dims local model selector depending on engine choice."""
        if not hasattr(self, "ai_engine_var"):
            return
        selected_label = self.ai_engine_var.get()
        engine_key = self.ai_engine_keys_by_label.get(selected_label, "auto")
        try:
            from settings_manager import save_app_settings
            save_app_settings(refiner_ai_engine=engine_key)
        except Exception:
            pass

        if hasattr(self, "local_model_row"):
            if engine_key in ("cloud", "gemini_web"):
                if self.local_model_row.winfo_ismapped():
                    self.local_model_row.pack_forget()
            else:
                if not self.local_model_row.winfo_ismapped():
                    target_before = getattr(self, "row_gemini_web", getattr(self, "edit_profile_menu", None))
                    before_w = target_before.master if hasattr(target_before, "master") else None
                    self.local_model_row.pack(fill="x", pady=(4, 10))

        if hasattr(self, "row_gemini_web"):
            if engine_key == "gemini_web":
                if not self.row_gemini_web.winfo_ismapped():
                    self.row_gemini_web.pack(fill="x", pady=(2, 6))
            else:
                if self.row_gemini_web.winfo_ismapped():
                    self.row_gemini_web.pack_forget()

    def _on_connect_gemini_web(self):
        try:
            from gemini_web_automator import open_login_window
            self._log("🌐 Abrindo Google Chrome para login da sua conta Google no Gemini Pro...")
            open_login_window(on_log=self._log)
        except Exception as e:
            self._log(f"⚠️ Erro ao abrir janela de login: {e}")


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

        if resolved_key == "viral_59":
            hint_msg = (
                f"⚡ Previsão Viral Flow 59s: {min_d:.1f}s a {max_d:.1f}s (Teto Rígido: 59.0s). "
                f"Vídeo original: {format_time(dur)}. 🔍 Duplo Refino Ativo: IA Geradora + IA Auditora e transições de áudio ultra-suaves."
            )
        elif resolved_key == "dorama":
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

    def _start_feedback_correction(self):
        if self.is_processing:
            messagebox.showinfo("Em Processamento", "Aguarde o processamento atual terminar antes de solicitar correções.")
            return

        if not self.input_path or not os.path.exists(self.input_path):
            messagebox.showwarning("Aviso", "Vídeo de entrada não encontrado.")
            return

        feedback = self.correction_entry.get().strip() if hasattr(self, "correction_entry") else ""
        if not feedback:
            messagebox.showwarning(
                "Feedback Vazio",
                "Por favor, descreva o que faltou ou o que precisa ser ajustado na cena.\n\n"
                "Exemplo: 'Faltou mostrar ele pegando a espada aos ~45s antes de atacar'."
            )
            return

        prev_segments = self.last_result.get("segments") if (hasattr(self, "last_result") and self.last_result) else None

        # Gerar novo nome de arquivo de saída para preservar o corte anterior
        in_p = Path(self.input_path)
        corr_out = str(in_p.parent / f"{in_p.stem}_corrigido_{int(time.time())}.mp4")
        self.output_entry.delete(0, "end")
        self.output_entry.insert(0, corr_out)
        self.output_path = corr_out

        self._run_refine(user_feedback=feedback, previous_segments=prev_segments)

    def _run_refine(self, user_feedback="", previous_segments=None):
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
        work_title = self.work_title_entry.get().strip() if hasattr(self, 'work_title_entry') else ""
        raw_scene_text = self.scene_context_entry.get().strip() if hasattr(self, 'scene_context_entry') else (
            self.context_entry.get().strip() if hasattr(self, 'context_entry') else ""
        )

        # Resolução do Foco do Clímax (Dropdown + Texto opcional)
        climax_val = self.climax_type_var.get() if hasattr(self, 'climax_type_var') else ""
        climax_key = getattr(self, "climax_keys_by_label", {}).get(climax_val, "auto")
        climax_hints = {
            "action": "Foco prioritário em Ação Épica, combate dinâmico e clímax no golpe/ataque decisivo",
            "comedy": "Foco prioritário em Comédia, trapalhadas, quebra cômica e clímax na punchline/reação hilária",
            "shock": "Foco prioritário em Choque e revelação inacreditável, feito impossível e clímax na reação de espanto e 'É o quê?!'",
            "taunt": "Foco prioritário em Provocação e superioridade absoluta, intimidando o oponente com resposta ácida e deboche",
            "drama": "Foco prioritário em Emoção Intensa, drama comovente, lágrimas, reencontro ou despedida marcante",
            "romance": "Foco prioritário em Romance e Química entre personagens, declaração, quase-beijo ou troca de olhares",
            "threat": "Foco prioritário em Tensão e Ameaça Iminente, encarada tensa, perigo iminente e contagem regressiva",
        }
        chosen_hint = climax_hints.get(climax_key, "")
        if chosen_hint:
            if raw_scene_text:
                scene_ctx = f"{chosen_hint}. Detalhes adicionais: {raw_scene_text}"
            else:
                scene_ctx = chosen_hint
        else:
            scene_ctx = raw_scene_text

        combined_context = f"{work_title} {scene_ctx}".strip()
        is_dorama = (
            resolved_key == "dorama"
            or refine_mode == "dorama"
            or editorial_mode == "dorama"
            or any(k in combined_context.lower() for k in ("dorama", "kdrama", "k-drama", "coreano", "c-drama", "j-drama", "doramas"))
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

        ai_engine_key = self.ai_engine_keys_by_label.get(self.ai_engine_var.get(), "auto") if hasattr(self, "ai_engine_var") else "auto"
        ai_engine_label = self.ai_engine_var.get() if hasattr(self, "ai_engine_var") else "Automático"
        self._log(f"Motor IA:   {ai_engine_label}")

        chosen_local_model = ""
        if hasattr(self, "local_model_var") and hasattr(self, "local_model_keys_by_label"):
            lbl = self.local_model_var.get()
            chosen_local_model = self.local_model_keys_by_label.get(lbl, "")
        if ai_engine_key in ("ollama_local", "auto") and chosen_local_model:
            self._log(f"Modelo Local: {chosen_local_model} (na RTX 5060)")

        if work_title:
            self._log(f"Obra/Título:  {work_title} (Busca de Lore/Personagens na API)")
        if climax_key != "auto" and climax_key != "custom":
            self._log(f"Clímax Foco:  {climax_val}")
        if scene_ctx:
            self._log(f"Foco da Cena: {scene_ctx} (Instrução direta para a IA)")
        if user_feedback:
            self._log(f"🛠️ [DIREÇÃO & CORREÇÃO IA] Aplicando feedback do diretor: \"{user_feedback}\"")
            if previous_segments:
                self._log(f"📋 [PROPOSTA ANTERIOR] Base de {len(previous_segments)} cortes anteriores enviada para reconstrução cirúrgica.")

        if demucs_iso:
            self._log("[AI] Isolamento com IA Demucs: ATIVADO (Removerá 100% do instrumental)")

        def _worker():
            try:
                stats = self.pipeline.process(
                    video_path=self.input_path,
                    output_path=self.output_path,
                    video_context=scene_ctx or work_title,
                    work_title=work_title,
                    scene_context=scene_ctx,
                    user_feedback=user_feedback,
                    previous_segments=previous_segments,
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
                    ai_engine=ai_engine_key,
                    local_model=chosen_local_model,
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

        roteiro = stats.get("roteiro")
        if roteiro and isinstance(roteiro, dict):
            lines = []
            if roteiro.get("premissa"):
                lines.append(f"• Premissa: {roteiro['premissa']}")
            if roteiro.get("hook"):
                lines.append(f"• Hook (Abertura): {roteiro['hook']}")
            if roteiro.get("conflito_desenvolvimento"):
                lines.append(f"• Desenvolvimento: {roteiro['conflito_desenvolvimento']}")
            if roteiro.get("climax_fechamento"):
                lines.append(f"• Clímax/Fechamento: {roteiro['climax_fechamento']}")
            script_text = "\n".join(lines) if lines else "Roteiro narrativo gerado com sucesso."
            self.script_body_label.configure(text=script_text)
            self.script_card.pack(fill="x", pady=(0, 12), before=self.result_btn_row)
        else:
            self.script_card.pack_forget()

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
        if hasattr(self, "shield_standalone_btn"):
            self.shield_standalone_btn.configure(state="disabled")
        if hasattr(self, "shield_standalone_quick_btn"):
            self.shield_standalone_quick_btn.configure(state="disabled")
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
                    if hasattr(self, "shield_standalone_btn"):
                        self.shield_standalone_btn.configure(state="normal")
                    if hasattr(self, "shield_standalone_quick_btn"):
                        self.shield_standalone_quick_btn.configure(state="normal")
                    self.progress_bar.set(0.0)
                    self.status_label.configure(text="Pronto.")
                self.after(0, _reset_ui)

        threading.Thread(target=_worker, daemon=True).start()
