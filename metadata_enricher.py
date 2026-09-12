"""
Metadata Enricher - Anime, Dorama & Pop Culture Intelligence API
Fetches official synopses, characters, genres, and lore for newly released
or obscure animes and doramas using Kitsu API, Jikan (MyAnimeList), and TVMaze.
Provides grounded knowledge to Gemini AI so it never hallucinates characters or storylines.
"""

import os
import re
import json
import time
import urllib.request
import urllib.parse
from typing import Optional, Dict, Any, Callable
from pathlib import Path

# Local persistent cache file
CACHE_DIR = Path(__file__).parent / ".cache"
CACHE_FILE = CACHE_DIR / "media_metadata_cache.json"

_memory_cache: Dict[str, Any] = {}


def _ensure_cache_loaded():
    global _memory_cache
    if _memory_cache:
        return
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                _memory_cache = json.load(f)
    except Exception:
        _memory_cache = {}


def _save_cache():
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_memory_cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _safe_log(on_log, msg: str):
    if not on_log:
        return
    try:
        on_log(msg)
    except Exception:
        try:
            clean_msg = msg.encode("ascii", "replace").decode("ascii")
            on_log(clean_msg)
        except Exception:
            pass


def clean_media_query(query: str) -> str:
    """
    Cleans episode/season suffixes (e.g., 'S01E05', 'Ep 270', 'Episodio 12', 'Part 2')
    so that search APIs can find the exact anime or series title.
    """
    if not query:
        return ""
    q = query.strip()
    # Remove patterns like S01E35, E05, Ep 20, Episódio 5, Episode 12, Chapter 50
    q = re.sub(r'(?i)\b(S\d+)?E\d+\b|\bepis[óo]dio\s*\d+\b|\bepisode\s*\d+\b|\bep\s*\d+\b', '', q)
    # Remove trailing season/part specifications if followed by numbers
    q = re.sub(r'(?i)\b(temporada|season|part|parte)\s*\d+\b', '', q)
    # Remove trailing dashes, colons, or punctuation
    q = re.sub(r'[\-_:\s]+$', '', q).strip()
    return q if len(q) >= 2 else query.strip()


def fetch_anime_metadata(query_or_title: str, timeout: float = 3.5, on_log: Optional[Callable[[str], None]] = None) -> Optional[Dict[str, Any]]:
    """
    Fetches anime metadata with Kitsu API (primary, fast, handles new 2024-2026 animes)
    and Jikan MyAnimeList v4 as fallback.
    """
    if not query_or_title or len(query_or_title.strip()) < 2:
        return None

    raw_query = query_or_title.strip()
    clean_q = clean_media_query(raw_query)

    _ensure_cache_loaded()
    cache_key = f"anime:{clean_q.lower()}"
    if cache_key in _memory_cache:
        cached = _memory_cache[cache_key]
        _safe_log(on_log, f"⚡ [Cache Hit] Metadados carregados para '{clean_q}': {cached.get('title', '')}")
        return cached

    # ── Attempt 1: Kitsu API (Ultra-fast, rich synopsis, no Cloudflare block) ──
    try:
        _safe_log(on_log, f"⛩️ Consultando API de Animes (Kitsu) para: '{clean_q}'...")

        params = urllib.parse.urlencode({"filter[text]": clean_q, "page[limit]": 1})
        url = f"https://kitsu.io/api/edge/anime?{params}"
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.api+json",
                "Content-Type": "application/vnd.api+json",
                "User-Agent": "UpscalingAnimeIntelligence/2.0"
            }
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                results = data.get("data", [])
                if results:
                    attr = results[0].get("attributes", {})
                    canonical = attr.get("canonicalTitle") or clean_q
                    titles = attr.get("titles", {}) or {}
                    title_en = titles.get("en") or titles.get("en_jp") or canonical
                    title_jp = titles.get("ja_jp", "")
                    synopsis = attr.get("synopsis", "") or ""
                    rating = attr.get("averageRating")
                    rating_str = f"{float(rating) / 10:.1f}/10" if rating else "N/A"
                    status = attr.get("status", "N/A")
                    age_guide = attr.get("ageRatingGuide", "")

                    synopsis_clean = re.sub(r'<[^>]+>', '', synopsis).replace("\n", " ").strip()
                    if len(synopsis_clean) > 500:
                        synopsis_clean = synopsis_clean[:500] + "..."

                    item = {
                        "type": "anime",
                        "source": "Kitsu API",
                        "title": canonical,
                        "title_english": title_en,
                        "title_japanese": title_jp,
                        "synopsis": synopsis_clean,
                        "score": rating_str,
                        "status": status,
                        "age_rating": age_guide,
                        "genres": "Anime / Ação / Shounen / Seinen",
                    }

                    _memory_cache[cache_key] = item
                    _save_cache()
                    _safe_log(on_log, f"✓ Metadados encontrados: '{canonical}' (Nota: {rating_str})")
                    return item
    except Exception as e:
        _safe_log(on_log, f"Aviso Kitsu API ({e}) - tentando fallback MyAnimeList...")

    # ── Attempt 2: Jikan API (MyAnimeList REST) ──
    try:
        _safe_log(on_log, f"⛩️ Consultando MyAnimeList (Jikan v4) para: '{clean_q}'...")

        params = urllib.parse.urlencode({"q": clean_q, "limit": 1})
        url = f"https://api.jikan.moe/v4/anime?{params}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "application/json"
            }
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                results = data.get("data", [])
                if results:
                    anime = results[0]
                    title_eng = anime.get("title_english") or anime.get("title") or clean_q
                    title_jp = anime.get("title_japanese", "")
                    synopsis = anime.get("synopsis", "") or ""
                    score = anime.get("score")
                    score_str = f"{score}/10" if score else "N/A"
                    genres = [g.get("name") for g in anime.get("genres", []) if g.get("name")]
                    genre_str = ", ".join(genres) if genres else "Anime"

                    synopsis_clean = re.sub(r'<[^>]+>', '', synopsis).replace("\n", " ").strip()
                    if len(synopsis_clean) > 500:
                        synopsis_clean = synopsis_clean[:500] + "..."

                    item = {
                        "type": "anime",
                        "source": "MyAnimeList (Jikan)",
                        "title": title_eng,
                        "title_english": title_eng,
                        "title_japanese": title_jp,
                        "synopsis": synopsis_clean,
                        "score": score_str,
                        "status": anime.get("status", "N/A"),
                        "age_rating": anime.get("rating", ""),
                        "genres": genre_str,
                    }

                    _memory_cache[cache_key] = item
                    _save_cache()
                    _safe_log(on_log, f"✓ Metadados encontrados no MyAnimeList: '{title_eng}' (Nota: {score_str})")
                    return item
    except Exception as e:
        _safe_log(on_log, f"Aviso MyAnimeList API: {e}")

    return None


