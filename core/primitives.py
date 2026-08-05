"""
core/primitives.py
==================
Математически примитиви за макро анализ.

Робастната част (`robust_stats_latest`) е портната от фамилния двигател
(`dashboards/eu-macro-dashboard/core/primitives.py`) — виж
`dashboards/macro-satellite/LENS_SCORING_METHODOLOGY.md` §2.
"""
import numpy as np
import pandas as pd
from typing import Optional

# ─── Константи на фамилния примитив (синхронни с core/scorer.py) ─────────────
WINDOW_YEARS = 10   # близката норма = последните 10 години
MIN_OBS = 36        # ≥3 г. в прозореца, иначе fallback към пълната история
MAD_TO_SIGMA = 1.4826


def compute_yoy_pct(series: pd.Series) -> pd.Series:
    """Изчислява Year-over-Year процентно изменение."""
    if series.empty:
        return series
        
    # `pd.infer_freq` ХВЪРЛЯ при < 3 дати („Need at least 3 dates to infer
    # frequency"), а не връща None. Кодът отдолу вече има път за „не можах да
    # позная" — грешката просто не стигаше до него. Мандат №45: реконструираната
    # история реже сериите при ранните тримесечни маркове и кредитният seed има
    # ТОЧНО една точка на 2005-12-01 → без този guard build-ът гърми.
    # Поведението при ≥3 дати е непроменено, затова живите числа не мърдат.
    try:
        freq = pd.infer_freq(series.index)
    except ValueError:
        freq = None
    periods = 12
    if freq:
        if freq.startswith('Q'):
            periods = 4
        elif freq.startswith('A'):
            periods = 1
            
    # Fallback to manual shift if frequency inference fails
    if not freq:
        # Check median days between points
        diffs = series.index.to_series().diff().dt.days.median()
        if diffs > 80 and diffs < 100:  # Quarterly
            periods = 4
        elif diffs > 350:  # Annual
            periods = 1
            
    # Zero-base guard (порт от EU): база минаваща през 0 → pct_change дава ±inf,
    # т.е. фалшив вечен екстремум. inf → NaN (легитимно „недефинирано").
    return _no_inf(series.pct_change(periods=periods) * 100.0)

def compute_mom_pct(series: pd.Series) -> pd.Series:
    """Изчислява Month-over-Month (или период-към-период) процентно изменение."""
    return _no_inf(series.pct_change(periods=1) * 100.0)

def compute_qoq_pct(series: pd.Series) -> pd.Series:
    """Изчислява Quarter-over-Quarter процентно изменение."""
    return _no_inf(series.pct_change(periods=1) * 100.0)

def _no_inf(series: pd.Series) -> pd.Series:
    """±inf → NaN. Пази скоринга от нулева база в знаменателя."""
    return series.replace([np.inf, -np.inf], np.nan)

def compute_roll4q_mean(series: pd.Series) -> pd.Series:
    """
    4-тримесечна плъзгаща средна.
    Конвенционалният прочит за съотношения като текуща сметка / БВП —
    изглажда тримесечната сезонност, без да маскира тренда.
    """
    return series.rolling(4).mean()

def compute_yoy_roll4(series: pd.Series) -> pd.Series:
    """4-периодна плъзгаща средна НА годишния темп (мандат №47 §А2).

    За серии, чието сурово г/г е твърде шумно, за да носи АБСОЛЮТЕН праг:
    разрешителните за строеж скачат ±60% на тримесечие и всяка зона се дави в
    шума (2015-19 max на суровото г/г = 61.1 срещу 38.7 на плъзгащата). Редът е
    важен: първо темпът, после изглаждането — обратното („темп на плъзгащата")
    би смесило две различни трансформации.
    """
    return compute_yoy_pct(series).rolling(4).mean()

def compute_z_score(series: pd.Series, window: int = None) -> pd.Series:
    """Изчислява Z-score (ролиращ или върху цялата серия)."""
    if window:
        mean = series.rolling(window=window, min_periods=window//2).mean()
        std = series.rolling(window=window, min_periods=window//2).std()
    else:
        mean = series.mean()
        std = series.std()
        
    # Prevent division by zero
    std = std.replace(0, np.nan)
    return (series - mean) / std

def apply_transform(series: pd.Series, transform: str) -> pd.Series:
    """Прилага трансформация според каталога."""
    if series.empty:
        return series
        
    if transform == "level":
        return series
    elif transform == "yoy_pct":
        return compute_yoy_pct(series)
    elif transform == "mom_pct":
        return compute_mom_pct(series)
    elif transform == "qoq_pct":
        return compute_qoq_pct(series)
    elif transform == "roll4q_mean":
        return compute_roll4q_mean(series)
    elif transform == "yoy_roll4":
        return compute_yoy_roll4(series)
    elif transform == "z_score":
        return compute_z_score(series)
    elif transform == "first_diff":
        return series.diff()

    return series


def robust_stats_latest(
    series: pd.Series,
    window_years: int = WINDOW_YEARS,
    min_obs: int = MIN_OBS,
) -> Optional[tuple[float, float, float]]:
    """Робастна норма на последната точка спрямо плъзгащ прозорец.

    Връща (latest_value, median, scale), scale = 1.4826 · MAD (σ-еквивалент,
    устойчив на outlier-и — един COVID месец не разтяга скалата). Прозорецът е
    последните `window_years` години ДО последното наблюдение. None ако в
    прозореца има < min_obs точки (недостатъчна норма → викащият решава).
    """
    s = series.dropna()
    if s.empty:
        return None
    if isinstance(s.index, pd.DatetimeIndex):
        cutoff = s.index[-1] - pd.DateOffset(years=window_years)
        w = s[s.index >= cutoff]
    else:
        w = s
    if len(w) < min_obs:
        return None
    med = float(w.median())
    mad = float((w - med).abs().median())
    return float(s.iloc[-1]), med, MAD_TO_SIGMA * mad
