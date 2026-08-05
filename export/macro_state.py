"""
export/macro_state.py
=====================
Машинният api export — `output/api/macro_state.json` (мандат ORGANISM-v1, Ф1).

Фамилният шаблон: us/eu/china публикуват `output/api/macro_state.json` и
консуматорите (macro-satellite, организмовият дрил) ги четат машинно — не
парсват Markdown. Новата генерация на двигателя (bg/jp) нямаше такъв файл;
този модул е първият носител на схемата ѝ (`jp-macro-state v1`).

Дисциплината на числата: executive_summary се ЦИТИРА от последния ред на
живия журнал (`score_journal.csv`) — файлът е снимка на записания PIT момент,
не втора сметка. Режимният етикет идва от `get_regime` през подадения
`regime` dict; латинският ключ — от `config.REGIME_KEYS`. Йена-редовете са
ДОСЛОВНО `segment_lines` (ЕДИН източник на формулировките — AGENT.md).

Наблюдение, не сигнал: файлът описва състояние; никакъв механичен извод
не живее тук (KS е на организма, не на сателитите).
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from analysis.yen_segment import segment_lines
from config import MODULE_WEIGHTS, REGIME_KEYS

REGION = "JP"
SCHEMA = "jp-macro-state v1"
ENGINE = "robust-z-10y-mad"          # фамилната нова генерация (bg/jp)
OBSERVATION_NOTE_BG = (
    "НАБЛЮДЕНИЕ, НЕ СИГНАЛ — уредът наблюдава състояние, не издава сигнал "
    "за действие."
)


def _num(v: Any) -> Optional[float]:
    """numpy/NaN → чист JSON float или None (журналът идва през pandas)."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _int(v: Any) -> Optional[int]:
    f = _num(v)
    return None if f is None else int(f)


def build_macro_state(
    *,
    journal: pd.DataFrame,
    lens_reports: dict,
    regime: dict,
    temp: dict,
    tension: dict,
    yen: dict,
    today: date,
    generated_at: Optional[str] = None,
) -> dict:
    """Сглобява api документа от ВЕЧЕ сметнатите обекти на `--briefing` пуска.

    `journal` е рамката, ВЪРНАТА от `append_journal` — редът за днес е
    задължителен (fail-loud: липсва ли, пускът е извикан в грешен ред, не
    произвеждаме файл с втора сметка).
    """
    rows = journal[journal["date"] == today.isoformat()]
    if rows.empty:
        raise ValueError(
            f"журналът няма ред за {today.isoformat()} — build_macro_state "
            "се вика СЛЕД append_journal (редът на --briefing)"
        )
    row = rows.iloc[-1]

    lenses: dict[str, dict[str, Any]] = {}
    for lens in MODULE_WEIGHTS:
        rep = lens_reports.get(lens) or {}
        lenses[lens] = {
            "score": _num(row.get(f"score_{lens}")),
            "health_z": _num(row.get(f"z_{lens}")),
            "n_series": rep.get("n_series"),
        }

    regime_name = regime.get("name")
    doc = {
        "region": REGION,
        "schema": SCHEMA,
        "engine": ENGINE,
        "as_of_date": today.isoformat(),
        "generated_at": generated_at
        or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note_bg": OBSERVATION_NOTE_BG,
        "executive_summary": {
            "composite_score": _num(row.get("composite")),
            "regime_key": REGIME_KEYS.get(regime_name),
            "regime_label_bg": regime_name,
            "regime_color": regime.get("color"),
            "n_series": _int(row.get("n_series")),
            "n_lenses": _int(row.get("n_lenses")),
            "temp_count": _int(row.get("temp_count")),
            "k1_ratio": _num(row.get("k1_ratio")),
            "composition": str(row.get("composition")),
            "tension_sentence": tension.get("sentence"),
        },
        "lenses": lenses,
        "temperature": {
            "n_hot": temp.get("n_hot"),
            "n_total": temp.get("n_total"),
            "hot": temp.get("hot", []),
            "as_of": temp.get("as_of"),
        },
        "yen_layer": yen,
        "yen_layer_lines": segment_lines(yen),
    }
    return doc


def generate_macro_state(output_path: str, **kwargs) -> dict:
    """Записва `macro_state.json` (UTF-8, четим — фамилният api е за хора и код)."""
    doc = build_macro_state(**kwargs)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return doc
