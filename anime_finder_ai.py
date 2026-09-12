"""
Anime Finder AI - Mecanismo de busca e recomendação de animes e episódios virais.
Integrado com call_ai_text (Gemini multi-key / Groq fallback).
"""

import json
import logging
import re
from typing import Dict, Any, List, Optional
from director_ai import call_ai_text

logger = logging.getLogger(__name__)

SYSTEM_CONTEXT = """
Você é o maior especialista mundial em cultura pop, animes, mangás e conteúdo viral para TikTok, YouTube Shorts e Instagram Reels.
Você conhece milhares de animes, seus arcos, episódios exatos, cenas icônicas e momentos com alto potencial de compartilhamento e retenção.
Sempre responda em PORTUGUÊS DO BRASIL.
"""


def _clean_json_response(raw_text: str) -> dict:
    """Extrai e parseia JSON da resposta do modelo."""
    if not raw_text:
        return {}
    text = raw_text.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()

    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1 and end > start:
        json_str = text[start:end]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', json_str)
            try:
                return json.loads(json_str)
            except Exception:
                pass
    return {"raw_response": text, "parse_error": True}


def build_anime_finder_prompt(query: str, genre: str = "", platform: str = "all",
                              count: int = 5, popularity: str = "any", era: str = "any") -> str:
    """Constrói o prompt para o Anime Finder."""
    genre_instruction = f"\nFiltro de gênero preferido: {genre}" if genre else ""
    platform_map = {
        "all": "TikTok, YouTube Shorts e Instagram Reels",
        "tiktok": "TikTok",
        "youtube": "YouTube Shorts",
        "instagram": "Instagram Reels"
    }
    platform_name = platform_map.get(platform, "TikTok, YouTube Shorts e Instagram Reels")
    popularity_map = {
        "any": "",
        "mainstream": "\nPriorize animes MAINSTREAM muito populares (ex: Naruto, Dragon Ball, One Piece, Jujutsu Kaisen, Attack on Titan, Demon Slayer, etc).",
        "popular": "\nPriorize animes populares mas não necessariamente os TOP mainstream.",
        "hidden_gem": "\nFoque em animes POUCO EXPLORADOS (joias escondidas) que têm cenas incríveis mas poucos criadores de conteúdo usam."
    }
    popularity_instruction = popularity_map.get(popularity, "")
    era_map = {
        "any": "",
        "new": "\nFoque em animes NOVOS lançados a partir de 2020.",
        "modern": "\nFoque em animes MODERNOS lançados entre 2010 e 2019.",
        "classic": "\nFoque em animes CLÁSSICOS lançados antes de 2010."
    }
    era_instruction = era_map.get(era, "")

    return f"""{SYSTEM_CONTEXT}
Você é um especialista absoluto em ANIME. Conhece os animes mais populares, seus episódios exatos, arcos principais,
e as cenas mais icônicas que a comunidade anime reconhece como memoráveis.

TAREFA: O usuário quer encontrar os melhores animes e os EPISÓDIOS EXATOS para baixar e postar conteúdo viral em {platform_name}.
Pedido do usuário: "{query}"
{genre_instruction}{popularity_instruction}{era_instruction}

Analise o pedido e sugira EXATAMENTE {count} animes que atendam perfeitamente ao que o usuário quer.
Para cada anime, indique as CENAS MAIS ICÔNICAS E CONHECIDAS e o NÚMERO EXATO DO EPISÓDIO onde a cena acontece.

⚠️ REGRAS ABSOLUTAMENTE OBRIGATÓRIAS:
1. SOMENTE recomende cenas que são AMPLAMENTE CONHECIDAS pela comunidade anime. NÃO invente cenas.
2. É OBRIGATÓRIO fornecer o NÚMERO EXATO DO EPISÓDIO (ex: "Episódio 131", "Episódios 47 e 48", "Episódio 1071") onde a cena ocorre.
3. NÃO invente timestamps falsos. Descreva a cena com precisão para que o usuário identifique o momento exato dentro do episódio.
4. Para cada cena, forneça um TERMO DE BUSCA detalhado contendo o nome do anime, número do episódio e descrição (ex: "Dragon Ball Super episodio 131 Goku vs Jiren").
5. Foque em momentos que são REFERÊNCIA na comunidade — cenas que qualquer fã conhece.
6. Ordene do anime com MAIOR potencial viral para o menor.

Responda EXATAMENTE neste formato JSON:
{{
    "summary": "Resumo rápido do que foi encontrado baseado no pedido do usuário",
    "animes": [
        {{
            "name": "Nome do Anime (Nome Original)",
            "genre": "Gênero (ex: Romance, Ação, Drama)",
            "year": "Ano de lançamento ou período (ex: 2020-2023)",
            "episodes_total": "Total de episódios (ex: 24)",
            "popularity_level": "Nível de popularidade (ex: 🔥 Mainstream, ⭐ Popular, 💎 Joia Escondida)",
            "viral_potential": 92,
            "why_recommended": "Explicação de por que esse anime é perfeito para o que o usuário quer",
            "viral_appeal": "O que faz as cenas desse anime bombar nas redes sociais (animação, emoção, etc)",
            "best_episodes": [
                {{
                    "episode": "Episódio X exato (MANDATÓRIO o número do episódio, ex: Episódio 131)",
                    "arc_name": "Nome do Arco/Saga onde o episódio ocorre",
                    "scene_description": "Descrição detalhada da cena: o que acontece, quais personagens estão envolvidos, emoção, clímax.",
                    "search_term": "Termo de busca com o número do episódio para pesquisar no YouTube/Google",
                    "why_viral": "Por que essa cena específica viralizaria nas redes sociais",
                    "editing_tips": "Dicas de edição para maximizar o impacto (zoom, slow motion, música, cortes)",
                    "suggested_title": "Título viral pronto para usar nessa cena"
                }}
            ],
            "recommended_hashtags": "#anime #nomedoanime #hashtag1 #hashtag2"
        }}
    ],
    "posting_tips": [
        "Dica geral 1 sobre como postar esse tipo de conteúdo",
        "Dica geral 2",
        "Dica geral 3"
    ],
    "trending_keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"]
}}
Responda APENAS com o JSON, sem texto adicional.
"""


