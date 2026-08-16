# AGENT.md — карта за работа по jp-macro-dashboard

Този документ описва **архитектурата и инвариантите** (формата, не снимка).
Числата от примерите живеят в `output/` и в тестовете — не тук.

## Пайплайн (редът е ЗАДЪЛЖИТЕЛЕН)

`fetch → derive → score`: `run.py::_score_everything` е единният път на
всички команди — `build_adapters()` → `_build_snapshot` (fetch_many по TTL) →
`derive_series` (диференциалите стъпват на фетчнатите родители) →
`compute_lens_reports` → `compute_composite_score` → `get_regime`.
`validate_catalog()` е гейт преди всичко — невалиден каталог спира пуска.

При `--briefing`: `append_journal` ПРЕДИ `wow_delta` (идемпотентност по дата);
двете HTML страници се раждат ЗАЕДНО; api export-ът се ражда СЛЕД журнала
(executive частта му ЦИТИРА записания ред, не втора сметка). При
`--export-context`: историята се смята in-memory и НЕ се записва, журналът
се ЧЕТЕ и НЕ се дописва.

## Модулите

### Корен
- `run.py` — entry point: `--status` / `--briefing` / `--export-context` / `--refresh`.
- `config.py` — ключовете (FRED/e-Stat, `.env` fallback per ключ), MOF URL-ите,
  `COT_JPY_CANONICAL` (data-core), `MODULE_WEIGHTS` (сума точно 1.0),
  `HISTORY_START` (1955 — без данни-качествен разлом), `EPOCHS` (дефлационната
  1995-2012 · абеномиката 2013-19 · текущата 2022→, ковид 2020-21 нарочно зее),
  ФОРМА-КАНОН речниците (`LENS_*`, `YEN_LAYER_*`, `CONTEXT_*`), палитрата,
  линк шаблоните, `STALE_AFTER_MONTHS`.

### catalog/ — декларациите
- `series.py` — `SERIES_CATALOG`: 33 записа (14 скорирани в 6 лещи + 19
  контекст). Всяка серия: source/id/леща/peer_group/transform/hints.
  `series_by_source()` дава спецификации за адаптерите; `yen_layer_keys()`
  извежда йена-слоя от тага (един източник); `validate_catalog()` — гейтът.
- `polarity.py` — какво значи „здраво": ±1 линейни, U около целта на BOJ (2%)
  за инфлацията, `("OPT", lo, hi, s)` абсолютни зони за трите бум-серии.
  Зоните са от данни-пас (05.08.2026) с приемен гейт и НЕ се прекалибрират
  без нов мандат; `OPT_PROVENANCE` + `OPT_SOURCE_NOTE` пътуват с числата;
  `opt_keys()` е ЕДИНСТВЕНИЯТ източник за „кои са бум-сериите".

### sources/ — адаптерите (всички наследяват `_base.py`: кеш/TTL/retry)
- `fred_adapter.py` — fredapi, fail-loud без ключ; мъртвите OECD-MEI тикери
  НЕ са в каталога (списъкът им — в мандата и в data-quality бележките).
- `estat_adapter.py` — getStatsData JSON; source_id
  `<statsDataId>?tab=…&cat01=…&area=…`; месечните редове се филтрират от
  смесената месечно/годишна времева ос.
- `boj_adapter.py` — wide CSV в zip; броят мета колони се извежда от
  header-а (CGPI 3, BP 4). Tankan НЕ е тук (co.zip = само текущото издание).
- `mof_adapter.py` — JGB кривата (`jgb:<tenor>`) + седмичните потоци
  (`flows:<поле>`); ⚠ Shift-JIS тирето: Python дава U+301C, .NET — U+FF5E,
  регексът приема двете (регресия, хваната на живия пуск).
- `derived.py` — carry диференциалите; ражда се СЛЕД fetch-а, липсващ
  родител = серията не се ражда (декларира се, не гърми).

### core/ — уредът
- `primitives.py` — трансформациите + `robust_stats_latest` (10г прозорец,
  MAD, `MIN_OBS=36`).
