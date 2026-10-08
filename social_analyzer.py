"""
Social Media Video Analyzer - Core Intelligence Module
Provides viral intelligence, algorithm optimization, and copywriting for Instagram Reels and YouTube Shorts.
"""

import os
import sys
import json
import re
from typing import Optional, Dict, Any, Callable
from pathlib import Path

from director_ai import (
    call_ai_text,
    extract_audio,
    transcribe_video_audio,
)
from metadata_enricher import get_enriched_context_for_prompt

COPY_TEMPLATES = {
    "Padrão": "",
    "Anime / Geek Épico": "Tom épico e empolgante para público otaku/geek, destacando momentos icônicos, falas de impacto e poder dos personagens.",
    "Dorama / Emocional": "Conexão emocional profunda, foco na química entre personagens, momentos de tensão dramática e romance.",
    "Curiosidade / Mistério": "Gera curiosidade irresistível com perguntas intrigantes no início e promessa de revelação chocante.",
    "CTA Agressivo / Engajamento": "Foco em bater recordes de comentários e compartilhamentos via DM, provocando o público com opiniões polarizadoras.",
    "Humor / Relatable": "Tom descontraído de meme e identificação imediata ('Acontece com todo mundo', 'Quem nunca fez isso?').",
}

INSTAGRAM_CONTEXT = """
Você é o maior especialista mundial em conteúdo viral para o Instagram (Reels, Feed e Stories). Você possui conhecimento profundo sobre:
1. ALGORITMO DO INSTAGRAM:
   - O Instagram Reels prioriza Watch Time, Shares (Envios por DM são fortíssimos), Saves (Salvamentos) e Replays.
   - Vídeos originais (sem marca d'água de outras redes) têm prioridade.
   - O algoritmo testa o vídeo com seus seguidores ativos primeiro, depois entrega para a aba Explorar e Reels feed.
   - Estética e qualidade visual importam muito mais no Instagram do que no TikTok.
   - Uso de áudios em alta (trending audios) é um forte indicativo de distribuição.
2. PADRÕES VIRAIS COMPROVADOS NO INSTAGRAM:
   - HOOK VISUAL FORTE: Os primeiros 2 segundos devem prender o olho (texto chamativo, qualidade alta, ação imediata).
   - LOOP INVISÍVEL: O final do Reel conecta com o início perfeitamente.
   - VALOR DE SALVAMENTO: Conteúdo educativo, tutoriais ou listas que a pessoa precisa salvar para ver depois.
   - COMPARTILHAMENTO: Conteúdo "relatable" (identificação) ou humor que faça a pessoa querer mandar para um amigo na DM.
3. COPYWRITING VIRAL E LEGENDA (CAPTION):
   - A primeira linha da legenda é crucial (deve gerar curiosidade antes do "ver mais").
   - Texto no vídeo (overlay) é obrigatório, pois muitos assistem sem som.
   - CTAs (Call to Actions) para engajamento: "Mande para aquele amigo que...", "Salve para não esquecer", "Comente X para receber o link".
4. HASHTAGS E ESTRATÉGIAS ADICIONAIS:
   - 3 a 5 hashtags altamente relevantes (o Instagram mudou e não recomenda mais 30 hashtags).
   - Uso de tópicos/tópicos de marcação de conteúdo (topics).
"""

DORAMA_INSTAGRAM_CONTEXT = """
Você é o maior especialista mundial em conteúdo viral de Doramas e K-Dramas para o Instagram Reels.
Você conhece profundamente a comunidade 'dorameira', o algoritmo do Reels e as dinâmicas de engajamento do Instagram:
1. ALGORITMO DO INSTAGRAM REELS PARA DORAMAS:
   - Envios por Direct (DM): Fãs de dorama compartilham massivamente cenas marcantes com amigas ("amiga olha essa cena", "precisa assistir esse dorama"). Esse é o sinal de maior peso no Reels.
   - Salvamentos (Saves): Recomendações de doramas ("onde assistir", "melhores doramas de romance") geram altíssima taxa de salvamento.
   - Watch Time & Replays: Cenas com química palpável, olhares intensos e beijos são assistidas repetidas vezes.
2. ESTRATÉGIA DE GANCHOS (0-2s) PARA DORAMAS:
   - Gancho com dilema ou choque emocional: "O dia em que ele percebeu que nunca mais veria ela...", "A cena que fez todo mundo chorar em 2024".
   - Frases provocativas na tela: Texto grande e legível no primeiro segundo para prender o olhar antes de passar.
   - OSTs e Áudios em Alta: Destaque a importância da música de fundo (trilhas sonoras e baladas coreanas famosas).
3. LEGENDAS E COPYWRITING VIRAL:
   - Conexão emocional genuína, perguntando a opinião da audiência ("Você perdoaria essa atitude?", "Qual nota você dá pra esse casal?").
   - Hashtags estratégicas: 3 a 5 tags essenciais como #dorama #kdrama #doramascoreanos #seriescoreanas e a hashtag oficial da obra.
"""

YOUTUBE_SHORTS_CONTEXT = """
Você é o maior especialista mundial em conteúdo viral para o YouTube Shorts. Você possui conhecimento profundo sobre:
1. ALGORITMO DO YOUTUBE SHORTS:
   - O Shorts prioriza a Retenção de Público (Audience Retention) e a Taxa de Visualização vs. Rejeição (Viewed vs Swiped Away rate, idealmente acima de 70-80%).
   - Vídeos que têm mais de 100% de retenção (por conta de replays/loops) são fortemente impulsionados.
   - O YouTube Shorts depende muito do feed de Shorts, mas também se beneficia de tráfego de pesquisa (SEO do YouTube).
   - O título é o elemento visual e metadado mais importante do Shorts.
2. PADRÕES VIRAIS COMPROVADOS NO SHORTS:
   - GANCHO INICIAL CRUCIAL: Os primeiros 1 a 3 segundos devem impedir o usuário de passar (swipe) o vídeo.
   - LOOP ESTRATÉGICO: Conectar perfeitamente o áudio e o visual do final do vídeo com o começo.
   - EDIÇÃO RÁPIDA: Cortes dinâmicos, textos na tela (legenda gerada ou texto de destaque), efeitos sonoros (SFX) e quebras de padrão frequentes.
3. SEO, TÍTULO E DESCRIÇÃO:
   - Títulos curtos e impactantes (com menos de 60-70 caracteres para não serem cortados na tela do celular), com uso estratégico de letras maiúsculas e emojis.
   - Uso obrigatório de hashtags relevantes, incluindo `#shorts` ou tags de nicho (ex: `#anime`, `#animeedit`).
   - Descrições contendo palavras-chave e chamadas para ação (CTAs) de inscrição (Subscribe) ou engajamento.
   - Tags/Palavras-chave focadas na pesquisa do YouTube.
"""

