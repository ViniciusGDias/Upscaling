"""
Gemini Web Automator - Background Browser Automation for Gemini Web (gemini.google.com)
Allows using Gemini Pro / Advanced with full web token limits directly from Chrome in background (headless).
"""

import os
import sys
import time
import shutil
import sqlite3
import subprocess
import threading
from pathlib import Path
from typing import Optional, Callable, Dict, Any

from playwright.sync_api import sync_playwright

# Perfil persistente do Chrome onde os cookies da conta Google ficam salvos
PROFILE_DIR = Path(os.path.expanduser("~")) / ".gemini_web_automator_profile"

_CHROME_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-infobars",
    "--disable-dev-shm-usage",
    "--disable-extensions",
]


def get_profile_dir() -> Path:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return PROFILE_DIR


def get_chrome_path() -> Optional[str]:
    """Retorna o executável oficial do Google Chrome instalado no sistema."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def _release_profile_lock(profile_dir: Path):
    """Fecha qualquer processo do Chrome associado exclusivamente a este perfil para liberar o lock."""
    try:
        p_str = str(profile_dir).replace("/", "\\")
        ps_cmd = (
            f"Get-CimInstance Win32_Process -Filter \"Name = 'chrome.exe'\" | "
            f"Where-Object {{ $_.CommandLine -like '*{p_str}*' }} | "
            f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, timeout=6)
    except Exception:
        pass


def is_logged_in() -> bool:
    """
    Verifica instantaneamente via banco de cookies do Chrome se o usuário está logado na conta Google.
    Não requer abrir o navegador nem gasta recursos.
    """
    p_dir = get_profile_dir()
    cookie_db = p_dir / "Default" / "Network" / "Cookies"
    if not cookie_db.exists():
        # Em algumas versões fica diretamente em Default/Cookies
        cookie_db = p_dir / "Default" / "Cookies"
        if not cookie_db.exists():
            return False

    tmp_db = p_dir / "Default" / "Cookies_check_tmp"
    try:
        shutil.copy2(cookie_db, tmp_db)
        conn = sqlite3.connect(str(tmp_db))
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM cookies WHERE host_key LIKE '%google.com%'")
        cookie_names = {row[0] for row in cursor.fetchall()}
        conn.close()
        try:
            os.remove(tmp_db)
        except Exception:
            pass

        # Cookies essenciais de autenticação da conta Google
        auth_tokens = {"SID", "SSID", "SAPISID", "HSID", "__Secure-1PSID", "__Secure-3PSID"}
        return bool(cookie_names.intersection(auth_tokens))
    except Exception:
        return False


def open_login_window(on_log: Optional[Callable[[str], None]] = None, on_success: Optional[Callable[[], None]] = None):
    """
    Abre o Google Chrome nativo em janela normal para o usuário fazer login.
    NÃO fecha automaticamente! O usuário tem todo o tempo para digitar login, senha e 2FA.
    """
    def _log(m):
        if on_log:
            on_log(m)
        else:
            print(m)

    chrome_path = get_chrome_path()
    p_dir = get_profile_dir()
    _release_profile_lock(p_dir)

    _log("🌐 Abrindo Google Chrome para login da sua conta Google...")
    _log("👉 Faça login na janela que se abriu. Quando terminar, você pode fechar o Chrome. A sessão ficará salva!")

    login_url = "https://accounts.google.com/ServiceLogin?continue=https://gemini.google.com/app"

    if chrome_path and os.path.exists(chrome_path):
        cmd = [
            chrome_path,
            f"--user-data-dir={str(p_dir)}",
            "--no-first-run",
            "--no-default-browser-check",
            "--start-maximized",
            login_url,
        ]
        try:
            proc = subprocess.Popen(cmd)
        except Exception as e:
            _log(f"⚠️ Erro ao iniciar Chrome diretamente: {e}")
            proc = None
    else:
        _log("⚠️ Executável do Google Chrome não encontrado nos caminhos padrão.")
        return

    # Thread em background que monitora o momento em que o login é concluído
    def _monitor():
        detected = False
        for _ in range(180): # monitora por até 6 minutos
            time.sleep(2)
            if is_logged_in():
                detected = True
                _log("🎉 [SUCESSO] Conta Google detectada e conectada com sucesso!")
                _log("💡 Pode fechar a janela do Chrome quando quiser para usar o Gemini Pro no app.")
                if on_success:
                    try:
                        on_success()
                    except Exception:
                        pass
                break

    threading.Thread(target=_monitor, daemon=True).start()


def ask_gemini_web(
    prompt: str,
    timeout: int = 180,
    headless: bool = True,
    on_log: Optional[Callable[[str], None]] = None
) -> str:
    """
    Envia um prompt para o Gemini Web (gemini.google.com/app) em segundo plano (headless),
    aguarda a resposta completa e retorna o texto gerado.
    """
    def _log(m):
        if on_log:
            on_log(m)
        else:
            print(m)

    if not is_logged_in():
        _log("⚠️ [GEMINI WEB] Nenhuma conta Google conectada.")
        _log("👉 Clique no botão '🔑 Conectar Conta Google' acima para fazer login uma única vez no navegador.")
        return ""

    p_dir = get_profile_dir()
    # Libera qualquer lock de processo anterior
    _release_profile_lock(p_dir)

    _log("🌐 [GEMINI WEB] Iniciando navegador em segundo plano (Headless)...")

    with sync_playwright() as p:
        browser = None
        try:
            browser = p.chromium.launch_persistent_context(
                user_data_dir=str(p_dir),
                channel="chrome",
                headless=headless,
                args=_CHROME_ARGS
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            
            _log("🌐 [GEMINI WEB] Acessando gemini.google.com...")
            page.goto("https://gemini.google.com/app", timeout=35000)
            page.wait_for_timeout(2500)

            # Tenta clicar no botão de 'Novo chat' para garantir sessão limpa
            for nc_sel in [
                'a[href*="/app"]', 'button[aria-label*="Novo chat"]', 'button[aria-label*="New chat"]',
                'div[aria-label*="Novo chat"]', 'button[data-test-id="new-chat-button"]'
            ]:
                try:
                    nc_btn = page.query_selector(nc_sel)
                    if nc_btn and nc_btn.is_visible():
                        nc_btn.click()
                        page.wait_for_timeout(1000)
                        break
                except Exception:
                    pass

            # Aguarda a caixa de entrada de texto
            input_box = None
            for sel in ['div.ql-editor', 'div[role="textbox"]', 'rich-textarea', 'div[contenteditable="true"]']:
                try:
                    input_box = page.wait_for_selector(sel, timeout=8000)
                    if input_box:
                        break
                except Exception:
                    continue

            if not input_box:
                _log("❌ [GEMINI WEB] Campo de mensagem do Gemini não encontrado. Verifique se o login está ativo.")
                return ""

            # Registra respostas pré-existentes na tela antes do envio
            pre_responses = page.query_selector_all('message-content, .model-response-text')
            initial_count = len(pre_responses)

            _log("✍️ [GEMINI WEB] Injetando prompt estruturado no chat...")
            input_box.click()
            page.wait_for_timeout(400)

            # Injeta texto via execCommand para suportar multi-linhas com perfeição
            page.evaluate("""({el, text}) => {
                el.focus();
                document.execCommand('insertText', false, text);
            }""", {"el": input_box, "text": prompt})

            page.wait_for_timeout(800)

            # Procura botão de enviar ou aperta Enter
            _log("🚀 [GEMINI WEB] Enviando para o Gemini Pro...")
            sent = False
            send_btn = page.query_selector('button[aria-label*="Enviar"], button[aria-label*="Send"], button.send-button, mat-icon[data-mat-icon-name="send"]')
            if send_btn:
                try:
                    send_btn.click()
                    sent = True
                except Exception:
                    pass

            if not sent:
                input_box.press("Enter")

            # Aguarda o início da resposta
            _log("⏳ [GEMINI WEB] Aguardando raciocínio e geração do Gemini Pro...")
            page.wait_for_timeout(3500)

            # Monitora o término da geração garantindo que é a NOVA resposta
            start_time = time.time()
            last_text = ""
            stable_count = 0

            while time.time() - start_time < timeout:
                page.wait_for_timeout(2000)

                # Busca as respostas do modelo
                responses = page.query_selector_all('message-content, .model-response-text')
                
                # Só analisa se houver uma NOVA resposta após a nossa mensagem
                if len(responses) > initial_count:
                    target_response = responses[-1]
                    current_text = target_response.inner_text().strip()
                elif initial_count == 0 and responses:
                    target_response = responses[-1]
                    current_text = target_response.inner_text().strip()
                else:
                    # Ainda está pensando, não gerou o container da nova resposta
                    current_text = ""
                    stable_count = 0
                    continue

                # Verifica se botão de parar sumiu
                stop_btn = page.query_selector('button[aria-label*="Parar"], button[aria-label*="Stop"]')
                copy_btn = target_response.query_selector('button[aria-label*="Copiar"], button[aria-label*="Copy"]')

                if current_text and current_text == last_text:
                    stable_count += 1
                    # Texto estável por 4s e sem botão de parar, ou botão de copiar já renderizado
                    if (stable_count >= 2 and not stop_btn) or copy_btn:
                        _log("✅ [GEMINI WEB] Resposta completa recebida com sucesso!")
                        return current_text
                else:
                    stable_count = 0
                    last_text = current_text

            if last_text:
                _log("⚠ [GEMINI WEB] Tempo limite atingido, capturando resposta obtida.")
                return last_text

            _log("❌ [GEMINI WEB] Nenhuma resposta retornada dentro do tempo limite.")
            return ""

        except Exception as e:
            _log(f"❌ [GEMINI WEB] Erro na automação: {e}")
            return ""
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
