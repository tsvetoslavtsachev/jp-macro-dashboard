"""
analysis/temperature.py
=======================
ТЕМПЕРАТУРНИЯТ СЛОЙ — колко бум-серии са НАД зоната си (мандат №47, П2).

Защо отделен слой, а не още едно число в скора:

  · Скорът е ГЛАДЪК и двупосочен — той пада и при прегряване, и при криза, и
    двете падания изглеждат еднакво на 0–100 скалата. „Кредитът е на 40" не
    казва дали заемите тичат, или са замръзнали.
  · Температурата брои САМО горното нарушение: колко от петте бум-серии стоят
    над горния праг на зоната си. Под lo е криза/кредитен крънч — той се чете
    в скора, не в термометъра. Един уред, един въпрос.
  · Праговете са АБСОЛЮТНИ (`catalog/polarity.py`, фиксирани от данни-пас
    28.07.2026), затова числото е смятаемо и НАЗАД без look-ahead: 2007 не
    знае нищо за 2026. Точно това прави приемния гейт възможен —
    2006H2-2008 свети 4-5/5, 2015-2019 мълчи 0/20.

Един източник за „кои са бум-сериите": `TEMP_SERIES` се ИЗВЕЖДА от POLARITY
(всички OPT ключове). Шеста OPT серия утре влиза и в скоринга, и в термометъра
наведнъж — няма втори списък, който да остане назад.

Честност при липсваща стойност: серия без наблюдение към дадената дата НЕ се
брои в `n_total` за тази дата. Ранните маркове на реконструкцията показват
„2/4", а не „2/5" — знаменателят казва колко уред реално стои зад числото.

⚠ Мандат №53: върху температурата стъпва и БАЛОННАТА ДВОЙКА — дискретният
сигнал за съ-прегряване имоти↔кредит (`bubble_pair*` по-долу). Тя е ЧИСТА
ФУНКЦИЯ на `temp_hot`: нула нови прагове, нула нова математика, нула нови
колони. Старият К3 етикет („≥2 структурни двойки" върху лещови score-ове) НЕ
се възкресява — П4 го изпита и го пенсионира.
"""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from catalog.polarity import OPT_PROVENANCE, opt_keys, opt_zone, polarity_for
from core.primitives import apply_transform

# Бум-сериите — изведени от полярностната карта, не преписани (виж докстринга).
TEMP_SERIES: list[str] = opt_keys()

# ── БАЛОННАТА ДВОЙКА (фамилен мандат №53; JP представители по същия принцип) ─
# Представителите не са избор на вкус, а провенанс:
#   · имоти = `JP_RPPI` — ЦЕНАТА НА АКТИВА (BIS RPPI, 1955→, вижда балона
#     от 80-те).
#   · кредит = `JP_CREDIT_GDP_HH` ИЛИ `JP_CREDIT_GDP_NFC` — двата кредитни
#     крака дават ЕДИН сигнал (peer-групата `credit_depth` в каталога),
#     затова е достатъчно да гори единият.
BUBBLE_PAIR_PROPERTY = "JP_RPPI"
BUBBLE_PAIR_CREDIT = ("JP_CREDIT_GDP_HH", "JP_CREDIT_GDP_NFC")

# Името на уреда — ЕДИН източник (ФОРМА-КАНОН): лицето, context експортът и
# методологията го цитират, не го преписват.
BUBBLE_PAIR_LABEL_BG = "Балонната двойка (имоти↔кредит)"

# Провенансът, който пътува ЗАЕДНО с показанието навсякъде, където то се
# показва. Числата са мерени в П4 върху ЗАМРАЗЕНАТА история и се цитират КАТО
# такива, с източника — не се преизмерват мълчаливо тук.
BUBBLE_PAIR_PROVENANCE = (
    "JP v1: двойката е ДЕФИНИРАНА (имоти↔кредит по фамилния принцип №53), но "
    "НЕИЗПИТАНА — не е минала ретро-изпит върху японската история. До фаза 6 "
    "(OPT данни-пас с приемен гейт: балонната ера 1985-90 свети, спокойна "
    "епоха мълчи) няма обявени бум-серии, `temp_hot` е празен и двойката е "
    "структурно неактивна. Показанието е сигнал за СЪ-ПРЕГРЯВАНЕ на цената на "
    "актива и кредита — НЕ прогноза и НЕ етикет на тензия (К1 е отделен слой)."
)


