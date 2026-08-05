"""
config.py
=========
Конфигурация за Japan Macro Dashboard (INIT-26, пети член на макро фамилията).
Съдържа API endpoints, тегла за composite score, прагове за режими и др.

Фамилният стандарт: bg-macro-dashboard (двигател: робастен z / 10г / MAD).
JP-специфики: дълга история без данни-качествен разлом (HISTORY_START 1955),
японски епохи (дефлационната ера · Абеномиката · пост-2022 инфлационния режим),
отделен йена-слой над композита (мандат INIT-26 v1).
"""
from pathlib import Path
import os

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

# ─── API ключове ─────────────────────────────────────────────────────────────
# FRED е основният доставчик (~70% от таблото). Ключовете се четат от env,
# с .env файла в корена като fallback ЗА ВСЕКИ ключ поотделно — иначе ключ,
# дошъл от средата, би заглушил четенето на другите от .env.
def _env_file_value(name: str) -> str:
    _env = BASE_DIR / ".env"
    if not _env.exists():
        return ""
    for _line in _env.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line.startswith(f"{name}="):
            return _line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


FRED_API_KEY = os.environ.get("FRED_API_KEY", "") or _env_file_value("FRED_API_KEY")

# e-Stat (фаза 4 — инфлационната леща). Регистрацията е безплатна; без ключ
# e-Stat сериите просто не се фетчват и лещата остава без данни (ренормализация).
ESTAT_APP_ID = os.environ.get("ESTAT_APP_ID", "") or _env_file_value("ESTAT_APP_ID")

# ─── MOF стабилни URL-и (йена-слоят, фаза 3) ─────────────────────────────────
# Живо проверени 2026-08-05 (скаутът на INIT-26):
#   · JGB кривата — daily, колони Date,1Y…40Y, история от 1974-09-24
#   · Седмичните портфейлни потоци — Shift-JIS! Английският път (/english/…)
#     връща 404 — ползва се JP-пътят.
MOF_JGB_HISTORICAL_CSV = (
    "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/"
    "historical/jgbcme_all.csv"
)
MOF_JGB_CURRENT_CSV = (
    "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv"
)
MOF_WEEKLY_FLOWS_CSV = (
    "https://www.mof.go.jp/policy/international_policy/reference/"
    "itn_transactions_in_securities/week.csv"
)

# COT JPY net — вече живее в data-core (1051 седмични obs от 2006-06-13).
# Преизползва се, не се фетчва наново (мандат INIT-26 раздел 4).
COT_JPY_CANONICAL = Path(r"C:\Projects\data-core\data\canonical\cot_jpy_net.json")

# ─── Кеш ─────────────────────────────────────────────────────────────────────
CACHE_TTL_HOURS_DEFAULT = 12
CACHE_TTL_DAYS_BY_SCHEDULE = {
    "weekly":     3,
    "monthly":   10,
    "quarterly": 30,
    "annually":  90,
}

# ─── Исторически прозорци ────────────────────────────────────────────────────
# За Япония НЯМА данни-качествен разлом като българската хиперинфлация (1997).
# Историята се пази дълга нарочно: балонната ера от 80-те е бъдещият приемен
# гейт на температурния слой (фаза 6), а персентилният fallback на скоринга
# стъпва на пълната история.
HISTORY_START = "1955-01-01"
ANALOG_HISTORY_START = "1955-01-01"

# ─── Модулни тегла за Composite Macro Score (JP v1, мандат INIT-26) ──────────
# Шест скорирани лещи: fiscal е context-only в v1 (FRED дава само годишни
# IMF WEO данни до 2023 — 10 точки за 10-годишен z е нечестно; подписано
# решение №1 от мандата). Йена-слоят е ОТДЕЛЕН, наблюдателен — не е леща и
# не влиза тук (решение №2).
#
# Разпределение по фамилния дух: инфлация и растеж водещи по 0.20, четирите
# структурни лещи РАВНИ по 0.15. Сумата е точно 1.0 (пази се от тест).
# ⚠ До фаза 4 (e-Stat) инфлационната леща е без данни → score=None →
# композитът се ренормализира по останалите пет. Това е декларирано, не скрито.
MODULE_WEIGHTS = {
    "inflation": 0.20,
    "growth":    0.20,
    "labor":     0.15,
    "credit":    0.15,
    "external":  0.15,
    "property":  0.15,
}

# ─── Macro режими ────────────────────────────────────────────────────────────
MACRO_REGIMES = [
    (80, "ЕКСПАНЗИОНЕН",   "#00c853"),
    (65, "ЗДРАВ",          "#69f0ae"),
    (50, "СМЕСЕН",         "#ffd600"),
    (35, "ВЛОШАВАЩ СЕ",    "#ff6d00"),
    (0,  "РЕЦЕСИОНЕН",     "#d50000"),
]

# ─── Лещови ленти на СЪЩАТА 0–100 скала ──────────────────────────────────────
# Режимното име носи КОМПОЗИТЪТ; отделната леща носи само силата си
# (фамилният одит 24.07 §4.4).
LENS_BANDS = [
    (80, "МНОГО СИЛНО"),
    (65, "СИЛНО"),
    (50, "ОКОЛО НОРМАТА"),
    (35, "СЛАБО"),
    (0,  "МНОГО СЛАБО"),
]

