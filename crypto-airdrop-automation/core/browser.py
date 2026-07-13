import os
from pathlib import Path
import config

# Определяем корень проекта (Новая папка)
# browser.py находится в Avtomatization/Multik/automation/core/
# Значит: parent(core) -> parent(automation) -> parent(Multik) -> parent(Avtomatization) -> root
BASE_DIR = Path(__file__).resolve().parent.parent
PROFILES_DIR = os.path.join(str(BASE_DIR), "profiles")


import logging

_launch_lock = None

def get_launch_lock():
    global _launch_lock
    if _launch_lock is None:
        import asyncio
        _launch_lock = asyncio.Lock()
    return _launch_lock


def force_kill_chrome_by_profile(user_data_dir: str):
    """
    Принудительно завершает процессы Chrome, запущенные с указанной user_data_dir.
    """
    import os
    import psutil
    target = os.path.normpath(user_data_dir).lower()
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            name = proc.info.get('name') or ''
            if 'chrome' in name.lower() or 'chromium' in name.lower():
                cmdline = proc.info.get('cmdline') or []
                for arg in cmdline:
                    low = arg.lower()
                    if low.startswith("--user-data-dir="):
                        val = arg.split("=", 1)[1]
                        if os.path.normpath(val).lower() == target:
                            logging.warning(f"💥 [FORCED KILL] Убиваем зависший процесс Chrome {proc.info['pid']} для профиля {user_data_dir}")
                            proc.kill()
                            break
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

async def launch_context(playwright, name, cfg, extra_args=None):
    lock = get_launch_lock()
    async with lock:
        # Стартовый разброс (1-3с)
        import random
        import asyncio
        stagger_delay = random.uniform(1.0, 3.0)
        logging.info(f"[{name}] Стартовый разброс: пауза {stagger_delay:.2f}с перед запуском браузера")
        await asyncio.sleep(stagger_delay)

        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=os.path.join(PROFILES_DIR, name),
            channel="chromium",  # ✅ Chromium (поддерживает --load-extension)
            headless=False,
            proxy=cfg["proxy"],
            timezone_id=cfg["timezone"],
            locale=cfg["locale"],
            extra_http_headers={
                "Accept-Language": cfg["accept_language"]
            },
            no_viewport=True,
            args=[
                f"--window-size={config.AUTO_WINDOW_WIDTH},{config.AUTO_WINDOW_HEIGHT}",
                f"--window-position={config.SECONDARY_MONITOR_X},{config.SECONDARY_MONITOR_Y}",

                "--disable-blink-features=AutomationControlled",
                "--disable-webrtc",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--webrtc-ip-handling-policy=disable_non_proxied_udp",
                # ✅ Загружаем расширения (работает только в Chromium)
                f"--disable-extensions-except={config.EXTENSION_PATH_MM},{config.EXTENSION_PATH_RW},{config.EXTENSION_PATH_PH},{config.EXTENSION_PATH_SUB}",
                f"--load-extension={config.EXTENSION_PATH_MM},{config.EXTENSION_PATH_RW},{config.EXTENSION_PATH_PH},{config.EXTENSION_PATH_SUB}",
            ] + (extra_args or []),
        )
        # Трейсинг по флагу config.TRACE или переменной окружения TRACE=1
        trace_enabled = getattr(config, "TRACE", False) or os.environ.get("TRACE") == "1"
        if trace_enabled:
            await context.tracing.start(screenshots=True, snapshots=True, sources=True)
            
        original_close = context.close
        async def safe_close(*args, **kwargs):
            import asyncio
            try:
                await asyncio.wait_for(original_close(*args, **kwargs), timeout=8.0)
            except asyncio.TimeoutError:
                logging.warning(f"[{name}] ⚠️ context.close() завис по таймауту. Применяем принудительное закрытие процесса...")
                try:
                    user_dir = os.path.join(PROFILES_DIR, name)
                    await asyncio.to_thread(force_kill_chrome_by_profile, user_dir)
                except Exception as fk_err:
                    logging.error(f"[{name}] Ошибка при принудительном убийстве процесса: {fk_err}")
            except Exception:
                pass
        context.close = safe_close
        
        return context


