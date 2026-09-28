"""
api_health_manager.py - Gerenciador Inteligente de Saúde de Chaves e Modelos de IA
Evita esperas infinitas e lentidão (ex: 15 minutos em loop) salvando em arquivo temporário
o status de chaves esgotadas (429 / Quota) e modelos sobrecarregados (503 UNAVAILABLE / 404).
"""

import os
import sys
import json
import time
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional


def _get_cache_file_path() -> Path:
    """Retorna o caminho para o arquivo de status de saúde das APIs."""
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).parent
    else:
        base_dir = Path(__file__).resolve().parent
    
    cand = base_dir / "api_health_cache.json"
    try:
        cand.touch(exist_ok=True)
        return cand
    except Exception:
        import tempfile
        return Path(tempfile.gettempdir()) / "urahara_api_health_cache.json"


CACHE_FILE = _get_cache_file_path()


def _key_id(key: str) -> str:
    """Gera um identificador anônimo para a chave de API (primeiros e ultimos chars + hash)."""
    if not key:
        return "empty"
    clean = key.strip()
    h = hashlib.sha256(clean.encode("utf-8")).hexdigest()[:8]
    if len(clean) > 10:
        return f"{clean[:6]}...{clean[-4:]}_{h}"
    return f"key_{h}"


class ApiHealthManager:
    """Gerencia em tempo real e de forma persistente quais chaves e modelos estão disponíveis."""

    def __init__(self, cache_file: Optional[Path] = None):
        self.cache_file = cache_file or CACHE_FILE
        self._memory_cache: Dict[str, Any] = {
            "disabled_models": {},
            "disabled_keys": {}
        }
        self._load()

    def _load(self):
        """Carrega do arquivo JSON persistente."""
        if self.cache_file and self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._memory_cache = data
            except Exception:
                pass
        self._clean_expired()

    def _save(self):
        """Persiste atomicamente no arquivo JSON."""
        self._clean_expired()
        try:
            tmp_path = self.cache_file.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._memory_cache, f, indent=2, ensure_ascii=False)
            tmp_path.replace(self.cache_file)
        except Exception:
            pass

    def _clean_expired(self):
        """Remove entradas cujo tempo de espera (cooldown) já expirou."""
        now = time.time()
        mod_dict = self._memory_cache.get("disabled_models", {})
        expired_models = [m for m, v in mod_dict.items() if v.get("until", 0) <= now]
        for m in expired_models:
            mod_dict.pop(m, None)

        key_dict = self._memory_cache.get("disabled_keys", {})
        expired_keys = [k for k, v in key_dict.items() if v.get("until", 0) <= now]
        for k in expired_keys:
            key_dict.pop(k, None)

    # ── Modelos ──────────────────────────────────────────────────────────────

    def is_model_available(self, model_name: str) -> Tuple[bool, str]:
        """Verifica se o modelo está livre ou em cooldown."""
        self._clean_expired()
        info = self._memory_cache.get("disabled_models", {}).get(model_name)
        if not info:
            return True, ""
        rem = int(info.get("until", 0) - time.time())
        reason = info.get("reason", "indisponível")
        return False, f"Modelo {model_name} em cooldown ({reason}) por mais {rem}s"

    def mark_model_unavailable(self, model_name: str, error_msg: str = "", cooldown_secs: float = 600.0):
        """Marca o modelo em cooldown (padrão 10 minutos para 503 UNAVAILABLE)."""
        now = time.time()
        until = now + max(60.0, cooldown_secs)
        
        reason = "503 UNAVAILABLE" if "503" in error_msg else "erro"
        if "404" in error_msg:
            reason = "404 NOT FOUND"
            until = now + 3600.0  # 1 hora se modelo não existir

        self._memory_cache.setdefault("disabled_models", {})[model_name] = {
            "reason": reason,
            "until": round(until, 1),
            "marked_at": round(now, 1),
            "message": error_msg[:120] if error_msg else ""
        }
        self._save()

    def mark_model_success(self, model_name: str):
        """Se o modelo respondeu com sucesso, remove imediatamente de qualquer cooldown."""
        mod_dict = self._memory_cache.get("disabled_models", {})
        if model_name in mod_dict:
            mod_dict.pop(model_name, None)
            self._save()

    def filter_available_models(self, models: List[str]) -> List[str]:
        """Retorna apenas os modelos que NÃO estão em cooldown (a menos que todos estejam)."""
        self._clean_expired()
        avail = [m for m in models if self.is_model_available(m)[0]]
        return avail if avail else models

    # ── Chaves de API ─────────────────────────────────────────────────────────

    def is_key_available(self, key: str) -> Tuple[bool, str]:
        """Verifica se a chave está livre ou com quota esgotada/inválida."""
        self._clean_expired()
        k_id = _key_id(key)
        info = self._memory_cache.get("disabled_keys", {}).get(k_id)
        if not info:
            return True, ""
        rem = int(info.get("until", 0) - time.time())
        reason = info.get("reason", "esgotada")
        return False, f"Chave {k_id} em cooldown ({reason}) por mais {rem}s"

    def mark_key_exhausted(self, key: str, error_msg: str = "", cooldown_secs: float = 900.0):
        """Marca chave em cooldown (15 min para 429 quota esgotada; 24h para chave inválida)."""
        now = time.time()
        k_id = _key_id(key)
        
        if "API_KEY_INVALID" in error_msg or "400" in error_msg or "403" in error_msg:
            reason = "chave_invalida"
            cooldown_secs = 86400.0  # 24 horas
        else:
            reason = "429_quota_esgotada"
            cooldown_secs = max(300.0, cooldown_secs)

        self._memory_cache.setdefault("disabled_keys", {})[k_id] = {
            "reason": reason,
            "until": round(now + cooldown_secs, 1),
            "marked_at": round(now, 1),
            "message": error_msg[:120] if error_msg else ""
        }
        self._save()

    def mark_key_success(self, key: str):
        """Se a chave respondeu com sucesso, remove de qualquer cooldown."""
        k_id = _key_id(key)
        key_dict = self._memory_cache.get("disabled_keys", {})
        if k_id in key_dict:
            key_dict.pop(k_id, None)
            self._save()

    def filter_available_keys(self, keys: List[str]) -> List[str]:
        """Retorna apenas chaves livres de cooldown. Se todas estiverem marcadas, retorna todas."""
        self._clean_expired()
        avail = [k for k in keys if self.is_key_available(k)[0]]
        return avail if avail else keys

    def clear_all(self):
        """Limpa todo o histórico de cooldowns (forçar reset)."""
        self._memory_cache = {"disabled_models": {}, "disabled_keys": {}}
        self._save()


# Instância global compartilhada
api_health = ApiHealthManager()
