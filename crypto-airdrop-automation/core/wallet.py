import asyncio
import logging
import random
import re
from dataclasses import dataclass

from playwright.async_api import TimeoutError
from core.utils import idle

@dataclass(frozen=True)
class WalletPolicy:
    network: str
    allowed_actions: tuple[str, ...]




# =====================================================================
# NETWORK ALLOWLIST — разрешённые сети для транзакций
# =====================================================================
# Ключ = идентификатор сети (используется в ACTIVE_NETWORK),
# Значение = список строк, которые MetaMask показывает для этой сети.
# Расширяй по мере добавления новых проектов/сетей.

NETWORK_ALLOWLIST = {
    "sepolia": [
        "sepolia",
        "sep",
        "11155111",
    ],
    "goerli": [
        "goerli",
        "gor",
        "5",
    ],
    "mumbai": [
        "mumbai",
        "80001",
    ],
    "base_sepolia": [
        "base sepolia",
        "84532",
    ],
    "arb_sepolia": [
        "arbitrum sepolia",
        "421614",
    ],
    "optimism_sepolia": [
        "optimism sepolia",
        "11155420",
    ],
    "dachain_testnet": [
        "dac testnet",
        "dachain",
    ],
    "ethereum_mainnet": [
        "ethereum mainnet",
        "main network",
        "основная сеть",
        "1",
    ],
    "simplechain_testnet": [
        "simplechain testnet",
        "simplechain",
        "1913",
    ],
    # Добавляй новые сети по шаблону:
    # "network_key": ["название в MetaMask", "chain_id"],
}

# =====================================================================
# ACTIVE_NETWORK — текущая сеть для проекта.
# Каждый скрипт ДОЛЖЕН установить эту переменную перед транзакциями.
# Пример: wallet.ACTIVE_NETWORK = "sepolia"
# =====================================================================

ACTIVE_NETWORK = "sepolia"

# =====================================================================
# ALLOWED_METAMASK_ACTIONS — какие действия разрешены в MetaMask.
# По умолчанию = ВСЕ действия разрешены (тестнет без ограничений).
# Проект на mainnet ДОЛЖЕН ограничить этот список!
#
# Доступные действия:
#   "connect"  — Next/Далее → Connect/Подключиться (подключение кошелька)
#   "sign"     — Sign/Подписать (подпись сообщения, не тратит токены)
#   "approve"  — Approve/Одобрить (апрув spending, ОПАСНО на mainnet!)
#   "confirm"  — Confirm/Подтвердить (отправка транзакции, ОПАСНО на mainnet!)
#
# Правило: НЕ указал ALLOWED_METAMASK_ACTIONS → тестнет, всё разрешено.
#          Указал только ["connect", "sign"] → mainnet, только безопасные.
#
# Примеры:
#   Тестнет (по умолчанию, можно не указывать):
#     wallet.ALLOWED_METAMASK_ACTIONS = ["connect", "sign", "approve", "confirm"]
#   Mainnet проект (только подписи):
#     wallet.ALLOWED_METAMASK_ACTIONS = ["connect", "sign"]
# =====================================================================

ALLOWED_METAMASK_ACTIONS = ["connect", "sign", "approve", "confirm"]

# =====================================================================
# GAS LIMIT OVERRIDE — снижение gas limit в MetaMask перед Confirm
# =====================================================================
# Если None (по умолчанию) — не редактируем газ, подтверждаем как есть.
# Если число (например 500_000) — перед Confirm заходим в Advanced gas settings
# и устанавливаем gas limit = этому значению.
# Полезно когда dApp ставит слишком высокий gas limit (0.033 ETH на Sepolia).
#
# Типичные gas limits для Nemesis (Sepolia):
#   Approve:     ~50_000
#   Swap:        ~200_000
#   Open Long/Short: ~350_000-500_000
#   Liquidity:   ~300_000-400_000
# Устанавливайте с запасом, иначе транзакция упадёт с "out of gas".
# =====================================================================

GAS_LIMIT_OVERRIDE = None  # None = don't edit, или число типа 500_000