def build_anime_finder_followup_prompt(query: str, previous_recommendations: dict, chat_history: list = None) -> str:
    """Prompt para follow-up de perguntas específicas do Anime Finder."""
    prev_str = json.dumps(previous_recommendations, indent=2, ensure_ascii=False)
    history_str = ""
    if chat_history:
        history_str = "\n[HISTÓRICO DE PERGUNTAS E RESPOSTAS ANTERIORES]\n"
        for h in chat_history:
            history_str += f"Usuário: {h.get('user', '')}\nIA: {h.get('ai', '')}\n\n"

    return f"""{SYSTEM_CONTEXT}
Você é um especialista absoluto em ANIME.
O usuário fez uma busca anterior de animes e recebeu as seguintes recomendações:
```json
{prev_str}
```
{history_str}
Agora, o usuário tem uma dúvida adicional ou quer mais detalhes específicos:
Dúvida do usuário: "{query}"

INSTRUÇÕES:
1. Responda diretamente à dúvida do usuário em PORTUGUÊS DO BRASIL.
2. Seja específico, forneça SEMPRE o NÚMERO EXATO DO EPISÓDIO para qualquer cena sugerida.
3. Se ele pedir mais opções de animes parecidos com os recomendados, sugira novos mantendo os números exatos.
4. Retorne a resposta em formato JSON válido estruturado.

Retorne EXATAMENTE este formato JSON e nada mais:
{{
    "response": "Sua resposta explicativa e detalhada formatada em Markdown",
    "suggested_episodes": [
        {{
            "anime": "Nome do Anime",
            "episode": "Episódio X exato (ex: Episódio 131)",
            "scene_description": "Descrição detalhada da cena recomendada",
            "search_term": "Termo de busca para pesquisar no YouTube/Google",
            "why_viral": "Por que essa cena é viral",
            "suggested_title": "Título sugerido"
        }}
    ]
}}
"""