DORAMA_YOUTUBE_CONTEXT = """
Você é o maior especialista mundial em conteúdo viral de Doramas (K-Drama, C-Drama, J-Drama, Thai Drama) para o YouTube Shorts.
Você conhece TODOS os doramas de sucesso (da Netflix, Viki, tvN, JTBC, SBS), seus tropos narrativos e a psicologia do público dorameiro.

1. ALGORITMO DO YOUTUBE SHORTS PARA DORAMAS:
   - Retenção Emocional: Dorameiras assistem vídeos até o fim quando há química forte, tensão romântica, indignação ou choro.
   - Pinned Comment Engagement: O maior segredo viral de Doramas no Shorts é o Comentário Fixado com o Nome do Dorama + Onde Assistir + Uma Pergunta Provocadora ("Você perdoaria?"). Isso gera centenas de comentários e impulsiona o algoritmo.
   - Compartilhamento & Replay: Cenas de término, primeiro beijo ou vingança geram taxas de visualização vs. rejeição acima de 85%.

2. PADRÕES E TROPAS VIRAIS DE DORAMAS:
   - ROMANCE & QUÍMICA: Primeiro beijo, declaração tímida, toque acidental de mãos, olhar fixo, "vou cuidar de você".
   - CEO ARROGANTE & PROTETOR: O chefe frio que perde o controle e defende a mocinha na frente de todo mundo.
   - VINGANÇA & SUPERAÇÃO: A protagonista humilhada pela família rica ou vilã que dá a volta por cima de salto alto.
   - CHORO & SEPARAÇÃO: Despedida dolorosa no aeroporto/chuva, quebra de promessa, sacrifício por amor.
   - SEGREDO & IDENTIDADE: Quando descobrem quem ele/ela realmente é (herdeiro secreto, policial disfarçado, etc.).
"""


def _repair_truncated_json(text: str) -> Optional[Dict[str, Any]]:
    """
    Tenta reparar e fechar de forma resiliente JSONs truncados ou cortados pela IA
    (quando atinge limite de tokens ou falha de conexão).
    """
    if not text or not isinstance(text, str):
        return None
    s = text.strip()
    first_brace = s.find("{")
    if first_brace == -1:
        return None
    s = s[first_brace:]

    # 1. Tentar parse direto
    try:
        return json.loads(s)
    except Exception:
        pass

    # 2. Tentar cortar a partir da última chave fechada
    last_brace = s.rfind("}")
    if last_brace != -1:
        try:
            return json.loads(s[:last_brace + 1])
        except Exception:
            pass

    # 3. Balanceamento de aspas e colchetes/chaves
    stack = []
    in_string = False
    escape = False
    clean_chars = []

    for ch in s:
        if escape:
            clean_chars.append(ch)
            escape = False
            continue
        if ch == '\\':
            clean_chars.append(ch)
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            clean_chars.append(ch)
            continue
        clean_chars.append(ch)
        if not in_string:
            if ch in ('{', '['):
                stack.append('}' if ch == '{' else ']')
            elif ch in ('}', ']'):
                if stack and stack[-1] == ch:
                    stack.pop()

    repaired = "".join(clean_chars)
    if in_string:
        repaired += '"'

    # Remove vírgulas órfãs no final ou chaves incompletas como `,"campo":` ou `,"campo"`
    repaired = re.sub(r',\s*$', '', repaired)
    repaired = re.sub(r',\s*"(?:[^"\\]|\\.)*"\s*:\s*$', '', repaired)
    repaired = re.sub(r',\s*"(?:[^"\\]|\\.)*"\s*$', '', repaired)
    repaired = re.sub(r':\s*$', ': null', repaired)

    # Fecha colchetes e chaves pendentes
    closing = "".join(reversed(stack))
    try:
        res = json.loads(repaired + closing)
        if isinstance(res, dict) and len(res) > 0:
            return res
    except Exception:
        pass

    # 4. Backtracking progressivo até o último nó estrutural válido
    cur = repaired
    for _ in range(25):
        last_cut = max(cur.rfind(','), cur.rfind('}'), cur.rfind(']'))
        if last_cut <= 0:
            break
        cur = cur[:last_cut].rstrip()
        if cur.endswith(','):
            cur = cur[:-1].rstrip()

        stk = []
        in_s = False
        esc = False
        for c in cur:
            if esc:
                esc = False
                continue
            if c == '\\':
                esc = True
                continue
            if c == '"':
                in_s = not in_s
                continue
            if not in_s:
                if c in ('{', '['):
                    stk.append('}' if c == '{' else ']')
                elif c in ('}', ']'):
                    if stk and stk[-1] == c:
                        stk.pop()

        attempt = cur + ('"' if in_s else "") + "".join(reversed(stk))
        try:
            res = json.loads(attempt)
            if isinstance(res, dict) and len(res) > 0:
                return res
        except Exception:
            continue

    return None


