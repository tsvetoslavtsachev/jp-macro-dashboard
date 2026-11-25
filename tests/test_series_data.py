"""
Тестове на export/series_data.py — схемата е договорът с US/CN (§ ПРОЛЕТР4).
Без мрежа: синтетичен snapshot + реалният каталог за имената.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from catalog.series import SERIES_CATALOG
from core.scorer import compute_lens_reports
from export.series_data import (
    LATEST_KEYS,
    META_KEYS,
    SERIES_DATA_KEYS,
    build_series_data,
    change_kind,
    relative_staleness,
)

TODAY = date(2026, 11, 25)

# Опорни ключове, поискани от мандата
REQUIRED = {
    "JP_CPI": "headline", "JP_CPI_CORE": "core", "JP_CPI_CORECORE": "core-core",
    "JP_CGPI": "CGPI", "JP_RGDP": "реален БВП", "JP_INDPRO": "промишлено",
    "JP_RETAIL": "дребно", "JP_UNRATE": "безработица", "JP_EARNINGS_MFG": "заплати",
    "JP_USDJPY": "USDJPY", "JP_JGB_10Y_D": "10y дневна", "JP_10Y": "10y месечна",
    "JP_CALL_RATE": "call rate",
}


def _snapshot(end="2026-10-01"):
    snap = {}
    for key, spec in SERIES_CATALOG.items():
        sched = spec["release_schedule"]
        freq = {"daily": "B", "weekly": "W-FRI", "monthly": "MS",
                "quarterly": "QS", "annually": "YS"}[sched]
        idx = pd.date_range(end=end, periods=400 if sched == "daily" else 180, freq=freq)
        rng = np.random.default_rng(abs(hash(key)) % 2**32)
        snap[key] = pd.Series(100 + np.cumsum(rng.normal(0, 1, len(idx))), index=idx)
    return snap


@pytest.fixture(scope="module")
def built():
    snap = _snapshot()
    reports = compute_lens_reports(SERIES_CATALOG, snap)
    return build_series_data(snap, reports, today=TODAY), snap


def test_required_series_are_in_catalog_with_bulgarian_names():
    for key in REQUIRED:
        assert key in SERIES_CATALOG, key
        assert any("Ѐ" <= ch <= "ӿ" for ch in SERIES_CATALOG[key]["name_bg"]), key


def test_schema_top_level_meta_latest_keys(built):
    data, _ = built
    assert tuple(data) == SERIES_DATA_KEYS
    assert data["region"] == "JP" and data["years_included"] == 10
    assert data["series_count"] == len(data["series"]) == len(SERIES_CATALOG)
    for key, ser in data["series"].items():
        assert set(ser) == {"meta", "latest", "chart"}, key
        assert set(ser["meta"]) == set(META_KEYS), key
        assert set(ser["latest"]) == set(LATEST_KEYS), key
        assert len(ser["chart"]["dates"]) == len(ser["chart"]["values"]) > 0, key


def test_chart_is_last_ten_years_only(built):
    data, _ = built
    cutoff = str(pd.Timestamp(TODAY) - pd.DateOffset(years=10))[:10]
    assert all(d >= cutoff for ser in data["series"].values() for d in ser["chart"]["dates"])


def test_scores_come_from_the_scorer_not_a_second_calculation(built):
    data, snap = built
    reports = compute_lens_reports(SERIES_CATALOG, snap)
    unrate = next(s for s in reports["labor"]["series"] if s["key"] == "JP_UNRATE")
    assert data["series"]["JP_UNRATE"]["latest"]["score"] == unrate["score"]
    assert data["series"]["JP_UNRATE"]["latest"]["health_z"] == unrate["health_z"]


def test_change_kind_natural_units():
    assert change_kind("JP_JGB_10Y_D", SERIES_CATALOG["JP_JGB_10Y_D"]) == "bps"
    assert change_kind("JP_UNRATE", SERIES_CATALOG["JP_UNRATE"]) == "bps"
    assert change_kind("JP_CPI", SERIES_CATALOG["JP_CPI"]) == "absolute"   # pp
    assert change_kind("JP_USDJPY", SERIES_CATALOG["JP_USDJPY"]) == "percent"


def test_staleness_is_relative_to_cadence():
    ref = {"monthly": pd.Timestamp("2026-10-01"), "daily": pd.Timestamp("2026-11-25")}
    assert relative_staleness("2026-10-01", "monthly", ref) == (False, 0)
    assert relative_staleness("2026-08-01", "monthly", ref) == (False, 2)   # 61 дни < 90
    assert relative_staleness("2026-06-01", "monthly", ref) == (True, 4)    # 122 дни > 90
    # дневна серия 3 дни зад — нормален lag, 30 дни зад — stale
    assert relative_staleness("2026-11-22", "daily", ref)[0] is False
    assert relative_staleness("2026-10-25", "daily", ref)[0] is True
    # без референция / без дата — не стале
    assert relative_staleness(None, "monthly", ref) == (False, 0)
    assert relative_staleness("2026-01-01", "weekly", ref) == (False, 0)


def test_stale_flag_lands_in_output():
    snap = _snapshot()
    key = "JP_UNRATE"
    snap[key] = snap[key][snap[key].index <= "2026-05-01"]   # 5 месеца зад
    data = build_series_data(snap, None, today=TODAY)
    assert data["series"][key]["latest"]["stale"] is True
    assert data["series"][key]["latest"]["periods_behind"] == 5
