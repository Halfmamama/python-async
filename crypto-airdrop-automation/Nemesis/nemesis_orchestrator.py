"""
Nemesis Orchestrator — точка входа, управление сценариями, мультиаккинг.

Сценарии запуска (SCENARIO):
  "all"   — всё: ETH→DAI + DAI→token + Long/Short + Liquidity
  "swap"  — только свапы: ETH→DAI + DAI→token
  "ls"    — только Long/Short (с предварительным ETH→DAI для маржи)
  "liq"   — только Liquidity (с предварительным ETH→DAI)

Можно комбинировать списком: ["swap", "ls"], ["swap", "liq"], ["ls", "liq"]
"""

import asyncio
import logging
import random
from playwright.async_api import async_playwright

# ===================== TARGET ACCOUNTS CONFIG =====================
TARGET_ACCOUNTS = []

# ===================== ACTION CONFIG =====================
# Диапазон количества DAI для каждой из операций (свап, лс, ликвидность)
DAI_AMOUNT_MIN = 0.1
DAI_AMOUNT_MAX = 0.5

# Фиксированная сумма ETH для свапа в DAI (временно)
# Предыдущее решение: передавать None (динамический расчет в do_swap_eth_to_dai)
SWAP_ETH_AMOUNT = 0.0001

import config
from core.browser import launch_context
from core.wallet import (
    unlock_metamask,
    close_network_warning,
    WalletPolicy,
)
from core import wallet
from core.utils import idle, safe_open_with_retry, ProxyConnectionError
from core.logger import setup_logger

from Nemesis.nemesis_helpers import (
    URL_APP,
    RUN_MODE,
    MAX_CONCURRENT,
    MAX_RETRIES,
    SWAP_ETH_TO_DAI_LOW,
    SWAP_ETH_TO_DAI_HIGH,
    MIN_ETH_RESERVE,
    MIN_DAI_RESERVE,
    SWAP_DAI_MIN,  # NEW: разделённые лимиты
    SWAP_DAI_MAX,
    LS_DAI_MIN,
    LS_DAI_MAX,
    LIQ_DAI_MIN,
    LIQ_DAI_MAX,
    SESSION_PAIR_TOKENS,
    select_profiles,
    plan_session,
    random_mouse_wiggle,
    human_pause,
)

# Импортируем TARGET_ACCOUNTS из helpers и переопределяем
from Nemesis import nemesis_helpers
nemesis_helpers.TARGET_ACCOUNTS = TARGET_ACCOUNTS

from Nemesis.nemesis_swap import (
    do_swap_eth_to_dai,
    do_swap_dai_to_token,
)
from Nemesis.nemesis_ls import do_long_short
from Nemesis.nemesis_liquidity import (
    do_liquidity,
    connect_wallet_if_needed,
)

# ===================== NETWORK CONFIG =====================
# Устанавливаем сеть для проекта Nemesis (Sepolia testnet)
POLICY = WalletPolicy(
    network="sepolia",
    allowed_actions=("connect", "sign", "approve", "confirm"),
)

# ===================== SCENARIO CONFIG =====================
# Выберите действия для выполнения:
#   "all"   — всё: ETH→DAI + DAI→token + Long/Short + Liquidity
#   "swap"  — только свапы: ETH→DAI + DAI→token
#   "ls"    — только Long/Short (без ETH→DAI)
#   "liq"   — только Liquidity (без ETH→DAI)
#   ["swap","ls"] — можно комбинировать списком
SCENARIO = "all"


def _scenario_has(action: str) -> bool:
    """Проверяет, включено ли действие в сценарий."""
    if SCENARIO == "all":
        return True
    if isinstance(SCENARIO, list):
        return action in SCENARIO
    return SCENARIO == action


# ===================== MAIN PROFILE RUNNER =====================

