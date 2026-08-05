"""
export/methodology.py
=====================
„Как да четеш този дашборд" — на СОБСТВЕНА страница (фамилният прецедент №52).

ФОРМА-КАНОН духът: изводът остава първи на лицето, обяснението е на ЕДНА
клика, а обяснението на място (tooltips-ите на сериите) не мърда.

Страницата е детерминистична: тя не чете snapshot ДИРЕКТНО. Динамичните ѝ
части идват от каталога и конфигурацията (числителното на лещите и теглата от
`MODULE_WEIGHTS`, зоните-таблица от `POLARITY` през `zone_table`, константите
от `polarity` / `tension` / `temperature`). Входовете са два, и двата вече
сдъвкани: `history` — котвеното изречение на тензията носи и ИЗМЕРЕНОТО на
живия уред (`anchors_note`); `credit` — живото четене на 10Y JGB от лещовите
доклади (`credit_reading`), за да не преписва секцията за нормализацията
числа, които утре ще са други.
"""
import html as _html
import math
from datetime import datetime
from typing import Optional

from analysis.temperature import (
    BUBBLE_PAIR_CREDIT,
    BUBBLE_PAIR_PROPERTY,
    BUBBLE_PAIR_PROVENANCE,
    zone_table,
)
from analysis.tension import (
    AS_OF_NOTE,
    ENERGY_FLOOR,
    ND_LABEL,
    SIX_TO_SEVEN_NOTE,
    anchors_note,
)
from catalog.polarity import INFLATION_TARGET, OPT_SOURCE_NOTE, U_BAND
from catalog.series import SERIES_CATALOG
from config import (
    CONTEXT_BADGE_BG,
    LENS_NAMES_BG,
    MODULE_WEIGHTS,
    NOMINAL_10Y_KEY,
    YEN_LAYER_NAME_BG,
    YEN_LAYER_NOTE,
)
from core.display import ANCHOR_DISCLAIMER, fmt_target
from core.scorer import TANH_SLOPE
from export.page_style import BASE_CSS, REPO_URL
from analysis.lens_history import HONESTY_LABEL


# ── Едно име на две места: лицето линква, страницата се кръщава ──────────────
METHODOLOGY_HREF = "methodology.html"
METHODOLOGY_TITLE = "Как да четеш този дашборд"
METHODOLOGY_TEASER = (
    "Скалата 0-100, целта на BOJ, оптималните зони, температурата, тензията, "
    "йена-слоят и уговорките на данните — на отделна страница."
)
BACK_LINK_LABEL = "← Дашбордът"
LEAD_SENTENCE = (
    "Обяснението на уреда: какво точно мери всяко число, откъде идват "
    "праговете и какво уредът НЕ твърди."
)


# ── Броят лещи не е зашит никъде в текста ────────────────────────────────────
_COUNT_WORD_BG = {
    2: "двете", 3: "трите", 4: "четирите", 5: "петте",
    6: "шестте", 7: "седемте", 8: "осемте",
}


def _count_word(n: int) -> str:
    return _COUNT_WORD_BG.get(n, f"{n}-те")


def credit_reading(lens_reports: Optional[dict]) -> Optional[dict]:
    """Живото четене на 10Y JGB от кредитната леща — за секцията за
    нормализацията.

    Един източник: числата идват от СЪЩИЯ лещов доклад, който храни лицето и
    context експорта — страницата не смята нищо втори път и не преписва
    константи, които остаряват. `health_z` е полярностно ориентиран (по-скъп
    дълг = по-нездраво), затова знакът му казва посоката на разрива.
    """
    rep = (lens_reports or {}).get("credit") or {}
    for s in rep.get("series", []):
        if s.get("key") != NOMINAL_10Y_KEY:
            continue
        if s.get("score") is None or s.get("display_value") is None:
            return None
        return {
            "value": float(s["display_value"]),
            "health_z": s.get("health_z"),
            "score": float(s["score"]),
            "last_date": s.get("last_date"),
            "percentile_window": s.get("percentile_window", ""),
            "lens_z": rep.get("health_z"),
            "lens_score": rep.get("score"),
        }
    return None


