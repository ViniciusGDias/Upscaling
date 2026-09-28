"""
video_trimmer.py - Módulo de Corte e Exclusão Cirúrgica de Trechos de Vídeo
Permite aparar início, cortar segundos finais ou remover trechos específicos do meio do vídeo.
Integrado com o Studio Pipeline para garantir que transcrição, legendas e renderização
fiquem 100% sincronizados com a duração desejada.
"""

import os
import re
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional, Callable, Dict, Any


def parse_time_to_seconds(time_str: Any) -> float:
    """Converte strings como '10', '10s', '0:15', '01:30' ou float em segundos."""
    if not time_str:
        return 0.0
    if isinstance(time_str, (int, float)):
        return max(0.0, float(time_str))
    s = str(time_str).strip().lower().rstrip('s')
    if not s:
        return 0.0
    parts = s.split(':')
    try:
        if len(parts) == 1:
            return max(0.0, float(parts[0]))
        elif len(parts) == 2:
            return max(0.0, float(parts[0]) * 60.0 + float(parts[1]))
        elif len(parts) == 3:
            return max(0.0, float(parts[0]) * 3600.0 + float(parts[1]) * 60.0 + float(parts[2]))
    except Exception:
        return 0.0
    return 0.0


def format_seconds_to_time(seconds: float) -> str:
    """Formata segundos em MM:SS.s ou SS.s de forma legível."""
    if seconds <= 0:
        return "00:00"
    m = int(seconds // 60)
    s = seconds % 60
    if m > 0:
        return f"{m:02d}:{s:04.1f}"
    return f"{s:.1f}s"


def parse_exclusion_intervals(text: str) -> List[Tuple[float, float]]:
    """
    Analisa texto contendo intervalos a excluir, ex:
    '00:15 - 00:18'
    '15-18, 30-35'
    '10 a 14; 22 ate 25'
    Retorna lista ordenada e mesclada de tuplas [(start, end), ...]
    """
    if not text or not str(text).strip():
        return []
    raw = str(text).strip()
    # Divide por vírgulas, ponto-e-vírgula ou quebras de linha
    chunks = re.split(r'[,;|\n]+', raw)
    intervals = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        m = re.split(r'\s*(?:-|ate|até|to|a)\s*', chunk, flags=re.IGNORECASE)
        if len(m) == 2:
            s = parse_time_to_seconds(m[0])
            e = parse_time_to_seconds(m[1])
            if e > s:
                intervals.append((round(s, 3), round(e, 3)))

    if not intervals:
        return []

    # Ordena e mescla intervalos sobrepostos
    intervals.sort(key=lambda x: x[0])
    merged = [intervals[0]]
    for cur in intervals[1:]:
        prev_s, prev_e = merged[-1]
        if cur[0] <= prev_e + 0.05:
            merged[-1] = (prev_s, max(prev_e, cur[1]))
        else:
            merged.append(cur)
    return merged


def calculate_keep_intervals(
    total_duration: float,
    trim_start: float = 0.0,
    cut_from_end: float = 0.0,
    end_at: Optional[float] = None,
    exclude_intervals: Optional[List[Tuple[float, float]]] = None
) -> Tuple[List[Tuple[float, float]], float, float]:
    """
    Calcula os intervalos contínuos a MANTER no vídeo final.

    Retorna:
      (keep_intervals, final_duration, removed_duration)
    """
    if total_duration <= 0.0:
        return [], 0.0, 0.0

    t_start = max(0.0, float(trim_start or 0.0))
    t_end = total_duration

    # Cortar X segundos do final (ex: cut_from_end = 2.0 remove os últimos 2s)
    if cut_from_end and float(cut_from_end) > 0.0:
        t_end = max(t_start, total_duration - float(cut_from_end))

    # Ou terminar em tempo absoluto fixo (end_at)
    if end_at is not None and float(end_at) > 0.0:
        t_end = max(t_start, min(t_end, float(end_at)))

    if t_end <= t_start:
        return [], 0.0, total_duration

    # Processa intervalos excluídos dentro do limite [t_start, t_end]
    excl = exclude_intervals or []
    valid_excl = []
    for s, e in excl:
        s_c = max(t_start, min(t_end, s))
        e_c = max(t_start, min(t_end, e))
        if e_c - s_c > 0.05:
            valid_excl.append((s_c, e_c))

    if not valid_excl:
        keep = [(t_start, t_end)]
    else:
        keep = []
        curr = t_start
        for s, e in valid_excl:
            if s > curr + 0.05:
                keep.append((curr, s))
            curr = max(curr, e)
        if t_end > curr + 0.05:
            keep.append((curr, t_end))

    final_dur = sum(e - s for s, e in keep)
    removed_dur = max(0.0, total_duration - final_dur)
    return keep, round(final_dur, 3), round(removed_dur, 3)


def is_trim_active(
    total_duration: float,
    trim_start: float = 0.0,
    cut_from_end: float = 0.0,
    end_at: Optional[float] = None,
    exclude_intervals: Optional[List[Tuple[float, float]]] = None
) -> bool:
    """Verifica se alguma parte do vídeo será de fato cortada/removida."""
    if total_duration <= 0.0:
        return False
    keep, final_dur, removed_dur = calculate_keep_intervals(
        total_duration=total_duration,
        trim_start=trim_start,
        cut_from_end=cut_from_end,
        end_at=end_at,
        exclude_intervals=exclude_intervals
    )
    # Se removeu mais de 0.05s ou se dividiu em múltiplos blocos, o corte está ativo
    return removed_dur >= 0.05 or len(keep) > 1


def trim_video_file(
    input_path: str,
    output_path: str,
    keep_intervals: List[Tuple[float, float]],
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[float, str], None]] = None
) -> bool:
    """
    Executa o corte e/ou concatenação dos trechos do vídeo via FFmpeg.
    Garante fidelidade total de sincronia de áudio e vídeo.
    """
    def log(msg: str):
        if on_log:
            on_log(msg)

    if not keep_intervals:
        log("Erro: nenhum intervalo a manter definido para corte.")
        return False

    from subtitle_renderer import _find_ffmpeg
    ffmpeg = _find_ffmpeg()

    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    # Caso 1: Intervalo único (apenas corte de início e/ou fim)
    if len(keep_intervals) == 1:
        s, e = keep_intervals[0]
        dur = e - s
        log(f"✂️ FFmpeg aparando vídeo: {s:.2f}s até {e:.2f}s (duração: {dur:.2f}s)...")
        cmd = [
            ffmpeg,
            "-ss", f"{s:.3f}",
            "-to", f"{e:.3f}",
            "-i", str(input_path),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "17",
            "-c:a", "aac",
            "-b:a", "192k",
            "-y",
            str(output_path)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, creationflags=creation_flags)
        if res.returncode != 0:
            log(f"Erro no FFmpeg trim: {res.stderr[-400:]}")
            return False
        return os.path.exists(output_path) and os.path.getsize(output_path) > 1000

    # Caso 2: Múltiplos intervalos (exclusão de trechos do meio)
    log(f"✂️ FFmpeg unindo {len(keep_intervals)} trechos mantidos (removendo partes indesejadas)...")
    fc_parts = []
    concat_v = []
    concat_a = []
    for idx, (s, e) in enumerate(keep_intervals):
        fc_parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{idx}]")
        fc_parts.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{idx}]")
        concat_v.append(f"[v{idx}]")
        concat_a.append(f"[a{idx}]")

    inputs_str = "".join(f"{concat_v[i]}{concat_a[i]}" for i in range(len(keep_intervals)))
    fc_parts.append(f"{inputs_str}concat=n={len(keep_intervals)}:v=1:a=1[vout][aout]")
    fc = ";".join(fc_parts)

    cmd = [
        ffmpeg,
        "-i", str(input_path),
        "-filter_complex", fc,
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "17",
        "-c:a", "aac",
        "-b:a", "192k",
        "-y",
        str(output_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, creationflags=creation_flags)
    if res.returncode != 0:
        log(f"Erro no FFmpeg multi-trim: {res.stderr[-400:]}")
        return False
    return os.path.exists(output_path) and os.path.getsize(output_path) > 1000
