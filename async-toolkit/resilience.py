import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


async def dump_failure(page, name: str, action: str, output_dir: str = "logs/failures") -> None:
    """
    Creates a failure dump: a full-page screenshot and raw HTML content.
    
    :param page: The Playwright Page instance.
    :param name: Identifier of the process or profile.
    :param action: Action name where the failure occurred.
    :param output_dir: Directory to save the dump files.
    """
    if page is None:
        logger.warning(f"[{name}] Cannot dump failure: page is None")
        return
        
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_path = Path(output_dir) / f"{name}_{action}_{ts}"
    base_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        await page.screenshot(path=f"{base_path}.png", full_page=True)
        html_content = await page.content()
        Path(f"{base_path}.html").write_text(html_content, encoding="utf-8")
        logger.info(f"[{name}] Failure dump saved successfully: {base_path}.*")
    except Exception as e:
        logger.warning(f"[{name}] Failed to save failure dump: {e}")


async def click_if_visible(locator, name: str, label: str, timeout: int = 3000) -> bool:
    """
    Safely clicks an element if it is visible within the given timeout.
    Prevents crashing from unattached or hidden elements.
    
    :param locator: Playwright Locator instance.
    :param name: Identifier of the process or profile.
    :param label: Descriptive label of the element for logs.
    :param timeout: Time to wait in milliseconds.
    :return: True if clicked, False otherwise.
    """
    try:
        if await locator.is_visible(timeout=timeout):
            await locator.click()
            logger.info(f"[{name}] Clicked: {label}")
            return True
    except Exception as e:
        logger.debug(f"[{name}] Click omitted for '{label}': {e}")
    return False


async def start_tracing(context, enable: bool = False) -> None:
    """
    Starts Playwright tracing on the given browser context.
    
    :param context: Playwright BrowserContext instance.
    :param enable: Flag to enable tracing.
    """
    if enable:
        try:
            await context.tracing.start(
                screenshots=True,
                snapshots=True,
                sources=True
            )
            logger.info("Playwright tracing started.")
        except Exception as e:
            logger.warning(f"Failed to start tracing: {e}")


async def stop_tracing(context, filepath: str = "logs/trace.zip", enable: bool = False) -> None:
    """
    Stops Playwright tracing and saves the trace file.
    
    :param context: Playwright BrowserContext instance.
    :param filepath: Path to save the trace ZIP.
    :param enable: Flag to stop/save tracing.
    """
    if enable:
        try:
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            await context.tracing.stop(path=filepath)
            logger.info(f"Playwright tracing saved to: {filepath}")
        except Exception as e:
            logger.warning(f"Failed to save trace zip: {e}")
