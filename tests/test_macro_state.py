"""
tests/test_macro_state.py
=========================
Гейтовете на api export-а (мандат ORGANISM-v1, Ф1): фамилната схема +
тъждеството „api ≡ последния ред на журнала" + режимът ≡ get_regime +
йена-редовете дословни. Ако api файлът и журналът се разминат, дрилът и
сателитът тръгват от лъжа.
"""
import json
from datetime import date

import pandas as pd
import pytest

from analysis.lens_history import append_journal, load_journal
from analysis.temperature import temperature
from analysis.tension import annihilation
from analysis.yen_segment import segment_lines, yen_segment
from catalog.series import SERIES_CATALOG
from config import MACRO_REGIMES, MODULE_WEIGHTS, REGIME_KEYS
from core.scorer import compute_composite_score, compute_lens_reports, get_regime
from export.macro_state import ENGINE, REGION, SCHEMA, generate_macro_state

TODAY = date(2026, 8, 5)


def _synthetic_snapshot():
    idx = pd.date_range(end="2026-06-01", periods=300, freq="MS")
    return {key: pd.Series([1.0, 3.0] * 150, index=idx) for key in SERIES_CATALOG}


@pytest.fixture(scope="module")
def state(tmp_path_factory):
    """Синтетичният пуск 1:1 по реда на `run.py::cmd_briefing`:
    журнал ПЪРВО (в tmp — живият журнал не се пипа), api ВТОРО."""
    snapshot = _synthetic_snapshot()
    reports = compute_lens_reports(SERIES_CATALOG, snapshot)
    composite = compute_composite_score({l: r["score"] for l, r in reports.items()})
    temp = temperature(SERIES_CATALOG, snapshot)

    tmp = tmp_path_factory.mktemp("api")
    journal = append_journal(
        reports, composite, today=TODAY, path=tmp / "journal.csv", temp=temp
    )
    doc = generate_macro_state(
        str(tmp / "macro_state.json"),
        journal=journal,
        lens_reports=reports,
        regime=get_regime(composite),
        temp=temp,
        tension=annihilation(reports),
        yen=yen_segment(snapshot),
        today=TODAY,
    )
    on_disk = json.loads((tmp / "macro_state.json").read_text(encoding="utf-8"))
    return doc, on_disk, journal, reports, composite, snapshot


# ── Фамилната схема ──────────────────────────────────────────────────────────

def test_the_file_round_trips_and_matches_the_returned_doc(state):
    doc, on_disk, *_ = state
    assert on_disk == doc


def test_top_level_carries_the_family_keys(state):
    """Шаблонът на us/eu/cn: region · as_of_date · generated_at ·
    executive_summary · lenses. JP добавя своите слоеве, не маха фамилните."""
    doc, *_ = state
    for key in ("region", "as_of_date", "generated_at",
                "executive_summary", "lenses"):
        assert key in doc, key
    assert doc["region"] == REGION
    assert doc["schema"] == SCHEMA
    assert doc["engine"] == ENGINE
    assert doc["as_of_date"] == TODAY.isoformat()


def test_the_observation_badge_travels_with_the_file(state):
    doc, *_ = state
    assert "НАБЛЮДЕНИЕ, НЕ СИГНАЛ" in doc["note_bg"]


# ── Тъждеството: api ≡ последния ред на журнала ─────────────────────────────

def test_executive_summary_quotes_the_journal_row(state):
    doc, _, journal, *_ = state
    row = journal[journal["date"] == TODAY.isoformat()].iloc[-1]
    es = doc["executive_summary"]
    assert es["composite_score"] == float(row["composite"])
    assert es["n_series"] == int(row["n_series"])
    assert es["n_lenses"] == int(row["n_lenses"])
    assert es["temp_count"] == int(row["temp_count"])
    assert es["k1_ratio"] == float(row["k1_ratio"])
    assert es["composition"] == str(row["composition"])


def test_every_lens_quotes_the_journal_scores(state):
    doc, _, journal, reports, *_ = state
    row = journal[journal["date"] == TODAY.isoformat()].iloc[-1]
    assert set(doc["lenses"]) == set(MODULE_WEIGHTS)
    for lens, block in doc["lenses"].items():
        assert block["score"] == float(row[f"score_{lens}"]), lens
        assert block["health_z"] == float(row[f"z_{lens}"]), lens
        assert block["n_series"] == reports[lens]["n_series"], lens


