"""
analysis/tension.py
===================
ТЕНЗИОННИЯТ СЛОЙ — К1 „Погасяването" (мандат №51, по присъдата върху П4).

Какво мери и какво НЕ мери:

  · Композитът е ПРЕТЕГЛЕНО СРЕДНО. Средното не различава „всички лещи са
    около нормата" от „едни дърпат силно нагоре, други силно надолу, и двете
    се изяждат". Първото е спокойна икономика; второто е воюваща икономика,
    която ИЗГЛЕЖДА спокойна. К1 мери точно това разминаване.
  · `energy` е вътрешният натиск: Σw·|L−50| — колко точки отклонение има в
    системата, без значение накъде. `net` е това, което оцелява до композита:
    |Σw·(L−50)|. Погасената част е `ratio = 1 − net/energy`.
  · **К1 е детектор на ЛЪЖЛИВОТО СРЕДНО, не на кризата.** При срив всички
    лещи сочат надолу заедно, енергията минава почти цялата в нетното и К1
    правилно МЪЛЧИ (2008-12: ratio 0.218 на 6-лещовия уред). Високо
    показание значи „композитът е по-спокоен от състоянието", а не „лошо е".

Двете котви на прочита (от П4 доклада, `49-P4-TENSION-REPORT.md`):
  · **2015-19 ≈ 0.008** — най-високият композит в историята (68.3) при почти
    нулево погасяване: тогавашните 70 бяха ИСТИНСКИ консенсус на лещите.
  · **2025-09 = 0.995** — „фалшивата неутралност": 15.8 точки енергия се свиват
    до 0.075 нетно при композит 49.9.

⚠ **6→7 преходът.** П4 тестът съдеше ЗАМРАЗЕНАТА 6-лещова история (преди №50).
Вграденият тук К1 тече на ЖИВИЯ 7-лещов уред → числата се РАЗМИНАВАТ и това се
декларира навсякъде, където показанието се показва (виж `SIX_TO_SEVEN_NOTE`).

Правото на отказ: при `energy < ENERGY_FLOOR` съотношението е „н.д.", НЕ 0 —
малък знаменател би произвел показание от нищото.

Нула независими пътища: числата идват САМО от `lens_reports` (същите доклади,
по които се смята композитът). Тензионният слой е СЛОЙ ВЪРХУ уреда, а не
промяна В него — композитът остава бит-в-бит недокоснат (гейт-тест).
"""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from config import EPOCHS, LENS_SUBJECTS_BG, MODULE_WEIGHTS

# Под този вътрешен натиск съотношението не се смята — знаменателят е твърде
# малък, за да носи информация (П4 §А5 „правото на отказ").
ENERGY_FLOOR = 5.0

# Прагът на прочита: под 0.50 напрежението престава да доминира. Falsifier-ът се
# смята срещу него, не срещу вкус.
RATIO_PIVOT = 0.50

# ── Декларацията 6→7 — ЕДИН източник (ФОРМА-КАНОН) ───────────────────────────
# Лицето, методологията и briefing_context цитират ТОЗИ стринг. Ако утре влезе
# осма леща, изречението се сменя на едно място.
SIX_TO_SEVEN_NOTE = (
    "JP уредът е 6-лещов (фискалът е контекст по мандат INIT-26); до фаза 4 "
    "инфлационната леща е без данни и К1 реално тече на петте живи лещи — "
    "числата не се сравняват 1:1 с другите членове на фамилията."
)

# Кое четене е публичното (присъдата по §6 на доклада): full с етикет
# „реконструирана"; as-of четенето остава в одитната следа на П4.
AS_OF_NOTE = (
    "Публичното четене е full (днешният уред върху цялата история) с етикета "
    "„реконструирана“; as-of четенето живее в одитната следа (П4 CSV-тата)."
)

ND_LABEL = "н.д."

# ── Котвите на прочита ───────────────────────────────────────────────────────
# Числата на П4 са от ЗАМРАЗЕНАТА 6-лещова история и се цитират КАТО ТАКИВА, с
# датата и източника. Живият 7-лещов уред чете същите прозорци по друг начин —
# затова спокойната епоха се МЕРИ (`epoch_ratio_stats`), не се преписва.
#
# ⚠ Мандат №55: границите на спокойната епоха вече ЖИВЕЯТ в `config.EPOCHS` —
# същата декларация обслужва и наемния епохен прочит. Двете имена долу остават
# като тънки псевдоними, за да не се чупи нито един import.
# JP: ролята на „спокойната" референтна епоха играе абеномиката (2013-19) —
# най-близкият стабилен пред-ковид прозорец. Тя се МЕРИ (`epoch_ratio_stats`
# върху живата решетка), НЕ се цитира по памет: JP уредът няма ретро-изпит
# като българския П4 и котвите му тепърва ще се родят (фаза 6+).
CALM_EPOCH_START, CALM_EPOCH_END = EPOCHS["abenomics"]

