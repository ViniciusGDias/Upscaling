"""
Video Upscaler 4K - Main Application
A modern GUI application for upscaling videos to 4K resolution using FFmpeg.
"""

import customtkinter as ctk
from tkinter import filedialog, messagebox
import os
import time
import sys

# Safe stdout/stderr for GUI / noconsole mode
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

try:
    from ctypes import windll
    # Set AppUserModelID so Windows taskbar displays the Urahara icon correctly
    myappid = 'urahara.studio.v1'
    windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception:
    pass

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

from upscaler import (
    VideoUpscaler,
    get_video_info,
    VideoInfo,
    RESOLUTIONS,
    ALGORITHMS,
    QUALITY_PRESETS,
    ASPECT_RATIOS,
    FPS_OPTIONS,
    SHARPEN_OPTIONS,
    COLOR_ENHANCEMENTS,
    DENOISE_OPTIONS,
    compute_target_dimensions,
    find_ffmpeg,
    format_time,
    ENCODERS,
    ANTI_COPYRIGHT_OPTIONS,
    # AI Upscaling
    AI_MODELS,
    AIVideoUpscaler,
    check_realesrgan_available,
    install_ai_dependencies,
    AI_AVAILABLE,
)
from audio_tab import AudioSeparationTab
from refiner_tab import RefinerMastercutTab
from director_tab import DirectorTab
from instagram_tab import InstagramAnalyzerTab
from yt_shorts_tab import YTShortsAnalyzerTab
from anime_finder_tab import AnimeFinderTab
from settings_tab import SettingsTab
from updater import CURRENT_VERSION, check_for_updates_async, open_download_page
from engine_manager import check_all_engines


# ── Theme Configuration ──────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Color palette — Minimal Black Pro (Vercel/Linear-inspired)
COLORS = {
    "bg_dark": "#09090b",          # true black background
    "bg_card": "#111113",          # slightly lifted card
    "bg_card_hover": "#18181b",    # hover state
    "accent_primary": "#e2e8f0",   # near-white for primary actions
    "accent_secondary": "#94a3b8", # muted silver hover
    "success": "#22c55e",
    "warning": "#f59e0b",
    "error": "#ef4444",
    "text_primary": "#fafafa",     # pure off-white
    "text_secondary": "#71717a",   # zinc-500 — muted labels
    "text_muted": "#3f3f46",       # zinc-700 — very subtle
    "border": "#27272a",           # zinc-800 — ultra-thin borders
    "border_active": "#52525b",    # zinc-600 — focus/hover border
    "console_bg": "#050505",
    "console_text": "#a1a1aa",     # subtle console grey
}

VIDEO_EXTENSIONS = (
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv",
    ".webm", ".m4v", ".mpeg", ".mpg", ".3gp", ".ts",
)