async def _adjust_gas_in_metamask(mm_page, profile_name, gas_limit):
    """
    Редактирует gas limit в открытом попапе MetaMask перед Confirm.

    Алгоритм:
    1. Кликаем на отображение gas fee (кнопка/ссылка с суммой ETH)
    2. Переключаемся на вкладку Advanced
    3. Устанавливаем gas limit в поле ввода
    4. Нажимаем Save

    Если что-то не получилось — логируем предупреждение, но НЕ ломаем поток
    (подтверждение пройдёт с дефолтным газом).
    """
    try:
        logging.info(
            f"[{profile_name}] ⛽ Редактирование gas limit → {gas_limit:,}"
        )

        # Шаг 1: Кликаем на gas fee display
        # В MetaMask это обычно кнопка/ссылка с текстом вида "0.033 ETH" или "Site suggestion"
        # Ищем по паттернам
        gas_fee_selectors = [
            # EN: кнопка с суммой ETH
            mm_page.locator("button").filter(has_text=re.compile(r"\d+\.\d+ ETH", re.IGNORECASE)),
            # RU: кнопка с суммой ETH
            mm_page.locator("button").filter(has_text=re.compile(r"\d+\.\d+ ETH", re.IGNORECASE)),
            # Ссылка "Edit" / "Изменить" рядом с gas fee
            mm_page.get_by_role("button", name=re.compile(r"Edit|Изменить|gas|fee", re.IGNORECASE)),
            # Кликабельный div с газом (новые версии MetaMask)
            mm_page.locator("[data-testid='edit-gas-fees-btn']"),
            mm_page.locator("[data-testid='gas-fee-item']"),
        ]

        gas_fee_btn = None
        for sel in gas_fee_selectors:
            try:
                if await sel.first.is_visible(timeout=2_000):
                    gas_fee_btn = sel.first
                    logging.debug(f"[{profile_name}] ⛽ Gas fee кнопка найдена")
                    break
            except Exception:
                continue

        if not gas_fee_btn:
            # Фоллбэк: ищем любой кликабельный элемент рядом с текстом "Gas"
            try:
                gas_fee_btn = mm_page.locator(
                    ":text('Gas') >> xpath=ancestor::button | :text('Gas') >> xpath=ancestor::*[@role='button']"
                ).first
                if not await gas_fee_btn.is_visible(timeout=2_000):
                    gas_fee_btn = None
            except Exception:
                gas_fee_btn = None

        if not gas_fee_btn:
            logging.warning(
                f"[{profile_name}] ⛽ Не найдена кнопка gas fee в MetaMask, "
                f"пропускаю редактирование газа"
            )
            return False

        await asyncio.sleep(random.uniform(0.3, 0.8))
        await gas_fee_btn.click()
        await asyncio.sleep(random.uniform(1.0, 2.0))

        # Шаг 2: Переключаемся на Advanced / Расширенный
        # В новых версиях MetaMask: кнопка "Advanced" или таб
        # RU: "Расширенный"
        advanced_selectors = [
            mm_page.get_by_role("tab", name=re.compile(r"Advanced|Расширенный|Дополнительно", re.IGNORECASE)),
            mm_page.get_by_role("button", name=re.compile(r"Advanced|Расширенный|Дополнительно", re.IGNORECASE)),
            mm_page.locator("button").filter(has_text=re.compile(r"Advanced|Расширенный|Дополнительно", re.IGNORECASE)),
        ]

        advanced_btn = None
        for sel in advanced_selectors:
            try:
                if await sel.first.is_visible(timeout=3_000):
                    advanced_btn = sel.first
                    break
            except Exception:
                continue

        if advanced_btn:
            await asyncio.sleep(random.uniform(0.3, 0.8))
            await advanced_btn.click()
            await asyncio.sleep(random.uniform(1.0, 2.0))
            logging.debug(f"[{profile_name}] ⛽ Переключился на Advanced")
        else:
            logging.debug(
                f"[{profile_name}] ⛽ Advanced tab не найден — "
                f"возможно уже в режиме редактирования"
            )

        # Шаг 3: Устанавливаем gas limit
        # Ищем input поле для gas limit.
        #
        # Стратегия (от надёжной к фоллбэку):
        #   1. data-testid (если MetaMask их не вырезал)
        #   2. Поиск по label-тексту (EN + RU)
        #   3. Позиция: первый number input = gas limit
        #
        # RU-переводы в MetaMask:
        #   "Gas Limit" → "Лимит газа"
        #   "Max gas" → "Макс. газ" / "Максимальный газ"
        #   "Max priority fee" → "Макс. приоритетная комиссия"
        gas_limit_input = None

        # Стратегия 1: data-testid
        for testid in ["gas-limit-input", "gas-limit"]:
            try:
                sel = mm_page.locator(f"[data-testid='{testid}']")
                if await sel.is_visible(timeout=1_000):
                    gas_limit_input = sel
                    logging.debug(f"[{profile_name}] ⛽ Gas limit input найден через data-testid")
                    break
            except Exception:
                continue

        # Стратегия 2: Поиск input по соседнему label-тексту (EN + RU)
        if not gas_limit_input:
            try:
                # EN: Gas Limit, Max gas / RU: Лимит газа, Макс. газ, Максимальный газ
                for label_pattern in [
                    r"Gas Limit", r"gas limit", r"Max gas",
                    r"Лимит газа", r"лимит газа", r"Макс\. газ", r"Максимальный газ",
                ]:
                    label = mm_page.locator(
                        f":text-matches('{label_pattern}', 'i')"
                    ).first
                    if await label.is_visible(timeout=1_000):
                        # Ищем input рядом с label (sibling или в родителе)
                        parent = label.locator("xpath=ancestor::div[1]")
                        input_in_parent = parent.locator("input").first
                        if await input_in_parent.is_visible(timeout=1_000):
                            gas_limit_input = input_in_parent
                            logging.debug(
                                f"[{profile_name}] ⛽ Gas limit input найден через label"
                            )
                            break
            except Exception:
                pass

        # Стратегия 3: Позиция — первый number input = gas limit
        # После перехода на Advanced появляются number inputs:
        #   1-й = gas limit, 2-й = max priority fee (per tip)
        # Это самый надёжный способ, т.к. не зависит от языка
        if not gas_limit_input:
            try:
                all_inputs = mm_page.locator("input[type='number']")
                count = await all_inputs.count()
                if count > 0:
                    # Первый input = gas limit, второй = max priority fee
                    gas_limit_input = all_inputs.first
                    logging.debug(
                        f"[{profile_name}] ⛽ Gas limit input найден "
                        f"(первый number input из {count})"
                    )
            except Exception:
                pass

        if not gas_limit_input:
            logging.warning(
                f"[{profile_name}] ⛽ Не найден input для gas limit, "
                f"пропускаю редактирование"
            )
            # Закрываем gas editing modal
            try:
                cancel_btn = mm_page.get_by_role(
                    "button",
                    name=re.compile(r"Cancel|Отмена|Close|Закрыть", re.IGNORECASE),
                )
                if await cancel_btn.is_visible(timeout=2_000):
                    await cancel_btn.click()
                    await asyncio.sleep(0.5)
            except Exception:
                pass
            return False

        # Очищаем и вводим новый gas limit
        await asyncio.sleep(random.uniform(0.3, 0.8))
        await gas_limit_input.click()
        await asyncio.sleep(0.2)
        # Выделяем всё и удаляем
        await mm_page.keyboard.press("Control+a")
        await asyncio.sleep(0.1)
        await mm_page.keyboard.press("Backspace")
        await asyncio.sleep(0.2)
        # Вводим новое значение
        await mm_page.keyboard.type(str(gas_limit), delay=50)
        await asyncio.sleep(random.uniform(0.5, 1.0))

        logging.info(
            f"[{profile_name}] ⛽ Gas limit установлен: {gas_limit:,}"
        )

        # Шаг 4: Сохраняем
        save_selectors = [
            mm_page.get_by_role("button", name=re.compile(r"Save|Сохранить", re.IGNORECASE)),
            mm_page.get_by_role("button", name=re.compile(r"Confirm|Подтвердить", re.IGNORECASE)),
        ]

        saved = False
        for sel in save_selectors:
            try:
                if await sel.first.is_visible(timeout=3_000):
                    await asyncio.sleep(random.uniform(0.3, 0.8))
                    await sel.first.click()
                    saved = True
                    logging.debug(f"[{profile_name}] ⛽ Gas settings сохранены")
                    break
            except Exception:
                continue

        if not saved:
            logging.warning(
                f"[{profile_name}] ⛽ Кнопка Save не найдена в gas editor"
            )
            return False

        await asyncio.sleep(random.uniform(1.0, 2.0))
        return True

    except Exception as e:
        logging.warning(
            f"[{profile_name}] ⛽ Ошибка при редактировании газа: {e}"
        )
        return False


