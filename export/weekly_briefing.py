"""
export/weekly_briefing.py
=========================
Генерира пълен интерактивен HTML дашборд за японската икономика.

Портнат от фамилния образец (bg-macro-dashboard). JP спецификите: йена-слоят
като собствена карта (segment_lines — ЕДИН източник на формулировките),
лещовите линии върху филма на композита, e-Stat/BOJ/MOF линковете на имената.
Палитрата (CSS баджове + JS линии) се ГЕНЕРИРА от config речниците — нова
леща или нов слой е един ред в config, не три поправки тук.
"""
import html as _html
import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from config import (
    CONTEXT_BADGE_BG,
    CONTEXT_BADGE_COLORS,
    CONTEXT_LINE_COLOR,
    CONTEXT_SCORE_NOTE,
    LENS_BADGE_COLORS,
    LENS_BADGES_BG,
    LENS_LINE_COLORS,
    LENS_NAMES_BG,
    MACRO_REGIMES,
    MODULE_WEIGHTS,
    YEN_LAYER_BADGE_BG,
    YEN_LAYER_BADGE_COLORS,
    YEN_LAYER_LINE_COLOR,
    YEN_LAYER_NAME_BG,
)
from analysis.lens_history import HONESTY_LABEL, ROW_LIVE, ROW_QUARTER
from analysis.temperature import (
    BUBBLE_PAIR_PROVENANCE,
    TEMP_SERIES,
    bubble_pair,
    bubble_pair_line,
    bubble_pair_streak,
    temp_level,
)
from analysis.tension import (
    AS_OF_NOTE,
    SIX_TO_SEVEN_NOTE,
    price_str,
    price_table,
)
from analysis.yen_segment import segment_lines, yen_segment
from catalog.series import SERIES_CATALOG
from core.display import (
    inflation_anchors,
    is_stale,
    source_url,
    stale_note,
    thin_window_note,
    verdict_sentence,
)
from core.primitives import apply_transform
from export.methodology import (
    METHODOLOGY_HREF,
    METHODOLOGY_TEASER,
    METHODOLOGY_TITLE,
)
from export.page_style import BASE_CSS, REPO_URL


# ── Температурният слой: цветовете на трите нива ─────────────────────────────
# Сиво при 0 · оранж при 1-2 · червено при ≥3. Нивото идва от
# `analysis.temperature.temp_level` — праговете не се преизмислят тук.
TEMP_COLORS = {
    "cold": "#8892a4",
    "warm": "#ff9800",
    "hot":  "#ef4444",
}

# ── Тензионният слой: цветът на К1 линията ───────────────────────────────────
# Приглушен вариант на акцента — линията е ПРОЧИТ върху композита, не втори
# композит; затова е тънка и по-бледа от лилавата линия на самия композит.
TENSION_COLOR = "#a99bff"

