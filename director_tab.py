"""
Director Tab - UI component for Diretor IA (Top 3 & Smart Cortes de Episódios)
Allows analyzing long episodes (20+ minutes) to identify peak viral moments,
previewing the exact scenes, cutting them instantly via FFmpeg,
and transferring them directly to the Refiner (Mastercut) or Upscaler.
"""

import os
import re
import time
import threading
import subprocess
from pathlib import Path
from typing import Optional, List, Dict
import customtkinter as ctk
from tkinter import filedialog, messagebox

from director_ai import (
    analyze_episode,
    analyze_episode_reroll,
    cut_clip_fast,
    preview_clip_ffplay,
    parse_candidate_times,
    _time_str_to_seconds,
    ranges_overlap,
)
from upscaler import (
    get_video_info,
    format_time,
    find_ffmpeg,
    find_ffplay,
)

COLORS = {
    "bg_dark": "#09090b",
    "bg_card": "#111113",
    "bg_card_hover": "#18181b",
    "accent_primary": "#e2e8f0",
    "accent_secondary": "#94a3b8",
    "accent_director": "#e2e8f0",
    "accent_director_hover": "#a1a1aa",
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


class DirectorTab(ctk.CTkFrame):
    """Self-contained UI tab for Diretor IA."""

    def __init__(self, parent, main_app=None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.main_app = main_app

        self.input_path = ""
        self.current_video_info = None
        self.is_processing = False
        self.candidates = []

        # Cache for reroll (skip re-transcription)
        self._last_transcript: str = ""
        self._last_lore: str = ""
        # Stores excluded ranges as list of (start_sec, end_sec, label) tuples for robust overlap detection
        self._all_excluded_ranges: List[tuple] = []  # (start_sec, end_sec, str_repr)
        self._all_excluded_strs: List[str] = []      # formatted strings sent to prompt

        self._build_ui()

    def _build_ui(self):
        self.scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["accent_director"],
        )
        self.scroll.pack(fill="both", expand=True)

        self._build_header()
        self._build_file_section()
        self._build_info_section()
        self._build_config_section()
        self._build_action_section()
        self._build_progress_section()
        self._build_results_section()

    def _build_header(self):
        header = ctk.CTkFrame(self.scroll, fg_color="transparent")
        header.pack(fill="x", pady=(0, 14))

        row = ctk.CTkFrame(header, fg_color="transparent")
        row.pack(fill="x")

        ctk.CTkLabel(
            row, text="🎬  Diretor IA",
            font=ctk.CTkFont(family="Segoe UI", size=26, weight="bold"),
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        ctk.CTkLabel(
            row, text=" Smart Cortes & Top 3 ",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=COLORS["text_secondary"], fg_color=COLORS["bg_card"],
            corner_radius=12, padx=8, pady=3,
        ).pack(side="left", padx=(10, 0), pady=(4, 0))

        ctk.CTkLabel(
            header,
            text="Analise episódios longos de animes/séries. A IA mapeia lore, falas e hype da internet para achar os melhores cortes.",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_secondary"], anchor="w",
        ).pack(fill="x", pady=(4, 0))

        ctk.CTkFrame(header, fg_color=COLORS["border"], height=1).pack(fill="x", pady=(10, 0))

    def _build_file_section(self):
        card = ctk.CTkFrame(
            self.scroll, fg_color=COLORS["bg_card"],
            corner_radius=12, border_width=1, border_color=COLORS["border"],
        )
        card.pack(fill="x", pady=(0, 10))

        h_row = ctk.CTkFrame(card, fg_color="transparent")
        h_row.pack(fill="x", padx=16, pady=(12, 6))

        ctk.CTkLabel(
            h_row, text="📁  Episódio / Vídeo Longo",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        ctk.CTkButton(
            h_row, text="⚡ Usar vídeo do Upscaler",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLORS["bg_dark"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"],
            height=28, corner_radius=6,
            command=self._sync_from_main_app,
        ).pack(side="right")

        f_row = ctk.CTkFrame(card, fg_color="transparent")
        f_row.pack(fill="x", padx=16, pady=(0, 10))

        self.file_entry = ctk.CTkEntry(
            f_row, placeholder_text="Selecione o episódio longo...",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_dark"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"], height=38, corner_radius=8,
        )
        self.file_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            f_row, text="Buscar Vídeo",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=COLORS["bg_dark"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            height=38, width=110, corner_radius=10,
            command=self._browse_file,
        ).pack(side="right")

        # Output directory row (onde salvar)
        out_lbl_row = ctk.CTkFrame(card, fg_color="transparent")
        out_lbl_row.pack(fill="x", padx=16, pady=(4, 4))
        ctk.CTkLabel(
            out_lbl_row, text="💾  Pasta de Saída dos Cortes (Onde Salvar):",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLORS["text_secondary"], anchor="w",
        ).pack(side="left")

        out_dir_row = ctk.CTkFrame(card, fg_color="transparent")
        out_dir_row.pack(fill="x", padx=16, pady=(0, 14))

        self.output_dir_entry = ctk.CTkEntry(
            out_dir_row, placeholder_text="Pasta de destino (padrão: mesma pasta do episódio)...",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_dark"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"], height=38, corner_radius=8,
        )
        self.output_dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            out_dir_row, text="Escolher Pasta",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_dark"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"],
            height=38, width=130, corner_radius=8,
            command=self._browse_output_dir,
        ).pack(side="right")

    def _build_info_section(self):
        self.info_card = ctk.CTkFrame(
            self.scroll, fg_color=COLORS["bg_card"],
            corner_radius=10, border_width=1, border_color=COLORS["border"],
        )
        # Not packed initially

        grid = ctk.CTkFrame(self.info_card, fg_color="transparent")
        grid.pack(fill="x", padx=16, pady=10)
        grid.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.info_labels = {}
        fields = [
            ("Duração:", "duration", 0),
            ("Resolução:", "resolution", 1),
            ("FPS:", "fps", 2),
            ("Tamanho:", "size", 3),
        ]
        for label_text, key, col in fields:
            f = ctk.CTkFrame(grid, fg_color="transparent")
            f.grid(row=0, column=col, sticky="ew", padx=4)
            ctk.CTkLabel(
                f, text=label_text,
                font=ctk.CTkFont(family="Segoe UI", size=10),
                text_color=COLORS["text_secondary"], anchor="w",
            ).pack(fill="x")
            lbl = ctk.CTkLabel(
                f, text="--",
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                text_color=COLORS["text_primary"], anchor="w",
            )
            lbl.pack(fill="x")
            self.info_labels[key] = lbl

    def _build_config_section(self):
        card = ctk.CTkFrame(
            self.scroll, fg_color=COLORS["bg_card"],
            corner_radius=12, border_width=1, border_color=COLORS["border"],
        )
        card.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            card, text="🧠  Contexto e Modo da Curadoria",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=16, pady=(12, 6))

        # Context row
        ctk.CTkLabel(
            card, text="Nome do Anime / Série e Episódio (para pesquisar lore e reações):",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_secondary"], anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 4))

        self.context_entry = ctk.CTkEntry(
            card,
            placeholder_text="Ex: Chainsaw Man Episódio 8 (Emboscada da Katana Man e Tiroteio)",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_dark"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"], height=38, corner_radius=8,
        )
        self.context_entry.pack(fill="x", padx=16, pady=(0, 12))

        # Mode row
        mode_row = ctk.CTkFrame(card, fg_color="transparent")
        mode_row.pack(fill="x", padx=16, pady=(0, 10))

        ctk.CTkLabel(
            mode_row, text="Escopo da Curadoria:",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_secondary"],
        ).pack(side="left", padx=(0, 10))

        self.mode_var = ctk.StringVar(value="🏆 Top 3 do Episódio (Picos de Hype)")
        modes = [
            "🏆 Top 3 do Episódio (Picos de Hype)",
            "🧠 Smart Cortes (Curadoria Sincera)",
        ]
        ctk.CTkOptionMenu(
            mode_row, values=modes, variable=self.mode_var,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_dark"], button_color=COLORS["border"],
            button_hover_color=COLORS["accent_director"],
            height=36, corner_radius=8, width=280,
        ).pack(side="left")

        # Modo de Corte (Contexto, Contínuo, Arco Narrativo)
        self._build_cut_mode_selector(card)

    def _build_cut_mode_selector(self, parent):
        """Build interactive selectable cards matching user design (Contexto, Contínuo, Arco Narrativo)."""
        ctk.CTkLabel(
            parent, text="Modo de Corte",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=16, pady=(10, 8))

        cards_container = ctk.CTkFrame(parent, fg_color="transparent")
        cards_container.pack(fill="x", padx=16, pady=(0, 16))
        cards_container.grid_columnconfigure((0, 1, 2), weight=1, uniform="modes")

        self.cut_mode_var = ctk.StringVar(value="context")
        self.cut_mode_cards = {}

        mode_defs = [
            {
                "key": "context",
                "title": "Contexto",
                "badge": "ATUAL",
                "badge_color": "#18181b",
                "badge_text_color": "#a1a1aa",
                "desc": "Vídeo com diálogos e narrativa. Perfeito para shorts que contam uma mini-história.",
                "col": 0,
            },
            {
                "key": "continuous",
                "title": "Contínuo",
                "badge": "NOVO",
                "badge_color": "#18181b",
                "badge_text_color": "#a1a1aa",
                "desc": "1 trecho contínuo, sem cortes internos — menos alucinação e falhas de fala. Refine depois na aba Refinador.",
                "col": 1,
            },
            {
                "key": "narrative_arc",
                "title": "Arco Narrativo",
                "badge": "NOVO",
                "badge_color": "#18181b",
                "badge_text_color": "#a1a1aa",
                "desc": "Analisa 3 a 20 min do episódio e comprime num vídeo de 1–2 min contando a história completa.",
                "col": 2,
            },
        ]

        for m in mode_defs:
            card_f = ctk.CTkFrame(
                cards_container,
                fg_color=COLORS["bg_dark"],
                corner_radius=10,
                border_width=1,
                border_color=COLORS["border"],
                cursor="hand2",
            )
            card_f.grid(row=0, column=m["col"], sticky="nsew", padx=4)

            inner = ctk.CTkFrame(card_f, fg_color="transparent", cursor="hand2")
            inner.pack(fill="both", expand=True, padx=14, pady=12)

            t_row = ctk.CTkFrame(inner, fg_color="transparent", cursor="hand2")
            t_row.pack(fill="x", pady=(0, 6))

            lbl_title = ctk.CTkLabel(
                t_row, text=m["title"],
                font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                text_color=COLORS["text_primary"], anchor="w",
                cursor="hand2",
            )
            lbl_title.pack(side="left")

            lbl_badge = ctk.CTkLabel(
                t_row, text=f" {m['badge']} ",
                font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
                text_color=m["badge_text_color"],
                fg_color=m["badge_color"],
                corner_radius=4, padx=5, pady=1,
                cursor="hand2",
            )
            lbl_badge.pack(side="left", padx=(6, 0))

            lbl_desc = ctk.CTkLabel(
                inner, text=m["desc"],
                font=ctk.CTkFont(family="Segoe UI", size=10),
                text_color=COLORS["text_secondary"], anchor="w",
                justify="left", wraplength=250,
                cursor="hand2",
            )
            lbl_desc.pack(fill="both", expand=True)

            self.cut_mode_cards[m["key"]] = card_f

            def _make_handler(k=m["key"]):
                return lambda e: self._select_cut_mode(k)

            card_f.bind("<Button-1>", _make_handler())
            inner.bind("<Button-1>", _make_handler())
            t_row.bind("<Button-1>", _make_handler())
            lbl_title.bind("<Button-1>", _make_handler())
            lbl_badge.bind("<Button-1>", _make_handler())
            lbl_desc.bind("<Button-1>", _make_handler())

        self._update_cut_mode_visuals()

    def _select_cut_mode(self, mode_key: str):
        self.cut_mode_var.set(mode_key)
        self._update_cut_mode_visuals()

    def _update_cut_mode_visuals(self):
        active = self.cut_mode_var.get()
        for k, card in self.cut_mode_cards.items():
            if k == active:
                card.configure(
                    border_color=COLORS["border_active"],
                    border_width=1,
                    fg_color=COLORS["bg_card_hover"],
                )
            else:
                card.configure(
                    border_color=COLORS["border"],
                    border_width=1,
                    fg_color=COLORS["bg_dark"],
                )

    def _build_action_section(self):
        card = ctk.CTkFrame(self.scroll, fg_color="transparent")
        card.pack(fill="x", pady=(4, 10))

        self.analyze_btn = ctk.CTkButton(
            card, text="🎬  Analisar Episódio com Diretor IA",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=COLORS["accent_primary"], hover_color=COLORS["accent_secondary"],
            text_color="#09090b",
            height=44, corner_radius=10,
            command=self._start_analysis,
        )
        self.analyze_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.cancel_btn = ctk.CTkButton(
            card, text="✕ Cancelar",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_card"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"],
            height=44, width=100, corner_radius=8,
            state="disabled",
            command=self._cancel_analysis,
        )
        self.cancel_btn.pack(side="right")

    def _build_progress_section(self):
        self.progress_card = ctk.CTkFrame(
            self.scroll, fg_color=COLORS["bg_card"],
            corner_radius=12, border_width=1, border_color=COLORS["border"],
        )
        # Not packed initially

        inner = ctk.CTkFrame(self.progress_card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=12)

        self.progress_status_label = ctk.CTkLabel(
            inner, text="Iniciando...",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_primary"], anchor="w",
        )
        self.progress_status_label.pack(fill="x", pady=(0, 6))

        self.progress_bar = ctk.CTkProgressBar(
            inner, fg_color=COLORS["bg_dark"],
            progress_color=COLORS["accent_primary"], height=8, corner_radius=4,
        )
        self.progress_bar.pack(fill="x", pady=(0, 10))
        self.progress_bar.set(0)

        # Log box
        self.log_box = ctk.CTkTextbox(
            inner, height=90,
            fg_color=COLORS["console_bg"], text_color=COLORS["console_text"],
            font=ctk.CTkFont(family="Consolas", size=11),
            corner_radius=6, border_width=1, border_color=COLORS["border"],
        )
        self.log_box.pack(fill="x")
        self.log_box.configure(state="disabled")

    def _build_results_section(self):
        self.results_container = ctk.CTkFrame(self.scroll, fg_color="transparent")
        self.results_container.pack(fill="x", pady=(10, 20))
        # Candidates will be dynamically populated here

    # ── Actions & Execution ───────────────────────────────────────────────

    def _sync_from_main_app(self):
        if self.main_app and self.main_app.file_entry.get().strip():
            path = self.main_app.file_entry.get().strip()
            self._load_video(path)
        else:
            messagebox.showinfo("Aviso", "Nenhum vídeo selecionado na aba Upscaling.")

    def _browse_output_dir(self):
        initial = self.output_dir_entry.get().strip() or (str(Path(self.input_path).parent) if self.input_path else "")
        d = filedialog.askdirectory(
            title="Escolher Pasta para Salvar os Cortes",
            initialdir=initial,
        )
        if d:
            self.output_dir_entry.delete(0, "end")
            self.output_dir_entry.insert(0, d)

    def _browse_file(self):
        filetypes = [
            ("Vídeos", "*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.m4v *.ts"),
            ("Todos os arquivos", "*.*"),
        ]
        filepath = filedialog.askopenfilename(
            title="Selecionar Episódio Longo",
            filetypes=filetypes,
        )
        if filepath:
            self._load_video(filepath)

    def _load_video(self, filepath: str):
        self.input_path = filepath
        self.file_entry.delete(0, "end")
        self.file_entry.insert(0, filepath)

        # Default output directory to video's folder if empty
        p = Path(filepath)
        if not self.output_dir_entry.get().strip():
            self.output_dir_entry.delete(0, "end")
            self.output_dir_entry.insert(0, str(p.parent))

        info = get_video_info(filepath)
        if info:
            self.current_video_info = info
            self.info_labels["duration"].configure(text=format_time(info.duration))
            self.info_labels["resolution"].configure(text=f"{info.width}×{info.height}")
            self.info_labels["fps"].configure(text=f"{info.fps:.1f}")
            self.info_labels["size"].configure(text=info.file_size_label)

            if not self.info_card.winfo_ismapped():
                self.info_card.pack(fill="x", pady=(0, 10))

            # Auto-suggest context if empty
            if not self.context_entry.get().strip():
                clean_name = Path(filepath).stem.replace("_", " ").replace("-", " ")
                self.context_entry.insert(0, clean_name)

    def _log(self, text: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _start_analysis(self):
        if not self.input_path or not os.path.exists(self.input_path):
            messagebox.showwarning("Aviso", "Por favor, selecione um arquivo de vídeo válido primeiro.")
            return

        if self.is_processing:
            return

        self.is_processing = True
        self.analyze_btn.configure(state="disabled", text="⏳ Analisando Episódio...")
        self.cancel_btn.configure(state="normal")

        if not self.progress_card.winfo_ismapped():
            self.progress_card.pack(fill="x", pady=(0, 10))

        self.progress_bar.set(0)
        self._clear_log()

        # Clear previous candidate cards
        for widget in self.results_container.winfo_children():
            widget.destroy()

        # Reset excluded ranges for fresh analysis
        self._all_excluded_ranges = []
        self._all_excluded_strs = []
        self._last_transcript = ""
        self._last_lore = ""

        context = self.context_entry.get().strip()
        mode_str = "top3" if "Top 3" in self.mode_var.get() else "smart"
        cut_mode_str = self.cut_mode_var.get() if hasattr(self, "cut_mode_var") else "context"
        duration = self.current_video_info.duration if self.current_video_info else 0.0
        ffmpeg_bin = find_ffmpeg() or "ffmpeg"

        def _thread():
            try:
                def _on_progress(pct, msg):
                    self.after(0, lambda: self._update_progress(pct, msg))

                def _on_log(msg):
                    self.after(0, lambda: self._log(msg))

                candidates, transcript, lore = analyze_episode(
                    video_path=self.input_path,
                    context=context,
                    mode=mode_str,
                    cut_mode=cut_mode_str,
                    video_duration=duration,
                    ffmpeg_bin=ffmpeg_bin,
                    on_progress=_on_progress,
                    on_log=_on_log,
                )
                self.after(0, lambda: self._on_analysis_finished(True, candidates, transcript, lore))
            except Exception as e:
                self.after(0, lambda: self._on_analysis_finished(False, str(e), "", ""))

        threading.Thread(target=_thread, daemon=True).start()

    def _update_progress(self, pct: float, msg: str):
        self.progress_bar.set(pct / 100.0)
        self.progress_status_label.configure(text=f"{msg} ({int(pct)}%)")

    def _cancel_analysis(self):
        self.is_processing = False
        self.analyze_btn.configure(state="normal", text="🎬  Analisar Episódio com Diretor IA")
        self.cancel_btn.configure(state="disabled")
        self._log("✕ Operação cancelada.")

    def _on_analysis_finished(self, success: bool, data, transcript: str = "", lore: str = ""):
        self.is_processing = False
        self.analyze_btn.configure(state="normal", text="🎬  Analisar Episódio com Diretor IA")
        self.cancel_btn.configure(state="disabled")

        if not success:
            messagebox.showerror("Erro na Análise", f"Falha ao analisar episódio:\n{data}")
            return

        # Cache transcript & lore for potential rerolls
        self._last_transcript = transcript
        self._last_lore = lore

        # Accumulate excluded ranges from this batch using overlap detection
        for c in (data or []):
            st_str = c.get("start_time", "")
            et_str = c.get("end_time", "")
            if st_str and et_str:
                st_sec = _time_str_to_seconds(st_str)
                et_sec = _time_str_to_seconds(et_str)
                if et_sec > st_sec:
                    # Only add if no existing range overlaps significantly
                    if not any(ranges_overlap(st_sec, et_sec, ex_st, ex_et) for ex_st, ex_et, _ in self._all_excluded_ranges):
                        rng_str = f"{st_str} -> {et_str}"
                        self._all_excluded_ranges.append((st_sec, et_sec, rng_str))
                        self._all_excluded_strs.append(rng_str)

        self.candidates = data
        if not self.candidates:
            self._log("⚠ Nenhum corte encontrado com os critérios fornecidos.")
            return

        self._render_candidates()

    def _render_candidates(self):
        """Build modern visual cards for each candidate identified by AI."""
        for widget in self.results_container.winfo_children():
            widget.destroy()

        header_row = ctk.CTkFrame(self.results_container, fg_color="transparent")
        header_row.pack(fill="x", pady=(0, 12))

        header_lbl = ctk.CTkLabel(
            header_row,
            text=f"✨ {len(self.candidates)} Melhores Momentos Selecionados pelo Diretor:",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        )
        header_lbl.pack(side="left", fill="x", expand=True)

        btn_row_right = ctk.CTkFrame(header_row, fg_color="transparent")
        btn_row_right.pack(side="right")

        # Reroll button
        ctk.CTkButton(
            btn_row_right,
            text="🔄 Novos Cortes",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=COLORS["bg_dark"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border_active"],
            text_color=COLORS["text_primary"],
            height=32, corner_radius=10,
            command=self._start_reroll,
        ).pack(side="left", padx=(0, 8))

        # Batch export all cuts button
        ctk.CTkButton(
            btn_row_right,
            text=f"💾 Salvar Todos ({len(self.candidates)})",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=COLORS["bg_card"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            height=32, corner_radius=10,
            command=self._save_all_candidates,
        ).pack(side="left")

        for idx, cand in enumerate(self.candidates, 1):
            self._build_candidate_card(cand, idx)

    def _save_all_candidates(self):
        """Batch extract and save all identified moments to the output folder."""
        if not self.candidates:
            return
        if self.is_processing:
            messagebox.showwarning("Aguarde", "Existe uma operação em andamento.")
            return

        total = len(self.candidates)
        if not messagebox.askyesno(
            "Salvar Todos os Cortes",
            f"Deseja extrair e salvar todos os {total} trechos para a pasta selecionada?"
        ):
            return

        self.is_processing = True
        self._log(f"📦 Iniciando extração em lote de {total} momentos...")

        def _batch_worker():
            saved_count = 0
            out_dir_path = ""
            for idx, cand in enumerate(self.candidates, 1):
                title = cand.get("title") or f"Momento #{idx}"
                self.after(0, lambda t=title, i=idx: self._log(f"⏳ Extraindo [{i}/{total}]: {t}..."))
                out_path, err = self._create_cut_file(cand)
                if out_path:
                    saved_count += 1
                    out_dir_path = os.path.dirname(os.path.abspath(out_path))
                    self.after(0, lambda p=out_path: self._log(f"   ✓ Salvo: {os.path.basename(p)}"))
                else:
                    self.after(0, lambda e=err: self._log(f"   ✕ Falha: {e}"))

            def _batch_done():
                self.is_processing = False
                self._log(f"✨ Concluído! {saved_count}/{total} cortes salvos com sucesso.")
                resp = messagebox.askyesno(
                    "Extração em Lote Concluída",
                    f"{saved_count} de {total} cortes foram salvos com sucesso!\n\nDeseja abrir a pasta agora?"
                )
                if resp and out_dir_path:
                    try:
                        if os.name == 'nt':
                            os.startfile(out_dir_path)
                        else:
                            subprocess.Popen(["xdg-open", out_dir_path])
                    except Exception:
                        pass

            self.after(0, _batch_done)

        threading.Thread(target=_batch_worker, daemon=True).start()

    def _start_reroll(self):
        """Re-run AI curation with the same transcript/lore but excluding previously shown clips."""
        if self.is_processing:
            messagebox.showwarning("Aguarde", "Existe uma operação em andamento.")
            return

        if not self.input_path or not os.path.exists(self.input_path):
            messagebox.showwarning("Aviso", "Nenhum vídeo carregado.")
            return

        if not self._last_transcript and not self._last_lore and not self.context_entry.get().strip():
            messagebox.showinfo(
                "Análise Necessária",
                "Realize a análise completa primeiro. O Reroll usa a transcrição já gerada para ser mais rápido."
            )
            return

        self.is_processing = True
        self.analyze_btn.configure(state="disabled", text="⏳ Gerando Novos Cortes...")

        if not self.progress_card.winfo_ismapped():
            self.progress_card.pack(fill="x", pady=(0, 10))

        self.progress_bar.set(0)
        self._clear_log()
        self._log(f"🔄 Gerando novos cortes alternativos ({len(self._all_excluded_ranges)} trechos já excluídos)...")

        context = self.context_entry.get().strip()
        mode_str = "top3" if "Top 3" in self.mode_var.get() else "smart"
        cut_mode_str = self.cut_mode_var.get() if hasattr(self, "cut_mode_var") else "context"
        duration = self.current_video_info.duration if self.current_video_info else 0.0
        excluded = list(self._all_excluded_strs)  # snapshot of formatted strings for prompt

        def _thread():
            try:
                def _on_progress(pct, msg):
                    self.after(0, lambda: self._update_progress(pct, msg))

                def _on_log(msg):
                    self.after(0, lambda: self._log(msg))

                new_candidates = analyze_episode_reroll(
                    context=context,
                    transcript=self._last_transcript,
                    lore=self._last_lore,
                    mode=mode_str,
                    cut_mode=cut_mode_str,
                    video_duration=duration,
                    excluded_ranges=excluded,
                    on_progress=_on_progress,
                    on_log=_on_log,
                )
                self.after(0, lambda: self._on_reroll_finished(True, new_candidates))
            except Exception as e:
                self.after(0, lambda: self._on_reroll_finished(False, str(e)))

        threading.Thread(target=_thread, daemon=True).start()

    def _on_reroll_finished(self, success: bool, data):
        self.is_processing = False
        self.analyze_btn.configure(state="normal", text="🎬  Analisar Episódio com Diretor IA")

        if not success:
            messagebox.showerror("Erro no Reroll", f"Falha ao gerar novos cortes:\n{data}")
            return

        if not data:
            self._log("⚠ Nenhum novo corte encontrado. O vídeo pode não ter mais trechos não mostrados.")
            messagebox.showinfo(
                "Sem Novos Cortes",
                "A IA não encontrou mais trechos alternativos não mostrados anteriormente.\n\n"
                "Tente mudar o Modo de Corte ou o Escopo da Curadoria e clique em 'Analisar Episódio' novamente."
            )
            return

        # Accumulate exclusion ranges from this new batch with overlap detection
        for c in data:
            st_str = c.get("start_time", "")
            et_str = c.get("end_time", "")
            if st_str and et_str:
                st_sec = _time_str_to_seconds(st_str)
                et_sec = _time_str_to_seconds(et_str)
                if et_sec > st_sec:
                    if not any(ranges_overlap(st_sec, et_sec, ex_st, ex_et) for ex_st, ex_et, _ in self._all_excluded_ranges):
                        rng_str = f"{st_str} -> {et_str}"
                        self._all_excluded_ranges.append((st_sec, et_sec, rng_str))
                        self._all_excluded_strs.append(rng_str)

        self.candidates = data
        self._log(f"✨ {len(data)} novos cortes alternativos prontos!")
        self._render_candidates()

    def _build_candidate_card(self, cand: dict, idx: int):
        card = ctk.CTkFrame(
            self.results_container, fg_color=COLORS["bg_card"],
            corner_radius=12, border_width=1, border_color=COLORS["border"],
        )
        card.pack(fill="x", pady=(0, 12))


        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=12)

        # Top row: Title + Score badge
        top_row = ctk.CTkFrame(inner, fg_color="transparent")
        top_row.pack(fill="x")

        score = cand.get("quality_score", 8)
        score_color = "#10b981" if score >= 8.5 else "#f59e0b"

        title_text = str(cand.get("title") or f"Momento #{idx}")
        ctk.CTkLabel(
            top_row, text=f"#{idx}  {title_text}",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(side="left", fill="x", expand=True)

        badge_text = f"⭐ Nota {score}/10"
        ctk.CTkLabel(
            top_row, text=f" {badge_text} ",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="white", fg_color=score_color,
            corner_radius=6, padx=8, pady=2,
        ).pack(side="right")

        # Sub row: Timestamps + Editable Time Inputs + Duration + Genre
        max_dur = self.current_video_info.duration if self.current_video_info else 0.0
        start_sec, dur_sec, start_t, end_t, dur_calc = parse_candidate_times(cand, max_duration=max_dur)
        dur_t = cand.get("duration") or dur_calc
        genre = cand.get("genre", "")

        is_arc = dur_sec >= 180 or "Arco" in genre or (hasattr(self, "cut_mode_var") and self.cut_mode_var.get() == "narrative_arc")

        meta_frame = ctk.CTkFrame(inner, fg_color="transparent")
        meta_frame.pack(fill="x", pady=(4, 6))

        # Time controls (editable)
        ctk.CTkLabel(
            meta_frame, text="⏱️ Início:",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLORS["text_secondary"],
        ).pack(side="left", padx=(0, 4))

        start_entry = ctk.CTkEntry(
            meta_frame, width=70, height=26,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLORS["bg_dark"], border_color=COLORS["border"],
            justify="center",
        )
        start_entry.insert(0, start_t)
        start_entry.pack(side="left", padx=(0, 8))

        ctk.CTkLabel(
            meta_frame, text="➔ Fim:",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLORS["text_secondary"],
        ).pack(side="left", padx=(0, 4))

        end_entry = ctk.CTkEntry(
            meta_frame, width=70, height=26,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLORS["bg_dark"], border_color=COLORS["border"],
            justify="center",
        )
        end_entry.insert(0, end_t)
        end_entry.pack(side="left", padx=(0, 8))

        dur_label = ctk.CTkLabel(
            meta_frame, text=f"({dur_t})",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLORS["accent_director"],
        )
        dur_label.pack(side="left", padx=(0, 10))

        if is_arc:
            ctk.CTkLabel(
                meta_frame, text="• 🗺️ Arco Narrativo (Comprimir no Refinador)",
                font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
                text_color="#f59e0b",
            ).pack(side="left", padx=(0, 4))
        elif genre:
            ctk.CTkLabel(
                meta_frame, text=f"• {genre}",
                font=ctk.CTkFont(family="Segoe UI", size=11),
                text_color=COLORS["text_secondary"],
            ).pack(side="left", padx=(0, 4))

        def _sync_candidate_times():
            s_val = start_entry.get().strip()
            e_val = end_entry.get().strip()
            if s_val:
                cand["start_time"] = s_val
            if e_val:
                cand["end_time"] = e_val
            # Clear range strings so user's edits take priority
            cand.pop("estimated_range", None)
            cand.pop("range", None)
            cand.pop("time_range", None)
            s_sec, d_sec, st_str, et_str, d_str = parse_candidate_times(cand, max_duration=max_dur)
            dur_label.configure(text=f"({d_str})")
            cand["duration"] = d_str
            return s_sec, d_sec, st_str, et_str, d_str

        start_entry.bind("<FocusOut>", lambda e: _sync_candidate_times())
        start_entry.bind("<Return>", lambda e: _sync_candidate_times())
        end_entry.bind("<FocusOut>", lambda e: _sync_candidate_times())
        end_entry.bind("<Return>", lambda e: _sync_candidate_times())

        # Description
        desc = cand.get("description", "")
        if desc:
            ctk.CTkLabel(
                inner, text=desc,
                font=ctk.CTkFont(family="Segoe UI", size=11),
                text_color=COLORS["text_secondary"], anchor="w",
                wraplength=750, justify="left",
            ).pack(fill="x", pady=(0, 4))

        # Director critique
        reason = cand.get("quality_reasoning", "")
        if reason:
            ctk.CTkLabel(
                inner, text=f"💡 Por que viraliza: {reason}",
                font=ctk.CTkFont(family="Segoe UI", size=11, slant="italic"),
                text_color=COLORS["text_muted"], anchor="w",
                wraplength=750, justify="left",
            ).pack(fill="x", pady=(0, 10))

        # Action buttons row
        btn_row = ctk.CTkFrame(inner, fg_color="transparent")
        btn_row.pack(fill="x", pady=(4, 0))

        # References to buttons so callbacks can toggle them
        btn_refs = {}

        # 1. Preview
        btn_prev = ctk.CTkButton(
            btn_row, text="▶️ Preview",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color=COLORS["bg_dark"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            height=32, corner_radius=10, width=88,
            command=lambda c=cand, s=_sync_candidate_times: (s(), self._preview_candidate(c)),
        )
        btn_prev.pack(side="left", padx=(0, 6))

        # 2. Salvar Corte Rápido
        btn_cut = ctk.CTkButton(
            btn_row, text="💾 Salvar Corte",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color=COLORS["accent_primary"], hover_color=COLORS["accent_secondary"],
            text_color="#09090b",
            height=32, corner_radius=10, width=105,
            command=lambda c=cand, s=_sync_candidate_times: (s(), self._cut_candidate(c, save_as=False, btn=btn_refs.get("cut"))),
        )
        btn_cut.pack(side="left", padx=(0, 6))
        btn_refs["cut"] = btn_cut

        # 3. Salvar Como...
        btn_saveas = ctk.CTkButton(
            btn_row, text="📁 Salvar Como...",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLORS["bg_dark"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"],
            height=32, corner_radius=10, width=110,
            command=lambda c=cand, s=_sync_candidate_times: (s(), self._cut_candidate(c, save_as=True, btn=btn_refs.get("saveas"))),
        )
        btn_saveas.pack(side="left", padx=(0, 6))
        btn_refs["saveas"] = btn_saveas

        # 4. Refinar (Mastercut)
        refine_title = "⚡ Condensar Arco no Refinador" if is_arc else "⚡ Refinar (Mastercut)"
        btn_refine = ctk.CTkButton(
            btn_row, text=refine_title,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color=COLORS["bg_dark"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            height=32, corner_radius=10, width=165 if is_arc else 145,
            command=lambda c=cand, s=_sync_candidate_times: (s(), self._send_to_refiner(c, btn=btn_refs.get("refine"))),
        )
        btn_refine.pack(side="left", padx=(0, 6))
        btn_refs["refine"] = btn_refine

        # 5. Upscaler
        btn_upscale = ctk.CTkButton(
            btn_row, text="🚀 Enviar para Upscaler",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color=COLORS["bg_dark"], hover_color=COLORS["bg_card_hover"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            height=32, corner_radius=10, width=150,
            command=lambda c=cand, s=_sync_candidate_times: (s(), self._send_to_upscaler(c, btn=btn_refs.get("upscale"))),
        )
        btn_upscale.pack(side="left")
        btn_refs["upscale"] = btn_upscale

    def _preview_candidate(self, cand: dict):
        ffplay_bin = find_ffplay() or "ffplay"
        max_dur = self.current_video_info.duration if self.current_video_info else 0.0
        start_sec, dur_sec, start_t, end_t, _ = parse_candidate_times(cand, max_duration=max_dur)
        ok = preview_clip_ffplay(self.input_path, start_time=start_sec, duration=dur_sec, ffplay_bin=ffplay_bin)
        if not ok:
            messagebox.showwarning("Aviso", "Não foi possível abrir o FFplay para pré-visualização.")

    def _create_cut_file(self, cand: dict, custom_out_path: Optional[str] = None) -> tuple[Optional[str], str]:
        """
        Extract the clip fast and return (output_path, error_message).
        Thread-safe and handles Windows filename sanitization and directory creation.
        """
        if not self.input_path or not os.path.exists(self.input_path):
            return None, "Nenhum arquivo de vídeo válido selecionado."

        max_dur = self.current_video_info.duration if self.current_video_info else 0.0
        start_sec, dur_sec, start_str, end_str, _ = parse_candidate_times(cand, max_duration=max_dur)
        clean_input = str(self.input_path).strip().strip('"\'')
        p = Path(clean_input)

        if custom_out_path:
            out_path = os.path.abspath(custom_out_path)
        else:
            # Clean title for Windows filenames
            raw_title = cand.get("title") or "corte"
            clean_title = re.sub(r'[\\/*?:"<>|]', '', str(raw_title))
            clean_title = re.sub(r'[^\w\s\-.,()]', '', clean_title, flags=re.UNICODE).strip()
            clean_title = re.sub(r'\s+', '_', clean_title)[:45]
            if not clean_title:
                clean_title = "corte"

            # Clean time tag without colons
            time_tag = start_str.replace(":", "m") + "s"
            out_name = f"{p.stem}_{clean_title}_{time_tag}.mp4"

            custom_dir = self.output_dir_entry.get().strip().strip('"\'')
            if custom_dir:
                try:
                    os.makedirs(custom_dir, exist_ok=True)
                    out_dir = Path(custom_dir)
                except Exception:
                    out_dir = p.parent
            else:
                out_dir = p.parent

            out_path = str(out_dir / out_name)

        ffmpeg_bin = find_ffmpeg() or "ffmpeg"
        ok, err = cut_clip_fast(
            clean_input,
            start_time=start_sec,
            duration_sec=dur_sec,
            output_path=out_path,
            ffmpeg_bin=ffmpeg_bin
        )
        if ok and os.path.exists(out_path) and os.path.getsize(out_path) > 1024:
            return out_path, ""
        return None, err

    def _cut_candidate(self, cand: dict, save_as: bool = False, btn=None):
        """Cut and save the candidate clip with asynchronous execution."""
        custom_out = None
        if save_as:
            raw_title = cand.get("title") or "corte"
            clean_title = re.sub(r'[\\/*?:"<>|]', '', str(raw_title)).strip()[:30]
            clean_input = str(self.input_path).strip().strip('"\'')
            p = Path(clean_input)
            initial_name = f"{p.stem}_{clean_title}.mp4"
            initial_dir = self.output_dir_entry.get().strip().strip('"\'') or str(p.parent)

            custom_out = filedialog.asksaveasfilename(
                title="Salvar Trecho Como...",
                initialdir=initial_dir,
                initialfile=initial_name,
                filetypes=[("Vídeo MP4", "*.mp4"), ("Vídeo MKV", "*.mkv"), ("Todos", "*.*")],
                defaultextension=".mp4",
            )
            if not custom_out:
                return

        orig_text = btn.cget("text") if btn else ""
        if btn:
            btn.configure(state="disabled", text="⏳ Cortando...")

        def _worker():
            out_path, err = self._create_cut_file(cand, custom_out_path=custom_out)

            def _ui_done():
                if btn and btn.winfo_exists():
                    btn.configure(state="normal", text=orig_text)

                if out_path:
                    self._log(f"✓ Trecho extraído com sucesso: {out_path}")
                    resp = messagebox.askyesno(
                        "Corte Salvo com Sucesso!",
                        f"Trecho extraído e salvo com sucesso!\n\nArquivo:\n{out_path}\n\nDeseja abrir a pasta onde foi salvo?"
                    )
                    if resp:
                        try:
                            out_dir = os.path.dirname(os.path.abspath(out_path))
                            if os.name == 'nt':
                                os.startfile(out_dir)
                            else:
                                subprocess.Popen(["xdg-open", out_dir])
                        except Exception as e:
                            self._log(f"⚠ Não foi possível abrir pasta: {e}")
                else:
                    self._log(f"✕ Falha ao cortar trecho: {err}")
                    messagebox.showerror("Erro ao Cortar", f"Falha ao extrair vídeo com FFmpeg:\n\n{err}")

            self.after(0, _ui_done)

        threading.Thread(target=_worker, daemon=True).start()

    def _send_to_refiner(self, cand: dict, btn=None):
        """Cut the candidate clip and transfer directly to Refiner (Mastercut) tab."""
        orig_text = btn.cget("text") if btn else ""
        if btn:
            btn.configure(state="disabled", text="⏳ Preparando...")

        def _worker():
            out_path, err = self._create_cut_file(cand)

            def _ui_done():
                if btn and btn.winfo_exists():
                    btn.configure(state="normal", text=orig_text)

                if not out_path:
                    self._log(f"✕ Erro ao preparar corte para o Refinador: {err}")
                    messagebox.showerror("Erro", f"Falha ao gerar o corte do trecho:\n{err}")
                    return

                self._log(f"✓ Corte pronto e transferido para o Refinador: {out_path}")
                max_dur = self.current_video_info.duration if self.current_video_info else 0.0
                start_sec, dur_sec, _, _, _ = parse_candidate_times(cand, max_duration=max_dur)
                is_arc = dur_sec >= 180 or (hasattr(self, "cut_mode_var") and self.cut_mode_var.get() == "narrative_arc")

                if self.main_app and hasattr(self.main_app, "refiner_tab"):
                    self.main_app.refiner_tab._load_video(out_path)
                    self.main_app.tabview.set("✂️  Refinador (Mastercut)")
                    if is_arc:
                        msg = (
                            f"Arco Narrativo extraído ({format_time(dur_sec)}) e carregado no Refinador!\n\n"
                            f"Arquivo: {os.path.basename(out_path)}\n\n"
                            "💡 Próximo passo: na aba '✂️ Refinador (Mastercut)', clique em 'Criar Mastercut' "
                            "para condensar este arco inteiro num vídeo dinâmico de 1 a 2 minutos com a história completa!"
                        )
                    else:
                        msg = (
                            f"Trecho extraído e carregado no Refinador!\n\nArquivo: {os.path.basename(out_path)}\n\n"
                            "Agora você pode gerar o Mastercut para condensar o clipe com ritmo perfeito."
                        )
                    messagebox.showinfo("Enviado para o Refinador", msg)
                else:
                    messagebox.showinfo("Corte Pronto", f"Trecho salvo em:\n{out_path}")

            self.after(0, _ui_done)

        threading.Thread(target=_worker, daemon=True).start()

    def _send_to_upscaler(self, cand: dict, btn=None):
        """Cut the candidate clip and transfer directly to Upscaling tab."""
        orig_text = btn.cget("text") if btn else ""
        if btn:
            btn.configure(state="disabled", text="⏳ Preparando...")

        def _worker():
            out_path, err = self._create_cut_file(cand)

            def _ui_done():
                if btn and btn.winfo_exists():
                    btn.configure(state="normal", text=orig_text)

                if not out_path:
                    self._log(f"✕ Erro ao preparar corte para o Upscaler: {err}")
                    messagebox.showerror("Erro", f"Falha ao gerar o corte do trecho:\n{err}")
                    return

                self._log(f"✓ Corte pronto e transferido para o Upscaler: {out_path}")
                if self.main_app:
                    self.main_app._load_video(out_path)
                    self.main_app.tabview.set("⬆  Upscaling")
                    self.main_app._set_status(
                        f"✓ Corte carregado no Upscaler: {os.path.basename(out_path)}",
                        COLORS["success"]
                    )
                    messagebox.showinfo(
                        "Enviado para o Upscaler",
                        f"Trecho extraído e carregado no Upscaler!\n\nArquivo: {os.path.basename(out_path)}\n\n"
                        "Selecione o modelo de IA ou nitidez e clique em 'Iniciar Upscaling'."
                    )
                else:
                    messagebox.showinfo("Corte Pronto", f"Trecho salvo em:\n{out_path}")

            self.after(0, _ui_done)

        threading.Thread(target=_worker, daemon=True).start()