async def stop_tracing(context, name, failed: bool):
    if not context:
        return
    try:
        # Трейсинг по флагу config.TRACE или переменной окружения TRACE=1
        trace_enabled = getattr(config, "TRACE", False) or os.environ.get("TRACE") == "1"
        if not trace_enabled:
            return

        if failed:
            PROJECT_ROOT = Path(__file__).resolve().parent.parent
            trace_dir = PROJECT_ROOT / "logs" / "traces"
            trace_dir.mkdir(parents=True, exist_ok=True)
            await context.tracing.stop(path=str(trace_dir / f"{name}.zip"))
            logging.info(f"[{name}] трассировка сохранена: logs/traces/{name}.zip")
        else:
            await context.tracing.stop()
    except Exception as e:
        logging.debug(f"[{name}] не удалось остановить трассировку: {e}")



async def launch_context_manual(
    playwright,
    profile_name,
    cfg,
    index,
    win_width,
    win_height,
    cols,
):
    lock = get_launch_lock()
    async with lock:
        # Стартовый разброс (1-3с)
        import random
        import asyncio
        stagger_delay = random.uniform(1.0, 3.0)
        logging.info(f"[{profile_name}] Стартовый разброс: пауза {stagger_delay:.2f}с перед запуском браузера")
        await asyncio.sleep(stagger_delay)

        user_data_dir = os.path.join(PROFILES_DIR, profile_name)
        os.makedirs(user_data_dir, exist_ok=True)

        # Ограничиваем количество строк, чтобы окна не уходили за нижний край экрана
        # Если win_height == 540, а экран 1080, то макс. строк = 2.
        screen_height = 1080
        max_rows = max(1, screen_height // win_height)
        
        windows_per_screen = cols * max_rows
        
        grid_index = index % windows_per_screen
        layer = index // windows_per_screen
        
        col = grid_index % cols
        row = grid_index // cols

        offset = layer * 30
        x = col * win_width + offset
        y = row * win_height + offset

        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            channel="chromium",  # ✅ Chromium (поддерживает --load-extension)
            headless=False,
            proxy=cfg["proxy"],
            timezone_id=cfg.get("timezone", "Europe/Berlin"),
            locale=cfg.get("locale", "en-US"),
            extra_http_headers={
                "Accept-Language": cfg.get(
                    "accept_language", "en-US,en;q=0.9"
                )
            },
            no_viewport=True,
            args=[
                f"--window-size={win_width},{win_height}",
                f"--window-position={x},{y}",

                "--disable-blink-features=AutomationControlled",
                "--disable-webrtc",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--webrtc-ip-handling-policy=disable_non_proxied_udp",

                # ✅ Загружаем расширения (работает только в Chromium)
                f"--disable-extensions-except={config.EXTENSION_PATH_MM},{config.EXTENSION_PATH_RW},{config.EXTENSION_PATH_PH},{config.EXTENSION_PATH_SUB}",
                f"--load-extension={config.EXTENSION_PATH_MM},{config.EXTENSION_PATH_RW},{config.EXTENSION_PATH_PH},{config.EXTENSION_PATH_SUB}",
            ],
        )
        
        original_close = context.close
        async def safe_close(*args, **kwargs):
            import asyncio
            try:
                await asyncio.wait_for(original_close(*args, **kwargs), timeout=8.0)
            except asyncio.TimeoutError:
                logging.warning(f"[{profile_name}] ⚠️ context.close() завис по таймауту. Применяем принудительное закрытие процесса...")
                try:
                    user_dir = os.path.join(PROFILES_DIR, profile_name)
                    await asyncio.to_thread(force_kill_chrome_by_profile, user_dir)
                except Exception as fk_err:
                    logging.error(f"[{profile_name}] Ошибка при принудительном убийстве процесса: {fk_err}")
            except Exception:
                pass
        context.close = safe_close
        
        return context