# Дневните серии носят хиляди точки в 12-годишния прозорец; за ГРАФИКАТА се
# ресемплират седмично (последно наблюдение) — това е дисплей решение, не
# трансформация: скорингът и таблиците четат пълната серия.
CHART_MAX_POINTS = 800


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """`#60a5fa` → `rgba(96,165,250,0.08)` — запълването под линията."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def _score_color(score) -> str:
    if score is None:
        return "#8892a4"
    for threshold, _, color in MACRO_REGIMES:
        if score >= threshold:
            return color
    return MACRO_REGIMES[-1][2]


def _fmt_score(score) -> str:
    return f"{score:.1f}" if score is not None else "—"


def _series_results(lens_reports: dict) -> dict:
    """{key: score dict} — плоският индекс на скорираните серии."""
    return {
        s["key"]: s
        for rep in lens_reports.values()
        for s in rep.get("series", [])
    }


def _display_series(snapshot: dict, key: str, spec: dict) -> pd.Series:
    """
    Серията както се ПОКАЗВА: с приложената каталожна трансформация.
    Дисплеят и скорингът трябва да гледат едно и също число.
    """
    if key not in snapshot or snapshot[key].empty:
        return pd.Series(dtype="float64")
    return apply_transform(snapshot[key], spec.get("transform", "level")).dropna()


def _compute_as_of(snapshot: dict) -> str | None:
    """Най-скорошното наблюдение измежду показваните серии (YYYY-MM)."""
    last_dates = []
    for key, spec in SERIES_CATALOG.items():
        s = _display_series(snapshot, key, spec)
        if not s.empty:
            last_dates.append(s.index[-1])
    if not last_dates:
        return None
    return max(last_dates).strftime("%Y-%m")


def _chart_palette_key(spec: dict) -> str:
    """Кой цвят носи серията на графиката и в баджа.

    Йена-слоят (тагът `yen_layer`) има собствен цвят и бадж от config — той е
    отделен слой, не леща. Останалите контекстни серии са сиви: „наблюдение,
    не компонент". Скорираната серия носи цвета на лещата си.
    """
    if "yen_layer" in spec.get("tags", []):
        return "yen"
    if spec.get("context_only"):
        return "context"
    return spec["lens"][0] if spec.get("lens") else "growth"


def _prep_chart_data(snapshot: dict) -> dict:
    chart_data = {}
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=12)
    for key, spec in SERIES_CATALOG.items():
        if key not in snapshot or snapshot[key].empty:
            continue
        s = _display_series(snapshot, key, spec)
        if s.empty:
            continue
        s_recent = s[s.index >= cutoff]
        if s_recent.empty:
            continue
        # Дневна серия → седмични точки за ГРАФИКАТА (дисплей, не трансформация).
        if len(s_recent) > CHART_MAX_POINTS:
            s_recent = s_recent.resample("W-FRI").last().dropna()
        chart_data[key] = {
            "name": spec["name_bg"],
            "dates": [d.strftime("%Y-%m-%d") for d in s_recent.index],
            "values": [round(float(v), 4) for v in s_recent.values],
            "lens": _chart_palette_key(spec),
            "is_rate": spec.get("is_rate", False),
        }
    return chart_data


def _regime_bands() -> list:
    """Режимните ленти като [{y0, y1, color}] — праговете от `MACRO_REGIMES`."""
    bands = []
    upper = 100.0
    for threshold, _name, color in MACRO_REGIMES:
        bands.append({"y0": float(threshold), "y1": upper, "color": color})
        upper = float(threshold)
    return bands


def _prep_film_data(history) -> dict:
    """Решетката → JSON за филма. Смятането е ТУК, в JS остава само рисуването.

    Композитът + ЛЕЩОВИТЕ линии (score_{lens} колоните) — цветовете идват от
    config.LENS_LINE_COLORS, имената от LENS_NAMES_BG (един речник).
    """
    if history is None or len(history) == 0:
        return {}

    q = history[history["row_type"] == ROW_QUARTER].dropna(subset=["composite"])
    live = history[history["row_type"] == ROW_LIVE].dropna(subset=["composite"])

    data = {
        "dates": [d.strftime("%Y-%m-%d") for d in q.index],
        "values": [round(float(v), 1) for v in q["composite"]],
        "bands": _regime_bands(),
        "label": HONESTY_LABEL,
    }
    if len(live):
        data["live"] = {
            "date": live.index[-1].strftime("%Y-%m-%d"),
            "value": round(float(live["composite"].iloc[-1]), 1),
        }

    # ── Лещовите линии: тънки следи под композита, обща x-ос ────────────────
    lenses = []
    for lens in MODULE_WEIGHTS:
        col = f"score_{lens}"
        if col not in q.columns or not q[col].notna().any():
            continue
        lenses.append({
            "lens": lens,
            "name": LENS_NAMES_BG.get(lens, lens),
            "color": LENS_LINE_COLORS.get(lens, "#8892a4"),
            "values": [
                round(float(v), 1) if pd.notna(v) else None for v in q[col]
            ],
        })
    if lenses:
        data["lenses"] = lenses

    # ── Температурната лента ─────────────────────────────────────────────────
    if "temp_count" in q.columns and q["temp_count"].notna().any():
        counts = [
            int(v) if pd.notna(v) else 0 for v in q["temp_count"]
        ]
        data["temp"] = {
            "values": counts,
            "colors": [TEMP_COLORS[temp_level(c)] for c in counts],
            "max": len(TEMP_SERIES),
            "note": ("Температурата: колко бум-серии са над зоната си "
                     "(абсолютни котви — валидни и назад)"),
        }

    # ── Тензионната линия ────────────────────────────────────────────────────
    if "k1_ratio" in q.columns and q["k1_ratio"].notna().any():
        data["tension"] = {
            "values": [
                round(float(v), 3) if pd.notna(v) else None for v in q["k1_ratio"]
            ],
            "color": TENSION_COLOR,
            "name": "Погасена енергия (К1)",
            "note": ("Погасена енергия (К1, дясна ос 0–1): колко от лещовата "
                     "енергия се изяжда в средното. Етикетът „реконструирана“ "
                     "покрива и нея. " + SIX_TO_SEVEN_NOTE),
        }
    return data


def _prep_wow_data(wow) -> dict:
    """WoW делтата → готови за рисуване редове (нула аритметика в JS)."""
    if not wow:
        return {
            "available": False,
            "empty_note": "Първи запис в живия журнал — делтата тръгва от "
                          "следващия пуск.",
        }

    def _fmt_delta(d) -> str:
        if d is None:
            return "—"
        return f"{d:+.1f}"

    def _cls(d) -> str:
        if d is None or d == 0:
            return ""
        return "pos" if d > 0 else "neg"

    try:
        prev_human = datetime.strptime(wow["prev_date"], "%Y-%m-%d").strftime("%d.%m.%Y")
    except (ValueError, KeyError, TypeError):
        prev_human = str(wow.get("prev_date", "—"))

    lens_deltas = wow.get("lens_deltas") or {}
    rows = [
        {
            "name": LENS_NAMES_BG.get(lens, lens),
            "delta": lens_deltas.get(lens),
            "delta_str": _fmt_delta(lens_deltas.get(lens)),
            "cls": _cls(lens_deltas.get(lens)),
        }
        for lens in MODULE_WEIGHTS
        if lens in lens_deltas
    ]
    rows.sort(key=lambda r: abs(r["delta"]) if r["delta"] is not None else -1.0,
              reverse=True)

    return {
        "available": True,
        "prev_date": prev_human,
        "since": f"спрямо {prev_human}",
        "composite_delta": wow.get("composite_delta"),
        "composite_delta_str": _fmt_delta(wow.get("composite_delta")),
        "composite_cls": _cls(wow.get("composite_delta")),
        "rows": rows,
        "composition_changed": bool(wow.get("composition_changed")),
        "composition_note": "⚠ съставът на уреда се смени между двата записа — "
                            "делтата не е чиста",
    }


def _temp_badge_html(temp) -> str:
    """„Прегряване: N/M" до режимния етикет + tooltip кой гори."""
    if not temp or not temp.get("n_total"):
        return ""
    n_hot, n_total = int(temp["n_hot"]), int(temp["n_total"])
    level = temp_level(n_hot)
    if temp.get("hot"):
        tip = " · ".join(
            f"{e['name_bg']}: {e['value']:.1f} (зона до {e['hi']:.1f})"
            for e in temp["hot"]
        )
    else:
        tip = "Нито една бум-серия не е над зоната си."
    return (
        f'<span class="temp-badge temp-{level}" title="{_html.escape(tip)}">'
        f'🌡 Прегряване: {n_hot}/{n_total}</span>'
    )


