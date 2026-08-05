"""
tests/test_scorer.py
====================
Робастният скоринг двигател (мандат №38 §А1) — портнат от фамилията.

Пази трите неща, заради които percentile-of-full-history падна:
дрейфът (близка норма, не 2000г), MAD=0 капанът (фалшиво „неутрално 50"
върху реален екстремум) и полярността (U-форма за инфлацията).
"""
import math

import pandas as pd
import pytest

from catalog.polarity import U_BAND
from core.primitives import robust_stats_latest
from core.scorer import (
    TANH_SLOPE,
    THIN_WINDOW_FRACTION,
    percentile_rank,
    score_series,
)


def _monthly(values):
    """Месечна серия, завършваща на 2026-06-01 (изцяло след HISTORY_START)."""
    idx = pd.date_range(end="2026-06-01", periods=len(values), freq="MS")
    return pd.Series([float(v) for v in values], index=idx)


# ── Норма и скала ────────────────────────────────────────────────────────────

def test_score_is_fifty_at_the_local_norm():
    """Стойност на медианата на 10-годишния прозорец → точно 50."""
    s = _monthly([1.0, 3.0] * 60 + [2.0])
    res = score_series(s, "level", +1)

    assert res["health_z"] == pytest.approx(0.0)
    assert res["score"] == pytest.approx(50.0)
    assert res["degenerate"] is False


def test_score_is_tanh_of_the_robust_z():
    """score = 50·(1 + tanh(z/2)) върху (x − median₁₀)/(1.4826·MAD₁₀)."""
    s = _monthly([1.0, 3.0] * 60 + [7.0])
    res = score_series(s, "level", +1)

    val, med, scale = robust_stats_latest(s)
    expected = 50.0 * (1.0 + math.tanh(((val - med) / scale) / TANH_SLOPE))

    assert res["score"] == pytest.approx(round(expected, 1))
    assert res["score"] > 50.0


def test_ten_year_window_ignores_the_old_regime():
    """Дефектът, който гасим: серията се съди спрямо близката си норма, не спрямо 2000г."""
    old_era = [10.0] * 180                      # 15 г. „висока" ера
    recent = [1.0, 3.0] * 60 + [2.0]            # последните 10 г. около 2
    s = _monthly(old_era + recent)

    res = score_series(s, "level", +1)
    full_history_pct = float((s < 2.0).mean() * 100)

    assert full_history_pct < 25.0              # старият percentile: „на дъното"
    assert res["score"] == pytest.approx(50.0)  # робастният: „на нормата"
    assert res["percentile_window"] == "10г"


def test_percentile_stays_secondary_context():
    """Percentile се публикува, но НЕ е заглавният score."""
    s = _monthly([1.0, 3.0] * 60 + [7.0])
    res = score_series(s, "level", +1)

    assert res["percentile"] == pytest.approx(
        percentile_rank(7.0, s.tail(121)), abs=0.1
    )
    assert res["score"] != res["percentile"]


# ── MAD = 0 guard ────────────────────────────────────────────────────────────

def test_mad_zero_in_window_falls_back_to_full_history_scale():
    """Пинната серия + реален екстремум: без guard-а → фалшиво 50."""
    s = _monthly([1.0, 9.0] * 98 + [5.0] * 120 + [100.0])
    res = score_series(s, "level", +1)

    assert res["scale_fallback"] is True
    assert res["degenerate"] is False
    assert res["score"] > 95.0                       # екстремумът се вижда
    assert res["percentile_window"] == "пълна история"


def test_scale_fallback_clips_at_six_sigma():
    s = _monthly([1.0, 9.0] * 98 + [5.0] * 120 + [100.0])
    res = score_series(s, "level", +1)

    assert abs(res["health_z"]) <= 6.0
    assert abs(res["z_raw"]) <= 6.0


def test_constant_series_is_degenerate_not_extreme():
    """Без вариация дори в пълната история → неутрално + флаг, не 0/100."""
    s = _monthly([5.0] * 300)
    res = score_series(s, "level", +1)

    assert res["degenerate"] is True
    assert res["score"] == pytest.approx(50.0)
    assert res["health_z"] == pytest.approx(0.0)


# ── Полярност ────────────────────────────────────────────────────────────────

def test_negative_polarity_inverts_the_health():
    s = _monthly([1.0, 3.0] * 60 + [7.0])
    up = score_series(s, "level", +1)
    down = score_series(s, "level", -1)

    assert up["score"] > 50.0
    assert down["score"] < 50.0
    assert up["health_z"] == pytest.approx(-down["health_z"])


def test_u_form_pins_health_at_the_target():
    """Мандатният пин: score(2.0) > score(5.2) И score(2.0) > score(0.0)."""
    def at(x):
        return score_series(_monthly([1.0, 3.0] * 60 + [x]), "level",
                            ("U", "target", 2.0))["score"]

    assert at(2.0) > at(5.2)
    assert at(2.0) > at(0.0)


