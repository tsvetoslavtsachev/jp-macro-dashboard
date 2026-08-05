"""
analysis/lens_history.py
========================
Реконструираната лещова история + ЖИВИЯТ журнал (мандат №45, П1).

Двата артефакта тук са РАЗЛИЧНИ уреди и НЕ се смесват:

1. **Реконструираната история** (`data/lens_history.parquet`) — какво би казал
   ДНЕШНИЯТ уред, ако беше гледал само данните до дадено тримесечие. Прави се с
   **днешните дефиниции** (днешният каталог, днешните полярности, днешните
   тегла) върху **днешните — вече ревизирани — данни**, като сериите се режат по
   ПЕРИОДНАТА дата (`s[s.index <= t]`). Това **НЕ е point-in-time**: не знаем
   какво е показвал екранът тогава, защото:
     · числата оттогава са ревизирани (БВП, заплати, разрешителни са
       `revision_prone`), а ние виждаме само ревизираната версия;
     · режем по периода на наблюдението, не по датата на ПУБЛИКУВАНЕ — реален
       наблюдател през март не е разполагал с мартенското тримесечие;
     · съставът на уреда (7 лещи, 19 скорирани серии) не е съществувал през 2007.
   Затова редът се чете като „как изглежда този период през днешния уред", а не
   като „какво писа дашбордът тогава". Ранните редове стъпват на ПО-КЪСИ норми
   (fallback-ите на скорера: <36 точки в 10-г. прозорец → пълна история; <12 →
   неутрално 50) и на по-малко лещи — затова `n_series` и `n_lenses` пътуват
   във ВСЕКИ ред и се четат заедно със `composite`.

2. **Живият журнал** (`data/score_journal.csv`) — истинският PIT запис: по един
   ред на всеки ритуален пуск, с числата такива, каквито са били в момента на
   пуска. Той тръгва ДНЕС и расте напред. Журналът НЕ се seed-ва назад от
   старите briefing_context файлове — те са ДРУГИ композиции (36.3 / 40.3 /
   39.7 / 45.1 са различни уреди) и ретро-редовете биха били нечестни.

Нула нова математика: историята минава през СЪЩИЯ `compute_lens_reports` →
`compute_composite_score`, по който върви и живото `--status`. Затова рязането
при `t_live` е no-op и последният ред е ТЪЖДЕСТВЕН на живото изчисление —
това е гейт-тестът на модула. От мандат №47 гейтът включва и `temp_count`.

⚠ Мандат №47: всеки ред носи и ТЕМПЕРАТУРА (`temp_count` + `temp_hot`) —
колко бум-серии стоят над абсолютната си зона на този марк. Праговете са
абсолютни, затова колоната е смятаема назад БЕЗ look-ahead и точно тя носи
приемния гейт (2006H2-2008 свети · 2015-2019 мълчи). Виж
`analysis/temperature.py`.

⚠ Мандат №51: всеки ред носи и ТЕНЗИЯ (`k1_ratio`) — колко от лещовата енергия
се погасява в средното на този марк. Числото се смята от СЪЩИТЕ лещови доклади,
от които идват `score_*` колоните (нула независими пътища), затова е
консистентно с реда по конструкция. „н.д." (енергия под прага) е ПРАЗНА клетка,
не 0. Виж `analysis/tension.py` — включително декларацията 6→7: П4 тестът
съдеше 6-лещовата история, тази колона тече на 7-лещовия уред.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from config import DATA_DIR, MODULE_WEIGHTS
from analysis.temperature import hot_keys_str, temperature
from analysis.tension import annihilation
from catalog.polarity import polarity_for
from catalog.series import SERIES_CATALOG
from core.scorer import (
    _polarity_repr,          # ЕДИН източник за стринговия вид на полярността
    compute_composite_score,
    compute_lens_reports,
)

# ── Решетката ────────────────────────────────────────────────────────────────
# JP: решетката тръгва от 1985 — за да носи балонната ера 1985-90 (бъдещият
# приемен гейт на фаза 6). Робастният прозорец тогава стъпва на данни от
# 1975+ (BIS кредит 1964→, IP 1956→, безработица 1970→); късите серии
# (БВП 1994→, TIBOR 2002→) носят thin_window флаг, не мълчат.
GRID_START = "1985-12-01"

# Ден 1 на месеците 3/6/9/12. Марк на тази решетка включва ЗАВЪРШЕНОТО
# тримесечие и в двете датови конвенции на репото: тримесечните Eurostat серии
# сядат на ден 1 на ПЪРВИЯ месец от тримесечието (2026-Q1 → 2026-01-01), а
# сплайснатите кредитни — на ден 1 на ПОСЛЕДНИЯ (2026-03-01).
GRID_FREQ = "QS-DEC"

ROW_QUARTER = "quarter"
ROW_LIVE = "live"

HISTORY_PATH = DATA_DIR / "lens_history.parquet"
JOURNAL_PATH = DATA_DIR / "score_journal.csv"

# ── Етикетът на честността — ЕДИН източник (ФОРМА-КАНОН) ─────────────────────
# Лицето и briefing_context цитират ТОЗИ стринг, не своя препис. Ако утре
# семантиката се смени, се сменя на едно място.
HONESTY_LABEL = (
    "Реконструирана история — днешните дефиниции и днешните данни върху "
    "тримесечна решетка от 1985Q4; не point-in-time запис."
)


# ═════════════════════════════════════════════════════════════════════════════
# КОЛОНИТЕ
# ═════════════════════════════════════════════════════════════════════════════

def _lens_order() -> list[str]:
    """Лещите в реда на `MODULE_WEIGHTS` — един ред навсякъде."""
    return list(MODULE_WEIGHTS)


def history_columns() -> list[str]:
    """Колоните на решетката (без индекса `date`).

    `temp_count` / `temp_hot` са температурният слой (мандат №47): колко
    бум-серии стоят над зоната си на този марк и кои точно. Праговете са
    АБСОЛЮТНИ, затова колоната е смятаема и назад — нула look-ahead.

    `k1_ratio` е тензионният слой (мандат №51): колко от лещовата енергия се
    погасява в средното. Смята се от score-овете на СЪЩИЯ ред, затова също е
    валидна назад — тя не пита данните за нищо ново.
    """
    lenses = _lens_order()
    return (
        ["composite"]
        + [f"z_{lens}" for lens in lenses]
        + [f"score_{lens}" for lens in lenses]
        + ["n_series", "n_lenses", "temp_count", "temp_hot", "k1_ratio", "row_type"]
    )


def journal_columns() -> list[str]:
    """Колоните на живия журнал (`date` е ПЪРВА колона, не индекс)."""
    lenses = _lens_order()
    return (
        ["date", "composite"]
        + [f"score_{lens}" for lens in lenses]
        + [f"z_{lens}" for lens in lenses]
        + ["n_series", "n_lenses", "temp_count", "k1_ratio", "composition"]
    )


# ═════════════════════════════════════════════════════════════════════════════
# СЪСТАВЪТ НА УРЕДА — тагът, който се сменя САМ
# ═════════════════════════════════════════════════════════════════════════════

def composition_tag(
    catalog: Optional[dict] = None,
    weights: Optional[dict] = None,
) -> str:
    """Отпечатък на УРЕДА: `<N>s<M>l-<sha1[:8]>`.

    Влиза всичко, което мени значението на числото: серия → (леща, peer-група,
    трансформация, полярност) + модулните тегла. Смяна на състав, на peer-група,
    на полярност или на тегло → друг таг, БЕЗ някой да го помни. Така WoW
    делтата може да каже „съставът се смени между двата записа — делтата не е
    чиста", вместо да сравнява ябълки с круши мълчаливо.
    """
    catalog = SERIES_CATALOG if catalog is None else catalog
    weights = MODULE_WEIGHTS if weights is None else weights

    series_part: dict[str, list[Any]] = {}
    for key, spec in catalog.items():
        lenses = list(spec.get("lens", []))
        pol = polarity_for(key, lenses[0] if lenses else None)
        series_part[key] = [
            lenses,
            spec.get("peer_group") or key,
            spec.get("transform", "level"),
            _polarity_repr(pol),
        ]

    payload = {"series": series_part, "weights": dict(weights)}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
    digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:8]
    return f"{len(catalog)}s{len(weights)}l-{digest}"


# ═════════════════════════════════════════════════════════════════════════════
# ДВИГАТЕЛЯТ
# ═════════════════════════════════════════════════════════════════════════════

def last_observation(snapshot: dict[str, pd.Series]) -> Optional[pd.Timestamp]:
    """Максималната последна дата измежду СУРОВИТЕ серии в snapshot-а."""
    lasts: list[pd.Timestamp] = []
    for s in snapshot.values():
        if s is None or not isinstance(getattr(s, "index", None), pd.DatetimeIndex):
            continue
        clean = s.dropna()
        if clean.empty:
            continue
        lasts.append(clean.index[-1])
    return max(lasts) if lasts else None


def build_grid(
    snapshot: dict[str, pd.Series],
    *,
    grid_start: str = GRID_START,
) -> list[tuple[pd.Timestamp, str]]:
    """[(марк, row_type)] — тримесечните маркове СТРОГО преди `t_live` + живата точка.

    Живата точка е отделен ред, а не поредният марк: така „днес" винаги е
    последният ред, дори когато днешната дата случайно седи върху решетката
    (тогава марк-редът отпада и остава само живият — без дубликат).
    """
    t_live = last_observation(snapshot)
    if t_live is None:
        return []
    marks = pd.date_range(grid_start, t_live, freq=GRID_FREQ)
    rows = [(t, ROW_QUARTER) for t in marks if t < t_live]
    rows.append((t_live, ROW_LIVE))
    return rows


def _row_from_reports(lens_reports: dict, composite: Optional[float],
                      row_type: str, temp: Optional[dict] = None) -> dict[str, Any]:
    """Лещовите доклади (+ температурата + тензията) → един ред.

    `temp=None` значи „не е мерено", не „нула горещи" — редът носи празна
    стойност вместо фалшива студенина.

    `k1_ratio` се смята ТУК, от същите доклади: така колоната не може да се
    разсинхронизира със `score_*` колоните на реда. „н.д." (енергия под прага)
    остава празна клетка — не 0.
    """
    row: dict[str, Any] = {"composite": composite}
    for lens in _lens_order():
        rep = lens_reports.get(lens, {})
        row[f"z_{lens}"] = rep.get("health_z")
    for lens in _lens_order():
        rep = lens_reports.get(lens, {})
        row[f"score_{lens}"] = rep.get("score")
    row["n_series"] = int(sum(
        rep.get("n_series", 0) or 0 for rep in lens_reports.values()
    ))
    row["n_lenses"] = int(sum(
        1 for rep in lens_reports.values() if rep.get("score") is not None
    ))
    row["temp_count"] = None if temp is None else int(temp.get("n_hot", 0))
    row["temp_hot"] = hot_keys_str(temp)
    row["k1_ratio"] = annihilation(lens_reports).get("ratio")
    row["row_type"] = row_type
    return row


def build_history(
    catalog: dict,
    snapshot: dict[str, pd.Series],
    *,
    grid_start: str = GRID_START,
) -> pd.DataFrame:
    """Реконструираната тримесечна лещова история (виж докстринга на модула).

    За всеки марк `t` суровите серии се режат на `s[s.index <= t]` и минават
    през СЪЩИЯ скорер като живото изчисление. `snapshot`-ът не се мутира.

    ⚠ Семантика: реконструкция с ДНЕШНИТЕ дефиниции върху ДНЕШНИТЕ (ревизирани)
    данни, рязана по ПЕРИОДНАТА дата — **не point-in-time**. Ранните редове
    стъпват на по-къси норми и на по-малко лещи; `n_series` и `n_lenses` казват
    колко уред реално стои зад точката.
    """
    grid = build_grid(snapshot, grid_start=grid_start)
    if not grid:
        return _empty_history()

    records: list[dict[str, Any]] = []
    index: list[pd.Timestamp] = []
    for t, row_type in grid:
        cut = {k: s[s.index <= t] for k, s in snapshot.items() if s is not None}
        reports = compute_lens_reports(catalog, cut)
        composite = compute_composite_score(
            {lens: rep["score"] for lens, rep in reports.items()}
        )
        # Температурата се мери върху СЪЩИЯ рязан snapshot — абсолютните прагове
        # нямат look-ahead, затова колоната е честна и на марк от 2007.
        records.append(_row_from_reports(
            reports, composite, row_type, temp=temperature(catalog, cut)
        ))
        index.append(t)

    df = pd.DataFrame(records, index=pd.DatetimeIndex(index, name="date"))
    return _normalize_history(df)


def _empty_history() -> pd.DataFrame:
    df = pd.DataFrame(columns=history_columns(),
                      index=pd.DatetimeIndex([], name="date"))
    return _normalize_history(df)


def _normalize_history(df: pd.DataFrame) -> pd.DataFrame:
    """Фиксирани колони и dtype-ове — иначе parquet-ът не е идемпотентен."""
    df = df.reindex(columns=history_columns())
    lenses = _lens_order()
    for col in ["composite"] + [f"z_{l}" for l in lenses] + [f"score_{l}" for l in lenses]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    for col in ("n_series", "n_lenses"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype("int64")
    # Нулевата температура е ЛЕГИТИМЕН отговор (2015-19 мълчи 0/20), затова
    # колоната е nullable: празно = „не е мерено", 0 = „мерено, никой не гори".
    df["temp_count"] = pd.to_numeric(df["temp_count"], errors="coerce").astype("Int64")
    df["temp_hot"] = df["temp_hot"].fillna("").astype("object")
    # Тензията е ЧИСЛО с легитимно празно: „н.д." (енергия под прага) е отказ да
    # се произведе показание, не нула. Затова float64 с NaN, а не 0.0.
    df["k1_ratio"] = pd.to_numeric(df["k1_ratio"], errors="coerce").astype("float64")
    df["row_type"] = df["row_type"].astype("object")
    df.index = pd.DatetimeIndex(df.index, name="date")
    return df


# ═════════════════════════════════════════════════════════════════════════════
# ЗАПИС
# ═════════════════════════════════════════════════════════════════════════════
# Каноничният запис (чип-билетът на Ц., 29.07.2026; лечение по №44 price_guard
# прецедента). `build_history` не е бит-стабилен между среди — последно-цифрен
# float jitter в z-клетките (локален пуск срещу CI) влачеше шумни parquet
# диффове в понеделнишките комити без промяна по същество. Лекът е в ЗАПИСА,
# не в уреда (in-memory числата остават пълна точност, гейтът бит-в-бит стои):
#   ROUND    — float колоните се закръглят до канонична точност при запис;
#              jitter-ът е ~1e-15 и закръглянето го убива изцяло;
#   DEADBAND — ако съществуващият файл носи същите ПО СЪЩЕСТВО стойности
#              (в допуска), старите байтове остават — така не мърдат и pyarrow
#              метаданните между версии/среди. Материална промяна → пълен запис.

ROUND_DECIMALS = 4
# Прагът трябва да поглъща СТРОГО наблюдавания крос-среда шум, не да сяда върху
# него: реалният CI↔локално jitter е ±0.001 в z-клетките (мерен в №51 и
# възпроизведен при №54 — 7 клетки точно на 0.001, а float остатъкът на
# изваждането го бута над праг 1e-3 и гардът падаше на собствената си граница).
# 2e-3 го поглъща с резерв и остава далеч под четимата резолюция (score 0.1).
DEADBAND_EPS = 2e-3


def _float_columns() -> list[str]:
    """Float колоните на решетката — тези, които ROUND/DEADBAND третират."""
    lenses = _lens_order()
    return (["composite"] + [f"z_{l}" for l in lenses]
            + [f"score_{l}" for l in lenses] + ["k1_ratio"])


def _round_history(df: pd.DataFrame) -> pd.DataFrame:
    """Каноничната точност на записа (`ROUND_DECIMALS`); df-ът не се мутира."""
    df = df.copy()
    for col in _float_columns():
        df[col] = df[col].round(ROUND_DECIMALS)
    return df


def _within_deadband(existing: pd.DataFrame, canon: pd.DataFrame) -> bool:
    """Еднакви по същество: форма/индекс точно · float в допуска · останалото точно."""
    if existing.shape != canon.shape or not existing.index.equals(canon.index):
        return False
    if list(existing.columns) != list(canon.columns):
        return False
    float_cols = set(_float_columns())
    for col in canon.columns:
        a, b = existing[col], canon[col]
        if col in float_cols:
            if not (a.isna() == b.isna()).all():
                return False
            if not ((a - b).abs().fillna(0.0) <= DEADBAND_EPS).all():
                return False
        elif not a.equals(b):
            return False
    return True


def write_history(df: pd.DataFrame, path: Path | str = HISTORY_PATH) -> str:
    """Решетката → parquet (pyarrow), в каноничната точност.

    Идемпотентен И бит-стабилен: същият df → същите байтове, а пуск от друга
    среда със същите по същество стойности (в `DEADBAND_EPS`) оставя старите
    байтове недокоснати. Файлът мърда само при материална промяна.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    canon = _round_history(_normalize_history(df))
    if out.exists():
        try:
            existing = _normalize_history(pd.read_parquet(out, engine="pyarrow"))
        except Exception:
            existing = None
        if existing is not None and _within_deadband(existing, canon):
            return str(out)
    canon.to_parquet(out, engine="pyarrow", index=True)
    return str(out)


