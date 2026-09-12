"""
Settings Manager - Application Configuration & API Key Management
Handles loading, editing, saving, and testing API keys and AI models directly from the GUI.
Persists settings in .env and synchronizes os.environ in real-time.
"""

import os
import re
import json
import requests
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent / ".env"

AVAILABLE_GEMINI_MODELS = [
    ("gemini-3.6-flash", "Gemini 3.6 Flash (Mais Estável & Rápido)"),
    ("gemini-3.8-flash", "Gemini 3.8 Flash (Mais Novo / Grátis)"),
    ("gemini-3.7-flash", "Gemini 3.7 Flash (Grátis)"),
    ("gemini-3.5-flash", "Gemini 3.5 Flash (Grátis)"),
    ("gemini-flash-lite-latest", "Gemini Flash Lite (Ultra Rápido / 500 RPD)"),
    ("gemini-flash-latest", "Gemini Flash (Padrão)"),
    ("gemini-2.5-flash", "Gemini 2.5 Flash (Legado)"),
]


def load_app_settings() -> Dict[str, Any]:
    """Load settings from .env file."""
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH, override=True)

    gemini_raw = os.getenv("GEMINI_API_KEY", "")
    # Format gemini keys as one per line for the UI textarea
    gemini_keys = []
    for k in gemini_raw.replace(";", ",").split(","):
        clean_k = k.strip().strip('"\'')
        if clean_k and "sua_chave" not in clean_k.lower():
            gemini_keys.append(clean_k)

    gemini_keys_text = "\n".join(gemini_keys)
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    felo_key = os.getenv("FELO_API_KEY", "").strip()
    check_updates = os.getenv("CHECK_UPDATES_ON_STARTUP", "true").lower() in ("true", "1", "yes")

    return {
        "gemini_keys": gemini_keys,
        "gemini_keys_text": gemini_keys_text,
        "gemini_model": gemini_model,
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
    gemini_keys_text: str,
    gemini_model: str,
    groq_key: str = "",
    openrouter_key: str = "",
    felo_key: str = "",
    check_updates: bool = True
) -> Tuple[bool, str]:
    """
    Save configuration to .env and synchronize runtime os.environ immediately.
    """
    try:
        keys_list = parse_keys_from_text(gemini_keys_text)
        joined_gemini = ",".join(keys_list)
        clean_groq = groq_key.strip().strip('"\'').splitlines()[0].strip() if groq_key.strip() else ""
        if clean_groq.startswith("AQ.") or clean_groq.startswith("AIzaSy"):
            clean_groq = ""  # User mistakenly pasted a Gemini key into Groq
        clean_or = openrouter_key.strip().strip('"\'').splitlines()[0].strip() if openrouter_key.strip() else ""
        clean_felo = felo_key.strip().strip('"\'').splitlines()[0].strip() if felo_key.strip() else ""
        clean_model = gemini_model.strip() or "gemini-3.6-flash"

        # Update running os.environ in memory instantly
        os.environ["GEMINI_API_KEY"] = joined_gemini
        os.environ["GEMINI_MODEL"] = clean_model
        os.environ["GROQ_API_KEY"] = clean_groq
        os.environ["OPENROUTER_API_KEY"] = clean_or
        os.environ["FELO_API_KEY"] = clean_felo
        os.environ["CHECK_UPDATES_ON_STARTUP"] = "true" if check_updates else "false"

        # Read existing .env if present to preserve other keys
        env_lines = []
        if ENV_PATH.exists():
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                env_lines = f.readlines()

        keys_to_update = {
            "GEMINI_API_KEY": joined_gemini,
            "GEMINI_MODEL": clean_model,
            "GROQ_API_KEY": clean_groq,
            "OPENROUTER_API_KEY": clean_or,
            "FELO_API_KEY": clean_felo,
            "CHECK_UPDATES_ON_STARTUP": "true" if check_updates else "false",
        }

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

        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        return True, f"Configurações salvas com sucesso! ({len(keys_list)} chave(s) Gemini carregada(s))"
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
