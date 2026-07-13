"""
Nemesis Swap — операции свапа токенов (ETH→DAI, DAI→token).

Вынесено из nemesis_trading.py при рефакторинге.
"""

import asyncio
import logging
import random
import re
from playwright.async_api import TimeoutError

from core.wallet import (
    confirm_dapp_transaction,
)
from core.utils import idle
from Nemesis.nemesis_helpers import (
    # constants
    MIN_ETH_RESERVE,
    SWAP_ETH_TO_DAI_LOW,
    SWAP_ETH_TO_DAI_HIGH,
    DAI_THRESHOLD,
    MIN_DAI_RESERVE,
    SWAP_DAI_MIN,  # NEW: лимиты для свапа DAI→token
    SWAP_DAI_MAX,
    LS_DAI_MIN,
    LS_DAI_MAX,
    LIQ_DAI_MIN,
    LIQ_DAI_MAX,
    DAI_SWAP_TOKENS,
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
    read_from_balance,
    read_to_balance,
    select_token_in_dialog,
    ensure_token_selected,
    # universal clicker
    click_nemesis_action_button,
    is_terminal_action,
)
from Nemesis.nemesis_selectors import (
    get_field_input,
    get_field_token_button,
    get_swap_tab,
    wait_for_toast,
)


# ===================== NAVIGATION =====================

async def click_swap_tab(page, name):
    """Переключается на вкладку Swap."""
    await human_pause(0.5, 1.5)
    await random_mouse_wiggle(page)
    swap_btn = get_swap_tab(page)
    await human_click(swap_btn, name, "Swap tab")
    await human_pause(1.0, 2.5)
    logging.info(f"[{name}] 🔄 Переключился на Swap")


# ===================== SWAP ETH → DAI =====================

