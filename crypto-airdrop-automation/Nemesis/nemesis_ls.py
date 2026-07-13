"""
Nemesis Long/Short — открытие позиций Long/Short.

Вынесено из nemesis_trading.py при рефакторинге.
"""

import asyncio
import logging
import random
import re
from playwright.async_api import TimeoutError

from core.wallet import (
    confirm_dapp_transaction,
    handle_multiple_metamask_popups,
    _find_metamask_page,
)
from core.utils import idle
from Nemesis.nemesis_helpers import (
    # constants
    LS_DAI_MIN,  # NEW: лимиты для Long/Short
    LS_DAI_MAX,
    MIN_DAI_RESERVE,
    PERP_TOKENS,
    TOKEN_INFO,
    MAX_RETRIES,
    UI_TIMEOUT,
    TX_WAIT_TIMEOUT,
    # anti-detect
    human_type,
    human_pause,
    random_mouse_wiggle,
    human_click,
    # helpers
    select_token_in_dialog,
    ensure_token_selected,
    # NEW: универсальный кликер и терминальная проверка
    click_nemesis_action_button,
    is_terminal_action,
)
from Nemesis.nemesis_selectors import (
    read_balance,
    get_field_input,
    get_field_token_button,
    get_short_tab,
    get_long_tab,
    wait_for_toast,
)


# ===================== NAVIGATION =====================

async def click_short_tab(page, name):
    """Переключается на вкладку Short."""
    await human_pause(0.5, 1.5)
    await random_mouse_wiggle(page)
    short_btn = get_short_tab(page)
    await human_click(short_btn, name, "Short tab")
    await human_pause(1.0, 2.5)
    logging.info(f"[{name}] [DOWN] Переключился на Short")


async def click_long_tab(page, name):
    """Переключается на вкладку Long."""
    await human_pause(0.5, 1.5)
    await random_mouse_wiggle(page)
    long_btn = get_long_tab(page)
    await human_click(long_btn, name, "Long tab")
    await human_pause(1.0, 2.5)
    logging.info(f"[{name}] [UP] Переключился на Long")


# ===================== LONG/SHORT MAIN =====================

