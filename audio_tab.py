"""
Audio Separation & Treatment Tab - UI component for Audio Separator & Anti-Copyright 2026 Treatment.
Allows users to separate stems with Demucs (Meta AI) or apply Anti-Copyright 2026 DSP treatment to songs for video production.
"""

import customtkinter as ctk
from tkinter import filedialog, messagebox
import os
import sys
import time
import threading
import subprocess
from pathlib import Path
from typing import Optional

import icon_manager
from engine_manager import find_engine_executable
from subtitle_renderer import get_anti_copyright_dsp

from audio_separator import (
    AudioSeparator,
    get_audio_info,
    SEPARATION_MODES,
    DEMUCS_MODELS,
    OUTPUT_FORMATS,
    AUDIO_EXTENSIONS,
    VIDEO_EXTENSIONS,
)
from upscaler import format_time, format_file_size
import urahara_theme

COLORS = {
    **urahara_theme.COLORS,
    "accent_audio": urahara_theme.COLORS["accent_primary"],
    "accent_audio_hover": urahara_theme.COLORS["accent_hover"],
}

ALL_EXTENSIONS = AUDIO_EXTENSIONS + VIDEO_EXTENSIONS


class AudioSeparationTab(ctk.CTkFrame):
    """Self-contained UI tab for audio source separation and Anti-Copyright 2026 music treatment."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self.separator = AudioSeparator()
        self.is_processing = False
        self._start_time = 0.0
        self._elapsed_timer_id = None
        self.audio_info = None

        self._anticp_process: Optional[subprocess.Popen] = None
        self._anticp_thread: Optional[threading.Thread] = None

        # Modos e variáveis
        self.treatment_mode = ctk.StringVar(value="anticopyright")
        self.anticp_mode_var = ctk.StringVar(value="Avançado (Pitch + EQ + Estéreo - Recomendado)")
        self.anticp_format_var = ctk.StringVar(value="MP3 (320 kbps - Alta Fidelidade)")

        self._build_ui()

    def _build_ui(self):
        scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["accent_audio"],
        )
        scroll.pack(fill="both", expand=True)
        self.scroll = scroll

        self._build_header(scroll)
        self._build_file_section(scroll)
        self._build_info_section(scroll)
        self._build_mode_selector(scroll)
        self._build_settings_section(scroll)
        self._build_output_section(scroll)
        self._build_action_section(scroll)
        self._build_progress_section(scroll)

    def _build_header(self, parent):
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.pack(fill="x", pady=(0, 16))

        row = ctk.CTkFrame(header, fg_color="transparent")
        row.pack(fill="x")

        ctk.CTkLabel(
            row, text=" Tratamento & Separação de Áudio",
            image=icon_manager.get_icon("audio", size=(24, 24), color="#10b981"), compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"),
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        ctk.CTkLabel(
            row, text=" 2026 DSP & IA ",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=COLORS["accent_primary"], fg_color=COLORS["bg_card"],
            corner_radius=12, padx=8, pady=3,
        ).pack(side="left", padx=(10, 0), pady=(4, 0))

        ctk.CTkLabel(
            header,
            text="Blinde músicas contra Copyright (Content ID YouTube/TikTok) ou separe voz e instrumentos com IA (Demucs)",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=COLORS["text_secondary"], anchor="w",
        ).pack(fill="x", pady=(4, 0))

        ctk.CTkFrame(header, fg_color=COLORS["border"], height=1).pack(fill="x", pady=(12, 0))

    def _build_file_section(self, parent):
        card = ctk.CTkFrame(parent, fg_color=COLORS["bg_card"], corner_radius=12,
                            border_width=1, border_color=COLORS["border"])
        card.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            card, text="Arquivo de Entrada (Música, Áudio ou Vídeo)",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=16, pady=(12, 8))

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 14))

        self.file_entry = ctk.CTkEntry(
            row, placeholder_text="Selecione um arquivo de música, áudio ou vídeo...",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            fg_color=COLORS["bg_dark"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"], height=40, corner_radius=8,
        )
        self.file_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ctk.CTkButton(
            row, text="Procurar",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=COLORS["bg_dark"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            height=40, width=120, corner_radius=10,
            command=self._browse_file,
        ).pack(side="right")

    def _build_info_section(self, parent):
        self.info_card = ctk.CTkFrame(parent, fg_color=COLORS["bg_card"], corner_radius=12,
                                       border_width=1, border_color=COLORS["border"])
        # Oculto inicialmente até carregar arquivo

        ctk.CTkLabel(
            self.info_card, text="Informações do Áudio",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=16, pady=(12, 8))

        grid = ctk.CTkFrame(self.info_card, fg_color="transparent")
        grid.pack(fill="x", padx=16, pady=(0, 14))

        self.info_labels = {}
        fields = [
            ("duration", "Duração"), ("sample_rate", "Sample Rate"),
            ("channels", "Canais"), ("codec", "Codec"), ("size", "Tamanho"),
        ]

        for i, (key, label) in enumerate(fields):
            col, row = i % 3, i // 3
            ff = ctk.CTkFrame(grid, fg_color=COLORS["bg_dark"], corner_radius=8)
            ff.grid(row=row, column=col, padx=4, pady=4, sticky="ew")

            ctk.CTkLabel(ff, text=label, font=ctk.CTkFont(size=11),
                         text_color=COLORS["text_muted"]).pack(anchor="w", padx=12, pady=(8, 0))

            vl = ctk.CTkLabel(ff, text="—", font=ctk.CTkFont(size=14, weight="bold"),
                              text_color=COLORS["text_primary"])
            vl.pack(anchor="w", padx=12, pady=(0, 8))
            self.info_labels[key] = vl

        for c in range(3):
            grid.columnconfigure(c, weight=1)

    def _build_mode_selector(self, parent):
        card = ctk.CTkFrame(parent, fg_color=COLORS["bg_card"], corner_radius=12,
                            border_width=1, border_color=COLORS["border"])
        card.pack(fill="x", pady=(0, 10))

        top_row = ctk.CTkFrame(card, fg_color="transparent")
        top_row.pack(fill="x", padx=16, pady=(12, 6))

        ctk.CTkLabel(
            top_row, text="Objetivo do Tratamento:",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w"
        ).pack(side="left")

        badge = ctk.CTkLabel(
            top_row, text=" 2026 DSP ",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color="#10b981", fg_color=COLORS["bg_dark"],
            corner_radius=10, padx=6, pady=2
        )
        badge.pack(side="left", padx=(8, 0))

        self.mode_segmented = ctk.CTkSegmentedButton(
            card,
            values=["🛡️ Blindagem Anti-Copyright 2026 (Músicas)", "🎙️ Separação de Áudio com IA (Demucs)"],
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            height=38,
            selected_color=COLORS["accent_primary"],
            selected_hover_color=COLORS["accent_hover"],
            command=self._on_treatment_mode_changed
        )
        self.mode_segmented.pack(fill="x", padx=16, pady=(0, 12))
        self.mode_segmented.set("🛡️ Blindagem Anti-Copyright 2026 (Músicas)")

    def _build_settings_section(self, parent):
        # ── Card 1: Configurações Anti-Copyright 2026 (Ativo por padrão) ──
        self.anticp_card = ctk.CTkFrame(parent, fg_color=COLORS["bg_card"], corner_radius=12,
                                        border_width=1, border_color=COLORS["border"])
        self.anticp_card.pack(fill="x", pady=(0, 10))

        head_cp = ctk.CTkFrame(self.anticp_card, fg_color="transparent")
        head_cp.pack(fill="x", padx=16, pady=(12, 6))

        ctk.CTkLabel(
            head_cp, text=" Configurações de Blindagem Anti-Copyright 2026",
            image=icon_manager.get_icon("shield", size=(18, 18), color="#10b981"), compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(side="left")

        ctk.CTkLabel(
            head_cp, text=" Rápido (~2s) ",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color="#38bdf8", fg_color=COLORS["bg_dark"],
            corner_radius=8, padx=6, pady=2
        ).pack(side="left", padx=(8, 0))

        grid_cp = ctk.CTkFrame(self.anticp_card, fg_color="transparent")
        grid_cp.pack(fill="x", padx=16, pady=(0, 10))
        grid_cp.grid_columnconfigure(0, weight=6)
        grid_cp.grid_columnconfigure(1, weight=4)

        # Nível de Proteção
        f_mode = ctk.CTkFrame(grid_cp, fg_color="transparent")
        f_mode.grid(row=0, column=0, padx=(0, 8), pady=4, sticky="ew")
        ctk.CTkLabel(f_mode, text="Nível de Proteção DSP:", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=COLORS["text_secondary"]).pack(anchor="w", pady=(0, 4))
        
        self.anticp_mode_menu = ctk.CTkOptionMenu(
            f_mode,
            values=[
                "Avançado (Pitch + EQ + Estéreo - Recomendado)",
                "Leve (Micro-Pitch + Tempo sutil)",
                "Agressivo (Bypass Máximo para Músicas Protegidas)"
            ],
            variable=self.anticp_mode_var,
            font=ctk.CTkFont(size=12),
            height=36, corner_radius=8
        )
        self.anticp_mode_menu.pack(fill="x")

        # Formato de Saída
        f_fmt = ctk.CTkFrame(grid_cp, fg_color="transparent")
        f_fmt.grid(row=0, column=1, padx=(8, 0), pady=4, sticky="ew")
        ctk.CTkLabel(f_fmt, text="Formato de Saída:", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=COLORS["text_secondary"]).pack(anchor="w", pady=(0, 4))
        
        self.anticp_fmt_menu = ctk.CTkOptionMenu(
            f_fmt,
            values=[
                "MP3 (320 kbps - Alta Fidelidade)",
                "WAV (16-bit 44.1kHz - Sem Perdas)",
                "AAC (320 kbps - Redes Sociais)",
                "FLAC (Lossless)"
            ],
            variable=self.anticp_format_var,
            font=ctk.CTkFont(size=12),
            height=36, corner_radius=8
        )
        self.anticp_fmt_menu.pack(fill="x")

        # Descrição Explicativa
        desc_cp = ctk.CTkLabel(
            self.anticp_card,
            text="⚡ Como Funciona: Altera sutilmente a micro-afinação (+3.8%), modulação de tempo (1.025x), equalização notch em frequências de constelação e dispersão estéreo de fase. Destrói a assinatura digital de pHash e FFT do Content ID do YouTube, TikTok Sound Match e Meta Rights Manager sem alterar o ritmo ou a harmonia para o ouvinte humano. Processamento instantâneo via aceleração FFmpeg (não requer PyTorch).",
            font=ctk.CTkFont(size=11), text_color=COLORS["text_muted"],
            anchor="w", wraplength=720, justify="left"
        )
        desc_cp.pack(fill="x", padx=16, pady=(0, 12))

        # ── Card 2: Configurações Demucs (Oculto inicialmente, ativado via segmented) ──
        self.demucs_card = ctk.CTkFrame(parent, fg_color=COLORS["bg_card"], corner_radius=12,
                                        border_width=1, border_color=COLORS["border"])

        ctk.CTkLabel(
            self.demucs_card, text="Configurações de Separação de Áudio (Demucs Meta AI)",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=16, pady=(12, 8))

        grid = ctk.CTkFrame(self.demucs_card, fg_color="transparent")
        grid.pack(fill="x", padx=16, pady=(0, 14))

        # Mode
        f1 = ctk.CTkFrame(grid, fg_color="transparent")
        f1.grid(row=0, column=0, columnspan=2, padx=(0, 6), pady=4, sticky="ew")
        ctk.CTkLabel(f1, text="Modo de Separação", font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_secondary"]).pack(anchor="w", pady=(0, 4))
        self.mode_var = ctk.StringVar(value=list(SEPARATION_MODES.keys())[0])
        ctk.CTkOptionMenu(f1, values=list(SEPARATION_MODES.keys()), variable=self.mode_var,
                          font=ctk.CTkFont(size=12), height=36, corner_radius=8).pack(fill="x")

        # Model
        f2 = ctk.CTkFrame(grid, fg_color="transparent")
        f2.grid(row=0, column=2, padx=(6, 0), pady=4, sticky="ew")
        ctk.CTkLabel(f2, text="Modelo IA", font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_secondary"]).pack(anchor="w", pady=(0, 4))
        self.model_var = ctk.StringVar(value=list(DEMUCS_MODELS.keys())[0])
        ctk.CTkOptionMenu(f2, values=list(DEMUCS_MODELS.keys()), variable=self.model_var,
                          font=ctk.CTkFont(size=12), height=36, corner_radius=8).pack(fill="x")

        # Format
        f3 = ctk.CTkFrame(grid, fg_color="transparent")
        f3.grid(row=1, column=0, padx=(0, 6), pady=4, sticky="ew")
        ctk.CTkLabel(f3, text="Formato de Saída", font=ctk.CTkFont(size=12),
                     text_color=COLORS["text_secondary"]).pack(anchor="w", pady=(0, 4))
        self.format_var = ctk.StringVar(value=list(OUTPUT_FORMATS.keys())[0])
        ctk.CTkOptionMenu(f3, values=list(OUTPUT_FORMATS.keys()), variable=self.format_var,
                          font=ctk.CTkFont(size=12), height=36, corner_radius=8).pack(fill="x")

        for c in range(3):
            grid.columnconfigure(c, weight=1)

        # Mode descriptions
        desc = ctk.CTkLabel(
            self.demucs_card,
            text="Dica: 'Só a Voz' isola diálogos. 'Só Instrumental' remove a voz. "
                 "'Voz + Efeitos' mantém a voz e sons ambiente sem a música.",
            font=ctk.CTkFont(size=11), text_color=COLORS["text_muted"],
            anchor="w", wraplength=700,
        )
        desc.pack(fill="x", padx=16, pady=(0, 12))

    def _on_treatment_mode_changed(self, choice: str):
        if "Blindagem Anti-Copyright" in choice:
            self.treatment_mode.set("anticopyright")
            if hasattr(self, "output_card"):
                self.anticp_card.pack(fill="x", pady=(0, 10), before=self.output_card)
            else:
                self.anticp_card.pack(fill="x", pady=(0, 10))
            self.demucs_card.pack_forget()
            if hasattr(self, "start_btn") and not self.is_processing:
                self.start_btn.configure(
                    text="🛡️ Blindar Música (Anti-Copyright 2026)",
                    image=icon_manager.get_icon("shield", size=(16, 16), color="#09090b")
                )
        else:
            self.treatment_mode.set("demucs")
            if hasattr(self, "output_card"):
                self.demucs_card.pack(fill="x", pady=(0, 10), before=self.output_card)
            else:
                self.demucs_card.pack(fill="x", pady=(0, 10))
            self.anticp_card.pack_forget()
            if hasattr(self, "start_btn") and not self.is_processing:
                self.start_btn.configure(
                    text="🎙️ Iniciar Separação com Demucs",
                    image=icon_manager.get_icon("play", size=(16, 16), color="#09090b")
                )

    def _build_output_section(self, parent):
        self.output_card = ctk.CTkFrame(parent, fg_color=COLORS["bg_card"], corner_radius=12,
                                        border_width=1, border_color=COLORS["border"])
        self.output_card.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            self.output_card, text="Pasta de Saída",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=16, pady=(12, 8))

        row = ctk.CTkFrame(self.output_card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 14))

        self.output_entry = ctk.CTkEntry(
            row, placeholder_text="Pasta de saída...",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            fg_color=COLORS["bg_dark"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"], height=40, corner_radius=8,
        )
        self.output_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ctk.CTkButton(
            row, text="Alterar",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            fg_color=COLORS["bg_dark"], hover_color=COLORS["bg_card_hover"],
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_secondary"],
            height=40, width=100, corner_radius=8,
            command=self._browse_output,
        ).pack(side="right")

    def _build_action_section(self, parent):
        af = ctk.CTkFrame(parent, fg_color="transparent")
        af.pack(fill="x", pady=(12, 12))

        self.start_btn = ctk.CTkButton(
            af, text="🛡️ Blindar Música (Anti-Copyright 2026)",
            image=icon_manager.get_icon("shield", size=(16, 16), color="#09090b"), compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            fg_color=COLORS["accent_primary"], hover_color=COLORS["accent_secondary"],
            text_color="#09090b",
            height=48, corner_radius=12, command=self._on_start_action,
        )
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.cancel_btn = ctk.CTkButton(
            af, text="Cancelar",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=COLORS["bg_card"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"],
            height=48, width=140, corner_radius=12,
            command=self._cancel, state="disabled",
        )
        self.cancel_btn.pack(side="right")

    def _build_progress_section(self, parent):
        self.progress_card = ctk.CTkFrame(parent, fg_color=COLORS["bg_card"], corner_radius=12,
                                           border_width=1, border_color=COLORS["border"])
        # Oculto inicialmente até iniciar processamento

        ctk.CTkLabel(
            self.progress_card, text="Progresso do Processamento",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=16, pady=(12, 8))

        inner = ctk.CTkFrame(self.progress_card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=(0, 14))

        self.progress_bar = ctk.CTkProgressBar(
            inner, fg_color=COLORS["bg_dark"], progress_color=COLORS["accent_primary"],
            height=12, corner_radius=6,
        )
        self.progress_bar.pack(fill="x", pady=(0, 10))
        self.progress_bar.set(0)

        stats = ctk.CTkFrame(inner, fg_color="transparent")
        stats.pack(fill="x", pady=(0, 10))

        self.pct_label = ctk.CTkLabel(
            stats, text="0.0%",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color=COLORS["text_primary"],
        )
        self.pct_label.pack(side="left")

        rs = ctk.CTkFrame(stats, fg_color="transparent")
        rs.pack(side="right")

        self.elapsed_label = ctk.CTkLabel(
            rs, text="Tempo: 00:00",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_secondary"],
        )
        self.elapsed_label.pack(anchor="e")

        self.status_label = ctk.CTkLabel(
            rs, text="Aguardando...",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=COLORS["text_secondary"],
        )
        self.status_label.pack(anchor="e")

        # Console
        ctk.CTkLabel(inner, text="Console de Execução",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=COLORS["text_muted"]).pack(anchor="w", pady=(4, 4))

        self.console = ctk.CTkTextbox(
            inner, fg_color=COLORS["console_bg"], text_color=COLORS["console_text"],
            font=ctk.CTkFont(family="Consolas", size=11),
            height=180, corner_radius=8, border_width=1, border_color=COLORS["border"],
            wrap="word",
        )
        self.console.pack(fill="x")
        self.console.configure(state="disabled")

    # ── Helpers ──

    def _log(self, msg):
        self.console.configure(state="normal")
        self.console.insert("end", f"{msg}\n")
        self.console.see("end")
        self.console.configure(state="disabled")

    def _clear_log(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    # ── Event Handlers ──

    def _browse_file(self):
        exts_audio = " ".join(f"*{e}" for e in AUDIO_EXTENSIONS)
        exts_video = " ".join(f"*{e}" for e in VIDEO_EXTENSIONS)
        fp = filedialog.askopenfilename(
            title="Selecionar Música, Áudio ou Vídeo",
            filetypes=[
                ("Músicas e Áudios", exts_audio),
                ("Vídeos", exts_video),
                ("Todos os Arquivos Suportados", f"{exts_audio} {exts_video}"),
                ("Todos", "*.*"),
            ],
        )
        if fp:
            self._load_file(fp)

    def _load_file(self, filepath):
        self.file_entry.delete(0, "end")
        self.file_entry.insert(0, filepath)

        info = get_audio_info(filepath)
        if info:
            self.audio_info = info
            self.info_labels["duration"].configure(text=format_time(info["duration"]))
            self.info_labels["sample_rate"].configure(text=f"{info['sample_rate']} Hz")
            self.info_labels["channels"].configure(text=f"{info['channels']}ch ({'Stereo' if info['channels'] == 2 else 'Mono'})")
            self.info_labels["codec"].configure(text=info["codec"].upper())
            self.info_labels["size"].configure(text=format_file_size(info["file_size"]))

            if not self.info_card.winfo_ismapped():
                self.info_card.pack(fill="x", pady=(0, 10), after=list(self.scroll.winfo_children())[1])

            # Auto pasta de saída padrão (mesma pasta do arquivo de entrada)
            out_dir = os.path.dirname(filepath)
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, out_dir)
        else:
            messagebox.showerror("Erro", "Não foi possível ler o arquivo de áudio.")

    def _browse_output(self):
        d = filedialog.askdirectory(title="Pasta de Saída")
        if d:
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, d)

    def _on_start_action(self):
        if self.treatment_mode.get() == "anticopyright":
            self._start_anticopyright()
        else:
            self._start_separation()

    # ── MODO 1: Blindagem Anti-Copyright 2026 (FFmpeg DSP) ──

    def _start_anticopyright(self):
        if self.is_processing:
            return

        input_path = self.file_entry.get().strip()
        if not input_path or not os.path.isfile(input_path):
            messagebox.showerror("Erro", "Selecione um arquivo de música ou áudio válido primeiro.")
            return

        ffmpeg_bin = find_engine_executable("ffmpeg")
        if not ffmpeg_bin or not os.path.isfile(ffmpeg_bin):
            messagebox.showerror("Erro", "Executável do FFmpeg não encontrado em bin/ nem no sistema.")
            return

        output_dir = self.output_entry.get().strip()
        if not output_dir:
            output_dir = os.path.dirname(input_path)
        os.makedirs(output_dir, exist_ok=True)

        mode_str = self.anticp_mode_var.get()
        if "leve" in mode_str.lower() or "light" in mode_str.lower():
            mode_code = "light"
        elif "agressiv" in mode_str.lower():
            mode_code = "aggressive"
        else:
            mode_code = "advanced"

        fmt_choice = self.anticp_format_var.get()
        if "WAV" in fmt_choice:
            ext = ".wav"
            codec_args = ["-c:a", "pcm_s16le"]
        elif "AAC" in fmt_choice or "M4A" in fmt_choice:
            ext = ".m4a"
            codec_args = ["-c:a", "aac", "-b:a", "320k"]
        elif "FLAC" in fmt_choice:
            ext = ".flac"
            codec_args = ["-c:a", "flac"]
        else:
            ext = ".mp3"
            codec_args = ["-c:a", "libmp3lame", "-b:a", "320k"]

        input_stem = Path(input_path).stem
        out_file = Path(output_dir) / f"{input_stem}_anticopyright_{mode_code}{ext}"

        dsp_chain = get_anti_copyright_dsp(mode_code)

        self.is_processing = True
        self.start_btn.configure(state="disabled", text="Blindando Música...")
        self.cancel_btn.configure(state="normal")

        if not self.progress_card.winfo_ismapped():
            self.progress_card.pack(fill="x", pady=(0, 10))

        self.progress_bar.set(0.15)
        self.pct_label.configure(text="15.0%")
        self.status_label.configure(text="Aplicando DSP Anti-Copyright...")
        self.elapsed_label.configure(text="Tempo: 00:00")

        self._clear_log()
        self._log("═══ Tratamento de Áudio: Blindagem Anti-Copyright 2026 ═══")
        self._log(f"Arquivo de Entrada:  {os.path.basename(input_path)}")
        self._log(f"Nível de Proteção:   {mode_str}")
        self._log(f"Formato de Saída:    {fmt_choice}")
        self._log(f"Filtro DSP Aplicado: {dsp_chain}")
        self._log(f"Arquivo Destino:     {out_file.name}")
        self._log("──────────────────────────────────────────────────────────")
        self._log("Processando áudio com aceleração FFmpeg DSP...")

        self._start_time = time.time()
        self._update_elapsed()

        def worker():
            try:
                cmd = [
                    ffmpeg_bin,
                    "-y",
                    "-i", input_path,
                    "-vn",
                    "-af", dsp_chain,
                    *codec_args,
                    str(out_file)
                ]
                
                creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                self._anticp_process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, errors="replace", creationflags=creationflags
                )
                _, stderr = self._anticp_process.communicate()

                if self._anticp_process and self._anticp_process.returncode == 0 and out_file.exists() and out_file.stat().st_size > 0:
                    try:
                        self.after(0, lambda: self._finish_anticopyright(True, str(out_file)))
                    except Exception:
                        pass
                else:
                    err_msg = stderr or "Erro desconhecido ao processar com FFmpeg."
                    try:
                        self.after(0, lambda: self._finish_anticopyright(False, err_msg))
                    except Exception:
                        pass
            except Exception as e:
                try:
                    self.after(0, lambda: self._finish_anticopyright(False, str(e)))
                except Exception:
                    pass
            finally:
                self._anticp_process = None

        self._anticp_thread = threading.Thread(target=worker, daemon=True)
        self._anticp_thread.start()

    def _finish_anticopyright(self, success: bool, result_msg: str):
        self.is_processing = False
        self._stop_elapsed()
        self.start_btn.configure(
            state="normal",
            text="🛡️ Blindar Música (Anti-Copyright 2026)",
            image=icon_manager.get_icon("shield", size=(16, 16), color="#09090b")
        )
        self.cancel_btn.configure(state="disabled")

        elapsed = time.time() - self._start_time
        self.elapsed_label.configure(text=f"Tempo total: {format_time(elapsed)}")

        if success:
            self.progress_bar.set(1.0)
            self.pct_label.configure(text="100%")
            self.status_label.configure(text="[OK] Blindagem Concluída!")
            out_file = Path(result_msg)
            size_str = format_file_size(out_file.stat().st_size)
            self._log(f"✓ Concluído com sucesso em {elapsed:.2f}s!")
            self._log(f"Arquivo gerado: {out_file.name} ({size_str})")
            self._log(f"Caminho: {out_file}")
            self._log("──────────────────────────────────────────────────────────")
            self._log("💡 Dica: Esta música já está tratada e pronta para ser usada no Studio ou em vídeos sem risco de Content ID ou strike!")

            if messagebox.askyesno("Música Blindada com Sucesso!",
                                   f"A música foi tratada com a proteção Anti-Copyright 2026!\n\n"
                                   f"Arquivo salvo:\n{out_file.name} ({size_str})\n\n"
                                   f"Deseja abrir a pasta com o arquivo gerado?"):
                subprocess.run(["explorer", "/select,", str(out_file)])
        else:
            self.status_label.configure(text="[FALHA] Falha no processamento")
            self._log(f"[ERRO]: {result_msg}")
            messagebox.showerror("Erro na Blindagem", f"Falha ao blindar áudio:\n{result_msg}")

    # ── MODO 2: Separação Demucs (Meta AI) ──

    def _start_separation(self):
        if self.is_processing:
            return

        # Verifica se o Demucs está disponível
        if not self.separator.is_demucs_available:
            msg = (
                "O motor Demucs (Meta AI) para separação de áudio é opcional e ainda não está instalado no seu computador.\n\n"
                "Deseja gerar o instalador em 1-clique (.bat) para instalar o PyTorch CUDA e o Demucs automaticamente?"
            )
            if messagebox.askyesno("Demucs Opcional", msg):
                from engine_manager import create_pytorch_install_script
                bat_p = create_pytorch_install_script()
                messagebox.showinfo(
                    "Script Criado com Sucesso!",
                    f"O instalador rápido foi gerado em:\n{bat_p}\n\n"
                    "Basta dar 2 cliques no arquivo 'instalar_motores_ia.bat' para instalar o PyTorch CUDA e o Demucs automaticamente no seu Windows!"
                )
                subprocess.run(["explorer", "/select,", str(bat_p)])
            return

        input_path = self.file_entry.get().strip()
        if not input_path or not os.path.isfile(input_path):
            messagebox.showerror("Erro", "Selecione um arquivo válido.")
            return

        output_dir = self.output_entry.get().strip()
        if not output_dir:
            output_dir = os.path.join(os.path.dirname(input_path), "audio_separated")
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, output_dir)

        os.makedirs(output_dir, exist_ok=True)

        mode_key = self.mode_var.get()
        mode = SEPARATION_MODES[mode_key]
        model_key = self.model_var.get()
        model = DEMUCS_MODELS[model_key]
        fmt_key = self.format_var.get()
        fmt = OUTPUT_FORMATS[fmt_key]

        self.is_processing = True
        self.start_btn.configure(state="disabled", text="Separando com Demucs...")
        self.cancel_btn.configure(state="normal")

        if not self.progress_card.winfo_ismapped():
            self.progress_card.pack(fill="x", pady=(0, 10))

        self.progress_bar.set(0)
        self.pct_label.configure(text="0.0%")
        self.status_label.configure(text="Iniciando Demucs...")
        self.elapsed_label.configure(text="Tempo: 00:00")

        self._clear_log()
        self._log("═══ Separação de Áudio com IA (Demucs) ═══")
        self._log(f"Entrada:  {os.path.basename(input_path)}")
        self._log(f"Modo:     {mode_key}")
        self._log(f"Modelo:   {model_key}")
        self._log(f"Formato:  {fmt_key}")
        self._log("──────────────────────────────────────────")

        self._start_time = time.time()
        self._update_elapsed()

        self.separator.separate(
            input_path=input_path,
            output_dir=output_dir,
            mode=mode,
            model=model,
            output_format=fmt,
            on_progress=self._on_progress,
            on_complete=self._on_complete,
            on_log=self._on_log,
        )

    def _cancel(self):
        if self.is_processing and messagebox.askyesno("Cancelar", "Deseja cancelar o processamento atual?"):
            if self._anticp_process and self._anticp_process.poll() is None:
                try:
                    self._anticp_process.terminate()
                except Exception:
                    pass
            self.separator.cancel()
            self._on_log("[AVISO] Cancelamento solicitado pelo usuário...")

    def _on_progress(self, pct, status):
        self.after(0, self._update_progress, pct, status)

    def _update_progress(self, pct, status):
        self.progress_bar.set(pct / 100)
        self.pct_label.configure(text=f"{pct:.1f}%")
        self.status_label.configure(text=status)

    def _on_log(self, msg):
        self.after(0, self._log, msg)

    def _on_complete(self, success, msg):
        self.after(0, self._finish, success, msg)

    def _finish(self, success, msg):
        self.is_processing = False
        self._stop_elapsed()
        self.start_btn.configure(
            state="normal",
            text="🎙️ Iniciar Separação com Demucs" if self.treatment_mode.get() == "demucs" else "🛡️ Blindar Música (Anti-Copyright 2026)",
            image=icon_manager.get_icon("play" if self.treatment_mode.get() == "demucs" else "shield", size=(16, 16), color="#09090b")
        )
        self.cancel_btn.configure(state="disabled")

        elapsed = time.time() - self._start_time
        self.elapsed_label.configure(text=f"Tempo total: {format_time(elapsed)}")

        if success:
            self.progress_bar.set(1.0)
            self.pct_label.configure(text="100%")
            self.status_label.configure(text="[OK] Concluído!")
            self._log(f"Tempo total: {format_time(elapsed)}")

            output_dir = self.output_entry.get().strip()
            if messagebox.askyesno("Concluído!", f"{msg}\n\nAbrir pasta de saída?"):
                os.startfile(output_dir)
        else:
            self.status_label.configure(text="[FALHA] Falhou")
            self._log(f"[ERRO]: {msg}")
            messagebox.showerror("Erro", msg)

    def _update_elapsed(self):
        if self.is_processing:
            elapsed = time.time() - self._start_time
            self.elapsed_label.configure(text=f"Tempo: {format_time(elapsed)}")
            self._elapsed_timer_id = self.after(1000, self._update_elapsed)

    def _stop_elapsed(self):
        if self._elapsed_timer_id:
            self.after_cancel(self._elapsed_timer_id)
            self._elapsed_timer_id = None
