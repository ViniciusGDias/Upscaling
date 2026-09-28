"""
Aba Analisar Instagram para CustomTkinter.
Análise estética, retenção, compartilhamento (DM), salvamentos, legendas completas e hashtags.
"""

import os
import shutil
import subprocess
import threading
from pathlib import Path
from PIL import Image
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
import icon_manager
def _copy_text_to_clipboard(widget, text: str):
    try:
        import pyperclip
        pyperclip.copy(text)
    except Exception:
        widget.clipboard_clear()
        widget.clipboard_append(text)
        widget.update()

from social_analyzer import analyze_instagram_video, get_video_info_fast, COPY_TEMPLATES
from video_preview_player import VideoPreviewPlayer
import windows_notifier

COLOR_BG_DARK = "#09090b"
COLOR_CARD = "#111113"
COLOR_CARD_BORDER = "#27272a"
COLOR_ACCENT = "#e2e8f0"       # off-white — principal action
COLOR_ACCENT_HOVER = "#a1a1aa" # muted silver
COLOR_TEXT_MUTED = "#a1a1aa"   # zinc-400 — high contrast
COLOR_BTN_COPY = "#18181b"     # dark ghost button
COLOR_BTN_COPY_BORDER = "#3f3f46"
COLOR_SUCCESS = "#22c55e"


