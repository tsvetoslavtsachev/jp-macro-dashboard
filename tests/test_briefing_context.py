"""
tests/test_briefing_context.py
==============================
Горивото на бъдещия скил `macro-deep-brief-jp` (фамилният стандарт §А4).

Числата в експорта идват от скоринга и слоевете — нула ръчни константи. Ако
таблицата и `--status` се разминат, анализът за клиент тръгва от лъжа.
JP спецификата: йена-секцията носи редовете на `segment_lines` ДОСЛОВНО.
"""
from datetime import date

import pandas as pd
import pytest

from analysis.temperature import BUBBLE_PAIR_LABEL_BG, temperature
from analysis.tension import annihilation
from analysis.yen_segment import segment_lines, yen_segment
from catalog.polarity import OPT_PROVENANCE, OPT_SOURCE_NOTE, opt_keys
from catalog.series import SERIES_CATALOG
from config import LENS_NAMES_BG
from core.display import inflation_anchors
from core.scorer import compute_composite_score, compute_lens_reports, get_regime
from export.briefing_context import DATA_QUALITY_NOTES, generate_briefing_context


def _synthetic_snapshot():
    idx = pd.date_range(end="2026-06-01", periods=300, freq="MS")
    return {key: pd.Series([1.0, 3.0] * 150, index=idx) for key in SERIES_CATALOG}


@pytest.fixture(scope="module")
def context(tmp_path_factory):
    snapshot = _synthetic_snapshot()
    reports = compute_lens_reports(SERIES_CATALOG, snapshot)
    composite = compute_composite_score({l: r["score"] for l, r in reports.items()})
    out = tmp_path_factory.mktemp("ctx") / "briefing_context_2026-08-05.md"
    generate_briefing_context(
        snapshot=snapshot,
        lens_reports=reports,
        composite=composite,
        regime=get_regime(composite),
        output_path=str(out),
        today=date(2026, 8, 5),
        temp=temperature(SERIES_CATALOG, snapshot),
        tension=annihilation(reports),
    )
    return out.read_text(encoding="utf-8"), snapshot, reports, composite


@pytest.fixture(scope="module")
def live_context(tmp_path_factory):
    """Живият експорт 1:1 по `run.py::cmd_export_context` — от комитнатия кеш,
    с ВСИЧКИ живи секции (историята + WoW от журнала + температурата +
    тензията + йена-слоя). Нула мрежови заявки; датата е пинната за
    детерминизъм.
    """
    from analysis.lens_history import build_history, load_journal, wow_delta
    from catalog.series import series_by_source
    from sources import build_adapters
    from sources.derived import derive_series

    snapshot = {}
    for source_name, adapter in build_adapters().items():
        keys = [spec["key"] for spec in series_by_source(source_name)]
        snapshot.update(adapter.get_snapshot(keys))
    # Живата верига: fetch (кеш) → derive. Проверката за пълнота е СЛЕД нея —
    # изведените серии не идват от адаптер.
    snapshot = derive_series(snapshot)
    if len(snapshot) < len(SERIES_CATALOG):
        pytest.skip("кешът в data/ е непълен — тестът иска комитнатия кеш")

    reports = compute_lens_reports(SERIES_CATALOG, snapshot)
    composite = compute_composite_score({l: r["score"] for l, r in reports.items()})
    out = tmp_path_factory.mktemp("live_ctx") / "briefing_context.md"
    generate_briefing_context(
        snapshot=snapshot,
        lens_reports=reports,
        composite=composite,
        regime=get_regime(composite),
        output_path=str(out),
        today=date(2026, 8, 5),
        history=build_history(SERIES_CATALOG, snapshot),
        wow=wow_delta(load_journal()),
        temp=temperature(SERIES_CATALOG, snapshot),
        tension=annihilation(reports),
    )
    return out.read_text(encoding="utf-8")


# ── Формата ──────────────────────────────────────────────────────────────────

def test_context_file_is_written(context):
    text, _, _, _ = context
    assert text.startswith("# 🇯🇵 Japan Macro Dashboard")
    assert "**Дата:** 2026-08-05" in text


def test_context_carries_every_lens(context):
    """Речникът е един — колкото лещи има в него, толкова секции в експорта."""
    text, _, _, _ = context
    for name in LENS_NAMES_BG.values():
        assert f"## {name}" in text
        assert f"| {name} |" in text


def test_context_composite_matches_the_scoring(context):
    text, _, _, composite = context
    assert f"## Композитен Macro Score: {composite:.1f} / 100" in text


def test_context_series_scores_match_the_scoring(context):
    text, _, reports, _ = context
    for rep in reports.values():
        for s in rep["series"]:
            if s["score"] is not None:
                assert f"| {s['name_bg']} |" in text
                assert f"| {s['score']:.1f} |" in text


def test_context_tables_have_the_mandated_columns(context):
    text, _, _, _ = context
    assert "| Показател | Стойност | Score | Данни към |" in text


def test_context_carries_the_narrative_hints(context):
    text, _, _, _ = context
    hint = SERIES_CATALOG["JP_CPI_CORE"]["narrative_hint"]
    assert hint in text


