"""
sources/_base.py
================
Shared base за data source adapter-и (ECB, Eurostat, OECD).

Експонира:
  - BaseAdapter (cache I/O, retry, fresh check, status introspection)
  - подкласовете имплементират само _fetch_remote(series_key, source_id) -> pd.Series

Cache формат (JSON):
  {series_key: {
      "source_id": str,            # ECB flowref/key, Eurostat dataset+filter
      "schedule": str,             # weekly/monthly/quarterly/annually
      "last_fetched": ISO datetime,
      "last_observation": "YYYY-MM-DD" or None,
      "n_observations": int,
      "data": {"YYYY-MM-DD": float, ...}
  }}

Retry класификация (transient vs permanent) е същата като FRED adapter:
  - HTTP 5xx / timeout / connection reset → transient (retry)
  - HTTP 4xx / 404 / Bad Request → permanent (fail fast)
  - Unknown → transient (консервативно)
"""
from __future__ import annotations

import json
import logging
import time
import warnings
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ============================================================
# CONFIG
# ============================================================

CACHE_TTL_DAYS = {
    "daily":      1,   # JP разширение: дневните серии (USDJPY, Nikkei, DGS2/10)
    "weekly":     3,
    "monthly":   10,
    "quarterly": 30,
    "annually":  90,
}

DEFAULT_RETRY_BACKOFF = [2, 5, 15]  # секунди между опитите

PERMANENT_ERROR_MARKERS = (
    "Bad Request",
    "does not exist",
    "Not Found",
    " 400",
    " 404",
)

TRANSIENT_ERROR_MARKERS = (
    " 500",
    " 502",
    " 503",
    " 504",
    "Internal Server Error",
    "Bad Gateway",
    "Service Unavailable",
    "Gateway Timeout",
    "Connection reset",
    "Connection aborted",
    "timed out",
    "timeout",
)


def classify_fetch_error(err: Exception) -> str:
    """Класифицира HTTP грешка като 'transient' (retry) или 'permanent' (fail fast)."""
    code = getattr(err, "code", None) or getattr(err, "status", None) or getattr(err, "status_code", None)
    if isinstance(code, int):
        if 500 <= code < 600:
            return "transient"
        if 400 <= code < 500:
            return "permanent"

    msg = str(err)
    for marker in PERMANENT_ERROR_MARKERS:
        if marker in msg:
            return "permanent"
    for marker in TRANSIENT_ERROR_MARKERS:
        if marker in msg:
            return "transient"
    return "transient"


# ============================================================
# Tolerant JSON parser (за повреден cache tail)
# ============================================================

def tolerant_parse_cache(raw: str) -> dict[str, dict[str, Any]]:
    """Парсва cache JSON серия-по-серия; спира при първата счупена.

    При crash по време на save последната серия може да е truncated. Strict
    json.load() тогава фейлва и губим ВСИЧКО валидно. Това е non-destructive
    fallback: парсва key-value по key-value с JSONDecoder.raw_decode и ранен
    exit на грешка.
    """
    n = len(raw)
    i = 0
    while i < n and raw[i] in " \t\n\r":
        i += 1
    if i >= n or raw[i] != "{":
        return {}
    i += 1

    out: dict[str, dict[str, Any]] = {}
    decoder = json.JSONDecoder()

    while i < n:
        while i < n and raw[i] in " \t\n\r,":
            i += 1
        if i >= n or raw[i] == "}":
            break
        if raw[i] != '"':
            break
        try:
            key, i = decoder.raw_decode(raw, i)
        except json.JSONDecodeError:
            break
        while i < n and raw[i] in " \t\n\r":
            i += 1
        if i >= n or raw[i] != ":":
            break
        i += 1
        while i < n and raw[i] in " \t\n\r":
            i += 1
        try:
            value, i = decoder.raw_decode(raw, i)
        except json.JSONDecodeError:
            break
        if isinstance(value, dict):
            out[key] = value
    return out


