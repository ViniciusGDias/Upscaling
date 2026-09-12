"""
Settings Tab - Application Configuration, API Keys, Engine Verification & Updater
Provides a centralized, modern interface for:
1. Managing Gemini, Groq, OpenRouter, and Felo API keys and model selection (reference from pasta 22).
2. Live testing of API connections with real-time status.
3. Automated verification and 1-click downloading of media engines (FFmpeg, Real-CUGAN, Whisper, Demucs).
4. Update checking and notification system.
5. Onboarding guide for new users.
"""

import os
import sys
import webbrowser
import threading
import customtkinter as ctk
from tkinter import messagebox
from typing import Optional, Callable

from settings_manager import (
    load_app_settings,
    save_app_settings,
    parse_keys_from_text,
    test_gemini_connection,
    test_groq_connection,
    test_openrouter_connection,
    AVAILABLE_GEMINI_MODELS
)
from engine_manager import (
    check_all_engines,
    download_and_install_ffmpeg
)
from updater import (
    CURRENT_VERSION,
    APP_NAME,
    check_for_updates,
    open_download_page
)

# Colors matching Minimal Black Pro
COLORS = {
    "bg_dark": "#09090b",
    "bg_card": "#111113",
    "bg_card_hover": "#18181b",
    "accent_primary": "#e2e8f0",
    "accent_secondary": "#94a3b8",
    "success": "#22c55e",
    "warning": "#f59e0b",
    "error": "#ef4444",
    "text_primary": "#fafafa",
    "text_secondary": "#71717a",
    "text_muted": "#3f3f46",
    "border": "#27272a",
    "border_active": "#52525b",
    "console_bg": "#050505",
}


