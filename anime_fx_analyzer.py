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


def curate_manga_punchlines_with_ollama(
    items: List[Dict[str, Any]],
    video_duration: float,
    target_count: int = 6,
    model: str = "qwen2.5:7b",
    timeout: float = 30.0,
    log_callback: Optional[Callable[[str], None]] = None,
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

    prompt = f"""Você é um Diretor de Anime e Editor Chefe de Mangá Shonen.
Seu objetivo é criar um ritmo cinematográfico equilibrado ao longo de todo o vídeo de {video_duration:.1f}s.
O vídeo foi dividido em {target_count} Setores Temporais ({sectors[0][0]}s a {sectors[-1][1]}s).

Você DEVE selecionar EXATAMENTE 1 momento de impacto por Setor (totalizando exatamente {target_count} momentos).
NUNCA aglomere momentos no mesmo setor deixando outros setores vazios. Cada setor DEVE ter seu momento!

REGRAS OBRIGATÓRIAS:
1. EXATAMENTE 1 MOMENTO POR SETOR (Distribuídos ao longo de todo o vídeo):
   - 1 momento do Setor 1 (Abertura / Hook: 0s-{sectors[0][1]}s)
   - 1 momento do Setor 2
   - 1 momento do Setor 3
   - 1 momento do Setor 4
   - 1 momento do Setor 5
   - 1 momento do Setor 6 (Desfecho / Clímax final)
2. PUNCHLINE CURTA: Extraia 1 a 4 palavras por momento. NUNCA selecione frases longas.
3. PALAVRAS REAIS: Use EXCLUSIVAMENTE palavras faladas no áudio da oração indicada pelo "id". NUNCA invente palavras. NUNCA use palavras de exemplos anteriores se elas não existirem na transcrição deste vídeo.
4. DIVISÃO EM 2 LINHAS: Divida em "line1" e "line2" com cadência dramática de mangá (ex: L1: "PALAVRA 1", L2: "PALAVRA 2!"). Se for apenas 1 palavra, line1 fica vazio e line2 recebe a palavra.
5. FEELING DA CENA:
   - "slam": Choque, perigo, corte, impacto físico imediato.
   - "electric": Suspense tenso, questionamento, dúvida.
   - "golden_god": Poder supremo, transformação, revelação ou vitória.
   - "fire": Raiva, fúria, ataque, grito de batalha.
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


            feeling = m.get("feeling", "slam")
            if feeling not in ("slam", "golden_god", "electric", "fire", "offset_comic", "manga_bubble", "shonen_badge", "typewriter", "comedy"):
                feeling = "slam"

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

        # Pacing Guard: Garante espacamento ritmico equilibrado (sem recortes colados)
        min_pacing_gap = max(3.5, (video_duration / target_count) * 0.40)
        spaced_events = []
        for ev in events:
            if not spaced_events:
                spaced_events.append(ev)
                continue
            prev_ev = spaced_events[-1]
            if ev["start"] >= prev_ev["end"] + min_pacing_gap:
                spaced_events.append(ev)

        # Se houver setores vazios (gap > min_pacing_gap * 2.2), preenche lacunas com o melhor candidato
        if len(spaced_events) < target_count:
            candidates = build_spoken_punchline_candidates(items, video_duration)
            used_sentence_ids = {e["sentence_idx"] for e in spaced_events}
            for sec_idx, (sec_st, sec_et) in enumerate(sectors):
                if len(spaced_events) >= target_count:
                    break
                has_ev = any(sec_st - 1.5 <= e["start"] <= sec_et + 1.5 for e in spaced_events)
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
    model: str = "qwen2.5:7b",
    timeout: float = 15.0,
    log_callback: Optional[Callable[[str], None]] = None
) -> List[str]:
    """Classifica o feeling emocional de frases manuais usando IA Local Ollama ou heurística rápida."""
    default_feelings = []
    for txt in cards_text:
        low = txt.lower()
        if "?" in txt:
            f = "electric"
        elif any(w in low for w in ["deus", "mundo", "poder", "ouro", "glória", "supremo"]):
            f = "golden_god"
        elif any(w in low for w in ["morte", "matar", "sangue", "corte", "destruir", "morrer"]):
            f = "slam"
        elif any(w in low for w in ["justiça", "fogo", "luta", "combate", "fúria", "atacar"]):
            f = "fire"
        elif any(w in low for w in ["não", "nunca", "acha", "quem", "olhe", "veja"]):
            f = "offset_comic"
        else:
            f = "slam"
        default_feelings.append(f)

    if not cards_text:
        return default_feelings

    try:
        prompt = f"""Você é um Diretor de Anime Shonen. Classifique o feeling visual de mangá para cada uma das {len(cards_text)} frases abaixo.
Opções permitidas: "slam", "electric", "golden_god", "fire", "offset_comic", "manga_bubble".

Frases:
{json.dumps(cards_text, ensure_ascii=False, indent=2)}

Responda ESTRITAMENTE em formato JSON com uma lista "feelings":
{{"feelings": ["slam", "electric"]}}
"""
        resp = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1}
            },
            timeout=timeout
        )
        if resp.status_code == 200:
            data = json.loads(resp.json().get("message", {}).get("content", ""))
            f_list = data.get("feelings")
            if isinstance(f_list, list) and len(f_list) == len(cards_text):
                valid_opts = {"slam", "electric", "golden_god", "fire", "offset_comic", "manga_bubble"}
                return [f if f in valid_opts else default_feelings[i] for i, f in enumerate(f_list)]
    except Exception:
        pass

    return default_feelings


def build_manual_manga_punchlines(
    items: List[Dict[str, Any]],
    video_duration: float,
    model: str = "qwen2.5:7b",
    log_callback: Optional[Callable[[str], None]] = None
) -> Optional[List[Dict[str, Any]]]:
    """
    Constrói os recortes de mangá com base EXCLUSIVA nas frases selecionadas
    pelo usuário na janela de revisão de legendas.
    - Se o usuário marcou duas frases consecutivas, elas viram Linha 1 e Linha 2.
    - Se marcou uma frase isolada, divide em 2 linhas ou centraliza na Linha 2.
    - Classifica os feelings visuais via Ollama com base no texto escolhido.
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

    cards_summary_text = []
    for grp in card_groups:
        full_text = " ".join(g.get("text", "") for g in grp).strip()
        cards_summary_text.append(full_text)

    _emit_log(log_callback, f"Anime FX Pro: Classificando feelings dinâmicos para {len(card_groups)} recortes manuais...")
    feelings = classify_manga_feelings_with_ollama(cards_summary_text, model=model, log_callback=log_callback)

    flat_words = _flatten_words(items)
    events: List[Dict[str, Any]] = []
    layout_cycle = ["center", "bottom", "lateral_right", "lateral_left", "center", "bottom"]

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

        feeling = feelings[idx] if idx < len(feelings) else "slam"

        events.append({
            "sentence_idx": idx,
            "score": 100.0,
            "start": st,
            "end": et,
            "speech_start": sp_st,
            "speech_end": sp_et,
            "text": cards_summary_text[idx],
            "punch_text": f"{clean_l1} {clean_l2}".strip(),
            "line1": clean_l1,
            "line2": clean_l2,
            "symbol": sym,
            "event_type": "manga_eyes_panel" if sym == "?" else "scene_manga_panel",
            "item_idx": -1,
            "text_style": feeling,
            "pos_layout": layout_cycle[idx % len(layout_cycle)]
        })

    events.sort(key=lambda x: x["start"])
    _emit_log(log_callback, f"Anime FX Pro: {len(events)} recortes manuais configurados com sucesso!")
    for idx, ev in enumerate(events):
        gap_str = f" [Intervalo: {ev['start'] - events[idx-1]['end']:.1f}s]" if idx > 0 else " [Abertura]"
        _emit_log(log_callback, f"   -> Recorte Manual ({idx+1}/{len(events)}): '{ev['punch_text']}' [Estilo: {ev['text_style']}] no momento {ev['start']}s-{ev['end']}s{gap_str}")

    return events


def analyze_transcript_for_anime_fx(
    items: List[Dict[str, Any]],
    video_duration: float = 60.0,
    log_callback: Optional[Callable[[str], None]] = None,
    use_local_ai: bool = True,
    local_ai_model: str = "qwen2.5:7b"
) -> Dict[str, Any]:
    """
    Analisa os chunks de transcrição e retorna os eventos programados de FX de Elite:
    - Prioridade 1: Curadoria Semântica de Clímax via IA Local (Ollama Qwen 2.5 7B na GPU RTX 5060).
    - Prioridade 2 (Fallback ou Seleção Manual): Analisador heurístico determinístico com âncoras canônicas.
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

    if video_duration < 22.0:
        target_count = 2
    elif video_duration < 36.0:
        target_count = 3
    elif video_duration < 48.0:
        target_count = 4
    elif video_duration < 65.0:
        target_count = 6
    else:
        target_count = min(10, max(6, int(video_duration / 8.8)))

    # Layouts 100% seguros: Central e Inferior (NUNCA top/split -> ZERO colisão com a watermark @ANIMAX_97)
    layout_cycle = ["center", "bottom", "lateral_right", "lateral_left", "center", "bottom"]
    style_cycle = ["shonen_badge", "manga_bubble", "fire", "electric", "golden_god", "offset_comic", "slam", "typewriter"]

    # 0. Prioridade Absoluta: Seleção Manual do Usuário (se configurada na janela de revisão de legendas)
    has_manual = any(it.get("is_manga_cutout") for it in items)
    if has_manual:
        _emit_log(log_callback, "Anime FX Pro: Modo Manual Ativo! Utilizando frases marcadas pelo usuário...")
        manual_events = build_manual_manga_punchlines(items, video_duration, model=local_ai_model, log_callback=log_callback)
        if manual_events:
            fx_schedule["manga_events"] = manual_events
            fx_schedule["manga_climax"] = manual_events[0]
            return fx_schedule

    # 1. Tenta Curadoria Inteligente via IA Local (se ativada)
    ollama_events = None
    if use_local_ai:
        ollama_events = curate_manga_punchlines_with_ollama(
            items, video_duration, target_count=target_count,
            model=local_ai_model, timeout=30.0, log_callback=log_callback
        )
    else:
        _emit_log(log_callback, "Anime FX Pro: Modo Heurístico Ativo (IA Local desativada nas opções do Studio)...")

    if ollama_events and len(ollama_events) >= max(2, target_count - 1):
        for i, ev in enumerate(ollama_events):
            ev["pos_layout"] = layout_cycle[i % len(layout_cycle)]
        manga_events = ollama_events
    else:
        if use_local_ai:
            _emit_log(log_callback, "Anime FX Pro: Alternando para Curadoria Heurística Determinística com âncoras canônicas...")
        # Fallback Determinístico Heurístico com Âncoras Canônicas
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
        min_gap = max(3.5, (video_duration / target_count) * 0.40)

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
            ev["event_type"] = "manga_eyes_panel" if ev["symbol"] == "?" else "scene_manga_panel"
            ev["item_idx"] = -1
            manga_events.append(ev)

        for i, ev in enumerate(manga_events):
            ev["pos_layout"] = layout_cycle[i % len(layout_cycle)]
            style = style_cycle[i % len(style_cycle)]
            if ev["symbol"] == "?" and style in ("fire", "slam"):
                style = "electric"
            ev["text_style"] = style

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
