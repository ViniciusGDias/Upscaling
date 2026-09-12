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
)
from upscaler import (
    get_video_info,
    format_time,
    format_file_size,
)

COLORS = {
    "bg_dark": "#09090b",
    "bg_card": "#111113",
    "bg_card_hover": "#18181b",
    "accent_primary": "#e2e8f0",
    "accent_secondary": "#94a3b8",
    "accent_refiner": "#e2e8f0",
    "accent_refiner_hover": "#a1a1aa",
    "success": "#22c55e",
    "warning": "#f59e0b",
    "error": "#ef4444",
    "text_primary": "#fafafa",
    "text_secondary": "#71717a",
    "text_muted": "#3f3f46",
    "border": "#27272a",
    "border_active": "#52525b",
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
            row, text="✂️  Refinador",
            font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"),
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        ctk.CTkLabel(
            row, text=" Opção 4: Mastercut ",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=COLORS["text_secondary"],
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            padx=8, pady=3,
        ).pack(side="left", padx=(8, 0), pady=(4, 0))

        ctk.CTkLabel(
            row, text=" 30s-60s ",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=COLORS["text_secondary"],
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            padx=8, pady=3,
        ).pack(side="left", padx=(6, 0), pady=(4, 0))

        ctk.CTkLabel(
            header,
            text="Extraia 'O Suco do Vídeo' com IA antes do upscaling. Pré-visualize o corte e só faça upscaling se gostar!",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=COLORS["text_secondary"],
            anchor="w",
        ).pack(fill="x", pady=(4, 0))

        ctk.CTkFrame(header, fg_color=COLORS["border"], height=1).pack(fill="x", pady=(10, 0))

    # ── File Section ──────────────────────────────────────────────────────

    def _build_file_section(self):
        card = ctk.CTkFrame(
            self.scroll, fg_color=COLORS["bg_card"],
            corner_radius=12, border_width=1, border_color=COLORS["border"],
        )
        card.pack(fill="x", pady=(0, 10))

        title_row = ctk.CTkFrame(card, fg_color="transparent")
        title_row.pack(fill="x", padx=16, pady=(12, 6))

        ctk.CTkLabel(
            title_row, text="📁  Vídeo Original para o Mastercut",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(side="left")

        # Sync button with main tab
        self.sync_btn = ctk.CTkButton(
            title_row, text="🔄 Usar vídeo da aba Upscaling",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color="transparent", hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"],
            height=26, command=self._sync_from_main_app,
        )
        self.sync_btn.pack(side="right")

        input_row = ctk.CTkFrame(card, fg_color="transparent")
        input_row.pack(fill="x", padx=16, pady=(0, 12))

        self.file_entry = ctk.CTkEntry(
            input_row,
            placeholder_text="Selecione um vídeo longo ou episódio (ex: 20-30 min)...",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_dark"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            placeholder_text_color=COLORS["text_muted"],
            height=38, corner_radius=8,
        )
        self.file_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            input_row, text="Buscar Vídeo",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=COLORS["bg_dark"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            height=38, corner_radius=10,
            command=self._browse_file,
        ).pack(side="right")

        # Context input box (optional anime / episode)
        ctx_box = ctk.CTkFrame(card, fg_color="transparent")
        ctx_box.pack(fill="x", padx=16, pady=(0, 12))

        ctx_label_row = ctk.CTkFrame(ctx_box, fg_color="transparent")
        ctx_label_row.pack(fill="x", pady=(0, 4))

        ctk.CTkLabel(
            ctx_label_row, text="🏷️  Anime, Série ou Episódio (Opcional):",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLORS["text_secondary"], anchor="w",
        ).pack(side="left")

        ctk.CTkLabel(
            ctx_label_row, text="💡 Se informado, a IA foca nos personagens, golpes e frases lendárias daquele episódio!",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=COLORS["text_muted"], anchor="w",
        ).pack(side="left", padx=(8, 0))

        self.context_entry = ctk.CTkEntry(
            ctx_box,
            placeholder_text="Ex: Bleach Ep 270 / Luta Ichigo vs Ulquiorra (se deixar vazio, a IA analisa só pelas falas)...",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_dark"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            placeholder_text_color=COLORS["text_muted"],
            height=36, corner_radius=8,
        )
        self.context_entry.pack(fill="x")

    # ── Video Info Section ────────────────────────────────────────────────

    def _build_info_section(self):
        self.info_card = ctk.CTkFrame(
            self.scroll, fg_color=COLORS["bg_card"],
            corner_radius=12, border_width=1, border_color=COLORS["border"],
        )

        grid = ctk.CTkFrame(self.info_card, fg_color="transparent")
        grid.pack(fill="x", padx=16, pady=12)

        self.info_labels = {}
        items = [
            ("Duração Original", "duration", "--:--"),
            ("Resolução", "resolution", "--"),
            ("FPS", "fps", "--"),
            ("Tamanho", "size", "--"),
        ]
        for col_idx, (label_text, key, default_val) in enumerate(items):
            box = ctk.CTkFrame(grid, fg_color=COLORS["bg_dark"], corner_radius=8)
            box.grid(row=0, column=col_idx, padx=4, sticky="ew")
            grid.columnconfigure(col_idx, weight=1)

            ctk.CTkLabel(
                box, text=label_text,
                font=ctk.CTkFont(family="Segoe UI", size=10),
                text_color=COLORS["text_muted"],
            ).pack(pady=(6, 0))

            lbl = ctk.CTkLabel(
                box, text=default_val,
                font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                text_color=COLORS["text_primary"],
            )
            lbl.pack(pady=(0, 6))
            self.info_labels[key] = lbl

    # ── Settings Section ──────────────────────────────────────────────────

    def _build_settings_section(self):
        card = ctk.CTkFrame(
            self.scroll, fg_color=COLORS["bg_card"],
            corner_radius=12, border_width=1, border_color=COLORS["border"],
        )
        card.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            card, text="⚙️  Configurações do Mastercut",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=16, pady=(12, 6))

        # Mode explanation banner
        banner = ctk.CTkFrame(card, fg_color=COLORS["bg_dark"], corner_radius=8)
        banner.pack(fill="x", padx=16, pady=(0, 12))

        b_row = ctk.CTkFrame(banner, fg_color="transparent")
        b_row.pack(fill="x", padx=12, pady=10)

        ctk.CTkLabel(
            b_row,
            text="🧠 Opção 4: Mastercut Concentrado (O Suco do Vídeo)",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=COLORS["accent_refiner"],
            anchor="w",
        ).pack(fill="x")

        ctk.CTkLabel(
            b_row,
            text="O algoritmo mapeia as falas com Whisper, elimina silêncios mortos (>0.35s) e seleciona com IA os momentos de maior clímax, impacto e ação, condensando tudo com narrativa contínua e sem mutilação de falas.",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_secondary"],
            wraplength=700, justify="left",
            anchor="w",
        ).pack(fill="x", pady=(4, 0))

        # Selectors row: Mode & Target Duration
        ctrls_row = ctk.CTkFrame(card, fg_color="transparent")
        ctrls_row.pack(fill="x", padx=16, pady=(0, 10))

        # Col 1: Mode (Intensity)
        mode_box = ctk.CTkFrame(ctrls_row, fg_color="transparent")
        mode_box.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkLabel(
            mode_box, text="🎯  Intensidade / Modo de Refino:",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", pady=(0, 4))

        self.refine_mode_var = ctk.StringVar(value="🟡 Equilibrado (Dinâmico - Padrão)")
        self.refine_mode_menu = ctk.CTkOptionMenu(
            mode_box,
            values=[
                "🟢 Preservar Conteúdo (Anti-Silêncio / Sem Perdas)",
                "🟡 Equilibrado (Dinâmico - Padrão)",
                "🔴 Agressivo (O Suco Puro / Clímax)",
            ],
            variable=self.refine_mode_var,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLORS["bg_dark"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["bg_card_hover"],
            text_color=COLORS["text_primary"],
            height=34,
            command=self._on_setting_changed,
        )
        self.refine_mode_menu.pack(fill="x")

        # Col 2: Target Duration
        dur_box = ctk.CTkFrame(ctrls_row, fg_color="transparent")
        dur_box.pack(side="left", fill="x", expand=True, padx=(8, 0))

        ctk.CTkLabel(
            dur_box, text="⏱️  Duração Alvo do Mastercut:",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", pady=(0, 4))

        self.target_duration_var = ctk.StringVar(value="Automático Inteligente (Recomendado)")
        self.target_duration_menu = ctk.CTkOptionMenu(
            dur_box,
            values=[
                "Automático Inteligente (Recomendado)",
                "Manter Máximo (45s - 55s para 1 min)",
                "Padrão Shorts/Reels (35s - 50s)",
                "Curto & Rápido (25s - 35s)",
            ],
            variable=self.target_duration_var,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLORS["bg_dark"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["bg_card_hover"],
            text_color=COLORS["text_primary"],
            height=34,
            command=self._on_setting_changed,
        )
        self.target_duration_menu.pack(fill="x")

        # Dynamic Duration Hint & Anti-Cut Shield Banner
        self.hint_frame = ctk.CTkFrame(card, fg_color=COLORS["bg_dark"], corner_radius=8, border_width=1, border_color=COLORS["border"])
        self.hint_frame.pack(fill="x", padx=16, pady=(0, 12))

        h_inner = ctk.CTkFrame(self.hint_frame, fg_color="transparent")
        h_inner.pack(fill="x", padx=12, pady=8)

        self.hint_label = ctk.CTkLabel(
            h_inner,
            text="🛡️ Proteção Anti-Corte: Carregue um vídeo para ver a previsão exata de retenção e duração final.",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_secondary"],
            wraplength=700, justify="left",
            anchor="w",
        )
        self.hint_label.pack(fill="x")

        # Checkboxes row
        opts_row = ctk.CTkFrame(card, fg_color="transparent")
        opts_row.pack(fill="x", padx=16, pady=(0, 14))

        self.vocal_isolation_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            opts_row, text="Isolamento Vocal / Limpeza de Áudio (realça falas e remove ruídos)",
            variable=self.vocal_isolation_var,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_primary"],
            fg_color=COLORS["accent_primary"], hover_color=COLORS["accent_secondary"],
        ).pack(side="left", padx=(0, 20))

        self.anti_copyright_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            opts_row, text="Modo Anti-Copyright (micro-zoom 1.05x + velocidade 1.05x)",
            variable=self.anti_copyright_var,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_primary"],
            fg_color=COLORS["accent_primary"], hover_color=COLORS["accent_secondary"],
        ).pack(side="left")

    # ── Output Destination Section ────────────────────────────────────────

    def _build_output_section(self):
        card = ctk.CTkFrame(
            self.scroll, fg_color=COLORS["bg_card"],
            corner_radius=12, border_width=1, border_color=COLORS["border"],
        )
        card.pack(fill="x", pady=(0, 10))

        title_row = ctk.CTkFrame(card, fg_color="transparent")
        title_row.pack(fill="x", padx=16, pady=(12, 6))

        ctk.CTkLabel(
            title_row, text="💾  Destino / Onde Salvar o Mastercut",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(side="left")

        out_row = ctk.CTkFrame(card, fg_color="transparent")
        out_row.pack(fill="x", padx=16, pady=(0, 14))

        self.output_entry = ctk.CTkEntry(
            out_row,
            placeholder_text="Caminho de saída do Mastercut (padrão: mesma pasta do vídeo original)...",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_dark"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            placeholder_text_color=COLORS["text_muted"],
            height=38, corner_radius=8,
        )
        self.output_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            out_row, text="Escolher Destino",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_dark"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"],
            height=38, width=130, corner_radius=8,
            command=self._browse_output,
        ).pack(side="right")

    # ── Action Section ────────────────────────────────────────────────────

    def _build_action_section(self):
        row = ctk.CTkFrame(self.scroll, fg_color="transparent")
        row.pack(fill="x", pady=(0, 10))

        self.generate_btn = ctk.CTkButton(
            row, text="⚡  Gerar Mastercut Concentrado (30s-60s)",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=COLORS["accent_primary"], hover_color=COLORS["accent_secondary"],
            text_color="#09090b",
            height=46, corner_radius=10,
            command=self._start_mastercut,
        )
        self.generate_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.cancel_btn = ctk.CTkButton(
            row, text="⛔ Cancelar",
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

        p_inner = ctk.CTkFrame(self.progress_card, fg_color="transparent")
        p_inner.pack(fill="x", padx=16, pady=12)

        self.status_label = ctk.CTkLabel(
            p_inner, text="Aguardando início...",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        )
        self.status_label.pack(fill="x", pady=(0, 6))

        self.progress_bar = ctk.CTkProgressBar(
            p_inner, height=10, corner_radius=5,
            fg_color=COLORS["bg_dark"], progress_color=COLORS["accent_primary"],
        )
        self.progress_bar.pack(fill="x", pady=(0, 8))
        self.progress_bar.set(0)

        # Log box
        self.log_box = ctk.CTkTextbox(
            p_inner, height=90, corner_radius=8,
            fg_color=COLORS["console_bg"], text_color=COLORS["console_text"],
            font=ctk.CTkFont(family="Consolas", size=11),
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
            h_row, text="🎉  Mastercut Gerado com Sucesso!",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color="#10b981", anchor="w",
        ).pack(side="left")

        self.stats_label = ctk.CTkLabel(
            r_inner, text="Duração: 00:00 ➔ 00:00 (-0.0%) | 0 cortes",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_secondary"], anchor="w",
        )
        self.stats_label.pack(fill="x", pady=(4, 12))

        # Action buttons row: Preview + Send to Upscaler
        btn_row = ctk.CTkFrame(r_inner, fg_color="transparent")
        btn_row.pack(fill="x")

        self.preview_btn = ctk.CTkButton(
            btn_row, text="▶️  Pré-visualizar Vídeo",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=COLORS["bg_dark"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            height=42, corner_radius=10,
            command=self._preview_video,
        )
        self.preview_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.send_to_upscaler_btn = ctk.CTkButton(
            btn_row, text="⬆️  Usar no Upscaler (Avançar para Melhorias)",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=COLORS["accent_primary"], hover_color=COLORS["accent_secondary"],
            text_color="#09090b",
            height=42, corner_radius=10,
            command=self._send_to_upscaler,
        )
        self.send_to_upscaler_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.open_folder_btn = ctk.CTkButton(
            btn_row, text="📁 Pasta",
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

            # Auto-tune for short clips (e.g. <= 75s) to protect key moments
            if info.duration <= 75.0:
                cur_mode = self._get_refine_mode_key()
                if cur_mode == "aggressive":
                    self.refine_mode_var.set("🟡 Equilibrado (Dinâmico - Padrão)")

            self._update_duration_hint()

        # Auto-populate output path
        input_p = Path(filepath)
        default_out = str(input_p.parent / f"{input_p.stem}_mastercut_{int(time.time())}.mp4")
        self.output_entry.delete(0, "end")
        self.output_entry.insert(0, default_out)

    def _get_refine_mode_key(self) -> str:
        val = self.refine_mode_var.get() if hasattr(self, "refine_mode_var") else ""
        if "Preservar" in val:
            return "soft"
        if "Agressivo" in val:
            return "aggressive"
        return "balanced"

    def _get_target_duration_key(self) -> str:
        val = self.target_duration_var.get() if hasattr(self, "target_duration_var") else ""
        if "Manter Máximo" in val:
            return "max_retention"
        if "Padrão Shorts" in val:
            return "standard"
        if "Curto & Rápido" in val:
            return "short"
        return "auto"

    def _on_setting_changed(self, *args):
        self._update_duration_hint()

    def _update_duration_hint(self):
        if not hasattr(self, "hint_label"):
            return

        dur = self.current_video_info.duration if self.current_video_info else 0.0
        mode_key = self._get_refine_mode_key()
        dur_key = self._get_target_duration_key()

        if dur <= 0.0:
            self.hint_label.configure(
                text="🛡️ Proteção Anti-Corte: Carregue um vídeo para ver a estimativa exata de retenção e duração final."
            )
            return

        min_d, max_d = calculate_mastercut_bounds(dur, refine_mode=mode_key, target_duration_mode=dur_key)
        mode_name = "Preservar Conteúdo" if mode_key == "soft" else ("Agressivo" if mode_key == "aggressive" else "Equilibrado")

        if dur <= 75.0:
            if mode_key == "soft":
                msg = (
                    f"🛡️ Previsão para este clipe ({format_time(dur)}): Modo {mode_name} manterá {min_d:.1f}s a {max_d:.1f}s (~85% do vídeo). "
                    "Corta estritamente silêncios mortos (>0.35s), mantendo 100% dos diálogos, réplicas e momentos importantes!"
                )
            elif mode_key == "aggressive":
                msg = (
                    f"⚡ Previsão para este clipe ({format_time(dur)}): Modo {mode_name} condensará para {min_d:.1f}s a {max_d:.1f}s "
                    "focando no clímax de maior impacto."
                )
            else:
                msg = (
                    f"🛡️ Previsão Anti-Corte para este clipe ({format_time(dur)}): Modo {mode_name} manterá {min_d:.1f}s a {max_d:.1f}s "
                    "com ritmo acelerado, eliminando pausas mortas sem picotar o vídeo nem perder momentos essenciais (nunca gerará 19s!)."
                )
        else:
            msg = (
                f"🎯 Previsão para este vídeo ({format_time(dur)}): Duração final estimada entre {min_d:.1f}s e {max_d:.1f}s "
                f"(Modo: {mode_name}). Proteção de narrativa ativa para garantir início, desenvolvimento e clímax."
            )

        self.hint_label.configure(text=msg)

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
            title="Escolher onde salvar o Mastercut",
            filetypes=filetypes,
            defaultextension=".mp4",
            initialdir=initialdir,
            initialfile=initialfile,
        )
        if filepath:
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, filepath)

    def _log(self, text: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _start_mastercut(self):
        if not self.input_path or not os.path.exists(self.input_path):
            messagebox.showwarning("Aviso", "Por favor, selecione um arquivo de vídeo válido.")
            return

        if self.is_processing:
            return

        # Prepare output path from user entry or default
        custom_out = self.output_entry.get().strip()
        if custom_out:
            self.output_path = custom_out
        else:
            input_p = Path(self.input_path)
            out_name = f"{input_p.stem}_mastercut_{int(time.time())}.mp4"
            out_dir = input_p.parent
            self.output_path = str(out_dir / out_name)

        self.is_processing = True
        self._start_time = time.time()
        self.last_result = None

        # UI updates
        self.generate_btn.configure(state="disabled", text="⏳ Processando Mastercut...")
        self.cancel_btn.configure(state="normal", text_color=COLORS["error"])

        if not self.progress_card.winfo_ismapped():
            self.progress_card.pack(fill="x", pady=(0, 10))
        if self.result_card.winfo_ismapped():
            self.result_card.pack_forget()

        refine_mode = self._get_refine_mode_key()
        target_dur = self._get_target_duration_key()

        self._clear_log()
        self._log(f"════════ Refinador: Mastercut Concentrado ════════")
        self._log(f"Entrada: {self.input_path}")
        self._log(f"Saída:   {self.output_path}")
        self._log(f"Modo:    {refine_mode} | Duração Alvo: {target_dur}")

        vocal_iso = self.vocal_isolation_var.get()
        anti_copy = self.anti_copyright_var.get()
        video_ctx = self.context_entry.get().strip() if hasattr(self, 'context_entry') else ""
        if video_ctx:
            self._log(f"Contexto: {video_ctx}")

        def _worker():
            try:
                stats = self.pipeline.process(
                    video_path=self.input_path,
                    output_path=self.output_path,
                    video_context=video_ctx,
                    vocal_isolation=vocal_iso,
                    anti_copyright=anti_copy,
                    refine_mode=refine_mode,
                    target_duration_mode=target_dur,
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
        self.generate_btn.configure(state="normal", text="⚡  Gerar Mastercut Concentrado (30s-60s)")
        self.cancel_btn.configure(state="disabled", text_color=COLORS["text_muted"])

        dur_before = format_time(stats["duration_before"])
        dur_after = format_time(stats["duration_after"])
        pct = stats["time_saved_percent"]
        segs = stats["segments_count"]
        size = stats["size_mb"]

        self.stats_label.configure(
            text=f"Duração: {dur_before} ➔ {dur_after} ({pct}% economizado) | {segs} cortes | Tamanho: {size} MB"
        )
        self.result_card.pack(fill="x", pady=(0, 10))
        self._log(f"✓ Concluído com sucesso em {time.time() - self._start_time:.1f}s!")

    def _on_process_cancelled(self):
        self.is_processing = False
        self.generate_btn.configure(state="normal", text="⚡  Gerar Mastercut Concentrado (30s-60s)")
        self.cancel_btn.configure(state="disabled", text_color=COLORS["text_muted"])
        self.status_label.configure(text="Cancelado pelo usuário.")
        self._log("⛔ Processamento cancelado.")

    def _on_process_error(self, err_msg: str):
        self.is_processing = False
        self.generate_btn.configure(state="normal", text="⚡  Gerar Mastercut Concentrado (30s-60s)")
        self.cancel_btn.configure(state="disabled", text_color=COLORS["text_muted"])
        self.status_label.configure(text="Erro no processamento.")
        self._log(f"✕ Erro: {err_msg}")
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

    def _send_to_upscaler(self):
        """Transfers the generated mastercut video into the main Upscaling tab."""
        if not self.output_path or not os.path.exists(self.output_path):
            messagebox.showwarning("Aviso", "Vídeo não encontrado para enviar.")
            return

        if self.main_app:
            # Load video into main app
            self.main_app._load_video(self.output_path)
            # Switch tab to Upscaling
            self.main_app.tabview.set("⬆  Upscaling")
            self.main_app._set_status("✓ Vídeo do Mastercut carregado! Escolha as melhorias e inicie o upscaling.", COLORS["success"])
        else:
            messagebox.showinfo("Sucesso", f"Vídeo salvo em:\n{self.output_path}")

    def _open_output_folder(self):
        if self.output_path and os.path.exists(self.output_path):
            folder = os.path.dirname(os.path.abspath(self.output_path))
            subprocess.run(["explorer", folder])
        elif self.input_path and os.path.exists(self.input_path):
            folder = os.path.dirname(os.path.abspath(self.input_path))
            subprocess.run(["explorer", folder])
