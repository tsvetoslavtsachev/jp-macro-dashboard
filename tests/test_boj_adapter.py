"""
Тестове на BOJ wide-CSV парсинга — чисти (текст → Series), без мрежа.
Фикстурата повтаря реалния формат (проверен 2026-08-05): header с празни
мета клетки + YYYYMM периоди (вкл. БЪДЕЩИ празни колони — BP файлът върви
до 202702 при данни до 202605), после редове с променлив брой мета колони.
"""
import pandas as pd
import pytest

from sources.boj_adapter import parse_boj_wide

# BP-стил: 4 мета колони (код, набор, име, единица) + бъдеща празна колона
BP_SAMPLE = (
    ',,,,199601,199602,202605,202702\n'
    'BPBP6JYNCB,"Balance of Payments (Data Based on the BPM6)",'
    '"Current account/Net balance","100 million Yen",'
    '341.51732161,8609.02695631,39682.53973505,\n'
    'BPBP6JYNTS,"Balance of Payments (Data Based on the BPM6)",'
    '"Goods & services/Net balance","100 million Yen",'
    '-3099.23378043,3814.38765226,,\n'
)

# CGPI-стил: 3 мета колони + NA маркер
CGPI_SAMPLE = (
    ',,,202001,202002,202606\n'
    'PRCG20_2200000000,"Corporate Goods Price Index (2020 Base)",'
    '"[Producer Price Index] All commodities",102.1,101.7,135.4\n'
    'PRCG20_XXX,"Corporate Goods Price Index (2020 Base)","Other",NA,99.1,\n'
)


def test_bp_current_account_parses_with_four_meta_columns():
    s = parse_boj_wide(BP_SAMPLE, "BPBP6JYNCB")
    assert len(s) == 3
    assert s.loc["1996-01-01"] == pytest.approx(341.51732161)
    assert s.loc["2026-05-01"] == pytest.approx(39682.53973505)


def test_future_empty_columns_drop_silently():
    s = parse_boj_wide(BP_SAMPLE, "BPBP6JYNCB")
    assert pd.Timestamp("2027-02-01") not in s.index


def test_cgpi_parses_with_three_meta_columns():
    s = parse_boj_wide(CGPI_SAMPLE, "PRCG20_2200000000")
    assert len(s) == 3
    assert s.loc["2026-06-01"] == 135.4


def test_na_markers_drop_not_zero():
    s = parse_boj_wide(CGPI_SAMPLE, "PRCG20_XXX")
    assert len(s) == 1
    assert s.iloc[0] == 99.1


def test_missing_row_code_raises_loudly():
    with pytest.raises(ValueError, match="липсва"):
        parse_boj_wide(BP_SAMPLE, "NO_SUCH_CODE")


def test_header_without_periods_raises_loudly():
    with pytest.raises(ValueError, match="формат"):
        parse_boj_wide("a,b,c\nx,y,z\n", "x")
