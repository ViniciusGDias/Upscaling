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
import numpy as np
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
    diretamente na interface do aplicativo com suporte completo a áudio estéreo
    e mixagem simultânea de Trilha Sonora / BGM em tempo real.
    """

    def __init__(
        self,
        parent,
        video_path: Optional[str] = None,
        max_width: int = 320,
        max_height: int = 240,
        bgm_path: Optional[str] = None,
        bgm_volume: float = 0.15,
        bgm_start_sec: float = 0.0,
        music_auto_ducking: bool = False,
        ducking_mode: str = "cinema",
        anti_copyright: bool = False,
        anti_copyright_mode: str = "advanced",
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
        self._lock = threading.RLock()
        self._last_ctk_img = None

        # Estado de Áudio Principal do Vídeo (Pygame Mixer)
        self._audio_path: Optional[str] = None
        self._has_audio: bool = False
        self._audio_ready: bool = False
        self._audio_start_sec: float = 0.0
        self._is_muted: bool = False
        self._volume: float = 1.0

        # Estado de Trilha Sonora / BGM (Música de Fundo com Ducking e Anti-Copyright)
        self._bgm_path: Optional[str] = None
        self._bgm_volume: float = max(0.0, min(1.0, float(bgm_volume)))
        self._bgm_start_sec: float = max(0.0, float(bgm_start_sec))
        self._music_auto_ducking: bool = bool(music_auto_ducking)
        self._ducking_mode: str = str(ducking_mode or "cinema")
        self._anti_copyright: bool = bool(anti_copyright)
        self._anti_copyright_mode: str = str(anti_copyright_mode or "advanced")
        self._bgm_muted: bool = False
        self._bgm_has_audio: bool = False
        self._bgm_ready: bool = False
        self._bgm_array: Optional[np.ndarray] = None
        self._bgm_channel: Optional[pygame.mixer.Channel] = None

        _ensure_mixer_init()
        self._build_ui()

        if video_path and os.path.exists(video_path):
            self.load_video(video_path)

        if bgm_path and os.path.exists(bgm_path):
            self.load_bgm(
                bgm_path,
                volume=self._bgm_volume,
                start_sec=self._bgm_start_sec,
                music_auto_ducking=self._music_auto_ducking,
                ducking_mode=self._ducking_mode,
                anti_copyright=self._anti_copyright,
                anti_copyright_mode=self._anti_copyright_mode
            )

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

            w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or self.max_width
            h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or self.max_height
            scale = min(self.max_width / w, self.max_height / h)
            self._target_w = max(10, int(w * scale))
            self._target_h = max(10, int(h * scale))
            self._last_rendered_sec = -1

            self.slider.configure(to=self._total_frames - 1)
            self.slider.set(0)
            self._update_time_label(0, force=True)

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

    def load_bgm(
        self,
        bgm_path: Optional[str],
        volume: float = 0.15,
        start_sec: float = 0.0,
        music_auto_ducking: Optional[bool] = None,
        ducking_mode: Optional[str] = None,
        anti_copyright: Optional[bool] = None,
        anti_copyright_mode: Optional[str] = None,
    ):
        """Carrega a música de fundo para reprodução simultânea com o vídeo com suporte a ducking e anti-copyright."""
        self._bgm_path = bgm_path
        self._bgm_volume = max(0.0, min(1.0, float(volume)))
        self._bgm_start_sec = max(0.0, float(start_sec))
        if music_auto_ducking is not None:
            self._music_auto_ducking = bool(music_auto_ducking)
        if ducking_mode is not None:
            self._ducking_mode = str(ducking_mode)
        if anti_copyright is not None:
            self._anti_copyright = bool(anti_copyright)
        if anti_copyright_mode is not None:
            self._anti_copyright_mode = str(anti_copyright_mode)

        self._bgm_has_audio = False
        self._bgm_ready = False
        self._bgm_array = None

        if not (bgm_path and os.path.exists(bgm_path) and _AUDIO_AVAILABLE):
            return

        def bgm_loader():
            try:
                temp_dir = Path(os.environ.get("TEMP", ".")) / "urahara_audio_cache"
                temp_dir.mkdir(parents=True, exist_ok=True)

                mtime = os.path.getmtime(bgm_path)
                has_video_ref = bool(self.video_path and os.path.exists(self.video_path))
                v_tag = ""
                if has_video_ref:
                    v_mtime = os.path.getmtime(self.video_path)
                    v_tag = f"_{self.video_path}_{v_mtime}"

                cache_key = (
                    f"bgm_{bgm_path}_{mtime}{v_tag}_"
                    f"ss{self._bgm_start_sec:.2f}_"
                    f"duck{self._music_auto_ducking}_{self._ducking_mode}_"
                    f"ac{self._anti_copyright}_{self._anti_copyright_mode}"
                )
                h = hashlib.md5(cache_key.encode("utf-8")).hexdigest()
                wav_path = str(temp_dir / f"bgm_{h}.wav")

                # Converte para WAV 44100Hz 16-bit estéreo com FFmpeg aplicando ducking e anti-copyright
                if not (os.path.exists(wav_path) and os.path.getsize(wav_path) > 1000):
                    ffmpeg_exe = _find_ffmpeg()
                    flags = 0x08000000 if sys.platform == "win32" else 0
                    from subtitle_renderer import get_anti_copyright_dsp

                    dsp_str = get_anti_copyright_dsp(mode=self._anti_copyright_mode) if self._anti_copyright else ""

                    if self._music_auto_ducking and has_video_ref:
                        ducking_presets = {
                            "cinema": {"ratio": 1.35, "threshold": 0.05, "attack": 80, "release": 900, "knee": 3.0},
                            "balanced": {"ratio": 1.55, "threshold": 0.045, "attack": 60, "release": 750, "knee": 2.5},
                            "aggressive": {"ratio": 1.85, "threshold": 0.04, "attack": 40, "release": 600, "knee": 2.0},
                        }
                        params = ducking_presets.get(self._ducking_mode, ducking_presets["cinema"])
                        rat = params["ratio"]
                        th = params["threshold"]
                        att = params["attack"]
                        rel = params["release"]
                        kne = params["knee"]

                        if dsp_str:
                            dsp_chain = f"[1:a]{dsp_str}[bgm_prep];[bgm_prep]"
                        else:
                            dsp_chain = "[1:a]"

                        fc = (
                            f"[0:a]highpass=f=200,lowpass=f=3500[vocal_voice];"
                            f"{dsp_chain}[vocal_voice]sidechaincompress=threshold={th}:ratio={rat}:attack={att}:release={rel}:knee={kne}[aout]"
                        )
                        cmd = [
                            ffmpeg_exe, "-y",
                            "-i", self.video_path,
                        ]
                        if self._bgm_start_sec > 0:
                            cmd += ["-ss", f"{self._bgm_start_sec:.2f}"]
                        cmd += [
                            "-stream_loop", "-1",
                            "-i", bgm_path,
                            "-filter_complex", fc,
                            "-map", "[aout]",
                            "-vn", "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2",
                        ]
                        if self._duration > 0:
                            cmd += ["-t", f"{self._duration:.2f}"]
                        cmd.append(wav_path)
                    else:
                        cmd = [ffmpeg_exe, "-y"]
                        if self._bgm_start_sec > 0:
                            cmd += ["-ss", f"{self._bgm_start_sec:.2f}"]
                        cmd += ["-i", bgm_path]
                        if dsp_str:
                            cmd += ["-af", dsp_str]
                        cmd += [
                            "-vn", "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2",
                            wav_path
                        ]

                    res = subprocess.run(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=flags
                    )
                    if res.returncode != 0 or not os.path.exists(wav_path) or os.path.getsize(wav_path) < 1000:
                        # Fallback simples caso sidechain com vídeo falhe (ex: vídeo mudo)
                        fallback_cmd = [ffmpeg_exe, "-y"]
                        if self._bgm_start_sec > 0:
                            fallback_cmd += ["-ss", f"{self._bgm_start_sec:.2f}"]
                        fallback_cmd += ["-i", bgm_path]
                        if dsp_str:
                            fallback_cmd += ["-af", dsp_str]
                        fallback_cmd += [
                            "-vn", "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2",
                            wav_path
                        ]
                        subprocess.run(
                            fallback_cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            creationflags=flags
                        )

                    if not (os.path.exists(wav_path) and os.path.getsize(wav_path) > 1000):
                        return

                if self._bgm_path == bgm_path:
                    import soundfile as sf
                    arr, sr = sf.read(wav_path, dtype='int16')
                    if arr.ndim == 1:
                        arr = np.column_stack((arr, arr))
                    elif arr.ndim > 2 or arr.shape[1] > 2:
                        arr = arr[:, :2]

                    # Se a duração for conhecida, repete se necessário para cobrir o vídeo
                    target_dur = max(self._duration, 60.0)
                    needed_samples = int(target_dur * 44100)
                    if len(arr) < needed_samples and len(arr) > 0:
                        repeats = int(np.ceil(needed_samples / len(arr)))
                        arr = np.tile(arr, (repeats, 1))

                    self._bgm_array = arr
                    self._bgm_has_audio = True
                    self._bgm_ready = True

                    # Se o vídeo já estiver em reprodução, dispara a BGM no segundo atual
                    if self._is_playing:
                        curr_sec = self._current_frame_idx / self._fps if self._fps else 0.0
                        self._start_bgm_playback(curr_sec)
            except Exception:
                pass

        threading.Thread(target=bgm_loader, daemon=True).start()

    def _start_bgm_playback(self, start_sec: float):
        """Inicia a reprodução síncrona da música de fundo a partir do segundo do vídeo."""
        if not (self._bgm_has_audio and self._bgm_ready and self._bgm_array is not None and _AUDIO_AVAILABLE):
            return
        try:
            _ensure_mixer_init()
            if self._bgm_channel is None:
                self._bgm_channel = pygame.mixer.Channel(1)

            # Como -ss foi aplicado na geração do cache, o segundo start_sec do vídeo alinha com o sample do array
            start_sample = int(max(0.0, start_sec) * 44100)

            if len(self._bgm_array) == 0:
                return

            if start_sample < len(self._bgm_array):
                bgm_slice = self._bgm_array[start_sample:]
            else:
                looped = start_sample % len(self._bgm_array)
                bgm_slice = self._bgm_array[looped:]

            snd = pygame.sndarray.make_sound(bgm_slice)
            effective_vol = 0.0 if self._bgm_muted else self._bgm_volume
            self._bgm_channel.set_volume(effective_vol)
            self._bgm_channel.play(snd)
        except Exception:
            pass

    def set_bgm_volume(self, volume: float):
        """Ajusta o volume da música de fundo dinamicamente em tempo real."""
        self._bgm_volume = max(0.0, min(1.0, float(volume)))
        if _AUDIO_AVAILABLE and self._bgm_channel:
            try:
                effective_vol = 0.0 if self._bgm_muted else self._bgm_volume
                self._bgm_channel.set_volume(effective_vol)
            except Exception:
                pass

    def toggle_bgm_mute(self) -> bool:
        """Alterna o mudo exclusivamente para a música de fundo (mantém a voz do vídeo limpa)."""
        self._bgm_muted = not self._bgm_muted
        if _AUDIO_AVAILABLE and self._bgm_channel:
            try:
                effective_vol = 0.0 if self._bgm_muted else self._bgm_volume
                self._bgm_channel.set_volume(effective_vol)
            except Exception:
                pass
        return self._bgm_muted

    @property
    def is_bgm_muted(self) -> bool:
        return self._bgm_muted

    @property
    def bgm_volume(self) -> float:
        return self._bgm_volume

    @property
    def has_bgm(self) -> bool:
        return bool(self._bgm_has_audio and self._bgm_ready)

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

    def _update_time_label(self, frame_idx: int, force: bool = False):
        curr_sec = frame_idx / self._fps if self._fps else 0.0
        sec_int = int(curr_sec)
        if force or getattr(self, "_last_rendered_sec", -1) != sec_int:
            self._last_rendered_sec = sec_int
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
        self._update_time_label(frame_idx, force=True)
        if not self._is_scrubbing:
            self.slider.set(frame_idx)

    def _render_frame(self, bgr_frame):
        try:
            target_w = getattr(self, "_target_w", self.max_width)
            target_h = getattr(self, "_target_h", self.max_height)

            # INTER_LINEAR é ~5x mais rápido que INTER_AREA e fluido para reprodução de vídeo
            resized = cv2.resize(bgr_frame, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)
            ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(target_w, target_h))

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
        self._start_bgm_playback(start_sec)
        self._play_loop()

    def _pause_audio(self):
        if _AUDIO_AVAILABLE:
            if self._has_audio:
                try:
                    pygame.mixer.music.pause()
                except Exception:
                    pass
            if self._bgm_channel and self._bgm_channel.get_busy():
                try:
                    self._bgm_channel.pause()
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

        self._pause_audio()

        self.btn_play.configure(
            text=" Play",
            fg_color="#10b981",
            hover_color="#059669",
            image=icon_manager.get_icon("play", size=(14, 14), color="#09090b")
        )

    def stop(self):
        self.pause()
        if _AUDIO_AVAILABLE:
            if self._has_audio:
                try:
                    pygame.mixer.music.stop()
                except Exception:
                    pass
            if self._bgm_channel:
                try:
                    self._bgm_channel.stop()
                except Exception:
                    pass
        self._current_frame_idx = 0

    def rewind(self):
        """Reinicia o vídeo para o início."""
        was_playing = self._is_playing
        self.pause()
        self._show_frame_at(0)
        if was_playing:
            self.after(50, self.play)

    def seek_seconds(self, sec: float):
        """Pula para um segundo específico do vídeo com sincronização de áudio."""
        if self._cap is None or not self._cap.isOpened() or self._fps <= 0:
            return
        sec = max(0.0, min(sec, self._duration))
        frame_idx = max(0, min(int(sec * self._fps), self._total_frames - 1))
        self._show_frame_at(frame_idx)

        if self._is_playing:
            self._start_audio_playback(sec)
            self._start_bgm_playback(sec)

    def _on_playback_ended(self):
        """Finaliza a reprodução com segurança ao término do vídeo/áudio sem travar a interface."""
        self.pause()
        if self._bgm_channel:
            try:
                self._bgm_channel.stop()
            except Exception:
                pass
        self._show_frame_at(0)

    def _play_loop(self):
        if not self._is_playing:
            return

        ended = False
        frame_to_render = None

        with self._lock:
            if self._cap is None or not self._cap.isOpened():
                ended = True
            elif self._has_audio and self._audio_ready and _AUDIO_AVAILABLE:
                pos_ms = pygame.mixer.music.get_pos()
                if pos_ms >= 0:
                    curr_sec = self._audio_start_sec + (pos_ms / 1000.0)
                    target_frame = int(curr_sec * self._fps)
                    if target_frame >= self._total_frames:
                        ended = True
                    elif target_frame == self._current_frame_idx:
                        # Se ainda estiver no mesmo frame já desenhado, aguarda próximo ciclo
                        delay_ms = max(10, int(350.0 / self._fps))
                        self._after_id = self.after(delay_ms, self._play_loop)
                        return
                    else:
                        delta = target_frame - self._current_frame_idx
                        if delta == 1:
                            ret, frame = self._cap.read()
                        elif 1 < delta <= 4:
                            for _ in range(delta - 1):
                                self._cap.grab()
                            ret, frame = self._cap.retrieve()
                        else:
                            self._cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                            ret, frame = self._cap.read()

                        if not ret or frame is None:
                            ended = True
                        else:
                            self._current_frame_idx = target_frame
                            frame_to_render = frame
                else:
                    ended = True
            else:
                ret, frame = self._cap.read()
                if not ret or frame is None or self._current_frame_idx + 1 >= self._total_frames:
                    ended = True
                else:
                    self._current_frame_idx += 1
                    frame_to_render = frame

        if ended:
            self._on_playback_ended()
            return

        if frame_to_render is not None:
            self._render_frame(frame_to_render)

        if not self._is_scrubbing:
            if self._current_frame_idx % 4 == 0:
                self.slider.set(self._current_frame_idx)
        self._update_time_label(self._current_frame_idx)

        # Intervalo calculado para sincronização fluida e leve
        delay_ms = max(15, int(1000.0 / self._fps))
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
            if self._bgm_channel:
                try:
                    self._bgm_channel.stop()
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
