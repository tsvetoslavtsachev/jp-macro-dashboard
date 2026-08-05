"""
tests/test_form_canon.py
========================
ФОРМА-КАНОН пасът на JP повърхността (фамилният стандарт, мандат №38 §А5).

Петте правила: изводът първо · линк на всяко фетчвано име към първоизточника ·
обяснение на място · един речник · застоялото наблюдение маркирано.
"""
from datetime import date

import pandas as pd
import pytest

from catalog.series import SERIES_CATALOG
from config import (
    FRED_SERIES_URL,
    LENS_BADGE_COLORS,
    LENS_BADGES_BG,
    LENS_LINE_COLORS,
    LENS_NAMES_BG,
    LENS_SUBJECTS_BG,
    MODULE_WEIGHTS,
    MOF_FLOWS_PAGE,
    MOF_JGB_PAGE,
    YEN_LAYER_NAME_BG,
)
from core.display import (
    BOJ_STAT_SEARCH,
    boj_series_url,
    estat_series_url,
    fred_series_url,
    inflation_anchor,
    is_stale,
    mof_series_url,
    months_old,
    source_url,
    verdict_sentence,
)
from core.scorer import compute_composite_score, compute_lens_reports, get_regime
from export.methodology import (
    METHODOLOGY_HREF,
    METHODOLOGY_TEASER,
    METHODOLOGY_TITLE,
    generate_methodology,
)
from export.weekly_briefing import generate_html


# ── Линк на всяко име (правило 2) ────────────────────────────────────────────

def test_fred_series_url_uses_the_config_template():
    url = fred_series_url("JPNRGDPEXP")
    assert url == FRED_SERIES_URL.format(series_id="JPNRGDPEXP")
    assert url == "https://fred.stlouisfed.org/series/JPNRGDPEXP"
    assert fred_series_url("") == ""


def test_estat_url_uses_the_stats_data_id_before_the_query():
    """Каталожното id носи филтрите след `?` — линкът стъпва на таблицата."""
    spec = SERIES_CATALOG["JP_CPI"]
    url = estat_series_url(spec["id"])
    assert url == (
        "https://www.e-stat.go.jp/en/stat-search/database?statdisp_id=0003427113"
    )
    assert estat_series_url("") == ""


def test_boj_url_is_the_stat_search_portal():
    """Flat файловете нямат страница-на-серия — порталът е първоизточникът."""
    assert boj_series_url("bp:BPBP6JYNCB") == BOJ_STAT_SEARCH
    assert boj_series_url("cgpi:PRCG20_2200000000") == BOJ_STAT_SEARCH


def test_mof_url_branches_on_the_recipe_prefix():
    assert mof_series_url("jgb:2Y") == MOF_JGB_PAGE
    assert mof_series_url("jgb:10Y") == MOF_JGB_PAGE
    assert mof_series_url("flows:nonres_equity_net") == MOF_FLOWS_PAGE
    assert mof_series_url("flows:res_ltdebt_net") == MOF_FLOWS_PAGE


def test_every_catalog_series_yields_a_first_source_url():
    """Всяко ФЕТЧВАНО име води към първоизточника си; derived — празен линк.

    Изведената серия няма първоизточник — нейното „id" е рецепта, не адрес.
    Липсващ линк е по-честен от линк, който сочи някъде, откъдето числото
    не идва.
    """
    expected_prefix = {
        "fred": "https://fred.stlouisfed.org/series/",
        "estat": "https://www.e-stat.go.jp/en/stat-search/database?statdisp_id=",
        "boj": "https://www.stat-search.boj.or.jp/",
        "mof": "https://www.mof.go.jp/",
    }
    for key, spec in SERIES_CATALOG.items():
        source = spec["source"]
        if source == "derived":
            assert source_url(source, spec["id"]) == "", key
            continue
        assert source in expected_prefix, key
        url = source_url(source, spec["id"])
        assert url.startswith(expected_prefix[source]), key


# ── Изводът първо (правило 1) ────────────────────────────────────────────────

def _reports(**scores):
    return {lens: {"score": scores.get(lens)} for lens in MODULE_WEIGHTS}


def test_verdict_names_the_heaviest_and_the_strongest_lens():
    reports = _reports(inflation=68.4, labor=79.2, growth=59.6,
                       credit=0.4, external=73.1, property=67.7)
    assert verdict_sentence(reports) == (
        "Тежи кредитът (0.4), крепи пазарът на труда (79.2)."
    )


