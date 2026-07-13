import logging
from pathlib import Path
from datetime import datetime

async def dump_failure(page, name, action):
    """
    Создаёт дамп падения: полноэкранный скриншот и HTML-код страницы.
    """
    if page is None:
        return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = Path("logs/failures") / f"{name}_{action}_{ts}"
    base.parent.mkdir(parents=True, exist_ok=True)
    try:
        await page.screenshot(path=f"{base}.png", full_page=True)
        Path(f"{base}.html").write_text(await page.content(), encoding="utf-8")
        logging.info(f"[{name}] дамп падения сохранён: {base}.*")
    except Exception as e:
        logging.warning(f"[{name}] не смог сохранить дамп: {e}")
