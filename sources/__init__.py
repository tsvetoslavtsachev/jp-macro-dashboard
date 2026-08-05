"""
sources/
========
Адаптерната фабрика — ЕДНО място, където се обявяват живите източници.

Фази по мандат INIT-26: v1 = fred · фаза 3 = mof · фаза 4 = estat ·
фаза 5 = boj. Каталогът може да декларира източник, който още не е тук —
серията тогава просто не се фетчва (и лещата ѝ ренормализира), без грешка.
"""
from sources.fred_adapter import FredAdapter
from sources.mof_adapter import MofAdapter


def build_adapters() -> dict:
    return {
        "fred": FredAdapter(),
        "mof": MofAdapter(),
    }
