"""
Тестове на e-Stat parse функциите — чисти (JSON фрагменти → Series), без
мрежа. Фикстурите повтарят реалния формат на getStatsData (проверен
2026-08-05, таблица 0003427113): времевата ос СМЕСВА месечни и годишни
редове, месечният код повтаря месеца в последните две двойки.
"""
import pandas as pd
import pytest

from sources.estat_adapter import parse_estat_id, parse_estat_values


# ── source_id парсингът ──────────────────────────────────────────────────────

def test_id_splits_stats_id_and_cd_filters():
    stats_id, params = parse_estat_id("0003427113?tab=1&cat01=0161&area=00000")
    assert stats_id == "0003427113"
    assert params == {"cdTab": "1", "cdCat01": "0161", "cdArea": "00000"}


def test_id_without_query_gives_empty_filters():
    stats_id, params = parse_estat_id("0003427113")
    assert stats_id == "0003427113"
    assert params == {}


def test_id_without_stats_id_raises_loudly():
    with pytest.raises(ValueError):
        parse_estat_id("?tab=1")


# ── VALUE парсингът ──────────────────────────────────────────────────────────

VALUES = [
    {"@time": "2026000606", "$": "113.6"},   # месечен: юни 2026
    {"@time": "2026000505", "$": "113.4"},
    {"@time": "1970000000", "$": "31.0"},    # годишен ред → изпада
    {"@time": "1970000101", "$": "30.9"},    # месечен: януари 1970
    {"@time": "2025000000", "$": "111.9"},   # годишен ред → изпада
]


def test_monthly_rows_parse_annual_rows_drop():
    s = parse_estat_values(VALUES)
    assert len(s) == 3
    assert s.loc["1970-01-01"] == 30.9
    assert s.loc["2026-06-01"] == 113.6


def test_series_is_sorted_ascending():
    s = parse_estat_values(VALUES)
    assert list(s.index) == sorted(s.index)


def test_missing_value_markers_drop_silently():
    s = parse_estat_values([
        {"@time": "2026000606", "$": "-"},
        {"@time": "2026000505", "$": "…"},
        {"@time": "2026000404", "$": "113.2"},
    ])
    assert len(s) == 1
    assert s.iloc[0] == 113.2


def test_mismatched_month_pairs_drop():
    # Защитата срещу непознат времеви формат: двете двойки не съвпадат.
    s = parse_estat_values([{"@time": "2026000607", "$": "113.6"}])
    assert s.empty
