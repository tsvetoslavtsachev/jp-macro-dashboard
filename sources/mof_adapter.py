"""
sources/mof_adapter.py
======================
MOF адаптер — двата стабилни CSV-а на японското Министерство на финансите
(живо проверени 2026-08-05, скаутът на INIT-26):

  · JGB кривата: jgbcme_all.csv — daily, колони Date,1Y…40Y, от 1974-09-24.
    Първият ред е декоративен („Interest Rate,…(Unit : %)"), вторият е
    истинският header. Липсващо наблюдение = "-". Дати като 1974/9/24.
  · Седмичните портфейлни потоци: week.csv — ⚠ Shift-JIS! Английският път
    (/english/…/week.csv) връща 404 — ползва се JP-пътят. Двуезични headers
    (~15 реда), после данни. Период „2005．1．2～ 1．8" (full-width точки,
    годината само отпред). Единица: 100 млн йени. Знак: + = нетно придобиване.
    Датовата конвенция ТУК: серията сяда на КРАЯ на седмицата.

source_id конвенция в каталога:
  · "jgb:<tenor>"   — tenor ∈ {1Y,2Y,…,10Y,15Y,20Y,25Y,30Y,40Y}
  · "flows:<field>" — field ∈ FLOW_FIELDS (виж долу)

Parse функциите са чисти (текст → Series) — тестват се без мрежа.
"""
from __future__ import annotations

import csv
import io
import re

import pandas as pd
import requests

from sources._base import BaseAdapter

import config

# Колонните индекси в week.csv (0 = период). Секция 1 = резиденти навън
# (Portfolio Investment Assets), секция 2 = нерезиденти навътре (Liabilities).
# Индексите са срещу ИСТИНСКИЯ подреден ред „取得,処分,ネット,…" (ред 3 от
# header блока): equity(1,2,3) · LT debt(4,5,6) · subtotal(7) · ST(8,9,10) ·
# total(11) · после секция 2 огледално от 12.
FLOW_FIELDS: dict[str, int] = {
    "res_equity_net":     3,   # резиденти: нетно в чужди акции
    "res_ltdebt_net":     6,   # резиденти: нетно в чужди дългосрочни облигации
    "res_total":         11,
    "nonres_equity_net": 14,   # нерезиденти: нетно в японски акции
    "nonres_ltdebt_net": 17,   # нерезиденти: нетно в японски дългосрочни облигации
    "nonres_total":      22,
}

JGB_TENORS = {"1Y", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y",
              "15Y", "20Y", "25Y", "30Y", "40Y"}

# Период „2026．6．28～7．4" / „2005．1．2～ 1．8": година．месец．ден～[месец．]ден
# ⚠ Тирето: Python shift_jis декодира 0x8160 като U+301C „〜" (WAVE DASH), а
# .NET — като U+FF5E „～" (FULLWIDTH TILDE). Приемаме и двете, иначе parse-ът
# работи във фикстурата и мълчи на живия файл.
_PERIOD_RE = re.compile(
    r"^\s*(\d{4})．\s*(\d{1,2})．\s*(\d{1,2})\s*[～〜]\s*(?:(\d{1,2})．)?\s*(\d{1,2})\s*$"
)


def parse_jgb_csv(text: str, tenor: str) -> pd.Series:
    """jgbcme_all.csv текст → daily Series за един tenor. '-' → NaN (изпада)."""
    lines = text.splitlines()
    # Истинският header е редът, който почва с "Date," (първият е декоративен).
    header_i = next(i for i, ln in enumerate(lines) if ln.startswith("Date,"))
    header = lines[header_i].split(",")
    if tenor not in header:
        raise ValueError(f"jgbcme_all.csv: непознат tenor {tenor!r} (има {header[1:]})")
    col = header.index(tenor)

    dates, values = [], []
    for ln in lines[header_i + 1:]:
        parts = ln.split(",")
        if len(parts) <= col or not parts[0].strip():
            continue
        raw = parts[col].strip()
        if raw in ("", "-"):
            continue
        try:
            values.append(float(raw))
            dates.append(pd.Timestamp(parts[0].strip().replace("/", "-")))
        except (ValueError, TypeError):
            continue
    return pd.Series(values, index=pd.DatetimeIndex(dates)).sort_index()


def _parse_period_end(raw: str) -> pd.Timestamp | None:
    """„2026．6．28～7．4" → 2026-07-04 (краят на седмицата).

    Годината е само отпред; ако крайният месец < началния, периодът е
    прехвърлил Нова година (28.12～3.1) и годината се вдига с 1.
    """
    m = _PERIOD_RE.match(raw)
    if not m:
        return None
    year, m1, _d1, m2, d2 = m.groups()
    year, m1, d2 = int(year), int(m1), int(d2)
    m2 = int(m2) if m2 else m1
    if m2 < m1:
        year += 1
    try:
        return pd.Timestamp(year=year, month=m2, day=d2)
    except ValueError:
        return None


def parse_flows_csv(text: str, field: str) -> pd.Series:
    """week.csv текст (вече декодиран от Shift-JIS) → weekly Series.

    Единица: 100 млн йени, знак + = нетно придобиване. Числата идват с
    хилядни запетаи в кавички → csv модулът, не naive split.
    """
    if field not in FLOW_FIELDS:
        raise ValueError(f"week.csv: непознато поле {field!r} (има {list(FLOW_FIELDS)})")
    col = FLOW_FIELDS[field]

    dates, values = [], []
    for parts in csv.reader(io.StringIO(text)):
        if not parts or len(parts) <= col:
            continue
        end = _parse_period_end(parts[0])
        if end is None:
            continue
        raw = parts[col].replace(",", "").replace("，", "").strip()
        if raw in ("", "-", "－"):
            continue
        try:
            values.append(float(raw))
            dates.append(end)
        except ValueError:
            continue
    return pd.Series(values, index=pd.DatetimeIndex(dates)).sort_index()


class MofAdapter(BaseAdapter):
    SOURCE_NAME = "mof"

    def __init__(self, cache_path: str = "data/mof_cache.json", **kwargs):
        super().__init__(cache_path, **kwargs)
        # Двата файла носят ВСИЧКИ серии — свалят се веднъж на fetch сесия,
        # не веднъж на серия.
        self._jgb_text: str | None = None
        self._flows_text: str | None = None

    def _download(self, url: str, encoding: str) -> str:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        return resp.content.decode(encoding, errors="replace")

    def _fetch_remote(self, series_key: str, source_id: str) -> pd.Series:
        kind, _, field = source_id.partition(":")
        if kind == "jgb":
            if self._jgb_text is None:
                self._jgb_text = self._download(config.MOF_JGB_HISTORICAL_CSV, "utf-8")
            return parse_jgb_csv(self._jgb_text, field)
        if kind == "flows":
            if self._flows_text is None:
                self._flows_text = self._download(config.MOF_WEEKLY_FLOWS_CSV, "shift_jis")
            return parse_flows_csv(self._flows_text, field)
        raise ValueError(f"MofAdapter: непознат source_id {source_id!r}")
