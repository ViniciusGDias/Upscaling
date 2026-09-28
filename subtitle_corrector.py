"""
subtitle_corrector.py - Dicionario e Corretor Automatico de Nomes de Anime e Termos Japoneses
Corrige automaticamente falhas e trocas foneticas do Whisper (Groq/OpenAI) em nomes de animes.
Permite adicao persistente de novas palavras pelo usuario.
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Any


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


DICT_FILE = get_base_dir() / "anime_dictionary.json"

DEFAULT_CORRECTIONS = {
    # One Piece
    "cheira roxo": "Shirahoshi",
    "cheira rox": "Shirahoshi",
    "chira roxo": "Shirahoshi",
    "chirahoshi": "Shirahoshi",
    "lufe": "Luffy",
    "lufi": "Luffy",
    "sandy": "Sanji",
    "sanji": "Sanji",
    "zoro": "Zoro",
    "solon": "Zoro",
    "usopp": "Usopp",
    "usop": "Usopp",
    "nami": "Nami",
    "robin": "Robin",
    "chopper": "Chopper",
    "franky": "Franky",
    "brook": "Brook",
    "jinbe": "Jinbe",
    "jimbei": "Jinbe",
    "netuno": "Netuno",
    "neptuno": "Netuno",
    "kaido": "Kaido",
    "kaidou": "Kaido",
    "big mom": "Big Mom",
    "shanks": "Shanks",
    "barba branca": "Barba Branca",
    "barba negra": "Barba Negra",
    "teach": "Teach",
    "kurohige": "Kurohige",
    "gol d roger": "Gol D. Roger",
    "roger": "Roger",
    "ace": "Ace",
    "sabo": "Sabo",
    "akainu": "Akainu",
    "aokiji": "Aokiji",
    "kizaru": "Kizaru",
    "fujitora": "Fujitora",
    "gear 5": "Gear 5",
    "gear five": "Gear 5",
    "gear 4": "Gear 4",
    "akuma no mi": "Akuma no Mi",
    "haki": "Haki",
    "haki do conquistador": "Haki do Conquistador",

    # Bleach
    "ichigo": "Ichigo",
    "kurosaki": "Kurosaki",
    "urahara": "Urahara",
    "kisuke": "Kisuke",
    "aizen": "Aizen",
    "sosuke aizen": "Sosuke Aizen",
    "shinji": "Shinji",
    "hirako": "Hirako",
    "kenpachi": "Kenpachi",
    "zaraki": "Zaraki",
    "byakuya": "Byakuya",
    "kuchiki": "Kuchiki",
    "rukia": "Rukia",
    "renji": "Renji",
    "toshiro": "Toshiro",
    "hitsugaya": "Hitsugaya",
    "yamamoto": "Yamamoto",
    "genryusai": "Genryusai",
    "shunsui": "Shunsui",
    "kyoraku": "Kyoraku",
    "ulquiorra": "Ulquiorra",
    "grimmjow": "Grimmjow",
    "yhwach": "Yhwach",
    "yuha": "Yhwach",
    "yuha bacha": "Yhwach",
    "zanpakuto": "Zanpakuto",
    "bankai": "Bankai",
    "shikai": "Shikai",
    "shinigami": "Shinigami",
    "espada": "Espada",
    "hollow": "Hollow",
    "quincy": "Quincy",

    # Naruto / Boruto
    "naruto": "Naruto",
    "sasuke": "Sasuke",
    "sakura": "Sakura",
    "kakashi": "Kakashi",
    "itachi": "Itachi",
    "madara": "Madara",
    "obito": "Obito",
    "hashirama": "Hashirama",
    "tobirama": "Tobirama",
    "minato": "Minato",
    "jiraiya": "Jiraiya",
    "tsunade": "Tsunade",
    "orochimaru": "Orochimaru",
    "pain": "Pain",
    "nagato": "Nagato",
    "konan": "Konan",
    "sharingan": "Sharingan",
    "rinnegan": "Rinnegan",
    "byakugan": "Byakugan",
    "rasengan": "Rasengan",
    "chidori": "Chidori",

    # Jujutsu Kaisen
    "sukuna": "Sukuna",
    "gojo": "Gojo",
    "satoru": "Satoru",
    "itadori": "Itadori",
    "yuji": "Yuji",
    "megumi": "Megumi",
    "fushiguro": "Fushiguro",
    "nobara": "Nobara",
    "kugisaki": "Kugisaki",
    "nanami": "Nanami",
    "maki": "Maki",
    "toji": "Toji",
    "yuta": "Yuta",
    "okkotsu": "Okkotsu",
    "geto": "Geto",
    "kenjaku": "Kenjaku",
    "mahito": "Mahito",
    "ryomen sukuna": "Ryomen Sukuna",

    # Dragon Ball
    "goku": "Goku",
    "vegeta": "Vegeta",
    "gohan": "Gohan",
    "trunks": "Trunks",
    "piccolo": "Piccolo",
    "kuririn": "Kuririn",
    "freeza": "Freeza",
    "cell": "Cell",
    "majin buu": "Majin Buu",
    "kamehameha": "Kamehameha",
    "super saiyajin": "Super Saiyajin",
    "saiyajin": "Saiyajin",

    # Attack on Titan / Hunter x Hunter / Outros
    "eren": "Eren",
    "mikasa": "Mikasa",
    "armin": "Armin",
    "levi": "Levi",
    "gon": "Gon",
    "killua": "Killua",
    "kurapika": "Kurapika",
    "leorio": "Leorio",
    "hisoka": "Hisoka",
    "tanjiro": "Tanjiro",
    "nezuko": "Nezuko",
    "zenitsu": "Zenitsu",
    "inosuke": "Inosuke",
    "muzan": "Muzan",
}


def load_dictionary() -> Dict[str, str]:
    """Carrega o dicionario do disco ou cria o padrao."""
    if DICT_FILE.exists():
        try:
            with open(DICT_FILE, "r", encoding="utf-8") as f:
                custom = json.load(f)
                combined = dict(DEFAULT_CORRECTIONS)
                combined.update(custom)
                return combined
        except Exception:
            pass
    # Salva o arquivo padrao inicial
    save_dictionary(DEFAULT_CORRECTIONS)
    return dict(DEFAULT_CORRECTIONS)


def save_dictionary(mapping: Dict[str, str]) -> bool:
    """Salva o dicionario no arquivo JSON."""
    try:
        with open(DICT_FILE, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def add_correction_term(wrong: str, correct: str) -> bool:
    """Adiciona ou atualiza um termo de correcao."""
    wrong = wrong.strip().lower()
    correct = correct.strip()
    if not wrong or not correct:
        return False
    current = load_dictionary()
    current[wrong] = correct
    return save_dictionary(current)


def correct_phrase(text: str, custom_dict: Dict[str, str] = None) -> str:
    """
    Substitui termos incorretos no texto por termos corretos do dicionario.
    Ordena por tamanho decrescente para priorizar expressoes compostas (ex: 'gear five' antes de 'gear').
    """
    if not text:
        return ""
    d = custom_dict if custom_dict is not None else load_dictionary()
    
    # Ordena termos do maior para o menor em numero de caracteres
    sorted_keys = sorted(d.keys(), key=lambda k: len(k), reverse=True)

    result = text
    for wrong in sorted_keys:
        correct = d[wrong]
        pattern = re.compile(rf"\b{re.escape(wrong)}\b", re.IGNORECASE)
        result = pattern.sub(correct, result)

    return result


def apply_corrections_to_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aplica o dicionario em uma lista de segmentos de legendas."""
    d = load_dictionary()
    corrected_items = []
    for item in items:
        new_item = dict(item)
        if "text" in new_item:
            new_item["text"] = correct_phrase(new_item["text"], d)
        if "word" in new_item:
            new_item["word"] = correct_phrase(new_item["word"], d)
        corrected_items.append(new_item)
    return corrected_items


if __name__ == "__main__":
    d = load_dictionary()
    test_text = "O lufe foi falar com a cheira roxo e depois o sandy apareceu com o aizen"
    print("Original:", test_text)
    print("Corrigido:", correct_phrase(test_text, d))