class InstagramAnalyzerTab(ctk.CTkFrame):
    def __init__(self, master, log_callback=None, main_app=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.log_callback = log_callback
        self.main_app = main_app
        self.video_path = ""
        self.analysis_data = None
        self.is_analyzing = False

        self._build_ui()

    def _log(self, msg: str):
        if self.log_callback:
            self.log_callback(f"[Instagram] {msg}")
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", msg + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def _build_ui(self):
        # Layout dividido em 2 colunas principais: Esquerda (Config / Input), Direita (Resultados / Copy cards)
        self.grid_columnconfigure(0, weight=4)
        self.grid_columnconfigure(1, weight=6)
        self.grid_rowconfigure(0, weight=1)

        # ── Coluna Esquerda: Controles Scrolláveis ──
        left_frame = ctk.CTkScrollableFrame(self, fg_color=COLOR_BG_DARK, corner_radius=8, border_width=1, border_color=COLOR_CARD_BORDER)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(5, 5), pady=5)

        # Cabeçalho
        header_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=(15, 10))
        ctk.CTkLabel(
            header_frame,
            text=" Analisar Instagram Reels",
            image=icon_manager.get_icon("instagram", size=(20, 20), color="#10b981"), compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color="#fafafa"
        ).pack(anchor="w")
        ctk.CTkLabel(
            header_frame,
            text="Estética · Gancho 0-2s · Compartilhamentos DM · Salvamentos · Legendas virais",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLOR_TEXT_MUTED,
            wraplength=380,
            justify="left"
        ).pack(anchor="w", pady=(2, 0))

        ctk.CTkFrame(left_frame, fg_color=COLOR_CARD_BORDER, height=1).pack(fill="x", padx=15, pady=(8, 0))

        # Seleção de Vídeo
        file_box = ctk.CTkFrame(left_frame, fg_color="transparent")
        file_box.pack(fill="x", padx=15, pady=(12, 0))

        ctk.CTkLabel(file_box, text="Vídeo para Análise", font=ctk.CTkFont(size=11, weight="bold"), text_color="#71717a").pack(anchor="w", pady=(0, 4))
        
        row_pick = ctk.CTkFrame(file_box, fg_color="transparent")
        row_pick.pack(fill="x", pady=(0, 4))
        
        self.file_entry = ctk.CTkEntry(
            row_pick,
            placeholder_text="Selecione um arquivo de vídeo...",
            height=34, corner_radius=6,
            fg_color="#111113", border_color="#27272a", border_width=1,
            text_color="#fafafa", font=ctk.CTkFont(size=12)
        )
        self.file_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        
        self.btn_browse = ctk.CTkButton(
            row_pick, text="Procurar", width=95, height=34,
            image=icon_manager.get_icon("folder", size=(14, 14)), compound="left",
            fg_color="#18181b", hover_color="#27272a",
            border_width=1, border_color="#3f3f46",
            text_color="#e2e8f0", font=ctk.CTkFont(size=11),
            corner_radius=6,
            command=self._choose_video
        )
        self.btn_browse.pack(side="right")

        self.lbl_video_info = ctk.CTkLabel(file_box, text="Nenhum vídeo selecionado", font=ctk.CTkFont(size=11), text_color="#a1a1aa")
        self.lbl_video_info.pack(anchor="w", pady=(0, 4))

        # Linha de Cache Inteligente e Botão de Limpeza
        row_cache = ctk.CTkFrame(file_box, fg_color="transparent")
        row_cache.pack(fill="x", pady=(2, 4))

        self.cache_status_badge = ctk.CTkLabel(
            row_cache,
            text="[CACHE: NENHUM]",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#71717a",
            anchor="w"
        )
        self.cache_status_badge.pack(side="left")

        self.btn_clear_cache = ctk.CTkButton(
            row_cache,
            text="Limpar Cache do Vídeo",
            image=icon_manager.get_icon("trash", size=(12, 12), color="#f59e0b"), compound="left",
            height=26,
            width=140,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#18181b",
            hover_color="#27272a",
            border_width=1,
            border_color="#f59e0b",
            text_color="#f59e0b",
            command=self._clear_cache_for_video
        )
        self.btn_clear_cache.pack(side="right")

        # Mini-Player Embutido para Prévia
        self.preview_player = VideoPreviewPlayer(file_box, max_width=320, max_height=180)
        self.preview_player.pack(fill="x", pady=(0, 6))

        # ── AÇÃO RÁPIDA: Capa / Thumbnail do Reels (1080x1920) ──
        thumb_btn_frame = ctk.CTkFrame(left_frame, fg_color="#181308", corner_radius=8, border_width=1, border_color="#f59e0b")
        thumb_btn_frame.pack(fill="x", padx=15, pady=(4, 6))

        tb_top = ctk.CTkFrame(thumb_btn_frame, fg_color="transparent")
        tb_top.pack(fill="x", padx=10, pady=(6, 2))

        ctk.CTkLabel(
            tb_top, text="📸 Gerador de Capa Reels (1080x1920):",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#fbbf24"
        ).pack(side="left")

        tb_row = ctk.CTkFrame(thumb_btn_frame, fg_color="transparent")
        tb_row.pack(fill="x", padx=10, pady=(0, 6))

        ctk.CTkLabel(tb_row, text="Frame no segundo:", font=ctk.CTkFont(size=11), text_color="#d4d4d8").pack(side="left")

        self.thumb_time_entry = ctk.CTkEntry(tb_row, width=54, height=28, font=ctk.CTkFont(size=11), justify="center")
        self.thumb_time_entry.insert(0, "1.5s")
        self.thumb_time_entry.pack(side="left", padx=(6, 8))

        self.btn_extract_thumb = ctk.CTkButton(
            tb_row, text="Gerar Capa", width=115, height=28,
            image=icon_manager.get_icon("image", size=(14, 14), color="#09090b"), compound="left",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#f59e0b", hover_color="#d97706", text_color="#09090b",
            command=self._on_quick_extract_thumb
        )
        self.btn_extract_thumb.pack(side="left")

        # ── Botão de Ação Principal: Analisar para Instagram ──
        self.btn_analyze = ctk.CTkButton(
            left_frame,
            text="Analisar para Instagram Reels",
            image=icon_manager.get_icon("sparkle", size=(16, 16), color="#09090b"), compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            height=40,
            fg_color="#10b981",
            hover_color="#059669",
            text_color="#09090b",
            corner_radius=6,
            command=self._start_analysis
        )
        self.btn_analyze.pack(fill="x", padx=15, pady=(4, 8))

        # Obra / Anime / Dorama (Opcional - busca via API)
        work_box = ctk.CTkFrame(left_frame, fg_color="transparent")
        work_box.pack(fill="x", padx=15, pady=(10, 0))

        row_work_lbl = ctk.CTkFrame(work_box, fg_color="transparent")
        row_work_lbl.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            row_work_lbl, text="Nome do Anime / Dorama (Opcional):",
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#a1a1aa"
        ).pack(side="left")
        ctk.CTkLabel(
            row_work_lbl, text="Lore via API",
            font=ctk.CTkFont(size=9, weight="bold"), text_color="#10b981"
        ).pack(side="right")

        self.ent_work_name = ctk.CTkEntry(
            work_box,
            placeholder_text="Ex: Dandadan, Jujutsu Kaisen, Queen of Tears...",
            height=32, corner_radius=6,
            fg_color="#111113", border_color="#27272a", border_width=1,
            text_color="#fafafa", font=ctk.CTkFont(size=11)
        )
        self.ent_work_name.pack(fill="x")

        # Contexto do Criador com Templates
        ctx_box = ctk.CTkFrame(left_frame, fg_color="transparent")
        ctx_box.pack(fill="x", padx=15, pady=(10, 0))

        row_tpl = ctk.CTkFrame(ctx_box, fg_color="transparent")
        row_tpl.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            row_tpl, text="Template de Copy:",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=COLOR_TEXT_MUTED
        ).pack(side="left")
        self.opt_template = ctk.CTkOptionMenu(
            row_tpl,
            values=list(COPY_TEMPLATES.keys()),
            height=26,
            font=ctk.CTkFont(size=11),
            command=self._on_template_selected
        )
        self.opt_template.pack(side="right", fill="x", expand=True, padx=(8, 0))

        self.txt_context = ctk.CTkTextbox(
            ctx_box, height=55, font=ctk.CTkFont(size=11),
            fg_color="#111113", border_color="#27272a", border_width=1,
            text_color="#d4d4d8"
        )
        self.txt_context.pack(fill="x")
        self.txt_context.insert("1.0", "Ex: anime edit do Gojo, público jovem/otaku.")

        # Pílulas de Contexto Rápido
        chips_frame = ctk.CTkFrame(ctx_box, fg_color="transparent")
        chips_frame.pack(fill="x", pady=(4, 0))

        quick_chips = [
            ("🔥 Luta/Clímax", "foco em luta épica, ação frenética e clímax"),
            ("😂 Comédia", "foco em humor, meme, cena engraçada e descontraída"),
            ("🤫 Mistério", "foco em mistério, revelação chocante e suspense"),
            ("💔 Emocional", "foco em cena triste, despedida e arcos dramáticos"),
            ("⚡ Plot Twist", "foco em reviravolta insana e quebra de expectativa")
        ]
        for label, val in quick_chips:
            btn_chip = ctk.CTkButton(
                chips_frame,
                text=label,
                height=22,
                font=ctk.CTkFont(size=10),
                fg_color="#18181b",
                hover_color="#27272a",
                border_width=1,
                border_color="#3f3f46",
                text_color="#e4e4e7",
                corner_radius=11,
                command=lambda v=val: self._append_context_chip(v)
            )
            btn_chip.pack(side="left", padx=(0, 3), pady=2)

        # Opções extras
        opt_row = ctk.CTkFrame(left_frame, fg_color="transparent")
        opt_row.pack(fill="x", padx=15, pady=(8, 0))
        
        ctk.CTkLabel(opt_row, text="Idioma:", font=ctk.CTkFont(size=11, weight="bold"), text_color=COLOR_TEXT_MUTED).pack(side="left", padx=(0, 4))
        self.seg_lang = ctk.CTkSegmentedButton(
            opt_row,
            values=["PT", "EN", "ES"],
            height=26
        )
        self.seg_lang.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.seg_lang.set("PT")

        self.chk_force_refresh = ctk.CTkCheckBox(
            opt_row,
            text="Forçar Nova Análise (Ignorar Cache)",
            font=ctk.CTkFont(size=11),
            text_color="#f59e0b",
            border_color="#f59e0b",
            fg_color="#f59e0b",
            checkmark_color="#09090b"
        )
        self.chk_force_refresh.pack(side="right", pady=4)



        # Log
        ctk.CTkLabel(left_frame, text="Log", font=ctk.CTkFont(size=10, weight="bold"), text_color="#3f3f46").pack(anchor="w", padx=15, pady=(4, 2))
        self.log_textbox = ctk.CTkTextbox(
            left_frame, height=120,
            font=ctk.CTkFont(family="Consolas", size=10),
            fg_color="#050505", text_color="#52525b",
            border_color="#27272a", border_width=1
        )
        self.log_textbox.pack(fill="both", expand=True, padx=15, pady=(0, 12))
        self.log_textbox.configure(state="disabled")

        # ── Coluna Direita: Resultados Scrolláveis ──
        self.right_scroll = ctk.CTkScrollableFrame(self, fg_color=COLOR_BG_DARK, corner_radius=8, border_width=1, border_color=COLOR_CARD_BORDER)
        self.right_scroll.grid(row=0, column=1, sticky="nsew", padx=(5, 5), pady=5)
        self.right_scroll.grid_columnconfigure(0, weight=1)

        self.placeholder_frame = ctk.CTkFrame(self.right_scroll, fg_color="transparent")
        self.placeholder_frame.pack(expand=True, pady=110)

        ctk.CTkLabel(
            self.placeholder_frame,
            text="",
            image=icon_manager.get_icon("instagram", size=(48, 48), color="#3f3f46")
        ).pack(pady=(0, 14))

        ctk.CTkLabel(
            self.placeholder_frame,
            text="Central de Inteligência & Capas Instagram Reels",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            text_color="#fafafa"
        ).pack(pady=(0, 6))

        ctk.CTkLabel(
            self.placeholder_frame,
            text="Selecione um corte de vídeo para extrair a Capa 1080x1920 imediatamente\nou clique em 'Analisar para Instagram' para ganchos virais, copies e hashtags.",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color="#a1a1aa",
            justify="center"
        ).pack()

    def _update_cache_badge(self, path: str = ""):
        path = path or self.file_entry.get().strip()
        if not path or not os.path.exists(path):
            self.cache_status_badge.configure(text="[CACHE: NENHUM]", text_color="#71717a")
            return

        try:
            from ai_cache_hub import ai_cache
            has_cache = ai_cache.has(path, "instagram_analysis")
            if has_cache:
                self.cache_status_badge.configure(text="[⚡ CACHE SALVO (24h)]", text_color="#10b981")
            else:
                self.cache_status_badge.configure(text="[CACHE: VAZIO]", text_color="#71717a")
        except Exception:
            self.cache_status_badge.configure(text="[CACHE: N/A]", text_color="#71717a")

    def _clear_cache_for_video(self):
        path = self.file_entry.get().strip()
        if not path:
            self._log("[AVISO] Selecione um vídeo para limpar o cache.")
            return

        try:
            from ai_cache_hub import ai_cache
            ai_cache.invalidate(path, "instagram_analysis")
            ai_cache.invalidate(path, "viral_metadata")
            self._update_cache_badge(path)
            self._log(f"🧹 [Cache] Cache de Instagram limpo com sucesso para: {os.path.basename(path)}")
        except Exception as e:
            self._log(f"[ERRO] Falha ao limpar cache: {e}")

    def _clear_cache_and_reanalyze(self):
        self._clear_cache_for_video()
        self._start_analysis(force_refresh=True)

    def _on_template_selected(self, choice: str):
        tpl_txt = COPY_TEMPLATES.get(choice, "")
        if tpl_txt:
            self.txt_context.delete("1.0", "end")
            self.txt_context.insert("1.0", tpl_txt)
            self._log(f"Template '{choice}' carregado.")

    def _choose_video(self):
        path = filedialog.askopenfilename(
            title="Selecione um vídeo para análise",
            filetypes=[("Vídeos", "*.mp4 *.mov *.mkv *.webm *.avi *.m4v"), ("Todos os arquivos", "*.*")]
        )
        if path:
            self.video_path = path
            self.file_entry.delete(0, "end")
            self.file_entry.insert(0, path)
            info = get_video_info_fast(path)
            self.lbl_video_info.configure(
                text=f"Resolução: {info['resolution']} | Duração: {info['duration_str']} | Áudio: {'Sim' if info['has_audio'] else 'Não'}"
            )
            self._update_cache_badge(path)
            if hasattr(self, "preview_player"):
                self.preview_player.load_video(path)
            self._log(f"Vídeo carregado: {path} ({info['resolution']}, {info['duration_str']})")

    def _start_analysis(self, force_refresh: bool = False):
        path = self.file_entry.get().strip()
        if not path:
            self._log("[ERRO]: Selecione um arquivo de vídeo primeiro.")
            return
        if self.is_analyzing:
            return

        force = force_refresh or bool(self.chk_force_refresh.get())
        if force:
            self._log("🔄 Forçando nova análise (ignorando cache salvo)...")

        self.is_analyzing = True
        self.btn_analyze.configure(state="disabled", text="Analisando Vídeo...")
        self._show_loading_state()
        work_name = self.ent_work_name.get().strip() if hasattr(self, 'ent_work_name') else ""
        context = self.txt_context.get("1.0", "end").strip()
        if context == "Ex: anime edit do Gojo, público jovem/otaku.":
            context = ""
        lang_str = self.seg_lang.get() if hasattr(self, "seg_lang") else "PT"
        lang = "en" if "EN" in lang_str else ("es" if "ES" in lang_str else "pt")
        language_en = (lang == "en")

        def worker():
            try:
                res = analyze_instagram_video(
                    path,
                    context=context,
                    work_name=work_name,
                    language_en=language_en,
                    language=lang,
                    force_refresh=force,
                    on_log=self._log,
                    log_cb=self._log
                )
                self.after(0, lambda: self._render_results(res))
                self.after(0, lambda: self._update_cache_badge(path))
            except Exception as e:
                err_msg = str(e)
                self._log(f"[ERRO] Erro na análise: {err_msg}")
                self.after(0, lambda: self._render_error_card(
                    error_msg=err_msg,
                    raw_response=(
                        f"Falha de conexão ou processamento com a IA:\n{err_msg}\n\n"
                        f"Possíveis causas:\n"
                        f"• Rate Limit (429) do Gemini ou instabilidade no provedor.\n"
                        f"• Conexão oscilando durante a chamada de API.\n"
                        f"• Resposta incompleta do modelo.\n\n"
                        f"Clique abaixo para limpar o cache e tentar novamente."
                    )
                ))
            finally:
                self.after(0, self._finish_analysis)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_analysis(self):
        self.is_analyzing = False
        self.btn_analyze.configure(state="normal", text="Analisar Vídeo para Instagram")
        vid_name = os.path.basename(self.file_entry.get().strip() or "Vídeo")
        windows_notifier.show_toast(
            "Urahara Studio - Instagram Reels Concluído",
            f"Análise de Reels concluída para: {vid_name}"
        )

    def _copy_to_clipboard(self, text: str, btn: ctk.CTkButton, original_text: str = "Copiar"):
        _copy_text_to_clipboard(self, text)
        btn.configure(
            text="Copiado!",
            image=icon_manager.get_icon("check", size=(12, 12), color="#ffffff"),
            fg_color="#10b981"
        )
        self.after(1800, lambda: btn.configure(
            text=original_text,
            image=icon_manager.get_icon("copy", size=(12, 12), color="#ffffff"),
            fg_color="#16a34a"
        ))

    def _append_context_chip(self, chip_text: str):
        curr = self.txt_context.get("1.0", "end").strip()
        if curr.startswith("Ex: anime edit"):
            self.txt_context.delete("1.0", "end")
            self.txt_context.insert("1.0", chip_text)
        elif chip_text not in curr:
            if curr:
                self.txt_context.insert("end", f", {chip_text}")
            else:
                self.txt_context.insert("1.0", chip_text)

    def _open_file(self, path: str):
        if path and os.path.exists(path):
            try:
                os.startfile(path)
            except Exception:
                pass

    def _reveal_in_folder(self, path: str):
        if path and os.path.exists(path):
            try:
                import subprocess
                subprocess.run(["explorer", "/select,", os.path.normpath(path)])
            except Exception:
                pass

    def _repurpose_to_yt_shorts(self, data: dict):
        try:
            from social_analyzer import adapt_instagram_to_yt
            from tkinter import messagebox
            adapted = adapt_instagram_to_yt(data)
            if self.main_app and hasattr(self.main_app, "shorts_tab"):
                self.main_app.shorts_tab.file_entry.delete(0, "end")
                self.main_app.shorts_tab.file_entry.insert(0, self.video_path)
                self.main_app.shorts_tab.analysis_data = adapted
                self.main_app.shorts_tab._render_results(adapted)
                if hasattr(self.main_app, "tabview"):
                    self.main_app.tabview.set("YouTube Shorts")
                self._log("✓ Conteúdo adaptado e transferido para a aba YouTube Shorts!")
            else:
                first_title = adapted.get("titles", [{}])[0].get("title", "")
                self.clipboard_clear()
                self.clipboard_append(first_title)
                messagebox.showinfo("Copiado para YouTube", "Título otimizado para o YouTube Shorts copiado para a área de transferência!")
        except Exception as e:
            self._log(f"Erro ao adaptar para YouTube Shorts: {e}")

    def _show_loading_state(self):
        """Exibe card de carregamento com animação enquanto a IA processa o vídeo."""
        for w in self.right_scroll.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

        card = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color="#e1306c")
        card.pack(fill="x", padx=12, pady=40)

        ctk.CTkLabel(
            card,
            text="",
            image=icon_manager.get_icon("sparkle", size=(36, 36), color="#f472b6")
        ).pack(pady=(24, 10))

        ctk.CTkLabel(
            card,
            text="IA Analisando Vídeo para Instagram Reels...",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color="#ffffff"
        ).pack(pady=(0, 6))

        ctk.CTkLabel(
            card,
            text="Avaliando ganchos 0-3s, gerando legendas completas com storytelling,\nhashtags estratégicas e thumbnail vertical 9:16...",
            font=ctk.CTkFont(size=12),
            text_color="#a1a1aa",
            justify="center"
        ).pack(pady=(0, 16))

        self.analysis_pbar = ctk.CTkProgressBar(card, mode="indeterminate", height=6, progress_color="#e1306c")
        self.analysis_pbar.pack(fill="x", padx=36, pady=(0, 12))
        self.analysis_pbar.start()

        ctk.CTkLabel(
            card,
            text="Tempo estimado: 10 a 25 segundos • Gemini 2.5 / 3.0",
            font=ctk.CTkFont(family="Consolas", size=10),
            text_color="#71717a"
        ).pack(pady=(0, 20))

    def _render_error_card(self, error_msg: str, raw_response: str = ""):
        """Renderiza card de erro seguro com botões de recuperação para nunca deixar a tela preta."""
        for w in self.right_scroll.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

        err_box = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color="#ef4444")
        err_box.pack(fill="x", padx=10, pady=20)

        ctk.CTkLabel(
            err_box,
            text="⚠️ Falha na Análise de IA ou Comunicação com Servidor",
            text_color="#ef4444",
            font=ctk.CTkFont(weight="bold", size=14)
        ).pack(pady=(16, 6), padx=14)

        ctk.CTkLabel(
            err_box,
            text="Não foi possível obter ou processar os dados gerados pela IA no momento.\nO cache problemático foi limpo automaticamente.",
            font=ctk.CTkFont(size=12),
            text_color="#d4d4d8",
            justify="center"
        ).pack(pady=(0, 14), padx=14)

        btn_retry_row = ctk.CTkFrame(err_box, fg_color="transparent")
        btn_retry_row.pack(pady=(0, 14))

        ctk.CTkButton(
            btn_retry_row,
            text="🔄 Limpar Cache & Gerar Novamente",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#ef4444",
            hover_color="#dc2626",
            height=34,
            command=self._clear_cache_and_reanalyze
        ).pack(side="left", padx=6)

        ctk.CTkButton(
            btn_retry_row,
            text="🧹 Limpar Cache Apenas",
            font=ctk.CTkFont(size=12),
            fg_color="#27272a",
            hover_color="#3f3f46",
            height=34,
            command=self._clear_cache_for_video
        ).pack(side="left", padx=6)

        raw = raw_response or error_msg or "Sem detalhes técnicos."
        tb = ctk.CTkTextbox(err_box, height=140, font=ctk.CTkFont(family="Consolas", size=11))
        tb.pack(fill="x", padx=14, pady=(0, 14))
        tb.insert("1.0", raw)
        tb.configure(state="disabled")

    def _render_results(self, data: dict):
        for w in self.right_scroll.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

        if not data or ("video_analysis" not in data and "optimization" not in data and "suggested_captions" not in data) or data.get("parse_error"):
            raw = str(data.get("raw_response", data) if data else "Resposta vazia da API")
            err_msg = data.get("error_msg", "Formato de resposta incompleto ou truncado") if isinstance(data, dict) else str(data)
            self._render_error_card(err_msg, raw_response=raw)
            return

        try:
            self._render_results_content(data)
        except Exception as e:
            self._log(f"[ERRO] Erro ao renderizar resultados: {e}")
            self._render_error_card(f"Erro visual ao montar interface: {e}")

    def _render_results_content(self, data: dict):
        # ── Card de Capa de Alto CTR (1080x1920) ──
        thumb_path = data.get("_thumbnail_path")
        if not thumb_path or not os.path.exists(thumb_path):
            vid_p = self.file_entry.get().strip() or getattr(self, "video_path", "")
            if vid_p and os.path.exists(vid_p):
                from social_analyzer import extract_hook_thumbnail
                from upscaler import find_ffmpeg
                ff = find_ffmpeg() or "ffmpeg"
                first_t = data.get("title") or data.get("hook_text") or ""
                thumb_path = extract_hook_thumbnail(vid_p, ffmpeg_bin=ff, overlay_text=first_t)
                data["_thumbnail_path"] = thumb_path
                data["_thumbnail_text"] = first_t

        if thumb_path and os.path.exists(thumb_path):
            self._render_thumbnail_card(
                thumb_path,
                timestamp_sec=float(data.get("_thumbnail_sec", 1.5)),
                overlay_text=data.get("_thumbnail_text", "")
            )

        # ── Card de Sincronização Cruzada (Postar no YouTube Shorts) ──
        repurpose_card = ctk.CTkFrame(self.right_scroll, fg_color="#450a0a", corner_radius=10, border_width=1, border_color="#ef4444")
        repurpose_card.pack(fill="x", padx=5, pady=(0, 8))

        r_row = ctk.CTkFrame(repurpose_card, fg_color="transparent")
        r_row.pack(fill="x", padx=12, pady=8)

        ctk.CTkLabel(
            r_row,
            text="🔄 Cross-Post: Quer postar este mesmo corte no YouTube Shorts?",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#fecaca"
        ).pack(side="left")

        ctk.CTkButton(
            r_row, text="Adaptar p/ YouTube Shorts", width=185, height=26,
            image=icon_manager.get_icon("youtube", size=(14, 14), color="#ffffff"), compound="left",
            font=ctk.CTkFont(size=11, weight="bold"), fg_color="#dc2626", hover_color="#b91c1c",
            command=lambda: self._repurpose_to_yt_shorts(data)
        ).pack(side="right")

        # ── Badge de API Lore integrada ──
        if data.get("_enriched_context"):
            api_badge = ctk.CTkFrame(self.right_scroll, fg_color="#18181b", corner_radius=8, border_width=1, border_color="#22c55e")
            api_badge.pack(fill="x", padx=5, pady=(0, 8))
            ctk.CTkLabel(
                api_badge,
                text="Metadados & Lore Integrados via API Oficial (Kitsu / MyAnimeList / TVMaze)",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#22c55e"
            ).pack(anchor="w", padx=12, pady=6)

        va = data.get("video_analysis", {})
        opt = data.get("optimization", {})
        score = opt.get("viral_score", 80)

        # ── Card de Score e Visão Geral ──
        score_card = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
        score_card.pack(fill="x", padx=5, pady=(0, 10))

        top_score_row = ctk.CTkFrame(score_card, fg_color="transparent")
        top_score_row.pack(fill="x", padx=15, pady=(12, 4))

        # Badge com nota
        badge_color = "#10b981" if score >= 80 else ("#f59e0b" if score >= 65 else "#ef4444")
        ctk.CTkLabel(
            top_score_row,
            text=f"  POTENCIAL VIRAL REELS: {score}/100  ",
            font=ctk.CTkFont(weight="bold", size=14),
            fg_color=badge_color,
            text_color="#ffffff",
            corner_radius=6
        ).pack(side="left")

        # Barra Gráfica de Score
        gauge_row = ctk.CTkFrame(score_card, fg_color="transparent")
        gauge_row.pack(fill="x", padx=15, pady=(2, 6))

        score_pbar = ctk.CTkProgressBar(gauge_row, height=8, progress_color=badge_color, fg_color="#27272a")
        score_pbar.pack(side="left", fill="x", expand=True, padx=(0, 10))
        score_pbar.set(score / 100.0)

        ctk.CTkLabel(
            gauge_row, text=f"{score}%",
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color=badge_color
        ).pack(side="right")

        ctk.CTkLabel(
            score_card,
            text=opt.get("viral_score_explanation", ""),
            font=ctk.CTkFont(size=12),
            text_color="#e4e4e7",
            wraplength=480,
            justify="left"
        ).pack(anchor="w", padx=15, pady=(0, 10))

        # Detalhes de Estética, Shares e Saves
        metrics_frame = ctk.CTkFrame(score_card, fg_color="#1f1f23", corner_radius=8)
        metrics_frame.pack(fill="x", padx=15, pady=(0, 12))

        m1 = f"Estética: {va.get('aesthetic_quality', 'N/A')}"
        m2 = f"Compartilhamento (DM): {va.get('shareability_factor', 'N/A')}"
        m3 = f"Salvamentos: {va.get('saveability_factor', 'N/A')}"
        
        for m in [m1, m2, m3]:
            ctk.CTkLabel(metrics_frame, text=m, font=ctk.CTkFont(size=11), text_color="#d4d4d8").pack(anchor="w", padx=10, pady=2)

        # ── Gancho e Loop com Detector de Hook ──
        hook_grade = str(opt.get("hook_grade", "")).upper()
        if not hook_grade or hook_grade not in ("EXCELENTE", "BOM", "ATENCAO", "ATENÇÃO", "FRACO"):
            hook_grade = "EXCELENTE" if score >= 85 else ("BOM" if score >= 75 else ("ATENÇÃO" if score >= 60 else "FRACO"))

        hook_border = "#ef4444" if "FRACO" in hook_grade else ("#f59e0b" if "ATEN" in hook_grade else "#10b981")
        hook_card = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color=hook_border)
        hook_card.pack(fill="x", padx=5, pady=6)
        
        h_top = ctk.CTkFrame(hook_card, fg_color="transparent")
        h_top.pack(fill="x", padx=15, pady=(10, 4))
        ctk.CTkLabel(h_top, text=f"🎯 DIAGNÓSTICO DO GANCHO (0-2s): [{hook_grade}]", font=ctk.CTkFont(weight="bold", size=13), text_color=hook_border).pack(side="left")

        ctk.CTkLabel(hook_card, text=f"• Análise Atual: {opt.get('hook_quality', '')}", font=ctk.CTkFont(size=12), wraplength=480, justify="left").pack(anchor="w", padx=15, pady=2)
        
        sugg = opt.get("suggested_hook", "")
        if sugg:
            s_row = ctk.CTkFrame(hook_card, fg_color="transparent")
            s_row.pack(fill="x", padx=15, pady=(2, 4))
            ctk.CTkLabel(s_row, text=f"• Gancho Sugerido: \"{sugg}\"", font=ctk.CTkFont(size=12, weight="bold"), text_color="#facc15", wraplength=350, justify="left").pack(side="left")
            btn_cp_h = ctk.CTkButton(s_row, text="Copiar Gancho", width=95, height=22, font=ctk.CTkFont(size=10), fg_color="#27272a", hover_color="#3f3f46", command=lambda s=sugg: self._copy_to_clipboard(s, btn_cp_h))
            btn_cp_h.pack(side="right")
        
        if opt.get("loop_strategy"):
            ctk.CTkLabel(hook_card, text="Estratégia de Loop Invisível:", font=ctk.CTkFont(weight="bold", size=13), text_color="#a855f7").pack(anchor="w", padx=15, pady=(8, 4))
            ctk.CTkLabel(hook_card, text=opt.get("loop_strategy", ""), font=ctk.CTkFont(size=12), wraplength=480, justify="left").pack(anchor="w", padx=15, pady=(0, 10))

        # ── Legendas Virais (Captions) ──
        captions = data.get("captions", [])
        if captions:
            ctk.CTkLabel(self.right_scroll, text="3 Opções de Legendas Prontas para Copiar:", font=ctk.CTkFont(weight="bold", size=15), text_color="#ec4899").pack(anchor="w", padx=5, pady=(12, 6))

            for idx, c in enumerate(captions, 1):
                c_box = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
                c_box.pack(fill="x", padx=5, pady=5)

                top_c = ctk.CTkFrame(c_box, fg_color="transparent")
                top_c.pack(fill="x", padx=12, pady=(10, 4))

                ctk.CTkLabel(top_c, text=f"Opção {idx}", font=ctk.CTkFont(weight="bold", size=13), text_color="#f472b6").pack(side="left")

                full_text = f"{c.get('first_line', '')}\n\n{c.get('body', '')}\n\n{c.get('cta', '')}"
                
                btn_copy_cap = ctk.CTkButton(
                    top_c, text="Copiar Legenda", width=125, height=28,
                    image=icon_manager.get_icon("copy", size=(12, 12), color="#ffffff"), compound="left",
                    fg_color="#16a34a", hover_color="#15803d", font=ctk.CTkFont(size=11, weight="bold")
                )
                btn_copy_cap.configure(command=lambda t=full_text, b=btn_copy_cap: self._copy_to_clipboard(t, b, "Copiar Legenda"))
                btn_copy_cap.pack(side="right")

                # Preview da legenda
                txt_preview = ctk.CTkTextbox(c_box, height=90, font=ctk.CTkFont(size=12))
                txt_preview.pack(fill="x", padx=12, pady=(4, 8))
                txt_preview.insert("1.0", full_text)
                txt_preview.configure(state="disabled")

        # ── Hashtags ──
        hs = data.get("hashtag_strategy", {})
        recommended_tags = hs.get("recommended", [])
        if recommended_tags:
            h_card = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
            h_card.pack(fill="x", padx=5, pady=8)

            top_h = ctk.CTkFrame(h_card, fg_color="transparent")
            top_h.pack(fill="x", padx=12, pady=(10, 4))
            ctk.CTkLabel(top_h, text="Hashtags Estratégicas (3-5 Tags Ideais):", font=ctk.CTkFont(weight="bold", size=13), text_color="#34d399").pack(side="left")

            tags_joined = " ".join(recommended_tags)
            btn_copy_tags = ctk.CTkButton(
                top_h, text="Copiar Tags", width=110, height=28,
                image=icon_manager.get_icon("tag", size=(12, 12), color="#ffffff"), compound="left",
                fg_color="#10b981", hover_color="#059669", font=ctk.CTkFont(size=11, weight="bold")
            )
            btn_copy_tags.configure(command=lambda t=tags_joined, b=btn_copy_tags: self._copy_to_clipboard(t, b, "Copiar Tags"))
            btn_copy_tags.pack(side="right")

            ctk.CTkLabel(h_card, text=tags_joined, font=ctk.CTkFont(size=13, weight="bold"), text_color="#6ee7b7", wraplength=480).pack(anchor="w", padx=12, pady=4)
            if hs.get("explanation"):
                ctk.CTkLabel(h_card, text=hs.get("explanation", ""), font=ctk.CTkFont(size=11), text_color=COLOR_TEXT_MUTED, wraplength=480).pack(anchor="w", padx=12, pady=(0, 10))

        # ── Recomendação de Áudio ──
        if data.get("audio_recommendation"):
            a_card = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
            a_card.pack(fill="x", padx=5, pady=6)
            ctk.CTkLabel(a_card, text="Recomendação de Áudio e Trilha:", font=ctk.CTkFont(weight="bold", size=13), text_color="#f59e0b").pack(anchor="w", padx=12, pady=(8, 4))
            ctk.CTkLabel(a_card, text=data.get("audio_recommendation", ""), font=ctk.CTkFont(size=12), wraplength=480, justify="left").pack(anchor="w", padx=12, pady=(0, 10))

    # ── Métodos de Criação e Interação com Thumbnail do Reels (1080x1920) ──

    def _on_quick_extract_thumb(self):
        """Dispara extração de thumbnail a partir do botão no painel esquerdo."""
        video_path = self.file_entry.get().strip() if hasattr(self, "file_entry") else ""
        if not video_path or not os.path.exists(video_path):
            messagebox.showwarning("Aviso", "Por favor, selecione um arquivo de vídeo válido primeiro.")
            return

        time_str = self.thumb_time_entry.get().replace("s", "").strip() if hasattr(self, "thumb_time_entry") else "1.5"
        try:
            sec = float(time_str)
        except Exception:
            sec = 1.5

        title = ""
        if hasattr(self, "analysis_data") and isinstance(self.analysis_data, dict):
            title = self.analysis_data.get("title") or self.analysis_data.get("hook_text") or ""

        if hasattr(self, "placeholder_frame") and self.placeholder_frame.winfo_ismapped():
            self.placeholder_frame.pack_forget()

        self._reextract_thumb(timestamp_sec=sec, overlay_text=title)

    def _on_thumb_time_preset(self, s_val: float):
        if hasattr(self, "thumb_time_field") and self.thumb_time_field.winfo_exists():
            self.thumb_time_field.delete(0, "end")
            self.thumb_time_field.insert(0, f"{s_val:.2f}")
        self._trigger_thumb_update()

    def _trigger_thumb_update(self):
        """Coleta parâmetros dos seletores da miniatura e reexecuta geração em 9:16."""
        video_path = self.file_entry.get().strip() if hasattr(self, "file_entry") else ""
        if not video_path or not os.path.exists(video_path):
            messagebox.showwarning("Aviso", "Selecione um vídeo primeiro.")
            return

        try:
            sec = float(self.thumb_time_field.get().replace("s", "").strip())
        except Exception:
            sec = getattr(self, "_current_thumb_sec", 1.5)

        crop_label = self.thumb_seg_crop.get() if hasattr(self, "thumb_seg_crop") else "Centro"
        crop_vals_map = {
            "Centro": "center",
            "Esquerda": "left",
            "Direita": "right",
            "Desfoque 9:16": "blur_canvas",
            "Pan Manual": "pan"
        }
        crop_mode = crop_vals_map.get(crop_label, "center")
        pan_x = float(self.thumb_slider_pan.get()) if hasattr(self, "thumb_slider_pan") else 0.5

        overlay_text = self.thumb_ent_text.get().strip() if hasattr(self, "thumb_ent_text") else ""

        style_label = self.thumb_seg_style.get() if hasattr(self, "thumb_seg_style") else "Amarelo Viral"
        inv_style = {"Amarelo Viral": "yellow", "Branco Bold": "white", "Faixa Vermelha": "badge"}
        text_style = inv_style.get(style_label, "yellow")

        pos_label = self.thumb_seg_pos.get() if hasattr(self, "thumb_seg_pos") else "Topo (Safe Zone)"
        inv_pos = {"Topo (Safe Zone)": "top", "Centro": "center"}
        text_position = inv_pos.get(pos_label, "top")

        self._reextract_thumb(
            timestamp_sec=sec,
            crop_mode=crop_mode,
            pan_x=pan_x,
            overlay_text=overlay_text,
            text_position=text_position,
            text_style=text_style
        )

    def _reextract_thumb(
        self,
        timestamp_sec: float = 1.5,
        crop_mode: str = "center",
        pan_x: float = 0.5,
        overlay_text: str = "",
        text_position: str = "top",
        text_style: str = "yellow"
    ):
        """Gera ou atualiza uma capa 9:16 (1080x1920) e atualiza o card na interface."""
        video_path = self.file_entry.get().strip() if hasattr(self, "file_entry") else ""
        if not video_path or not os.path.exists(video_path):
            messagebox.showwarning("Aviso", "Selecione um vídeo primeiro.")
            return

        if hasattr(self, "btn_update_thumb") and self.btn_update_thumb.winfo_exists():
            self.btn_update_thumb.configure(state="disabled", text="Gerando 9:16...")
        if hasattr(self, "btn_extract_thumb") and self.btn_extract_thumb.winfo_exists():
            self.btn_extract_thumb.configure(state="disabled", text="Gerando...")

        def _worker():
            try:
                from thumbnail_studio import generate_shorts_thumbnail_pipeline
                from upscaler import find_ffmpeg
                ff_bin = find_ffmpeg() or "ffmpeg"
                p = Path(video_path)
                out_path = str(p.parent / f"{p.stem}_capa_reels_1080x1920.jpg")
                res = generate_shorts_thumbnail_pipeline(
                    video_path=video_path,
                    output_path=out_path,
                    timestamp_sec=timestamp_sec,
                    crop_mode=crop_mode,
                    pan_x=pan_x,
                    overlay_text=overlay_text,
                    text_position=text_position,
                    text_style=text_style,
                    ffmpeg_bin=ff_bin
                )

                def _ui():
                    if hasattr(self, "btn_update_thumb") and self.btn_update_thumb.winfo_exists():
                        self.btn_update_thumb.configure(state="normal", text="🔄 Atualizar Capa")
                    if hasattr(self, "btn_extract_thumb") and self.btn_extract_thumb.winfo_exists():
                        self.btn_extract_thumb.configure(state="normal", text="Gerar Capa")
                    if res and os.path.exists(res):
                        self._render_thumbnail_card(
                            res,
                            timestamp_sec=timestamp_sec,
                            crop_mode=crop_mode,
                            pan_x=pan_x,
                            overlay_text=overlay_text,
                            text_position=text_position,
                            text_style=text_style
                        )
                        self._log(f"🖼️ [THUMBNAIL 9:16] Capa Reels gerada ({crop_mode}, {timestamp_sec:.2f}s): {os.path.basename(res)}")
                    else:
                        self._log(f"[ERRO] Falha ao extrair frame no tempo {timestamp_sec:.2f}s")
                        messagebox.showerror("Erro", f"Não foi possível extrair o frame no tempo {timestamp_sec:.2f}s.")

                self.after(0, _ui)
            except Exception as e:
                def _err():
                    if hasattr(self, "btn_update_thumb") and self.btn_update_thumb.winfo_exists():
                        self.btn_update_thumb.configure(state="normal", text="🔄 Atualizar Capa")
                    if hasattr(self, "btn_extract_thumb") and self.btn_extract_thumb.winfo_exists():
                        self.btn_extract_thumb.configure(state="normal", text="Gerar Capa")
                    self._log(f"[ERRO] Erro ao gerar thumbnail: {e}")
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    def _render_thumbnail_card(
        self,
        thumb_path: str,
        timestamp_sec: float = 1.5,
        crop_mode: str = "center",
        pan_x: float = 0.5,
        overlay_text: str = "",
        text_position: str = "top",
        text_style: str = "yellow"
    ):
        """Renderiza estúdio interativo de capa 1080x1920 com enquadramento no personagem e tipografia viral."""
        if not thumb_path or not os.path.exists(thumb_path):
            return

        self._current_thumb_path = thumb_path
        self._current_thumb_sec = timestamp_sec
        self._current_crop_mode = crop_mode
        self._current_pan_x = pan_x
        self._current_overlay_text = overlay_text
        self._current_text_position = text_position
        self._current_text_style = text_style

        # Esconde placeholder
        if hasattr(self, "placeholder_frame") and self.placeholder_frame.winfo_ismapped():
            self.placeholder_frame.pack_forget()

        # Remove card anterior se existir
        if hasattr(self, "_active_thumb_card") and self._active_thumb_card and self._active_thumb_card.winfo_exists():
            try:
                self._active_thumb_card.destroy()
            except Exception:
                pass

        thumb_card = ctk.CTkFrame(self.right_scroll, fg_color="#141108", corner_radius=12, border_width=1, border_color="#f59e0b")
        thumb_card.pack(fill="x", padx=5, pady=(0, 10))
        self._active_thumb_card = thumb_card

        # Header do Card
        top_row = ctk.CTkFrame(thumb_card, fg_color="transparent")
        top_row.pack(fill="x", padx=14, pady=(10, 8))

        ctk.CTkLabel(
            top_row,
            text="🖼️ Estúdio de Capas Instagram Reels (1080x1920 Vertical 9:16)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#fbbf24"
        ).pack(side="left")

        ctk.CTkLabel(
            top_row,
            text=f" ⏱️ {timestamp_sec:.2f}s | 📐 1080x1920 ",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#09090b",
            fg_color="#f59e0b",
            corner_radius=4, padx=6, pady=2
        ).pack(side="right")

        content_row = ctk.CTkFrame(thumb_card, fg_color="transparent")
        content_row.pack(fill="x", padx=14, pady=(0, 12))

        # Coluna Esquerda: Preview Visual Vertical 9:16 (140x248)
        left_preview = ctk.CTkFrame(content_row, fg_color="transparent")
        left_preview.pack(side="left", padx=(0, 14), anchor="n")

        preview_frame = ctk.CTkFrame(left_preview, fg_color="#09090b", corner_radius=8, border_width=1, border_color="#78350f")
        preview_frame.pack()

        try:
            pil_img = Image.open(thumb_path)
            ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(140, 248))
            img_lbl = ctk.CTkLabel(preview_frame, text="", image=ctk_img, corner_radius=6)
            img_lbl.image = ctk_img
            img_lbl.pack(padx=3, pady=3)
        except Exception:
            ctk.CTkLabel(preview_frame, text="Prévia\nIndisponível", width=140, height=248, text_color="#71717a").pack(padx=3, pady=3)

        ctk.CTkLabel(
            left_preview,
            text="Formato Oficial 9:16\n1080 x 1920 px",
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color="#a1a1aa",
            justify="center"
        ).pack(pady=(4, 0))

        # Coluna Direita: Controles Completos
        ctrl_frame = ctk.CTkFrame(content_row, fg_color="transparent")
        ctrl_frame.pack(side="left", fill="both", expand=True)

        # 1. Título / Texto na Capa
        ctk.CTkLabel(
            ctrl_frame,
            text="✍️ Título / Gancho na Capa (Alto CTR):",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#fbbf24"
        ).pack(anchor="w", pady=(0, 2))

        titles_opts = []
        titles_map = {}
        if hasattr(self, "analysis_data") and isinstance(self.analysis_data, dict):
            hook_txt = self.analysis_data.get("hook_text") or self.analysis_data.get("hook_analysis", {}).get("hook_text", "")
            if hook_txt:
                label_h = f"🪝 Gancho 0-2s: {hook_txt[:38]}..."
                titles_opts.append(label_h)
                titles_map[label_h] = hook_txt
            t_txt = self.analysis_data.get("title", "")
            if t_txt:
                label_t = f"🏆 Título: {t_txt[:38]}..."
                titles_opts.append(label_t)
                titles_map[label_t] = t_txt
            caps = self.analysis_data.get("suggested_captions", [])
            for idx, c in enumerate(caps[:3]):
                chook = c.get("hook", "")
                if chook:
                    label_c = f"✨ Opção {idx+1}: {chook[:38]}..."
                    titles_opts.append(label_c)
                    titles_map[label_c] = chook

        titles_opts.append("✏️ Personalizado (Digitar abaixo)")
        titles_opts.append("🚫 Sem Texto (Apenas Imagem)")

        def _on_dropdown_title_selected(choice: str):
            if choice == "🚫 Sem Texto (Apenas Imagem)":
                self.thumb_ent_text.delete(0, "end")
            elif choice in titles_map:
                self.thumb_ent_text.delete(0, "end")
                self.thumb_ent_text.insert(0, titles_map[choice])
            self._trigger_thumb_update()

        initial_choice = titles_opts[0] if titles_opts else "✏️ Personalizado"
        self.thumb_opt_title = ctk.CTkOptionMenu(
            ctrl_frame,
            values=titles_opts,
            height=26,
            font=ctk.CTkFont(size=10),
            command=_on_dropdown_title_selected
        )
        self.thumb_opt_title.pack(fill="x", pady=(0, 4))
        self.thumb_opt_title.set(initial_choice)

        self.thumb_ent_text = ctk.CTkEntry(
            ctrl_frame,
            height=30,
            font=ctk.CTkFont(size=11, weight="bold"),
            placeholder_text="Digite a frase de impacto para a capa..."
        )
        self.thumb_ent_text.pack(fill="x", pady=(0, 8))
        if overlay_text:
            self.thumb_ent_text.insert(0, overlay_text)
        elif initial_choice in titles_map:
            self.thumb_ent_text.insert(0, titles_map[initial_choice])

        # 2. Enquadramento e Foco no Personagem
        crop_row_lbl = ctk.CTkFrame(ctrl_frame, fg_color="transparent")
        crop_row_lbl.pack(fill="x", pady=(0, 2))
        ctk.CTkLabel(
            crop_row_lbl,
            text="🎯 Enquadramento / Foco no Personagem (9:16):",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#d4d4d8"
        ).pack(side="left")

        crop_labels = ["Centro", "Esquerda", "Direita", "Desfoque 9:16", "Pan Manual"]
        crop_vals_map = {
            "Centro": "center",
            "Esquerda": "left",
            "Direita": "right",
            "Desfoque 9:16": "blur_canvas",
            "Pan Manual": "pan"
        }
        inv_crop_map = {v: k for k, v in crop_vals_map.items()}

        pan_frame = ctk.CTkFrame(ctrl_frame, fg_color="#18181b", corner_radius=6)
        lbl_pan = ctk.CTkLabel(pan_frame, text=f"Posição Horizontal: {int(pan_x*100)}%", font=ctk.CTkFont(size=10))
        lbl_pan.pack(side="left", padx=8)

        def _on_slider(val):
            lbl_pan.configure(text=f"Posição Horizontal: {int(val*100)}%")

        self.thumb_slider_pan = ctk.CTkSlider(
            pan_frame,
            from_=0.0, to=1.0,
            number_of_steps=20,
            command=_on_slider,
            height=16
        )
        self.thumb_slider_pan.set(pan_x)
        self.thumb_slider_pan.pack(side="right", fill="x", expand=True, padx=8, pady=4)

        def _on_crop_change(label: str):
            if label == "Pan Manual":
                pan_frame.pack(fill="x", pady=(2, 6))
            else:
                pan_frame.pack_forget()
            self._trigger_thumb_update()

        self.thumb_seg_crop = ctk.CTkSegmentedButton(
            ctrl_frame,
            values=crop_labels,
            height=26,
            font=ctk.CTkFont(size=10, weight="bold"),
            command=_on_crop_change
        )
        self.thumb_seg_crop.pack(fill="x", pady=(0, 4))
        self.thumb_seg_crop.set(inv_crop_map.get(crop_mode, "Centro"))
        if crop_mode == "pan":
            pan_frame.pack(fill="x", pady=(2, 6))

        # 3. Estilo e Posição do Texto
        style_pos_row = ctk.CTkFrame(ctrl_frame, fg_color="transparent")
        style_pos_row.pack(fill="x", pady=(4, 8))

        style_col = ctk.CTkFrame(style_pos_row, fg_color="transparent")
        style_col.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkLabel(style_col, text="Estilo:", font=ctk.CTkFont(size=10, weight="bold"), text_color="#a1a1aa").pack(anchor="w")
        self.thumb_seg_style = ctk.CTkSegmentedButton(
            style_col,
            values=["Amarelo Viral", "Branco Bold", "Faixa Vermelha"],
            height=24, font=ctk.CTkFont(size=9, weight="bold"),
            command=lambda _: self._trigger_thumb_update()
        )
        self.thumb_seg_style.pack(fill="x")
        style_map = {"yellow": "Amarelo Viral", "white": "Branco Bold", "badge": "Faixa Vermelha"}
        self.thumb_seg_style.set(style_map.get(text_style, "Amarelo Viral"))

        pos_col = ctk.CTkFrame(style_pos_row, fg_color="transparent")
        pos_col.pack(side="right", fill="x", expand=True, padx=(4, 0))
        ctk.CTkLabel(pos_col, text="Posição do Texto:", font=ctk.CTkFont(size=10, weight="bold"), text_color="#a1a1aa").pack(anchor="w")
        self.thumb_seg_pos = ctk.CTkSegmentedButton(
            pos_col,
            values=["Topo (Safe Zone)", "Centro"],
            height=24, font=ctk.CTkFont(size=9, weight="bold"),
            command=lambda _: self._trigger_thumb_update()
        )
        self.thumb_seg_pos.pack(fill="x")
        pos_map = {"top": "Topo (Safe Zone)", "center": "Centro"}
        self.thumb_seg_pos.set(pos_map.get(text_position, "Topo (Safe Zone)"))

        # 4. Seletor de Segundo / Frame
        time_row = ctk.CTkFrame(ctrl_frame, fg_color="transparent")
        time_row.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(time_row, text="Segundo do vídeo:", font=ctk.CTkFont(size=10, weight="bold"), text_color="#a1a1aa").pack(side="left", padx=(0, 6))

        for s_val in [0.5, 1.5, 3.0, 5.0]:
            ctk.CTkButton(
                time_row, text=f"{s_val}s", width=42, height=24,
                font=ctk.CTkFont(size=10, weight="bold"),
                fg_color="#d97706" if abs(s_val - timestamp_sec) < 0.1 else "#27272a",
                hover_color="#b45309",
                command=lambda s=s_val: self._on_thumb_time_preset(s)
            ).pack(side="left", padx=2)

        self.thumb_time_field = ctk.CTkEntry(time_row, width=54, height=24, font=ctk.CTkFont(size=10), justify="center")
        self.thumb_time_field.insert(0, f"{timestamp_sec:.2f}")
        self.thumb_time_field.pack(side="left", padx=(6, 4))

        self.btn_update_thumb = ctk.CTkButton(
            time_row, text="🔄 Atualizar Capa", width=120, height=24,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#f59e0b", hover_color="#d97706", text_color="#09090b",
            command=self._trigger_thumb_update
        )
        self.btn_update_thumb.pack(side="right")

        # 5. Linha de Ações Finais (Copiar / Salvar / Ver)
        act_row = ctk.CTkFrame(ctrl_frame, fg_color="transparent")
        act_row.pack(fill="x", pady=(2, 0))

        ctk.CTkButton(
            act_row, text="Copiar Imagem", width=125, height=30,
            image=icon_manager.get_icon("copy", size=(13, 13), color="#09090b"), compound="left",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#fbbf24", hover_color="#f59e0b", text_color="#09090b",
            command=lambda: self._copy_thumb_to_clipboard(thumb_path)
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            act_row, text="Salvar Como...", width=115, height=30,
            image=icon_manager.get_icon("download", size=(13, 13), color="#ffffff"), compound="left",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#27272a", hover_color="#3f3f46",
            command=lambda: self._save_thumb_as(thumb_path)
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            act_row, text="Ver Imagem", width=100, height=30,
            image=icon_manager.get_icon("image", size=(13, 13), color="#ffffff"), compound="left",
            font=ctk.CTkFont(size=11),
            fg_color="#27272a", hover_color="#3f3f46",
            command=lambda: self._open_file(thumb_path)
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            act_row, text="Abrir Pasta", width=95, height=30,
            image=icon_manager.get_icon("folder", size=(13, 13), color="#ffffff"), compound="left",
            font=ctk.CTkFont(size=11),
            fg_color="#27272a", hover_color="#3f3f46",
            command=lambda: self._reveal_in_folder(thumb_path)
        ).pack(side="left")

    def _copy_thumb_to_clipboard(self, thumb_path: str):
        """Copia o arquivo de imagem diretamente para a área de transferência do Windows."""
        if not thumb_path or not os.path.exists(thumb_path):
            return
        try:
            full_p = os.path.abspath(thumb_path).replace("'", "''")
            cmd = ["powershell", "-NoProfile", "-Command", f"Set-Clipboard -Path '{full_p}'"]
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            messagebox.showinfo("Copiado!", "Imagem da capa copiada para a área de transferência!\nVocê pode colar diretamente onde desejar.")
        except Exception as e:
            messagebox.showwarning("Aviso", f"Não foi possível copiar diretamente para a área de transferência: {e}")

    def _save_thumb_as(self, thumb_path: str):
        """Abre diálogo para o usuário salvar a capa onde quiser."""
        if not thumb_path or not os.path.exists(thumb_path):
            return
        dest = filedialog.asksaveasfilename(
            title="Salvar Capa do Reels Como",
            defaultextension=".jpg",
            filetypes=[("Imagem JPEG", "*.jpg"), ("Todos os arquivos", "*.*")],
            initialfile=os.path.basename(thumb_path)
        )
        if dest:
            try:
                shutil.copy2(thumb_path, dest)
                messagebox.showinfo("Salvo!", f"Capa do Reels salva com sucesso em:\n{dest}")
            except Exception as e:
                messagebox.showerror("Erro", f"Falha ao salvar a imagem: {e}")
