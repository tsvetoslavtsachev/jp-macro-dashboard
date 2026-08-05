"""
run.py
======
Entry point за Japan Macro Dashboard (INIT-26).

Фамилният pipeline ред (bg-macro-dashboard, AGENT.md L39-50): fetch → derive →
score. JP v1 няма сплайс (няма ръчен seed) и няма derived серии — carry
диференциалите идват с фаза 3 и ще се родят ТУК, преди скоринга.
"""
import argparse
import sys
import logging
from datetime import date
from pathlib import Path

# Windows конзолата е cp1252 по подразбиране — без това print-овете гърмят.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from sources import build_adapters
from analysis.temperature import temperature
from analysis.tension import annihilation, ratio_str
from catalog.series import SERIES_CATALOG, series_by_source, validate_catalog
from core.primitives import apply_transform
from core.scorer import (
    compute_composite_score,
    compute_lens_reports,
    get_regime,
)


def _build_snapshot(adapters: dict, force: bool = False) -> dict:
    """
    Сглобява snapshot от всички серии.
    fetch_many сам решава кеш или мрежа по TTL — затова минава през него
    ВИНАГИ, не само при липсваща серия. Източник без адаптер (estat/boj/mof
    преди фазата си) просто не се фетчва — декларирано, не скрито.
    """
    snapshot = {}
    for source_name, adapter in adapters.items():
        specs = series_by_source(source_name)
        if not specs:
            continue
        results = adapter.fetch_many(specs, force=force)
        snapshot.update(results)
    return snapshot


def _score_everything(force: bool = False) -> tuple[dict, dict, float | None, dict]:
    """snapshot → лещови доклади → композит → режим. Единният път на всички команди."""
    adapters = build_adapters()
    snapshot = _build_snapshot(adapters, force=force)
    # Фаза 3: derive_series (carry диференциалите) се ражда ТУК, преди скоринга.
    lens_reports = compute_lens_reports(SERIES_CATALOG, snapshot)
    module_scores = {lens: rep["score"] for lens, rep in lens_reports.items()}
    composite = compute_composite_score(module_scores)
    regime = get_regime(composite)
    return snapshot, lens_reports, composite, regime


def _fmt(score) -> str:
    return f"{score:.1f}" if score is not None else "—"


def cmd_status(args):
    """Показва статуса на данните."""
    print(f"📊 Catalog: {len(SERIES_CATALOG)} series")

    snapshot, lens_reports, composite, regime = _score_everything(force=args.refresh)

    print(f"\n📈 Извлечени: {len(snapshot)} / {len(SERIES_CATALOG)} серии")

    print("\n" + "=" * 40)
    print(f"🌍 ТЕКУЩ МАКРО РЕЖИМ: {regime['name']} (Score: {_fmt(composite)}/100)")
    print("=" * 40)
    print("Скала: 50 = близката 10-годишна норма (робастен z, tanh); "
          "инфлационната леща чака e-Stat (фаза 4) и композитът се "
          "ренормализира по живите лещи.")

    # Температурният слой — колко бум-серии са над зоната си. JP v1: 0/0
    # законно (няма OPT зони преди данни-паса на фаза 6).
    temp = temperature(SERIES_CATALOG, snapshot)
    hot_str = " · ".join(
        f"{e['key']} {e['value']:.1f} > {e['hi']:.0f}" for e in temp["hot"]
    ) or "няма обявени бум-серии (OPT зоните идват с фаза 6)"
    print(f"🌡 Прегряване: {temp['n_hot']}/{temp['n_total']} ({hot_str})")

    # Тензионният слой — колко от лещовата енергия се погасява.
    tension = annihilation(lens_reports)
    print(f"⚖ Погасяване (К1): {ratio_str(tension)} — {tension['sentence']}")

    for lens, rep in lens_reports.items():
        z = rep["health_z"]
        z_str = f"z={z:+.2f}" if z is not None else "няма данни"
        n = rep["n_series"]
        print(f"  • {lens.capitalize():<10}: {_fmt(rep['score']):>5}   ({z_str}, "
              f"{n} {'серия' if n == 1 else 'серии'})")

    print("\nПоследни данни по серии (след трансформацията от каталога):")
    for key, spec in SERIES_CATALOG.items():
        res = next(
            (s for rep in lens_reports.values() for s in rep["series"] if s["key"] == key),
            None,
        )
        if key in snapshot and not snapshot[key].empty:
            s = apply_transform(snapshot[key], spec["transform"]).dropna()
            if s.empty:
                print(f"  ✗ {key:<20} | {spec['name_bg']:<52} | ЛИПСВАТ ДАННИ")
                continue
            last_date = s.index[-1].strftime("%Y-%m-%d")
            last_val = s.iloc[-1]
            n_raw = len(snapshot[key].dropna())
            score_str = _fmt(res["score"]) if res else "—"
            print(f"  ✓ {key:<20} | {spec['name_bg']:<52} | {last_date}: {last_val:>10.2f} "
                  f"| score={score_str:>5} | n={n_raw}")
        else:
            print(f"  ✗ {key:<20} | {spec['name_bg']:<52} | ЛИПСВАТ ДАННИ")

    return 0


def cmd_briefing(args):
    """HTML дашбордът + историята + журналът — идва с фаза 7 (export слоят)."""
    print("⚠ --briefing идва с фаза 7 на мандата (export слоят: "
          "weekly_briefing + methodology). Ползвай --status дотогава.")
    return 1


def cmd_export_context(args):
    """briefing_context експортът — идва с фаза 7 (export слоят)."""
    print("⚠ --export-context идва с фаза 7 на мандата (export слоят: "
          "briefing_context.py). Ползвай --status дотогава.")
    return 1


def main():
    parser = argparse.ArgumentParser(description="Japan Macro Dashboard")
    parser.add_argument("--status", action="store_true", help="Показва статуса на данните")
    parser.add_argument("--briefing", action="store_true", help="Генерира HTML дашборд (фаза 7)")
    parser.add_argument("--export-context", action="store_true",
                        help="Генерира briefing_context за LLM анализ (фаза 7)")
    parser.add_argument("--refresh", action="store_true", help="Форсира обновяване на данните")

    args = parser.parse_args()

    catalog_errors = validate_catalog()
    if catalog_errors:
        print("❌ Каталогът не е валиден:")
        for err in catalog_errors:
            print(f"  • {err}")
        return 1

    if args.briefing:
        return cmd_briefing(args)

    if args.export_context:
        return cmd_export_context(args)

    return cmd_status(args)


if __name__ == "__main__":
    sys.exit(main())
