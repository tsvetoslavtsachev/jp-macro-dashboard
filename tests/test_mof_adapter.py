"""
Тестове на MOF parse функциите — чисти (текст → Series), без мрежа.
Фикстурите са РЕАЛНИ редове от двата CSV-а (свалени 2026-08-05) — форматът
се пази такъв, какъвто MOF го сервира, вкл. декоративния първи ред на JGB
файла и full-width пунктуацията на week.csv.
"""
import pandas as pd
import pytest

from sources.mof_adapter import (
    FLOW_FIELDS,
    _parse_period_end,
    parse_flows_csv,
    parse_jgb_csv,
)

JGB_SAMPLE = """Interest Rate,,,,,,,,,,,,,,,(Unit : %)
Date,1Y,2Y,3Y,4Y,5Y,6Y,7Y,8Y,9Y,10Y,15Y,20Y,25Y,30Y,40Y
1974/9/24,10.327,9.362,8.83,8.515,8.348,8.29,8.24,8.121,8.127,-,-,-,-,-,-
1974/9/25,10.333,9.364,8.831,8.516,8.348,8.29,8.24,8.121,8.127,-,-,-,-,-,-
2026/7/31,1.255,1.507,1.658,1.876,2.044,2.19,2.343,2.517,2.658,2.801,3.382,3.69,3.987,3.982,3.967
"""

# Ред 1: нормална седмица · ред 2: седмица през граница на месец
FLOWS_SAMPLE = (
    '対外及び対内証券売買契約等の状況,,,,,,,,,,,,,,,,,,,junk,,,\n'
    '"期間\nPeriod",   株式,,,   中 長 期 債 ,,,  小  計,   短 期 債,,,  合  計,'
    '   株式,,,   中 長 期 債 ,,,  小  計,   短 期 債,,,  合  計\n'
    '2005．1．2～ 1．8,"1,689 ","1,419 ",270 ,"23,929 ","15,051 ","8,878 ",'
    '"9,149 ","1,662 ","1,001 ",662 ,"9,811 ","17,853 ","15,575 ","2,278 ",'
    '"15,867 ","11,675 ","4,192 ","6,470 ","7,885 ","3,991 ","3,894 ","10,363 "\n'
    '2026．6．28～7．4,"43,977 ","35,732 ","8,245 ","112,693 ","114,865 ",'
    '"-2,173 ","6,073 ","6,781 ","8,024 ","-1,243 ","4,830 ","450,633 ",'
    '"450,847 ",-213 ,"82,929 ","83,313 ",-384 ,-597 ,"36,832 ","36,786 ",46 ,-551 \n'
)


# ── JGB кривата ──────────────────────────────────────────────────────────────

def test_jgb_parses_a_tenor_with_real_dates():
    s = parse_jgb_csv(JGB_SAMPLE, "2Y")
    assert len(s) == 3
    assert s.index[0] == pd.Timestamp("1974-09-24")
    assert s.iloc[0] == 9.362
    assert s.iloc[-1] == 1.507


def test_jgb_missing_dash_observations_drop_out_not_zero():
    s = parse_jgb_csv(JGB_SAMPLE, "10Y")
    # 1974-те редове имат "-" за 10Y → изпадат; остава само живият ред.
    assert len(s) == 1
    assert s.iloc[0] == 2.801


def test_jgb_long_end_parses_too():
    s = parse_jgb_csv(JGB_SAMPLE, "40Y")
    assert len(s) == 1
    assert s.iloc[0] == 3.967


def test_jgb_unknown_tenor_raises_loudly():
    with pytest.raises(ValueError):
        parse_jgb_csv(JGB_SAMPLE, "50Y")


# ── Периодът на week.csv ─────────────────────────────────────────────────────

def test_period_end_within_month():
    assert _parse_period_end("2005．1．2～ 1．8") == pd.Timestamp("2005-01-08")


def test_period_end_crossing_month_carries_end_month():
    assert _parse_period_end("2026．6．28～7．4") == pd.Timestamp("2026-07-04")


def test_period_end_crossing_new_year_bumps_the_year():
    # 28.12～3.1: крайният месец < началния → годината се вдига.
    assert _parse_period_end("2025．12．28～1．3") == pd.Timestamp("2026-01-03")


def test_non_period_rows_are_ignored():
    assert _parse_period_end("（備考）") is None
    assert _parse_period_end("") is None


def test_period_end_accepts_python_shift_jis_wave_dash():
    # Python shift_jis → U+301C „〜"; .NET → U+FF5E „～". Живият файл през
    # requests+Python идва с U+301C — регресията, хваната на първия жив пуск.
    assert _parse_period_end("2005．1．2〜 1．8") == pd.Timestamp("2005-01-08")


# ── Потоците ─────────────────────────────────────────────────────────────────

def test_flows_nonres_equity_net_column_is_the_right_one():
    s = parse_flows_csv(FLOWS_SAMPLE, "nonres_equity_net")
    # 2005-01-08: нерез. акции net = 2,278 · 2026-07-04: net = -213
    assert len(s) == 2
    assert s.loc["2005-01-08"] == 2278.0
    assert s.loc["2026-07-04"] == -213.0


def test_flows_res_ltdebt_net_handles_negatives_and_thousand_commas():
    s = parse_flows_csv(FLOWS_SAMPLE, "res_ltdebt_net")
    assert s.loc["2005-01-08"] == 8878.0
    assert s.loc["2026-07-04"] == -2173.0


def test_flows_header_rows_do_not_leak_into_data():
    for field in FLOW_FIELDS:
        s = parse_flows_csv(FLOWS_SAMPLE, field)
        assert len(s) == 2, field


def test_flows_unknown_field_raises_loudly():
    with pytest.raises(ValueError):
        parse_flows_csv(FLOWS_SAMPLE, "no_such_field")