- `scorer.py` — health_z (OPT плато → U → линейно) → peer-групи (невзвешено
  средно) → лещи (претеглени) → композит (ренормализация: `None` изпада).
  Пазачите: `scale_fallback`, `degenerate`, `thin_window`.
- `display.py` — ФОРМА-КАНОН примитивите: `fmt_value`, `months_old`,
  `is_stale`, `thin_window_note`, `verdict_sentence`, `epoch_label`,
  линковете per източник (`source_url` диспечира), `inflation_anchor`
  (пп зони около 2%).

### analysis/ — слоевете НАД уреда (не го пипат; пазено от тестове)
- `temperature.py` — бум-сериите над зоната си (от `opt_keys()`, не от свой
  списък) + балонната двойка (`JP_RPPI` × кредитен крак) с измерен провенанс.
- `tension.py` — К1 погасяването + LOO аукционът; `ENERGY_FLOOR` дава право
  на отказ („н.д.", не 0); референтната епоха е абеномиката и се МЕРИ.
- `lens_history.py` — реконструираната решетка (`GRID_START` 1985Q4, за да
  носи балонната ера) + живият журнал с `composition` тага
  (`<N>s<M>l-<sha1[:8]>`); последният ред ≡ живото изчисление.
- `yen_segment.py` — йена-слоят: 6 блока (лихви · валута · финансиране ·
  carry · позициониране · потоци); COT от `config.COT_JPY_CANONICAL`;
  `segment_lines()` е ЕДИНСТВЕНИЯТ източник на формулировките за всички
  повърхности.

### export/ — повърхностите
- `weekly_briefing.py` — `output/index.html`; CSS/JS палитрата се ГЕНЕРИРА
  от config; дневните серии се ресемплират седмично само за графиката.
- `briefing_context.py` — Markdown за LLM (горивото на macro-deep-brief-jp);
  нула ръчни константи — изреченията се цитират от display/analysis;
  `DATA_QUALITY_NOTES` са JP уговорките.
- `methodology.py` — методологичната страница; ражда се ЗАЕДНО с лицето;
  съдържа „Кредитната леща и нормализацията" (`credit_reading` чете живите
  лещови доклади — 10Y z-разривът се обяснява, не се крие).
- `macro_state.py` — машинният api export (`output/api/macro_state.json`,
  мандат ORGANISM-v1 Ф1): фамилната схема на us/eu/cn + JP слоевете;
  executive_summary цитира последния журнален ред (fail-loud без него);
  `regime_key` от `config.REGIME_KEYS`; йена-редовете дословно
  `segment_lines`. Консуматори: macro-satellite + аналитичният дрил.
- `page_style.py` — ЕДИН CSS за двете страници.

### scripts/ — празно (JP v1 няма ръчен seed)

## Гейтовете (pytest, ~126 теста)

`test_catalog` (валидатор + състав) · `test_polarity` + `test_opt_zones`
(зоните пиннати с провенанс; приемният гейт offline от комитнатия кеш) ·
`test_scorer`/`test_primitives`/`test_composite` идват от фамилията ·
`test_mof_adapter`/`test_estat_adapter`/`test_boj_adapter` (parse функциите
с фикстури от реалните формати) · `test_form_canon` (петте правила) ·
`test_briefing_context` (числата съвпадат със скоринга; йена-секцията
дословна) · `test_macro_state` (api ≡ журналния ред; режимът ≡ get_regime;
йена-редовете дословни) · `test_docs` (този документ и README не дрейфват
от кода).

## Как се добавя серия

1. Запис в `SERIES_CATALOG` (source/id живо проверени!) + изричен ред в
   `POLARITY` (или `context_only`).
2. `validate_catalog()` + pytest минават.
3. Ако е нов източник — адаптер подклас на `_base.py` + parse тестове с
   фикстура от реалния формат.
4. OPT зона САМО с данни-пас + провенанс + пиннат гейт тест (нов мандат).

## Menu-items (декларирани дупки)

Tankan история (BOJ портал CGI) · JPY cross-currency basis (няма безплатен
източник) · M2/bank lending месечни (BOJ CGI) · housing starts (e-Stat, ще
разшири имотната леща) · MOF FX интервенциите (HTML/PDF скрейпър).
