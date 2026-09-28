"""
style_analyzer.py - Animax Style Learning AI
Le todos os projetos CapCut do canal Animax e extrai padroes de estilo para
gerar o user_style.json que o Studio Pipeline vai usar.
"""

import os
import sys
import json
import base64
import subprocess
import time
import statistics
import tempfile
from pathlib import Path
from collections import Counter


CAPCUT_PROJECTS_ROOT = Path(os.environ["LOCALAPPDATA"]) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
ANIMAX_PROJECT = CAPCUT_PROJECTS_ROOT / "Animax-copia-copia"
TRAINING_VIDEOS_DIR = Path("D:/Old Animax")

# When running as compiled EXE, save user_style.json next to the .exe (not inside _internal)
# When running as script, save next to style_analyzer.py
if getattr(sys, "frozen", False):
    _BASE_DIR = Path(sys.executable).parent
else:
    _BASE_DIR = Path(__file__).parent
OUTPUT_STYLE_FILE = _BASE_DIR / "user_style.json"

CANVAS_W = 1080
CANVAS_H = 1920


def load_all_drafts(project_root):
    drafts = []
    for f in project_root.rglob("draft_content.json"):
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fp:
                data = json.load(fp)
                data["_source_file"] = str(f)
                drafts.append(data)
        except Exception:
            pass
    return drafts


def extract_text_segments(drafts):
    segments = []
    for draft in drafts:
        tracks = draft.get("tracks", [])
        materials_texts = {m["id"]: m for m in draft.get("materials", {}).get("texts", [])}
        canvas_h = draft.get("canvas_config", {}).get("height", CANVAS_H) or CANVAS_H

        for track in tracks:
            if track.get("type") != "text":
                continue
            for seg in track.get("segments", []):
                mat_id = seg.get("material_id", "")
                mat = materials_texts.get(mat_id, {})
                if not mat:
                    continue

                content_raw = mat.get("content", "{}")
                try:
                    content = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
                except Exception:
                    content = {}

                text = content.get("text", mat.get("text", ""))
                styles = content.get("styles", [{}])
                style0 = styles[0] if styles else {}

                font_info = style0.get("font", {})
                font_path = font_info.get("path", "")
                font_name = Path(font_path).stem if font_path else mat.get("font_name", "")

                fill = style0.get("fill", {})
                color_val = fill.get("content", {}).get("solid", {}).get("color", [1, 1, 1])
                if isinstance(color_val, list) and len(color_val) >= 3:
                    color_hex = "#{:02X}{:02X}{:02X}".format(
                        int(color_val[0] * 255),
                        int(color_val[1] * 255),
                        int(color_val[2] * 255),
                    )
                else:
                    color_hex = mat.get("text_color", "#FFFFFF")

                size_capcut = style0.get("size", mat.get("font_size", 15))
                clip_attrs = seg.get("clip", {})
                pos = clip_attrs.get("transform", {})
                pos_x = pos.get("x", 0.5)
                pos_y = pos.get("y", 0.5)
                duration_us = seg.get("target_timerange", {}).get("duration", 0)
                is_subtitle = len(text.split()) <= 8 and duration_us < 5_000_000

                segments.append({
                    "text": text,
                    "font_name": font_name,
                    "font_path": font_path,
                    "color": color_hex,
                    "size_capcut": size_capcut,
                    "pos_x": pos_x,
                    "pos_y": pos_y,
                    "stroke_color": mat.get("stroke_color", ""),
                    "stroke_width": mat.get("stroke_width", 0),
                    "is_subtitle": is_subtitle,
                    "duration_us": duration_us,
                    "canvas_h": canvas_h,
                    "use_letter_color": style0.get("useLetterColor", False),
                })
    return segments


def capcut_size_to_px(size_capcut, canvas_h=1920):
    return max(24, int(size_capcut * (canvas_h / 400)))


def most_common(lst, default=None):
    if not lst:
        return default
    return Counter(lst).most_common(1)[0][0]


