"""
Nemesis Liquidity — создание liquidity position и подключение кошелька.

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
from Nemesis.nemesis_helpers import (
    # constants
    LIQ_DAI_MIN,  # NEW: лимиты для Liquidity
    LIQ_DAI_MAX,
    LIQUIDITY_TOKENS,
    TOKEN_INFO,
    UI_TIMEOUT,
    DIALOG_TIMEOUT,
    TX_WAIT_TIMEOUT,
    # anti-detect
    human_type,
    human_pause,
    random_mouse_wiggle,
    human_click,
    # helpers
    select_token_in_dialog,
    # NEW: универсальный кликер и терминальная проверка
    click_nemesis_action_button,
    is_terminal_action,
)
from Nemesis.nemesis_selectors import (
    get_liquidity_link,
    get_create_position_button,
    get_add_liquidity_button,
    get_choose_token_button,
    get_connect_wallet_button,
    get_metamask_option,
)


# ===================== WALLET CONNECTION =====================

async def connect_wallet_if_needed(page, context, name):
    """Подключает кошелёк MetaMask, если приложение его требует."""
    from Nemesis.nemesis_orchestrator import POLICY
    try:
        connect_selectors = [
            get_connect_wallet_button(page),
            page.get_by_test_id("connect-wallet-button"),
        ]

        for selector in connect_selectors:
            try:
                if await selector.is_visible(timeout=3_000):
                    logging.info(f"[{name}] 🦊 Кошелёк не подключен, подключаю...")
                    await human_pause(0.5, 1.5)
                    await human_click(selector, name, "Connect wallet")
                    await human_pause(1.0, 2.5)

                    mm_btn = get_metamask_option(page)
                    if await mm_btn.is_visible(timeout=UI_TIMEOUT):
                        await human_pause(0.5, 1.0)
                        await human_click(mm_btn, name, "MetaMask option")

                    # handle_multiple: connect может требовать 2 попапа (Next→Connect + Signature)
                    await handle_multiple_metamask_popups(
                        context, name, "connect", max_popups=2, policy=POLICY
                    )
                    await human_pause(2.0, 4.0)

                    logging.info(f"[{name}] 🦊 Кошелёк подключен")
                    return True
            except TimeoutError:
                continue

        logging.info(f"[{name}] ℹ️ Кошелёк уже подключен")
        return True

    except Exception as e:
        logging.warning(f"[{name}] ⚠️ Ошибка при подключении кошелька: {e}")
        return False


# ===================== LIQUIDITY FLOW =====================

async def do_liquidity(page, context, name, primary_token="DAI", second_token=None, liq_amount=None):
    """
    Создаёт liquidity position.
    - primary_token: первый токен в паре (DAI)
    - second_token: второй токен в паре (из плана сессии, иначе случайный)
    - liq_amount: сумма для ликвидности (из плана сессии, иначе случайная)
    - Контроль баланса: не превышать доступное количество
    - До 4 MetaMask попапов (Wrap ETH, approve, confirm)
    """
    try:
        # --- 1. Выбираем пару ---
        if not second_token:
            second_options = ["ETH"] + [
                t for t in LIQUIDITY_TOKENS if t != primary_token
            ]
            second_token = random.choice(second_options)

        logging.info(f"[{name}] 💧 Пара: {primary_token}/{second_token}")

        # --- 2. Navigate to Liquidity ---
        await human_pause(0.5, 1.5)
        await random_mouse_wiggle(page)
        liq_link = get_liquidity_link(page)
        await human_click(liq_link, name, "Liquidity link")
        await human_pause(2.0, 4.0)
        logging.info(f"[{name}] 💧 Перешёл на Liquidity")

        # --- 3. Create new position ---
        create_btn = get_create_position_button(page)
        try:
            await create_btn.wait_for(state="visible", timeout=DIALOG_TIMEOUT)
            await human_pause(0.5, 1.5)
            await human_click(create_btn, name, "New position link")
            await human_pause(1.5, 3.0)
        except TimeoutError:
            logging.error(f"[{name}] ❌ 'New' link не найдена")
            return False

        # --- 4. Select first token ---
        await human_pause(0.5, 1.0)
        first_token_btn = get_choose_token_button(page, 0)
        try:
            await first_token_btn.wait_for(state="visible", timeout=DIALOG_TIMEOUT)
            await human_pause(0.5, 1.0)
            await human_click(first_token_btn, name, "Choose token (1)")
            await human_pause(0.5, 1.5)
            dialog = page.get_by_role("dialog", name="Select a Token")
            try:
                await dialog.wait_for(state="visible", timeout=DIALOG_TIMEOUT)
            except TimeoutError:
                pass
            await human_pause(0.8, 2.0)
            await select_token_in_dialog(page, name, primary_token)
            await human_pause(1.0, 2.5)
        except TimeoutError:
            logging.warning(f"[{name}] ⚠️ Не удалось выбрать первый токен")
            return False

        # --- 5. Select second token ---
        await human_pause(0.5, 1.0)
        second_token_btn = page.get_by_role("button", name="Choose a token")
        try:
            await second_token_btn.wait_for(state="visible", timeout=DIALOG_TIMEOUT)
            await human_pause(0.5, 1.0)
            await human_click(second_token_btn, name, "Choose token (2)")
            await human_pause(0.5, 1.5)
            dialog = page.get_by_role("dialog", name="Select a Token")
            try:
                await dialog.wait_for(state="visible", timeout=DIALOG_TIMEOUT)
            except TimeoutError:
                pass
            await human_pause(0.8, 2.0)
            await select_token_in_dialog(page, name, second_token)
            await human_pause(1.0, 2.5)
        except TimeoutError:
            logging.warning(f"[{name}] ⚠️ Не удалось выбрать второй токен")
            return False

        # --- 6. Add Liquidity ---
        await human_pause(0.5, 1.5)
        add_liq_btn = get_add_liquidity_button(page)
        try:
            await add_liq_btn.wait_for(state="visible", timeout=DIALOG_TIMEOUT)
            await human_pause(0.5, 1.0)
            await human_click(add_liq_btn, name, "Add Liquidity")
            await human_pause(1.5, 3.0)
        except TimeoutError:
            logging.warning(f"[{name}] ⚠️ 'Add Liquidity' не найдена")
            return False

        # --- 7. Fill amount (посимвольно) ---
        await human_pause(0.5, 1.0)
        try:
            amount_input = page.locator("input[placeholder='0.00']").first
            await human_click(amount_input, name, "Liquidity amount field")
            await human_pause(0.3, 0.8)
            if liq_amount is not None:
                liq_amt = liq_amount
            else:
                liq_amt = round(random.uniform(LIQ_DAI_MIN, LIQ_DAI_MAX), 2)
            await human_type(page, str(liq_amt), field=amount_input)
            logging.info(f"[{name}] 💧 Ввёл сумму: {liq_amt} {primary_token}")
            await human_pause(1.0, 2.5)
        except Exception as e:
            logging.warning(f"[{name}] ⚠️ Не удалось ввести сумму: {e}")
            return False

        # --- 8. Click Review (навигационная кнопка, НЕ MetaMask) ---
        await human_pause(2.0, 4.0)
        review_btn = page.get_by_role("button", name="Review")
        try:
            await review_btn.wait_for(state="visible", timeout=15_000)
            await human_click(review_btn, name, "Review")
            logging.info(f"[{name}] 👆 Нажал Review")
            await human_pause(2.0, 4.0)
        except TimeoutError:
            logging.warning(f"[{name}] ⚠️ Кнопка 'Review' не найдена за 15с")
            return False

        # --- 9. Подтверждаем транзакции через универсальный кликер ---
        logging.info(f"[{name}] 🔄 Начинаю цепочку подтверждений для ликвидности {primary_token}/{second_token}")
        await human_pause(3.0, 5.0)  # NEW: увеличил паузу для обновления UI модалки
        
        from Nemesis.nemesis_orchestrator import POLICY
        total_steps = await confirm_dapp_transaction(
            page, context, name,
            action_name=f"liquidity_{primary_token}_{second_token}",  # NEW: добавил токены в action_name
            max_iterations=4,  # достаточно для Approve + Add Liquidity
            click_fn=click_nemesis_action_button,
            terminal_fn=is_terminal_action,
            post_confirm_wait=(20.0, 30.0),  # увеличил ожидание после MetaMask
            auto_mm_check_delay=20.0,  # NEW: жду 20с для проверки авто-попапа MetaMask после КАЖДОГО подтверждения
            policy=POLICY,
        )

        if total_steps == 0:
            logging.warning(f"[{name}] ⚠️ Не удалось подтвердить ликвидность (нет шагов)")
            return False

        # Ожидание 30-40 секунд для гарантированного завершения, так как toast скрыт за модалкой
        wait_time = random.uniform(30.0, 40.0)
        logging.info(f"[{name}] ⏳ Ожидаю {wait_time:.1f}с для завершения транзакции (обход бага UI)...")
        await asyncio.sleep(wait_time)

        logging.info(
            f"[{name}] ✅ Liquidity position создана! ({total_steps} подтверждений)"
        )
        return True

    except Exception as e:
        logging.error(f"[{name}] ❌ Ошибка при Liquidity: {e}")
        return False