async def unlock_metamask(context, password, profile_name):
    """Разблокирует MetaMask.
    
    MM-вкладку ищем опросом context.pages — wait_for_event теряет событие из-за tracing.start.
    """
    try:
        page = None
        # Цикл опроса до 40 секунд, шаг 1 секунда
        for attempt in range(40):
            # Сначала ищем уже открытую вкладку
            page = await _find_metamask_page(context)
            if page:
                break
            
            # Фоллбэк с коротким таймаутом
            try:
                candidate = await context.wait_for_event("page", timeout=1_000)
                if candidate:
                    await candidate.wait_for_load_state()
                    title = await candidate.title()
                    url = candidate.url
                    is_metamask = "MetaMask" in title or ("chrome-extension" in url and "metamask" in url.lower())
                    if is_metamask:
                        page = candidate
                        break
            except TimeoutError:
                pass
                
            await asyncio.sleep(1.0)
            
        if not page:
            logging.warning(f"[{profile_name}] 🦊 MetaMask страница не найдена за 40с")
            return None

        await page.wait_for_load_state()

        title = await page.title()
        url = page.url
        is_metamask = "MetaMask" in title or ("chrome-extension" in url and "metamask" in url.lower())
        if not is_metamask:
            return None

        password_input = page.locator("#password")
        try:
            await password_input.wait_for(state="visible", timeout=3_000)
            is_unlocked = False
        except TimeoutError:
            is_unlocked = True

        if is_unlocked:
            logging.info(f"[{profile_name}] MetaMask уже разблокирован (поле #password не появилось)")
            return page

        await password_input.fill(password)
        await page.locator("button[type=submit]").click()
        await idle(4, 6)
        print(f"[{profile_name}] MetaMask разблокирован")
        return page
    except Exception as e:
        logging.error(f"[{profile_name}] 🦊 Ошибка при разблокировке MetaMask: {e}")
        return None




async def close_network_warning(page, profile_name):
    """
    Закрывает уведомление о смене сети в MetaMask.
    Ставит уверенный клик и ждёт полного скрытия,
    чтобы не закрывать вкладку «на авось».
    """
    try:
        # Ловим конкретно кнопку вида <div class="page-container__header-close"></div>
        close_btn = page.locator("div.page-container__header-close")

        # Если такого элемента нет — считаем, что предупреждения нет
        if not await close_btn.count():
            print(f"[{profile_name}] ℹ️ network warning не найден")
            return False

        try:
            # Ждём, пока кнопка реально станет видимой
            await close_btn.first.wait_for(state="visible", timeout=10_000)
        except TimeoutError:
            print(f"[{profile_name}] ⚠️ network warning не успел появиться / не виден")
            return False

        # Важно: НЕ используем evaluate (LavaMoat его режет), только стандартный click()
        await close_btn.first.click(timeout=10_000)

        try:
            # Ждём, пока кнопка исчезнет/станет скрытой — сигнал, что баннер закрылся
            await close_btn.first.wait_for(state="hidden", timeout=10_000)
        except TimeoutError:
            print(f"[{profile_name}] ⚠️ network warning не исчез после клика")
            return False

        print(f"[{profile_name}] ✅ network warning закрыт")
        return True

    except Exception as e:
        print(f"[{profile_name}] ⚠️ ошибка при закрытии network warning: {e}")
        return False


async def confirm_metamask_action(
    context,
    page,
    profile_name,
    success_text,
    timeout=30_000
):
    print(f"[{profile_name}] ⏳ ожидаю окно MetaMask")

    try:
        mm_page = await context.wait_for_event("page", timeout=timeout)
        await mm_page.wait_for_load_state()
    except TimeoutError:
        print(f"[{profile_name}] ⚠️ MetaMask не открылся")
        return False

    # 1️⃣ Кнопка «Подключиться»
    try:
        connect_btn = mm_page.get_by_role("button", name="Подключиться")
        if await connect_btn.count():
            await connect_btn.click()
            print(f"[{profile_name}] 🦊 MetaMask: Подключиться")
            await idle(1, 2)
    except:
        pass

    # 2️⃣ Кнопка «Подтвердить»
    try:
        confirm_btn = mm_page.get_by_role("button", name="Подтвердить")
        if await confirm_btn.count():
            await confirm_btn.click()
            print(f"[{profile_name}] 🦊 MetaMask: Подтвердить")
            await idle(1, 2)
    except:
        pass

    # 3️⃣ ждём подтверждение на сайте
    try:
        await page.locator(
            "div",
            has_text=success_text
        ).wait_for(timeout=20_000)
        print(f"[{profile_name}] ✅ подтверждено на сайте: {success_text}")
        return True
    except TimeoutError:
        print(f"[{profile_name}] ⚠️ toast '{success_text}' не появился")
        return False


