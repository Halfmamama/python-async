"""Nemesis trading automation package.

После рефакторинга:
  nemesis_helpers.py      — константы, anti-detect, универсальный кликер, хелперы
  nemesis_selectors.py    — стабильные селекторы (Field Group архитектура)
  nemesis_swap.py         — операции свапа (ETH→DAI, DAI→token)
  nemesis_ls.py           — операции Long/Short
  nemesis_liquidity.py    — операции Liquidity и подключение кошелька
  nemesis_orchestrator.py — точка входа, сценарии, мультиаккинг
  nemesis_trading.py      — обратная совместимость (враппер)
"""

# NEW: Убран импорт main из немесис_orчестратор для избежания циклического импорта.
# Запускайте скрипт напрямую: python nemesis_orchestrator.py

__all__ = []