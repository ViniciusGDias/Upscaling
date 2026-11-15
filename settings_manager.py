"""
Settings Manager - Application Configuration & API Key Management
Handles loading, editing, saving, and testing API keys and AI models directly from the GUI.
Persists settings in .env and synchronizes os.environ in real-time.
"""

import os
import re
import json
import requests
import sys
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from dotenv import load_dotenv

def get_env_path() -> Path:
    """Find .env path robustly whether running as script or compiled PyInstaller binary."""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        if (exe_dir / ".env").exists():
            return exe_dir / ".env"
        if (exe_dir.parent.parent / ".env").exists():
            return exe_dir.parent.parent / ".env"
        if (exe_dir.parent / ".env").exists():
            return exe_dir.parent / ".env"
        return exe_dir / ".env"
    file_env = Path(__file__).parent / ".env"
    if file_env.exists():
        return file_env
    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        return cwd_env
    return file_env

ENV_PATH = get_env_path()

AVAILABLE_GEMINI_MODELS = [
    ("gemini-3.8-flash", "Gemini 3.8 Flash (Mais Novo / Rápido / Grátis)"),
    ("gemini-3.6-flash", "Gemini 3.6 Flash (Mais Estável & Rápido)"),
    ("gemini-3.7-flash", "Gemini 3.7 Flash (Grátis)"),
    ("gemini-3.5-flash", "Gemini 3.5 Flash (Grátis)"),
    ("gemini-flash-lite-latest", "Gemini Flash Lite (Ultra Rápido / 500 RPD)"),
    ("gemini-flash-latest", "Gemini Flash (Padrão)"),
    ("gemini-2.5-flash", "Gemini 2.5 Flash (Legado)"),
]

AVAILABLE_DIRECTOR_ENGINES = [
    ("gemini", "Google Gemini (Padrão Cloud / Grátis & Rápido)"),
    ("gemini_web", "Gemini Web (Navegador Pro / Tokens Ilimitados do Web Chat)"),
    ("ollama_local", "Ollama Local (Offline / RTX 5060 / Sem Custos)"),
    ("qwen_max", "Qwen 2.5 Max (Alibaba / Máximo Raciocínio & Lore)"),
    ("kimi", "Kimi Moonshot (Janela Longa / Maratona de Episódios)"),
]

AVAILABLE_GEMINI_WEB_MODELS = [
    ("4 Hydrogen", "Gemini 4 Hydrogen (Rápido / Ajuda no dia a dia - Recomendado)"),
    ("4 Argon", "Gemini 4 Argon (Tarefas complexas)"),
    ("3.1 Pro", "Gemini 3.1 Pro (Raciocínio avançado)"),
    ("3.8 Flash", "Gemini 3.8 Flash (Ajuda para tudo -> 4 Hydrogen)"),
    ("3.5 Flash Lite", "Gemini 3.5 Flash Lite (Respostas mais rápidas)"),
]

AVAILABLE_OLLAMA_MODELS = [
    ("qwen3.8:27b", "Qwen 3.8 27B (Máximo Raciocínio, Narrativa & Lore - 17GB)"),
    ("qwen2.5:7b", "Qwen 2.5 7B (Ultra Rápido & Slicing Cirúrgico / Recomendado)"),
    ("qwen2.5:14b", "Qwen 2.5 14B (Equilíbrio Perfeito Velocidade/Inteligência)"),
    ("qwen2.5vl:7b", "Qwen 2.5 VL 7B (Multimodal Texto & Visão de Cenas)"),
    ("qwen2.5vl:3b", "Qwen 2.5 VL 3B (Ultra Leve / Economiza VRAM)"),
    ("deepseek-r1:8b", "DeepSeek R1 8B (Raciocínio Profundo & Clímax)"),
    ("deepseek-r1:14b", "DeepSeek R1 14B (Raciocínio Avançado)"),
    ("llama3.1:8b", "Llama 3.1 8B (Ganchos Virais & Copywriting Meta)"),
    ("llama3.2-vision:latest", "Llama 3.2 Vision (Análise Visual Multimodal)"),
    ("llama3:latest", "Llama 3 8B (Meta Clássico)"),
    ("mistral:7b", "Mistral 7B (Direto & Sem Enrolação)"),
]

def get_installed_ollama_models(timeout: float = 2.0) -> List[str]:
    """Queries Ollama local instance for currently downloaded models."""
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=timeout)
        if resp.status_code == 200:
            return [m.get("name", "") for m in resp.json().get("models", []) if m.get("name")]
    except Exception:
        pass
    return []

