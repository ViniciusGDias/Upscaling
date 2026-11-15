"""
anime_fx_analyzer.py - Analisador Semântico e de Impacto para Efeitos Visuais Anime & Mangá
Analisa a linha do tempo e transições de fala (Whisper chunks) para identificar os momentos ideais de:
  - CENA CLÍMAX MANGÁ (Recorte de Personagem Neural ISNet + Speed Lines + Halftone Retícula)
  - ANTI-COPYRIGHT: Transforma visualmente mais de 60% da tela durante momentos-chave
  - ZERO FLASHES AMADORES: Elimina completamente flashes brancos ou transições infantis
  - ANTI-COLISÃO DE LEGENDAS: Eleva a legenda para o topo durante o recorte de mangá
"""

import os
import sys
import re
import json
import time
import requests
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Callable

CLIMAX_TRIGGER_KEYWORDS = [
    "morram", "morra", "matar", "morte", "sangue", "esmagador", "destruição",
    "poder", "força", "impossível", "impossivel", "desapareça", "acabou", "verme", "lixo",
    "cale a boca", "idiota", "desgraçado", "monstro", "fraco", "patético",
    "cala a boca", "já era", "adeus", "morra de uma vez", "não tem chance",
    "chega", "basta", "absorção", "absorver", "revela", "transformação",
    "despertar", "magia", "derrotar", "inimigo", "inimiga", "perder", "vencer", "pagar",
    "sereitei", "shinigami", "divisão", "divisões", "capitão", "haki", "bankai", "fala demais",
    "perdoar", "rir", "faça rir", "filha", "trovão", "trovao", "feitiço", "feitico",
    "imperatriz", "poderoso", "tenta a sorte", "tenta sorte", "nunca",
    "serial", "killer", "serial killer", "justiça", "justica", "deus", "novo mundo",
    "kira", "armadilha", "do mal", "o l"
]

QUESTION_WORDS = [
    "o que", "quem", "por que", "como", "onde", "quando", "qual", "será", "hein"
]

POWER_WORDS = [
    "ESMAGADOR", "PODER", "FORÇA", "SUPREMO", "DESTRUIÇÃO", "ABSOLUTO",
    "DIVINO", "INVENCÍVEL", "COLOSSAL", "GIGANTE", "IMPACTO", "EXPLOSÃO", "ABSORÇÃO"
]

THREAT_WORDS = [
    "MORRAM", "MORRA", "MATAR", "MORTE", "SANGUE", "DESAPAREÇA",
    "ACABOU", "VERME", "LIXO", "INÚTIL", "CADÁVER", "INFERNO", "TORTURA"
]


_EDGE_FORBIDDEN_START = {
    "de", "do", "da", "dos", "das", "que", "e", "ou", "por", "para", "pra", "com", "em",
    "no", "na", "nos", "nas", "se", "mas", "porque", "pois", "à", "ao", "aos", "às", "pelo", "pela"
}
_EDGE_FORBIDDEN_END = _EDGE_FORBIDDEN_START | {
    "o", "a", "os", "as", "um", "uma", "uns", "umas", "meu", "minha", "seu", "sua", "esse",
    "essa", "este", "esta", "eu", "me", "te", "lhe", "não", "vou", "vai", "é", "sou"
}
_IMPACT_WORDS = (
    {kw for kw in CLIMAX_TRIGGER_KEYWORDS if " " not in kw}
    | {w.lower() for w in POWER_WORDS + THREAT_WORDS}
    | {"mortos", "morto", "morrer", "assassino", "segredo", "verdade", "fim", "mundo",
       "justiça", "deus", "mal", "vingança", "traição", "sozinho", "destino", "monstro"}
)
_MAX_PUNCH_CHARS = 32
_LEAD_IN = 0.12
_TAIL_OUT = 0.25
_MIN_CARD = 1.0
_MAX_CARD = 2.4

CLIMAX_CANONICAL_ANCHORS = [
    r'(?i)\b(?:o\s+)?deus\s+(?:de\s+um\s+|do\s+)?novo\s+mundo\b',
    r'(?i)\bserial\s+killer\b',
    r'(?i)\b(?:eu\s+sou\s+a\s+|sou\s+a\s+|é\s+a\s+)justi[çc]a\b',
    r'(?i)\b(?:eu\s+sou\s+o|eu\s+sou|sou\s+o)\s+l\b',
    r'(?i)\b(?:caiu\s+na\s+)?armadilha(?:\s+genial)?\b',
    r'(?i)\b(?:eu\s+sou\s+do|sou\s+do|é\s+do|sou\s+o)\s+mal\b',
    r'(?i)\bnovo\s+mundo\b',
]


def _norm(word: str) -> str:
    return re.sub(r"[^\wà-úÀ-Ú]", "", word.lower())


def _display(word: str) -> str:
    cleaned = re.sub(r"[^\w\sÀ-úà-ú\-']", "", word)
    return re.sub(r"\s+", " ", cleaned).strip().upper()


