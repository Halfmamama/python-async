import os
import sys
import logging
import time
import requests
from typing import Dict, Any, Optional, Callable

# --noconsole guard: stdout/stderr may be None in windowless PyInstaller builds
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

# Reconfigure console stream encoding to UTF-8 to prevent encoding errors on Windows
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

logger = logging.getLogger("steam_market_monitor.telegram_notifier")


def ensure_chat_id(cfg: Dict[str, Any], save_config_fn: Callable[[Dict[str, Any]], None]) -> str:
    """Ensures that chat_id is populated in config.

    If not set, polls getUpdates from Telegram Bot API for up to 5 minutes,
    saves the detected chat_id to the config using save_config_fn, and returns it.
    """
    chat_id = cfg.get("chat_id")
    if chat_id is not None and str(chat_id).strip() != "":
        return str(chat_id)

    token = cfg.get("telegram_token", "").strip()
    if not token:
        raise ValueError("В конфигурации отсутствует токен Telegram (telegram_token)!")

    logger.info("Откройте бота в Telegram и нажмите Start (ждём до 5 минут)...")
    print("Откройте бота в Telegram и нажмите Start (ждём до 5 минут)...")

    timeout = 300
    start_time = time.time()
    session = requests.Session()

    while time.time() - start_time < timeout:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates"
            response = session.get(url, timeout=10)
            
            if response.status_code == 409:
                logger.error("getUpdates вернул 409 Conflict. Вероятно, на боте установлен Webhook.")
                print("Ошибка: getUpdates вернул 409 Conflict. Вероятно, на боте установлен Webhook.")
                raise RuntimeError("getUpdates вернул 409 Conflict. Webhook активен на боте.")
            elif response.status_code == 429:
                try:
                    retry_after = response.json().get("parameters", {}).get("retry_after", 3)
                except Exception:
                    retry_after = 3
                logger.warning(f"Telegram Rate Limit (429) при getUpdates. Ожидание {retry_after} сек.")
                time.sleep(retry_after)
                continue

            response.raise_for_status()
            data = response.json()
            if data.get("ok"):
                result = data.get("result", [])
                if result:
                    detected_chat_id = None
                    # Iterate in reverse to get the latest message
                    for update in reversed(result):
                        message = update.get("message")
                        if message and isinstance(message, dict):
                            chat = message.get("chat")
                            if chat and isinstance(chat, dict) and "id" in chat:
                                detected_chat_id = chat["id"]
                                break
                    
                    if detected_chat_id is not None:
                        chat_id_str = str(detected_chat_id)
                        cfg["chat_id"] = chat_id_str
                        save_config_fn(cfg)
                        logger.info(f"Успешно получен и сохранен chat_id: {chat_id_str}")
                        print(f"Успешно получен и сохранен chat_id: {chat_id_str}")
                        return chat_id_str
        except RuntimeError:
            raise
        except Exception as e:
            logger.warning(f"Ошибка при получении обновлений getUpdates: {e}")

        time.sleep(3)

    raise TimeoutError("Не удалось получить chat_id за 5 минут. Пожалуйста, отправьте сообщение боту и перезапустите программу.")


