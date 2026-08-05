"""
export/briefing_context.py
==========================
Markdown context export за LLM анализ (горивото на бъдещия macro-deep-brief-jp).

Фамилната конвенция: `output/briefing_context_YYYY-MM-DD.md`, генериран през
`python run.py --export-context`. Форматът е компактният фамилен модел,
пропорционален на каталога и 6-те лещи.

Всяко число тук идва от snapshot-а/скоринга/слоевете. Нула ръчни константи;
изреченията се ЦИТИРАТ от display/analysis, не се преписват — двете
повърхности (лицето и този експорт) не могат да се разминат по формулировка.

JP диференциаторът: секцията „Йена-слоят" — редовете идват ДОСЛОВНО от
`analysis.yen_segment.segment_lines` (ЕДИН източник на формулировките).
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Optional

import math

from analysis.lens_history import HONESTY_LABEL, history_stats, yearly_table
from analysis.temperature import (
    BUBBLE_PAIR_PROVENANCE,
    TEMP_SERIES,
    bubble_pair,
    bubble_pair_line,
    bubble_pair_streak,
    zone_table,
)
from analysis.tension import (
    AS_OF_NOTE,
    ENERGY_FLOOR,
    SIX_TO_SEVEN_NOTE,
    anchors_note,
    price_str,
    price_table,
    ratio_str,
)
from analysis.yen_segment import segment_lines, yen_segment
from catalog.polarity import OPT_SOURCE_NOTE, U_BAND
from catalog.series import SERIES_CATALOG
from config import LENS_BANDS, LENS_NAMES_BG
from core.display import (
    fmt_value,
    inflation_anchors,
    is_stale,
    thin_window_note,
)
from core.scorer import TANH_SLOPE

# ── ФИКСИРАНИ бележки за качеството на данните (JP уговорките) ───────────────
# Уговорките зад числата, които анализаторът трябва да знае ПРЕДИ да ги ползва.
DATA_QUALITY_NOTES = [
    "**FRED OECD-MEI замразяванията са картата на дупките в v1:** JP CPI е "
    "замразен на 2021-06, central-bank rate (IRSTCB01JPM156N) — на 2023-12 и "
    "ИЗПУСКА целия 2024-26 цикъл на покачване, M2/M3, CLI и housing starts "
    "също са спрели. Затова CPI идва от e-Stat, call rate-ът от ЖИВИЯ "
    "IRSTCI01JPM156N, а M2 просто липсва в v1 — дупката е декларирана, не "
    "запълнена с мъртва серия.",
    "**Японският БВП е известен с големи ревизии** (Cabinet Office): първата "
    "оценка излиза ~6 седмици след тримесечието и втората я мести осезаемо. "
    "Не строй остър извод върху последното тримесечие само.",
    "**e-Stat CPI:** ~3 седмици лаг след месеца; серията е 2020-база, linked "
    "назад до 1970 — един непрекъснат индекс, г/г темпът се смята в уреда.",
    "**BIS сериите (кредит към НФК/домакинства, RPPI) носят ~4-5 месеца лаг** "
    "— тримесечни са и последната точка изостава от месечните серии; "
    "кредитната и имотната леща дишат по-бавно от останалите по конструкция.",
    "**GFC знаменателят в кредитните зони:** 2008Q4-2010Q1 кредит/БВП темпът "
    "свети не от нов кредит, а от свит БВП (знаменателят пада). Деклариран "
    "клас фалшив позитив на температурния слой — в криза композитът и без "
    "това крещи от другите лещи.",
    "**CGPI (производствените цени):** flat файлът на BOJ носи само "
    "2020-базата (2020-01→) — твърде къса история за леща, затова серията е "
    "контекст, не глас в скоринга.",
    "**MOF week.csv е Shift-JIS и живее на JP-пътя** — английският път 404-ва "
    "(живо проверено 05.08.2026). JGB кривата: „-“ в ранните години значи "
    "липсващ tenor, не нула — дългите матуритети се раждат късно.",
    "**COT JPY идва от data-core канона (CFTC),** седмичен, с латентност ~3 "
    "дни след вторника на отчета. Не се фетчва наново тук — един канон, един "
    "източник.",
    "**Текущата сметка е BOJ BoP (1996→),** а не FRED тримесечната серия — тя "
    "е заложник на годишния OECD ревизионен цикъл (stale на 2024Q4 при "
    "скаутския пас 05.08.2026).",
    "**Фискалът е context-only (мандатно решение №1):** FRED дава само "
    "годишни IMF WEO данни до 2023 — 10 точки за 10-годишен робастен z е "
    "нечестно. Дълг и салдо са наблюдение до композита, не леща в него.",
    "**Tankan няма machine-readable история** (menu-item за бъдеща фаза) — "
    "growth лещата е без survey глас; четеш твърди данни, не настроение.",
    "**JPY cross-currency basis няма безплатен източник** (menu-item) — "
    "офшорният доларов funding стрес не се вижда в йена-слоя; при carry "
    "unwind епизод това е сляпото петно на уреда.",
    "**Трансформациите не са еднакви по произход:** INDPRO/RETAIL/EARNINGS "
    "идват от FRED ВЕЧЕ като г/г темпове (суфиксите GYSAM/659), докато "
    "CPI/RPPI/кредитът се диференцират в уреда (yoy_pct върху индекса). "
    "Числото в таблицата е винаги темпът, но родословието му е различно.",
    "**Датовите конвенции:** дневните серии (USDJPY, JGB кривата, "
    "диференциалите) сядат на датата на наблюдението; месечните — на ден 1 "
    "на месеца. „Данни към“ на дневна серия затова изглежда по-свежо от "
    "месечните ѝ съседи — това е ритъм, не превъзходство.",
]


def _thin_window_notes(lens_reports: dict) -> list[str]:
    """Динамични бележки за сериите с къс прозорец.

    Флагът идва от скоринга, не от ръчен списък — ако утре серията порасне над
    прага, бележката изчезва сама.
    """
    notes: list[str] = []
    for rep in lens_reports.values():
        for s in rep.get("series", []):
            if not s.get("thin_window"):
                continue
            notes.append(
                f"⚠ **{s.get('name_bg', s.get('key', '?'))} — "
                f"{s.get('percentile_window', 'къс прозорец')}:** "
                f"{thin_window_note()}"
            )
    return notes


def _inflation_anchor_block(voices: dict) -> list[str]:
    """Котвеният прочит — под инфлационната таблица.

    Всяко изречение идва от `core.display` (ЕДИН източник с лицето), затова
    дашбордът и този експорт не могат да се разминат по формулировка.
    """
    anchors = voices.get("anchors") or []
    if not anchors:
        return []

    L: list[str] = ["**Котвеният прочит (абсолютни пп от целта на BOJ):**", ""]
    for a in anchors:
        L.append(f"- {a['name_bg']}: {a['value_str']} = **{a['gap_phrase']}** — "
                 f"{a['zone_phrase']} (данни към {a['last_date']})")
    L.append("")
    L.append(voices.get("disclaimer", ""))
    L.append("")
    return L


def _lens_band(score: Optional[float]) -> str:
    """Лещова лента на 0–100 скалата (същите прагове, лещов речник).

    Режимното име („ВЛОШАВАЩ СЕ") принадлежи на КОМПОЗИТА. На ниво леща то би
    твърдяло нещо, което метриката не мери. Виж config.LENS_BANDS.
    """
    if score is None:
        return "НЯМА ДАННИ"
    for threshold, label in LENS_BANDS:
        if score >= threshold:
            return label
    return LENS_BANDS[-1][1]


def _fmt_score(score: Optional[float]) -> str:
    return f"{score:.1f}" if score is not None else "—"


def _fmt_delta(d: Optional[float]) -> str:
    return f"{d:+.1f}" if d is not None else "—"


def _history_section(history, wow) -> list[str]:
    """„Композитът през времето" — реконструкцията + живият журнал.

    Всяко число идва от решетката/журнала. Нула ръчни константи — включително
    percentile-ът, min/max и годишната таблица.
    """
    stats = history_stats(history)
    if stats is None and not wow:
        return []

    L: list[str] = []
    L.append("## Композитът през времето — реконструирана история [не PIT]")
    L.append("")
    L.append(HONESTY_LABEL)
    L.append("")

    # ── Какво се смени: ЖИВИЯТ журнал, не реконструкцията ────────────────────
    L.append("**Какво се смени (жив журнал):**")
    if not wow:
        L.append("- Първи запис в живия журнал — делтата тръгва от следващия пуск.")
    else:
        L.append(f"- Композит: {_fmt_delta(wow.get('composite_delta'))} "
                 f"спрямо {wow.get('prev_date', '—')}")
        deltas = [
            (lens, d) for lens, d in (wow.get("lens_deltas") or {}).items()
            if d is not None
        ]
        deltas.sort(key=lambda kv: abs(kv[1]), reverse=True)
        for lens, d in deltas[:3]:
            L.append(f"- {LENS_NAMES_BG.get(lens, lens)}: {_fmt_delta(d)}")
        if wow.get("composition_changed"):
            L.append("- ⚠ Съставът на уреда се смени между двата записа — "
                     "делтата НЕ е чиста.")
    L.append("")

    if stats is None:
        L.append("---")
        L.append("")
        return L

    # ── Къде сме спрямо реконструкцията ──────────────────────────────────────
    L.append("**Къде сме спрямо реконструираната история:**")
    if stats["percentile"] is not None:
        L.append(f"- Текущият композит ({_fmt_score(stats['current'])}) е над "
                 f"{stats['percentile']:.1f}% от {stats['n_quarters']} тримесечни "
                 f"точки ({stats['first_date']} → {stats['last_date']}).")
    L.append(f"- Най-ниско: {_fmt_score(stats['min_value'])} на {stats['min_date']}")
    L.append(f"- Най-високо: {_fmt_score(stats['max_value'])} на {stats['max_date']}")
    L.append("")

    rows = yearly_table(history)
    if rows:
        L.append("| Година | Среден композит | Тримесечни точки |")
        L.append("|--------|-----------------|------------------|")
        for r in rows:
            L.append(f"| {r['year']} | {r['mean_composite']:.1f} | {r['n']} |")
        L.append("")

    L.append("⚠ Ранните редове стъпват на ПО-КЪСИ норми и на по-малко серии "
             "(fallback-ите на скорера), затова сравнението 1990 срещу 2026 е "
             "ориентир, не калибрация. Цитирай числата винаги с уговорката "
             "„реконструирана история“; WoW делтата идва от живия журнал и е "
             "единственият истински PIT запис.")
    L.append("")
    L.append("---")
    L.append("")
    return L


def _zone_score() -> float:
    """Score-ът на серия В зоната — смятан от константите, не преписан."""
    return round(50.0 * (1.0 + math.tanh(U_BAND / TANH_SLOPE)), 1)


def _temperature_section(temp, history=None) -> list[str]:
    """„Температурният слой" — колко бум-серии са над зоната си.

    Всяко число идва от `analysis.temperature` и от полярностната карта. Нула
    ръчни константи: праговете и provenance-ът се четат от кода, не се
    преписват. Секцията носи и БАЛОННАТА ДВОЙКА (съ-прегряване имоти↔кредит).
    """
    if not temp or not temp.get("n_total"):
        return []

    n_hot, n_total = int(temp["n_hot"]), int(temp["n_total"])
    L: list[str] = []
    L.append(f"## Температурният слой: {n_hot}/{n_total} бум-серии над зоната си")
    L.append("")
    L.append("Термометърът брои САМО нарушенията НАГОРЕ — прегряването. Под долния "
             "праг е криза/дългово разлистване и то се чете в score-а (който пада "
             "и в двете посоки), не тук. Праговете са АБСОЛЮТНИ, затова числото е "
             "смятаемо и назад във времето без look-ahead — балонната ера 1985-90 "
             "е приемният гейт на зоните.")
    L.append("")

    if temp.get("hot"):
        L.append("**Кои горят сега:**")
        for e in temp["hot"]:
            L.append(f"- {e['name_bg']}: **{e['value']:.1f}** при праг {e['hi']:.1f} "
                     f"(данни към {e['last_date']})")
    else:
        L.append("**Нито една бум-серия не е над зоната си.**")
    L.append("")

    if temp.get("cold"):
        L.append("**Под долния праг (разлистване/криза, не прегряване — не влиза "
                 "в броя):**")
        for e in temp["cold"]:
            L.append(f"- {e['name_bg']}: **{e['value']:.1f}** при долен праг "
                     f"{e['lo']:.1f}")
        L.append("")

    # Балонната двойка — СЛЕД списъка кой гори, ПРЕДИ тензията.
    pair = bubble_pair(temp)
    line = bubble_pair_line(pair, bubble_pair_streak(history))
    if line:
        L.append(f"**{line}**")
        L.append("")
        L.append(f"⚠ {BUBBLE_PAIR_PROVENANCE}")
        L.append("")

    L.append("**Зоните и откъде идват праговете:**")
    L.append("")
    L.append("| Серия | Зона | 1σ на | Provenance на горния праг |")
    L.append("|-------|------|-------|---------------------------|")
    for z in zone_table(SERIES_CATALOG):
        L.append(f"| {z['name_bg']} | {z['lo']:.0f} … {z['hi']:.1f}% | "
                 f"{z['s']:.0f} пп | {z['provenance']} |")
    L.append("")
    L.append(OPT_SOURCE_NOTE)
    L.append("")
    L.append(f"⚠ Как се чете score при оптимална зона: серия В зоната стои на "
             f"**{_zone_score():.1f}**, не на 50 — платото е ЗДРАВЕ, не "
             f"неутралност. Score 50 при такава серия значи, че тя е точно на "
             f"един „s“ извън зоната. Затова не превеждай „50“ като „нормално“ "
             f"при {len(TEMP_SERIES)}-те бум-серии.")
    L.append("")
    L.append("---")
    L.append("")
    return L


def _tension_section(tension, history=None) -> list[str]:
    """„Тензионният слой (К1)" — показанието, разписката и фалсификаторът.

    Всяко число идва от `analysis.tension`, което пък чете само лещовите
    доклади. Секцията се появява САМО когато има показание.
    """
    if not tension or not tension.get("sentence"):
        return []

    L: list[str] = []
    L.append(f"## Тензионният слой (К1 „Погасяването“): {ratio_str(tension)}")
    L.append("")
    L.append(tension["sentence"])
    L.append("")
    if tension.get("energy") is not None:
        L.append(f"Енергия {tension['energy']:.2f} т. → нето {tension['net']:.2f} т. "
                 f"(праг на отказа: под {ENERGY_FLOOR:.0f} т. енергия показанието е "
                 f"„н.д.“, не 0). К1 мери ЛЪЖЛИВОТО СРЕДНО, не кризата: при срив "
                 f"всички лещи падат заедно, нищо не се погасява и показанието "
                 f"правилно мълчи.")
        L.append("")

    rows = price_table(tension)
    if rows:
        L.append("**Разписката (leave-one-out аукцион — цена = композит БЕЗ "
                 "лещата минус композит С нея; плюс = тежи, минус = крепи):**")
        L.append("")
        L.append("| Леща | Цена (композитни точки) | Композит без нея |")
        L.append("|------|-------------------------|------------------|")
        base = tension.get("composite")
        for r in rows:
            without = "—" if base is None else f"{base + r['price']:.1f}"
            L.append(f"| {LENS_NAMES_BG.get(r['lens'], r['lens'])} | "
                     f"{price_str(r['price'])} | {without} |")
        L.append("")

    falsifier = tension.get("falsifier") or {}
    if falsifier.get("sentence"):
        L.append(f"**Falsifier:** {falsifier['sentence']}")
        L.append("")

    L.append(f"⚠ {SIX_TO_SEVEN_NOTE}")
    L.append("")
    L.append(f"⚠ {AS_OF_NOTE}")
    L.append("")
    L.append(f"⚠ {anchors_note(history)}")
    L.append("")
    L.append("---")
    L.append("")
    return L


def _yen_section(snapshot: dict) -> list[str]:
    """„Йена-слоят" — диференциаторът на JP уреда, като секция на експорта.

    Редовете идват ДОСЛОВНО от `analysis.yen_segment.segment_lines` — ЕДИН
    източник на формулировките (същият, който печата `--status` и лицето).
    Тук се решава само рамката: заглавие, бележката и списъчният вид.
    """
    seg = yen_segment(snapshot)
    lines = segment_lines(seg)

    L: list[str] = []
    L.append(f"## {seg['label_bg']}")
    L.append("")
    L.append(f"Диференциаторът на JP уреда: {seg['note']}. Шестте блока са "
             f"сурови наблюдения — НЕ сигнал и НЕ прогноза; възелът на carry "
             f"unwind е позициониране × лихвена траектория.")
    L.append("")
    # lines[0] е конзолният хедър (име + бележка) — вече изречен по-горе.
    for line in lines[1:]:
        L.append(f"- {line.strip()}")
    L.append("")
    L.append("---")
    L.append("")
    return L


def generate_briefing_context(
    snapshot: dict,
    lens_reports: dict,
    composite: Optional[float],
    regime: dict,
    output_path: str,
    today: Optional[date] = None,
    history=None,
    wow=None,
    temp=None,
    tension=None,
) -> str:
    """Генерира Markdown context и го записва. Връща пътя."""
    if today is None:
        today = date.today()

    L: list[str] = []
    L.append("# 🇯🇵 Japan Macro Dashboard — Context за LLM анализ")
    L.append(f"**Дата:** {today.isoformat()}  ")
    L.append(f"**Генериран:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  ")
    n_scored = sum(len(r["series"]) for r in lens_reports.values())
    L.append(f"**Серии:** {len(snapshot)} в каталога · {n_scored} скорирани "
             f"в {len(lens_reports)} лещи · {len(snapshot) - n_scored} контекст "
             f"(вкл. йена-слоя)  ")
    L.append("")
    L.append("---")
    L.append("")

    # ── Композит + лещова таблица (изводът ПЪРВИ — ФОРМА-КАНОН) ──────────────
    L.append(f"## Композитен Macro Score: {_fmt_score(composite)} / 100")
    L.append(f"**Режим:** {regime.get('name', '—')}")
    L.append("")
    L.append("Скалата: 50 = близката 10-годишна норма на всяка серия (робастен z "
             "спрямо median ± 1.4826·MAD, притиснат през tanh). Инфлацията се "
             "мери като ОТКЛОНЕНИЕ от целта на BOJ (2%) в двете посоки — "
             "дефлационната страна на U-то в Япония е изживяна история, не "
             "теория. Числото е сравнимо с us/eu/china/bg-macro-dashboard "
             "(същият примитив).")
    L.append("")
    L.append(f"⚠ {SIX_TO_SEVEN_NOTE}")
    L.append("")
    L.append("| Леща | Score | Състояние |")
    L.append("|------|-------|-----------|")
    for lens, rep in lens_reports.items():
        name = LENS_NAMES_BG.get(lens, lens)
        L.append(f"| {name} | {_fmt_score(rep['score'])} | {_lens_band(rep['score'])} |")
    L.append("")
    L.append("---")
    L.append("")

    # ── Филмът: композитът през времето ──────────────────────────────────────
    L.extend(_history_section(history, wow))

    # ── Термометърът: колко бум-серии горят + балонната двойка ───────────────
    L.extend(_temperature_section(temp, history))

    # ── Тензията: колко от енергията се погасява ─────────────────────────────
    L.extend(_tension_section(tension, history))

    # ── Йена-слоят: диференциаторът на JP ────────────────────────────────────
    L.extend(_yen_section(snapshot))

    # ── Секция на всяка леща ─────────────────────────────────────────────────
    voices = inflation_anchors(snapshot)
    for lens, rep in lens_reports.items():
        L.append(f"## {LENS_NAMES_BG.get(lens, lens)}")
        L.append(f"**Score:** {_fmt_score(rep['score'])}  **Състояние:** {_lens_band(rep['score'])}")
        L.append("")
        L.append("| Показател | Стойност | Score | Данни към |")
        L.append("|-----------|----------|-------|-----------|")
        for s in rep["series"]:
            last = s.get("last_date") or "—"
            if last != "—" and is_stale(last, s.get("release_schedule", "monthly"), today):
                last = f"⚠ {last}"
            L.append(
                f"| {s['name_bg']} | {fmt_value(s)} | {_fmt_score(s.get('score'))} | {last} |"
            )
        L.append("")

        # Вторият глас стои ПОД таблицата на своята леща, не в нея.
        if lens == "inflation":
            L.extend(_inflation_anchor_block(voices))

        hints = [s.get("narrative_hint", "").strip() for s in rep["series"]]
        hints = [h for h in hints if h][:2]
        if hints:
            for h in hints:
                L.append(f"- {h}")
            L.append("")
        L.append("---")
        L.append("")

    # ── Бележки за качеството ────────────────────────────────────────────────
    L.append("## ⚠ Бележки за качеството на данните")
    L.append("")
    for note in DATA_QUALITY_NOTES:
        L.append(f"- {note}")
    for note in _thin_window_notes(lens_reports):
        L.append(f"- {note}")
    L.append("")
    L.append("---")
    L.append("")
    L.append("*Данни: FRED (OECD-MEI, BIS, IMF WEO препубликации) · e-Stat (CPI) "
             "· BOJ (BoP, CGPI flat файлове) · MOF (JGB крива, седмични потоци) "
             "· BIS (кредит и RPPI, чрез FRED) · data-core COT (CFTC).*")

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")
    print(f"✅ Context готов: {output_path}")
    return str(path)