def _flatten_words(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Recupera a lista palavra-a-palavra com timestamps reais (interpola apenas se o chunk não tiver words)."""
    flat: List[Dict[str, Any]] = []
    for it in items:
        sub = it.get("words")
        if sub:
            for w in sub:
                txt = str(w.get("word") or w.get("text") or "").strip()
                if txt:
                    flat.append({"word": txt, "start": float(w.get("start", 0.0)), "end": float(w.get("end", 0.0))})
            continue
        toks = str(it.get("text") or it.get("word") or "").split()
        if not toks:
            continue
        st, et = float(it.get("start", 0.0)), float(it.get("end", 0.0))
        step = max(0.05, (et - st) / len(toks))
        for k, t in enumerate(toks):
            flat.append({"word": t, "start": st + k * step, "end": st + (k + 1) * step})
    flat.sort(key=lambda w: w["start"])
    return flat


def _build_sentences(words: List[Dict[str, Any]], max_gap: float = 0.6) -> List[List[int]]:
    sentences: List[List[int]] = []
    cur: List[int] = []
    for i, w in enumerate(words):
        if cur and (w["start"] - words[cur[-1]]["end"]) >= max_gap:
            sentences.append(cur)
            cur = []
        cur.append(i)
        if re.search(r"[.!?…]$", w["word"]):
            sentences.append(cur)
            cur = []
    if cur:
        sentences.append(cur)
    return sentences


def split_punch_lines(tokens: List[str]) -> Tuple[str, str]:
    """Divide as palavras reais da punchline em 2 linhas equilibradas (sem quebrar após palavra fraca)."""
    if len(tokens) <= 1:
        return "", " ".join(tokens)
    best_k, best_cost = 1, 10 ** 9
    for k in range(1, len(tokens)):
        l1, l2 = " ".join(tokens[:k]), " ".join(tokens[k:])
        cost = abs(len(l1) - len(l2))
        prev_norm = _norm(tokens[k - 1])
        if prev_norm in _EDGE_FORBIDDEN_START or prev_norm in _EDGE_FORBIDDEN_END:
            cost += 8
        if cost < best_cost:
            best_k, best_cost = k, cost
    return " ".join(tokens[:best_k]), " ".join(tokens[best_k:])


def extract_climax_text_lines(current_text: str, prev_text: str = "") -> Tuple[str, str, str]:
    """Versão fiel: usa somente palavras ditas (últimas até 4 palavras válidas), nunca inventa texto."""
    raw = current_text.split()
    symbol = "?" if "?" in current_text else "!"
    toks = [_display(w) for w in raw if _display(w)]
    while len(toks) > 1 and _norm(toks[0]) in _EDGE_FORBIDDEN_START:
        toks = toks[1:]
    toks = toks[-4:]
    l1, l2 = split_punch_lines(toks)
    return l1, (f"{l2}{symbol}" if l2 else ""), symbol


def _score_span(words: List[Dict[str, Any]], sent: List[int], i: int, j: int) -> Optional[float]:
    """Pontua um trecho contínuo sent[i:j] de palavras realmente faladas."""
    idxs = sent[i:j]
    raw = [words[k]["word"] for k in idxs]
    norms = [_norm(w) for w in raw]
    if not all(norms):
        return None
    if len(" ".join(_display(w) for w in raw)) > _MAX_PUNCH_CHARS:
        return None
    whole = (i == 0 and j == len(sent))
    if norms[0] in _EDGE_FORBIDDEN_START:
        return None
    if norms[-1] in _EDGE_FORBIDDEN_END and not whole:
        return None

    n = j - i
    score = 10.0 * sum(1 for w in norms if w in _IMPACT_WORDS)
    # Nomes próprios no meio da frase (Whisper capitaliza nomes: Kira, Deus, L...)
    if any(raw[k][:1].isupper() and (i + k) > 0 for k in range(n)):
        score += 6.0
    if j == len(sent):
        score += 6.0  # a punchline costuma ser o fim da oração
    if whole:
        score += 4.0 + (4.0 if raw[0][:1].isupper() and n == 1 else 0.0)
    score += {1: 1.0, 2: 4.0, 3: 5.0, 4: 4.0, 5: 3.0}.get(n, 0.0)
    if norms[0] == "eu" and n >= 3:
        score += 3.0
    return score


def _sentence_bonus(words: List[Dict[str, Any]], sent: List[int]) -> float:
    text = " ".join(words[k]["word"] for k in sent)
    low = text.lower()
    bonus = 3.0 * sum(1 for k in sent if _norm(words[k]["word"]) in _IMPACT_WORDS)
    if "!" in text:
        bonus += 4.0
    if "?" in text:
        bonus += 3.0
    if re.search(r"\beu (sou|vou|serei)\b", low):
        bonus += 5.0
    return bonus


def _card_timing(words: List[Dict[str, Any]], first: int, last: int, video_duration: float) -> Tuple[float, float]:
    """
    Janela do recorte frame-accurate:
    - Entrada (st): Ancora estrita no inicio da primeira palavra da punchline.
      NUNCA invade falas anteriores (st >= words[first - 1]['end'] se houver).
    - Saida (et): Cobre toda a fala da punchline e estende exclusivamente para
      o silencio posterior, parando antes da proxima fala comecar.
    """
    speech_start = float(words[first]["start"])
    speech_end = float(words[last]["end"])

    # Entrada no tempo exato da fala (-0.04s de respiracao para corte no beat)
    st = max(0.0, speech_start - 0.04)
    if first > 0:
        prev_end = float(words[first - 1]["end"])
        st = max(st, prev_end)  # NUNCA invade o audio ou legenda anterior!

    # Duracao minima para leitura confortavel do quadrinho (1.05s a 1.20s)
    # Qualquer extensao e feita SEMPRE no final (cauda), NUNCA puxando st para tras!
    min_card = 1.10
    max_card = 2.40
    et = speech_end + 0.20

    if last + 1 < len(words):
        next_start = float(words[last + 1]["start"])
        # Se ha fala logo em seguida, respeita o inicio da proxima fala
        if et - st < min_card:
            et = min(st + min_card, max(speech_end + 0.15, next_start - 0.04))
        else:
            et = min(et, next_start - 0.04)
    else:
        if et - st < min_card:
            et = min(video_duration - 0.05, st + min_card)

    # Limite maximo de duracao
    if et - st > max_card:
        et = min(video_duration - 0.05, st + max(max_card, speech_end - st + 0.15))

    st = max(0.0, min(st, video_duration - 0.5))
    et = max(st + 0.75, min(et, video_duration - 0.05))
    return round(st, 2), round(et, 2)



def build_spoken_punchline_candidates(items: List[Dict[str, Any]], video_duration: float) -> List[Dict[str, Any]]:
    """Gera 1 candidato por oração com o melhor trecho (1-5 palavras faladas ou âncora canônica) e timing palavra-a-palavra."""
    words = _flatten_words(items)
    candidates: List[Dict[str, Any]] = []
    for s_idx, sent in enumerate(_build_sentences(words)):
        sent_words_raw = [words[k]["word"] for k in sent]
        sent_text = " ".join(sent_words_raw)

        # 1. Checa se a oração contém uma âncora canônica de clímax mangá
        anchor_match = None
        for pat in CLIMAX_CANONICAL_ANCHORS:
            m = re.search(pat, sent_text)
            if m:
                char_start, char_end = m.start(), m.end()
                cur_pos = 0
                first_k, last_k = None, None
                for k in sent:
                    w = words[k]["word"]
                    w_start = sent_text.find(w, cur_pos)
                    if w_start == -1:
                        w_start = cur_pos
                    w_end = w_start + len(w)
                    cur_pos = w_end
                    if w_end > char_start and first_k is None:
                        first_k = k
                    if w_start < char_end:
                        last_k = k
                if first_k is not None and last_k is not None:
                    anchor_match = (first_k, last_k)
                    break

        if anchor_match:
            first, last = anchor_match
            # Pega EXCLUSIVAMENTE as palavras reais faladas na oração, sem criar nem substituir frases
            tokens = [_display(words[k]["word"]) for k in range(first, last + 1)]
            tail_raw = words[last]["word"]
            sent_end_raw = words[sent[-1]]["word"]
            is_question = tail_raw.endswith("?") or sent_end_raw.endswith("?")
            symbol = "?" if is_question else "!"
            l1, l2 = split_punch_lines(tokens)
            st, et = _card_timing(words, first, last, video_duration)
            candidates.append({
                "sentence_idx": s_idx,
                "score": 60.0 + _sentence_bonus(words, sent),
                "start": st,
                "end": et,
                "frame_t": round((words[first]["start"] + words[last]["end"]) / 2.0, 2),
                "speech_start": round(words[first]["start"], 2),
                "speech_end": round(words[last]["end"], 2),
                "text": sent_text,
                "punch_text": " ".join(tokens),
                "line1": l1,
                "line2": f"{l2}{symbol}",
                "symbol": symbol,
            })
            continue

        best = None
        for i in range(len(sent)):
            for j in range(i + 1, min(len(sent), i + 5) + 1):
                sc = _score_span(words, sent, i, j)
                if sc is not None and (best is None or sc > best[0]):
                    best = (sc, i, j)
        if best is None:
            continue
        sc, i, j = best
        first, last = sent[i], sent[j - 1]
        tokens = [_display(words[k]["word"]) for k in sent[i:j]]
        tail_raw = words[last]["word"]
        sent_end_raw = words[sent[-1]]["word"]
        is_question = tail_raw.endswith("?") or (j == len(sent) and sent_end_raw.endswith("?"))
        symbol = "?" if is_question else "!"
        l1, l2 = split_punch_lines(tokens)
        st, et = _card_timing(words, first, last, video_duration)
        candidates.append({
            "sentence_idx": s_idx,
            "score": sc + _sentence_bonus(words, sent),
            "start": st,
            "end": et,
            "frame_t": round((words[first]["start"] + words[last]["end"]) / 2.0, 2),
            "speech_start": round(words[first]["start"], 2),
            "speech_end": round(words[last]["end"], 2),
            "text": " ".join(words[k]["word"] for k in sent),
            "punch_text": " ".join(tokens),
            "line1": l1,
            "line2": f"{l2}{symbol}",
            "symbol": symbol,
        })
    return candidates


def _emit_log(cb: Optional[Callable[[str], None]], msg: str):
    if cb:
        try:
            cb(msg)
        except Exception:
            pass
    print(msg)


HQ_PANEL_STYLES = [
    "hq_shonen_panel",     # Quadro Clássico Shonen Jump (Nanquim P&B + Retícula 45° + Selective Color Pop)
    "hq_color_webtoon",    # Quadro Colorido Solo Leveling / Manhwa Deluxe (Cel-Shading + Lineart Nanquim)
    "hq_diagonal_impact",  # Quadro de Ação Inclinado em Paralelogramo + Katana Slash
    "hq_eyes_strip",       # Faixa Horizontal Cinematográfica Close-Up nos Olhos/Expressão
    "hq_dual_split",       # Página Dupla de Mangá (2-Panel Split: Setup + Clímax)
    "hq_triple_cascade",   # Página Tripla de Mangá (3-Panel Escalation Strip: Setup -> Zoom -> Clímax)
    "hq_noir_crimson",     # Quadro Seinen Dark / Sin City Noir Duotone
    "hq_rain_melancholy",  # Quadro Melancólico Chuva & Prata Azul-Frio (Triste / Emocional)
    "hq_soft_memory",      # Quadro Memória / Flashback Marfim-Prateado (Triste / Nostalgia)
    "hq_romance_glow",     # Quadro Shoujo / Webtoon Romance (Luz Rosé & Ouro Quente)
    "hq_pop_halftone",     # Quadro Pop Vibrante Mangá (Comédia / Animada / Hype)
    "hq_golden_eclipse",   # Quadro Eclipse Dourado / Imperial (Épico / Seinen / Soberano)
]

ALL_FEELING_STYLES = [
    "domain_dark", "blade_stream", "golden_god", "blood_ink", "electric",
    "fire", "cyber_glitch", "comic_halftone", "emotional_tear", "offset_comic",
    "manga_bubble", "slam", "shonen_badge", "typewriter", "comedy",
    "dramatic_silence", "silver_grief", "midnight_sorrow",
    "fading_echo", "broken_promise", "cold_solitude",
    "sakura_bloom", "golden_romance", "heart_pulse",
    "velvet_kiss", "starlight_crush", "sweet_blush", "eternal_vow",
    "cursed_aura", "abyssal_void"
]

MANGA_THEME_PROFILES: Dict[str, Dict[str, Any]] = {
    "geral": {
        "label": "🌟 Geral / Dinâmico (Padrão IA)",
        "description": "Adaptação livre ao vídeo: usa todos os 12 Quadros Editoriais HQ e 30 Feelings sem repetição.",
        "panels": [
            "hq_shonen_panel", "hq_color_webtoon", "hq_diagonal_impact",
            "hq_eyes_strip", "hq_dual_split", "hq_triple_cascade",
            "hq_noir_crimson", "hq_golden_eclipse", "hq_pop_halftone",
            "hq_rain_melancholy", "hq_soft_memory", "hq_romance_glow"
        ],
        "feelings": [
            "domain_dark", "blade_stream", "golden_god", "blood_ink", "electric",
            "fire", "cyber_glitch", "comic_halftone", "emotional_tear", "offset_comic",
            "manga_bubble", "slam", "shonen_badge", "cursed_aura", "abyssal_void",
            "dramatic_silence", "silver_grief", "sakura_bloom", "golden_romance"
        ],
        "keywords": [],
        "prompt_hint": "Modo Geral Dinâmico: adapte livremente as 12 arquiteturas de quadro e feelings ao clímax real de cada frase, sem repetir estilos.",
    },
    "triste": {
        "label": "💧 Triste / Emocional & Melancólico",
        "description": "6 Quadros Melancólicos (Chuva/Memória/Olhos/Split/Cascata 3x) • 8 Feelings Emocionais Únicos (Zero Katana/Fogo).",
        "panels": [
            "hq_rain_melancholy", "hq_eyes_strip", "hq_soft_memory",
            "hq_dual_split", "hq_triple_cascade", "hq_shonen_panel"
        ],
        "feelings": [
            "emotional_tear", "dramatic_silence", "silver_grief", "midnight_sorrow",
            "fading_echo", "broken_promise", "cold_solitude", "typewriter"
        ],
        "keywords": [
            "adeus", "perdão", "perdoa", "desculpa", "sozinho", "sozinha", "chorar", "choro",
            "lágrimas", "dor", "doi", "dói", "nunca", "promessa", "saudade", "partir", "morrer",
            "morte", "fim", "culpa", "tarde", "esquecer", "lembrar", "coração", "triste", "perdi"
        ],
        "prompt_hint": (
            "TEMA OBRIGATÓRIO: TRISTE / EMOCIONAL / MELANCÓLICO. "
            "Este vídeo é dramático, triste ou reflexivo. Escolha as falas de maior carga emocional, despedida, dor, luto ou desabafo. "
            "Use EXCLUSIVAMENTE panel_style dentre ['hq_rain_melancholy', 'hq_eyes_strip', 'hq_soft_memory', 'hq_dual_split', 'hq_triple_cascade', 'hq_shonen_panel'] "
            "e feeling dentre ['emotional_tear', 'dramatic_silence', 'silver_grief', 'midnight_sorrow', 'fading_echo', 'broken_promise', 'cold_solitude', 'typewriter']. "
            "PROIBIDO usar feelings agressivos ou cômicos como 'fire', 'slam', 'comedy', 'blood_ink' ou 'manga_bubble'!"
        ),
    },
    "romantica": {
        "label": "💖 Romântica / Casal & Shoujo",
        "description": "6 Quadros Romance (Glow/Olhos/Split/Cascata 3x/Memória/Webtoon) • 8 Feelings Românticos Únicos.",
        "panels": [
            "hq_romance_glow", "hq_eyes_strip", "hq_dual_split",
            "hq_triple_cascade", "hq_soft_memory", "hq_color_webtoon"
        ],
        "feelings": [
            "sakura_bloom", "golden_romance", "heart_pulse", "velvet_kiss",
            "starlight_crush", "sweet_blush", "eternal_vow", "emotional_tear"
        ],
        "keywords": [
            "amor", "amo", "amar", "coração", "juntos", "proteger", "sempre", "sorriso",
            "linda", "lindo", "sentimento", "apaixonado", "apaixonada", "beijo", "abraço",
            "comigo", "mundo", "prometo", "cuidar", "feliz", "destino", "você", "casar"
        ],
        "prompt_hint": (
            "TEMA OBRIGATÓRIO: ROMÂNTICA / CASAL / SHOUJO / DORAMA. "
            "Este vídeo foca em romance, química, afeto ou declaração emocional. Escolha as falas mais apaixonantes, doces ou intensas do casal. "
            "Use EXCLUSIVAMENTE panel_style dentre ['hq_romance_glow', 'hq_eyes_strip', 'hq_dual_split', 'hq_triple_cascade', 'hq_soft_memory', 'hq_color_webtoon'] "
            "e feeling dentre ['sakura_bloom', 'golden_romance', 'heart_pulse', 'velvet_kiss', 'starlight_crush', 'sweet_blush', 'eternal_vow', 'emotional_tear']. "
            "PROIBIDO usar estilos violentos ou sombrios!"
        ),
    },
    "acao": {
        "label": "⚔️ Ação / Batalha & Poder Shonen",
        "description": "7 Quadros de Combate (Diagonal/Webtoon/Split/Cascata 3x/Shonen/Noir/Eclipse) • 9 Feelings de Poder.",
        "panels": [
            "hq_diagonal_impact", "hq_color_webtoon", "hq_dual_split",
            "hq_triple_cascade", "hq_shonen_panel", "hq_noir_crimson", "hq_golden_eclipse"
        ],
        "feelings": [
            "blade_stream", "fire", "electric", "blood_ink", "slam",
            "shonen_badge", "domain_dark", "golden_god", "cursed_aura"
        ],
        "keywords": [
            "morra", "matar", "poder", "força", "ataque", "golpe", "corte", "destruir",
            "bankai", "haki", "lutem", "lutar", "vencer", "derrotar", "sangue", "fogo", "raio"
        ],
        "prompt_hint": (
            "TEMA OBRIGATÓRIO: AÇÃO / BATALHA SHONEN / COMBATE EXPLOSIVO. "
            "Escolha gritos de guerra, técnicas especiais, impactos de luta e momentos de adrenalina máxima. "
            "Use EXCLUSIVAMENTE panel_style dentre ['hq_diagonal_impact', 'hq_color_webtoon', 'hq_dual_split', 'hq_triple_cascade', 'hq_shonen_panel', 'hq_noir_crimson', 'hq_golden_eclipse'] "
            "e feeling dentre ['blade_stream', 'fire', 'electric', 'blood_ink', 'slam', 'shonen_badge', 'domain_dark', 'golden_god', 'cursed_aura']."
        ),
    },
    "animada": {
        "label": "🎉 Animada / Comédia & Hype Pop",
        "description": "6 Quadros Pop (Halftone/Webtoon/Split/Cascata 3x/Shonen/Olhos) • 8 Feelings Vibrantes.",
        "panels": [
            "hq_pop_halftone", "hq_color_webtoon", "hq_dual_split",
            "hq_triple_cascade", "hq_shonen_panel", "hq_eyes_strip"
        ],
        "feelings": [
            "comedy", "offset_comic", "comic_halftone", "manga_bubble",
            "electric", "golden_god", "shonen_badge", "starlight_crush"
        ],
        "keywords": [
            "incrível", "demais", "maluco", "doido", "sério", "mentira", "olha", "bora",
            "vamos", "ganhei", "perfeito", "festa", "amigos", "engraçado", "socorro", "eita", "opa"
        ],
        "prompt_hint": (
            "TEMA OBRIGATÓRIO: ANIMADA / COMÉDIA / HYPE POP / DIVERTIDA. "
            "Escolha falas carismáticas, reações engraçadas, surpresas ou momentos empolgantes. "
            "Use EXCLUSIVAMENTE panel_style dentre ['hq_pop_halftone', 'hq_color_webtoon', 'hq_dual_split', 'hq_triple_cascade', 'hq_shonen_panel', 'hq_eyes_strip'] "
            "e feeling dentre ['comedy', 'offset_comic', 'comic_halftone', 'manga_bubble', 'electric', 'golden_god', 'shonen_badge', 'starlight_crush']."
        ),
    },
    "sombria": {
        "label": "🌑 Sombria / Suspense & Seinen Dark",
        "description": "6 Quadros Seinen (Noir/Olhos/Shonen/Split/Cascata 3x/Eclipse) • 8 Feelings Sombrios.",
        "panels": [
            "hq_noir_crimson", "hq_eyes_strip", "hq_shonen_panel",
            "hq_dual_split", "hq_triple_cascade", "hq_golden_eclipse"
        ],
        "feelings": [
            "domain_dark", "blood_ink", "cursed_aura", "abyssal_void",
            "cyber_glitch", "typewriter", "blade_stream", "midnight_sorrow"
        ],
        "keywords": [
            "morte", "sangue", "maldição", "medo", "escuridão", "inferno", "demônio", "monstro",
            "segredo", "mentira", "traição", "assassino", "kira", "justiça", "sombra", "pesadelo", "caos"
        ],
        "prompt_hint": (
            "TEMA OBRIGATÓRIO: SOMBRIA / SUSPENSE PSICOLÓGICO / VILÃO / SEINEN DARK. "
            "Escolha falas frias, intimidadoras, ameaças calculistas ou revelações sombrias. "
            "Use EXCLUSIVAMENTE panel_style dentre ['hq_noir_crimson', 'hq_eyes_strip', 'hq_shonen_panel', 'hq_dual_split', 'hq_triple_cascade', 'hq_golden_eclipse'] "
            "e feeling dentre ['domain_dark', 'blood_ink', 'cursed_aura', 'abyssal_void', 'cyber_glitch', 'typewriter', 'blade_stream', 'midnight_sorrow']."
        ),
    },
    "epica": {
        "label": "👑 Épica / Clímax Supremo & Divino",
        "description": "7 Quadros Soberanos (Eclipse/Split/Cascata 3x/Webtoon/Shonen/Diagonal) • 9 Feelings Épicos.",
        "panels": [
            "hq_golden_eclipse", "hq_dual_split", "hq_triple_cascade",
            "hq_color_webtoon", "hq_shonen_panel", "hq_diagonal_impact", "hq_eyes_strip"
        ],
        "feelings": [
            "golden_god", "domain_dark", "electric", "fire", "blade_stream",
            "shonen_badge", "cursed_aura", "eternal_vow", "abyssal_void"
        ],
        "keywords": [
            "deus", "rei", "imperador", "supremo", "absoluto", "mundo", "destino", "história",
            "lenda", "nunca", "jamais", "juro", "poder", "erguer", "vencer", "eternidade", "glória"
        ],
        "prompt_hint": (
            "TEMA OBRIGATÓRIO: ÉPICA / CLÍMAX SUPREMO / DIVINO / ARREPIO. "
            "Escolha discursos lendários, despertares supremos, juramentos e momentos históricos. "
            "Use EXCLUSIVAMENTE panel_style dentre ['hq_golden_eclipse', 'hq_dual_split', 'hq_triple_cascade', 'hq_color_webtoon', 'hq_shonen_panel', 'hq_diagonal_impact', 'hq_eyes_strip'] "
            "e feeling dentre ['golden_god', 'domain_dark', 'electric', 'fire', 'blade_stream', 'shonen_badge', 'cursed_aura', 'eternal_vow', 'abyssal_void']."
        ),
    },
}


def resolve_manga_theme_key(theme_input: Optional[str]) -> str:
    """Converte chave ou rótulo de UI para a chave canônica do tema ('geral', 'triste', 'romantica', 'acao', 'animada', 'sombria', 'epica')."""
    if not theme_input:
        return "geral"
    raw = str(theme_input).strip().lower()
    if raw in MANGA_THEME_PROFILES:
        return raw
    for k, v in MANGA_THEME_PROFILES.items():
        if raw == v["label"].lower() or k in raw:
            return k
    if "triste" in raw or "emocional" in raw or "melanc" in raw:
        return "triste"
    if "romant" in raw or "românt" in raw or "casal" in raw or "shoujo" in raw:
        return "romantica"
    if "ação" in raw or "acao" in raw or "batalha" in raw or "shonen" in raw:
        return "acao"
    if "animad" in raw or "comédia" in raw or "comedia" in raw or "pop" in raw:
        return "animada"
    if "sombri" in raw or "suspense" in raw or "seinen" in raw or "noir" in raw:
        return "sombria"
    if "épic" in raw or "epic" in raw or "suprem" in raw or "divin" in raw:
        return "epica"
    return "geral"


def curate_manga_punchlines_with_ollama(
    items: List[Dict[str, Any]],
    video_duration: float,
    target_count: int = 6,
    model: str = "qwen2.5:7b",
    timeout: float = 30.0,
    log_callback: Optional[Callable[[str], None]] = None,
    manga_theme: str = "geral",
) -> Optional[List[Dict[str, Any]]]:
    """
    Curadoria Semântica via IA Local (Ollama Qwen 2.5 7B na GPU RTX 5060):
    - Lê a cena inteira e detecta os momentos de clímax máximo (revelações, gritos, confronto).
    - Extrai punchlines curtas (1 a 4 palavras) e quebra em Linha 1 e Linha 2 de forma natural.
    - Classifica o 'feeling' visual de cada fala ('slam', 'golden_god', 'electric', 'fire', 'offset_comic', 'manga_bubble').
    - Sincroniza com as palavras reais do Whisper para precisão frame-accurate.
    - Retorna None em caso de falha ou timeout para acionar fallback heurístico imediato.
    """
    words = _flatten_words(items)
    sents = _build_sentences(words)
    if not sents:
        return None

    sector_step = video_duration / target_count
    sectors = []
    for i in range(target_count):
        sec_st = round(i * sector_step, 1)
        sec_et = round((i + 1) * sector_step if i < target_count - 1 else video_duration, 1)
        sectors.append((sec_st, sec_et))

    sent_summaries = []
    for idx, sent in enumerate(sents):
        raw_text = " ".join(words[k]["word"] for k in sent)
        st = round(words[sent[0]]["start"], 2)
        et = round(words[sent[-1]]["end"], 2)
        mid_t = (st + et) / 2.0
        sec_idx = min(target_count - 1, max(0, int(mid_t / sector_step)))
        sec_label = f"Setor {sec_idx + 1}/{target_count} ({sectors[sec_idx][0]}s-{sectors[sec_idx][1]}s)"
        sent_summaries.append({
            "id": idx,
            "setor": sec_label,
            "start": st,
            "end": et,
            "text": raw_text
        })

    t_key = resolve_manga_theme_key(manga_theme)
    theme_cfg = MANGA_THEME_PROFILES.get(t_key, MANGA_THEME_PROFILES["geral"])
    theme_hint_block = f"\nDIRETRIZ DE TEMA ESCOLHIDA PELO USUÁRIO ({theme_cfg['label']}):\n{theme_cfg['prompt_hint']}\n"

    sector_rules_str = "\n".join(
        f"   - 1 momento do Setor {i+1} ({sectors[i][0]}s-{sectors[i][1]}s)"
        for i in range(target_count)
    )

    prompt = f"""Você é um Diretor de Anime e Editor Chefe de Mangá.
Seu objetivo é criar um ritmo cinematográfico equilibrado ao longo de todo o vídeo de {video_duration:.1f}s.{theme_hint_block}
O vídeo foi dividido em {target_count} Setores Temporais ({sectors[0][0]}s a {sectors[-1][1]}s).

Você DEVE selecionar EXATAMENTE 1 momento de impacto por Setor (totalizando exatamente {target_count} momentos).
NUNCA aglomere momentos no mesmo setor deixando outros setores vazios. Cada setor DEVE ter seu momento!

REGRAS OBRIGATÓRIAS:
1. EXATAMENTE 1 MOMENTO POR SETOR (Distribuídos ao longo de todo o vídeo):
{sector_rules_str}
2. PUNCHLINE CURTA: Extraia 1 a 4 palavras por momento. NUNCA selecione frases longas.
3. PALAVRAS REAIS: Use EXCLUSIVAMENTE palavras faladas no áudio da oração indicada pelo "id". NUNCA invente palavras. NUNCA use palavras de exemplos anteriores se elas não existirem na transcrição deste vídeo.
4. DIVISÃO EM 2 LINHAS: Divida em "line1" e "line2" com cadência dramática de mangá (ex: L1: "PALAVRA 1", L2: "PALAVRA 2!"). Se for apenas 1 palavra, line1 fica vazio e line2 recebe a palavra.
5. FEELING DA CENA (Adapte ao tom dramático ou emocional real):
   - "slam": Choque, perigo, corte, impacto físico imediato.
   - "domain_dark": Poder absoluto, vazio cósmico, escuridão, vilão, Sukuna/Gojo.
   - "blade_stream": Respiração shonen, espada, corte fluido de katana, marcial.
   - "blood_ink": Fúria visceral, berserk, ódio, combate sangrento, desespero.
   - "golden_god": Poder supremo, transformação divina, revelação ou vitória.
   - "electric": Suspense tenso, questionamento, raio/reiatsu.
   - "fire": Raiva, fúria, ataque, grito de batalha.
   - "cyber_glitch": Tecnologia, scanline, distorção holográfica.
   - "comic_halftone": Pop shonen clássico reticulado, super-herói.
   - "emotional_tear": Tristeza profunda, dor emocional, luto, despedida, lágrimas.
   - "offset_comic": Ironia, impacto pop, surpresa.
   - "manga_bubble": Chamada de nome, exclamação rápida.

TRANSCRIÇÃO DAS ORAÇÕES POR SETOR TEMPORAL:
{json.dumps(sent_summaries, ensure_ascii=False, indent=2)}

Responda ESTRITAMENTE em formato JSON com uma chave "moments" contendo os {target_count} momentos (um por setor):
{{
  "moments": [
    {{
      "setor": 1,
      "id": 0,
      "exact_words": "PALAVRAS DA PUNCHLINE",
      "line1": "LINHA 1",
      "line2": "LINHA 2!",
      "feeling": "slam"
    }}
  ]
}}
"""
    _emit_log(log_callback, f"Anime FX Pro: Consultando IA Local Ollama ({model}) na GPU para curadoria de {target_count} momentos...")
    t0 = time.time()
    try:
        resp = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.2}
            },
            timeout=timeout
        )
        if resp.status_code != 200:
            _emit_log(log_callback, f"Anime FX Pro: Ollama retornou HTTP {resp.status_code} ({resp.text[:80]}). Ativando curadoria heurística...")
            return None
        content = resp.json().get("message", {}).get("content", "")
        data = json.loads(content)
        moments = data.get("moments") or (data if isinstance(data, list) else None)
        if not moments:
            _emit_log(log_callback, "Anime FX Pro: IA Local não retornou momentos válidos no JSON. Ativando curadoria heurística...")
            return None

        events = []
        used_sents = set()
        for m in moments:
            s_id = m.get("id")
            if s_id is None or s_id >= len(sents) or s_id in used_sents:
                continue
            sent = sents[s_id]
            sent_text = " ".join(words[k]["word"] for k in sent)

            exact_target = (m.get("exact_words") or "").strip().lower()
            l1 = (m.get("line1") or "").strip()
            l2 = (m.get("line2") or "").strip()

            is_q = "?" in l2 or "?" in sent_text
            sym = "?" if is_q else "!"
            clean_l1 = re.sub(r"[?!]", "", l1).strip().upper()
            clean_l2 = re.sub(r"[?!]", "", l2).strip().upper()
            if not clean_l2.endswith(sym):
                clean_l2 = f"{clean_l2}{sym}"

            # Tokens alvo: prioriza o que esta efetivamente escrito no card (clean_l1 + clean_l2)
            card_phrase = f"{clean_l1} {clean_l2}".strip().lower()
            target_phrase = card_phrase if card_phrase else exact_target
            target_toks = [_norm(w) for w in target_phrase.split() if _norm(w)]
            if not target_toks:
                target_toks = [_norm(w) for w in exact_target.split() if _norm(w)]

            first_k, last_k = None, None

            # 1. Busca primeiro dentro da oracao indicada pelo LLM
            sent_norms = [_norm(words[k]["word"]) for k in sent]
            if target_toks:
                for start_idx in range(len(sent_norms) - len(target_toks) + 1):
                    if sent_norms[start_idx:start_idx + len(target_toks)] == target_toks:
                        first_k = sent[start_idx]
                        last_k = sent[start_idx + len(target_toks) - 1]
                        break

            # 2. Se nao encontrou na oracao indicada, busca em todas as oracoes (recupera caso o LLM erre o id)
            if first_k is None and target_toks:
                all_norms = [_norm(w["word"]) for w in words]
                for start_idx in range(len(all_norms) - len(target_toks) + 1):
                    if all_norms[start_idx:start_idx + len(target_toks)] == target_toks:
                        first_k = start_idx
                        last_k = start_idx + len(target_toks) - 1
                        # Atualiza s_id para a oracao real correspondente
                        for check_s_idx, check_sent in enumerate(sents):
                            if first_k in check_sent:
                                s_id = check_s_idx
                                sent = check_sent
                                sent_text = " ".join(words[k]["word"] for k in sent)
                                break
                        break

            # 3. Fallback de sub-sequencia (se o card tiver 2 palavras e apenas a punchline final coincidir)
            if first_k is None and target_toks:
                for t_word in reversed(target_toks):
                    for idx in reversed(sent):
                        if _norm(words[idx]["word"]) == t_word:
                            first_k = idx
                            last_k = idx
                            break
                    if first_k is not None:
                        break

            # 4. Fallback de seguranca estruturada da propria oracao
            if first_k is None or last_k is None:
                first_k = sent[max(0, len(sent) - 2)]
                last_k = sent[-1]

            st, et = _card_timing(words, first_k, last_k, video_duration)


            allowed_f = theme_cfg.get("feelings") or ALL_FEELING_STYLES
            feeling = m.get("feeling", allowed_f[0])
            if feeling not in allowed_f:
                feeling = allowed_f[len(events) % len(allowed_f)]

            events.append({
                "sentence_idx": s_id,
                "score": 95.0,
                "start": st,
                "end": et,
                "frame_t": round((words[first_k]["start"] + words[last_k]["end"]) / 2.0, 2),
                "speech_start": round(words[first_k]["start"], 2),
                "speech_end": round(words[last_k]["end"], 2),
                "text": sent_text,
                "punch_text": f"{clean_l1} {clean_l2}".strip(),
                "line1": clean_l1,
                "line2": clean_l2,
                "symbol": sym,
                "event_type": "manga_eyes_panel" if sym == "?" else "scene_manga_panel",
                "item_idx": -1,
                "text_style": feeling
            })
            used_sents.add(s_id)

        events.sort(key=lambda x: x["start"])

        # Pacing Guard: Garante espacamento ritmico equilibrado (permitindo 8-9 recortes em videos >40s)
        min_pacing_gap = max(1.4, (video_duration / max(1, target_count)) * 0.22)
        spaced_events = []
        for ev in events:
            if not spaced_events:
                spaced_events.append(ev)
                continue
            prev_ev = spaced_events[-1]
            if ev["start"] >= prev_ev["end"] + min_pacing_gap:
                spaced_events.append(ev)

        # Se houver setores vazios, preenche lacunas com o melhor candidato de cada setor
        if len(spaced_events) < target_count:
            candidates = build_spoken_punchline_candidates(items, video_duration)
            used_sentence_ids = {e["sentence_idx"] for e in spaced_events}
            for sec_idx, (sec_st, sec_et) in enumerate(sectors):
                if len(spaced_events) >= target_count:
                    break
                has_ev = any(sec_st - 0.8 <= e["start"] <= sec_et + 0.8 for e in spaced_events)
                if not has_ev:
                    best_cand, best_sc = None, -1e9
                    sec_mid = (sec_st + sec_et) / 2.0
                    for c in candidates:
                        if c["sentence_idx"] in used_sentence_ids:
                            continue
                        collides = any(
                            not (c["end"] + min_pacing_gap <= e["start"] or c["start"] >= e["end"] + min_pacing_gap)
                            for e in spaced_events
                        )
                        if collides:
                            continue
                        sc = c["score"] - 0.25 * abs(c["speech_start"] - sec_mid)
                        if sc > best_sc:
                            best_cand, best_sc = c, sc
                    if best_cand:
                        used_sentence_ids.add(best_cand["sentence_idx"])
                        new_ev = dict(best_cand)
                        new_ev["event_type"] = "manga_eyes_panel" if new_ev["symbol"] == "?" else "scene_manga_panel"
                        new_ev["item_idx"] = -1
                        new_ev["text_style"] = "electric" if new_ev["symbol"] == "?" else "slam"
                        spaced_events.append(new_ev)
                        spaced_events.sort(key=lambda x: x["start"])

            # Segunda passagem com gap relaxado (0.9s) caso ainda falte atingir a meta de 8-9 recortes
            if len(spaced_events) < target_count:
                relaxed_gap = 0.90
                for c in sorted(candidates, key=lambda x: x["score"], reverse=True):
                    if len(spaced_events) >= target_count:
                        break
                    if c["sentence_idx"] in used_sentence_ids:
                        continue
                    collides = any(
                        not (c["end"] + relaxed_gap <= e["start"] or c["start"] >= e["end"] + relaxed_gap)
                        for e in spaced_events
                    )
                    if not collides:
                        used_sentence_ids.add(c["sentence_idx"])
                        new_ev = dict(c)
                        new_ev["event_type"] = "manga_eyes_panel" if new_ev["symbol"] == "?" else "scene_manga_panel"
                        new_ev["item_idx"] = -1
                        new_ev["text_style"] = "electric" if new_ev["symbol"] == "?" else "slam"
                        spaced_events.append(new_ev)
                        spaced_events.sort(key=lambda x: x["start"])

        events = spaced_events
        events.sort(key=lambda x: x["start"])

        elapsed = time.time() - t0
        _emit_log(log_callback, f"Anime FX Pro: IA Local Ollama ({model}) selecionou {len(events)} punchlines com feelings dinâmicos em {elapsed:.1f}s!")
        for idx, ev in enumerate(events):
            gap_str = f" [Intervalo: {ev['start'] - events[idx-1]['end']:.1f}s]" if idx > 0 else " [Abertura]"
            _emit_log(log_callback, f"   -> Recorte ({idx+1}/{len(events)}): '{ev['punch_text']}' [Estilo: {ev['text_style']}] no momento {ev['start']}s-{ev['end']}s{gap_str}")
        return events
    except Exception as e:
        _emit_log(log_callback, f"Anime FX Pro: Exceção na IA Local ({e}). Ativando curadoria heurística determinística...")
        return None


def classify_manga_feelings_with_ollama(
    cards_text: List[str],
    model: str = "qwen2.5vl:3b",
    timeout: float = 22.0,
    log_callback: Optional[Callable[[str], None]] = None
) -> List[str]:
    """
    Classifica o feeling emocional de frases manuais usando IA Local Ollama ou heurística contextual,
    garantindo DIVERSIDADE VISUAL MÁXIMA E ZERO REPETIÇÃO em recortes consecutivos.
    """
    if not cards_text:
        return []

    decisions = analyze_cutouts_with_vlm(
        cards_meta=[{"text": t, "start": i * 5.0, "end": i * 5.0 + 2.0} for i, t in enumerate(cards_text)],
        video_path=None,
        video_duration=max(30.0, len(cards_text) * 6.0),
        model=model,
        timeout=timeout,
        log_callback=log_callback,
    )
    return [d["feeling"] for d in decisions]


def ensure_ollama_running(log_callback: Optional[Callable[[str], None]] = None) -> List[str]:
    """
    Garante que o servidor local Ollama esteja rodando em localhost:11434.
    Se estiver offline, inicia `ollama serve` automaticamente em background sem janela.
    Retorna a lista de modelos instalados no Ollama.
    """
    import subprocess
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=1.8)
        if r.status_code == 200:
            return [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        pass

    try:
        if log_callback:
            _emit_log(log_callback, "Anime FX Pro: Iniciando servidor local Ollama em segundo plano...")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if os.name == "nt" else 0
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        for _ in range(10):
            time.sleep(0.5)
            try:
                r = requests.get("http://localhost:11434/api/tags", timeout=1.5)
                if r.status_code == 200:
                    return [m.get("name", "") for m in r.json().get("models", [])]
            except Exception:
                continue
    except Exception:
        pass
    return []


def _resolve_best_ollama_model(requested_model: str, installed_models: List[str]) -> Tuple[str, bool]:
    """
    Resolve o melhor modelo disponível no Ollama (priorizando VLMs visuais se instalados)
    e retorna (model_name, is_vision_model).
    """
    vision_keywords = ("vl", "vision", "moondream", "llava", "minicpm-v", "bakllava")
    req_lower = (requested_model or "").strip().lower()

    if installed_models:
        # 1. Match exato
        for m in installed_models:
            if m.lower() == req_lower:
                is_v = any(vk in m.lower() for vk in vision_keywords)
                return m, is_v
        # 2. Match parcial pelo prefixo
        req_prefix = req_lower.split(":")[0]
        for m in installed_models:
            if m.lower().startswith(req_prefix):
                is_v = any(vk in m.lower() for vk in vision_keywords)
                return m, is_v
        # 3. Se pediu VLM e tem algum VLM instalado (ex: qwen2.5vl:3b, qwen2.5vl:7b, llama3.2-vision)
        for pref in ("qwen2.5vl:3b", "qwen2-vl", "qwen2.5vl:7b", "moondream", "phi3", "llava", "llama3.2-vision"):
            for m in installed_models:
                if pref in m.lower():
                    is_v = any(vk in m.lower() for vk in vision_keywords)
                    return m, is_v
        # 4. Fallback para qwen2.5:7b ou primeiro modelo disponível
        for m in installed_models:
            if "qwen2.5:7b" in m.lower():
                return m, False
        return installed_models[0], any(vk in installed_models[0].lower() for vk in vision_keywords)

    is_v = any(vk in req_lower for vk in vision_keywords)
    return requested_model or "qwen2.5vl:3b", is_v


def _extract_cutout_visual_context(
    video_path: Optional[str],
    cards_meta: List[Dict[str, Any]],
    video_duration: float
) -> Tuple[List[Dict[str, Any]], Optional[str], List[Any]]:
    """
    Extrai métricas visuais reais de cada recorte (luminância, saturação, contraste, movimento,
    detecção de rosto/close-up) e monta uma Prancha de Storyboard (Contact Sheet base64)
    para que o Vision LLM enxergue todos os quadros simultaneamente.
    """
    import base64
    from io import BytesIO
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw

    telemetry: List[Dict[str, Any]] = []
    pil_thumbs: List[Image.Image] = []

    has_video = bool(video_path and os.path.exists(str(video_path)))
    cap = cv2.VideoCapture(str(video_path)) if has_video else None
    v_fps = (cap.get(cv2.CAP_PROP_FPS) or 24.0) if cap else 24.0

    detect_faces = None
    ort_lock = None
    try:
        import manga_fx_engine
        ort_lock = getattr(manga_fx_engine, "_ORT_GPU_LOCK", None)
    except Exception:
        pass
    try:
        from imgutils.detect import detect_faces as _df
        detect_faces = _df
        has_face_det = True
    except Exception:
        has_face_det = False

    for idx, cm in enumerate(cards_meta):
        st = float(cm.get("start", 0.0))
        et = float(cm.get("end", st + 1.5))
        mid_t = st + min(0.45, max(0.15, (et - st) * 0.35))
        prog = round(min(1.0, max(0.0, st / max(1.0, video_duration))), 2)

        info = {
            "card_index": idx + 1,
            "text": cm.get("text", ""),
            "narrative_progress": prog,
            "luminance": 115.0,
            "saturation": 95.0,
            "contrast": 52.0,
            "motion_intensity": 20.0,
            "has_face_closeup": False,
            "face_area_ratio": 0.0,
        }

        if cap and cap.isOpened():
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(mid_t * v_fps)))
            ret, frame_bgr = cap.read()
            if ret and frame_bgr is not None:
                rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
                hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)

                info["luminance"] = round(float(np.mean(gray)), 1)
                info["saturation"] = round(float(np.mean(hsv[:, :, 1])), 1)
                info["contrast"] = round(float(np.std(gray)), 1)

                # Mede intensidade de movimento comparando frame 0.25s antes
                cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(max(0.0, mid_t - 0.25) * v_fps)))
                ret_prev, prev_bgr = cap.read()
                if ret_prev and prev_bgr is not None and prev_bgr.shape == frame_bgr.shape:
                    prev_gray = cv2.cvtColor(prev_bgr, cv2.COLOR_BGR2GRAY)
                    diff = float(np.mean(cv2.absdiff(gray, prev_gray)))
                    info["motion_intensity"] = round(diff, 1)

                pil_f = Image.fromarray(rgb)
                if has_face_det and detect_faces is not None:
                    try:
                        orig_w, orig_h = pil_f.size
                        det_f = pil_f.resize((640, max(1, int(orig_h * (640.0 / orig_w)))), Image.Resampling.BILINEAR) if orig_w > 640 else pil_f
                        if ort_lock is not None:
                            with ort_lock:
                                faces = detect_faces(det_f)
                        else:
                            faces = detect_faces(det_f)
                        if faces:
                            best_f = max(faces, key=lambda item: (item[0][2] - item[0][0]) * (item[0][3] - item[0][1]))
                            fw = max(1, best_f[0][2] - best_f[0][0])
                            fh = max(1, best_f[0][3] - best_f[0][1])
                            f_ratio = float(fw * fh) / float(det_f.width * det_f.height)
                            info["face_area_ratio"] = round(f_ratio, 3)
                            info["has_face_closeup"] = f_ratio >= 0.045
                    except Exception:
                        pass

                thumb = pil_f.resize((384, 216), Image.Resampling.BILINEAR)
                tdraw = ImageDraw.Draw(thumb)
                tdraw.rectangle([0, 0, 130, 32], fill=(0, 0, 0))
                tdraw.text((8, 6), f"CARD #{idx + 1} ({st:.1f}s)", fill=(255, 220, 40))
                pil_thumbs.append(thumb)

        telemetry.append(info)

    if cap:
        cap.release()

    contact_b64 = None
    if pil_thumbs:
        cols = min(2, len(pil_thumbs))
        rows = (len(pil_thumbs) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * 384, rows * 216), (12, 12, 16))
        for i, th in enumerate(pil_thumbs):
            r_idx = i // cols
            c_idx = i % cols
            sheet.paste(th, (c_idx * 384, r_idx * 216))
        buf = BytesIO()
        sheet.save(buf, format="JPEG", quality=82)
        contact_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    return telemetry, contact_b64, pil_thumbs


def _compute_context_driven_design(
    cards_meta: List[Dict[str, Any]],
    telemetry: List[Dict[str, Any]],
    manga_theme: str = "geral"
) -> List[Dict[str, str]]:
    """
    Motor Contextual Inteligente baseado nas métricas visuais reais da cena + semântica da fala + tema escolhido:
    NUNCA usa uma sequência fixa! Adapta o estilo do painel e o feeling respeitando estritamente o `manga_theme`
    ('geral', 'triste', 'romantica', 'acao', 'animada', 'sombria', 'epica') e garantindo zero repetição consecutiva.
    """
    from manga_fx_engine import detect_manga_feeling

    t_key = resolve_manga_theme_key(manga_theme)
    theme_cfg = MANGA_THEME_PROFILES.get(t_key, MANGA_THEME_PROFILES["geral"])
    allowed_panels: List[str] = list(theme_cfg["panels"])
    allowed_feelings: List[str] = list(theme_cfg["feelings"])

    results: List[Dict[str, str]] = []
    used_feelings_recent: List[str] = []
    used_panels_recent: List[str] = []
    used_layouts_recent: List[str] = []

    # Janela de Anti-Repetição de Baralho Completo (Full-Deck Cycle):
    # Garante que em vídeos com 8 a 9 recortes cada recorte tenha um feeling 100% único
    # e alterne entre todas as arquiteturas de quadro do tema antes de repetir!
    f_win = max(1, len(allowed_feelings) - 1)
    p_win = max(1, len(allowed_panels) - 1)

    for idx, cm in enumerate(cards_meta):
        txt = str(cm.get("text", "")).strip()
        t_up = txt.upper()
        tel = telemetry[idx] if idx < len(telemetry) else {}

        lum = float(tel.get("luminance", 115.0))
        sat = float(tel.get("saturation", 95.0))
        mot = float(tel.get("motion_intensity", 20.0))
        has_closeup = bool(tel.get("has_face_closeup", False))
        prog = float(tel.get("narrative_progress", 0.5))

        # 1. Determina candidatos de Feeling ordenados por afinidade contextual + tema
        feeling_candidates: List[str] = []
        if t_key == "triste":
            if "?" in txt or lum < 80.0:
                feeling_candidates.extend(["midnight_sorrow", "dramatic_silence", "broken_promise", "cold_solitude", "emotional_tear", "silver_grief", "fading_echo", "typewriter"])
            elif prog >= 0.65:
                feeling_candidates.extend(["emotional_tear", "silver_grief", "fading_echo", "broken_promise", "midnight_sorrow", "dramatic_silence", "cold_solitude", "typewriter"])
            else:
                feeling_candidates.extend(["dramatic_silence", "emotional_tear", "silver_grief", "fading_echo", "midnight_sorrow", "broken_promise", "cold_solitude", "typewriter"])
        elif t_key == "romantica":
            if prog >= 0.65 or "!" in txt:
                feeling_candidates.extend(["sakura_bloom", "heart_pulse", "eternal_vow", "velvet_kiss", "golden_romance", "starlight_crush", "sweet_blush", "emotional_tear"])
            elif sat > 110.0:
                feeling_candidates.extend(["golden_romance", "starlight_crush", "sakura_bloom", "sweet_blush", "heart_pulse", "velvet_kiss", "eternal_vow", "emotional_tear"])
            else:
                feeling_candidates.extend(["heart_pulse", "sakura_bloom", "sweet_blush", "golden_romance", "velvet_kiss", "starlight_crush", "eternal_vow", "emotional_tear"])
        elif t_key == "animada":
            if "!" in txt or mot > 22.0:
                feeling_candidates.extend(["comedy", "offset_comic", "comic_halftone", "manga_bubble", "electric", "golden_god", "shonen_badge", "starlight_crush"])
            else:
                feeling_candidates.extend(["offset_comic", "manga_bubble", "comedy", "comic_halftone", "starlight_crush", "golden_god", "electric", "shonen_badge"])
        else:
            base_f = detect_manga_feeling(txt)
            if base_f in allowed_feelings and base_f != "slam":
                feeling_candidates.append(base_f)
            if "?" in txt or any(q in t_up for q in ("COMO", "POR QUE", "QUEM", "ONDE", "SERÁ", "IMPOSSÍVEL")):
                feeling_candidates.extend(["cyber_glitch", "electric", "manga_bubble", "domain_dark", "typewriter"])
            if lum < 75.0:
                feeling_candidates.extend(["domain_dark", "blood_ink", "cursed_aura", "abyssal_void", "electric", "cyber_glitch"])
            elif sat > 125.0:
                feeling_candidates.extend(["fire", "golden_god", "electric", "blade_stream", "comic_halftone"])
            elif mot > 26.0:
                feeling_candidates.extend(["blade_stream", "fire", "blood_ink", "shonen_badge", "slam"])
            elif prog >= 0.72:
                feeling_candidates.extend(["golden_god", "domain_dark", "fire", "blood_ink", "electric", "cursed_aura"])

        text_seed = sum((i + 1) * ord(ch) for i, ch in enumerate(t_up)) % len(allowed_feelings)
        rotated_f = allowed_feelings[text_seed:] + allowed_feelings[:text_seed]
        feeling_candidates.extend(rotated_f)
        feeling_candidates = [f for f in feeling_candidates if f in allowed_feelings]
        if not feeling_candidates:
            feeling_candidates = list(allowed_feelings)

        chosen_feeling = feeling_candidates[0]
        for cand_f in feeling_candidates:
            if cand_f not in used_feelings_recent[-f_win:]:
                chosen_feeling = cand_f
                break

        # 2. Determina candidatos de Arquitetura de Quadro HQ (panel_style) dentro do tema escolhido
        panel_candidates: List[str] = []
        if t_key == "triste":
            if "?" in txt or has_closeup:
                panel_candidates.extend(["hq_eyes_strip", "hq_rain_melancholy", "hq_soft_memory"])
            if prog >= 0.65 or mot >= 22.0:
                panel_candidates.extend(["hq_dual_split", "hq_triple_cascade", "hq_rain_melancholy"])
            if lum < 85.0:
                panel_candidates.extend(["hq_rain_melancholy", "hq_shonen_panel", "hq_eyes_strip"])
            else:
                panel_candidates.extend(["hq_soft_memory", "hq_rain_melancholy", "hq_dual_split", "hq_triple_cascade"])
        elif t_key == "romantica":
            if "?" in txt or has_closeup:
                panel_candidates.extend(["hq_eyes_strip", "hq_romance_glow", "hq_soft_memory"])
            if prog >= 0.60 or mot >= 20.0:
                panel_candidates.extend(["hq_dual_split", "hq_triple_cascade", "hq_romance_glow", "hq_color_webtoon"])
            else:
                panel_candidates.extend(["hq_romance_glow", "hq_soft_memory", "hq_dual_split", "hq_triple_cascade", "hq_eyes_strip"])
        elif t_key == "animada":
            if "?" in txt or has_closeup:
                panel_candidates.extend(["hq_eyes_strip", "hq_pop_halftone", "hq_color_webtoon"])
            elif mot >= 22.0 or prog >= 0.65:
                panel_candidates.extend(["hq_dual_split", "hq_triple_cascade", "hq_pop_halftone", "hq_color_webtoon"])
            else:
                panel_candidates.extend(["hq_pop_halftone", "hq_color_webtoon", "hq_shonen_panel", "hq_dual_split", "hq_triple_cascade"])
        else:
            if "?" in txt or (has_closeup and mot < 24.0):
                panel_candidates.extend(["hq_eyes_strip", "hq_shonen_panel", "hq_noir_crimson"])
            if mot >= 25.0 and idx > 0:
                panel_candidates.extend(["hq_dual_split", "hq_triple_cascade", "hq_diagonal_impact", "hq_color_webtoon"])
            if sat >= 115.0 or chosen_feeling in ("fire", "golden_god", "electric", "blade_stream"):
                panel_candidates.extend(["hq_color_webtoon", "hq_diagonal_impact", "hq_dual_split", "hq_golden_eclipse"])
            if lum <= 82.0 or chosen_feeling in ("domain_dark", "blood_ink", "cursed_aura", "abyssal_void"):
                panel_candidates.extend(["hq_noir_crimson", "hq_shonen_panel", "hq_diagonal_impact", "hq_golden_eclipse"])
            if prog >= 0.75:
                panel_candidates.extend(["hq_dual_split", "hq_triple_cascade", "hq_color_webtoon", "hq_diagonal_impact"])

        p_seed = (int(lum) + int(sat) + len(t_up) * 7 + idx * 3) % len(allowed_panels)
        panel_candidates.extend(allowed_panels[p_seed:] + allowed_panels[:p_seed])
        panel_candidates = [p for p in panel_candidates if p in allowed_panels]
        if not panel_candidates:
            panel_candidates = list(allowed_panels)

        chosen_panel = panel_candidates[0]
        for cand_p in panel_candidates:
            if cand_p not in used_panels_recent[-p_win:]:
                chosen_panel = cand_p
                break

        # 3. Determina Layout de Posição da Legenda harmonizado com o Quadro HQ
        if chosen_panel in ("hq_eyes_strip", "hq_dual_split", "hq_triple_cascade"):
            layout_candidates = ["bottom", "lateral_right", "lateral_left", "center"]
        elif chosen_panel == "hq_diagonal_impact":
            layout_candidates = ["lateral_right", "lateral_left", "bottom", "center"]
        elif has_closeup:
            layout_candidates = ["bottom", "lateral_right", "lateral_left", "center"]
        else:
            layout_candidates = ["center", "bottom", "lateral_right", "lateral_left"]

        chosen_layout = layout_candidates[0]
        for cand_l in layout_candidates:
            if cand_l not in used_layouts_recent[-1:]:
                chosen_layout = cand_l
                break

        used_feelings_recent.append(chosen_feeling)
        used_panels_recent.append(chosen_panel)
        used_layouts_recent.append(chosen_layout)

        results.append({
            "feeling": chosen_feeling,
            "panel_style": chosen_panel,
            "pos_layout": chosen_layout,
        })

    return results


_HF_VLM_CACHE: Dict[str, Any] = {}


def _try_huggingface_vlm_inference(
    hf_model_id: str,
    prompt: str,
    pil_thumbs: List[Any],
    log_callback: Optional[Callable[[str], None]] = None
) -> Optional[Dict[str, Any]]:
    """
    Suporte nativo aos modelos Vision-Language do Hugging Face sugeridos pelo usuário:
      - Qwen/Qwen2-VL-2B-Instruct (ou 7B em 4-bit)
      - microsoft/Phi-3-vision-128k-instruct
      - vikhyatk/moondream2
      - llava-hf/llava-1.5-7b-hf
    Carrega sob demanda na GPU (8GB VRAM friendly) e retorna o JSON estruturado.
    """
    try:
        import torch
        from PIL import Image
        clean_id = hf_model_id.replace("hf:", "").strip()
        if log_callback:
            _emit_log(log_callback, f"Anime FX Pro: Consultando VLM Hugging Face '{clean_id}' na GPU...")

        if "moondream" in clean_id.lower():
            from transformers import AutoModelForCausalLM, AutoTokenizer
            if clean_id not in _HF_VLM_CACHE:
                tok = AutoTokenizer.from_pretrained(clean_id, trust_remote_code=True)
                mdl: Any = AutoModelForCausalLM.from_pretrained(
                    clean_id, trust_remote_code=True,
                    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
                )
                dev_str = "cuda" if torch.cuda.is_available() else "cpu"
                mdl = mdl.to(torch.device(dev_str))
                _HF_VLM_CACHE[clean_id] = (tok, mdl)
            tok, mdl = _HF_VLM_CACHE[clean_id]
            img = pil_thumbs[0] if pil_thumbs else Image.new("RGB", (384, 216), (0, 0, 0))
            enc_img = mdl.encode_image(img)
            ans = mdl.answer_question(enc_img, prompt, tok)
            m = re.search(r"\{.*\}", ans, re.DOTALL)
            if m:
                return json.loads(m.group(0))
    except Exception as e:
        if log_callback:
            _emit_log(log_callback, f"Anime FX Pro: Aviso HuggingFace VLM ({hf_model_id}): {e}")
    return None


def analyze_cutouts_with_vlm(
    cards_meta: List[Dict[str, Any]],
    video_path: Optional[str] = None,
    video_duration: float = 60.0,
    model: str = "qwen2.5vl:3b",
    timeout: float = 28.0,
    log_callback: Optional[Callable[[str], None]] = None,
    manga_theme: str = "geral"
) -> List[Dict[str, str]]:
    """
    Diretor de Arte Multimodal (Vision LLM + Telemetria Visual de Cena):
    Analisa os quadros reais do vídeo e o contexto dramático/clímax de cada frase para escolher
    dinamicamente para cada recorte:
      1. `feeling` (tipografia e animação de energia)
      2. `panel_style` (arquitetura do Quadro Editorial HQ)
      3. `pos_layout` (posicionamento seguro da legenda)
    """
    if not cards_meta:
        return []

    t_key = resolve_manga_theme_key(manga_theme)
    theme_cfg = MANGA_THEME_PROFILES.get(t_key, MANGA_THEME_PROFILES["geral"])
    allowed_panels: List[str] = list(theme_cfg["panels"])
    allowed_feelings: List[str] = list(theme_cfg["feelings"])

    telemetry, contact_b64, pil_thumbs = _extract_cutout_visual_context(video_path, cards_meta, video_duration)
    baseline_decisions = _compute_context_driven_design(cards_meta, telemetry, manga_theme=t_key)

    installed_models = ensure_ollama_running(log_callback=log_callback)
    resolved_model, is_vision = _resolve_best_ollama_model(model, installed_models)

    prompt = f"""Você é um Diretor de Arte de Mangá e Webtoon.
Analise os {len(cards_meta)} recortes abaixo (com suas frases, progresso narrativo e telemetria visual da cena) e defina um design ÚNICO, DINÂMICO e CONTEXTUAL para cada recorte.

🎭 TEMA ESCOLHIDO PELO USUÁRIO: {theme_cfg['label']}
{theme_cfg['prompt_hint']}

ARQUITETURAS DE QUADRO HQ (`panel_style`) PERMITIDAS PARA ESTE TEMA:
{json.dumps(allowed_panels, ensure_ascii=False)}

FEELINGS DE TIPOGRAFIA E ANIMAÇÃO (`feeling`) PERMITIDOS PARA ESTE TEMA:
{json.dumps(allowed_feelings, ensure_ascii=False)}

POSIÇÕES DE LEGENDA (`pos_layout`) DISPONÍVEIS:
- "bottom", "center", "lateral_right", "lateral_left"

⛔ REGRAS OBRIGATÓRIAS:
1. NUNCA use uma ordem fixa ou repetitiva! A escolha DEVE refletir o clímax, a emoção da fala e a cena visual de cada card.
2. PROIBIDO repetir o mesmo `feeling` ou o mesmo `panel_style` em recortes consecutivos!
3. Se houver 3 ou mais recortes, use pelo menos 3 arquiteturas diferentes de `panel_style`.

DADOS DOS RECORTES E TELEMETRIA DA CENA:
{json.dumps(telemetry, ensure_ascii=False, indent=2)}

Responda ESTRITAMENTE em formato JSON:
{{
  "cutouts": [
    {{"card_index": 1, "feeling": "...", "panel_style": "...", "pos_layout": "..."}},
    ...
  ]
}}"""

    parsed_cutouts = None

    if str(model).startswith("hf:"):
        hf_data = _try_huggingface_vlm_inference(model, prompt, pil_thumbs, log_callback=log_callback)
        if isinstance(hf_data, dict):
            parsed_cutouts = hf_data.get("cutouts")

    if not parsed_cutouts:
        try:
            msg_payload: Dict[str, Any] = {"role": "user", "content": prompt}
            if is_vision and contact_b64:
                msg_payload["images"] = [contact_b64]
                if log_callback:
                    _emit_log(log_callback, f"Anime FX Pro: Analisando {len(cards_meta)} cenas com Vision LLM '{resolved_model}' (Imagem + Contexto)...")
            else:
                if log_callback:
                    _emit_log(log_callback, f"Anime FX Pro: Analisando contexto e telemetria visual com LLM '{resolved_model}'...")

            resp = requests.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": resolved_model,
                    "messages": [msg_payload],
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.35}
                },
                timeout=timeout
            )
            if resp.status_code == 200:
                raw_content = resp.json().get("message", {}).get("content", "")
                data = json.loads(raw_content)
                if isinstance(data.get("cutouts"), list):
                    parsed_cutouts = data["cutouts"]
                elif isinstance(data.get("feelings"), list):
                    parsed_cutouts = [{"feeling": f} for f in data["feelings"]]
        except Exception as e:
            if log_callback:
                _emit_log(log_callback, f"Anime FX Pro: Aviso VLM/Ollama ({e}). Aplicando Diretor Visual Contextual de Cena.")

    if isinstance(parsed_cutouts, list) and len(parsed_cutouts) == len(cards_meta):
        final_decisions: List[Dict[str, str]] = []
        valid_feelings = set(allowed_feelings)
        valid_panels = set(allowed_panels)
        valid_layouts = {"bottom", "center", "lateral_right", "lateral_left"}

        f_win = max(1, len(allowed_feelings) - 1)
        p_win = max(1, len(allowed_panels) - 1)

        for i, item in enumerate(parsed_cutouts):
            if not isinstance(item, dict):
                item = {}
            f = item.get("feeling")
            p = item.get("panel_style")
            l = item.get("pos_layout")

            f_val = f if f in valid_feelings else baseline_decisions[i]["feeling"]
            p_val = p if p in valid_panels else baseline_decisions[i]["panel_style"]
            l_val = l if l in valid_layouts else baseline_decisions[i]["pos_layout"]

            recent_feelings = [d["feeling"] for d in final_decisions[-f_win:]]
            recent_panels = [d["panel_style"] for d in final_decisions[-p_win:]]
            recent_layouts = [d["pos_layout"] for d in final_decisions[-2:]]

            if f_val in recent_feelings:
                ctx_f = baseline_decisions[i]["feeling"]
                if ctx_f not in recent_feelings:
                    f_val = ctx_f
                else:
                    for cand_f in allowed_feelings:
                        if cand_f not in recent_feelings:
                            f_val = cand_f
                            break

            if "?" in str(cards_meta[i].get("text", "")) and "hq_eyes_strip" in valid_panels and "hq_eyes_strip" not in recent_panels:
                p_val = "hq_eyes_strip"
            elif p_val in recent_panels:
                ctx_p = baseline_decisions[i]["panel_style"]
                if ctx_p not in recent_panels:
                    p_val = ctx_p
                else:
                    for cand_p in allowed_panels:
                        if cand_p not in recent_panels:
                            p_val = cand_p
                            break

            if l_val in recent_layouts:
                ctx_l = baseline_decisions[i]["pos_layout"]
                if ctx_l not in recent_layouts:
                    l_val = ctx_l
                else:
                    for cand_l in ["bottom", "center", "lateral_right", "lateral_left"]:
                        if cand_l not in recent_layouts:
                            l_val = cand_l
                            break

            final_decisions.append({
                "feeling": f_val,
                "panel_style": p_val,
                "pos_layout": l_val,
            })

        if log_callback:
            summary_str = ", ".join(f"#{i+1}:{d['panel_style']}[{d['feeling']}]" for i, d in enumerate(final_decisions))
            _emit_log(log_callback, f"Anime FX Pro: Direção de Arte VLM concluída -> {summary_str}")
        return final_decisions

    if log_callback:
        summary_str = ", ".join(f"#{i+1}:{d['panel_style']}[{d['feeling']}]" for i, d in enumerate(baseline_decisions))
        _emit_log(log_callback, f"Anime FX Pro: Direção de Arte Contextual concluída -> {summary_str}")
    return baseline_decisions


def build_manual_manga_punchlines(
    items: List[Dict[str, Any]],
    video_duration: float,
    model: str = "qwen2.5vl:3b",
    log_callback: Optional[Callable[[str], None]] = None,
    video_path: Optional[str] = None,
    manga_theme: str = "geral"
) -> Optional[List[Dict[str, Any]]]:
    """
    Constrói os recortes de mangá com base EXCLUSIVA nas frases selecionadas
    pelo usuário na janela de revisão de legendas:
      - Analisa os quadros reais do vídeo + contexto dramático da fala via Vision LLM (Qwen2-VL / Moondream / Phi-3-Vision / LLaVA).
      - Nunca repete a mesma ordem fixa de design! Cada recorte recebe uma arquitetura de Quadro HQ
        (`hq_shonen_panel`, `hq_color_webtoon`, `hq_diagonal_impact`, `hq_eyes_strip`, `hq_dual_split`, `hq_noir_crimson`)
        e um `feeling` condizente com o clímax e a imagem da cena.
    """
    selected_items = [it for it in items if it.get("is_manga_cutout")]
    if not selected_items:
        return None

    item_to_orig_idx = {id(it): idx for idx, it in enumerate(items)}
    selected_with_idx = [(item_to_orig_idx.get(id(it), i), it) for i, it in enumerate(selected_items)]
    selected_with_idx.sort(key=lambda x: x[0])

    card_groups: List[List[Dict[str, Any]]] = []
    cur_group: List[Dict[str, Any]] = []
    prev_idx = -999

    for orig_idx, it in selected_with_idx:
        explicit_cid = it.get("manga_card_id")
        if explicit_cid is not None:
            found = False
            for grp in card_groups:
                if grp and grp[0].get("manga_card_id") == explicit_cid:
                    if len(grp) < 2:
                        grp.append(it)
                    found = True
                    break
            if not found:
                card_groups.append([it])
            continue

        if orig_idx == prev_idx + 1 and len(cur_group) == 1:
            cur_group.append(it)
            card_groups.append(cur_group)
            cur_group = []
            prev_idx = -999
        else:
            if cur_group:
                card_groups.append(cur_group)
            cur_group = [it]
            prev_idx = orig_idx

    if cur_group:
        card_groups.append(cur_group)

    if not card_groups:
        return None

    cards_meta = []
    for grp in card_groups:
        full_text = " ".join(g.get("text", "") for g in grp).strip()
        raw_st = float(grp[0].get("start", 0.0))
        raw_et = float(grp[-1].get("end", raw_st + 1.5))
        cards_meta.append({"text": full_text, "start": raw_st, "end": raw_et})

    t_key = resolve_manga_theme_key(manga_theme)
    theme_label = MANGA_THEME_PROFILES.get(t_key, MANGA_THEME_PROFILES["geral"])["label"]
    _emit_log(log_callback, f"Anime FX Pro: Analisando {len(card_groups)} cenas selecionadas [Tema: {theme_label}] com Vision LLM ({model})...")
    vlm_decisions = analyze_cutouts_with_vlm(
        cards_meta=cards_meta,
        video_path=video_path,
        video_duration=video_duration,
        model=model,
        log_callback=log_callback,
        manga_theme=t_key,
    )

    flat_words = _flatten_words(items)
    events: List[Dict[str, Any]] = []

    for idx, grp in enumerate(card_groups):
        if len(grp) >= 2:
            clean_l1 = re.sub(r"[?!]", "", grp[0].get("text", "")).strip().upper()
            raw_l2 = grp[1].get("text", "").strip()
            sym = "?" if "?" in raw_l2 or "?" in grp[0].get("text", "") else "!"
            clean_l2 = re.sub(r"[?!]", "", raw_l2).strip().upper()
            if not clean_l2.endswith(sym):
                clean_l2 = f"{clean_l2}{sym}"
            raw_st = float(grp[0]["start"])
            raw_et = float(grp[1]["end"])
        else:
            full = grp[0].get("text", "").strip()
            sym = "?" if "?" in full else "!"
            clean_full = re.sub(r"[?!]", "", full).strip().upper()
            toks = clean_full.split()
            if len(toks) > 1:
                mid = len(toks) // 2
                clean_l1 = " ".join(toks[:mid])
                clean_l2 = " ".join(toks[mid:])
            else:
                clean_l1 = ""
                clean_l2 = clean_full
            if not clean_l2.endswith(sym):
                clean_l2 = f"{clean_l2}{sym}"
            raw_st = float(grp[0]["start"])
            raw_et = float(grp[0]["end"])

        matching_word_indices = [
            i for i, w in enumerate(flat_words)
            if raw_st - 0.15 <= float(w["start"]) <= raw_et + 0.15
        ]
        if matching_word_indices:
            first_k = matching_word_indices[0]
            last_k = matching_word_indices[-1]
            st, et = _card_timing(flat_words, first_k, last_k, video_duration)
            sp_st = round(flat_words[first_k]["start"], 2)
            sp_et = round(flat_words[last_k]["end"], 2)
        else:
            st = max(0.0, raw_st - 0.04)
            et = min(video_duration - 0.05, max(st + 1.10, raw_et + 0.20))
            sp_st = round(raw_st, 2)
            sp_et = round(raw_et, 2)

        # Respeita escolha manual explícita do usuário apenas se ele trocou de "auto" para um feeling específico
        explicit_f = None
        for g in grp:
            mf = g.get("manga_feeling")
            if mf and mf != "auto":
                explicit_f = mf
                break

        dec = vlm_decisions[idx] if idx < len(vlm_decisions) else {
            "feeling": "domain_dark",
            "panel_style": "hq_shonen_panel",
            "pos_layout": "bottom",
        }
        feeling = explicit_f or dec["feeling"]
        panel_style = dec["panel_style"]
        pos_layout = dec["pos_layout"]

        events.append({
            "sentence_idx": idx,
            "score": 100.0,
            "start": st,
            "end": et,
            "speech_start": sp_st,
            "speech_end": sp_et,
            "text": cards_meta[idx]["text"],
            "punch_text": f"{clean_l1} {clean_l2}".strip(),
            "line1": clean_l1,
            "line2": clean_l2,
            "symbol": sym,
            "event_type": panel_style,
            "panel_style": panel_style,
            "item_idx": -1,
            "text_style": feeling,
            "pos_layout": pos_layout,
        })

    events.sort(key=lambda x: x["start"])
    _emit_log(log_callback, f"Anime FX Pro: {len(events)} Quadros Editoriais HQ configurados dinamicamente conforme cena e clímax!")
    for idx, ev in enumerate(events):
        gap_str = f" [Intervalo: {ev['start'] - events[idx-1]['end']:.1f}s]" if idx > 0 else " [Abertura]"
        _emit_log(log_callback, f"   -> Quadro HQ ({idx+1}/{len(events)}): '{ev['punch_text']}' [Painel: {ev['panel_style']} | Feeling: {ev['text_style']} | Posição: {ev['pos_layout']}] em {ev['start']}s-{ev['end']}s{gap_str}")

    return events


def analyze_transcript_for_anime_fx(
    items: List[Dict[str, Any]],
    video_duration: float = 60.0,
    log_callback: Optional[Callable[[str], None]] = None,
    use_local_ai: bool = True,
    local_ai_model: str = "qwen2.5vl:3b",
    video_path: Optional[str] = None,
    manga_theme: str = "geral"
) -> Dict[str, Any]:
    """
    Analisa os chunks de transcrição e retorna os eventos programados de FX de Elite:
    - Prioridade 0: Seleção Manual do Usuário enriquecida por Vision LLM (analisando os quadros reais do vídeo).
    - Prioridade 1: Curadoria Semântica & Visual via IA Local (Ollama Vision / Qwen2-VL / Moondream / Phi-3-Vision).
    - Prioridade 2 (Fallback): Analisador heurístico determinístico com Diretor Visual Contextual.
    """
    fx_schedule: Dict[str, Any] = {
        "white_flashes": [],
        "negative_flashes": [],
        "anime_symbols": [],
        "manga_climax": None,
        "manga_events": [],
        "styled_items": []
    }

    if not items:
        return fx_schedule

    # Meta de recortes automáticos: vídeos > 40s geram em média 8 a 9 quadros de mangá!
    if video_duration < 18.0:
        target_count = 3
    elif video_duration < 28.0:
        target_count = 5
    elif video_duration < 40.0:
        target_count = 6
    elif video_duration < 52.0:
        target_count = 8
    elif video_duration <= 72.0:
        target_count = 9
    else:
        target_count = min(12, max(9, int(round(video_duration / 6.5))))

    t_key = resolve_manga_theme_key(manga_theme)
    theme_label = MANGA_THEME_PROFILES.get(t_key, MANGA_THEME_PROFILES["geral"])["label"]

    # 0. Prioridade Absoluta: Seleção Manual do Usuário (se configurada na janela de revisão de legendas)
    has_manual = any(it.get("is_manga_cutout") for it in items)
    if has_manual:
        _emit_log(log_callback, f"Anime FX Pro: Modo Manual Ativo [Tema: {theme_label}]! Analisando quadros e contexto para design dinâmico...")
        manual_events = build_manual_manga_punchlines(
            items, video_duration, model=local_ai_model,
            log_callback=log_callback, video_path=video_path,
            manga_theme=t_key
        )
        if manual_events:
            fx_schedule["manga_events"] = manual_events
            fx_schedule["manga_climax"] = manual_events[0]
            return fx_schedule

    # 1. Tenta Curadoria Inteligente via IA Local (se ativada)
    ollama_events = None
    if use_local_ai:
        ensure_ollama_running(log_callback=log_callback)
        ollama_events = curate_manga_punchlines_with_ollama(
            items, video_duration, target_count=target_count,
            model=local_ai_model, timeout=30.0, log_callback=log_callback,
            manga_theme=t_key
        )
    else:
        _emit_log(log_callback, "Anime FX Pro: Modo Heurístico Ativo (IA Local desativada nas opções do Studio)...")

    if ollama_events and len(ollama_events) >= max(2, target_count - 1):
        manga_events = ollama_events
    else:
        if use_local_ai:
            _emit_log(log_callback, "Anime FX Pro: Alternando para Curadoria Heurística Determinística com âncoras canônicas...")
        windows = [(0.0, min(6.0, video_duration - 1.5))]
        if target_count > 1 and video_duration > 8.0:
            rem_start = 7.0
            rem_end = max(rem_start + 4.0, video_duration - 2.5)
            rem_span = rem_end - rem_start
            step = rem_span / (target_count - 1)
            for i in range(target_count - 1):
                w_s = rem_start + i * step
                w_e = min(rem_end, w_s + step)
                windows.append((round(w_s, 2), round(w_e, 2)))

        candidates = build_spoken_punchline_candidates(items, video_duration)
        manga_events = []
        used_sentences = set()
        min_gap = max(1.4, (video_duration / max(1, target_count)) * 0.22)

        def _pick(pool: List[Dict[str, Any]], w_mid: float, hook: bool) -> Optional[Dict[str, Any]]:
            best, best_sc = None, -1e9
            for c in pool:
                sc = c["score"] - 0.15 * abs(c["speech_start"] - w_mid)
                if hook and c["speech_start"] <= 4.5:
                    sc += 15.0
                if sc > best_sc:
                    best, best_sc = c, sc
            return best

        for w_idx, (w_start, w_end) in enumerate(windows):
            prev_end = manga_events[-1]["end"] if manga_events else -1.0
            free = [c for c in candidates if c["sentence_idx"] not in used_sentences and c["start"] >= prev_end + min_gap]
            if w_idx == 0:
                pool = [c for c in free if c["speech_start"] <= 5.0]
            else:
                pool = [c for c in free if (w_start - 2.0) <= c["speech_start"] <= (w_end + 2.0)]
                if not pool:
                    pool = [c for c in free if c["speech_start"] <= (w_end + 6.0)]
            chosen = _pick(pool, (w_start + w_end) / 2.0, hook=(w_idx == 0))
            if chosen is None:
                continue
            used_sentences.add(chosen["sentence_idx"])
            ev = dict(chosen)
            ev["item_idx"] = -1
            manga_events.append(ev)

        # Passagem complementar: garante atingir a meta de 8-9 recortes quando houver falas suficientes
        if len(manga_events) < target_count and len(candidates) > len(manga_events):
            relaxed_gap = 0.90
            for c in sorted(candidates, key=lambda x: x["score"], reverse=True):
                if len(manga_events) >= target_count:
                    break
                if c["sentence_idx"] in used_sentences:
                    continue
                collides = any(
                    not (c["end"] + relaxed_gap <= e["start"] or c["start"] >= e["end"] + relaxed_gap)
                    for e in manga_events
                )
                if not collides:
                    used_sentences.add(c["sentence_idx"])
                    ev = dict(c)
                    ev["item_idx"] = -1
                    manga_events.append(ev)
                    manga_events.sort(key=lambda x: x["start"])

    # Passa todos os eventos automáticos pelo Diretor de Arte VLM / Contextual para atribuir panel_style + feeling + pos_layout dinâmicos
    if manga_events:
        auto_meta = [
            {"text": ev.get("punch_text") or ev.get("text", ""), "start": ev["start"], "end": ev["end"]}
            for ev in manga_events
        ]
        vlm_auto = analyze_cutouts_with_vlm(
            cards_meta=auto_meta,
            video_path=video_path,
            video_duration=video_duration,
            model=local_ai_model,
            log_callback=log_callback if use_local_ai else None,
            manga_theme=t_key,
        )
        for i, ev in enumerate(manga_events):
            if i < len(vlm_auto):
                ev["panel_style"] = vlm_auto[i]["panel_style"]
                ev["event_type"] = vlm_auto[i]["panel_style"]
                ev["text_style"] = vlm_auto[i]["feeling"]
                ev["pos_layout"] = vlm_auto[i]["pos_layout"]

        fx_schedule["manga_events"] = manga_events
        fx_schedule["manga_climax"] = manga_events[0]

    # 2. Identificar Símbolo 3D de Anime (Ex: '?' em perguntas e mistérios)
    for idx, it in enumerate(items):
        text = str(it.get("text", "")).strip()
        start = float(it.get("start", 0.0))
        end = float(it.get("end", 0.0))
        # Não sobrepor com a cena de mangá
        if fx_schedule["manga_climax"]:
            m_s = fx_schedule["manga_climax"]["start"]
            m_e = fx_schedule["manga_climax"]["end"]
            if abs(start - m_s) < 2.0 or abs(end - m_e) < 2.0:
                continue

        if "?" in text or any(qw in text.lower() for qw in QUESTION_WORDS):
            fx_schedule["anime_symbols"].append({
                "start": start,
                "end": end,
                "duration": min(1.8, end - start),
                "symbol": "?",
                "item_idx": idx
            })
            if len(fx_schedule["anime_symbols"]) >= 2:
                break

    return fx_schedule
