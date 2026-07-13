"""
Nemesis Helpers — constants, anti-detect, universal clicker, token selection,
balance reading, session planning.

Вынесено из nemesis_trading.py при рефакторинге.
"""

import asyncio
import logging
import random
import re
from playwright.async_api import TimeoutError

import config
from core.humanize import (
    human_type,
    human_pause,
    random_mouse_wiggle,
    human_click,
)
from Nemesis.nemesis_selectors import (
    read_balance,
    wait_for_toast,
    get_field_input,
    get_field_token_button,
    get_field_group,
    get_swap_tab,
    get_short_tab,
    get_long_tab,
    get_liquidity_link,
    get_create_position_button,
    get_add_liquidity_button,
    get_choose_token_button,
    get_connect_wallet_button,
    get_metamask_option,
    get_token_dialog,
    get_token_in_dialog,
    get_leverage_slider_track,
    get_leverage_button,
    FormContext,
)

# ===================== CONSTANTS =====================

URL_APP = "https://nemesis.trade/trade"

RUN_MODE = "ONLY"  # ALL | ONLY

# TARGET_ACCOUNTS перенесён в nemesis_orchestrator.py для централизованной конфигурации
# Импортируется и переопределяется через: nemesis_helpers.TARGET_ACCOUNTS = TARGET_ACCOUNTS
TARGET_ACCOUNTS = []  # Заполняется из orchestrator

MAX_CONCURRENT = 5
MAX_RETRIES = 3

# ===================== BALANCE CONTROL =====================

MIN_ETH_RESERVE = 0.1       # Минимальный остаток ETH
SWAP_ETH_TO_DAI_LOW = 0.01   # Свап ETH→DAI если DAI < 30
SWAP_ETH_TO_DAI_HIGH = 0.001  # Свап ETH→DAI если DAI >= 30
DAI_THRESHOLD = 30           # Порог DAI для определения суммы свапа

# NEW: Разделённые лимиты DAI для разных операций
SWAP_DAI_MIN = 4             # Минимум DAI для свапа DAI→token
SWAP_DAI_MAX = 6             # Максимум DAI для свапа DAI→token
LS_DAI_MIN = 1               # Минимум DAI для Long/Short
LS_DAI_MAX = 3               # Максимум DAI для Long/Short
LIQ_DAI_MIN = 1              # Минимум DAI для Liquidity
LIQ_DAI_MAX = 3              # Максимум DAI для Liquidity
MIN_DAI_RESERVE = 1          # Минимальный остаток DAI (для обратного свапа)

# ===================== TIMEOUT CONSTANTS =====================
UI_TIMEOUT = 5_000
DIALOG_TIMEOUT = 10_000
TX_WAIT_TIMEOUT = 25_000

# ===================== TOKEN CONFIG =====================

# Токены из "Your tokens" и "Popular tokens"
TOKEN_INFO = {
    "ETH":   "Ethereum",
    "WETH":  "Wrapped Ether",
    "DAI":   "Dai Stablecoin",
    "USDC":  "USD Coin",
    "UNI":   "Uniswap",
    "LINK":  "Chainlink",
}

# Токены для обмена DAI → token (включая ETH для полной пары)
DAI_SWAP_TOKENS = ["USDC", "ETH", "UNI", "LINK", "WETH"]

# Токены для Long/Short — после свапа доступны ВСЕ токены, которые мы имеем
PERP_TOKENS = ["USDC", "ETH", "UNI", "LINK", "WETH"]

# Токены для Liquidity — после свапа доступны ВСЕ токены, которые мы имеем
LIQUIDITY_TOKENS = ["DAI", "USDC", "ETH", "UNI", "LINK"]  # NEW: убран WETH

# Токены для сессионной пары DAI/XXX — доступны во ВСЕХ контекстах (свап, LS, liq)
SESSION_PAIR_TOKENS = ["USDC", "ETH", "UNI", "LINK", "WETH"]

# NEW: Токены для сессионной пары ТОЛЬКО для Liquidity (без WETH)
LIQUIDITY_PAIR_TOKENS = ["USDC", "ETH", "UNI", "LINK"]


# ===================== NEMESIS-SPECIFIC DAPP BUTTONS =====================