def analyze_style(segments):
    subtitles = [s for s in segments if s["is_subtitle"]]
    statics = [s for s in segments if not s["is_subtitle"]]

    sub_fonts = [s["font_name"] for s in subtitles if s["font_name"]]
    sub_colors = [s["color"] for s in subtitles if s["color"]]
    sub_sizes = [capcut_size_to_px(s["size_capcut"], s["canvas_h"]) for s in subtitles if s["size_capcut"]]
    sub_pos_y = [s["pos_y"] for s in subtitles if s["pos_y"]]

    all_texts = [s["text"] for s in subtitles if s["text"]]
    upper_count = sum(1 for t in all_texts if t == t.upper() and t.strip())
    cap_style = "upper" if upper_count > len(all_texts) * 0.6 else "title"

    word_counts = [len(line.split()) for t in all_texts for line in t.split("\n") if line.strip()]

    watermark_text = ""
    cta_text = ""
    font_paths = {}
    cta_fonts = []

    for s in segments:
        if s["font_name"] and s["font_path"]:
            font_paths[s["font_name"]] = s["font_path"]

    for s in statics:
        text = s["text"].strip()
        if text.startswith("@") and not watermark_text:
            watermark_text = text
        elif len(text) > 20 and not cta_text:
            cta_text = text
        if len(text) > 20 and s["font_name"]:
            cta_fonts.append(s["font_name"])

    dominant_font = most_common(sub_fonts, "Queens")

    return {
        "subtitle": {
            "font_name": dominant_font,
            "font_path": font_paths.get(dominant_font, ""),
            "size_px": int(statistics.median(sub_sizes)) if sub_sizes else 72,
            "color": most_common(sub_colors, "#FFFFFF"),
            "stroke_color": "#000000",
            "stroke_width_px": 4,
            "position_y_percent": int(statistics.median([y * 100 for y in sub_pos_y])) if sub_pos_y else 60,
            "alignment": "center",
            "capitalization": cap_style,
            "max_words_per_line": int(statistics.median(word_counts)) if word_counts else 4,
            "highlight_color": "#00FFFF",
        },
        "watermark_text": {
            "text": watermark_text or "@ANIMAX_97",
            "position": "center",
            "opacity": 0.25,
            "color": "#FFFFFF",
            "font_name": dominant_font,
        },
        "watermark_png": {
            "path": str(TRAINING_VIDEOS_DIR / "Perfil 1.png"),
            "position": "top-left",
            "opacity": 1.0,
            "size_percent": 12,
        },
        "channel_header": {
            "name": "Animax",
            "verified": True,
            "profile_png": str(TRAINING_VIDEOS_DIR / "Perfil 1.png"),
            "font_name": dominant_font,
            "font_color": "#FFFFFF",
        },
        "title_overlay": {
            "font_name": dominant_font,
            "font_path": font_paths.get(dominant_font, ""),
            "size_px": int(statistics.median(sub_sizes) * 1.2) if sub_sizes else 86,
            "color": "#FFFFFF",
            "stroke_color": "#000000",
            "stroke_width_px": 5,
            "position_y_percent": 20,
            "capitalization": "upper",
        },
        "cta_bar": {
            "text": cta_text or "Finalmente o algoritmo te trouxe\npro canal certo! Rocket Se inscreve ai!",
            "font_name": most_common(cta_fonts, dominant_font),
            "font_path": font_paths.get(most_common(cta_fonts, dominant_font) or dominant_font, ""),
            "background_color": "#F5E6D0",
            "text_color": "#2C1810",
            "height_percent": 18,
        },
        "video_style": {
            "blur_sides": True,
            "blur_strength": 20,
            "format": "9:16",
            "resolution": "1080x1920",
            "fps": 60,
        },
        "_meta": {
            "analyzed_segments": len(segments),
            "subtitle_segments": len(subtitles),
            "static_segments": len(statics),
            "font_paths": font_paths,
        }
    }