def get_all_selectable_ollama_models() -> List[Tuple[str, str]]:
    """
    Returns an enriched list of (code, label) for Ollama models.
    Marks models that are currently installed with '🟢 [Instalado]'!
    Also includes any locally installed model not in the predefined list.
    """
    installed = get_installed_ollama_models()
    result = []
    seen = set()

    for code, label in AVAILABLE_OLLAMA_MODELS:
        is_inst = any(code == m or code.split(":")[0] == m.split(":")[0] for m in installed)
        badge = "🟢 " if is_inst else "📥 "
        inst_note = " [Instalado]" if is_inst else ""
        result.append((code, f"{badge}{label}{inst_note}"))
        seen.add(code)
        seen.add(code.split(":")[0])

    for m in installed:
        base = m.split(":")[0]
        if m not in seen and base not in seen:
            result.append((m, f"🟢 {m} (Modelo Local Detectado) [Instalado]"))
            seen.add(m)

    return result

AVAILABLE_REFINER_AI_ENGINES = [
    ("auto", "🤖 Automático (Ollama Local se Ativo, senão Nuvem)"),
    ("ollama_local", "🖥️ 100% IA Local (Ollama RTX 5060 / Zero Custos)"),
    ("cloud", "☁️ Nuvem Híbrida (Google Gemini 3.8 Flash + Groq Whisper)"),
]

AVAILABLE_WHISPER_MODES = [
    ("auto", "🤖 Automático (Groq Nuvem ➔ GPU Local large-v3)"),
    ("local_gpu", "⚡ 100% GPU Local (faster-whisper large-v3 — Sem Limite)"),
]




