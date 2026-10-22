"""
dataset_logger.py - Permanent training-data logger for local LLM distillation.

Appends one JSON object per line (JSONL) to .cache/training/<task>.jsonl.
Unlike ai_cache_hub, nothing here expires: this is the raw material for fine-tuning.
Every public function is fail-safe: logging must never break the main pipeline.
Set DATASET_LOG=0 in .env to disable.
"""

import os
import sys
import json
import time
import uuid
import hashlib
import threading
from pathlib import Path
from typing import Any, Dict, Optional

SCHEMA_VERSION = 1
_write_lock = threading.Lock()


def _get_training_dir() -> Path:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    return base / ".cache" / "training"


TRAINING_DIR = _get_training_dir()


def is_enabled() -> bool:
    return os.getenv("DATASET_LOG", "1").strip() not in ("0", "false", "no")


def text_fingerprint(text: str) -> str:
    """Stable short hash, used to group samples by episode for leak-free train/test splits."""
    return hashlib.sha1((text or "").encode("utf-8", errors="ignore")).hexdigest()[:16]


def append_record(task: str, record: Dict[str, Any], directory: Optional[Path] = None) -> Optional[str]:
    """Append a record to <task>.jsonl. Returns the generated record_id, or None on failure."""
    if not is_enabled():
        return None
    try:
        target_dir = directory or TRAINING_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        record_id = uuid.uuid4().hex[:12]
        line = json.dumps(
            {"record_id": record_id, "schema": SCHEMA_VERSION, "ts": time.time(), **record},
            ensure_ascii=False,
        )
        with _write_lock, open(target_dir / f"{task}.jsonl", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return record_id
    except Exception:
        return None


def log_director_sample(
    prompt: str,
    response: str,
    provider_info: Dict[str, str],
    params: Dict[str, Any],
    n_candidates: int,
) -> Optional[str]:
    """Log one Director AI teacher sample (prompt -> raw model response)."""
    clean_params = {k: v for k, v in params.items() if k != "source"}
    return append_record("director", {
        "type": "sample",
        "source": params.get("source", "live"),
        "provider": provider_info.get("provider", "unknown"),
        "model": provider_info.get("model", "unknown"),
        "params": clean_params,
        "n_candidates": n_candidates,
        "parse_ok": n_candidates > 0,
        "prompt": prompt,
        "response": response,
    })


def log_director_feedback(event: str, episode: str, cut: Dict[str, Any]) -> Optional[str]:
    """Log a human feedback event (e.g. 'accepted' when the user exports a suggested cut)."""
    return append_record("director", {"type": "feedback", "event": event, "episode": episode, "cut": cut})
