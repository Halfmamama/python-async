"""Module for fetching currency exchange rates and converting Steam eCurrency to RUB.

Supports fetching live rates (RUB base) from public endpoints with local caching (in-memory and state.json),
and falls back to static hardcoded rates on network failure.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, Optional

import requests

logger = logging.getLogger("steam_market_monitor.currency")

# Map of Steam eCurrency (int) to ISO 4217 currency code
STEAM_CURRENCY_ISO: Dict[int, str] = {
    1: "USD",
    2: "GBP",
    3: "EUR",
    4: "CHF",
    5: "RUB",
    6: "PLN",
    7: "BRL",
    8: "JPY",
    9: "NOK",
    10: "IDR",
    11: "MYR",
    12: "PHP",
    13: "SGD",
    14: "THB",
    15: "VND",
    16: "KRW",
    17: "TRY",
    18: "UAH",
    19: "MXN",
    20: "CAD",
    21: "AUD",
    22: "NZD",
    23: "CNY",
    24: "INR",
    25: "CLP",
    26: "PEN",
    27: "COP",
    28: "ZAR",
    29: "HKD",
    30: "TWD",
    31: "SAR",
    32: "AED",
    34: "ILS",
    37: "KZT",
}

# Static fallback rates (X -> RUB multiplier) in case all network/cached sources fail
STATIC_FALLBACK_RATES: Dict[str, float] = {
    "RUB": 1.0,
    "USD": 90.0,
    "EUR": 98.0,
    "GBP": 115.0,
    "PLN": 22.5,
    "UAH": 2.2,
    "KZT": 0.19,
    "CNY": 12.5,
    "CHF": 100.0,
    "JPY": 0.58,
    "BRL": 16.0,
    "CAD": 65.0,
    "AUD": 60.0,
    "NZD": 55.0,
    "TRY": 2.7,
    "ILS": 24.5,
    "SGD": 67.0,
    "HKD": 11.5,
    "AED": 24.5,
    "SAR": 24.0,
    "KRW": 0.065,
    "THB": 2.5,
    "MXN": 5.0,
    "CLP": 0.095,
    "PEN": 24.0,
    "COP": 0.022,
    "ZAR": 4.8,
    "TWD": 2.8,
    "MYR": 19.0,
    "PHP": 1.55,
    "IDR": 0.0055,
    "VND": 0.0035,
    "NOK": 8.5,
}

FX_RETRY_TTL_SECONDS = 300  # 5 minutes between retries when using fallback rates

# In-memory cache
_RATES_CACHE: Optional[Dict[str, float]] = None
_LAST_FETCH_TS: float = 0.0
_LAST_FETCH_OK: bool = False


def get_rates_to_rub(
    cfg: Dict[str, Any],
    state: Dict[str, Any],
    save_state_fn: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, float]:
    """Retrieves exchange rates converting foreign currency ISO code -> RUB multiplier.

    Cache TTL is configured via cfg['fx_refresh_hours'] (default 6 hours) on live success,
    or FX_RETRY_TTL_SECONDS (5 minutes) if using fallback rates.
    Attempts fetching from primary and secondary FX APIs. On network errors,
    falls back to state.json cache, then to STATIC_FALLBACK_RATES. Never raises exceptions.

    Args:
        cfg: Configuration dictionary.
        state: Application state dictionary.
        save_state_fn: Optional callback to persist updated state.

    Returns:
        Dict mapping currency ISO code -> RUB rate multiplier (e.g. {"USD": 90.5, "RUB": 1.0}).
    """
    global _RATES_CACHE, _LAST_FETCH_TS, _LAST_FETCH_OK

    now = time.time()
    full_ttl = int(cfg.get("fx_refresh_hours", 6)) * 3600
    ttl = full_ttl if _LAST_FETCH_OK else FX_RETRY_TTL_SECONDS

    # 1. Check in-memory cache
    if _RATES_CACHE is not None and _LAST_FETCH_TS and (now - _LAST_FETCH_TS) < ttl:
        return _RATES_CACHE

    # Helper to process raw rates dict where RUB = 1.0 (rates gives RUB -> X, so X -> RUB is 1 / X)
    def invert_rub_rates(raw_rates: Dict[str, float]) -> Dict[str, float]:
        res: Dict[str, float] = {"RUB": 1.0}
        for code, val in raw_rates.items():
            if isinstance(val, (int, float)) and val > 0:
                res[code.upper()] = 1.0 / float(val)
        return res

    # 2. Try Primary Network API: open.er-api.com
    try:
        logger.info("\u0417\u0430\u043f\u0440\u043e\u0441 \u0430\u043a\u0442\u0443\u0430\u043b\u044c\u043d\u044b\u0445 \u043a\u0443\u0440\u0441\u043e\u0432 \u0432\u0430\u043b\u044e\u0442 (Primary API: open.er-api.com)...")
        resp = requests.get("https://open.er-api.com/v6/latest/RUB", timeout=10)
        if resp.ok:
            data = resp.json()
            if data.get("result") == "success" and isinstance(data.get("rates"), dict):
                rates = invert_rub_rates(data["rates"])
                _RATES_CACHE = rates
                _LAST_FETCH_TS = now
                _LAST_FETCH_OK = True

                # Save to state.json if function provided
                if save_state_fn is not None:
                    state["__fx_rates__"] = {"rates": rates, "ts": now}
                    try:
                        save_state_fn(state)
                    except Exception as e:
                        logger.warning(f"\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0441\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c \u043a\u0443\u0440\u0441\u044b \u0432 state: {e}")

                logger.info(f"\u041a\u0443\u0440\u0441\u044b \u0432\u0430\u043b\u044e\u0442 \u0443\u0441\u043f\u0435\u0448\u043d\u043e \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u043b\u044b (\u043f\u043e\u043b\u0443\u0447\u0435\u043d\u043e {len(rates)} \u0432\u0430\u043b\u044e\u0442).")
                return rates
    except Exception as e:
        logger.warning(f"\u041e\u0448\u0438\u0431\u043a\u0430 \u0437\u0430\u043f\u0440\u043e\u0441\u0430 \u043a \u043f\u0435\u0440\u0432\u0438\u0447\u043d\u043e\u043c\u0443 FX API: {e}")

    # 3. Try Secondary Network API: exchangerate-api fallback
    try:
        logger.info("\u0417\u0430\u043f\u0440\u043e\u0441 \u043a\u0443\u0440\u0441\u043e\u0432 \u0432\u0430\u043b\u044e\u0442 \u0447\u0435\u0440\u0435\u0437 \u0444\u043e\u043b\u0431\u044d\u043a-\u0441\u0435\u0440\u0432\u0438\u0441...")
        resp = requests.get("https://api.exchangerate-api.com/v4/latest/RUB", timeout=10)
        if resp.ok:
            data = resp.json()
            if isinstance(data.get("rates"), dict):
                rates = invert_rub_rates(data["rates"])
                _RATES_CACHE = rates
                _LAST_FETCH_TS = now
                _LAST_FETCH_OK = True

                if save_state_fn is not None:
                    state["__fx_rates__"] = {"rates": rates, "ts": now}
                    try:
                        save_state_fn(state)
                    except Exception as e:
                        logger.warning(f"\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0441\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c \u043a\u0443\u0440\u0441\u044b \u0432 state: {e}")

                logger.info(f"\u041a\u0443\u0440\u0441\u044b \u0432\u0430\u043b\u044e\u0442 \u0443\u0441\u043f\u0435\u0448\u043d\u043e \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u044b \u0447\u0435\u0440\u0435\u0437 \u0444\u043e\u043b\u0431\u044d\u043a (\u043f\u043e\u043b\u0443\u0447\u0435\u043d\u043e {len(rates)} \u0432\u0430\u043b\u044e\u0442).")
                return rates
    except Exception as e:
        logger.warning(f"\u041e\u0448\u0438\u0431\u043a\u0430 \u0437\u0430\u043f\u0440\u043e\u0441\u0430 \u043a \u0444\u043e\u043b\u0431\u044d\u043a FX API: {e}")

    # 4. Fallback to cached state.json
    cached_fx = state.get("__fx_rates__") if isinstance(state, dict) else None
    if isinstance(cached_fx, dict) and isinstance(cached_fx.get("rates"), dict):
        logger.warning("\u0421\u0435\u0442\u0435\u0432\u044b\u0435 FX \u0441\u0435\u0440\u0432\u0438\u0441\u044b \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u044b. \u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u044e \u0440\u0430\u043d\u0435\u0435 \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u043d\u044b\u0435 \u043a\u0443\u0440\u0441\u044b \u0438\u0437 \u0444\u0430\u0439\u043b\u0430 \u0441\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u044f.")
        cached_rates = cached_fx["rates"]
        _RATES_CACHE = cached_rates
        _LAST_FETCH_TS = now
        _LAST_FETCH_OK = False
        return cached_rates

    # 5. Fallback to static hardcoded rates
    logger.warning("\u0421\u0435\u0442\u0435\u0432\u044b\u0435 \u0441\u0435\u0440\u0432\u0438\u0441\u044b \u0438 \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u043d\u043e\u0435 \u0441\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u044b! \u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u044e \u0441\u0442\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438\u0435 \u043e\u0440\u0438\u0435\u043d\u0442\u0438\u0440\u043e\u0432\u043e\u0447\u043d\u044b\u0435 \u043a\u0443\u0440\u0441\u044b.")
    _RATES_CACHE = STATIC_FALLBACK_RATES.copy()
    _LAST_FETCH_TS = now
    _LAST_FETCH_OK = False
    return _RATES_CACHE


def convert_to_rub(minor: int, ecurrency: int, rates: Dict[str, float]) -> Optional[int]:
    """Converts price in minor currency units (cents/kopecks) to RUB in kopecks.

    Returns:
        Converted RUB price in kopecks (int), or None if conversion failed.
    """
    iso = STEAM_CURRENCY_ISO.get(ecurrency)
    if iso is None:
        return None
    rate = rates.get(iso)
    if rate is None:
        return None
    major = minor / 100.0
    return int(round(major * rate * 100))
