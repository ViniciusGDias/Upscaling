"""
Aba Analisar YouTube Shorts para CustomTkinter.
Análise de retenção (viewed vs swiped), gancho 0-3s, 5 títulos otimizados, 3 descrições SEO,
tags, legendas/textos sobrepostos (video_captions), comentários sugeridos fixados e roadmap.
"""

import threading
import tkinter as tk
from tkinter import filedialog
import customtkinter as ctk
def _copy_text_to_clipboard(widget, text: str):
    try:
        import pyperclip
        pyperclip.copy(text)
    except Exception:
        widget.clipboard_clear()
        widget.clipboard_append(text)
        widget.update()

from social_analyzer import analyze_yt_shorts_video, get_video_info_fast

COLOR_BG_DARK = "#09090b"
COLOR_CARD = "#111113"
COLOR_CARD_BORDER = "#27272a"
COLOR_ACCENT = "#e2e8f0"       # off-white — principal action
COLOR_ACCENT_HOVER = "#a1a1aa"
COLOR_TEXT_MUTED = "#52525b"


class YTShortsAnalyzerTab(ctk.CTkFrame):
    def __init__(self, master, log_callback=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.log_callback = log_callback
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

        # ── Coluna Esquerda: Controles ──
        left_frame = ctk.CTkFrame(self, fg_color=COLOR_BG_DARK, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(5, 5), pady=5)
        left_frame.grid_columnconfigure(0, weight=1)

        # Cabeçalho
        header_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=(15, 10))
        ctk.CTkLabel(
            header_frame,
            text="▶️ Analisador YouTube Shorts",
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
            row_pick, text="📁 Procurar", width=90, height=32,
            fg_color="#16a34a", hover_color="#15803d",
            command=self._choose_video
        )
        self.btn_browse.pack(side="right")

        self.lbl_video_info = ctk.CTkLabel(file_box, text="Nenhum vídeo selecionado", font=ctk.CTkFont(size=11), text_color=COLOR_TEXT_MUTED)
        self.lbl_video_info.pack(anchor="w", padx=10, pady=(0, 8))

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

        # Idioma
        opt_row = ctk.CTkFrame(left_frame, fg_color="transparent")
        opt_row.pack(fill="x", padx=15, pady=2)
        self.chk_en = ctk.CTkCheckBox(opt_row, text="Gerar em Inglês (Audiência Global / US / IN)", font=ctk.CTkFont(size=12))
        self.chk_en.pack(side="left", pady=4)

        # Botão de Ação Principal
        self.btn_analyze = ctk.CTkButton(
            left_frame,
            text="🚀 Analisar Vídeo para YouTube Shorts",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            height=42,
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HOVER,
            command=self._start_analysis
        )
        self.btn_analyze.pack(fill="x", padx=15, pady=(10, 8))

        # Log
        ctk.CTkLabel(left_frame, text="Log de Execução:", font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_TEXT_MUTED).pack(anchor="w", padx=15, pady=(4, 2))
        self.log_textbox = ctk.CTkTextbox(left_frame, height=120, font=ctk.CTkFont(family="Consolas", size=11))
        self.log_textbox.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        self.log_textbox.configure(state="disabled")

        # ── Coluna Direita: Resultados Scrolláveis ──
        self.right_scroll = ctk.CTkScrollableFrame(self, fg_color=COLOR_BG_DARK, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
        self.right_scroll.grid(row=0, column=1, sticky="nsew", padx=(5, 5), pady=5)
        self.right_scroll.grid_columnconfigure(0, weight=1)

        self.placeholder_lbl = ctk.CTkLabel(
            self.right_scroll,
            text="Selecione um vídeo e clique em 'Analisar Vídeo para YouTube Shorts'\npara ver títulos, descrições SEO, tags, legendas de tela e ganchos.",
            font=ctk.CTkFont(size=14),
            text_color=COLOR_TEXT_MUTED,
            justify="center"
        )
        self.placeholder_lbl.pack(expand=True, pady=120)

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
            self._log(f"Vídeo carregado: {path} ({info['resolution']}, {info['duration_str']})")

    def _start_analysis(self):
        path = self.file_entry.get().strip()
        if not path:
            self._log("❌ Erro: Selecione um arquivo de vídeo primeiro.")
            return
        if self.is_analyzing:
            return

        self.is_analyzing = True
        self.btn_analyze.configure(state="disabled", text="⏳ Analisando Shorts...")
        category = self.opt_category.get().lower()
        anime = self.ent_anime.get().strip()
        character = self.ent_character.get().strip()
        language_en = bool(self.chk_en.get())

        def worker():
            try:
                res = analyze_yt_shorts_video(
                    path, category=category, character=character,
                    anime=anime, language_en=language_en, on_log=self._log, log_cb=self._log
                )
                self.after(0, lambda: self._render_results(res))
            except Exception as e:
                self._log(f"❌ Erro na análise: {str(e)}")
            finally:
                self.after(0, self._finish_analysis)

        threading.Thread(target=worker, daemon=True).start()

    def _on_category_change(self, choice):
        if choice == "Dorama":
            self.lbl_work.configure(text="Nome do Dorama:")
            self.ent_anime.configure(placeholder_text="Ex: Pousando no Amor, Vincenzo, Goblin...")
            self.lbl_char.configure(text="Personagem(ns):")
        elif choice == "Anime":
            self.lbl_work.configure(text="Nome do Anime:")
            self.ent_anime.configure(placeholder_text="Ex: Jujutsu Kaisen, One Piece, Naruto...")
            self.lbl_char.configure(text="Personagem:")
        else:
            self.lbl_work.configure(text="Tema / Obra:")
            self.ent_anime.configure(placeholder_text="Ex: Nome do canal, tema ou vídeo...")
            self.lbl_char.configure(text="Destaque:")

    def _finish_analysis(self):
        self.is_analyzing = False
        self.btn_analyze.configure(state="normal", text="🚀 Analisar Vídeo para YouTube Shorts")

    def _copy_to_clipboard(self, text: str, btn: ctk.CTkButton, original_text: str = "📋 Copiar"):
        _copy_text_to_clipboard(self, text)
        btn.configure(text="✅ Copiado!", fg_color="#10b981")
        self.after(1800, lambda: btn.configure(text=original_text, fg_color="#16a34a"))

    def _render_results(self, data: dict):
        for w in self.right_scroll.winfo_children():
            w.destroy()

        if not data or ("video_analysis" not in data and "optimization" not in data):
            err_box = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=8)
            err_box.pack(fill="x", padx=10, pady=10)
            ctk.CTkLabel(err_box, text="⚠️ Não foi possível processar a resposta.", text_color="#ef4444", font=ctk.CTkFont(weight="bold")).pack(pady=10)
            ctk.CTkLabel(err_box, text=str(data.get("raw_response", data)), wraplength=450).pack(pady=10)
            return

        # ── Badge de API Lore integrada ──
        if data.get("_enriched_context"):
            api_badge = ctk.CTkFrame(self.right_scroll, fg_color="#18181b", corner_radius=8, border_width=1, border_color="#ef4444")
            api_badge.pack(fill="x", padx=5, pady=(0, 8))
            ctk.CTkLabel(
                api_badge,
                text="⛩️  Metadados & Lore Integrados via API Oficial (Kitsu / MyAnimeList / TVMaze)",
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
        top_score.pack(fill="x", padx=15, pady=(12, 6))

        badge_color = "#10b981" if score >= 80 else ("#f59e0b" if score >= 65 else "#ef4444")
        ctk.CTkLabel(
            top_score,
            text=f"  POTENCIAL VIRAL SHORTS: {score}/100  ",
            font=ctk.CTkFont(weight="bold", size=14),
            fg_color=badge_color,
            text_color="#ffffff",
            corner_radius=6
        ).pack(side="left")

        ctk.CTkLabel(
            score_card,
            text=opt.get("viral_score_explanation", ""),
            font=ctk.CTkFont(size=12),
            text_color="#e4e4e7",
            wraplength=480,
            justify="left"
        ).pack(anchor="w", padx=15, pady=(0, 6))

        # Contexto do Personagem / Anime / Dorama
        char_ctx = va.get("character_context") or va.get("dorama_context")
        if char_ctx:
            ctx_box = ctk.CTkFrame(score_card, fg_color="#18181b", corner_radius=8, border_width=1, border_color="#27272a")
            ctx_box.pack(fill="x", padx=15, pady=(0, 8))
            is_dorama = "dorama" in self.opt_category.get().lower()
            ctx_title = "👤 Contexto do Personagem & Dorama:" if is_dorama else "👤 Contexto do Personagem & Anime:"
            ctk.CTkLabel(ctx_box, text=ctx_title, font=ctk.CTkFont(size=11, weight="bold"), text_color="#38bdf8").pack(anchor="w", padx=10, pady=(6, 2))
            ctk.CTkLabel(ctx_box, text=char_ctx, font=ctk.CTkFont(size=11), text_color="#d4d4d8", wraplength=460, justify="left").pack(anchor="w", padx=10, pady=(0, 6))

        # Gancho, Loop e Retenção
        hook_box = ctk.CTkFrame(score_card, fg_color="#18181b", corner_radius=8, border_width=1, border_color="#27272a")
        hook_box.pack(fill="x", padx=15, pady=(0, 12))
        
        ctk.CTkLabel(hook_box, text=f"🪝 Gancho 0-3s: {opt.get('hook_quality', '')}", font=ctk.CTkFont(size=11), text_color="#38bdf8", wraplength=460, justify="left").pack(anchor="w", padx=10, pady=(6, 2))
        ctk.CTkLabel(hook_box, text=f"💡 Gancho Sugerido: {opt.get('suggested_hook', '')}", font=ctk.CTkFont(size=11, weight="bold"), text_color="#facc15", wraplength=460, justify="left").pack(anchor="w", padx=10, pady=2)
        if opt.get("loop_strategy"):
            ctk.CTkLabel(hook_box, text=f"🔁 Loop Infinito: {opt.get('loop_strategy', '')}", font=ctk.CTkFont(size=11), text_color="#a855f7", wraplength=460, justify="left").pack(anchor="w", padx=10, pady=(2, 6))

        # ── 2. Títulos Otimizados para Shorts ──
        titles = data.get("titles", [])
        if titles:
            ctk.CTkLabel(self.right_scroll, text="✍️ 5 Títulos com Alto CTR (#shorts):", font=ctk.CTkFont(weight="bold", size=15), text_color="#f87171").pack(anchor="w", padx=5, pady=(10, 4))
            for idx, t in enumerate(titles, 1):
                t_card = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color=COLOR_CARD_BORDER)
                t_card.pack(fill="x", padx=5, pady=4)
                
                t_row = ctk.CTkFrame(t_card, fg_color="transparent")
                t_row.pack(fill="x", padx=10, pady=(8, 4))
                
                title_text = t.get("title", "")
                ctk.CTkLabel(t_row, text=title_text, font=ctk.CTkFont(weight="bold", size=12), text_color="#fef08a", wraplength=380, justify="left").pack(side="left", padx=5)
                
                btn_c = ctk.CTkButton(t_row, text="📋 Copiar", width=80, height=26, font=ctk.CTkFont(size=11), fg_color="#16a34a", hover_color="#15803d")
                btn_c.configure(command=lambda txt=title_text, b=btn_c: self._copy_to_clipboard(txt, b))
                btn_c.pack(side="right")

                style_t = t.get("style", "")
                why_t = t.get("why_works", "")
                sub_parts = []
                if style_t: sub_parts.append(f"Estilo: {style_t}")
                if why_t: sub_parts.append(f"💡 {why_t}")
                if sub_parts:
                    ctk.CTkLabel(t_card, text=" | ".join(sub_parts), font=ctk.CTkFont(size=10), text_color="#a1a1aa", wraplength=460, justify="left").pack(anchor="w", padx=15, pady=(0, 6))

        # ── 3. Legendas para o Vídeo (Texto no Topo / Overlays) ──
        captions = data.get("video_captions") or data.get("captions") or []
        if captions:
            ctk.CTkLabel(self.right_scroll, text="🎬 Legendas para o Vídeo (Texto no Topo):", font=ctk.CTkFont(weight="bold", size=15), text_color="#fbbf24").pack(anchor="w", padx=5, pady=(14, 2))
            ctk.CTkLabel(self.right_scroll, text="⭐ Frases curtas e impactantes para colocar como texto sobreposto no topo do vídeo. Aumentam a retenção nos primeiros segundos!", font=ctk.CTkFont(size=11), text_color="#71717a").pack(anchor="w", padx=5, pady=(0, 6))

            for idx, c in enumerate(captions, 1):
                c_card = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color="#f59e0b")
                c_card.pack(fill="x", padx=5, pady=4)

                c_header = ctk.CTkFrame(c_card, fg_color="transparent")
                c_header.pack(fill="x", padx=12, pady=(8, 2))

                style_badge = c.get("style", "IMPACTO").upper()
                ctk.CTkLabel(c_header, text=f"💥 Legenda {idx}  [{style_badge}]", font=ctk.CTkFont(size=12, weight="bold"), text_color="#fbbf24").pack(side="left")

                cap_text = c.get("text", "")
                btn_cp = ctk.CTkButton(c_header, text="📋 Copiar", width=80, height=26, font=ctk.CTkFont(size=11), fg_color="#16a34a", hover_color="#15803d")
                btn_cp.configure(command=lambda txt=cap_text, b=btn_cp: self._copy_to_clipboard(txt, b))
                btn_cp.pack(side="right")

                # Texto de destaque em caixa alta e tamanho grande
                ctk.CTkLabel(c_card, text=f'"{cap_text.upper()}"', font=ctk.CTkFont(size=14, weight="bold"), text_color="#facc15", wraplength=460, justify="left").pack(anchor="w", padx=12, pady=(4, 2))

                why_c = c.get("why_viral", "")
                if why_c:
                    ctk.CTkLabel(c_card, text=f"💡 Por que funciona: {why_c}", font=ctk.CTkFont(size=10), text_color="#a1a1aa", wraplength=460, justify="left").pack(anchor="w", padx=12, pady=(0, 8))

        # ── 4. Descrições Recomendadas (Padrão SEO YouTube Shorts) ──
        descriptions = data.get("descriptions", [])
        if descriptions:
            ctk.CTkLabel(
                self.right_scroll,
                text="📝 Descrições Recomendadas (Padrão SEO & Storytelling):",
                font=ctk.CTkFont(weight="bold", size=15),
                text_color="#38bdf8"
            ).pack(anchor="w", padx=5, pady=(14, 2))
            ctk.CTkLabel(
                self.right_scroll,
                text="💡 Descrições completas estruturadas para o feed de Shorts e algoritmo de busca do YouTube.",
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
                    top_d, text="📋 Copiar Tudo", width=120, height=28,
                    fg_color="#16a34a", hover_color="#15803d", font=ctk.CTkFont(size=11, weight="bold")
                )
                btn_copy_d.configure(command=lambda t=full_text, b=btn_copy_d: self._copy_to_clipboard(t, b, "📋 Copiar Tudo"))
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
                        f_box, text="👆 Primeira linha — aparece antes do \"ver mais\" no Shorts",
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
                    ctk.CTkLabel(d_card, text=f"👉 CTA: {cta_val}", font=ctk.CTkFont(size=10, weight="bold"), text_color="#38bdf8", wraplength=470, justify="left").pack(anchor="w", padx=12, pady=(0, 2))
                if why_val:
                    ctk.CTkLabel(d_card, text=f"💡 Por que funciona: {why_val}", font=ctk.CTkFont(size=10), text_color="#71717a", wraplength=470, justify="left").pack(anchor="w", padx=12, pady=(0, 8))

        # ── 5. Comentários Sugeridos para Fixar ──
        comments = data.get("suggested_comments", [])
        if comments:
            ctk.CTkLabel(self.right_scroll, text="💬 Comentários Sugeridos para Fixar no Vídeo:", font=ctk.CTkFont(weight="bold", size=15), text_color="#a78bfa").pack(anchor="w", padx=5, pady=(14, 2))
            ctk.CTkLabel(self.right_scroll, text="💡 Cole esses comentários no YouTube e fixe no topo para incentivar respostas e aumentar o engajamento.", font=ctk.CTkFont(size=11), text_color="#71717a").pack(anchor="w", padx=5, pady=(0, 6))

            for idx, cm in enumerate(comments, 1):
                cm_box = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color=COLOR_CARD_BORDER)
                cm_box.pack(fill="x", padx=5, pady=5)

                top_cm = ctk.CTkFrame(cm_box, fg_color="transparent")
                top_cm.pack(fill="x", padx=10, pady=(6, 2))
                ctk.CTkLabel(top_cm, text=f"💬 Comentário {idx}", font=ctk.CTkFont(weight="bold", size=12), text_color="#c4b5fd").pack(side="left")

                comm_text = cm.get("comment", "")
                btn_copy_cm = ctk.CTkButton(top_cm, text="📋 Copiar Comentário", width=130, height=26, font=ctk.CTkFont(size=11), fg_color="#16a34a", hover_color="#15803d")
                btn_copy_cm.configure(command=lambda t=comm_text, b=btn_copy_cm: self._copy_to_clipboard(t, b, "📋 Copiar Comentário"))
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
            ctk.CTkLabel(top_t, text="#️⃣ Tags & Palavras-chave SEO:", font=ctk.CTkFont(weight="bold", size=13), text_color="#34d399").pack(side="left")

            tags_joined = ", ".join(tags)
            btn_copy_tags = ctk.CTkButton(top_t, text="📋 Copiar Tudo", width=100, height=26, fg_color="#10b981", hover_color="#059669", font=ctk.CTkFont(size=11))
            btn_copy_tags.configure(command=lambda t=tags_joined, b=btn_copy_tags: self._copy_to_clipboard(t, b, "📋 Copiar Tudo"))
            btn_copy_tags.pack(side="right")

            ctk.CTkLabel(tag_card, text=tags_joined, font=ctk.CTkFont(size=12), text_color="#a7f3d0", wraplength=480).pack(anchor="w", padx=12, pady=(4, 4))
            ctk.CTkLabel(tag_card, text="Cole estas tags na seção de Tags/Keywords do YouTube Studio para impulsionar a pesquisa.", font=ctk.CTkFont(size=10), text_color="#71717a").pack(anchor="w", padx=12, pady=(0, 10))

        # ── 7. Sugestão de Trilha Sonora / OST (Se disponível) ──
        ost = data.get("ost_recommendation")
        if ost:
            ost_card = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color="#ec4899")
            ost_card.pack(fill="x", padx=5, pady=6)
            ctk.CTkLabel(ost_card, text="🎵 Sugestão de Trilha Sonora / OST:", font=ctk.CTkFont(weight="bold", size=13), text_color="#f472b6").pack(anchor="w", padx=12, pady=(10, 4))
            ost_text = ost if isinstance(ost, str) else (ost.get("song_name", "") + " - " + ost.get("why_fit", ""))
            ctk.CTkLabel(ost_card, text=ost_text, font=ctk.CTkFont(size=12), text_color="#fbcfe8", wraplength=480).pack(anchor="w", padx=12, pady=(0, 10))

        # ── 8. Roadmap de Melhorias de Edição ──
        roadmap = data.get("improvement_roadmap", [])
        if roadmap:
            rm_card = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
            rm_card.pack(fill="x", padx=5, pady=(4, 12))

            ctk.CTkLabel(rm_card, text="🛠️ Sugestões de Edição para Viralizar:", font=ctk.CTkFont(weight="bold", size=13), text_color="#fb923c").pack(anchor="w", padx=12, pady=(10, 6))
            for item in roadmap:
                action = item.get("action", "")
                impact = str(item.get("impact", "")).strip()
                impact_color = "#ef4444" if "alto" in impact.lower() else ("#f59e0b" if "médio" in impact.lower() or "medio" in impact.lower() else "#10b981")

                r_row = ctk.CTkFrame(rm_card, fg_color="transparent")
                r_row.pack(fill="x", padx=12, pady=2)
                ctk.CTkLabel(r_row, text=f"[{impact.upper()}]" if impact else "[DICA]", font=ctk.CTkFont(weight="bold", size=10), text_color=impact_color, width=65).pack(side="left")
                ctk.CTkLabel(r_row, text=action, font=ctk.CTkFont(size=11), text_color="#d4d4d8", wraplength=400, justify="left").pack(side="left", padx=5)

            ctk.CTkFrame(rm_card, height=6, fg_color="transparent").pack()
