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
                              count: int = 5, popularity: str = "any", era: str = "any",
                              exclude_animes: list = None) -> str:
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

    exclude_clause = ""
    if exclude_animes:
        clean_ex = [str(x).strip() for x in exclude_animes if str(x).strip()]
        if clean_ex:
            exclude_clause = (
                f"\n🚫 ANIMES JÁ VISTOS / USADOS PELO USUÁRIO (ESTRITAMENTE PROIBIDO REPETIR):\n"
                f"{', '.join(clean_ex)}\n"
                f"⚠️ ATENÇÃO: O usuário já viu os animes acima. Sugira animes TOTALMENTE DIFERENTES e novos!"
            )

    return f"""{SYSTEM_CONTEXT}
Você é um especialista absoluto em ANIME. Conhece os animes mais populares, seus episódios exatos, arcos principais,
e as cenas mais icônicas que a comunidade anime reconhece como memoráveis.

TAREFA: O usuário quer encontrar os melhores animes e os EPISÓDIOS EXATOS para baixar e postar conteúdo viral em {platform_name}.
Pedido do usuário: "{query}"
{genre_instruction}{popularity_instruction}{era_instruction}{exclude_clause}

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
                                exclude_episodes: list = None, season: int = None,
                                details: str = "") -> str:
    """Prompt com verificação factual rígida e anti-alucinação para episódios de uma obra específica."""
    category_label = "ANIME" if category == "anime" else "DORAMA"
    exclude_str = ""
    if exclude_episodes:
        clean_excludes = [str(x).strip() for x in exclude_episodes if str(x).strip()]
        if clean_excludes:
            exclude_str = (
                f"\n🚫 EPISÓDIOS JÁ VISTOS / USADOS PELO USUÁRIO (ESTRITAMENTE PROIBIDO REPETIR):\n"
                f"{', '.join(clean_excludes)}\n"
                f"⚠️ REGRA CRÍTICA DE EXCLUSÃO: O usuário já utilizou ou não quer os episódios acima. "
                f"Você NÃO PODE sugerir NENHUM desses episódios listados! Traga episódios TOTALMENTE NOVOS e diferentes!\n"
            )

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

    details_section = ""
    if details and details.strip():
        details_section = (
            f"\n🎯 PEDIDO ESPECÍFICO / PREFERÊNCIAS DO USUÁRIO:\n"
            f"\"{details.strip()}\"\n"
            f"⚠️ PRIORIDADE MÁXIMA: O usuário descreveu especificamente o tipo de episódio que deseja. "
            f"Se ele pediu episódios pouco populares/subestimados, raros, engraçados, ou focados em determinado personagem/situação, "
            f"você DEVE filtrar e selecionar episódios que atendam a esses critérios exatos!\n"
        )

    return f"""{SYSTEM_CONTEXT}
Você é um especialista enciclopédico absoluto em {category_label}. Você conhece a obra "{full_name}" profundamente, incluindo a numeração canônica oficial de cada episódio, títulos originais em Japonês/Português/Inglês, arcos e o minuto exato das cenas.

TAREFA: O usuário quer sugestões de excelentes episódios do {category_label} "{full_name}" com momentos que se encaixem no tema/foco: "{theme}" ({theme_desc}) para criar cortes virais no TikTok/Reels/Shorts.{details_section}{(' IMPORTANTE: o usuário quer especificamente episódios da Temporada ' + str(season) + '.') if season else ''}
Forneça até {count} episódios ideais.
{exclude_str}

⚠️ REGRAS RIGOROSAS DE PRECISÃO FÁCTICA (ANTI-ERRO DE EPISÓDIO):
1. PRECISÃO EXATA DO NÚMERO CANÔNICO:
   - Você DEVE validar o número canônico exato da transmissão oficial da obra "{name}".
   - Pense no TÍTULO OFICIAL DO EPISÓDIO antes de definir o número (ex: no Dragon Ball Z, a autoescola de Goku e Piccolo é EXATAMENTE o Episódio 125 "Uma Lição Difícil"; em Naruto Shippuden, Kakashi vs Obito é EXATAMENTE o Episódio 375; em Death Note, a morte de L é EXATAMENTE o Episódio 25).
   - NUNCA chute ou invente números aproximados. O número do episódio DEVE corresponder 100% à cena descrita.
2. TÍTULO OFICIAL DO EPISÓDIO OBRIGATÓRIO ("episode_title"):
   - Forneça o título oficial do episódio (em Português ou Inglês oficial). O título oficial serve como confirmação factual para o usuário e evita qualquer confusão entre versões de TV ou mangá.
3. MINUTO APROXIMADO DA CENA ("approx_time"):
   - Indique o intervalo ou minuto aproximado dentro do episódio em que a cena acontece (ex: "12:30 - 15:40").
4. TERMO DE BUSCA NO YOUTUBE À PROVA DE FALHAS ("search_term"):
   - O termo de busca DEVE conter: [Nome da Obra] ep [Número] [Nome da cena / Título oficial / Personagens principais]
   - Exemplo: "{name} ep 125 autoescola goku piccolo"
   - Exemplo: "{name} ep 375 kakashi vs obito luta kamui"
   - Isso garante que ao clicar no botão "Buscar no YouTube", o usuário caia no vídeo exato da cena mesmo se houver cortes na TV!

Responda EXATAMENTE neste formato JSON:
{{
    "summary": "Resumo da busca de episódios de {name} atendendo ao tema '{theme}' e às preferências solicitadas",
    "episodes": [
        {{
            "episode_number": 125,
            "episode": "Episódio 125",
            "episode_title": "Título Oficial do Episódio (ex: Uma Lição Difícil)",
            "arc_name": "Nome do Arco/Saga onde ocorre",
            "approx_time": "12:30 - 16:00",
            "scene_description": "Descrição detalhada do momento/cena correspondente ao tema, personagens e ação.",
            "why_viral": "Explicação do apelo viral dessa cena e por que atende ao pedido do usuário.",
            "search_term": "Termo de busca com anime + ep número + palavras da cena para o YouTube/Google",
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
                  exclude_animes: list = None,
                  log_cb=None, on_log=None, **kwargs) -> Dict[str, Any]:
    """Executa a busca de animes por tema/estilo usando a IA com suporte a exclusão."""
    _log = on_log or log_cb
    if _log:
        ex_str = f" (excluindo {len(exclude_animes)} anteriores)" if exclude_animes else ""
        _log(f"⛩️ Consultando IA sobre os melhores animes e episódios{ex_str}...")
    prompt = build_anime_finder_prompt(query, genre, platform, count, popularity, era, exclude_animes=exclude_animes)
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
                    details: str = "",
                    log_cb=None, on_log=None, **kwargs) -> Dict[str, Any]:
    """Busca episódios exatos de uma obra específica com suporte a descrição extra / preferências."""
    _log = on_log or log_cb
    det_msg = f" | Detalhes: '{details}'" if details and details.strip() else ""
    if _log:
        _log(f"🔍 Mapeando episódios de {name} no tema '{theme}'{det_msg}...")
    prompt = build_episode_finder_prompt(category, name, theme, count, exclude_episodes, season, details=details)
    raw = call_ai_text(prompt, max_tokens=16384, log_cb=_log, on_log=_log)
    return _clean_json_response(raw)