def test_verdict_says_so_when_there_is_nothing_to_conclude():
    assert verdict_sentence(_reports()) == "Няма достатъчно данни за извод."


def test_verdict_handles_a_single_measured_lens():
    sentence = verdict_sentence(_reports(labor=67.4))
    assert "пазарът на труда" in sentence
    assert "67.4" in sentence


def test_context_states_the_composite_before_any_lens_section(context):
    """Правило 1 в експорта: композитът/режимът ПРЕДИ лещовите секции."""
    text, _, _ = context
    composite_at = text.index("## Композитен Macro Score")
    assert "**Режим:**" in text
    for name in LENS_NAMES_BG.values():
        assert composite_at < text.index(f"## {name}"), name


# ── Един речник (правило 4) ──────────────────────────────────────────────────

def test_one_vocabulary_covers_every_lens():
    for lens in MODULE_WEIGHTS:
        assert lens in LENS_NAMES_BG
        assert lens in LENS_BADGES_BG
        assert lens in LENS_SUBJECTS_BG


def test_lens_badges_are_bulgarian():
    assert set(LENS_BADGES_BG.values()) == {
        "растеж", "инфлация", "труд", "кредит", "външен", "имоти"
    }


def test_every_lens_has_a_colour_in_the_single_palette():
    """Палитрата е ЕДНА (config) — и всяка леща от теглата има ред в нея."""
    for lens in MODULE_WEIGHTS:
        assert lens in LENS_LINE_COLORS, lens
        assert lens in LENS_BADGE_COLORS, lens
        bg, fg = LENS_BADGE_COLORS[lens]
        assert bg.startswith("#") and fg.startswith("#"), lens


# ── Застояло наблюдение (правило 5) ──────────────────────────────────────────

def test_monthly_observation_goes_stale_after_two_months():
    today = date(2026, 8, 5)
    assert is_stale("2026-07-01", "monthly", today) is False
    assert is_stale("2026-06-01", "monthly", today) is False
    assert is_stale("2026-05-01", "monthly", today) is True


def test_quarterly_observation_goes_stale_after_six_months():
    today = date(2026, 8, 5)
    assert is_stale("2026-02-01", "quarterly", today) is False
    assert is_stale("2026-01-01", "quarterly", today) is True


def test_daily_and_weekly_observations_go_stale_after_one_month():
    today = date(2026, 8, 5)
    assert is_stale("2026-07-31", "daily", today) is False
    assert is_stale("2026-06-15", "daily", today) is True
    assert is_stale("2026-06-15", "weekly", today) is True


def test_months_old_counts_calendar_months():
    assert months_old("2026-01-01", date(2026, 8, 5)) == 7
    assert months_old(None, date(2026, 8, 5)) is None


def test_context_marks_stale_observations_in_the_lens_tables(context_stale):
    """Синтетичен snapshot + днешна дата далеч напред → всеки ред носи ⚠."""
    text = context_stale
    growth_section = text.split(f"## {LENS_NAMES_BG['growth']}")[1].split("\n---\n")[0]
    table_rows = [
        l for l in growth_section.splitlines()
        if l.startswith("| ") and "Показател" not in l
    ]
    assert table_rows, "лещовата таблица липсва"
    for row in table_rows:
        assert "⚠" in row, row


# ── Котвеният прочит (обяснение на място) ────────────────────────────────────

def test_inflation_anchor_zones_follow_the_pp_bands():
    assert inflation_anchor(2.0)["zone"] == "green"
    assert inflation_anchor(2.9)["zone"] == "green"
    assert inflation_anchor(3.5)["zone"] == "yellow"
    assert inflation_anchor(5.0)["zone"] == "red"


def test_inflation_anchor_reads_deflation_through_the_same_zones():
    """Дефлационната посока минава огледално — в Япония тя е изживяна история."""
    assert inflation_anchor(1.2)["zone"] == "green"
    assert inflation_anchor(0.5)["zone"] == "yellow"
    assert inflation_anchor(-0.5)["zone"] == "red"
    assert "под целта" in inflation_anchor(0.5)["gap_phrase"]


# ── Фикстурите ───────────────────────────────────────────────────────────────

def _synthetic_snapshot():
    idx = pd.date_range(end="2026-06-01", periods=300, freq="MS")
    return {
        key: pd.Series([1.0, 3.0] * 150, index=idx)
        for key in SERIES_CATALOG
    }


