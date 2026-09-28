"""
update_dialog.py - In-App Update Modal Dialog for Urahara Studio
Allows users to view release changelog, download update packages directly inside the app,
and automatically install & restart Urahara without opening a web browser.
"""

import os
import time
import tempfile
import threading
from pathlib import Path
from typing import Dict, Any, Optional
import customtkinter as ctk
from tkinter import messagebox

from updater import (
    CURRENT_VERSION,
    download_update_asset,
    apply_update_and_restart,
    open_download_page,
)
import icon_manager

DIALOG_COLORS = {
    "bg": "#09090b",
    "card": "#121216",
    "card_border": "#222228",
    "accent_primary": "#10b981",
    "accent_hover": "#059669",
    "text_primary": "#fafafa",
    "text_secondary": "#a1a1aa",
    "text_muted": "#71717a",
    "success": "#10b981",
    "warning": "#f59e0b",
    "error": "#ef4444",
}


class UpdateDialog(ctk.CTkToplevel):
    """
    Modal window for downloading and applying updates in-place.
    """

    def __init__(self, parent, update_info: Dict[str, Any], **kwargs):
        super().__init__(parent, **kwargs)
        self.parent = parent
        self.update_info = update_info
        self._cancel_event = threading.Event()
        self._is_downloading = False

        self.title("Atualização do Urahara Studio")
        self.geometry("640x530")
        self.minsize(580, 480)
        self.configure(fg_color=DIALOG_COLORS["bg"])

        # Center on screen / parent
        self._center_window()

        self.attributes("-topmost", True)
        self.grab_set()

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _center_window(self):
        try:
            self.update_idletasks()
            pw = self.parent.winfo_width()
            ph = self.parent.winfo_height()
            px = self.parent.winfo_rootx()
            py = self.parent.winfo_rooty()
            w, h = 640, 530
            x = px + max(0, (pw - w) // 2)
            y = py + max(0, (ph - h) // 2)
            self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            self.geometry("640x530")

    def _build_ui(self):
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=24, pady=20)

        # ── Header ────────────────────────────────────────────────────────
        header = ctk.CTkFrame(main_frame, fg_color="transparent")
        header.pack(fill="x", pady=(0, 16))

        top_brand = ctk.CTkFrame(header, fg_color="transparent")
        top_brand.pack(fill="x")

        ctk.CTkLabel(
            top_brand, text="●",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=DIALOG_COLORS["accent_primary"],
        ).pack(side="left", padx=(0, 8))

        ctk.CTkLabel(
            top_brand, text="URAHARA STUDIO",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            text_color="#ffffff",
        ).pack(side="left")

        latest_ver = self.update_info.get("latest_version", "1.0.3")
        badge = ctk.CTkLabel(
            top_brand, text=f" Nova Versão v{latest_ver} ",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#ffffff", fg_color="#064e3b",
            corner_radius=6, padx=8, pady=2,
        )
        badge.pack(side="left", padx=(10, 0))

        sub_text = f"Sua versão atual é v{CURRENT_VERSION}. Uma versão mais recente está pronta para instalação direta!"
        ctk.CTkLabel(
            header, text=sub_text,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=DIALOG_COLORS["text_secondary"], anchor="w",
        ).pack(fill="x", pady=(4, 0))

        # ── Release Info & Changelog Card ─────────────────────────────────
        card = ctk.CTkFrame(
            main_frame, fg_color=DIALOG_COLORS["card"],
            corner_radius=12, border_width=1, border_color=DIALOG_COLORS["card_border"],
        )
        card.pack(fill="both", expand=True, pady=(0, 14))

        card_inner = ctk.CTkFrame(card, fg_color="transparent")
        card_inner.pack(fill="both", expand=True, padx=16, pady=14)

        rel_title = self.update_info.get("release_title") or f"Lançamento v{latest_ver}"
        ctk.CTkLabel(
            card_inner, text=f"Novidades da {rel_title}:",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=DIALOG_COLORS["text_primary"], anchor="w",
        ).pack(fill="x", pady=(0, 8))

        # Changelog scrollable textbox
        self.changelog_box = ctk.CTkTextbox(
            card_inner, fg_color="#0b0b0e",
            text_color=DIALOG_COLORS["text_secondary"],
            border_width=1, border_color=DIALOG_COLORS["card_border"],
            corner_radius=8, font=ctk.CTkFont(family="Segoe UI", size=12),
        )
        self.changelog_box.pack(fill="both", expand=True)

        raw_changelog = self.update_info.get("changelog")
        if isinstance(raw_changelog, list):
            changelog_text = "\n".join(f"• {line}" for line in raw_changelog if line.strip())
        elif isinstance(raw_changelog, str):
            changelog_text = raw_changelog
        else:
            changelog_text = "• Melhorias de estabilidade e novas proteções anti-copyright."

        self.changelog_box.insert("1.0", changelog_text)
        self.changelog_box.configure(state="disabled")

        # ── Progress Section ──────────────────────────────────────────────
        prog_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        prog_frame.pack(fill="x", pady=(0, 14))

        info_row = ctk.CTkFrame(prog_frame, fg_color="transparent")
        info_row.pack(fill="x", pady=(0, 6))

        asset_size = self.update_info.get("asset_size", 0)
        size_str = f" (~{asset_size / (1024 * 1024):.1f} MB)" if asset_size > 0 else ""
        self.status_label = ctk.CTkLabel(
            info_row,
            text=f"Pronto para baixar{size_str}. Não é necessário abrir o navegador.",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=DIALOG_COLORS["text_secondary"], anchor="w",
        )
        self.status_label.pack(side="left")

        self.pct_label = ctk.CTkLabel(
            info_row, text="0%",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=DIALOG_COLORS["accent_primary"], anchor="e",
        )
        self.pct_label.pack(side="right")

        self.progress_bar = ctk.CTkProgressBar(
            prog_frame, fg_color="#18181f",
            progress_color=DIALOG_COLORS["accent_primary"],
            height=10, corner_radius=5,
        )
        self.progress_bar.set(0.0)
        self.progress_bar.pack(fill="x")

        # ── Action Buttons ────────────────────────────────────────────────
        btn_row = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_row.pack(fill="x")

        self.update_btn = ctk.CTkButton(
            btn_row, text="Atualizar Agora (Direto no App)",
            image=icon_manager.get_icon("download", size=(16, 16), color="#09090b"),
            compound="left",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=DIALOG_COLORS["accent_primary"],
            hover_color=DIALOG_COLORS["accent_hover"],
            text_color="#09090b",
            height=38, corner_radius=8,
            command=self._start_in_app_update,
        )
        self.update_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.later_btn = ctk.CTkButton(
            btn_row, text="Lembrar Mais Tarde",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color="#18181f", hover_color="#24242e",
            border_width=1, border_color=DIALOG_COLORS["card_border"],
            text_color=DIALOG_COLORS["text_secondary"],
            height=38, corner_radius=8, width=130,
            command=self.destroy,
        )
        self.later_btn.pack(side="right")

        # Fallback button to open GitHub if desired
        github_url = self.update_info.get("download_url")
        if github_url:
            self.github_btn = ctk.CTkButton(
                btn_row, text="Ver no GitHub",
                font=ctk.CTkFont(family="Segoe UI", size=11),
                fg_color="transparent", hover_color="#18181f",
                text_color=DIALOG_COLORS["text_muted"],
                height=38, width=100,
                command=lambda: open_download_page(github_url),
            )
            self.github_btn.pack(side="right", padx=(0, 8))

    def _start_in_app_update(self):
        if self._is_downloading:
            return

        # Identify download URL: direct asset or release zip
        direct_url = self.update_info.get("direct_download_url")
        if not direct_url:
            # Fallback to repo release zip or releases page
            latest_v = self.update_info.get("latest_version", "1.0.3")
            direct_url = f"https://github.com/ViniciusGDias/Upscaling/releases/download/v{latest_v}/Urahara_Setup_v{latest_v}.exe"

        asset_name = self.update_info.get("asset_name") or f"Urahara_Update_v{self.update_info.get('latest_version', '1.0.3')}.exe"

        # Temporary download destination
        temp_dir = Path(tempfile.gettempdir())
        dest_file = str(temp_dir / asset_name)

        self._is_downloading = True
        self._cancel_event.clear()

        self.update_btn.configure(state="disabled", text="Baixando Atualização...")
        self.later_btn.configure(text="Cancelar")
        self.status_label.configure(text="Conectando ao servidor...", text_color=DIALOG_COLORS["text_primary"])
        self.progress_bar.set(0.0)

        def _on_progress(frac: float, cur_bytes: int, total_bytes: int):
            def _ui():
                if not self.winfo_exists():
                    return
                self.progress_bar.set(frac)
                pct = int(frac * 100)
                self.pct_label.configure(text=f"{pct}%")
                if total_bytes > 0:
                    mb_cur = cur_bytes / (1024 * 1024)
                    mb_tot = total_bytes / (1024 * 1024)
                    self.status_label.configure(text=f"Baixando pacote... {mb_cur:.1f} MB de {mb_tot:.1f} MB ({pct}%)")
                else:
                    mb_cur = cur_bytes / (1024 * 1024)
                    self.status_label.configure(text=f"Baixando pacote... {mb_cur:.1f} MB transferidos")
            self.after(0, _ui)

        def _worker():
            ok, err_or_path = download_update_asset(
                asset_url=direct_url,
                dest_path=dest_file,
                progress_callback=_on_progress,
                cancel_event=self._cancel_event
            )

            def _done():
                self._is_downloading = False
                if not self.winfo_exists():
                    return

                if not ok:
                    self.update_btn.configure(state="normal", text="Tentar Novamente")
                    self.later_btn.configure(text="Fechar")
                    self.status_label.configure(
                        text=f"Falha ao baixar: {err_or_path}",
                        text_color=DIALOG_COLORS["error"]
                    )
                    # Offer opening web page if direct link failed
                    if messagebox.askyesno(
                        "Falha no Download",
                        f"Não foi possível concluir o download direto:\n{err_or_path}\n\nDeseja abrir a página de download no navegador?"
                    ):
                        open_download_page(self.update_info.get("download_url"))
                    return

                # Success: apply update
                self.status_label.configure(
                    text="✅ Download concluído! Reiniciando o Urahara Studio atualizado...",
                    text_color=DIALOG_COLORS["success"]
                )
                self.progress_bar.set(1.0)
                self.pct_label.configure(text="100%")

                # Wait 1.2s so user sees success and then restart
                self.after(1200, lambda: apply_update_and_restart(dest_file))

            self.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_close(self):
        if self._is_downloading:
            self._cancel_event.set()
        self.destroy()