class SettingsTab(ctk.CTkFrame):
    """Modern Settings and System Management tab."""

    def __init__(self, parent, main_app=None, log_callback: Optional[Callable[[str], None]] = None):
        super().__init__(parent, fg_color="transparent")
        self.main_app = main_app
        self.log_callback = log_callback

        self._build_ui()
        self.load_current_settings()
        self.refresh_engine_status()

    def _log(self, msg: str):
        if self.log_callback:
            try:
                self.log_callback(msg)
            except Exception:
                pass

    def _build_ui(self):
        self.scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["accent_primary"],
        )
        self.scroll.pack(fill="both", expand=True, padx=8, pady=8)

        # ── Header ──
        header = ctk.CTkFrame(self.scroll, fg_color="transparent")
        header.pack(fill="x", pady=(0, 14))

        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.pack(fill="x")

        ctk.CTkLabel(
            title_row,
            text="⚙️ Configurações & Motores",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        ctk.CTkLabel(
            title_row,
            text=f"v{CURRENT_VERSION}",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLORS["text_secondary"],
            fg_color=COLORS["bg_card"],
            corner_radius=6,
            padx=8, pady=3,
        ).pack(side="left", padx=(12, 0))

        ctk.CTkLabel(
            header,
            text="Gerencie suas chaves de IA, selecione modelos, monitore dependências do sistema e verifique atualizações.",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_secondary"],
            anchor="w",
        ).pack(fill="x", pady=(4, 0))

        ctk.CTkFrame(header, fg_color=COLORS["border"], height=1).pack(fill="x", pady=(10, 0))

        # ── Card 0: Guia do Novo Usuário (Zero Config) ──
        self._build_onboarding_guide()

        # ── Card 1: Chaves de IA & Modelos (Referência Pasta 22) ──
        self._build_ai_keys_section()

        # ── Card 2: Motores & Dependências (FFmpeg, CUGAN, PyTorch) ──
        self._build_engines_section()

        # ── Card 3: Atualizações do Aplicativo ──
        self._build_updates_section()

    def _build_onboarding_guide(self):
        card = ctk.CTkFrame(
            self.scroll, fg_color=COLORS["bg_card"],
            corner_radius=10, border_width=1, border_color=COLORS["border"],
        )
        card.pack(fill="x", pady=(0, 12))

        top_row = ctk.CTkFrame(card, fg_color="transparent")
        top_row.pack(fill="x", padx=16, pady=(12, 6))

        ctk.CTkLabel(
            top_row,
            text="🚀 Guia Rápido para Novo Usuário (Primeiros Passos)",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        guide_box = ctk.CTkFrame(card, fg_color="#141416", corner_radius=8)
        guide_box.pack(fill="x", padx=16, pady=(0, 14))

        steps = (
            "1. Crie sua chave gratuita no Google AI Studio (leva 30 segundos, sem cartão de crédito).\n"
            "2. Cole a chave gerada no campo 'Chave(s) Gemini' abaixo e clique em 'Salvar Configurações'.\n"
            "3. Pronto! O Diretor IA, Refinador Mastercut, YouTube Shorts, Instagram e Anime Finder estarão 100% ativos."
        )
        ctk.CTkLabel(
            guide_box,
            text=steps,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["accent_secondary"],
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=12, pady=10)

    def _build_ai_keys_section(self):
        card = ctk.CTkFrame(
            self.scroll, fg_color=COLORS["bg_card"],
            corner_radius=10, border_width=1, border_color=COLORS["border"],
        )
        card.pack(fill="x", pady=(0, 12))

        # Title Row
        title_row = ctk.CTkFrame(card, fg_color="transparent")
        title_row.pack(fill="x", padx=16, pady=(14, 8))

        ctk.CTkLabel(
            title_row,
            text="🧠 Configuração da API & Modelos de IA",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        self.key_count_badge = ctk.CTkLabel(
            title_row,
            text="0 chaves ativas",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_secondary"],
            fg_color="#18181b",
            corner_radius=12,
            padx=10, pady=2,
        )
        self.key_count_badge.pack(side="right")

        # Gemini Link Row
        link_row = ctk.CTkFrame(card, fg_color="transparent")
        link_row.pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(
            link_row,
            text="Para usar a IA, você precisa de uma chave da API do Google Gemini (100% Gratuita).",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_secondary"],
        ).pack(side="left")

        get_gemini_btn = ctk.CTkButton(
            link_row,
            text="🌐 Obter Chave Grátis no Google AI Studio →",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#18181b",
            hover_color=COLORS["border_active"],
            text_color="#4ade80",
            corner_radius=6,
            height=26,
            command=lambda: webbrowser.open("https://aistudio.google.com/apikey"),
        )
        get_gemini_btn.pack(side="right")

        # Gemini Keys Textarea
        label_k = ctk.CTkLabel(
            card,
            text="Chave(s) da API (Google Gemini) — Cole uma por linha para rotação automática:",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLORS["text_secondary"],
            anchor="w",
        )
        label_k.pack(fill="x", padx=16, pady=(6, 4))

        self.gemini_textbox = ctk.CTkTextbox(
            card,
            height=85,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#0d0d0f",
            text_color=COLORS["text_primary"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=6,
        )
        self.gemini_textbox.pack(fill="x", padx=16, pady=(0, 6))
        self.gemini_textbox.bind("<KeyRelease>", lambda e: self._update_key_count())

        # Gemini Model Selector
        model_row = ctk.CTkFrame(card, fg_color="transparent")
        model_row.pack(fill="x", padx=16, pady=(4, 10))

        ctk.CTkLabel(
            model_row,
            text="Modelo de IA Principal:",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLORS["text_secondary"],
        ).pack(side="left", padx=(0, 10))

        self.model_combo = ctk.CTkComboBox(
            model_row,
            values=[label for _, label in AVAILABLE_GEMINI_MODELS],
            font=ctk.CTkFont(family="Segoe UI", size=11),
            dropdown_font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color="#0d0d0f",
            border_color=COLORS["border"],
            button_color=COLORS["border"],
            button_hover_color=COLORS["border_active"],
            text_color=COLORS["text_primary"],
            dropdown_fg_color="#18181b",
            dropdown_text_color=COLORS["text_primary"],
            dropdown_hover_color="#27272a",
            width=320,
            corner_radius=6,
        )
        self.model_combo.pack(side="left")

        # ── Fallback Gratuito Section (Anti-Parada) ──
        fallback_card = ctk.CTkFrame(
            card, fg_color="#131713",
            corner_radius=8, border_width=1, border_color="#1e3a1e",
        )
        fallback_card.pack(fill="x", padx=16, pady=(6, 12))

        fb_header = ctk.CTkFrame(fallback_card, fg_color="transparent")
        fb_header.pack(fill="x", padx=12, pady=(10, 6))

        ctk.CTkLabel(
            fb_header,
            text="🛡️ Provedores de Fallback Gratuito (Anti-Parada)",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color="#4ade80",
        ).pack(side="left")

        ctk.CTkLabel(
            fallback_card,
            text="Quando o Gemini atingir o limite temporário por minuto (429), o sistema ativa o Groq instantaneamente para não parar a sua produção.",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=COLORS["accent_secondary"],
            justify="left", anchor="w",
        ).pack(fill="x", padx=12, pady=(0, 8))

        # Groq Input
        groq_row = ctk.CTkFrame(fallback_card, fg_color="transparent")
        groq_row.pack(fill="x", padx=12, pady=(0, 6))

        ctk.CTkLabel(
            groq_row, text="Groq API Key (14.400 req/dia grátis):",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=COLORS["text_secondary"], width=230, anchor="w",
        ).pack(side="left")

        self.groq_entry = ctk.CTkEntry(
            groq_row, placeholder_text="gsk_...",
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#0d0d0f", border_color=COLORS["border"], corner_radius=6,
            show="*",
        )
        self.groq_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        groq_btn = ctk.CTkButton(
            groq_row, text="Obter Chave Groq →",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            fg_color="#1f1f23", hover_color=COLORS["border_active"],
            text_color="#fb923c", corner_radius=6, height=26, width=125,
            command=lambda: webbrowser.open("https://console.groq.com/keys"),
        )
        groq_btn.pack(side="right")

        # OpenRouter Input
        or_row = ctk.CTkFrame(fallback_card, fg_color="transparent")
        or_row.pack(fill="x", padx=12, pady=(0, 6))

        ctk.CTkLabel(
            or_row, text="OpenRouter API Key (Opcional):",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=COLORS["text_secondary"], width=230, anchor="w",
        ).pack(side="left")

        self.openrouter_entry = ctk.CTkEntry(
            or_row, placeholder_text="sk-or-...",
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#0d0d0f", border_color=COLORS["border"], corner_radius=6,
            show="*",
        )
        self.openrouter_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        or_btn = ctk.CTkButton(
            or_row, text="Obter Chave OpenRouter →",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            fg_color="#1f1f23", hover_color=COLORS["border_active"],
            text_color="#c084fc", corner_radius=6, height=26, width=125,
            command=lambda: webbrowser.open("https://openrouter.ai/keys"),
        )
        or_btn.pack(side="right")

        # Felo Input
        felo_row = ctk.CTkFrame(fallback_card, fg_color="transparent")
        felo_row.pack(fill="x", padx=12, pady=(0, 10))

        ctk.CTkLabel(
            felo_row, text="Felo API Key (OX Alpha - Opcional):",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=COLORS["text_secondary"], width=230, anchor="w",
        ).pack(side="left")

        self.felo_entry = ctk.CTkEntry(
            felo_row, placeholder_text="fk-...",
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#0d0d0f", border_color=COLORS["border"], corner_radius=6,
            show="*",
        )
        self.felo_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        felo_btn = ctk.CTkButton(
            felo_row, text="Obter Chave Felo →",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            fg_color="#1f1f23", hover_color=COLORS["border_active"],
            text_color="#34d399", corner_radius=6, height=26, width=125,
            command=lambda: webbrowser.open("https://openapi.felo.ai"),
        )
        felo_btn.pack(side="right")

        # Status & Action Buttons
        status_row = ctk.CTkFrame(card, fg_color="transparent")
        status_row.pack(fill="x", padx=16, pady=(4, 14))

        self.ai_test_status = ctk.CTkLabel(
            status_row,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_secondary"],
            anchor="w",
        )
        self.ai_test_status.pack(side="left", fill="x", expand=True)

        self.test_ai_btn = ctk.CTkButton(
            status_row,
            text="🧪 Testar Conexão",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#1f1f23",
            hover_color=COLORS["border_active"],
            text_color=COLORS["text_primary"],
            corner_radius=6,
            height=32,
            width=130,
            command=self._test_api_connection,
        )
        self.test_ai_btn.pack(side="right", padx=(8, 0))

        self.save_settings_btn = ctk.CTkButton(
            status_row,
            text="💾 Salvar Configurações",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color=COLORS["accent_primary"],
            hover_color=COLORS["accent_secondary"],
            text_color=COLORS["bg_dark"],
            corner_radius=6,
            height=32,
            width=160,
            command=self._save_settings,
        )
        self.save_settings_btn.pack(side="right")

    def _build_engines_section(self):
        card = ctk.CTkFrame(
            self.scroll, fg_color=COLORS["bg_card"],
            corner_radius=10, border_width=1, border_color=COLORS["border"],
        )
        card.pack(fill="x", pady=(0, 12))

        top_row = ctk.CTkFrame(card, fg_color="transparent")
        top_row.pack(fill="x", padx=16, pady=(14, 8))

        ctk.CTkLabel(
            top_row,
            text="⚡ Motores & Dependências do Sistema",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        refresh_engines_btn = ctk.CTkButton(
            top_row,
            text="🔄 Re-verificar",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            fg_color="#18181b",
            hover_color=COLORS["border_active"],
            text_color=COLORS["text_secondary"],
            corner_radius=6,
            height=26,
            width=90,
            command=self.refresh_engine_status,
        )
        refresh_engines_btn.pack(side="right")

        # Container for engine cards
        self.engines_container = ctk.CTkFrame(card, fg_color="transparent")
        self.engines_container.pack(fill="x", padx=16, pady=(0, 14))

        # Progress bar for downloading engines
        self.engine_prog_frame = ctk.CTkFrame(card, fg_color="transparent")
        self.engine_progress = ctk.CTkProgressBar(
            self.engine_prog_frame,
            progress_color=COLORS["success"],
            fg_color="#18181b",
            height=8,
            corner_radius=4,
        )
        self.engine_prog_label = ctk.CTkLabel(
            self.engine_prog_frame,
            text="",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=COLORS["text_secondary"],
        )

    def _build_updates_section(self):
        card = ctk.CTkFrame(
            self.scroll, fg_color=COLORS["bg_card"],
            corner_radius=10, border_width=1, border_color=COLORS["border"],
        )
        card.pack(fill="x", pady=(0, 16))

        top_row = ctk.CTkFrame(card, fg_color="transparent")
        top_row.pack(fill="x", padx=16, pady=(14, 8))

        ctk.CTkLabel(
            top_row,
            text="🚀 Atualizações do Aplicativo",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        ctk.CTkLabel(
            top_row,
            text=f"Versão Atual: v{CURRENT_VERSION}",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_secondary"],
        ).pack(side="right")

        body_row = ctk.CTkFrame(card, fg_color="transparent")
        body_row.pack(fill="x", padx=16, pady=(0, 14))

        self.update_status_label = ctk.CTkLabel(
            body_row,
            text="Clique para verificar se há novas versões disponíveis.",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_secondary"],
            anchor="w",
        )
        self.update_status_label.pack(side="left", fill="x", expand=True)

        self.download_update_btn = ctk.CTkButton(
            body_row,
            text="⬇️ Baixar Nova Versão",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color=COLORS["success"],
            hover_color="#16a34a",
            text_color="#ffffff",
            corner_radius=6,
            height=30,
            command=lambda: open_download_page(self._latest_download_url),
        )

        self.check_update_btn = ctk.CTkButton(
            body_row,
            text="🔄 Verificar Agora",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#1f1f23",
            hover_color=COLORS["border_active"],
            text_color=COLORS["text_primary"],
            corner_radius=6,
            height=30,
            width=130,
            command=self._check_for_updates_ui,
        )
        self.check_update_btn.pack(side="right")

        self._latest_download_url = None

    # ── Logic & Handlers ──────────────────────────────────────────────────────

    def _update_key_count(self):
        text = self.gemini_textbox.get("1.0", "end")
        keys = parse_keys_from_text(text)
        count = len(keys)
        badge_text = f"{count} chave{'s' if count != 1 else ''} ativa{'s' if count != 1 else ''}"
        self.key_count_badge.configure(
            text=badge_text,
            text_color=COLORS["success"] if count > 0 else COLORS["text_secondary"]
        )

    def load_current_settings(self):
        """Populate fields with loaded settings."""
        settings = load_app_settings()

        self.gemini_textbox.delete("1.0", "end")
        self.gemini_textbox.insert("1.0", settings.get("gemini_keys_text", ""))
        self._update_key_count()

        cur_model = settings.get("gemini_model", "gemini-3.8-flash")
        # Match label
        matched_label = None
        for code, label in AVAILABLE_GEMINI_MODELS:
            if code == cur_model:
                matched_label = label
                break
        if matched_label:
            self.model_combo.set(matched_label)
        else:
            self.model_combo.set(AVAILABLE_GEMINI_MODELS[0][1])

        self.groq_entry.delete(0, "end")
        self.groq_entry.insert(0, settings.get("groq_key", ""))

        self.openrouter_entry.delete(0, "end")
        self.openrouter_entry.insert(0, settings.get("openrouter_key", ""))

        self.felo_entry.delete(0, "end")
        self.felo_entry.insert(0, settings.get("felo_key", ""))

    def _save_settings(self):
        """Save settings and apply them to runtime os.environ."""
        keys_text = self.gemini_textbox.get("1.0", "end")
        selected_label = self.model_combo.get()

        model_code = "gemini-3.8-flash"
        for code, label in AVAILABLE_GEMINI_MODELS:
            if label == selected_label:
                model_code = code
                break

        groq_val = self.groq_entry.get().strip()
        or_val = self.openrouter_entry.get().strip()
        felo_val = self.felo_entry.get().strip()

        success, msg = save_app_settings(
            gemini_keys_text=keys_text,
            gemini_model=model_code,
            groq_key=groq_val,
            openrouter_key=or_val,
            felo_key=felo_val,
            check_updates=True
        )

        if success:
            self.ai_test_status.configure(text=f"✓ {msg}", text_color=COLORS["success"])
            self._log(f"✓ Configurações salvas. {msg}")
            messagebox.showinfo("Configurações Salvas", f"{msg}\n\nTodas as ferramentas já estão utilizando as novas configurações.")
        else:
            self.ai_test_status.configure(text=f"✕ {msg}", text_color=COLORS["error"])
            messagebox.showerror("Erro ao Salvar", msg)

    def _test_api_connection(self):
        """Test API connectivity in background thread."""
        keys_text = self.gemini_textbox.get("1.0", "end")
        keys = parse_keys_from_text(keys_text)
        groq_val = self.groq_entry.get().strip()

        if not keys and not groq_val:
            messagebox.showwarning("Nenhuma Chave", "Por favor, insira ao menos uma chave da API do Gemini ou Groq antes de testar.")
            return

        self.test_ai_btn.configure(state="disabled", text="⏳ Testando...")
        self.ai_test_status.configure(text="Conectando aos servidores do Google / Groq...", text_color=COLORS["warning"])

        def _worker():
            results = []
            selected_label = self.model_combo.get()
            model_code = "gemini-2.5-flash"
            for code, label in AVAILABLE_GEMINI_MODELS:
                if label == selected_label:
                    model_code = code
                    break

            if keys:
                ok, msg = test_gemini_connection(keys[0], model=model_code)
                results.append(("Gemini", ok, msg))

            if groq_val:
                ok_groq, msg_groq = test_groq_connection(groq_val)
                results.append(("Groq", ok_groq, msg_groq))

            def _update_ui():
                self.test_ai_btn.configure(state="normal", text="🧪 Testar Conexão")
                all_ok = all(ok for _, ok, _ in results)
                status_texts = [f"{name}: {'✓ ' if ok else '✕ '}{m}" for name, ok, m in results]
                combined_msg = " | ".join(status_texts)
                self.ai_test_status.configure(
                    text=combined_msg,
                    text_color=COLORS["success"] if all_ok else COLORS["warning"]
                )
                if all_ok:
                    messagebox.showinfo("Teste de Conexão Bem-Sucedido! ✓", f"Tudo funcionando perfeitamente:\n\n" + "\n".join(status_texts))
                else:
                    messagebox.showwarning("Resultado do Teste", "\n".join(status_texts))

            self.after(0, _update_ui)

        threading.Thread(target=_worker, daemon=True).start()

    def refresh_engine_status(self):
        """Inspect all engines and render their status cards."""
        for widget in self.engines_container.winfo_children():
            widget.destroy()

        engines = check_all_engines()

        # 1. FFmpeg
        ff = engines["ffmpeg"]
        self._render_engine_card(
            title="🎬 FFmpeg & FFprobe (Processador de Vídeo e Áudio)",
            desc="Essencial para cortes, renderização, separação e compressão de mídia.",
            is_ok=ff["installed"],
            detail=f"Versão: {ff['version']} ({ff['path']})" if ff["installed"] else "Não encontrado no sistema.",
            action_btn_text="⬇️ Baixar FFmpeg Automaticamente (1-Clique)" if not ff["installed"] else None,
            action_cmd=self._auto_download_ffmpeg if not ff["installed"] else None,
        )

        # 2. Real-CUGAN
        cugan = engines["realcugan"]
        self._render_engine_card(
            title="⚡ Real-CUGAN Vulkan (Motor 4K para Anime)",
            desc="Upscaling ultrarrápido para animes e desenhos com modelos Pro e SE.",
            is_ok=cugan["installed"],
            detail="Binário e modelos prontos em ./bin/realcugan/" if cugan["installed"] else "Motor não encontrado em ./bin/realcugan/",
        )

        # 3. CUDA & GPU
        cuda = engines["cuda"]
        self._render_engine_card(
            title="🖥️ Aceleração por Hardware (GPU / CUDA)",
            desc="Processamento acelerado por placa de vídeo NVIDIA.",
            is_ok=cuda["available"],
            detail=f"GPU Ativa: {cuda['device_name']} ({cuda['vram_gb']} GB VRAM)" if cuda["available"] else "Modo CPU (Nenhuma GPU NVIDIA CUDA detectada)",
        )

        # 4. Whisper
        wh = engines["whisper"]
        self._render_engine_card(
            title="🧠 Faster-Whisper (Transcrição e Sincronia de Falas)",
            desc="Mapeamento de palavras e legendas com timestamps exatos.",
            is_ok=wh["available"],
            detail="Biblioteca Faster-Whisper pronta para uso local e via Groq Cloud." if wh["available"] else "Pendente",
        )

        # 5. Demucs
        dem = engines["demucs"]
        self._render_engine_card(
            title="🎧 Demucs (Separação Vocal e Instrumental Meta AI)",
            desc="Isolamento de vozes e trilhas sonoras.",
            is_ok=dem["available"],
            detail="Pronto para isolamento de canais." if dem["available"] else "Pendente",
        )

    def _render_engine_card(self, title: str, desc: str, is_ok: bool, detail: str, action_btn_text: Optional[str] = None, action_cmd: Optional[Callable] = None):
        row = ctk.CTkFrame(self.engines_container, fg_color="#141416", corner_radius=8, border_width=1, border_color=COLORS["border"])
        row.pack(fill="x", pady=4)

        inner = ctk.CTkFrame(row, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=10)

        left = ctk.CTkFrame(inner, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)

        title_frame = ctk.CTkFrame(left, fg_color="transparent")
        title_frame.pack(fill="x")

        status_tag = "✓ Pronto" if is_ok else "⚠️ Pendente"
        tag_color = COLORS["success"] if is_ok else COLORS["warning"]

        ctk.CTkLabel(
            title_frame, text=title,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        ctk.CTkLabel(
            title_frame, text=status_tag,
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=tag_color,
            fg_color="#18181b",
            corner_radius=6, padx=6, pady=1,
        ).pack(side="left", padx=(10, 0))

        ctk.CTkLabel(
            left, text=f"{desc} · {detail}",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=COLORS["text_secondary"],
            anchor="w",
        ).pack(fill="x", pady=(2, 0))

        if action_btn_text and action_cmd:
            btn = ctk.CTkButton(
                inner, text=action_btn_text,
                font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                fg_color=COLORS["accent_primary"],
                hover_color=COLORS["accent_secondary"],
                text_color=COLORS["bg_dark"],
                corner_radius=6, height=28,
                command=action_cmd,
            )
            btn.pack(side="right", padx=(8, 0))

    def _auto_download_ffmpeg(self):
        """Trigger automatic 1-click download of FFmpeg."""
        self.engine_prog_frame.pack(fill="x", padx=16, pady=(0, 10))
        self.engine_progress.set(0.05)
        self.engine_prog_label.configure(text="Iniciando download automático do FFmpeg...")
        self.engine_prog_label.pack(anchor="w", pady=(4, 0))

        def _on_prog(pct, msg):
            self.after(0, lambda: (self.engine_progress.set(pct), self.engine_prog_label.configure(text=msg)))

        def _on_log(msg):
            self._log(msg)

        def _on_comp(success, msg):
            def _done():
                self.engine_prog_frame.pack_forget()
                self.refresh_engine_status()
                if success:
                    messagebox.showinfo("FFmpeg Instalado! ✓", f"{msg}\n\nO FFmpeg já está disponível e pronto para uso em todas as abas.")
                    if self.main_app and hasattr(self.main_app, "_check_ffmpeg"):
                        self.main_app._check_ffmpeg()
                else:
                    messagebox.showerror("Erro no Download", msg)
            self.after(0, _done)

        download_and_install_ffmpeg(on_progress=_on_prog, on_log=_on_log, on_complete=_on_comp)

    def _check_for_updates_ui(self):
        """User clicked 'Verificar Agora' button."""
        self.check_update_btn.configure(state="disabled", text="⏳ Verificando...")
        self.update_status_label.configure(text="Consultando lançamentos no GitHub...", text_color=COLORS["warning"])

        def _worker():
            res = check_for_updates()

            def _update():
                self.check_update_btn.configure(state="normal", text="🔄 Verificar Agora")
                if res["has_update"]:
                    self._latest_download_url = res["download_url"]
                    self.update_status_label.configure(
                        text=f"🚀 Nova versão disponível: v{res['latest_version']} (Você está na v{CURRENT_VERSION})",
                        text_color=COLORS["success"]
                    )
                    self.download_update_btn.pack(side="right", padx=(0, 8))
                    msg_box = (
                        f"Uma nova versão ({res['release_title']}) foi lançada!\n\n"
                        f"Versão Atual: v{CURRENT_VERSION}\n"
                        f"Nova Versão: v{res['latest_version']}\n\n"
                        f"Deseja abrir a página de download agora?"
                    )
                    if messagebox.askyesno("Atualização Disponível!", msg_box):
                        open_download_page(res["download_url"])
                else:
                    self.update_status_label.configure(
                        text=f"✓ Você já está utilizando a versão mais recente (v{CURRENT_VERSION}).",
                        text_color=COLORS["text_secondary"]
                    )
                    self.download_update_btn.pack_forget()
                    messagebox.showinfo("Atualizado", f"Você já está na versão mais recente (v{CURRENT_VERSION}).")

            self.after(0, _update)

        threading.Thread(target=_worker, daemon=True).start()