def _bubble_pair_html(temp, history=None) -> str:
    """Редът на балонната двойка в температурната лента под филма.

    Изречението идва ГОТОВО от `analysis.temperature` (един източник), тук се
    решава само дали да го има и какво носи tooltip-ът.
    """
    if not temp or not temp.get("n_total"):
        return ""
    pair = bubble_pair(temp)
    line = bubble_pair_line(pair, bubble_pair_streak(history))
    if not line:
        return ""
    cls = "bubble-on" if pair["active"] else "bubble-off"
    return (
        f'<div class="film-temp-note bubble-row {cls}" '
        f'title="{_html.escape(BUBBLE_PAIR_PROVENANCE)}">'
        f'🫧 {_html.escape(line)}</div>'
    )


def _tension_row_html(tension) -> str:
    """Тензионният ред под извода: „⚖ {изречение}" + разписката в tooltip-а."""
    if not tension or not tension.get("sentence"):
        return ""

    rows = price_table(tension)
    parts = []
    if rows:
        parts.append(
            "Разписка (leave-one-out: композит БЕЗ лещата минус композит С нея; "
            "плюс = тежи, минус = крепи) — "
            + " · ".join(f"{r['subject']} {price_str(r['price'])}" for r in rows)
        )
    falsifier = tension.get("falsifier") or {}
    if falsifier.get("sentence"):
        parts.append(falsifier["sentence"])
    parts.append(SIX_TO_SEVEN_NOTE)
    parts.append(AS_OF_NOTE)
    tip = " | ".join(parts)

    return (
        f'<div class="tension-row" title="{_html.escape(tip)}">'
        f'⚖ {_html.escape(tension["sentence"])}</div>'
    )


def _yen_card_html(snapshot: dict) -> str:
    """Йена-слоят като собствена карта — диференциаторът на JP лицето.

    Редовете идват ДОСЛОВНО от `segment_lines` (ЕДИН източник на
    формулировките — същият, който печата `--status` и context експортът).
    Баджът и цветът идват от config.YEN_LAYER_* — не се преписват тук.
    """
    seg = yen_segment(snapshot)
    lines = segment_lines(seg)
    items = "".join(
        f"<li>{_html.escape(line.strip())}</li>" for line in lines[1:]
    )
    return f"""
  <!-- Йена-слоят: отделен наблюдателен слой над композита -->
  <div class="card yen-card">
    <h2>¥ {_html.escape(seg['label_bg'])}
      <span class="lens-badge lens-yen">{_html.escape(YEN_LAYER_BADGE_BG)}</span></h2>
    <div class="yen-note">{_html.escape(seg['note'])}</div>
    <ul class="yen-lines">{items}</ul>
  </div>
"""


def _anchor_card(voices: dict) -> str:
    """Котвената лента: инфлацията, мерена в пп от целта на BOJ.

    Вторият глас стои ДО модул-баровете, а не в тях. Празни данни → няма
    лента, а не празна рамка.
    """
    anchors = voices.get("anchors") or []
    if not anchors:
        return ""

    rows = ""
    for a in anchors:
        rows += f"""
      <div class="anchor-row">
        <span class="anchor-dot" style="background:{a['color']}"></span>
        <span class="anchor-name">{_html.escape(a['name_bg'])}</span>
        <span class="anchor-sentence">{_html.escape(a['value_str'])} =
          <b>{_html.escape(a['gap_phrase'])}</b> — {_html.escape(a['zone_phrase'])}</span>
      </div>"""

    return f"""
  <!-- Котвената лента: инфлацията с абсолютни зони около целта на BOJ -->
  <div class="anchor-card">
    <h2>Инфлацията с котви</h2>
    <div class="anchor-rows">{rows}
    </div>
    <div class="anchor-note">{_html.escape(voices.get('disclaimer', ''))}</div>
  </div>
"""