async def do_swap_eth_to_dai(page, context, name, swap_amount=None):
    from Nemesis.nemesis_orchestrator import POLICY
    """
    Шаг 1: Свап ETH → DAI.
    - Проверяем текущий баланс DAI перед свапом:
      если DAI < DAI_THRESHOLD (30) → свапаем SWAP_ETH_TO_DAI_LOW (0.01 ETH)
      если DAI >= DAI_THRESHOLD (30) → свапаем SWAP_ETH_TO_DAI_HIGH (0.001 ETH)
    - Контроль: оставлять >= MIN_ETH_RESERVE ETH
    - Если уведомление не появилось → повторный Confirm Swap

    Returns: dai_balance (float) или None при ошибке
    """
    for attempt in range(MAX_RETRIES):
        try:
            logging.info(f"[{name}] 🔄 Свап ETH → DAI (попытка {attempt + 1})")

            # --- 1. Переключаемся на Swap ---
            await click_swap_tab(page, name)
            await random_mouse_wiggle(page)

            # --- 2. Проверяем, что To = DAI ---
            await human_pause(0.5, 1.5)
            to_token_btn = get_field_token_button(page, "To")
            await ensure_token_selected(page, name, to_token_btn, "DAI", log_context="To")

            # --- 3. Проверяем текущий баланс DAI и определяем сумму свапа ---
            await human_pause(0.5, 1.0)
            dai_balance_before = await read_to_balance(page, name)

            # Сумма свапа зависит от переданного аргумента или текущего баланса DAI
            if swap_amount is not None:
                logging.info(f"[{name}] 💰 Использую фиксированную сумму для свапа: {swap_amount} ETH")
            elif dai_balance_before is not None and dai_balance_before >= DAI_THRESHOLD:
                swap_amount = SWAP_ETH_TO_DAI_HIGH  # 0.001 ETH — DAI уже достаточно
                logging.info(
                    f"[{name}] 💰 DAI баланс: {dai_balance_before} (>= {DAI_THRESHOLD}), "
                    f"свапаем минимум: {swap_amount} ETH"
                )
            else:
                swap_amount = SWAP_ETH_TO_DAI_LOW  # 0.01 ETH — нужно больше DAI
                dai_info = f"{dai_balance_before}" if dai_balance_before is not None else "неизвестно"
                logging.info(
                    f"[{name}] 💰 DAI баланс: {dai_info} (< {DAI_THRESHOLD}), "
                    f"свапаем: {swap_amount} ETH"
                )

            # --- 4. Проверяем баланс ETH ---
            eth_balance = await read_from_balance(page, name)
            if eth_balance is not None:
                available = eth_balance - MIN_ETH_RESERVE
                if available < swap_amount:
                    logging.warning(
                        f"[{name}] ⚠️ ETH мало ({eth_balance}). "
                        f"Доступно: {available:.4f}, нужно: {swap_amount}"
                    )
                    return None
                logging.info(
                    f"[{name}] 💰 ETH баланс: {eth_balance}, "
                    f"доступно для свапа: {available:.4f}"
                )

            # --- 5. Вводим сумму (посимвольно) ---
            amount_input = get_field_input(page, "From")
            try:
                await amount_input.wait_for(state="visible", timeout=UI_TIMEOUT)
            except TimeoutError:
                pass
            await human_click(amount_input, name, "ETH amount field")
            await human_pause(0.3, 0.8)
            await human_type(page, str(swap_amount), field=amount_input)
            logging.info(f"[{name}] 🔄 Ввёл сумму: {swap_amount} ETH")
            await human_pause(1.0, 2.5)

            # --- 6. Нажимаем Swap ---
            swap_btn = page.get_by_role("button", name="Swap").last
            await human_pause(0.5, 1.5)
            await human_click(swap_btn, name, "Swap button")
            await human_pause(1.0, 2.0)

            # --- 7. Подтверждаем транзакцию (Approve + Confirm Swap + MetaMask) ---
            logging.info(f"[{name}] 🔄 Начинаю цепочку подтверждений для свапа ETH → DAI")
            await human_pause(2.0, 3.0)  # Пауза перед поиском кнопок
            
            steps = await confirm_dapp_transaction(
                page, context, name,
                action_name="swap_eth_dai",
                max_iterations=3,  # для обработки Approve + Confirm
                click_fn=click_nemesis_action_button,
                terminal_fn=is_terminal_action,
                post_confirm_wait=(20.0, 30.0),
                policy=POLICY,
            )
            if steps == 0:
                logging.warning(f"[{name}] ⚠️ Не удалось подтвердить свап ETH → DAI")

            # --- 8. Ждём уведомление ---
            if await wait_for_toast(page, r"Swapped", timeout=TX_WAIT_TIMEOUT):
                logging.info(f"[{name}] ✅ Свап ETH → DAI выполнен!")
                # --- 9. Читаем баланс DAI из To ---
                await human_pause(1.0, 2.0)
                dai_balance = await read_to_balance(page, name)
                if dai_balance:
                    logging.info(f"[{name}] 💰 DAI баланс после свапа: {dai_balance}")
                return dai_balance
            else:
                logging.warning(f"[{name}] ⚠️ Уведомление о свапе не появилось, повторное подтверждение...")
                await human_pause(3.0, 5.0)
                retry_steps = await confirm_dapp_transaction(
                    page, context, name,
                    action_name="swap_eth_dai_retry",
                    max_iterations=2,
                    click_fn=click_nemesis_action_button,
                    terminal_fn=is_terminal_action,
                    policy=POLICY,
                )
                if retry_steps > 0:
                    if await wait_for_toast(page, r"Swapped", timeout=TX_WAIT_TIMEOUT):
                        logging.info(f"[{name}] ✅ Свап ETH → DAI выполнен (ретрай)!")
                        await human_pause(1.0, 2.0)
                        dai_balance = await read_to_balance(page, name)
                        return dai_balance
                    else:
                        logging.warning(f"[{name}] ⚠️ Свап не удался даже после ретрая")
                
                logging.warning(f"[{name}] ⚠️ Ошибка или не появилось уведомление, перезагружаю страницу...")
                await asyncio.sleep(random.uniform(5.0, 7.0))
                await page.reload()
                await page.wait_for_load_state("networkidle")
                await idle(3.0, 5.0)

        except Exception as e:
            logging.error(f"[{name}] ❌ Ошибка при свапе ETH → DAI (попытка {attempt + 1}): {e}")
            await page.reload()
            await idle(3.0, 5.0)

    logging.error(f"[{name}] ❌ Исчерпаны попытки свапа ETH → DAI")
    return None


# ===================== SWAP DAI → TOKEN =====================