async def run_profile(playwright, name, cfg, semaphore, results):
    async with semaphore:
        context = None
        page = None
        results[name] = {
            "wallet": False,
            "connected": False,
            "swap_eth_dai": False,
            "swap_dai_token": False,
            "swapped_token": None,
            "long_short": False,
            "liquidity": False,
            "error": None,
        }

        try:
            logging.info(f"[{name}] [START] start")
            wallet_addr = cfg.get("wallet_address")
            if not wallet_addr:
                raise ValueError("wallet_address missing in config")

            # --- 1. Запуск браузера и MetaMask ---
            context = await launch_context(playwright, name, cfg)
            mm = await unlock_metamask(context, config.PASSWORD, name)
            if mm:
                await close_network_warning(mm, name)
                await mm.close()
            results[name]["wallet"] = True

            # --- 2. Основная страница ---
            page = await context.new_page()

            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    logging.info(
                        f"[{name}] [RETRY] Открытие {URL_APP} (попытка {attempt})"
                    )
                    await safe_open_with_retry(page, URL_APP, name)
                    await page.wait_for_load_state("networkidle")
                    await idle(3.0, 6.0)

                    # --- 3. Подключение кошелька ---
                    connected = await connect_wallet_if_needed(
                        page, context, name
                    )
                    results[name]["connected"] = connected
                    await human_pause(2.0, 4.0)

                    # --- 4. Swap ETH → DAI (только если сценарий включает swap / all) ---
                    # Для "ls" и "liq" — пропускаем, пользователь сам обеспечивает DAI
                    need_dai = _scenario_has("swap")  # "all" включает "swap"
                    dai_balance = None
                    if need_dai:
                        await random_mouse_wiggle(page)
                        # do_swap_eth_to_dai(page, context, name)  # <--- Предыдущее решение (без фикс. суммы)
                        dai_balance = await do_swap_eth_to_dai(
                            page, context, name, swap_amount=SWAP_ETH_AMOUNT
                        )
                        results[name]["swap_eth_dai"] = dai_balance is not None
                        await human_pause(3.0, 6.0)
                        if dai_balance is None:
                            logging.warning(f"[{name}] [WARN] ETH→DAI не удался, DAI=0, продолжаем...")
                            dai_balance = 0.0
                    else:
                        results[name]["swap_eth_dai"] = False  # не требуется

                    # --- 5. Определяем что делать по сценарию ---
                    run_swap = _scenario_has("swap")
                    run_ls = _scenario_has("ls")
                    run_liq = _scenario_has("liq")
                    is_all = SCENARIO == "all"

                    pair_token = None
                    plan = None

                    if is_all:
                        # Полный сценарий: план сессии на все 3 операции
                        plan = plan_session(dai_balance or 15.0)
                        
                        # Применяем фиксированную сумму DAI если задана
                        if DAI_AMOUNT_MIN is not None and DAI_AMOUNT_MAX is not None:
                            plan["swap_amount"] = round(random.uniform(DAI_AMOUNT_MIN, DAI_AMOUNT_MAX), 2)
                            plan["ls_amount"] = round(random.uniform(DAI_AMOUNT_MIN, DAI_AMOUNT_MAX), 2)
                            plan["liq_amount"] = round(random.uniform(DAI_AMOUNT_MIN, DAI_AMOUNT_MAX), 2)

                        results[name]["pair_token"] = plan["pair_token"]
                        results[name]["plan"] = plan
                        logging.info(
                            f"[{name}] [PLAN] Сессия: DAI/{plan['pair_token']} | "
                            f"свап={plan['swap_amount']} | лс={plan['ls_amount']} | "
                            f"ликв={plan['liq_amount']} DAI"
                        )
                    elif run_swap:
                        # Только свап: выбираем случайную пару
                        pair_token = random.choice(SESSION_PAIR_TOKENS)
                        results[name]["pair_token"] = pair_token

                    # --- 6. Swap DAI → token ---
                    if run_swap:
                        await random_mouse_wiggle(page)
                        if plan:
                            swap_args = {
                                "target_token": plan["pair_token"],
                                "swap_amount": plan["swap_amount"],
                            }
                        else:
                            swap_args = {
                                "target_token": pair_token,
                                "swap_amount": round(random.uniform(DAI_AMOUNT_MIN, DAI_AMOUNT_MAX), 2),
                            }
                        swapped_token = await do_swap_dai_to_token(
                            page, context, name, **swap_args
                        )
                        results[name]["swap_dai_token"] = swapped_token is not None
                        results[name]["swapped_token"] = swapped_token
                        await human_pause(3.0, 6.0)

                    # --- 7. Long/Short ---
                    if run_ls:
                        await random_mouse_wiggle(page)
                        if plan:
                            ls_args = {
                                "margin_token": "DAI",
                                "position_token": plan["pair_token"],
                                "ls_amount": plan["ls_amount"],
                            }
                        else:
                            ls_args = {
                                "margin_token": "DAI",
                                "position_token": pair_token,
                                "ls_amount": round(random.uniform(DAI_AMOUNT_MIN, DAI_AMOUNT_MAX), 2),
                            }
                        ls_result = await do_long_short(
                            page, context, name, **ls_args
                        )
                        results[name]["long_short"] = ls_result

                        if not ls_result:
                            logging.warning(
                                f"[{name}] [WARN] Long/Short не удался, "
                                f"перезагружаю страницу и продолжаю..."
                            )
                            try:
                                await page.reload()
                                await page.wait_for_load_state("networkidle")
                                await idle(3.0, 6.0)
                            except Exception as reload_err:
                                logging.warning(f"[{name}] [WARN] Ошибка при reload: {reload_err}")
                        else:
                            await human_pause(3.0, 6.0)

                    # --- 8. Liquidity ---
                    if run_liq:
                        await random_mouse_wiggle(page)
                        if plan:
                            liq_args = {
                                "primary_token": "DAI",
                                "second_token": plan["pair_token"],
                                "liq_amount": plan["liq_amount"],
                            }
                        else:
                            liq_args = {
                                "primary_token": "DAI",
                                "second_token": pair_token,
                                "liq_amount": round(random.uniform(DAI_AMOUNT_MIN, DAI_AMOUNT_MAX), 2),
                            }
                        liq_result = await do_liquidity(
                            page, context, name, **liq_args
                        )
                        results[name]["liquidity"] = liq_result

                    break  # Успех

                except Exception as e:
                    logging.warning(
                        f"[{name}] [WARN] Ошибка на попытке {attempt}: {e}"
                    )
                    if attempt == MAX_RETRIES:
                        raise
                    await page.reload()
                    await idle(5, 10)

        except ProxyConnectionError as e:
            results[name]["error"] = str(e)
            results[name]["proxy_suspect"] = True
            logging.error(f"[{name}] [FAIL] Proxy connection failure: {e}")
            if page:
                from core.failure import dump_failure
                await dump_failure(page, name, "nemesis")
        except Exception as e:
            results[name]["error"] = str(e)
            logging.error(f"[{name}] [FAIL] Nemesis failed: {e}")
            if page:
                from core.failure import dump_failure
                await dump_failure(page, name, "nemesis")
        finally:
            if context:
                from core.browser import stop_tracing
                await stop_tracing(context, name, failed=bool(results[name]["error"]))
                await context.close()
            logging.info(f"[{name}] done")


