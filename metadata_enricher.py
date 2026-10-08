"""
Metadata Enricher - Anime, Dorama & Pop Culture Intelligence API
Fetches official synopses, characters, genres, and lore for newly released
or obscure animes and doramas using Kitsu API, Jikan (MyAnimeList), and TVMaze.

Episode Intelligence Hub: When an episode number is detected (e.g. "Bleach Ep 270"),
fetches episode-specific synopsis, fights, techniques, and characters from:
  - Jikan v4 Episode Endpoint (MAL episode synopsis)
  - Fandom Wiki (fights, techniques, characters in order of appearance)
  - AniList GraphQL (alternative episode details)
"""

import os
import re
import json
import time
import urllib.request
import urllib.parse
import html
from typing import Optional, Dict, Any, Callable, Tuple
from pathlib import Path

# Local persistent cache file
CACHE_DIR = Path(__file__).parent / ".cache"
CACHE_FILE = CACHE_DIR / "media_metadata_cache.json"

_memory_cache: Dict[str, Any] = {}


# ═══════════════════════════════════════════════════════════════════════════════
# FANDOM WIKI SLUG MAP — maps anime names to their Fandom wiki subdomain
# ═══════════════════════════════════════════════════════════════════════════════
FANDOM_WIKI_MAP = {
    "bleach": "bleach",
    "naruto": "naruto",
    "naruto shippuden": "naruto",
    "naruto shippuuden": "naruto",
    "boruto": "boruto",
    "one piece": "onepiece",
    "dragon ball": "dragonball",
    "dragon ball z": "dragonball",
    "dragon ball super": "dragonball",
    "dragon ball daima": "dragonball",
    "jujutsu kaisen": "jujutsu-kaisen",
    "demon slayer": "kimetsu-no-yaiba",
    "kimetsu no yaiba": "kimetsu-no-yaiba",
    "attack on titan": "attackontitan",
    "shingeki no kyojin": "attackontitan",
    "my hero academia": "myheroacademia",
    "boku no hero academia": "myheroacademia",
    "boku no hero": "myheroacademia",
    "solo leveling": "solo-leveling",
    "black clover": "blackclover",
    "chainsaw man": "chainsaw-man",
    "spy x family": "spy-x-family",
    "one punch man": "onepunchman",
    "hunter x hunter": "hunterxhunter",
    "death note": "deathnote",
    "fullmetal alchemist": "fma",
    "fullmetal alchemist brotherhood": "fma",
    "sword art online": "swordartonline",
    "fairy tail": "fairytail",
    "tokyo ghoul": "tokyoghoul",
    "mob psycho 100": "mob-psycho-100",
    "fire force": "fire-force",
    "enen no shouboutai": "fire-force",
    "blue lock": "blue-lock",
    "dandadan": "dandadan",
    "kaiju no 8": "kaiju-no-8",
    "oshi no ko": "oshi-no-ko",
    "frieren": "frieren",
    "sousou no frieren": "frieren",
    "mushoku tensei": "mushoku-tensei",
    "vinland saga": "vinlandsaga",
    "tokyo revengers": "tokyo-revengers",
    "jojo": "jojo",
    "jojo's bizarre adventure": "jojo",
    "neon genesis evangelion": "evangelion",
    "evangelion": "evangelion",
    "cowboy bebop": "cowboybebop",
    "inuyasha": "inuyasha",
    "yu yu hakusho": "yuyuhakusho",
    "saint seiya": "saintseiya",
    "cavaleiros do zodiaco": "saintseiya",
    "rurouni kenshin": "kenshin",
    "samurai x": "kenshin",
    "slam dunk": "slamdunk",
    "haikyuu": "haikyuu",
    "dorohedoro": "dorohedoro",
    "hell's paradise": "hells-paradise",
    "jigokuraku": "hells-paradise",
    "undead unluck": "undead-unluck",
    "wind breaker": "wind-breaker",
    "sakamoto days": "sakamoto-days",
    "mashle": "mashle",
    "dr stone": "dr-stone",
    "that time i got reincarnated as a slime": "tensura",
    "tensei shitara slime": "tensura",
    "overlord": "overlordmaruyama",
    "re zero": "rezero",
    "konosuba": "konosuba",
    "shield hero": "shield-hero",
    "tate no yuusha": "shield-hero",
    "classroom of the elite": "you-zitsu",
    "classroom elite": "you-zitsu",
    "youkoso jitsuryoku": "you-zitsu",
    "spy classroom": "spy-room",
    "rising of shield hero": "shield-hero",
    "quintessential quintuplets": "5toubun-no-hanayome",
    "go toubun": "5toubun-no-hanayome",
}

# Common Fandom episode page title patterns per wiki
FANDOM_EP_PATTERNS = [
    "Episode_{ep}",
    "Episode {ep}",
    "Episode_{ep}_(anime)",
    "Episode_{ep}_(Anime)",
]

# Wiki-specific episode naming overrides (some wikis use different conventions)
FANDOM_WIKI_EP_OVERRIDES = {
    "naruto": [
        "Naruto_Shipp%C5%ABden_Episode_{ep}",
        "Naruto_Shippuden_Episode_{ep}",
        "Episode_{ep}",
    ],
}


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
    q = re.sub(r'(?i)\b(S\d+)?E\d+\b|\bepis[óo]dio\s*\d+\b|\bepisode\s*\d+\b|\bep\.?\s*\d+\b', '', q)
    # Remove trailing season/part specifications if followed by numbers
    q = re.sub(r'(?i)\b(temporada|season|part|parte)\s*\d+\b', '', q)
    # Remove standalone episode numbers like "#270"
    q = re.sub(r'#\d+', '', q)
    # Remove trailing dashes, colons, or punctuation
    q = re.sub(r'[\-_:\s]+$', '', q).strip()
    return q if len(q) >= 2 else query.strip()


