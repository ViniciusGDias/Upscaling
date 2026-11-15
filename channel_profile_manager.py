"""
channel_profile_manager.py - Gerenciador de Perfis de Canais para o Studio Pipeline
Permite alternar entre diferentes canais (ex: Animax, Vinny, ViniAnimes),
mantendo exatamente os mesmos parâmetros de layout e enquadramento de vídeo,
mas personalizando foto de perfil, marca d'água, cor do título e texto inferior (CTA).
"""

import os
import sys
import json
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional
from PIL import Image, ImageDraw


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


PROFILES_FILE = get_base_dir() / "channel_profiles.json"
USER_STYLE_FILE = get_base_dir() / "user_style.json"

DEFAULT_PROFILES: Dict[str, Dict[str, Any]] = {
    "animax": {
        "id": "animax",
        "name": "Animax",
        "handle": "@animax_97",
        "verified": True,
        "profile_png": "assets/Perfil_1.png",
        "watermark_text": "@ANIMAX_97",
        "watermark_opacity": 0.38,
        "title_color": "#FFFFFF",
        "cta_lines": [
            "FINALMENTE O ALGORITMO TE TROUXE",
            "PRO CANAL CERTO! 🚀 SE INSCREVE"
        ],
        "description": "Perfil clássico oficial Animax com selo de verificado e tema branco."
    },
    "vinny": {
        "id": "vinny",
        "name": "Vinny",
        "handle": "@vinny.animes",
        "verified": False,
        "profile_png": "assets/Perfil_Vinny.png",
        "watermark_text": "@VINNY.ANIMES",
        "watermark_opacity": 0.38,
        "title_color": "#00A8FF",
        "cta_lines": [
            "FINALMENTE ENCONTROU O",
            "SEU CANAL DE ANIMES.",
            "SE INSCREVE!"
        ],
        "description": "Perfil do canal Vinny com avatar circular Aizen e títulos em azul cyan vibrante."
    },
    "vinianimes": {
        "id": "vinianimes",
        "name": "ViniAnimes",
        "handle": "@ViniAnime__s",
        "verified": False,
        "profile_png": "assets/Perfil_ViniAnimes.png",
        "watermark_text": "@VINIANIMES",
        "watermark_opacity": 0.38,
        "title_color": "#FF1E27",
        "cta_lines": [
            "VOCÊ ENCONTROU SEU CANTINHO",
            "DE ANIMES. SE INSCREVE!"
        ],
        "description": "Perfil do canal ViniAnimes com avatar circular Shizuku e títulos em vermelho carmesim."
    }
}


def make_circular_avatar(src_path: str, dst_path: str, size: int = 270) -> str:
    """Cria um avatar perfeitamente circular com anti-aliasing 4x supersampled e fundo transparente."""
    im = Image.open(src_path).convert("RGBA")
    w, h = im.size
    min_dim = min(w, h)
    left = (w - min_dim) // 2
    top = (h - min_dim) // 2
    sq = im.crop((left, top, left + min_dim, top + min_dim))

    ss = size * 4
    sq_large = sq.resize((ss, ss), Image.Resampling.LANCZOS)
    mask = Image.new("L", (ss, ss), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, ss, ss), fill=255)

    out_large = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))
    out_large.paste(sq_large, (0, 0), mask)
    final = out_large.resize((size, size), Image.Resampling.LANCZOS)

    dst_p = Path(dst_path)
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    final.save(dst_p, "PNG")
    return str(dst_p)