def send_message(
    token: str,
    chat_id: str,
    text: str,
    parse_mode: Optional[str] = "HTML",
    disable_web_page_preview: bool = False
) -> bool:
    """Sends a text message using Telegram's sendMessage API.

    Handles 429 rate limit retries (up to 3 times) and falls back to plain text
    on HTML parsing errors (HTTP 400).
    """
    if not token or not chat_id:
        logger.warning("Токен или chat_id отсутствуют. Отмена отправки.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": disable_web_page_preview
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    max_attempts = 3
    session = requests.Session()

    for attempt in range(max_attempts):
        try:
            logger.debug(f"Отправка сообщения в Telegram (попытка {attempt+1}/{max_attempts})...")
            response = session.post(url, json=payload, timeout=10)
            
            if response.status_code == 429:
                try:
                    retry_after = response.json().get("parameters", {}).get("retry_after", 3)
                except Exception:
                    retry_after = 3
                logger.warning(f"Telegram Rate Limit (429). Ожидание {retry_after} сек перед повтором.")
                time.sleep(retry_after)
                continue

            if response.status_code == 400 and parse_mode == "HTML":
                try:
                    desc = response.json().get("description", "").lower()
                    if "can't parse entities" in desc or "bad request" in desc:
                        logger.warning("Ошибка разметки HTML в Telegram. Повторная отправка простым текстом.")
                        # Strip parse_mode and retry immediately
                        payload.pop("parse_mode", None)
                        response = session.post(url, json=payload, timeout=10)
                except Exception as parse_err:
                    logger.debug(f"Не удалось распарсить ошибку 400: {parse_err}")

            response.raise_for_status()
            logger.debug("Сообщение успешно отправлено в Telegram.")
            return True

        except Exception as e:
            logger.error(f"Не удалось отправить сообщение в Telegram на попытке {attempt+1}: {e}")
            if attempt == max_attempts - 1:
                return False
            time.sleep(1)

    return False


def send_photo(
    token: str,
    chat_id: str,
    photo_url: str,
    caption: str,
    parse_mode: Optional[str] = "HTML"
) -> bool:
    """Sends an image using Telegram's sendPhoto API.

    If caption length exceeds 1024 characters, automatically falls back to send_message.
    If sendPhoto fails (due to network error, invalid image URL, etc.), falls back
    to send_message with the caption text.
    """
    if not token or not chat_id:
        logger.warning("Токен или chat_id отсутствуют. Отмена отправки фото.")
        return False

    # Caption limit for sendPhoto is 1024 characters
    if len(caption) > 1024:
        logger.warning("Длина подписи к фото превышает 1024 символа. Отправка в виде сообщения.")
        return send_message(token, chat_id, caption, parse_mode)

    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    payload = {
        "chat_id": chat_id,
        "photo": photo_url,
        "caption": caption
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    max_attempts = 3
    session = requests.Session()

    for attempt in range(max_attempts):
        try:
            logger.debug(f"Отправка фото в Telegram (попытка {attempt+1}/{max_attempts})...")
            response = session.post(url, json=payload, timeout=10)

            if response.status_code == 429:
                try:
                    retry_after = response.json().get("parameters", {}).get("retry_after", 3)
                except Exception:
                    retry_after = 3
                logger.warning(f"Telegram Rate Limit (429) при отправке фото. Ожидание {retry_after} сек.")
                time.sleep(retry_after)
                continue

            if response.status_code == 400 and parse_mode == "HTML":
                try:
                    desc = response.json().get("description", "").lower()
                    if "can't parse entities" in desc or "bad request" in desc:
                        logger.warning("Ошибка разметки HTML в подписи к фото. Повторная отправка простым текстом.")
                        payload.pop("parse_mode", None)
                        response = session.post(url, json=payload, timeout=10)
                except Exception as parse_err:
                    logger.debug(f"Не удалось распарсить ошибку 400: {parse_err}")

            response.raise_for_status()
            logger.debug("Фото успешно отправлено в Telegram.")
            return True

        except Exception as e:
            logger.warning(f"Ошибка при отправке фото в Telegram на попытке {attempt+1}: {e}")
            if attempt == max_attempts - 1:
                # Last attempt failed, fallback to text message
                logger.info("Попытки отправки фото исчерпаны. Переключение на текстовое сообщение.")
                return send_message(token, chat_id, caption, parse_mode)
            time.sleep(1)

    return False


def notify(cfg: Dict[str, Any], text: str, image_url: Optional[str] = None) -> bool:
    """Sends a notification to Telegram chat.

    Routes to send_photo if send_images is configured and image_url is provided,
    otherwise routes to send_message.
    """
    token = cfg.get("telegram_token", "")
    chat_id = cfg.get("chat_id")
    send_images = cfg.get("send_images", True)

    if not token or chat_id is None:
        logger.warning("Telegram Bot не настроен (отсутствует токен или chat_id). Пропуск уведомления.")
        return False

    chat_id_str = str(chat_id)
    if send_images and image_url:
        return send_photo(token, chat_id_str, image_url, text)
    return send_message(token, chat_id_str, text, disable_web_page_preview=True)


class TelegramNotifier:
    """Object-oriented wrapper class for backward compatibility and clean OOP design."""

    def __init__(
        self, config: Dict[str, Any], session: Optional[requests.Session] = None
    ) -> None:
        self.config = config
        self.token = config.get("telegram_token", "")
        self.chat_id = config.get("chat_id")

    def ensure_chat_id(self, save_config_fn: Callable[[Dict[str, Any]], None]) -> str:
        """Ensures chat ID is configured, polling Telegram updates if necessary."""
        return ensure_chat_id(self.config, save_config_fn)

    def send_message(self, text: str) -> bool:
        """Sends a text message using the instance's token and chat_id."""
        chat_id_str = str(self.chat_id) if self.chat_id is not None else ""
        return send_message(self.token, chat_id_str, text)

    def send_photo(self, photo_url: str, caption: Optional[str] = None) -> bool:
        """Sends a photo using the instance's token and chat_id."""
        chat_id_str = str(self.chat_id) if self.chat_id is not None else ""
        return send_photo(self.token, chat_id_str, photo_url, caption or "")

    def notify(self, text: str, image_url: Optional[str] = None) -> bool:
        """Sends a notification using the instance's configuration."""
        return notify(self.config, text, image_url)