# Универсальный кликер: на Nemesis ВСЕ кнопки действий (Approve, Swap, Open, Confirm)
# имеют оранжевый фон (bg-brand) и полную ширину формы (~390px).
# Табы навигации (Swap/Short/Long), селекторы токенов (ETH, DAI),
# кнопка Max — узкие и серые/прозрачные.
# Отличаем action-кнопки по ШИРИНЕ: ≥200px = действие.

# Минимальная ширина кнопки действия (px)
ACTION_BUTTON_MIN_WIDTH = 200

# Навигационные кнопки которые нужно пропускать ДАЖЕ если они широкие.
# УЗКИЕ табы (Swap/Short/Long) отфильтровываются проверкой ширины (≥200px).
# Широкие кнопки "Swap"/"Short"/"Long" — это ACTION-кнопки (оранжевые, полная ширина формы), их НЕ пропускаем!
WIDE_NAV_TEXTS = {"trade", "liquidity"}

# Кнопки которые нужно ПОЛНОСТЬЮ ПРОПУСКАТЬ (не нажимать никогда)
# Close Position — закроет открытую позицию!
# Enter amount — disabled, не действие
# Review — уже нажата ДО confirm_dapp_transaction, не нужно повторно кликать!
EXCLUDE_BUTTON_KEYWORDS = ["close position", "enter amount", "review"]

# Ключевые слова для определения что кнопка вызывает MetaMask
METAMASK_KEYWORDS = ["approve", "swap", "open", "confirm", "wrap", "retry", "supply"]

# Ключевые слова для навигационных кнопок (НЕ вызывают MetaMask, но нажимаем)
# NEW: "review" убран — теперь полностью исключается из кандидатов на клик в confirm_dapp_transaction
# NEW: "add liquidity" убран — в модалке действий вызывает MetaMask, не навигация!
UI_ONLY_KEYWORDS = ["create new position"]

# Ключевые слова для обхода проверки ширины.
# Если текст кнопки содержит любое из этих слов (и это не навигационный таб),
# кнопка считается action-кнопкой НЕЗАВИСИМО от ширины.
WIDTH_BYPASS_KEYWORDS = [
    "approve", "confirm", "supply", "review", "retry", "wrap", "open",
    "add liquidity", "create new position",
]

# Навигационные табы — НЕ обходят проверку ширины,
# даже если их текст совпадает с ключевым словом.
NAV_TAB_EXACT = {"swap", "short", "long", "trade", "liquidity"}

# Терминальные действия — после подтверждения в MetaMask цикл подтверждений
# нужно ОСТАНОВИТЬ, иначе кликер найдёт ту же кнопку на форме и кликнет снова.
# NEW: "Swap" — финальное действие в цепочке (после Approve)
# NEW: "Open" — финальное действие в LS
TERMINAL_KEYWORDS = ["swap", "open", "add liquidity", "supply"]


# ===================== UNIVERSAL ACTION BUTTON CLICKER =====================

def is_terminal_action(btn_name: str) -> bool:
    """
    Определяет, является ли нажатая кнопка ТЕРМИНАЛЬНЫМ действием.
    После терминального действия не нужно искать новые кнопки —
    операция завершена (свап выполнен, позиция открыта, ликвидность добавлена).
    
    NEW: Исправлена логика для отличия "Swap" (отдельная операция) от 
    "Swap X → Y" (часть цепочки LS/LongShort).
    
    Терминальные действия:
    - "Confirm Swap" — терминальное (свап на вкладке Swap завершён)
    - "Open 2x Long/Short" — терминальное (позиция открыта)
    - "Add Liquidity" — терминальное (ликвидность добавлена)
    - "Supply" — терминальное
    
    НЕ терминальные (промежуточные шаги):
    - "Swap DAI → UNI" — НЕ терминальное (часть LS цепочки)
    - "Approve XXX" — НЕ терминальное
    """
    if not btn_name:
        return False
    text = btn_name.lower()
    
    # "Confirm Swap" → терминальное (чистый свап на вкладке Swap)
    # "Swap DAI → UNI" → НЕ терминальное (часть цепочки LS)
    if "confirm swap" in text:
        logging.debug(f"🏁 Terminal check: '{btn_name}' → TERMINAL (Confirm Swap)")
        return True
    
    # "Open 2x Short/Long" → терминальное (позиция открыта)
    if "open" in text and ("short" in text or "long" in text):
        logging.debug(f"🏁 Terminal check: '{btn_name}' → TERMINAL (Open Position)")
        return True
    
    # "Supply" / "Confirm Supply" → терминальное (ликвидность добавлена)
    if "supply" in text and "approve" not in text:
        logging.debug(f"🏁 Terminal check: '{btn_name}' → TERMINAL (Supply)")
        return True
    
    # "Add Liquidity" → терминальное (ликвидность добавлена)
    if "add liquidity" in text:
        logging.debug(f"🏁 Terminal check: '{btn_name}' → TERMINAL (Add Liquidity)")
        return True
    
    logging.debug(f"⏭️  Terminal check: '{btn_name}' → NOT terminal (continue loop)")
    return False


