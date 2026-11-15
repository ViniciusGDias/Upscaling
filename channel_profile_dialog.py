"""
channel_profile_dialog.py - Modal moderno para gerenciar e criar perfis de canais do Studio.
Permite alternar, editar e criar novos canais mantendo rigorosamente os mesmos parâmetros
de enquadramento, fontes e proporções do Animax.
"""

import os
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List
import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image

import urahara_theme
import channel_profile_manager as cpm

COLORS = {
    **urahara_theme.COLORS,
    "accent_studio": urahara_theme.COLORS["accent_benihime"],
    "accent_studio_hover": urahara_theme.COLORS["accent_benihime_hover"],
}

COLOR_PRESETS = [
    ("#FFFFFF", "Branco (Animax)"),
    ("#00A8FF", "Azul Cyan (Vinny)"),
    ("#FF1E27", "Vermelho (ViniAnimes)"),
    ("#FFD700", "Amarelo Ouro"),
    ("#00FFAA", "Verde Neon"),
    ("#A855F7", "Roxo Cosmic"),
]


class ChannelProfileDialog(ctk.CTkToplevel):
    """Janela moderna para gerenciar perfis de canal (Animax, Vinny, ViniAnimes, etc.)."""

    def __init__(self, parent, on_profile_changed: Optional[Callable[[str], None]] = None, **kwargs):
        super().__init__(parent, **kwargs)
        self.title("Perfis de Canais - Studio Pipeline")
        self.geometry("860x680")
        self.minsize(780, 580)
        self.configure(fg_color=COLORS["bg_dark"])

        self.on_profile_changed = on_profile_changed
        self.active_id = cpm.get_active_profile_id()
        self.selected_profile_id = self.active_id
        self.profiles = cpm.get_all_profiles()

        # Tkinter variables
        self.var_name = ctk.StringVar()
        self.var_handle = ctk.StringVar()
        self.var_verified = ctk.BooleanVar(value=False)
        self.var_watermark = ctk.StringVar()
        self.var_title_color = ctk.StringVar(value="#FFFFFF")
        self.var_cta_l1 = ctk.StringVar()
        self.var_cta_l2 = ctk.StringVar()
        self.var_cta_l3 = ctk.StringVar()
        self.current_avatar_path = ""
        self._avatar_ctk_img = None

        self.transient(parent)
        self.grab_set()

        self._build_ui()
        self._load_profile_into_editor(self.selected_profile_id)

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], corner_radius=10)
        header.grid(row=0, column=0, columnspan=2, padx=16, pady=(16, 10), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Perfis de Canais (Studio)",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=COLORS["accent_secondary"]
        ).grid(row=0, column=0, padx=16, pady=(12, 2), sticky="w")

        ctk.CTkLabel(
            header,
            text="Alterne ou crie formatos personalizados mantendo o mesmo enquadramento, fontes e qualidade do Animax.",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"]
        ).grid(row=1, column=0, padx=16, pady=(0, 12), sticky="w")

        # Container Principal
        # Esquerda: Lista de Canais
        left_panel = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], corner_radius=10, width=240)
        left_panel.grid(row=1, column=0, padx=(16, 8), pady=(0, 16), sticky="nsew")
        left_panel.grid_rowconfigure(1, weight=1)
        left_panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            left_panel,
            text="CANAIS CADASTRADOS",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLORS["text_secondary"]
        ).grid(row=0, column=0, padx=14, pady=(14, 6), sticky="w")

        self.list_frame = ctk.CTkScrollableFrame(left_panel, fg_color="transparent")
        self.list_frame.grid(row=1, column=0, padx=6, pady=4, sticky="nsew")
        self.list_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(
            left_panel,
            text="+ Criar Novo Canal",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=COLORS["bg_dark"],
            hover_color=COLORS["bg_card_hover"],
            border_width=1,
            border_color=COLORS["accent_studio"],
            text_color=COLORS["accent_studio"],
            height=36,
            command=self._on_click_new_profile
        ).grid(row=2, column=0, padx=12, pady=12, sticky="ew")

        # Direita: Editor do Perfil Selecionado
        right_panel = ctk.CTkScrollableFrame(self, fg_color=COLORS["bg_card"], corner_radius=10)
        right_panel.grid(row=1, column=1, padx=(8, 16), pady=(0, 16), sticky="nsew")
        right_panel.grid_columnconfigure((1, 3), weight=1)
        self.right_panel = right_panel

        self._build_editor_fields()
        self._refresh_profiles_list()

    def _build_editor_fields(self):
        rp = self.right_panel

        # Row 0: Top Status & Actions (Perfil Ativo / Salvar / Excluir)
        top_bar = ctk.CTkFrame(rp, fg_color=COLORS["bg_dark"], corner_radius=8)
        top_bar.grid(row=0, column=0, columnspan=4, padx=14, pady=(12, 14), sticky="ew")
        top_bar.grid_columnconfigure(1, weight=1)

        self.lbl_profile_status = ctk.CTkLabel(
            top_bar,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["success"]
        )
        self.lbl_profile_status.grid(row=0, column=0, padx=12, pady=8, sticky="w")

        btn_act_box = ctk.CTkFrame(top_bar, fg_color="transparent")
        btn_act_box.grid(row=0, column=2, padx=10, pady=6, sticky="e")

        self.btn_set_active = ctk.CTkButton(
            btn_act_box,
            text="★ Usar no Studio",
            width=130,
            height=30,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLORS["accent_studio"],
            hover_color=COLORS["accent_studio_hover"],
            command=self._set_selected_as_active
        )
        self.btn_set_active.pack(side="left", padx=4)

        self.btn_delete = ctk.CTkButton(
            btn_act_box,
            text="Excluir",
            width=70,
            height=30,
            font=ctk.CTkFont(size=11),
            fg_color="#3f1a1a",
            hover_color="#dc2626",
            text_color="#f87171",
            command=self._delete_current_profile
        )
        self.btn_delete.pack(side="left", padx=4)

        # Row 1: Foto de Perfil & Identificação
        avatar_box = ctk.CTkFrame(rp, fg_color="transparent")
        avatar_box.grid(row=1, column=0, rowspan=2, padx=(14, 10), pady=4, sticky="nw")

        self.lbl_avatar_preview = ctk.CTkLabel(avatar_box, text="", width=90, height=90)
        self.lbl_avatar_preview.pack(pady=(0, 6))

        ctk.CTkButton(
            avatar_box,
            text="Trocar Foto",
            width=90,
            height=28,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=COLORS["bg_dark"],
            hover_color=COLORS["bg_card_hover"],
            border_width=1,
            border_color=COLORS["border"],
            command=self._browse_avatar_image
        ).pack()

        # Nome do Canal & Handle
        ctk.CTkLabel(rp, text="Nome do Canal:", font=ctk.CTkFont(size=11, weight="bold"), text_color=COLORS["text_primary"]).grid(row=1, column=1, padx=(6, 4), pady=4, sticky="w")
        self.entry_name = ctk.CTkEntry(rp, textvariable=self.var_name, height=32, placeholder_text="Ex: Vinny", fg_color=COLORS["bg_dark"], border_color=COLORS["border"])
        self.entry_name.grid(row=1, column=2, padx=(4, 14), pady=4, sticky="ew")

        ctk.CTkLabel(rp, text="@Handle Twitter/YT:", font=ctk.CTkFont(size=11, weight="bold"), text_color=COLORS["text_primary"]).grid(row=2, column=1, padx=(6, 4), pady=4, sticky="w")
        self.entry_handle = ctk.CTkEntry(rp, textvariable=self.var_handle, height=32, placeholder_text="Ex: @vinny.animes", fg_color=COLORS["bg_dark"], border_color=COLORS["border"])
        self.entry_handle.grid(row=2, column=2, padx=(4, 14), pady=4, sticky="ew")

        # Selo de Verificado
        ctk.CTkSwitch(
            rp,
            text="Selo de Verificado (Checkmark ✓)",
            variable=self.var_verified,
            progress_color=COLORS["accent_studio"],
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_secondary"]
        ).grid(row=3, column=1, columnspan=2, padx=(6, 14), pady=(4, 12), sticky="w")

        # Separador visual
        ctk.CTkFrame(rp, height=1, fg_color=COLORS["border"]).grid(row=4, column=0, columnspan=4, padx=14, pady=10, sticky="ew")

        # Row 5: Cor do Título & Marca d'água
        ctk.CTkLabel(rp, text="Cor do Título (Topo):", font=ctk.CTkFont(size=11, weight="bold"), text_color=COLORS["text_primary"]).grid(row=5, column=0, padx=14, pady=6, sticky="w")
        
        color_row = ctk.CTkFrame(rp, fg_color="transparent")
        color_row.grid(row=5, column=1, columnspan=3, padx=(4, 14), pady=6, sticky="ew")
        
        self.entry_title_color = ctk.CTkEntry(color_row, textvariable=self.var_title_color, width=95, height=30, fg_color=COLORS["bg_dark"], border_color=COLORS["border"])
        self.entry_title_color.pack(side="left", padx=(0, 8))

        self.color_sample_box = ctk.CTkLabel(color_row, text="", width=24, height=24, corner_radius=4, fg_color="#FFFFFF")
        self.color_sample_box.pack(side="left", padx=(0, 10))
        self.var_title_color.trace_add("write", lambda *a: self._update_color_sample())

        for hex_code, desc in COLOR_PRESETS:
            btn = ctk.CTkButton(
                color_row,
                text="",
                width=22,
                height=22,
                corner_radius=11,
                fg_color=hex_code,
                hover_color=hex_code,
                command=lambda c=hex_code: self.var_title_color.set(c)
            )
            btn.pack(side="left", padx=2)

        # Marca d'água Central
        ctk.CTkLabel(rp, text="Marca d'Água (Texto Central):", font=ctk.CTkFont(size=11, weight="bold"), text_color=COLORS["text_primary"]).grid(row=6, column=0, padx=14, pady=6, sticky="w")
        self.entry_watermark = ctk.CTkEntry(rp, textvariable=self.var_watermark, height=32, placeholder_text="Ex: @VINNY.ANIMES", fg_color=COLORS["bg_dark"], border_color=COLORS["border"])
        self.entry_watermark.grid(row=6, column=1, columnspan=3, padx=(4, 14), pady=6, sticky="ew")

        # Separador visual
        ctk.CTkFrame(rp, height=1, fg_color=COLORS["border"]).grid(row=7, column=0, columnspan=4, padx=14, pady=10, sticky="ew")

        # Row 8: Texto Inferior / CTA
        ctk.CTkLabel(rp, text="Texto Inferior (CTA):", font=ctk.CTkFont(size=11, weight="bold"), text_color=COLORS["text_primary"]).grid(row=8, column=0, padx=14, pady=(6, 2), sticky="w")
        ctk.CTkLabel(rp, text="Aparece centralizado na base do vídeo com fonte Lovely Scream Queens.", font=ctk.CTkFont(size=10), text_color=COLORS["text_secondary"]).grid(row=8, column=1, columnspan=3, padx=(4, 14), pady=(6, 2), sticky="w")

        ctk.CTkLabel(rp, text="Linha 1:", font=ctk.CTkFont(size=10, weight="bold"), text_color=COLORS["text_secondary"]).grid(row=9, column=0, padx=14, pady=3, sticky="w")
        ctk.CTkEntry(rp, textvariable=self.var_cta_l1, height=30, fg_color=COLORS["bg_dark"], border_color=COLORS["border"]).grid(row=9, column=1, columnspan=3, padx=(4, 14), pady=3, sticky="ew")

        ctk.CTkLabel(rp, text="Linha 2:", font=ctk.CTkFont(size=10, weight="bold"), text_color=COLORS["text_secondary"]).grid(row=10, column=0, padx=14, pady=3, sticky="w")
        ctk.CTkEntry(rp, textvariable=self.var_cta_l2, height=30, fg_color=COLORS["bg_dark"], border_color=COLORS["border"]).grid(row=10, column=1, columnspan=3, padx=(4, 14), pady=3, sticky="ew")

        ctk.CTkLabel(rp, text="Linha 3 (opcional):", font=ctk.CTkFont(size=10, weight="bold"), text_color=COLORS["text_secondary"]).grid(row=11, column=0, padx=14, pady=3, sticky="w")
        ctk.CTkEntry(rp, textvariable=self.var_cta_l3, height=30, fg_color=COLORS["bg_dark"], border_color=COLORS["border"]).grid(row=11, column=1, columnspan=3, padx=(4, 14), pady=3, sticky="ew")

        # Botão Salvar no Rodapé
        save_f = ctk.CTkFrame(rp, fg_color="transparent")
        save_f.grid(row=12, column=0, columnspan=4, padx=14, pady=(16, 10), sticky="ew")
        save_f.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(
            save_f,
            text="Salvar Alterações do Perfil",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=38,
            fg_color=COLORS["accent_studio"],
            hover_color=COLORS["accent_studio_hover"],
            command=self._save_current_profile_changes
        ).grid(row=0, column=0, sticky="ew")

    def _update_color_sample(self):
        c = self.var_title_color.get().strip()
        try:
            self.color_sample_box.configure(fg_color=c)
        except Exception:
            pass

    def _refresh_profiles_list(self):
        for w in self.list_frame.winfo_children():
            w.destroy()

        self.profiles = cpm.get_all_profiles()
        self.active_id = cpm.get_active_profile_id()

        for pid, pdata in self.profiles.items():
            is_active = (pid == self.active_id)
            is_selected = (pid == self.selected_profile_id)

            item_card = ctk.CTkFrame(
                self.list_frame,
                fg_color=COLORS["bg_card_hover"] if is_selected else COLORS["bg_dark"],
                corner_radius=8,
                border_width=2 if is_selected else (1 if is_active else 0),
                border_color=COLORS["accent_studio"] if is_selected else (COLORS["success"] if is_active else "transparent")
            )
            item_card.pack(fill="x", pady=4, padx=2)
            item_card.grid_columnconfigure(1, weight=1)

            # Avatar miniatura
            avatar_p = pdata.get("profile_png", "assets/Perfil_1.png")
            resolved_p = cpm.get_base_dir() / avatar_p if not Path(avatar_p).is_absolute() else Path(avatar_p)
            if not resolved_p.exists():
                resolved_p = cpm.get_base_dir() / "assets" / Path(avatar_p).name

            thumb_ctk = None
            if resolved_p.exists():
                try:
                    pil_im = Image.open(resolved_p).convert("RGBA").resize((32, 32), Image.Resampling.LANCZOS)
                    thumb_ctk = ctk.CTkImage(pil_im, size=(32, 32))
                except Exception:
                    pass

            lbl_ic = ctk.CTkLabel(item_card, text="", image=thumb_ctk, width=32)
            lbl_ic.grid(row=0, column=0, rowspan=2, padx=(8, 4), pady=6)

            title_txt = pdata.get("name", pid)
            if is_active:
                title_txt += " ★ [Ativo]"

            lbl_t = ctk.CTkLabel(
                item_card,
                text=title_txt,
                font=ctk.CTkFont(size=12, weight="bold" if (is_selected or is_active) else "normal"),
                text_color=COLORS["accent_studio"] if is_selected else (COLORS["success"] if is_active else COLORS["text_primary"]),
                anchor="w"
            )
            lbl_t.grid(row=0, column=1, sticky="w", padx=(2, 6), pady=(6, 0))

            lbl_h = ctk.CTkLabel(
                item_card,
                text=pdata.get("handle", ""),
                font=ctk.CTkFont(size=10),
                text_color=COLORS["text_secondary"],
                anchor="w"
            )
            lbl_h.grid(row=1, column=1, sticky="w", padx=(2, 6), pady=(0, 6))

            # Bind clique para selecionar
            for w in (item_card, lbl_ic, lbl_t, lbl_h):
                w.bind("<Button-1>", lambda e, p_id=pid: self._select_profile(p_id))

    def _select_profile(self, profile_id: str):
        self.selected_profile_id = profile_id
        self._load_profile_into_editor(profile_id)
        self._refresh_profiles_list()

    def _load_profile_into_editor(self, profile_id: str):
        pdata = self.profiles.get(profile_id, {})
        if not pdata:
            return

        self.var_name.set(pdata.get("name", ""))
        self.var_handle.set(pdata.get("handle", ""))
        self.var_verified.set(bool(pdata.get("verified", False)))
        self.var_watermark.set(pdata.get("watermark_text", ""))
        self.var_title_color.set(pdata.get("title_color", "#FFFFFF"))

        lines = pdata.get("cta_lines", [])
        self.var_cta_l1.set(lines[0] if len(lines) > 0 else "")
        self.var_cta_l2.set(lines[1] if len(lines) > 1 else "")
        self.var_cta_l3.set(lines[2] if len(lines) > 2 else "")

        self.current_avatar_path = pdata.get("profile_png", "assets/Perfil_1.png")
        self._update_avatar_preview(self.current_avatar_path)

        is_active = (profile_id == self.active_id)
        if is_active:
            self.lbl_profile_status.configure(text=f"● PERFIL ATIVO NO STUDIO: {pdata.get('name')}", text_color=COLORS["success"])
            self.btn_set_active.configure(state="disabled", text="✓ Perfil Ativo")
        else:
            self.lbl_profile_status.configure(text=f"Perfil Selecionado: {pdata.get('name')}", text_color=COLORS["text_secondary"])
            self.btn_set_active.configure(state="normal", text="★ Usar no Studio")

        # Não permite excluir Animax
        if profile_id == "animax":
            self.btn_delete.configure(state="disabled")
        else:
            self.btn_delete.configure(state="normal")

    def _update_avatar_preview(self, img_path: str):
        resolved_p = cpm.get_base_dir() / img_path if not Path(img_path).is_absolute() else Path(img_path)
        if not resolved_p.exists():
            resolved_p = cpm.get_base_dir() / "assets" / Path(img_path).name

        if resolved_p.exists():
            try:
                pil_im = Image.open(resolved_p).convert("RGBA").resize((84, 84), Image.Resampling.LANCZOS)
                self._avatar_ctk_img = ctk.CTkImage(pil_im, size=(84, 84))
                self.lbl_avatar_preview.configure(image=self._avatar_ctk_img, text="")
            except Exception:
                self.lbl_avatar_preview.configure(image=None, text="[Sem Imagem]")
        else:
            self.lbl_avatar_preview.configure(image=None, text="[Sem Imagem]")

    def _browse_avatar_image(self):
        f = filedialog.askopenfilename(
            title="Selecione a Imagem de Perfil do Canal",
            filetypes=[("Imagens", "*.png *.jpg *.jpeg *.webp"), ("Todos", "*.*")]
        )
        if f and Path(f).exists():
            try:
                # Corta redondinho bonitinho automaticamente
                dst_name = f"Perfil_{self.selected_profile_id}.png"
                dst_path = str(cpm.get_base_dir() / "assets" / dst_name)
                cpm.make_circular_avatar(f, dst_path, size=270)
                self.current_avatar_path = f"assets/{dst_name}"
                self._update_avatar_preview(self.current_avatar_path)
                messagebox.showinfo("Foto de Perfil", "Foto cortada em formato circular com sucesso e salva!")
            except Exception as e:
                messagebox.showerror("Erro", f"Erro ao processar imagem: {e}")

    def _save_current_profile_changes(self):
        lines = [self.var_cta_l1.get().strip(), self.var_cta_l2.get().strip()]
        if self.var_cta_l3.get().strip():
            lines.append(self.var_cta_l3.get().strip())

        p_dict = {
            "id": self.selected_profile_id,
            "name": self.var_name.get().strip() or "Canal",
            "handle": self.var_handle.get().strip() or "@canal",
            "verified": bool(self.var_verified.get()),
            "profile_png": self.current_avatar_path or "assets/Perfil_1.png",
            "watermark_text": self.var_watermark.get().strip() or "@CANAL",
            "watermark_opacity": 0.38,
            "title_color": self.var_title_color.get().strip() or "#FFFFFF",
            "cta_lines": lines
        }

        cpm.save_or_update_profile(p_dict)
        self.profiles = cpm.get_all_profiles()
        self._refresh_profiles_list()
        self._load_profile_into_editor(self.selected_profile_id)
        if self.on_profile_changed and self.selected_profile_id == self.active_id:
            self.on_profile_changed(self.selected_profile_id)
        messagebox.showinfo("Perfil Salvo", f"Perfil '{p_dict['name']}' salvo com sucesso!")

    def _set_selected_as_active(self):
        cpm.set_active_profile_id(self.selected_profile_id)
        self.active_id = self.selected_profile_id
        self._refresh_profiles_list()
        self._load_profile_into_editor(self.selected_profile_id)
        if self.on_profile_changed:
            self.on_profile_changed(self.selected_profile_id)
        messagebox.showinfo("Perfil Ativado", f"O perfil '{self.var_name.get()}' agora está ativo no Studio Pipeline!")

    def _on_click_new_profile(self):
        new_id = f"canal_{len(self.profiles) + 1}"
        new_data = {
            "id": new_id,
            "name": f"Novo Canal {len(self.profiles) + 1}",
            "handle": "@novocanal",
            "verified": False,
            "profile_png": "assets/Perfil_1.png",
            "watermark_text": "@NOVOCANAL",
            "watermark_opacity": 0.38,
            "title_color": "#FFFFFF",
            "cta_lines": [
                "FINALMENTE ENCONTROU O CANAL",
                "SE INSCREVE PARA MAIS!"
            ]
        }
        cpm.save_or_update_profile(new_data)
        self.profiles = cpm.get_all_profiles()
        self.selected_profile_id = new_id
        self._refresh_profiles_list()
        self._load_profile_into_editor(new_id)

    def _delete_current_profile(self):
        if self.selected_profile_id == "animax":
            messagebox.showwarning("Aviso", "O perfil Animax é o padrão do sistema e não pode ser excluído.")
            return

        resp = messagebox.askyesno("Confirmar Exclusão", f"Deseja excluir o perfil '{self.var_name.get()}'?")
        if resp:
            cpm.delete_profile(self.selected_profile_id)
            self.profiles = cpm.get_all_profiles()
            self.selected_profile_id = "animax"
            self.active_id = cpm.get_active_profile_id()
            self._refresh_profiles_list()
            self._load_profile_into_editor("animax")
            if self.on_profile_changed:
                self.on_profile_changed(self.active_id)
