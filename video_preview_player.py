"""
video_preview_player.py - Mini-Player de Vídeo e Áudio Embutido para Urahara Studio.
Fornece preview interativo com Play/Pause, scrubber de linha do tempo, controle de áudio/mute
e abertura externa, utilizando OpenCV, Pygame Mixer e Pillow para máxima performance e sincronização perfeita.
"""

from __future__ import annotations
import os
import sys
import time
import shutil
import hashlib
import subprocess
import threading
from pathlib import Path
from typing import Optional, Callable
import cv2
from PIL import Image
import customtkinter as ctk
import icon_manager

# Silencia o aviso inicial do Pygame no terminal
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

_AUDIO_AVAILABLE = False
try:
    import pygame
    _AUDIO_AVAILABLE = True
except ImportError:
    _AUDIO_AVAILABLE = False


def _ensure_mixer_init() -> bool:
    """Inicializa o subsistema de áudio do Pygame com baixa latência se ainda não estiver ativo."""
    if not _AUDIO_AVAILABLE:
        return False
    try:
        if not pygame.mixer.get_init():
            # 44.1 kHz, 16-bit signed, estéreo, buffer de 1024 amostras (~23ms)
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
        return True
    except Exception:
        return False


def _find_ffmpeg() -> str:
    """Localiza o binário do FFmpeg em caminhos locais do Urahara ou PATH do sistema."""
    base = Path(__file__).parent.resolve()
    candidates = [
        base / "bin" / "ffmpeg.exe",
        base / "_internal" / "bin" / "ffmpeg.exe",
        Path("bin/ffmpeg.exe"),
        Path("ffmpeg.exe"),
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    found = shutil.which("ffmpeg")
    return found if found else "ffmpeg"


def _format_time(sec: float) -> str:
    m = int(sec // 60)
    s = int(sec % 60)
    return f"{m:02d}:{s:02d}"


class VideoPreviewPlayer(ctk.CTkFrame):
    """
    Mini-Player embutido de alta fidelidade para inspecionar vídeos e cortes
    diretamente na interface do aplicativo com suporte completo a áudio estéreo.
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

        # Estado de Vídeo (OpenCV)
        self._cap: Optional[cv2.VideoCapture] = None
        self._fps: float = 30.0
        self._total_frames: int = 0
        self._duration: float = 0.0
        self._current_frame_idx: int = 0
        self._is_playing: bool = False
        self._is_scrubbing: bool = False
        self._was_playing_before_scrub: bool = False
        self._after_id = None
        self._lock = threading.Lock()
        self._last_ctk_img = None

        # Estado de Áudio (Pygame Mixer)
        self._audio_path: Optional[str] = None
        self._has_audio: bool = False
        self._audio_ready: bool = False
        self._audio_start_sec: float = 0.0
        self._is_muted: bool = False
        self._volume: float = 1.0

        _ensure_mixer_init()
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

        # 3. Barra de Controles (Play/Pause, Replay, Mute/Áudio, Abrir Externo)
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
            width=75,
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
            width=65,
            corner_radius=6,
            command=self.rewind
        )
        self.btn_rewind.pack(side="left", padx=(0, 6))

        self.btn_mute = ctk.CTkButton(
            controls_row,
            text="",
            image=icon_manager.get_icon("volume", size=(13, 13), color="#e4e4e7"),
            fg_color="#18181b",
            hover_color="#27272a",
            height=28,
            width=32,
            corner_radius=6,
            command=self.toggle_mute
        )
        self.btn_mute.pack(side="left", padx=(0, 6))

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

    def toggle_mute(self):
        """Alterna entre mudo e reprodução normal de som."""
        self._is_muted = not self._is_muted
        if _AUDIO_AVAILABLE:
            try:
                vol = 0.0 if self._is_muted else self._volume
                pygame.mixer.music.set_volume(vol)
            except Exception:
                pass

        if self._is_muted:
            self.btn_mute.configure(
                image=icon_manager.get_icon("mute", size=(13, 13), color="#ef4444")
            )
        else:
            self.btn_mute.configure(
                image=icon_manager.get_icon("volume", size=(13, 13), color="#e4e4e7")
            )

    def load_video(self, video_path: str):
        """Carrega um novo vídeo no mini-player e prepara a trilha sonora."""
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

        # Extrai áudio em background para evitar travamento da interface
        self._extract_audio(video_path)

    def _extract_audio(self, video_path: str):
        """Extrai e armazena em cache o áudio do vídeo para reprodução síncrona."""
        self._has_audio = False
        self._audio_ready = False
        self._audio_path = None

        if not _AUDIO_AVAILABLE:
            return

        def worker():
            try:
                temp_dir = Path(os.environ.get("TEMP", ".")) / "urahara_audio_cache"
                temp_dir.mkdir(parents=True, exist_ok=True)

                mtime = os.path.getmtime(video_path)
                h = hashlib.md5(f"{video_path}_{mtime}".encode()).hexdigest()
                wav_path = str(temp_dir / f"audio_{h}.wav")

                # Reutiliza se o arquivo já existir no cache
                if not (os.path.exists(wav_path) and os.path.getsize(wav_path) > 1000):
                    ffmpeg_exe = _find_ffmpeg()
                    cmd = [
                        ffmpeg_exe, "-y", "-i", video_path,
                        "-vn", "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2",
                        wav_path
                    ]
                    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
                    res = subprocess.run(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=flags
                    )
                    if res.returncode != 0 or not os.path.exists(wav_path) or os.path.getsize(wav_path) < 1000:
                        return

                if self.video_path == video_path:
                    self._audio_path = wav_path
                    self._has_audio = True
                    self._audio_ready = True

                    # Se o usuário clicou Play antes da extração terminar, inicia o áudio agora
                    if self._is_playing:
                        start_sec = self._current_frame_idx / self._fps if self._fps else 0.0
                        self._start_audio_playback(start_sec)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _start_audio_playback(self, start_sec: float):
        """Inicia a trilha sonora no segundo especificado com volume configurado."""
        if not (self._has_audio and self._audio_ready and self._audio_path and _AUDIO_AVAILABLE):
            return
        try:
            _ensure_mixer_init()
            pygame.mixer.music.load(self._audio_path)
            vol = 0.0 if self._is_muted else self._volume
            pygame.mixer.music.set_volume(vol)
            pygame.mixer.music.play(start=max(0.0, start_sec))
            self._audio_start_sec = start_sec
        except Exception:
            pass

    def _on_slider_press(self, event=None):
        self._is_scrubbing = True
        self._was_playing_before_scrub = self._is_playing
        if self._is_playing:
            self._pause_audio()

    def _on_slider_release(self, event=None):
        self._is_scrubbing = False
        val = int(self.slider.get())
        sec = val / self._fps if self._fps else 0.0
        self.seek_seconds(sec)
        if self._was_playing_before_scrub:
            self.play()

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

        start_sec = self._current_frame_idx / self._fps if self._fps else 0.0
        self._start_audio_playback(start_sec)
        self._play_loop()

    def _pause_audio(self):
        if _AUDIO_AVAILABLE and self._has_audio:
            try:
                pygame.mixer.music.pause()
            except Exception:
                pass

    def pause(self):
        self._is_playing = False
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

        if _AUDIO_AVAILABLE and self._has_audio:
            try:
                pygame.mixer.music.pause()
            except Exception:
                pass

        self.btn_play.configure(
            text=" Play",
            fg_color="#10b981",
            hover_color="#059669",
            image=icon_manager.get_icon("play", size=(14, 14), color="#09090b")
        )

    def stop(self):
        self.pause()
        if _AUDIO_AVAILABLE and self._has_audio:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
        self._current_frame_idx = 0

    def rewind(self):
        was_playing = self._is_playing
        self.stop()
        self._show_frame_at(0)
        if was_playing:
            self.play()

    def seek_seconds(self, sec: float):
        """Pula para um segundo específico do vídeo com sincronização de áudio."""
        if self._cap is None or not self._cap.isOpened() or self._fps <= 0:
            return
        sec = max(0.0, min(sec, self._duration))
        frame_idx = max(0, min(int(sec * self._fps), self._total_frames - 1))
        self._show_frame_at(frame_idx)

        if self._is_playing:
            self._start_audio_playback(sec)

    def _play_loop(self):
        if not self._is_playing:
            return

        with self._lock:
            if self._cap is None or not self._cap.isOpened():
                self.pause()
                return

            if self._has_audio and self._audio_ready and _AUDIO_AVAILABLE:
                pos_ms = pygame.mixer.music.get_pos()
                if pos_ms >= 0:
                    curr_sec = self._audio_start_sec + (pos_ms / 1000.0)
                    target_frame = int(curr_sec * self._fps)
                    if target_frame >= self._total_frames:
                        self.rewind()
                        return
                    if abs(target_frame - self._current_frame_idx) > 1:
                        self._cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                    ret, frame = self._cap.read()
                    if not ret or frame is None:
                        self.rewind()
                        return
                    self._current_frame_idx = target_frame
                else:
                    # Final do áudio atingido -> reinicia
                    self.rewind()
                    return
            else:
                ret, frame = self._cap.read()
                if not ret or frame is None:
                    self.rewind()
                    return
                self._current_frame_idx += 1

        self._render_frame(frame)
        if not self._is_scrubbing:
            self.slider.set(self._current_frame_idx)
        self._update_time_label(self._current_frame_idx)

        # Intervalo calculado para sincronização fluida (mínimo de 20ms)
        delay_ms = max(20, int(1000.0 / self._fps))
        self._after_id = self.after(delay_ms, self._play_loop)

    def open_in_system_player(self):
        """Abre o vídeo no reprodutor padrão do Windows."""
        if self.video_path and os.path.exists(self.video_path):
            try:
                os.startfile(self.video_path)
            except Exception:
                try:
                    subprocess.Popen(["cmd", "/c", "start", "", self.video_path])
                except Exception:
                    pass

    def destroy(self):
        self.stop()
        if _AUDIO_AVAILABLE:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
        with self._lock:
            if self._cap is not None:
                try:
                    self._cap.release()
                except Exception:
                    pass
                self._cap = None
        super().destroy()