# =====================================================================
# NEW: Универсальные функции для MetaMask и DApp подтверждений
# =====================================================================


# ===== Поиск открытого окна MetaMask =====

async def _find_metamask_page(context):
    """Ищет уже открытое окно MetaMask среди страниц контекста.
    
    Проверяет по title ИЛИ по URL (chrome-extension://...),
    т.к. popup может ещё не загрузить title.
    """
    for pg in context.pages:
        try:
            title = await pg.title()
            if "MetaMask" in title:
                return pg
            # Фоллбэк: MetaMask popup может ещё не иметь title,
            # но URL всегда содержит chrome-extension
            url = pg.url
            if "chrome-extension" in url and "metamask" in url.lower():
                return pg
        except Exception:
            continue
    return None


# ===== Проверка тестовой сети =====

async def verify_test_network(mm_page, profile_name, active_network=None, policy=None):
    """
    Проверяет, что MetaMask подключен к ожидаемой сети из NETWORK_ALLOWLIST.

    Логика:
    1. Читаем текст попапа MetaMask
    2. Ищем маркеры ACTIVE_NETWORK из NETWORK_ALLOWLIST
    3. Если найден маркер → сеть подтверждена
    4. Если найден маркер ДРУГОЙ сети из allowlist → предупреждение
    5. Если ни один маркер не найден → сеть неопределена (предупреждение)
    6. Если найден "mainnet" → БЛОКИРОВКА

    Returns:
        True  — ожидаемая сеть подтверждена
        False — обнаружена опасная сеть (Mainnet) → транзакция отменена
        None  — сеть не удалось определить (предупреждение, не блокировка)
    """
    try:
        page_text = (await mm_page.text_content("body") or "").lower()

        # Определяем ожидаемую сеть
        expected_network = policy.network if policy else (active_network or ACTIVE_NETWORK)
        expected_markers = NETWORK_ALLOWLIST.get(expected_network, [])

        if not expected_markers:
            logging.warning(
                f"[{profile_name}] ⚠️ ACTIVE_NETWORK='{expected_network}' "
                f"не найден в NETWORK_ALLOWLIST! "
                f"Добавьте сеть в словарь wallet.NETWORK_ALLOWLIST."
            )
            return None

        # Проверяем совпадение с ожидаемой сетью
        for marker in expected_markers:
            if marker.lower() in page_text:
                logging.info(
                    f"[{profile_name}] ✅ Сеть подтверждена: "
                    f"{expected_network} (маркер: '{marker}')"
                )
                return True

        # Проверяем другие сети из allowlist
        for net_key, markers in NETWORK_ALLOWLIST.items():
            if net_key == expected_network:
                continue
            for marker in markers:
                if marker.lower() in page_text:
                    logging.warning(
                        f"[{profile_name}] ⚠️ Обнаружена сеть '{net_key}', "
                        f"а ожидается '{expected_network}'! "
                        f"Транзакция может быть на неправильной сети."
                    )
                    return False

        # Проверяем явные признаки Mainnet (последний рубеж)
        mainnet_indicators = [
            "ethereum mainnet",
            "main network",
            "основная сеть",
            "chain id: 1",
        ]
        for indicator in mainnet_indicators:
            if indicator in page_text:
                logging.error(
                    f"[{profile_name}] 🚨 ОБНАРУЖЕН MAINNET! "
                    f"Транзакция отменена ради безопасности!"
                )
                return False

        # Ни один маркер не найден — сеть неопределена
        logging.warning(
            f"[{profile_name}] ⚠️ Не удалось определить сеть в MetaMask. "
            f"Ожидалась: '{expected_network}'. "
            f"Продолжаем с осторожностью."
        )
        return None

    except Exception as e:
        logging.warning(
            f"[{profile_name}] ⚠️ Ошибка при проверке сети: {e}"
        )
        return None


# ===== Универсальный обработчик MetaMask popups =====

async def classify_metamask_popup(popup) -> str:
    """
    Определяет тип открытого попапа MetaMask:
    "connect" | "signature" | "approve" | "confirm" | "unknown"
    """
    try:
        title = (await popup.title()) or ""
    except Exception:
        title = ""

    title_lower = title.lower()

    # 1. Проверяем заголовок (RU/EN)
    if "connect" in title_lower or "подключение" in title_lower:
        return "connect"
    if "signature request" in title_lower or "запрос подписи" in title_lower:
        return "signature"

    # 2. Проверяем наличие характерных кнопок действия
    # Connect
    try:
        next_btn = popup.get_by_role("button", name=re.compile(r"Next|Далее", re.IGNORECASE))
        connect_btn = popup.get_by_role("button", name=re.compile(r"Connect|Подключиться", re.IGNORECASE))
        if await next_btn.first.is_visible(timeout=500) or await connect_btn.first.is_visible(timeout=500):
            return "connect"
    except Exception:
        pass

    # Signature
    try:
        sign_btn = popup.get_by_role("button", name=re.compile(r"Sign|Подписать", re.IGNORECASE))
        if await sign_btn.first.is_visible(timeout=500):
            return "signature"
    except Exception:
        pass

    # Approve
    try:
        approve_btn = popup.get_by_role("button", name=re.compile(r"Approve|Одобрить", re.IGNORECASE))
        if await approve_btn.first.is_visible(timeout=500):
            return "approve"
    except Exception:
        pass

    # Confirm
    try:
        confirm_btn = popup.get_by_role("button", name=re.compile(r"Confirm|Подтвердить", re.IGNORECASE))
        if await confirm_btn.first.is_visible(timeout=500):
            return "confirm"
    except Exception:
        pass

    # 3. Дополнительные проверки заголовка/содержимого на случай, если кнопки ещё не прорисовались полностью
    if "signature" in title_lower or "подпис" in title_lower:
        return "signature"
    if "approve" in title_lower or "одобрить" in title_lower or "permission" in title_lower or "разрешение" in title_lower:
        return "approve"
    if "confirm" in title_lower or "подтвердить" in title_lower:
        return "confirm"

    return "unknown"


