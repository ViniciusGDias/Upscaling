"""
Aba Analisar YouTube Shorts para CustomTkinter.
Análise de retenção (viewed vs swiped), gancho 0-3s, 5 títulos otimizados, 3 descrições SEO,
tags, legendas/textos sobrepostos (video_captions), comentários sugeridos fixados e roadmap.
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

from social_analyzer import analyze_yt_shorts_video, get_video_info_fast, COPY_TEMPLATES
from video_preview_player import VideoPreviewPlayer
import windows_notifier

COLOR_BG_DARK = "#09090b"
COLOR_CARD = "#111113"
COLOR_CARD_BORDER = "#27272a"
COLOR_ACCENT = "#e2e8f0"       # off-white — principal action
COLOR_ACCENT_HOVER = "#a1a1aa"
COLOR_TEXT_MUTED = "#a1a1aa"   # zinc-400 — high contrast on dark frames


class YTShortsAnalyzerTab(ctk.CTkFrame):
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
            self.log_callback(f"[YT Shorts] {msg}")
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", msg + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=4)
        self.grid_columnconfigure(1, weight=6)
        self.grid_rowconfigure(0, weight=1)

        # ── Coluna Esquerda: Controles Scrolláveis ──
        left_frame = ctk.CTkScrollableFrame(self, fg_color=COLOR_BG_DARK, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(5, 5), pady=5)

        # Cabeçalho
        header_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=(15, 10))
        ctk.CTkLabel(
            header_frame,
            text=" Analisador YouTube Shorts",
            image=icon_manager.get_icon("youtube", size=(20, 20), color="#10b981"), compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color="#ef4444"
        ).pack(anchor="w")
        ctk.CTkLabel(
            header_frame,
            text="Otimização algorítmica para Shorts: Retenção, Gancho 0-3s, 5 Títulos, SEO, Tags e Legendas na Tela.",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_MUTED,
            wraplength=380,
            justify="left"
        ).pack(anchor="w", pady=(2, 0))

        # Seleção de Vídeo
        file_box = ctk.CTkFrame(left_frame, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color=COLOR_CARD_BORDER)
        file_box.pack(fill="x", padx=15, pady=8)

        ctk.CTkLabel(file_box, text="Vídeo para Análise:", font=ctk.CTkFont(weight="bold", size=13)).pack(anchor="w", padx=10, pady=(8, 4))
        
        row_pick = ctk.CTkFrame(file_box, fg_color="transparent")
        row_pick.pack(fill="x", padx=10, pady=(0, 6))
        
        self.file_entry = ctk.CTkEntry(row_pick, placeholder_text="Selecione um arquivo de vídeo (MP4, MKV, etc)...", height=32)
        self.file_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        
        self.btn_browse = ctk.CTkButton(
            row_pick, text="Procurar", width=100, height=32,
            image=icon_manager.get_icon("folder", size=(14, 14)), compound="left",
            fg_color="#16a34a", hover_color="#15803d",
            command=self._choose_video
        )
        self.btn_browse.pack(side="right")

        self.lbl_video_info = ctk.CTkLabel(file_box, text="Nenhum vídeo selecionado", font=ctk.CTkFont(size=11), text_color=COLOR_TEXT_MUTED)
        self.lbl_video_info.pack(anchor="w", padx=10, pady=(0, 4))

        # Linha de Cache Inteligente e Botão de Limpeza
        row_cache = ctk.CTkFrame(file_box, fg_color="transparent")
        row_cache.pack(fill="x", padx=10, pady=(0, 8))

        self.cache_status_badge = ctk.CTkLabel(
            row_cache,
            text="[CACHE: NENHUM]",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=COLOR_TEXT_MUTED,
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
        self.preview_player.pack(fill="x", padx=10, pady=(0, 8))

        # ── AÇÃO RÁPIDA: Gerador de Thumb Shorts (1080x1920) - 100% visível no topo ──
        thumb_btn_frame = ctk.CTkFrame(left_frame, fg_color="#181308", corner_radius=8, border_width=1, border_color="#f59e0b")
        thumb_btn_frame.pack(fill="x", padx=15, pady=(4, 6))

        tb_top = ctk.CTkFrame(thumb_btn_frame, fg_color="transparent")
        tb_top.pack(fill="x", padx=10, pady=(6, 2))

        ctk.CTkLabel(
            tb_top, text="📸 Gerador de Thumb Shorts (1080x1920):",
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
            tb_row, text="Gerar Thumb", width=120, height=28,
            image=icon_manager.get_icon("image", size=(14, 14), color="#09090b"), compound="left",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#f59e0b", hover_color="#d97706", text_color="#09090b",
            command=self._on_quick_extract_thumb
        )
        self.btn_extract_thumb.pack(side="left")

        # ── Botão de Ação Principal: Analisar Vídeo para YouTube Shorts ──
        self.btn_analyze = ctk.CTkButton(
            left_frame,
            text="Analisar Vídeo para YouTube Shorts",
            image=icon_manager.get_icon("sparkle", size=(16, 16), color="#09090b"), compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            height=42,
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HOVER,
            command=self._start_analysis
        )
        self.btn_analyze.pack(fill="x", padx=15, pady=(4, 8))

        # Configurações de Nicho / Categoria
        cat_box = ctk.CTkFrame(left_frame, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color=COLOR_CARD_BORDER)
        cat_box.pack(fill="x", padx=15, pady=6)

        ctk.CTkLabel(cat_box, text="Nicho & Personagem:", font=ctk.CTkFont(weight="bold", size=13)).pack(anchor="w", padx=10, pady=(8, 4))

        row_cat = ctk.CTkFrame(cat_box, fg_color="transparent")
        row_cat.pack(fill="x", padx=10, pady=2)
        ctk.CTkLabel(row_cat, text="Categoria:", font=ctk.CTkFont(size=12), width=105).pack(side="left")
        self.opt_category = ctk.CTkOptionMenu(
            row_cat,
            values=["Anime", "Dorama", "Geral / Outros"],
            height=28,
            command=self._on_category_change
        )
        self.opt_category.pack(side="left", fill="x", expand=True)

        row_anim = ctk.CTkFrame(cat_box, fg_color="transparent")
        row_anim.pack(fill="x", padx=10, pady=4)
        self.lbl_work = ctk.CTkLabel(row_anim, text="Nome do Anime:", font=ctk.CTkFont(size=12), width=105)
        self.lbl_work.pack(side="left")
        self.ent_anime = ctk.CTkEntry(row_anim, placeholder_text="Ex: Jujutsu Kaisen, One Piece...", height=28)
        self.ent_anime.pack(side="left", fill="x", expand=True)

        row_char = ctk.CTkFrame(cat_box, fg_color="transparent")
        row_char.pack(fill="x", padx=10, pady=(2, 8))
        self.lbl_char = ctk.CTkLabel(row_char, text="Personagem:", font=ctk.CTkFont(size=12), width=105)
        self.lbl_char.pack(side="left")
        self.ent_character = ctk.CTkEntry(row_char, placeholder_text="Ex: Gojo Satoru, Luffy...", height=28)
        self.ent_character.pack(side="left", fill="x", expand=True)

        # Contexto do Criador com Templates
        ctx_box = ctk.CTkFrame(left_frame, fg_color="transparent")
        ctx_box.pack(fill="x", padx=15, pady=(6, 0))

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
            ctx_box, height=52, font=ctk.CTkFont(size=11),
            fg_color="#111113", border_color="#27272a", border_width=1,
            text_color="#d4d4d8"
        )
        self.txt_context.pack(fill="x")
        self.txt_context.insert("1.0", "Ex: anime edit do Gojo, foco em luta épica, público jovem/otaku.")

        # Pílulas de Contexto Rápido Dinâmicas (adaptam-se à categoria Anime / Dorama)
        self.chips_frame = ctk.CTkFrame(ctx_box, fg_color="transparent")
        self.chips_frame.pack(fill="x", pady=(4, 0))
        self._render_quick_chips("Anime")

        # Idioma e Opções
        opt_row = ctk.CTkFrame(left_frame, fg_color="transparent")
        opt_row.pack(fill="x", padx=15, pady=(8, 2))
        
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
            text="Ignorar Cache",
            font=ctk.CTkFont(size=11),
            text_color="#f59e0b"
        )
        self.chk_force_refresh.pack(side="right")



        # Log
        ctk.CTkLabel(left_frame, text="Log de Execução:", font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_TEXT_MUTED).pack(anchor="w", padx=15, pady=(4, 2))
        self.log_textbox = ctk.CTkTextbox(left_frame, height=120, font=ctk.CTkFont(family="Consolas", size=11))
        self.log_textbox.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        self.log_textbox.configure(state="disabled")

        # ── Coluna Direita: Resultados Scrolláveis ──
        self.right_scroll = ctk.CTkScrollableFrame(self, fg_color=COLOR_BG_DARK, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
        self.right_scroll.grid(row=0, column=1, sticky="nsew", padx=(5, 5), pady=5)
        self.right_scroll.grid_columnconfigure(0, weight=1)

        self.placeholder_frame = ctk.CTkFrame(self.right_scroll, fg_color="transparent")
        self.placeholder_frame.pack(expand=True, pady=110)

        ctk.CTkLabel(
            self.placeholder_frame,
            text="",
            image=icon_manager.get_icon("youtube", size=(48, 48), color="#3f3f46")
        ).pack(pady=(0, 14))

        ctk.CTkLabel(
            self.placeholder_frame,
            text="Central de Inteligência & Thumbnails YouTube Shorts",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            text_color="#fafafa"
        ).pack(pady=(0, 6))

        ctk.CTkLabel(
            self.placeholder_frame,
            text="Selecione um corte de vídeo para extrair a Capa 1080x1920 imediatamente\nou clique em 'Analisar Vídeo' para desbloquear títulos de alto CTR, ganchos anti-swipe e SEO.",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color="#a1a1aa",
            justify="center"
        ).pack()

    def _update_cache_badge(self, path: str = ""):
        path = path or self.file_entry.get().strip()
        if not path or not os.path.exists(path):
            self.cache_status_badge.configure(text="[CACHE: NENHUM]", text_color=COLOR_TEXT_MUTED)
            return

        try:
            from ai_cache_hub import ai_cache
            has_direct = ai_cache.has(path, "yt_shorts_analysis")
            has_cross = ai_cache.has(path, "instagram_analysis")
            if has_direct:
                self.cache_status_badge.configure(text="[⚡ CACHE SALVO (24h)]", text_color="#10b981")
            elif has_cross:
                self.cache_status_badge.configure(text="[⚡ CACHE SALVO (Instagram)]", text_color="#10b981")
            else:
                self.cache_status_badge.configure(text="[CACHE: VAZIO]", text_color=COLOR_TEXT_MUTED)
        except Exception:
            self.cache_status_badge.configure(text="[CACHE: N/A]", text_color=COLOR_TEXT_MUTED)

    def _clear_cache_for_video(self):
        path = self.file_entry.get().strip()
        if not path:
            self._log("[AVISO] Selecione um vídeo para limpar o cache.")
            return

        try:
            from ai_cache_hub import ai_cache
            ai_cache.invalidate(path, "yt_shorts_analysis")
            ai_cache.invalidate(path, "instagram_analysis")
            ai_cache.invalidate(path, "viral_metadata")
            self._update_cache_badge(path)
            self._log(f"🧹 [Cache] Cache limpo com sucesso para: {os.path.basename(path)}")
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
        self.btn_analyze.configure(state="disabled", text="Analisando Shorts...")
        self._show_loading_state()
        category = self.opt_category.get().lower()
        anime = self.ent_anime.get().strip()
        character = self.ent_character.get().strip()
        context = self.txt_context.get("1.0", "end").strip() if hasattr(self, "txt_context") else ""
        if "Ex: anime edit" in context or "Ex: Cena emocionante" in context:
            context = ""
        lang_str = self.seg_lang.get() if hasattr(self, "seg_lang") else "PT"
        lang = "en" if "EN" in lang_str else ("es" if "ES" in lang_str else "pt")
        language_en = (lang == "en")

        def worker():
            try:
                res = analyze_yt_shorts_video(
                    path, category=category, character=character,
                    anime=anime, context=context, language_en=language_en,
                    language=lang, force_refresh=force,
                    on_log=self._log, log_cb=self._log
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
                        f"• Rate Limit (429) do Gemini ou falta de cota temporária no provedor.\n"
                        f"• Conexão oscilando durante a chamada de API.\n"
                        f"• Resposta incompleta do modelo.\n\n"
                        f"Clique abaixo para limpar o cache corrompido e tentar novamente."
                    )
                ))
            finally:
                self.after(0, self._finish_analysis)

        threading.Thread(target=worker, daemon=True).start()

    def _render_quick_chips(self, category="Anime"):
        if not hasattr(self, "chips_frame"):
            return
        for widget in self.chips_frame.winfo_children():
            widget.destroy()

        if category == "Dorama":
            quick_chips = [
                ("💖 Romance / Química", "foco no romance arrebatador, química intensa entre os protagonistas e tensão de proximidade"),
                ("😭 Choro / Separação", "foco no momento mais emocionante, lágrimas, despedida dolorosa e desabafo"),
                ("👑 Vingança / Poder", "foco na virada de jogo, humilhação do vilão, protagonista poderoso e volta por cima"),
                ("😱 Revelação / Choque", "foco na revelação da verdadeira identidade, segredo de família desmascarado"),
                ("🥺 Declaração / Fofo", "foco na confissão de sentimentos, primeiro beijo ou momento 'vou te proteger'"),
                ("💔 Traição / Término", "foco no término dramático, quebra de confiança e discussão de casal")
            ]
        elif category == "Anime":
            quick_chips = [
                ("🔥 Luta/Clímax", "foco em luta épica, ação frenética e clímax"),
                ("😂 Comédia", "foco em humor, meme, cena engraçada e descontraída"),
                ("🤫 Mistério", "foco em mistério, revelação chocante e suspense"),
                ("💔 Emocional", "foco em cena triste, despedida e arcos dramáticos"),
                ("⚡ Plot Twist", "foco em reviravolta insana e quebra de expectativa")
            ]
        else:
            quick_chips = [
                ("🔥 Alta Energia", "foco em dinamismo, ritmo acelerado e alto impacto"),
                ("😂 Humor / Meme", "foco em descontração, comédia e meme"),
                ("💡 Curiosidade", "foco em fato curioso, mistério e explicação rápida"),
                ("🎬 Storytelling", "foco em narrativa envolvente do início ao fim"),
                ("⚡ Retenção Máxima", "foco em gancho magnético e loop perfeito")
            ]

        for label, val in quick_chips:
            btn_chip = ctk.CTkButton(
                self.chips_frame,
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

    def _on_category_change(self, choice):
        if choice == "Dorama":
            self.lbl_work.configure(text="Nome do Dorama:")
            self.ent_anime.configure(placeholder_text="Ex: Pousando no Amor, Vincenzo, Rainha das Lágrimas, Goblin...")
            self.lbl_char.configure(text="Personagem(ns) / Atores:")
            self.ent_character.configure(placeholder_text="Ex: Ri Jeong-hyeok, Hong Hae-in, Hyun Bin, Song Joong-ki...")
            if hasattr(self, "opt_template"):
                self.opt_template.set("Dorama / Emocional")
            if hasattr(self, "txt_context"):
                cur_ctx = self.txt_context.get("1.0", "end").strip()
                if not cur_ctx or "anime edit do Gojo" in cur_ctx or "Ex:" in cur_ctx:
                    self.txt_context.delete("1.0", "end")
                    self.txt_context.insert("1.0", "Ex: Cena emocionante do casal, conflito com a família, química intensa, revelação.")
            self._render_quick_chips("Dorama")
        elif choice == "Anime":
            self.lbl_work.configure(text="Nome do Anime:")
            self.ent_anime.configure(placeholder_text="Ex: Jujutsu Kaisen, One Piece, Naruto, Bleach...")
            self.lbl_char.configure(text="Personagem:")
            self.ent_character.configure(placeholder_text="Ex: Gojo Satoru, Luffy, Zoro, Ichigo...")
            if hasattr(self, "opt_template"):
                self.opt_template.set("Anime / Geek Épico")
            if hasattr(self, "txt_context"):
                cur_ctx = self.txt_context.get("1.0", "end").strip()
                if not cur_ctx or "Cena emocionante do casal" in cur_ctx or "Ex:" in cur_ctx:
                    self.txt_context.delete("1.0", "end")
                    self.txt_context.insert("1.0", "Ex: anime edit do Gojo, foco em luta épica, público jovem/otaku.")
            self._render_quick_chips("Anime")
        else:
            self.lbl_work.configure(text="Tema / Obra:")
            self.ent_anime.configure(placeholder_text="Ex: Nome do canal, tema ou vídeo...")
            self.lbl_char.configure(text="Destaque:")
            self.ent_character.configure(placeholder_text="Ex: Tema principal, pessoa ou assunto...")
            if hasattr(self, "opt_template"):
                self.opt_template.set("Padrão")
            self._render_quick_chips("Geral")

    def _finish_analysis(self):
        self.is_analyzing = False
        self.btn_analyze.configure(state="normal", text="Analisar Vídeo para YouTube Shorts")
        vid_name = os.path.basename(self.file_entry.get().strip() or "Vídeo")
        windows_notifier.show_toast(
            "Urahara Studio - YouTube Shorts Concluído",
            f"Análise de Shorts concluída para: {vid_name}"
        )

    def _select_ab_title(self, title_text: str, active_card):
        for c in getattr(self, "_ab_cards", []):
            try:
                c.configure(border_color="#27272a", fg_color="#18181b")
            except Exception:
                pass
        try:
            active_card.configure(border_color="#10b981", fg_color="#062e20")
        except Exception:
            pass
        _copy_text_to_clipboard(self, title_text)
        self._log(f"✓ Título A/B selecionado e copiado: {title_text}")
        if hasattr(self, "_on_apply_title_to_thumb"):
            self._on_apply_title_to_thumb(title_text)

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

    def _fill_character(self, name: str):
        self.ent_character.delete(0, "end")
        self.ent_character.insert(0, name)
        self._log(f"Personagem preenchido automaticamente: '{name}'")

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

    def _repurpose_to_instagram(self, data: dict):
        try:
            from social_analyzer import adapt_yt_to_instagram
            from tkinter import messagebox
            adapted = adapt_yt_to_instagram(data)
            if self.main_app and hasattr(self.main_app, "insta_tab"):
                self.main_app.insta_tab.file_entry.delete(0, "end")
                self.main_app.insta_tab.file_entry.insert(0, self.video_path)
                self.main_app.insta_tab.analysis_data = adapted
                self.main_app.insta_tab._render_results(adapted)
                if hasattr(self.main_app, "tabview"):
                    self.main_app.tabview.set("Instagram Shorts")
                self._log("✓ Conteúdo adaptado e transferido para a aba Instagram Reels!")
            else:
                first_cap = adapted.get("suggested_captions", [{}])[0].get("caption", "")
                self.clipboard_clear()
                self.clipboard_append(first_cap)
                messagebox.showinfo("Copiado para Instagram", "Copywriting adaptado para o Instagram Reels copiado para a área de transferência!")
        except Exception as e:
            self._log(f"Erro ao adaptar para Instagram: {e}")

    def _clear_results_panel(self):
        """Limpa de forma 100% segura todos os widgets de resultados sem quebrar referências internas."""
        if hasattr(self, "analysis_pbar") and self.analysis_pbar:
            try:
                self.analysis_pbar.stop()
            except Exception:
                pass
            self.analysis_pbar = None

        self._active_thumb_card = None
        self.placeholder_frame = None

        for w in list(self.right_scroll.winfo_children()):
            try:
                if w.winfo_exists():
                    w.destroy()
            except Exception:
                pass

    def _show_loading_state(self):
        """Exibe card de carregamento com animação enquanto a IA processa o vídeo."""
        self._clear_results_panel()

        card = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color="#8b5cf6")
        card.pack(fill="x", padx=12, pady=40)

        ctk.CTkLabel(
            card,
            text="",
            image=icon_manager.get_icon("sparkle", size=(36, 36), color="#a78bfa")
        ).pack(pady=(24, 10))

        ctk.CTkLabel(
            card,
            text="IA Analisando Vídeo para YouTube Shorts...",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color="#ffffff"
        ).pack(pady=(0, 6))

        ctk.CTkLabel(
            card,
            text="Avaliando ganchos de retenção 0-3s, títulos virais de alto CTR,\ntags, legendas dinâmicas e thumbnail vertical 9:16...",
            font=ctk.CTkFont(size=12),
            text_color="#a1a1aa",
            justify="center"
        ).pack(pady=(0, 16))

        self.analysis_pbar = ctk.CTkProgressBar(card, mode="indeterminate", height=6, progress_color="#8b5cf6")
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
        self._clear_results_panel()

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
        self._clear_results_panel()

        if not data or ("video_analysis" not in data and "optimization" not in data) or data.get("parse_error"):
            raw = str(data.get("raw_response", data) if data else "Resposta vazia da API")
            err_msg = data.get("error_msg", "Formato de resposta incompleto ou truncado") if isinstance(data, dict) else str(data)
            self._render_error_card(err_msg, raw_response=raw)
            return

        try:
            self._render_results_content(data)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self._log(f"[ERRO] Erro ao renderizar resultados: {e}\n{tb}")
            self._render_error_card(f"Erro visual ao montar interface: {e}", raw_response=tb)

    def _render_results_content(self, data: dict):
        # ── Card de Capa de Alto CTR (1080x1920) ──
        thumb_path = data.get("_thumbnail_path")
        if not thumb_path or not os.path.exists(thumb_path):
            vid_p = self.file_entry.get().strip() or getattr(self, "video_path", "")
            if vid_p and os.path.exists(vid_p):
                from social_analyzer import extract_hook_thumbnail
                from upscaler import find_ffmpeg
                ff = find_ffmpeg() or "ffmpeg"
                titles = data.get("titles", [])
                t_first = ""
                if titles and isinstance(titles, list):
                    item = titles[0]
                    t_first = item.get("title", "") if isinstance(item, dict) else str(item)
                thumb_path = extract_hook_thumbnail(vid_p, ffmpeg_bin=ff, overlay_text=t_first)
                data["_thumbnail_path"] = thumb_path
                data["_thumbnail_text"] = t_first

        if thumb_path and os.path.exists(thumb_path):
            self._render_thumbnail_card(
                thumb_path,
                timestamp_sec=float(data.get("_thumbnail_sec", 1.5)),
                overlay_text=data.get("_thumbnail_text", "")
            )

        # ── Card de Sincronização Cruzada (Postar no Instagram Reels) ──
        repurpose_card = ctk.CTkFrame(self.right_scroll, fg_color="#1e1b4b", corner_radius=10, border_width=1, border_color="#6366f1")
        repurpose_card.pack(fill="x", padx=5, pady=(0, 8))

        r_row = ctk.CTkFrame(repurpose_card, fg_color="transparent")
        r_row.pack(fill="x", padx=12, pady=8)

        ctk.CTkLabel(
            r_row,
            text="🔄 Cross-Post: Quer postar este mesmo corte no Instagram Reels?",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#c7d2fe"
        ).pack(side="left")

        ctk.CTkButton(
            r_row, text="Adaptar p/ Instagram Reels", width=180, height=26,
            image=icon_manager.get_icon("instagram", size=(14, 14), color="#ffffff"), compound="left",
            font=ctk.CTkFont(size=11, weight="bold"), fg_color="#4f46e5", hover_color="#4338ca",
            command=lambda: self._repurpose_to_instagram(data)
        ).pack(side="right")

        # ── Badge de API Lore integrada ──
        if data.get("_enriched_context"):
            api_badge = ctk.CTkFrame(self.right_scroll, fg_color="#18181b", corner_radius=8, border_width=1, border_color="#ef4444")
            api_badge.pack(fill="x", padx=5, pady=(0, 8))
            ctk.CTkLabel(
                api_badge,
                text="Metadados & Lore Integrados via API Oficial (Kitsu / MyAnimeList / TVMaze)",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#ef4444"
            ).pack(anchor="w", padx=12, pady=6)

        va = data.get("video_analysis", {})
        opt = data.get("optimization", {})
        score = opt.get("viral_score", 85)

        # ── 1. Análise do Vídeo & Score ──
        score_card = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
        score_card.pack(fill="x", padx=5, pady=(0, 10))

        top_score = ctk.CTkFrame(score_card, fg_color="transparent")
        top_score.pack(fill="x", padx=15, pady=(12, 4))

        badge_color = "#10b981" if score >= 80 else ("#f59e0b" if score >= 65 else "#ef4444")
        ctk.CTkLabel(
            top_score,
            text=f"  POTENCIAL VIRAL SHORTS: {score}/100  ",
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
        ).pack(anchor="w", padx=15, pady=(0, 8))

        # Personagens Identificados no Corte
        raw_chars = (
            va.get("characters_detected") or
            data.get("characters_detected") or
            va.get("personagens_detectados") or
            va.get("characters")
        )
        if raw_chars:
            if isinstance(raw_chars, list):
                char_items = [str(c).strip() for c in raw_chars if str(c).strip()]
            elif isinstance(raw_chars, str):
                char_items = [c.strip() for c in raw_chars.split("\n") if c.strip()]
            else:
                char_items = []

            if char_items:
                char_box = ctk.CTkFrame(score_card, fg_color="#18181b", corner_radius=8, border_width=1, border_color="#8b5cf6")
                char_box.pack(fill="x", padx=15, pady=(0, 8))

                char_head = ctk.CTkFrame(char_box, fg_color="transparent")
                char_head.pack(fill="x", padx=10, pady=(6, 4))

                ctk.CTkLabel(
                    char_head,
                    text="Personagens Identificados no Corte:",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color="#c084fc"
                ).pack(side="left")

                first_name = char_items[0].split("(")[0].split("—")[0].split("-")[0].replace("•", "").strip()
                if first_name and not self.ent_character.get().strip():
                    btn_fill = ctk.CTkButton(
                        char_head,
                        text=f"Usar '{first_name[:16]}'",
                        width=85,
                        height=22,
                        font=ctk.CTkFont(size=10, weight="bold"),
                        fg_color="#7c3aed",
                        hover_color="#6d28d9",
                        command=lambda n=first_name: self._fill_character(n)
                    )
                    btn_fill.pack(side="right")

                for ch in char_items:
                    bullet = ch if ch.startswith(("•", "-", "*")) else f"• {ch}"
                    ctk.CTkLabel(
                        char_box,
                        text=bullet,
                        font=ctk.CTkFont(size=11),
                        text_color="#f1f5f9",
                        wraplength=460,
                        justify="left"
                    ).pack(anchor="w", padx=12, pady=(1, 2))

                ctk.CTkFrame(char_box, fg_color="transparent", height=4).pack()

        # Contexto do Personagem / Anime / Dorama
        char_ctx = va.get("character_context") or va.get("dorama_context")
        if char_ctx:
            ctx_box = ctk.CTkFrame(score_card, fg_color="#18181b", corner_radius=8, border_width=1, border_color="#27272a")
            ctx_box.pack(fill="x", padx=15, pady=(0, 8))
            is_dorama = "dorama" in self.opt_category.get().lower()
            ctx_title = "Contexto do Personagem & Dorama:" if is_dorama else "Contexto do Personagem & Anime:"
            ctk.CTkLabel(ctx_box, text=ctx_title, font=ctk.CTkFont(size=11, weight="bold"), text_color="#38bdf8").pack(anchor="w", padx=10, pady=(6, 2))
            ctk.CTkLabel(ctx_box, text=char_ctx, font=ctk.CTkFont(size=11), text_color="#d4d4d8", wraplength=460, justify="left").pack(anchor="w", padx=10, pady=(0, 6))

        # Gancho, Loop e Retenção com Detector de Hook
        hook_grade = str(opt.get("hook_grade", "")).upper()
        if not hook_grade or hook_grade not in ("EXCELENTE", "BOM", "ATENCAO", "ATENÇÃO", "FRACO"):
            hook_grade = "EXCELENTE" if score >= 85 else ("BOM" if score >= 75 else ("ATENÇÃO" if score >= 60 else "FRACO"))

        hook_border = "#ef4444" if "FRACO" in hook_grade else ("#f59e0b" if "ATEN" in hook_grade else "#10b981")
        hook_box = ctk.CTkFrame(score_card, fg_color="#18181b", corner_radius=8, border_width=1, border_color=hook_border)
        hook_box.pack(fill="x", padx=15, pady=(0, 12))

        h_top = ctk.CTkFrame(hook_box, fg_color="transparent")
        h_top.pack(fill="x", padx=10, pady=(8, 2))
        ctk.CTkLabel(h_top, text=f"🎯 DIAGNÓSTICO DO GANCHO (0-3s): [{hook_grade}]", font=ctk.CTkFont(size=12, weight="bold"), text_color=hook_border).pack(side="left")

        ctk.CTkLabel(hook_box, text=f"Qualidade: {opt.get('hook_quality', '')}", font=ctk.CTkFont(size=11), text_color="#d4d4d8", wraplength=460, justify="left").pack(anchor="w", padx=10, pady=(2, 2))
        
        sugg = opt.get("suggested_hook", "")
        if sugg:
            s_row = ctk.CTkFrame(hook_box, fg_color="transparent")
            s_row.pack(fill="x", padx=10, pady=(2, 4))
            ctk.CTkLabel(s_row, text=f"Gancho Sugerido: \"{sugg}\"", font=ctk.CTkFont(size=11, weight="bold"), text_color="#facc15", wraplength=350, justify="left").pack(side="left")
            btn_cp_h = ctk.CTkButton(s_row, text="Copiar", width=75, height=22, font=ctk.CTkFont(size=10), fg_color="#27272a", hover_color="#3f3f46", command=lambda s=sugg: self._copy_to_clipboard(s, btn_cp_h))
            btn_cp_h.pack(side="right")

        if opt.get("loop_strategy"):
            ctk.CTkLabel(hook_box, text=f"Loop Infinito: {opt.get('loop_strategy', '')}", font=ctk.CTkFont(size=11), text_color="#a855f7", wraplength=460, justify="left").pack(anchor="w", padx=10, pady=(2, 6))

        # ── 2. A/B Testing de Títulos Interativo ──
        titles = data.get("titles", [])
        if titles:
            if len(titles) >= 3:
                ab_frame = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color="#38bdf8")
                ab_frame.pack(fill="x", padx=5, pady=(8, 10))

                ab_head = ctk.CTkFrame(ab_frame, fg_color="transparent")
                ab_head.pack(fill="x", padx=12, pady=(10, 4))
                ctk.CTkLabel(ab_head, text="⚡ A/B Testing: 3 Variações Estratégicas", font=ctk.CTkFont(size=13, weight="bold"), text_color="#38bdf8").pack(side="left")
                ctk.CTkLabel(ab_head, text="Clique em qualquer opção para ativá-la e copiar", font=ctk.CTkFont(size=10), text_color="#a1a1aa").pack(side="right")

                self._ab_cards = []
                for t_idx, t_data in enumerate(titles[:3]):
                    ab_card = ctk.CTkFrame(ab_frame, fg_color="#18181b", corner_radius=8, border_width=1, border_color="#27272a")
                    ab_card.pack(fill="x", padx=12, pady=4)
                    self._ab_cards.append(ab_card)

                    card_head = ctk.CTkFrame(ab_card, fg_color="transparent")
                    card_head.pack(fill="x", padx=10, pady=(6, 2))

                    v_letter = ["A", "B", "C"][t_idx]
                    v_style = t_data.get("style", f"Variação {v_letter}")
                    ctk.CTkLabel(card_head, text=f"VARIAÇÃO {v_letter}  [{v_style}]", font=ctk.CTkFont(size=11, weight="bold"), text_color="#7dd3fc").pack(side="left")

                    t_val = t_data.get("title", "")
                    btn_pick = ctk.CTkButton(
                        card_head, text="Ativar & Copiar", width=105, height=24,
                        image=icon_manager.get_icon("copy", size=(11, 11), color="#ffffff"), compound="left",
                        font=ctk.CTkFont(size=10, weight="bold"),
                        fg_color="#16a34a", hover_color="#15803d",
                        command=lambda tv=t_val, c=ab_card: self._select_ab_title(tv, c)
                    )
                    btn_pick.pack(side="right")

                    ctk.CTkLabel(ab_card, text=t_val, font=ctk.CTkFont(size=12, weight="bold"), text_color="#fef08a", wraplength=480, justify="left").pack(anchor="w", padx=10, pady=(2, 6))

                ctk.CTkFrame(ab_frame, fg_color="transparent", height=4).pack()
        titles = data.get("titles", [])
        if titles:
            ctk.CTkLabel(self.right_scroll, text="5 Títulos com Alto CTR (#shorts):", font=ctk.CTkFont(weight="bold", size=15), text_color="#f87171").pack(anchor="w", padx=5, pady=(10, 4))
            for idx, t in enumerate(titles, 1):
                t_card = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color=COLOR_CARD_BORDER)
                t_card.pack(fill="x", padx=5, pady=4)
                
                t_row = ctk.CTkFrame(t_card, fg_color="transparent")
                t_row.pack(fill="x", padx=10, pady=(8, 4))
                
                title_text = t.get("title", "")
                ctk.CTkLabel(t_row, text=title_text, font=ctk.CTkFont(weight="bold", size=12), text_color="#fef08a", wraplength=380, justify="left").pack(side="left", padx=5)
                
                btn_c = ctk.CTkButton(
                    t_row, text="Copiar", width=88, height=26,
                    image=icon_manager.get_icon("copy", size=(12, 12), color="#ffffff"), compound="left",
                    font=ctk.CTkFont(size=11), fg_color="#16a34a", hover_color="#15803d"
                )
                btn_c.configure(command=lambda txt=title_text, b=btn_c: self._copy_to_clipboard(txt, b))
                btn_c.pack(side="right")

                style_t = t.get("style", "")
                why_t = t.get("why_works", "")
                sub_parts = []
                if style_t: sub_parts.append(f"Estilo: {style_t}")
                if why_t: sub_parts.append(f"Dica: {why_t}")
                if sub_parts:
                    ctk.CTkLabel(t_card, text=" | ".join(sub_parts), font=ctk.CTkFont(size=10), text_color="#a1a1aa", wraplength=460, justify="left").pack(anchor="w", padx=15, pady=(0, 6))

        # ── 3. Legendas para o Vídeo (Texto no Topo / Overlays) ──
        captions = data.get("video_captions") or data.get("captions") or []
        if captions:
            ctk.CTkLabel(self.right_scroll, text="Legendas para o Vídeo (Texto no Topo):", font=ctk.CTkFont(weight="bold", size=15), text_color="#fbbf24").pack(anchor="w", padx=5, pady=(14, 2))
            ctk.CTkLabel(self.right_scroll, text="Frases curtas e impactantes para colocar como texto sobreposto no topo do vídeo. Aumentam a retenção nos primeiros segundos!", font=ctk.CTkFont(size=11), text_color="#71717a").pack(anchor="w", padx=5, pady=(0, 6))

            for idx, c in enumerate(captions, 1):
                c_card = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color="#f59e0b")
                c_card.pack(fill="x", padx=5, pady=4)

                c_header = ctk.CTkFrame(c_card, fg_color="transparent")
                c_header.pack(fill="x", padx=12, pady=(8, 2))

                style_badge = c.get("style", "IMPACTO").upper()
                ctk.CTkLabel(c_header, text=f"Legenda {idx}  [{style_badge}]", font=ctk.CTkFont(size=12, weight="bold"), text_color="#fbbf24").pack(side="left")

                cap_text = c.get("text", "")
                btn_cp = ctk.CTkButton(
                    c_header, text="Copiar", width=88, height=26,
                    image=icon_manager.get_icon("copy", size=(12, 12), color="#ffffff"), compound="left",
                    font=ctk.CTkFont(size=11), fg_color="#16a34a", hover_color="#15803d"
                )
                btn_cp.configure(command=lambda txt=cap_text, b=btn_cp: self._copy_to_clipboard(txt, b))
                btn_cp.pack(side="right")

                # Texto de destaque em caixa alta e tamanho grande
                ctk.CTkLabel(c_card, text=f'"{cap_text.upper()}"', font=ctk.CTkFont(size=14, weight="bold"), text_color="#facc15", wraplength=460, justify="left").pack(anchor="w", padx=12, pady=(4, 2))

                why_c = c.get("why_viral", "")
                if why_c:
                    ctk.CTkLabel(c_card, text=f"Por que funciona: {why_c}", font=ctk.CTkFont(size=10), text_color="#a1a1aa", wraplength=460, justify="left").pack(anchor="w", padx=12, pady=(0, 8))

        # ── 4. Descrições Recomendadas (Padrão SEO YouTube Shorts) ──
        descriptions = data.get("descriptions", [])
        if descriptions:
            ctk.CTkLabel(
                self.right_scroll,
                text="Descrições Recomendadas (Padrão SEO & Storytelling):",
                font=ctk.CTkFont(weight="bold", size=15),
                text_color="#38bdf8"
            ).pack(anchor="w", padx=5, pady=(14, 2))
            ctk.CTkLabel(
                self.right_scroll,
                text="Descrições completas estruturadas para o feed de Shorts e algoritmo de busca do YouTube.",
                font=ctk.CTkFont(size=11),
                text_color="#71717a"
            ).pack(anchor="w", padx=5, pady=(0, 6))

            for idx, d in enumerate(descriptions, 1):
                d_card = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
                d_card.pack(fill="x", padx=5, pady=6)

                top_d = ctk.CTkFrame(d_card, fg_color="transparent")
                top_d.pack(fill="x", padx=12, pady=(10, 4))

                style_name = d.get("style", f"Opção {idx}")
                ctk.CTkLabel(top_d, text=f"OPÇÃO {idx}  [{style_name}]", font=ctk.CTkFont(weight="bold", size=12), text_color="#7dd3fc").pack(side="left")

                # Resolve texto completo pronto para colar
                full_text = d.get("full_caption", "")
                if not full_text:
                    parts = []
                    if d.get("first_line"):
                        parts.append(d.get("first_line"))
                    if d.get("body"):
                        parts.append(d.get("body"))
                    elif d.get("text"):
                        parts.append(d.get("text"))
                    if d.get("cta"):
                        parts.append(d.get("cta"))
                    if d.get("hashtags_inline"):
                        parts.append(d.get("hashtags_inline"))
                    full_text = "\n\n".join(p for p in parts if p)

                btn_copy_d = ctk.CTkButton(
                    top_d, text="Copiar Tudo", width=125, height=28,
                    image=icon_manager.get_icon("copy", size=(12, 12), color="#ffffff"), compound="left",
                    fg_color="#16a34a", hover_color="#15803d", font=ctk.CTkFont(size=11, weight="bold")
                )
                btn_copy_d.configure(command=lambda t=full_text, b=btn_copy_d: self._copy_to_clipboard(t, b, "Copiar Tudo"))
                btn_copy_d.pack(side="right")

                # Bloco 1: Primeira linha (antes do "ver mais")
                first_line = d.get("first_line", "")
                if first_line:
                    f_box = ctk.CTkFrame(d_card, fg_color="#18181b", corner_radius=6, border_width=1, border_color="#27272a")
                    f_box.pack(fill="x", padx=12, pady=(4, 4))
                    ctk.CTkLabel(
                        f_box, text=first_line,
                        font=ctk.CTkFont(size=12, weight="bold"), text_color="#fafafa",
                        wraplength=460, justify="left"
                    ).pack(anchor="w", padx=10, pady=(6, 2))
                    ctk.CTkLabel(
                        f_box, text="Primeira linha — aparece antes do \"ver mais\" no Shorts",
                        font=ctk.CTkFont(size=10), text_color="#71717a"
                    ).pack(anchor="w", padx=10, pady=(0, 6))

                # Bloco 2: Corpo / Descrição completa
                desc_lines = full_text.count("\n") + 2
                calc_height = max(110, min(240, desc_lines * 18))
                txt_desc = ctk.CTkTextbox(
                    d_card, height=calc_height, font=ctk.CTkFont(size=11),
                    fg_color="#09090b", border_width=1, border_color="#27272a"
                )
                txt_desc.pack(fill="x", padx=12, pady=(4, 6))
                txt_desc.insert("1.0", full_text)
                txt_desc.configure(state="disabled")

                # CTA & Por que funciona
                cta_val = d.get("cta", "")
                why_val = d.get("why_works", "")
                if cta_val:
                    ctk.CTkLabel(d_card, text=f"CTA: {cta_val}", font=ctk.CTkFont(size=10, weight="bold"), text_color="#38bdf8", wraplength=470, justify="left").pack(anchor="w", padx=12, pady=(0, 2))
                if why_val:
                    ctk.CTkLabel(d_card, text=f"Por que funciona: {why_val}", font=ctk.CTkFont(size=10), text_color="#71717a", wraplength=470, justify="left").pack(anchor="w", padx=12, pady=(0, 8))

        # ── 5. Comentários Sugeridos para Fixar ──
        comments = data.get("suggested_comments", [])
        if comments:
            ctk.CTkLabel(self.right_scroll, text="Comentários Sugeridos para Fixar no Vídeo:", font=ctk.CTkFont(weight="bold", size=15), text_color="#a78bfa").pack(anchor="w", padx=5, pady=(14, 2))
            ctk.CTkLabel(self.right_scroll, text="Cole esses comentários no YouTube e fixe no topo para incentivar respostas e aumentar o engajamento.", font=ctk.CTkFont(size=11), text_color="#71717a").pack(anchor="w", padx=5, pady=(0, 6))

            for idx, cm in enumerate(comments, 1):
                cm_box = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color=COLOR_CARD_BORDER)
                cm_box.pack(fill="x", padx=5, pady=5)

                top_cm = ctk.CTkFrame(cm_box, fg_color="transparent")
                top_cm.pack(fill="x", padx=10, pady=(6, 2))
                ctk.CTkLabel(top_cm, text=f"Comentário {idx}", font=ctk.CTkFont(weight="bold", size=12), text_color="#c4b5fd").pack(side="left")

                comm_text = cm.get("comment", "")
                btn_copy_cm = ctk.CTkButton(top_cm, text="Copiar Comentário", width=130, height=26, font=ctk.CTkFont(size=11), fg_color="#16a34a", hover_color="#15803d")
                btn_copy_cm.configure(command=lambda t=comm_text, b=btn_copy_cm: self._copy_to_clipboard(t, b, "Copiar Comentário"))
                btn_copy_cm.pack(side="right")

                txt_c_preview = ctk.CTkTextbox(cm_box, height=80, font=ctk.CTkFont(size=11))
                txt_c_preview.pack(fill="x", padx=10, pady=(4, 8))
                txt_c_preview.insert("1.0", comm_text)
                txt_c_preview.configure(state="disabled")

        # ── 6. Tags & Palavras-chave SEO ──
        tags = data.get("tags", [])
        if tags:
            tag_card = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
            tag_card.pack(fill="x", padx=5, pady=10)

            top_t = ctk.CTkFrame(tag_card, fg_color="transparent")
            top_t.pack(fill="x", padx=12, pady=(10, 4))
            ctk.CTkLabel(top_t, text="Tags & Palavras-chave SEO:", font=ctk.CTkFont(weight="bold", size=13), text_color="#34d399").pack(side="left")

            tags_joined = ", ".join(tags)
            btn_copy_tags = ctk.CTkButton(top_t, text="Copiar Tudo", width=100, height=26, fg_color="#10b981", hover_color="#059669", font=ctk.CTkFont(size=11))
            btn_copy_tags.configure(command=lambda t=tags_joined, b=btn_copy_tags: self._copy_to_clipboard(t, b, "Copiar Tudo"))
            btn_copy_tags.pack(side="right")

            ctk.CTkLabel(tag_card, text=tags_joined, font=ctk.CTkFont(size=12), text_color="#a7f3d0", wraplength=480).pack(anchor="w", padx=12, pady=(4, 4))
            ctk.CTkLabel(tag_card, text="Cole estas tags na seção de Tags/Keywords do YouTube Studio para impulsionar a pesquisa.", font=ctk.CTkFont(size=10), text_color="#71717a").pack(anchor="w", padx=12, pady=(0, 10))

        # ── 7. Sugestão de Trilha Sonora / OST (Se disponível) ──
        ost = data.get("ost_recommendation")
        if ost:
            ost_card = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color="#ec4899")
            ost_card.pack(fill="x", padx=5, pady=6)
            ctk.CTkLabel(ost_card, text="Sugestão de Trilha Sonora / OST:", font=ctk.CTkFont(weight="bold", size=13), text_color="#f472b6").pack(anchor="w", padx=12, pady=(10, 4))
            ost_text = ost if isinstance(ost, str) else (ost.get("song_name", "") + " - " + ost.get("why_fit", ""))
            ctk.CTkLabel(ost_card, text=ost_text, font=ctk.CTkFont(size=12), text_color="#fbcfe8", wraplength=480).pack(anchor="w", padx=12, pady=(0, 10))

        # ── 8. Roadmap de Melhorias de Edição ──
        roadmap = data.get("improvement_roadmap", [])
        if roadmap:
            rm_card = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
            rm_card.pack(fill="x", padx=5, pady=(4, 12))

            ctk.CTkLabel(rm_card, text="Sugestões de Edição para Viralizar:", font=ctk.CTkFont(weight="bold", size=13), text_color="#fb923c").pack(anchor="w", padx=12, pady=(10, 6))
            for item in roadmap:
                action = item.get("action", "")
                impact = str(item.get("impact", "")).strip()
                impact_color = "#ef4444" if "alto" in impact.lower() else ("#f59e0b" if "médio" in impact.lower() or "medio" in impact.lower() else "#10b981")

                r_row = ctk.CTkFrame(rm_card, fg_color="transparent")
                r_row.pack(fill="x", padx=12, pady=2)
                ctk.CTkLabel(r_row, text=f"[{impact.upper()}]" if impact else "[DICA]", font=ctk.CTkFont(weight="bold", size=10), text_color=impact_color, width=65).pack(side="left")
                ctk.CTkLabel(r_row, text=action, font=ctk.CTkFont(size=11), text_color="#d4d4d8", wraplength=400, justify="left").pack(side="left", padx=5)

            ctk.CTkFrame(rm_card, height=6, fg_color="transparent").pack()

    # ── Métodos de Criação e Interação com Thumbnail do Shorts (1080x1920) ──

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

        # Se já tiver análise com títulos, usa o título 1; senão gera limpo
        title = ""
        if hasattr(self, "analysis_data") and isinstance(self.analysis_data, dict):
            titles = self.analysis_data.get("titles", [])
            if titles:
                t = titles[0]
                title = t.get("title", "") if isinstance(t, dict) else str(t)

        try:
            if hasattr(self, "placeholder_frame") and self.placeholder_frame and self.placeholder_frame.winfo_exists():
                self.placeholder_frame.pack_forget()
        except Exception:
            pass

        self._reextract_thumb(timestamp_sec=sec, overlay_text=title)

    def _on_apply_title_to_thumb(self, title_text: str):
        """Aplica automaticamente o título clicado no A/B Testing para a miniatura."""
        if hasattr(self, "thumb_ent_text") and self.thumb_ent_text.winfo_exists():
            self.thumb_ent_text.delete(0, "end")
            self.thumb_ent_text.insert(0, title_text)
            self._trigger_thumb_update()

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
                out_path = str(p.parent / f"{p.stem}_capa_shorts_1080x1920.jpg")
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
                        self.btn_extract_thumb.configure(state="normal", text="Gerar Thumb")
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
                        self._log(f"🖼️ [THUMBNAIL 9:16] Capa gerada ({crop_mode}, {timestamp_sec:.2f}s): {os.path.basename(res)}")
                    else:
                        self._log(f"[ERRO] Falha ao extrair frame no tempo {timestamp_sec:.2f}s")
                        messagebox.showerror("Erro", f"Não foi possível extrair o frame no tempo {timestamp_sec:.2f}s.")

                self.after(0, _ui)
            except Exception as e:
                def _err():
                    if hasattr(self, "btn_update_thumb") and self.btn_update_thumb.winfo_exists():
                        self.btn_update_thumb.configure(state="normal", text="🔄 Atualizar Capa")
                    if hasattr(self, "btn_extract_thumb") and self.btn_extract_thumb.winfo_exists():
                        self.btn_extract_thumb.configure(state="normal", text="Gerar Thumb")
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
        try:
            if hasattr(self, "placeholder_frame") and self.placeholder_frame and self.placeholder_frame.winfo_exists():
                self.placeholder_frame.pack_forget()
        except Exception:
            pass

        # Remove card anterior se existir
        if hasattr(self, "_active_thumb_card") and self._active_thumb_card:
            try:
                if self._active_thumb_card.winfo_exists():
                    self._active_thumb_card.destroy()
            except Exception:
                pass
            self._active_thumb_card = None

        thumb_card = ctk.CTkFrame(self.right_scroll, fg_color="#141108", corner_radius=12, border_width=1, border_color="#f59e0b")
        thumb_card.pack(fill="x", padx=5, pady=(0, 10))
        self._active_thumb_card = thumb_card

        # Header do Card
        top_row = ctk.CTkFrame(thumb_card, fg_color="transparent")
        top_row.pack(fill="x", padx=14, pady=(10, 8))

        ctk.CTkLabel(
            top_row,
            text="🖼️ Estúdio de Thumbnails YouTube Shorts (1080x1920 Vertical 9:16)",
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
            # Preview proporcional vertical 9:16 (140 x 248)
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
            text="✍️ Título / Texto na Capa (Alto CTR):",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#fbbf24"
        ).pack(anchor="w", pady=(0, 2))

        # Dropdown de Títulos Rápidos da IA
        titles_opts = []
        titles_map = {}
        if hasattr(self, "analysis_data") and isinstance(self.analysis_data, dict):
            raw_titles = self.analysis_data.get("titles", [])
            for idx, t in enumerate(raw_titles[:5]):
                t_str = t.get("title", "") if isinstance(t, dict) else str(t)
                if t_str:
                    label = f"🏆 Título {idx+1}: {t_str[:38]}..."
                    titles_opts.append(label)
                    titles_map[label] = t_str
            hook_sugg = self.analysis_data.get("optimization", {}).get("suggested_hook", "")
            if hook_sugg:
                label_hook = f"🪝 Gancho 0-3s: {hook_sugg[:38]}..."
                titles_opts.append(label_hook)
                titles_map[label_hook] = hook_sugg

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

        # Slider de Pan Manual (declarado antes da função do segmented)
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

        # Botão Aplicar Atualização
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
            messagebox.showinfo("Copiado!", "Imagem da capa copiada para a área de transferência!\nVocê pode colar diretamente no navegador ou no YouTube Studio.")
        except Exception as e:
            messagebox.showwarning("Aviso", f"Não foi possível copiar diretamente para a área de transferência: {e}")

    def _save_thumb_as(self, thumb_path: str):
        """Abre diálogo para o usuário salvar a capa onde quiser."""
        if not thumb_path or not os.path.exists(thumb_path):
            return
        dest = filedialog.asksaveasfilename(
            title="Salvar Capa do Shorts Como",
            defaultextension=".jpg",
            filetypes=[("Imagem JPEG", "*.jpg"), ("Todos os arquivos", "*.*")],
            initialfile=os.path.basename(thumb_path)
        )
        if dest:
            try:
                shutil.copy2(thumb_path, dest)
                messagebox.showinfo("Salvo!", f"Capa do Shorts salva com sucesso em:\n{dest}")
            except Exception as e:
                messagebox.showerror("Erro", f"Falha ao salvar a imagem: {e}")
