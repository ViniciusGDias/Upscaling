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
Você é o maior especialista mundial em conteúdo viral de doramas (K-Drama, C-Drama, J-Drama, Thai Drama) para o YouTube Shorts.
Você conhece TODOS os doramas populares, seus arcos emocionais, e sabe identificar os momentos que geram mais engajamento.
1. ALGORITMO DO YOUTUBE SHORTS:
   - O Shorts prioriza Retenção de Público e Taxa de Visualização vs. Rejeição (>70-80%).
   - Vídeos com loop imperceptível e >100% retenção viralizam massivamente.
2. PADRÕES VIRAIS DE DORAMAS NO SHORTS:
   - CENAS ROMÂNTICAS: Primeiro beijo, declaração de amor, reencontros, tensão de proximidade.
   - DRAMA EMOCIONAL: Choro, traição, sacrifício, separação dolorosa.
   - PLOT TWISTS: Revelação de segredos e identidade.
   - TRILHA / OST: Músicas coreanas que elevam a emoção.
"""


def _parse_ai_json(text: str) -> Dict[str, Any]:
    """Parse JSON from AI response robustly."""
    if not text:
        return {}
    clean = text.strip()
    if "```json" in clean:
        clean = clean.split("```json")[1].split("```")[0].strip()
    elif "```" in clean:
        clean = clean.split("```")[1].split("```")[0].strip()

    try:
        return json.loads(clean)
    except Exception:
        match = re.search(r'\{.*\}', clean, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
    return {"raw_response": text, "parse_error": True}


def build_instagram_analysis_prompt(
    context: str = "",
    work_name: str = "",
    enriched_context: str = "",
    transcript: str = "",
    language_en: bool = False
) -> str:
    """Build prompt for Instagram Reels analysis with rich pop culture / anime API grounding."""
    ctx_parts = []
    if work_name:
        ctx_parts.append(f"Obra/Anime/Série: {work_name}")
    if context:
        ctx_parts.append(f"Contexto do criador: {context}")
    if enriched_context:
        ctx_parts.append(enriched_context)

    ctx_instruction = "\n" + "\n".join(ctx_parts) + "\n" if ctx_parts else ""
    lang_instruction = (
        "IMPORTANT: Write all analysis, captions, and text strictly in ENGLISH."
        if language_en else
        "Sua resposta e análise devem ser escritas inteiramente em PORTUGUÊS DO BRASIL."
    )

    return f"""{INSTAGRAM_CONTEXT}
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
    enriched_context: str = "",
    transcript: str = "",
    language_en: bool = False
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
    if enriched_context:
        ctx_parts.append(enriched_context)
    ctx_instruction = "\nContexto extra fornecido:\n" + "\n".join(ctx_parts) if ctx_parts else ""

    lang_instruction = (
        "IMPORTANT: Write all titles, descriptions, tags, comments and analysis strictly in ENGLISH."
        if language_en else
        "Sua resposta e análise devem ser escritas inteiramente em PORTUGUÊS DO BRASIL."
    )

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
        "hook_quality": "Análise detalhada do gancho nos primeiros 3 segundos",
        "suggested_hook": "Sugestão de gancho (verbal/visual) para impedir o swipe",
        "loop_strategy": "Estratégia para conectar o áudio/visual do fim com o início para >100% retenção",
        "retention_tricks": ["Truque de edição/ritmo 1", "Truque de edição 2"]
    }},
    "titles": [
        {{
            "title": "Título Shorts Chamativo com #shorts e emojis",
            "style": "Curiosidade / Hype / Suspense / Épico",
            "why_works": "Por que esse título chama cliques no feed"
        }}
    ],
    "descriptions": [
        {{
            "style": "Estilo da descrição (ex: Storytelling Emocional / Curiosidade & Hype / Análise Épica)",
            "first_line": "PRIMEIRA LINHA DA DESCRIÇÃO — parte que aparece ANTES do 'ver mais' no Shorts. Deve ser IRRESISTÍVEL e CURTA (máx 80 chars) com gancho e emoji.",
            "body": "CORPO COMPLETO da descrição (300-800 chars). Storytelling envolvente que complemente o vídeo, quebras de linha visuais, emojis a cada 1-2 linhas, perguntas retóricas para gerar comentários e palavras-chave para o algoritmo do YouTube Shorts.",
            "cta": "CALL-TO-ACTION forte e específico (ex: 'Inscreva-se no canal para não perder os próximos vídeos! Deixe seu like e comente o que achou!')",
            "hashtags_inline": "#shorts {work_tag} #edit #[personagem] #[nome] — mix de hashtags estratégicas para o final da descrição",
            "full_caption": "A DESCRIÇÃO COMPLETA PRONTA PRA COLAR NO YOUTUBE: first_line + quebra de linha + body + quebra de linha + CTA + quebra de linha + hashtags_inline — tudo junto e perfeitamente formatado com quebras de linha reais.",
            "why_works": "Explicação de por que essa descrição potencializa o SEO e o engajamento no algoritmo do Shorts"
        }}
    ],
    "tags": [
        "tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8", "tag9", "tag10"
    ],
    "video_captions": [
        {{
            "text": "Frase curta e IMPACTANTE (máx 8-10 palavras) para texto sobreposto no topo do vídeo que impede o scroll",
            "style": "Choque / Curiosidade / Hype / Provocação / Emoção",
            "why_viral": "Por que essa frase gera retenção visual imediata e impede o swipe"
        }}
    ],
    "suggested_comments": [
        {{
            "comment": "{work_label}: [Nome Real]\\n\\n{work_tag} #[NomeSemEspaco] {extra_tags} #trend #shorts #viral\\n\\nPergunta engajadora específica sobre a cena para fazer os espectadores responderem nos comentários?"
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


def analyze_instagram_video(
    video_path: str,
    context: str = "",
    work_name: str = "",
    language_en: bool = False,
    ffmpeg_bin: str = "ffmpeg",
    on_log: Optional[Callable[[str], None]] = None,
    log_cb: Optional[Callable[[str], None]] = None,
    **kwargs
) -> Dict[str, Any]:
    """Execute full Instagram Reels video analysis with optional Anime/Dorama API grounding."""
    _logger = on_log or log_cb

    def _log(m):
        if _logger:
            _logger(m)

    _log("📸 Iniciando análise para Instagram Reels...")
    _log(f"   Arquivo: {os.path.basename(video_path)}")

    # 1. Transcribe audio if available
    transcript = ""
    try:
        _log("🎙️ Extraindo áudio do vídeo...")
        audio_path = extract_audio(video_path, ffmpeg_bin=ffmpeg_bin)
        _log("✓ Áudio extraído. Gerando transcrição com timestamps...")
        transcript = transcribe_video_audio(audio_path, on_log=_log)
        if transcript:
            _log(f"✓ Transcrição gerada ({len(transcript.splitlines())} segmentos de fala)")
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
        enriched_context = get_enriched_context_for_prompt(target_work, on_log=_log)
        if enriched_context:
            _log("✓ Lore e metadados oficiais integrados ao prompt do Instagram!")

    # 3. Build prompt and call AI
    _log("🧠 IA avaliando métricas do Instagram (DMs, Saves, Watch Time e Estética)...")
    prompt = build_instagram_analysis_prompt(
        context=context,
        work_name=work_name,
        enriched_context=enriched_context,
        transcript=transcript,
        language_en=language_en
    )
    raw_response = call_ai_text(prompt, on_log=_log, max_tokens=4096)

    _log("✨ Formatando resultados da análise...")
    data = _parse_ai_json(raw_response)
    data["_transcript"] = transcript
    data["_enriched_context"] = enriched_context
    return data


def analyze_yt_shorts_video(
    video_path: str,
    character: str = "",
    anime: str = "",
    scene_type: str = "",
    category: str = "anime",
    language_en: bool = False,
    ffmpeg_bin: str = "ffmpeg",
    on_log: Optional[Callable[[str], None]] = None,
    log_cb: Optional[Callable[[str], None]] = None,
    **kwargs
) -> Dict[str, Any]:
    """Execute full YouTube Shorts video analysis with Anime/Dorama API grounding."""
    _logger = on_log or log_cb

    def _log(m):
        if _logger:
            _logger(m)

    _log("▶️ Iniciando análise para YouTube Shorts...")
    _log(f"   Arquivo: {os.path.basename(video_path)}")
    _log(f"   Categoria: {category.capitalize()} | Idioma: {'Inglês' if language_en else 'Português'}")

    # 1. Transcribe audio if available
    transcript = ""
    try:
        _log("🎙️ Extraindo áudio do vídeo...")
        audio_path = extract_audio(video_path, ffmpeg_bin=ffmpeg_bin)
        _log("✓ Áudio extraído. Gerando transcrição com timestamps...")
        transcript = transcribe_video_audio(audio_path, on_log=_log)
        if transcript:
            _log(f"✓ Transcrição gerada ({len(transcript.splitlines())} segmentos)")
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
        enriched_context=enriched_context,
        transcript=transcript,
        language_en=language_en
    )
    raw_response = call_ai_text(prompt, on_log=_log, max_tokens=4096)

    _log("✨ Formatando resultados de SEO e retenção...")
    data = _parse_ai_json(raw_response)
    data["_transcript"] = transcript
    data["_enriched_context"] = enriched_context
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