async def _confirm_open_popup(
    popup, profile_name, action_name="confirm", active_network=None, allowed_actions=None, policy=None
) -> bool:
    """
    Внутренний помощник для подтверждения уже открытого окна MetaMask.
    Содержит проверки сети, лимитов газа и клики по кнопкам.
    """
    # Проверяем тестовую сеть
    network_check = await verify_test_network(popup, profile_name, active_network, policy=policy)
    if network_check is False:
        # Небезопасная сеть обнаружена — отклоняем транзакцию
        logging.error(
            f"[{profile_name}] 🚨 Небезопасная сеть! Отклоняю транзакцию..."
        )
        try:
            reject_btn = popup.get_by_role(
                "button",
                name=re.compile(
                    r"Reject|Отклонить|Cancel|Отмена", re.IGNORECASE
                ),
            )
            if await reject_btn.is_visible(timeout=3_000):
                await reject_btn.click()
                logging.warning(
                    f"[{profile_name}] 🚨 Транзакция ОТКЛОНЕНА (небезопасная сеть)!"
                )
        except Exception:
            logging.warning(
                f"[{profile_name}] 🚨 Не удалось отклонить в MetaMask"
            )
        return False

    actual_allowed_actions = policy.allowed_actions if policy else (allowed_actions or ALLOWED_METAMASK_ACTIONS)

    # Вспомогательная функция для отклонения запрещённых действий
    async def _reject_action(action_type, btn_label):
        """Отклоняет действие, не входящее в ALLOWED_METAMASK_ACTIONS."""
        logging.error(
            f"[{profile_name}] 🚨 Действие '{action_type}' ЗАПРЕЩЕНО! "
            f"ALLOWED_METAMASK_ACTIONS={actual_allowed_actions}. "
            f"Отклоняю..."
        )
        try:
            reject_btn = popup.get_by_role(
                "button",
                name=re.compile(
                    r"Reject|Отклонить|Cancel|Отмена", re.IGNORECASE
                ),
            )
            if await reject_btn.is_visible(timeout=3_000):
                await reject_btn.click()
                logging.warning(
                    f"[{profile_name}] 🚨 {btn_label} ОТКЛОНЕНО (не в allowlist)!"
                )
        except Exception:
            logging.warning(
                f"[{profile_name}] 🚨 Не удалось отклонить {btn_label}"
            )
        return False

    # 1. Next → Connect
    if "connect" in actual_allowed_actions:
        next_btn = popup.get_by_role(
            "button", name=re.compile(r"Next|Далее", re.IGNORECASE)
        )
        if await next_btn.is_visible():
            await asyncio.sleep(random.uniform(0.5, 1.5))
            await next_btn.click()
            logging.info(f"[{profile_name}] 🦊 MetaMask: Next")
            await idle(1.0, 2.0)
            connect_btn = popup.get_by_role(
                "button",
                name=re.compile(r"Connect|Подключиться", re.IGNORECASE),
            )
            if await connect_btn.is_visible():
                await asyncio.sleep(random.uniform(0.5, 1.5))
                await connect_btn.click()
                logging.info(
                    f"[{profile_name}] 🦊 MetaMask: Next → Connect"
                )
                return True
    else:
        # Connect не разрешён — проверяем, не является ли попап запросом на подключение
        next_btn = popup.get_by_role(
            "button", name=re.compile(r"Next|Далее", re.IGNORECASE)
        )
        connect_btn_check = popup.get_by_role(
            "button",
            name=re.compile(r"Connect|Подключиться", re.IGNORECASE),
        )
        if await next_btn.is_visible() or await connect_btn_check.is_visible():
            return await _reject_action("connect", "Connect")

    # 2. Connect (direct)
    if "connect" in actual_allowed_actions:
        connect_btn_direct = popup.get_by_role(
            "button",
            name=re.compile(r"Connect|Подключиться", re.IGNORECASE),
        )
        if await connect_btn_direct.is_visible():
            await asyncio.sleep(random.uniform(0.5, 1.5))
            await connect_btn_direct.click()
            logging.info(f"[{profile_name}] 🦊 MetaMask: Connect")
            return True

    # 3. Sign / Подписать
    sign_btn = popup.get_by_role(
        "button", name=re.compile(r"Sign|Подписать", re.IGNORECASE)
    )
    if await sign_btn.is_visible():
        if "sign" not in actual_allowed_actions:
            return await _reject_action("sign", "Sign")
        if not await sign_btn.is_enabled():
            # Скроллим если кнопка disabled
            scroll_btn = popup.locator(
                "div[data-testid='signature-request-scroll-button']"
            )
            if await scroll_btn.is_visible():
                await scroll_btn.click()
                await idle(0.5, 1.0)
        await asyncio.sleep(random.uniform(0.5, 1.5))
        await sign_btn.click()
        logging.info(f"[{profile_name}] 🦊 MetaMask: Sign")
        return True

    # 4. Approve / Одобрить
    approve_btn = popup.get_by_role(
        "button",
        name=re.compile(r"Approve|Одобрить", re.IGNORECASE),
    )
    if await approve_btn.is_visible():
        if "approve" not in actual_allowed_actions:
            return await _reject_action("approve", "Approve")
        # Редактируем gas limit если задан GAS_LIMIT_OVERRIDE
        if GAS_LIMIT_OVERRIDE is not None:
            await _adjust_gas_in_metamask(popup, profile_name, GAS_LIMIT_OVERRIDE)
        await asyncio.sleep(random.uniform(0.5, 1.5))
        await approve_btn.click()
        logging.info(f"[{profile_name}] 🦊 MetaMask: Approve")
        return True

    # 5. Confirm / Подтвердить
    confirm_btn = popup.get_by_role(
        "button",
        name=re.compile(r"Confirm|Подтвердить", re.IGNORECASE),
    )
    if await confirm_btn.is_visible():
        if "confirm" not in actual_allowed_actions:
            return await _reject_action("confirm", "Confirm")
        # Редактируем gas limit если задан GAS_LIMIT_OVERRIDE
        if GAS_LIMIT_OVERRIDE is not None:
            await _adjust_gas_in_metamask(popup, profile_name, GAS_LIMIT_OVERRIDE)
        await asyncio.sleep(random.uniform(0.5, 1.5))
        await confirm_btn.click()
        logging.info(f"[{profile_name}] 🦊 MetaMask: Confirm")
        return True

    logging.warning(
        f"[{profile_name}] 🦊 Окно MetaMask открылось, но нужная кнопка не найдена"
    )
    return False


