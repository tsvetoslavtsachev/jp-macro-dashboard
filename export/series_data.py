"""
export/series_data.py
=====================
output/api/series_data.json — времеви редове за графиките, СЪЩАТА схема като
us-macro-dashboard/export_api.py::build_series_data (и china-): за всяка серия
{meta, latest, chart}. Скоринговите полета идват от core/scorer.py (лещовите
доклади или score_series за контекстните серии) — тук няма втора сметка.

Разлики спрямо US, нарочни:
  - years_included = 10 (мандат ПРОЛЕТР4), не 7.
  - daily каденция има собствен период (PERIOD_LENGTH_DAYS["daily"] = 5) —
    US няма дневни серии.
  - `yoy_change` е истинска годишна промяна по ДАТА (стойността ~1 година
    назад), не хардкодирани 12 наблюдения (за дневна серия те са 12 дни).
  - Полета, които JP скорерът не смята (z_score, dev_sigma, severity,
    direction, regime) -> null, но ключът стои.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from catalog.polarity import polarity_for
from catalog.series import SERIES_CATALOG
from core.primitives import apply_transform
from core.scorer import score_series

YEARS_INCLUDED = 10

# ПРОЛЕТР4 (26.11.2026): правилото живее в core/staleness.py, общо с оценката на лещите.
from core.staleness import (  # noqa: E402,F401
    PERIOD_LENGTH_DAYS, RELATIVE_STALE_PERIODS, relative_staleness, sched_reference,
)

RATE_TRANSFORMS = ("yoy_pct", "mom_pct", "qoq_pct")

# change_kind — огледало на us core/display.py::change_kind:
#   "bps" (delta = diff*100, лихви/проценти), "absolute" (diff), "percent" (% промяна).
BPS_PEER_GROUPS = {"unemployment", "yields"}
BPS_KEYS = {  # контекстни лихвени серии (peer_group "context")
    "JP_CALL_RATE", "JP_TIBOR3M", "JP_JGB_2Y", "JP_JGB_10Y_D",
    "US_2Y", "US_10Y", "JP_CARRY_2Y", "JP_CARRY_10Y",
}
ABS_PEER_GROUPS = {"external_balance"}
ABS_KEYS = {"JP_GOV_DEBT", "JP_GOV_BAL", "JP_CREDIT_GDP_PNF"}  # % от БВП

SERIES_DATA_KEYS = ("region", "last_updated", "years_included", "series_count", "series")
META_KEYS = ("name_bg", "name_en", "lens", "lens_all", "peer_group", "transform",
             "is_rate", "change_kind", "release_schedule", "narrative_hint")
LATEST_KEYS = ("date", "stale", "periods_behind", "value", "yoy_change", "percentile",
               "percentile_window", "z_score", "z_raw", "health_z", "dev_sigma",
               "severity", "score", "direction", "regime")


def change_kind(key: str, meta: dict) -> str:
    if key in BPS_KEYS or meta.get("peer_group") in BPS_PEER_GROUPS:
        return "bps"
    if key in ABS_KEYS or meta.get("peer_group") in ABS_PEER_GROUPS:
        return "absolute"
    # Серия, която вече Е процент/темп (is_rate на ниво, или yoy/mom/qoq
    # трансформация): промяната се чете в пункта (pp), не като % от процент.
    if meta.get("is_rate") or meta.get("transform", "level") in RATE_TRANSFORMS:
        return "absolute"
    return "percent"


def _clean(val: Any) -> Any:
    if isinstance(val, (float, np.floating)):
        v = float(val)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(val, np.integer):
        return int(val)
    if isinstance(val, np.bool_):
        return bool(val)
    if isinstance(val, pd.Timestamp):
        return str(val.date())
    return val


def _yoy_change(s: pd.Series, kind: str) -> float | None:
    """Промяна спрямо стойността ~1 година назад (по дата), в единиците на kind."""
    s = s.dropna()
    if len(s) < 2:
        return None
    last_d = s.index[-1]
    prior = s[s.index <= last_d - pd.DateOffset(years=1)]
    if prior.empty:
        return None
    last, then = float(s.iloc[-1]), float(prior.iloc[-1])
    if kind == "bps":
        return (last - then) * 100
    if kind == "absolute":
        return last - then
    return None if then == 0 else (last / then - 1) * 100


def _sched_reference(snapshot: dict, catalog: dict) -> dict:
    return sched_reference(snapshot, catalog)


def build_series_data(
    snapshot: dict,
    lens_reports: dict | None = None,
    today: date | None = None,
    years: int = YEARS_INCLUDED,
    catalog: dict | None = None,
    now: datetime | None = None,
) -> dict:
    catalog = SERIES_CATALOG if catalog is None else catalog
    today = today or date.today()
    cutoff = pd.Timestamp(today) - pd.DateOffset(years=years)
    sched_ref = _sched_reference(snapshot, catalog)

    # (lens, key) -> готовият score dict от лещовите доклади (без втора сметка)
    scored = {
        (lens, s["key"]): s
        for lens, rep in (lens_reports or {}).items()
        for s in rep.get("series", [])
    }

    series_out: dict[str, dict] = {}
    for key, meta in catalog.items():
        raw = snapshot.get(key)
        if raw is None:
            continue
        raw = raw.dropna()
        if raw.empty:
            continue

        lens_list = list(meta.get("lens", []))
        primary = lens_list[0] if lens_list else "other"
        transform = meta.get("transform", "level")
        kind = change_kind(key, meta)

        if transform in RATE_TRANSFORMS:
            try:
                display = apply_transform(raw, transform).dropna()
            except Exception:
                display = raw
        else:
            display = raw
        shown = display[display.index >= cutoff].dropna()
        if shown.empty:
            continue

        latest_date = str(shown.index[-1].date())
        yoy = None if transform in RATE_TRANSFORMS else _yoy_change(raw, kind)

        sc = scored.get((primary, key))
        if sc is None:  # контекстна серия — същият примитив на скорера
            sc = score_series(raw, transform, polarity_for(key), name=key)
        stale, behind = relative_staleness(
            latest_date, meta.get("release_schedule", "monthly"), sched_ref
        )

        series_out[key] = {
            "meta": {
                "name_bg": meta.get("name_bg", key),
                "name_en": meta.get("name_en", key),
                "lens": primary,
                "lens_all": lens_list,
                "peer_group": meta.get("peer_group", ""),
                "transform": transform,
                "is_rate": meta.get("is_rate", False),
                "change_kind": kind,
                "release_schedule": meta.get("release_schedule", "monthly"),
                "narrative_hint": meta.get("narrative_hint", ""),
            },
            "latest": {
                "date": latest_date,
                "stale": stale,
                "periods_behind": behind,
                "value": _clean(float(shown.iloc[-1])),
                "yoy_change": _clean(yoy),
                "percentile": _clean(sc.get("percentile")),
                "percentile_window": sc.get("percentile_window"),
                "z_score": None,   # JP скорерът не пази отделен z (z_raw е сурогатът)
                "z_raw": _clean(sc.get("z_raw")),
                "health_z": _clean(sc.get("health_z")),
                "dev_sigma": None,
                "severity": None,
                "score": _clean(sc.get("score")),
                "direction": None,
                "regime": None,
            },
            "chart": {
                "dates": [str(d.date()) for d in shown.index],
                "values": [_clean(float(v)) for v in shown.values],
            },
        }

    stamp = (now or datetime.now(timezone.utc)).replace(tzinfo=None).isoformat() + "Z"
    return {
        "region": "JP",
        "last_updated": stamp,
        "years_included": years,
        "series_count": len(series_out),
        "series": series_out,
    }


def write_series_data(path: str | Path, **kwargs) -> dict:
    """Строи и записва (indent=2, ensure_ascii=False — както US _safe_dump)."""
    data = build_series_data(**kwargs)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    return data