# ============================================================
# BaseAdapter
# ============================================================

class BaseAdapter(ABC):
    """Shared parent за data source adapter-и.

    Subclass-ите имплементират _fetch_remote(series_key, source_id) -> pd.Series.
    BaseAdapter управлява cache, retry, freshness, status introspection.
    """

    SOURCE_NAME: str = "base"  # override-ва се от subclass-овете

    def __init__(
        self,
        cache_path: str | Path,
        base_dir: Optional[Path] = None,
        retry_backoff: Optional[list[int]] = None,
    ):
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).parent.parent
        self.cache_path = self.base_dir / cache_path
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict[str, Any]] = self._load_cache()
        self.retry_backoff = (
            list(retry_backoff) if retry_backoff is not None
            else list(DEFAULT_RETRY_BACKOFF)
        )
        self._fetch_failures: list[str] = []

    # ─── Subclass hook ────────────────────────────────────────

    @abstractmethod
    def _fetch_remote(self, series_key: str, source_id: str) -> pd.Series:
        """Fetch единична серия от remote source. Subclass implements.

        Трябва да:
          - върне pd.Series с DatetimeIndex (sorted ascending)
          - raise при HTTP/network грешки (BaseAdapter ще класифицира)
          - върне пуста Series ако response-ът е валиден, но без observations
        """
        ...

    # ─── Cache I/O ────────────────────────────────────────────

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        if not self.cache_path.exists():
            return {}
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except OSError as e:
            logger.warning(f"Cache load failed ({e}); стартирам с празен кеш.")
            return {}
        except json.JSONDecodeError as e:
            logger.warning(
                f"Cache JSON corrupt ({e}); опитвам tolerant парсинг..."
            )
            try:
                raw = self.cache_path.read_text(encoding="utf-8")
                recovered = tolerant_parse_cache(raw)
                logger.warning(
                    f"Tolerant парсинг успя: {len(recovered)} серии възстановени."
                )
                return recovered
            except Exception as e2:
                logger.warning(f"Tolerant парсинг също фейлна ({e2}); празен кеш.")
                return {}

    def save_cache(self) -> None:
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2, default=str)
        except OSError as e:
            logger.error(f"Cache save failed: {e}")

    # ─── Public API ───────────────────────────────────────────

    def fetch(
        self,
        series_key: str,
        source_id: str,
        release_schedule: str,
        force: bool = False,
    ) -> pd.Series:
        """Взима серия — от кеша или от remote, според TTL."""
        if not force and self._is_cache_fresh(series_key, release_schedule):
            return self._series_from_cache(series_key)

        try:
            series = self._fetch_with_retry(series_key, source_id)
            if series is None or series.empty:
                warnings.warn(f"{series_key} ({source_id}): empty response from {self.SOURCE_NAME}")
                self._fetch_failures.append(series_key)
                return self._series_from_cache(series_key)

            # Гарантираме DatetimeIndex и сортиране
            if not isinstance(series.index, pd.DatetimeIndex):
                series.index = pd.to_datetime(series.index)
            series = series.sort_index()
            self._store_in_cache(series_key, source_id, series, release_schedule)
            return series

        except Exception as e:
            logger.error(f"{series_key} ({source_id}): fetch failed — {e}")
            self._fetch_failures.append(series_key)
            return self._series_from_cache(series_key)

    def fetch_many(
        self,
        series_specs: list[dict[str, Any]],
        force: bool = False,
    ) -> dict[str, pd.Series]:
        """Batch fetch. specs формат: [{key, source_id, release_schedule}, ...]"""
        self._fetch_failures = []
        results: dict[str, pd.Series] = {}
        for spec in series_specs:
            key = spec["key"]
            source_id = spec["source_id"]
            schedule = spec.get("release_schedule", "monthly")
            results[key] = self.fetch(key, source_id, schedule, force=force)
        self.save_cache()
        return results

    def _fetch_with_retry(self, series_key: str, source_id: str) -> pd.Series:
        """Обвива _fetch_remote с retry на transient грешки."""
        max_retries = len(self.retry_backoff)
        last_err: Optional[Exception] = None
        retry_log: list[str] = []

        for attempt in range(max_retries + 1):
            try:
                result = self._fetch_remote(series_key, source_id)
                if retry_log:
                    logger.info(
                        f"{series_key} ({source_id}): успех след {len(retry_log)} retry-та"
                    )
                return result
            except Exception as e:
                last_err = e
                classification = classify_fetch_error(e)
                if classification == "permanent":
                    logger.error(
                        f"{series_key} ({source_id}): permanent error, no retry — {e}"
                    )
                    raise
                if attempt < max_retries:
                    wait = self.retry_backoff[attempt]
                    retry_log.append(
                        f"transient error, retry {attempt + 1}/{max_retries} "
                        f"след {wait}s — {e}"
                    )
                    if wait > 0:
                        time.sleep(wait)
                else:
                    for msg in retry_log:
                        logger.warning(f"{series_key} ({source_id}): {msg}")
                    logger.error(
                        f"{series_key} ({source_id}): изчерпан retry budget — {e}"
                    )

        assert last_err is not None
        raise last_err

    # ─── Helpers ──────────────────────────────────────────────

    def last_fetch_failures(self) -> list[str]:
        return list(self._fetch_failures)

    def find_stale_specs(self, specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            s for s in specs
            if not self._is_cache_fresh(s["key"], s.get("release_schedule", "monthly"))
        ]

    def _is_cache_fresh(self, series_key: str, release_schedule: str) -> bool:
        entry = self._cache.get(series_key)
        if entry is None or not entry.get("last_fetched"):
            return False
        try:
            last_fetched = datetime.fromisoformat(entry["last_fetched"])
        except ValueError:
            return False
        ttl = CACHE_TTL_DAYS.get(release_schedule, 10)
        return (datetime.now() - last_fetched) < timedelta(days=ttl)

    def _store_in_cache(
        self,
        series_key: str,
        source_id: str,
        series: pd.Series,
        release_schedule: str,
    ) -> None:
        if series.empty:
            return
        data_dict = {
            idx.strftime("%Y-%m-%d"): float(val)
            for idx, val in series.dropna().items()
        }
        last_obs = series.dropna().index.max()
        self._cache[series_key] = {
            "source_id": source_id,
            "schedule": release_schedule,
            "last_fetched": datetime.now().isoformat(),
            "last_observation": last_obs.strftime("%Y-%m-%d") if last_obs is not None else None,
            "n_observations": len(data_dict),
            "data": data_dict,
        }

    def _series_from_cache(self, series_key: str) -> pd.Series:
        entry = self._cache.get(series_key)
        if entry is None or not entry.get("data"):
            return pd.Series(dtype=float)
        s = pd.Series(entry["data"])
        s.index = pd.to_datetime(s.index)
        return s.sort_index()

    def get_cache_status(self, series_key: str) -> dict[str, Any]:
        entry = self._cache.get(series_key)
        if entry is None:
            return {
                "is_cached": False,
                "last_fetched": None,
                "last_observation": None,
                "n_observations": 0,
                "source_id": None,
            }
        return {
            "is_cached": True,
            "last_fetched": entry.get("last_fetched"),
            "last_observation": entry.get("last_observation"),
            "n_observations": entry.get("n_observations", 0),
            "source_id": entry.get("source_id"),
        }

    def get_snapshot(self, series_keys) -> dict[str, pd.Series]:
        out: dict[str, pd.Series] = {}
        for key in series_keys:
            s = self._series_from_cache(key)
            if s is not None and not s.empty:
                out[key] = s
        return out

    def invalidate(self, series_key: str) -> None:
        self._cache.pop(series_key, None)

    def invalidate_all(self) -> None:
        self._cache.clear()