class VideoUpscalerApp(ctk.CTk):
    """Main application window."""

    def __init__(self):
        super().__init__()

        # Window setup
        self.title("Urahara")
        self.geometry("980x940")
        self.minsize(860, 800)
        self.configure(fg_color=COLORS["bg_dark"])

        # Set window icon
        try:
            icon_p = resource_path("app_icon.ico")
            if os.path.exists(icon_p):
                self.iconbitmap(icon_p)
        except Exception:
            pass

        # State
        self.upscaler = VideoUpscaler()
        self.ai_upscaler = AIVideoUpscaler() if AIVideoUpscaler else None
        self.current_video: VideoInfo | None = None
        self.input_path: str = ""
        self.is_processing = False
        self._start_time = 0.0
        self._elapsed_timer_id = None
        self._ai_mode = False  # True when using Real-ESRGAN AI pipeline

        # Build UI
        self._build_ui()

        # Check FFmpeg on startup
        self.after(500, self._check_ffmpeg)
        # Check updates and key configuration
        self.after(1500, self._check_startup_notifications)

    # ── UI Construction ──────────────────────────────────────────────────

    def _build_ui(self):
        """Build the complete user interface."""
        # Top Brand & Quick Settings Bar
        self.top_bar = ctk.CTkFrame(self, fg_color="transparent")
        self.top_bar.pack(fill="x", padx=16, pady=(6, 2))

        app_title_lbl = ctk.CTkLabel(
            self.top_bar,
            text="URAHARA",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLORS["text_primary"],
        )
        app_title_lbl.pack(side="left")

        ver_lbl = ctk.CTkLabel(
            self.top_bar,
            text=f"v{CURRENT_VERSION}",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=COLORS["text_secondary"],
            fg_color=COLORS["bg_card"],
            corner_radius=4,
            padx=6, pady=1,
        )
        ver_lbl.pack(side="left", padx=(8, 0))

        # Quick Config button top right
        cfg_top_btn = ctk.CTkButton(
            self.top_bar,
            text="⚙️ Configurações & Motores",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_card_hover"],
            text_color=COLORS["text_primary"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=6,
            height=24,
            command=lambda: self.tabview.set("⚙️  Configurações"),
        )
        cfg_top_btn.pack(side="right")

        self.update_top_btn = ctk.CTkButton(
            self.top_bar,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            fg_color="#15803d",
            hover_color="#16a34a",
            text_color="#ffffff",
            corner_radius=6,
            height=24,
            command=lambda: (self.tabview.set("⚙️  Configurações"), open_download_page()),
        )

        # Tab view for multi-tool
        self.tabview = ctk.CTkTabview(
            self, fg_color=COLORS["bg_dark"],
            segmented_button_fg_color=COLORS["bg_dark"],
            segmented_button_selected_color=COLORS["bg_card"],
            segmented_button_selected_hover_color=COLORS["bg_card_hover"],
            segmented_button_unselected_color=COLORS["bg_dark"],
            segmented_button_unselected_hover_color=COLORS["bg_card"],
            text_color=COLORS["text_secondary"],
            corner_radius=6,
        )
        self.tabview.pack(fill="both", expand=True, padx=12, pady=(4, 12))

        # ── Tab 1: Video Upscaler ──
        tab_upscale = self.tabview.add("⬆  Upscaling")
        tab_upscale.configure(fg_color="transparent")

        self.main_scroll = ctk.CTkScrollableFrame(
            tab_upscale, fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["accent_primary"],
        )
        self.main_scroll.pack(fill="both", expand=True)

        self._build_header()
        self._build_file_section()
        self._build_video_info_section()
        self._build_settings_section()
        self._build_output_section()
        self._build_action_section()
        self._build_progress_section()
        self._build_status_bar()

        # ── Tab 2: Diretor IA (Smart Cortes & Top 3) ──
        tab_director = self.tabview.add("🎬  Diretor IA")
        tab_director.configure(fg_color="transparent")
        self.director_tab = DirectorTab(tab_director, main_app=self)
        self.director_tab.pack(fill="both", expand=True)

        # ── Tab 3: Refinador Mastercut ──
        tab_refiner = self.tabview.add("✂️  Refinador (Mastercut)")
        tab_refiner.configure(fg_color="transparent")
        self.refiner_tab = RefinerMastercutTab(tab_refiner, main_app=self)
        self.refiner_tab.pack(fill="both", expand=True)

        # ── Tab 4: Audio Separation ──
        tab_audio = self.tabview.add("🎧  Separação de Áudio")
        tab_audio.configure(fg_color="transparent")
        self.audio_tab = AudioSeparationTab(tab_audio)
        self.audio_tab.pack(fill="both", expand=True)

        # ── Tab 5: Analisar Instagram ──
        tab_insta = self.tabview.add("📸  Analisar Instagram")
        tab_insta.configure(fg_color="transparent")
        self.insta_tab = InstagramAnalyzerTab(tab_insta, log_callback=self._log)
        self.insta_tab.pack(fill="both", expand=True)

        # ── Tab 6: Analisar YT Shorts ──
        tab_shorts = self.tabview.add("▶️  Analisar YT Shorts")
        tab_shorts.configure(fg_color="transparent")
        self.shorts_tab = YTShortsAnalyzerTab(tab_shorts, log_callback=self._log)
        self.shorts_tab.pack(fill="both", expand=True)

        # ── Tab 7: Anime Finder ──
        tab_finder = self.tabview.add("⛩️  Anime Finder")
        tab_finder.configure(fg_color="transparent")
        self.anime_finder_tab = AnimeFinderTab(tab_finder, log_callback=self._log)
        self.anime_finder_tab.pack(fill="both", expand=True)

        # ── Tab 8: Configurações & Motores ──
        tab_settings = self.tabview.add("⚙️  Configurações")
        tab_settings.configure(fg_color="transparent")
        self.settings_tab = SettingsTab(tab_settings, main_app=self, log_callback=self._log)
        self.settings_tab.pack(fill="both", expand=True)

    def _build_header(self):
        """Build the app header with title and subtitle."""
        header = ctk.CTkFrame(self.main_scroll, fg_color="transparent")
        header.pack(fill="x", pady=(0, 18))

        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.pack(fill="x")

        ctk.CTkLabel(
            title_row,
            text="Video Upscaler",
            font=ctk.CTkFont(family="Segoe UI", size=26, weight="bold"),
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        ctk.CTkLabel(
            title_row,
            text="4K · AI",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_secondary"],
            fg_color="transparent",
        ).pack(side="left", padx=(12, 0), pady=(6, 0))

        ctk.CTkLabel(
            header,
            text="Upscaling profissional com FFmpeg · Real-ESRGAN Neural AI",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_muted"],
            anchor="w",
        ).pack(fill="x", pady=(3, 0))

        ctk.CTkFrame(header, fg_color=COLORS["border"], height=1).pack(fill="x", pady=(14, 0))

    def _build_file_section(self):
        """Build the file selection section."""
        card = ctk.CTkFrame(
            self.main_scroll, fg_color=COLORS["bg_card"],
            corner_radius=8, border_width=1, border_color=COLORS["border"],
        )
        card.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            card, text="Arquivo de Entrada",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLORS["text_secondary"], anchor="w",
        ).pack(fill="x", padx=16, pady=(14, 8))

        file_row = ctk.CTkFrame(card, fg_color="transparent")
        file_row.pack(fill="x", padx=16, pady=(0, 12))

        self.file_entry = ctk.CTkEntry(
            file_row,
            placeholder_text="Selecione um arquivo de vídeo...",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_dark"],
            border_color=COLORS["border"],
            border_width=1,
            text_color=COLORS["text_primary"],
            height=36, corner_radius=6,
        )
        self.file_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            file_row, text="Procurar",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_card_hover"],
            hover_color=COLORS["border_active"],
            text_color=COLORS["text_primary"],
            border_width=1,
            border_color=COLORS["border"],
            height=36, width=100, corner_radius=6,
            command=self._browse_file,
        ).pack(side="right")

        # Quick shortcuts
        shortcut_row = ctk.CTkFrame(card, fg_color="transparent")
        shortcut_row.pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkLabel(
            shortcut_row,
            text="Vídeo longo? Extraia os melhores momentos primeiro.",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_muted"],
        ).pack(side="left")

        ctk.CTkButton(
            shortcut_row,
            text="Diretor IA",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color="transparent",
            hover_color=COLORS["bg_card_hover"],
            border_width=1,
            border_color=COLORS["border_active"],
            text_color=COLORS["text_secondary"],
            height=24,
            command=self._open_in_director,
        ).pack(side="left", padx=(10, 0))

        ctk.CTkButton(
            shortcut_row,
            text="Mastercut (30-60s)",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color="transparent",
            hover_color=COLORS["bg_card_hover"],
            border_width=1,
            border_color=COLORS["border_active"],
            text_color=COLORS["text_secondary"],
            height=24,
            command=self._open_in_refiner,
        ).pack(side="left", padx=(6, 0))

    def _build_video_info_section(self):
        """Build the video information display section (hidden by default)."""
        self.info_card_outer = ctk.CTkFrame(
            self.main_scroll, fg_color=COLORS["bg_card"],
            corner_radius=8, border_width=1, border_color=COLORS["border"],
        )
        # DO NOT pack yet — hidden until video is loaded

        ctk.CTkLabel(
            self.info_card_outer, text="Informações do Vídeo",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLORS["text_secondary"], anchor="w",
        ).pack(fill="x", padx=16, pady=(14, 8))

        info_inner = ctk.CTkFrame(self.info_card_outer, fg_color="transparent")
        info_inner.pack(fill="x", padx=16, pady=(0, 14))

        self.info_grid = ctk.CTkFrame(info_inner, fg_color="transparent")
        self.info_grid.pack(fill="x")

        self.info_labels = {}
        info_fields = [
            ("resolution", "Resolução"),
            ("codec", "Codec"),
            ("fps", "FPS"),
            ("duration", "Duração"),
            ("size", "Tamanho"),
        ]

        for i, (key, label) in enumerate(info_fields):
            col = i % 3
            row = i // 3

            field_frame = ctk.CTkFrame(
                self.info_grid, fg_color=COLORS["bg_dark"], corner_radius=8,
            )
            field_frame.grid(row=row, column=col, padx=4, pady=4, sticky="ew")

            ctk.CTkLabel(
                field_frame, text=label,
                font=ctk.CTkFont(family="Segoe UI", size=11),
                text_color=COLORS["text_muted"],
            ).pack(anchor="w", padx=12, pady=(8, 0))

            value_label = ctk.CTkLabel(
                field_frame, text="—",
                font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
                text_color=COLORS["text_primary"],
            )
            value_label.pack(anchor="w", padx=12, pady=(0, 8))
            self.info_labels[key] = value_label

        for col in range(3):
            self.info_grid.columnconfigure(col, weight=1)

    def _build_settings_section(self):
        """Build the upscaling settings section."""
        card = ctk.CTkFrame(
            self.main_scroll, fg_color=COLORS["bg_card"],
            corner_radius=12, border_width=1, border_color=COLORS["border"],
        )
        card.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            card, text="⚙️  Configurações",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=16, pady=(12, 8))

        settings_grid = ctk.CTkFrame(card, fg_color="transparent")
        settings_grid.pack(fill="x", padx=16, pady=(0, 10))

        # ── Row 0: Resolution, Aspect Ratio, FPS ──
        res_frame = ctk.CTkFrame(settings_grid, fg_color="transparent")
        res_frame.grid(row=0, column=0, padx=(0, 6), pady=4, sticky="ew")
        ctk.CTkLabel(res_frame, text="Resolução", font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(anchor="w", pady=(0, 4))
        self.resolution_var = ctk.StringVar(value=list(RESOLUTIONS.keys())[0])
        ctk.CTkOptionMenu(res_frame, values=list(RESOLUTIONS.keys()), variable=self.resolution_var, font=ctk.CTkFont(size=12), height=36, corner_radius=8, command=lambda _: self._on_resolution_changed()).pack(fill="x")

        ar_frame = ctk.CTkFrame(settings_grid, fg_color="transparent")
        ar_frame.grid(row=0, column=1, padx=6, pady=4, sticky="ew")
        ctk.CTkLabel(ar_frame, text="Proporção", font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(anchor="w", pady=(0, 4))
        self.aspect_ratio_var = ctk.StringVar(value=list(ASPECT_RATIOS.keys())[0])
        ctk.CTkOptionMenu(ar_frame, values=list(ASPECT_RATIOS.keys()), variable=self.aspect_ratio_var, font=ctk.CTkFont(size=12), height=36, corner_radius=8, command=lambda _: self._update_dims_preview()).pack(fill="x")

        fps_frame = ctk.CTkFrame(settings_grid, fg_color="transparent")
        fps_frame.grid(row=0, column=2, padx=(6, 0), pady=4, sticky="ew")
        ctk.CTkLabel(fps_frame, text="FPS", font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(anchor="w", pady=(0, 4))
        self.fps_var = ctk.StringVar(value=list(FPS_OPTIONS.keys())[0])
        ctk.CTkOptionMenu(fps_frame, values=list(FPS_OPTIONS.keys()), variable=self.fps_var, font=ctk.CTkFont(size=12), height=36, corner_radius=8).pack(fill="x")

        # ── Row 1: Algorithm, Quality, Encoder ──
        algo_frame = ctk.CTkFrame(settings_grid, fg_color="transparent")
        algo_frame.grid(row=1, column=0, padx=(0, 6), pady=4, sticky="ew")
        ctk.CTkLabel(algo_frame, text="Algoritmo", font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(anchor="w", pady=(0, 4))
        self.algorithm_var = ctk.StringVar(value=list(ALGORITHMS.keys())[0])
        ctk.CTkOptionMenu(algo_frame, values=list(ALGORITHMS.keys()), variable=self.algorithm_var, font=ctk.CTkFont(size=12), height=36, corner_radius=8).pack(fill="x")

        quality_frame = ctk.CTkFrame(settings_grid, fg_color="transparent")
        quality_frame.grid(row=1, column=1, padx=6, pady=4, sticky="ew")
        ctk.CTkLabel(quality_frame, text="Qualidade", font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(anchor="w", pady=(0, 4))
        self.quality_var = ctk.StringVar(value=list(QUALITY_PRESETS.keys())[0])
        ctk.CTkOptionMenu(quality_frame, values=list(QUALITY_PRESETS.keys()), variable=self.quality_var, font=ctk.CTkFont(size=12), height=36, corner_radius=8).pack(fill="x")

        encoder_frame = ctk.CTkFrame(settings_grid, fg_color="transparent")
        encoder_frame.grid(row=1, column=2, padx=(6, 0), pady=4, sticky="ew")
        ctk.CTkLabel(encoder_frame, text="Processamento", font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(anchor="w", pady=(0, 4))
        self.encoder_var = ctk.StringVar(value=list(ENCODERS.keys())[0])
        ctk.CTkOptionMenu(encoder_frame, values=list(ENCODERS.keys()), variable=self.encoder_var, font=ctk.CTkFont(size=12), height=36, corner_radius=8).pack(fill="x")

        for col in range(3):
            settings_grid.columnconfigure(col, weight=1)

        # ── AI Mode Section ─────────────────────────────────────────────────
        ai_label = ctk.CTkLabel(
            card,
            text="🤖  Modo IA — Real-ESRGAN (Upscaling Neural)",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color="#10b981",
            anchor="w",
        )
        ai_label.pack(fill="x", padx=16, pady=(14, 4))

        ai_main_frame = ctk.CTkFrame(card, fg_color=COLORS["bg_dark"], corner_radius=10, border_width=1, border_color="#065f46")
        ai_main_frame.pack(fill="x", padx=16, pady=(0, 10))

        # Toggle row
        ai_toggle_row = ctk.CTkFrame(ai_main_frame, fg_color="transparent")
        ai_toggle_row.pack(fill="x", padx=12, pady=(10, 6))

        self.ai_switch_var = ctk.StringVar(value="off")
        self.ai_switch = ctk.CTkSwitch(
            ai_toggle_row,
            text="Ativar Real-ESRGAN (IA foto-realista)",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=COLORS["text_primary"],
            fg_color=COLORS["bg_card"],
            progress_color="#10b981",
            button_color="#34d399",
            button_hover_color="#6ee7b7",
            variable=self.ai_switch_var,
            onvalue="on",
            offvalue="off",
            command=self._on_ai_toggle,
        )
        self.ai_switch.pack(side="left")

        # AI status badge
        self.ai_status_label = ctk.CTkLabel(
            ai_toggle_row,
            text="Verificando...",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_muted"],
        )
        self.ai_status_label.pack(side="right", padx=(0, 4))

        # AI model selector (hidden when AI is off)
        self.ai_model_panel = ctk.CTkFrame(ai_main_frame, fg_color="transparent")
        self.ai_model_panel.pack(fill="x", padx=12, pady=(0, 10))

        model_sel_row = ctk.CTkFrame(self.ai_model_panel, fg_color="transparent")
        model_sel_row.pack(fill="x")

        ai_model_label_frame = ctk.CTkFrame(model_sel_row, fg_color="transparent")
        ai_model_label_frame.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkLabel(
            ai_model_label_frame,
            text="Modelo de IA",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"],
        ).pack(anchor="w", pady=(0, 4))

        ai_model_values = list(AI_MODELS.keys()) if AI_MODELS else ["Real-ESRGAN x4 (Geral — Foto Real)"]
        self.ai_model_var = ctk.StringVar(value=ai_model_values[0])
        self.ai_model_menu = ctk.CTkOptionMenu(
            ai_model_label_frame,
            values=ai_model_values,
            variable=self.ai_model_var,
            font=ctk.CTkFont(size=12),
            height=36,
            corner_radius=8,
            fg_color=COLORS["bg_card"],
            button_color="#059669",
            button_hover_color="#047857",
            command=self._on_ai_model_change,
        )
        self.ai_model_menu.pack(fill="x")

        # Install button (shows only when deps missing)
        self.ai_install_btn = ctk.CTkButton(
            model_sel_row,
            text="📦 Instalar IA",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#065f46",
            hover_color="#047857",
            text_color="white",
            height=36,
            width=120,
            corner_radius=8,
            command=self._install_ai_deps,
        )
        # Hidden by default — shown if deps missing
        self.ai_install_btn.pack(side="right", pady=(20, 0))
        self.ai_install_btn.pack_forget()

        # Model description label
        self.ai_model_desc = ctk.CTkLabel(
            self.ai_model_panel,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#6ee7b7",
            anchor="w",
        )
        self.ai_model_desc.pack(fill="x", pady=(6, 0))

        # Warning label
        self.ai_warn_label = ctk.CTkLabel(
            self.ai_model_panel,
            text="⚠  Modo IA é mais lento (segundos por frame) mas produz qualidade foto-realista próxima ao DLSS.",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["warning"],
            anchor="w",
            wraplength=700,
        )
        self.ai_warn_label.pack(fill="x", pady=(4, 0))

        # Initially hide model panel and check AI availability
        self.ai_model_panel.pack_forget()
        self.after(300, self._check_ai_status)

        # ── Row 2: Color Style, Denoise, Sharpen ──
        enhance_label = ctk.CTkLabel(card, text="✨ Melhorias de Estilo", font=ctk.CTkFont(size=13, weight="bold"), text_color=COLORS["accent_primary"], anchor="w")
        enhance_label.pack(fill="x", padx=16, pady=(10, 4))

        enhance_grid = ctk.CTkFrame(card, fg_color="transparent")
        enhance_grid.pack(fill="x", padx=16, pady=(0, 14))

        color_frame = ctk.CTkFrame(enhance_grid, fg_color="transparent")
        color_frame.grid(row=0, column=0, padx=(0, 8), pady=4, sticky="ew")
        ctk.CTkLabel(color_frame, text="Estilo de Cor", font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(anchor="w", pady=(0, 4))
        self.color_var = ctk.StringVar(value=list(COLOR_ENHANCEMENTS.keys())[0])
        ctk.CTkOptionMenu(color_frame, values=list(COLOR_ENHANCEMENTS.keys()), variable=self.color_var, font=ctk.CTkFont(size=12), height=36, corner_radius=8).pack(fill="x")

        denoise_frame = ctk.CTkFrame(enhance_grid, fg_color="transparent")
        denoise_frame.grid(row=0, column=1, padx=8, pady=4, sticky="ew")
        ctk.CTkLabel(denoise_frame, text="Limpeza (Denoise)", font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(anchor="w", pady=(0, 4))
        self.denoise_var = ctk.StringVar(value=list(DENOISE_OPTIONS.keys())[0])
        ctk.CTkOptionMenu(denoise_frame, values=list(DENOISE_OPTIONS.keys()), variable=self.denoise_var, font=ctk.CTkFont(size=12), height=36, corner_radius=8).pack(fill="x")

        sharpen_frame = ctk.CTkFrame(enhance_grid, fg_color="transparent")
        sharpen_frame.grid(row=0, column=2, padx=(8, 0), pady=4, sticky="ew")
        ctk.CTkLabel(sharpen_frame, text="Nitidez", font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(anchor="w", pady=(0, 4))
        self.sharpen_var = ctk.StringVar(value=list(SHARPEN_OPTIONS.keys())[0])
        ctk.CTkOptionMenu(sharpen_frame, values=list(SHARPEN_OPTIONS.keys()), variable=self.sharpen_var, font=ctk.CTkFont(size=12), height=36, corner_radius=8).pack(fill="x")

        enhance_grid.columnconfigure(0, weight=1)
        enhance_grid.columnconfigure(1, weight=1)
        enhance_grid.columnconfigure(2, weight=1)

        # ── Row 3: YouTube/Anti-Copyright ──
        ac_label = ctk.CTkLabel(card, text="🛡️ Segurança (Burlar Direitos Autorais)", font=ctk.CTkFont(size=13, weight="bold"), text_color=COLORS["warning"], anchor="w")
        ac_label.pack(fill="x", padx=16, pady=(10, 4))
        
        ac_frame = ctk.CTkFrame(card, fg_color="transparent")
        ac_frame.pack(fill="x", padx=16, pady=(0, 14))
        
        ctk.CTkLabel(ac_frame, text="Filtro Invisível", font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(anchor="w", pady=(0, 4))
        self.anti_copyright_var = ctk.StringVar(value=list(ANTI_COPYRIGHT_OPTIONS.keys())[0])
        ctk.CTkOptionMenu(ac_frame, values=list(ANTI_COPYRIGHT_OPTIONS.keys()), variable=self.anti_copyright_var, font=ctk.CTkFont(size=12), height=36, corner_radius=8).pack(fill="x")

        # ── Preview: computed target dimensions ──
        self.dims_preview_label = ctk.CTkLabel(
            card, text="",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLORS["accent_primary"], anchor="w",
        )
        self.dims_preview_label.pack(fill="x", padx=16, pady=(2, 10))

    def _build_output_section(self):
        """Build the output file section."""
        card = ctk.CTkFrame(
            self.main_scroll, fg_color=COLORS["bg_card"],
            corner_radius=12, border_width=1, border_color=COLORS["border"],
        )
        card.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            card, text="💾  Arquivo de Saída",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=16, pady=(12, 8))

        output_row = ctk.CTkFrame(card, fg_color="transparent")
        output_row.pack(fill="x", padx=16, pady=(0, 14))

        self.output_entry = ctk.CTkEntry(
            output_row,
            placeholder_text="Caminho de saída será gerado automaticamente...",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            fg_color=COLORS["bg_dark"],
            border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            height=40, corner_radius=8,
        )
        self.output_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ctk.CTkButton(
            output_row, text="Alterar",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            fg_color=COLORS["bg_dark"],
            hover_color=COLORS["bg_card_hover"],
            border_color=COLORS["border"], border_width=1,
            text_color=COLORS["text_secondary"],
            height=40, width=100, corner_radius=8,
            command=self._browse_output,
        ).pack(side="right")

    def _build_action_section(self):
        """Build the action buttons section."""
        action_frame = ctk.CTkFrame(self.main_scroll, fg_color="transparent")
        action_frame.pack(fill="x", pady=(12, 12))

        self.preview_btn = ctk.CTkButton(
            action_frame,
            text="👁️  Ver Efeito",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_card_hover"],
            border_color=COLORS["border_active"], border_width=1,
            text_color=COLORS["text_primary"],
            height=50, corner_radius=12,
            command=self._preview_filters,
        )
        self.preview_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.start_btn = ctk.CTkButton(
            action_frame,
            text="🚀  Iniciar Upscaling",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["accent_secondary"],
            height=50, corner_radius=12,
            command=self._start_upscaling,
        )
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.cancel_btn = ctk.CTkButton(
            action_frame,
            text="✕  Cancelar",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            fg_color=COLORS["error"], hover_color="#dc2626",
            height=50, width=140, corner_radius=12,
            command=self._cancel_upscaling,
            state="disabled",
        )
        self.cancel_btn.pack(side="right")

    def _build_progress_section(self):
        """Build the progress display with console log (hidden by default)."""
        self.progress_card_outer = ctk.CTkFrame(
            self.main_scroll, fg_color=COLORS["bg_card"],
            corner_radius=12, border_width=1, border_color=COLORS["border"],
        )
        # DO NOT pack yet — hidden until upscaling starts

        ctk.CTkLabel(
            self.progress_card_outer, text="📊  Progresso",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"], anchor="w",
        ).pack(fill="x", padx=16, pady=(12, 8))

        progress_inner = ctk.CTkFrame(self.progress_card_outer, fg_color="transparent")
        progress_inner.pack(fill="x", padx=16, pady=(0, 14))

        # ── Progress bar ──
        self.progress_bar = ctk.CTkProgressBar(
            progress_inner,
            fg_color=COLORS["bg_dark"],
            progress_color=COLORS["accent_primary"],
            height=16, corner_radius=8,
        )
        self.progress_bar.pack(fill="x", pady=(0, 10))
        self.progress_bar.set(0)

        # ── Stats row ──
        stats_row = ctk.CTkFrame(progress_inner, fg_color="transparent")
        stats_row.pack(fill="x", pady=(0, 10))

        # Percentage
        self.progress_percent_label = ctk.CTkLabel(
            stats_row, text="0.0%",
            font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"),
            text_color=COLORS["accent_primary"],
        )
        self.progress_percent_label.pack(side="left")

        # Right side stats
        right_stats = ctk.CTkFrame(stats_row, fg_color="transparent")
        right_stats.pack(side="right")

        self.elapsed_label = ctk.CTkLabel(
            right_stats, text="Tempo: 00:00",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_secondary"],
        )
        self.elapsed_label.pack(anchor="e")

        self.progress_status_label = ctk.CTkLabel(
            right_stats, text="Aguardando...",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=COLORS["text_secondary"],
        )
        self.progress_status_label.pack(anchor="e")

        # ── Buttons ──
        btns_row = ctk.CTkFrame(progress_inner, fg_color="transparent")
        btns_row.pack(fill="x", pady=(8, 0))

        self.live_compare_btn = ctk.CTkButton(
            btns_row, text="🔍  Ver Comparação (Lado a Lado)",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["accent_secondary"],
            height=40, corner_radius=8,
            command=self._show_comparison
        )
        # Hidden initially
        self.live_compare_btn.pack_forget()

        # ── Console Log ──
        console_label_row = ctk.CTkFrame(progress_inner, fg_color="transparent")
        console_label_row.pack(fill="x", pady=(4, 4))

        ctk.CTkLabel(
            console_label_row, text="Console",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLORS["text_muted"],
        ).pack(side="left")

        self.console_text = ctk.CTkTextbox(
            progress_inner,
            fg_color=COLORS["console_bg"],
            text_color=COLORS["console_text"],
            font=ctk.CTkFont(family="Consolas", size=11),
            height=140, corner_radius=8,
            border_width=1, border_color=COLORS["border"],
            wrap="word",
        )
        self.console_text.pack(fill="x")
        self.console_text.configure(state="disabled")

    def _build_status_bar(self):
        """Build the bottom status bar."""
        status_frame = ctk.CTkFrame(self.main_scroll, fg_color="transparent")
        status_frame.pack(fill="x", pady=(8, 0))

        self.status_label = ctk.CTkLabel(
            status_frame, text="",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_muted"], anchor="w",
        )
        self.status_label.pack(side="left")

        self.ffmpeg_status = ctk.CTkLabel(
            status_frame, text="",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_muted"], anchor="e",
        )
        self.ffmpeg_status.pack(side="right")

    # ── Helper Methods ───────────────────────────────────────────────────

    def _set_status(self, text: str, color: str = None):
        """Update the status bar text."""
        self.status_label.configure(
            text=text,
            text_color=color or COLORS["text_muted"]
        )

    def _log(self, message: str):
        """Append a message to the console log."""
        self.console_text.configure(state="normal")
        self.console_text.insert("end", f"{message}\n")
        self.console_text.see("end")
        self.console_text.configure(state="disabled")

    def _clear_log(self):
        """Clear the console log."""
        self.console_text.configure(state="normal")
        self.console_text.delete("1.0", "end")
        self.console_text.configure(state="disabled")

    def _show_info_card(self):
        """Show the video info card in the correct position (after file section)."""
        self.info_card_outer.pack(fill="x", pady=(0, 10))
        # Reorder: lift it to proper position (after the file section card)
        # We need to re-pack in correct order. Instead we use pack_configure
        # The card was not packed initially so packing it will put it at the end.
        # Let's reorder by lifting after the second child of main_scroll's inner frame
        children = self.main_scroll._parent_frame.winfo_children()
        # We want to place info card after the 3rd widget (header, file_section)
        # Since it's added dynamically, we need to re-order
        # Actually for simplicity, let's just show it — it appears at bottom but that's fine
        # The trick is we can't easily reorder pack widgets. Let's use a different approach.

    def _on_resolution_changed(self):
        """Called when resolution dropdown changes."""
        self._update_dims_preview()
        filepath = self.file_entry.get().strip()
        current_out = self.output_entry.get().strip()
        if filepath and current_out:
            base, ext = os.path.splitext(filepath)
            res_key = self.resolution_var.get()
            base_height = RESOLUTIONS.get(res_key, 0)
            res_tag = "original" if base_height == 0 else f"{base_height}p"
            if current_out.startswith(base) and "_upscaled_" in current_out:
                new_out = f"{base}_upscaled_{res_tag}{ext}"
                self.output_entry.delete(0, "end")
                self.output_entry.insert(0, new_out)

    def _update_dims_preview(self):
        """Update the dimensions preview label based on current settings."""
        res_key = self.resolution_var.get()
        base_height = RESOLUTIONS.get(res_key, 0)
        ar_key = self.aspect_ratio_var.get()
        aspect = ASPECT_RATIOS.get(ar_key)

        orig_w = self.current_video.width if self.current_video else 0
        orig_h = self.current_video.height if self.current_video else 0

        target_w, target_h = compute_target_dimensions(
            base_height, aspect, orig_w, orig_h
        )
        if base_height == 0:
            if self.current_video:
                self.dims_preview_label.configure(
                    text=f"📍 Saída: {target_w}×{target_h} (Original)"
                )
            else:
                self.dims_preview_label.configure(
                    text="📍 Saída: Original"
                )
        else:
            self.dims_preview_label.configure(
                text=f"📍 Saída: {target_w}×{target_h}"
            )

    def _start_elapsed_timer(self):
        """Start the elapsed time counter."""
        self._start_time = time.time()
        self._update_elapsed()

    def _update_elapsed(self):
        """Update elapsed time display."""
        if self.is_processing:
            elapsed = time.time() - self._start_time
            self.elapsed_label.configure(text=f"Tempo: {format_time(elapsed)}")
            self._elapsed_timer_id = self.after(1000, self._update_elapsed)

    def _stop_elapsed_timer(self):
        """Stop the elapsed time counter."""
        if self._elapsed_timer_id:
            self.after_cancel(self._elapsed_timer_id)
            self._elapsed_timer_id = None

    # ── Event Handlers ───────────────────────────────────────────────────

    def _check_ffmpeg(self):
        """Check if FFmpeg is available and offer 1-click automatic download if missing."""
        self.upscaler.ffmpeg_path = find_ffmpeg()
        if self.upscaler.is_available:
            self.ffmpeg_status.configure(
                text="✓ FFmpeg encontrado",
                text_color=COLORS["success"],
            )
            self._set_status("Pronto para uso.")
        else:
            self.ffmpeg_status.configure(
                text="✕ FFmpeg não encontrado",
                text_color=COLORS["error"],
            )
            self._set_status("FFmpeg não encontrado!", COLORS["error"])
            # Ask user if they want the app to auto-download FFmpeg
            if messagebox.askyesno(
                "FFmpeg Necessário",
                "O FFmpeg não foi encontrado no seu computador.\n"
                "Ele é o motor essencial para processar e editar vídeos.\n\n"
                "Deseja que o aplicativo baixe e instale o FFmpeg automaticamente agora com 1 clique?"
            ):
                self.tabview.set("⚙️  Configurações")
                if hasattr(self, "settings_tab"):
                    self.settings_tab._auto_download_ffmpeg()

    def _check_startup_notifications(self):
        """Check for updates and verify API keys in background on startup."""
        try:
            from settings_manager import load_app_settings
            settings = load_app_settings()

            # Check if keys are missing
            if not settings.get("gemini_keys") and not settings.get("groq_key"):
                self._set_status("⚙️ Nenhuma chave de IA configurada. Acesse a aba Configurações para adicionar sua chave grátis.", COLORS["warning"])

            # Check for updates
            if settings.get("check_updates", True):
                def _on_update_result(res):
                    if res.get("has_update"):
                        latest = res.get("latest_version")
                        def _show_badge():
                            self.update_top_btn.configure(
                                text=f"🚀 Nova Versão v{latest} Disponível!",
                            )
                            self.update_top_btn.pack(side="right", padx=(0, 10))
                        self.after(0, _show_badge)

                check_for_updates_async(_on_update_result)
        except Exception:
            pass

    # ── AI Mode Methods ───────────────────────────────────────────────────

    def _check_ai_status(self):
        """Check Real-ESRGAN availability and update UI accordingly."""
        if not AI_AVAILABLE:
            self.ai_status_label.configure(
                text="ai_upscaler.py não encontrado",
                text_color=COLORS["error"],
            )
            return

        available, msg = check_realesrgan_available()
        if available:
            self.ai_status_label.configure(
                text=f"✓ IA pronta ({msg.split('✓')[0].strip()})",
                text_color=COLORS["success"],
            )
            self.ai_install_btn.pack_forget()
        else:
            self.ai_status_label.configure(
                text="⚠ Dependências faltando",
                text_color=COLORS["warning"],
            )
            # Show install button
            self.ai_install_btn.pack(side="right", pady=(20, 0))

    def _on_ai_toggle(self):
        """Handle AI mode switch toggle."""
        self._ai_mode = self.ai_switch_var.get() == "on"
        if self._ai_mode:
            self.ai_model_panel.pack(fill="x", padx=0, pady=(0, 4))
            self._on_ai_model_change(self.ai_model_var.get())
            self._set_status("🤖 Modo IA ativado — qualidade foto-realista", "#10b981")
        else:
            self.ai_model_panel.pack_forget()
            self._set_status("Modo FFmpeg — rápido e eficiente")

    def _on_ai_model_change(self, model_key: str):
        """Update description when AI model changes."""
        model_info = AI_MODELS.get(model_key, {})
        desc = model_info.get("description", "")
        scale = model_info.get("scale", 4)
        self.ai_model_desc.configure(
            text=f"   ↳ {desc} | Fator: {scale}×"
        )

    def _install_ai_deps(self):
        """Launch AI dependency installation in background thread."""
        if self.is_processing:
            messagebox.showwarning("Aguarde", "Aguarde o processamento atual terminar.")
            return

        import threading

        if not messagebox.askyesno(
            "Instalar Dependências de IA",
            "Isso instalará:\n• PyTorch (CUDA 12.8)\n• basicsr\n• realesrgan\n• opencv-python\n• facexlib / gfpgan\n\n"
            "Pode demorar vários minutos e usar ~2-3 GB.\n\nContinuar?"
        ):
            return

        # Show progress section
        if not self.progress_card_outer.winfo_ismapped():
            self.progress_card_outer.pack(fill="x", pady=(0, 10))
        self._clear_log()
        self._log("📦 Iniciando instalação das dependências de IA...")
        self.ai_install_btn.configure(state="disabled", text="⏳ Instalando...")

        def _do_install():
            from ai_upscaler import install_dependencies
            success = install_dependencies(on_log=self._on_log)
            self.after(0, self._on_install_done, success)

        threading.Thread(target=_do_install, daemon=True).start()

    def _on_install_done(self, success: bool):
        """Called when AI dependency installation finishes."""
        self.ai_install_btn.configure(state="normal", text="📦 Instalar IA")
        if success:
            self._log("✓ Instalação concluída! Reinicie o app para carregar os módulos.")
            messagebox.showinfo(
                "Instalação Concluída",
                "Dependências de IA instaladas com sucesso!\n\nReinicie o app para usar o Modo IA."
            )
            self._check_ai_status()
        else:
            self._log("✕ Instalação falhou. Veja o console para detalhes.")
            messagebox.showerror("Erro", "Falha na instalação. Verifique a conexão e tente novamente.")

    def _browse_file(self):
        """Open file dialog to select input video."""
        filetypes = [
            ("Vídeos", "*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.m4v *.mpeg *.mpg *.ts"),
            ("Todos os arquivos", "*.*"),
        ]
        filepath = filedialog.askopenfilename(
            title="Selecionar Vídeo",
            filetypes=filetypes,
        )
        if filepath:
            self._load_video(filepath)

    def _open_in_refiner(self):
        """Send current video to Refiner Mastercut tab and switch to it."""
        if hasattr(self, 'refiner_tab'):
            if self.input_path and os.path.exists(self.input_path):
                self.refiner_tab._load_video(self.input_path)
            self.tabview.set("✂️  Refinador (Mastercut)")

    def _open_in_director(self):
        """Send current video to Director AI tab and switch to it."""
        if hasattr(self, 'director_tab'):
            if self.input_path and os.path.exists(self.input_path):
                self.director_tab._load_video(self.input_path)
            self.tabview.set("🎬  Diretor IA")

    def _browse_output(self):
        """Open file dialog to select output path."""
        filetypes = [("MP4", "*.mp4"), ("MKV", "*.mkv"), ("AVI", "*.avi")]
        filepath = filedialog.asksaveasfilename(
            title="Salvar Vídeo Como",
            filetypes=filetypes,
            defaultextension=".mp4",
        )
        if filepath:
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, filepath)

    def _load_video(self, filepath: str):
        """Load video file and display its information."""
        self.input_path = filepath

        self.file_entry.delete(0, "end")
        self.file_entry.insert(0, filepath)

        self._set_status("Analisando vídeo...", COLORS["warning"])
        self.update_idletasks()  # Force UI refresh

        video_info = get_video_info(filepath)

        if video_info:
            self.current_video = video_info

            # Update info labels
            self.info_labels["resolution"].configure(
                text=f"{video_info.width}×{video_info.height} ({video_info.resolution_label})"
            )
            self.info_labels["codec"].configure(text=video_info.codec.upper())
            self.info_labels["fps"].configure(text=f"{video_info.fps} fps")
            self.info_labels["duration"].configure(text=format_time(video_info.duration))
            self.info_labels["size"].configure(text=video_info.file_size_label)

            # Show info card
            if not self.info_card_outer.winfo_ismapped():
                self.info_card_outer.pack(fill="x", pady=(0, 10))

            # Update dims preview
            self._update_dims_preview()

            # Auto-generate output path
            base, ext = os.path.splitext(filepath)
            res_key = self.resolution_var.get()
            base_height = RESOLUTIONS.get(res_key, 0)
            res_tag = "original" if base_height == 0 else f"{base_height}p"
            output_path = f"{base}_upscaled_{res_tag}{ext}"
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, output_path)

            self._set_status(f"✓ Vídeo carregado: {video_info.filename}", COLORS["success"])
        else:
            self._set_status(
                "✕ Não foi possível ler o vídeo. Verifique se o FFmpeg está instalado.",
                COLORS["error"]
            )
            messagebox.showerror(
                "Erro ao ler vídeo",
                f"Não foi possível analisar o vídeo:\n{filepath}\n\n"
                "Certifique-se que o FFmpeg (ffprobe) está instalado e no PATH."
            )

    def _preview_filters(self):
        """Preview current filters on the selected video."""
        input_path = self.file_entry.get().strip()
        if not input_path or not os.path.isfile(input_path):
            messagebox.showerror("Erro", "Selecione um arquivo de vídeo válido primeiro.")
            return

        if not self.upscaler.is_available:
            messagebox.showerror("Erro", "FFmpeg não disponível. Instale-o primeiro.")
            return

        # Obter configurações
        res_key = self.resolution_var.get()
        base_height = RESOLUTIONS[res_key]
        ar_key = self.aspect_ratio_var.get()
        aspect = ASPECT_RATIOS[ar_key]
        fps_key = self.fps_var.get()
        target_fps = FPS_OPTIONS[fps_key]
        algo_key = self.algorithm_var.get()
        algorithm = ALGORITHMS[algo_key]
        sharpen_key = self.sharpen_var.get()
        sharpen_filter = SHARPEN_OPTIONS[sharpen_key]
        color_key = self.color_var.get()
        color_filter = COLOR_ENHANCEMENTS[color_key]
        denoise_key = self.denoise_var.get()
        denoise_filter = DENOISE_OPTIONS[denoise_key]
        anti_copyright = self.anti_copyright_var.get()

        orig_w = self.current_video.width if self.current_video else 0
        orig_h = self.current_video.height if self.current_video else 0
        target_w, target_h = compute_target_dimensions(
            base_height, aspect, orig_w, orig_h
        )

        self._set_status("Iniciando pré-visualização...", COLORS["warning"])
        
        success = self.upscaler.preview_video(
            input_path=input_path,
            target_width=target_w,
            target_height=target_h,
            algorithm=algorithm,
            aspect_ratio=aspect,
            target_fps=target_fps,
            sharpen_filter=sharpen_filter,
            color_filter=color_filter,
            denoise_filter=denoise_filter,
            anti_copyright=anti_copyright,
        )

        if success:
            self._set_status("Pré-visualização iniciada. Feche a janela para continuar.", COLORS["success"])
        else:
            self._set_status("Falha ao abrir pré-visualização.", COLORS["error"])

    def _start_upscaling(self):
        """Start the upscaling process."""
        if self.is_processing:
            return

        input_path = self.file_entry.get().strip()
        if not input_path or not os.path.isfile(input_path):
            messagebox.showerror("Erro", "Selecione um arquivo de vídeo válido.")
            return

        output_path = self.output_entry.get().strip()
        if not output_path:
            messagebox.showerror("Erro", "Defina o caminho do arquivo de saída.")
            return

        if not self.upscaler.is_available:
            messagebox.showerror("Erro", "FFmpeg não disponível. Instale-o primeiro.")
            return

        if os.path.exists(output_path):
            if not messagebox.askyesno("Arquivo Existente",
                    f"O arquivo já existe:\n{output_path}\n\nSubstituir?"):
                return

        # Get settings
        res_key = self.resolution_var.get()
        base_height = RESOLUTIONS[res_key]

        ar_key = self.aspect_ratio_var.get()
        aspect = ASPECT_RATIOS[ar_key]

        fps_key = self.fps_var.get()
        target_fps = FPS_OPTIONS[fps_key]

        algo_key = self.algorithm_var.get()
        algorithm = ALGORITHMS[algo_key]
        quality_key = self.quality_var.get()
        quality = QUALITY_PRESETS[quality_key]
        encoder_key = self.encoder_var.get()
        encoder = ENCODERS[encoder_key]
        sharpen_key = self.sharpen_var.get()
        sharpen_filter = SHARPEN_OPTIONS[sharpen_key]
        color_key = self.color_var.get()
        color_filter = COLOR_ENHANCEMENTS[color_key]
        denoise_key = self.denoise_var.get()
        denoise_filter = DENOISE_OPTIONS[denoise_key]
        anti_copyright = self.anti_copyright_var.get()

        # Compute target dimensions
        orig_w = self.current_video.width if self.current_video else 0
        orig_h = self.current_video.height if self.current_video else 0
        target_w, target_h = compute_target_dimensions(
            base_height, aspect, orig_w, orig_h
        )

        # Update UI
        self.is_processing = True
        self.start_btn.configure(state="disabled", text="⏳  Processando...")
        self.cancel_btn.configure(state="normal")
        self.live_compare_btn.pack_forget() # Hide if it was there from previous run

        # Show progress card
        if not self.progress_card_outer.winfo_ismapped():
            self.progress_card_outer.pack(fill="x", pady=(0, 10))

        self.progress_bar.set(0)
        self.progress_percent_label.configure(text="0.0%")
        self.progress_status_label.configure(text="Iniciando...")
        self.elapsed_label.configure(text="Tempo: 00:00")

        # Build info for console
        ar_label = ar_key
        fps_label = fps_key
        mode_label = f"🤖 Real-ESRGAN ({self.ai_model_var.get()})" if self._ai_mode else f"FFmpeg / {algo_key}"

        # Clear and populate console
        self._clear_log()
        self._log(f"═══ Video Studio Pro ═══")
        self._log(f"Modo:        {mode_label}")
        self._log(f"Entrada:     {os.path.basename(input_path)}")
        self._log(f"Saída:       {os.path.basename(output_path)}")
        res_display = f"{target_w}×{target_h} (Original)" if base_height == 0 else f"{target_w}×{target_h}"
        self._log(f"Resolução:   {res_display}")
        self._log(f"Proporção:   {ar_label}")
        self._log(f"FPS:         {fps_label}")
        self._log(f"Nitidez:     {sharpen_key}")
        self._log(f"Estilo Cor:  {color_key}")
        self._log(f"Limpeza:     {denoise_key}")
        self._log(f"Anti-Copyr.: {anti_copyright}")
        if not self._ai_mode:
            self._log(f"Algoritmo:   {algorithm}")
            self._log(f"Encoder:     {encoder_key}")
            self._log(f"Qualidade:   CRF={quality['crf']}, Preset={quality['preset']}")
        self._log(f"─────────────────────────")

        self._set_status("⏳ Upscaling em andamento...", COLORS["warning"])
        self._start_elapsed_timer()

        # ── AI Pipeline ──────────────────────────────────────────────────
        if self._ai_mode:
            if not self.ai_upscaler:
                messagebox.showerror("Erro", "ai_upscaler.py não encontrado!")
                self.is_processing = False
                self.start_btn.configure(state="normal", text="🚀  Iniciar Upscaling")
                self.cancel_btn.configure(state="disabled")
                return

            available, msg = check_realesrgan_available()
            if not available:
                messagebox.showerror(
                    "IA não disponível",
                    f"{msg}\n\nClique em '📦 Instalar IA' para instalar as dependências."
                )
                self.is_processing = False
                self.start_btn.configure(state="normal", text="🚀  Iniciar Upscaling")
                self.cancel_btn.configure(state="disabled")
                return

            selected_model = self.ai_model_var.get()
            engine_tag = "Real-CUGAN (Vulkan / Alta Velocidade)" if "CUGAN" in selected_model else "Real-ESRGAN (CUDA)"
            self._log(f"🤖 Iniciando pipeline de IA ({engine_tag})...")
            self._log(f"   Modelo selecionado: {selected_model}")

            # Resolve anti-copyright filters
            ac_options = ANTI_COPYRIGHT_OPTIONS.get(anti_copyright)
            ac_video_filter = None
            ac_audio_filter = None
            if ac_options:
                ac_video_filter = ac_options.get("video")
                ac_audio_filter = ac_options.get("audio")

            self.ai_upscaler.upscale(
                input_path=input_path,
                output_path=output_path,
                model_key=self.ai_model_var.get(),
                target_width=target_w,
                target_height=target_h,
                encoder=encoder,
                crf=quality["crf"],
                preset=quality["preset"],
                target_fps=target_fps,
                sharpen_filter=sharpen_filter,
                color_filter=color_filter,
                denoise_filter=denoise_filter,
                anti_copyright_filter=ac_video_filter,
                anti_copyright_audio=ac_audio_filter,
                on_progress=self._on_progress,
                on_complete=self._on_complete,
                on_log=self._on_log,
            )

        # ── FFmpeg Pipeline ───────────────────────────────────────────────
        else:
            self._log("Iniciando FFmpeg...")
            self.upscaler.upscale(
                input_path=input_path,
                output_path=output_path,
                target_width=target_w,
                target_height=target_h,
                algorithm=algorithm,
                encoder=encoder,
                crf=quality["crf"],
                preset=quality["preset"],
                aspect_ratio=aspect,
                target_fps=target_fps,
                sharpen_filter=sharpen_filter,
                color_filter=color_filter,
                denoise_filter=denoise_filter,
                anti_copyright=anti_copyright,
                on_progress=self._on_progress,
                on_complete=self._on_complete,
                on_log=self._on_log,
            )

    def _cancel_upscaling(self):
        """Cancel the current upscaling process."""
        if self.is_processing:
            if messagebox.askyesno("Cancelar", "Cancelar o upscaling?"):
                if self._ai_mode and self.ai_upscaler:
                    self.ai_upscaler.cancel()
                else:
                    self.upscaler.cancel()
                self._on_log("⚠ Cancelamento solicitado...")

    def _on_progress(self, percent: float, status: str):
        """Handle progress updates (called from worker thread)."""
        self.after(0, self._update_progress, percent, status)

    def _update_progress(self, percent: float, status: str):
        """Update progress UI (main thread)."""
        self.progress_bar.set(percent / 100)
        self.progress_percent_label.configure(text=f"{percent:.1f}%")
        self.progress_status_label.configure(text=status)

    def _on_log(self, message: str):
        """Handle log messages (called from worker thread)."""
        self.after(0, self._log, message)

    def _on_complete(self, success: bool, message: str):
        """Handle completion (called from worker thread)."""
        self.after(0, self._update_complete, success, message)

    def _update_complete(self, success: bool, message: str):
        """Update UI on completion (main thread)."""
        self.is_processing = False
        self._stop_elapsed_timer()
        self.start_btn.configure(state="normal", text="🚀  Iniciar Upscaling")
        self.cancel_btn.configure(state="disabled")

        elapsed = time.time() - self._start_time
        self.elapsed_label.configure(text=f"Tempo total: {format_time(elapsed)}")

        if success:
            self.progress_bar.set(1.0)
            self.progress_percent_label.configure(text="100%")
            self.progress_status_label.configure(text="✓ Concluído!")
            self._set_status(message, COLORS["success"])
            self._log(f"─────────────────────────")
            self._log(f"✓ {message}")
            self._log(f"Tempo total: {format_time(elapsed)}")

            output_path = self.output_entry.get().strip()
            if output_path and os.path.exists(output_path):
                self.live_compare_btn.pack(fill="x", pady=(10, 0))
                
                if messagebox.askyesno("Concluído! ✓",
                        f"{message}\n\nAbrir pasta do arquivo?"):
                    folder = os.path.dirname(os.path.abspath(output_path))
                    os.startfile(folder)
        else:
            self.progress_status_label.configure(text="✕ Falhou")
            self._set_status(message, COLORS["error"])
            self._log(f"─────────────────────────")
            self._log(f"✕ ERRO: {message}")
            messagebox.showerror("Erro", message)

    def _show_comparison(self):
        """Open side-by-side comparison."""
        input_path = self.file_entry.get().strip()
        output_path = self.output_entry.get().strip()
        
        print(f"DEBUG: Opening comparison for:\n  Orig: {input_path}\n  Upsk: {output_path}")
        
        if os.path.exists(input_path) and os.path.exists(output_path):
            success = self.upscaler.compare_videos(input_path, output_path)
            if not success:
                messagebox.showerror("Erro", "Não foi possível abrir o player de comparação (ffplay).")
        else:
            messagebox.showerror("Erro", "Arquivos não encontrados para comparação.")


# ── Drag & Drop Support ──────────────────────────────────────────────────────
def setup_drag_drop(app: VideoUpscalerApp):
    try:
        import windnd
        def handle_drop(files):
            if files:
                fp = files[0].decode('gbk') if isinstance(files[0], bytes) else files[0]
                if any(fp.lower().endswith(ext) for ext in VIDEO_EXTENSIONS):
                    app._load_video(fp)
        windnd.hook_dropfiles(app, func=handle_drop)
    except ImportError:
        pass


# ── Entry Point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = VideoUpscalerApp()
    setup_drag_drop(app)
    app.mainloop()