async def click_nemesis_action_button(page, profile_name, timeout=5_000):
    """
    Универсальный кликер — нажимает ЛЮБУЮ кнопку действия на Nemesis.

    Стратегия: находим ВСЕ видимые кнопки, фильтруем по ширине
    (action-кнопки ≥200px), исключаем навигацию и селекторы токенов,
    кликаем первую подходящую.

    Для disabled-кнопок, которые выглядят как action (широкие, нужный текст),
    ждём когда станут enabled вместо того чтобы пропускать.

    Returns:
        (button_name: str, True, triggers_metamask: bool)  — если кликнули
        (None, False, False)                                — если нет доступных кнопок
    """
    SCAN_RETRIES = 5
    SCAN_RETRY_DELAY = 6
    ENABLED_WAIT = 20_000

    for scan_attempt in range(SCAN_RETRIES):
        try:
            buttons = page.locator("button")
            count = await buttons.count()
            logging.info(f"[{profile_name}] 🔍 Сканирую {count} кнопок на странице...")

            best = None          # (button_locator, text, width, triggers_mm)
            best_disabled = None # То же, но кнопка disabled — ждём enabled
            
            # DEBUG: Счётчики для статистики
            excluded_count = 0
            narrow_count = 0
            candidate_count = 0

            for i in range(count):
                btn = buttons.nth(i)
                try:
                    if not await btn.is_visible(timeout=500):
                        continue

                    text = (await btn.text_content() or "").strip()
                    if not text:
                        continue
                    text_lower = text.lower()

                    # Исключаем опасные/ненужные кнопки
                    if any(kw in text_lower for kw in EXCLUDE_BUTTON_KEYWORDS):
                        excluded_count += 1
                        continue
                    
                    # Исключаем короткие кнопки-селекторы (ETH, DAI, Max, 2X)
                    if len(text) <= 3:
                        excluded_count += 1
                        continue
                    
                    # Исключаем "Choose a token"
                    if "choose" in text_lower:
                        excluded_count += 1
                        continue
                    
                    # NEW: Исключаем кнопки-адреса токенов (0xXXXX...XXXX) — 
                    # это дисплей адреса контракта, не action-кнопка
                    if re.match(r'^0x[a-fA-F0-9]{4}\.\.[a-fA-F0-9]{4}$', text):
                        excluded_count += 1
                        continue
                    
                    # Проверяем ширину — action-кнопки широкие (≥200px)
                    # Кнопки с классом bg-brand (оранжевые) — ВСЕГДА action-кнопки
                    # Также пропускаем проверку ширины для кнопок с ключевыми словами действий
                    box = await btn.bounding_box()
                    if not box:
                        continue
                    is_brand_btn = "bg-brand" in (await btn.get_attribute("class") or "")
                    is_action_by_text = (
                        any(kw in text_lower for kw in WIDTH_BYPASS_KEYWORDS)
                        and text_lower not in NAV_TAB_EXACT
                    )
                    if not is_brand_btn and not is_action_by_text and box["width"] < ACTION_BUTTON_MIN_WIDTH:
                        narrow_count += 1
                        if text and len(text) > 3:
                            logging.info(
                                f"[{profile_name}] 🔍 Узкая: '{text}' "
                                f"({box['width']:.0f}px < {ACTION_BUTTON_MIN_WIDTH})"
                            )
                        continue
                                        
                    # NEW: Логируем все кандидаты на клик (INFO уровень)
                    candidate_count += 1
                    logging.info(
                        f"[{profile_name}] ✅ Кандидат #{candidate_count}: '{text}' "
                        f"({box['width']:.0f}px) brand={is_brand_btn} "
                        f"enabled={await btn.is_enabled()}"
                    )

                    # Широкие кнопки "Swap"/"Short"/"Long" — это ACTION-кнопки!
                    # Исключаем только чисто навигационные широкие кнопки:
                    if text_lower in WIDE_NAV_TEXTS:
                        continue

                    # Проверяем enabled/disabled
                    is_enabled = await btn.is_enabled()

                    # Определяем: вызывает ли MetaMask?
                    if any(kw in text_lower for kw in UI_ONLY_KEYWORDS):
                        triggers_mm = False
                    else:
                        triggers_mm = True

                    # Debug-логирование — видим все кандидаты
                    logging.debug(
                        f"[{profile_name}] 🔍 Кнопка: '{text}' "
                        f"({box['width']:.0f}px) "
                        f"enabled={is_enabled} mm={triggers_mm}"
                    )

                    candidate = (btn, text, box["width"], triggers_mm)

                    if is_enabled:
                        if best is None or box["width"] > best[2]:
                            best = candidate
                    else:
                        if best_disabled is None or box["width"] > best_disabled[2]:
                            best_disabled = candidate

                except Exception:
                    continue

            # Если есть disabled action-кнопка и нет enabled — ждём enabled
            if best is None and best_disabled is not None:
                disabled_btn, disabled_text, disabled_width, disabled_mm = best_disabled
                logging.info(
                    f"[{profile_name}] ⏳ Кнопка '{disabled_text}' disabled, "
                    f"жду enabled (до {ENABLED_WAIT/1000:.0f}с)..."
                )
                poll_interval = 1.0
                elapsed = 0.0
                while elapsed < ENABLED_WAIT / 1000:
                    await asyncio.sleep(poll_interval)
                    elapsed += poll_interval
                    try:
                        if await disabled_btn.is_enabled():
                            best = best_disabled
                            logging.info(
                                f"[{profile_name}] ✅ Кнопка '{disabled_text}' "
                                f"стала enabled через {elapsed:.0f}с"
                            )
                            break
                    except Exception:
                        break
                else:
                    logging.debug(
                        f"[{profile_name}] Кнопка '{disabled_text}' "
                        f"не стала enabled за {ENABLED_WAIT/1000:.0f}с"
                    )

            if best:
                btn, text, width, triggers_mm = best
                await asyncio.sleep(random.uniform(0.5, 1.5))
                await btn.click()
                logging.info(
                    f"[{profile_name}] 👆 Универсальный клик: '{text}' ({width:.0f}px)"
                    f" {'[→MetaMask]' if triggers_mm else '[UI-only]'}"
                )
                return (text, True, triggers_mm)
            else:
                # NEW: Логируем статистику если не нашли кнопку
                logging.info(
                    f"[{profile_name}] 📊 Статистика: "
                    f"всего={count} | исключено={excluded_count} | "
                    f"узкие={narrow_count} | кандидаты={candidate_count}"
                )

        except Exception as e:
            logging.debug(f"[{profile_name}] Универсальный кликер (попытка {scan_attempt+1}): {e}")

        # Не нашли кнопку — ждём и пробуем снова
        if scan_attempt < SCAN_RETRIES - 1:
            logging.info(
                f"[{profile_name}] ⏳ Кнопок не найдено, "
                f"повторное сканирование через {SCAN_RETRY_DELAY}с "
                f"(попытка {scan_attempt+2}/{SCAN_RETRIES})..."
            )
            await asyncio.sleep(SCAN_RETRY_DELAY)

    return (None, False, False)