# Името на живия ред в решетката. Дублирането на стринга тук (вместо импорт от
# `analysis.lens_history`) е нарочно — иначе двата модула се внасят циклично.
ROW_LIVE_NAME = "live"


def lens_scores(lens_reports: dict, weights: Optional[dict] = None) -> dict[str, float]:
    """{леща: score} само за лещите С показание — редът е редът на теглата.

    Единствената входна точка към данните: ако лещата няма score, тя не влиза
    нито в енергията, нито в теглата (същото правило като в композита —
    празната леща ИЗПАДА, не се брои за „неутрално 50").
    """
    weights = MODULE_WEIGHTS if weights is None else weights
    out: dict[str, float] = {}
    for lens in weights:
        rep = lens_reports.get(lens) or {}
        score = rep.get("score") if isinstance(rep, dict) else None
        if score is None or (isinstance(score, float) and score != score):
            continue
        out[lens] = float(score)
    return out


def _renorm(weights: dict, lenses: list[str]) -> dict[str, float]:
    """Теглата на наличните лещи, ренормализирани до сума 1."""
    total = sum(float(weights[l]) for l in lenses)
    if total == 0:
        return {l: 0.0 for l in lenses}
    return {l: float(weights[l]) / total for l in lenses}


def _subject(lens: str) -> str:
    return LENS_SUBJECTS_BG.get(lens, lens)


def _empty(reason: str) -> dict[str, Any]:
    return {
        "ratio": None,
        "energy": None,
        "net": None,
        "net_signed": None,
        "composite": None,
        "prices": {},
        "top_payer": None,
        "top_supporter": None,
        "sentence": reason,
        "falsifier": None,
        "nd": True,
        "n_lenses": 0,
    }


def annihilation(lens_reports: dict, weights: Optional[dict] = None) -> dict[str, Any]:
    """К1 „Погасяването" + LOO аукционът — от лещовите доклади, нищо друго.

    Връща::

        {ratio, energy, net, net_signed, composite, prices: {леща: цена},
         top_payer, top_supporter, sentence, falsifier, nd, n_lenses}

    · `ratio = 1 − |Σw·(L−50)| / Σw·|L−50|` върху НАЛИЧНИТЕ лещи с
      ренормализирани тегла; `energy < ENERGY_FLOOR` → `nd=True` и `ratio=None`
      („н.д.", не 0).
    · Цената на лещата (LOO аукцион) е `композит_БЕЗ − композит_С` при
      ренормализация. ПЛЮС значи „махнеш ли я, композитът се качва", т.е.
      лещата ТЕЖИ на композита; МИНУС значи, че тя го КРЕПИ.
    · `falsifier` казва при коя нетна стойност показанието пада под 0.50 и в
      кой композитен коридор това се превежда при непроменена енергия.
    """
    weights = MODULE_WEIGHTS if weights is None else weights
    scores = lens_scores(lens_reports, weights)
    lenses = [l for l in weights if l in scores]
    if not lenses:
        return _empty("Няма измерена леща — тензионният слой мълчи.")

    w = _renorm(weights, lenses)
    dev = {l: scores[l] - 50.0 for l in lenses}
    energy = sum(w[l] * abs(dev[l]) for l in lenses)
    net_signed = sum(w[l] * dev[l] for l in lenses)
    composite = 50.0 + net_signed

    # LOO аукционът: цена = композит_БЕЗ − композит_С (знаковата конвенция на П4)
    prices: dict[str, Optional[float]] = {}
    for lens in lenses:
        rest = [l for l in lenses if l != lens]
        if not rest:
            prices[lens] = None
            continue
        wr = _renorm(weights, rest)
        comp_wo = sum(wr[l] * scores[l] for l in rest)
        prices[lens] = round(comp_wo - composite, 4)

    priced = [(l, p) for l, p in prices.items() if p is not None]
    top_payer = top_supporter = None
    if priced:
        payer = max(priced, key=lambda kv: kv[1])
        supporter = min(priced, key=lambda kv: kv[1])
        top_payer = {"lens": payer[0], "subject": _subject(payer[0]), "price": payer[1]}
        top_supporter = {"lens": supporter[0], "subject": _subject(supporter[0]),
                         "price": supporter[1]}

    nd = energy < ENERGY_FLOOR
    ratio = None if nd else round(1.0 - abs(net_signed) / energy, 4)

    if nd:
        sentence = (
            f"Лещовата енергия е {energy:.1f} т. — под прага от "
            f"{ENERGY_FLOOR:.0f} т.; показанието е „{ND_LABEL}“ "
            f"(няма достатъчно натиск, който да се погасява)."
        )
    elif top_payer is None or top_supporter is None:
        sentence = (
            f"{ratio * 100:.0f}% от лещовата енергия се погасява в средното — "
            f"композитът е по-спокоен от състоянието."
        )
    else:
        sentence = (
            f"{ratio * 100:.0f}% от лещовата енергия се погасява в средното — "
            f"композитът е по-спокоен от състоянието; тежи "
            f"{top_payer['subject']} ({top_payer['price']:+.1f} т.), крепи "
            f"{top_supporter['subject']} ({top_supporter['price']:+.1f} т.)."
        )

    return {
        "ratio": ratio,
        "energy": round(energy, 4),
        "net": round(abs(net_signed), 4),
        "net_signed": round(net_signed, 4),
        "composite": round(composite, 4),
        "prices": prices,
        "top_payer": top_payer,
        "top_supporter": top_supporter,
        "sentence": sentence,
        "falsifier": falsifier(energy),
        "nd": bool(nd),
        "n_lenses": len(lenses),
    }