def load_app_settings(env_file_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load settings from .env file."""
    global ENV_PATH
    target_path = env_file_path or ENV_PATH
    if target_path is None:
        target_path = get_env_path()
        ENV_PATH = target_path
    if target_path and target_path.exists():
        load_dotenv(target_path, override=True)
    else:
        # Primeiro uso seguro para novos usuários: cria .env a partir do .env.example
        try:
            if target_path:
                example_p = target_path.parent / ".env.example"
                if not example_p.exists():
                    example_p = Path(__file__).parent / ".env.example"
                if example_p.exists():
                    import shutil
                    shutil.copy2(example_p, target_path)
                    load_dotenv(target_path, override=True)
                else:
                    load_dotenv(override=False)
            else:
                load_dotenv(override=False)
        except Exception:
            load_dotenv(override=False)

    gemini_raw = os.getenv("GEMINI_API_KEY", "")
    # Format gemini keys as one per line for the UI textarea
    gemini_keys = []
    for k in gemini_raw.replace(";", ",").split(","):
        clean_k = k.strip().strip('"\'')
        if clean_k and "sua_chave" not in clean_k.lower():
            gemini_keys.append(clean_k)

    gemini_keys_text = "\n".join(gemini_keys)
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
    gemini_web_model = os.getenv("GEMINI_WEB_PRIMARY_MODEL", "4 Hydrogen").strip()
    gemini_web_fallback = os.getenv("GEMINI_WEB_AUTO_FALLBACK", "true").lower() in ("true", "1", "yes")
    director_engine = os.getenv("DIRECTOR_ENGINE", "gemini").strip().lower()
    director_local_model = os.getenv("DIRECTOR_LOCAL_MODEL", "qwen2.5:7b").strip()
    refiner_ai_engine = os.getenv("REFINER_AI_ENGINE", "auto").strip().lower()
    whisper_mode = os.getenv("WHISPER_MODE", "auto").strip().lower()
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    felo_key = os.getenv("FELO_API_KEY", "").strip()
    check_updates = os.getenv("CHECK_UPDATES_ON_STARTUP", "true").lower() in ("true", "1", "yes")

    return {
        "gemini_keys": gemini_keys,
        "gemini_keys_text": gemini_keys_text,
        "gemini_model": gemini_model,
        "gemini_web_model": gemini_web_model,
        "gemini_web_fallback": gemini_web_fallback,
        "director_engine": director_engine,
        "director_local_model": director_local_model,
        "refiner_ai_engine": refiner_ai_engine,
        "whisper_mode": whisper_mode,
        "groq_key": groq_key,
        "openrouter_key": openrouter_key,
        "felo_key": felo_key,
        "check_updates": check_updates,
    }


def parse_keys_from_text(raw_text: str) -> List[str]:
    """Parse comma, semicolon, or newline-separated keys into a clean deduplicated list."""
    seen = set()
    clean_keys = []
    # Replace separators with newlines
    normalized = raw_text.replace(",", "\n").replace(";", "\n")
    for line in normalized.splitlines():
        k = line.strip().strip('"\'')
        if k and "sua_chave" not in k.lower() and k not in seen:
            seen.add(k)
            clean_keys.append(k)
    return clean_keys


def save_app_settings(
    gemini_keys_text: Optional[str] = None,
    gemini_model: Optional[str] = None,
    gemini_web_model: Optional[str] = None,
    gemini_web_fallback: Optional[bool] = None,
    groq_key: Optional[str] = None,
    openrouter_key: Optional[str] = None,
    felo_key: Optional[str] = None,
    check_updates: Optional[bool] = None,
    director_engine: Optional[str] = None,
    director_local_model: Optional[str] = None,
    refiner_ai_engine: Optional[str] = None,
    whisper_mode: Optional[str] = None,
    env_file_path: Optional[Path] = None,
) -> Tuple[bool, str]:
    """
    Save configuration to .env and synchronize runtime os.environ immediately.
    Only parameters that are explicitly passed (not None) will be updated.
    Existing keys in .env will remain intact.
    """
    try:
        keys_to_update: Dict[str, str] = {}
        msg_gemini_info = ""

        if gemini_keys_text is not None:
            keys_list = parse_keys_from_text(gemini_keys_text)
            joined_gemini = ",".join(keys_list)
            os.environ["GEMINI_API_KEY"] = joined_gemini
            keys_to_update["GEMINI_API_KEY"] = joined_gemini
            msg_gemini_info = f" ({len(keys_list)} chave(s) Gemini carregada(s))"

        if gemini_model is not None:
            clean_model = gemini_model.strip() or "gemini-3.8-flash"
            os.environ["GEMINI_MODEL"] = clean_model
            keys_to_update["GEMINI_MODEL"] = clean_model

        if gemini_web_model is not None:
            clean_gw_model = gemini_web_model.strip() or "4 Argon"
            os.environ["GEMINI_WEB_PRIMARY_MODEL"] = clean_gw_model
            keys_to_update["GEMINI_WEB_PRIMARY_MODEL"] = clean_gw_model

        if gemini_web_fallback is not None:
            gw_fb_val = "true" if gemini_web_fallback else "false"
            os.environ["GEMINI_WEB_AUTO_FALLBACK"] = gw_fb_val
            keys_to_update["GEMINI_WEB_AUTO_FALLBACK"] = gw_fb_val

        if director_engine is not None:
            clean_engine = director_engine.strip().lower() or "gemini"
            os.environ["DIRECTOR_ENGINE"] = clean_engine
            keys_to_update["DIRECTOR_ENGINE"] = clean_engine

        if director_local_model is not None:
            clean_local_model = director_local_model.strip() or "qwen2.5:7b"
            os.environ["DIRECTOR_LOCAL_MODEL"] = clean_local_model
            keys_to_update["DIRECTOR_LOCAL_MODEL"] = clean_local_model

        if refiner_ai_engine is not None:
            clean_ref_engine = refiner_ai_engine.strip().lower() or "auto"
            os.environ["REFINER_AI_ENGINE"] = clean_ref_engine
            keys_to_update["REFINER_AI_ENGINE"] = clean_ref_engine

        if whisper_mode is not None:
            clean_w_mode = whisper_mode.strip().lower() or "auto"
            os.environ["WHISPER_MODE"] = clean_w_mode
            keys_to_update["WHISPER_MODE"] = clean_w_mode

        if groq_key is not None:
            clean_groq = groq_key.strip().strip('"\'').splitlines()[0].strip() if groq_key.strip() else ""
            if clean_groq.startswith("AQ.") or clean_groq.startswith("AIzaSy"):
                clean_groq = ""  # User mistakenly pasted a Gemini key into Groq
            os.environ["GROQ_API_KEY"] = clean_groq
            keys_to_update["GROQ_API_KEY"] = clean_groq

        if openrouter_key is not None:
            clean_or = openrouter_key.strip().strip('"\'').splitlines()[0].strip() if openrouter_key.strip() else ""
            os.environ["OPENROUTER_API_KEY"] = clean_or
            keys_to_update["OPENROUTER_API_KEY"] = clean_or

        if felo_key is not None:
            clean_felo = felo_key.strip().strip('"\'').splitlines()[0].strip() if felo_key.strip() else ""
            os.environ["FELO_API_KEY"] = clean_felo
            keys_to_update["FELO_API_KEY"] = clean_felo

        if check_updates is not None:
            upd_val = "true" if check_updates else "false"
            os.environ["CHECK_UPDATES_ON_STARTUP"] = upd_val
            keys_to_update["CHECK_UPDATES_ON_STARTUP"] = upd_val

        target_path = env_file_path or ENV_PATH
        if target_path is None:
            target_path = get_env_path()

        env_lines = []
        if target_path.exists():
            with open(target_path, "r", encoding="utf-8") as f:
                env_lines = f.readlines()

        updated_keys = set()
        new_lines = []
        for line in env_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                new_lines.append(line)
                continue
            if "=" in stripped:
                k, _ = stripped.split("=", 1)
                k = k.strip()
                if k in keys_to_update:
                    new_lines.append(f"{k}={keys_to_update[k]}\n")
                    updated_keys.add(k)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)

        # Append any new keys not already in the file
        for k, v in keys_to_update.items():
            if k not in updated_keys:
                new_lines.append(f"{k}={v}\n")

        with open(target_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        return True, f"Configurações salvas com sucesso!{msg_gemini_info}"
    except Exception as e:
        return False, f"Erro ao salvar configurações: {e}"


def test_gemini_connection(api_key: str, model: str = "gemini-2.5-flash") -> Tuple[bool, str]:
    """
    Test a single Gemini API key with a minimal prompt.
    Returns (success, message).
    """
    clean_k = api_key.strip().strip('"\'')
    if not clean_k:
        return False, "Nenhuma chave Gemini fornecida."

    test_models = [model, "gemini-2.5-flash", "gemini-flash-lite-latest"]
    last_err = ""

    for m in test_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={clean_k}"
        payload = {
            "contents": [{"parts": [{"text": "Diga 'OK' em 1 palavra."}]}],
            "generationConfig": {"maxOutputTokens": 10, "temperature": 0.1}
        }
        try:
            resp = requests.post(url, json=payload, timeout=12)
            if resp.status_code == 200:
                return True, f"Conexão ativa com sucesso! Modelo: {m}"
            elif resp.status_code == 400:
                last_err = f"Chave inválida ou modelo não suportado (HTTP 400)."
            elif resp.status_code == 403:
                return False, "Chave da API não autorizada ou restrita (HTTP 403)."
            elif resp.status_code == 429:
                return False, "Limite temporário de requisições atingido (HTTP 429). A chave é válida, aguarde alguns instantes."
            else:
                last_err = f"HTTP {resp.status_code}: {resp.text[:100]}"
        except Exception as e:
            last_err = str(e)

    return False, f"Falha ao conectar ao Gemini: {last_err}"


def test_groq_connection(api_key: str) -> Tuple[bool, str]:
    """Test Groq API key."""
    clean_k = api_key.strip().strip('"\'')
    if not clean_k:
        return False, "Nenhuma chave Groq fornecida."

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {clean_k}"}
    payload = {
        "model": "qwen/qwen3.8-27b",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        if resp.status_code == 200:
            return True, "Groq conectado com sucesso! (Fallback ultrarrápido ativo)"
        elif resp.status_code == 401:
            return False, "Chave Groq inválida (HTTP 401)."
        else:
            return False, f"Groq retornou HTTP {resp.status_code}: {resp.text[:100]}"
    except Exception as e:
        return False, f"Falha na conexão com Groq: {e}"


def test_openrouter_connection(api_key: str) -> Tuple[bool, str]:
    """Test OpenRouter API key."""
    clean_k = api_key.strip().strip('"\'')
    if not clean_k:
        return False, "Nenhuma chave OpenRouter fornecida."

    url = "https://openrouter.ai/api/v1/auth/key"
    headers = {"Authorization": f"Bearer {clean_k}"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            label = data.get("label", "Ativa")
            return True, f"OpenRouter conectado! ({label})"
        return False, f"OpenRouter retornou HTTP {resp.status_code}"
    except Exception as e:
        return False, f"Falha ao conectar com OpenRouter: {e}"


def test_ollama_connection(model: str = "qwen2.5:7b") -> Tuple[bool, str]:
    """Test local Ollama connection and check if requested model is available."""
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        if resp.status_code == 200:
            models_data = resp.json().get("models", [])
            installed_names = [m.get("name", "") for m in models_data]
            matched = any(model in name or name in model for name in installed_names)
            if matched:
                return True, f"Ollama Local Ativo! Modelo '{model}' pronto na GPU."
            inst_str = ", ".join(installed_names[:3]) if installed_names else "nenhum"
            return True, f"Ollama Ativo! (Modelos detectados: {inst_str})"
        return False, f"Ollama respondeu com HTTP {resp.status_code}"
    except Exception:
        return False, "Ollama não está em execução (localhost:11434 offline)."


# Auto-load on import so os.environ is ready across all modules
try:
    load_app_settings()
except Exception:
    pass

