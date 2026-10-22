"""
censorship_editor_dialog.py - Editor e Revisor Interativo de Censura Visual (Anime Shield)
Permite ao usuário:
- Visualizar os quadros do vídeo com o desfoque aplicado em tempo real
- Ajustar a posição do blur (descer para não pegar no rosto do personagem)
- Ajustar largura, altura e timestamps de início/fim do blur
- Adicionar censuras manuais em qualquer ponto do vídeo
- Excluir detecções automáticas indesejadas (1 clique)
- Escolher entre Modo Automático, Interativo ou 100% Manual
"""

import cv2
import numpy as np
import customtkinter as ctk
import icon_manager
from PIL import Image
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional
from censorship_manager import apply_soft_blur_to_box, apply_zoom_focus_to_frame


import urahara_theme

COLORS = {
    **urahara_theme.COLORS,
    "accent": urahara_theme.COLORS["accent_primary"],
    "accent_hover": urahara_theme.COLORS["accent_hover"],
    "accent_green": urahara_theme.COLORS["accent_primary"],
    "accent_green_hover": urahara_theme.COLORS["accent_hover"],
}


class CensorshipEditorDialog(ctk.CTkToplevel):
    """Janela modal para inspecionar, mover, redimensionar e criar censuras manuais (Blur ou Zoom no Rosto)."""

    def __init__(
        self,
        parent,
        video_path: str,
        initial_detections: Optional[List[Dict[str, Any]]] = None,
        blur_strength: str = "medium",
        censor_method: str = "blur",
        on_confirm: Optional[Callable[[List[Dict[str, Any]], str], None]] = None,
        **kwargs
    ):
        super().__init__(parent, **kwargs)
        self.title("Anime Shield — Ajuste Interativo & Manual de Censura Visual (Blur & Zoom)")
        self.geometry("1080x810")
        self.minsize(960, 700)
        self.configure(fg_color=COLORS["bg_dark"])

        self.video_path = video_path
        self.on_confirm = on_confirm
        self.blur_strength = blur_strength
        self.censor_method = censor_method
        self.preview_simulated = False

        # Abre o vídeo para leitura de quadros
        self.cap = cv2.VideoCapture(video_path)
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        self.video_duration = self.total_frames / self.fps
        self.vid_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
        self.vid_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720

        # Normaliza intervalos: lista de dicts com {"start", "end", "box": [x1, y1, x2, y2], "label"}
        self.regions: List[Dict[str, Any]] = self._convert_detections_to_intervals(initial_detections or [])
        self.current_time = 0.0
        self.selected_region_idx: Optional[int] = None
        self._preview_ctk_img = None

        self.transient(parent)
        self.grab_set()

        self._build_ui()
        self._jump_to_time(0.0)

        # Se houver regiões já detectadas, pula para a primeira
        if self.regions:
            self._jump_to_time(self.regions[0]["start"])

    def _convert_detections_to_intervals(self, raw_dets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Converte detecções pontuais em blocos/intervalos contínuos editáveis."""
        if not raw_dets:
            return []

        default_action = "zoom" if "zoom" in str(self.censor_method).lower() else "blur"

        # Se já estiver no formato de intervalos (com 'start' e 'end')
        if "start" in raw_dets[0] and "end" in raw_dets[0]:
            out = []
            for d in raw_dets:
                dc = dict(d)
                if "action" not in dc:
                    dc["action"] = default_action
                if "zoom_factor" not in dc:
                    dc["zoom_factor"] = 1.8
                out.append(dc)
            return out

        # Agrupa detecções pontuais próximas com persistência de ~0.5s
        sorted_dets = sorted(raw_dets, key=lambda x: x["time"])
        intervals = []
        curr_box = None
        curr_start = None
        curr_end = None
        curr_lbl = "bust"
        curr_action = default_action
        curr_zf = 1.8

        for d in sorted_dets:
            t = d["time"]
            box = list(d["box"])
            lbl = d.get("label", "bust")
            act = d.get("action", default_action)
            zf = float(d.get("zoom_factor", 1.8))

            if curr_start is None:
                curr_start = max(0.0, t - 0.1)
                curr_end = t + 0.45
                curr_box = box
                curr_lbl = lbl
                curr_action = act
                curr_zf = zf
            elif t <= curr_end + 0.35:
                # Continua o mesmo bloco
                curr_end = t + 0.45
                # Faz média suave da posição da caixa
                curr_box = [
                    int((curr_box[0] + box[0]) / 2),
                    int((curr_box[1] + box[1]) / 2),
                    int((curr_box[2] + box[2]) / 2),
                    int((curr_box[3] + box[3]) / 2),
                ]
            else:
                # Salva o bloco anterior e inicia novo
                intervals.append({
                    "start": round(curr_start, 2),
                    "end": round(min(self.video_duration, curr_end), 2),
                    "box": curr_box,
                    "label": curr_lbl,
                    "action": curr_action,
                    "zoom_factor": curr_zf
                })
                curr_start = max(0.0, t - 0.1)
                curr_end = t + 0.45
                curr_box = box
                curr_lbl = lbl
                curr_action = act
                curr_zf = zf

        if curr_start is not None:
            intervals.append({
                "start": round(curr_start, 2),
                "end": round(min(self.video_duration, curr_end), 2),
                "box": curr_box,
                "label": curr_lbl,
                "action": curr_action,
                "zoom_factor": curr_zf
            })

        return intervals

    def _build_ui(self):
        # Header
        header = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], corner_radius=0, height=60)
        header.pack(fill="x")
        header.pack_propagate(False)

        title_lbl = ctk.CTkLabel(
            header,
            text=" Editor & Ajuste Interativo de Censura Visual",
            image=icon_manager.get_icon("shield", size=(20, 20), color="#10b981"), compound="left",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=COLORS["text_primary"]
        )
        title_lbl.pack(side="left", padx=16, pady=6)

        sub_lbl = ctk.CTkLabel(
            header,
            text="Desça o blur para afastar do rosto, redimensione ou adicione novos intervalos manuais.",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"]
        )
        sub_lbl.pack(side="left", padx=8, pady=6)

        # Body principal dividido em 2 colunas
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=14, pady=10)
        body.grid_columnconfigure(0, weight=3) # Preview
        body.grid_columnconfigure(1, weight=2) # Controles

        # ── COLUNA ESQUERDA: PREVIEW DE VÍDEO + TIMELINE ───────────
        left_col = ctk.CTkFrame(body, fg_color=COLORS["bg_card"], corner_radius=10)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=0)
        left_col.grid_rowconfigure(0, weight=1)
        left_col.grid_columnconfigure(0, weight=1)

        # Canvas para exibir o frame
        self.canvas_label = ctk.CTkLabel(left_col, text="", fg_color="#000000", corner_radius=8, cursor="fleur")
        self.canvas_label.grid(row=0, column=0, padx=12, pady=12, sticky="nsew")
        self.canvas_label.bind("<Button-1>", self._on_canvas_press)
        self.canvas_label.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas_label.bind("<ButtonRelease-1>", self._on_canvas_release)

        # Barra de modo de visualização e dica
        mode_bar = ctk.CTkFrame(left_col, fg_color="transparent")
        mode_bar.grid(row=1, column=0, padx=12, pady=(0, 6), sticky="ew")

        self.btn_preview_mode = ctk.CTkButton(
            mode_bar,
            text="👁️ Ver com Efeito Aplicado",
            width=185,
            height=28,
            fg_color=COLORS["border"],
            hover_color=COLORS["bg_card_hover"],
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._toggle_preview_mode
        )
        self.btn_preview_mode.pack(side="left")

        self.preview_hint_lbl = ctk.CTkLabel(
            mode_bar,
            text="💡 Arraste a caixa até o rosto do personagem!",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["accent"]
        )
        self.preview_hint_lbl.pack(side="left", padx=10)

        # Controles de navegação da timeline
        nav_frame = ctk.CTkFrame(left_col, fg_color="transparent")
        nav_frame.grid(row=2, column=0, padx=12, pady=(0, 8), sticky="ew")
        nav_frame.grid_columnconfigure(1, weight=1)

        self.time_label = ctk.CTkLabel(
            nav_frame,
            text="00:00.0 / 00:00.0",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["accent"]
        )
        self.time_label.grid(row=0, column=0, padx=(0, 10), sticky="w")

        self.timeline_slider = ctk.CTkSlider(
            nav_frame,
            from_=0.0,
            to=self.video_duration,
            command=self._on_slider_moved,
            progress_color=COLORS["accent"],
            button_color=COLORS["accent"]
        )
        self.timeline_slider.set(0.0)
        self.timeline_slider.grid(row=0, column=1, sticky="ew", padx=8)

        # Botões de navegação fina
        btn_nav = ctk.CTkFrame(left_col, fg_color="transparent")
        btn_nav.grid(row=3, column=0, padx=12, pady=(0, 10), sticky="ew")

        ctk.CTkButton(btn_nav, text="-1s", width=55, height=28, fg_color=COLORS["border"],
                      command=lambda: self._jump_relative(-1.0)).pack(side="left", padx=2)
        ctk.CTkButton(btn_nav, text="◀ -0.2s", width=60, height=28, fg_color=COLORS["border"],
                      command=lambda: self._jump_relative(-0.2)).pack(side="left", padx=2)
        ctk.CTkButton(btn_nav, text="▶ +0.2s", width=60, height=28, fg_color=COLORS["border"],
                      command=lambda: self._jump_relative(0.2)).pack(side="left", padx=2)
        ctk.CTkButton(btn_nav, text="+1s", width=55, height=28, fg_color=COLORS["border"],
                      command=lambda: self._jump_relative(1.0)).pack(side="left", padx=2)

        ctk.CTkButton(btn_nav, text="Pular p/ Próxima Censura", height=28,
                      fg_color=COLORS["accent_green"], hover_color=COLORS["accent_green_hover"],
                      font=ctk.CTkFont(weight="bold"),
                      command=self._jump_to_next_region).pack(side="right", padx=4)

        # ── COLUNA DIREITA: PAINEL DE AJUSTES DA REGIÃO ─────────────
        right_col = ctk.CTkFrame(body, fg_color=COLORS["bg_card"], corner_radius=10)
        right_col.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=0)
        right_col.grid_rowconfigure(2, weight=1)
        right_col.grid_columnconfigure(0, weight=1)

        adj_header = ctk.CTkLabel(
            right_col,
            text="Ajuste Interativo da Censura Ativa",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text_primary"]
        )
        adj_header.grid(row=0, column=0, padx=14, pady=(10, 4), sticky="w")

        self.region_info_lbl = ctk.CTkLabel(
            right_col,
            text="Nenhuma região ativa neste segundo.",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_muted"],
            justify="left"
        )
        self.region_info_lbl.grid(row=1, column=0, padx=14, pady=(0, 6), sticky="w")

        # Container rolável para todos os ajustes
        self.adjust_scroll = ctk.CTkScrollableFrame(right_col, fg_color=COLORS["bg_dark"], corner_radius=8)
        self.adjust_scroll.grid(row=2, column=0, padx=10, pady=2, sticky="nsew")
        self.adjust_scroll.grid_columnconfigure(0, weight=1)

        # ── BLOCO 0: TIPO DE EFEITO (BLUR VS ZOOM NO ROSTO) ──
        box_action = ctk.CTkFrame(self.adjust_scroll, fg_color=COLORS["bg_card"], corner_radius=6, border_width=1, border_color=COLORS["border"])
        box_action.pack(fill="x", padx=6, pady=4)

        ctk.CTkLabel(
            box_action,
            text="🎬 Tipo de Censura nesta Região:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLORS["accent"]
        ).pack(anchor="w", padx=8, pady=(6, 4))

        self.action_segmented = ctk.CTkSegmentedButton(
            box_action,
            values=["🌫️ Desfoque (Blur)", "🔍 Zoom no Foco (Close)"],
            command=self._on_action_segmented_changed,
            selected_color=COLORS["accent"],
            selected_hover_color=COLORS["accent_hover"],
            height=28
        )
        self.action_segmented.set("🔍 Zoom no Foco (Close)" if "zoom" in str(self.censor_method).lower() else "🌫️ Desfoque (Blur)")
        self.action_segmented.pack(fill="x", padx=8, pady=(0, 6))

        # Opções específicas para Zoom
        self.zoom_opts_frame = ctk.CTkFrame(box_action, fg_color="transparent")
        self.zoom_opts_frame.pack(fill="x", padx=8, pady=(0, 6))

        ctk.CTkLabel(self.zoom_opts_frame, text="Intensidade do Zoom:", font=ctk.CTkFont(size=11)).pack(side="left")
        self.zoom_factor_menu = ctk.CTkOptionMenu(
            self.zoom_opts_frame,
            values=["1.4x (Leve)", "1.8x (Recomendado - Foco Rosto)", "2.2x (Close Forte)"],
            width=200,
            height=24,
            command=self._on_zoom_factor_changed
        )
        self.zoom_factor_menu.set("1.8x (Recomendado - Foco Rosto)")
        self.zoom_factor_menu.pack(side="right")

        self.zoom_hint_lbl = ctk.CTkLabel(
            box_action,
            text="💡 Posicione a caixa no rosto. O vídeo dará zoom nessa área e cortará a parte sensível.",
            font=ctk.CTkFont(size=10),
            text_color=COLORS["accent_green"],
            wraplength=340,
            justify="left"
        )
        self.zoom_hint_lbl.pack(anchor="w", padx=8, pady=(0, 6))

        # ── BLOCO 1: EDIÇÃO DE INTERVALO DE TEMPO ──
        box_time = ctk.CTkFrame(self.adjust_scroll, fg_color=COLORS["bg_card"], corner_radius=6, border_width=1, border_color=COLORS["border"])
        box_time.pack(fill="x", padx=6, pady=4)

        ctk.CTkLabel(
            box_time,
            text="⏱️ Intervalo de Tempo da Censura:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLORS["accent"]
        ).pack(anchor="w", padx=8, pady=(6, 4))

        # Início
        row_start = ctk.CTkFrame(box_time, fg_color="transparent")
        row_start.pack(fill="x", padx=8, pady=2)
        ctk.CTkLabel(row_start, text="Início (s):", font=ctk.CTkFont(size=11), width=65, anchor="w").pack(side="left")
        self.entry_start = ctk.CTkEntry(row_start, width=70, height=26, font=ctk.CTkFont(family="Consolas", size=11))
        self.entry_start.pack(side="left", padx=4)
        self.entry_start.bind("<Return>", self._on_start_entry_submitted)
        self.entry_start.bind("<FocusOut>", self._on_start_entry_submitted)

        self.btn_set_start = ctk.CTkButton(
            row_start, text="⏱️ Início = Atual", width=95, height=26,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=COLORS["accent_green"], hover_color=COLORS["accent_green_hover"],
            text_color="#000000",
            command=self._set_start_current_time
        )
        self.btn_set_start.pack(side="left", padx=4)

        ctk.CTkButton(row_start, text="-0.5s", width=42, height=26, fg_color=COLORS["border"], font=ctk.CTkFont(size=10),
                      command=lambda: self._nudge_time("start", -0.5)).pack(side="left", padx=2)
        ctk.CTkButton(row_start, text="+0.5s", width=42, height=26, fg_color=COLORS["border"], font=ctk.CTkFont(size=10),
                      command=lambda: self._nudge_time("start", 0.5)).pack(side="left", padx=2)

        # Fim
        row_end = ctk.CTkFrame(box_time, fg_color="transparent")
        row_end.pack(fill="x", padx=8, pady=2)
        ctk.CTkLabel(row_end, text="Fim (s):", font=ctk.CTkFont(size=11), width=65, anchor="w").pack(side="left")
        self.entry_end = ctk.CTkEntry(row_end, width=70, height=26, font=ctk.CTkFont(family="Consolas", size=11))
        self.entry_end.pack(side="left", padx=4)
        self.entry_end.bind("<Return>", self._on_end_entry_submitted)
        self.entry_end.bind("<FocusOut>", self._on_end_entry_submitted)

        self.btn_set_end = ctk.CTkButton(
            row_end, text="⏱️ Fim = Atual", width=95, height=26,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=COLORS["accent_green"], hover_color=COLORS["accent_green_hover"],
            text_color="#000000",
            command=self._set_end_current_time
        )
        self.btn_set_end.pack(side="left", padx=4)

        ctk.CTkButton(row_end, text="-0.5s", width=42, height=26, fg_color=COLORS["border"], font=ctk.CTkFont(size=10),
                      command=lambda: self._nudge_time("end", -0.5)).pack(side="left", padx=2)
        ctk.CTkButton(row_end, text="+0.5s", width=42, height=26, fg_color=COLORS["border"], font=ctk.CTkFont(size=10),
                      command=lambda: self._nudge_time("end", 0.5)).pack(side="left", padx=2)

        self.lbl_time_summary = ctk.CTkLabel(
            box_time, text="Duração: --", font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLORS["text_secondary"]
        )
        self.lbl_time_summary.pack(anchor="w", padx=8, pady=(2, 6))

        # ── BLOCO 2: POSIÇÃO DO BLUR (X E Y - 4 DIREÇÕES) ──
        box_pos = ctk.CTkFrame(self.adjust_scroll, fg_color=COLORS["bg_card"], corner_radius=6, border_width=1, border_color=COLORS["border"])
        box_pos.pack(fill="x", padx=6, pady=4)

        ctk.CTkLabel(
            box_pos,
            text="📍 Mover Blur (X / Y - Cima, Baixo, Lados):",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLORS["accent"]
        ).pack(anchor="w", padx=8, pady=(6, 4))

        # Linha Cima
        row_up = ctk.CTkFrame(box_pos, fg_color="transparent")
        row_up.pack(pady=2)
        ctk.CTkButton(row_up, text="⬆️ Subir (-20px)", width=130, height=28, fg_color=COLORS["border"],
                      hover_color=COLORS["accent_hover"], command=lambda: self._nudge_selected_box(dy=-20)).pack()

        # Linha Esquerda / Centro / Direita
        row_mid = ctk.CTkFrame(box_pos, fg_color="transparent")
        row_mid.pack(pady=2)
        ctk.CTkButton(row_mid, text="⬅️ Esquerda (-25px)", width=120, height=28, fg_color=COLORS["border"],
                      hover_color=COLORS["accent_hover"], command=lambda: self._nudge_selected_box(dx=-25)).pack(side="left", padx=3)
        ctk.CTkButton(row_mid, text="🎯 Centro", width=75, height=28, fg_color=COLORS["bg_dark"],
                      border_width=1, border_color=COLORS["border"], hover_color=COLORS["border"],
                      command=self._center_selected_box).pack(side="left", padx=3)
        ctk.CTkButton(row_mid, text="➡️ Direita (+25px)", width=120, height=28, fg_color=COLORS["border"],
                      hover_color=COLORS["accent_hover"], command=lambda: self._nudge_selected_box(dx=25)).pack(side="left", padx=3)

        # Linha Baixo
        row_down = ctk.CTkFrame(box_pos, fg_color="transparent")
        row_down.pack(pady=2)
        ctk.CTkButton(row_down, text="⬇️ Descer (+20px)", width=130, height=28, fg_color=COLORS["border"],
                      hover_color=COLORS["accent_hover"], command=lambda: self._nudge_selected_box(dy=20)).pack()

        # Passo Fino (±5px)
        row_fine = ctk.CTkFrame(box_pos, fg_color="transparent")
        row_fine.pack(pady=(4, 6))
        ctk.CTkLabel(row_fine, text="Fino:", font=ctk.CTkFont(size=10), text_color=COLORS["text_muted"]).pack(side="left", padx=2)
        ctk.CTkButton(row_fine, text="◀ 5px", width=48, height=24, fg_color=COLORS["bg_dark"], font=ctk.CTkFont(size=10),
                      command=lambda: self._nudge_selected_box(dx=-5)).pack(side="left", padx=2)
        ctk.CTkButton(row_fine, text="▲ 5px", width=48, height=24, fg_color=COLORS["bg_dark"], font=ctk.CTkFont(size=10),
                      command=lambda: self._nudge_selected_box(dy=-5)).pack(side="left", padx=2)
        ctk.CTkButton(row_fine, text="▼ 5px", width=48, height=24, fg_color=COLORS["bg_dark"], font=ctk.CTkFont(size=10),
                      command=lambda: self._nudge_selected_box(dy=5)).pack(side="left", padx=2)
        ctk.CTkButton(row_fine, text="▶ 5px", width=48, height=24, fg_color=COLORS["bg_dark"], font=ctk.CTkFont(size=10),
                      command=lambda: self._nudge_selected_box(dx=5)).pack(side="left", padx=2)

        # ── BLOCO 3: DIMENSÕES E LARGURA DO BLUR ──
        box_dim = ctk.CTkFrame(self.adjust_scroll, fg_color=COLORS["bg_card"], corner_radius=6, border_width=1, border_color=COLORS["border"])
        box_dim.pack(fill="x", padx=6, pady=4)

        ctk.CTkLabel(
            box_dim,
            text="📐 Largura, Altura & Escala do Blur:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLORS["accent"]
        ).pack(anchor="w", padx=8, pady=(6, 4))

        # Largura
        row_w = ctk.CTkFrame(box_dim, fg_color="transparent")
        row_w.pack(fill="x", padx=8, pady=2)
        ctk.CTkLabel(row_w, text="Largura:", font=ctk.CTkFont(size=11), width=75, anchor="w").pack(side="left")
        ctk.CTkButton(row_w, text="-25px", width=65, height=26, fg_color=COLORS["border"],
                      command=lambda: self._adjust_box_dimensions(dw=-25)).pack(side="left", padx=3)
        ctk.CTkButton(row_w, text="+25px", width=65, height=26, fg_color=COLORS["border"],
                      command=lambda: self._adjust_box_dimensions(dw=25)).pack(side="left", padx=3)

        # Altura
        row_h = ctk.CTkFrame(box_dim, fg_color="transparent")
        row_h.pack(fill="x", padx=8, pady=2)
        ctk.CTkLabel(row_h, text="Altura:", font=ctk.CTkFont(size=11), width=75, anchor="w").pack(side="left")
        ctk.CTkButton(row_h, text="-20px", width=65, height=26, fg_color=COLORS["border"],
                      command=lambda: self._adjust_box_dimensions(dh=-20)).pack(side="left", padx=3)
        ctk.CTkButton(row_h, text="+20px", width=65, height=26, fg_color=COLORS["border"],
                      command=lambda: self._adjust_box_dimensions(dh=20)).pack(side="left", padx=3)

        # Escala Geral
        row_scale = ctk.CTkFrame(box_dim, fg_color="transparent")
        row_scale.pack(fill="x", padx=8, pady=(2, 6))
        ctk.CTkLabel(row_scale, text="Escala:", font=ctk.CTkFont(size=11), width=75, anchor="w").pack(side="left")
        ctk.CTkButton(row_scale, text="Menor (-25%)", width=105, height=26, fg_color=COLORS["border"],
                      command=lambda: self._scale_selected_box(0.8)).pack(side="left", padx=3)
        ctk.CTkButton(row_scale, text="Maior (+25%)", width=105, height=26, fg_color=COLORS["border"],
                      command=lambda: self._scale_selected_box(1.25)).pack(side="left", padx=3)

        # ── BLOCO 4: AÇÕES DA REGIÃO ──
        action_btns = ctk.CTkFrame(self.adjust_scroll, fg_color="transparent")
        action_btns.pack(fill="x", padx=6, pady=(6, 4))
        action_btns.grid_columnconfigure((0, 1), weight=1)

        self.del_btn = ctk.CTkButton(
            action_btns,
            text="Excluir esta Censura",
            image=icon_manager.get_icon("trash", size=(13, 13), color=COLORS["error"]), compound="left",
            fg_color="#451A1A",
            hover_color=COLORS["error"],
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._delete_current_region
        )
        self.del_btn.grid(row=0, column=0, padx=3, sticky="ew")

        self.add_manual_btn = ctk.CTkButton(
            action_btns,
            text="Nova Censura Aqui",
            image=icon_manager.get_icon("sparkle", size=(13, 13)), compound="left",
            fg_color=COLORS["border"],
            hover_color=COLORS["accent_hover"],
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._add_manual_region_at_current_time
        )
        self.add_manual_btn.grid(row=0, column=1, padx=3, sticky="ew")

        # ── BLOCO 5: LISTA DE REGIÕES ──
        ctk.CTkLabel(
            right_col,
            text="Intervalos Censurados no Vídeo:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"]
        ).grid(row=3, column=0, padx=14, pady=(8, 2), sticky="w")

        self.region_listbox = ctk.CTkScrollableFrame(right_col, fg_color=COLORS["bg_dark"], height=105)
        self.region_listbox.grid(row=4, column=0, padx=10, pady=(0, 6), sticky="nsew")

        # Botão Limpar Tudo
        ctk.CTkButton(
            right_col,
            text="Limpar Todas as Censuras (Fazer do Zero)",
            image=icon_manager.get_icon("trash", size=(13, 13), color=COLORS["error"]), compound="left",
            height=26,
            fg_color="transparent",
            text_color=COLORS["text_secondary"],
            hover_color=COLORS["border"],
            command=self._clear_all_regions
        ).grid(row=5, column=0, padx=14, pady=(0, 6), sticky="ew")

        # Footer com botões de confirmar e fechar
        footer = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], corner_radius=0, height=54)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        ctk.CTkButton(
            footer,
            text="Cancelar",
            width=100,
            height=38,
            fg_color=COLORS["border"],
            command=self.destroy
        ).pack(side="left", padx=16, pady=8)

        ctk.CTkButton(
            footer,
            text="SALVAR E APLICAR CENSURA",
            image=icon_manager.get_icon("check", size=(16, 16), color="#09090b"), compound="left",
            width=260,
            height=38,
            fg_color=COLORS["accent_green"],
            hover_color=COLORS["accent_green_hover"],
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_save_and_apply
        ).pack(side="right", padx=16, pady=8)

    # ── MÉTODOS DE CONTROLE E NAVEGAÇÃO ───────────────────────────
    def _jump_to_time(self, seconds: float):
        self.current_time = max(0.0, min(self.video_duration, seconds))
        self.timeline_slider.set(self.current_time)
        self._update_time_label()
        self._render_current_frame()
        self._update_region_panel()
        self._refresh_regions_list()

    def _jump_relative(self, delta: float):
        self._jump_to_time(self.current_time + delta)

    def _on_slider_moved(self, value: float):
        self.current_time = float(value)
        self._update_time_label()
        self._render_current_frame()
        self._update_region_panel()

    def _update_time_label(self):
        cur_m = int(self.current_time // 60)
        cur_s = self.current_time % 60
        tot_m = int(self.video_duration // 60)
        tot_s = self.video_duration % 60
        self.time_label.configure(text=f"{cur_m:02d}:{cur_s:04.1f} / {tot_m:02d}:{tot_s:04.1f}")

    def _find_region_at_time(self, t: float) -> Optional[int]:
        for idx, r in enumerate(self.regions):
            if r["start"] <= t <= r["end"]:
                return idx
        return None

    def _jump_to_next_region(self):
        future_regions = [idx for idx, r in enumerate(self.regions) if r["start"] > self.current_time + 0.2]
        if future_regions:
            next_idx = future_regions[0]
            self._jump_to_time(self.regions[next_idx]["start"] + 0.1)
        elif self.regions:
            self._jump_to_time(self.regions[0]["start"] + 0.1)

    def _toggle_preview_mode(self):
        """Alterna entre o modo de demarcação de caixa e a visualização simulada do efeito final."""
        self.preview_simulated = not self.preview_simulated
        if self.preview_simulated:
            self.btn_preview_mode.configure(
                text="📐 Voltar p/ Ajustar Caixa",
                fg_color=COLORS["accent"],
                hover_color=COLORS["accent_hover"]
            )
            self.preview_hint_lbl.configure(
                text="✨ Modo Simulação: Veja exatamente o resultado final da censura!",
                text_color=COLORS["accent_green"]
            )
        else:
            self.btn_preview_mode.configure(
                text="👁️ Ver com Efeito Aplicado",
                fg_color=COLORS["border"],
                hover_color=COLORS["bg_card_hover"]
            )
            self.preview_hint_lbl.configure(
                text="💡 Arraste a caixa até o rosto do personagem!",
                text_color=COLORS["accent"]
            )
        self._render_current_frame()

    def _on_action_segmented_changed(self, value: str):
        """Alterna a ação da região selecionada entre Zoom no Rosto e Blur Suave."""
        if self.selected_region_idx is None:
            return
        action = "zoom" if "zoom" in str(value).lower() else "blur"
        r = self.regions[self.selected_region_idx]
        r["action"] = action
        if action == "zoom":
            self.zoom_opts_frame.pack(fill="x", padx=8, pady=(0, 6))
            self.zoom_hint_lbl.configure(
                text="💡 Posicione a caixa no rosto. O vídeo dará zoom nessa área e cortará a parte sensível.",
                text_color=COLORS["accent_green"]
            )
        else:
            self.zoom_opts_frame.pack_forget()
            self.zoom_hint_lbl.configure(
                text="💡 Posicione a caixa sobre o decote/região que receberá o desfoque suave.",
                text_color=COLORS["accent"]
            )
        self._render_current_frame()
        self._refresh_regions_list()

    def _on_zoom_factor_changed(self, value: str):
        """Altera a intensidade do zoom para a região selecionada."""
        if self.selected_region_idx is None:
            return
        try:
            factor = float(str(value).split("x")[0])
        except Exception:
            factor = 1.8
        r = self.regions[self.selected_region_idx]
        r["zoom_factor"] = factor
        self._render_current_frame()
        self._refresh_regions_list()

    def _render_current_frame(self):
        """Renderiza o quadro atual com o efeito (blur suave ou zoom focado) ou caixas indicativas."""
        frame_idx = int(self.current_time * self.fps)
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = self.cap.read()
        if not ret or frame is None:
            return

        active_idx = self._find_region_at_time(self.current_time)

        if self.preview_simulated:
            # MODO SIMULAÇÃO: Aplica os efeitos reais (Zoom focado no rosto ou Blur suave)
            for idx, r in enumerate(self.regions):
                if r["start"] <= self.current_time <= r["end"]:
                    box = r["box"]
                    act = r.get("action", "blur")
                    if act == "zoom":
                        zf = float(r.get("zoom_factor", 1.8))
                        frame = apply_zoom_focus_to_frame(frame, box, zoom_factor=zf)
                    else:
                        frame = apply_soft_blur_to_box(frame, box, blur_strength=self.blur_strength)
        else:
            # MODO DEMARCAÇÃO DE CAIXA: Desenha as bordas e rótulos
            for idx, r in enumerate(self.regions):
                if r["start"] <= self.current_time <= r["end"]:
                    box = r["box"]
                    act = r.get("action", "blur")
                    is_active = (idx == active_idx)

                    if act == "zoom":
                        # Caixa de Zoom: Borda Ciano vibrante com mira no centro
                        color = (255, 229, 0) if is_active else (180, 150, 20) # BGR
                        cv2.rectangle(frame, (box[0], box[1]), (box[2], box[3]), color, 2)
                        tag = f"FOCO ZOOM ({r.get('zoom_factor', 1.8):.1f}x)"
                        cv2.putText(frame, tag, (box[0], max(22, box[1] - 8)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
                        # Mira sutil central
                        cx = (box[0] + box[2]) // 2
                        cy = (box[1] + box[3]) // 2
                        cv2.drawMarker(frame, (cx, cy), color, markerType=cv2.MARKER_CROSS, markerSize=18, thickness=2)
                    else:
                        # Caixa de Blur: Aplica blur e desenha contorno
                        frame = apply_soft_blur_to_box(frame, box, blur_strength=self.blur_strength)
                        color = (0, 212, 255) if is_active else (100, 100, 100)
                        cv2.rectangle(frame, (box[0], box[1]), (box[2], box[3]), color, 2)
                        tag = "DESFOQUE (BLUR)"
                        cv2.putText(frame, tag, (box[0], max(22, box[1] - 8)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)

        # Redimensiona para caber na tela mantendo proporção
        h_frame, w_frame = frame.shape[:2]
        target_w = 540
        target_h = int(target_w * (h_frame / w_frame))
        self._target_w = target_w
        self._target_h = target_h
        resized = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)

        # Converte para CTkImage
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        self._preview_ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(target_w, target_h))
        self.canvas_label.configure(image=self._preview_ctk_img)

    # ── MOUSE DRAG & DROP NO PREVIEW ─────────────────────────────
    def _canvas_to_video_coords(self, cx: int, cy: int) -> tuple[int, int]:
        target_w = getattr(self, "_target_w", 540)
        target_h = getattr(self, "_target_h", 360)
        scale_x = self.vid_w / max(1, target_w)
        scale_y = self.vid_h / max(1, target_h)
        return int(cx * scale_x), int(cy * scale_y)

    def _on_canvas_press(self, event):
        vx, vy = self._canvas_to_video_coords(event.x, event.y)
        # Verifica se clicou dentro da região ativa atual
        active_idx = self._find_region_at_time(self.current_time)
        if active_idx is not None:
            r = self.regions[active_idx]
            x1, y1, x2, y2 = r["box"]
            # Margem de tolerância
            if (x1 - 10) <= vx <= (x2 + 10) and (y1 - 10) <= vy <= (y2 + 10):
                self.selected_region_idx = active_idx
                self._drag_start_mouse = (vx, vy)
                self._drag_start_box = list(r["box"])
                return

        # Ou verifica qualquer região ativa neste tempo
        for idx, r in enumerate(self.regions):
            if r["start"] <= self.current_time <= r["end"]:
                x1, y1, x2, y2 = r["box"]
                if x1 <= vx <= x2 and y1 <= vy <= y2:
                    self.selected_region_idx = idx
                    self._drag_start_mouse = (vx, vy)
                    self._drag_start_box = list(r["box"])
                    self._update_region_panel()
                    self._render_current_frame()
                    return

    def _on_canvas_drag(self, event):
        if self.selected_region_idx is None or not hasattr(self, "_drag_start_mouse"):
            return
        vx, vy = self._canvas_to_video_coords(event.x, event.y)
        dx = vx - self._drag_start_mouse[0]
        dy = vy - self._drag_start_mouse[1]
        x1, y1, x2, y2 = self._drag_start_box
        bw = x2 - x1
        bh = y2 - y1
        nx1 = max(0, min(self.vid_w - bw, x1 + dx))
        ny1 = max(0, min(self.vid_h - bh, y1 + dy))
        r = self.regions[self.selected_region_idx]
        r["box"] = [nx1, ny1, nx1 + bw, ny1 + bh]
        self._render_current_frame()
        self._update_region_panel(update_entries=False)

    def _on_canvas_release(self, event):
        if hasattr(self, "_drag_start_mouse"):
            del self._drag_start_mouse
            del self._drag_start_box
        self._update_region_panel()
        self._refresh_regions_list()

    # ── EDIÇÃO DO INTERVALO DE TEMPO ──
    def _set_start_current_time(self):
        if self.selected_region_idx is None:
            return
        r = self.regions[self.selected_region_idx]
        s = round(self.current_time, 2)
        e = r["end"]
        if s >= e:
            e = round(min(self.video_duration, s + 1.5), 2)
        r["start"] = s
        r["end"] = e
        self._refresh_all_after_edit()

    def _set_end_current_time(self):
        if self.selected_region_idx is None:
            return
        r = self.regions[self.selected_region_idx]
        e = round(self.current_time, 2)
        s = r["start"]
        if e <= s:
            s = round(max(0.0, e - 1.5), 2)
        r["start"] = s
        r["end"] = e
        self._refresh_all_after_edit()

    def _nudge_time(self, which: str, delta: float):
        if self.selected_region_idx is None:
            return
        r = self.regions[self.selected_region_idx]
        if which == "start":
            ns = max(0.0, min(self.video_duration - 0.1, round(r["start"] + delta, 2)))
            if ns >= r["end"]:
                ns = max(0.0, round(r["end"] - 0.2, 2))
            r["start"] = ns
        else:
            ne = max(0.1, min(self.video_duration, round(r["end"] + delta, 2)))
            if ne <= r["start"]:
                ne = min(self.video_duration, round(r["start"] + 0.2, 2))
            r["end"] = ne
        self._refresh_all_after_edit()

    def _on_start_entry_submitted(self, event=None):
        if self.selected_region_idx is None:
            return
        txt = self.entry_start.get().strip()
        try:
            val = float(txt)
            r = self.regions[self.selected_region_idx]
            ns = max(0.0, min(self.video_duration - 0.1, round(val, 2)))
            if ns >= r["end"]:
                r["end"] = round(min(self.video_duration, ns + 1.0), 2)
            r["start"] = ns
            self._refresh_all_after_edit()
        except Exception:
            pass

    def _on_end_entry_submitted(self, event=None):
        if self.selected_region_idx is None:
            return
        txt = self.entry_end.get().strip()
        try:
            val = float(txt)
            r = self.regions[self.selected_region_idx]
            ne = max(0.1, min(self.video_duration, round(val, 2)))
            if ne <= r["start"]:
                r["start"] = round(max(0.0, ne - 1.0), 2)
            r["end"] = ne
            self._refresh_all_after_edit()
        except Exception:
            pass

    def _refresh_all_after_edit(self):
        cur_r = self.regions[self.selected_region_idx] if self.selected_region_idx is not None else None
        self.regions.sort(key=lambda x: x["start"])
        if cur_r is not None:
            for i, reg in enumerate(self.regions):
                if reg is cur_r:
                    self.selected_region_idx = i
                    break
        self._render_current_frame()
        self._update_region_panel()
        self._refresh_regions_list()

    def _update_region_panel(self, update_entries: bool = True):
        """Atualiza os controles da coluna direita baseado na região atual."""
        idx = self._find_region_at_time(self.current_time)
        self.selected_region_idx = idx

        if idx is not None:
            r = self.regions[idx]
            x1, y1, x2, y2 = r["box"]
            dur = max(0.0, r["end"] - r["start"])
            act = r.get("action", "blur")
            zf = float(r.get("zoom_factor", 1.8))
            badge = f"🔍 ZOOM {zf:.1f}x" if act == "zoom" else "🌫️ BLUR"

            self.region_info_lbl.configure(
                text=f"Região #{idx + 1} [{badge}]: {r['start']:.2f}s até {r['end']:.2f}s  (Duração: {dur:.2f}s)\nPosição: X={x1}..{x2} | Y={y1}..{y2}  ({x2 - x1}x{y2 - y1}px)",
                text_color=COLORS["accent"]
            )
            self.lbl_time_summary.configure(
                text=f"Duração: {dur:.2f}s  (De {r['start']:.2f}s até {r['end']:.2f}s)",
                text_color=COLORS["accent_green"]
            )
            if update_entries:
                self.entry_start.delete(0, "end")
                self.entry_start.insert(0, f"{r['start']:.2f}")
                self.entry_end.delete(0, "end")
                self.entry_end.insert(0, f"{r['end']:.2f}")
            self.del_btn.configure(state="normal")

            # Atualiza o SegmentedButton e menu de Zoom
            self.action_segmented.set("🔍 Zoom no Foco (Close)" if act == "zoom" else "🌫️ Desfoque (Blur)")
            if act == "zoom":
                self.zoom_opts_frame.pack(fill="x", padx=8, pady=(0, 6))
                if abs(zf - 1.4) < 0.1:
                    self.zoom_factor_menu.set("1.4x (Leve)")
                elif abs(zf - 2.2) < 0.1:
                    self.zoom_factor_menu.set("2.2x (Close Forte)")
                else:
                    self.zoom_factor_menu.set("1.8x (Recomendado - Foco Rosto)")
                self.zoom_hint_lbl.configure(
                    text="💡 Posicione a caixa no rosto. O vídeo dará zoom nessa área e cortará a parte sensível.",
                    text_color=COLORS["accent_green"]
                )
            else:
                self.zoom_opts_frame.pack_forget()
                self.zoom_hint_lbl.configure(
                    text="💡 Posicione a caixa sobre o decote/região que receberá o desfoque suave.",
                    text_color=COLORS["accent"]
                )
        else:
            self.region_info_lbl.configure(
                text="Sem censura ativa neste segundo.\nClique abaixo para adicionar ou pule para uma existente.",
                text_color=COLORS["text_muted"]
            )
            self.lbl_time_summary.configure(
                text="Duração: Nenhuma região ativa",
                text_color=COLORS["text_muted"]
            )
            if update_entries:
                self.entry_start.delete(0, "end")
                self.entry_end.delete(0, "end")
            self.del_btn.configure(state="disabled")

    # ── AJUSTES NA CAIXA SELECIONADA (X, Y E DIMENSÕES) ─────────
    def _nudge_selected_box(self, dx: int = 0, dy: int = 0):
        """Move a caixa em 4 direções: horizontalmente (dx) e/ou verticalmente (dy)."""
        if self.selected_region_idx is None:
            return
        r = self.regions[self.selected_region_idx]
        x1, y1, x2, y2 = r["box"]
        bw = x2 - x1
        bh = y2 - y1

        nx1 = max(0, min(self.vid_w - bw, x1 + dx))
        nx2 = nx1 + bw

        ny1 = max(0, min(self.vid_h - bh, y1 + dy))
        ny2 = ny1 + bh

        r["box"] = [nx1, ny1, nx2, ny2]
        self._render_current_frame()
        self._update_region_panel(update_entries=False)

    def _adjust_box_dimensions(self, dw: int = 0, dh: int = 0):
        """Aumenta ou diminui a largura ou altura da caixa independentemente."""
        if self.selected_region_idx is None:
            return
        r = self.regions[self.selected_region_idx]
        x1, y1, x2, y2 = r["box"]
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        nw = max(30, min(self.vid_w, (x2 - x1) + dw))
        nh = max(30, min(self.vid_h, (y2 - y1) + dh))
        nx1 = max(0, cx - nw // 2)
        nx2 = min(self.vid_w, nx1 + nw)
        ny1 = max(0, cy - nh // 2)
        ny2 = min(self.vid_h, ny1 + nh)
        r["box"] = [nx1, ny1, nx2, ny2]
        self._render_current_frame()
        self._update_region_panel(update_entries=False)

    def _center_selected_box(self):
        """Centraliza horizontalmente e verticalmente a caixa selecionada."""
        if self.selected_region_idx is None:
            return
        r = self.regions[self.selected_region_idx]
        x1, y1, x2, y2 = r["box"]
        bw = x2 - x1
        bh = y2 - y1
        nx1 = (self.vid_w - bw) // 2
        ny1 = (self.vid_h - bh) // 2
        r["box"] = [nx1, ny1, nx1 + bw, ny1 + bh]
        self._render_current_frame()
        self._update_region_panel(update_entries=False)

    def _scale_selected_box(self, factor: float):
        """Aumenta ou diminui a área do blur proporcionalmente."""
        if self.selected_region_idx is None:
            return
        r = self.regions[self.selected_region_idx]
        x1, y1, x2, y2 = r["box"]
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        nw = int((x2 - x1) * factor)
        nh = int((y2 - y1) * factor)
        nx1 = max(0, cx - nw // 2)
        nx2 = min(self.vid_w, cx + nw // 2)
        ny1 = max(0, cy - nh // 2)
        ny2 = min(self.vid_h, cy + nh // 2)
        r["box"] = [nx1, ny1, nx2, ny2]
        self._render_current_frame()
        self._update_region_panel()

    def _delete_current_region(self):
        if self.selected_region_idx is not None:
            del self.regions[self.selected_region_idx]
            self.selected_region_idx = None
            self._render_current_frame()
            self._update_region_panel()
            self._refresh_regions_list()

    def _delete_region_by_index(self, idx: int):
        if 0 <= idx < len(self.regions):
            del self.regions[idx]
            self._render_current_frame()
            self._update_region_panel()
            self._refresh_regions_list()

    def _add_manual_region_at_current_time(self):
        """Adiciona uma nova região manual centralizada de tamanho padrão."""
        box_w = int(self.vid_w * 0.28)
        box_h = int(self.vid_h * 0.22)
        cx = self.vid_w // 2
        cy = int(self.vid_h * 0.55) # Ligeiramente abaixo do centro para focar no busto/tronco

        current_action = "zoom" if "zoom" in str(self.action_segmented.get()).lower() else "blur"
        try:
            current_zf = float(str(self.zoom_factor_menu.get()).split("x")[0])
        except Exception:
            current_zf = 1.8

        new_region = {
            "start": round(self.current_time, 2),
            "end": round(min(self.video_duration, self.current_time + 2.5), 2),
            "box": [cx - box_w // 2, cy - box_h // 2, cx + box_w // 2, cy + box_h // 2],
            "label": "manual",
            "action": current_action,
            "zoom_factor": current_zf
        }
        self.regions.append(new_region)
        self.regions.sort(key=lambda x: x["start"])
        self._render_current_frame()
        self._update_region_panel()
        self._refresh_regions_list()

    def _refresh_regions_list(self):
        """Atualiza a lista de cards de intervalos censurados."""
        if not hasattr(self, "region_listbox") or self.region_listbox is None:
            return

        for w in self.region_listbox.winfo_children():
            w.destroy()

        if not self.regions:
            ctk.CTkLabel(
                self.region_listbox,
                text="Nenhuma região demarcada. Clique em 'Nova Censura Aqui' para criar.",
                font=ctk.CTkFont(size=11),
                text_color=COLORS["text_muted"]
            ).pack(pady=10)
            return

        for idx, r in enumerate(self.regions):
            card = ctk.CTkFrame(self.region_listbox, fg_color=COLORS["bg_card"], corner_radius=6)
            card.pack(fill="x", padx=4, pady=2)
            card.grid_columnconfigure(1, weight=1)

            dur = max(0.0, r["end"] - r["start"])
            act = r.get("action", "blur")
            zf = float(r.get("zoom_factor", 1.8))
            badge_text = f"🔍 Zoom {zf:.1f}x" if act == "zoom" else "🌫️ Blur"
            badge_color = "#0284c7" if act == "zoom" else COLORS["border"]

            # Badge do tipo
            b_lbl = ctk.CTkLabel(
                card,
                text=badge_text,
                font=ctk.CTkFont(size=10, weight="bold"),
                fg_color=badge_color,
                corner_radius=4,
                width=80,
                height=20
            )
            b_lbl.grid(row=0, column=0, padx=(6, 4), pady=4)

            # Texto do tempo
            t_lbl = ctk.CTkLabel(
                card,
                text=f"#{idx+1}: {r['start']:.2f}s → {r['end']:.2f}s ({dur:.1f}s)",
                font=ctk.CTkFont(size=11),
                text_color=COLORS["text_primary"],
                anchor="w"
            )
            t_lbl.grid(row=0, column=1, padx=4, pady=4, sticky="w")

            # Botão ir até
            ctk.CTkButton(
                card,
                text="Ir",
                width=36,
                height=22,
                font=ctk.CTkFont(size=10, weight="bold"),
                fg_color=COLORS["accent"],
                hover_color=COLORS["accent_hover"],
                command=lambda s=r["start"]: self._jump_to_time(s)
            ).grid(row=0, column=2, padx=2, pady=4)

            # Botão excluir
            ctk.CTkButton(
                card,
                text="✕",
                width=24,
                height=22,
                font=ctk.CTkFont(size=10, weight="bold"),
                fg_color="transparent",
                hover_color=COLORS["error"],
                text_color=COLORS["error"],
                command=lambda i=idx: self._delete_region_by_index(i)
            ).grid(row=0, column=3, padx=(2, 6), pady=4)

    def _clear_all_regions(self):
        self.regions.clear()
        self.selected_region_idx = None
        self._render_current_frame()
        self._update_region_panel()
        self._refresh_regions_list()

    def _on_save_and_apply(self):
        if self.on_confirm:
            self.on_confirm(self.regions, self.blur_strength)
        self.cap.release()
        self.destroy()

    def destroy(self):
        if self.cap and self.cap.isOpened():
            self.cap.release()
        super().destroy()