def build_episode_finder_prompt(category: str, name: str, theme: str, count: int = 5,
                                exclude_episodes: list = None, season: int = None) -> str:
    """Prompt para sugestão de episódios de uma obra específica (Anime ou Dorama)."""
    category_label = "ANIME" if category == "anime" else "DORAMA"
    exclude_str = ""
    if exclude_episodes:
        exclude_str = f"\n⚠️ ATENÇÃO: Você DEVE EXCLUIR os seguintes episódios: {', '.join(exclude_episodes)}."

    theme_examples = {
        "geral": "os momentos mais impactantes, emocionantes e memoráveis da obra",
        "acao": "cenas de luta épicas, confrontos intensos, demonstrações de poder ou batalhas marcantes",
        "engraçado": "momentos cômicos, piadas engraçadas, reações hilárias dos personagens ou situações embaraçosas",
        "teoria": "mistérios, revelações de segredos, momentos que dão margem a teorias de fãs ou pistas importantes da trama",
        "drama": "tensões dramáticas fortes, conflitos de relacionamento, revelações chocantes ou suspense intenso",
        "tristeza": "cenas tristes de choro, perdas de personagens queridos, separações dolorosas ou despedidas emocionantes",
        "romance": "momentos românticos de casal, primeiro beijo, declaração de amor, abraço protetor ou flertes fofos"
    }
    theme_desc = theme_examples.get(theme.lower(), f"momentos com o tema/foco em '{theme}'")
    season_context = f" (Temporada {season})" if season else ""
    full_name = f"{name}{season_context}"

    return f"""{SYSTEM_CONTEXT}
Você é um especialista absoluto em {category_label}. Você conhece a obra "{full_name}" profundamente, incluindo todos os episódios reais, números exatos, arcos principais e detalhes exatos das cenas.

TAREFA: O usuário quer sugestões de excelentes episódios do {category_label} "{full_name}" com momentos que se encaixem perfeitamente no tema/foco: "{theme}" ({theme_desc}) para criar cortes virais no TikTok/Reels/Shorts.{(' IMPORTANTE: o usuário quer especificamente episódios da Temporada ' + str(season) + '.') if season else ''}
Forneça até {count} episódios ideais.
{exclude_str}

⚠️ REGRAS OBRIGATÓRIAS:
1. SOMENTE recomende episódios reais e verídicos da obra "{name}". NÃO invente episódios.
2. Cada episódio sugerido deve conter o número exato (ex: "Episódio 10", "Episódio 131").
3. Para cada episódio, explique detalhadamente a cena/momento correspondente ao tema "{theme}" e por que ela é perfeita para postagem viral.
4. Forneça o termo de busca exato para o usuário pesquisar no YouTube ou Google (ex: "{name} episodio 10 cena").

Responda EXATAMENTE neste formato JSON:
{{
    "summary": "Resumo da busca de episódios de {name} focando no tema {theme}",
    "episodes": [
        {{
            "episode": "Número exato do episódio (ex: Episódio 10)",
            "arc_name": "Nome do Arco/Saga onde ocorre",
            "scene_description": "Descrição detalhada do momento/cena correspondente ao tema, personagens e ação.",
            "why_viral": "Explicação do apelo viral dessa cena e por que funciona para o tema pedido.",
            "search_term": "Termo de busca com o número do episódio e descrição para o YouTube/Google",
            "editing_tips": "Dicas de edição para maximizar o impacto visual e sonoro.",
            "suggested_title": "Título viral pronto para usar",
            "viral_potential": 90
        }}
    ]
}}
Responda APENAS com o JSON, sem texto adicional.
"""


def search_animes(query: str, genre: str = "", platform: str = "all",
                  count: int = 5, popularity: str = "any", era: str = "any",
                  log_cb=None, on_log=None, **kwargs) -> Dict[str, Any]:
    """Executa a busca de animes por tema/estilo usando a IA."""
    _log = on_log or log_cb
    if _log:
        _log("⛩️ Consultando IA sobre os melhores animes e episódios...")
    prompt = build_anime_finder_prompt(query, genre, platform, count, popularity, era)
    raw = call_ai_text(prompt, max_tokens=16384, log_cb=_log, on_log=_log)
    return _clean_json_response(raw)


def ask_anime_followup(query: str, previous_recommendations: dict, chat_history: list = None,
                       log_cb=None, on_log=None, **kwargs) -> Dict[str, Any]:
    """Processa pergunta de acompanhamento mantendo contexto."""
    _log = on_log or log_cb
    if _log:
        _log("💬 Processando dúvida com o especialista em anime...")
    prompt = build_anime_finder_followup_prompt(query, previous_recommendations, chat_history)
    raw = call_ai_text(prompt, max_tokens=8192, log_cb=_log, on_log=_log)
    return _clean_json_response(raw)


def search_episodes(category: str, name: str, theme: str, count: int = 5,
                    exclude_episodes: list = None, season: int = None,
                    log_cb=None, on_log=None, **kwargs) -> Dict[str, Any]:
    """Busca episódios exatos de uma obra específica."""
    _log = on_log or log_cb
    if _log:
        _log(f"🔍 Mapeando episódios de {name} no tema '{theme}'...")
    prompt = build_episode_finder_prompt(category, name, theme, count, exclude_episodes, season)
    raw = call_ai_text(prompt, max_tokens=16384, log_cb=_log, on_log=_log)
    return _clean_json_response(raw)