def test_context_limits_hints_to_two_per_lens(context):
    text, _, _, _ = context
    growth_section = text.split(f"## {LENS_NAMES_BG['growth']}")[1].split("\n---\n")[0]
    bullets = [l for l in growth_section.splitlines() if l.startswith("- ")]
    assert len(bullets) <= 2


# ── Йена-секцията: диференциаторът на JP ─────────────────────────────────────

def test_context_carries_the_yen_layer_section(context):
    text, _, _, _ = context
    assert "## Йена-слоят" in text


def test_yen_section_carries_all_six_blocks(context):
    """Шестте блока: лихви · валута · финансиране · carry · позициониране ·
    потоци."""
    text, _, _, _ = context
    yen_section = text.split("## Йена-слоят")[1].split("\n---\n")[0]
    for token in ("Лихви:", "Валута:", "Финансиране:", "Carry:",
                  "Позициониране:", "Потоци 4w:"):
        assert token in yen_section, token


def test_yen_section_quotes_segment_lines_verbatim(context):
    """ЕДИН източник на формулировките: редовете идват от segment_lines,
    не се преписват."""
    text, snapshot, _, _ = context
    for line in segment_lines(yen_segment(snapshot))[1:]:
        assert line.strip() in text, line


# ── Котвеният прочит под инфлационната секция ────────────────────────────────

def test_inflation_anchor_block_sits_under_the_inflation_section(context):
    text, snapshot, _, _ = context
    section = text.split(f"## {LENS_NAMES_BG['inflation']}")[1].split("\n---\n")[0]
    assert "**Котвеният прочит (абсолютни пп от целта на BOJ):**" in section
    voices = inflation_anchors(snapshot)
    assert voices["anchors"], "котвите липсват от синтетичния snapshot"
    for a in voices["anchors"]:
        assert a["gap_phrase"] in section, a["key"]
    assert voices["disclaimer"] in section


# ── Температурният слой + зоните ─────────────────────────────────────────────

def test_context_carries_the_temperature_section(context):
    text, _, _, _ = context
    assert "## Температурният слой:" in text
    assert OPT_SOURCE_NOTE in text


def test_every_opt_zone_appears_with_its_provenance(context):
    """Праговете пътуват с провенанса си, не като голи числа."""
    text, _, _, _ = context
    assert opt_keys(), "няма OPT зони — фаза 6 не е стигнала дотук"
    for key in opt_keys():
        assert SERIES_CATALOG[key]["name_bg"] in text, key
        assert OPT_PROVENANCE[key] in text, key


def test_context_carries_the_bubble_pair_reading(context):
    text, _, _, _ = context
    assert BUBBLE_PAIR_LABEL_BG in text


# ── Тензионният слой ─────────────────────────────────────────────────────────

def test_context_carries_the_tension_section_with_the_receipt(context):
    text, _, reports, _ = context
    tension = annihilation(reports)
    assert "## Тензионният слой (К1 „Погасяването“):" in text
    assert tension["sentence"] in text
    assert "**Falsifier:**" in text


# ── Бележките за качеството ──────────────────────────────────────────────────

def test_context_carries_the_data_quality_notes(context):
    text, _, _, _ = context
    assert "## ⚠ Бележки за качеството на данните" in text
    assert len(DATA_QUALITY_NOTES) >= 12


def test_data_quality_notes_name_the_known_traps():
    joined = " ".join(DATA_QUALITY_NOTES)
    for token in ("OECD-MEI", "IRSTCI01", "Cabinet Office", "e-Stat", "BIS",
                  "GFC", "CGPI", "Shift-JIS", "data-core", "BOJ BoP",
                  "IMF WEO", "Tankan", "basis", "GYSAM"):
        assert token in joined, token


def test_data_quality_notes_explain_the_transform_lineage():
    """Анализаторът трябва да знае кой темп е сметнат в уреда и кой идва готов."""
    joined = " ".join(DATA_QUALITY_NOTES)
    assert "вече като г/г темпове" in joined.lower() or "ВЕЧЕ като г/г темпове" in joined
    assert "дневните серии" in joined.lower()


def test_context_footer_names_all_the_sources(context):
    text, _, _, _ = context
    footer = text.rsplit("---", 1)[1]
    for token in ("FRED", "e-Stat", "BOJ", "MOF", "BIS", "data-core", "CFTC"):
        assert token in footer, token


# ── Живият експорт ───────────────────────────────────────────────────────────

def test_the_live_context_stays_compact(live_context):
    """Компактният фамилен модел: таванът е тревога, не бюджет — гърми при
    следващата НОВА секция, не при седмичната порция числа."""
    assert len(live_context.encode("utf-8")) < 60_000


def test_the_live_context_carries_the_history_and_yen_numbers(live_context):
    """Живият файл носи и реконструкцията, и йена-числата от кеша."""
    assert "## Композитът през времето — реконструирана история" in live_context
    assert "## Йена-слоят" in live_context
    assert "COT JPY net" in live_context
