"""
analysis/yen_segment.py
=======================
Йена-слоят — диференциаторът на JP репото (мандат INIT-26, решение №2):
ОТДЕЛЕН наблюдателен слой НАД композита, като температурата и тензията.
Не влиза в score-а; чете context сериите с таг `yen_layer` + COT от data-core.

Водещият блок (дрилът USD/JPY 05.08): възелът на carry unwind —
ПОЗИЦИОНИРАНЕ × ЛИХВЕНА ТРАЕКТОРИЯ. Останалите блокове са обстановката:
валута, финансиране, потоци.

Дисциплина: всяко число тук идва от snapshot-а или от data-core файла —
нула ръчни константи. Персентилите се смятат по 10-годишен прозорец
(същият хоризонт като робастния z на уреда).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import pandas as pd

import config
from catalog.series import SERIES_CATALOG, yen_layer_keys

logger = logging.getLogger(__name__)

WINDOW_YEARS = 10  # персентилният прозорец — паритет с робастния z


# ── Помощници ────────────────────────────────────────────────────────────────

def _latest(s: Optional[pd.Series]) -> Optional[dict]:
    """{value, as_of} на последното наблюдение или None."""
    if s is None or s.dropna().empty:
        return None
    s = s.dropna()
    return {"value": float(s.iloc[-1]), "as_of": s.index[-1].strftime("%Y-%m-%d")}


def _delta(s: Optional[pd.Series], months: int = 12) -> Optional[float]:
    """Промяната спрямо наблюдението отпреди ~months месеца (най-близкото)."""
    if s is None or s.dropna().empty:
        return None
    s = s.dropna()
    target = s.index[-1] - pd.DateOffset(months=months)
    past = s.loc[:target]
    if past.empty:
        return None
    return float(s.iloc[-1] - past.iloc[-1])


def _pctile_10y(s: Optional[pd.Series]) -> Optional[float]:
    """Персентилът на последната стойност в 10-годишния прозорец (0-100)."""
    if s is None or s.dropna().empty:
        return None
    s = s.dropna()
    window = s.loc[s.index[-1] - pd.DateOffset(years=WINDOW_YEARS):]
    if len(window) < 20:
        return None
    return round(float((window <= window.iloc[-1]).mean() * 100), 1)


def _sum_4w(s: Optional[pd.Series]) -> Optional[float]:
    """Сумата на последните 4 седмични наблюдения (потоците)."""
    if s is None or s.dropna().empty:
        return None
    tail = s.dropna().iloc[-4:]
    if len(tail) < 4:
        return None
    return float(tail.sum())


# ── COT от data-core (мандат: преизползва се, НЕ се фетчва наново) ───────────

def load_cot_jpy() -> Optional[pd.Series]:
    """cot_jpy_net.json → weekly Series на primary net позиционирането.

    Файлът е канонът на data-core (schema_version 1): списък от записи с
    `as_of` + `value` (primary_net). Липсващ/счупен файл → None с warning,
    не крах — слоят декларира дупката вместо да събори статуса.
    """
    path = config.COT_JPY_CANONICAL
    if not path.exists():
        logger.warning(f"COT файлът липсва: {path}")
        return None
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
        s = pd.Series(
            {pd.Timestamp(r["as_of"]): float(r["value"]) for r in records},
        ).sort_index()
        return s if not s.empty else None
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        logger.warning(f"COT файлът не се чете ({e}) — блокът остава празен.")
        return None


# ── Слоят ────────────────────────────────────────────────────────────────────

def yen_segment(snapshot: dict[str, pd.Series]) -> dict[str, Any]:
    """Пълното четене на йена-слоя върху текущия snapshot.

    Блокове: rates · fx · funding · carry · positioning · flows. Всеки елемент
    носи value/as_of/делта или персентил — сурови наблюдения за лицето и за
    briefing_context, НЕ сигнал и НЕ прогноза.
    """
    def s(key: str) -> Optional[pd.Series]:
        return snapshot.get(key)

    cot = load_cot_jpy()

    out: dict[str, Any] = {
        "label_bg": config.YEN_LAYER_NAME_BG,
        "note": config.YEN_LAYER_NOTE,
        "rates": {
            "call_rate": _latest(s("JP_CALL_RATE")),
            "call_rate_d12m": _delta(s("JP_CALL_RATE")),
            "jgb_2y": _latest(s("JP_JGB_2Y")),
            "jgb_2y_d12m": _delta(s("JP_JGB_2Y")),
            "jgb_10y": _latest(s("JP_JGB_10Y_D")),
            "jgb_10y_d12m": _delta(s("JP_JGB_10Y_D")),
            "tibor_3m": _latest(s("JP_TIBOR3M")),
        },
        "fx": {
            "usdjpy": _latest(s("JP_USDJPY")),
            "usdjpy_d12m": _delta(s("JP_USDJPY")),
            "reer": _latest(s("JP_REER")),
            "reer_pctile_10y": _pctile_10y(s("JP_REER")),
        },
        "funding": {
            "boj_assets": _latest(s("JP_BOJ_ASSETS")),
            "boj_assets_yoy_pct": None,
        },
        "carry": {
            "spread_2y": _latest(s("JP_CARRY_2Y")),
            "spread_2y_d12m": _delta(s("JP_CARRY_2Y")),
            "spread_10y": _latest(s("JP_CARRY_10Y")),
            "spread_10y_d12m": _delta(s("JP_CARRY_10Y")),
        },
        "positioning": {
            "cot_net": _latest(cot),
            "cot_pctile_10y": _pctile_10y(cot),
            "cot_source": str(config.COT_JPY_CANONICAL),
        },
        "flows": {
            "nonres_equity_4w": _sum_4w(s("JP_FLOWS_NONRES_EQ")),
            "res_ltdebt_4w": _sum_4w(s("JP_FLOWS_RES_LTDEBT")),
            "unit": "100 млн йени, + = нетно придобиване",
        },
    }

    # BOJ баланс: г/г темп от суровата серия (не от _delta, който е абсолютен).
    boj = s("JP_BOJ_ASSETS")
    if boj is not None and not boj.dropna().empty:
        b = boj.dropna()
        target = b.index[-1] - pd.DateOffset(months=12)
        past = b.loc[:target]
        if not past.empty and past.iloc[-1] != 0:
            out["funding"]["boj_assets_yoy_pct"] = round(
                float((b.iloc[-1] / past.iloc[-1] - 1) * 100), 2
            )

    return out


def _fmt(v: Optional[float], nd: int = 2) -> str:
    return f"{v:+.{nd}f}" if isinstance(v, (int, float)) else "н.д."


def segment_lines(seg: dict[str, Any]) -> list[str]:
    """Конзолният/текстовият вид — ЕДИН източник за формулировките."""
    r, f, c, p, fl, fu = (seg["rates"], seg["fx"], seg["carry"],
                          seg["positioning"], seg["flows"], seg["funding"])

    def val(d: Optional[dict], nd: int = 2) -> str:
        return f"{d['value']:.{nd}f} ({d['as_of']})" if d else "н.д."

    lines = [
        f"¥ {seg['label_bg']} — {seg['note']}",
        f"  Лихви: call {val(r['call_rate'])} (Δ12м {_fmt(r['call_rate_d12m'])}) · "
        f"JGB 2Y {val(r['jgb_2y'])} · 10Y {val(r['jgb_10y'])} · "
        f"TIBOR 3м {val(r['tibor_3m'])}",
        f"  Валута: USD/JPY {val(f['usdjpy'])} (Δ12м {_fmt(f['usdjpy_d12m'])}) · "
        f"REER {val(f['reer'], 1)} — {f['reer_pctile_10y'] if f['reer_pctile_10y'] is not None else 'н.д.'}-ти "
        f"персентил (10г)",
        f"  Финансиране: BOJ баланс {val(fu['boj_assets'], 0)} · "
        f"г/г {_fmt(fu['boj_assets_yoy_pct'])}%",
        f"  Carry: US−JP 2Y {val(c['spread_2y'])} (Δ12м {_fmt(c['spread_2y_d12m'])}) · "
        f"10Y {val(c['spread_10y'])} (Δ12м {_fmt(c['spread_10y_d12m'])})",
        f"  Позициониране: COT JPY net {val(p['cot_net'], 0)} — "
        f"{p['cot_pctile_10y'] if p['cot_pctile_10y'] is not None else 'н.д.'}-ти "
        f"персентил (10г)",
        f"  Потоци 4w: нерез.→JP акции {_fmt(fl['nonres_equity_4w'], 0)} · "
        f"рез.→чужд дълг {_fmt(fl['res_ltdebt_4w'], 0)} ({fl['unit']})",
    ]
    return lines