def generate_html(
    snapshot: dict,
    lens_reports: dict,
    composite,
    regime: dict,
    output_path: str,
    history=None,
    wow=None,
    temp=None,
    tension=None,
):
    chart_data = _prep_chart_data(snapshot)
    film_data = _prep_film_data(history)
    wow_data = _prep_wow_data(wow)
    as_of = _compute_as_of(snapshot)
    as_of_str = as_of if as_of else "няма данни"
    today = date.today()
    generated_str = datetime.now().strftime("%d.%m.%Y")

    module_scores = {lens: rep.get("score") for lens, rep in lens_reports.items()}
    results = _series_results(lens_reports)
    verdict = verdict_sentence(lens_reports)

    # ── Latest values table ──────────────────────────────────────────────────
    rows_html = ""
    for key, spec in SERIES_CATALOG.items():
        is_context = bool(spec.get("context_only"))
        lens = _chart_palette_key(spec)
        if lens == "yen":
            badge = YEN_LAYER_BADGE_BG
        elif is_context:
            badge = CONTEXT_BADGE_BG
        else:
            badge = LENS_BADGES_BG.get(lens, lens)
        hint = _html.escape(spec.get("narrative_hint", "") or "")
        url = source_url(spec.get("source", ""), spec.get("id", ""))
        name_html = _html.escape(spec["name_bg"])
        if url:
            name_html = (
                f'<a href="{url}" target="_blank" rel="noopener" '
                f'onclick="event.stopPropagation()">{name_html}</a>'
            )
        name_cell = f'<td class="ind-name" title="{hint}">{name_html}</td>'

        if key not in snapshot or snapshot[key].empty:
            rows_html += f"""
            <tr>
                {name_cell}
                <td><span class="lens-badge lens-{lens}">{badge}</span></td>
                <td>—</td><td>—</td><td>—</td>
                <td style="color:#888">Липсват данни</td>
            </tr>"""
            continue
        s = _display_series(snapshot, key, spec)
        if s.empty:
            continue
        last_val = s.iloc[-1]
        last_ts = s.index[-1]
        last_date = last_ts.strftime("%Y-%m")
        schedule = spec.get("release_schedule", "monthly")
        if is_stale(last_ts, schedule, today):
            last_date = (
                f'<span class="stale" title="{_html.escape(stale_note(schedule))}">⚠</span> '
                f'{last_date}'
            )
        prev_val = s.iloc[-2] if len(s) > 1 else None
        delta = last_val - prev_val if prev_val is not None else None
        delta_str = ""
        delta_cls = ""
        if delta is not None:
            sign = "+" if delta > 0 else ""
            delta_cls = "pos" if delta > 0 else "neg" if delta < 0 else ""
            delta_str = f'{sign}{delta:.2f}'
        res = results.get(key, {})
        score_val = res.get("score")
        thin_mark = ""
        if res.get("thin_window"):
            thin_mark = (
                f'<span class="thin" title="'
                f'{_html.escape(thin_window_note(res.get("percentile_window")))}">⚠</span> '
            )
        if is_context:
            # Контекстната серия НЯМА score — и го казва, вместо да покаже
            # тире, което читателят би прочел като „липсват данни".
            score_cell = (
                f'<td class="ctx-score" title="{_html.escape(CONTEXT_SCORE_NOTE)}">—</td>'
            )
        else:
            score_cell = (
                f'<td style="color:{_score_color(score_val)}">'
                f'{thin_mark}<b>{_fmt_score(score_val)}</b></td>'
            )
        rows_html += f"""
            <tr onclick="showChart('{key}')" style="cursor:pointer">
                {name_cell}
                <td><span class="lens-badge lens-{lens}">{badge}</span></td>
                <td>{last_date}</td>
                <td><b>{last_val:.2f}</b></td>
                <td class="{delta_cls}">{delta_str}</td>
                {score_cell}
            </tr>"""

    # ── Module score bars ────────────────────────────────────────────────────
    module_bars = ""
    for mod, score in module_scores.items():
        color = _score_color(score)
        name = LENS_NAMES_BG.get(mod, mod.capitalize())
        width = score if score is not None else 0.0
        module_bars += f"""
        <div class="mod-row">
            <div class="mod-label">{name}</div>
            <div class="mod-bar-wrap">
                <div class="mod-bar" style="width:{width:.1f}%; background:{color}"></div>
            </div>
            <div class="mod-score" style="color:{color}">{_fmt_score(score)}</div>
        </div>"""

    # ── Regime hero ──────────────────────────────────────────────────────────
    regime_color = regime["color"]
    regime_name = regime["name"]
    composite_str = _fmt_score(composite)
    temp_badge = _temp_badge_html(temp)
    tension_row = _tension_row_html(tension)
    bubble_row = _bubble_pair_html(temp, history)

    # Палитрата се генерира от ЕДИНИТЕ речници в config.py — CSS баджовете тук,
    # линиите и запълването в JS по-долу. Нова леща/слой = един ред в config.
    badge_colors = dict(
        LENS_BADGE_COLORS,
        context=CONTEXT_BADGE_COLORS,
        yen=YEN_LAYER_BADGE_COLORS,
    )
    line_colors = dict(
        LENS_LINE_COLORS,
        context=CONTEXT_LINE_COLOR,
        yen=YEN_LAYER_LINE_COLOR,
    )
    lens_badge_css = "\n".join(
        f"  .lens-{lens} {{ background:{bg}; color:{fg}; }}"
        for lens, (bg, fg) in badge_colors.items()
    )
    lens_fill_colors = {
        lens: _hex_to_rgba(color, 0.08) for lens, color in line_colors.items()
    }

    # ── Котвената лента + йена-слоят ─────────────────────────────────────────
    anchor_card = _anchor_card(inflation_anchors(snapshot))
    yen_card = _yen_card_html(snapshot)

    # ── Филмът на композита ──────────────────────────────────────────────────
    film_card = ""
    if film_data or wow_data.get("available"):
        film_card = f"""
  <!-- Филмът: композитът + лещите през времето -->
  <div class="card film-card">
    <h2>Филмът: композитът и лещите през времето</h2>
    <div class="film-label">{_html.escape(HONESTY_LABEL)}</div>
    <div class="film-grid">
      <div>
        <div id="film-chart"></div>
        <div class="film-temp-note" id="film-temp-note"></div>
        {bubble_row}
        <div class="film-temp-note" id="film-tension-note"></div>
      </div>
      <div class="wow-block">
        <h3>Какво се смени този пуск</h3>
        <div id="wow-body"></div>
      </div>
    </div>
  </div>
"""

    html = f"""<!DOCTYPE html>
<html lang="bg">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Японска Макроикономика — Дашборд</title>
<script src="https://cdn.plot.ly/plotly-2.24.1.min.js"></script>
<style>
{BASE_CSS}
  /* Regime hero */
  .regime-hero {{ background:var(--card); border-radius:16px; padding:30px; margin-bottom:30px;
                  border-left:6px solid {regime_color}; display:flex; align-items:center; gap:30px; flex-wrap:wrap; }}
  .regime-score-big {{ font-size:4em; font-weight:800; color:{regime_color}; line-height:1; }}
  .regime-line {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; }}
  .regime-label {{ font-size:1.5em; font-weight:600; color:{regime_color}; }}
  .regime-desc {{ color:var(--muted); font-size:0.9em; margin-top:6px; max-width:500px; }}

  /* Термометърът на прегряването */
  .temp-badge {{ font-size:0.78em; font-weight:700; padding:4px 10px; border-radius:20px;
                 cursor:help; letter-spacing:0.3px; white-space:nowrap; }}
  .temp-cold {{ background:rgba(136,146,164,0.16); color:{TEMP_COLORS['cold']}; }}
  .temp-warm {{ background:rgba(255,152,0,0.16);   color:{TEMP_COLORS['warm']}; }}
  .temp-hot  {{ background:rgba(239,68,68,0.18);   color:{TEMP_COLORS['hot']}; }}
  .film-temp-note {{ color:var(--muted); font-size:0.78em; margin-top:8px; line-height:1.5; }}

  /* Балонната двойка: съ-прегряване имоти↔кредит */
  .bubble-row {{ cursor:help; border-left:2px solid transparent; padding-left:10px; }}
  .bubble-on  {{ color:{TEMP_COLORS['hot']}; border-left-color:{TEMP_COLORS['hot']}; font-weight:600; }}
  .bubble-off {{ color:var(--muted); border-left-color:var(--border); }}
  .verdict {{ font-size:1.05em; font-weight:600; color:var(--text); margin-top:10px; max-width:560px; line-height:1.45; }}

  /* Тензионният ред */
  .tension-row {{ font-size:0.86em; color:{TENSION_COLOR}; margin-top:8px; max-width:560px;
                  line-height:1.45; cursor:help; border-left:2px solid {TENSION_COLOR};
                  padding-left:10px; }}

  /* Йена-слоят: отделен наблюдателен слой (config.YEN_LAYER_*) */
  .yen-card {{ margin-bottom:30px; border-left:3px solid {YEN_LAYER_LINE_COLOR}; }}
  .yen-card h2 {{ display:flex; align-items:center; gap:10px; }}
  .yen-note {{ color:var(--muted); font-size:0.82em; margin:-6px 0 12px; line-height:1.5; }}
  .yen-lines {{ list-style:none; padding:0; margin:0; }}
  .yen-lines li {{ padding:6px 0; border-bottom:1px solid #1e2130; font-size:0.88em;
                   color:var(--text); line-height:1.5; }}
  .yen-lines li:last-child {{ border-bottom:none; }}

  /* Филмът на композита */
  .film-card {{ margin-bottom:30px; }}
  .film-label {{ color:var(--muted); font-size:0.82em; margin:-8px 0 16px; line-height:1.5; }}
  .film-grid {{ display:grid; grid-template-columns:2.2fr 1fr; gap:24px; align-items:start; }}
  @media(max-width:900px) {{ .film-grid {{ grid-template-columns:1fr; }} }}
  #film-chart {{ height:360px; }}
  .wow-block h3 {{ font-size:0.8em; text-transform:uppercase; letter-spacing:0.6px;
                   color:var(--muted); margin-bottom:12px; }}
  .wow-since {{ color:var(--muted); font-size:0.78em; margin-bottom:12px; }}
  .wow-head {{ display:flex; justify-content:space-between; align-items:baseline;
               padding:8px 0 10px; border-bottom:1px solid var(--border); margin-bottom:8px; }}
  .wow-head .label {{ font-size:0.85em; color:var(--text); font-weight:600; }}
  .wow-head .val {{ font-size:1.25em; font-weight:700; }}
  .wow-row {{ display:flex; justify-content:space-between; align-items:baseline;
              padding:5px 0; font-size:0.85em; }}
  .wow-row .label {{ color:var(--muted); }}
  .wow-row .val {{ font-weight:600; }}
  .wow-note {{ color:var(--muted); font-size:0.82em; line-height:1.5; }}
  .wow-warn {{ color:#ff9800; font-size:0.78em; margin-top:10px; line-height:1.45; }}

  /* Линк-картата към методологията */
  .page-link {{ display:block; background:var(--card); border:1px solid var(--border);
                border-radius:12px; padding:16px 24px; margin-bottom:30px; color:var(--text); }}
  .page-link:hover {{ border-color:var(--accent); }}
  .page-link-title {{ font-weight:600; font-size:0.95em; color:var(--accent); }}
  .page-link-teaser {{ color:var(--muted); font-size:0.85em; margin-top:6px; line-height:1.5; }}

  /* Индикаторни имена */
  .ind-name a {{ border-bottom:1px dotted rgba(124,106,247,0.5); }}
  .ind-name a:hover {{ border-bottom-color:var(--accent); }}

  /* Module bars */
  .modules-card {{ background:var(--card); border-radius:12px; padding:24px; margin-bottom:30px; border:1px solid var(--border); }}
  .modules-card h2 {{ margin-bottom:20px; font-size:1.1em; color:var(--muted); text-transform:uppercase; letter-spacing:1px; }}
  .mod-row {{ display:flex; align-items:center; gap:12px; margin-bottom:14px; }}
  .mod-label {{ width:160px; font-size:0.9em; color:var(--muted); flex-shrink:0; }}
  .mod-bar-wrap {{ flex:1; background:#252836; border-radius:4px; height:8px; overflow:hidden; }}
  .mod-bar {{ height:100%; border-radius:4px; transition:width 0.5s; }}
  .mod-score {{ width:40px; text-align:right; font-weight:700; font-size:0.95em; }}

  /* Котвената лента */
  .anchor-card {{ background:var(--card); border-radius:12px; padding:20px 24px;
                  margin-bottom:30px; border:1px solid var(--border); }}
  .anchor-card h2 {{ font-size:1.1em; color:var(--muted); text-transform:uppercase;
                     letter-spacing:1px; margin-bottom:14px; }}
  .anchor-row {{ display:flex; align-items:baseline; gap:10px; padding:6px 0;
                 font-size:0.9em; flex-wrap:wrap; }}
  .anchor-dot {{ width:10px; height:10px; border-radius:50%; flex-shrink:0; }}
  .anchor-name {{ color:var(--muted); min-width:210px; }}
  .anchor-sentence {{ color:var(--text); }}
  .anchor-note {{ color:var(--muted); font-size:0.8em; margin-top:12px;
                  line-height:1.5; border-top:1px solid var(--border); padding-top:10px; }}
  .ctx-score {{ color:var(--muted); cursor:help; }}

  /* Two-column layout */
  .two-col {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:30px; }}
  @media(max-width:900px) {{ .two-col {{ grid-template-columns:1fr; }} }}

  /* Lens badges */
  .lens-badge {{ font-size:0.72em; padding:2px 7px; border-radius:20px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; }}
{lens_badge_css}

  /* Chart area */
  .chart-area {{ background:var(--card); border-radius:12px; padding:24px; border:1px solid var(--border); margin-bottom:30px; }}
  .chart-area h2 {{ font-size:1.1em; color:var(--muted); text-transform:uppercase; letter-spacing:1px; margin-bottom:6px; }}
  .chart-selector {{ display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }}
  .chart-btn {{ background:#252836; border:1px solid var(--border); color:var(--muted); padding:6px 14px; border-radius:20px;
                cursor:pointer; font-size:0.82em; transition:all 0.2s; }}
  .chart-btn:hover, .chart-btn.active {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
  #main-chart {{ height:380px; }}
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <div class="header-left">
      <h1>🇯🇵 Японска Макроикономика</h1>
      <div class="sub">Данни от FRED · e-Stat · BOJ · MOF · data-core COT · Автоматично обновяване</div>
    </div>
    <div class="header-right">
      <div class="updated">Генериран {generated_str} · Данни към {as_of_str}</div>
    </div>
  </div>

  <!-- Regime Hero -->
  <div class="regime-hero">
    <div>
      <div class="regime-score-big">{composite_str}</div>
      <div style="color:var(--muted); font-size:0.8em; margin-top:4px;">от 100</div>
    </div>
    <div>
      <div class="regime-line">
        <span class="regime-label">{regime_name}</span>
        {temp_badge}
      </div>
      <div class="verdict">{verdict}</div>
      {tension_row}
      <div class="regime-desc">
        Композитен макроикономически резултат за Япония по {len(SERIES_CATALOG)} ключови
        индикатора от FRED, e-Stat, BOJ и MOF. 50 = близката 10-годишна норма;
        по-високо = по-здраво. Инфлацията се мери като отклонение от целта на BOJ (2%).
      </div>
    </div>
  </div>

{film_card}
  <!-- Методологията: линк-карта към собствената ѝ страница.
       ФОРМА-КАНОН: изводът остава първи ТУК, обяснението е на ЕДНА клика. -->
  <a class="page-link" href="{METHODOLOGY_HREF}">
    <div class="page-link-title">📖 {METHODOLOGY_TITLE} →</div>
    <div class="page-link-teaser">{METHODOLOGY_TEASER}</div>
  </a>

  <!-- Module Bars -->
  <div class="modules-card">
    <h2>Компоненти на резултата</h2>
    {module_bars}
  </div>
{anchor_card}{yen_card}
  <!-- Two columns: Table + Radar -->
  <div class="two-col">
    <div class="card">
      <h2>Последни стойности</h2>
      <table>
        <thead><tr><th>Индикатор</th><th>Леща</th><th>Период</th><th>Стойност</th><th>Δ</th><th>Score</th></tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>

    <div class="card">
      <h2>Режими по компонент</h2>
      <div id="radar-chart" style="height:320px;"></div>
    </div>
  </div>

  <!-- Main Chart -->
  <div class="chart-area">
    <h2 id="chart-title">Изберете индикатор</h2>
    <div class="chart-selector" id="chart-selector"></div>
    <div id="main-chart"></div>
  </div>

</div>

<footer>
  Данните са от <a href="https://fred.stlouisfed.org" target="_blank">FRED</a> ·
  <a href="https://www.e-stat.go.jp/en" target="_blank">e-Stat</a> ·
  <a href="https://www.stat-search.boj.or.jp/" target="_blank">BOJ</a> ·
  <a href="https://www.mof.go.jp/english/" target="_blank">MOF</a> ·
  data-core COT (CFTC) ·
  Генериран {generated_str} · Данни към {as_of_str} ·
  <a href="{METHODOLOGY_HREF}">{METHODOLOGY_TITLE}</a> ·
  <a href="{REPO_URL}" target="_blank">GitHub</a>
</footer>

<script>
const CHART_DATA = {json.dumps(chart_data, ensure_ascii=False)};

// Един речник за палитрата (config.py) — CSS баджовете, линиите и запълването
// не се разминават, а нова леща/слой не иска пипане на три места.
const LENS_COLORS = {json.dumps(line_colors, ensure_ascii=False)};

const LENS_BG = {json.dumps(lens_fill_colors, ensure_ascii=False)};

const MODULE_SCORES = {json.dumps(module_scores)};
// Един речник — същите имена като модул-баровете и briefing_context (config.py)
const BG_NAMES = {json.dumps(LENS_NAMES_BG, ensure_ascii=False)};

// Build chart selector buttons
const selector = document.getElementById("chart-selector");
for (const [key, data] of Object.entries(CHART_DATA)) {{
  const btn = document.createElement("button");
  btn.className = "chart-btn";
  btn.textContent = data.name;
  btn.dataset.key = key;
  btn.onclick = () => showChart(key);
  selector.appendChild(btn);
}}

let activeKey = null;

function showChart(key) {{
  if (!CHART_DATA[key]) return;

  document.querySelectorAll(".chart-btn").forEach(b => b.classList.remove("active"));
  const btn = document.querySelector(`[data-key="${{key}}"]`);
  if (btn) btn.classList.add("active");

  const data = CHART_DATA[key];
  const color = LENS_COLORS[data.lens] || "#7c6af7";
  const fillColor = LENS_BG[data.lens] || "rgba(124,106,247,0.08)";

  document.getElementById("chart-title").textContent = data.name;

  const trace = {{
    x: data.dates,
    y: data.values,
    type: "scatter",
    mode: "lines",
    name: data.name,
    line: {{ color: color, width: 2.5 }},
    fill: "tozeroy",
    fillcolor: fillColor,
    hovertemplate: "%{{x|%b %Y}}: <b>%{{y:.2f}}</b><extra></extra>"
  }};

  const traces = [trace];

  // Add zero line
  const shapes = [];
  if (data.values.some(v => v < 0)) {{
    shapes.push({{
      type: "line", x0: data.dates[0], x1: data.dates[data.dates.length-1],
      y0: 0, y1: 0, line: {{ color: "#555", width: 1, dash: "dot" }}
    }});
  }}

  const layout = {{
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: {{ color: "#8892a4", family: "-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif" }},
    margin: {{ t: 10, r: 20, b: 40, l: 50 }},
    xaxis: {{ showgrid: false, zeroline: false, color: "#8892a4" }},
    yaxis: {{ gridcolor: "#1e2130", zerolinecolor: "#444", color: "#8892a4" }},
    shapes: shapes,
    hovermode: "x unified",
    showlegend: false
  }};

  Plotly.react("main-chart", traces, layout, {{displayModeBar: false, responsive: true}});
  activeKey = key;
}}

// ── Филмът на композита + лещите ────────────────────────────────────────────
// FILM_DATA/WOW_DATA идват ГОТОВИ от Python — тук само се рисува.
const FILM_DATA = {json.dumps(film_data, ensure_ascii=False)};
const WOW_DATA = {json.dumps(wow_data, ensure_ascii=False)};

(function() {{
  const el = document.getElementById("film-chart");
  if (!el || !FILM_DATA.dates || !FILM_DATA.dates.length) return;

  // Режимните ленти — праговете на композита като бледи хоризонтални полета
  const shapes = (FILM_DATA.bands || []).map(b => ({{
    type: "rect", xref: "paper", yref: "y",
    x0: 0, x1: 1, y0: b.y0, y1: b.y1,
    fillcolor: b.color, opacity: 0.06, line: {{ width: 0 }}, layer: "below"
  }}));

  const traces = [];

  // Лещовите линии: тънки следи ПОД композита (цветовете от config).
  for (const lens of (FILM_DATA.lenses || [])) {{
    traces.push({{
      x: FILM_DATA.dates,
      y: lens.values,
      type: "scatter",
      mode: "lines",
      name: lens.name,
      connectgaps: false,
      opacity: 0.45,
      line: {{ color: lens.color, width: 1 }},
      hovertemplate: "%{{x|%b %Y}} " + lens.name + ": <b>%{{y:.1f}}</b><extra></extra>"
    }});
  }}

  traces.push({{
    x: FILM_DATA.dates,
    y: FILM_DATA.values,
    type: "scatter",
    mode: "lines",
    name: "композит",
    line: {{ color: "#7c6af7", width: 2.5 }},
    hovertemplate: "%{{x|%b %Y}}: <b>%{{y:.1f}}</b><extra></extra>"
  }});

  if (FILM_DATA.live) {{
    traces.push({{
      x: [FILM_DATA.live.date],
      y: [FILM_DATA.live.value],
      type: "scatter",
      mode: "markers",
      name: "днес",
      showlegend: false,
      marker: {{ color: "#7c6af7", size: 11, line: {{ color: "#0f1117", width: 2 }} }},
      hovertemplate: "%{{x|%b %Y}} (живо): <b>%{{y:.1f}}</b><extra></extra>"
    }});
  }}

  const layout = {{
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: {{ color: "#8892a4", family: "-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif" }},
    margin: {{ t: 10, r: 16, b: 40, l: 44 }},
    xaxis: {{ showgrid: false, zeroline: false, color: "#8892a4" }},
    yaxis: {{ range: [0, 100], gridcolor: "#1e2130", color: "#8892a4", dtick: 25 }},
    shapes: shapes,
    hovermode: "x unified",
    showlegend: true,
    legend: {{ orientation: "h", y: 1.14, x: 0, font: {{ size: 10 }} }}
  }};

  // Температурната лента: отделен под-panel под композита, обща x-ос.
  if (FILM_DATA.temp) {{
    traces.push({{
      x: FILM_DATA.dates,
      y: FILM_DATA.temp.values,
      type: "bar",
      name: "прегряване",
      showlegend: false,
      yaxis: "y2",
      marker: {{ color: FILM_DATA.temp.colors }},
      hovertemplate: "%{{x|%b %Y}}: <b>%{{y}}</b> бум-серии над зоната<extra></extra>"
    }});
    layout.yaxis.domain = [0.30, 1.0];
    layout.yaxis2 = {{
      domain: [0.0, 0.20],
      range: [0, FILM_DATA.temp.max],
      dtick: FILM_DATA.temp.max,
      gridcolor: "#1e2130",
      color: "#8892a4",
      anchor: "x"
    }};
    layout.xaxis.anchor = "y2";
    layout.bargap = 0.25;
    const note = document.getElementById("film-temp-note");
    if (note) note.textContent = FILM_DATA.temp.note;
  }}

  // Тензионната линия: дясна ос 0–1 върху СЪЩИЯ панел на композита.
  if (FILM_DATA.tension) {{
    traces.push({{
      x: FILM_DATA.dates,
      y: FILM_DATA.tension.values,
      type: "scatter",
      mode: "lines",
      name: FILM_DATA.tension.name,
      yaxis: "y3",
      connectgaps: false,
      opacity: 0.7,
      line: {{ color: FILM_DATA.tension.color, width: 1.2, dash: "dot" }},
      hovertemplate: "%{{x|%b %Y}}: <b>%{{y:.3f}}</b> погасена енергия<extra></extra>"
    }});
    layout.yaxis3 = {{
      overlaying: "y",
      side: "right",
      range: [0, 1],
      dtick: 0.5,
      showgrid: false,
      color: FILM_DATA.tension.color,
      tickfont: {{ size: 10 }}
    }};
    const tnote = document.getElementById("film-tension-note");
    if (tnote) tnote.textContent = FILM_DATA.tension.note;
  }}

  Plotly.newPlot("film-chart", traces, layout, {{displayModeBar: false, responsive: true}});
}})();

(function() {{
  const box = document.getElementById("wow-body");
  if (!box) return;

  if (!WOW_DATA.available) {{
    box.innerHTML = '<div class="wow-note">' + WOW_DATA.empty_note + '</div>';
    return;
  }}

  let h = '<div class="wow-since">' + WOW_DATA.since + '</div>';
  h += '<div class="wow-head"><span class="label">Композит</span>' +
       '<span class="val ' + WOW_DATA.composite_cls + '">' +
       WOW_DATA.composite_delta_str + '</span></div>';
  for (const r of WOW_DATA.rows) {{
    h += '<div class="wow-row"><span class="label">' + r.name + '</span>' +
         '<span class="val ' + r.cls + '">' + r.delta_str + '</span></div>';
  }}
  if (WOW_DATA.composition_changed) {{
    h += '<div class="wow-warn">' + WOW_DATA.composition_note + '</div>';
  }}
  box.innerHTML = h;
}})();

// Radar chart
(function() {{
  // Леща без данни (null) изпада от радара — не се рисува като „неутрално 50"
  const entries = Object.entries(MODULE_SCORES).filter(([, v]) => v !== null);
  if (!entries.length) return;
  const categories = entries.map(([k]) => BG_NAMES[k] || k);
  const values = entries.map(([, v]) => v);
  // Close the polygon
  const cats = [...categories, categories[0]];
  const vals = [...values, values[0]];

  const trace = {{
    type: "scatterpolar",
    r: vals,
    theta: cats,
    fill: "toself",
    fillcolor: "rgba(124,106,247,0.15)",
    line: {{ color: "#7c6af7", width: 2 }},
    marker: {{ color: "#7c6af7", size: 6 }},
    hovertemplate: "%{{theta}}: <b>%{{r:.1f}}</b><extra></extra>"
  }};

  const layout = {{
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: {{ color: "#8892a4" }},
    margin: {{ t: 20, r: 20, b: 20, l: 20 }},
    polar: {{
      bgcolor: "rgba(0,0,0,0)",
      radialaxis: {{ visible: true, range: [0, 100], color: "#444", gridcolor: "#2a2d3e", tickfont: {{ size: 10 }} }},
      angularaxis: {{ color: "#8892a4", gridcolor: "#2a2d3e" }}
    }},
    showlegend: false
  }};

  Plotly.newPlot("radar-chart", [trace], layout, {{displayModeBar: false, responsive: true}});
}})();

// Auto-show first chart
const firstKey = Object.keys(CHART_DATA)[0];
if (firstKey) showChart(firstKey);
</script>
</body>
</html>
"""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ HTML дашбордът е запазен в: {output_path}")
