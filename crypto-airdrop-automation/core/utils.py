import asyncio
import random
import logging

async def idle(a=2, b=5):
    await asyncio.sleep(random.uniform(a, b))


async def wait_for_reactions_or_timeout(page, timeout=15_000):
    try:
        await page.wait_for_selector(
            'div.chakra-stack p:has-text("")',
            timeout=timeout
        )
        return True
    except Exception:
        return False


async def safe_open(
    page,
    url: str,
    max_reload: int = 5,
    goto_timeout: int = 45_000,
):
    """
    Универсальное открытие SPA / testnet / dashboard страниц.

    [FAIL] НЕ верит HTTP статусам (503, 429, CF)
    [OK] Верит ТОЛЬКО живому DOM
    """

    await page.goto(url, wait_until="domcontentloaded", timeout=goto_timeout)

    for attempt in range(1, max_reload + 1):
        try:
            # 1️⃣ DOM должен существовать
            await page.wait_for_selector("body", timeout=10_000)

            # 2️⃣ Должен быть хотя бы один кликабельный элемент в DOM
            clickable = page.locator(
                "button, a, input, textarea, select"
            )
            await clickable.first.wait_for(state="attached", timeout=10_000)

            # 3️⃣ Cloudflare / Error экраны — не должны быть активны
            # MODIFIED: проверяем специфичные селекторы CF challenge вместо
            # грубого поиска слова "cloudflare" по всему HTML (давало
            # ложные срабатывания на сайтах с CF CDN).
            cf_challenge = page.locator(
                "#challenge-running, #cf-browser-verification, "
                ".challenge-running, .cf-browser-verification"
            )
            if await cf_challenge.count() > 0:
                raise TimeoutError("cloudflare challenge screen detected")

            # проверяем bad-сигналы только в <title> и видимых заголовках
            title_text = (await page.title()).lower()
            h1_text = ""
            h1_loc = page.locator("h1").first
            if await h1_loc.count() > 0:
                h1_text = (await h1_loc.text_content() or "").lower()

            check_text = f"{title_text} {h1_text}"

            bad_signals = [
                "checking your browser",
                "attention required",
                "service unavailable",
                "error 503",
                "temporarily unavailable",
            ]

            if any(x in check_text for x in bad_signals):
                raise TimeoutError("blocking screen detected")

            print(f"[INFO] page ready (attempt {attempt})")
            return

        except TimeoutError:
            if attempt >= max_reload:
                break

            print(f"[WARN] page not ready, reload #{attempt}")
            await page.reload(wait_until="domcontentloaded")
            await idle(2, 4)

    raise Exception("page not usable after reloads")


class ProxyConnectionError(Exception):
    """Raised when connection to or through the proxy tunnel fails."""


async def safe_open_with_retry(page, url, profile_name, retries=3, timeout=30_000):
    for attempt in range(1, retries + 1):
        try:
            resp = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=timeout
            )

            if resp and resp.status >= 500:
                raise RuntimeError(f"HTTP {resp.status}")

            return True

        except Exception as e:
            from core.proxy_health import is_proxy_level_error
            if is_proxy_level_error(e):
                logging.warning(f"[{profile_name}] proxy tunnel error: {e}")
                raise ProxyConnectionError(str(e))

            logging.warning(
                f"[{profile_name}] [WARN] 503 detected, reload #{attempt}"
            )
            if attempt == retries:
                raise RuntimeError("503 not resolved")
            await idle(5 * attempt, 8 * attempt)


async def click_if_visible(locator, name, label, timeout=3000) -> bool:
    try:
        if await locator.is_visible(timeout=timeout):
            await locator.click()
            logging.info(f"[{name}] {label}")
            return True
    except Exception as e:
        logging.debug(f"[{name}] {label} пропущен: {e}")
    return False
