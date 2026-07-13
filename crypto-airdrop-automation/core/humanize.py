import asyncio
import logging
import random

async def human_type(page, text: str, field=None):
    """Ввод текста посимвольно с человеческими задержками."""
    await asyncio.sleep(random.uniform(0.1, 0.3))
    await page.keyboard.press("Control+a")
    await asyncio.sleep(random.uniform(0.05, 0.15))
    await page.keyboard.press("Backspace")
    await asyncio.sleep(random.uniform(0.2, 0.5))

    for char in text:
        await asyncio.sleep(random.uniform(0.05, 0.20))
        await page.keyboard.type(char, delay=0)
        if random.random() < 0.05:
            await asyncio.sleep(random.uniform(0.3, 0.8))


async def human_pause(min_s=0.8, max_s=2.5):
    """Пауза «на раздумье» — перед подтверждениями, табами и т.д."""
    await asyncio.sleep(random.uniform(min_s, max_s))


async def random_mouse_wiggle(page):
    """Случайное микро-движение мыши — эмуляция живого курсора."""
    try:
        viewport = page.viewport_size
        if viewport:
            x = random.randint(100, viewport["width"] - 100)
            y = random.randint(100, viewport["height"] - 100)
            await page.mouse.move(x, y, steps=random.randint(3, 8))
    except Exception:
        pass


async def human_click(locator, name="", label=""):
    """Клик с человеческой задержкой — наведение, пауза, клик."""
    try:
        await locator.scroll_into_view_if_needed()
        await asyncio.sleep(random.uniform(0.2, 0.6))
        await locator.hover()
        await asyncio.sleep(random.uniform(0.1, 0.4))
        await locator.click()
        if label:
            logging.info(f"[{name}]  {label}")
    except Exception as e:
        if label:
            logging.warning(f"[{name}] [WARN] Ошибка клика '{label}': {e}")
        raise
