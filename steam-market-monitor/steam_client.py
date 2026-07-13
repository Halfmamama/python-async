"""Module for interacting with the Steam Community Market (new React API).

Steam migrated to a React frontend. The old JSON render endpoint
(/market/search/render/) and window.SSR.renderContext HTML parsing
no longer return results for description-search queries.

This module uses the new POST-based market search endpoint discovered on the
new React market UI. A single requests.Session is reused across all calls
(anonymous, cookie-based — no login required).

Public interface (consumed by monitor.py):
    fetch(search, cfg, rates)  -> List[dict]
    check_canary(cfg)          -> bool
    SteamClient                (compatibility class)
    SteamRateLimited           (exception)
    SteamFetchError            (exception)
    extract_currency_symbol()  (helper)
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import sys
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

import currency

# ---------------------------------------------------------------------------
# --noconsole guard: stdout/stderr may be None in windowless PyInstaller builds
# ---------------------------------------------------------------------------
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

logger = logging.getLogger("steam_market_monitor.steam_client")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_MARKET_BASE = "https://steamcommunity.com/market"
_SEARCH_URL = f"{_MARKET_BASE}/search"

# Regex to extract the action-type hash from a JS bundle.
_ACTION_TYPE_RE = re.compile(r'"([A-Z0-9]{8}:SearchItemDescriptions)"')

# Legacy compatibility stub
DETECTED_CURRENCY: Dict[str, str] = {"code_name": "RUB", "symbol": "₽"}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class SteamRateLimited(Exception):
    """Raised when Steam responds with HTTP 429 Too Many Requests."""


class SteamFetchError(Exception):
    """Raised when an error occurs while fetching or parsing Steam Market data."""


# ---------------------------------------------------------------------------
# Price / currency helpers
# ---------------------------------------------------------------------------
def parse_price_text(price_text: str) -> int:
    """Parses a price string into integer kopecks/cents."""
    cleaned = price_text.replace("\xa0", "").replace("\u00a0", "").replace(" ", "")
    match = re.search(r"(\d+(?:[.,]\d+)?)", cleaned)
    if not match:
        return 0
    val_str = match.group(1).replace(",", ".")
    try:
        if "." in val_str:
            return int(round(float(val_str) * 100))
        return int(val_str) * 100
    except ValueError:
        return 0


# Smoke-test assertions
assert parse_price_text("1 234,56 ₽") == 123456
assert parse_price_text("12,50 руб.") == 1250
assert parse_price_text("1\u00a0000 ₽") == 100000
assert parse_price_text("$2.41") == 241
assert parse_price_text("777 ₽") == 77700


def extract_currency_symbol(price_text: str) -> Optional[str]:
    """Extracts and normalises the currency symbol or code from a price string."""
    if not price_text:
        return None
    cleaned = re.sub(r"[\d\s.,\xa0\u00a0\u202f\u2009\-]", "", price_text)
    if not cleaned:
        return None

    t = cleaned.casefold()
    if "руб" in t or "rub" in t or "pуб" in t:
        return "₽"
    if "eur" in t:
        return "€"
    if "usd" in t:
        return "$"
    return cleaned


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------
_session: Optional[requests.Session] = None


def _make_session() -> requests.Session:
    """Creates a requests.Session with retry adapter and Steam-compatible headers."""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ru-RU,ru;q=0.9",
            "Origin": "https://steamcommunity.com",
            "Referer": "https://steamcommunity.com/market/search",
        }
    )
    return session


def _get_session() -> requests.Session:
    """Returns the shared Steam session, initialising it on first call."""
    global _session
    if _session is not None:
        return _session

    _session = _make_session()
    try:
        logger.info("Инициализация сессии Steam (GET /market/)…")
        resp = _session.get(f"{_MARKET_BASE}/", timeout=20)
        resp.raise_for_status()
        cookies_summary = {k: v for k, v in _session.cookies.items()}
        logger.info(f"Сессия инициализирована. Cookies: {cookies_summary}")
    except Exception as exc:
        logger.warning(f"Не удалось инициализировать сессию Steam: {exc}")
    return _session


# ---------------------------------------------------------------------------
# Filter builder
# ---------------------------------------------------------------------------
def build_filters(search: Dict[str, Any]) -> Dict[str, List[str]]:
    """Builds the filters dict for the POST request body."""
    filters: Dict[str, List[str]] = {}
    quality: Optional[str] = search.get("quality") or None
    item_type: Optional[str] = search.get("type") or None
    if quality:
        filters["Quality"] = [quality]
    if item_type:
        filters["Type"] = [item_type]
    return filters


# ---------------------------------------------------------------------------
# Action-type auto-refresh
# ---------------------------------------------------------------------------
def _try_refresh_action_type(cfg: Dict[str, Any]) -> Optional[str]:
    """Attempts to extract the current x-valve-action-type hash from Steam JS bundles."""
    session = _get_session()
    try:
        resp = session.get(
            f"{_SEARCH_URL}?appid=440",
            timeout=20,
            headers={"Accept": "text/html,application/xhtml+xml"},
        )
        resp.raise_for_status()
        bundle_urls = re.findall(r'src="(https://[^"]+\.js)"', resp.text)
        for bundle_url in bundle_urls[:5]:
            try:
                js_resp = session.get(bundle_url, timeout=15)
                match = _ACTION_TYPE_RE.search(js_resp.text)
                if match:
                    found = match.group(1)
                    logger.info(f"Найден актуальный action type в JS-бандле: {found}")
                    return found
            except Exception:
                continue
    except Exception as exc:
        logger.debug(f"Не удалось получить JS-бандл для обновления action type: {exc}")
    return None


# ---------------------------------------------------------------------------
# Core POST helper
# ---------------------------------------------------------------------------
def _post_search(
    query: str,
    filters: Dict[str, List[str]],
    cfg: Dict[str, Any],
    *,
    start: int = 0,
    search_descriptions: bool = True,
) -> Dict[str, Any]:
    """Performs a single POST to the Steam React market search endpoint."""
    session = _get_session()
    action_type: str = cfg.get(
        "market_action_type", "ZFJAHYDA:SearchItemDescriptions"
    )
    appid: int = int(cfg.get("appid", 440))
    currency_code: int = int(cfg.get("currency", 5))

    headers = {
        "content-type": "application/json",
        "x-valve-request-type": "routeAction",
        "x-valve-action-type": action_type,
    }

    body = [
        {
            "appid": appid,
            "filters": filters,
            "price": {"eCurrency": currency_code},
            "accessoryFilters": {},
            "strQuery": query,
            "bSearchDescriptions": search_descriptions,
            "start": start,
        }
    ]

    post_url = "{}/search?appid={}&q={}&descriptions=1".format(
        _MARKET_BASE, appid, urllib.parse.quote(query, safe="")
    )

    for attempt in range(3):
        try:
            resp = session.post(
                post_url,
                json=body,
                headers=headers,
                timeout=25,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            if attempt < 2:
                wait = random.uniform(2, 5)
                logger.warning(
                    f"Ошибка соединения (попытка {attempt + 1}/3), повтор через {wait:.1f}с: {exc}"
                )
                time.sleep(wait)
                continue
            raise SteamFetchError(f"Ошибка сети после 3 попыток: {exc}") from exc

        if resp.status_code == 429:
            raise SteamRateLimited("Steam Rate Limit Exceeded (HTTP 429)")

        if resp.status_code in (400, 404):
            logger.error(
                f"Steam вернул HTTP {resp.status_code} для action_type='{action_type}'. "
                "Скорее всего хеш сборки Steam изменился — обнови market_action_type в config.json. "
                "Попытка автообновления…"
            )
            new_type = _try_refresh_action_type(cfg)
            if new_type and new_type != action_type:
                logger.info(f"Автообновлён market_action_type: {new_type}")
                cfg["market_action_type"] = new_type
                action_type = new_type
                headers["x-valve-action-type"] = action_type
                continue
            raise SteamFetchError(
                f"HTTP {resp.status_code} от Steam. Обнови market_action_type в config.json вручную."
            )

        if not resp.ok:
            raise SteamFetchError(
                f"Неожиданный HTTP {resp.status_code} от Steam: {resp.text[:200]}"
            )

        try:
            data: Dict[str, Any] = resp.json()
        except ValueError as exc:
            raise SteamFetchError(f"Steam вернул невалидный JSON: {exc}") from exc

        return data

    raise SteamFetchError("Все попытки POST исчерпаны.")


# ---------------------------------------------------------------------------
# Listing normalizer with RUB currency conversion
# ---------------------------------------------------------------------------
def _normalize_listing(
    listing: Dict[str, Any], rates: Optional[Dict[str, float]] = None
) -> Dict[str, Any]:
    """Normalises a single raw listing dict from the Steam API response, converting to RUB if rates supplied."""
    desc: Dict[str, Any] = listing.get("description") or {}
    hash_name: str = desc.get("market_hash_name", "")
    name: str = desc.get("market_name") or hash_name

    price_native: int = listing.get("unPrice", 0) + listing.get("unFee", 0)
    str_subtotal: str = listing.get("strSubtotal", "")
    sym_native: Optional[str] = extract_currency_symbol(str_subtotal)
    ec: Optional[int] = listing.get("eCurrency")

    rub_price: Optional[int] = None
    if rates and ec is not None:
        rub_price = currency.convert_to_rub(price_native, ec, rates)

    if rub_price is not None:
        price = rub_price
        currency_symbol = "₽"
        converted = True
    else:
        price = price_native
        currency_symbol = sym_native
        converted = False

    icon_url: str = desc.get("icon_url", "")
    image: Optional[str] = (
        "https://community.fastly.steamstatic.com/economy/image/{}/360fx360f".format(
            icon_url
        )
        if icon_url
        else None
    )

    url: str = (
        "https://steamcommunity.com/market/listings/440/"
        + urllib.parse.quote(hash_name, safe="")
    )

    asset: Dict[str, Any] = listing.get("asset") or {}
    listing_id: str = str(asset.get("assetid") or listing.get("listingid") or "")

    return {
        "listingid": listing_id,
        "hash_name": hash_name,
        "name": name,
        "price": price,
        "currency_symbol": currency_symbol,
        "url": url,
        "image": image,
        "listings": 1,
        "price_native": price_native,
        "currency_symbol_native": sym_native,
        "str_subtotal_native": str_subtotal,
        "converted": converted,
        "ecurrency": ec,
    }


# ---------------------------------------------------------------------------
# Public: fetch
# ---------------------------------------------------------------------------
def fetch(
    search: Dict[str, Any],
    cfg: Dict[str, Any],
    rates: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """Fetches all market listings for a search config entry via the POST API.

    Args:
        search: Search entry dict from config["searches"].
        cfg: Full configuration dict.
        rates: Optional exchange rates dict (ISO code -> RUB rate multiplier).

    Returns:
        Flat list of normalised listing dicts.
    """
    query: str = (search.get("query") or "").strip()
    if not query:
        url_field: str = search.get("url", "")
        if url_field:
            parsed_u = urllib.parse.urlparse(url_field)
            qs = urllib.parse.parse_qs(parsed_u.query)
            query = (qs.get("q") or qs.get("query") or [""])[0]

    if not query:
        logger.error(f"Пустой query для поиска '{search.get('name')}' — пропуск.")
        return []

    filters = build_filters(search)
    delay = float(cfg.get("request_delay_seconds", 8))
    jitter = float(cfg.get("request_delay_jitter_seconds", 4))

    all_listings: List[Dict[str, Any]] = []
    start = 0

    while True:
        if start > 0:
            sleep_time = delay + random.uniform(0, jitter)
            logger.debug(f"Пауза перед страницей offset={start}: {sleep_time:.2f}с")
            time.sleep(sleep_time)

        logger.debug(f"POST search: query='{query}' filters={filters} start={start}")
        data = _post_search(query, filters, cfg, start=start)

        raw_listings: List[Dict[str, Any]] = data.get("listings") or []
        total_count: int = int(data.get("total_count", 0))
        has_more: bool = bool(data.get("more", False))

        if not raw_listings:
            logger.info(
                f"Получено 0 listings на offset={start} (total_count={total_count})"
            )
            break

        currencies = {
            lst.get("eCurrency")
            for lst in raw_listings
            if lst.get("eCurrency") is not None
        }
        if len(currencies) > 1:
            logger.warning(
                f"Смешанные валюты в ответе Steam ({len(currencies)} валют): {currencies}."
            )

        normalized = [_normalize_listing(lst, rates=rates) for lst in raw_listings]
        all_listings.extend(normalized)

        logger.info(
            f"  offset={start}: получено {len(raw_listings)} listings, "
            f"total_count={total_count}, more={has_more}"
        )

        start += len(raw_listings)
        if not has_more:
            break

    return all_listings


# ---------------------------------------------------------------------------
# Public: check_canary
# ---------------------------------------------------------------------------
def check_canary(cfg: Dict[str, Any]) -> bool:
    """Sends a control POST to verify the Steam endpoint is functional."""
    logger.info("Канарейка: проверка работоспособности POST-эндпоинта Steam…")
    for canary_query in ["Mann Co. Supply Crate Key", "Key"]:
        try:
            data = _post_search(
                query=canary_query,
                filters={},
                cfg=cfg,
                start=0,
                search_descriptions=False,
            )
            total: int = int(data.get("total_count", 0))
            if total > 0:
                logger.info(
                    f"✅ Канарейка OK: total_count={total} (запрос '{canary_query}')"
                )
                return True
        except SteamRateLimited:
            logger.warning("⚠️ Канарейка: Steam Rate Limit (429). Попробуем позже.")
            return False
        except Exception as exc:
            logger.error(f"⚠️ Канарейка: исключение — {exc}")
            return False

    logger.warning(
        "⚠️ Канарейка: total_count=0. "
        "Проблема сети/эндпоинта/заголовков или устаревший market_action_type в config.json."
    )
    return False


# ---------------------------------------------------------------------------
# Compatibility Wrapper Class
# ---------------------------------------------------------------------------
class SteamClient:
    """Class wrapper around steam_client functions for backward compatibility."""

    def __init__(self, session: Optional[requests.Session] = None) -> None:
        self.session = session or _get_session()

    def fetch(
        self,
        search: Dict[str, Any],
        cfg: Dict[str, Any],
        rates: Optional[Dict[str, float]] = None,
    ) -> List[Dict[str, Any]]:
        return fetch(search, cfg, rates=rates)

    def fetch_url(self, url: str) -> str:
        return fetch_url(url)

    def parse_json(self, response_text: str) -> Tuple[List[Dict[str, Any]], int]:
        return [], 0

    def parse_html(
        self, response_text: str, rates: Optional[Dict[str, float]] = None
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Legacy HTML/SSR parser kept for test suite compatibility."""
        soup = BeautifulSoup(response_text, "html.parser")
        scripts = soup.find_all("script")
        ssr_script = None
        for s in scripts:
            t = s.string or s.text or ""
            if "window.SSR.renderContext" in t:
                ssr_script = t
                break

        if ssr_script:
            try:
                start_marker = 'window.SSR.renderContext=JSON.parse("'
                start_idx = ssr_script.find(start_marker)
                if start_idx != -1:
                    chars = []
                    i = start_idx + len(start_marker)
                    while i < len(ssr_script):
                        c = ssr_script[i]
                        if c == '"':
                            break
                        elif c == '\\':
                            next_c = ssr_script[i + 1]
                            if next_c == '"':
                                chars.append('"')
                            elif next_c == '\\':
                                chars.append('\\')
                            elif next_c == 'n':
                                chars.append('\n')
                            elif next_c == 'r':
                                chars.append('\r')
                            elif next_c == 't':
                                chars.append('\t')
                            else:
                                chars.append(c + next_c)
                            i += 2
                            continue
                        else:
                            chars.append(c)
                        i += 1

                    decoded_str = "".join(chars)
                    render_context = json.loads(decoded_str)
                    query_data_str = render_context.get("queryData", "")
                    if query_data_str:
                        query_data = json.loads(query_data_str)
                        queries = query_data.get("queries", [])
                        for q in queries:
                            qdata = q.get("state", {}).get("data", {})
                            if isinstance(qdata, dict) and "pages" in qdata:
                                pages = qdata.get("pages", [])
                                if pages and isinstance(pages[0], dict) and "listings" in pages[0]:
                                    total_count = pages[0].get("total_count", 0)
                                    listings = pages[0].get("listings", [])

                                    items = []
                                    for listing in listings:
                                        desc = listing.get("description", {})
                                        name = desc.get("market_name") or desc.get("name") or desc.get("market_hash_name", "")
                                        hash_name = desc.get("market_hash_name", "")
                                        appid = str(desc.get("appid", "440"))
                                        price_native = listing.get("unPrice", 0) + listing.get("unFee", 0)
                                        subtotal_text = listing.get("strSubtotal", "")
                                        sym_native = extract_currency_symbol(subtotal_text)
                                        ec = listing.get("eCurrency")

                                        rub_price = currency.convert_to_rub(price_native, ec, rates) if (rates and ec is not None) else None
                                        if rub_price is not None:
                                            price = rub_price
                                            currency_symbol = "₽"
                                            converted = True
                                        else:
                                            price = price_native
                                            currency_symbol = sym_native
                                            converted = False

                                        icon_url = desc.get("icon_url", "")
                                        image = (
                                            "https://community.fastly.steamstatic.com/economy/image/{}/360fx360f".format(
                                                icon_url
                                            )
                                            if icon_url
                                            else None
                                        )
                                        url = "https://steamcommunity.com/market/listings/{}/{}".format(
                                            appid, urllib.parse.quote(hash_name, safe="")
                                        )

                                        items.append({
                                            "hash_name": hash_name,
                                            "name": name,
                                            "price": price,
                                            "listings": 1,
                                            "url": url,
                                            "image": image,
                                            "currency_symbol": currency_symbol,
                                            "price_native": price_native,
                                            "currency_symbol_native": sym_native,
                                            "str_subtotal_native": subtotal_text,
                                            "converted": converted,
                                            "ecurrency": ec,
                                        })
                                    return items, total_count
            except Exception as e:
                raise SteamFetchError(f"Ошибка при разборе SSR renderContext: {e}") from e

        return [], 0