# ===================== ANTI-DETECT / HUMANIZATION (Imported from core.humanize) =====================


# ===================== ACCOUNT SELECTION =====================

def select_profiles():
    if TARGET_ACCOUNTS:
        return {
            name: cfg
            for name, cfg in config.PROFILES.items()
            if name in TARGET_ACCOUNTS
        }
    return config.PROFILES


# ===================== BALANCE HELPERS =====================

async def read_from_balance(page, name):
    """Читает баланс из поля 'From' (через селектор по метке)."""
    balance = await read_balance(page, "From")
    if balance is not None:
        logging.info(f"[{name}] 💰 From баланс: {balance}")
    else:
        logging.warning(f"[{name}] ⚠️ Не удалось прочитать From баланс")
    return balance


async def read_to_balance(page, name):
    """Читает баланс из поля 'To' (через селектор по метке)."""
    balance = await read_balance(page, "To")
    if balance is not None:
        logging.info(f"[{name}] 💰 To баланс: {balance}")
    else:
        logging.warning(f"[{name}] ⚠️ Не удалось прочитать To баланс")
    return balance


# ===================== TOKEN SELECTION HELPERS =====================

async def select_token_in_dialog(page, name, token_symbol):
    """Выбирает токен в диалоге 'Select a Token'.

    Формат в списке: "{SYMBOL}{Full Name}" → "USDCUSD Coin"
    Если токен не найден — закрывает диалог нажатием Escape,
    иначе dialog-overlay заблокирует все дальнейшие клики.

    Ищем токен несколькими способами — сначала точное совпадение
    SYMBOL+Name, затем по кнопке с текстом SYMBOL, затем просто по тексту.
    """
    token_name = TOKEN_INFO.get(token_symbol, token_symbol)

    # Стратегия 1: точное совпадение SYMBOL+Name (оригинальный способ)
    try:
        token_locator = page.locator("div").filter(
            has_text=re.compile(rf"^{token_symbol}{re.escape(token_name)}")
        ).nth(1)
        await token_locator.wait_for(state="visible", timeout=5_000)
        await human_pause(0.3, 1.0)
        await human_click(token_locator, name, f"Token {token_symbol} (strategy 1)")
        logging.info(f"[{name}] 🪙 Выбран токен: {token_symbol} (стратегия 1)")
        return True
    except TimeoutError:
        logging.info(f"[{name}] ℹ️ Токен {token_symbol} не найден стратегией 1, пробуем 2...")
    except Exception as e:
        logging.info(f"[{name}] ℹ️ Стратегия 1 ошибка: {e}, пробуем 2...")

    # Стратегия 2: кнопка внутри диалога с точным текстом SYMBOL
    try:
        dialog = page.get_by_role("dialog", name="Select a Token")
        if await dialog.is_visible(timeout=2_000):
            token_in_dialog = dialog.locator(
                f"button:has-text('{token_symbol}'), "
                f"div:has-text('{token_symbol}{token_name}')"
            ).first
            await token_in_dialog.wait_for(state="visible", timeout=5_000)
            await human_pause(0.3, 1.0)
            await human_click(token_in_dialog, name, f"Token {token_symbol} (strategy 2)")
            logging.info(f"[{name}] 🪙 Выбран токен: {token_symbol} (стратегия 2)")
            return True
    except TimeoutError:
        logging.info(f"[{name}] ℹ️ Токен {token_symbol} не найден стратегией 2, пробуем 3...")
    except Exception:
        pass

    # Стратегия 3: поиск по тексту токена на всей странице
    try:
        token_by_text = page.get_by_text(
            re.compile(rf"^{token_symbol}\b"), exact=False
        ).first
        await token_by_text.wait_for(state="visible", timeout=5_000)
        await human_pause(0.3, 1.0)
        await human_click(token_by_text, name, f"Token {token_symbol} (strategy 3)")
        logging.info(f"[{name}] 🪙 Выбран токен: {token_symbol} (стратегия 3)")
        return True
    except TimeoutError:
        logging.error(f"[{name}] ❌ Токен {token_symbol} не найден ни одной стратегией")
    except Exception as e:
        logging.error(f"[{name}] ❌ Ошибка при выборе токена {token_symbol}: {e}")

    # Закрываем диалог чтобы dialog-overlay не блокировал клики
    try:
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.5)
        overlay = page.locator('[data-slot="dialog-overlay"]')
        if await overlay.count() > 0:
            await overlay.press("Escape")
            await asyncio.sleep(0.5)
        logging.info(f"[{name}] 🚪 Диалог выбора токена закрыт")
    except Exception:
        pass
    return False