# ─── Cross-reference ключове ─────────────────────────────────────────────────
# Инфлационните ключове пристигат с фаза 4 (e-Stat); дотогава None и
# консуматорите са длъжни да проверяват.
CORE_DEFLATOR_KEY = None       # фаза 4: JP core CPI ex fresh food (BOJ мярката)
HEADLINE_DEFLATOR_KEY = None   # фаза 4: JP headline CPI
NOMINAL_10Y_KEY = "JP_10Y"

# ─── Един речник за лещите (ФОРМА-КАНОН) ─────────────────────────────────────
LENS_NAMES_BG = {
    "growth":    "Растеж",
    "inflation": "Инфлация",
    "labor":     "Пазар на труда",
    "credit":    "Кредит и финанси",
    "external":  "Външен сектор",
    "property":  "Имоти",
}

LENS_BADGES_BG = {
    "growth":    "растеж",
    "inflation": "инфлация",
    "labor":     "труд",
    "credit":    "кредит",
    "external":  "външен",
    "property":  "имоти",
}

LENS_SUBJECTS_BG = {
    "growth":    "растежът",
    "inflation": "инфлацията",
    "labor":     "пазарът на труда",
    "credit":    "кредитът",
    "external":  "външният сектор",
    "property":  "имотният пазар",
}

# ─── Цветовете на лещите — ЕДИН източник (фамилен мандат №43) ────────────────
LENS_LINE_COLORS = {
    "growth":    "#60a5fa",
    "inflation": "#f87171",
    "labor":     "#fbbf24",
    "credit":    "#c084fc",
    "external":  "#34d399",
    "property":  "#fb923c",
}

LENS_BADGE_COLORS = {
    "growth":    ("#1e3a5f", "#60a5fa"),
    "inflation": ("#3f1515", "#f87171"),
    "labor":     ("#3f2a00", "#fbbf24"),
    "credit":    ("#2d1f4a", "#c084fc"),
    "external":  ("#0f3030", "#34d399"),
    "property":  ("#3a2408", "#fb923c"),
}

# ─── Контекстната серия — наблюдение ИЗВЪН композита (фамилен мандат №48) ────
CONTEXT_BADGE_BG = "контекст"
CONTEXT_LINE_COLOR = "#8892a4"
CONTEXT_BADGE_COLORS = ("#252836", "#8892a4")
CONTEXT_SCORE_NOTE = "контекстна серия — не влиза в композита"

# ─── Йена-слоят (мандат INIT-26, решение №2) ─────────────────────────────────
# Отделен наблюдателен слой НАД композита — като температурата и тензията.
# Диференциаторът е за гледане, не за осредняване. Един източник за името,
# цвета и обяснението (ФОРМА-КАНОН духа).
YEN_LAYER_NAME_BG = "Йена-слоят"
YEN_LAYER_BADGE_BG = "йена"
YEN_LAYER_LINE_COLOR = "#e879f9"
YEN_LAYER_BADGE_COLORS = ("#3a0f3f", "#e879f9")
YEN_LAYER_NOTE = (
    "наблюдателен слой над композита — лихви, финансиране, позициониране, "
    "carry; не влиза в score-а"
)

# ─── Котвените зони на инфлацията ────────────────────────────────────────────
# BOJ целта е 2% — котвата се пренася концептуално от фамилията (фаза 4 ще я
# събуди заедно с e-Stat CPI сериите).
INFLATION_ANCHOR_COLORS = {
    "green":  "#22c55e",
    "yellow": "#ffd600",
    "red":    "#ef4444",
}

# ─── Епохните граници — ЕДИН източник (фамилен мандат №55) ───────────────────
# Границите са ДЕКЛАРАЦИЯ (политика), НЕ калибровка. Японските епохи (мандат
# INIT-26 раздел 5) са съвсем различни от всички досегашни членове:
#   · `deflation` 1995-2012 — дефлационната ера / изгубените десетилетия:
#     нулеви лихви, падащи цени, счупена трансмисия. Началото е след пукането
#     на балона и банковата криза от началото на 90-те.
#   · `abenomics` 2013-2019 — трите стрели: QQE (04.2013), NIRP (2016), YCC
#     (09.2016). Рефлационният експеримент преди ковид.
#   · `current` 2022-… — пост-2022 инфлационният режим: първата устойчива
#     инфлация от 30 години, изход от YCC/NIRP, нормализация на BOJ. ОТВОРЕНА
#     отдясно (None = „до последното наблюдение").
# Между `abenomics` и `current` нарочно зеят 2020-21: ковид годините не са
# нито рефлационен експеримент, нито инфлационен режим и не бива да
# замърсяват ничия медиана.
EPOCHS = {
    "deflation": ("1995-01-01", "2012-12-31"),
    "abenomics": ("2013-01-01", "2019-12-31"),
    "current":   ("2022-01-01", None),
}

EPOCH_NAMES_BG = {
    "deflation": "дефлационната",
    "abenomics": "абеномиката",
    "current":   "текущата",
}

# ─── Първоизточник: линк на всяко име (ФОРМА-КАНОН) ──────────────────────────
FRED_SERIES_URL = "https://fred.stlouisfed.org/series/{series_id}"
MOF_JGB_PAGE = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/index.htm"
MOF_FLOWS_PAGE = (
    "https://www.mof.go.jp/policy/international_policy/reference/"
    "itn_transactions_in_securities/index.html"
)

# ─── Застояло наблюдение: 2× очаквания ритъм на публикуване ──────────────────
STALE_AFTER_MONTHS = {
    "daily":      1,
    "weekly":     1,
    "monthly":    2,
    "quarterly":  6,
    "annually":  24,
}
