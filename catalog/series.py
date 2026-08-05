"""
catalog/series.py
=================
Каталог на сериите за Japan Macro Dashboard (INIT-26 v1).

ДЕКЛАРАЦИИ: какво се мери, откъде идва, как се трансформира и в коя леща
живее. Как се СЪДИ (полярност) е в catalog/polarity.py — нарочно отделно.

Всеки FRED тикер тук е ЖИВО ПРОВЕРЕН на 2026-08-05 (скаутът на INIT-26 през
FRED API): фреквенция, начало на историята, последно наблюдение. Замразените
OECD-MEI тикери (JP CPI 2021-06 · central-bank rate 2023-12 · M2 2017 ·
housing starts 2023-11 · CLI 2024-01) НЕ са тук — вж. мандата, раздел 2.

Фази по мандата:
  · v1 (тази) — FRED: growth / labor / credit / external / property скорирани;
    fiscal context-only; йена-слоят като context серии с таг "yen_layer"
  · фаза 3 — MOF CSV (JGB крива, седмични потоци) + COT от data-core
  · фаза 4 — e-Stat: инфлационната леща (headline + core ex fresh food)
  · фаза 5 — BOJ zip: Tankan, CGPI, BoP
"""
from typing import Any

ALLOWED_SOURCES = {"fred", "mof", "estat", "boj", "derived"}
ALLOWED_REGIONS = {"JP", "US"}
ALLOWED_LENSES = {"growth", "inflation", "labor", "credit", "external", "property"}
ALLOWED_TRANSFORMS = {
    "level", "yoy_pct", "mom_pct", "qoq_pct", "z_score", "first_diff",
    "roll4q_mean", "yoy_roll4",
}
ALLOWED_SCORING_MODES = {"level", "momentum"}
ALLOWED_SCHEDULES = {"daily", "weekly", "monthly", "quarterly", "annually"}