async def ensure_token_selected(page, name, token_btn_locator, target_token, log_context="token"):
    """
    Проверяет выбран ли нужный токен. Если нет - открывает модалку и выбирает его.
    NEW: Добавлена повторная проверка после выбора чтобы убедиться что токен действительно выбран.
    """
    try:
        await token_btn_locator.wait_for(state="visible", timeout=UI_TIMEOUT)
        current_token = (await token_btn_locator.text_content() or "").strip()
        
        if target_token not in current_token:
            logging.info(f"[{name}] 🔄 {log_context}: текущий='{current_token}', нужен='{target_token}'")
            await human_click(token_btn_locator, name, f"{log_context} selector")
            await human_pause(0.5, 1.5)
            dialog = page.get_by_role("dialog", name="Select a Token")
            try:
                await dialog.wait_for(state="visible", timeout=DIALOG_TIMEOUT)
            except TimeoutError:
                pass
            await human_pause(0.8, 2.0)
            await select_token_in_dialog(page, name, target_token)
            await human_pause(1.0, 2.5)
            
            # NEW: Повторная проверка что токен действительно выбран
            await token_btn_locator.wait_for(state="visible", timeout=UI_TIMEOUT)
            verified_token = (await token_btn_locator.text_content() or "").strip()
            if target_token not in verified_token:
                logging.warning(
                    f"[{name}] ⚠️ {log_context}: токен НЕ выбран! "
                    f"Ожидался '{target_token}', выбран '{verified_token}'. "
                    f"Пробую ещё раз..."
                )
                # Пробуем ещё раз (один повтор)
                await human_click(token_btn_locator, name, f"{log_context} selector (retry)")
                await human_pause(0.5, 1.5)
                await select_token_in_dialog(page, name, target_token)
                await human_pause(1.0, 2.5)
                
                # Финальная проверка
                final_token = (await token_btn_locator.text_content() or "").strip()
                if target_token not in final_token:
                    logging.error(
                        f"[{name}] ❌ {log_context}: не удалось выбрать {target_token} "
                        f"после 2 попыток (выбран '{final_token}')"
                    )
                    return False
                else:
                    logging.info(f"[{name}] ✅ {log_context}: {target_token} выбран со второй попытки")
            else:
                logging.info(f"[{name}] ✅ {log_context}: {target_token} успешно выбран")
        else:
            logging.info(f"[{name}] ℹ️ {target_token} уже выбран ({log_context})")
        return True
    except TimeoutError:
        logging.info(f"[{name}] ℹ️ Кнопка селектора '{log_context}' не найдена")
        return False
    except Exception as e:
        logging.warning(f"[{name}] ⚠️ Ошибка выбора токена {target_token} ({log_context}): {e}")
        return False


