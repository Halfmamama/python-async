"""
Nemesis Selectors — стабильные селекторы для nemesis.trade

Архитектура: "Метка → Field Group → Элемент"

Каждая форма (Swap/Short/Long) состоит из 2 field groups:
  - Swap:  "From" + "To"
  - Short: "Sell" + "Use"
  - Long:  "Buy"  + "Use"

Каждый field group содержит:
  - BUTTON с текстом токена (ETH, DAI, UNI...)  — селектор токена
  - SPAN с меткой ("From", "To", "Sell", "Use", "Buy")  — ЯКОРЬ
  - INPUT placeholder="0.00"  — поле ввода суммы
  - SPAN "Bal: X.XX"  — баланс

Принцип: находим field group по метке, внутри него — нужный элемент.
Никаких regex на div-текст, никаких .nth(N), никаких токен-зависимых локаторов.
"""

import re
import logging
from playwright.async_api import Page, Locator, TimeoutError


# ===================== LABEL MAP =====================
# Какая метка у какого поля в каждой форме

FORM_LABELS = {
    "swap":  {"primary": "From", "secondary": "To"},
    "short": {"primary": "Sell", "secondary": "Use"},
    "long":  {"primary": "Buy",  "secondary": "Use"},
}


# ===================== FIELD GROUP LOCATORS =====================

def get_field_group(page: Page, label: str) -> Locator:
    """
    Находит контейнер field group по его метке.

    Метки: "From", "To", "Sell", "Buy", "Use"

    Стратегия:
    1. Ищем div, который содержит SPAN с точным текстом метки
    2. И фильтруем чтобы div также содержал input (исключаем ложные совпадения)
    3. Берём .last — самый глубокий (наиболее специфичный) контейнер

    Returns: Locator field group контейнера
    """
    return (
        page.locator("div")
        .filter(has=page.get_by_text(label, exact=True))
        .filter(has=page.locator("input"))
        .last
    )


def get_field_input(page: Page, label: str) -> Locator:
    """Находит INPUT внутри field group по метке."""
    return get_field_group(page, label).locator("input").first


def get_field_balance_span(page: Page, label: str) -> Locator:
    """Находит SPAN с балансом ("Bal: X.XX") внутри field group."""
    return (
        get_field_group(page, label)
        .locator("span")
        .filter(has_text=re.compile(r"Bal:\s*[\d.]+"))
    )


def get_field_token_button(page: Page, label: str) -> Locator:
    """
    Находит кнопку селектора токена внутри field group.

    Это ПЕРВАЯ кнопка в field group — та, что показывает
    текущий токен (ETH, DAI, UNI и т.д.)
    """
    return get_field_group(page, label).locator("button").first


def get_field_max_button(page: Page, label: str) -> Locator:
    """Находит кнопку 'Max' внутри field group."""
    return get_field_group(page, label).get_by_text("Max", exact=True)


# ===================== FORM-SPECIFIC HELPERS =====================

def get_swap_from_input(page: Page) -> Locator:
    return get_field_input(page, "From")

def get_swap_to_input(page: Page) -> Locator:
    return get_field_input(page, "To")

def get_short_sell_input(page: Page) -> Locator:
    return get_field_input(page, "Sell")

def get_short_use_input(page: Page) -> Locator:
    return get_field_input(page, "Use")

def get_long_buy_input(page: Page) -> Locator:
    return get_field_input(page, "Buy")

def get_long_use_input(page: Page) -> Locator:
    return get_field_input(page, "Use")


# ===================== BALANCE READERS =====================

async def read_balance(page: Page, label: str) -> float | None:
    """
    Читает баланс из field group по метке.

    Returns: float (баланс) или None если не найден
    """
    try:
        span = get_field_balance_span(page, label)
        text = await span.text_content(timeout=5_000)
        if text:
            match = re.search(r"Bal:\s*([\d.]+)", text)
            if match:
                return float(match.group(1))
    except TimeoutError:
        logging.warning(f"⚠️ Баланс '{label}' не найден (таймаут)")
    except Exception as e:
        logging.warning(f"⚠️ Ошибка чтения баланса '{label}': {e}")
    return None


async def read_from_balance(page: Page) -> float | None:
    """Читает баланс From (Swap)."""
    return await read_balance(page, "From")

async def read_to_balance(page: Page) -> float | None:
    """Читает баланс To (Swap)."""
    return await read_balance(page, "To")

async def read_sell_balance(page: Page) -> float | None:
    """Читает баланс Sell (Short)."""
    return await read_balance(page, "Sell")

async def read_use_balance(page: Page) -> float | None:
    """Читает баланс Use (Short/Long)."""
    return await read_balance(page, "Use")

async def read_buy_balance(page: Page) -> float | None:
    """Читает баланс Buy (Long)."""
    return await read_balance(page, "Buy")


# ===================== TOAST / NOTIFICATION =====================

def get_toast_container(page: Page) -> Locator:
    """
    Находит контейнер уведомлений (toast).

    Nemesis использует Sonner для тостов. После транзакции
    появляется toast с текстом "Swapped", "Opened" и т.д.
    """
    # Вариант 1: Sonner toast (data-sonner-toast)
    sonner = page.locator("[data-sonner-toast]")
    if sonner.count() > 0:
        return sonner.first

    # Вариант 2: любой элемент с role="status" или role="alert"
    # (исключаем __next-route-announcer__ — это Next.js route announcer)
    alert = page.locator('[role="alert"]').filter(
        has_not=page.locator("#__next-route-announcer__")
    )
    if alert.count() > 0:
        return alert.first

    # Вариант 3: поиск по тексту (фоллбэк)
    # Используем page.locator для видимого элемента с нужным текстом
    return page.get_by_text(re.compile(r"Swapped|Opened|Approved", re.IGNORECASE))