async def handle_metamask_popup(
    context, profile_name, action_name="confirm", timeout=30_000, active_network=None, allowed_actions=None, policy=None
):
    """
    Универсальный обработчик всплывающих окон MetaMask (RU/EN).

    Поддерживаемые действия:
    - Next → Connect
    - Connect (direct)
    - Sign / Подписать (со скроллом если кнопка disabled)
    - Approve / Одобрить
    - Confirm / Подтвердить

    NEW: Проверяет тестовую сеть перед подтверждением.
    Если обнаружен Mainnet — отклоняет транзакцию.
    """
    try:
        logging.info(
            f"[{profile_name}] 🦊 Ожидание окна MetaMask для: {action_name}"
        )

        popup = None
        for attempt in range(3):
            # 1. Проверяем уже открытые страницы
            popup = await _find_metamask_page(context)
            if popup:
                logging.info(
                    f"[{profile_name}] 🦊 Найдено уже открытое окно MetaMask"
                )
                break

            # 2. Ждём новое окно (с коротким таймаутом)
            wait_timeout = min(timeout, 15_000) if attempt == 0 else 10_000
            try:
                popup = await context.wait_for_event(
                    "page", timeout=wait_timeout
                )
                logging.info(
                    f"[{profile_name}] 🦊 Поймано новое окно MetaMask"
                )
                break
            except TimeoutError:
                # 3. Финальная проверка — popup мог открыться
                # пока мы ждали event
                popup = await _find_metamask_page(context)
                if popup:
                    logging.info(
                        f"[{profile_name}] 🦊 Найдено окно MetaMask "
                        f"после таймаута (попытка {attempt + 1})"
                    )
                    break
                if attempt < 2:
                    logging.info(
                        f"[{profile_name}] 🦊 Popup не найден, "
                        f"попробую ещё раз (попытка {attempt + 1}/3)"
                    )
                    await asyncio.sleep(1.0)
                else:
                    logging.info(
                        f"[{profile_name}] 🦊 Тайм-аут ожидания окна MetaMask "
                        f"для {action_name} после 3 попыток"
                    )
                    return False

        if not popup:
            return False

        await popup.wait_for_load_state("networkidle")
        await idle(1.0, 2.0)
        # Имитируем «чтение» попапа перед действием
        await asyncio.sleep(random.uniform(0.8, 2.0))

        return await _confirm_open_popup(
            popup=popup,
            profile_name=profile_name,
            action_name=action_name,
            active_network=active_network,
            allowed_actions=allowed_actions,
            policy=policy,
        )

    except TimeoutError:
        logging.info(
            f"[{profile_name}] 🦊 Тайм-аут ожидания окна MetaMask "
            f"({action_name})"
        )
    except Exception as e:
        logging.error(
            f"[{profile_name}] 🦊 Ошибка в MetaMask popup: {e}"
        )
    return False


async def handle_metamask_popup_sequence(
    context, profile_name, *, policy=None, active_network=None,
    allowed_actions=None, max_popups=4, first_timeout=25_000,
    settle_timeout=8_000,
) -> list[str]:
    """
    Универсальный цикл подхвата попапов MetaMask без навязывания порядка.
    """
    confirmed_types = []
    logging.info(f"[{profile_name}] 🦊 Запуск универсального цикла подхвата попапов MetaMask (max={max_popups})")

    for i in range(max_popups):
        timeout_ms = first_timeout if i == 0 else settle_timeout
        logging.debug(f"[{profile_name}] 🦊 Ожидание попапа #{i+1} (timeout={timeout_ms}ms)...")

        popup = None
        # Ищем уже открытое окно
        popup = await _find_metamask_page(context)
        if not popup:
            # Ожидаем новое окно
            try:
                popup = await context.wait_for_event("page", timeout=timeout_ms)
            except TimeoutError:
                # На случай race condition проверяем еще раз
                popup = await _find_metamask_page(context)

        if not popup:
            if i == 0:
                logging.warning(f"[{profile_name}] 🦊 MetaMask попап не появился в течение {first_timeout}ms.")
            else:
                logging.info(f"[{profile_name}] 🦊 Больше попапов не обнаружено (таймаут {settle_timeout}ms исчерпан). Завершаем цикл.")
            break

        try:
            await popup.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        await idle(1.0, 2.0)
        await asyncio.sleep(random.uniform(0.8, 2.0))

        # Определяем тип попапа
        classified_type = await classify_metamask_popup(popup)
        logging.info(f"[{profile_name}] 🦊 Определён попап: {classified_type}")

        # Подтверждаем попап
        success = await _confirm_open_popup(
            popup=popup,
            profile_name=profile_name,
            action_name=classified_type,
            active_network=active_network,
            allowed_actions=allowed_actions,
            policy=policy,
        )

        if success:
            confirmed_types.append(classified_type)

            # Ожидаем закрытия текущего попапа
            try:
                await popup.wait_for_event("close", timeout=12000)
            except Exception:
                # Проверяем опрашиванием на случай, если событие закрытия пропущено
                for _ in range(10):
                    still_open = await _find_metamask_page(context)
                    if not still_open:
                        break
                    await asyncio.sleep(0.5)

            # Небольшая human-пауза перед следующей итерацией
            await idle(1.5, 3.0)
        else:
            logging.warning(f"[{profile_name}] ⚠️ Не удалось подтвердить попап типа {classified_type}")
            # В случае ошибки подтверждения выходим из цикла
            break

    return confirmed_types