def _zone_rows_html() -> str:
    """Зоните като редове на таблица — от POLARITY, не преписани."""
    rows = ""
    for z in zone_table(SERIES_CATALOG):
        rows += (
            f"<tr><td>{_html.escape(z['name_bg'])}</td>"
            f"<td>{z['lo']:.0f} … {z['hi']:.1f}%</td>"
            f"<td>{z['s']:.0f} пп</td>"
            f"<td>{_html.escape(z['provenance'])}</td></tr>"
        )
    return rows


def _credit_normalization_html(credit: Optional[dict]) -> str:
    """„Кредитната леща и нормализацията" — живото число, ако е подадено.

    Без вход (стар пуск, чист unit тест) страницата пази качественото
    обяснение и КАЗВА къде живее числото, вместо да поднесе застояла снимка.
    """
    if credit:
        z_str = (
            f"health-z {credit['health_z']:+.1f}"
            if credit.get("health_z") is not None else "екстремен health-z"
        )
        lens_str = ""
        if credit.get("lens_score") is not None and credit.get("lens_z") is not None:
            lens_str = (
                f" — и приковава кредитната леща на <b>{credit['lens_score']:.1f}</b> "
                f"(лещов z {credit['lens_z']:+.1f})"
            )
        live = (
            f"Живото четене: 10Y JGB е на <b>{credit['value']:.2f}%</b> "
            f"(данни към {_html.escape(str(credit['last_date']))}) — {z_str} срещу "
            f"10-годишната норма ({_html.escape(credit['percentile_window'])}), "
            f"т.е. YCC-ерата на потиснатите доходности. Серийният score е "
            f"<b>{credit['score']:.1f}</b>{lens_str}."
        )
    else:
        live = (
            "Живото число стои на лицето и в context експорта — тази страница "
            "е генерирана без лещовите доклади и не го преписва."
        )
    return f"""
    <h4>Кредитната леща и нормализацията</h4>
    <p>
      {live}
    </p>
    <p>
      Какво ЗНАЧИ това число: уредът мери <b>разрив спрямо собствената норма</b>
      на серията, не оценява политиката. Десетгодишният прозорец на 10Y JGB е
      почти изцяло YCC-ера — норма от потиснати, почти нулеви доходности — и
      днешната доходност е екстремум спрямо НЕЯ. Нормализацията е
      <b>желана от BOJ</b>: изходът от YCC/NIRP е целта на политиката, не
      авария. Но тя <b>Е екстремно бърза</b> спрямо всичко, което десетилетието
      е виждало — цената на дълга за корпоративния сектор и за фиска се
      преоценява с темп без прецедент в прозореца. Двете четения вървят
      <b>заедно</b>: „успех на политиката" и „най-рязката промяна на
      финансовите условия от десетилетие" не се изключват — и точно затова
      кредитната леща тежи на композита, докато нормализацията тече.
    </p>"""