def falsifier(energy: float, pivot: float = RATIO_PIVOT) -> Optional[dict]:
    """При коя нетна стойност показанието пада под 0.50 — и какъв композит е това.

    `ratio < pivot` ⇔ `net > (1 − pivot)·energy`. При непроменена енергия това е
    композитен КОРИДОР: извън `50 ± net_крит` напрежението престава да доминира.
    """
    if energy is None or energy <= 0:
        return None
    net_crit = (1.0 - float(pivot)) * float(energy)
    low, high = 50.0 - net_crit, 50.0 + net_crit
    return {
        "pivot": float(pivot),
        "net": round(net_crit, 2),
        "composite_low": round(low, 1),
        "composite_high": round(high, 1),
        "sentence": (
            f"Показанието пада под {pivot:.2f}, когато нетното отклонение мине "
            f"{net_crit:.2f} т. — при непроменена енергия това значи композит "
            f"под {low:.1f} или над {high:.1f}."
        ),
    }


def price_table(tension: Optional[dict]) -> list[dict]:
    """Разписката на LOO аукциона, подредена от най-скъпата към най-крепящата.

    [{lens, subject, price}] — лицето и context експортът рисуват ОТТУК, за да
    не сортират по места (ФОРМА-КАНОН: един речник).
    """
    if not tension:
        return []
    rows = [
        {"lens": lens, "subject": _subject(lens), "price": price}
        for lens, price in (tension.get("prices") or {}).items()
        if price is not None
    ]
    rows.sort(key=lambda r: r["price"], reverse=True)
    return rows


def epoch_label(start: str = CALM_EPOCH_START, end: str = CALM_EPOCH_END) -> str:
    """`2015-01-01`, `2019-12-31` → „2015-19" — етикетът се ИЗВЕЖДА, не се зашива."""
    a, b = pd.Timestamp(start), pd.Timestamp(end)
    return f"{a.year}-{str(b.year)[-2:]}"


def epoch_ratio_stats(
    history: Optional[Any],
    start: str = CALM_EPOCH_START,
    end: str = CALM_EPOCH_END,
) -> Optional[dict]:
    """{label, mean, max, n} на `k1_ratio` в даден прозорец от решетката.

    Мери СЕГАШНИЯ уред. Точно затова спокойната епоха не се цитира по памет:
    на 6-лещовата история тя е ≈0, а със седмата леща числото е друго — и
    разликата е информация, не шум.
    """
    if history is None or len(history) == 0 or "k1_ratio" not in history.columns:
        return None
    df = history
    if "row_type" in df.columns:
        df = df[df["row_type"] != ROW_LIVE_NAME]
    part = df.loc[
        (df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end)),
        "k1_ratio",
    ].dropna()
    if part.empty:
        return None
    return {
        "label": epoch_label(start, end),
        "mean": round(float(part.mean()), 3),
        "max": round(float(part.max()), 3),
        "n": int(len(part)),
    }


def anchors_note(history: Optional[Any] = None) -> str:
    """Котвите на прочита + декларацията 6→7, с ИЗМЕРЕНОТО за живия уред."""
    base = (
        f"JP уредът НЯМА ретро-изпитани котви (българският П4 прецедент не се "
        f"пренася — други лещи, друга история). Референтната епоха "
        f"({epoch_label()}, абеномиката) се мери на живо от решетката. "
        f"{SIX_TO_SEVEN_NOTE}"
    )
    stats = epoch_ratio_stats(history)
    if not stats:
        return base
    return (
        f"{base} Измереното на живия уред за същия прозорец {stats['label']}: "
        f"средно {stats['mean']:.3f} (n={stats['n']}) — седмата леща стои далеч "
        f"под останалите в първата половина на епохата и добавя погасена "
        f"енергия, която 6-лещовият уред не е виждал."
    )


def ratio_str(tension: Optional[dict]) -> str:
    """Показанието както се чете: „0.493" или „н.д."."""
    if not tension or tension.get("ratio") is None:
        return ND_LABEL
    return f"{float(tension['ratio']):.3f}"


def price_str(price: Optional[float]) -> str:
    """Цената както се чете: „+5.2" · „-4.8" · „0.0".

    Закръглената нула се показва БЕЗ знак — „-0.0" изглежда като дефект, а
    смисълът е „тази леща не мести композита".
    """
    if price is None:
        return "—"
    value = round(float(price), 1)
    if value == 0:
        return "0.0"
    return f"{value:+.1f}"
