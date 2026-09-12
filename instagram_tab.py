"""
Aba Analisar Instagram para CustomTkinter.
Análise estética, retenção, compartilhamento (DM), salvamentos, legendas completas e hashtags.
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

from social_analyzer import analyze_instagram_video, get_video_info_fast

COLOR_BG_DARK = "#09090b"
COLOR_CARD = "#111113"
COLOR_CARD_BORDER = "#27272a"
COLOR_ACCENT = "#e2e8f0"       # off-white — principal action
COLOR_ACCENT_HOVER = "#a1a1aa" # muted silver
COLOR_TEXT_MUTED = "#52525b"   # zinc-600
COLOR_BTN_COPY = "#18181b"     # dark ghost button
COLOR_BTN_COPY_BORDER = "#3f3f46"
COLOR_SUCCESS = "#22c55e"


class InstagramAnalyzerTab(ctk.CTkFrame):
    def __init__(self, master, log_callback=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.log_callback = log_callback
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

        # ── Coluna Esquerda: Controles ──
        left_frame = ctk.CTkFrame(self, fg_color=COLOR_BG_DARK, corner_radius=8, border_width=1, border_color=COLOR_CARD_BORDER)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(5, 5), pady=5)
        left_frame.grid_columnconfigure(0, weight=1)

        # Cabeçalho
        header_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=(15, 10))
        ctk.CTkLabel(
            header_frame,
            text="Analisar Instagram Reels",
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
            row_pick, text="Procurar", width=85, height=34,
            fg_color="#18181b", hover_color="#27272a",
            border_width=1, border_color="#3f3f46",
            text_color="#e2e8f0", font=ctk.CTkFont(size=11),
            corner_radius=6,
            command=self._choose_video
        )
        self.btn_browse.pack(side="right")

        self.lbl_video_info = ctk.CTkLabel(file_box, text="Nenhum vídeo selecionado", font=ctk.CTkFont(size=11), text_color="#3f3f46")
        # Obra / Anime / Dorama (Opcional - busca via API)
        work_box = ctk.CTkFrame(left_frame, fg_color="transparent")
        work_box.pack(fill="x", padx=15, pady=(10, 0))

        row_work_lbl = ctk.CTkFrame(work_box, fg_color="transparent")
        row_work_lbl.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            row_work_lbl, text="⛩️ Nome do Anime / Dorama (Opcional):",
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#71717a"
        ).pack(side="left")
        ctk.CTkLabel(
            row_work_lbl, text="⚡ Lore via API",
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

        # Contexto do Criador
        ctx_box = ctk.CTkFrame(left_frame, fg_color="transparent")
        ctx_box.pack(fill="x", padx=15, pady=(10, 0))

        ctk.CTkLabel(ctx_box, text="Contexto Adicional (Opcional)", font=ctk.CTkFont(size=11, weight="bold"), text_color="#71717a").pack(anchor="w", pady=(0, 4))
        self.txt_context = ctk.CTkTextbox(
            ctx_box, height=55, font=ctk.CTkFont(size=11),
            fg_color="#111113", border_color="#27272a", border_width=1,
            text_color="#d4d4d8"
        )
        self.txt_context.pack(fill="x")
        self.txt_context.insert("1.0", "Ex: anime edit do Gojo, público jovem/otaku.")

        # Opções extras
        opt_row = ctk.CTkFrame(left_frame, fg_color="transparent")
        opt_row.pack(fill="x", padx=15, pady=(8, 0))
        
        self.chk_en = ctk.CTkCheckBox(
            opt_row, text="Gerar em Inglês (US / IN)",
            font=ctk.CTkFont(size=11),
            text_color="#71717a",
            border_color="#3f3f46",
            fg_color="#3f3f46",
            hover_color="#52525b",
            checkmark_color="#fafafa"
        )
        self.chk_en.pack(side="left", pady=4)

        # Botão de Ação Principal
        self.btn_analyze = ctk.CTkButton(
            left_frame,
            text="Analisar para Instagram",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            height=38,
            fg_color="#18181b",
            hover_color="#27272a",
            border_width=1,
            border_color="#52525b",
            text_color="#fafafa",
            corner_radius=6,
            command=self._start_analysis
        )
        self.btn_analyze.pack(fill="x", padx=15, pady=(10, 8))

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

        self.placeholder_lbl = ctk.CTkLabel(
            self.right_scroll,
            text="Selecione um vídeo e analise para ver\ndiagnósticos, legendas e hashtags.",
            font=ctk.CTkFont(size=13),
            text_color="#27272a",
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
        self.btn_analyze.configure(state="disabled", text="⏳ Analisando Vídeo...")
        work_name = self.ent_work_name.get().strip() if hasattr(self, 'ent_work_name') else ""
        context = self.txt_context.get("1.0", "end").strip()
        if context == "Ex: anime edit do Gojo, público jovem/otaku.":
            context = ""
        language_en = bool(self.chk_en.get())

        def worker():
            try:
                res = analyze_instagram_video(
                    path,
                    context=context,
                    work_name=work_name,
                    language_en=language_en,
                    on_log=self._log,
                    log_cb=self._log
                )
                self.after(0, lambda: self._render_results(res))
            except Exception as e:
                self._log(f"❌ Erro na análise: {str(e)}")
            finally:
                self.after(0, self._finish_analysis)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_analysis(self):
        self.is_analyzing = False
        self.btn_analyze.configure(state="normal", text="✨ Analisar Vídeo para Instagram")

    def _copy_to_clipboard(self, text: str, btn: ctk.CTkButton, original_text: str = "📋 Copiar"):
        _copy_text_to_clipboard(self, text)
        btn.configure(text="✅ Copiado!", fg_color="#10b981")
        self.after(1800, lambda: btn.configure(text=original_text, fg_color="#3b82f6"))

    def _render_results(self, data: dict):
        # Limpa área da direita
        for w in self.right_scroll.winfo_children():
            w.destroy()

        if not data or "video_analysis" not in data:
            err_box = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=8)
            err_box.pack(fill="x", padx=10, pady=10)
            ctk.CTkLabel(err_box, text="⚠️ Não foi possível processar a análise em JSON.", text_color="#ef4444", font=ctk.CTkFont(weight="bold")).pack(pady=10)
            ctk.CTkLabel(err_box, text=str(data.get("raw_response", data)), wraplength=450).pack(pady=10)
            return

        # ── Badge de API Lore integrada ──
        if data.get("_enriched_context"):
            api_badge = ctk.CTkFrame(self.right_scroll, fg_color="#18181b", corner_radius=8, border_width=1, border_color="#22c55e")
            api_badge.pack(fill="x", padx=5, pady=(0, 8))
            ctk.CTkLabel(
                api_badge,
                text="⛩️  Metadados & Lore Integrados via API Oficial (Kitsu / MyAnimeList / TVMaze)",
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
        top_score_row.pack(fill="x", padx=15, pady=(12, 6))

        # Badge com nota
        badge_color = "#10b981" if score >= 80 else ("#f59e0b" if score >= 65 else "#ef4444")
        ctk.CTkLabel(
            top_score_row,
            text=f"  POTENCIAL VIRAL: {score}/100  ",
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
        ).pack(anchor="w", padx=15, pady=(0, 10))

        # Detalhes de Estética, Shares e Saves
        metrics_frame = ctk.CTkFrame(score_card, fg_color="#1f1f23", corner_radius=8)
        metrics_frame.pack(fill="x", padx=15, pady=(0, 12))

        m1 = f"🎨 Estética: {va.get('aesthetic_quality', 'N/A')}"
        m2 = f"↗️ Compartilhamento (DM): {va.get('shareability_factor', 'N/A')}"
        m3 = f"💾 Salvamentos: {va.get('saveability_factor', 'N/A')}"
        
        for m in [m1, m2, m3]:
            ctk.CTkLabel(metrics_frame, text=m, font=ctk.CTkFont(size=11), text_color="#d4d4d8").pack(anchor="w", padx=10, pady=2)

        # ── Gancho e Loop ──
        hook_card = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
        hook_card.pack(fill="x", padx=5, pady=6)
        
        ctk.CTkLabel(hook_card, text="🪝 Gancho dos Primeiros 2 Segundos:", font=ctk.CTkFont(weight="bold", size=13), text_color="#38bdf8").pack(anchor="w", padx=15, pady=(10, 4))
        ctk.CTkLabel(hook_card, text=f"• Análise Atual: {opt.get('hook_quality', '')}", font=ctk.CTkFont(size=12), wraplength=480, justify="left").pack(anchor="w", padx=15, pady=2)
        ctk.CTkLabel(hook_card, text=f"• Sugestão de Gancho: {opt.get('suggested_hook', '')}", font=ctk.CTkFont(size=12, weight="bold"), text_color="#facc15", wraplength=480, justify="left").pack(anchor="w", padx=15, pady=2)
        
        if opt.get("loop_strategy"):
            ctk.CTkLabel(hook_card, text="🔁 Estratégia de Loop Invisível:", font=ctk.CTkFont(weight="bold", size=13), text_color="#a855f7").pack(anchor="w", padx=15, pady=(8, 4))
            ctk.CTkLabel(hook_card, text=opt.get("loop_strategy", ""), font=ctk.CTkFont(size=12), wraplength=480, justify="left").pack(anchor="w", padx=15, pady=(0, 10))

        # ── Legendas Virais (Captions) ──
        captions = data.get("captions", [])
        if captions:
            ctk.CTkLabel(self.right_scroll, text="📝 3 Opções de Legendas Prontas para Copiar:", font=ctk.CTkFont(weight="bold", size=15), text_color="#ec4899").pack(anchor="w", padx=5, pady=(12, 6))

            for idx, c in enumerate(captions, 1):
                c_box = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
                c_box.pack(fill="x", padx=5, pady=5)

                top_c = ctk.CTkFrame(c_box, fg_color="transparent")
                top_c.pack(fill="x", padx=12, pady=(10, 4))

                ctk.CTkLabel(top_c, text=f"Opção {idx}", font=ctk.CTkFont(weight="bold", size=13), text_color="#f472b6").pack(side="left")

                full_text = f"{c.get('first_line', '')}\n\n{c.get('body', '')}\n\n{c.get('cta', '')}"
                
                btn_copy_cap = ctk.CTkButton(
                    top_c, text="📋 Copiar Legenda", width=120, height=28,
                    fg_color="#3b82f6", hover_color="#2563eb", font=ctk.CTkFont(size=11, weight="bold")
                )
                btn_copy_cap.configure(command=lambda t=full_text, b=btn_copy_cap: self._copy_to_clipboard(t, b, "📋 Copiar Legenda"))
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
            ctk.CTkLabel(top_h, text="#️⃣ Hashtags Estratégicas (3-5 Tags Ideais):", font=ctk.CTkFont(weight="bold", size=13), text_color="#34d399").pack(side="left")

            tags_joined = " ".join(recommended_tags)
            btn_copy_tags = ctk.CTkButton(
                top_h, text="📋 Copiar Tags", width=100, height=28,
                fg_color="#10b981", hover_color="#059669", font=ctk.CTkFont(size=11, weight="bold")
            )
            btn_copy_tags.configure(command=lambda t=tags_joined, b=btn_copy_tags: self._copy_to_clipboard(t, b, "📋 Copiar Tags"))
            btn_copy_tags.pack(side="right")

            ctk.CTkLabel(h_card, text=tags_joined, font=ctk.CTkFont(size=13, weight="bold"), text_color="#6ee7b7", wraplength=480).pack(anchor="w", padx=12, pady=4)
            if hs.get("explanation"):
                ctk.CTkLabel(h_card, text=hs.get("explanation", ""), font=ctk.CTkFont(size=11), text_color=COLOR_TEXT_MUTED, wraplength=480).pack(anchor="w", padx=12, pady=(0, 10))

        # ── Recomendação de Áudio ──
        if data.get("audio_recommendation"):
            a_card = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
            a_card.pack(fill="x", padx=5, pady=6)
            ctk.CTkLabel(a_card, text="🎵 Recomendação de Áudio e Trilha:", font=ctk.CTkFont(weight="bold", size=13), text_color="#f59e0b").pack(anchor="w", padx=12, pady=(8, 4))
            ctk.CTkLabel(a_card, text=data.get("audio_recommendation", ""), font=ctk.CTkFont(size=12), wraplength=480, justify="left").pack(anchor="w", padx=12, pady=(0, 10))