def methodology_sections(history=None, credit=None) -> str:
    """Секциите на методологията — един източник за обяснението на уреда."""
    tension_anchors = anchors_note(history)
    zone_rows = _zone_rows_html()
    credit_html = _credit_normalization_html(credit)
    # Score-ът на серия В зоната — смятан, не преписан.
    zone_score = round(50.0 * (1.0 + math.tanh(U_BAND / TANH_SLOPE)), 1)
    weights_str = " · ".join(
        f"{LENS_NAMES_BG.get(m, m).lower()} {w:.0%}" for m, w in MODULE_WEIGHTS.items()
    )
    lens_count_word = _count_word(len(MODULE_WEIGHTS))
    bubble_credit = " / ".join(BUBBLE_PAIR_CREDIT)

    return f"""
    <h4>Скалата 0–100</h4>
    <p>
      Всяка серия се сравнява със СОБСТВЕНАТА си близка норма — медианата на
      последните 10 години, а разсейването се мери робастно
      (<code>1.4826 · MAD</code>, за да не разтяга скалата един извънреден месец).
      Полученото отклонение минава през <code>score = 50·(1 + tanh(z/2))</code>:
      <b>50 = нормалното за Япония напоследък</b>, ±2σ ≈ 88 / 12. Числото е
      описателно (къде сме), не прогнозно, и е сравнимо с останалите членове
      на фамилията (us/eu/china/bg) — същият примитив.
    </p>

    <h4>Инфлацията се мери като отклонение от целта на BOJ ({_html.escape(fmt_target(INFLATION_TARGET))})</h4>
    <p>
      Не „ниско = добре" — Япония е единствената икономика във фамилията,
      където дефлационната страна на U-формата не е теория, а три изживени
      десетилетия. Здравето е максимално при целта на BOJ
      ({_html.escape(fmt_target(INFLATION_TARGET))}, обявена 01.2013) и пада
      симетрично в двете посоки. Мярката на самата BOJ е ядреният CPI в
      японския смисъл — без прясна храна, С енергия — и точно тя е втората
      котва до headline числото.
    </p>
    <p>
      Освен U-score-а в композита експортът носи и <b>втори, абсолютен
      глас</b>: колко <b>процентни пункта</b> сме от целта, със фиксирани зони
      <b>≤1 пп</b> при целта (зелено) · <b>1–2 пп</b> отклонена (жълто) ·
      <b>&gt;2 пп</b> далеч от целта (червено). Зоните НЕ са калибрирани по
      историята — калибрирани по дефлационните десетилетия, те биха обявили
      самата цел за екстремум. {_html.escape(ANCHOR_DISCLAIMER)}
    </p>

    <h4>Композитът</h4>
    <p>
      Претеглена средна на {lens_count_word} лещи ({weights_str}). Леща без
      данни ИЗПАДА и теглата се преизчисляват — не се брои като „неутрално 50".
      Фискалът е <b>контекст, не леща</b> (мандат INIT-26, решение №1): FRED
      дава само годишни IMF WEO данни и десет точки за десетгодишна норма са
      нечестни. {_html.escape(SIX_TO_SEVEN_NOTE)}
    </p>

    <h4>Оптималните зони и температурата</h4>
    <p>
      Бумът вече <b>не се брои за здраве</b>. Бум-сериите — двата кредитни
      темпа и цените на жилищата — се мерят срещу <b>абсолютна оптимална
      зона</b>, а не срещу собствената си 10-годишна норма. Причината: в бум
      прозорец нормата сама се вдига и робастният <code>z</code> аплодира
      прегряването. В зоната здравето е на плато (score ≈ <b>{zone_score}</b>,
      същото като инфлация точно на целта); над горния праг score-ът пада с 1σ
      на всеки <code>s</code> пункта, под долния — симетрично. Медианата и
      MAD-скалата <b>не участват</b>.
    </p>
    <table class="zone-table">
      <thead><tr><th>Серия</th><th>Зона</th><th>1σ на</th><th>Откъде е прагът</th></tr></thead>
      <tbody>{zone_rows}</tbody>
    </table>
    <p>
      {_html.escape(OPT_SOURCE_NOTE)} <b>Термометърът</b> брои САМО нарушенията
      НАГОРЕ — колко серии стоят над зоната си. Под долния праг е
      разлистване/криза; то се чете в score-а, който пада и в двете посоки, не
      в термометъра. Праговете са абсолютни, затова температурата е смятаема и
      назад във времето без да знае бъдещето — балонната ера 1985-90 свети, а
      дефлацията и абеномиката мълчат. ⚠ <b>GFC знаменателят</b>:
      2008Q4-2010Q1 кредит/БВП темпът скача от свит БВП, не от нов кредит —
      деклариран клас фалшив позитив, четим от контекста (в криза композитът и
      без това крещи от другите лещи).
    </p>

    <h4>Балонната двойка (съ-прегряване имоти↔кредит)</h4>
    <p>
      Термометърът брои КОЛКО серии горят, но не казва <b>кои заедно</b>. Един
      прегрят показател е епизод; <b>цената на жилището и кредитът, прегрели
      едновременно</b>, е друго животно — там активът и финансирането му се
      надуват взаимно. Двойката е <b>активна</b>, когато
      <code>{_html.escape(BUBBLE_PAIR_PROPERTY)}</code> (цената на актива) е
      над зоната си <b>И</b> поне един от двата кредитни крака
      (<code>{_html.escape(bubble_credit)}</code>) също е над своята —
      двата крака дават <b>един</b> кредитен сигнал, точно както в
      peer-групата им.
    </p>
    <p>
      <b>Дискриминаторът работи и днес: ценова топлина без кредит НЕ е балон
      по тази дефиниция.</b> {_html.escape(BUBBLE_PAIR_PROVENANCE)}
    </p>

    <h4>Тензионният слой (К1 „Погасяването“)</h4>
    <p>
      Композитът е <b>средно</b>, а средното не различава две много различни
      икономики: една, в която {lens_count_word} лещи стоят около нормата, и
      друга, в която едни дърпат силно нагоре, други силно надолу и двете се
      изяждат. К1 мери точно това: колко от <b>лещовата енергия</b>
      (<code>Σw·|score−50|</code>) не оцелява до нетното отклонение
      (<code>|Σw·(score−50)|</code>). Показанието е делът, който се погасява:
      <code>1 − нето / енергия</code>.
    </p>
    <p>
      Какво НЕ е: <b>детектор на криза</b>. При срив всички лещи сочат надолу
      заедно, енергията минава почти цялата в нетното и К1 правилно
      <b>мълчи</b>. Високо показание значи „композитът е по-спокоен от
      състоянието, което описва", а не „лошо е". Разписката е
      <b>leave-one-out аукцион</b>: цената на всяка леща е композитът БЕЗ нея
      минус композитът С нея — <b>плюс</b> значи, че лещата тежи на композита,
      <b>минус</b> — че го крепи. При лещова енергия под
      <b>{ENERGY_FLOOR:.0f}</b> точки показанието е „{ND_LABEL}", а не нула:
      малък знаменател не бива да ражда голямо съотношение.
    </p>
    <p>
      {_html.escape(tension_anchors)}
      {_html.escape(AS_OF_NOTE)}
    </p>

    <h4>Реконструираната история</h4>
    <p>
      {_html.escape(HONESTY_LABEL)} Линията НЕ е запис на това, което дашбордът
      е показвал тогава: днешният уред — днешните дефиниции, лещи и тегла —
      пуснат върху днешните (вече <b>ревизирани</b>) данни, рязани по
      периодната дата. Решетката тръгва от <b>1985Q4</b> нарочно: балонната
      ера 1985-90 е приемният гейт на температурния слой. Ранните точки
      стъпват на <b>по-къси норми</b> и на по-малко серии (fallback-ите на
      скорера), затова всеки ред носи <code>n_lenses</code> и
      <code>n_series</code> — те казват колко уред реално стои зад точката.
      Живият запис е ДРУГ файл: <code>data/score_journal.csv</code> получава по
      един ред на всеки ритуален пуск и оттам идва делтата „какво се смени".
    </p>

    <h4>Къс прозорец</h4>
    <p>
      <span class="thin">⚠</span> до скора значи, че нормата НЕ е върху 10
      години — етикетът на серията казва откога тече вместо да твърди „10г",
      защото <code>z</code>-ът върху къс, еднопосочен период подценява
      екстремността.
    </p>
{credit_html}

    <h4>{_html.escape(YEN_LAYER_NAME_BG)}</h4>
    <p>
      {_html.escape(YEN_LAYER_NAME_BG)} е отделен <b>наблюдателен слой над
      композита</b> — както температурата и тензията:
      {_html.escape(YEN_LAYER_NOTE)}. Защо не е леща: курсът, carry
      диференциалът и позиционирането нямат „здрава" посока — слабата йена е
      добро за износителя и лошо за домакинството <b>едновременно</b>, и да се
      осредни това в композита би значело уредът да отсъди спор, който самата
      японска политика не е решила. Диференциаторът е за гледане, не за
      осредняване.
    </p>
    <p>
      Шестте блока: <b>лихви</b> (call rate, JGB 2Y/10Y, TIBOR) ·
      <b>валута</b> (USD/JPY, REER персентил) · <b>финансиране</b> (балансът
      на BOJ и г/г темпът му) · <b>carry</b> (диференциалите US−JP 2Y/10Y —
      сметката на carry трейда) · <b>позициониране</b> (COT JPY net от
      data-core канона, CFTC) · <b>потоци</b> (седмичните MOF ITS потоци).
      Възелът на carry unwind е <b>позициониране × лихвена траектория</b> —
      затова слоят стои над композита: той гледа точно този възел, който
      никоя леща не мери.
    </p>

    <h4>As-of дисциплина и източниците</h4>
    <p>
      „Данни към" е най-скорошното НАБЛЮДЕНИЕ, не времето на генериране. Всеки
      ред показва своя период; <span class="stale">⚠</span> означава наблюдение
      по-старо от двойния очакван ритъм на публикуване (месечни &gt; 2 месеца,
      тримесечни &gt; 6). Имената на индикаторите водят към първоизточника:
      FRED серията към страницата ѝ, e-Stat серията към таблицата
      (statdisp_id), BOJ сериите към stat-search портала, MOF сериите към
      страниците на кривата и на потоците. <b>Изведените серии нямат линк</b>
      — тяхното „id" е рецепта, не адрес; родителите им имат свои редове.
      Контекстните серии носят сивия бадж „{CONTEXT_BADGE_BG}", нямат score и
      не влизат в композита.
    </p>
"""


