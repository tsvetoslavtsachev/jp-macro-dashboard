"""
core/display.py
===============
Дисплейните примитиви на ФОРМА-КАНОН — един източник за това КАК се показва
число, име и период, за да казват HTML лицето и briefing_context едно и също.

Портнат от фамилния образец (bg-macro-dashboard); линк-функциите са JP:
FRED серия · e-Stat таблица · BOJ stat-search · MOF страници · derived без
линк. БГ-мандатните прочити (housing_hypotheses, rents_epochs_reading,
perceived_inflation_reading, следхиперинфлационната опашка) НЕ се пренасят —
те са отговор на български въпроси, не фамилни примитиви.

Public API:
    fred_series_url(catalog_id)          → страницата на серията във FRED
    estat_series_url(catalog_id)         → e-Stat таблицата (statdisp_id)
    boj_series_url(catalog_id)           → BOJ Time-Series Data Search портала
    mof_series_url(catalog_id)           → MOF страницата (JGB крива / потоци)
    source_url(source, catalog_id)       → линкът според източника на серията
    fmt_value(res)                       → „5.20 %" / „95.00" (по is_rate/transform)
    months_old(last_date, today)         → възраст на наблюдението в месеци
    is_stale(last_date, schedule, today) → по-старо от 2× очаквания ритъм?
    stale_note(schedule)                 → обяснението зад ⚠ при застояло
    thin_window_note(percentile_window)  → обяснението зад ⚠ при къс прозорец
    verdict_sentence(lens_reports)       → „Тежи X (n), крепи Y (m)."
    epoch_label(start, end)              → „1995-2012" / „2022-сега" от границите
    inflation_anchor(value)              → котвеният прочит: пп от целта + зона
    inflation_anchors(snapshot)          → двете котви (headline + core), готови
                                           за двете повърхности
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

import pandas as pd

from catalog.polarity import INFLATION_TARGET
from catalog.series import SERIES_CATALOG
from config import (
    CORE_DEFLATOR_KEY,
    FRED_SERIES_URL,
    HEADLINE_DEFLATOR_KEY,
    INFLATION_ANCHOR_COLORS,
    LENS_SUBJECTS_BG,
    MOF_FLOWS_PAGE,
    MOF_JGB_PAGE,
    STALE_AFTER_MONTHS,
)
from core.primitives import apply_transform

# ── JP линк-шаблоните, които не живеят в config ──────────────────────────────
# e-Stat: стабилният адрес на таблица е statdisp_id — частта ПРЕДИ `?` в
# каталожното id (`0003427113?tab=1&cat01=0001` → `0003427113`). Живо проверено
# 05.08.2026 за CPI таблицата на скаута.
ESTAT_DATABASE_URL = (
    "https://www.e-stat.go.jp/en/stat-search/database?statdisp_id={stats_data_id}"
)
# BOJ flat файловете нямат страница-на-серия — порталът на Time-Series Data
# Search е първоизточникът, който човек може да отвори и да намери серията.
BOJ_STAT_SEARCH = "https://www.stat-search.boj.or.jp/"


def fred_series_url(catalog_id: str) -> str:
    """Каталожно id (FRED тикер) → страницата на серията във FRED."""
    sid = (catalog_id or "").strip()
    if not sid:
        return ""
    return FRED_SERIES_URL.format(series_id=sid)


def estat_series_url(catalog_id: str) -> str:
    """Каталожно id → e-Stat таблицата по statdisp_id.

    `{stats_data_id}` е частта преди `?`: `0003427113?tab=1&…` → `0003427113`.
    """
    sid = (catalog_id or "").split("?", 1)[0].strip()
    if not sid:
        return ""
    return ESTAT_DATABASE_URL.format(stats_data_id=sid)


def boj_series_url(catalog_id: str = "") -> str:
    """BOJ серия → порталът на stat-search.

    Flat файловете (`bp:…`, `cgpi:…`) нямат адрес-на-серия; порталът е
    най-близкият стабилен първоизточник — по-честен от дълбок линк, който
    утре се чупи.
    """
    return BOJ_STAT_SEARCH


def mof_series_url(catalog_id: str) -> str:
    """MOF серия → страницата на набора: JGB кривата или седмичните потоци.

    Каталожното id носи префикса на рецептата: `jgb:2Y` → кривата,
    `flows:nonres_equity_net` → потоците (config.MOF_JGB_PAGE / MOF_FLOWS_PAGE).
    """
    cid = (catalog_id or "").strip().lower()
    if cid.startswith("flows:"):
        return MOF_FLOWS_PAGE
    return MOF_JGB_PAGE


def source_url(source: str, catalog_id: str) -> str:
    """Линкът на серията се разклонява по източник — един вход за дисплея.

    ИЗВЕДЕНАТА серия (`source: "derived"`) няма собствен първоизточник —
    нейното „id" е РЕЦЕПТА, не адрес. Затова тук се връща празен низ и лицето
    я показва без линк: по-добре без линк, отколкото с линк, който сочи
    някъде, откъдето числото не идва. Родителите ѝ си имат свои редове.
    """
    src = (source or "").strip().lower()
    if src == "derived":
        return ""
    if src == "fred":
        return fred_series_url(catalog_id)
    if src == "estat":
        return estat_series_url(catalog_id)
    if src == "boj":
        return boj_series_url(catalog_id)
    if src == "mof":
        return mof_series_url(catalog_id)
    return ""


def fmt_value(res: dict, digits: int = 2) -> str:
    """Стойността както се чете: процент, когато серията е ставка/темп."""
    val = res.get("display_value")
    if val is None or (isinstance(val, float) and val != val):
        return "—"
    txt = f"{float(val):.{digits}f}"
    if res.get("is_rate") or res.get("display_is_pct"):
        return f"{txt} %"
    return txt


def months_old(last_date, today: Optional[date] = None) -> Optional[int]:
    """Колко месеца има наблюдението (по календарни месеци, не по дни)."""
    if not last_date:
        return None
    try:
        d = pd.Timestamp(last_date)
    except Exception:
        return None
    ref = pd.Timestamp(today or date.today())
    return (ref.year - d.year) * 12 + (ref.month - d.month)


def is_stale(last_date, schedule: str = "monthly", today: Optional[date] = None) -> bool:
    """Наблюдението по-старо ли е от 2× очаквания ритъм на публикуване?

    daily/weekly > 1 месец · monthly > 2 месеца · quarterly > 6 месеца ·
    annually > 24 месеца (виж config.STALE_AFTER_MONTHS).
    """
    age = months_old(last_date, today)
    if age is None:
        return False
    return age > STALE_AFTER_MONTHS.get(schedule, 2)


def stale_note(schedule: str = "monthly") -> str:
    """Обяснението зад ⚠ — какъв ритъм се очакваше."""
    limit = STALE_AFTER_MONTHS.get(schedule, 2)
    return (
        f"Наблюдението е по-старо от {limit} месеца — двойно над очаквания ритъм "
        f"на публикуване ({schedule}). Провери за прекъсване на серията."
    )


def thin_window_note(percentile_window: Optional[str] = None) -> str:
    """Обяснението зад ⚠ при къс прозорец — едно изречение, без жаргон."""
    where = f" ({percentile_window})" if percentile_window else ""
    return (
        f"Нормата е върху къс период{where} — z-ът подценява екстремността, "
        f"ако периодът е бил еднопосочен."
    )


def verdict_sentence(lens_reports: dict) -> str:
    """Детерминистичен извод от лещовите scores — без свободен текст.

    „Тежи кредитът (0.4), крепи пазарът на труда (79.2)." Най-слабата и
    най-силната леща с числата им. Без данни → честно изречение, не мълчание.
    """
    scored = [
        (lens, rep["score"])
        for lens, rep in lens_reports.items()
        if rep.get("score") is not None
    ]
    if not scored:
        return "Няма достатъчно данни за извод."

    weakest = min(scored, key=lambda p: (p[1], p[0]))
    strongest = max(scored, key=lambda p: (p[1], -ord(p[0][0])))

    if len(scored) == 1 or weakest[0] == strongest[0]:
        name = LENS_SUBJECTS_BG.get(weakest[0], weakest[0])
        return f"Единствената измерена леща е {name} ({weakest[1]:.1f})."

    return (
        f"Тежи {LENS_SUBJECTS_BG.get(weakest[0], weakest[0])} ({weakest[1]:.1f}), "
        f"крепи {LENS_SUBJECTS_BG.get(strongest[0], strongest[0])} ({strongest[1]:.1f})."
    )


def epoch_label(start: str, end: Optional[str] = None) -> str:
    """`1995-01-01`, `2012-12-31` → „1995-2012" — етикетът се ИЗВЕЖДА, не се зашива.

    ОТВОРЕНАТА епоха (`end=None`, конвенцията на `config.EPOCHS`) чете
    „2022-сега": границата ѝ е последното наблюдение, не година, която някой
    трябва да помни да мести. Пълните четири цифри и на края — „1995-12" би
    се четяло като месец, не като година (българският къс формат работи само
    за епохи в едно десетилетие).
    """
    a = pd.Timestamp(start)
    if end is None:
        return f"{a.year}-сега"
    b = pd.Timestamp(end)
    return f"{a.year}-{b.year}"


# ═════════════════════════════════════════════════════════════════════════════
# КОТВЕНИЯТ ПРОЧИТ НА ИНФЛАЦИЯТА — вторият, абсолютен глас
# ═════════════════════════════════════════════════════════════════════════════
# U-score-ът в композита мери инфлацията ОТНОСИТЕЛНО: колко σ е отклонението от
# целта спрямо собствената разсейка на серията. Верният уред за агрегация, но
# в Япония относителната норма е дефлационно изкривена: три десетилетия около
# нулата правят и 1.5% да изглежда „далеч от нормалното", а политически това е
# почти успех. Затова тук стои ВТОРИ, АБСОЛЮТЕН глас: колко процентни пункта
# сме от целта на BOJ (2%, обявена 01.2013). Зоните са ФИКСИРАНИ
# политики-смислени котви, НЕ калибрирани по историята — калибрирани по
# дефлационните десетилетия, те биха обявили самата цел за екстремум.
#
# Двата гласа НЕ се смесват: котвата не пипа нито score, нито композит.
ANCHOR_GREEN_PP = 1.0    # |отклонение| ≤ 1 пп → при целта
ANCHOR_YELLOW_PP = 2.0   # 1 < |отклонение| ≤ 2 пп → отклонена

ANCHOR_ZONE_LABELS_BG = {
    "green": "при целта",
    "yellow": "отклонена",
    "red": "далеч от целта",
}

ANCHOR_ZONE_PHRASES_BG = {
    "green": "зелена зона",
    "yellow": "жълта зона",
    "red": "червена зона",
}

# Изречението, което пази двата гласа разделени — цитира се и от лицето, и от
# context експорта (ЕДИН източник, ФОРМА-КАНОН).
ANCHOR_DISCLAIMER = (
    "Котвите НЕ пипат композита — U-score-ът остава гласът в него; това е "
    "вторият, абсолютен глас. Дефлационната посока минава през същите зони "
    "огледално."
)

# Сериите, на които се слага котва: headline + мярката на BOJ (ex fresh food).
# Ключовете идват от config — един речник, нула преписани литерали.
ANCHOR_KEYS = (HEADLINE_DEFLATOR_KEY, CORE_DEFLATOR_KEY)


def fmt_target(target: float) -> str:
    """2.0 → „2%"; 2.5 → „2.5%". Целта се показва както се говори."""
    return f"{float(target):g}%"


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and value != value)


def inflation_anchor(value: Optional[float], target: float = INFLATION_TARGET) -> dict:
    """Котвеният прочит на едно инфлационно число: пп от целта + зона.

    `gap_pp` е ЗНАКОВ (над/под целта), зоната е по |gap| със `≤` семантика:
    ≤1 пп зелено · 1–2 пп жълто · >2 пп червено. Дефлационната посока минава
    през същите зони огледално — в Япония тя не е теория, а три изживени
    десетилетия, затова огледалото тук носи тежест.
    """
    if _is_missing(value):
        return {
            "value": None, "target": float(target), "gap_pp": None,
            "zone": None, "label_bg": None, "color": None,
            "value_str": "—", "gap_phrase": "", "zone_phrase": "",
            "sentence": "—",
        }

    value = float(value)
    gap = round(value - float(target), 1)
    spread = abs(gap)

    if spread <= ANCHOR_GREEN_PP:
        zone = "green"
    elif spread <= ANCHOR_YELLOW_PP:
        zone = "yellow"
    else:
        zone = "red"

    target_str = fmt_target(target)
    if gap == 0:
        gap_phrase = f"точно на целта ({target_str})"
    else:
        direction = "над целта" if gap > 0 else "под целта"
        gap_phrase = f"{spread:.1f} пп {direction} ({target_str})"

    zone_phrase = ANCHOR_ZONE_PHRASES_BG[zone]
    return {
        "value": value,
        "target": float(target),
        "gap_pp": gap,
        "zone": zone,
        "label_bg": ANCHOR_ZONE_LABELS_BG[zone],
        "color": INFLATION_ANCHOR_COLORS[zone],
        "value_str": f"{value:.1f}%",
        "gap_phrase": gap_phrase,
        "zone_phrase": zone_phrase,
        "sentence": f"{value:.1f}% = {gap_phrase} — {zone_phrase}",
    }


def _last_transformed(snapshot: dict, key: str, spec: dict) -> pd.Series:
    """Серията както се ЧЕТЕ (след каталожната трансформация), без празни точки."""
    s = snapshot.get(key) if snapshot else None
    if s is None or len(s) == 0:
        return pd.Series(dtype="float64")
    return apply_transform(s, spec.get("transform", "level")).dropna()


def inflation_anchors(
    snapshot: dict,
    catalog: Optional[dict] = None,
    target: float = INFLATION_TARGET,
) -> dict:
    """Двете котви на инфлацията, готови за ДВЕТЕ повърхности (ФОРМА-КАНОН).

    Връща `{"anchors": [...], "disclaimer": ...}` — лицето и
    `briefing_context` четат ЕДИН източник, за да не се разминат. Липсваща
    серия (например преди e-Stat ключа) → котвата просто я няма, без грешка.
    """
    catalog = SERIES_CATALOG if catalog is None else catalog

    anchors: list[dict] = []
    for key in ANCHOR_KEYS:
        spec = catalog.get(key)
        if not spec:
            continue
        s = _last_transformed(snapshot, key, spec)
        if s.empty:
            continue
        value = float(s.iloc[-1])
        row = inflation_anchor(value, target)
        row.update({
            "key": key,
            "name_bg": spec.get("name_bg", key),
            "last_date": (
                s.index[-1].strftime("%Y-%m")
                if isinstance(s.index, pd.DatetimeIndex) else str(s.index[-1])
            ),
        })
        anchors.append(row)

    return {
        "anchors": anchors,
        "disclaimer": ANCHOR_DISCLAIMER,
    }