def fetch_dorama_metadata(query_or_title: str, timeout: float = 3.5, on_log: Optional[Callable[[str], None]] = None) -> Optional[Dict[str, Any]]:
    """
    Fetches K-Drama, C-Drama, J-Drama, or Series metadata via TVMaze API (fast, open).
    """
    if not query_or_title or len(query_or_title.strip()) < 2:
        return None

    raw_query = query_or_title.strip()
    clean_q = clean_media_query(raw_query)

    _ensure_cache_loaded()
    cache_key = f"dorama:{clean_q.lower()}"
    if cache_key in _memory_cache:
        cached = _memory_cache[cache_key]
        _safe_log(on_log, f"⚡ [Cache Hit] Dorama carregado para '{clean_q}': {cached.get('title', '')}")
        return cached

    try:
        _safe_log(on_log, f"🎭 Consultando TVMaze API para Dorama/Série: '{clean_q}'...")

        params = urllib.parse.urlencode({"q": clean_q})
        url = f"https://api.tvmaze.com/singlesearch/shows?{params}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "UpscalingDoramaIntelligence/2.0",
                "Accept": "application/json"
            }
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                show = json.loads(resp.read().decode("utf-8"))
                if show and isinstance(show, dict):
                    name = show.get("name", clean_q)
                    genres = ", ".join(show.get("genres", [])) if show.get("genres") else "Dorama / Série"
                    rating_val = (show.get("rating") or {}).get("average")
                    rating_str = f"{rating_val}/10" if rating_val else "N/A"
                    network = (show.get("network") or {}).get("name") or (show.get("webChannel") or {}).get("name") or "Streaming"
                    summary = show.get("summary", "") or ""
                    summary_clean = re.sub(r'<[^>]+>', '', summary).replace("\n", " ").strip()
                    if len(summary_clean) > 500:
                        summary_clean = summary_clean[:500] + "..."

                    item = {
                        "type": "dorama",
                        "source": "TVMaze API",
                        "title": name,
                        "title_english": name,
                        "title_japanese": "",
                        "synopsis": summary_clean,
                        "score": rating_str,
                        "status": show.get("status", "N/A"),
                        "age_rating": "",
                        "genres": genres,
                        "network": network,
                    }

                    _memory_cache[cache_key] = item
                    _save_cache()
                    _safe_log(on_log, f"✓ Dorama encontrado no TVMaze: '{name}' ({network})")
                    return item
    except Exception as e:
        _safe_log(on_log, f"Aviso TVMaze API ({e})")

    return None


def get_enriched_context_for_prompt(
    query_or_title: str,
    category: str = "anime",
    on_log: Optional[Callable[[str], None]] = None
) -> str:
    """
    Searches anime or dorama APIs and returns a structured markdown context block
    ready to inject into any Gemini AI prompt (YT Shorts, Instagram, Director AI, Refiner).
    """
    if not query_or_title or len(query_or_title.strip()) < 2:
        return ""

    cat_lower = (category or "").strip().lower()
    is_dorama = "dorama" in cat_lower or "kdrama" in cat_lower or "série" in cat_lower

    data = None
    if is_dorama:
        data = fetch_dorama_metadata(query_or_title, on_log=on_log)
        if not data:
            data = fetch_anime_metadata(query_or_title, on_log=on_log)
    else:
        data = fetch_anime_metadata(query_or_title, on_log=on_log)
        if not data:
            data = fetch_dorama_metadata(query_or_title, on_log=on_log)

    if not data:
        return ""

    title = data.get("title", "")
    title_jp = data.get("title_japanese", "")
    title_display = f"{title} ({title_jp})" if title_jp else title
    genres = data.get("genres", "Cultura Pop")
    score = data.get("score", "N/A")
    synopsis = data.get("synopsis", "")
    src = data.get("source", "API Oficial")

    block = f"""
[METADADOS OFICIAIS DA OBRA ({src.upper()})]
• Título Oficial: {title_display}
• Gênero / Temas: {genres} | Avaliação: {score}
• Sinopse e Enredo Oficial:
  "{synopsis}"
• DIRETRIZ PARA A IA: Use esse conhecimento verificado da obra para identificar personagens com precisão, contextualizar técnicas, arcos, frases icônicas e criar ganchos e títulos que os fãs reais reconhecerão instantaneamente!
"""
    return block.strip()