def load_profiles_data() -> Dict[str, Any]:
    """Carrega o arquivo channel_profiles.json, criando-o se não existir."""
    if not PROFILES_FILE.exists():
        data = {
            "active_profile": "animax",
            "profiles": DEFAULT_PROFILES
        }
        save_profiles_data(data)
        return data

    try:
        with open(PROFILES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "profiles" not in data or not isinstance(data["profiles"], dict):
                data["profiles"] = DEFAULT_PROFILES
            # Garante que os perfis padrão existam
            for k, def_p in DEFAULT_PROFILES.items():
                if k not in data["profiles"]:
                    data["profiles"][k] = def_p
            if "active_profile" not in data or data["active_profile"] not in data["profiles"]:
                data["active_profile"] = "animax"
            return data
    except Exception as e:
        print(f"[channel_profile_manager] Erro ao carregar perfis ({e}). Restaurando padrão.")
        data = {
            "active_profile": "animax",
            "profiles": DEFAULT_PROFILES
        }
        save_profiles_data(data)
        return data


def save_profiles_data(data: Dict[str, Any]):
    """Salva os perfis no arquivo channel_profiles.json."""
    try:
        PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PROFILES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[channel_profile_manager] Erro ao salvar perfis: {e}")


def get_all_profiles() -> Dict[str, Dict[str, Any]]:
    return load_profiles_data().get("profiles", DEFAULT_PROFILES)


def get_active_profile_id() -> str:
    return load_profiles_data().get("active_profile", "animax")


def get_active_profile() -> Dict[str, Any]:
    data = load_profiles_data()
    pid = data.get("active_profile", "animax")
    return data.get("profiles", {}).get(pid, DEFAULT_PROFILES.get("animax"))


def set_active_profile_id(profile_id: str) -> bool:
    data = load_profiles_data()
    if profile_id in data.get("profiles", {}):
        data["active_profile"] = profile_id
        save_profiles_data(data)
        # Sincroniza o user_style.json com o perfil selecionado
        sync_profile_to_user_style(profile_id)
        return True
    return False


def build_full_style_dict(profile_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Constrói a estrutura completa de estilo compatível com user_style.json e subtitle_renderer.
    Preserva rigorosamente todos os parâmetros padrão do Animax:
    - Resolução 1080x1920, 60fps
    - Zoom 187%, blur de fundo 30
    - Lovely Scream Queens (76px legendas, 60px título, 62px watermark, 44px cta)
    - Posicionamentos padronizados
    Apenas personaliza:
    - Foto do canal
    - Marca d'água
    - Texto inferior (CTA)
    - Cor do título
    - Nome e handle do canal (+ selo de verificado)
    """
    cta_lines = profile_data.get("cta_lines", [])
    if not cta_lines:
        cta_lines = [
            "FINALMENTE O ALGORITMO TE TROUXE",
            "PRO CANAL CERTO! 🚀 SE INSCREVE"
        ]

    prof_img = profile_data.get("profile_png", "assets/Perfil_1.png")

    style_dict = {
        "subtitle": {
            "font_name": "Lovely Scream Queens",
            "font_path": "assets/Queens.otf",
            "size_px": 76,
            "color": "#FFFFFF",
            "stroke_color": "#000000",
            "stroke_width_px": 6,
            "position_y_percent": 50,
            "alignment": "center",
            "capitalization": "upper",
            "max_words_per_line": 3,
            "style_preset": "anime_fx_pro",
            "pop_animation": True,
            "highlight_color": "#00FFFF"
        },
        "watermark_text": {
            "text": profile_data.get("watermark_text", "@ANIMAX_97"),
            "position": "center",
            "size_px": 62,
            "opacity": float(profile_data.get("watermark_opacity", 0.38)),
            "color": "#FFFFFF",
            "font_name": "Lovely Scream Queens"
        },
        "watermark_png": {
            "path": prof_img,
            "position": "top-left",
            "opacity": 1.0,
            "size_percent": 13
        },
        "channel_header": {
            "name": profile_data.get("name", "Animax"),
            "verified": bool(profile_data.get("verified", True)),
            "handle": profile_data.get("handle", "@animax_97"),
            "profile_png": prof_img,
            "size_px": 225,
            "font_color": "#FFFFFF"
        },
        "title_overlay": {
            "font_name": "Lovely Scream Queens",
            "font_path": "assets/Queens.otf",
            "size_px": 60,
            "color": profile_data.get("title_color", "#FFFFFF"),
            "stroke_color": "#000000",
            "stroke_width_px": 6,
            "position_y_percent": 20,
            "capitalization": "upper"
        },
        "cta_bar": {
            "line1": cta_lines[0] if len(cta_lines) > 0 else "FINALMENTE O ALGORITMO TE TROUXE",
            "line2": cta_lines[1] if len(cta_lines) > 1 else "PRO CANAL CERTO! 🚀 SE INSCREVE",
            "line3": cta_lines[2] if len(cta_lines) > 2 else "",
            "lines": cta_lines,
            "font_name": "Lovely Scream Queens",
            "font_path": "assets/Queens.otf",
            "background_color": "transparent",
            "text_color": "#FFFFFF"
        },
        "video_style": {
            "scale_percent": 187,
            "blur_sides": True,
            "blur_strength": 30,
            "format": "9:16",
            "resolution": "1080x1920",
            "fps": 60
        },
        "_meta": {
            "profile_id": profile_data.get("id", "animax"),
            "profile_name": profile_data.get("name", "Animax"),
            "font_family": "Lovely Scream Queens"
        }
    }
    return style_dict


def sync_profile_to_user_style(profile_id: Optional[str] = None):
    """Grava as configurações do perfil no arquivo user_style.json para interoperabilidade global."""
    data = load_profiles_data()
    pid = profile_id or data.get("active_profile", "animax")
    prof = data.get("profiles", {}).get(pid, DEFAULT_PROFILES.get("animax"))
    style_dict = build_full_style_dict(prof)
    try:
        with open(USER_STYLE_FILE, "w", encoding="utf-8") as f:
            json.dump(style_dict, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[channel_profile_manager] Erro ao sincronizar user_style.json: {e}")


def save_or_update_profile(profile_dict: Dict[str, Any]) -> str:
    """Salva ou atualiza um perfil no gerenciador."""
    data = load_profiles_data()
    pid = profile_dict.get("id")
    if not pid:
        # Gera id a partir do nome
        import re
        base_id = re.sub(r"[^a-zA-Z0-9_]", "", profile_dict.get("name", "perfil").lower())
        pid = base_id or "custom_channel"
        counter = 1
        while pid in data.get("profiles", {}):
            pid = f"{base_id}_{counter}"
            counter += 1
        profile_dict["id"] = pid

    data["profiles"][pid] = profile_dict
    save_profiles_data(data)
    if data.get("active_profile") == pid:
        sync_profile_to_user_style(pid)
    return pid


def delete_profile(profile_id: str) -> bool:
    """Exclui um perfil customizado (impede exclusão do Animax padrão)."""
    if profile_id == "animax":
        return False
    data = load_profiles_data()
    if profile_id in data.get("profiles", {}):
        del data["profiles"][profile_id]
        if data.get("active_profile") == profile_id:
            data["active_profile"] = "animax"
            sync_profile_to_user_style("animax")
        save_profiles_data(data)
        return True
    return False


if __name__ == "__main__":
    p_data = load_profiles_data()
    print("Perfis carregados com sucesso:")
    for k, v in p_data["profiles"].items():
        print(f" - [{k}] {v['name']} ({v['handle']}) | Título: {v['title_color']} | Watermark: {v['watermark_text']}")
    sync_profile_to_user_style(p_data["active_profile"])
    print(f"user_style.json sincronizado com perfil ativo: {p_data['active_profile']}")