@pytest.fixture(scope="module")
def scored():
    snapshot = _synthetic_snapshot()
    reports = compute_lens_reports(SERIES_CATALOG, snapshot)
    composite = compute_composite_score({l: r["score"] for l, r in reports.items()})
    return snapshot, reports, composite


@pytest.fixture(scope="module")
def rendered(scored, tmp_path_factory):
    snapshot, reports, composite = scored
    out = tmp_path_factory.mktemp("face") / "index.html"
    generate_html(snapshot, reports, composite, get_regime(composite), str(out))
    return out.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def context(scored, tmp_path_factory):
    from export.briefing_context import generate_briefing_context

    snapshot, reports, composite = scored
    out = tmp_path_factory.mktemp("ctx") / "briefing_context.md"
    generate_briefing_context(
        snapshot=snapshot,
        lens_reports=reports,
        composite=composite,
        regime=get_regime(composite),
        output_path=str(out),
        today=date(2026, 8, 5),
    )
    return out.read_text(encoding="utf-8"), reports, composite


@pytest.fixture(scope="module")
def context_stale(scored, tmp_path_factory):
    """Същият snapshot, но „днес" е далеч напред → всичко е застояло."""
    from export.briefing_context import generate_briefing_context

    snapshot, reports, composite = scored
    out = tmp_path_factory.mktemp("ctx_stale") / "briefing_context.md"
    generate_briefing_context(
        snapshot=snapshot,
        lens_reports=reports,
        composite=composite,
        regime=get_regime(composite),
        output_path=str(out),
        today=date(2027, 8, 5),
    )
    return out.read_text(encoding="utf-8")


# ── Лицето ───────────────────────────────────────────────────────────────────

def test_html_links_every_indicator_name_to_the_source(rendered):
    """Изведената серия няма адрес → няма и линк; останалите — да."""
    for key, spec in SERIES_CATALOG.items():
        if spec["source"] == "derived":
            continue
        assert source_url(spec["source"], spec["id"]) in rendered, key


def test_html_carries_the_narrative_hint_as_a_tooltip(rendered):
    """Обяснение на място (правило 3): хинтът пътува с името."""
    import html as _html
    for spec in SERIES_CATALOG.values():
        hint = spec.get("narrative_hint", "")
        if hint:
            assert f'title="{_html.escape(hint)}"' in rendered, spec["name_bg"]


def test_html_shows_the_verdict_sentence_first(rendered):
    assert 'class="verdict"' in rendered
    assert "Тежи" in rendered and "крепи" in rendered


def test_html_generates_the_lens_palette_from_config(rendered):
    """Правило 4: CSS баджовете се раждат от config речника, не се пишат."""
    for lens in MODULE_WEIGHTS:
        bg, fg = LENS_BADGE_COLORS[lens]
        assert f".lens-{lens} {{ background:{bg}; color:{fg}; }}" in rendered, lens
    for lens, name in LENS_NAMES_BG.items():
        assert name in rendered, lens


def test_html_carries_the_yen_layer_block_with_all_six_blocks(rendered):
    """Диференциаторът: йена-картата с шестте блока от segment_lines."""
    assert YEN_LAYER_NAME_BG in rendered
    assert 'class="lens-badge lens-yen"' in rendered
    for token in ("Лихви:", "Валута:", "Финансиране:", "Carry:",
                  "Позициониране:", "Потоци 4w:"):
        assert token in rendered, token


def test_the_face_links_to_the_methodology_page_instead_of_carrying_it(rendered):
    """Методологията е на ЕДНА клика — линк-карта + тийзър, не блок на лицето."""
    assert '<details class="methodology"' not in rendered
    assert f'href="{METHODOLOGY_HREF}"' in rendered
    assert METHODOLOGY_TITLE in rendered
    assert METHODOLOGY_TEASER in rendered


@pytest.fixture(scope="module")
def methodology(tmp_path_factory):
    out = tmp_path_factory.mktemp("meth") / "methodology.html"
    generate_methodology(str(out))
    return out.read_text(encoding="utf-8")


def test_methodology_page_stands_on_its_own(methodology):
    assert METHODOLOGY_TITLE in methodology
    assert 'href="index.html"' in methodology
    assert "Кредитната леща и нормализацията" in methodology
    assert YEN_LAYER_NAME_BG in methodology