def zone_table(catalog: Optional[dict] = None) -> list[dict]:
    """[{key, name_bg, lo, hi, s, provenance}] — зоните такива, каквито са в кода.

    Лицето и briefing_context рисуват ОТТУК, за да не се преписват прагове по
    места (ФОРМА-КАНОН: един речник).
    """
    rows: list[dict] = []
    for key in TEMP_SERIES:
        lo, hi, width = opt_zone(polarity_for(key))
        spec = (catalog or {}).get(key, {})
        rows.append({
            "key": key,
            "name_bg": spec.get("name_bg", key),
            "lo": lo,
            "hi": hi,
            "s": width,
            "provenance": OPT_PROVENANCE.get(key, ""),
        })
    return rows


def temperature(
    catalog: dict,
    snapshot: dict[str, pd.Series],
    *,
    at: Optional[pd.Timestamp] = None,
) -> dict[str, Any]:
    """Колко бум-серии горят към дадения момент.

    Връща `{n_hot, n_total, hot: [...], cold: [...], as_of}`. `hot` са сериите
    НАД `hi` (прегряването — това, което брои термометърът), `cold` — тези под
    `lo` (кризата; изнесени за контекст, не се броят в `n_hot`).

    `at` реже суровата серия по ПЕРИОДНАТА дата преди трансформацията — същата
    семантика като реконструираната история, затова числото е сравнимо назад.
    """
    hot: list[dict] = []
    cold: list[dict] = []
    n_total = 0
    as_of: Optional[pd.Timestamp] = None

    for key in TEMP_SERIES:
        spec = catalog.get(key)
        if spec is None:
            continue
        raw = snapshot.get(key)
        if raw is None or len(raw) == 0:
            continue
        if at is not None:
            raw = raw[raw.index <= at]
        transformed = apply_transform(raw, spec.get("transform", "level")).dropna()
        if transformed.empty:
            continue      # няма стойност → серията не се брои в знаменателя

        value = float(transformed.iloc[-1])
        last = transformed.index[-1]
        n_total += 1
        as_of = last if as_of is None else max(as_of, last)

        lo, hi, width = opt_zone(polarity_for(key))
        entry = {
            "key": key,
            "name_bg": spec.get("name_bg", key),
            "value": round(value, 2),
            "lo": lo,
            "hi": hi,
            "s": width,
            "last_date": last.strftime("%Y-%m-%d") if hasattr(last, "strftime") else str(last),
        }
        if value > hi:
            hot.append(entry)
        elif value < lo:
            cold.append(entry)

    return {
        "n_hot": len(hot),
        "n_total": n_total,
        "hot": hot,
        "cold": cold,
        "as_of": as_of.strftime("%Y-%m-%d") if as_of is not None else None,
    }


def hot_keys_str(temp: Optional[dict]) -> str:
    """Кой гори, компактно: „BG_LOANS_HH+BG_HPI" (празно при нула)."""
    if not temp:
        return ""
    return "+".join(e["key"] for e in temp.get("hot", []))


def temp_level(n_hot: int) -> str:
    """Трите нива на термометъра: `cold` (0) · `warm` (1-2) · `hot` (≥3).

    Един източник за цвета — лицето чете нивото оттук, не преизмисля прагове.
    """
    if n_hot <= 0:
        return "cold"
    if n_hot <= 2:
        return "warm"
    return "hot"


# ═════════════════════════════════════════════════════════════════════════════
# БАЛОННАТА ДВОЙКА — съ-прегряване имоти↔кредит (мандат №53)
# ═════════════════════════════════════════════════════════════════════════════
# Защо изобщо съществува: лещовите score-ове на имотите и кредита могат да
# изглеждат КРОТКИ (днес 62.3 и 40.8), докато и двете серии стоят над зоните
# си втора година. П2 премести бум-сигнала от score-овете в температурата —
# двойката покрива точно тази слепота, и то без нито един нов праг.