def _parse_ai_json(text: str) -> Dict[str, Any]:
    """Parse JSON from AI response robustly with auto-repair for truncated output."""
    if not text:
        return {}
    clean = text.strip()
    if "```json" in clean:
        clean = clean.split("```json", 1)[1]
        if "```" in clean:
            clean = clean.split("```", 1)[0]
    elif "```" in clean:
        clean = clean.split("```", 1)[1]
        if "```" in clean:
            clean = clean.split("```", 1)[0]
    clean = clean.strip()

    try:
        return json.loads(clean)
    except Exception:
        repaired = _repair_truncated_json(clean)
        if repaired and isinstance(repaired, dict):
            return repaired

        match = re.search(r'\{.*\}', clean, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                repaired = _repair_truncated_json(match.group(0))
                if repaired and isinstance(repaired, dict):
                    return repaired

    return {"raw_response": text, "parse_error": True}


def build_instagram_analysis_prompt(
    context: str = "",
    work_name: str = "",
    category: str = "anime",
    enriched_context: str = "",
    transcript: str = "",
    language_en: bool = False,
    language: str = "pt"
) -> str:
    """Build prompt for Instagram Reels analysis with rich pop culture / anime / dorama API grounding."""
    cat_lower = (category or "").strip().lower()
    is_dorama = "dorama" in cat_lower or "kdrama" in cat_lower or "k-drama" in cat_lower
    base_context = DORAMA_INSTAGRAM_CONTEXT if is_dorama else INSTAGRAM_CONTEXT

    ctx_parts = []
    if work_name:
        ctx_parts.append(f"Obra/Anime/Dorama/Série: {work_name}")
    if context:
        ctx_parts.append(f"Contexto do criador: {context}")
    if enriched_context:
        ctx_parts.append(enriched_context)

    ctx_instruction = "\n" + "\n".join(ctx_parts) + "\n" if ctx_parts else ""

    lang_lower = (language or "pt").lower()
    if language_en or lang_lower in ("en", "english", "ingles", "inglês"):
        lang_instruction = "IMPORTANT: Write all analysis, captions, and text strictly in ENGLISH."
    elif lang_lower in ("es", "spanish", "espanhol", "español"):
        lang_instruction = "IMPORTANTE: Escribe todo el análisis, leyendas (captions) y textos estrictamente en ESPAÑOL."
    else:
        lang_instruction = "Sua resposta e análise devem ser escritas inteiramente em PORTUGUÊS DO BRASIL."

    return f"""{base_context}
TAREFA: Analise o vídeo com base na transcrição de falas, no contexto da obra e nos metadados fornecidos e entregue uma estratégia completa de otimização para viralizar no Instagram Reels.
{ctx_instruction}
{lang_instruction}

[TRANSCRIÇÃO DE ÁUDIO COM TIMESTAMPS]
{transcript if transcript else "Sem diálogos audíveis. Considere o contexto visual e sonoro fornecido."}

Responda EXATAMENTE neste formato JSON:
{{
    "video_analysis": {{
        "content_summary": "Resumo detalhado do conteúdo do vídeo",
        "aesthetic_quality": "Avaliação detalhada da estética e qualidade visual (crucial pro Reels)",
        "shareability_factor": "Avaliação do quão compartilhável via DM para amigos o vídeo é",
        "saveability_factor": "Avaliação do valor prático/salvamento do vídeo para rever depois",
        "strengths": ["Ponto forte 1", "Ponto forte 2", "Ponto forte 3"],
        "weaknesses": ["Ponto de melhoria 1", "Ponto de melhoria 2"]
    }},
    "optimization": {{
        "viral_score": 85,
        "viral_score_explanation": "Explicação detalhada da nota baseada no algoritmo do Instagram Reels",
        "hook_grade": "EXCELENTE / BOM / ATENCAO / FRACO",
        "hook_quality": "Análise crítica do gancho nos primeiros 2 segundos",
        "suggested_hook": "Sugestão de gancho visual/verbal muito mais magnético",
        "loop_strategy": "Instrução exata de como fazer o vídeo ter um loop invisível",
        "text_overlay_tips": ["Dica de texto na tela 1 (para quem assiste sem som)", "Dica 2"]
    }},
    "captions": [
        {{
            "style": "Storytelling / Curiosidade / Relatable",
            "first_line": "Primeira linha irresistível que aparece antes do 'ver mais'",
            "body": "Corpo completo da legenda com emojis, quebras de linha e storytelling",
            "cta": "Chamada para ação clara (Compartilhe na DM, Salve, Comente)",
            "why_works": "Por que essa legenda gera engajamento no algoritmo do Instagram",
            "full_caption": "Texto completo pronto para copiar e colar no Instagram"
        }}
    ],
    "hashtag_strategy": {{
        "recommended": ["#hashtag1", "#hashtag2", "#hashtag3", "#hashtag4", "#hashtag5"],
        "explanation": "Explicação da seleção (estratégia oficial de 3 a 5 hashtags altamente relevantes)",
        "copy_text": "#hashtag1 #hashtag2 #hashtag3 #hashtag4 #hashtag5"
    }},
    "audio_recommendation": "Recomendação sobre usar áudio original ou áudio em alta (trending audio) e como encaixar",
    "improvement_roadmap": [
        {{
            "action": "Ação prática de edição ou postagem",
            "impact": "Alto / Médio / Baixo"
        }}
    ]
}}

REGRAS:
- Gere EXATAMENTE 3 opções de legendas completas com estilos distintos.
- Forneça recomendações práticas e acionáveis.
- Responda APENAS com o JSON, sem texto fora dele.
"""


def build_yt_shorts_analysis_prompt(
    character: str = "",
    anime: str = "",
    scene_type: str = "",
    category: str = "anime",
    context: str = "",
    enriched_context: str = "",
    transcript: str = "",
    language_en: bool = False,
    language: str = "pt"
) -> str:
    """Build prompt for YouTube Shorts analysis with rich pop culture / anime API grounding."""
    cat_lower = (category or "").strip().lower()
    is_dorama = "dorama" in cat_lower
    
    if is_dorama:
        work_label = "Nome do Dorama"
        work_type_str = "Dorama"
        work_tag = "#dorama"
        extra_tags = "#kdrama"
        base_context = DORAMA_YOUTUBE_CONTEXT
    else:
        work_label = "Nome do Anime"
        work_type_str = "Anime"
        work_tag = "#anime"
        extra_tags = "#otaku"
        base_context = YOUTUBE_SHORTS_CONTEXT

    ctx_parts = []
    if character:
        ctx_parts.append(f"Personagem em foco: {character}")
    if anime:
        ctx_parts.append(f"{work_label}: {anime}")
    if scene_type:
        ctx_parts.append(f"Tipo de cena: {scene_type}")
    if context:
        ctx_parts.append(f"Contexto Adicional do Criador: {context}")
    if enriched_context:
        ctx_parts.append(enriched_context)
    ctx_instruction = "\nContexto extra fornecido:\n" + "\n".join(ctx_parts) if ctx_parts else ""

    lang_lower = (language or "pt").lower()
    if language_en or lang_lower in ("en", "english", "ingles", "inglês"):
        lang_instruction = "IMPORTANT: Write all titles, descriptions, tags, comments and analysis strictly in ENGLISH."
    elif lang_lower in ("es", "spanish", "espanhol", "español"):
        lang_instruction = "IMPORTANTE: Escribe todos los títulos, descripciones, tags, comentarios y análisis estrictamente en ESPAÑOL."
    else:
        lang_instruction = "Sua resposta e análise devem ser escritas inteiramente em PORTUGUÊS DO BRASIL."

    if is_dorama:
        title_instruction = """FÓRMULA DE OURO PARA 5 TÍTULOS DE DORAMA (K-DRAMA / C-DRAMA) NO SHORTS:
1. Curiosidade & Choque: ex: "Ela pensava que ele era pobre, até descobrir a verdade... 😱💔 #shorts #kdrama"
2. Romance & Proteção: ex: "Ele enfrentou a família inteira só pra defender ela 🥺❤️ #dorama #shorts"
3. CEO / Chefe Rendido: ex: "Quando o CEO frio percebe que é louco por ela 😳🍿 #kdrama #shorts"
4. Vingança & Superação: ex: "Tentaram humilhar ela, mas a resposta foi ÉPICA! 🔥👠 #dorama #shorts"
5. Emoção & Lágrimas: ex: "Essa cena partiu o coração de qualquer dorameira... 😭💔 #dorama #shorts"
TODOS os 5 títulos devem conter #shorts, emojis emocionais (💔, 🥺, 😱, 😭, ❤️, 😳) e forte gancho dramático!"""
        comment_format_hint = f"🎬 {work_label}: [Nome em Português] ([Nome Internacional / Inglês])\\n📺 Onde Assistir: [Netflix / Viki / Disney+ / etc.]\\n🍿 Cena / Episódio: [Nº aproximado]\\n\\n💬 Me contem dorameiras: o que vocês fariam nessa situação? Você perdoaria? Deixa sua opinião aqui embaixo! 👇❤️\\n\\n#dorama #kdrama #doramascoreanos #seriescoreanas #shorts"
        caption_hint = "Frase curta e de ALTO IMPACTO EMOCIONAL (máx 6-8 palavras) que faz a dorameira parar o scroll (ex: 'A dor nos olhos dela... 💔' ou 'Ele defendeu ela na frente de todos! 🥺❤️')"
        desc_hint = f"CORPO COMPLETO da descrição para dorameiras: Storytelling envolvente da cena + Ficha Técnica (🎬 Dorama: [Nome] | 📺 Onde assistir: [Streaming]) + CTA provocador nos comentários + hashtags ({work_tag} {extra_tags} #seriescoreanas #shorts)."
    else:
        title_instruction = "Gere 5 títulos Shorts altamente clicáveis com #shorts e emojis."
        comment_format_hint = f"{work_label}: [Nome Real]\\n\\n{work_tag} #[NomeSemEspaco] {extra_tags} #trend #shorts #viral\\n\\nPergunta engajadora específica sobre a cena para fazer os espectadores responderem nos comentários?"
        caption_hint = "Frase curta e IMPACTANTE (máx 8-10 palavras) para texto sobreposto no topo do vídeo que impede o scroll"
        desc_hint = f"CORPO COMPLETO da descrição (300-800 chars). Storytelling envolvente que complemente o vídeo, quebras de linha visuais, emojis a cada 1-2 linhas, perguntas retóricas para gerar comentários e palavras-chave para o algoritmo do YouTube Shorts."

    return f"""{base_context}
TAREFA: Analise este vídeo e forneça uma estratégia impecável de otimização para viralizar no YouTube Shorts.
{ctx_instruction}
{lang_instruction}

[TRANSCRIÇÃO DE ÁUDIO COM TIMESTAMPS]
{transcript if transcript else "Sem diálogos audíveis. Considere o ritmo sonoro e visual fornecido no contexto."}

Responda EXATAMENTE neste formato JSON:
{{
    "video_analysis": {{
        "content_summary": "Resumo detalhado do conteúdo da cena",
        "characters_detected": [
            "Nome do Personagem 1 (Papel/Ação/Fala neste corte específico)",
            "Nome do Personagem 2 (Papel/Ação/Fala neste corte específico)"
        ],
        "character_context": "Como os personagens e elementos de {work_type_str} estão contextualizados e o apelo aos fãs",
        "strengths": ["Ponto forte 1", "Ponto forte 2", "Ponto forte 3"],
        "weaknesses": ["Ponto de melhoria 1", "Ponto de melhoria 2"]
    }},
    "optimization": {{
        "viral_score": 88,
        "viral_score_explanation": "Explicação da nota com base no algoritmo do Shorts (retenção e swipe rate)",
        "hook_grade": "EXCELENTE / BOM / ATENCAO / FRACO",
        "hook_quality": "Análise detalhada do gancho nos primeiros 3 segundos",
        "suggested_hook": "Sugestão de gancho (verbal/visual) para impedir o swipe",
        "loop_strategy": "Estratégia para conectar o áudio/visual do fim com o início para >100% retenção",
        "retention_tricks": ["Truque de edição/ritmo 1", "Truque de edição 2"]
    }},
    "titles": [
        {{
            "title": "Título Shorts Chamativo com #shorts e emojis ({title_instruction})",
            "style": "Curiosidade / Hype / Suspense / Épico / Emocional",
            "why_works": "Por que esse título chama cliques no feed"
        }}
    ],
    "descriptions": [
        {{
            "style": "Estilo da descrição (ex: Storytelling Emocional / Curiosidade & Hype / Análise Épica)",
            "first_line": "PRIMEIRA LINHA DA DESCRIÇÃO — parte que aparece ANTES do 'ver mais' no Shorts. Deve ser IRRESISTÍVEL e CURTA (máx 80 chars) com gancho e emoji.",
            "body": "{desc_hint}",
            "cta": "CALL-TO-ACTION forte e específico (ex: 'Inscreva-se no canal para não perder os próximos vídeos! Deixe seu like e comente o que achou!')",
            "hashtags_inline": "#shorts {work_tag} {extra_tags} #seriescoreanas #[personagem] #[nome] — mix de hashtags estratégicas para o final da descrição",
            "full_caption": "A DESCRIÇÃO COMPLETA PRONTA PRA COLAR NO YOUTUBE: first_line + quebra de linha + body + quebra de linha + CTA + quebra de linha + hashtags_inline — tudo junto e perfeitamente formatado com quebras de linha reais.",
            "why_works": "Explicação de por que essa descrição potencializa o SEO e o engajamento no algoritmo do Shorts"
        }}
    ],
    "tags": [
        "tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8", "tag9", "tag10"
    ],
    "video_captions": [
        {{
            "text": "{caption_hint}",
            "style": "Choque / Curiosidade / Hype / Provocação / Emoção",
            "why_viral": "Por que essa frase gera retenção visual imediata e impede o swipe"
        }}
    ],
    "suggested_comments": [
        {{
            "comment": "{comment_format_hint}"
        }}
    ],
    "improvement_roadmap": [
        {{
            "action": "Ação de edição recomendada",
            "impact": "Alto / Médio / Baixo"
        }}
    ]
}}

IMPORTANTE SOBRE CHARACTERS_DETECTED (IDENTIFICAÇÃO DE PERSONAGENS NO CORTE):
Analise detalhadamente o áudio, falas transcritas, termos/jargões, golpes, tom de voz e o contexto da obra para identificar com precisão QUEM SÃO os personagens presentes, falando ou em destaque neste corte específico.
- Liste no campo "characters_detected" cada personagem com seu nome oficial e uma breve descrição da sua ação ou fala na cena (ex: ["Gojo Satoru (enfrentando o inimigo e ativando o Mugen)", "Jogo (em desespero com o ataque)"]).
- Se o corte tiver apenas 1 personagem, liste esse personagem com clareza.
- Se não for possível identificar com 100% de precisão (vídeo sem falas ou nomes), aponte os personagens prováveis com base no contexto ou indique "Não identificados com precisão".

IMPORTANTE SOBRE VIDEO_CAPTIONS (LEGENDAS NO TOPO):
As "video_captions" são LEGENDAS/TEXTOS que ficam sobrepostos NO TOPO DO VÍDEO para chamar atenção imediatamente e impedir o espectador de passar (swipe) o vídeo. NÃO são títulos nem descrições. São frases CURTAS (máximo 8-10 palavras), IMPACTANTES e PROVOCATIVAS que aparecem como texto na tela do vídeo. Devem causar curiosidade, choque, hype ou emoção. Exemplos de estilo: "ELE FEZ O IMPOSSÍVEL... 😱", "NINGUÉM ESPERAVA ISSO 🔥", "ASSISTA ATÉ O FINAL...", "O MOMENTO QUE MUDOU TUDO". Gere pelo menos 5 opções variadas de legendas de vídeo com "text", "style" e "why_viral".

IMPORTANTE SOBRE SUGGESTED_COMMENTS (COMENTÁRIOS PARA FIXAR):
Gere EXATAMENTE 3 comentários prontos pra fixar/postar no vídeo.
Cada comentário DEVE iniciar obrigatoriamente na primeira linha com "{work_label}: [Nome Real]", seguido de linha em branco, depois uma linha de hashtags começando com {work_tag} #[NomeSemEspacos] {extra_tags} #trend #shorts #viral seguidas de 2 a 4 hashtags adicionais relevantes (personagem, estúdio, gênero), linha em branco, e por fim uma pergunta curta e provocativa/envolvente sobre a cena para estimular o público a comentar.
As 3 perguntas devem ser COMPLETAMENTE DIFERENTES entre si.
Se o nome não for identificável, use "{work_label}: [Não identificado]".
A linha 1 deve iniciar impreterivelmente com o prefixo exato "{work_label}: ".

REGRAS CRÍTICAS PARA AS DESCRIÇÕES:
- Gere EXATAMENTE 3 descrições completas no padrão profissional, cada uma com um estilo DIFERENTE (ex: 1. Storytelling Emocional / 2. Curiosidade Agressiva & Hype / 3. Análise & Pergunta Retórica).
- A first_line é o que aparece ANTES do "ver mais" no YouTube Shorts (deve prender a atenção em até 80 caracteres e conter emoji).
- O body deve conter parágrafos curtos, storytelling sobre a cena, quebras visuais de linha, emojis e palavras-chave que posicionam o vídeo nas buscas do YouTube.
- O full_caption DEVE ser a versão COMPLETA e 100% pronta para colar direto no YouTube Studio (first_line + quebra de linha + body + quebra de linha + CTA + quebra de linha + hashtags_inline).
- Gere pelo menos 5 títulos variados (sempre incluindo #shorts).
- Gere entre 10 e 15 tags prontas para o YouTube Studio.
- Responda APENAS com o JSON.
"""


def _sec_to_ts(s: float) -> str:
    m = int(s // 60)
    sec = int(s % 60)
    return f"{m:02d}:{sec:02d}"


def extract_hook_thumbnail(
    video_path: str,
    output_path: Optional[str] = None,
    timestamp_sec: float = 1.5,
    ffmpeg_bin: str = "ffmpeg",
    overlay_text: str = "",
    crop_mode: str = "center",
    pan_x: float = 0.5,
    text_position: str = "top",
    text_style: str = "yellow"
) -> Optional[str]:
    """
    Extrai frame de alta qualidade rigorosamente em 9:16 (1080x1920)
    para ser utilizado como Capa / Thumbnail de alto CTR no YouTube Shorts e Instagram Reels,
    com opções de enquadramento (corte no personagem ou blur) e tipografia viral.
    """
    if not video_path or not os.path.exists(video_path):
        return None
    try:
        from thumbnail_studio import generate_shorts_thumbnail_pipeline
        return generate_shorts_thumbnail_pipeline(
            video_path=video_path,
            output_path=output_path,
            timestamp_sec=timestamp_sec,
            crop_mode=crop_mode,
            pan_x=pan_x,
            overlay_text=overlay_text,
            text_position=text_position,
            text_style=text_style,
            ffmpeg_bin=ffmpeg_bin
        )
    except Exception:
        # Fallback para extração direta via ffmpeg
        try:
            p = Path(video_path)
            if not output_path:
                output_path = str(p.parent / f"{p.stem}_capa_hook.jpg")
            import subprocess
            cmd = [
                ffmpeg_bin, "-y",
                "-ss", f"{timestamp_sec:.2f}",
                "-i", str(video_path),
                "-vframes", "1",
                "-q:v", "2",
                str(output_path)
            ]
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return output_path
        except Exception:
            pass
    return None


def adapt_yt_to_instagram(yt_data: Dict[str, Any]) -> Dict[str, Any]:
    """Converte análise do YouTube Shorts diretamente para o formato do Instagram Reels."""
    if not yt_data or not isinstance(yt_data, dict):
        return {}
    va = yt_data.get("video_analysis") or {}
    opt = yt_data.get("optimization") or {}
    titles = yt_data.get("titles") or []
    descriptions = yt_data.get("descriptions") or []
    tags = yt_data.get("tags") or []
    captions = yt_data.get("video_captions") or []

    # Converte tags do YouTube em hashtags do Instagram
    insta_hashtags = []
    for t in tags[:15]:
        clean = re.sub(r'[^a-zA-Z0-9_]', '', t.replace(" ", ""))
        if clean and not clean.startswith("#"):
            insta_hashtags.append(f"#{clean.lower()}")
        elif clean:
            insta_hashtags.append(clean.lower())
    if "#reels" not in insta_hashtags:
        insta_hashtags.insert(0, "#reels")
    if "#viral" not in insta_hashtags:
        insta_hashtags.insert(1, "#viral")

    adapted_captions = []
    for d in descriptions:
        full = d.get("full_caption") or (d.get("first_line", "") + "\n\n" + d.get("body", "") + "\n\n" + d.get("cta", ""))
        adapted_captions.append({
            "caption": full,
            "style": d.get("style", "Geral"),
            "why_works": d.get("why_works", "")
        })

    first_cta = descriptions[0].get("cta", "Salve para ver depois e compartilhe na DM!") if descriptions else "Compartilhe na DM!"

    res = {
        "source_network": "youtube_shorts",
        "adapted_for": "instagram_reels",
        "content_summary": va.get("content_summary", ""),
        "characters_detected": va.get("characters_detected", []),
        "hook_analysis": {
            "score": opt.get("viral_score", 85),
            "explanation": opt.get("viral_score_explanation", ""),
            "hook_quality": opt.get("hook_quality", ""),
            "suggested_hook": opt.get("suggested_hook", "")
        },
        "suggested_captions": adapted_captions,
        "hashtags": insta_hashtags,
        "video_captions": captions,
        "call_to_actions": [first_cta],
        "viral_tricks": opt.get("retention_tricks", [])
    }
    if "_thumbnail_path" in yt_data:
        res["_thumbnail_path"] = yt_data["_thumbnail_path"]
        res["_thumbnail_sec"] = yt_data.get("_thumbnail_sec", 1.5)
        res["_thumbnail_text"] = yt_data.get("_thumbnail_text", "")
    return res


def adapt_instagram_to_yt(insta_data: Dict[str, Any]) -> Dict[str, Any]:
    """Converte análise do Instagram Reels diretamente para o formato do YouTube Shorts."""
    if not insta_data or not isinstance(insta_data, dict):
        return {}
    va = insta_data.get("video_analysis") or {}
    hook_info = insta_data.get("hook_analysis") or {}
    captions = insta_data.get("suggested_captions") or []
    hashtags = insta_data.get("hashtags") or []
    video_caps = insta_data.get("video_captions") or []

    yt_tags = [h.replace("#", "") for h in hashtags if h.replace("#", "")]
    first_cap = captions[0].get("caption", "") if captions else ""
    first_line = first_cap.split("\n")[0][:80] if first_cap else "Momento Épico!"

    titles = [
        {"title": f"{first_line} #shorts", "style": "Hype / Viral", "why_works": "Inspirado no gancho viral do Reels"},
        {"title": f"VOCÊ JÁ VIU ISSO?! 🔥 #shorts", "style": "Curiosidade", "why_works": "Provoca clique imediato no feed"},
        {"title": f"O final vai te chocar... 😱 #shorts", "style": "Suspense", "why_works": "Alto potencial de retenção"}
    ]

    yt_descriptions = [{
        "style": "Storytelling Instagram Adaptado",
        "first_line": first_line,
        "body": first_cap,
        "cta": "Inscreva-se no canal para mais vídeos como este e ative as notificações! 🚀",
        "hashtags_inline": " ".join([f"#{t}" for t in yt_tags[:5]]),
        "full_caption": f"{first_line}\n\n{first_cap}\n\nInscreva-se no canal e deixe seu like! 🚀\n\n{' '.join([f'#{t}' for t in yt_tags[:5]])}",
        "why_works": "Adaptado do Reels mantendo narrativa e direcionando CTA para inscritos"
    }]

    res = {
        "source_network": "instagram_reels",
        "adapted_for": "youtube_shorts",
        "video_analysis": {
            "content_summary": insta_data.get("content_summary") or va.get("content_summary", ""),
            "characters_detected": insta_data.get("characters_detected") or va.get("characters_detected", []),
            "strengths": ["Alto apelo visual testado para Reels"],
            "weaknesses": []
        },
        "optimization": {
            "viral_score": hook_info.get("score", 85),
            "viral_score_explanation": hook_info.get("explanation", ""),
            "hook_quality": hook_info.get("hook_quality", ""),
            "suggested_hook": hook_info.get("suggested_hook", ""),
            "retention_tricks": insta_data.get("viral_tricks", [])
        },
        "titles": titles,
        "descriptions": yt_descriptions,
        "tags": yt_tags[:15],
        "video_captions": video_caps
    }
    if "_thumbnail_path" in insta_data:
        res["_thumbnail_path"] = insta_data["_thumbnail_path"]
        res["_thumbnail_sec"] = insta_data.get("_thumbnail_sec", 1.5)
        res["_thumbnail_text"] = insta_data.get("_thumbnail_text", "")
    return res


def analyze_instagram_video(
    video_path: str,
    context: str = "",
    work_name: str = "",
    category: str = "anime",
    language_en: bool = False,
    language: str = "pt",
    force_refresh: bool = False,
    ffmpeg_bin: str = "ffmpeg",
    on_log: Optional[Callable[[str], None]] = None,
    log_cb: Optional[Callable[[str], None]] = None,
    **kwargs
) -> Dict[str, Any]:
    """Execute full Instagram Reels video analysis with optional Anime/Dorama API grounding and 24h AI caching."""
    _logger = on_log or log_cb

    def _log(m):
        if _logger:
            _logger(m)

    try:
        from ai_cache_hub import ai_cache
    except Exception:
        ai_cache = None

    # Check cached analysis unless force_refresh is requested
    if ai_cache and not force_refresh:
        cached_res = ai_cache.get(video_path, "instagram_analysis")
        if (cached_res and isinstance(cached_res, dict) and
            not cached_res.get("parse_error") and
            ("hook_analysis" in cached_res or "suggested_captions" in cached_res)):
            _log("⚡ [Cache Inteligente 24h] Análise Instagram recuperada instantaneamente (0 tokens gastos)!")
            return cached_res

        # Cross-cache: verifica se o vídeo já foi analisado na aba YouTube Shorts
        cached_yt = ai_cache.get(video_path, "yt_shorts_analysis")
        if (cached_yt and isinstance(cached_yt, dict) and
            not cached_yt.get("parse_error") and
            ("video_analysis" in cached_yt or "optimization" in cached_yt)):
            _log("⚡ [Cross-Cache 24h] Análise do YouTube Shorts encontrada para este vídeo! Reutilizando dados para o Instagram Reels instantaneamente (0 tokens gastos)!")
            adapted = adapt_yt_to_instagram(cached_yt)
            ai_cache.set(video_path, "instagram_analysis", adapted)
            return adapted

    _log("📸 Iniciando análise para Instagram Reels...")
    _log(f"   Arquivo: {os.path.basename(video_path)}")

    # 1. Transcribe audio if available (check cache first)
    transcript = ""
    if ai_cache and not force_refresh:
        cached_dt = ai_cache.get(video_path, "director_transcript")
        if cached_dt and isinstance(cached_dt, str):
            transcript = cached_dt
            _log("⚡ [Cache Inteligente 24h] Transcrição recuperada do cache (0 tokens gastos)!")
        else:
            cached_trans = ai_cache.get(video_path, "transcription")
            if cached_trans and isinstance(cached_trans, dict):
                words = cached_trans.get("words", [])
                if words:
                    lines = []
                    curr = []
                    st = None
                    for w in words:
                        s = float(w.get("start", 0.0))
                        e = float(w.get("end", 0.0))
                        txt = w.get("word") if "word" in w else w.get("text", "")
                        if st is None:
                            st = s
                        curr.append(txt)
                        if len(curr) >= 8 or (txt and txt[-1] in ".!?"):
                            lines.append(f"[{_sec_to_ts(st)} -> {_sec_to_ts(e)}] {' '.join(curr)}")
                            curr = []
                            st = None
                    if curr and st is not None:
                        lines.append(f"[{_sec_to_ts(st)} -> {_sec_to_ts(e)}] {' '.join(curr)}")
                    transcript = "\n".join(lines)
                    _log("⚡ [Cache Inteligente 24h] Falas e diálogos sincronizados a partir do cache Whisper!")

    if not transcript and ai_cache:
        try:
            cut_origin = ai_cache.get_cut_origin(video_path)
            if cut_origin:
                src_ep = cut_origin.get("source_episode_path") or cut_origin.get("source_episode")
                st_sec = cut_origin.get("start_sec")
                end_sec = cut_origin.get("end_sec")
                if src_ep and st_sec is not None and end_sec is not None:
                    src_trans = ai_cache.get(src_ep, "transcription")
                    if src_trans and isinstance(src_trans, dict):
                        words = src_trans.get("words", [])
                        cut_words = [w for w in words if float(st_sec) - 0.5 <= float(w.get("start", 0)) <= float(end_sec) + 0.5]
                        if cut_words:
                            lines = []
                            curr = []
                            st_rel = None
                            for w in cut_words:
                                s = max(0.0, float(w.get("start", 0)) - float(st_sec))
                                e = max(s + 0.1, float(w.get("end", 0)) - float(st_sec))
                                txt = w.get("word") if "word" in w else w.get("text", "")
                                if st_rel is None:
                                    st_rel = s
                                curr.append(txt)
                                if len(curr) >= 8 or (txt and txt[-1] in ".!?"):
                                    lines.append(f"[{_sec_to_ts(st_rel)} -> {_sec_to_ts(e)}] {' '.join(curr)}")
                                    curr = []
                                    st_rel = None
                            if curr and st_rel is not None:
                                lines.append(f"[{_sec_to_ts(st_rel)} -> {_sec_to_ts(e)}] {' '.join(curr)}")
                            transcript = "\n".join(lines)
                            _log("⚡ [Cache Inteligente] Diálogos herdados do episódio original (0s gastos, sem re-transcrever)!")
        except Exception:
            pass

    if not transcript:
        try:
            _log("🎙️ Extraindo áudio do vídeo...")
            audio_path = extract_audio(video_path, ffmpeg_bin=ffmpeg_bin)
            _log("✓ Áudio extraído. Gerando transcrição com timestamps...")
            transcript = transcribe_video_audio(audio_path, on_log=_log)
            if transcript:
                _log(f"✓ Transcrição gerada ({len(transcript.splitlines())} segmentos de fala)")
                if ai_cache:
                    ai_cache.set(video_path, "director_transcript", transcript)
            try:
                os.remove(audio_path)
            except Exception:
                pass
        except Exception as e:
            _log(f"⚠ Aviso ao transcrever áudio: {e}. Prosseguindo com análise contextual...")

    # 2. Enrich context via Anime/Dorama APIs (Kitsu, MyAnimeList, TVMaze)
    enriched_context = ""
    target_work = work_name.strip() or context.strip()
    if target_work and len(target_work) >= 2:
        enriched_context = get_enriched_context_for_prompt(target_work, category=category, on_log=_log)
        if enriched_context:
            _log(f"✓ Lore e metadados oficiais ({category}) integrados ao prompt do Instagram!")

    # 3. Build prompt and call AI
    _log("🧠 IA avaliando métricas do Instagram (DMs, Saves, Watch Time e Estética)...")
    prompt = build_instagram_analysis_prompt(
        context=context,
        work_name=work_name,
        category=category,
        enriched_context=enriched_context,
        transcript=transcript,
        language_en=language_en,
        language=language
    )
    raw_response = call_ai_text(prompt, on_log=_log, max_tokens=4096)

    _log("✨ Formatando resultados da análise...")
    data = _parse_ai_json(raw_response)
    data["_transcript"] = transcript
    data["_enriched_context"] = enriched_context

    # Extrai frame de capa para Thumbnail de Alto CTR (1080x1920) com título do gancho
    first_title = data.get("title") or data.get("hook_text") or ""
    thumb_path = extract_hook_thumbnail(video_path, ffmpeg_bin=ffmpeg_bin, overlay_text=first_title)
    if thumb_path:
        data["_thumbnail_path"] = thumb_path
        data["_thumbnail_sec"] = 1.5
        data["_thumbnail_text"] = first_title
        _log(f"🖼️ [Thumbnail Hook CTR] Capa 1080x1920 extraída com sucesso: {os.path.basename(thumb_path)}")

    if ai_cache and data and not data.get("parse_error") and ("hook_analysis" in data or "suggested_captions" in data):
        ai_cache.set(video_path, "instagram_analysis", data)
        # Sincroniza cross-cache para o YouTube Shorts instantaneamente
        try:
            adapted_yt = adapt_instagram_to_yt(data)
            if adapted_yt:
                ai_cache.set(video_path, "yt_shorts_analysis", adapted_yt)
        except Exception:
            pass
        # Salva metadados virais para compartilhamento
        viral_info = {
            "title": data.get("title") or data.get("hook_text") or "",
            "hashtags": data.get("hashtags", []),
            "source": "instagram"
        }
        ai_cache.set(video_path, "viral_metadata", viral_info)
    elif data.get("parse_error") and ai_cache:
        ai_cache.invalidate(video_path, "instagram_analysis")

    return data


def analyze_yt_shorts_video(
    video_path: str,
    character: str = "",
    anime: str = "",
    scene_type: str = "",
    category: str = "anime",
    context: str = "",
    language_en: bool = False,
    language: str = "pt",
    force_refresh: bool = False,
    ffmpeg_bin: str = "ffmpeg",
    on_log: Optional[Callable[[str], None]] = None,
    log_cb: Optional[Callable[[str], None]] = None,
    **kwargs
) -> Dict[str, Any]:
    """Execute full YouTube Shorts video analysis with Anime/Dorama API grounding and 24h AI caching."""
    _logger = on_log or log_cb

    def _log(m):
        if _logger:
            _logger(m)

    try:
        from ai_cache_hub import ai_cache
    except Exception:
        ai_cache = None

    # Check cached analysis unless force_refresh is requested
    if ai_cache and not force_refresh:
        cached_res = ai_cache.get(video_path, "yt_shorts_analysis")
        if (cached_res and isinstance(cached_res, dict) and
            not cached_res.get("parse_error") and
            ("video_analysis" in cached_res or "optimization" in cached_res)):
            _log("⚡ [Cache Inteligente 24h] Análise YouTube Shorts recuperada instantaneamente (0 tokens gastos)!")
            return cached_res

        # Cross-cache: verifica se o vídeo já foi analisado na aba Instagram Reels
        cached_insta = ai_cache.get(video_path, "instagram_analysis")
        if (cached_insta and isinstance(cached_insta, dict) and
            not cached_insta.get("parse_error") and
            ("hook_analysis" in cached_insta or "suggested_captions" in cached_insta)):
            _log("⚡ [Cross-Cache 24h] Análise do Instagram Reels encontrada para este vídeo! Reutilizando dados para o YouTube Shorts instantaneamente (0 tokens gastos)!")
            adapted = adapt_instagram_to_yt(cached_insta)
            ai_cache.set(video_path, "yt_shorts_analysis", adapted)
            return adapted

    _log("▶️ Iniciando análise para YouTube Shorts...")
    _log(f"   Arquivo: {os.path.basename(video_path)}")
    _log(f"   Categoria: {category.capitalize()} | Idioma: {'Inglês' if language_en else 'Português'}")
    if context.strip():
        _log(f"   Contexto extra: {context.strip()}")

    # 1. Transcribe audio if available (check cache first)
    transcript = ""
    if ai_cache and not force_refresh:
        cached_dt = ai_cache.get(video_path, "director_transcript")
        if cached_dt and isinstance(cached_dt, str):
            transcript = cached_dt
            _log("⚡ [Cache Inteligente 24h] Transcrição recuperada do cache (0 tokens gastos)!")
        else:
            cached_trans = ai_cache.get(video_path, "transcription")
            if cached_trans and isinstance(cached_trans, dict):
                words = cached_trans.get("words", [])
                if words:
                    lines = []
                    curr = []
                    st = None
                    for w in words:
                        s = float(w.get("start", 0.0))
                        e = float(w.get("end", 0.0))
                        txt = w.get("word") if "word" in w else w.get("text", "")
                        if st is None:
                            st = s
                        curr.append(txt)
                        if len(curr) >= 8 or (txt and txt[-1] in ".!?"):
                            lines.append(f"[{_sec_to_ts(st)} -> {_sec_to_ts(e)}] {' '.join(curr)}")
                            curr = []
                            st = None
                    if curr and st is not None:
                        lines.append(f"[{_sec_to_ts(st)} -> {_sec_to_ts(e)}] {' '.join(curr)}")
                    transcript = "\n".join(lines)
                    _log("⚡ [Cache Inteligente 24h] Falas e diálogos sincronizados a partir do cache Whisper!")

    if not transcript and ai_cache:
        try:
            cut_origin = ai_cache.get_cut_origin(video_path)
            if cut_origin:
                src_ep = cut_origin.get("source_episode_path") or cut_origin.get("source_episode")
                st_sec = cut_origin.get("start_sec")
                end_sec = cut_origin.get("end_sec")
                if src_ep and st_sec is not None and end_sec is not None:
                    src_trans = ai_cache.get(src_ep, "transcription")
                    if src_trans and isinstance(src_trans, dict):
                        words = src_trans.get("words", [])
                        cut_words = [w for w in words if float(st_sec) - 0.5 <= float(w.get("start", 0)) <= float(end_sec) + 0.5]
                        if cut_words:
                            lines = []
                            curr = []
                            st_rel = None
                            for w in cut_words:
                                s = max(0.0, float(w.get("start", 0)) - float(st_sec))
                                e = max(s + 0.1, float(w.get("end", 0)) - float(st_sec))
                                txt = w.get("word") if "word" in w else w.get("text", "")
                                if st_rel is None:
                                    st_rel = s
                                curr.append(txt)
                                if len(curr) >= 8 or (txt and txt[-1] in ".!?"):
                                    lines.append(f"[{_sec_to_ts(st_rel)} -> {_sec_to_ts(e)}] {' '.join(curr)}")
                                    curr = []
                                    st_rel = None
                            if curr and st_rel is not None:
                                lines.append(f"[{_sec_to_ts(st_rel)} -> {_sec_to_ts(e)}] {' '.join(curr)}")
                            transcript = "\n".join(lines)
                            _log("⚡ [Cache Inteligente] Diálogos herdados do episódio original (0s gastos, sem re-transcrever)!")
        except Exception:
            pass

    if not transcript:
        try:
            _log("🎙️ Extraindo áudio do vídeo...")
            audio_path = extract_audio(video_path, ffmpeg_bin=ffmpeg_bin)
            _log("✓ Áudio extraído. Gerando transcrição com timestamps...")
            transcript = transcribe_video_audio(audio_path, on_log=_log)
            if transcript:
                _log(f"✓ Transcrição gerada ({len(transcript.splitlines())} segmentos)")
                if ai_cache:
                    ai_cache.set(video_path, "director_transcript", transcript)
            try:
                os.remove(audio_path)
            except Exception:
                pass
        except Exception as e:
            _log(f"⚠ Aviso ao transcrever áudio: {e}. Prosseguindo com análise...")

    # 2. Enrich context via Anime/Dorama APIs (Kitsu, MyAnimeList, TVMaze)
    enriched_context = ""
    target_work = anime.strip() or character.strip()
    if target_work and len(target_work) >= 2:
        enriched_context = get_enriched_context_for_prompt(target_work, category=category, on_log=_log)
        if enriched_context:
            _log("✓ Lore e metadados oficiais integrados ao prompt de Shorts!")

    # 3. Build prompt and call AI
    _log("🧠 IA avaliando retenção, CTR de título, tags e ganchos para Shorts...")
    prompt = build_yt_shorts_analysis_prompt(
        character=character,
        anime=anime,
        scene_type=scene_type,
        category=category,
        context=context,
        enriched_context=enriched_context,
        transcript=transcript,
        language_en=language_en,
        language=language
    )
    raw_response = call_ai_text(prompt, on_log=_log, max_tokens=4096)

    _log("✨ Formatando resultados de SEO e retenção...")
    data = _parse_ai_json(raw_response)
    data["_transcript"] = transcript
    data["_enriched_context"] = enriched_context

    # Identifica o melhor título para a capa 9:16
    titles = data.get("titles", [])
    chosen_title = ""
    if titles and isinstance(titles, list):
        first_t = titles[0]
        chosen_title = first_t.get("title", "") if isinstance(first_t, dict) else str(first_t)
    if not chosen_title:
        chosen_title = data.get("title", "")

    # Extrai frame de capa para Thumbnail de Alto CTR (1080x1920) já com o título 9:16
    thumb_path = extract_hook_thumbnail(video_path, ffmpeg_bin=ffmpeg_bin, overlay_text=chosen_title)
    if thumb_path:
        data["_thumbnail_path"] = thumb_path
        data["_thumbnail_sec"] = 1.5
        data["_thumbnail_text"] = chosen_title
        _log(f"🖼️ [Thumbnail Hook CTR] Capa 1080x1920 extraída com sucesso: {os.path.basename(thumb_path)}")

    if ai_cache and data and not data.get("parse_error") and ("video_analysis" in data or "optimization" in data):
        ai_cache.set(video_path, "yt_shorts_analysis", data)
        # Sincroniza cross-cache para o Instagram Reels instantaneamente
        try:
            adapted_insta = adapt_yt_to_instagram(data)
            if adapted_insta:
                ai_cache.set(video_path, "instagram_analysis", adapted_insta)
        except Exception:
            pass
        # Salva metadados virais para compartilhamento
        viral_info = {
            "title": chosen_title,
            "tags": data.get("tags", []),
            "source": "yt_shorts"
        }
        ai_cache.set(video_path, "viral_metadata", viral_info)
    elif data.get("parse_error") and ai_cache:
        ai_cache.invalidate(video_path, "yt_shorts_analysis")

    return data


def get_video_info_fast(video_path: str) -> Dict[str, Any]:
    """Obtém rapidamente resolução, duração e presença de áudio com ffprobe ou fallback."""
    import subprocess
    info = {
        "duration": 0.0,
        "duration_str": "00:00",
        "resolution": "Desconhecido",
        "has_audio": False
    }
    if not os.path.exists(video_path):
        return info

    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height:format=duration",
            "-of", "json",
            video_path
        ]
        res = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        if res.returncode == 0 and res.stdout:
            data = json.loads(res.stdout)
            streams = data.get("streams", [])
            fmt = data.get("format", {})
            if streams:
                w = streams[0].get("width")
                h = streams[0].get("height")
                if w and h:
                    info["resolution"] = f"{w}x{h}"
            dur = float(fmt.get("duration", 0.0))
            if dur > 0:
                info["duration"] = dur
                m = int(dur // 60)
                s = int(dur % 60)
                info["duration_str"] = f"{m:02d}:{s:02d}"
    except Exception:
        pass

    try:
        cmd_a = [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            video_path
        ]
        res_a = subprocess.run(
            cmd_a, capture_output=True, encoding="utf-8", errors="replace", timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        if res_a.returncode == 0 and "audio" in res_a.stdout.lower():
            info["has_audio"] = True
    except Exception:
        pass

    return info