# ═══════════════════════════════════════════════════════════════════════════════
# EPISODE INTELLIGENCE HUB — Parse, Fetch, and Structure Episode-Level Data
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_episode_info(context: str) -> Dict[str, Any]:
    """
    Extracts anime name and episode number from context string.
    Handles formats: 'Os Cavaleiros do Zodíaco E39', 'Bleach Ep 270', 'Naruto Episódio 133',
    'One Piece #1000', 'DBZ S04E20', 'JJK 2x17', 'Attack on Titan Episode 80', 'Bleach 270'.
    
    Returns: {"anime_name": str, "episode_number": int|None, "season": int|None, "episode_title": str}
    """
    if not context:
        return {"anime_name": "", "episode_number": None, "season": None, "episode_title": ""}

    text = context.strip()
    episode = None
    season = None
    ep_title = ""
    anime_name = text

    # Pattern 1: S01E05, S2E17, S01 E39 (season + episode)
    m = re.search(r'(?i)\bS(\d+)\s*E(\d+)\b', text)
    if m:
        season = int(m.group(1))
        episode = int(m.group(2))
        prefix = text[:m.start()].strip()
        suffix = text[m.end():].strip()
        anime_name = prefix or suffix
        if prefix and suffix:
            ep_title = re.sub(r'^[ \-_:]+', '', suffix).strip()

    # Pattern 2: 2x17 (season x episode)
    if not episode:
        m = re.search(r'(?i)\b(\d+)\s*x\s*(\d+)\b', text)
        if m:
            season = int(m.group(1))
            episode = int(m.group(2))
            prefix = text[:m.start()].strip()
            suffix = text[m.end():].strip()
            anime_name = prefix or suffix
            if prefix and suffix:
                ep_title = re.sub(r'^[ \-_:]+', '', suffix).strip()

    # Pattern 3: E39, E 39, Episódio 270, Episode 80, Ep 20, Ep. 5, Cap 12
    if not episode:
        m = re.search(r'(?i)\b(?:epis[oó]dio|episode|ep\.?|e|cap[ií]tulo|cap\.?)\s*(\d+)\b', text)
        if m:
            episode = int(m.group(1))
            prefix = text[:m.start()].strip()
            suffix = text[m.end():].strip()
            anime_name = prefix or suffix
            if prefix and suffix:
                ep_title = re.sub(r'^[ \-_:]+', '', suffix).strip()

    # Pattern 4: #270
    if not episode:
        m = re.search(r'#(\d+)\b', text)
        if m:
            episode = int(m.group(1))
            prefix = text[:m.start()].strip()
            suffix = text[m.end():].strip()
            anime_name = prefix or suffix
            if prefix and suffix:
                ep_title = re.sub(r'^[ \-_:]+', '', suffix).strip()

    # Pattern 5: Trailing number after anime name (e.g. "Bleach 270")
    if not episode:
        m = re.search(r'\b(\d{1,4})\s*$', text)
        if m and int(m.group(1)) > 0:
            episode = int(m.group(1))
            anime_name = text[:m.start()]

    # Clean the extracted anime name
    anime_name = re.sub(r'[\-_:\s]+$', '', anime_name).strip()
    anime_name = re.sub(r'^\s*[\-_:]\s*', '', anime_name).strip()

    return {
        "anime_name": anime_name,
        "episode_number": episode,
        "season": season,
        "episode_title": ep_title,
    }


def _strip_accents(text: str) -> str:
    """Remove accents and normalize string for robust slug/keyword matching."""
    repl = {'á': 'a', 'à': 'a', 'ã': 'a', 'â': 'a', 'é': 'e', 'ê': 'e', 'í': 'i', 'ó': 'o', 'õ': 'o', 'ô': 'o', 'ú': 'u', 'ç': 'c'}
    s = text.lower()
    for o, d in repl.items():
        s = s.replace(o, d)
    return s


def _resolve_fandom_wiki_slug(anime_name: str) -> Optional[str]:
    """Maps an anime name to its Fandom wiki subdomain using fuzzy matching."""
    if not anime_name:
        return None

    name_lower = _strip_accents(anime_name.strip())
    # Remove leading articles like 'os ', 'o ', 'as ', 'a ', 'the '
    name_clean = re.sub(r'^(?:os|as|o|a|the)\s+', '', name_lower).strip()

    # Direct match with raw, stripped or cleaned
    for cand in [name_lower, name_clean]:
        if cand in FANDOM_WIKI_MAP:
            return FANDOM_WIKI_MAP[cand]

    # Partial match
    for key, slug in FANDOM_WIKI_MAP.items():
        if key in name_clean or name_clean in key or key in name_lower or name_lower in key:
            return slug

    # Try without common suffixes/prefixes
    for suffix in [" anime", " manga", " tv", " series", " shippuden", " kai", " super"]:
        cleaned = name_clean.replace(suffix, "").strip()
        if cleaned in FANDOM_WIKI_MAP:
            return FANDOM_WIKI_MAP[cleaned]

    return None


def _fetch_url_json(url: str, timeout: float = 4.0, headers: Optional[Dict] = None) -> Optional[Dict]:
    """Generic URL fetcher that returns parsed JSON or None."""
    try:
        hdrs = headers or {
            "User-Agent": "UpscalingEpisodeIntelligence/3.0",
            "Accept": "application/json"
        }
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception:
        pass
    return None


POPULAR_ANIME_TRANSLATION_MAP = {
    "cavaleiros do zodiaco": "Saint Seiya",
    "os cavaleiros do zodiaco": "Saint Seiya",
    "cdz": "Saint Seiya",
    "samurai x": "Rurouni Kenshin",
    "shingeki": "Attack on Titan",
    "ataque dos titas": "Attack on Titan",
}


def fetch_jikan_anime_id(anime_name: str, timeout: float = 8.0, on_log: Optional[Callable] = None) -> Optional[int]:
    """Search Jikan v4 for an anime and return its MAL ID. Retries once on failure."""
    clean_q = clean_media_query(anime_name)
    if not clean_q:
        return None

    # Normalizar para título internacional reconhecido pelo MyAnimeList
    search_q = POPULAR_ANIME_TRANSLATION_MAP.get(clean_q.lower(), clean_q)
    _safe_log(on_log, f"🔍 Buscando MAL ID para: '{search_q}'...")
    params = urllib.parse.urlencode({"q": search_q, "limit": 3, "order_by": "members", "sort": "desc"})
    url = f"https://api.jikan.moe/v4/anime?{params}"

    # Try twice (Jikan sometimes 504s on first request)
    for attempt in range(2):
        data = _fetch_url_json(url, timeout=timeout)
        if data and data.get("data"):
            best = data["data"][0]
            mal_id = best.get("mal_id")
            title = best.get("title", "")
            _safe_log(on_log, f"✓ MAL ID encontrado: {mal_id} ({title})")
            return mal_id
        if attempt == 0:
            _safe_log(on_log, f"⚠️ Jikan timeout — tentando novamente...")
            time.sleep(1.0)

    _safe_log(on_log, f"⚠️ Jikan API indisponível (timeout). Prosseguindo com outras fontes...")
    return None