async def do_swap_dai_to_token(page, context, name, target_token=None, swap_amount=None):
    from Nemesis.nemesis_orchestrator import POLICY
    """
    Шаг 2: Свап DAI → target_token.
    - target_token: токен для обмена (из плана сессии)
    - swap_amount: сумма в DAI (из плана сессии, иначе случайная)
    - Контроль: оставлять ≥ MIN_DAI_RESERVE DAI
    - Если уведомление не появилось → reload + ретрай (максимум 1 повтор)

    Returns: target_token (str) или None
    """
    if not target_token:
        target_token = random.choice(DAI_SWAP_TOKENS)

    for attempt in range(MAX_RETRIES):
        try:
            logging.info(f"[{name}] 🔄 Свап DAI → {target_token} (попытка {attempt + 1})")

            # --- 1. Переключаемся на Swap ---
            await click_swap_tab(page, name)
            await random_mouse_wiggle(page)

            # --- 2. Убеждаемся что From = DAI ---
            await human_pause(0.5, 1.5)
            from_token_btn = get_field_token_button(page, "From")
            await ensure_token_selected(page, name, from_token_btn, "DAI", log_context="From")

            # --- 3. Выбираем To токен ---
            await human_pause(0.5, 1.5)
            to_token_btn = get_field_token_button(page, "To")
            await ensure_token_selected(page, name, to_token_btn, target_token, log_context="To")

            # --- 4. Читаем баланс DAI ---
            await human_pause(0.5, 1.0)
            dai_balance = await read_from_balance(page, name)

            # Используем запланированную сумму если задана, иначе рассчитываем случайно
            if swap_amount is not None:
                if dai_balance is not None:
                    available = dai_balance - MIN_DAI_RESERVE
                    current_swap_amount = min(swap_amount, max(available, SWAP_DAI_MIN))
                    current_swap_amount = round(current_swap_amount, 2)
                else:
                    current_swap_amount = swap_amount
            else:
                if dai_balance is not None:
                    available = dai_balance - MIN_DAI_RESERVE
                    if available < SWAP_DAI_MIN:
                        logging.warning(
                            f"[{name}] ⚠️ DAI мало ({dai_balance}). "
                            f"Доступно: {available:.2f}, минимум: {SWAP_DAI_MIN}"
                        )
                        return None
                    max_amount = min(SWAP_DAI_MAX, available)
                    current_swap_amount = round(random.uniform(SWAP_DAI_MIN, max_amount), 2)
                else:
                    current_swap_amount = round(random.uniform(SWAP_DAI_MIN, SWAP_DAI_MAX), 2)

            logging.info(f"[{name}] 🔄 Сумма свапа: {current_swap_amount} DAI")

            # --- 5. Вводим сумму (посимвольно) ---
            amount_input = get_field_input(page, "From")
            try:
                await amount_input.wait_for(state="visible", timeout=UI_TIMEOUT)
            except TimeoutError:
                pass
            await human_click(amount_input, name, "DAI amount field")
            await human_pause(0.3, 0.8)
            await human_type(page, str(current_swap_amount), field=amount_input)
            logging.info(f"[{name}] 🔄 Ввёл сумму: {current_swap_amount} DAI")
            await human_pause(1.0, 2.5)

            # --- 6. Нажимаем Swap ---
            swap_btn = page.get_by_role("button", name="Swap").last
            await human_pause(0.5, 1.5)
            await human_click(swap_btn, name, "Swap button")
            await human_pause(1.0, 2.0)

            # --- 7. Подтверждаем транзакцию (Approve + Confirm + MetaMask) ---
            steps = await confirm_dapp_transaction(
                page, context, name,
                action_name=f"swap_dai_{target_token}",
                max_iterations=3,
                click_fn=click_nemesis_action_button,
                terminal_fn=is_terminal_action,
                post_confirm_wait=(20.0, 30.0),
                policy=POLICY,
            )
            if steps == 0:
                logging.warning(f"[{name}] ⚠️ Не удалось подтвердить свап DAI → {target_token}")

            # --- 8. Ждём уведомление ---
            if await wait_for_toast(page, r"Swapped", timeout=TX_WAIT_TIMEOUT):
                logging.info(f"[{name}] ✅ Свап DAI → {target_token} выполнен!")
                return target_token
            else:
                logging.warning(f"[{name}] ⚠️ Уведомление о свапе не появилось, повторное подтверждение...")
                await human_pause(3.0, 5.0)
                retry_steps = await confirm_dapp_transaction(
                    page, context, name,
                    action_name=f"swap_dai_{target_token}_retry",
                    max_iterations=2,
                    click_fn=click_nemesis_action_button,
                    terminal_fn=is_terminal_action,
                    policy=POLICY,
                )
                if retry_steps > 0:
                    if await wait_for_toast(page, r"Swapped", timeout=TX_WAIT_TIMEOUT):
                        logging.info(f"[{name}] ✅ Свап DAI → {target_token} выполнен (ретрай)!")
                        return target_token
                    else:
                        logging.warning(f"[{name}] ⚠️ Свап не удался даже после ретрая")
                
                logging.warning(f"[{name}] ⚠️ Ошибка или не появилось уведомление, перезагружаю страницу...")
                await asyncio.sleep(random.uniform(5.0, 7.0))
                await page.reload()
                await page.wait_for_load_state("networkidle")
                await idle(3.0, 5.0)

        except Exception as e:
            logging.error(f"[{name}] ❌ Ошибка при свапе DAI → {target_token} (попытка {attempt + 1}): {e}")
            await page.reload()
            await idle(3.0, 5.0)

    logging.error(f"[{name}] ❌ Исчерпаны попытки свапа DAI → {target_token}")
    return None
