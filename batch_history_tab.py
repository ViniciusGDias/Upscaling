"""
batch_history_tab.py - Central de Processamento em Lote (Batch) e Histórico de Análises.
Permite processar múltiplos vídeos em lote para YouTube Shorts e Instagram Reels,
exportar relatórios consolidados em CSV e navegar pelo histórico de análises salvas no cache
sem gastar tokens de IA.
"""

from __future__ import annotations
import os
import csv
import time
import json
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
import customtkinter as ctk
from tkinter import filedialog, messagebox

import icon_manager
import windows_notifier
from social_analyzer import COPY_TEMPLATES, analyze_yt_shorts_video, analyze_instagram_video

COLOR_BG_DARK = "#09090b"
COLOR_CARD = "#111113"
COLOR_CARD_BORDER = "#27272a"
COLOR_ACCENT = "#10b981"
COLOR_ACCENT_HOVER = "#059669"
COLOR_TEXT_MUTED = "#a1a1aa"
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


class BatchHistoryTab(ctk.CTkFrame):
    """
    Aba dedicada para Repurpose em Lote e Histórico de Inteligência Social.
    """

    def __init__(self, parent, main_app=None, log_callback: Optional[Callable[[str], None]] = None, **kwargs):
        super().__init__(parent, fg_color=COLOR_BG_DARK, **kwargs)
        self.main_app = main_app
        self.log_callback = log_callback

        self.selected_folder: str = ""
        self.found_videos: List[str] = []
        self.batch_results: List[Dict[str, Any]] = []
        self.is_batch_running: bool = False
        self._cancel_batch: bool = False

        self._build_ui()

    def _log(self, msg: str):
        if self.log_callback:
            self.log_callback(f"[Batch] {msg}")

    def _build_ui(self):
        # 1. Header Superior
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=16, pady=(14, 8))

        top_row = ctk.CTkFrame(header_frame, fg_color="transparent")
        top_row.pack(fill="x")

        ctk.CTkLabel(
            top_row,
            text=" Central Batch & Histórico de Análises",
            image=icon_manager.get_icon("layers", size=(22, 22), color="#10b981"),
            compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color="#fafafa"
        ).pack(side="left")

        # Seletor de Modo (Abas Internas)
        self.mode_switcher = ctk.CTkSegmentedButton(
            top_row,
            values=["Repurpose em Lote (Batch)", "Histórico de Análises & Cache"],
            font=ctk.CTkFont(size=12, weight="bold"),
            selected_color="#10b981",
            selected_hover_color="#059669",
            command=self._on_mode_switched
        )
        self.mode_switcher.pack(side="right")
        self.mode_switcher.set("Repurpose em Lote (Batch)")

        ctk.CTkLabel(
            header_frame,
            text="Processe pastas inteiras de vídeos gerando títulos, ganchos e SEO em fila ou pesquise conteúdos passados.",
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_MUTED
        ).pack(anchor="w", pady=(2, 0))

        # Divisor
        ctk.CTkFrame(self, fg_color=COLOR_CARD_BORDER, height=1).pack(fill="x", padx=16, pady=(6, 8))

        # Container Principal dos Modos
        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        # Constrói ambos os containers de modo
        self._build_batch_view()
        self._build_history_view()

        # Inicia no modo Batch
        self._show_batch_view()

    def _on_mode_switched(self, choice: str):
        if "Batch" in choice:
            self._show_batch_view()
        else:
            self._show_history_view()

    # ── MODO 1: BATCH REPURPOSE ──────────────────────────────────────────────

    def _build_batch_view(self):
        self.batch_frame = ctk.CTkFrame(self.container, fg_color="transparent")

        # Grid em 2 colunas: Controles e Fila (Esquerda) vs Resultados (Direita)
        self.batch_frame.grid_columnconfigure(0, weight=4, minsize=380)
        self.batch_frame.grid_columnconfigure(1, weight=6)
        self.batch_frame.grid_rowconfigure(0, weight=1)

        # ── Coluna Esquerda: Configurações do Lote ──
        left_box = ctk.CTkFrame(self.batch_frame, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
        left_box.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=0)

        ctk.CTkLabel(
            left_box,
            text="1. Seleção de Pasta com Vídeos",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#fafafa"
        ).pack(anchor="w", padx=14, pady=(12, 6))

        row_folder = ctk.CTkFrame(left_box, fg_color="transparent")
        row_folder.pack(fill="x", padx=14, pady=(0, 6))

        self.folder_entry = ctk.CTkEntry(row_folder, placeholder_text="Selecione a pasta dos cortes...", height=32)
        self.folder_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_select_folder = ctk.CTkButton(
            row_folder,
            text="Procurar Pasta",
            width=115,
            height=32,
            image=icon_manager.get_icon("folder", size=(13, 13)),
            compound="left",
            fg_color="#18181b",
            hover_color="#27272a",
            border_width=1,
            border_color="#3f3f46",
            command=self._choose_folder
        )
        self.btn_select_folder.pack(side="right")

        self.lbl_batch_scan = ctk.CTkLabel(
            left_box,
            text="Nenhuma pasta selecionada",
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_MUTED
        )
        self.lbl_batch_scan.pack(anchor="w", padx=14, pady=(0, 8))

        ctk.CTkFrame(left_box, fg_color=COLOR_CARD_BORDER, height=1).pack(fill="x", padx=14, pady=(2, 10))

        ctk.CTkLabel(
            left_box,
            text="2. Configurações de Análise do Lote",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#fafafa"
        ).pack(anchor="w", padx=14, pady=(0, 6))

        # Plataforma Alvo
        ctk.CTkLabel(left_box, text="Plataforma Alvo:", font=ctk.CTkFont(size=11, weight="bold"), text_color=COLOR_TEXT_MUTED).pack(anchor="w", padx=14, pady=(2, 2))
        self.seg_platform = ctk.CTkSegmentedButton(
            left_box,
            values=["YouTube Shorts", "Instagram Reels", "Ambos (Cross-Post)"],
            height=28
        )
        self.seg_platform.pack(fill="x", padx=14, pady=(0, 8))
        self.seg_platform.set("YouTube Shorts")

        # Categoria & Lore
        row_cfg = ctk.CTkFrame(left_box, fg_color="transparent")
        row_cfg.pack(fill="x", padx=14, pady=(0, 6))

        ctk.CTkLabel(row_cfg, text="Categoria:", font=ctk.CTkFont(size=11), width=70).pack(side="left")
        self.opt_batch_cat = ctk.CTkOptionMenu(row_cfg, values=["Anime", "Dorama", "Geral / Outros"], height=28)
        self.opt_batch_cat.pack(side="left", fill="x", expand=True, padx=(0, 6))

        # Idioma
        ctk.CTkLabel(left_box, text="Idioma de Saída:", font=ctk.CTkFont(size=11, weight="bold"), text_color=COLOR_TEXT_MUTED).pack(anchor="w", padx=14, pady=(2, 2))
        self.seg_batch_lang = ctk.CTkSegmentedButton(
            left_box,
            values=["Português (PT)", "English (EN)", "Español (ES)"],
            height=28
        )
        self.seg_batch_lang.pack(fill="x", padx=14, pady=(0, 8))
        self.seg_batch_lang.set("Português (PT)")

        # Template de Copywriting
        ctk.CTkLabel(left_box, text="Template de Copywriting:", font=ctk.CTkFont(size=11, weight="bold"), text_color=COLOR_TEXT_MUTED).pack(anchor="w", padx=14, pady=(2, 2))
        self.opt_batch_template = ctk.CTkOptionMenu(
            left_box,
            values=list(COPY_TEMPLATES.keys()),
            height=28
        )
        self.opt_batch_template.pack(fill="x", padx=14, pady=(0, 10))

        # Barra de Progresso e Ações
        self.progress_bar = ctk.CTkProgressBar(left_box, height=8, progress_color="#10b981")
        self.progress_bar.pack(fill="x", padx=14, pady=(10, 4))
        self.progress_bar.set(0)

        self.lbl_batch_status = ctk.CTkLabel(
            left_box,
            text="Pronto para iniciar o lote",
            font=ctk.CTkFont(size=11),
            text_color="#71717a"
        )
        self.lbl_batch_status.pack(anchor="w", padx=14, pady=(0, 8))

        row_actions = ctk.CTkFrame(left_box, fg_color="transparent")
        row_actions.pack(fill="x", padx=14, pady=(4, 12))

        self.btn_start_batch = ctk.CTkButton(
            row_actions,
            text="Iniciar Lote",
            image=icon_manager.get_icon("lightning", size=(14, 14), color="#09090b"),
            compound="left",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            text_color="#09090b",
            height=36,
            command=self._start_batch_processing
        )
        self.btn_start_batch.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_stop_batch = ctk.CTkButton(
            row_actions,
            text="Cancelar",
            font=ctk.CTkFont(size=12),
            fg_color="#18181b",
            hover_color="#27272a",
            text_color="#ef4444",
            border_width=1,
            border_color="#ef4444",
            height=36,
            width=80,
            command=self._cancel_batch_processing
        )
        self.btn_stop_batch.pack(side="right")
        self.btn_stop_batch.configure(state="disabled")

        # ── Coluna Direita: Resultados do Lote ──
        right_box = ctk.CTkFrame(self.batch_frame, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
        right_box.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=0)
        right_box.grid_columnconfigure(0, weight=1)
        right_box.grid_rowconfigure(1, weight=1)

        # Header da coluna de resultados
        res_header = ctk.CTkFrame(right_box, fg_color="transparent")
        res_header.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 6))

        ctk.CTkLabel(
            res_header,
            text="Resultados do Lote Processado:",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#fafafa"
        ).pack(side="left")

        self.btn_export_csv = ctk.CTkButton(
            res_header,
            text="Exportar Relatório CSV",
            image=icon_manager.get_icon("download", size=(13, 13), color="#10b981"),
            compound="left",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#18181b",
            hover_color="#27272a",
            border_width=1,
            border_color="#10b981",
            text_color="#10b981",
            height=28,
            command=self._export_batch_csv
        )
        self.btn_export_csv.pack(side="right")
        self.btn_export_csv.configure(state="disabled")

        # Scroll de resultados
        self.batch_results_scroll = ctk.CTkScrollableFrame(right_box, fg_color="transparent")
        self.batch_results_scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=(4, 10))

        self._render_batch_empty_state()

    def _render_batch_empty_state(self):
        for w in self.batch_results_scroll.winfo_children():
            w.destroy()

        ph = ctk.CTkFrame(self.batch_results_scroll, fg_color="transparent")
        ph.pack(expand=True, pady=80)

        ctk.CTkLabel(ph, text="", image=icon_manager.get_icon("layers", size=(40, 40), color="#3f3f46")).pack(pady=(0, 10))
        ctk.CTkLabel(ph, text="Nenhum lote processado ainda", font=ctk.CTkFont(size=14, weight="bold"), text_color="#fafafa").pack(pady=(0, 4))
        ctk.CTkLabel(
            ph,
            text="Selecione uma pasta com vídeos e clique em 'Iniciar Lote'\npara ver os títulos, scores e legendas de cada arquivo aqui.",
            font=ctk.CTkFont(size=11),
            text_color="#71717a",
            justify="center"
        ).pack()

    def _show_batch_view(self):
        if hasattr(self, "history_frame"):
            self.history_frame.pack_forget()
        self.batch_frame.pack(fill="both", expand=True)

    def _choose_folder(self):
        folder = filedialog.askdirectory(title="Selecione a pasta contendo os vídeos")
        if folder:
            self.selected_folder = folder
            self.folder_entry.delete(0, "end")
            self.folder_entry.insert(0, folder)

            # Escaneia vídeos
            self.found_videos = []
            for root, _, files in os.walk(folder):
                for f in files:
                    if Path(f).suffix.lower() in VIDEO_EXTS:
                        self.found_videos.append(os.path.join(root, f))

            count = len(self.found_videos)
            self.lbl_batch_scan.configure(
                text=f"{count} vídeos detectados na pasta prontos para o lote." if count > 0 else "Nenhum arquivo de vídeo encontrado na pasta selecionada.",
                text_color="#10b981" if count > 0 else "#f59e0b"
            )

    def _start_batch_processing(self):
        if not self.found_videos:
            messagebox.showwarning("Aviso", "Selecione uma pasta que contenha arquivos de vídeo.")
            return

        if self.is_batch_running:
            return

        self.is_batch_running = True
        self._cancel_batch = False
        self.batch_results = []
        self.btn_start_batch.configure(state="disabled")
        self.btn_stop_batch.configure(state="normal")
        self.btn_export_csv.configure(state="disabled")
        self.progress_bar.set(0)

        # Limpa scroll de resultados
        for w in self.batch_results_scroll.winfo_children():
            w.destroy()

        platform = self.seg_platform.get()
        category = self.opt_batch_cat.get().lower()
        lang_str = self.seg_batch_lang.get()
        lang = "en" if "EN" in lang_str else ("es" if "ES" in lang_str else "pt")
        tpl_name = self.opt_batch_template.get()
        tpl_context = COPY_TEMPLATES.get(tpl_name, "")

        def worker():
            total = len(self.found_videos)
            for idx, vid_path in enumerate(self.found_videos, 1):
                if self._cancel_batch:
                    self.after(0, lambda: self.lbl_batch_status.configure(text="Lote cancelado pelo usuário."))
                    break

                vid_name = os.path.basename(vid_path)
                progress = idx / total
                self.after(0, lambda i=idx, t=total, n=vid_name, p=progress: (
                    self.lbl_batch_status.configure(text=f"Processando {i}/{t}: {n}..."),
                    self.progress_bar.set(p)
                ))

                res_item = {
                    "video_path": vid_path,
                    "video_name": vid_name,
                    "platform": platform,
                    "language": lang,
                }

                try:
                    if "YouTube" in platform or "Ambos" in platform:
                        yt_res = analyze_yt_shorts_video(
                            vid_path,
                            category=category,
                            context=tpl_context,
                            language=lang,
                            on_log=self._log
                        )
                        res_item["yt_res"] = yt_res

                    if "Instagram" in platform or "Ambos" in platform:
                        insta_res = analyze_instagram_video(
                            vid_path,
                            context=tpl_context,
                            language=lang,
                            on_log=self._log
                        )
                        res_item["insta_res"] = insta_res

                    self.batch_results.append(res_item)
                    self.after(0, lambda r=res_item: self._append_batch_result_card(r))
                except Exception as e:
                    self._log(f"Erro ao processar {vid_name}: {e}")

            self.after(0, self._finish_batch_processing)

        threading.Thread(target=worker, daemon=True).start()

    def _cancel_batch_processing(self):
        self._cancel_batch = True
        self.lbl_batch_status.configure(text="Interrompendo lote...")

    def _finish_batch_processing(self):
        self.is_batch_running = False
        self.btn_start_batch.configure(state="normal")
        self.btn_stop_batch.configure(state="disabled")
        if self.batch_results:
            self.btn_export_csv.configure(state="normal")
            self.lbl_batch_status.configure(
                text=f"Concluído! {len(self.batch_results)} vídeos processados com sucesso.",
                text_color="#10b981"
            )
            # Notificação Toast Windows
            windows_notifier.show_toast(
                "Urahara Studio - Lote Concluído",
                f"O lote com {len(self.batch_results)} vídeos foi processado com sucesso!"
            )
        else:
            self.lbl_batch_status.configure(text="Nenhum resultado gerado.")

    def _append_batch_result_card(self, item: Dict[str, Any]):
        card = ctk.CTkFrame(self.batch_results_scroll, fg_color="#18181b", corner_radius=8, border_width=1, border_color="#27272a")
        card.pack(fill="x", padx=4, pady=4)

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=(8, 2))

        ctk.CTkLabel(
            header,
            text=item.get("video_name", "Vídeo"),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#fafafa"
        ).pack(side="left")

        # Resolve Título e Score
        yt = item.get("yt_res") or {}
        insta = item.get("insta_res") or {}

        title = ""
        score = 80
        if yt and "titles" in yt and yt["titles"]:
            title = yt["titles"][0].get("title", "")
            score = yt.get("optimization", {}).get("viral_score", 85)
        elif insta:
            score = insta.get("hook_analysis", {}).get("score", 85)
            caps = insta.get("suggested_captions", [])
            title = caps[0].get("caption", "").split("\n")[0][:60] if caps else "Reel"

        badge_color = "#10b981" if score >= 80 else "#f59e0b"
        ctk.CTkLabel(
            header,
            text=f"Score: {score}/100",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=badge_color
        ).pack(side="right")

        if title:
            ctk.CTkLabel(
                card,
                text=title,
                font=ctk.CTkFont(size=11),
                text_color="#fef08a",
                wraplength=420,
                justify="left"
            ).pack(anchor="w", padx=10, pady=(2, 6))

        # Botão rápido de copiar
        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=(0, 8))

        btn_copy = ctk.CTkButton(
            btn_row,
            text="Copiar Título / Legenda",
            height=24,
            font=ctk.CTkFont(size=10),
            fg_color="#27272a",
            hover_color="#3f3f46",
            command=lambda t=title: self._copy_text(t)
        )
        btn_copy.pack(side="left")

    def _copy_text(self, text: str):
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            messagebox.showinfo("Copiado", "Texto copiado para a área de transferência!")

    def _export_batch_csv(self):
        if not self.batch_results:
            return

        out_path = filedialog.asksaveasfilename(
            title="Salvar Relatório de Metadados em CSV",
            defaultextension=".csv",
            filetypes=[("CSV (Valores Separados por Vírgula)", "*.csv")],
            initialfile="relatorio_lote_urahara.csv"
        )
        if not out_path:
            return

        try:
            with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Arquivo", "Caminho Completo", "Score Viral",
                    "Título Shorts 1", "Título Shorts 2", "Título Shorts 3",
                    "Gancho Sugerido", "Tags SEO", "Primeira Linha Descrição",
                    "Legenda Completa", "Hashtags"
                ])

                for r in self.batch_results:
                    name = r.get("video_name", "")
                    path = r.get("video_path", "")
                    yt = r.get("yt_res") or {}
                    insta = r.get("insta_res") or {}

                    titles = [t.get("title", "") for t in yt.get("titles", [])]
                    t1 = titles[0] if len(titles) > 0 else ""
                    t2 = titles[1] if len(titles) > 1 else ""
                    t3 = titles[2] if len(titles) > 2 else ""

                    score = yt.get("optimization", {}).get("viral_score") or insta.get("hook_analysis", {}).get("score", "")
                    hook = yt.get("optimization", {}).get("suggested_hook") or insta.get("optimization", {}).get("suggested_hook", "")
                    tags = ", ".join(yt.get("tags", []))

                    desc = yt.get("descriptions", [{}])[0]
                    first_line = desc.get("first_line", "")
                    full_caption = desc.get("full_caption") or (insta.get("suggested_captions", [{}])[0].get("caption", ""))
                    hashtags = " ".join(insta.get("hashtags", []))

                    writer.writerow([name, path, score, t1, t2, t3, hook, tags, first_line, full_caption, hashtags])

            messagebox.showinfo("Exportado com Sucesso", f"Relatório CSV salvo em:\n{out_path}")
        except Exception as e:
            messagebox.showerror("Erro ao Exportar", f"Não foi possível salvar o CSV: {e}")

    # ── MODO 2: HISTÓRICO & CACHE ────────────────────────────────────────────

    def _build_history_view(self):
        self.history_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.history_frame.grid_columnconfigure(0, weight=1)
        self.history_frame.grid_rowconfigure(1, weight=1)

        # Barra Superior de Busca
        search_bar = ctk.CTkFrame(self.history_frame, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color=COLOR_CARD_BORDER)
        search_bar.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 8))

        ctk.CTkLabel(
            search_bar,
            text="",
            image=icon_manager.get_icon("search", size=(16, 16), color="#a1a1aa")
        ).pack(side="left", padx=(10, 6))

        self.search_entry = ctk.CTkEntry(
            search_bar,
            placeholder_text="Buscar análises por nome do vídeo, anime ou título salvo...",
            height=34,
            border_width=0,
            fg_color="transparent",
            font=ctk.CTkFont(size=12)
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.search_entry.bind("<KeyRelease>", lambda e: self._filter_history())

        self.lbl_history_count = ctk.CTkLabel(search_bar, text="0 análises", font=ctk.CTkFont(size=11), text_color=COLOR_TEXT_MUTED)
        self.lbl_history_count.pack(side="right", padx=10)

        self.btn_refresh_history = ctk.CTkButton(
            search_bar,
            text="Atualizar",
            width=80,
            height=28,
            image=icon_manager.get_icon("refresh", size=(12, 12)),
            compound="left",
            font=ctk.CTkFont(size=11),
            fg_color="#18181b",
            hover_color="#27272a",
            command=self._load_history_entries
        )
        self.btn_refresh_history.pack(side="right", padx=(0, 6))

        # Scroll de Itens do Histórico
        self.history_scroll = ctk.CTkScrollableFrame(self.history_frame, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
        self.history_scroll.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self.history_scroll.grid_columnconfigure(0, weight=1)

    def _show_history_view(self):
        if hasattr(self, "batch_frame"):
            self.batch_frame.pack_forget()
        self.history_frame.pack(fill="both", expand=True)
        self._load_history_entries()

    def _load_history_entries(self):
        try:
            from ai_cache_hub import ai_cache
            self._cached_entries = ai_cache.list_all_entries() if ai_cache else []
        except Exception:
            self._cached_entries = []

        self._render_history_list(self._cached_entries)

    def _filter_history(self):
        query = self.search_entry.get().strip().lower()
        if not query:
            self._render_history_list(self._cached_entries)
            return

        filtered = []
        for e in self._cached_entries:
            v_name = e.get("video_name", "").lower()
            v_path = e.get("video_path", "").lower()
            title = ""
            if e.get("yt_data") and "titles" in e["yt_data"]:
                titles = e["yt_data"]["titles"]
                if titles and isinstance(titles, list):
                    title = str(titles[0].get("title", "")).lower()

            if query in v_name or query in v_path or query in title:
                filtered.append(e)

        self._render_history_list(filtered)

    def _render_history_list(self, entries: List[Dict[str, Any]]):
        for w in self.history_scroll.winfo_children():
            w.destroy()

        count = len(entries)
        self.lbl_history_count.configure(text=f"{count} {'análise' if count == 1 else 'análises'}")

        if not entries:
            ph = ctk.CTkFrame(self.history_scroll, fg_color="transparent")
            ph.pack(expand=True, pady=80)
            ctk.CTkLabel(ph, text="", image=icon_manager.get_icon("search", size=(36, 36), color="#3f3f46")).pack(pady=(0, 8))
            ctk.CTkLabel(ph, text="Nenhuma análise salva no histórico", font=ctk.CTkFont(size=13, weight="bold"), text_color="#fafafa").pack()
            return

        for e in entries:
            self._create_history_card(e)

    def _create_history_card(self, entry: Dict[str, Any]):
        card = ctk.CTkFrame(self.history_scroll, fg_color="#18181b", corner_radius=8, border_width=1, border_color="#27272a")
        card.pack(fill="x", padx=6, pady=4)

        top_row = ctk.CTkFrame(card, fg_color="transparent")
        top_row.pack(fill="x", padx=12, pady=(10, 4))

        v_name = entry.get("video_name") or "Vídeo Sem Nome"
        ctk.CTkLabel(
            top_row,
            text=v_name,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#fafafa"
        ).pack(side="left")

        # Badges de Plataforma
        badges_frame = ctk.CTkFrame(top_row, fg_color="transparent")
        badges_frame.pack(side="right")

        if entry.get("has_youtube"):
            ctk.CTkLabel(
                badges_frame,
                text="YouTube Shorts",
                font=ctk.CTkFont(size=10, weight="bold"),
                fg_color="#ef4444",
                text_color="#ffffff",
                corner_radius=4
            ).pack(side="left", padx=3)

        if entry.get("has_instagram"):
            ctk.CTkLabel(
                badges_frame,
                text="Instagram Reels",
                font=ctk.CTkFont(size=10, weight="bold"),
                fg_color="#8b5cf6",
                text_color="#ffffff",
                corner_radius=4
            ).pack(side="left", padx=3)

        # Conteúdo do card
        yt = entry.get("yt_data") or {}
        first_title = ""
        score = None
        if yt and "titles" in yt and yt["titles"]:
            first_title = yt["titles"][0].get("title", "")
            score = yt.get("optimization", {}).get("viral_score")

        if first_title:
            ctk.CTkLabel(
                card,
                text=f'"{first_title}"',
                font=ctk.CTkFont(size=11),
                text_color="#fef08a",
                wraplength=520,
                justify="left"
            ).pack(anchor="w", padx=12, pady=(0, 6))

        # Rodapé de Ações
        b_row = ctk.CTkFrame(card, fg_color="transparent")
        b_row.pack(fill="x", padx=12, pady=(2, 10))

        if score is not None:
            ctk.CTkLabel(
                b_row,
                text=f"Score Viral: {score}/100",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#10b981" if score >= 80 else "#f59e0b"
            ).pack(side="left")

        # Botões de Carregar nas Abas
        if entry.get("has_youtube") and self.main_app and hasattr(self.main_app, "shorts_tab"):
            ctk.CTkButton(
                b_row,
                text="Abrir no YouTube Shorts",
                height=26,
                font=ctk.CTkFont(size=10),
                fg_color="#27272a",
                hover_color="#3f3f46",
                command=lambda e=entry: self._load_into_yt_tab(e)
            ).pack(side="right", padx=(4, 0))

        if entry.get("has_instagram") and self.main_app and hasattr(self.main_app, "insta_tab"):
            ctk.CTkButton(
                b_row,
                text="Abrir no Instagram",
                height=26,
                font=ctk.CTkFont(size=10),
                fg_color="#27272a",
                hover_color="#3f3f46",
                command=lambda e=entry: self._load_into_insta_tab(e)
            ).pack(side="right", padx=(4, 0))

    def _load_into_yt_tab(self, entry: Dict[str, Any]):
        v_path = entry.get("video_path") or ""
        yt_data = entry.get("yt_data") or {}
        if self.main_app and hasattr(self.main_app, "shorts_tab") and yt_data:
            tab = self.main_app.shorts_tab
            if v_path and os.path.exists(v_path):
                tab.file_entry.delete(0, "end")
                tab.file_entry.insert(0, v_path)
                tab.video_path = v_path
            tab._render_results(yt_data)
            if hasattr(self.main_app, "tabview"):
                self.main_app.tabview.set("YouTube Shorts")

    def _load_into_insta_tab(self, entry: Dict[str, Any]):
        v_path = entry.get("video_path") or ""
        insta_data = entry.get("insta_data") or {}
        if self.main_app and hasattr(self.main_app, "insta_tab") and insta_data:
            tab = self.main_app.insta_tab
            if v_path and os.path.exists(v_path):
                tab.file_entry.delete(0, "end")
                tab.file_entry.insert(0, v_path)
                tab.video_path = v_path
            tab.analysis_data = insta_data
            tab._render_results(insta_data)
            if hasattr(self.main_app, "tabview"):
                self.main_app.tabview.set("Instagram Shorts")