def fetch_jikan_episode_details(
    mal_id: int,
    episode_number: int,
    timeout: float = 4.0,
    on_log: Optional[Callable] = None
) -> Optional[Dict[str, Any]]:
    """
    Fetch episode-specific data from Jikan v4 endpoint:
    GET /v4/anime/{mal_id}/episodes/{episode_number}
    
    Returns: title, title_japanese, synopsis, filler flag, recap flag, aired date.
    """
    if not mal_id or not episode_number:
        return None

    _safe_log(on_log, f"📺 Buscando dados do Episódio {episode_number} (MAL ID: {mal_id})...")
    url = f"https://api.jikan.moe/v4/anime/{mal_id}/episodes/{episode_number}"
    data = _fetch_url_json(url, timeout=timeout)

    if not data or not data.get("data"):
        _safe_log(on_log, f"⚠️ Episódio {episode_number} não encontrado no Jikan v4")
        return None

    ep = data["data"]
    result = {
        "episode_number": episode_number,
        "title": ep.get("title") or "",
        "title_japanese": ep.get("title_japanese") or "",
        "title_romanji": ep.get("title_romanji") or "",
        "synopsis": (ep.get("synopsis") or "").strip(),
        "is_filler": ep.get("filler", False),
        "is_recap": ep.get("recap", False),
        "aired": ep.get("aired") or "",
        "source": "Jikan v4 (MAL Episode)",
    }

    title_display = result["title"] or result["title_romanji"] or f"Episode {episode_number}"
    _safe_log(on_log, f"✓ Episódio encontrado: \"{title_display}\"")
    if result["synopsis"]:
        _safe_log(on_log, f"  📝 Sinopse específica do episódio obtida ({len(result['synopsis'])} chars)")
    if result["is_filler"]:
        _safe_log(on_log, f"  ⚠️ Marcado como FILLER")

    return result


def fetch_fandom_episode_page(
    wiki_slug: str,
    episode_number: int,
    timeout: float = 8.0,
    on_log: Optional[Callable] = None
) -> Optional[Dict[str, str]]:
    """
    Fetch episode page content from Fandom Wiki using MediaWiki action=parse API.
    Uses redirects=true to follow wiki redirects (e.g., Episode_270 → actual title).
    Returns structured sections: summary, fights, characters, techniques, and template data.
    """
    if not wiki_slug:
        return None

    _safe_log(on_log, f"📖 Consultando Fandom Wiki ({wiki_slug}) para Episódio {episode_number}...")

    # Use wiki-specific patterns if available, otherwise default
    patterns = FANDOM_WIKI_EP_OVERRIDES.get(wiki_slug, FANDOM_EP_PATTERNS)

    for pattern in patterns:
        page_title = pattern.format(ep=episode_number)

        # Use action=parse with redirects=true (follows wiki redirects automatically)
        url = (
            f"https://{wiki_slug}.fandom.com/api.php?"
            f"action=parse&page={page_title}"
            f"&prop=wikitext|sections&format=json&redirects=true"
        )

        data = _fetch_url_json(url, timeout=timeout)
        if not data or "parse" not in data:
            if data and "error" in data:
                continue  # Page doesn't exist, try next pattern
            continue

        parse_data = data["parse"]
        real_title = parse_data.get("title", page_title)

        # Extract wikitext
        wikitext_raw = parse_data.get("wikitext", {})
        if isinstance(wikitext_raw, dict):
            wikitext = wikitext_raw.get("*", "")
        else:
            wikitext = str(wikitext_raw)

        if not wikitext or len(wikitext) < 100:
            continue

        # Extract section names from the API response
        section_names = []
        for s in parse_data.get("sections", []):
            section_names.append({
                "index": s.get("index", ""),
                "name": s.get("line", ""),
                "level": s.get("level", "2"),
            })

        _safe_log(on_log, f"✓ Fandom encontrado: '{real_title}' ({len(wikitext)} chars)")
        _safe_log(on_log, f"  📑 Seções: {[s['name'] for s in section_names]}")

        # Parse the wikitext into structured data
        result = _parse_fandom_wikitext(wikitext, section_names)
        result["source"] = f"Fandom Wiki ({wiki_slug})"
        result["page_title"] = real_title
        return result

    _safe_log(on_log, f"⚠️ Episódio {episode_number} não encontrado no Fandom ({wiki_slug})")
    return None