def _safe_print(msg):
    """Print that survives Windows cp1252 encoding."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode())


def _extract_frame(video_path, timestamp_sec, out_path, ffmpeg="ffmpeg"):
    """Extract a single frame from video at timestamp."""
    ffmpeg_bin = str(Path(__file__).parent / "bin" / "ffmpeg.exe")
    if not Path(ffmpeg_bin).exists():
        ffmpeg_bin = "ffmpeg"
    try:
        subprocess.run(
            [ffmpeg_bin, "-ss", str(timestamp_sec), "-i", str(video_path),
             "-frames:v", "1", "-q:v", "3", "-y", str(out_path)],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            timeout=30,
        )
        return Path(out_path).exists()
    except Exception:
        return False


def analyze_videos_with_gemini(on_log=None, gemini_api_key=None, num_videos=5):
    """
    Usa Gemini Vision para analisar os N videos mais recentes de D:/Old Animax
    e extrair padroes visuais de legenda, cores, posicoes.
    Retorna dict com observacoes consolidadas.
    """
    def log(msg):
        msg_str = str(msg)
        if on_log:
            try:
                on_log(msg_str)
            except UnicodeEncodeError:
                try:
                    on_log(msg_str.encode("ascii", errors="replace").decode())
                except Exception:
                    pass
            except Exception:
                pass
        else:
            _safe_print(msg_str)

    if not TRAINING_VIDEOS_DIR.exists():
        log(f"Pasta de videos nao encontrada: {TRAINING_VIDEOS_DIR}")
        return {}

    # Get most recent videos
    videos = sorted(
        [v for v in TRAINING_VIDEOS_DIR.glob("*.mp4")],
        key=lambda v: v.stat().st_mtime,
        reverse=True
    )[:num_videos]

    if not videos:
        log("Nenhum video encontrado para analise visual")
        return {}

    log(f"Analisando {len(videos)} videos mais recentes com Gemini Vision...")

    # Extract clean list of Gemini API keys
    keys_pool = []
    def _add_raw_keys(raw_str):
        if not raw_str:
            return
        for k in str(raw_str).replace(";", ",").split(","):
            clean_k = k.strip().strip('"\'')
            if clean_k and "sua_chave" not in clean_k.lower() and clean_k not in keys_pool:
                keys_pool.append(clean_k)

    if gemini_api_key:
        _add_raw_keys(gemini_api_key)

    if not keys_pool:
        _add_raw_keys(os.environ.get("GEMINI_API_KEY", ""))

    if not keys_pool:
        try:
            from settings_manager import load_app_settings
            s = load_app_settings()
            for k in s.get("gemini_keys", []):
                _add_raw_keys(k)
        except Exception:
            pass

    if not keys_pool:
        # Search possible .env files
        candidates = [
            Path(sys.executable).parent / ".env" if getattr(sys, "frozen", False) else None,
            Path(__file__).parent / ".env",
            Path.cwd() / ".env",
        ]
        for c in candidates:
            if c and c.exists():
                try:
                    for line in c.read_text(encoding="utf-8", errors="ignore").splitlines():
                        if line.startswith("GEMINI_API_KEY="):
                            _add_raw_keys(line.split("=", 1)[1])
                except Exception:
                    pass
            if keys_pool:
                break

    if not keys_pool:
        log("Chave Gemini nao encontrada - pulando analise visual")
        return {}

    log(f"Chave(s) Gemini carregada(s): {len(keys_pool)} chave(s) disponivel(is)")

    tmp_dir = tempfile.mkdtemp(prefix="style_analysis_")
    visual_observations = []
    active_key_idx = 0

    candidate_models = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-flash-lite-latest"]

    try:
        import urllib.request
        import urllib.error

        # Analyze multiple frames per video at different timestamps
        timestamps = [5, 15, 25]  # seconds

        for i, video in enumerate(videos):
            log(f"  [{i+1}/{len(videos)}] {video.name[:50]}...")

            for ts in timestamps:
                frame_path = Path(tmp_dir) / f"frame_{i}_{ts}.jpg"
                if not _extract_frame(video, ts, frame_path):
                    continue
                if not frame_path.exists() or frame_path.stat().st_size < 5000:
                    continue

                # Encode image to base64
                img_b64 = base64.b64encode(frame_path.read_bytes()).decode()

                prompt = (
                    "Analise este frame de video do canal Animax (shorts do YouTube) com muito cuidado. "
                    "Identifique e descreva TODOS os elementos visuais de forma PRECISA e TECNICA:\n\n"
                    "1. LEGENDA DE FALA (texto no centro/meio do video):\n"
                    "   - Texto exato visivel\n"
                    "   - Cor principal do texto (ex: branco #FFFFFF, vermelho #FF0000, ciano #00FFFF)\n"
                    "   - Tem borda/sombra? Qual cor?\n"
                    "   - Posicao: % vertical da tela (0=topo, 100=base)\n"
                    "   - Numero de palavras na linha\n"
                    "   - MAIUSCULO ou Titulo ou minusculo?\n"
                    "   - Estilo: negrito? italico? outlinado?\n\n"
                    "2. TITULO DO VIDEO (texto logo abaixo da foto de perfil):\n"
                    "   - Texto exato\n"
                    "   - Cor e estilo\n\n"
                    "3. HEADER DO CANAL (canto superior esquerdo):\n"
                    "   - Nome do canal visivel\n"
                    "   - Tem @ abaixo do nome? (ex: @animax_97)\n"
                    "   - Tem icone de verificacao (check)?\n\n"
                    "4. WATERMARK/MARCA DAGUA:\n"
                    "   - Texto da marca dagua (ex: @ANIMAX_97)\n"
                    "   - Posicao na tela\n"
                    "   - Opacidade aproximada\n\n"
                    "5. BARRA INFERIOR (CTA):\n"
                    "   - Texto exato\n"
                    "   - Cor de fundo\n"
                    "   - Cor do texto\n\n"
                    "Responda em JSON puro, sem markdown. Exemplo:\n"
                    '{"subtitle":{"text":"EXEMPLO","color":"#FFFFFF","has_stroke":true,"stroke_color":"#000000","position_y_pct":55,"words_per_line":2,"capitalization":"upper","bold":true},'
                    '"title":{"text":"Titulo aqui","color":"#FFFFFF"},'
                    '"header":{"name":"Animax","handle":"@animax_97","verified":true},'
                    '"watermark":{"text":"@ANIMAX_97","position":"center","opacity":0.25},'
                    '"cta":{"text":"Se inscreve!","bg_color":"#F5E6D0","text_color":"#2C1810"}}'
                )

                payload = json.dumps({
                    "contents": [{
                        "parts": [
                            {"text": prompt},
                            {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}}
                        ]
                    }],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 800}
                }).encode()

                success = False
                last_err = ""

                # Try with active key and models, rotate key and model if error
                for attempt in range(min(len(keys_pool) * len(candidate_models), 8)):
                    current_key = keys_pool[(active_key_idx + attempt) % len(keys_pool)]
                    model = candidate_models[attempt % len(candidate_models)]
                    api_url = (
                        f"https://generativelanguage.googleapis.com/v1beta/models/"
                        f"{model}:generateContent?key={current_key}"
                    )
                    try:
                        req = urllib.request.Request(
                            api_url,
                            data=payload,
                            headers={"Content-Type": "application/json"},
                            method="POST"
                        )
                        with urllib.request.urlopen(req, timeout=25) as resp:
                            result = json.loads(resp.read())
                        raw_text = result["candidates"][0]["content"]["parts"][0]["text"].strip()
                        if raw_text.startswith("```"):
                            raw_text = raw_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                        obs = json.loads(raw_text)
                        obs["_video"] = video.name
                        obs["_timestamp"] = ts
                        visual_observations.append(obs)
                        log(f"    Gemini ({model}): subtitulo='{obs.get('subtitle', {}).get('text', '')[:20]}' cor={obs.get('subtitle', {}).get('color', '')}")
                        success = True
                        break
                    except Exception as e:
                        last_err = str(e)
                        # Rotate to next key on failure
                        active_key_idx += 1
                        time.sleep(0.5)

                if not success:
                    log(f"    Gemini erro (frame {ts}s): {last_err}")

        log(f"Analise visual concluida: {len(visual_observations)} frames analisados")

    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {"observations": visual_observations}


def _merge_visual_into_style(style, visual_data):
    """Mescla as observacoes visuais do Gemini no perfil de estilo."""
    observations = visual_data.get("observations", [])
    if not observations:
        return style

    # Collect subtitle colors seen
    sub_colors = [o.get("subtitle", {}).get("color", "") for o in observations if o.get("subtitle", {}).get("color")]
    sub_positions = [o.get("subtitle", {}).get("position_y_pct", 0) for o in observations if o.get("subtitle", {}).get("position_y_pct")]
    sub_words = [o.get("subtitle", {}).get("words_per_line", 0) for o in observations if o.get("subtitle", {}).get("words_per_line")]
    caps_vals = [o.get("subtitle", {}).get("capitalization", "") for o in observations if o.get("subtitle", {}).get("capitalization")]

    # Handle subtitle color — store all variations seen
    color_counter = Counter(c for c in sub_colors if c)
    dominant_color = color_counter.most_common(1)[0][0] if color_counter else "#FFFFFF"
    all_colors = list(color_counter.keys())

    if sub_positions:
        avg_pos = int(statistics.median(sub_positions))
        style["subtitle"]["position_y_percent"] = avg_pos

    if sub_words:
        style["subtitle"]["max_words_per_line"] = int(statistics.median(sub_words))

    if caps_vals:
        cap_dominant = Counter(caps_vals).most_common(1)[0][0]
        style["subtitle"]["capitalization"] = cap_dominant

    style["subtitle"]["color"] = dominant_color
    style["subtitle"]["color_variations"] = all_colors  # All colors seen across videos

    # CTA text from most recent observation
    for obs in reversed(observations):
        cta = obs.get("cta", {})
        if cta.get("text"):
            style["cta_bar"]["text"] = cta["text"]
        if cta.get("bg_color"):
            style["cta_bar"]["background_color"] = cta["bg_color"]
        if cta.get("text_color"):
            style["cta_bar"]["text_color"] = cta["text_color"]
        break

    # Header
    for obs in observations:
        header = obs.get("header", {})
        if header.get("handle"):
            style["channel_header"]["handle"] = header["handle"]
        if header.get("verified") is not None:
            style["channel_header"]["verified"] = header["verified"]
        break

    style["_meta"]["visual_frames_analyzed"] = len(observations)
    style["_meta"]["subtitle_colors_seen"] = all_colors

    return style


def run_analysis(on_log=None, gemini_api_key=None):
    def log(msg):
        msg_str = str(msg)
        if on_log:
            try:
                on_log(msg_str)
            except UnicodeEncodeError:
                try:
                    on_log(msg_str.encode("ascii", errors="replace").decode())
                except Exception:
                    pass
            except Exception:
                pass
        else:
            _safe_print(msg_str)

    # -- Step 1: Find CapCut project folder --
    candidates = [
        CAPCUT_PROJECTS_ROOT / "Animax-copia-copia",
        CAPCUT_PROJECTS_ROOT / "Animax-c\u00f3pia-c\u00f3pia",
        CAPCUT_PROJECTS_ROOT / "Animax-c\u00f3pia",
    ]
    project_path = None
    for c in candidates:
        if c.exists():
            project_path = c
            break

    if not project_path:
        matches = list(CAPCUT_PROJECTS_ROOT.glob("*animax*")) + list(CAPCUT_PROJECTS_ROOT.glob("*Animax*"))
        if matches:
            project_path = matches[0]

    if not project_path:
        log(f"ERRO: Pasta do projeto Animax nao encontrada em: {CAPCUT_PROJECTS_ROOT}")
        return {}

    # -- Step 2: Parse CapCut JSONs --
    log(f"[1/3] Carregando projetos CapCut de: {project_path}")
    drafts = load_all_drafts(project_path)
    log(f"      {len(drafts)} projetos carregados")

    log("[2/3] Extraindo segmentos de texto...")
    segments = extract_text_segments(drafts)
    sub_count = sum(1 for s in segments if s["is_subtitle"])
    log(f"      {len(segments)} segmentos ({sub_count} legendas, {len(segments)-sub_count} estaticos)")

    log("      Analisando padroes estatisticos...")
    style = analyze_style(segments)

    # -- Step 3: Visual analysis with Gemini Vision --
    log("[3/3] Analise visual dos 5 videos mais recentes com Gemini Vision...")
    visual_data = analyze_videos_with_gemini(on_log=log, gemini_api_key=gemini_api_key)

    if visual_data.get("observations"):
        style = _merge_visual_into_style(style, visual_data)
        log(f"      Cores de legenda detectadas: {style['subtitle'].get('color_variations', [])}")
    else:
        log("      Analise visual nao disponivel - usando apenas dados CapCut")

    # -- Save --
    log(f"Salvando perfil em: {OUTPUT_STYLE_FILE}")
    with open(OUTPUT_STYLE_FILE, "w", encoding="utf-8") as f:
        json.dump(style, f, ensure_ascii=False, indent=2)

    # If running frozen or from a subdirectory, also ensure it is mirrored in script directory
    try:
        alt_path = Path(__file__).parent / "user_style.json"
        if alt_path.resolve() != OUTPUT_STYLE_FILE.resolve():
            with open(alt_path, "w", encoding="utf-8") as f:
                json.dump(style, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    log("user_style.json gerado com sucesso!")
    log(f"  Fonte: {style['subtitle']['font_name']} | Tamanho: {style['subtitle']['size_px']}px")
    log(f"  Cores vistas: {style['subtitle'].get('color_variations', [style['subtitle']['color']])}")
    log(f"  Watermark: {style['watermark_text']['text']}")
    return style


if __name__ == "__main__":
    run_analysis()
