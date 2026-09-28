"""
ai_cache_hub.py - Hub Central de Cache Inteligente de IA (Cross-Pipeline)
Compartilha dados entre Diretor IA, Refinador Mastercut, Upscaler, Studio Pipeline,
YouTube Shorts Analyzer e Instagram Analyzer.

Evita chamadas repetidas e gastos desnecessários de tokens com Whisper, Gemini e APIs de IA.
- TTL padrão: 24 horas (1 dia de ciclo de trabalho).
- Limite de disco gerenciado automaticamente com purga LRU de itens expirados.
- Chave baseada na identidade digital do vídeo (tamanho + hash dos primeiros 2MB + stem).
- Suporte a invalidação manual ("Forçar Nova Geração").
"""

import os
import sys
import json
import time
import hashlib
from pathlib import Path
from typing import Any, Optional, Dict, List


def _get_cache_dir() -> Path:
    """Retorna o diretório base para o cache persistente do Hub de IA."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent
    cache_dir = base / ".cache" / "ai_hub"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return cache_dir


CACHE_DIR = _get_cache_dir()
DEFAULT_TTL_SECONDS = 86400  # 24 Horas
MAX_CACHE_SIZE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB


class AICacheHub:
    """
    Gerenciador unificado de cache de IA para o pipeline Urahara.
    """

    def __init__(self, cache_dir: Optional[Path] = None, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self.cache_dir = cache_dir or CACHE_DIR
        self.ttl_seconds = ttl_seconds
        self._ensure_dir()

    def _ensure_dir(self):
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def compute_video_key(self, video_path: str) -> str:
        """
        Gera uma chave única e estável para o vídeo baseada em tamanho,
        nome base normalizado e hash dos primeiros 2MB de dados.
        """
        p = Path(video_path)
        if not p.exists():
            clean_name = p.stem.strip().lower()
            return f"video_{hashlib.md5(clean_name.encode('utf-8')).hexdigest()[:16]}"

        try:
            file_size = p.stat().st_size
            clean_stem = p.stem.strip().lower()
            # Lê primeiros 2MB para hash rápido
            hasher = hashlib.md5()
            hasher.update(clean_stem.encode("utf-8"))
            hasher.update(str(file_size).encode("utf-8"))
            with open(p, "rb") as f:
                chunk = f.read(2 * 1024 * 1024)
                hasher.update(chunk)
            return f"vid_{hasher.hexdigest()[:20]}"
        except Exception:
            clean_stem = p.stem.strip().lower()
            return f"video_{hashlib.md5(clean_stem.encode('utf-8')).hexdigest()[:16]}"

    def _get_entry_path(self, video_key: str) -> Path:
        return self.cache_dir / f"{video_key}.json"

    def _load_entry(self, video_key: str) -> Dict[str, Any]:
        entry_file = self._get_entry_path(video_key)
        if not entry_file.exists():
            return {}
        try:
            with open(entry_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Verifica expiração global da entrada
            created_at = data.get("_created_at", 0)
            if time.time() - created_at > self.ttl_seconds:
                try:
                    entry_file.unlink(missing_ok=True)
                except Exception:
                    pass
                return {}
            return data
        except Exception:
            return {}

    def _save_entry(self, video_key: str, data: Dict[str, Any]):
        self._ensure_dir()
        entry_file = self._get_entry_path(video_key)
        data["_updated_at"] = time.time()
        if "_created_at" not in data:
            data["_created_at"] = time.time()
        try:
            tmp_file = entry_file.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmp_file.replace(entry_file)
        except Exception:
            pass

    # ── Métodos Públicos de Consulta e Salvamento ──────────────────────────────

    def get(self, video_path: str, category: str, default: Any = None) -> Any:
        """
        Recupera dados em cache para um vídeo em uma categoria específica.
        Categorias:
          - 'transcription': Lista de palavras e timestamps gerados pelo Whisper
          - 'anime_lore': Contexto, sinopse, personagens enriquecidos por IA
          - 'scene_vision': Cenas e ações descritas pelo Gemini Vision
          - 'viral_metadata': Títulos virais, hooks, tags SEO e hashtags
          - 'director_cuts': Cortes sugeridos pelo Diretor IA
        """
        if not video_path:
            return default
        video_key = self.compute_video_key(video_path)
        entry = self._load_entry(video_key)
        cat_data = entry.get(category)
        if cat_data is None:
            return default

        # Verifica expiração específica da categoria se houver timestamp
        # Categorias persistentes como 'cut_origin' nunca expiram sozinhas ("até eu tirar")
        is_persistent = False
        if isinstance(cat_data, dict):
            if cat_data.get("persistent") or category == "cut_origin":
                is_persistent = True
            elif isinstance(cat_data.get("payload"), dict) and cat_data["payload"].get("persistent"):
                is_persistent = True

        cat_ts = cat_data.get("_ts") if isinstance(cat_data, dict) else None
        if not is_persistent and cat_ts and (time.time() - cat_ts > self.ttl_seconds):
            return default

        if isinstance(cat_data, dict) and "payload" in cat_data:
            return cat_data["payload"]
        return cat_data

    def set(self, video_path: str, category: str, payload: Any):
        """Salva dados de uma categoria no cache do vídeo com timestamp."""
        if not video_path:
            return
        video_key = self.compute_video_key(video_path)
        entry = self._load_entry(video_key)
        entry[category] = {
            "_ts": time.time(),
            "payload": payload
        }
        entry["video_name"] = Path(video_path).name
        entry["video_path"] = str(video_path)
        self._save_entry(video_key, entry)

    def has(self, video_path: str, category: str) -> bool:
        """Verifica se há dados válidos em cache para a categoria."""
        return self.get(video_path, category) is not None

    def list_all_entries(self) -> List[Dict[str, Any]]:
        """
        Retorna uma lista resumida de todas as análises salvas no cache
        para o histórico e busca no BatchHistoryTab.
        """
        results = []
        try:
            self._ensure_dir()
            for p in self.cache_dir.glob("*.json"):
                if p.name in ("cut_origins_index.json",):
                    continue
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    video_name = data.get("video_name") or p.stem
                    video_path = data.get("video_path") or ""
                    updated_at = data.get("_updated_at", data.get("_created_at", 0))

                    # Extrai dados de Shorts e Instagram se presentes
                    yt_entry = data.get("yt_shorts_analysis")
                    yt_data = yt_entry.get("payload") if isinstance(yt_entry, dict) and "payload" in yt_entry else yt_entry

                    insta_entry = data.get("instagram_analysis")
                    insta_data = insta_entry.get("payload") if isinstance(insta_entry, dict) and "payload" in insta_entry else insta_entry

                    viral_entry = data.get("viral_metadata")
                    viral_meta = viral_entry.get("payload") if isinstance(viral_entry, dict) and "payload" in viral_entry else viral_entry

                    if yt_data or insta_data or viral_meta:
                        results.append({
                            "key": p.stem,
                            "video_name": video_name,
                            "video_path": video_path,
                            "updated_at": updated_at,
                            "has_youtube": bool(yt_data),
                            "has_instagram": bool(insta_data),
                            "yt_data": yt_data,
                            "insta_data": insta_data,
                            "viral_meta": viral_meta,
                        })
                except Exception:
                    pass
        except Exception:
            pass
        results.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
        return results

    def invalidate(self, video_path: str, category: Optional[str] = None):
        """
        Invalida dados do vídeo.
        Se category=None, limpa todo o cache desse vídeo (forçar nova geração total).
        """
        if not video_path:
            return
        video_key = self.compute_video_key(video_path)
        if category is None:
            entry_file = self._get_entry_path(video_key)
            try:
                entry_file.unlink(missing_ok=True)
            except Exception:
                pass
        else:
            entry = self._load_entry(video_key)
            if category in entry:
                del entry[category]
                self._save_entry(video_key, entry)

    def purge_expired(self) -> int:
        """Remove arquivos de cache com mais de 24h e retorna a quantidade limpa (exceto se for persistente)."""
        count = 0
        now = time.time()
        try:
            for p in self.cache_dir.glob("*.json"):
                if p.name == "cut_origins_index.json":
                    continue
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    # Não remove se contiver categorias persistentes como 'cut_origin'
                    if data.get("persistent") or "cut_origin" in data:
                        continue
                    created_at = data.get("_created_at", 0)
                    if now - created_at > self.ttl_seconds:
                        p.unlink(missing_ok=True)
                        count += 1
                except Exception:
                    try:
                        p.unlink(missing_ok=True)
                        count += 1
                    except Exception:
                        pass
        except Exception:
            pass
        return count

    # ── Gerenciamento Persistente de Cortes do Diretor IA ("Até eu tirar") ──────

    def _get_cut_index_path(self) -> Path:
        return self.cache_dir / "cut_origins_index.json"

    def _load_cut_index(self) -> Dict[str, Any]:
        p = self._get_cut_index_path()
        if not p.exists():
            return {}
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_cut_index(self, index: Dict[str, Any]):
        self._ensure_dir()
        p = self._get_cut_index_path()
        try:
            tmp = p.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(index, f, ensure_ascii=False, indent=2)
            tmp.replace(p)
        except Exception:
            pass

    def register_cut_origin(self, video_path: str, cut_info: Dict[str, Any]):
        """
        Armazena de forma persistente a origem de um corte contínuo gerado pelo Diretor IA.
        Fica no cache até o usuário decidir remover ("até eu tirar").
        Permite consulta tanto pelo hash do arquivo quanto pelo nome/stem do arquivo.
        """
        if not video_path:
            return
        p = Path(video_path)
        clean_stem = p.stem.strip().lower()
        exact_name = p.name.strip().lower()
        video_key = self.compute_video_key(video_path)

        payload = dict(cut_info)
        payload["persistent"] = True
        payload["saved_at"] = time.time()
        payload["file_stem"] = clean_stem
        payload["file_name"] = p.name

        # 1. Salva no cache individual do vídeo
        self.set(video_path, "cut_origin", payload)

        # 2. Salva no índice mestre de cortes (indexado por stem, nome exato e hash)
        idx = self._load_cut_index()
        idx[clean_stem] = payload
        idx[exact_name] = payload
        idx[video_key] = payload
        self._save_cut_index(idx)

    def get_cut_origin(self, video_path: str) -> Optional[Dict[str, Any]]:
        """
        Consulta se o vídeo é originário de um corte do Diretor IA.
        Verifica:
          1. Cache do próprio arquivo via hash/chave.
          2. Índice de cortes por stem (nome do arquivo) ou nome exato.
        """
        if not video_path:
            return None

        # 1. Tenta pegar pelo cache do vídeo diretamente
        val = self.get(video_path, "cut_origin")
        if val and isinstance(val, dict):
            return val

        # 2. Tenta pelo índice mestre via stem ou nome exato
        p = Path(video_path)
        clean_stem = p.stem.strip().lower()
        exact_name = p.name.strip().lower()
        video_key = self.compute_video_key(video_path)

        idx = self._load_cut_index()
        if video_key in idx:
            return idx[video_key]
        if exact_name in idx:
            return idx[exact_name]
        if clean_stem in idx:
            return idx[clean_stem]

        # 3. Busca por correspondência parcial de stem se o nome tiver sufixos
        for k, v in idx.items():
            if k and (k in clean_stem or clean_stem in k):
                return v

        return None

    def remove_cut_origin(self, video_path: str):
        """
        Remove os metadados de corte contínuo para o vídeo ("até eu tirar").
        """
        if not video_path:
            return
        p = Path(video_path)
        clean_stem = p.stem.strip().lower()
        exact_name = p.name.strip().lower()
        video_key = self.compute_video_key(video_path)

        # 1. Remove da entrada de cache do vídeo
        self.invalidate(video_path, category="cut_origin")

        # 2. Remove do índice mestre
        idx = self._load_cut_index()
        changed = False
        for key in [clean_stem, exact_name, video_key]:
            if key in idx:
                del idx[key]
                changed = True
        # Remove eventuais correspondências pelo nome do arquivo
        keys_to_del = [k for k, v in idx.items() if isinstance(v, dict) and v.get("file_stem") == clean_stem]
        for k in keys_to_del:
            del idx[k]
            changed = True

        if changed:
            self._save_cut_index(idx)

    def get_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas de uso do cache (quantidade de vídeos, tamanho em MB)."""
        files = list(self.cache_dir.glob("*.json"))
        total_size = sum(f.stat().st_size for f in files if f.exists())
        return {
            "entries_count": len(files),
            "size_mb": round(total_size / (1024 * 1024), 2),
            "cache_dir": str(self.cache_dir)
        }


# Instância global singleton para fácil acesso em todo o app
ai_cache = AICacheHub()