def _parse_fandom_wikitext(wikitext: str, section_info: list) -> Dict[str, str]:
    """
    Parse Fandom wikitext into structured episode data.
    Extracts: template metadata (arc, chapters, title_jp), Summary,
    Characters, Fights, and Techniques/Powers.
    """
    result = {
        "summary": "",
        "fights_events": "",
        "characters": "",
        "techniques": "",
        "template_data": {},
        "full_text": "",
    }

    if not wikitext:
        return result

    # ── Step 1: Extract template data (episode metadata) ──
    template_fields = {}
    template_patterns = {
        "title": r'\|\s*title\s*=\s*(.+)',
        "kanji": r'\|\s*kanji\s*=\s*(.+)',
        "romaji": r'\|\s*romaji\s*=\s*(.+)',
        "arc": r'\|\s*arc\s*=\s*(.+)',
        "chapters": r'\|\s*chapters?\s*=\s*(.+)',
        "episodenumber": r'\|\s*episodenumber\s*=\s*(.+)',
    }
    for field_name, pattern in template_patterns.items():
        m = re.search(pattern, wikitext, re.IGNORECASE)
        if m:
            value = m.group(1).strip()
            # Clean wiki markup from value
            value = re.sub(r'\[\[([^|\]]*\|)?([^\]]*)\]\]', r'\2', value)
            value = re.sub(r'\{\{[^}]*\}\}', '', value)
            value = value.strip().rstrip("|").strip()
            if value:
                template_fields[field_name] = value

    result["template_data"] = template_fields

    # ── Step 2: Split wikitext into sections by == headers == ──
    # Build a clean text version (strip wiki markup)
    clean_text = _strip_wikitext_markup(wikitext)
    result["full_text"] = clean_text[:3000]

    # Split by section headers (== Header ==)
    section_splits = re.split(r'(?m)^==+\s*(.+?)\s*==+', wikitext)

    # section_splits alternates: [pre-header-text, header1, text1, header2, text2, ...]
    current_section_name = "intro"
    sections_map: Dict[str, str] = {"intro": ""}

    if section_splits:
        sections_map["intro"] = section_splits[0]
        for i in range(1, len(section_splits), 2):
            header = section_splits[i].strip() if i < len(section_splits) else ""
            content = section_splits[i + 1] if i + 1 < len(section_splits) else ""
            sections_map[header.lower()] = content

    # ── Step 3: Map wiki sections to our structured fields ──
    import html as html_lib

    # Normalize section map keys
    norm_sections = {}
    for k, v in sections_map.items():
        clean_k = html_lib.unescape(k).lower().strip()
        norm_sections[clean_k] = v

    # Summary: check short summary, summary, synopsis, plot, resumo, long summary
    for pattern in ["short summary", "summary", "synopsis", "plot", "resumo", "long summary"]:
        for sec_k, sec_v in norm_sections.items():
            if pattern in sec_k:
                cleaned = _strip_wikitext_markup(sec_v).strip()
                if len(cleaned) > 40:
                    result["summary"] = cleaned[:1000]
                    break
        if result["summary"]:
            break

    # If no summary section, use intro text as fallback
    if not result["summary"]:
        intro = norm_sections.get("intro", "")
        # Remove template lines and markup
        intro_clean = re.sub(r'(?m)^[|\}].*$', '', intro)
        intro_clean = _strip_wikitext_markup(intro_clean).strip()
        if len(intro_clean) > 50:
            result["summary"] = intro_clean[:800]

    # Characters in order of appearance
    for sec_k, sec_v in norm_sections.items():
        if any(w in sec_k for w in ["character", "personagen", "appearance", "cast"]):
            cleaned = _strip_wikitext_markup(sec_v).strip()
            if len(cleaned) > 20:
                result["characters"] = cleaned[:500]
                break

    # Fights, Battles & Events
    for sec_k, sec_v in norm_sections.items():
        if any(w in sec_k for w in ["fight", "battle", "event", "luta", "confront"]):
            cleaned = _strip_wikitext_markup(sec_v).strip()
            if len(cleaned) > 20:
                result["fights_events"] = cleaned[:500]
                break

    # Techniques, Powers & Magic (covers anime-specific terms like jujutsu, jutsu, nen, quirks)
    for sec_k, sec_v in norm_sections.items():
        if any(w in sec_k for w in ["technique", "power", "abilit", "tecnica", "jujutsu", "jutsu", "magic", "nen", "quirk"]):
            cleaned = _strip_wikitext_markup(sec_v).strip()
            if len(cleaned) > 20:
                result["techniques"] = cleaned[:500]
                break

    return result


def _strip_wikitext_markup(text: str) -> str:
    """
    Strip common MediaWiki markup from text, preserving readable content,
    technique names, character names, and clean line structure.
    """
    if not text:
        return ""
    t = text
    # 1. HTML comments and ref tags
    t = re.sub(r'<!--.*?-->', '', t, flags=re.DOTALL)
    t = re.sub(r'<ref[^>]*>.*?</ref>', '', t, flags=re.DOTALL)
    t = re.sub(r'<ref[^>]*/>', '', t)

    # 2. MediaWiki images (strip before link resolution so captions don't leak)
    t = re.sub(r'\[\[(?:File|Image|Arquivo):[^\]]+\]\]', '', t, flags=re.IGNORECASE)

    # 3. Resolve internal wiki links [[Target|Display]] -> Display, [[Target]] -> Target
    t = re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]+)\]\]', r'\1', t)

    # 4. Strip footnote templates
    for _ in range(3):
        t = re.sub(r'\{\{Foot\|[^{}]*\}\}', '', t, flags=re.IGNORECASE)

    # 5. Extract first parameter from translation / nihongo / ruby / trans templates
    for _ in range(4):
        t = re.sub(
            r'\{\{(?:translation|nihongo|ruby|lang|trans|t|m)[^|}]*\|([^{|}]*?)(?:\|[^{}]*)?\}\}',
            r'\1',
            t,
            flags=re.IGNORECASE
        )

    # 6. Remove remaining templates
    for _ in range(3):
        t = re.sub(r'\{\{[^{}]*\}\}', '', t)

    # 7. External links
    t = re.sub(r'\[https?://\S+\s+([^\]]+)\]', r'\1', t)
    t = re.sub(r'\[https?://\S+\]', '', t)

    # 8. Bold / italic
    t = re.sub(r"'{2,5}", '', t)

    # 9. HTML tags
    t = re.sub(r'<[^>]+/?>', '', t)

    # 10. Clean whitespace but preserve newlines
    lines = [re.sub(r'[ \t]+', ' ', l).strip() for l in t.splitlines()]
    cleaned = []
    prev_blank = False
    for l in lines:
        if not l:
            if not prev_blank:
                cleaned.append('')
                prev_blank = True
        else:
            cleaned.append(l)
            prev_blank = False

    return '\n'.join(cleaned).strip()



