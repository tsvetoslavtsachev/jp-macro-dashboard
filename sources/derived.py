"""
sources/derived.py
==================
Изведени серии — раждат се СЛЕД fetch-а, ПРЕДИ скоринга (фамилният ред:
fetch → derive → score). Рецептата стои в каталожното `id` като четим стринг;
адресът на изведената серия е този файл.

JP v1 (фаза 3): двата carry диференциала — гръбнакът на йена-слоя (дрилът
05.08: възелът „екстремно къса funding валута + централна банка в
нормализация"). Диференциалът се смята на ОБЩИТЕ дневни дати (inner join) —
празници Токио/Ню Йорк не съвпадат и външното изравняване би родило фантомни
наблюдения.
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

# рецепта: derived_key → (minuend_key, subtrahend_key)
_SPREADS: dict[str, tuple[str, str]] = {
    "JP_CARRY_2Y":  ("US_2Y", "JP_JGB_2Y"),
    "JP_CARRY_10Y": ("US_10Y", "JP_JGB_10Y_D"),
}


def derive_series(snapshot: dict[str, pd.Series]) -> dict[str, pd.Series]:
    """Добавя изведените серии към snapshot-а. Липсващ родител = серията
    просто не се ражда (правото на отказ — не гърми, декларира се в лога)."""
    out = dict(snapshot)
    for key, (a_key, b_key) in _SPREADS.items():
        a, b = snapshot.get(a_key), snapshot.get(b_key)
        if a is None or b is None or a.empty or b.empty:
            logger.warning(
                f"{key}: родител липсва ({a_key if a is None or a.empty else b_key}) "
                f"— серията не се ражда този пуск."
            )
            continue
        idx = a.index.intersection(b.index)
        if len(idx) == 0:
            logger.warning(f"{key}: нула общи дати между {a_key} и {b_key}.")
            continue
        out[key] = (a.loc[idx] - b.loc[idx]).sort_index()
    return out
