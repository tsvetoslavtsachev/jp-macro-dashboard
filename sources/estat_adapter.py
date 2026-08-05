"""
sources/estat_adapter.py
========================
e-Stat API адаптер (фаза 4) — инфлационната леща живее тук: FRED НЯМА жив
месечен японски CPI (всички OECD-MEI тикери замразени 2021-06, мандат §2).

API: https://api.e-stat.go.jp/rest/3.0/app/json — иска безплатен appId
(config.ESTAT_APP_ID; регистриран 2026-08-05). Отговорът е JSON.

source_id конвенция в каталога — четима и разширяема:
    "<statsDataId>?tab=1&cat01=0161&area=00000"
Всеки параметър става cdXxx филтър на getStatsData. Живо проверени кодове
(2026-08-05, таблица 0003427113 = CPI 2020-база, 790 записа, 1970→):
    tab  1=индекс · 3=前年同月比 (г/г)
    cat01  0001=総合 (headline) · 0161=ex fresh food (BOJ мярката) ·
           0178=ex fresh food & energy (core-core)
    area   00000=全国

⚠ Времевата ос СМЕСВА месечни и годишни редове: годишният е "1970000000"
(нули след годината), месечният — "2026000606" (месецът, повторен в двете
последни двойки). Парсваме САМО месечните; годишните изпадат мълчаливо по
дизайн — те са същата информация на друга честота, не липсващи данни.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl

import pandas as pd
import requests

from sources._base import BaseAdapter

import config

ESTAT_BASE = "https://api.e-stat.go.jp/rest/3.0/app/json"

# "2026000606" → година 2026, месец 06 (последните две двойки съвпадат)
_MONTHLY_TIME_RE = re.compile(r"^(\d{4})00(\d{2})(\d{2})$")


def parse_estat_id(source_id: str) -> tuple[str, dict[str, str]]:
    """"0003427113?tab=1&cat01=0161&area=00000" → (statsDataId, {cdTab: "1", …})."""
    stats_id, _, query = source_id.partition("?")
    if not stats_id.strip():
        raise ValueError(f"estat source_id без statsDataId: {source_id!r}")
    params = {}
    for k, v in parse_qsl(query):
        params["cd" + k[0].upper() + k[1:]] = v
    return stats_id.strip(), params


def parse_estat_values(values: list[dict]) -> pd.Series:
    """VALUE списъкът от getStatsData → месечна Series (ден 1 на месеца).

    Годишните редове (@time завършва на 0000) изпадат. Непарсваща стойност
    („-", „…") изпада тихо — e-Stat ги ползва за липсващо наблюдение.
    """
    dates, vals = [], []
    for v in values:
        m = _MONTHLY_TIME_RE.match(v.get("@time", ""))
        if not m:
            continue
        year, mm1, mm2 = m.groups()
        if mm1 != mm2 or not (1 <= int(mm2) <= 12):
            continue
        try:
            val = float(v["$"])
        except (KeyError, ValueError, TypeError):
            continue
        dates.append(pd.Timestamp(year=int(year), month=int(mm2), day=1))
        vals.append(val)
    return pd.Series(vals, index=pd.DatetimeIndex(dates)).sort_index()


class EstatAdapter(BaseAdapter):
    SOURCE_NAME = "estat"

    def __init__(self, app_id: str | None = None,
                 cache_path: str = "data/estat_cache.json", **kwargs):
        super().__init__(cache_path, **kwargs)
        self.app_id = app_id if app_id is not None else config.ESTAT_APP_ID

    def _fetch_remote(self, series_key: str, source_id: str) -> pd.Series:
        if not self.app_id:
            raise RuntimeError(
                "\n" + "=" * 60 + "\n"
                "ESTAT_APP_ID липсва.\n"
                "Сложи го в env или в .env файла в корена на репото:\n"
                "    ESTAT_APP_ID=твоят_ключ\n"
                "Безплатна регистрация: https://www.e-stat.go.jp/en/mypage/user/preregister\n"
                + "=" * 60
            )
        stats_id, filters = parse_estat_id(source_id)
        resp = requests.get(
            f"{ESTAT_BASE}/getStatsData",
            params={
                "appId": self.app_id,
                "statsDataId": stats_id,
                "metaGetFlg": "N",
                **filters,
            },
            timeout=120,
        )
        resp.raise_for_status()
        sd = resp.json()["GET_STATS_DATA"]
        status = int(sd["RESULT"]["STATUS"])
        if status != 0:
            # e-Stat връща 200 OK и слага грешката в STATUS — вдигаме я, за да
            # я класифицира базата (401-подобните са permanent).
            raise RuntimeError(
                f"e-Stat STATUS {status}: {sd['RESULT'].get('ERROR_MSG', '?')}"
            )
        values = sd["STATISTICAL_DATA"]["DATA_INF"]["VALUE"]
        if isinstance(values, dict):
            values = [values]
        return parse_estat_values(values)
