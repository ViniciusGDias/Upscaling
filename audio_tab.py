"""
Audio Separation Tab - UI component for the Audio Separator feature.
"""

import customtkinter as ctk
from tkinter import filedialog, messagebox
import os
import time

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

COLORS = {
    "bg_dark": "#09090b",
    "bg_card": "#111113",
    "bg_card_hover": "#18181b",
    "accent_primary": "#e2e8f0",
    "accent_secondary": "#94a3b8",
    "accent_audio": "#e2e8f0",
    "accent_audio_hover": "#a1a1aa",
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

ALL_EXTENSIONS = AUDIO_EXTENSIONS + VIDEO_EXTENSIONS


class AudioSeparationTab(ctk.CTkFrame):
    """Self-contained UI tab for audio source separation."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self.separator = AudioSeparator()
        self.is_processing = False
        self._start_time = 0.0
        self._elapsed_timer_id = None
        self.audio_info = None

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
            row, text="🎧  Separação de Áudio",
            font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"),
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        ctk.CTkLabel(
            row, text=" IA ",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=COLORS["text_secondary"], fg_color=COLORS["bg_card"],
            corner_radius=12, padx=8, pady=3,
        ).pack(side="left", padx=(10, 0), pady=(4, 0))

        ctk.CTkLabel(
            header,
            text="Separe voz, instrumentos e efeitos sonoros usando Demucs (Meta AI)",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=COLORS["text_secondary"], anchor="w",
        ).pack(fill="x", pady=(4, 0))

        ctk.CTkFrame(header, fg_color=COLORS["border"], height=1).pack(fill="x", pady=(12, 0))

    def _build_file_section(self, parent):
        card = ctk.CTkFrame(parent, fg_color=COLORS["bg_card"], corner_radius=12,
                            border_width=1, border_color=COLORS["border"])
        card.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            card, text="📁  Arquivo de Entrada (Áudio ou Vídeo)",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=16, pady=(12, 8))

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 14))

        self.file_entry = ctk.CTkEntry(
            row, placeholder_text="Selecione um arquivo de áudio ou vídeo...",
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
        # Hidden initially

        ctk.CTkLabel(
            self.info_card, text="🎵  Informações do Áudio",
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

    def _build_settings_section(self, parent):
        card = ctk.CTkFrame(parent, fg_color=COLORS["bg_card"], corner_radius=12,
                            border_width=1, border_color=COLORS["border"])
        card.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            card, text="⚙️  Configurações de Separação",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=16, pady=(12, 8))

        grid = ctk.CTkFrame(card, fg_color="transparent")
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
            card,
            text="💡 Dica: 'Só a Voz' isola diálogos. 'Só Instrumental' remove a voz. "
                 "'Voz + Efeitos' mantém a voz e sons ambiente sem a música.",
            font=ctk.CTkFont(size=11), text_color=COLORS["text_muted"],
            anchor="w", wraplength=700,
        )
        desc.pack(fill="x", padx=16, pady=(0, 12))

    def _build_output_section(self, parent):
        card = ctk.CTkFrame(parent, fg_color=COLORS["bg_card"], corner_radius=12,
                            border_width=1, border_color=COLORS["border"])
        card.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            card, text="💾  Pasta de Saída",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=16, pady=(12, 8))

        row = ctk.CTkFrame(card, fg_color="transparent")
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
            af, text="🎧  Iniciar Separação",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            fg_color=COLORS["accent_primary"], hover_color=COLORS["accent_secondary"],
            text_color="#09090b",
            height=48, corner_radius=12, command=self._start_separation,
        )
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.cancel_btn = ctk.CTkButton(
            af, text="✕  Cancelar",
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
        # Hidden initially

        ctk.CTkLabel(
            self.progress_card, text="📊  Progresso",
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
        ctk.CTkLabel(inner, text="Console",
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
            title="Selecionar Áudio ou Vídeo",
            filetypes=[
                ("Áudio e Vídeo", f"{exts_audio} {exts_video}"),
                ("Áudio", exts_audio),
                ("Vídeo", exts_video),
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

            # Auto output dir
            out_dir = os.path.join(os.path.dirname(filepath), "audio_separated")
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, out_dir)
        else:
            messagebox.showerror("Erro", "Não foi possível ler o arquivo de áudio.")

    def _browse_output(self):
        d = filedialog.askdirectory(title="Pasta de Saída")
        if d:
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, d)

    def _start_separation(self):
        if self.is_processing:
            return

        # Check Demucs availability before starting
        if not self.separator.is_demucs_available:
            msg = (
                "O motor Demucs (Meta AI) para separação de áudio é opcional e ainda não está instalado no seu computador.\n\n"
                "Deseja gerar o instalador em 1-clique (.bat) para instalar o PyTorch CUDA e o Demucs automaticamente?"
            )
            if messagebox.askyesno("Demucs Opcional", msg):
                from engine_manager import create_pytorch_install_script
                bat_p = create_pytorch_install_script()
                messagebox.showinfo(
                    "Script Criado com Sucesso! ✓",
                    f"O instalador rápido foi gerado em:\n{bat_p}\n\n"
                    "Basta dar 2 cliques no arquivo 'instalar_motores_ia.bat' para instalar o PyTorch CUDA e o Demucs automaticamente no seu Windows!"
                )
                import subprocess
                subprocess.run(["explorer", "/select,", str(bat_p)])
            return

        input_path = self.file_entry.get().strip()
        if not input_path or not os.path.isfile(input_path):
            messagebox.showerror("Erro", "Selecione um arquivo válido.")
            return

        output_dir = self.output_entry.get().strip()
        if not output_dir:
            messagebox.showerror("Erro", "Defina a pasta de saída.")
            return

        os.makedirs(output_dir, exist_ok=True)

        mode_key = self.mode_var.get()
        mode = SEPARATION_MODES[mode_key]
        model_key = self.model_var.get()
        model = DEMUCS_MODELS[model_key]
        fmt_key = self.format_var.get()
        fmt = OUTPUT_FORMATS[fmt_key]

        self.is_processing = True
        self.start_btn.configure(state="disabled", text="⏳  Processando...")
        self.cancel_btn.configure(state="normal")

        if not self.progress_card.winfo_ismapped():
            self.progress_card.pack(fill="x", pady=(0, 10))

        self.progress_bar.set(0)
        self.pct_label.configure(text="0.0%")
        self.status_label.configure(text="Iniciando...")
        self.elapsed_label.configure(text="Tempo: 00:00")

        self._clear_log()
        self._log("═══ Separação de Áudio ═══")
        self._log(f"Entrada:  {os.path.basename(input_path)}")
        self._log(f"Modo:     {mode_key}")
        self._log(f"Modelo:   {model_key}")
        self._log(f"Formato:  {fmt_key}")
        self._log("─────────────────────────")

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
        if self.is_processing and messagebox.askyesno("Cancelar", "Cancelar a separação?"):
            self.separator.cancel()
            self._on_log("⚠ Cancelamento solicitado...")

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
        self.start_btn.configure(state="normal", text="🎧  Iniciar Separação")
        self.cancel_btn.configure(state="disabled")

        elapsed = time.time() - self._start_time
        self.elapsed_label.configure(text=f"Tempo total: {format_time(elapsed)}")

        if success:
            self.progress_bar.set(1.0)
            self.pct_label.configure(text="100%")
            self.status_label.configure(text="✓ Concluído!")
            self._log(f"Tempo total: {format_time(elapsed)}")

            output_dir = self.output_entry.get().strip()
            if messagebox.askyesno("Concluído! ✓", f"{msg}\n\nAbrir pasta?"):
                os.startfile(output_dir)
        else:
            self.status_label.configure(text="✕ Falhou")
            self._log(f"✕ ERRO: {msg}")
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