async def handle_multiple_metamask_popups(
    context, profile_name, action_name="confirm", max_popups=4, policy=None
):
    """Обрабатывает несколько последовательных попапов MetaMask."""
    handled = 0
    for i in range(max_popups):
        timeout = 30_000 if i == 0 else 15_000
        result = await handle_metamask_popup(
            context, profile_name, f"{action_name}_{i + 1}", timeout=timeout, policy=policy
        )
        if result:
            handled += 1
            await asyncio.sleep(random.uniform(2.0, 4.0))
        else:
            break
    logging.info(
        f"[{profile_name}] 🦊 Обработано {handled} попап(ов) MetaMask "
        f"для {action_name}"
    )
    return handled


async def confirm_dapp_transaction(
    page,
    context,
    profile_name,
    action_name="transaction",
    max_iterations=6,
    click_fn=None,
    terminal_fn=None,
    post_confirm_wait=(5.0, 8.0),
    second_chance_delay=12.0,
    auto_mm_check_delay=0.0,  # NEW: задержка для проверки авто-попапа MetaMask
    policy=None,
):
    """
    Высокоуровневая функция: ищет и нажимает кнопки действий на DApp
    и подтверждает каждую в MetaMask.

    Параметр click_fn — асинхронная функция с сигнатурой:
        async def click_fn(page, profile_name)
            -> (btn_name: str | None, clicked: bool, triggers_metamask: bool)

    triggers_metamask:
        True  — кнопка вызывает popup MetaMask (транзакция)
        False — кнопка только меняет UI DApp (навигация, типа Review)

    NEW: Параметр terminal_fn — функция с сигнатурой:
        def terminal_fn(btn_name: str) -> bool

    Возвращает True если кнопка — терминальное действие (свап выполнен,
    позиция открыта). После терминального действия цикл прерывается,
    чтобы не кликать ту же кнопку повторно.

    NEW: Параметр auto_mm_check_delay — если > 0, то после каждого подтверждения
    в MetaMask ждёт указанное количество секунд и проверяет не появился ли новый
    попап MetaMask (для Liquidity где после Approve может автоматически открыться
    второе окно). Если появился — сразу подтверждает его, не ища кнопку на dApp.

    Если click_fn не передан — логирование и возврат 0.
    Каждый проект определяет свои кнопки и передаёт свою функцию.

    Цикл:
    1. Вызываем click_fn — ищем и кликаем кнопку на DApp
    2. Если triggers_metamask=True → обрабатываем MetaMask popup
    3. Если triggers_metamask=False → пропускаем, сразу следующая итерация
    4. Если terminal_fn(btn_name)=True и MetaMask подтвердил → СТОП
    5. NEW: Если auto_mm_check_delay > 0 → проверяем авто-попап MetaMask
    6. Повторяем, пока click_fn находит кнопки

    Returns: количество успешно обработанных шагов (MetaMask подтверждений)
    """
    if click_fn is None:
        logging.warning(
            f"[{profile_name}] ⚠️ click_fn не передан — "
            f"нечем искать кнопки для {action_name}"
        )
        return 0

    total_steps = 0

    # NEW: Защита от зацикливания — если одна и та же кнопка
    # появляется несколько раз подряд, скорее всего мы застряли
    last_btn_name = None
    stale_count = 0
    MAX_STALE = 3  # Одна и та же кнопка 3 раза подряд = зависли

    for iteration in range(max_iterations):
        # Ищем кнопку действия на DApp через переданную функцию
        # Поддерживаем и 2- и 3- элементный кортеж
        click_result = await click_fn(page, profile_name)
        if len(click_result) == 3:
            btn_name, clicked, triggers_mm = click_result
        else:
            btn_name, clicked = click_result[:2]
            triggers_mm = True  # По умолчанию считаем что вызывает MetaMask

        if not clicked:
            # NEW: Проверяем, не открылся ли MetaMask popup пока мы искали кнопку
            # Это решает проблему, когда скрипт "продолжал искать кнопку", игнорируя появившийся попап
            unhandled_popup = await _find_metamask_page(context)
            if unhandled_popup:
                logging.info(f"[{profile_name}] 🦊 Обнаружен задержавшийся MetaMask popup! Обрабатываю...")
                delayed_result = await handle_metamask_popup(
                    context, profile_name, f"{action_name}_delayed", policy=policy
                )
                if delayed_result:
                    total_steps += 1
                    await asyncio.sleep(random.uniform(*post_confirm_wait))
                    continue # Возвращаемся в начало цикла
            
            if iteration == 0:
                logging.info(
                    f"[{profile_name}] ℹ️ Нет доступных кнопок действий "
                    f"для {action_name}"
                )
                break
            # NEW: Второй шанс — если уже были обработанные шаги,
            # dApp мог не успеть обновиться после MetaMask подтверждения.
            # Ждём 12с и пробуем ещё раз перед тем как сдаться.
            if total_steps > 0:
                logging.info(
                    f"[{profile_name}] ⏳ Кнопок не найдено после {total_steps} шагов, "
                    f"жду {second_chance_delay}с и пробую ещё раз..."
                )
                await asyncio.sleep(second_chance_delay)
                click_result_2 = await click_fn(page, profile_name)
                if len(click_result_2) == 3:
                    btn_name, clicked, triggers_mm = click_result_2
                else:
                    btn_name, clicked = click_result_2[:2]
                    triggers_mm = True
                if clicked:
                    logging.info(
                        f"[{profile_name}] ✅ Кнопка найдена после ожидания: '{btn_name}'"
                    )
                    # Не break — продолжаем обработку этой кнопки ниже
                else:
                    logging.info(
                        f"[{profile_name}] ✅ Все кнопки действий обработаны "
                        f"для {action_name} ({total_steps} шагов)"
                    )
                    break
            else:
                logging.info(
                    f"[{profile_name}] ✅ Все кнопки действий обработаны "
                    f"для {action_name} ({total_steps} шагов)"
                )
                break

        # NEW: Проверяем не застряли ли мы на одной кнопке
        if btn_name and btn_name == last_btn_name:
            stale_count += 1
            if stale_count >= MAX_STALE:
                logging.warning(
                    f"[{profile_name}] ⚠️ Кнопка '{btn_name}' появляется "
                    f"{stale_count} раз подряд — вероятно зависли, "
                    f"прерываю цикл"
                )
                break
        else:
            stale_count = 0
        last_btn_name = btn_name

        logging.info(
            f"[{profile_name}] 🔄 Шаг {iteration + 1}: нажал "
            f"'{btn_name}' для {action_name}"
            f" {'[→MetaMask]' if triggers_mm else '[UI-only]'}"
        )

        if not triggers_mm:
            # Кнопка НЕ вызывает MetaMask — это навигация (Review, Add Liquidity)
            # Ждём обновления UI и переходим к следующей итерации
            await asyncio.sleep(random.uniform(1.5, 3.0))
            continue

        # Кнопка вызывает MetaMask — короткая пауза и обработка popup
        await asyncio.sleep(random.uniform(0.5, 1.0))

        # NEW: Retry MetaMask — иногда попап открывается но кнопка ещё не
        # отрисовалась (loading state). Даём второй шанс через 3с.
        mm_result = False
        for mm_attempt in range(2):
            mm_result = await handle_metamask_popup(
                context, profile_name,
                f"{action_name}_step_{iteration + 1}",
                policy=policy,
            )
            if mm_result:
                break
            if mm_attempt == 0:
                logging.info(
                    f"[{profile_name}] 🔄 MetaMask не ответил с первой попытки, "
                    f"повтор через 3с..."
                )
                await asyncio.sleep(3.0)

        if mm_result:
            total_steps += 1
            logging.info(
                f"[{profile_name}] ✅ Подтверждено в MetaMask: {btn_name}"
            )
            
            # СНАЧАЛА проверяем авто-попапы (для Liquidity, где попапы могут идти подряд)
            if auto_mm_check_delay > 0:
                logging.info(
                    f"[{profile_name}] ⏳ Жду {auto_mm_check_delay}с для проверки "
                    f"авто-попапа MetaMask..."
                )
                await asyncio.sleep(auto_mm_check_delay)
                
                auto_popup = await _find_metamask_page(context)
                if auto_popup:
                    logging.info(
                        f"[{profile_name}] 🦊 Авто-попап MetaMask обнаружен! "
                        f"Подтверждаю без поиска кнопки..."
                    )
                    auto_result = await handle_metamask_popup(
                        context, profile_name,
                        f"{action_name}_auto_step",
                        policy=policy,
                    )
                    if auto_result:
                        total_steps += 1
                        logging.info(
                            f"[{profile_name}] ✅ Авто-подтверждено в MetaMask"
                        )
                    else:
                        logging.warning(
                            f"[{profile_name}] ⚠️ Авто-попап MetaMask не подтвердился"
                        )
                else:
                    logging.info(
                        f"[{profile_name}] ℹ️ Авто-попап MetaMask не появился."
                    )

            # ЗАТЕМ проверяем терминальное действие
            if terminal_fn and terminal_fn(btn_name):
                logging.info(
                    f"[{profile_name}] 🏁 Терминальное действие '{btn_name}' "
                    f"подтверждено — выходим из цикла"
                )
                break
        else:
            logging.warning(
                f"[{profile_name}] ⚠️ MetaMask не подтвердил: {btn_name} "
                f"(2 попытки исчерпаны)"
            )
            # NEW: Закрываем зависший попап MetaMask, чтобы не блокировал dApp
            try:
                stuck_popup = await _find_metamask_page(context)
                if stuck_popup:
                    reject_btn = stuck_popup.get_by_role(
                        "button",
                        name=re.compile(r"Reject|Отклонить|Cancel|Отмена", re.IGNORECASE),
                    )
                    if await reject_btn.is_visible(timeout=3_000):
                        await reject_btn.click()
                        logging.info(f"[{profile_name}] 🦊 Зависший попап MetaMask закрыт")
                    else:
                        await stuck_popup.close()
                        logging.info(f"[{profile_name}] 🦊 Зависший попап MetaMask закрыт (close)")
            except Exception:
                pass
            # После неудачи с MetaMask — выходим из цикла.
            # Дальнейшие итерации только запутают dApp.
            logging.warning(
                f"[{profile_name}] ⚠️ Прерываю цепочку из-за ошибки MetaMask "
                f"({total_steps} шагов выполнено)"
            )
            break

        # Пауза между итерациями
        # MODIFIED: после MetaMask-подтверждения нужно ждать подтверждения
        # транзакции в блокчейне (12+ сек на Sepolia) — иначе кнопка может
        # быть disabled и кликер её пропустит
        # NEW: задержка настраивается через post_confirm_wait (по умолчанию 5-8с)
        if mm_result:
            await asyncio.sleep(random.uniform(*post_confirm_wait))
        else:
            await asyncio.sleep(random.uniform(2.0, 4.0))

    return total_steps