def load_history(path: Path | str = HISTORY_PATH) -> pd.DataFrame:
    """Записаната решетка (празна рамка при липсващ файл)."""
    src = Path(path)
    if not src.exists():
        return _empty_history()
    return _normalize_history(pd.read_parquet(src, engine="pyarrow"))


# ═════════════════════════════════════════════════════════════════════════════
# ЖИВИЯТ ЖУРНАЛ
# ═════════════════════════════════════════════════════════════════════════════

def _normalize_journal(df: pd.DataFrame) -> pd.DataFrame:
    """Фиксирани колони, dtype-ове и ред — иначе двоен пуск мени байтовете."""
    df = df.reindex(columns=journal_columns())
    lenses = _lens_order()
    for col in ["composite"] + [f"score_{l}" for l in lenses] + [f"z_{l}" for l in lenses]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    for col in ("n_series", "n_lenses"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype("int64")
    # Старите редове (отпреди №47) нямат температура — остават ПРАЗНИ, не 0.
    df["temp_count"] = pd.to_numeric(df["temp_count"], errors="coerce").astype("Int64")
    # Същото за тензията (отпреди №51): празна клетка = „не е мерено".
    df["k1_ratio"] = pd.to_numeric(df["k1_ratio"], errors="coerce").astype("float64")
    df["date"] = df["date"].astype(str)
    df["composition"] = df["composition"].astype(str)
    return df.sort_values("date", kind="stable").reset_index(drop=True)


def load_journal(path: Path | str = JOURNAL_PATH) -> pd.DataFrame:
    """Живият журнал (празна рамка с верните колони при липсващ файл)."""
    src = Path(path)
    if not src.exists():
        return _normalize_journal(pd.DataFrame(columns=journal_columns()))
    return _normalize_journal(pd.read_csv(src))


def append_journal(
    lens_reports: dict,
    composite: Optional[float],
    *,
    today: Optional[date] = None,
    path: Path | str = JOURNAL_PATH,
    catalog: Optional[dict] = None,
    temp: Optional[dict] = None,
) -> pd.DataFrame:
    """Записва ЕДИН ред за днес в живия журнал. Идемпотентен по дата.

    Втори пуск в същия ден ЗАМЕНЯ реда, не добавя втори — иначе WoW делтата би
    сравнявала днес с днес и би показвала нула при всяко повторение.

    `temp` е изходът на `analysis.temperature.temperature()`; без него редът
    носи празна температура (честно „не е мерено"), не фалшива нула. Тагът
    `composition` се сменя САМ с новите полярности — очаквано по дизайн.
    Тензията (`k1_ratio`) не иска аргумент: тя се смята от самите доклади.
    """
    today = date.today() if today is None else today
    row = _row_from_reports(lens_reports, composite, ROW_LIVE, temp=temp)
    row.pop("row_type")
    row.pop("temp_hot", None)     # кой гори живее в решетката, не в журнала
    row["date"] = today.isoformat()
    row["composition"] = composition_tag(catalog)

    journal = load_journal(path)
    journal = journal[journal["date"] != row["date"]]
    journal = pd.concat([journal, pd.DataFrame([row])], ignore_index=True)
    journal = _normalize_journal(journal)

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    journal.to_csv(out, index=False, encoding="utf-8", lineterminator="\n")
    return journal


def wow_delta(journal_df: Optional[pd.DataFrame]) -> Optional[dict]:
    """Какво се смени спрямо ПРЕДИШНИЯ запис с ДРУГА дата.

    Връща `{date, prev_date, composite_delta, lens_deltas, composition_changed}`
    или None при < 2 записа (първият пуск няма с какво да се сравни).
    """
    if journal_df is None or len(journal_df) < 2:
        return None
    df = _normalize_journal(journal_df.copy())
    cur = df.iloc[-1]
    prev_rows = df[df["date"] != cur["date"]]
    if prev_rows.empty:
        return None
    prev = prev_rows.iloc[-1]

    def _delta(a: Any, b: Any, digits: int = 1) -> Optional[float]:
        if pd.isna(a) or pd.isna(b):
            return None
        return round(float(a) - float(b), digits)

    return {
        "date": str(cur["date"]),
        "prev_date": str(prev["date"]),
        "composite_delta": _delta(cur["composite"], prev["composite"]),
        "lens_deltas": {
            lens: _delta(cur[f"score_{lens}"], prev[f"score_{lens}"])
            for lens in _lens_order()
        },
        "composition_changed": str(cur["composition"]) != str(prev["composition"]),
    }


# ═════════════════════════════════════════════════════════════════════════════
# ЧЕТЕНЕ НА РЕШЕТКАТА (за лицето и за context-а)
# ═════════════════════════════════════════════════════════════════════════════

def quarters(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Само реконструираните тримесечни редове (без живата точка)."""
    if df is None or df.empty:
        return _empty_history()
    return df[df["row_type"] == ROW_QUARTER]


def history_stats(df: Optional[pd.DataFrame]) -> Optional[dict]:
    """Контекстът от реконструкцията: percentile на живото, min/max, обхват.

    Percentile-ът е спрямо ТРИМЕСЕЧНИТЕ редове — живата точка не се сравнява
    със себе си.
    """
    if df is None or df.empty:
        return None
    q = quarters(df).dropna(subset=["composite"])
    if q.empty:
        return None

    live_rows = df[df["row_type"] == ROW_LIVE]
    current = None
    if not live_rows.empty and pd.notna(live_rows["composite"].iloc[-1]):
        current = float(live_rows["composite"].iloc[-1])

    comp = q["composite"].astype(float)
    imin, imax = comp.idxmin(), comp.idxmax()
    pct = None
    if current is not None:
        pct = round(float((comp < current).sum()) / len(comp) * 100, 1)

    return {
        "current": current,
        "percentile": pct,
        "n_quarters": int(len(comp)),
        "first_date": q.index[0].strftime("%Y-%m-%d"),
        "last_date": q.index[-1].strftime("%Y-%m-%d"),
        "min_date": imin.strftime("%Y-%m-%d"),
        "min_value": round(float(comp.loc[imin]), 1),
        "max_date": imax.strftime("%Y-%m-%d"),
        "max_value": round(float(comp.loc[imax]), 1),
    }


def yearly_table(df: Optional[pd.DataFrame]) -> list[dict]:
    """[{year, mean_composite, n}] по ТРИМЕСЕЧНИТЕ редове — компактният филм."""
    q = quarters(df).dropna(subset=["composite"])
    if q.empty:
        return []
    out: list[dict] = []
    for year, part in q.groupby(q.index.year):
        out.append({
            "year": int(year),
            "mean_composite": round(float(part["composite"].astype(float).mean()), 1),
            "n": int(len(part)),
        })
    return out
