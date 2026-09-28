"""
sidebar_navigation.py - Navegação Lateral de Estúdio (Studio Sidebar) para o Urahara Studio.

Substitui as abas horizontais espremidas no topo por uma barra lateral de navegação
moderna, espaçosa e elegante (Void Obsidian + Verde Esmeralda Kisuke).
Preserva 100% da API do CTkTabview (.add(), .set(), .get(), ._tab_dict).
"""

from __future__ import annotations
from typing import Dict, Optional, Callable
import customtkinter as ctk
import icon_manager

SIDEBAR_COLORS = {
    "bg": "#09090b",
    "sidebar_bg": "#0c0c0e",
    "card_border": "#1f1f23",
    "accent_primary": "#10b981",    # Verde Esmeralda Kisuke
    "accent_hover": "#059669",
    "btn_active_bg": "#18181f",
    "btn_inactive_bg": "transparent",
    "btn_hover": "#141418",
    "text_active": "#fafafa",
    "text_inactive": "#a1a1aa",
    "text_muted": "#52525b",
    "section_header": "#71717a",
    "indicator": "#10b981",
}

# Categorização elegante dos itens de menu
SECTIONS = [
    ("WORKFLOWS & CRIAÇÃO", [
        ("Upscaling", "upscale"),
        ("Diretor IA", "director"),
        ("Refinador Mastercut", "scissors"),
        ("Studio Pipeline", "studio"),
        ("Separação de Áudio", "audio"),
    ]),
    ("DISTRIBUIÇÃO & PESQUISA", [
        ("Instagram Shorts", "instagram"),
        ("YouTube Shorts", "youtube"),
        ("Batch & Histórico", "layers"),
        ("Anime Finder", "search"),
    ]),
    ("SISTEMA", [
        ("Configurações", "settings"),
    ]),
]