SERIES_CATALOG: dict[str, dict[str, Any]] = {

    # ─── РАСТЕЖ ──────────────────────────────────────────────────────────────

    "JP_RGDP": {
        "source": "fred",
        "id": "JPNRGDPEXP",
        "region": "JP",
        "name_bg": "Реален БВП (г/г)",
        "name_en": "Real GDP (YoY)",
        "lens": ["growth"],
        "peer_group": "gdp",
        "tags": ["headline"],
        "transform": "yoy_pct",
        "is_rate": False,
        "historical_start": "1994-01-01",
        "release_schedule": "quarterly",
        "typical_release": "mid_quarter",
        "revision_prone": True,
        "narrative_hint": "Cabinet Office, 1994→. Първата оценка излиза ~6 "
                          "седмици след тримесечието и се ревизира осезаемо — "
                          "японският БВП е известен с големи ревизии.",
    },
    "JP_INDPRO": {
        "source": "fred",
        "id": "JPNPRINTO01GYSAM",
        "region": "JP",
        "name_bg": "Промишлено производство (г/г)",
        "name_en": "Industrial Production (YoY)",
        "lens": ["growth"],
        "peer_group": "production",
        "tags": ["headline"],
        "transform": "level",   # серията Е годишен темп (growth rate, SA)
        "is_rate": True,
        "historical_start": "1956-01-01",
        "release_schedule": "monthly",
        "typical_release": "end_month",
        "revision_prone": True,
        "narrative_hint": "METI, 1956→. Японската индустрия е експортният "
                          "мотор — серията диша с глобалния цикъл и йената.",
    },
    "JP_RETAIL": {
        "source": "fred",
        "id": "JPNSLRTTO01GYSAM",
        "region": "JP",
        "name_bg": "Търговия на дребно (обем, г/г)",
        "name_en": "Retail Trade Volume (YoY)",
        "lens": ["growth"],
        "peer_group": "consumption",
        "tags": [],
        "transform": "level",   # серията Е годишен темп (growth rate, SA)
        "is_rate": True,
        "historical_start": "1956-01-01",
        "release_schedule": "monthly",
        "typical_release": "end_month",
        "revision_prone": False,
        "narrative_hint": "Домакинското потребление е слабото звено на "
                          "японския цикъл — реалните заплати го решават.",
    },

    # ─── ИНФЛАЦИЯ (фаза 4: e-Stat — FRED няма жив месечен JP CPI) ────────────
    # Таблица 0003427113 (CPI 2020-база, 1970→, живо проверена 05.08.2026).
    # Индексът се фетчва суров (tab=1), г/г темпът се смята в уреда — не
    # преписваме готовата колона (tab=3), за да е една дисциплината на
    # трансформациите с останалите серии.

    "JP_CPI": {
        "source": "estat",
        "id": "0003427113?tab=1&cat01=0001&area=00000",
        "region": "JP",
        "name_bg": "Инфлация (CPI headline, г/г)",
        "name_en": "CPI All Items (YoY)",
        "lens": ["inflation"],
        "peer_group": "headline_inflation",
        "tags": ["headline"],
        "transform": "yoy_pct",
        "is_rate": False,
        "historical_start": "1970-01-01",
        "release_schedule": "monthly",
        "typical_release": "next_month",
        "revision_prone": False,
        "narrative_hint": "Пълната кошница — вкл. прясната храна, която "
                          "японската политика игнорира. Разликата headline−core "
                          "е шумът на времето и реколтата.",
    },
    "JP_CPI_CORE": {
        "source": "estat",
        "id": "0003427113?tab=1&cat01=0161&area=00000",
        "region": "JP",
        "name_bg": "Ядрена инфлация (без прясна храна, г/г)",
        "name_en": "CPI ex Fresh Food (YoY)",
        "lens": ["inflation"],
        "peer_group": "core_inflation",
        "tags": ["headline"],
        "transform": "yoy_pct",
        "is_rate": False,
        "historical_start": "1970-01-01",
        "release_schedule": "monthly",
        "typical_release": "next_month",
        "revision_prone": False,
        "narrative_hint": "МЯРКАТА НА BOJ — ядреният CPI в японския смисъл "
                          "(без прясна храна, С енергия). Целта от 2% се "
                          "мери точно срещу тази серия.",
    },

    # ─── ПАЗАР НА ТРУДА ──────────────────────────────────────────────────────

    "JP_UNRATE": {
        "source": "fred",
        "id": "LRUN64TTJPM156S",
        "region": "JP",
        "name_bg": "Безработица (15-64, SA)",
        "name_en": "Unemployment Rate 15-64 (SA)",
        "lens": ["labor"],
        "peer_group": "unemployment",
        "tags": ["headline"],
        "transform": "level",
        "is_rate": True,
        "historical_start": "1970-01-01",
        "release_schedule": "monthly",
        "typical_release": "end_month",
        "revision_prone": False,
        "narrative_hint": "Структурно ниска (~2.5%) — демографията стяга "
                          "пазара постоянно. Малки движения значат много; "
                          "3% в Япония е каквото 6% е другаде.",
    },
    "JP_EARNINGS_MFG": {
        "source": "fred",
        "id": "LCEAMN01JPM659S",
        "region": "JP",
        "name_bg": "Заплати в промишлеността (г/г)",
        "name_en": "Hourly Earnings, Manufacturing (YoY)",
        "lens": ["labor"],
        "peer_group": "wages",
        "tags": [],
        # ⚠ ФАЗА-2 ПРОВЕРКА: OECD-MEI суфиксът 659 подсказва вече изчислен
        # годишен темп; ако живият fetch върне индекс (~стотици), transform
        # става yoy_pct. Проверява се срещу реалните стойности.
        "transform": "level",
        "is_rate": True,
        "historical_start": "1956-01-01",
        "release_schedule": "monthly",
        "typical_release": "next_month",
        "revision_prone": True,
        "narrative_hint": "Заплатният импулс е ОСТА на японската нормализация: "
                          "BOJ чака заплати→цени спирала, шунто договорките "
                          "са годишният ѝ пулс.",
    },

    # ─── КРЕДИТ И ФИНАНСИ ────────────────────────────────────────────────────

    "JP_CREDIT_GDP_NFC": {
        "source": "fred",
        "id": "QJPNAM770A",
        "region": "JP",
        "name_bg": "Кредит към нефинансови компании (% от БВП, г/г темп)",
        "name_en": "Credit to NFCs, % of GDP (YoY)",
        "lens": ["credit"],
        "peer_group": "credit_depth",
        "tags": [],
        "transform": "yoy_pct",
        "is_rate": False,
        "historical_start": "1964-10-01",
        "release_schedule": "quarterly",
        "typical_release": "next_quarter",
        "revision_prone": True,
        "narrative_hint": "BIS, 1964→ — покрива балонната ера и цялото "
                          "разлистване след нея. Японският корпоративен "
                          "сектор е нетен спестител от 90-те насам.",
    },
    "JP_CREDIT_GDP_HH": {
        "source": "fred",
        "id": "QJPHAM770A",
        "region": "JP",
        "name_bg": "Кредит към домакинствата (% от БВП, г/г темп)",
        "name_en": "Credit to Households, % of GDP (YoY)",
        "lens": ["credit"],
        "peer_group": "credit_depth",
        "tags": [],
        "transform": "yoy_pct",
        "is_rate": False,
        "historical_start": "1964-10-01",
        "release_schedule": "quarterly",
        "typical_release": "next_quarter",
        "revision_prone": True,
        "narrative_hint": "Двата кредитни крака (NFC + домакинства) са ЕДИН "
                          "шок — една peer-група, за да не се брои двойно "
                          "(фамилният принцип от външния сектор на BG).",
    },
    "JP_10Y": {
        "source": "fred",
        "id": "IRLTLT01JPM156N",
        "region": "JP",
        "name_bg": "10-годишна ДЦК доходност (JGB)",
        "name_en": "10Y JGB Yield",
        "lens": ["credit"],
        "peer_group": "yields",
        "tags": ["headline"],
        "transform": "level",
        "is_rate": True,
        "historical_start": "1989-01-01",
        "release_schedule": "monthly",
        "typical_release": "mid_month",
        "revision_prone": False,
        "narrative_hint": "Три десетилетия под похлупак (ZIRP → QQE → YCC); "
                          "пост-2024 кривата се освобождава. Дневната крива "
                          "1974→ идва от MOF в йена-слоя.",
    },

    # ─── ВЪНШЕН СЕКТОР ───────────────────────────────────────────────────────

    "JP_TRADE_BAL": {
        "source": "fred",
        "id": "XTNTVA01JPM664S",
        "region": "JP",
        "name_bg": "Търговски баланс (стоки, SA)",
        "name_en": "Trade Balance, Goods (SA)",
        "lens": ["external"],
        "peer_group": "external_balance",
        "tags": ["headline"],
        "transform": "level",
        "is_rate": False,
        "historical_start": "1955-01-01",
        "release_schedule": "monthly",
        "typical_release": "next_month",
        "revision_prone": False,
        "narrative_hint": "Енергийният внос прави баланса заложник на петрола "
                          "И на йената едновременно — слаба йена + скъп петрол "
                          "= двоен удар (2022 прецедентът).",
    },
    "JP_EXPORTS": {
        "source": "fred",
        "id": "XTEXVA01JPM667S",
        "region": "JP",
        "name_bg": "Износ (стойност, г/г)",
        "name_en": "Exports Value (YoY)",
        "lens": ["external"],
        "peer_group": "external_balance",
        "tags": [],
        "transform": "yoy_pct",
        "is_rate": False,
        "historical_start": "1957-01-01",
        "release_schedule": "monthly",
        "typical_release": "next_month",
        "revision_prone": False,
        "narrative_hint": "Износът и балансът са един шок → една peer-група. "
                          "Стойностният износ расте и от слаба йена — обемният "
                          "прочит идва с BOJ BoP (фаза 5).",
    },

    # (фаза 5) Текущата сметка от BOJ BoP — FRED тримесечната CA е заложник
    # на годишния OECD ревизионен цикъл (stale 2024Q4, скаутът 05.08).
    "JP_CA": {
        "source": "boj",
        "id": "bp:BPBP6JYNCB",
        "region": "JP",
        "name_bg": "Текуща сметка (нето, месечно)",
        "name_en": "Current Account Net Balance (monthly)",
        "lens": ["external"],
        "peer_group": "external_balance",
        "tags": [],
        "transform": "level",
        "is_rate": False,
        "historical_start": "1996-01-01",
        "release_schedule": "monthly",
        "typical_release": "next_month",
        "revision_prone": True,
        "narrative_hint": "Търговията отслабна, но доходът от чуждите активи "
                          "(първичният доход) държи сметката в излишък — "
                          "Япония е рентиер, не вече само износител. "
                          "100 млн йени.",
    },

    # ─── ИМОТИ ───────────────────────────────────────────────────────────────

    "JP_RPPI": {
        "source": "fred",
        "id": "QJPN628BIS",
        "region": "JP",
        "name_bg": "Цени на жилищата (BIS RPPI, г/г)",
        "name_en": "Residential Property Prices (BIS, YoY)",
        "lens": ["property"],
        "peer_group": "prices",
        "tags": ["headline"],
        "transform": "yoy_pct",
        "is_rate": False,
        "historical_start": "1955-01-01",
        "release_schedule": "quarterly",
        "typical_release": "next_quarter",
        "revision_prone": True,
        "narrative_hint": "1955→ — вижда балона от 80-те И трите десетилетия "
                          "спад след него. v1 лещата е само цени (мандат, "
                          "решение №4); housing starts идват с e-Stat.",
    },

    # ─── ДЪРЖАВНИ ФИНАНСИ — CONTEXT-ONLY (мандат, решение №1) ────────────────
    # FRED дава само годишни IMF WEO данни (до 2023). 10 точки за 10-годишен
    # робастен z е нечестно — наблюдение, не глас в композита.

    "JP_GOV_DEBT": {
        "source": "fred",
        "id": "GGGDTAJPA188N",
        "region": "JP",
        "name_bg": "Държавен дълг (% от БВП)",
        "name_en": "General Government Gross Debt (% of GDP)",
        "lens": [],
        "context_only": True,
        "peer_group": "context",
        "tags": ["fiscal_context"],
        "transform": "level",
        "is_rate": True,
        "historical_start": "1980-01-01",
        "release_schedule": "annually",
        "typical_release": "irregular",
        "revision_prone": True,
        "narrative_hint": "~250% от БВП — най-високият в развития свят, но "
                          "почти изцяло в йени и до голяма степен у BOJ. "
                          "Лихвената нормализация го прави отново въпрос.",
    },
    "JP_GOV_BAL": {
        "source": "fred",
        "id": "GGNLBAJPA188N",
        "region": "JP",
        "name_bg": "Бюджетно салдо (% от БВП)",
        "name_en": "General Government Net Lending/Borrowing (% of GDP)",
        "lens": [],
        "context_only": True,
        "peer_group": "context",
        "tags": ["fiscal_context"],
        "transform": "level",
        "is_rate": True,
        "historical_start": "1980-01-01",
        "release_schedule": "annually",
        "typical_release": "irregular",
        "revision_prone": True,
        "narrative_hint": "Хроничен дефицит от 90-те; годишният ритъм на IMF "
                          "WEO е причината фискалът да е контекст, не леща "
                          "(мандат INIT-26, решение №1).",
    },

    # ─── ИНФЛАЦИОНЕН КОНТЕКСТ ────────────────────────────────────────────────

    "JP_CGPI": {
        "source": "boj",
        "id": "cgpi:PRCG20_2200000000",
        "region": "JP",
        "name_bg": "Производствени цени (PPI/CGPI, г/г)",
        "name_en": "Producer Price Index (CGPI, YoY)",
        "lens": [],
        "context_only": True,
        "peer_group": "context",
        "tags": [],
        "transform": "yoy_pct",
        "is_rate": False,
        "historical_start": "2020-01-01",
        "release_schedule": "monthly",
        "typical_release": "mid_month",
        "revision_prone": True,
        "narrative_hint": "Тръбата ПРЕДИ потребителските цени — вносните "
                          "разходи (йена + суровини) удрят първо тук. "
                          "Flat файлът носи само 2020-базата (2020→) — "
                          "контекст, не глас в лещата.",
    },

    "JP_CPI_CORECORE": {
        "source": "estat",
        "id": "0003427113?tab=1&cat01=0178&area=00000",
        "region": "JP",
        "name_bg": "Core-core инфлация (без прясна храна и енергия, г/г)",
        "name_en": "CPI ex Fresh Food & Energy (YoY)",
        "lens": [],
        "context_only": True,
        "peer_group": "context",
        "tags": [],
        "transform": "yoy_pct",
        "is_rate": False,
        "historical_start": "1970-01-01",
        "release_schedule": "monthly",
        "typical_release": "next_month",
        "revision_prone": False,
        "narrative_hint": "Западната ядрена мярка — без храна И енергия. "
                          "Разликата core−corecore показва колко от японската "
                          "инфлация е внесена енергия (и значи: йена).",
    },

    # ─── КРЕДИТЕН КОНТЕКСТ ───────────────────────────────────────────────────

    "JP_CREDIT_GDP_PNF": {
        "source": "fred",
        "id": "QJPPAM770A",
        "region": "JP",
        "name_bg": "Кредит към частния нефинансов сектор (% от БВП)",
        "name_en": "Credit to Private Non-Financial Sector (% of GDP)",
        "lens": [],
        "context_only": True,
        "peer_group": "context",
        "tags": [],
        "transform": "level",
        "is_rate": True,
        "historical_start": "1964-10-01",
        "release_schedule": "quarterly",
        "typical_release": "next_quarter",
        "revision_prone": True,
        "narrative_hint": "Сборът на двата скорирани крака (NFC + домакинства) "
                          "— контекст, за да не се брои същият шок трети път.",
    },

    # ─── ЙЕНА-СЛОЯТ (мандат, решение №2): context серии с таг yen_layer ──────
    # Отделен наблюдателен слой НАД композита. analysis/yen_segment.py (фаза 3)
    # чете сериите по тага. Водещият блок е възелът на carry unwind:
    # позициониране × лихвена траектория (дрилът USD/JPY 05.08).

    "JP_CALL_RATE": {
        "source": "fred",
        "id": "IRSTCI01JPM156N",
        "region": "JP",
        "name_bg": "Overnight call rate (некол., месечен)",
        "name_en": "Uncollateralized Overnight Call Rate",
        "lens": [],
        "context_only": True,
        "peer_group": "context",
        "tags": ["yen_layer", "rates"],
        "transform": "level",
        "is_rate": True,
        "historical_start": "1985-07-01",
        "release_schedule": "monthly",
        "typical_release": "next_month",
        "revision_prone": False,
        "narrative_hint": "Политическата лихва на практика. ЖИВ тикер — хваща "
                          "целия 2024-26 цикъл на покачване (замразеният "
                          "IRSTCB01JPM156N спира 2023-12 и НЕ се ползва).",
    },
    "JP_TIBOR3M": {
        "source": "fred",
        "id": "IR3TIB01JPM156N",
        "region": "JP",
        "name_bg": "TIBOR 3м",
        "name_en": "3-Month Interbank Rate (TIBOR)",
        "lens": [],
        "context_only": True,
        "peer_group": "context",
        "tags": ["yen_layer", "rates"],
        "transform": "level",
        "is_rate": True,
        "historical_start": "2002-04-01",
        "release_schedule": "monthly",
        "typical_release": "next_month",
        "revision_prone": False,
        "narrative_hint": "Краткосрочното йеново финансиране — цената на "
                          "funding крака на carry трейда.",
    },
    "JP_USDJPY": {
        "source": "fred",
        "id": "DEXJPUS",
        "region": "JP",
        "name_bg": "USD/JPY (спот)",
        "name_en": "USD/JPY Spot",
        "lens": [],
        "context_only": True,
        "peer_group": "context",
        "tags": ["yen_layer", "fx"],
        "transform": "level",
        "is_rate": False,
        "historical_start": "1971-01-01",
        "release_schedule": "daily",
        "typical_release": "daily",
        "revision_prone": False,
        "narrative_hint": "Директната серия, която организмът нямаше — дрилът "
                          "05.08 четеше двойката през UUP×FXY прокси-та. "
                          "1971→, дневна.",
    },
    "JP_REER": {
        "source": "fred",
        "id": "RBJPBIS",
        "region": "JP",
        "name_bg": "Реален ефективен курс на йената (BIS, broad)",
        "name_en": "Real Broad Effective Exchange Rate (BIS)",
        "lens": [],
        "context_only": True,
        "peer_group": "context",
        "tags": ["yen_layer", "fx"],
        "transform": "level",
        "is_rate": False,
        "historical_start": "1994-01-01",
        "release_schedule": "monthly",
        "typical_release": "mid_month",
        "revision_prone": False,
        "narrative_hint": "Колко евтина е йената РЕАЛНО — множествените "
                          "десетилетни дъна тук са горивото на carry позицията "
                          "и на туристическия бум едновременно.",
    },
    "JP_BOJ_ASSETS": {
        "source": "fred",
        "id": "JPNASSETS",
        "region": "JP",
        "name_bg": "Баланс на BOJ (общо активи)",
        "name_en": "Bank of Japan Total Assets",
        "lens": [],
        "context_only": True,
        "peer_group": "context",
        "tags": ["yen_layer", "funding"],
        "transform": "level",
        "is_rate": False,
        "historical_start": "1998-04-01",
        "release_schedule": "monthly",
        "typical_release": "next_month",
        "revision_prone": False,
        "narrative_hint": "Източникът на глобална йенова ликвидност — QT "
                          "темпото тук е другата половина на нормализацията, "
                          "не само лихвата.",
    },
    "JP_NIKKEI": {
        "source": "fred",
        "id": "NIKKEI225",
        "region": "JP",
        "name_bg": "Nikkei 225",
        "name_en": "Nikkei 225",
        "lens": [],
        "context_only": True,
        "peer_group": "context",
        "tags": ["yen_layer", "markets"],
        "transform": "level",
        "is_rate": False,
        "historical_start": "1949-01-01",
        "release_schedule": "daily",
        "typical_release": "daily",
        "revision_prone": False,
        "narrative_hint": "Пазарният барометър — исторически диша обратно на "
                          "йената (слаба йена = експортни печалби); режимът "
                          "на тази връзка е сам по себе си наблюдение.",
    },
    "US_2Y": {
        "source": "fred",
        "id": "DGS2",
        "region": "US",
        "name_bg": "US 2-годишна доходност",
        "name_en": "US 2Y Treasury Yield",
        "lens": [],
        "context_only": True,
        "peer_group": "context",
        "tags": ["yen_layer", "carry_parent"],
        "transform": "level",
        "is_rate": True,
        "historical_start": "1976-06-01",
        "release_schedule": "daily",
        "typical_release": "daily",
        "revision_prone": False,
        "narrative_hint": "Родител на carry диференциала US−JP 2Y (derived, "
                          "фаза 3) — късият край носи carry сметката.",
    },
    "US_10Y": {
        "source": "fred",
        "id": "DGS10",
        "region": "US",
        "name_bg": "US 10-годишна доходност",
        "name_en": "US 10Y Treasury Yield",
        "lens": [],
        "context_only": True,
        "peer_group": "context",
        "tags": ["yen_layer", "carry_parent"],
        "transform": "level",
        "is_rate": True,
        "historical_start": "1962-01-01",
        "release_schedule": "daily",
        "typical_release": "daily",
        "revision_prone": False,
        "narrative_hint": "Родител на диференциала US−JP 10Y (derived, фаза 3) "
                          "— дългият край движи хеджираните облигационни "
                          "потоци на японските институции.",
    },

    # ─── MOF: JGB кривата (daily, 1974→) + седмичните потоци (2005→) ─────────
    # Двата стабилни CSV-а, живо проверени 05.08 (мандат, раздел 4).

    "JP_JGB_2Y": {
        "source": "mof",
        "id": "jgb:2Y",
        "region": "JP",
        "name_bg": "2-годишна JGB доходност (дневна)",
        "name_en": "2Y JGB Yield (daily)",
        "lens": [],
        "context_only": True,
        "peer_group": "context",
        "tags": ["yen_layer", "rates"],
        "transform": "level",
        "is_rate": True,
        "historical_start": "1974-09-24",
        "release_schedule": "daily",
        "typical_release": "daily",
        "revision_prone": False,
        "narrative_hint": "Късият край на кривата — най-чистото пазарно "
                          "четене на BOJ траекторията; родител на carry "
                          "диференциала US−JP 2Y.",
    },
    "JP_JGB_10Y_D": {
        "source": "mof",
        "id": "jgb:10Y",
        "region": "JP",
        "name_bg": "10-годишна JGB доходност (дневна, MOF)",
        "name_en": "10Y JGB Yield (daily, MOF)",
        "lens": [],
        "context_only": True,
        "peer_group": "context",
        "tags": ["yen_layer", "rates"],
        "transform": "level",
        "is_rate": True,
        "historical_start": "1974-09-24",
        "release_schedule": "daily",
        "typical_release": "daily",
        "revision_prone": False,
        "narrative_hint": "Дневният близнак на скорираната месечна JP_10Y "
                          "(FRED) — за диференциала срещу DGS10 и за кривата "
                          "в йена-слоя. 1974→ покрива и балонната ера.",
    },
    "JP_FLOWS_NONRES_EQ": {
        "source": "mof",
        "id": "flows:nonres_equity_net",
        "region": "JP",
        "name_bg": "Нерезиденти: нетни покупки на японски акции (седмично)",
        "name_en": "Non-residents' Net Purchases of Japanese Equities (weekly)",
        "lens": [],
        "context_only": True,
        "peer_group": "context",
        "tags": ["yen_layer", "flows"],
        "transform": "level",
        "is_rate": False,
        "historical_start": "2005-01-08",
        "release_schedule": "weekly",
        "typical_release": "weekly",
        "revision_prone": True,
        "narrative_hint": "Чуждият апетит за японски акции, седмица по "
                          "седмица (MOF ITS; 100 млн йени, + = покупка). "
                          "Горивото на Nikkei ралитата от чужбина.",
    },
    "JP_FLOWS_RES_LTDEBT": {
        "source": "mof",
        "id": "flows:res_ltdebt_net",
        "region": "JP",
        "name_bg": "Резиденти: нетни покупки на чужди дългосрочни облигации (седмично)",
        "name_en": "Residents' Net Purchases of Foreign Long-term Debt (weekly)",
        "lens": [],
        "context_only": True,
        "peer_group": "context",
        "tags": ["yen_layer", "flows"],
        "transform": "level",
        "is_rate": False,
        "historical_start": "2005-01-08",
        "release_schedule": "weekly",
        "typical_release": "weekly",
        "revision_prone": True,
        "narrative_hint": "Японските пари навън към чужда доходност — "
                          "класическият carry-съседен поток; обръщането му "
                          "към дома е репатрационният сигнал.",
    },

    # ─── DERIVED: carry диференциалите (фаза 3) ──────────────────────────────
    # Раждат се в sources/derived.py СЛЕД fetch-а; `id` е рецептата, не адрес.

    "JP_CARRY_2Y": {
        "source": "derived",
        "id": "US_2Y − JP_JGB_2Y (дневна пресечка)",
        "region": "JP",
        "name_bg": "Carry диференциал US−JP 2Y",
        "name_en": "US−JP 2Y Rate Differential",
        "lens": [],
        "context_only": True,
        "peer_group": "context",
        "tags": ["yen_layer", "carry"],
        "transform": "level",
        "is_rate": True,
        "historical_start": "1976-06-01",
        "release_schedule": "daily",
        "typical_release": "daily",
        "revision_prone": False,
        "narrative_hint": "Сметката на carry трейда в късия край — колкото "
                          "по-широк, толкова по-платен е шортът на йената; "
                          "стесняването е горивото на unwind епизодите.",
    },
    "JP_CARRY_10Y": {
        "source": "derived",
        "id": "US_10Y − JP_JGB_10Y_D (дневна пресечка)",
        "region": "JP",
        "name_bg": "Диференциал US−JP 10Y",
        "name_en": "US−JP 10Y Rate Differential",
        "lens": [],
        "context_only": True,
        "peer_group": "context",
        "tags": ["yen_layer", "carry"],
        "transform": "level",
        "is_rate": True,
        "historical_start": "1976-06-01",
        "release_schedule": "daily",
        "typical_release": "daily",
        "revision_prone": False,
        "narrative_hint": "Дългият край на същата сметка — движи хеджираните "
                          "облигационни потоци и структурната йена посока.",
    },
}


