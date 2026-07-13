import json
import logging
import os
import sys
from typing import Dict, Any

# --noconsole guard: stdout/stderr may be None in windowless PyInstaller builds
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

logger = logging.getLogger("steam_market_monitor.storage")

# Default configuration template
DEFAULT_CONFIG: Dict[str, Any] = {
    "telegram_token": "",
    "chat_id": None,
    "currency": 5,
    "country": "RU",
    "language": "russian",
    "currency_symbol": "₽",
    "poll_cycle_seconds": 150,
    "request_delay_seconds": 8,
    "request_delay_jitter_seconds": 4,
    "notify_on_new_item": True,
    "notify_on_count_increase": False,
    "notify_on_price_drop": False,
    "send_images": True,
    "fetch_strategy": "auto",
    "convert_to_rub": True,
    "fx_refresh_hours": 6,
    "market_action_type": "ZFJAHYDA:SearchItemDescriptions",
    "searches": [
        {
            "name": "Strange Primary — horns violet",
            "query": "horns violet",
            "quality": "strange",
            "type": "primary",
            "url": "https://steamcommunity.com/market/search?category_440_Quality=tag_strange&category_440_Type=tag_primary&appid=440&q=horns+violet&descriptions=1&sort=3&dir=1"
        },
        {
            "name": "Strange Primary — horns team",
            "query": "horns team",
            "quality": "strange",
            "type": "primary",
            "url": "https://steamcommunity.com/market/search?category_440_Quality=tag_strange&category_440_Type=tag_primary&appid=440&q=horns+team&descriptions=1&sort=3&dir=1"
        },
        {
            "name": "Strange Primary — horns hot",
            "query": "horns hot",
            "quality": "strange",
            "type": "primary",
            "url": "https://steamcommunity.com/market/search?category_440_Quality=tag_strange&category_440_Type=tag_primary&appid=440&q=horns+hot&descriptions=1&sort=3&dir=1"
        },
        {
            "name": "Strange Primary — tornado hot",
            "query": "tornado hot",
            "quality": "strange",
            "type": "primary",
            "url": "https://steamcommunity.com/market/search?category_440_Quality=tag_strange&category_440_Type=tag_primary&appid=440&q=tornado+hot&descriptions=1&sort=3&dir=1"
        },
        {
            "name": "Strange Primary — tornado violet",
            "query": "tornado violet",
            "quality": "strange",
            "type": "primary",
            "url": "https://steamcommunity.com/market/search?category_440_Quality=tag_strange&category_440_Type=tag_primary&appid=440&q=tornado+violet&descriptions=1&sort=3&dir=1"
        },
        {
            "name": "Strange Primary — tornado team",
            "query": "tornado team",
            "quality": "strange",
            "type": "primary",
            "url": "https://steamcommunity.com/market/search?category_440_Quality=tag_strange&category_440_Type=tag_primary&appid=440&q=tornado+team&descriptions=1&sort=3&dir=1"
        },
        {
            "name": "Melee — kunai horns",
            "query": "kunai horns",
            "type": "melee",
            "url": "https://steamcommunity.com/market/search?category_440_Type=tag_melee&appid=440&q=kunai+horns&descriptions=1&sort=3&dir=1"
        },
        {
            "name": "Melee — kunai tornado",
            "query": "kunai tornado",
            "type": "melee",
            "url": "https://steamcommunity.com/market/search?category_440_Type=tag_melee&appid=440&q=kunai+tornado&descriptions=1&sort=3&dir=1"
        }
    ]
}


def get_base_dir() -> str:
    """Returns the base directory of the running program.

    If compiled with PyInstaller, returns the directory containing the executable.
    If run as script, returns the directory containing sys.argv[0].
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    
    if sys.argv and sys.argv[0]:
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.getcwd()


def _resolve_path(path: str) -> str:
    """Helper to resolve paths relative to the base directory of the program if not absolute."""
    if os.path.isabs(path):
        return path
    return os.path.join(get_base_dir(), path)


def load_config(path: str = "config.json") -> Dict[str, Any]:
    """Loads configuration dictionary from JSON file.

    If file does not exist, creates it from DEFAULT_CONFIG and exits the application.
    """
    resolved_path = _resolve_path(path)
    if not os.path.exists(resolved_path):
        save_config(DEFAULT_CONFIG, resolved_path)
        msg = f"Создан {path}. Заполните telegram_token и перезапустите программу."
        logger.warning(msg)
        sys.exit(0)

    try:
        with open(resolved_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            if not isinstance(cfg, dict):
                raise ValueError("Config root must be a JSON object (dictionary)")
            return cfg
    except Exception as e:
        logger.error(f"Ошибка при загрузке конфигурации {resolved_path}: {e}")
        raise


def save_config(cfg: Dict[str, Any], path: str = "config.json") -> None:
    """Saves configuration dictionary to a JSON file."""
    resolved_path = _resolve_path(path)
    try:
        with open(resolved_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Не удалось сохранить конфигурацию в {resolved_path}: {e}")
        raise


def load_state(path: str = "state.json") -> Dict[str, Any]:
    """Loads state dictionary from JSON file.

    Returns an empty dict if the file does not exist.
    """
    resolved_path = _resolve_path(path)
    if not os.path.exists(resolved_path):
        return {}

    try:
        with open(resolved_path, "r", encoding="utf-8") as f:
            state = json.load(f)
            if not isinstance(state, dict):
                raise ValueError("State root must be a JSON object (dictionary)")
            return state
    except Exception as e:
        logger.error(f"Ошибка при загрузке состояния {resolved_path}: {e}")
        return {}


def save_state(state: Dict[str, Any], path: str = "state.json") -> None:
    """Saves state dictionary to a JSON file."""
    resolved_path = _resolve_path(path)
    try:
        with open(resolved_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Не удалось сохранить состояние в {resolved_path}: {e}")
        raise
