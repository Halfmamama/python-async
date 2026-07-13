"""Module for detecting changes in market items.

Compares current and historical states to spot price drops, new items, and volume increases.
"""

import html
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("steam_market_monitor.detector")


class MarketDetector:
    """Detects events of interest on the Steam Community Market."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config

    def detect_changes(
        self, current_items: List[Dict[str, Any]], previous_state: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Compares currently fetched items with the stored historical state.

        Args:
            current_items: List of item data dicts.
            previous_state: Previous state dictionary.

        Returns:
            List of dictionaries representing detected events.
        """
        current_snapshot = snapshot_from_items(current_items)
        return diff(previous_state, current_snapshot, self.config)


def snapshot_from_items(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Creates a snapshot dictionary from a list of items, merging duplicates by hash_name.

    For duplicates, the minimum price and the sum of listings are used.
    """
    snapshot: Dict[str, Dict[str, Any]] = {}
    for item in items:
        hname = item.get("hash_name") or item.get("name")
        if not hname:
            continue

        price = item.get("price", 0)
        listings = item.get("listings", 0)
        name = item.get("name", hname)
        url = item.get("url", "")
        image = item.get("image")
        currency_symbol = item.get("currency_symbol")

        if hname not in snapshot:
            snapshot[hname] = {
                "price": price,
                "listings": listings,
                "name": name,
                "url": url,
                "image": image,
                "currency_symbol": currency_symbol,
                "price_native": item.get("price_native"),
                "currency_symbol_native": item.get("currency_symbol_native"),
                "str_subtotal_native": item.get("str_subtotal_native"),
                "converted": item.get("converted", False),
                "ecurrency": item.get("ecurrency"),
            }
        else:
            existing = snapshot[hname]
            if price < existing["price"]:
                existing["price"] = price
                existing["name"] = name
                existing["url"] = url
                existing["image"] = image
                existing["currency_symbol"] = currency_symbol
                existing["price_native"] = item.get("price_native")
                existing["currency_symbol_native"] = item.get("currency_symbol_native")
                existing["str_subtotal_native"] = item.get("str_subtotal_native")
                existing["converted"] = item.get("converted", False)
                existing["ecurrency"] = item.get("ecurrency")
            existing["listings"] += listings

    return snapshot


def diff(
    old: Optional[Dict[str, Any]],
    new: Dict[str, Any],
    cfg: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Compares previous and current snapshots to detect new items, price drops, or volume increases."""
    if old is None:
        return []

    events = []
    notify_on_new = cfg.get("notify_on_new_item", True)
    notify_on_count = cfg.get("notify_on_count_increase", True)
    notify_on_price = cfg.get("notify_on_price_drop", True)

    for hash_name, new_item in new.items():
        if hash_name not in old:
            if notify_on_new:
                events.append({
                    "type": "new_item",
                    "item": {**new_item, "hash_name": hash_name},
                    "old_price": None,
                    "new_price": new_item["price"],
                    "old_count": None,
                    "new_count": new_item["listings"]
                })
        else:
            old_item = old[hash_name]
            if new_item["listings"] > old_item["listings"]:
                if notify_on_count:
                    events.append({
                        "type": "count_up",
                        "item": {**new_item, "hash_name": hash_name},
                        "old_price": old_item["price"],
                        "new_price": new_item["price"],
                        "old_count": old_item["listings"],
                        "new_count": new_item["listings"]
                    })
            if new_item["price"] < old_item["price"]:
                if notify_on_price:
                    events.append({
                        "type": "price_drop",
                        "item": {**new_item, "hash_name": hash_name},
                        "old_price": old_item["price"],
                        "new_price": new_item["price"],
                        "old_count": old_item["listings"],
                        "new_count": new_item["listings"]
                    })

    return events


CURRENCY_SYMBOL = "₽"


def price_to_human(price: int, custom_symbol: Optional[str] = None) -> str:
    """Formats price in kopecks/cents into a human readable string."""
    val = price / 100.0
    formatted = f"{val:,.2f}"
    formatted = formatted.replace(",", " ").replace(".", ",")
    sym = custom_symbol if custom_symbol else CURRENCY_SYMBOL
    return f"{formatted} {sym}"


def format_price_display(item: Dict[str, Any], price: int) -> str:
    """Formats price string with optional '≈' sign and native subtotal string in parentheses."""
    custom_sym = item.get("currency_symbol")
    base_price = price_to_human(price, custom_sym)
    converted = item.get("converted", False)
    str_subtotal_native = item.get("str_subtotal_native")

    if converted and str_subtotal_native:
        return f"≈ {base_price} ({str_subtotal_native})"
    elif converted:
        return f"≈ {base_price}"
    return base_price


def format_event(event: Dict[str, Any], search_name: str) -> str:
    """Formats a detected event into a Telegram HTML message with emojis."""
    event_type = event.get("type")
    item = event.get("item", {})
    name = html.escape(item.get("name", ""))
    url = item.get("url", "") or ""
    search_name_esc = html.escape(search_name)

    new_price = event.get("new_price", 0)
    old_price = event.get("old_price")
    new_count = event.get("new_count", 0)
    old_count = event.get("old_count")

    price_str = format_price_display(item, new_price)

    link_line = f'\n<a href="{url}">Ссылка на маркет</a>' if url else ""

    if event_type == "new_item":
        return (
            f" [{search_name_esc}] <b>{name}</b> — {price_str} "
            f"(Кол-во: {new_count} шт.)"
            f"{link_line}"
        )
    elif event_type == "count_up":
        old_val = old_count if old_count is not None else 0
        diff_count = new_count - old_val
        return (
            f" [{search_name_esc}] <b>{name}</b> — {price_str} "
            f"(Кол-во: {old_val}  {new_count} (+{diff_count} шт.))"
            f"{link_line}"
        )
    elif event_type == "price_drop":
        old_val = old_price if old_price is not None else 0
        diff_price = old_val - new_price
        diff_str = format_price_display(item, diff_price)
        return (
            f" [{search_name_esc}] <b>{name}</b> — {price_str} "
            f"(Цена упала с {format_price_display(item, old_val)} на -{diff_str}) (Кол-во: {new_count} шт.)"
            f"{link_line}"
        )
    else:
        return f"[{search_name_esc}] <b>{name}</b> — {price_str}"