def series_by_source(source: str) -> list[dict[str, Any]]:
    """Връща спецификации за адаптера: [{key, source_id, release_schedule, …}].

    Форматът е този на BaseAdapter.fetch_many (CN `_base.py`): `key` +
    `source_id` + `release_schedule`. Пълният запис пътува отдолу за
    адаптери, на които им трябва повече (derived рецепти и т.н.).
    """
    result = []
    for k, v in SERIES_CATALOG.items():
        if v.get("source") == source:
            item = dict(v)
            item["key"] = k
            item["source_id"] = v["id"]
            result.append(item)
    return result


def yen_layer_keys() -> list[str]:
    """Сериите на йена-слоя — ЕДИНСТВЕНИЯТ източник е тагът в каталога."""
    return [k for k, v in SERIES_CATALOG.items() if "yen_layer" in v.get("tags", [])]


def validate_catalog(catalog: dict[str, dict[str, Any]] | None = None) -> list[str]:
    """Валидира каталога за грешки.

    Празна леща е ГРЕШКА — иначе серия, на която някой е забравил лещата, тихо
    изпада от композита и никой не разбира. Единственото изключение е изричният
    флаг `context_only: True` (фамилен мандат №48): контекстната серия е
    наблюдение ДО композита по СЪЗНАТЕЛНО решение.
    """
    catalog = SERIES_CATALOG if catalog is None else catalog
    errors = []
    for k, v in catalog.items():
        if v.get("source") not in ALLOWED_SOURCES:
            errors.append(f"{k}: invalid source {v.get('source')}")
        if v.get("region") not in ALLOWED_REGIONS:
            errors.append(f"{k}: invalid region {v.get('region')}")
        lenses = v.get("lens", [])
        if not lenses and not v.get("context_only"):
            errors.append(
                f"{k}: empty lens without context_only "
                f"(серия без леща изпада от композита мълчаливо)"
            )
        for l in lenses:
            if l not in ALLOWED_LENSES:
                errors.append(f"{k}: invalid lens {l}")
        if v.get("context_only") and lenses:
            errors.append(f"{k}: context_only series must not carry a lens")
        if v.get("transform") not in ALLOWED_TRANSFORMS:
            errors.append(f"{k}: invalid transform {v.get('transform')}")
        if not v.get("peer_group"):
            errors.append(f"{k}: missing peer_group (съзнателното решение липсва)")
        if v.get("release_schedule") not in ALLOWED_SCHEDULES:
            errors.append(f"{k}: invalid release_schedule {v.get('release_schedule')}")
        if not v.get("narrative_hint"):
            errors.append(f"{k}: missing narrative_hint")
    return errors
