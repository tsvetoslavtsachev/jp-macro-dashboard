"""
Фаза 6 гейтове: OPT зоните са ПИННАТИ с точните си числа, всяка носи
провенанс, и приемният изпит минава върху КОМИТНАТИЯ кеш (offline —
get_snapshot чете кеша, никога мрежата):

    балонът 1985-90 СВЕТИ · дефлацията 1995-2012 и абеномиката 2013-19
    МЪЛЧАТ (извън декларирания GFC знаменател) · текущата ера: имоти топли
    БЕЗ кредитен крак.

Ако утре някой мести праг, този файл го кара да мести и провенанса, и
пиннатите бройки — със съзнателен нов мандат, не мълчаливо.
"""
import pytest

from catalog.polarity import (
    OPT_PROVENANCE,
    POLARITY,
    opt_keys,
)
from catalog.series import SERIES_CATALOG
from core.primitives import apply_transform
from sources import build_adapters

EPOCHS_PASS = {
    "bubble":    ("1985-01-01", "1990-12-31"),
    "deflation": ("1995-01-01", "2012-12-31"),
    "abenomics": ("2013-01-01", "2019-12-31"),
}


# ── Зоните са пиннати ────────────────────────────────────────────────────────

def test_the_three_zones_are_pinned_exactly():
    assert POLARITY["JP_RPPI"] == ("OPT", 0.0, 4.0, 4.0)
    assert POLARITY["JP_CREDIT_GDP_NFC"] == ("OPT", 0.0, 4.5, 3.0)
    assert POLARITY["JP_CREDIT_GDP_HH"] == ("OPT", 0.0, 3.0, 3.0)


def test_opt_keys_derive_from_polarity_not_a_second_list():
    assert opt_keys() == ["JP_CREDIT_GDP_NFC", "JP_CREDIT_GDP_HH", "JP_RPPI"]


def test_every_zone_carries_its_provenance():
    for key in opt_keys():
        assert key in OPT_PROVENANCE, f"{key}: зона без провенанс"
        assert OPT_PROVENANCE[key].strip()


# ── Приемният гейт — върху комитнатия кеш ────────────────────────────────────

@pytest.fixture(scope="module")
def transformed():
    """Трансформираните OPT серии от кеша (offline)."""
    adapters = build_adapters()
    out = {}
    for adapter in adapters.values():
        out.update(adapter.get_snapshot(opt_keys()))
    missing = [k for k in opt_keys() if k not in out]
    assert not missing, f"кешът не носи {missing} — комитни data/ кешовете"
    return {
        k: apply_transform(out[k], SERIES_CATALOG[k]["transform"]).dropna()
        for k in opt_keys()
    }


def _count_over(s, hi, epoch):
    a, b = EPOCHS_PASS[epoch]
    part = s.loc[a:b]
    return int((part > hi).sum()), len(part)


def test_bubble_era_lights_property_16_of_24(transformed):
    over, n = _count_over(transformed["JP_RPPI"], 4.0, "bubble")
    assert (over, n) == (16, 24)


def test_bubble_era_lights_both_credit_legs(transformed):
    assert _count_over(transformed["JP_CREDIT_GDP_NFC"], 4.5, "bubble") == (10, 24)
    assert _count_over(transformed["JP_CREDIT_GDP_HH"], 3.0, "bubble") == (15, 24)


def test_calm_epochs_stay_silent_for_property(transformed):
    assert _count_over(transformed["JP_RPPI"], 4.0, "deflation") == (0, 72)
    assert _count_over(transformed["JP_RPPI"], 4.0, "abenomics") == (0, 28)


def test_abenomics_stays_silent_for_credit(transformed):
    assert _count_over(transformed["JP_CREDIT_GDP_NFC"], 4.5, "abenomics")[0] == 0
    assert _count_over(transformed["JP_CREDIT_GDP_HH"], 3.0, "abenomics")[0] == 0


def test_deflation_credit_noise_is_exactly_the_declared_gfc_denominator(transformed):
    # 4/72 и в двата крака, всичките 2008Q4-2010Q1 — декларираният клас
    # фалшив позитив (БВП колапс, не кредитен бум). Повече от 4 = нов режим
    # на шума → зоната иска нов мандат.
    for key, hi in (("JP_CREDIT_GDP_NFC", 4.5), ("JP_CREDIT_GDP_HH", 3.0)):
        s = transformed[key]
        part = s.loc["1995-01-01":"2012-12-31"]
        over = part[part > hi]
        assert len(over) == 4, key
        assert all("2008" <= d.strftime("%Y") <= "2010" for d in over.index), key


def test_current_era_property_is_warm_without_a_credit_leg(transformed):
    # Дискриминаторът на двойката: имоти топли, кредитът мълчи.
    rppi = transformed["JP_RPPI"].loc["2022-01-01":]
    assert (rppi > 4.0).sum() > 0
    for key, hi in (("JP_CREDIT_GDP_NFC", 4.5), ("JP_CREDIT_GDP_HH", 3.0)):
        cur = transformed[key].loc["2022-01-01":]
        assert (cur > hi).sum() == 0, key
