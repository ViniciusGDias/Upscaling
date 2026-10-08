"""
Aba Anime Finder para CustomTkinter.
Busca inteligente de animes e episódios exatos com alto potencial viral,
além de chat interativo para tirar dúvidas com o especialista em anime.
"""

import threading
import urllib.parse
import webbrowser
import icon_manager
import customtkinter as ctk
def _copy_text_to_clipboard(widget, text: str):
    try:
        import pyperclip
        pyperclip.copy(text)
    except Exception:
        widget.clipboard_clear()
        widget.clipboard_append(text)
        widget.update()

from anime_finder_ai import search_animes, ask_anime_followup, search_episodes

COLOR_BG_DARK = "#09090b"
COLOR_CARD = "#111113"
COLOR_CARD_BORDER = "#27272a"
COLOR_ACCENT = "#e2e8f0"       # off-white — principal action
COLOR_ACCENT_HOVER = "#a1a1aa"
COLOR_TEXT_MUTED = "#52525b"


class AnimeFinderTab(ctk.CTkFrame):
    def __init__(self, master, log_callback=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.log_callback = log_callback
        self.current_results = None
        self.chat_history = []
        self.is_processing = False
        self.seen_episodes = {}  # {obra_key: [list of episode numbers/labels]}
        self.used_episodes = {}  # {obra_key: set(episode numbers/labels marked as used)}
        self.seen_animes = []    # [list of anime names seen in style search]

        self._build_ui()

    def _log(self, msg: str):
        if self.log_callback:
            self.log_callback(f"[Anime Finder] {msg}")

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=4)
        self.grid_columnconfigure(1, weight=6)
        self.grid_rowconfigure(0, weight=1)

        # ── Coluna Esquerda: Filtros e Controles ──
        left_frame = ctk.CTkFrame(self, fg_color=COLOR_BG_DARK, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(5, 5), pady=5)
        left_frame.grid_columnconfigure(0, weight=1)

        # Cabeçalho
        header_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=(15, 8))
        ctk.CTkLabel(
            header_frame,
            text=" Anime & Episode Finder",
            image=icon_manager.get_icon("search", size=(20, 20), color="#10b981"), compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color="#c084fc"
        ).pack(anchor="w")
        ctk.CTkLabel(
            header_frame,
            text="Encontre animes e episódios exatos com momentos icônicos e virais para criar cortes.",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLOR_TEXT_MUTED,
            wraplength=380,
            justify="left"
        ).pack(anchor="w", pady=(2, 0))

        # Alternador de Modo (Busca por Estilo vs Busca por Obra Específica)
        self.mode_selector = ctk.CTkSegmentedButton(
            left_frame,
            values=["Por Estilo / Nicho", "Episódios de uma Obra"],
            command=self._on_mode_change,
            height=32,
            font=ctk.CTkFont(weight="bold", size=12),
            selected_color="#9333ea",
            selected_hover_color="#7e22ce"
        )
        self.mode_selector.set("Por Estilo / Nicho")
        self.mode_selector.pack(fill="x", padx=15, pady=(5, 10))

        # Container dos Filtros Dinâmicos
        self.filters_container = ctk.CTkFrame(left_frame, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color=COLOR_CARD_BORDER)
        self.filters_container.pack(fill="x", padx=15, pady=5)

        self._build_style_filters()

        # Botão de Busca
        self.btn_search = ctk.CTkButton(
            left_frame,
            text="Buscar Animes e Cenas Virais",
            image=icon_manager.get_icon("search", size=(14, 14), color="#09090b"), compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            height=42,
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HOVER,
            command=self._start_search
        )
        self.btn_search.pack(fill="x", padx=15, pady=(12, 10))

        # ── Chat de Dúvidas / Follow-up ──
        chat_box = ctk.CTkFrame(left_frame, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color=COLOR_CARD_BORDER)
        chat_box.pack(fill="both", expand=True, padx=15, pady=(5, 15))
        chat_box.grid_columnconfigure(0, weight=1)
        chat_box.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(chat_box, text="Dúvidas sobre o Anime / Cenas?", font=ctk.CTkFont(weight="bold", size=13), text_color="#e9d5ff").grid(row=0, column=0, sticky="w", padx=10, pady=(8, 4))
        
        self.txt_chat_history = ctk.CTkTextbox(chat_box, font=ctk.CTkFont(size=11), wrap="word")
        self.txt_chat_history.grid(row=1, column=0, sticky="nsew", padx=10, pady=4)
        self.txt_chat_history.insert("1.0", "Assistente Anime: Faça uma busca para começar, ou pergunte detalhes sobre qualquer cena!\n\n")
        self.txt_chat_history.configure(state="disabled")

        row_input = ctk.CTkFrame(chat_box, fg_color="transparent")
        row_input.grid(row=2, column=0, sticky="ew", padx=10, pady=(4, 8))
        row_input.grid_columnconfigure(0, weight=1)

        self.ent_chat = ctk.CTkEntry(row_input, placeholder_text="Pergunte algo ex: Qual minuto dessa cena?", height=30)
        self.ent_chat.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.ent_chat.bind("<Return>", lambda e: self._send_followup())

        self.btn_send_chat = ctk.CTkButton(row_input, text="Enviar", width=70, height=30, fg_color="#16a34a", hover_color="#15803d", command=self._send_followup)
        self.btn_send_chat.grid(row=0, column=1)

        # ── Coluna Direita: Resultados Scrolláveis ──
        self.right_scroll = ctk.CTkScrollableFrame(self, fg_color=COLOR_BG_DARK, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
        self.right_scroll.grid(row=0, column=1, sticky="nsew", padx=(5, 5), pady=5)
        self.right_scroll.grid_columnconfigure(0, weight=1)

        self.placeholder_lbl = ctk.CTkLabel(
            self.right_scroll,
            text="Configure sua busca na esquerda e clique em 'Buscar'\npara ver animes, números exatos de episódios, termos de pesquisa e links rápidos.",
            font=ctk.CTkFont(size=14),
            text_color=COLOR_TEXT_MUTED,
            justify="center"
        )
        self.placeholder_lbl.pack(expand=True, pady=120)

    def _on_mode_change(self, value):
        for w in self.filters_container.winfo_children():
            w.destroy()
        if value == "Por Estilo / Nicho":
            self._build_style_filters()
            self.btn_search.configure(text="Buscar Animes e Cenas Virais")
        else:
            self._build_episode_filters()
            self.btn_search.configure(text="Buscar Episódios da Obra")

    def _build_style_filters(self):
        f = self.filters_container

        ctk.CTkLabel(f, text="O que você quer postar?", font=ctk.CTkFont(weight="bold", size=13)).pack(anchor="w", padx=10, pady=(8, 2))
        self.txt_query = ctk.CTkTextbox(f, height=60, font=ctk.CTkFont(size=12))
        self.txt_query.pack(fill="x", padx=10, pady=(0, 6))
        self.txt_query.insert("1.0", "Lutas épicas com transformação, momento de aura e determinação extrema.")

        # Grid de Opções
        row1 = ctk.CTkFrame(f, fg_color="transparent")
        row1.pack(fill="x", padx=10, pady=2)
        ctk.CTkLabel(row1, text="Gênero:", font=ctk.CTkFont(size=12), width=75).pack(side="left")
        self.opt_genre = ctk.CTkOptionMenu(row1, values=["Todos", "Ação / Shonen", "Romance / Drama", "Comédia / Humor", "Sobrenatural / Suspense", "Isekai", "Seinen"], height=28)
        self.opt_genre.pack(side="left", fill="x", expand=True)

        row2 = ctk.CTkFrame(f, fg_color="transparent")
        row2.pack(fill="x", padx=10, pady=2)
        ctk.CTkLabel(row2, text="Rede Alvo:", font=ctk.CTkFont(size=12), width=75).pack(side="left")
        self.opt_platform = ctk.CTkOptionMenu(row2, values=["Todas (TikTok, Shorts, Reels)", "YouTube Shorts", "TikTok", "Instagram Reels"], height=28)
        self.opt_platform.pack(side="left", fill="x", expand=True)

        row3 = ctk.CTkFrame(f, fg_color="transparent")
        row3.pack(fill="x", padx=10, pady=2)
        ctk.CTkLabel(row3, text="Popularidade:", font=ctk.CTkFont(size=12), width=75).pack(side="left")
        self.opt_popularity = ctk.CTkOptionMenu(row3, values=["Qualquer uma", "Mainstream (Mais Famosos)", "Populares", "Joias Escondidas (Pouco Usados)"], height=28)
        self.opt_popularity.pack(side="left", fill="x", expand=True)

        row4 = ctk.CTkFrame(f, fg_color="transparent")
        row4.pack(fill="x", padx=10, pady=(2, 8))
        ctk.CTkLabel(row4, text="Época:", font=ctk.CTkFont(size=12), width=75).pack(side="left")
        self.opt_era = ctk.CTkOptionMenu(row4, values=["Qualquer época", "Novos (2020+)", "Modernos (2010-2019)", "Clássicos (Antes de 2010)"], height=28)
        self.opt_era.pack(side="left", fill="x", expand=True)

    def _build_episode_filters(self):
        f = self.filters_container

        row_cat = ctk.CTkFrame(f, fg_color="transparent")
        row_cat.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(row_cat, text="Categoria:", font=ctk.CTkFont(size=12), width=75).pack(side="left")
        self.opt_ep_cat = ctk.CTkOptionMenu(row_cat, values=["Anime", "Dorama"], height=28)
        self.opt_ep_cat.pack(side="left", fill="x", expand=True)

        row_name = ctk.CTkFrame(f, fg_color="transparent")
        row_name.pack(fill="x", padx=10, pady=4)
        ctk.CTkLabel(row_name, text="Nome da Obra:", font=ctk.CTkFont(size=12), width=75).pack(side="left")
        self.ent_ep_name = ctk.CTkEntry(row_name, placeholder_text="Ex: Naruto Shippuden, Attack on Titan...", height=28)
        self.ent_ep_name.pack(side="left", fill="x", expand=True)

        row_season = ctk.CTkFrame(f, fg_color="transparent")
        row_season.pack(fill="x", padx=10, pady=4)
        ctk.CTkLabel(row_season, text="Temporada:", font=ctk.CTkFont(size=12), width=75).pack(side="left")
        self.ent_ep_season = ctk.CTkEntry(row_season, placeholder_text="Ex: 1, 2, 3 (Deixe vazio para todas)", height=28)
        self.ent_ep_season.pack(side="left", fill="x", expand=True)

        row_theme = ctk.CTkFrame(f, fg_color="transparent")
        row_theme.pack(fill="x", padx=10, pady=4)
        ctk.CTkLabel(row_theme, text="Foco / Tema:", font=ctk.CTkFont(size=12), width=75).pack(side="left")
        self.opt_ep_theme = ctk.CTkOptionMenu(
            row_theme,
            values=["Geral (Melhores Momentos)", "Ação / Lutas", "Engraçado / Comédia", "Teoria / Mistério", "Drama / Tensão", "Tristeza / Choro", "Romance / Casal"],
            height=28
        )
        self.opt_ep_theme.pack(side="left", fill="x", expand=True)

        # Campo para descrever algo a mais / preferências personalizadas
        row_details = ctk.CTkFrame(f, fg_color="transparent")
        row_details.pack(fill="x", padx=10, pady=(6, 8))

        lbl_det_row = ctk.CTkFrame(row_details, fg_color="transparent")
        lbl_det_row.pack(fill="x", pady=(0, 3))

        ctk.CTkLabel(
            lbl_det_row,
            text="O que procura a mais? (Descrição / Preferências):",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#c084fc"
        ).pack(side="left")

        ctk.CTkLabel(
            lbl_det_row,
            text="Opcional",
            font=ctk.CTkFont(size=10),
            text_color="#71717a"
        ).pack(side="right")

        self.ent_ep_details = ctk.CTkEntry(
            row_details,
            placeholder_text="Ex: episódios pouco populares e engraçados, fillers divertidos...",
            height=30,
            font=ctk.CTkFont(size=11)
        )
        self.ent_ep_details.pack(fill="x", expand=True)
        self.ent_ep_details.bind("<Return>", lambda e: self._start_search())
        self.ent_ep_name.bind("<Return>", lambda e: self._start_search())

        # Pílulas de Sugestão Rápida para preenchimento com 1 clique
        chips_frame = ctk.CTkFrame(row_details, fg_color="transparent")
        chips_frame.pack(fill="x", pady=(4, 0))

        def _apply_chip(text_to_set):
            current = self.ent_ep_details.get().strip()
            if not current:
                self.ent_ep_details.insert(0, text_to_set)
            elif text_to_set.lower() not in current.lower():
                self.ent_ep_details.delete(0, "end")
                self.ent_ep_details.insert(0, f"{current}, {text_to_set}")

        chips = [
            ("🎲 Pouco Populares", "episódios pouco populares e subestimados"),
            ("😂 Cenas Engraçadas", "momentos engraçados, cômicos e zoeira"),
            ("🥋 Treino / Fillers", "episódios de treino, filler ou calmaria"),
        ]

        for chip_label, chip_val in chips:
            c_btn = ctk.CTkButton(
                chips_frame,
                text=chip_label,
                font=ctk.CTkFont(size=10),
                height=22,
                fg_color="#18181b",
                hover_color="#27272a",
                text_color="#d4d4d8",
                border_width=1,
                border_color="#3f3f46",
                corner_radius=11,
                command=lambda v=chip_val: _apply_chip(v)
            )
            c_btn.pack(side="left", padx=(0, 4))

    def _start_search(self, regenerate: bool = False):
        if self.is_processing:
            return
        self.is_processing = True
        btn_text = "Buscando novas indicações..." if regenerate else "Buscando..."
        self.btn_search.configure(state="disabled", text=btn_text)

        mode = self.mode_selector.get()

        def worker():
            try:
                if mode == "Por Estilo / Nicho":
                    query = self.txt_query.get("1.0", "end").strip()
                    genre = self.opt_genre.get()
                    plat = self.opt_platform.get().lower()
                    plat_key = "youtube" if "shorts" in plat else ("tiktok" if "tiktok" in plat else ("instagram" if "instagram" in plat else "all"))
                    pop_key = "mainstream" if "mainstream" in self.opt_popularity.get().lower() else ("hidden_gem" if "joias" in self.opt_popularity.get().lower() else ("popular" if "populares" in self.opt_popularity.get().lower() else "any"))
                    era_key = "new" if "novos" in self.opt_era.get().lower() else ("modern" if "modernos" in self.opt_era.get().lower() else ("classic" if "clássicos" in self.opt_era.get().lower() else "any"))
                    
                    exclude_a = list(self.seen_animes) if regenerate else None
                    res = search_animes(query, genre=genre, platform=plat_key, popularity=pop_key, era=era_key, exclude_animes=exclude_a, log_cb=self._log)
                    
                    if not regenerate:
                        self.seen_animes = []
                    for a in res.get("animes", []):
                        aname = a.get("name")
                        if aname and aname not in self.seen_animes:
                            self.seen_animes.append(aname)

                    self.current_results = res
                    self.after(0, lambda: self._render_anime_results(res))
                else:
                    cat = self.opt_ep_cat.get().lower()
                    name = self.ent_ep_name.get().strip()
                    if not name:
                        self._log("[AVISO] Por favor, informe o Nome da Obra (ex: Dragon Ball Z).")
                        return
                    obra_key = f"{cat}_{name.lower()}"
                    season_val = self.ent_ep_season.get().strip()
                    season = int(season_val) if season_val.isdigit() else None
                    theme = self.opt_ep_theme.get().split()[0].lower()
                    details = self.ent_ep_details.get().strip() if hasattr(self, 'ent_ep_details') else ""
                    
                    if not regenerate and obra_key not in self.seen_episodes:
                        self.seen_episodes[obra_key] = []
                    
                    # Coleta todos os episódios vistos e usados para exclusão
                    exclude_eps = []
                    if regenerate:
                        seen = self.seen_episodes.get(obra_key, [])
                        used = list(self.used_episodes.get(obra_key, set()))
                        exclude_eps = list(set(seen) | set(used))

                    res = search_episodes(cat, name, theme=theme, season=season, details=details, exclude_episodes=exclude_eps if exclude_eps else None, log_cb=self._log)
                    
                    if obra_key not in self.seen_episodes:
                        self.seen_episodes[obra_key] = []
                    for ep in res.get("episodes", []):
                        ep_label = ep.get("episode") or f"Episódio {ep.get('episode_number', '')}"
                        if ep_label and ep_label not in self.seen_episodes[obra_key]:
                            self.seen_episodes[obra_key].append(ep_label)

                    self.current_results = res
                    self.after(0, lambda: self._render_episode_results(res, name, cat))
            except Exception as e:
                self._log(f"[ERRO] Erro na busca: {str(e)}")
            finally:
                self.after(0, self._finish_search)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_search(self):
        self.is_processing = False
        mode = self.mode_selector.get()
        text = "Buscar Animes e Cenas Virais" if mode == "Por Estilo / Nicho" else "Buscar Episódios da Obra"
        self.btn_search.configure(state="normal", text=text)

    def _copy_text(self, text: str, btn: ctk.CTkButton, original_text: str = "Copiar"):
        _copy_text_to_clipboard(self, text)
        btn.configure(text="Copiado!", fg_color="#10b981")
        self.after(1800, lambda: btn.configure(text=original_text, fg_color="#16a34a"))

    def _open_youtube_search(self, term: str):
        encoded = urllib.parse.quote(term)
        url = f"https://www.youtube.com/results?search_query={encoded}"
        webbrowser.open(url)

    def _render_anime_results(self, data: dict):
        for w in self.right_scroll.winfo_children():
            w.destroy()

        summary = data.get("summary", "")
        if summary:
            s_box = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color=COLOR_CARD_BORDER)
            s_box.pack(fill="x", padx=5, pady=(0, 10))

            top_s_row = ctk.CTkFrame(s_box, fg_color="transparent")
            top_s_row.pack(fill="x", padx=12, pady=(8, 8))

            ctk.CTkLabel(top_s_row, text=f"{summary}", font=ctk.CTkFont(size=12, weight="bold"), text_color="#e9d5ff", wraplength=360, justify="left").pack(side="left", fill="x", expand=True)

            btn_regen = ctk.CTkButton(
                top_s_row,
                text="🔄 Outros Animes",
                font=ctk.CTkFont(size=11, weight="bold"),
                height=30,
                width=130,
                fg_color="#9333ea",
                hover_color="#7e22ce",
                command=lambda: self._start_search(regenerate=True)
            )
            btn_regen.pack(side="right", padx=(8, 0))

        animes = data.get("animes", [])
        if not animes:
            ctk.CTkLabel(self.right_scroll, text="Nenhum anime encontrado para o critério informado.", text_color=COLOR_TEXT_MUTED).pack(pady=40)
            return

        for anime in animes:
            card = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
            card.pack(fill="x", padx=5, pady=8)

            # Top Header do Anime
            top_row = ctk.CTkFrame(card, fg_color="transparent")
            top_row.pack(fill="x", padx=12, pady=(10, 4))

            name = anime.get("name", "Anime")
            ctk.CTkLabel(top_row, text=name, font=ctk.CTkFont(size=16, weight="bold"), text_color="#a855f7").pack(side="left")

            score = anime.get("viral_potential", 90)
            ctk.CTkLabel(
                top_row, text=f" Potencial: {score}/100 ",
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color="#10b981" if score >= 85 else "#f59e0b",
                corner_radius=4
            ).pack(side="right")

            # Metadados rápidos
            meta_str = f"{anime.get('year', 'N/A')} | {anime.get('genre', 'N/A')} | {anime.get('episodes_total', 'N/A')} eps | {anime.get('popularity_level', '')}"
            ctk.CTkLabel(card, text=meta_str, font=ctk.CTkFont(size=11), text_color=COLOR_TEXT_MUTED).pack(anchor="w", padx=12, pady=(0, 4))

            if anime.get("why_recommended"):
                ctk.CTkLabel(card, text=anime["why_recommended"], font=ctk.CTkFont(size=12), text_color="#e4e4e7", wraplength=480, justify="left").pack(anchor="w", padx=12, pady=(2, 6))

            # Episódios / Cenas Exatas
            episodes = anime.get("best_episodes", [])
            if episodes:
                ctk.CTkLabel(card, text="Melhores Cenas e Episódios Exatos:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#facc15").pack(anchor="w", padx=12, pady=(4, 2))
                for ep in episodes:
                    ep_box = ctk.CTkFrame(card, fg_color="#1f1f23", corner_radius=6)
                    ep_box.pack(fill="x", padx=12, pady=4)

                    top_ep = ctk.CTkFrame(ep_box, fg_color="transparent")
                    top_ep.pack(fill="x", padx=8, pady=(6, 2))

                    ep_num = ep.get("episode", "Episódio")
                    arc = f" ({ep.get('arc_name', '')})" if ep.get("arc_name") else ""
                    ctk.CTkLabel(top_ep, text=f"{ep_num}{arc}", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8").pack(side="left")

                    desc = ep.get("scene_description", "")
                    if desc:
                        ctk.CTkLabel(ep_box, text=desc, font=ctk.CTkFont(size=11), text_color="#d4d4d8", wraplength=460, justify="left").pack(anchor="w", padx=8, pady=2)

                    # Botões de busca / copiar
                    term = ep.get("search_term", f"{name} {ep_num}")
                    btn_row = ctk.CTkFrame(ep_box, fg_color="transparent")
                    btn_row.pack(fill="x", padx=8, pady=(4, 6))

                    btn_cp = ctk.CTkButton(btn_row, text="Copiar Termo de Busca", width=140, height=24, font=ctk.CTkFont(size=11), fg_color="#16a34a", hover_color="#15803d")
                    btn_cp.configure(command=lambda t=term, b=btn_cp: self._copy_text(t, b, "Copiar Termo de Busca"))
                    btn_cp.pack(side="left", padx=(0, 6))

                    btn_yt = ctk.CTkButton(btn_row, text="Abrir no YouTube", width=120, height=24, font=ctk.CTkFont(size=11), fg_color="#ef4444", hover_color="#dc2626")
                    btn_yt.configure(command=lambda t=term: self._open_youtube_search(t))
                    btn_yt.pack(side="left")

            card.pack_configure(pady=(0, 10))

    def _render_episode_results(self, data: dict, obra_name: str, cat: str = "anime"):
        for w in self.right_scroll.winfo_children():
            w.destroy()

        obra_key = f"{cat}_{obra_name.lower()}"
        seen_set = set(self.seen_episodes.get(obra_key, []))
        used_set = set(self.used_episodes.get(obra_key, set()))
        total_excluded = len(seen_set | used_set)

        summary = data.get("summary", f"Episódios encontrados para {obra_name}")
        s_box = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color=COLOR_CARD_BORDER)
        s_box.pack(fill="x", padx=5, pady=(0, 10))

        # Top row do resumo com botão de novas indicações
        top_s_row = ctk.CTkFrame(s_box, fg_color="transparent")
        top_s_row.pack(fill="x", padx=12, pady=(10, 4))

        ctk.CTkLabel(top_s_row, text=f"{summary}", font=ctk.CTkFont(size=13, weight="bold"), text_color="#e9d5ff", wraplength=330, justify="left").pack(side="left", fill="x", expand=True)

        btn_regen = ctk.CTkButton(
            top_s_row,
            text="🔄 Gerar Outras Indicações",
            font=ctk.CTkFont(size=11, weight="bold"),
            height=32,
            width=175,
            fg_color="#9333ea",
            hover_color="#7e22ce",
            command=lambda: self._start_search(regenerate=True)
        )
        btn_regen.pack(side="right", padx=(8, 0))

        if total_excluded > 0:
            info_bar = ctk.CTkFrame(s_box, fg_color="transparent")
            info_bar.pack(fill="x", padx=12, pady=(2, 8))
            ctk.CTkLabel(info_bar, text=f"🚫 {total_excluded} episódios no histórico (não serão repetidos ao gerar novas indicações)", font=ctk.CTkFont(size=10), text_color="#a1a1aa").pack(side="left")

            def _clear_history():
                self.seen_episodes[obra_key] = []
                self.used_episodes[obra_key] = set()
                self._render_episode_results(data, obra_name, cat)

            btn_clear = ctk.CTkButton(
                info_bar,
                text="Limpar Histórico",
                font=ctk.CTkFont(size=10),
                height=18,
                width=85,
                fg_color="transparent",
                hover_color="#27272a",
                text_color="#f87171",
                command=_clear_history
            )
            btn_clear.pack(side="right")

        episodes = data.get("episodes", [])
        if not episodes:
            ctk.CTkLabel(self.right_scroll, text="Nenhum episódio retornado.", text_color=COLOR_TEXT_MUTED).pack(pady=40)
            return

        for ep in episodes:
            card = ctk.CTkFrame(self.right_scroll, fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color=COLOR_CARD_BORDER)
            card.pack(fill="x", padx=5, pady=6)

            top_row = ctk.CTkFrame(card, fg_color="transparent")
            top_row.pack(fill="x", padx=12, pady=(10, 2))

            ep_num = ep.get("episode", "Episódio")
            ep_title = ep.get("episode_title", "")
            title_display = f" — {ep_title}" if ep_title else ""
            arc = f" [{ep.get('arc_name', '')}]" if ep.get("arc_name") else ""

            # Número do episódio com título oficial
            ctk.CTkLabel(top_row, text=f"{ep_num}{title_display}", font=ctk.CTkFont(size=13, weight="bold"), text_color="#facc15").pack(side="left")
            if arc:
                ctk.CTkLabel(top_row, text=arc, font=ctk.CTkFont(size=11), text_color="#c084fc").pack(side="left", padx=(4, 0))

            score = ep.get("viral_potential", 90)
            approx_time = ep.get("approx_time", "")
            time_badge = f"⏱️ {approx_time} | " if approx_time else ""
            ctk.CTkLabel(top_row, text=f"{time_badge}Nota: {score}/100", font=ctk.CTkFont(size=11, weight="bold"), text_color="#34d399").pack(side="right")

            desc = ep.get("scene_description", "")
            if desc:
                ctk.CTkLabel(card, text=desc, font=ctk.CTkFont(size=12), text_color="#e4e4e7", wraplength=480, justify="left").pack(anchor="w", padx=12, pady=4)

            term = ep.get("search_term", f"{obra_name} {ep_num}")
            btn_row = ctk.CTkFrame(card, fg_color="transparent")
            btn_row.pack(fill="x", padx=12, pady=(6, 10))

            btn_cp = ctk.CTkButton(btn_row, text="Copiar Termo", width=110, height=26, font=ctk.CTkFont(size=11), fg_color="#16a34a", hover_color="#15803d")
            btn_cp.configure(command=lambda t=term, b=btn_cp: self._copy_text(t, b, "Copiar Termo"))
            btn_cp.pack(side="left", padx=(0, 6))

            btn_yt = ctk.CTkButton(btn_row, text="Buscar no YouTube", width=135, height=26, font=ctk.CTkFont(size=11), fg_color="#ef4444", hover_color="#dc2626")
            btn_yt.configure(command=lambda t=term: self._open_youtube_search(t))
            btn_yt.pack(side="left", padx=(0, 6))

            # Botão Já Usei / Descartar
            ep_key = ep_num
            is_already_used = ep_key in self.used_episodes.get(obra_key, set())
            
            def _toggle_used(k=ep_key, c=card, b=None):
                if obra_key not in self.used_episodes:
                    self.used_episodes[obra_key] = set()
                if k in self.used_episodes[obra_key]:
                    self.used_episodes[obra_key].remove(k)
                    c.configure(border_color=COLOR_CARD_BORDER)
                    if b:
                        b.configure(text="🚫 Já Usei / Descartar", fg_color="#27272a", hover_color="#3f3f46")
                else:
                    self.used_episodes[obra_key].add(k)
                    c.configure(border_color="#ef4444")
                    if b:
                        b.configure(text="✓ Marcado como Usado", fg_color="#7f1d1d", hover_color="#991b1b")

            btn_used = ctk.CTkButton(
                btn_row,
                text="✓ Marcado como Usado" if is_already_used else "🚫 Já Usei / Descartar",
                width=145,
                height=26,
                font=ctk.CTkFont(size=11),
                fg_color="#7f1d1d" if is_already_used else "#27272a",
                hover_color="#991b1b" if is_already_used else "#3f3f46"
            )
            btn_used.configure(command=lambda k=ep_key, c=card, b=btn_used: _toggle_used(k, c, b))
            btn_used.pack(side="left")

    def _send_followup(self):
        query = self.ent_chat.get().strip()
        if not query or self.is_processing:
            return
        if not self.current_results:
            self._append_chat("Você", query)
            self._append_chat("Assistente", "Faça uma busca de animes primeiro para termos um contexto para conversar!")
            self.ent_chat.delete(0, "end")
            return

        self._append_chat("Você", query)
        self.ent_chat.delete(0, "end")
        self.btn_send_chat.configure(state="disabled")

        def worker():
            try:
                res = ask_anime_followup(query, self.current_results, self.chat_history, log_cb=self._log)
                ans = res.get("response", "Aqui está o que encontrei.")
                self.chat_history.append({"user": query, "ai": ans})
                self.after(0, lambda: self._append_chat("Assistente", ans))
            except Exception as e:
                self.after(0, lambda: self._append_chat("Assistente", f"Erro: {str(e)}"))
            finally:
                self.after(0, lambda: self.btn_send_chat.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _append_chat(self, sender: str, msg: str):
        self.txt_chat_history.configure(state="normal")
        self.txt_chat_history.insert("end", f"{sender}: {msg}\n\n")
        self.txt_chat_history.see("end")
        self.txt_chat_history.configure(state="disabled")
