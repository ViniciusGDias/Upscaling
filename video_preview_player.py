"""
video_preview_player.py - Mini-Player de Vídeo Embutido para Urahara Studio.
Fornece preview interativo com Play/Pause, scrubber de linha do tempo e abertura externa,
utilizando OpenCV e Pillow para máxima performance e compatibilidade HiDPI.
"""

from __future__ import annotations
import os
import time
import threading
from pathlib import Path
from typing import Optional, Callable
import cv2
from PIL import Image
import customtkinter as ctk
import icon_manager


def _format_time(sec: float) -> str:
    m = int(sec // 60)
    s = int(sec % 60)
    return f"{m:02d}:{s:02d}"


class VideoPreviewPlayer(ctk.CTkFrame):
    """
    Mini-Player embutido de alta precisão para inspecionar vídeos e cortes
    diretamente na interface do aplicativo.
    """

    def __init__(
        self,
        parent,
        video_path: Optional[str] = None,
        max_width: int = 320,
        max_height: int = 240,
        **kwargs
    ):
        super().__init__(parent, fg_color="#111113", corner_radius=10, border_width=1, border_color="#27272a", **kwargs)
        self.max_width = max_width
        self.max_height = max_height
        self.video_path: Optional[str] = None

        self._cap: Optional[cv2.VideoCapture] = None
        self._fps: float = 30.0
        self._total_frames: int = 0
        self._duration: float = 0.0
        self._current_frame_idx: int = 0
        self._is_playing: bool = False
        self._is_scrubbing: bool = False
        self._after_id = None
        self._lock = threading.Lock()

        self._build_ui()

        if video_path and os.path.exists(video_path):
            self.load_video(video_path)

    def _build_ui(self):
        # 1. Canvas / Frame de Visualização
        self.display_container = ctk.CTkFrame(self, fg_color="#09090b", corner_radius=8)
        self.display_container.pack(fill="x", padx=8, pady=(8, 4))

        self.display_label = ctk.CTkLabel(
            self.display_container,
            text="Nenhum vídeo carregado",
            font=ctk.CTkFont(size=12),
            text_color="#71717a",
            width=self.max_width,
            height=self.max_height
        )
        self.display_label.pack(padx=2, pady=2)

        # 2. Linha do Tempo (Scrubber) e Timestamps
        timeline_row = ctk.CTkFrame(self, fg_color="transparent")
        timeline_row.pack(fill="x", padx=10, pady=(2, 2))

        self.slider = ctk.CTkSlider(
            timeline_row,
            from_=0,
            to=100,
            number_of_steps=1000,
            progress_color="#10b981",
            button_color="#10b981",
            button_hover_color="#059669",
            command=self._on_slider_moved
        )
        self.slider.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.slider.set(0)
        self.slider.bind("<ButtonPress-1>", self._on_slider_press)
        self.slider.bind("<ButtonRelease-1>", self._on_slider_release)

        self.time_lbl = ctk.CTkLabel(
            timeline_row,
            text="00:00 / 00:00",
            font=ctk.CTkFont(family="Consolas", size=11, weight="bold"),
            text_color="#a1a1aa"
        )
        self.time_lbl.pack(side="right")

        # 3. Barra de Controles (Play/Pause, Replay, Abrir Externo)
        controls_row = ctk.CTkFrame(self, fg_color="transparent")
        controls_row.pack(fill="x", padx=10, pady=(2, 8))

        self.btn_play = ctk.CTkButton(
            controls_row,
            text=" Play",
            image=icon_manager.get_icon("play", size=(14, 14), color="#09090b"),
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            text_color="#09090b",
            height=28,
            width=80,
            corner_radius=6,
            command=self.toggle_play
        )
        self.btn_play.pack(side="left", padx=(0, 6))

        self.btn_rewind = ctk.CTkButton(
            controls_row,
            text=" Início",
            image=icon_manager.get_icon("refresh", size=(13, 13), color="#e4e4e7"),
            font=ctk.CTkFont(size=11),
            fg_color="#18181b",
            hover_color="#27272a",
            text_color="#e4e4e7",
            height=28,
            width=70,
            corner_radius=6,
            command=self.rewind
        )
        self.btn_rewind.pack(side="left", padx=(0, 6))

        self.btn_open_external = ctk.CTkButton(
            controls_row,
            text=" Abrir no Player",
            image=icon_manager.get_icon("eye", size=(13, 13), color="#a1a1aa"),
            font=ctk.CTkFont(size=11),
            fg_color="#18181b",
            hover_color="#27272a",
            text_color="#a1a1aa",
            height=28,
            corner_radius=6,
            command=self.open_in_system_player
        )
        self.btn_open_external.pack(side="right")

    def load_video(self, video_path: str):
        """Carrega um novo vídeo no mini-player."""
        self.stop()

        with self._lock:
            if self._cap is not None:
                self._cap.release()
                self._cap = None

            if not video_path or not os.path.exists(video_path):
                self.video_path = None
                self.display_label.configure(image=None, text="Arquivo não encontrado")
                return

            self.video_path = video_path
            self._cap = cv2.VideoCapture(video_path)

            if not self._cap.isOpened():
                self.display_label.configure(image=None, text="Erro ao abrir vídeo")
                return

            self._fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
            if self._fps <= 0 or self._fps > 120:
                self._fps = 30.0
            self._total_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
            self._duration = self._total_frames / self._fps
            self._current_frame_idx = 0

            self.slider.configure(to=self._total_frames - 1)
            self.slider.set(0)
            self._update_time_label(0)

        # Mostra o primeiro frame imediatamente
        self._show_frame_at(0)

    def _on_slider_press(self, event=None):
        self._is_scrubbing = True

    def _on_slider_release(self, event=None):
        self._is_scrubbing = False
        val = int(self.slider.get())
        self._show_frame_at(val)

    def _on_slider_moved(self, value):
        val = int(value)
        self._update_time_label(val)
        if self._is_scrubbing:
            self._show_frame_at(val)

    def _update_time_label(self, frame_idx: int):
        curr_sec = frame_idx / self._fps if self._fps else 0.0
        self.time_lbl.configure(text=f"{_format_time(curr_sec)} / {_format_time(self._duration)}")

    def _show_frame_at(self, frame_idx: int):
        with self._lock:
            if self._cap is None or not self._cap.isOpened():
                return
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = self._cap.read()
            if not ret or frame is None:
                return
            self._current_frame_idx = frame_idx

        self._render_frame(frame)
        self._update_time_label(frame_idx)
        if not self._is_scrubbing:
            self.slider.set(frame_idx)

    def _render_frame(self, bgr_frame):
        try:
            h, w = bgr_frame.shape[:2]
            if w <= 0 or h <= 0:
                return

            # Ajusta aspecto mantendo proporção até max_width x max_height
            scale = min(self.max_width / w, self.max_height / h)
            nw = max(10, int(w * scale))
            nh = max(10, int(h * scale))

            resized = cv2.resize(bgr_frame, (nw, nh), interpolation=cv2.INTER_AREA)
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)
            ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(nw, nh))

            self.display_label.configure(image=ctk_img, text="")
            # Guarda referência para evitar coleta de lixo
            self._last_ctk_img = ctk_img
        except Exception:
            pass

    def toggle_play(self):
        """Alterna entre reproduzir e pausar o vídeo."""
        if self._is_playing:
            self.pause()
        else:
            self.play()

    def play(self):
        if self._cap is None or not self._cap.isOpened():
            return
        self._is_playing = True
        self.btn_play.configure(
            text=" Pause",
            fg_color="#f59e0b",
            hover_color="#d97706",
            image=None
        )
        self._play_loop()

    def pause(self):
        self._is_playing = False
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        self.btn_play.configure(
            text=" Play",
            fg_color="#10b981",
            hover_color="#059669",
            image=icon_manager.get_icon("play", size=(14, 14), color="#09090b")
        )

    def stop(self):
        self.pause()
        self._current_frame_idx = 0

    def rewind(self):
        self.pause()
        self._show_frame_at(0)

    def _play_loop(self):
        if not self._is_playing:
            return

        with self._lock:
            if self._cap is None or not self._cap.isOpened():
                self.pause()
                return

            ret, frame = self._cap.read()
            if not ret or frame is None:
                # Fim do vídeo -> loop volta para o início
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = self._cap.read()
                self._current_frame_idx = 0
                if not ret or frame is None:
                    self.pause()
                    return

            self._current_frame_idx += 1

        self._render_frame(frame)
        self.slider.set(self._current_frame_idx)
        self._update_time_label(self._current_frame_idx)

        # Intervalo calculado a partir do FPS (mínimo de 30ms para não engasgar a UI)
        delay_ms = max(33, int(1000.0 / self._fps))
        self._after_id = self.after(delay_ms, self._play_loop)

    def open_in_system_player(self):
        """Abre o vídeo no reprodutor padrão do Windows."""
        if self.video_path and os.path.exists(self.video_path):
            try:
                os.startfile(self.video_path)
            except Exception as e:
                try:
                    import subprocess
                    subprocess.Popen(["cmd", "/c", "start", "", self.video_path])
                except Exception:
                    pass

    def destroy(self):
        self.stop()
        with self._lock:
            if self._cap is not None:
                try:
                    self._cap.release()
                except Exception:
                    pass
                self._cap = None
        super().destroy()