def generate_methodology(output_path: str, history=None, credit=None) -> str:
    """Ражда `output/methodology.html` — второто лице на дашборда.

    Линковете са ОТНОСИТЕЛНИ, за да работи страницата и локално през
    `file://`. `credit` е изходът на `credit_reading(lens_reports)` — без него
    страницата остава качествена: обяснението стои, снимката не се измисля.
    """
    generated_str = datetime.now().strftime("%d.%m.%Y")

    html = f"""<!DOCTYPE html>
<html lang="bg">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{METHODOLOGY_TITLE} — Японска Макроикономика</title>
<style>
{BASE_CSS}
  /* Само за тази страница: обратният линк + уводното изречение */
  .back-link {{ display:inline-block; font-size:0.88em; margin-bottom:14px; }}
  .back-link:hover {{ text-decoration:underline; }}
  .lead {{ color:var(--muted); font-size:0.9em; line-height:1.6;
           max-width:760px; margin-bottom:24px; }}
</style>
</head>
<body>
<div class="container">

  <a class="back-link" href="index.html">{BACK_LINK_LABEL}</a>

  <div class="header">
    <div class="header-left">
      <h1>{METHODOLOGY_TITLE}</h1>
      <div class="sub">🇯🇵 Японска Макроикономика · методология на уреда</div>
    </div>
    <div class="header-right">
      <div class="updated">Генериран {generated_str}</div>
    </div>
  </div>

  <p class="lead">{LEAD_SENTENCE}</p>

  <div class="methodology">
{methodology_sections(history, credit)}
  </div>

  <a class="back-link" href="index.html">{BACK_LINK_LABEL}</a>

</div>

<footer>
  Генериран {generated_str} ·
  <a href="index.html">Дашбордът</a> ·
  <a href="{REPO_URL}" target="_blank">GitHub</a>
</footer>

</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ Методологията: {output_path}")
    return html