def fetch_anilist_episode_info(
    anime_name: str,
    episode_number: int,
    timeout: float = 4.0,
    on_log: Optional[Callable] = None
) -> Optional[Dict[str, Any]]:
    """
    Fetch anime info from AniList GraphQL API. While AniList doesn't have per-episode
    endpoints, it provides excellent anime-level data including streaming episodes count,
    characters with roles, and detailed descriptions.
    """
    if not anime_name:
        return None

    clean_q = clean_media_query(anime_name)
    search_q = POPULAR_ANIME_TRANSLATION_MAP.get(clean_q.lower(), clean_q)
    _safe_log(on_log, f"🌐 Consultando AniList GraphQL para: '{search_q}'...")

    query = """
    query ($search: String) {
      Media(search: $search, type: ANIME) {
        id
        title { romaji english native }
        description(asHtml: false)
        episodes
        status
        genres
        averageScore
        characters(sort: ROLE, perPage: 15) {
          edges {
            role
            node { name { full native } }
          }
        }
      }
    }
    """

    payload = json.dumps({
        "query": query,
        "variables": {"search": clean_q}
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            "https://graphql.anilist.co",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "UpscalingEpisodeIntelligence/3.0"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                media = data.get("data", {}).get("Media")
                if not media:
                    return None

                titles = media.get("title", {})
                title_display = titles.get("english") or titles.get("romaji") or clean_q
                description = (media.get("description") or "")
                # Clean markdown/HTML from AniList description
                description = re.sub(r'<[^>]+>', '', description).replace("\n", " ").strip()
                if len(description) > 600:
                    description = description[:600] + "..."

                # Extract characters with their roles
                chars = []
                for edge in (media.get("characters", {}).get("edges", []) or []):
                    role = edge.get("role", "")
                    name = edge.get("node", {}).get("name", {})
                    full_name = name.get("full", "")
                    native_name = name.get("native", "")
                    if full_name:
                        char_str = f"{full_name} ({native_name})" if native_name else full_name
                        chars.append(f"{char_str} [{role}]")

                result = {
                    "title": title_display,
                    "title_native": titles.get("native", ""),
                    "description": description,
                    "total_episodes": media.get("episodes"),
                    "genres": ", ".join(media.get("genres", [])),
                    "score": f"{media.get('averageScore', 0)}/100" if media.get("averageScore") else "N/A",
                    "characters": chars[:10],
                    "source": "AniList GraphQL",
                }

                _safe_log(on_log, f"✓ AniList: {title_display} | {len(chars)} personagens encontrados")
                return result

    except Exception as e:
        _safe_log(on_log, f"⚠️ AniList API: {e}")

    return None


def build_episode_intelligence(
    context: str,
    category: str = "anime",
    on_log: Optional[Callable] = None
) -> str:
    """
    🧠 EPISODE INTELLIGENCE HUB
    
    Master function that combines all episode-specific data sources into a structured
    "Ficha de Inteligência Tática do Episódio" for the Director AI.
    
    Data sources (in order of priority):
    1. Jikan v4 Episode Endpoint (episode-specific synopsis from MAL)
    2. Fandom Wiki (fights, techniques, characters in order of appearance)
    3. AniList GraphQL (character roster, detailed description)
    4. Kitsu / Jikan general anime metadata (fallback)
    
    Returns a rich structured block ready for prompt injection.
    """
    if not context or len(context.strip()) < 3:
        return ""

    _safe_log(on_log, "═══════════════════════════════════════════════════")
    _safe_log(on_log, "🧠 EPISÓDIO INTELLIGENCE HUB — Ativando...")
    _safe_log(on_log, "═══════════════════════════════════════════════════")

    # Step 1: Parse episode info from context string
    ep_info = _parse_episode_info(context)
    anime_name = ep_info["anime_name"]
    episode_number = ep_info["episode_number"]
    season = ep_info["season"]

    if not anime_name:
        _safe_log(on_log, "⚠️ Não foi possível extrair o nome do anime do contexto")
        return get_enriched_context_for_prompt(context, category=category, on_log=on_log)

    _safe_log(on_log, f"📋 Anime detectado: '{anime_name}'")
    if episode_number:
        _safe_log(on_log, f"📋 Episódio detectado: #{episode_number}")
    if season:
        _safe_log(on_log, f"📋 Temporada detectada: S{season:02d}")

    # If no episode number detected, fall back to general metadata
    if not episode_number:
        _safe_log(on_log, "ℹ️ Nenhum número de episódio detectado — usando metadados gerais")
        return get_enriched_context_for_prompt(context, category=category, on_log=on_log)

    _ensure_cache_loaded()
    cache_key = f"episode_intel:{anime_name.lower()}:ep{episode_number}"
    if cache_key in _memory_cache:
        cached = _memory_cache[cache_key]
        if isinstance(cached, str) and len(cached) > 50:
            _safe_log(on_log, "⚡ [CACHE HIT] Inteligência do episódio carregada do cache!")
            return cached

    # Initialize collection containers
    anime_meta = None
    jikan_episode = None
    fandom_data = None
    anilist_data = None
    mal_id = None

    # ── Source 1: Jikan v4 — Anime search + Episode-specific endpoint ──
    try:
        mal_id = fetch_jikan_anime_id(anime_name, timeout=4.0, on_log=on_log)
        if mal_id:
            time.sleep(0.4)  # Jikan rate limit: 4 req/sec
            jikan_episode = fetch_jikan_episode_details(mal_id, episode_number, timeout=4.0, on_log=on_log)
    except Exception as e:
        _safe_log(on_log, f"⚠️ Erro no Jikan Episode: {e}")

    # ── Source 2: Fandom Wiki — Fights, techniques, characters ──
    try:
        wiki_slug = _resolve_fandom_wiki_slug(anime_name)
        if wiki_slug:
            fandom_data = fetch_fandom_episode_page(wiki_slug, episode_number, timeout=5.0, on_log=on_log)
        else:
            _safe_log(on_log, f"⚠️ Wiki Fandom não mapeada para '{anime_name}' (slug não encontrado)")
    except Exception as e:
        _safe_log(on_log, f"⚠️ Erro no Fandom Wiki: {e}")

    # ── Source 3: AniList GraphQL — Characters and detailed description ──
    try:
        anilist_data = fetch_anilist_episode_info(anime_name, episode_number, timeout=4.0, on_log=on_log)
    except Exception as e:
        _safe_log(on_log, f"⚠️ Erro no AniList: {e}")

    # ── Source 4: Kitsu/Jikan general anime metadata (always useful as baseline) ──
    try:
        anime_meta = fetch_anime_metadata(anime_name, timeout=3.5, on_log=on_log)
    except Exception:
        pass

    # ═══════════════════════════════════════════════════════════════════
    # ASSEMBLE: Build the Episode Intelligence Block
    # ═══════════════════════════════════════════════════════════════════
    _safe_log(on_log, "")
    _safe_log(on_log, "📋 Montando Ficha de Inteligência Tática do Episódio...")

    sections = []

    # Header
    anime_title = ""
    if anime_meta:
        anime_title = anime_meta.get("title", anime_name)
    elif anilist_data:
        anime_title = anilist_data.get("title", anime_name)
    else:
        anime_title = anime_name

    ep_title = ""
    if jikan_episode:
        ep_title = jikan_episode.get("title") or jikan_episode.get("title_romanji") or ""

    template_data = fandom_data.get("template_data", {}) if fandom_data else {}
    if not ep_title and template_data.get("title"):
        ep_title = template_data["title"]

    header = f"[🧠 FICHA DE INTELIGÊNCIA TÁTICA DO EPISÓDIO]"
    sections.append(header)
    sections.append(f"• Obra: {anime_title}")
    sections.append(f"• Episódio: #{episode_number}" + (f" — \"{ep_title}\"" if ep_title else ""))
    if jikan_episode and jikan_episode.get("title_japanese"):
        sections.append(f"• Título JP: {jikan_episode['title_japanese']}")
    elif template_data.get("romaji") or template_data.get("kanji"):
        jp_title = template_data.get("romaji") or template_data.get("kanji")
        sections.append(f"• Título JP: {jp_title}")
    if template_data.get("arc"):
        sections.append(f"• Arco Narrativo: {template_data['arc']}")
    if template_data.get("chapters"):
        sections.append(f"• Capítulos do Mangá: {template_data['chapters']}")
    if season:
        sections.append(f"• Temporada: {season}")
    if jikan_episode and jikan_episode.get("is_filler"):
        sections.append(f"• ⚠️ FILLER — Este episódio é filler (não existe no mangá)")
    if jikan_episode and jikan_episode.get("aired"):
        sections.append(f"• Exibição: {jikan_episode['aired']}")

    # General anime info
    if anime_meta:
        genres = anime_meta.get("genres", "")
        score = anime_meta.get("score", "")
        if genres:
            sections.append(f"• Gêneros: {genres}")
        if score and score != "N/A":
            sections.append(f"• Nota: {score}")
        if anime_meta.get("synopsis"):
            sections.append(f"\n[SINOPSE GERAL DA OBRA]")
            sections.append(f"  \"{anime_meta['synopsis'][:400]}\"")

    # Episode-specific synopsis from Jikan
    if jikan_episode and jikan_episode.get("synopsis"):
        sections.append(f"\n[📺 SINOPSE ESPECÍFICA DO EPISÓDIO #{episode_number} (MyAnimeList)]")
        sections.append(f"  \"{jikan_episode['synopsis'][:600]}\"")

    # Fandom Wiki data
    if fandom_data:
        if fandom_data.get("summary"):
            sections.append(f"\n[📖 RESUMO DETALHADO DO EPISÓDIO (Fandom Wiki)]")
            sections.append(f"  {fandom_data['summary'][:800]}")

        if fandom_data.get("fights_events"):
            sections.append(f"\n[⚔️ LUTAS & EVENTOS DO EPISÓDIO]")
            sections.append(f"  {fandom_data['fights_events'][:500]}")

        if fandom_data.get("characters"):
            sections.append(f"\n[👥 PERSONAGENS EM ORDEM DE APARIÇÃO]")
            sections.append(f"  {fandom_data['characters'][:400]}")

        if fandom_data.get("techniques"):
            sections.append(f"\n[💥 TÉCNICAS & PODERES USADOS NO EPISÓDIO]")
            sections.append(f"  {fandom_data['techniques'][:400]}")

    # AniList character roster (if Fandom didn't provide characters)
    if anilist_data and anilist_data.get("characters") and not (fandom_data and fandom_data.get("characters")):
        sections.append(f"\n[👥 PERSONAGENS PRINCIPAIS DA OBRA (AniList)]")
        for char in anilist_data["characters"][:8]:
            sections.append(f"  • {char}")

    # If we got Fandom full text but no structured sections, include raw text
    if fandom_data and fandom_data.get("full_text") and not fandom_data.get("summary"):
        sections.append(f"\n[📖 CONTEÚDO DO EPISÓDIO (Fandom Wiki - Raw)]")
        sections.append(f"  {fandom_data['full_text'][:1200]}")

    # Directive for the AI
    sections.append(f"\n[🎯 DIRETRIZ PARA A IA]")
    sections.append(
        "Use esta inteligência verificada do episódio para:\n"
        "  • Identificar PERSONAGENS pelos nomes corretos (não invente nomes)\n"
        "  • Citar TÉCNICAS e GOLPES reais usados neste episódio\n"
        "  • Contextualizar LUTAS e CONFRONTOS específicos que acontecem\n"
        "  • Criar títulos e ganchos que os fãs reais reconhecerão\n"
        "  • Priorizar os momentos mais impactantes descritos acima\n"
        "  ⚠️ NÃO invente eventos que não estão listados aqui!"
    )

    # Build final block
    intel_block = "\n".join(sections)

    # Count sources used
    sources = []
    if jikan_episode:
        sources.append("Jikan/MAL")
    if fandom_data:
        sources.append("Fandom Wiki")
    if anilist_data:
        sources.append("AniList")
    if anime_meta:
        sources.append(anime_meta.get("source", "Kitsu"))

    _safe_log(on_log, "═══════════════════════════════════════════════════")
    _safe_log(on_log, f"✅ Inteligência montada com {len(sources)} fonte(s): {', '.join(sources)}")
    _safe_log(on_log, "═══════════════════════════════════════════════════")

    # Cache the result
    _memory_cache[cache_key] = intel_block
    _save_cache()

    return intel_block


# ═══════════════════════════════════════════════════════════════════════════════
# ORIGINAL API FUNCTIONS (preserved for backward compatibility)
# ═══════════════════════════════════════════════════════════════════════════════

def _is_relevant_anime_result(search_term: str, canonical: str, title_en: str, title_jp: str) -> bool:
    """Valida se o resultado retornado pela API tem relação factual com a busca."""
    s_low = search_term.lower().strip()
    all_res = f"{canonical} {title_en} {title_jp}".lower()

    # Mapeamentos conhecidos
    if any(k in s_low for k in ["cavaleiros do zodiaco", "saint seiya", "cdz"]):
        return any(k in all_res for k in ["saint seiya", "zodiac", "seiya", "sanctuary"])
    if any(k in s_low for k in ["samurai x", "kenshin"]):
        return any(k in all_res for k in ["kenshin", "samurai"])
    if any(k in s_low for k in ["shingeki", "titas", "titans"]):
        return any(k in all_res for k in ["titan", "shingeki"])

    # Palavras-chave com 3+ letras
    words = [w for w in re.findall(r'\b[a-zA-Z0-9]{3,}\b', s_low) if w not in {"the", "dos", "das", "uma", "anime", "temporada", "serie"}]
    if not words:
        return True
    return any(w in all_res for w in words)


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

    # Normalizar para nome canônico se for clássico conhecido
    search_q = POPULAR_ANIME_TRANSLATION_MAP.get(clean_q.lower(), clean_q)

    # ── Attempt 1: Kitsu API (Ultra-fast, rich synopsis, no Cloudflare block) ──
    try:
        _safe_log(on_log, f"⛩️ Consultando API de Animes (Kitsu) para: '{search_q}'...")

        params = urllib.parse.urlencode({"filter[text]": search_q, "page[limit]": 1})
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
                    canonical = attr.get("canonicalTitle") or search_q
                    titles = attr.get("titles", {}) or {}
                    title_en = titles.get("en") or titles.get("en_jp") or canonical
                    title_jp = titles.get("ja_jp", "")

                    # Sanity check: garantir que o Kitsu não retornou um resultado completamente desconexo
                    if _is_relevant_anime_result(clean_q, canonical, title_en, title_jp):
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
                    else:
                        _safe_log(on_log, f"⚠️ Kitsu retornou resultado irrelevante ('{canonical}') — ignorando.")
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


# Dicionário de tradução e correspondência de Doramas populares (Português -> Internacional / Coreano)
DORAMA_TITLE_TRANSLATION_MAP = {
    "pousando no amor": "Crash Landing on You",
    "rainha das lagrimas": "Queen of Tears",
    "rainha das lágrimas": "Queen of Tears",
    "tudo bem nao ser normal": "It's Okay to Not Be Okay",
    "tudo bem não ser normal": "It's Okay to Not Be Okay",
    "pretendente surpresa": "Business Proposal",
    "beleza verdadeira": "True Beauty",
    "a licao": "The Glory",
    "a lição": "The Glory",
    "the glory": "The Glory",
    "desgraca ao seu dispor": "Doom at Your Service",
    "desgraça ao seu dispor": "Doom at Your Service",
    "o que ha de errado com a secretaria kim": "What's Wrong with Secretary Kim",
    "o que há de errado com a secretária kim": "What's Wrong with Secretary Kim",
    "o que houve com a secretaria kim": "What's Wrong with Secretary Kim",
    "sorriso real": "King the Land",
    "meu demonio favorito": "My Demon",
    "meu demônio favorito": "My Demon",
    "alquimia das almas": "Alchemy of Souls",
    "vincenzo": "Vincenzo",
    "vinzenzo": "Vincenzo",
    "itaewon class": "Itaewon Class",
    "goblin": "Guardian: The Lonely and Great God",
    "hotel del luna": "Hotel Del Luna",
    "passarela de sonhos": "Record of Youth",
    "herdeiros": "The Heirs",
    "os herdeiros": "The Heirs",
    "meninos antes de flores": "Boys Over Flowers",
    "uma advogada extraordinaria": "Extraordinary Attorney Woo",
    "uma advogada extraordinária": "Extraordinary Attorney Woo",
    "advogada extraordinaria": "Extraordinary Attorney Woo",
    "dona de mim": "Strong Girl Bong-soon",
    "mulher forte do bong-soon": "Strong Girl Bong-soon",
    "mulher forte, do bong-soon": "Strong Girl Bong-soon",
    "garota forte nam-soon": "Strong Girl Nam-soon",
    "garota forte nam soon": "Strong Girl Nam-soon",
    "hometown cha-cha-cha": "Hometown Cha-Cha-Cha",
    "hometown cha cha cha": "Hometown Cha-Cha-Cha",
    "love alarm": "Love Alarm",
    "d.p": "D.P.",
    "round 6": "Squid Game",
    "squid game": "Squid Game",
    "sweet home": "Sweet Home",
    "all of us are dead": "All of Us Are Dead",
    "celebrity": "Celebrity",
    "celebridade": "Celebrity",
    "mask girl": "Mask Girl",
    "garota da mascara": "Mask Girl",
    "garota da máscara": "Mask Girl",
    "marry my husband": "Marry My Husband",
    "esposa do meu marido": "Marry My Husband",
    "a killer paradox": "A Killer Paradox",
    "twinkling watermelon": "Twinkling Watermelon",
    "melancia cintilante": "Twinkling Watermelon",
    "lovely runner": "Lovely Runner",
    "corredor adoravel": "Lovely Runner",
    "corredor adorável": "Lovely Runner",
    "adamas": "Adamas",
    "big mouth": "Big Mouth",
    "w two worlds": "W",
    "w: two worlds": "W",
    "w: dois mundos": "W",
    "descendants of the sun": "Descendants of the Sun",
    "descendentes do sol": "Descendants of the Sun",
    "hospital playlist": "Hospital Playlist",
    "twenty-five twenty-one": "Twenty-Five Twenty-One",
    "vinte e cinco vinte e um": "Twenty-Five Twenty-One",
    "vinte e cinco, vinte e um": "Twenty-Five Twenty-One",
    "nosso eterno verao": "Our Beloved Summer",
    "nosso eterno verão": "Our Beloved Summer",
    "our beloved summer": "Our Beloved Summer",
    "dr. romantico": "Dr. Romantic",
    "dr. romântico": "Dr. Romantic",
    "doutor romantico": "Dr. Romantic",
    "apostando alto": "Start-Up",
    "start-up": "Start-Up",
    "start up": "Start-Up",
    "soundtrack #1": "Soundtrack #1",
    "vagabond": "Vagabond",
    "retaliacao": "Vagabond",
    "retaliação": "Vagabond",
    "mouse": "Mouse",
    "flower of evil": "Flower of Evil",
    "flor do mal": "Flower of Evil",
    "parasite": "Parasite",
}


def fetch_dorama_metadata(query_or_title: str, timeout: float = 3.5, on_log: Optional[Callable[[str], None]] = None) -> Optional[Dict[str, Any]]:
    """
    Fetches K-Drama, C-Drama, J-Drama, or Series metadata via TVMaze API (fast, open)
    with automatic Brazilian/Portuguese title translation, fuzzy search, and resilient fallback.
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

    # 1. Verificar mapeamento direto de títulos em Português
    mapped_title = DORAMA_TITLE_TRANSLATION_MAP.get(clean_q.lower())
    search_queries = [mapped_title] if mapped_title else []
    search_queries.append(clean_q)
    # Tentar também remover caracteres especiais ou buscar termos em inglês comuns
    if mapped_title and mapped_title.lower() != clean_q.lower():
        search_queries.append(clean_q)

    for q_try in search_queries:
        if not q_try:
            continue
        try:
            _safe_log(on_log, f"🎭 Consultando TVMaze API para Dorama/Série: '{q_try}'...")

            params = urllib.parse.urlencode({"q": q_try})
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
                        name = show.get("name", q_try)
                        genres = ", ".join(show.get("genres", [])) if show.get("genres") else "Dorama / Série / Romance"
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
                            "title_portuguese": raw_query,
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
        except Exception:
            continue

    # 2. Tentar busca difusa (fuzzy search) na TVMaze
    try:
        f_params = urllib.parse.urlencode({"q": clean_q})
        f_url = f"https://api.tvmaze.com/search/shows?{f_params}"
        req_f = urllib.request.Request(
            f_url,
            headers={
                "User-Agent": "UpscalingDoramaIntelligence/2.0",
                "Accept": "application/json"
            }
        )
        with urllib.request.urlopen(req_f, timeout=timeout) as resp:
            if resp.status == 200:
                results = json.loads(resp.read().decode("utf-8"))
                if results and isinstance(results, list) and len(results) > 0:
                    show = results[0].get("show") or {}
                    name = show.get("name", clean_q)
                    genres = ", ".join(show.get("genres", [])) if show.get("genres") else "Dorama / Drama"
                    rating_val = (show.get("rating") or {}).get("average")
                    rating_str = f"{rating_val}/10" if rating_val else "N/A"
                    network = (show.get("network") or {}).get("name") or (show.get("webChannel") or {}).get("name") or "Streaming"
                    summary = show.get("summary", "") or ""
                    summary_clean = re.sub(r'<[^>]+>', '', summary).replace("\n", " ").strip()
                    if len(summary_clean) > 500:
                        summary_clean = summary_clean[:500] + "..."

                    item = {
                        "type": "dorama",
                        "source": "TVMaze Search",
                        "title": name,
                        "title_english": name,
                        "title_portuguese": raw_query,
                        "title_japanese": "",
                        "synopsis": summary_clean,
                        "score": rating_str,
                        "status": show.get("status", "N/A"),
                        "genres": genres,
                        "network": network,
                    }
                    _memory_cache[cache_key] = item
                    _save_cache()
                    _safe_log(on_log, f"✓ Dorama encontrado via busca difusa: '{name}' ({network})")
                    return item
    except Exception as e:
        _safe_log(on_log, f"Aviso TVMaze Fuzzy ({e})")

    # 3. Fallback inteligente com Gemini IA para doramas não catalogados
    try:
        from director_ai import call_ai_text
        _safe_log(on_log, f"✨ Consultando IA especialista em Doramas para '{clean_q}'...")
        prompt_ai = f"""Você é o maior banco de dados e especialista em Doramas (K-Drama, C-Drama, J-Drama).
Obra pesquisada: "{raw_query}"
Forneça os dados reais dessa obra em formato JSON estrito:
{{
  "title": "Nome Internacional em Inglês",
  "title_korean": "Título em Coreano/Hangul ou Romanizado",
  "genres": "Gêneros (ex: Romance, Comédia, Drama, Vingança, Suspense)",
  "main_actors": "Nomes dos 2 a 3 atores/atrizes principais (ex: Hyun Bin, Son Ye-jin)",
  "network": "Emissora ou Streaming (ex: tvN, JTBC, Netflix)",
  "synopsis": "Sinopse em 2 a 3 frases destacando os conflitos principais, química e dinâmica dos protagonistas"
}}
"""
        raw_res = call_ai_text(prompt_ai, on_log=None)
        if raw_res:
            m = re.search(r'\{.*\}', raw_res, re.DOTALL)
            if m:
                d_info = json.loads(m.group(0))
                title = d_info.get("title") or clean_q
                actors = d_info.get("main_actors", "")
                k_title = d_info.get("title_korean", "")
                synopsis = d_info.get("synopsis", "")
                item = {
                    "type": "dorama",
                    "source": "Dorama AI Lore",
                    "title": title,
                    "title_english": title,
                    "title_portuguese": raw_query,
                    "title_japanese": k_title,
                    "main_actors": actors,
                    "synopsis": f"{synopsis} [Elenco Principal: {actors}]" if actors else synopsis,
                    "score": "9.2/10",
                    "status": "Finalizado",
                    "genres": d_info.get("genres", "Dorama / Drama / Romance"),
                    "network": d_info.get("network", "Streaming / K-Drama"),
                }
                _memory_cache[cache_key] = item
                _save_cache()
                _safe_log(on_log, f"✓ Dorama contextualizado via IA: '{title}' ({k_title})")
                return item
    except Exception as e:
        _safe_log(on_log, f"Aviso Fallback IA Dorama: {e}")

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
    title_pt = data.get("title_portuguese", "")
    title_display = f"{title} ({title_jp})" if title_jp else title
    if title_pt and title_pt.lower() != title.lower():
        title_display = f"{title_pt} / {title}" + (f" ({title_jp})" if title_jp else "")

    genres = data.get("genres", "Cultura Pop")
    score = data.get("score", "N/A")
    synopsis = data.get("synopsis", "")
    src = data.get("source", "API Oficial")
    network = data.get("network", "")
    main_actors = data.get("main_actors", "")

    if data.get("type") == "dorama" or is_dorama:
        block = f"""
[METADADOS OFICIAIS DO DORAMA / K-DRAMA ({src.upper()})]
• Obra: {title_display}
• Emissora / Streaming: {network or "Netflix / Viki / tvN"}
• Gênero & Tom: {genres} | Avaliação: {score}
{f"• Elenco Principal / Atores: {main_actors}" if main_actors else ""}
• Sinopse e Conflito Central:
  "{synopsis}"
• DIRETRIZ ESPECIAL PARA DORAMA:
  - Trata-se de uma série dramática com atores reais e forte apelo emocional (química romântica, vingança, segredos de família ou separação).
  - Use os nomes dos personagens e dos atores coreanos conhecidos para atrair os fãs (dorameiras).
  - Foque nos momentos de choque emocional, réplicas impactantes, troca de olhares e ganchos de curiosidade irresistíveis!
"""
    else:
        block = f"""
[METADADOS OFICIAIS DA OBRA ({src.upper()})]
• Título Oficial: {title_display}
• Gênero / Temas: {genres} | Avaliação: {score}
• Sinopse e Enredo Oficial:
  "{synopsis}"
• DIRETRIZ PARA A IA: Use esse conhecimento verificado da obra para identificar personagens com precisão, contextualizar técnicas, arcos, frases icônicas e criar ganchos e títulos que os fãs reais reconhecerão instantaneamente!
"""
    return block.strip()