def bubble_pair_from_hot(hot: str) -> bool:
    """Активна ли е двойката според стринга на решетъчната колона `temp_hot`.

    Сепараторът е „+" (както го пише `hot_keys_str`); празно/`None` → False;
    редът на ключовете е без значение. Това е ЕДИНСТВЕНОТО правило — и живото
    четене, и историческото минават през него, затова двата пътя не могат да
    се разсинхронизират.
    """
    if not hot or (isinstance(hot, float) and hot != hot):
        return False
    keys = {part.strip() for part in str(hot).split("+") if part.strip()}
    return BUBBLE_PAIR_PROPERTY in keys and bool(keys & set(BUBBLE_PAIR_CREDIT))


def bubble_pair(temp: Optional[dict]) -> dict[str, Any]:
    """Двойката от изхода на `temperature()`.

    Връща `{active, burning, label_bg, sentence}`. `burning` са ключовете ОТ
    ДВОЙКАТА, които горят (може да е един при неактивна двойка — това е
    диагностика, не активиране); редът им е фиксиран (имоти → кредит), за да е
    изречението стабилно между пуските.

    `sentence` е ЕДИНСТВЕНИЯТ източник на човешкото изречение (ФОРМА-КАНОН):
    лицето и context експортът го ЦИТИРАТ, не го преписват.

    Консистентност ПО КОНСТРУКЦИЯ: активността се смята през
    `bubble_pair_from_hot(hot_keys_str(temp))`, тоест същото правило като на
    решетката — не втора реализация, която утре да се разминее.
    """
    hot_entries = (temp or {}).get("hot") or []
    names = {e["key"]: e.get("name_bg", e["key"]) for e in hot_entries}
    burning = [
        key for key in (BUBBLE_PAIR_PROPERTY, *BUBBLE_PAIR_CREDIT) if key in names
    ]
    active = bubble_pair_from_hot(hot_keys_str(temp))

    if active:
        who = " + ".join(names[key] for key in burning)
        sentence = f"{BUBBLE_PAIR_LABEL_BG}: АКТИВНА — горят {who}"
    else:
        sentence = f"{BUBBLE_PAIR_LABEL_BG}: неактивна"

    return {
        "active": active,
        "burning": burning,
        "label_bg": BUBBLE_PAIR_LABEL_BG,
        "sentence": sentence,
    }


def bubble_pair_streak(history: Optional[Any]) -> dict[str, Any]:
    """`{n, since}` — колко ПОРЕДНИ марка от края на решетката двойката е активна.

    Броят включва живия ред. Неактивна днес → `{0, None}`: серия, прекъсната
    вчера, не е „текуща" и не бива да се показва като такава.

    ⚠ Честност: това са МАРКОВЕ на тримесечната решетка, не календарни дни и не
    непременно тримесечия (живият ред седи там, където е последното
    наблюдение). Затова лицето казва „поредни марка", не „от N тримесечия".
    """
    empty = {"n": 0, "since": None}
    if history is None or len(history) == 0:
        return empty
    if "temp_hot" not in getattr(history, "columns", []):
        return empty

    n = 0
    since: Optional[Any] = None
    for stamp, value in zip(reversed(list(history.index)),
                            reversed(list(history["temp_hot"]))):
        if not bubble_pair_from_hot(value):
            break
        n += 1
        since = stamp

    if n == 0:
        return empty
    return {
        "n": n,
        "since": since.strftime("%Y-%m-%d") if hasattr(since, "strftime") else str(since),
    }


def bubble_pair_line(pair: Optional[dict], streak: Optional[dict] = None) -> str:
    """Изречението + опашката на персистенцията — както се чете на лицето.

    „…: АКТИВНА — горят Х + У, от 2023-12-01 (11 поредни марка)". Съставянето
    е ТУК (един източник), за да не се разминат лицето и експортът по
    формулировка; `sentence` остава непокътнат вътре в стринга.
    """
    if not pair or not pair.get("sentence"):
        return ""
    line = str(pair["sentence"])
    if pair.get("active") and streak and streak.get("n"):
        line += f", от {streak['since']} ({streak['n']} поредни марка)"
    return line
