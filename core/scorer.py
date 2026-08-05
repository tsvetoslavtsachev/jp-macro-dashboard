"""
core/scorer.py
==============
Робастният lens scoring двигател на българската макро повърхност.

Портнат от `dashboards/eu-macro-dashboard` (core/scorer.py + analysis/health.py);
референтният документ на фамилията е
`dashboards/macro-satellite/LENS_SCORING_METHODOLOGY.md`.

Веригата (един примитив, локална норма):
  1. каталожна трансформация  → темп вместо ниво за номиналните серии
  2. робастен z спрямо ПЛЪЗГАЩ 10-г. прозорец:
         z = (x − median₁₀) / (1.4826 · MAD₁₀)
  3. полярност → health-z (по-високо = по-здраво; U-форма около целта за
     инфлацията; АБСОЛЮТНА оптимална зона за бум-сериите — мандат №47)
  4. score = 50 · (1 + tanh(z_h / 2))   → 50 = близката норма; ±2σ ≈ 88/12
  5. серия → peer-група (средно) → леща (претеглено) → композит (MODULE_WEIGHTS,
     с ренормализация: празна леща ИЗПАДА, не се брои като „неутрално 50")

Заменя percentile-of-full-history: номинално дрейфаща серия вече не се съди
спрямо 2000г., а спрямо собствената си близка норма.

ВАЖНО: скалата НЕ е сравнима 1:1 със стария percentile композит; сравнима е с
us/eu/china-macro-dashboard (същият примитив).
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Optional

import numpy as np
import pandas as pd

from config import MACRO_REGIMES, MODULE_WEIGHTS, HISTORY_START
from catalog.polarity import (
    polarity_for,
    peer_group_weight,
    U_BAND,
    is_opt,
    is_u_shaped,
    opt_zone,
)
from core.primitives import (
    MIN_OBS,
    WINDOW_YEARS,
    apply_transform,
    robust_stats_latest,
)

# ── константи на фамилията (синхронни с EU core/scorer.py) ───────────────────
TANH_SLOPE = 2.0        # score = 50·(1+tanh(z_h/SLOPE)); ±2σ ≈ 88/12
CLIP_SIGMA = 6.0        # клип при scale_fallback (пълна история вместо 10г)
# Трансформации, чийто ИЗХОД е процент (дисплей „12.34 %"). `yoy_roll4` е
# плъзгаща средна НА процент — също процент (мандат №47 §А2).
PCT_TRANSFORMS = {"yoy_pct", "mom_pct", "qoq_pct", "yoy_roll4"}

# ── Честният къс прозорец (мандат №39 §А3) ───────────────────────────────────
# Ако реалният обхват на данните в прозореца покрива по-малко от този дял от
# `window_years`, „10г" е ЛЪЖА за прозореца. Тогава етикетът казва откога тече
# нормата и се вдига флаг `thin_window` — z-ът е спрямо къс период и подценява
# екстремността, ако този период е бил еднопосочен (напр. кредитен бум).
THIN_WINDOW_FRACTION = 0.70


# ═════════════════════════════════════════════════════════════════════════════
# СЕРИЯ → SCORE
# ═════════════════════════════════════════════════════════════════════════════

def percentile_rank(current: float, history: pd.Series) -> float:
    """% от историческите стойности по-ниски от текущата (0..100).

    Второстепенен контекст — заглавният score идва от робастния z, не оттук.
    """
    if len(history) == 0:
        return 50.0
    return float(np.sum(history < current) / len(history) * 100)


def _health_z(val: float, med: float, scale: float, polarity: Any) -> float:
    """Робастен z → health-z (по-високо = по-здраво)."""
    # ── Оптимална зона (мандат №47) — ПРЕДИ линейния клон ────────────────────
    # Плато на здравето в [lo, hi] (както U-формата в центъра си), после спад
    # по 1σ на всеки `s` пункта. АБСОЛЮТНО: `med` и `scale` от 10-годишната
    # норма НЕ участват — точно това е смисълът на котвите. В бум прозорец
    # нормата сама се вдига и робастният z аплодира прегряването; абсолютният
    # праг не мърда и затова важи и назад във времето (нула look-ahead).
    if is_opt(polarity):
        lo, hi, width = opt_zone(polarity)
        if width <= 0 or np.isnan(width):
            return float(U_BAND)
        if val > hi:
            return float(U_BAND - (val - hi) / width)
        if val < lo:
            return float(U_BAND - (lo - val) / width)
        return float(U_BAND)
    if is_u_shaped(polarity):
        if scale == 0 or np.isnan(scale):
            return float(U_BAND)
        center = float(polarity[2]) if polarity[1] == "target" else med
        return float(U_BAND - abs((val - center) / scale))
    if scale == 0 or np.isnan(scale):
        return 0.0  # без вариация → на нормата
    z_raw = (val - med) / scale
    sign = float(polarity) if polarity in (1, -1, +1) else 1.0
    return float(sign * z_raw)


def _trailing_window(s: pd.Series, window_years: int) -> pd.Series:
    """Последните window_years години (ДО последната точка)."""
    if isinstance(s.index, pd.DatetimeIndex) and len(s):
        cutoff = s.index[-1] - pd.DateOffset(years=window_years)
        return s[s.index >= cutoff]
    return s


def _window_span_years(win: pd.Series) -> Optional[float]:
    """Реалният обхват на прозореца в години (None при не-времеви индекс)."""
    if not isinstance(win.index, pd.DatetimeIndex) or len(win) == 0:
        return None
    if len(win) == 1:
        return 0.0
    return float((win.index[-1] - win.index[0]).days) / 365.25


def _window_label(win: pd.Series, window_years: int, wide_label: str) -> tuple[str, bool]:
    """Етикет на прозореца + флагът `thin_window`.

    Къс обхват → „къс прозорец (от YYYY-MM)" вместо „10г"/„пълна история":
    уредът казва откога тече нормата, вместо да твърди прозорец, който няма.
    """
    span = _window_span_years(win)
    if span is None or span >= THIN_WINDOW_FRACTION * window_years:
        return wide_label, False
    start = win.index[0].strftime("%Y-%m")
    return f"къс прозорец (от {start})", True


def _num_repr(x: float) -> str:
    """`12.0` → „12", `12.5` → „12.5" — четимият вид на праг в етикет."""
    f = float(x)
    return str(int(f)) if f.is_integer() else str(f)


def _polarity_repr(polarity: Any) -> str:
    """Стрингов repr (избягва tuple в JSON/HTML)."""
    if is_opt(polarity):
        lo, hi, width = opt_zone(polarity)
        return f"OPT[{_num_repr(lo)}..{_num_repr(hi)}]/{_num_repr(width)}"
    if is_u_shaped(polarity):
        return f"U:{polarity[1]}" + (f"={polarity[2]}" if polarity[1] == "target" else "")
    return f"{polarity:+d}" if polarity in (1, -1, +1) else str(polarity)


def _empty_score(name: str) -> dict:
    return {
        "name": name,
        "score": None,
        "health_z": None,
        "percentile": None,
        "percentile_window": None,
        "z_raw": None,
        "value": None,
        "display_value": None,
        "display_is_pct": False,
        "last_date": None,
        "transform": "level",
        "polarity": "+1",
        "history_n": 0,
        "scale_fallback": False,
        "degenerate": True,
        "thin_window": False,
    }


def score_series(
    s_raw: pd.Series,
    transform: str = "level",
    polarity: Any = +1,
    name: str = "",
    *,
    window_years: int = WINDOW_YEARS,
    min_obs: int = MIN_OBS,
    history_start: str = HISTORY_START,
) -> dict:
    """Сурова серия → health score dict (робастен z спрямо плъзгащ 10-г. прозорец).

    score 50 = близката норма; >50 по-здраво, <50 по-зле (полярностно ориентирано).
    Трансформацията от каталога се прилага ПРЕДИ скоринга.
    """
    if s_raw is None or s_raw.dropna().empty:
        return _empty_score(name)

    # HISTORY_START отрязва хиперинфлацията 1997 и предборд-периода (config)
    s = s_raw[s_raw.index >= pd.Timestamp(history_start)] if history_start else s_raw
    if s.dropna().empty:
        s = s_raw

    transformed = apply_transform(s, transform).dropna()
    is_pct = transform in PCT_TRANSFORMS
    if transformed.empty:      # серия твърде къса за трансформацията → сурово ниво
        transformed = s.dropna()
        is_pct = False
    if transformed.empty:
        return _empty_score(name)

    scored_val = float(transformed.iloc[-1])
    last_date = (
        transformed.index[-1].strftime("%Y-%m-%d")
        if isinstance(transformed.index, pd.DatetimeIndex)
        else str(transformed.index[-1])
    )

    stats = robust_stats_latest(transformed, window_years=window_years, min_obs=min_obs)
    used_window = window_years
    if stats is None:          # твърде къса за 10-г. норма → пълна история
        stats = robust_stats_latest(transformed, window_years=200, min_obs=12)
        used_window = 200

    if stats is None:          # твърде къса дори за fallback → неутрално
        label, thin = _window_label(transformed, window_years, "пълна история")
        out = _empty_score(name)
        out.update({
            "score": 50.0, "health_z": 0.0, "percentile": 50.0,
            "percentile_window": label,
            "value": scored_val, "display_value": round(scored_val, 4),
            "display_is_pct": is_pct, "last_date": last_date,
            "transform": transform, "polarity": _polarity_repr(polarity),
            "history_n": len(transformed),
            "thin_window": thin,
        })
        return out

    val, med, scale = stats

    # ── Каноничен degenerate guard (единен US/EU/CN) ─────────────────────────
    # MAD=0 в 10-г. прозорец (административно пиннати серии) → scale=0 → фалшиво
    # „неутрално 50" при реален всеисторически екстремум. Fallback: норма от
    # ПЪЛНАТА история; ако и тя е константа → degenerate (неутрално + флаг).
    win = _trailing_window(transformed, used_window)
    scale_fallback = False
    if (scale == 0 or np.isnan(scale)) and len(transformed) > len(win):
        med_f = float(transformed.median())
        mad_f = float((transformed - med_f).abs().median())
        scale_f = 1.4826 * mad_f
        if scale_f > 0 and not np.isnan(scale_f):
            med, scale = med_f, scale_f
            scale_fallback = True
            win = transformed
    degenerate = bool(scale == 0 or np.isnan(scale))

    if degenerate:
        hz = 0.0
        z_raw = 0.0
    else:
        hz = _health_z(val, med, scale, polarity)
        z_raw = (val - med) / scale
        if scale_fallback:
            hz = float(np.clip(hz, -CLIP_SIGMA, CLIP_SIGMA))
            z_raw = float(np.clip(z_raw, -CLIP_SIGMA, CLIP_SIGMA))

    score = round(50.0 * (1.0 + math.tanh(hz / TANH_SLOPE)), 1)
    wide_label = (
        "пълна история" if (scale_fallback or used_window != window_years) else f"{window_years}г"
    )
    percentile_window, thin_window = _window_label(win, window_years, wide_label)

    return {
        "name": name or (s_raw.name or "unknown"),
        "score": score,
        "health_z": round(float(hz), 3),
        "percentile": round(percentile_rank(scored_val, win), 1),
        "percentile_window": percentile_window,
        "z_raw": round(float(z_raw), 3),
        "value": scored_val,
        "display_value": round(scored_val, 4),
        "display_is_pct": is_pct,
        "last_date": last_date,
        "transform": transform,
        "polarity": _polarity_repr(polarity),
        "history_n": len(win),
        "scale_fallback": scale_fallback,
        "degenerate": degenerate,
        "thin_window": thin_window,
    }


# ═════════════════════════════════════════════════════════════════════════════
# ЛЕЩОВА АГРЕГАЦИЯ
# ═════════════════════════════════════════════════════════════════════════════

def compute_lens_reports(catalog: dict, snapshot: dict[str, pd.Series]) -> dict[str, dict]:
    """Серия → health-z → peer-група (средно) → леща (претеглено по peer-група).

    Връща {lens: {"lens", "health_z", "score", "n_series", "series": [...],
                  "peer_groups": [...]}}.
    Леща без нито една скорирана серия → health_z=None, score=None (ИЗПАДА от
    композита; НЕ се брои като „неутрално 50").
    """
    scored: dict[tuple[str, str], dict] = {}
    by_lens_pg: dict[str, dict[str, list[str]]] = {
        lens: defaultdict(list) for lens in MODULE_WEIGHTS
    }
    lens_members: dict[str, list[str]] = {lens: [] for lens in MODULE_WEIGHTS}

    for key, spec in catalog.items():
        for lens in spec.get("lens", []):
            if lens not in by_lens_pg:
                continue
            lens_members[lens].append(key)
            pg = spec.get("peer_group") or key
            by_lens_pg[lens][pg].append(key)
            scored[(lens, key)] = score_series(
                snapshot.get(key),
                spec.get("transform", "level"),
                polarity_for(key, lens),
                name=key,
            )

    reports: dict[str, dict] = {}
    for lens in MODULE_WEIGHTS:
        pg_out: list[dict] = []
        pg_zs: list[tuple[float, float]] = []

        for pg_name in sorted(by_lens_pg[lens]):
            zs = [
                scored[(lens, k)]["health_z"]
                for k in by_lens_pg[lens][pg_name]
                if scored[(lens, k)]["health_z"] is not None
                and not math.isnan(scored[(lens, k)]["health_z"])
            ]
            if not zs:
                pg_out.append({"name": pg_name, "health_z": None, "n_available": 0, "weight": 1.0})
                continue
            pg_z = float(np.mean(zs))
            w = peer_group_weight(pg_name)
            pg_zs.append((pg_z, w))
            pg_out.append({"name": pg_name, "health_z": round(pg_z, 3),
                           "n_available": len(zs), "weight": w})

        series_out = []
        for key in lens_members[lens]:
            spec = catalog[key]
            res = dict(scored[(lens, key)])
            res.update({
                "key": key,
                "name_bg": spec.get("name_bg", key),
                "catalog_id": spec.get("id", ""),
                "narrative_hint": spec.get("narrative_hint", ""),
                "release_schedule": spec.get("release_schedule", "monthly"),
                "is_rate": spec.get("is_rate", False),
            })
            series_out.append(res)

        if not pg_zs:
            reports[lens] = {"lens": lens, "health_z": None, "score": None,
                             "n_series": 0, "series": series_out, "peer_groups": pg_out}
            continue

        wsum = sum(w for _, w in pg_zs)
        lens_z = sum(z * w for z, w in pg_zs) / wsum if wsum else float("nan")
        reports[lens] = {
            "lens": lens,
            "health_z": round(float(lens_z), 3),
            "score": round(50.0 * (1.0 + math.tanh(lens_z / TANH_SLOPE)), 1),
            "n_series": sum(pg["n_available"] for pg in pg_out),
            "series": series_out,
            "peer_groups": pg_out,
        }

    return reports


def compute_module_scores(catalog: dict, snapshot: dict[str, pd.Series]) -> dict:
    """{lens: score | None} — тънка обвивка около compute_lens_reports."""
    return {lens: rep["score"] for lens, rep in compute_lens_reports(catalog, snapshot).items()}


def compute_composite_score(module_scores: dict) -> Optional[float]:
    """Претеглен композит по MODULE_WEIGHTS с РЕНОРМАЛИЗАЦИЯ.

    Празна леща (score=None) изпада и теглата на останалите се преизчисляват —
    вместо да я броим като „неутрално 50", което тихо би дърпало композита към
    средата. Ако нито една леща няма данни → None.
    """
    pairs = [
        (score, MODULE_WEIGHTS[lens])
        for lens, score in module_scores.items()
        if lens in MODULE_WEIGHTS and score is not None and not (
            isinstance(score, float) and math.isnan(score)
        )
    ]
    if not pairs:
        return None
    wsum = sum(w for _, w in pairs)
    if wsum == 0:
        return None
    return round(sum(s * w for s, w in pairs) / wsum, 1)


def get_regime(score: Optional[float]) -> dict:
    """Режимен етикет + цвят за композитен score (фамилната таблица)."""
    if score is None:
        return {"name": "НЯМА ДАННИ", "color": "#8892a4", "score": None}
    for threshold, name, color in MACRO_REGIMES:
        if score >= threshold:
            return {"name": name, "color": color, "score": score}
    threshold, name, color = MACRO_REGIMES[-1]
    return {"name": name, "color": color, "score": score}
