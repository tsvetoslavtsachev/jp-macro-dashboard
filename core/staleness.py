"""
core/staleness.py
=================
Правилото за застояване на серия, едно за файла със серии и за оценката на лещите
(ПРОЛЕТР4, 26.11.2026, реш. Ц. ЯП-1). Огледало на us _relative_staleness: серия е
застояла, ако е над RELATIVE_STALE_PERIODS периода зад най-свежата серия от СЪЩАТА
каденция в снимката.
"""
from __future__ import annotations

import pandas as pd

PERIOD_LENGTH_DAYS = {
    "daily": 5,   # работна седмица: FRED дневните серии изостават с дни, не са stale
    "weekly": 7,
    "monthly": 30,
    "quarterly": 90,
    "annually": 365,
}
RELATIVE_STALE_PERIODS = 3


def relative_staleness(last_date, schedule: str, sched_ref: dict) -> tuple[bool, int]:
    """stale ако е >3 периода зад най-свежата серия от СЪЩАТА каденция;
    periods_behind = закръглени периоди зад нея."""
    ref = sched_ref.get(schedule)
    if last_date is None or ref is None:
        return False, 0
    try:
        gap_days = (pd.Timestamp(ref) - pd.Timestamp(last_date)).days
    except Exception:
        return False, 0
    period = PERIOD_LENGTH_DAYS.get(schedule, 30)
    return gap_days > RELATIVE_STALE_PERIODS * period, max(0, int(round(gap_days / period)))


def sched_reference(snapshot: dict, catalog: dict) -> dict:
    """{каденция: последната дата на най-свежата серия от тази каденция}."""
    ref: dict[str, pd.Timestamp] = {}
    for k, s in snapshot.items():
        if s is None:
            continue
        s = s.dropna()
        if s.empty or not isinstance(s.index, pd.DatetimeIndex):
            continue
        sc = catalog.get(k, {}).get("release_schedule", "monthly")
        if sc not in ref or s.index[-1] > ref[sc]:
            ref[sc] = s.index[-1]
    return ref
