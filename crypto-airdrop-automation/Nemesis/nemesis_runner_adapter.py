"""
Nemesis Runner Adapter — мост между runner.py и nemesis_orchestrator.py

Этот файл НЕ изменяет оригинальную логику!
Он только предоставляет интерфейс для runner.py и устанавливает параметры.

Оригинальный файл: nemesis_orchestrator.py (НЕ ИЗМЕНЯЕТСЯ)
"""

import asyncio
import logging
from playwright.async_api import async_playwright

# Импортируем оригинальный orchestrator
from Nemesis.nemesis_orchestrator import (
    run_profile as original_run_profile,
    POLICY,
)
from Nemesis import nemesis_helpers
import config


async def run_nemesis_with_runner(
    playwright,
    accounts: list,
    mode: str = "all",
    max_concurrent: int = 5,
    **kwargs
):
    """
    Адаптер для запуска Nemesis из runner.py
    
    Args:
        playwright: Playwright instance
        accounts: List of account names ["acc_1", "acc_3", ...]
        mode: "all", "swap", "ls", "liq"
        max_concurrent: Max parallel browsers
        **kwargs: Дополнительные параметры (игнорируются)
    
    Returns:
        dict: Results dict with stats per account
    """
    # Устанавливаем режим через helpers (как в оригинале)
    # Это НЕ ломает standalone запуск, т.к. устанавливается перед каждым запуском
    nemesis_helpers.SCENARIO = mode
    nemesis_helpers.TARGET_ACCOUNTS = accounts
    nemesis_helpers.RUN_MODE = "ONLY"
    
    logging.info(f"[START] Nemesis adapter: mode={mode}, accounts={len(accounts)}, max_concurrent={max_concurrent}")
    
    # Вызываем оригинальную логику
    results = {}
    sem = asyncio.Semaphore(max_concurrent)
    
    await asyncio.gather(
        *[
            original_run_profile(
                playwright, 
                name, 
                config.PROFILES[name], 
                sem, 
                results
            )
            for name in accounts
        ]
    )
    
    logging.info(f"[OK] Nemesis adapter completed: {len(results)} accounts processed")
    
    return results
