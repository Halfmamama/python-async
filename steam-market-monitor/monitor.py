"""Main entry point for the Steam Market Monitor offline application.

Configures logging, environment variables, loads configurations,
and starts the monitoring loop.
"""

import logging
import os
import random
import sys
import time

# --noconsole / pythonw: stdout and stderr may be None. Redirect to devnull
# before ANY print() or reconfigure() to prevent crashes.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

# Reconfigure encoding for console builds (no-op in --noconsole mode)
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from logging.handlers import RotatingFileHandler
from storage import get_base_dir, load_config, save_config, load_state, save_state
import steam_client
import detector
import telegram_notifier
import currency

logger = logging.getLogger("steam_market_monitor.monitor")


def setup_logging() -> None:
    """Configures application-wide logging.

    In --noconsole (windowless) mode logs only to file.
    In console mode also logs to stdout.
    """
    base_dir = get_base_dir()
    logs_dir = os.path.join(base_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_file = os.path.join(logs_dir, "monitor.log")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    root_logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    is_console = not getattr(sys, "frozen", False) or sys.stdout.name != os.devnull
    if is_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO)
        root_logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)


def main() -> None:
    """Main application loop and configuration initializer."""
    setup_logging()

    logger.info("Запуск Steam Market монитора... 🚀")

    config = load_config()
    logger.info("Конфигурация успешно загружена.")

    token = config.get("telegram_token", "").strip()
    searches = config.get("searches", [])

    if not token or not searches:
        logger.error("Ошибка: В config.json не заполнен telegram_token или список searches пуст!")
        sys.exit(1)

    try:
        chat_id = telegram_notifier.ensure_chat_id(config, save_config)
    except Exception as e:
        logger.error(f"Критическая ошибка при определении chat_id: {e}")
        sys.exit(1)

    detector.CURRENCY_SYMBOL = config.get("currency_symbol", "₽")

    # Run canary check at startup
    logger.info("Проверка канарейки Steam API...")
    if not steam_client.check_canary(config):
        canary_warn = (
            "⚠️ Предупреждение: Стартовая проверка канарейки Steam не прошла! "
            "Возможно изменился market_action_type или проблемы с сетью."
        )
        logger.warning(canary_warn)
        try:
            telegram_notifier.send_message(token, chat_id, canary_warn)
        except Exception:
            pass

    cycle_sec = config.get("poll_cycle_seconds", 150)
    startup_msg = f"✅ Мониторинг запущен. Слежу за {len(searches)} ссылками. Цикл ~{cycle_sec} сек."
    telegram_notifier.send_message(token, chat_id, startup_msg)
    logger.info(startup_msg)

    state = load_state()
    logger.info("Предыдущее состояние успешно загружено.")

    seen = set(state.get("__seen__", []))
    is_baseline = not seen

    backoff_index = 0
    backoff_minutes = [5, 15, 30]

    try:
        while True:
            # Retrieve currency exchange rates ONCE per cycle
            rates = None
            if config.get("convert_to_rub", True):
                rates = currency.get_rates_to_rub(config, state, save_state)

            for idx, search in enumerate(searches, 1):
                url = search.get("url")
                name = search.get("name", f"Search #{idx}")
                if not url:
                    logger.warning(f"Пропуск записи без ссылки: {name}")
                    continue

                logger.info(f"[{idx}/{len(searches)}] Запрос: '{name}'")

                try:
                    try:
                        items = steam_client.fetch(search, config, rates=rates)
                    except TypeError:
                        items = steam_client.fetch(search, config)

                    if backoff_index > 0:
                        logger.info("Связь со Steam восстановлена. Сброс паузы Rate Limit.")
                        backoff_index = 0

                    snapshot = detector.snapshot_from_items(items)
                    old_snapshot = state.get(url)

                    events = detector.diff(old_snapshot, snapshot, config)
                    events = [e for e in events if e["type"] != "new_item"]

                    for hash_name, item_data in snapshot.items():
                        if hash_name not in seen:
                            seen.add(hash_name)
                            if not is_baseline:
                                new_item_event = {
                                    "type": "new_item",
                                    "item": {**item_data, "hash_name": hash_name},
                                    "new_price": item_data["price"],
                                    "new_count": item_data["listings"]
                                }
                                text = detector.format_event(new_item_event, name)
                                image_url = item_data.get("image")
                                logger.info(
                                    f"Событие [new_item] для '{item_data.get('name')}': отправка уведомления. "
                                    f"hash_name='{hash_name}' | url='{item_data.get('url')}'"
                                )
                                telegram_notifier.notify(config, text, image_url=image_url)

                    for event in events:
                        text = detector.format_event(event, name)
                        item = event["item"]
                        image_url = item.get("image")
                        logger.info(
                            f"Событие [{event['type']}] для '{item.get('name')}': отправка уведомления. "
                            f"hash_name='{item.get('hash_name')}' | url='{item.get('url')}'"
                        )
                        telegram_notifier.notify(config, text, image_url=image_url)

                    state[url] = snapshot
                    state["__seen__"] = list(seen)
                    save_state(state)

                except steam_client.SteamRateLimited:
                    wait_mins = backoff_minutes[min(backoff_index, len(backoff_minutes) - 1)]
                    backoff_index += 1

                    msg = f"⚠️ Steam лимит, пауза {wait_mins} мин"
                    logger.warning(msg)
                    telegram_notifier.send_message(token, chat_id, msg)

                    time.sleep(wait_mins * 60)
                    break

                except steam_client.SteamFetchError as e:
                    logger.error(f"Ошибка получения данных для '{name}': {e}")

                except Exception as e:
                    logger.error(f"Непредвиденная ошибка при обработке '{name}': {e}", exc_info=True)

                delay = float(config.get("request_delay_seconds", 8))
                jitter = float(config.get("request_delay_jitter_seconds", 4))
                sleep_time = delay + random.uniform(0, jitter)
                logger.info(f"Пауза перед следующей ссылкой: {sleep_time:.2f} сек.")
                time.sleep(sleep_time)
            else:
                present = set()
                for key, snap in state.items():
                    if key.startswith("__"):
                        continue
                    if isinstance(snap, dict):
                        present.update(snap.keys())

                seen = seen & present
                state["__seen__"] = list(seen)
                save_state(state)

                is_baseline = False

            poll_cycle = float(config.get("poll_cycle_seconds", 150))
            logger.info(f"Цикл завершен. Ожидание следующего цикла опроса {poll_cycle} сек... 😴")
            time.sleep(poll_cycle)

    except KeyboardInterrupt:
        logger.info("Мониторинг остановлен пользователем (Ctrl+C).")
        print("\nПрограмма остановлена пользователем (Ctrl+C).")
        sys.exit(0)


if __name__ == "__main__":
    main()