async def wait_for_toast(page: Page, text_pattern: str, timeout: int = 25_000) -> bool:
    """
    Ждёт появления toast с текстом, соответствующим pattern.

    Args:
        text_pattern: regex pattern (напр. "Swapped", "2x Short Opened")
        timeout: таймаут в мс

    Returns: True если toast появился, False если таймаут
    """
    try:
        # Ищем видимый элемент с текстом — более надёжно чем .nth(N)
        toast = page.get_by_text(re.compile(text_pattern, re.IGNORECASE)).first
        await toast.wait_for(state="visible", timeout=timeout)
        return True
    except TimeoutError:
        return False


# ===================== TAB NAVIGATION =====================

def get_swap_tab(page: Page) -> Locator:
    """Кнопка-таб Swap (навигация, не действие)."""
    return page.get_by_role("button", name="Swap").first

def get_short_tab(page: Page) -> Locator:
    """Кнопка-таб Short."""
    return page.get_by_role("button", name="Short").first

def get_long_tab(page: Page) -> Locator:
    """Кнопка-таб Long."""
    return page.get_by_role("button", name="Long").first


# ===================== ACTION BUTTONS =====================

# get_action_button removed in favor of click_nemesis_action_button



# ===================== TOKEN DIALOG =====================

def get_token_dialog(page: Page) -> Locator:
    """Диалог выбора токена (Select a Token)."""
    return page.get_by_role("dialog", name="Select a Token")


def get_token_in_dialog(page: Page, token_symbol: str) -> Locator:
    """
    Находит токен в диалоге выбора.

    Формат: "{SYMBOL}{Full Name}" → "USDCUSD Coin"
    Используем regex с началом строки для точного匹配.
    """
    return page.locator("div").filter(
        has_text=re.compile(rf"^{re.escape(token_symbol)}\w")
    ).nth(1)


# ===================== LIQUIDITY =====================

def get_liquidity_link(page: Page) -> Locator:
    """Ссылка на страницу Liquidity."""
    return page.get_by_role("link", name="Liquidity")

def get_create_position_button(page: Page) -> Locator:
    """Кнопка/ссылка 'New' на странице Liquidity для создания новой позиции."""
    return page.get_by_role("link", name="New")

def get_add_liquidity_button(page: Page) -> Locator:
    """Кнопка 'Add Liquidity' (навигация в форме, НЕ вызывает MetaMask)."""
    return page.get_by_role("button", name="Add Liquidity")

def get_choose_token_button(page: Page, index: int = 0) -> Locator:
    """Кнопка 'Choose a token' в форме Liquidity. index=0 первый, index=1 второй."""
    return page.get_by_role("button", name="Choose a token").nth(index)


# ===================== WALLET CONNECTION =====================

def get_connect_wallet_button(page: Page) -> Locator:
    """Кнопка подключения кошелька."""
    return page.get_by_role(
        "button",
        name=re.compile(r"Connect.*Wallet|Connect", re.IGNORECASE),
    ).first

def get_metamask_option(page: Page) -> Locator:
    """Кнопка выбора MetaMask в диалоге подключения."""
    return page.get_by_role(
        "button",
        name=re.compile(r"metamask|MetaMask", re.IGNORECASE),
    )


# ===================== LEVERAGE SLIDER =====================

def get_leverage_slider_track(page: Page) -> Locator:
    """Трек шкалы плеча (1X - 5X)."""
    # Слайдер — элемент с role="slider" в форме Long/Short
    return page.get_by_role("slider").first

def get_leverage_button(page: Page, leverage: int) -> Locator:
    """Кнопка с текстом 'NX' (1X, 2X, 3X, 4X, 5X)."""
    return page.get_by_text(f"{leverage}X", exact=True)


# ===================== UTILITY: FORM CONTEXT =====================

class FormContext:
    """
    Контекст текущей формы — упрощает работу с полями.

    Использование:
        ctx = FormContext(page, "swap")
        from_input = ctx.primary_input   # From
        to_input = ctx.secondary_input   # To
        from_balance = await ctx.read_primary_balance()
    """

    def __init__(self, page: Page, form: str):
        self.page = page
        self.form = form
        labels = FORM_LABELS.get(form)
        if not labels:
            raise ValueError(f"Unknown form: {form}. Use: {list(FORM_LABELS.keys())}")
        self.primary_label = labels["primary"]
        self.secondary_label = labels["secondary"]

    @property
    def primary_input(self) -> Locator:
        return get_field_input(self.page, self.primary_label)

    @property
    def secondary_input(self) -> Locator:
        return get_field_input(self.page, self.secondary_label)

    @property
    def primary_token_button(self) -> Locator:
        return get_field_token_button(self.page, self.primary_label)

    @property
    def secondary_token_button(self) -> Locator:
        return get_field_token_button(self.page, self.secondary_label)

    async def read_primary_balance(self) -> float | None:
        return await read_balance(self.page, self.primary_label)

    async def read_secondary_balance(self) -> float | None:
        return await read_balance(self.page, self.secondary_label)
