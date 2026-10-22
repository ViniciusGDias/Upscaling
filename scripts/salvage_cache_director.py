"""
scripts/salvage_cache_director.py - Resgata transcrições, cortes gerados e histórico de cortes
aceitos do .cache/ai_hub antes que expirem nas 24h, populando o dataset permanente (.cache/training/director.jsonl).
"""

import os
import sys
import glob
import json
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import dataset_logger
import director_ai


def salvage():
    hub_files = glob.glob(str(ROOT / ".cache" / "ai_hub" / "*.json"))
    print(f"Encontrados {len(hub_files)} arquivos em .cache/ai_hub...")

    salvaged_samples = 0
    salvaged_feedbacks = 0
    seen_prompts = set()
    seen_feedbacks = set()

    for fpath in hub_files:
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue

        if not isinstance(data, dict):
            continue

        v_name = data.get("video_name", "") or Path(fpath).stem
        transcript_raw = data.get("director_transcript")
        transcript = ""
        if isinstance(transcript_raw, dict):
            transcript = transcript_raw.get("payload", "")
        elif isinstance(transcript_raw, str):
            transcript = transcript_raw

        # 1. Resgatar amostras de pares (prompt -> cortes)
        cut_keys = [k for k in data if k.startswith("director_cuts")]
        if transcript and cut_keys:
            # Parse dos modos a partir da chave: director_cuts_{mode}_{cut_mode}_{content_type}
            for ck in cut_keys:
                cands_raw = data[ck]
                cands = []
                if isinstance(cands_raw, dict):
                    cands = cands_raw.get("payload", [])
                elif isinstance(cands_raw, list):
                    cands = cands_raw

                if not cands or not isinstance(cands, list):
                    continue

                parts = ck.replace("director_cuts_", "").split("_")
                mode = parts[0] if len(parts) > 0 else "smart"
                # Ex: smart_context_general -> mode="smart", cut_mode="context", genre="general"
                # Ex: smart_dynamic_montage_general -> cut_mode="dynamic_montage"
                if len(parts) >= 3:
                    genre = parts[-1]
                    cut_mode = "_".join(parts[1:-1])
                elif len(parts) == 2:
                    cut_mode = parts[1]
                    genre = "general"
                else:
                    cut_mode = "context"
                    genre = "general"

                # Reconstruir prompt exato usado pelo Diretor
                try:
                    reconstructed_prompt = director_ai.build_candidates_prompt(
                        mode=mode,
                        context=v_name,
                        lore="",
                        transcript=transcript,
                        video_duration_str="",
                        cut_mode=cut_mode,
                        excluded_ranges=[],
                        genre=genre,
                    )
                except Exception as e:
                    continue

                fp = dataset_logger.text_fingerprint(reconstructed_prompt + str(len(cands)))
                if fp in seen_prompts:
                    continue
                seen_prompts.add(fp)

                raw_response = json.dumps({"candidates": cands}, ensure_ascii=False, indent=2)

                dataset_logger.append_record("director", {
                    "type": "sample",
                    "source": "cache_reconstruction",
                    "provider": "gemini",
                    "model": "historical",
                    "params": {
                        "call": "analyze",
                        "mode": mode,
                        "cut_mode": cut_mode,
                        "genre": genre,
                        "video_duration": 0.0,
                        "temperature": 0.3,
                        "has_context": True,
                        "has_lore": False,
                        "n_excluded": 0,
                        "episode": v_name,
                        "transcript_sha1": dataset_logger.text_fingerprint(transcript),
                    },
                    "n_candidates": len(cands),
                    "parse_ok": True,
                    "prompt": reconstructed_prompt,
                    "response": raw_response,
                })
                salvaged_samples += 1

        # 2. Resgatar feedback de cortes aceitos / exportados
        if "cut_origin" in data:
            co = data["cut_origin"]
            if isinstance(co, dict):
                co = co.get("payload", co)
            if isinstance(co, dict) and co.get("source_episode") and co.get("title"):
                fb_key = f"{co.get('source_episode')}_{co.get('title')}_{co.get('start_sec')}"
                if fb_key not in seen_feedbacks:
                    seen_feedbacks.add(fb_key)
                    dataset_logger.log_director_feedback("accepted", co.get("source_episode"), {
                        "start_sec": co.get("start_sec"),
                        "end_sec": co.get("end_sec"),
                        "title": co.get("title"),
                        "cut_mode": co.get("cut_mode", "context"),
                        "quality_score": co.get("quality_score", 8),
                    })
                    salvaged_feedbacks += 1

    print(f"\n[SUCESSO] Resgate concluído!")
    print(f"- Amostras de treino recuperadas: {salvaged_samples}")
    print(f"- Feedbacks de cortes aceitos recuperados: {salvaged_feedbacks}")
    target_file = ROOT / ".cache" / "training" / "director.jsonl"
    if target_file.exists():
        size_kb = target_file.stat().st_size / 1024
        print(f"- Arquivo de treino gerado: {target_file} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    salvage()