def test_u_form_stops_deflation_from_scoring_excellent():
    """Наивното „ниско = добре" правеше дефлацията отличник."""
    s = _monthly([1.0, 3.0] * 60 + [0.0])
    naive = score_series(s, "level", -1)["score"]
    u_form = score_series(s, "level", ("U", "target", 2.0))["score"]

    assert naive > 60.0        # старият прочит: „чудесно"
    assert u_form < 50.0       # честният: отклонение от целта


def test_polarity_is_serialised_as_string():
    s = _monthly([1.0, 3.0] * 60 + [2.0])
    assert score_series(s, "level", ("U", "target", 2.0))["polarity"] == "U:target=2.0"
    assert score_series(s, "level", -1)["polarity"] == "-1"


# ── Оптималната зона (мандат №47) ────────────────────────────────────────────
# Кривата: плато в [lo, hi] → спад по 1σ на всеки `s` пункта извън нея.
# АБСОЛЮТНА — нормата (median/MAD) не участва.

ZONE = ("OPT", 0.0, 12.0, 6.0)
PLATEAU_SCORE = round(50.0 * (1.0 + math.tanh(U_BAND / TANH_SLOPE)), 1)  # 73.1


def _opt_score(x, polarity=ZONE, base=None):
    """Score на стойност `x` при OPT полярност, върху произволна норма.

    Базата е разнообразна нарочно: при `[1, 3]` една от тестваните стойности
    занулява MAD и серията влиза в degenerate guard-а (неутрално 50) — тогава
    тестът щеше да мери guard-а, не кривата.
    """
    base = [1.0, 3.0, 5.0, 7.0] * 30 if base is None else base
    return score_series(_monthly(base + [x]), "level", polarity)


def test_inside_the_zone_the_health_plateaus_at_the_u_band():
    """Плато = ЗДРАВЕ (както U-формата в центъра си), не неутралност."""
    for x in (0.0, 1.0, 6.0, 11.9, 12.0):
        res = _opt_score(x)
        assert res["health_z"] == pytest.approx(U_BAND), x
        assert res["score"] == pytest.approx(PLATEAU_SCORE), x


def test_one_slope_width_above_the_zone_scores_exactly_fifty():
    """hi + s → health-z = 0 → точно 50: „на нормата“, вече не здраво."""
    assert _opt_score(18.0)["health_z"] == pytest.approx(0.0)
    assert _opt_score(18.0)["score"] == pytest.approx(50.0)


def test_the_score_falls_by_one_sigma_per_slope_width():
    """Линейният наклон извън зоната: 1σ на всеки `s` пункта."""
    assert _opt_score(15.0)["health_z"] == pytest.approx(0.5)    # hi + s/2
    assert _opt_score(24.0)["health_z"] == pytest.approx(-1.0)   # hi + 2s
    assert _opt_score(30.0)["health_z"] == pytest.approx(-2.0)   # hi + 3s
    assert _opt_score(30.0)["score"] == pytest.approx(
        round(50.0 * (1.0 + math.tanh(-2.0 / TANH_SLOPE)), 1)
    )


def test_the_curve_is_continuous_at_the_upper_edge():
    """Няма скок на прага — иначе 11.99 и 12.01 биха били различни светове."""
    just_in = _opt_score(11.999)["health_z"]
    just_out = _opt_score(12.001)["health_z"]
    assert just_out == pytest.approx(just_in, abs=1e-3)


def test_below_the_lower_bound_the_penalty_mirrors_the_upper_one():
    """Спадът под lo е СИМЕТРИЧЕН — свиващ се кредит не е здраве."""
    zone = ("OPT", 0.0, 12.0, 6.0)
    above = _opt_score(12.0 + 9.0, zone)["health_z"]
    below = _opt_score(0.0 - 9.0, zone)["health_z"]
    assert above == pytest.approx(below)
    assert below == pytest.approx(U_BAND - 1.5)


def test_a_boom_deep_above_the_zone_saturates_near_zero():
    """2007: фирменият кредит на 72.4% г/г → сатурация, не „отличник“."""
    res = _opt_score(72.4)
    assert res["score"] < 2.0


def test_the_zone_is_absolute_and_ignores_the_local_norm():
    """Ядрото на П2: същата стойност → същият score, каквато и да е нормата.

    Робастният z би дал ДРУГО число при бум прозорец (нормата се вдига заедно с
    серията и уредът аплодира прегряването) — точно това гасят котвите.
    """
    calm = _opt_score(20.0, base=[1.0, 3.0] * 60)
    boom = _opt_score(20.0, base=[18.0, 22.0] * 60)
    assert calm["health_z"] == pytest.approx(boom["health_z"])
    assert calm["score"] == boom["score"]

    linear_calm = score_series(_monthly([1.0, 3.0] * 60 + [20.0]), "level", +1)
    linear_boom = score_series(_monthly([18.0, 22.0] * 60 + [20.0]), "level", +1)
    assert linear_calm["score"] != linear_boom["score"]


