"""
tests/test_primitives.py
========================
Математиката под трансформациите.
"""
import numpy as np
import pandas as pd
import pytest

from core.primitives import (
    MIN_OBS,
    WINDOW_YEARS,
    apply_transform,
    compute_roll4q_mean,
    compute_yoy_pct,
    compute_yoy_roll4,
    robust_stats_latest,
)


def _quarterly(values):
    idx = pd.date_range("2020-01-01", periods=len(values), freq="QS")
    return pd.Series([float(v) for v in values], index=idx)


def _monthly(values):
    idx = pd.date_range(end="2026-06-01", periods=len(values), freq="MS")
    return pd.Series([float(v) for v in values], index=idx)


def test_roll4q_mean_is_four_period_rolling_average():
    s = _quarterly([1, 2, 3, 4, 5, 6])
    r = compute_roll4q_mean(s)

    # Първите три точки нямат пълен прозорец
    assert r.iloc[:3].isna().all()
    assert r.iloc[3] == pytest.approx(2.5)   # (1+2+3+4)/4
    assert r.iloc[4] == pytest.approx(3.5)   # (2+3+4+5)/4
    assert r.iloc[5] == pytest.approx(4.5)   # (3+4+5+6)/4


def test_roll4q_mean_reachable_through_apply_transform():
    s = _quarterly([-1.8, -3.98, -5.45, -6.55])
    direct = compute_roll4q_mean(s)
    through = apply_transform(s, "roll4q_mean")
    pd.testing.assert_series_equal(direct, through)


def test_roll4q_mean_smooths_single_quarter_spike():
    """Едно лошо тримесечие не бива да води целия прочит."""
    s = _quarterly([-2.0, -2.0, -2.0, -10.0])
    assert apply_transform(s, "roll4q_mean").iloc[-1] == pytest.approx(-4.0)


def test_yoy_pct_on_quarterly_index_uses_four_periods():
    # Четири тримесечия на 100, после четири на 110 → +10% г/г от 5-тата точка
    s = _quarterly([100, 100, 100, 100, 110, 110, 110, 110])
    yoy = compute_yoy_pct(s)

    assert yoy.iloc[:4].isna().all()
    assert yoy.iloc[4] == pytest.approx(10.0)
    assert yoy.iloc[7] == pytest.approx(10.0)


def test_yoy_pct_on_monthly_index_uses_twelve_periods():
    idx = pd.date_range("2020-01-01", periods=14, freq="MS")
    s = pd.Series([100.0] * 12 + [105.0, 105.0], index=idx)
    yoy = compute_yoy_pct(s)

    assert yoy.iloc[:12].isna().all()
    assert yoy.iloc[12] == pytest.approx(5.0)


# ── yoy_roll4: изгладеният годишен темп (мандат №47 §А2) ─────────────────────

def test_yoy_roll4_is_the_four_period_mean_of_the_year_on_year_rate():
    """Аритметичният пин: първо темпът, после изглаждането — в този ред."""
    s = _quarterly([100, 100, 100, 100, 110, 120, 130, 140])
    r = compute_yoy_roll4(s)

    # Първите 4 нямат г/г; 5-та…7-ма нямат пълен 4-периоден прозорец
    assert r.iloc[:7].isna().all()
    # г/г: +10, +20, +30, +40 → средно 25
    assert r.iloc[7] == pytest.approx(25.0)


def test_yoy_roll4_reachable_through_apply_transform():
    s = _quarterly([100, 100, 100, 100, 110, 120, 130, 140])
    pd.testing.assert_series_equal(compute_yoy_roll4(s), apply_transform(s, "yoy_roll4"))


def test_yoy_roll4_smooths_a_single_quarter_spike_in_the_growth_rate():
    """Причината серията да мине на плъзгаща: едно тримесечие не бива да чупи
    абсолютния праг (разрешителните скачат ±60% на тримесечие)."""
    s = _quarterly([100, 100, 100, 100, 105, 105, 105, 200])
    raw = compute_yoy_pct(s)
    smooth = compute_yoy_roll4(s)

    assert raw.iloc[7] == pytest.approx(100.0)      # суровото г/г: +100%
    assert smooth.iloc[7] == pytest.approx(28.75)   # (5+5+5+100)/4
    assert smooth.iloc[7] < raw.iloc[7]


def test_yoy_roll4_inherits_the_zero_base_guard():
    s = _quarterly([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
    assert not np.isinf(compute_yoy_roll4(s).to_numpy()).any()


# ── Zero-base guard (порт от EU) ─────────────────────────────────────────────

def test_yoy_pct_with_a_zero_base_is_undefined_not_infinite():
    """База през 0 (съотношение/спред) → ±inf беше фалшив вечен екстремум."""
    s = _quarterly([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
    yoy = compute_yoy_pct(s)

    assert np.isnan(yoy.iloc[4])              # 4.0 спрямо база 0.0
    assert not np.isinf(yoy.to_numpy()).any()


def test_qoq_pct_also_guards_the_zero_base():
    s = _quarterly([0.0, 5.0, 10.0])
    assert np.isnan(apply_transform(s, "qoq_pct").iloc[1])


# ── Робастна норма ───────────────────────────────────────────────────────────

def test_robust_stats_returns_latest_median_and_mad_scale():
    s = _monthly([1.0, 3.0] * 60 + [2.0])
    val, med, scale = robust_stats_latest(s)

    assert val == pytest.approx(2.0)
    assert med == pytest.approx(2.0)
    assert scale == pytest.approx(1.4826)     # MAD = 1 → 1.4826·MAD


def test_robust_stats_window_is_the_last_ten_years():
    """Старият режим стои извън прозореца и не мести нормата."""
    s = _monthly([50.0] * 200 + [1.0, 3.0] * 60 + [2.0])
    _, med, _ = robust_stats_latest(s)
    assert med == pytest.approx(2.0)


def test_robust_stats_needs_enough_observations():
    assert robust_stats_latest(_monthly([1.0] * (MIN_OBS - 1))) is None
    assert robust_stats_latest(_monthly([1.0, 3.0] * MIN_OBS)) is not None


def test_robust_stats_reports_zero_scale_for_a_pinned_series():
    """MAD=0 не се крие — викащият решава (scale_fallback / degenerate)."""
    _, _, scale = robust_stats_latest(_monthly([7.0] * 200))
    assert scale == pytest.approx(0.0)


def test_family_constants_are_the_documented_ones():
    assert WINDOW_YEARS == 10
    assert MIN_OBS == 36