def test_building_without_a_journal_row_fails_loud(state):
    """Викане ПРЕДИ append_journal е грешен ред на пуска — не тиха втора
    сметка, а изрична грешка."""
    from export.macro_state import build_macro_state
    doc, _, journal, reports, composite, snapshot = state
    with pytest.raises(ValueError, match="append_journal"):
        build_macro_state(
            journal=journal[journal["date"] != TODAY.isoformat()],
            lens_reports=reports,
            regime=get_regime(composite),
            temp=temperature(SERIES_CATALOG, snapshot),
            tension=annihilation(reports),
            yen=yen_segment(snapshot),
            today=TODAY,
        )


# ── Режимът ≡ get_regime ─────────────────────────────────────────────────────

def test_the_regime_label_comes_from_get_regime(state):
    doc, _, _, _, composite, _ = state
    regime = get_regime(composite)
    es = doc["executive_summary"]
    assert es["regime_label_bg"] == regime["name"]
    assert es["regime_color"] == regime["color"]
    assert es["regime_key"] == REGIME_KEYS[regime["name"]]


def test_every_regime_name_has_a_latin_key():
    """Нов режим в MACRO_REGIMES без ключ пада ТУК, не в тих null към
    консуматорите."""
    for _, name, _ in MACRO_REGIMES:
        assert name in REGIME_KEYS, name
    assert "НЯМА ДАННИ" in REGIME_KEYS  # стражът на get_regime


# ── Йена-слоят: дословните редове ────────────────────────────────────────────

def test_yen_layer_lines_are_segment_lines_verbatim(state):
    """ЕДИН източник на формулировките (AGENT.md): api файлът носи същите
    редове, които виждат --status и briefing_context."""
    doc, _, _, _, _, snapshot = state
    assert doc["yen_layer_lines"] == segment_lines(yen_segment(snapshot))


def test_yen_layer_carries_all_six_blocks(state):
    doc, *_ = state
    for block in ("rates", "fx", "funding", "carry", "positioning", "flows"):
        assert block in doc["yen_layer"], block


# ── Температурата ────────────────────────────────────────────────────────────

def test_the_temperature_block_matches_the_layer(state):
    doc, _, _, _, _, snapshot = state
    temp = temperature(SERIES_CATALOG, snapshot)
    assert doc["temperature"]["n_hot"] == temp["n_hot"]
    assert doc["temperature"]["n_total"] == temp["n_total"]
    assert doc["executive_summary"]["temp_count"] == temp["n_hot"]


# ── Живият пас (комитнатият кеш + живият журнал) ─────────────────────────────

@pytest.fixture(scope="module")
def live_state(tmp_path_factory):
    """Живата верига по `cmd_briefing`, но журналът се чете, НЕ се дописва:
    api числата срещу ПОСЛЕДНИЯ записан PIT ред. Нула мрежови заявки."""
    from catalog.series import series_by_source
    from sources import build_adapters
    from sources.derived import derive_series

    snapshot = {}
    for source_name, adapter in build_adapters().items():
        keys = [spec["key"] for spec in series_by_source(source_name)]
        snapshot.update(adapter.get_snapshot(keys))
    snapshot = derive_series(snapshot)
    if len(snapshot) < len(SERIES_CATALOG):
        pytest.skip("кешът в data/ е непълен — тестът иска комитнатия кеш")

    journal = load_journal()
    if journal.empty:
        pytest.skip("живият журнал е празен")
    last_date = date.fromisoformat(str(journal["date"].iloc[-1]))

    reports = compute_lens_reports(SERIES_CATALOG, snapshot)
    composite = compute_composite_score({l: r["score"] for l, r in reports.items()})
    doc = generate_macro_state(
        str(tmp_path_factory.mktemp("live_api") / "macro_state.json"),
        journal=journal,
        lens_reports=reports,
        regime=get_regime(composite),
        temp=temperature(SERIES_CATALOG, snapshot),
        tension=annihilation(reports),
        yen=yen_segment(snapshot),
        today=last_date,
    )
    return doc, journal


def test_the_live_api_quotes_the_live_journal(live_state):
    doc, journal = live_state
    row = journal.iloc[-1]
    es = doc["executive_summary"]
    assert es["composite_score"] == float(row["composite"])
    assert es["composition"] == str(row["composition"])
    for lens in MODULE_WEIGHTS:
        assert doc["lenses"][lens]["score"] == pytest.approx(
            float(row[f"score_{lens}"])), lens


def test_the_live_api_regime_matches_the_journal_composite(live_state):
    """Режимният етикет в api-то е get_regime върху журналния композит —
    консуматорът никога не дублира праговете (мотивът на Ф1)."""
    doc, journal = live_state
    regime = get_regime(float(journal.iloc[-1]["composite"]))
    assert doc["executive_summary"]["regime_label_bg"] == regime["name"]
    assert doc["executive_summary"]["regime_key"] == REGIME_KEYS[regime["name"]]