# ---------------------------------------------------------------------------
# Legacy GET helper
# ---------------------------------------------------------------------------
def fetch_url(url: str) -> str:
    """Legacy GET helper kept for backward compatibility with diagnostic scripts."""
    session = _get_session()
    try:
        resp = session.get(url, timeout=20)
        if resp.status_code == 429:
            raise SteamRateLimited("Steam Rate Limit Exceeded (HTTP 429)")
        resp.raise_for_status()
        return resp.text
    except SteamRateLimited:
        raise
    except Exception as exc:
        raise SteamFetchError(f"GET {url}: {exc}") from exc


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        stream=sys.stdout,
    )

    _cfg: Dict[str, Any] = {
        "currency": 5,
        "market_action_type": "ZFJAHYDA:SearchItemDescriptions",
        "request_delay_seconds": 2,
        "request_delay_jitter_seconds": 1,
        "fx_refresh_hours": 6,
    }

    print("\n" + "=" * 80)
    print("TESTING CURRENCY & FETCH INTEGRATION")
    print("=" * 80)
    rates_test = currency.get_rates_to_rub(_cfg, {})
    print(f"Loaded {len(rates_test)} exchange rates. USD -> RUB: {rates_test.get('USD'):.2f}")

    _search: Dict[str, Any] = {
        "name": "Strange Primary — tornado violet",
        "query": "tornado violet",
        "quality": "strange",
        "type": "primary",
        "url": "https://steamcommunity.com/market/search?q=tornado+violet",
    }
    try:
        items = fetch(_search, _cfg, rates=rates_test)
        print(f"Fetched {len(items)} items with RUB conversion:")
        for item in items[:10]:
            converted_flag = "≈" if item.get("converted") else ""
            native_str = item.get("str_subtotal_native", "")
            print(
                f"  {item['name'][:45]:<47} -> {converted_flag} {item['price']/100:>8.2f} {item['currency_symbol']} ({native_str})"
            )
    except Exception as err:
        print(f"fetch() failed: {err}")
