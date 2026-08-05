"""
sources/fred_adapter.py
=======================
FRED адаптер за Japan Macro Dashboard — подклас на фамилния BaseAdapter
(CN `_base.py`: кеш/TTL/retry/tolerant-parse). Порт на us-macro-dashboard
адаптера към базовия интерфейс (мандат INIT-26, раздел C от скаута).

Какво носи базата: retry с класификация transient/permanent, graceful
degradation към кеша при всяка грешка, tolerant JSON парсинг на повреден кеш.
Какво носи този файл: само fredapi връзката + fail-loud при липсващ ключ.

API ключ: FRED_API_KEY от env или .env в корена (config.py). Регистрация:
https://fred.stlouisfed.org/docs/api/api_key.html
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from sources._base import BaseAdapter

import config


class FredAdapter(BaseAdapter):
    SOURCE_NAME = "fred"

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_path: str = "data/fred_cache.json",
        **kwargs,
    ):
        super().__init__(cache_path, **kwargs)
        self.api_key = api_key if api_key is not None else config.FRED_API_KEY
        self._fred = None

    def _get_fred(self):
        """Lazy fredapi.Fred. Fail-loud при липсващ ключ (US прецедентът):
        без ключ fetch-ът иначе би фейлнал тихо и кешът би останал стар."""
        if self._fred is not None:
            return self._fred
        if not self.api_key:
            raise RuntimeError(
                "\n" + "=" * 60 + "\n"
                "FRED_API_KEY липсва.\n"
                "Сложи го в env или в .env файла в корена на репото:\n"
                "    FRED_API_KEY=твоят_ключ\n"
                "Безплатна регистрация:\n"
                "    https://fred.stlouisfed.org/docs/api/api_key.html\n"
                + "=" * 60
            )
        try:
            from fredapi import Fred
        except ImportError:
            raise RuntimeError(
                "Липсва пакетът fredapi. Инсталирай с: pip install fredapi"
            )
        self._fred = Fred(api_key=self.api_key)
        return self._fred

    def _fetch_remote(self, series_key: str, source_id: str) -> pd.Series:
        """Fetch една серия от FRED. Базата класифицира грешките и retry-ва."""
        fred = self._get_fred()
        s = fred.get_series(source_id)
        if s is None:
            return pd.Series(dtype=float)
        return s.dropna()
