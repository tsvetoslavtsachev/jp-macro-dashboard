"""ПРОЛЕТР4 (26.11.2026, реш. Ц. ЯП-1 и ЯП-2): таванът ±6, застоялите извън сбора, API-то на BoJ."""
import numpy as np
import pandas as pd

from core.scorer import SERIES_Z_CAP, compute_lens_reports
from sources.boj_adapter import parse_boj_api


def _spec(lens, pg, sched="monthly"):
    return {"lens": [lens], "peer_group": pg, "transform": "level", "release_schedule": sched}


def _monthly(n, end="2026-10-01", last=None, seed=0):
    idx = pd.date_range(end=end, periods=n, freq="MS")
    rng = np.random.default_rng(seed)
    s = pd.Series(1.0 + rng.normal(0, 0.05, n), index=idx)
    if last is not None:
        s.iloc[-1] = last
    return s


def test_series_z_is_capped_before_the_lens_sum():
    cat = {"A": _spec("credit", "yields"), "B": _spec("credit", "depth")}
    snap = {"A": _monthly(180, last=50.0), "B": _monthly(180, seed=1)}
    rep = compute_lens_reports(cat, snap)["credit"]
    pg = {p["name"]: p for p in rep["peer_groups"]}
    assert abs(pg["yields"]["health_z"]) <= SERIES_Z_CAP + 1e-9
    a = next(s for s in rep["series"] if s["key"] == "A")
    assert a["capped"] is True
    assert abs(a["health_z"]) > SERIES_Z_CAP      # серията пази истинския си z за показване


def test_stale_series_shown_but_out_of_the_sum():
    cat = {"FRESH": _spec("property", "prices"), "OLD": _spec("property", "prices")}
    snap = {"FRESH": _monthly(150), "OLD": _monthly(150, end="2026-03-01", seed=2)}
    rep = compute_lens_reports(cat, snap)["property"]
    old = next(s for s in rep["series"] if s["key"] == "OLD")
    assert old["stale"] is True
    assert rep["n_series"] == 1


def test_lens_without_fresh_series_has_no_score():
    cat = {"OLD": _spec("property", "prices", "quarterly"), "Q": _spec("growth", "gdp", "quarterly")}
    q = pd.Series(1.0, index=pd.date_range(end="2026-07-01", periods=60, freq="QS")) + np.linspace(0, 1, 60)
    old = pd.Series(1.0, index=pd.date_range(end="2025-07-01", periods=60, freq="QS")) + np.linspace(0, 1, 60)
    rep = compute_lens_reports(cat, {"OLD": old, "Q": q})
    assert rep["property"]["score"] is None


def test_parse_boj_api_quarterly_dates():
    payload = {"RESULTSET": [{"SERIES_CODE": "TK99F1000601GCQ01000", "FREQUENCY": "QUARTERLY",
                              "VALUES": {"SURVEY_DATES": [202601, 202602, 202603], "VALUES": [17, None, 24]}}]}
    s = parse_boj_api(payload)
    assert list(s.index.strftime("%Y-%m-%d")) == ["2026-01-01", "2026-07-01"]
    assert s.iloc[-1] == 24.0


def test_parse_boj_api_empty_raises():
    try:
        parse_boj_api({"RESULTSET": [], "MESSAGEID": "M181001E", "MESSAGE": "x"})
    except ValueError:
        return
    raise AssertionError("празен RESULTSET трябва да гърми с име")