# ===================== ENTRY POINT =====================

async def main():
    setup_logger()
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    profiles = select_profiles()

    if not profiles:
        print("[FAIL] No profiles to run")
        return

    scenario_display = SCENARIO if isinstance(SCENARIO, str) else "+".join(SCENARIO)

    print(f"\n===== NEMESIS TRADING (Sepolia) =====")
    print(f"Сценарий: {scenario_display}")
    print(f"Аккаунтов: {len(profiles)} | Параллельно: {MAX_CONCURRENT}")
    print(f"Swap ETH→DAI: {SWAP_ETH_AMOUNT} ETH (fixed) | Min ETH: {MIN_ETH_RESERVE}")
    print(f"Пары для сессии: DAI + {' | '.join(SESSION_PAIR_TOKENS)}")
    print(f"Min DAI reserve: {MIN_DAI_RESERVE}")
    print(f"DAI лимиты: от {DAI_AMOUNT_MIN} до {DAI_AMOUNT_MAX}\n")

    results = {}
    async with async_playwright() as p:
        await asyncio.gather(
            *[
                run_profile(p, name, cfg, sem, results)
                for name, cfg in profiles.items()
            ]
        )

    # ========= SUMMARY =========
    print("\n===== NEMESIS SUMMARY =====")
    for name, res in results.items():
        wallet_ok = "[OK]" if res["wallet"] else "[FAIL]"
        conn = "[OK]" if res["connected"] else "[FAIL]"
        s1 = "[OK]" if res["swap_eth_dai"] else "[FAIL]"
        s2 = "[OK]" if res["swap_dai_token"] else "[FAIL]"
        pair = res.get("pair_token", "—")
        ls = "[OK]" if res["long_short"] else "[FAIL]"
        liq = "[OK]" if res["liquidity"] else "[FAIL]"
        err = f" | Error: {res['error']}" if res["error"] else ""
        plan = res.get("plan", {})
        plan_str = (
            f"свап={plan.get('swap_amount', '?')} | "
            f"лс={plan.get('ls_amount', '?')} | "
            f"ликв={plan.get('liq_amount', '?')}"
        ) if plan else ""
        print(
            f"{name:<8} | wallet: {wallet_ok} | conn: {conn} | "
            f"ETH→DAI: {s1} | DAI→{pair}: {s2} | "
            f"LS: {ls} | liq: {liq} | {plan_str}{err}"
        )
    print("===========================\n")


if __name__ == "__main__":
    asyncio.run(main())