def test_the_optimal_zone_is_serialised_as_a_readable_string():
    assert _opt_score(5.0)["polarity"] == "OPT[0..12]/6"
    assert _opt_score(5.0, ("OPT", -20.0, 40.0, 15.0))["polarity"] == "OPT[-20..40]/15"


def test_a_too_short_series_falls_back_to_neutral_fifty_and_the_thermometer_covers_it():
    """ДЕКЛАРИРАНОТО ограничение (мандат №47 §А1).

    Под 12 наблюдения скорерът няма норма и връща неутрално 50 — включително за
    OPT серия, чиято зона е абсолютна и би могла да се произнесе. Това бие само
    в най-ранните редове на реконструкцията (до 2009 при кредитните серии) и е
    прието: температурният слой мери СЪЩИТЕ серии независимо от скорера, затова
    бумът 2006-2008 се вижда в `temp_count` дори където score-ът мълчи.
    """
    short = _monthly([30.0] * 8)          # далеч над зоната, но твърде къса
    res = score_series(short, "level", ZONE)

    assert res["score"] == pytest.approx(50.0)
    assert res["health_z"] == pytest.approx(0.0)


def test_a_boom_series_scores_lower_under_the_zone_than_under_plus_one():
    """Композитът пада ЗАЩОТО бумът вече не се брои за здраве."""
    boom = [18.0, 22.0] * 60
    with_zone = score_series(_monthly(boom + [21.0]), "level", ZONE)["score"]
    with_plus_one = score_series(_monthly(boom + [21.0]), "level", +1)["score"]
    assert with_zone < with_plus_one


# ── Трансформация преди скоринга ─────────────────────────────────────────────

def test_transform_is_applied_before_scoring():
    """Номинално растящ индекс се съди на ТЕМП, не на ниво."""
    levels = [100.0 * (1.10 ** (i / 12)) for i in range(300)]
    s = _monthly(levels)

    res = score_series(s, "yoy_pct", +1)

    assert res["display_is_pct"] is True
    assert res["display_value"] == pytest.approx(10.0, abs=0.6)
    assert res["score"] < 90.0     # постоянен темп → близо до нормата, не екстремум


def test_empty_series_returns_empty_score():
    res = score_series(pd.Series(dtype="float64"), "level", +1, name="X")
    assert res["score"] is None
    assert res["health_z"] is None
    assert res["name"] == "X"
    assert res["thin_window"] is False


# ── Честният къс прозорец (мандат №39 §А3) ───────────────────────────────────

def test_short_series_does_not_claim_a_ten_year_window():
    """Заемите: ~3.4 г. данни в 10-годишен прозорец. „10г" би било лъжа."""
    s = _monthly([1.0, 3.0] * 20 + [7.0])          # 41 месеца ≈ 3.4 г.
    res = score_series(s, "level", +1, history_start="2000-01-01")

    assert res["thin_window"] is True
    assert res["percentile_window"].startswith("къс прозорец (от ")
    assert "10г" not in res["percentile_window"]


def test_short_window_label_says_when_the_norm_starts():
    s = _monthly([1.0, 3.0] * 20 + [7.0])
    start = s.index[0].strftime("%Y-%m")
    assert score_series(s, "level", +1)["percentile_window"] == (
        f"къс прозорец (от {start})"
    )


def test_a_full_window_is_not_flagged_as_thin():
    s = _monthly([1.0, 3.0] * 60 + [2.0])          # 121 месеца = 10 г.
    res = score_series(s, "level", +1)

    assert res["thin_window"] is False
    assert res["percentile_window"] == "10г"


def test_thin_flag_does_not_change_the_score_itself():
    """Флагът е ЧЕСТНОСТ за прозореца, не корекция на числото."""
    s = _monthly([1.0, 3.0] * 20 + [7.0])
    res = score_series(s, "level", +1)

    val, med, scale = robust_stats_latest(s)
    expected = 50.0 * (1.0 + math.tanh(((val - med) / scale) / TANH_SLOPE))
    assert res["score"] == pytest.approx(round(expected, 1))


def test_threshold_is_seventy_percent_of_the_window():
    assert THIN_WINDOW_FRACTION == pytest.approx(0.70)
    # 8 години в 10-годишен прозорец → над прага, не е тънък
    wide = score_series(_monthly([1.0, 3.0] * 48 + [2.0]), "level", +1)
    assert wide["thin_window"] is False
