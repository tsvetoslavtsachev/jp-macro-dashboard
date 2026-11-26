"""
sources/boj_adapter.py
======================
BOJ flat-file адаптер (фаза 5) — wide CSV в zip от stat-search портала
(https://www.stat-search.boj.or.jp/info/dload_en.html), живо проверени
2026-08-05:

  · bp_m_en.zip   — платежен баланс (BPM6), месечен, 1996→. Текущата сметка
    net = ред BPBP6JYNCB, единица 100 млн йени.
  · cgpi_m_en.zip — CGPI/PPI 2020-база, месечен, САМО 2020-01→ (flat файлът
    носи текущата база; дългата история живее в портала през бази).

Формат: ред 1 = header (празни мета клетки + периоди YYYYMM), после редове
[код, набор, име(, единица), стойности…]. Броят мета колони ВАРИРА (CGPI 3,
BP 4) — затова се извежда от header-а (първата 6-цифрена клетка), не се зашива.

⚠ Tankan НЕ Е тук: co.zip носи само текущото издание (48k кода × 1-2 obs,
проверено 05.08), а DBnomics-BOJ огледалото е застояло и без Tankan изобщо.
Tankan историята е menu-item (BOJ портал CGI).

source_id конвенция: "<файл>:<ред-код>", файл ∈ {bp, cgpi}.
ПРОЛЕТР4 (26.11.2026): и "api:<DB>:<код>" за официалния API на BoJ
(https://www.stat-search.boj.or.jp/api/v1/getDataCode, без ключ, живо проверен 26.11.2026).
Там е и историята на Tankan (DB=CO), която флет-файловете нямат.
"""
from __future__ import annotations

import csv
from typing import Any
import io
import zipfile

import pandas as pd
import requests

from sources._base import BaseAdapter

BOJ_FILES = {
    "bp": "https://www.stat-search.boj.or.jp/info/bp_m_en.zip",
    "cgpi": "https://www.stat-search.boj.or.jp/info/cgpi_m_en.zip",
}

_MISSING = {"", "NA", "ND", "-"}


BOJ_API = "https://www.stat-search.boj.or.jp/api/v1/getDataCode"


def _boj_period_to_ts(period: Any, frequency: str) -> pd.Timestamp:
    """YYYYMM от API-то: при тримесечна серия MM е номерът на тримесечието (202603 = 3 тр.),
    датата е началото на тримесечието (както FRED); при месечна е началото на месеца."""
    p = str(period)
    y, m = int(p[:4]), int(p[4:6])
    if frequency.upper().startswith("QUARTER"):
        return pd.Timestamp(year=y, month=3 * (m - 1) + 1, day=1)
    return pd.Timestamp(year=y, month=m, day=1)


def parse_boj_api(payload: dict) -> pd.Series:
    rs = payload.get("RESULTSET") or []
    if not rs:
        raise ValueError(f"BOJ API: празен RESULTSET ({payload.get('MESSAGEID')} {payload.get('MESSAGE')})")
    r = rs[0]
    vals = r.get("VALUES") or {}
    dates, values = vals.get("SURVEY_DATES") or [], vals.get("VALUES") or []
    freq = r.get("FREQUENCY") or ""
    out = {}
    for d, v in zip(dates, values):
        if v is None or v == "":
            continue
        out[_boj_period_to_ts(d, freq)] = float(v)
    s = pd.Series(out, dtype=float).sort_index()
    s.name = r.get("SERIES_CODE")
    return s


def parse_boj_wide(text: str, row_code: str) -> pd.Series:
    """Wide BOJ CSV текст → месечна Series за един ред-код.

    Периодните колони се разпознават по формата YYYYMM в header-а; бъдещи
    празни колони и NA/ND изпадат тихо (липсващо наблюдение, не нула).
    """
    rows = csv.reader(io.StringIO(text))
    try:
        header = next(rows)
    except StopIteration:
        raise ValueError("BOJ CSV: празен файл")

    period_cols = [
        (i, c.strip()) for i, c in enumerate(header)
        if c.strip().isdigit() and len(c.strip()) == 6
    ]
    if not period_cols:
        raise ValueError("BOJ CSV: header без YYYYMM периоди — форматът се е сменил")

    target = None
    for row in rows:
        if row and row[0].strip() == row_code:
            target = row
            break
    if target is None:
        raise ValueError(f"BOJ CSV: ред-кодът {row_code!r} липсва във файла")

    dates, values = [], []
    for i, period in period_cols:
        if i >= len(target):
            continue
        raw = target[i].strip()
        if raw in _MISSING:
            continue
        year, month = int(period[:4]), int(period[4:])
        if not (1 <= month <= 12):
            continue
        try:
            values.append(float(raw))
        except ValueError:
            continue
        dates.append(pd.Timestamp(year=year, month=month, day=1))
    return pd.Series(values, index=pd.DatetimeIndex(dates)).sort_index()


class BojAdapter(BaseAdapter):
    SOURCE_NAME = "boj"

    def __init__(self, cache_path: str = "data/boj_cache.json", **kwargs):
        super().__init__(cache_path, **kwargs)
        # Един zip носи много серии — сваля се веднъж на fetch сесия.
        self._texts: dict[str, str] = {}

    def _get_text(self, file_key: str) -> str:
        if file_key not in self._texts:
            url = BOJ_FILES[file_key]
            resp = requests.get(url, timeout=120)
            resp.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                inner = zf.namelist()[0]
                self._texts[file_key] = zf.read(inner).decode("utf-8", errors="replace")
        return self._texts[file_key]

    def _fetch_remote(self, series_key: str, source_id: str) -> pd.Series:
        file_key, _, row_code = source_id.partition(":")
        if file_key == "api":
            db, _, code = row_code.partition(":")
            resp = requests.get(BOJ_API, params={"format": "json", "lang": "en", "db": db, "code": code},
                                timeout=60)
            resp.raise_for_status()
            return parse_boj_api(resp.json())
        if file_key not in BOJ_FILES:
            raise ValueError(
                f"BojAdapter: непознат файл {file_key!r} (има {list(BOJ_FILES)})"
            )
        return parse_boj_wide(self._get_text(file_key), row_code)
