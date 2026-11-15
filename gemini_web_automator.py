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
_WEB_AUTOMATION_LOCK = threading.Lock()

_CHROME_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--disable-dev-shm-usage",
    "--disable-extensions",
    "--no-sandbox",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--start-maximized",
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
    """Fecha processos órfãos do Chrome deste perfil apenas quando existir lock ativo no disco."""
    try:
        has_lock = any(
            (profile_dir / name).exists()
            for name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile")
        )
        if not has_lock:
            return
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


# ═══════════════════════════════════════════════════════════════════════════════
# SESSÕES PERSISTENTES POR ANIME / TÓPICO
# ═══════════════════════════════════════════════════════════════════════════════
SESSION_MAP_FILE = PROFILE_DIR / "gemini_sessions.json"


def _clean_session_key(key: Optional[str]) -> str:
    if not key:
        return "default"
    import re
    import hashlib
    raw = str(key).strip()
    clean = re.sub(r'[^a-zA-Z0-9_\-]', '_', raw.lower())
    clean = re.sub(r'_+', '_', clean).strip('_')
    digest = hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()[:8]
    prefix = clean[:31] if clean else "chat"
    return f"{prefix}_{digest}"


def get_saved_chat_url(session_key: str) -> Optional[str]:
    """Retorna a URL do chat salvo para o anime/tópico especificado."""
    try:
        if SESSION_MAP_FILE.exists():
            import json
            with open(SESSION_MAP_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get(_clean_session_key(session_key))
    except Exception:
        pass
    return None


def save_chat_url(session_key: str, url: str):
    """Associa a URL do chat ao anime/tópico no arquivo de sessões."""
    try:
        import json
        data = {}
        if SESSION_MAP_FILE.exists():
            try:
                with open(SESSION_MAP_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data[_clean_session_key(session_key)] = url.strip()
        with open(SESSION_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def clear_chat_session(session_key: Optional[str] = None):
    """Limpa a sessão salva para um anime específico ou todas as sessões."""
    try:
        import json
        if not SESSION_MAP_FILE.exists():
            return
        if not session_key:
            # Limpa todas
            SESSION_MAP_FILE.unlink(missing_ok=True)
            return
        with open(SESSION_MAP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        c_key = _clean_session_key(session_key)
        if c_key in data:
            del data[c_key]
            with open(SESSION_MAP_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _safe_log(on_log, m: str):
    if on_log:
        try:
            on_log(m)
        except UnicodeEncodeError:
            try:
                on_log(m.encode("ascii", "replace").decode("ascii"))
            except Exception:
                pass
        except Exception:
            pass
    else:
        try:
            print(m)
        except UnicodeEncodeError:
            try:
                print(m.encode("ascii", "replace").decode("ascii"))
            except Exception:
                pass
        except Exception:
            pass


def _is_model_error(text: str) -> bool:
    """Detecta se o Gemini retornou uma mensagem de erro de cota ou limite do modelo."""
    if not text:
        return False
    low = text.lower()
    error_patterns = [
        "você atingiu o limite",
        "atingiu o limite",
        "limite de mensagens",
        "limite diário",
        "ocorreu um erro",
        "não foi possível gerar uma resposta",
        "tente novamente mais tarde",
        "algo deu errado",
        "you've reached your limit",
        "message limit",
        "daily limit",
        "something went wrong",
        "please try again later",
        "upgrade to gemini advanced",
    ]
    if len(text) < 450 and any(p in low for p in error_patterns):
        return True
    return False


def _dismiss_overlays_and_modals(page):
    """Fecha popups/diálogos promocionais rapidamente em 1 chamada JS sem afetar menus úteis."""
    try:
        dismissed = page.evaluate("""() => {
            let acted = false;
            const modalRoots = document.querySelectorAll(
                'mat-dialog-container, .cdk-overlay-pane [class*="treatment"], .cdk-overlay-pane [class*="promo"]'
            );
            const dismissTexts = new Set([
                'entendi', 'got it', 'agora não', 'agora nao', 'not now',
                'fechar', 'close', 'continuar', 'concluir', 'ok', 'dispensar', 'dismiss'
            ]);
            for (const root of modalRoots) {
                const btns = root.querySelectorAll('button');
                for (const b of btns) {
                    if (b.offsetParent === null) continue;
                    const txt = (b.innerText || '').trim().toLowerCase();
                    const lbl = (b.getAttribute('aria-label') || '').trim().toLowerCase();
                    if (dismissTexts.has(txt) || lbl.includes('fechar') || lbl.includes('close') || lbl.includes('dismiss')) {
                        try { b.click(); acted = true; } catch(e) {}
                    }
                }
            }
            const backdrops = document.querySelectorAll(
                '.cdk-overlay-backdrop, .cdk-overlay-dark-backdrop, .cdk-overlay-container [class*="treatment"]'
            );
            for (const el of backdrops) {
                if (el.offsetParent === null) continue;
                try {
                    const container = el.closest('.cdk-overlay-pane') || el;
                    container.style.display = 'none';
                    container.style.pointerEvents = 'none';
                    acted = true;
                } catch(e) {}
            }
            return acted;
        }""")
        if dismissed:
            page.wait_for_timeout(120)
    except Exception:
        pass


def _normalize_web_model_target(model_name: Optional[str]) -> str:
    m = (model_name or "").strip().lower()
    if "lite" in m or "3.5" in m:
        return "3.5 Flash Lite"
    if "3.1" in m or "pro" in m:
        return "3.1 Pro"
    if "hydrogen" in m or "3.8" in m or "flash" in m:
        return "4 Hydrogen"
    if "argon" in m:
        return "4 Argon"
    return "4 Hydrogen"


def _switch_model_on_page(page, model_name: str, on_log: Optional[Callable[[str], None]] = None) -> bool:
    """Alterna o modelo ativo no Gemini Web ('4 Hydrogen', '4 Argon', '3.1 Pro', '3.5 Flash Lite')."""
    def _log(m):
        _safe_log(on_log, m)

    target = _normalize_web_model_target(model_name)
    try:
        _dismiss_overlays_and_modals(page)

        mode_btn = None
        try:
            mode_btn = page.wait_for_selector('button[data-test-id="bard-mode-menu-button"]', timeout=5000)
        except Exception:
            mode_btn = page.query_selector('button[data-test-id="bard-mode-menu-button"]')
        if not mode_btn:
            return False

        current_t = (mode_btn.inner_text() or "").strip().lower()
        if target == "4 Hydrogen" and "hydrogen" in current_t:
            return True
        if target == "3.5 Flash Lite" and "lite" in current_t:
            return True
        if target == "3.1 Pro" and "pro" in current_t:
            return True
        if target == "4 Argon" and "argon" in current_t:
            return True

        _log(f"⚡ [GEMINI WEB] Configurando modelo para '{target}'...")

        try:
            mode_btn.click(timeout=2500, force=True)
        except Exception:
            page.evaluate("(el) => el.click()", mode_btn)
        page.wait_for_timeout(550)

        clicked = False
        items = page.query_selector_all('gem-menu-item, [role="menuitem"], .mat-mdc-menu-item')
        for it in items:
            t = (it.inner_text() or "").strip()
            tl = t.lower()
            match = (
                (target == "4 Hydrogen" and ("hydrogen" in tl or "ajuda no dia" in tl or ("flash" in tl and "lite" not in tl)))
                or (target == "4 Argon" and "argon" in tl)
                or (target == "3.1 Pro" and ("3.1 pro" in tl or "pesquisa detalhada" in tl))
                or (target == "3.5 Flash Lite" and ("lite" in tl or "respostas rápidas" in tl))
            )
            if match:
                try:
                    it.click(timeout=2500, force=True)
                except Exception:
                    page.evaluate("(el) => el.click()", it)
                page.wait_for_timeout(650)
                _log(f"✓ Modelo '{target}' ativado!")
                clicked = True
                break

        # Se ativou 4 Argon, garante nível de raciocínio 'Baixo Rápido e eficiente' para não travar 3 minutos pensando
        if clicked and target == "4 Argon":
            try:
                mode_btn = page.query_selector('button[data-test-id="bard-mode-menu-button"]')
                if mode_btn:
                    mode_btn.click(timeout=2000, force=True)
                    page.wait_for_timeout(450)
                    for it in page.query_selector_all('gem-menu-item, [role="menuitem"], .mat-mdc-menu-item, button'):
                        tl = (it.inner_text() or "").strip().lower()
                        if "baixo" in tl and ("rápido" in tl or "rapido" in tl or "eficiente" in tl):
                            if it.get_attribute("aria-checked") != "true":
                                it.click(timeout=2000, force=True)
                                page.wait_for_timeout(400)
                            else:
                                page.keyboard.press("Escape")
                            break
                    else:
                        page.keyboard.press("Escape")
            except Exception:
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass

        if not clicked:
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
        return clicked
    except Exception as e:
        _log(f"⚠️ Aviso ao alternar modelo: {e}")
    return False


def ask_gemini_web(
    prompt: str,
    timeout: int = 240,
    headless: bool = True,
    on_log: Optional[Callable[[str], None]] = None,
    session_key: Optional[str] = None,
    new_chat: bool = False,
    preferred_model: Optional[str] = None,
    **kwargs
) -> str:
    """
    Envia um prompt para o Gemini Web (gemini.google.com/app) em segundo plano (headless).
    Estratégia Resiliente com Contingência Automática:
    - Inicia no modelo '4 Argon' (máxima inteligência e tarefas complexas).
    - Se encontrar limite de cota ou erro no 4 Argon, alterna automaticamente para '3.8 Flash'.
    - NUNCA fecha o navegador antes do término da digitação (aguarda o desaparecimento do botão de parada).
    """
    def _log(m):
        _safe_log(on_log, m)

    if not is_logged_in():
        _log("⚠️ [GEMINI WEB] Nenhuma conta Google conectada.")
        _log("👉 Clique no botão '🔑 Conectar Conta Google' para fazer login uma única vez no navegador.")
        return ""

    if not preferred_model:
        try:
            from settings_manager import load_app_settings
            preferred_model = load_app_settings().get("gemini_web_model", "4 Argon")
        except Exception:
            preferred_model = "4 Argon"

    p_dir = get_profile_dir()

    with _WEB_AUTOMATION_LOCK:
        _release_profile_lock(p_dir)
        _log("🌐 [GEMINI WEB] Abrindo navegador Chrome...")

        with sync_playwright() as p:
            browser = None
            try:
                browser = p.chromium.launch_persistent_context(
                    user_data_dir=str(p_dir),
                    channel="chrome",
                    headless=headless,
                    args=_CHROME_ARGS,
                    ignore_default_args=["--enable-automation"]
                )
                page = browser.pages[0] if browser.pages else browser.new_page()

                # Anti-bot stealth: mascara a sessão para o Google tratar como humano
                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    window.chrome = { runtime: {} };
                """)

                def _check_is_generating() -> bool:
                    """Detecta de forma precisa se o Gemini Web ainda está gerando (sem falso positivo em SVGs)."""
                    try:
                        return bool(page.evaluate("""() => {
                            const stopSelectors = [
                                'button[aria-label*="interromper" i]',
                                'button[aria-label*="parar" i]',
                                'button[aria-label*="stop" i]',
                                'button[mattooltip*="interromper" i]',
                                'button[mattooltip*="parar" i]',
                                'button[mattooltip*="stop" i]',
                                'button.stop-button',
                                '[data-test-id*="stop"]',
                                'mat-icon[data-mat-icon-name="stop"]',
                                'mat-icon[data-mat-icon-name="pause"]',
                                '.stop-icon'
                            ];
                            for (const sel of stopSelectors) {
                                const el = document.querySelector(sel);
                                if (el && el.offsetParent !== null) {
                                    const r = el.getBoundingClientRect();
                                    if (r.width > 0 && r.height > 0) return true;
                                }
                            }

                            // Botão específico com quadrado de stop (M6 6h12v12H6z), sem varrer qualquer <rect> da página
                            const exactStops = document.querySelectorAll('button svg path[d*="M6 6h12v12H6z"]');
                            for (const pEl of exactStops) {
                                const btn = pEl.closest('button');
                                if (btn && btn.offsetParent !== null) return true;
                            }

                            // Indicadores reais de streaming ativos
                            const anim = document.querySelectorAll(
                                '.typing-indicator, .response-streaming, model-response .loading-spinner'
                            );
                            for (const a of anim) {
                                if (a.offsetParent !== null && a.getBoundingClientRect().height > 0) return true;
                            }

                            return false;
                        }"""))
                    except Exception:
                        return False

                def _get_non_empty_texts():
                    try:
                        return page.evaluate("""() => {
                            const results = [];
                            let items = document.querySelectorAll('model-response');
                            if (!items || items.length === 0) {
                                items = document.querySelectorAll('message-content, structured-content-container, .model-response-text');
                            }
                            for (const el of items) {
                                let t = '';
                                const mdList = el.querySelectorAll('.markdown');
                                if (mdList && mdList.length > 0) {
                                    t = Array.from(mdList).map(m => (m.innerText || m.textContent || '').trim()).filter(Boolean).join('\\n\\n');
                                }
                                if (!t) {
                                    t = (el.innerText || el.textContent || '').trim();
                                }
                                t = t.replace(/^O Gemini disse\\s*/i, '').replace(/^Gemini said\\s*/i, '').trim();
                                if (t && !results.includes(t)) {
                                    results.push(t);
                                }
                            }
                            return results;
                        }""")
                    except Exception:
                        return []

                def _open_chat():
                    reused = False
                    if not new_chat and session_key:
                        saved_chat_url = get_saved_chat_url(session_key)
                        if saved_chat_url:
                            _log(f"💬 [GEMINI WEB] Reabrindo chat contínuo de '{session_key}'...")
                            try:
                                page.goto(saved_chat_url, wait_until="domcontentloaded", timeout=25000)
                                page.wait_for_selector('div.ql-editor, div[role="textbox"], div[contenteditable="true"]', timeout=8000)
                                _dismiss_overlays_and_modals(page)
                                check_box = page.query_selector('div.ql-editor, div[role="textbox"], div[contenteditable="true"]')
                                if check_box:
                                    reused = True
                                    _log("✓ Chat contínuo restaurado com sucesso!")
                            except Exception:
                                pass

                    if not reused:
                        try:
                            page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=25000)
                            page.wait_for_selector('div.ql-editor, div[role="textbox"], div[contenteditable="true"]', timeout=10000)
                        except Exception:
                            pass

                        _dismiss_overlays_and_modals(page)

                        for nc_sel in [
                            'button[aria-label*="Nova conversa" i]',
                            'button[aria-label*="Novo chat" i]',
                            'button[aria-label*="New chat" i]',
                            'div[aria-label*="Nova conversa" i]',
                            'button[data-test-id="new-chat-button"]'
                        ]:
                            try:
                                nc_btn = page.query_selector(nc_sel)
                                if nc_btn and nc_btn.is_visible():
                                    try:
                                        nc_btn.click(timeout=1500, force=True)
                                    except Exception:
                                        page.evaluate("(el) => el.click()", nc_btn)
                                    page.wait_for_timeout(350)
                                    break
                            except Exception:
                                pass

                def _inject_prompt_fast(input_box, text_to_send: str) -> None:
                    """Injeta prompts longos instantaneamente via ClipboardEvent/paste, com fallback para keyboard.insert_text."""
                    try:
                        input_box.click(timeout=2500, force=True)
                    except Exception:
                        page.evaluate("(el) => { el.focus(); el.click(); }", input_box)
                    page.wait_for_timeout(120)

                    pasted_len = 0
                    try:
                        pasted_len = page.evaluate("""([el, txt]) => {
                            el.focus();
                            const dt = new DataTransfer();
                            dt.setData('text/plain', txt);
                            const evt = new ClipboardEvent('paste', {
                                clipboardData: dt,
                                bubbles: true,
                                cancelable: true
                            });
                            el.dispatchEvent(evt);
                            return (el.innerText || el.textContent || '').trim().length;
                        }""", [input_box, text_to_send])
                    except Exception:
                        pasted_len = 0

                    if not pasted_len or pasted_len < min(20, len(text_to_send.strip())):
                        page.keyboard.insert_text(text_to_send)
                    page.wait_for_timeout(200)

                def _trigger_send(input_box) -> None:
                    send_btn = page.query_selector(
                        'button[aria-label*="Enviar" i], button[aria-label*="Send" i], button.send-button'
                    )
                    if send_btn and send_btn.is_visible():
                        try:
                            send_btn.click(timeout=2000, force=True)
                            return
                        except Exception:
                            pass
                    try:
                        input_box.press("Enter")
                    except Exception:
                        input_box.press("Control+Enter")

                def _send_and_wait(target_model: str, max_wait: int) -> str:
                    _open_chat()
                    _switch_model_on_page(page, target_model, on_log=on_log)
                    _dismiss_overlays_and_modals(page)

                    input_box = None
                    for sel in ['div.ql-editor', 'div[contenteditable="true"]', 'div[role="textbox"]']:
                        try:
                            input_box = page.wait_for_selector(sel, timeout=10000)
                            if input_box:
                                break
                        except Exception:
                            continue

                    if not input_box:
                        if "/sorry" in page.url or "google.com/sorry" in page.url:
                            _log("🛑 [GEMINI WEB] O Google bloqueou temporariamente o navegador automatizado (verificação 'tráfego incomum' / CAPTCHA).")
                            _log("👉 Clique em '🔑 Conectar Conta Google', resolva a verificação manualmente na janela e feche-a. Depois tente novamente.")
                            return "__BLOCKED__"
                        _log(f"❌ [GEMINI WEB] Campo de mensagem não encontrado (URL atual: {page.url[:80]}).")
                        return ""

                    pre_texts = _get_non_empty_texts()
                    initial_count = len(pre_texts)

                    _log(f"✍️ [GEMINI WEB] Injetando prompt no modelo '{target_model}'...")
                    _inject_prompt_fast(input_box, prompt)

                    _log("🚀 [GEMINI WEB] Enviando mensagem...")
                    _trigger_send(input_box)

                    _log("⏳ [GEMINI WEB] Aguardando resposta do Gemini...")
                    page.wait_for_timeout(1200)

                    # Verifica se a caixa ainda está cheia (envio falhou) e tenta reenviar uma vez
                    try:
                        still_in_box = page.evaluate("(el) => (el.innerText || '').trim().length", input_box)
                        if still_in_box > 10 and not _check_is_generating():
                            _dismiss_overlays_and_modals(page)
                            _trigger_send(input_box)
                            page.wait_for_timeout(1000)
                    except Exception:
                        pass

                    start_time = time.time()
                    last_text = ""
                    stable_count = 0
                    last_log_sec = 0
                    ever_saw_activity = False
                    post_gen_empty_ticks = 0
                    brace_grace_ticks = 0

                    while time.time() - start_time < max_wait:
                        page.wait_for_timeout(1000)
                        elapsed = int(time.time() - start_time)

                        is_generating = _check_is_generating()
                        if is_generating:
                            ever_saw_activity = True
                            post_gen_empty_ticks = 0

                        if elapsed - last_log_sec >= 8:
                            last_log_sec = elapsed
                            if is_generating:
                                _log(f"🧠 [GEMINI WEB] [{target_model}] Escrevendo resposta ({elapsed}s)...")
                            else:
                                _log(f"⏳ [GEMINI WEB] [{target_model}] Aguardando tokens ({elapsed}s)...")

                        if is_generating:
                            stable_count = 0
                            brace_grace_ticks = 0
                            continue

                        current_texts = _get_non_empty_texts()
                        candidate = current_texts[-1] if current_texts else ""
                        is_new_response = bool(
                            candidate and (not pre_texts or candidate != pre_texts[-1] or len(current_texts) > initial_count)
                        )

                        if not is_new_response:
                            # Se já estava gerando e parou sem entregar texto, aborta em 5s para acionar contingência!
                            if ever_saw_activity:
                                post_gen_empty_ticks += 1
                                if post_gen_empty_ticks >= 5:
                                    _log(f"⚠️ [GEMINI WEB] '{target_model}' finalizou sem texto visível. Acionando contingência...")
                                    break
                            elif elapsed >= 40:
                                _log(f"⚠️ [GEMINI WEB] Sem resposta do '{target_model}' após 40s. Abortando espera ociosa...")
                                break
                            continue

                        ever_saw_activity = True
                        post_gen_empty_ticks = 0

                        # Proteção contra JSON incompleto com teto de espera pós-geração (máx 10s)
                        first_brace = candidate.find("{")
                        if first_brace != -1 and candidate.count("{") > candidate.count("}"):
                            brace_grace_ticks += 1
                            if brace_grace_ticks < 10:
                                stable_count = 0
                                continue
                        else:
                            brace_grace_ticks = 0

                        if candidate == last_text:
                            stable_count += 1
                            if stable_count >= 2:
                                if _is_model_error(candidate):
                                    _log(f"⚠️ [GEMINI WEB] Mensagem de erro/limite detectada no {target_model}: '{candidate[:80]}...'")
                                    return "__MODEL_ERROR__"

                                _log("✅ [GEMINI WEB] Resposta recebida e concluída com sucesso!")
                                if session_key:
                                    current_url = page.url
                                    if "/app/" in current_url and not current_url.endswith("/app"):
                                        save_chat_url(session_key, current_url)
                                    else:
                                        first_chat = page.query_selector('a[href*="/app/"]')
                                        if first_chat:
                                            href = first_chat.get_attribute("href") or ""
                                            if href.startswith("/"):
                                                href = f"https://gemini.google.com{href}"
                                            save_chat_url(session_key, href)

                                return candidate
                        else:
                            stable_count = 0
                            last_text = candidate

                    if last_text and not _is_model_error(last_text):
                        _log("⚠️ [GEMINI WEB] Tempo limite atingido, retornando texto capturado.")
                        return last_text
                    return ""

                # ── Execução Principal com Contingência Automática (4 Hydrogen / 4 Argon / 3.5 Flash Lite) ──
                primary = _normalize_web_model_target(preferred_model)
                _log(f"🎯 [GEMINI WEB] Modelo prioritário: '{primary}'")

                primary_wait = min(timeout, 95) if primary == "4 Argon" else min(timeout, 120)
                result = _send_and_wait(primary, max_wait=primary_wait)
                if result == "__BLOCKED__":
                    return ""

                if (result == "__MODEL_ERROR__" or not result) and primary != "4 Hydrogen":
                    _log(f"🔄 [CONTINGÊNCIA ATIVADA] Limite ou lentidão em '{primary}'. Alternando automaticamente para '4 Hydrogen'...")
                    result = _send_and_wait("4 Hydrogen", max_wait=min(timeout, 110))

                if (result == "__MODEL_ERROR__" or not result) and primary == "4 Hydrogen":
                    _log("🔄 [CONTINGÊNCIA ATIVADA] Alternando automaticamente para '3.5 Flash Lite'...")
                    result = _send_and_wait("3.5 Flash Lite", max_wait=min(timeout, 90))

                if result and result != "__MODEL_ERROR__":
                    return result

                _log("⚠️ [GEMINI WEB] Nenhuma resposta válida retornada.")
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