class SidebarNavigation(ctk.CTkFrame):
    """
    Componente de Navegação Lateral de Estúdio que gerencia as abas
    e containers de conteúdo da aplicação com compatibilidade total com CTkTabview.
    """

    def __init__(self, parent, on_tab_changed: Optional[Callable[[str], None]] = None, **kwargs):
        super().__init__(parent, fg_color=SIDEBAR_COLORS["bg"], **kwargs)
        self.on_tab_changed = on_tab_changed

        self._tab_dict: Dict[str, ctk.CTkFrame] = {}
        self._buttons_dict: Dict[str, ctk.CTkButton] = {}
        self._active_tab: str = ""

        # Layout dividido em 2 colunas: Sidebar (esquerda) e Content Area (direita)
        self.grid_columnconfigure(0, weight=0, minsize=240)  # Sidebar fixa
        self.grid_columnconfigure(1, weight=1)              # Conteúdo flexível
        self.grid_rowconfigure(0, weight=1)

        # ── Sidebar Lateral ──────────────────────────────────────────────
        self.sidebar_frame = ctk.CTkFrame(
            self,
            fg_color=SIDEBAR_COLORS["sidebar_bg"],
            corner_radius=0,
            border_width=1,
            border_color=SIDEBAR_COLORS["card_border"],
            width=240,
        )
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_propagate(False)

        # ── Container de Conteúdo ────────────────────────────────────────
        self.content_container = ctk.CTkFrame(
            self,
            fg_color="transparent",
            corner_radius=0,
        )
        self.content_container.grid(row=0, column=1, sticky="nsew")
        self.content_container.grid_columnconfigure(0, weight=1)
        self.content_container.grid_rowconfigure(0, weight=1)

        # Scrollable container interno para a lista de botões da sidebar
        self._build_sidebar_header()
        self.nav_scroll = ctk.CTkScrollableFrame(
            self.sidebar_frame,
            fg_color="transparent",
            scrollbar_button_color=SIDEBAR_COLORS["card_border"],
            scrollbar_button_hover_color=SIDEBAR_COLORS["accent_primary"],
        )
        self.nav_scroll.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        self._build_sidebar_footer()

        # Compatibilidade com código legado que acessa _segmented_button
        self._segmented_button = self

    def _build_sidebar_header(self):
        """Cabeçalho da sidebar com logo, badge e indicador de energia."""
        header_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=16, pady=(16, 12))

        brand_row = ctk.CTkFrame(header_frame, fg_color="transparent")
        brand_row.pack(fill="x")

        # Ponto de energia verde Kisuke
        ctk.CTkLabel(
            brand_row,
            text="●",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=SIDEBAR_COLORS["accent_primary"],
        ).pack(side="left", padx=(0, 8))

        ctk.CTkLabel(
            brand_row,
            text="URAHARA",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color="#ffffff",
        ).pack(side="left")

        ctk.CTkLabel(
            brand_row,
            text="STUDIO",
            font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
            text_color=SIDEBAR_COLORS["accent_primary"],
            fg_color="#064e3b",
            corner_radius=4,
            padx=5, pady=1,
        ).pack(side="left", padx=(8, 0))

        sub_lbl = ctk.CTkLabel(
            header_frame,
            text="Anime & Video Intelligence Suite",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=SIDEBAR_COLORS["text_muted"],
            anchor="w",
        )
        sub_lbl.pack(fill="x", pady=(4, 0))

        # Linha divisória sutil
        ctk.CTkFrame(self.sidebar_frame, fg_color=SIDEBAR_COLORS["card_border"], height=1).pack(fill="x", padx=12, pady=(0, 8))

    def _build_sidebar_footer(self):
        """Rodapé da sidebar com status do sistema."""
        footer_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        footer_frame.pack(side="bottom", fill="x", padx=12, pady=(4, 12))

        ctk.CTkFrame(footer_frame, fg_color=SIDEBAR_COLORS["card_border"], height=1).pack(fill="x", pady=(0, 10))

        status_box = ctk.CTkFrame(footer_frame, fg_color="#101014", corner_radius=6, border_width=1, border_color=SIDEBAR_COLORS["card_border"])
        status_box.pack(fill="x")

        s_inner = ctk.CTkFrame(status_box, fg_color="transparent")
        s_inner.pack(fill="x", padx=10, pady=6)

        ctk.CTkLabel(
            s_inner,
            text="SISTEMA:",
            font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
            text_color=SIDEBAR_COLORS["text_muted"],
        ).pack(side="left")

        self.footer_status_label = ctk.CTkLabel(
            s_inner,
            text="Online [Pronto]",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=SIDEBAR_COLORS["accent_primary"],
        )
        self.footer_status_label.pack(side="right")

        # Botão de notificação de atualização in-app (visível quando houver nova versão)
        self.update_btn = ctk.CTkButton(
            footer_frame,
            text="⚡ Atualização Disponível!",
            image=icon_manager.get_icon("download", size=(12, 12), color="#09090b"),
            compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#10b981", hover_color="#059669",
            text_color="#09090b",
            height=28, corner_radius=6,
            command=self._on_update_clicked,
        )
        self._update_info = None
        self._on_update_custom_click = None

    def show_update_alert(self, update_info: dict, on_click: Optional[Callable] = None):
        """Exibe o alerta brilhante de atualização na barra lateral."""
        self._update_info = update_info
        self._on_update_custom_click = on_click
        latest = update_info.get("latest_version", "")
        self.update_btn.configure(text=f"⚡ Atualizar para v{latest}")
        self.update_btn.pack(fill="x", pady=(0, 6))

    def _on_update_clicked(self):
        """Abre o diálogo de atualização in-app com barra de progresso."""
        if hasattr(self, "_on_update_custom_click") and self._on_update_custom_click:
            self._on_update_custom_click(self._update_info)
        elif self._update_info:
            from update_dialog import UpdateDialog
            UpdateDialog(self.winfo_toplevel(), self._update_info)

    def add(self, name: str) -> ctk.CTkFrame:
        """
        Adiciona uma nova aba à aplicação.
        Retorna o CTkFrame correspondente ao conteúdo da aba.
        """
        # Cria o frame de conteúdo para a aba
        content_frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self._tab_dict[name] = content_frame

        # Procura a seção a que pertence o item
        i_key = icon_manager.TAB_ICONS.get(name, "sparkle")
        
        # Cria o botão de navegação na sidebar
        btn = self._create_nav_button(name, i_key)
        self._buttons_dict[name] = btn

        # Se for a primeira aba, ativa-a por padrão
        if not self._active_tab:
            self.set(name)

        return content_frame

    def _create_nav_button(self, name: str, icon_key: str) -> ctk.CTkButton:
        """Cria o botão de navegação na sidebar com ícone vetorial."""
        # Se for início de seção, podemos adicionar um título de seção
        for sec_title, items in SECTIONS:
            if items and items[0][0] == name:
                sec_lbl = ctk.CTkLabel(
                    self.nav_scroll,
                    text=sec_title,
                    font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
                    text_color=SIDEBAR_COLORS["section_header"],
                    anchor="w",
                )
                sec_lbl.pack(fill="x", padx=6, pady=(12, 4))
                break

        icon_img = icon_manager.get_icon(icon_key, size=(16, 16), color=SIDEBAR_COLORS["text_inactive"])

        btn = ctk.CTkButton(
            self.nav_scroll,
            text=f"  {name}",
            image=icon_img,
            compound="left",
            anchor="w",
            height=40,
            corner_radius=8,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="normal"),
            fg_color=SIDEBAR_COLORS["btn_inactive_bg"],
            hover_color=SIDEBAR_COLORS["btn_hover"],
            text_color=SIDEBAR_COLORS["text_inactive"],
            border_width=0,
            command=lambda n=name: self.set(n),
        )
        btn.pack(fill="x", pady=2)
        return btn

    def set(self, name: str):
        """Muda a aba ativa para o nome especificado."""
        if name not in self._tab_dict:
            return

        prev_tab = self._active_tab
        self._active_tab = name

        # Atualiza a visibilidade dos containers de conteúdo
        for t_name, frame in self._tab_dict.items():
            if t_name == name:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()

        # Atualiza o estilo visual dos botões da sidebar
        for t_name, btn in self._buttons_dict.items():
            i_key = icon_manager.TAB_ICONS.get(t_name, "sparkle")
            if t_name == name:
                # Aba selecionada: destaque esmeralda + fundo escuro com borda
                btn.configure(
                    fg_color=SIDEBAR_COLORS["btn_active_bg"],
                    text_color=SIDEBAR_COLORS["text_active"],
                    font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                    border_width=1,
                    border_color=SIDEBAR_COLORS["accent_primary"],
                    image=icon_manager.get_icon(i_key, size=(16, 16), color=SIDEBAR_COLORS["accent_primary"]),
                )
            else:
                # Aba inativa: texto suave sem borda
                btn.configure(
                    fg_color=SIDEBAR_COLORS["btn_inactive_bg"],
                    text_color=SIDEBAR_COLORS["text_inactive"],
                    font=ctk.CTkFont(family="Segoe UI", size=12, weight="normal"),
                    border_width=0,
                    image=icon_manager.get_icon(i_key, size=(16, 16), color=SIDEBAR_COLORS["text_inactive"]),
                )

        if self.on_tab_changed and prev_tab != name:
            try:
                self.on_tab_changed(name)
            except Exception:
                pass

    def get(self) -> str:
        """Retorna o nome da aba ativa."""
        return self._active_tab