async def do_long_short(page, context, name, margin_token="DAI", position_token=None, ls_amount=None):
    from Nemesis.nemesis_orchestrator import POLICY
    """
    Открывает Long позицию.
    - margin_token: токен маржи (по умолчанию DAI)
    - position_token: позиционный токен (из плана сессии, иначе случайный)
    - ls_amount: сумма маржи в DAI (из плана сессии, иначе случайная)
    - Всегда Long (Short глючит с пустым интерфейсом)
    - Плечо 2x (дефолт)
    """
    if not position_token:
        position_tokens = [t for t in PERP_TOKENS if t != margin_token]
        if not position_tokens:
            logging.warning(f"[{name}] [WARN] Нет доступных токенов для позиции")
            return False
        position_token = random.choice(position_tokens)

    direction = "Long"  # всегда Long — Short глючит с пустым интерфейсом
    leverage = 2

    for attempt in range(MAX_RETRIES):
        try:
            logging.info(
                f"[{name}]  Позиция: {direction} {leverage}x "
                f"{position_token}/{margin_token} (попытка {attempt + 1})"
            )

            # --- 2. Переключаемся на нужную вкладку ---
            if direction == "Short":
                await click_short_tab(page, name)
            else:
                await click_long_tab(page, name)
            await random_mouse_wiggle(page)

            # --- 3. Выбираем позиционный токен ---
            await human_pause(1.0, 2.5)
            pos_label = "Buy" if direction == "Long" else "Sell"
            pos_btn = get_field_token_button(page, pos_label)
            await ensure_token_selected(page, name, pos_btn, position_token, log_context=f"Position token ({pos_label})")

            # --- 3.5. Проверяем что маржинальный токен = DAI ---
            margin_label = "Use"
            margin_btn = get_field_token_button(page, margin_label)
            await ensure_token_selected(page, name, margin_btn, margin_token, log_context=f"Margin token ({margin_label})")

            # --- 4. Вводим сумму (посимвольно) ---
            await human_pause(2.0, 3.5)
            margin_balance = await read_balance(page, "Use")
            if margin_balance is not None:
                logging.info(f"[{name}]  Margin (Use) баланс: {margin_balance}")

            if ls_amount is not None:
                if margin_balance is not None:
                    available = margin_balance - MIN_DAI_RESERVE
                    amount = min(ls_amount, max(available, LS_DAI_MIN))
                    amount = round(amount, 2)
                else:
                    amount = ls_amount
            else:
                if margin_balance:
                    available = margin_balance - MIN_DAI_RESERVE
                    max_amount = min(LS_DAI_MAX, max(available, LS_DAI_MIN))
                    amount = round(random.uniform(LS_DAI_MIN, max_amount), 2)
                else:
                    amount = round(random.uniform(LS_DAI_MIN, LS_DAI_MAX), 2)

            # Поиск инпута для ввода суммы маржи
            amount_input = None

            # Попытка 1: через метку "Use"
            try:
                candidate = get_field_input(page, "Use")
                await candidate.wait_for(state="visible", timeout=UI_TIMEOUT)
                amount_input = candidate
                logging.info(f"[{name}]  Input найден через 'Use'")
            except TimeoutError:
                logging.info(f"[{name}] [INFO] Input 'Use' не найден, пробуем фоллбэки...")

            # Попытка 2: через Sell/Buy label
            if amount_input is None:
                try:
                    fallback_label = "Sell" if direction == "Short" else "Buy"
                    candidate = get_field_input(page, fallback_label)
                    await candidate.wait_for(state="visible", timeout=3_000)
                    amount_input = candidate
                    logging.info(f"[{name}]  Input найден через '{fallback_label}'")
                except TimeoutError:
                    pass

            # Попытка 3: через placeholder
            if amount_input is None:
                try:
                    inputs = page.locator("input[placeholder='0.00']")
                    count = await inputs.count()
                    if count >= 2:
                        amount_input = inputs.nth(count - 1)
                        await amount_input.wait_for(state="visible", timeout=3_000)
                        logging.info(f"[{name}]  Input найден через placeholder (последний из {count})")
                    elif count == 1:
                        amount_input = inputs.first
                        logging.info(f"[{name}]  Input найден через placeholder (единственный)")
                except TimeoutError:
                    pass

            if amount_input is None:
                logging.error(f"[{name}] [FAIL] Не удалось найти поле ввода суммы маржи")
                return False

            await human_click(amount_input, name, "Margin amount field")
            await human_pause(0.3, 0.8)
            await human_type(page, str(amount), field=amount_input)
            logging.info(f"[{name}]  Ввёл сумму: {amount} {margin_token}")
            await human_pause(2.0, 4.0)

            # --- 5.5. Нажимаем "Open Nx Short/Long" — ЭТО АНАЛОГ "Review" В LIQUIDITY ---
            await human_pause(0.5, 1.5)
            open_btn = page.get_by_role(
                "button",
                name=re.compile(rf"Open {leverage}x {direction}", re.IGNORECASE),
            )
            try:
                await open_btn.wait_for(state="visible", timeout=UI_TIMEOUT)
                if await open_btn.is_enabled():
                    await human_click(open_btn, name, f"Open {leverage}x {direction}")
                    logging.info(f"[{name}]  Нажат: Open {leverage}x {direction}")
                    await human_pause(1.0, 2.0)
                else:
                    logging.info(
                        f"[{name}] [INFO] Кнопка 'Open {leverage}x {direction}' disabled"
                    )
            except TimeoutError:
                # Кнопка не найдена — ждём и проверяем снова
                logging.info(
                    f"[{name}] [INFO] Кнопка 'Open {leverage}x {direction}' не найдена, "
                    f"ждём 5-10с..."
                )
                await asyncio.sleep(random.uniform(5.0, 10.0))
                open_btn = page.get_by_role(
                    "button",
                    name=re.compile(rf"Open {leverage}x {direction}", re.IGNORECASE),
                )
                btn_visible = False
                try:
                    btn_visible = await open_btn.is_visible(timeout=3_000)
                except TimeoutError:
                    pass

                if btn_visible:
                    if await open_btn.is_enabled():
                        await human_click(open_btn, name, f"Open {leverage}x {direction}")
                        logging.info(f"[{name}]  Нажат (после ожидания): Open {leverage}x {direction}")
                        await human_pause(1.0, 2.0)
                    else:
                        logging.info(
                            f"[{name}] [INFO] Кнопка 'Open {leverage}x {direction}' disabled"
                        )
                else:
                    logging.warning(
                        f"[{name}] [WARN] Кнопка не найдена, перезагружаю и повторяю LS..."
                    )
                    await page.reload()
                    await page.wait_for_load_state("networkidle")
                    await idle(3.0, 6.0)
                    continue  # Переход к следующей попытке в цикле

            # --- 6. Подтверждаем транзакции через универсальный кликер ---
            logging.info(f"[{name}] [RETRY] Начинаю цепочку подтверждений для {direction} {position_token}")
            await human_pause(3.0, 5.0)  # NEW: увеличил паузу для обновления UI модалки
            
            total_steps = await confirm_dapp_transaction(
                page, context, name,
                action_name=f"long_short_{direction}_{position_token}",  # NEW: добавил токен в action_name
                max_iterations=4,  # достаточно для Swap + Approve + Open
                click_fn=click_nemesis_action_button,
                terminal_fn=is_terminal_action,
                post_confirm_wait=(20.0, 30.0),  # увеличил ожидание после MetaMask
                policy=POLICY,
            )

            if total_steps == 0:
                logging.warning(f"[{name}] [WARN] Не удалось подтвердить позицию (нет шагов)")

            # --- 7. Ждём уведомление ---
            if await wait_for_toast(page, rf"{leverage}x {direction} Opened", timeout=TX_WAIT_TIMEOUT):
                logging.info(f"[{name}] [OK] {leverage}x {direction} позиция открыта!")
                return True
            else:
                # Ищем кнопку Retry
                logging.info(f"[{name}] [SEARCH] Toast не появился, ищу кнопку Retry...")
                await human_pause(2.0, 4.0)
                retry_btn = page.get_by_role("button", name=re.compile(r"Retry", re.IGNORECASE))
                try:
                    if await retry_btn.is_visible(timeout=UI_TIMEOUT) and await retry_btn.is_enabled():
                        await human_click(retry_btn, name, "Retry (failed tx)")
                        logging.info(f"[{name}]  Нажал Retry")
                        await human_pause(1.0, 2.0)

                        # Попытка подтвердить Retry через MetaMask
                        mm_retry = await handle_multiple_metamask_popups(
                            context, name, f"ls_retry_{direction}", max_popups=2, policy=POLICY
                        )
                        if mm_retry > 0:
                            logging.info(f"[{name}] [OK] Retry подтверждён в MetaMask")
                            await asyncio.sleep(random.uniform(8.0, 12.0))
                            if await wait_for_toast(page, rf"{leverage}x {direction} Opened", timeout=TX_WAIT_TIMEOUT):
                                logging.info(f"[{name}] [OK] {leverage}x {direction} позиция открыта (после Retry)!")
                                return True
                        else:
                            logging.warning(f"[{name}] [WARN] MetaMask не подтвердил Retry")
                except TimeoutError:
                    logging.info(f"[{name}] [INFO] Кнопка Retry не найдена")

                logging.warning(f"[{name}] [WARN] Уведомление не появилось, пробую reload + повтор LS...")
                await asyncio.sleep(random.uniform(5.0, 7.0))
                await page.reload()
                await page.wait_for_load_state("networkidle")
                await idle(3.0, 5.0)

        except Exception as e:
            logging.error(f"[{name}] [FAIL] Ошибка при Long/Short (попытка {attempt + 1}): {e}")
            try:
                await page.reload()
                await page.wait_for_load_state("networkidle")
                await idle(3.0, 5.0)
            except Exception:
                pass

    logging.error(f"[{name}] [FAIL] Исчерпаны попытки для Long/Short")
    return False