# ===================== SESSION PLANNING =====================


def plan_session(dai_balance: float) -> dict:
    """
    Выбирает пару и рассчитывает количество DAI для каждой операции.

    Пара DAI/pair_token выбирается один раз и используется для всех 3 операций:
      - Swap DAI → pair_token (4-6 DAI)
      - Long/Short pair_token с маржой DAI (1-3 DAI)
      - Liquidity DAI/pair_token (1-3 DAI)
    
    NEW: pair_token выбирается из LIQUIDITY_PAIR_TOKENS (без WETH) чтобы
    гарантировать что токен доступен для Liquidity.

    Returns: dict с pair_token, swap_amount, ls_amount, liq_amount
    """
    pair_token = random.choice(LIQUIDITY_PAIR_TOKENS)  # NEW: без WETH

    available = max(0, dai_balance - MIN_DAI_RESERVE)

    # NEW: Разделённые лимиты для разных операций
    swap_amount = round(random.uniform(SWAP_DAI_MIN, SWAP_DAI_MAX), 2)  # 4-6 DAI
    ls_amount = round(random.uniform(LS_DAI_MIN, LS_DAI_MAX), 2)        # 1-3 DAI
    liq_amount = round(random.uniform(LIQ_DAI_MIN, LIQ_DAI_MAX), 2)     # 1-3 DAI

    # Проверяем что суммарно не превышаем available
    total_needed = swap_amount + ls_amount + liq_amount
    if total_needed > available and available > 0:
        scale = available / total_needed
        swap_amount = round(swap_amount * scale, 2)
        ls_amount = round(ls_amount * scale, 2)
        liq_amount = round(liq_amount * scale, 2)

    # Гарантируем что каждая операция в своих пределах
    swap_amount = max(SWAP_DAI_MIN, min(SWAP_DAI_MAX, swap_amount))
    ls_amount = max(LS_DAI_MIN, min(LS_DAI_MAX, ls_amount))
    liq_amount = max(LIQ_DAI_MIN, min(LIQ_DAI_MAX, liq_amount))

    logging.info(
        f"📋 План сессии: пара DAI/{pair_token} | "
        f"свап={swap_amount} | лс={ls_amount} | ликв={liq_amount} DAI"
    )

    return {
        "pair_token": pair_token,
        "swap_amount": swap_amount,
        "ls_amount": ls_amount,
        "liq_amount": liq_amount,
    }
