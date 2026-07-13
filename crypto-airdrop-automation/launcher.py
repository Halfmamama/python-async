"""
Automation Launcher — единая точка запуска проектов.

Запуск:
    python launcher.py
"""

import asyncio
import json
import logging
import random
import sys
import time
import uuid
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

# Добавляем корень проекта в sys.path, чтобы импорты работали
# независимо от того, откуда и как запущен скрипт.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from playwright.async_api import async_playwright
from core.account_selection import parse_accounts

# Фикс кодировки для Windows-консоли (cp1251 → utf-8)
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ═══════════════════════════════════════════════════════════════
#                    КОНФИГУРАЦИЯ АККАУНТОВ
# ═══════════════════════════════════════════════════════════════

ALL_ACCOUNTS = [f"acc_{i}" for i in range(1, 11)]


# ═══════════════════════════════════════════════════════════════
#                   ЧЕЛОВЕЧЕСКИЕ ЗАДЕРЖКИ (общие)
# ═══════════════════════════════════════════════════════════════
# Проекты используют random.uniform() внутри idle()/human_pause()
# — каждый вызов даёт уникальную задержку.

HUMAN_DELAYS = {
    "min_action_delay": 0.5,    # Задержка между действиями (сек)
    "max_action_delay": 2.0,
    "min_startup_delay": 5.0,   # Задержка перед стартом аккаунта
    "max_startup_delay": 15.0,
}

# Максимальное количество автоматических перезапусков для упавших аккаунтов
MAX_RETRIES = 5

# --- Рандомизированный per-account планировщик ---
GLOBAL_MAX_CONCURRENT = 5          # макс. одновременно открытых браузеров (глобально)
RANDOMIZE_EXECUTION = True         # флаг рандом-планировщика
MANUAL_PROJECTS = set()            # исключаются из рандома, идут классически
SERIAL_PROJECTS = {"nemesis"}      # per-project concurrency=1

# Файл истории выполнения (по дням)
HISTORY_FILE = PROJECT_ROOT / "logs" / "launcher_history.json"


# ═══════════════════════════════════════════════════════════════
#                    ИСТОРИЯ ВЫПОЛНЕНИЯ
# ═══════════════════════════════════════════════════════════════

def load_history() -> dict:
    """Загружает историю из JSON."""
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_history(history: dict):
    """Сохраняет историю в JSON."""
    HISTORY_FILE.parent.mkdir(exist_ok=True)
    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def record_completion(
    history: dict,
    proj_key: str,
    results: dict,
    scenario: str | None,
):
    """
    Записывает результаты проекта в историю.
    Сохраняет: сценарий, количество успешных/ошибочных, список аккаунтов.
    """
    today = get_today_key()
    if today not in history:
        history[today] = {}

    ok_accs = set([a for a, r in results.items() if not r.get("error")])
    err_accs = set([a for a, r in results.items() if r.get("error")])

    # Если уже есть данные за сегодня, обновляем их (мердж), а не затираем
    if proj_key in history[today]:
        prev_data = history[today][proj_key]
        prev_ok = set(prev_data.get("ok", []))
        prev_err = set(prev_data.get("err", []))
        
        # Убираем старые статусы для аккаунтов, которые мы только что обработали
        for acc in ok_accs.union(err_accs):
            prev_ok.discard(acc)
            prev_err.discard(acc)
            
        ok_accs = ok_accs.union(prev_ok)
        err_accs = err_accs.union(prev_err)

    # Сортируем аккаунты для красоты
    final_ok = sorted(list(ok_accs), key=lambda x: int(x.split("_")[1]) if "_" in x else 0)
    final_err = sorted(list(err_accs), key=lambda x: int(x.split("_")[1]) if "_" in x else 0)

    history[today][proj_key] = {
        "scenario": scenario,
        "ok": final_ok,
        "err": final_err,
        "total": len(final_ok) + len(final_err),
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    }


def get_today_status(history: dict) -> dict:
    """
    Возвращает статус на сегодня: {proj_key: {ok, err, total, scenario, time}}.
    """
    today = get_today_key()
    return history.get(today, {})


# ═══════════════════════════════════════════════════════════════
#                     РЕЕСТР ПРОЕКТОВ
# ═══════════════════════════════════════════════════════════════

PROJECTS = OrderedDict([
    ("nemesis", {
        "name": "Nemesis",
        "desc": "Sepolia: swap, long/short, liquidity",
        "scenarios": OrderedDict([
            ("all",      "Полный цикл (swap + LS + liquidity)"),
            ("swap",     "Только свапы (ETH→DAI + DAI→token)"),
            ("ls",       "Только Long/Short"),
            ("liq",      "Только Liquidity"),
            ("swap+ls",  "Свапы + Long/Short"),
            ("swap+liq", "Свапы + Liquidity"),
            ("ls+liq",   "Long/Short + Liquidity"),
        ]),
        "default_scenario": "all",
        "default_accounts": ALL_ACCOUNTS,
        "max_concurrent": 5,
        "batch_size": None,
    }),
])


# ═══════════════════════════════════════════════════════════════
#                    ПАРСИНГ ВВОДА
# ═══════════════════════════════════════════════════════════════


def parse_projects(raw: str) -> list:
    """Парсит выбор проектов: номера через запятую или *."""
    raw = raw.strip()
    keys = list(PROJECTS.keys())
    if raw == "*":
        return keys

    selected = []
    for part in raw.split(","):
        part = part.strip()
        try:
            idx = int(part) - 1
            if 0 <= idx < len(keys):
                selected.append(keys[idx])
        except ValueError:
            pass
    return selected


# ═══════════════════════════════════════════════════════════════
#                    МЕНЮ И UI
# ═══════════════════════════════════════════════════════════════

def _hr(char="═", width=52):
    return char * width


def show_project_menu(history: dict, today_status: dict | None = None):
    """Показывает главное меню выбора проектов с дневным статусом."""
    import time
    print(f"\n{_hr()}")
    print(f"  [START] AUTOMATION LAUNCHER  [{get_today_key()}]")
    print(f"{_hr()}")
    keys = list(PROJECTS.keys())
    for i, key in enumerate(keys, 1):
        proj = PROJECTS[key]
        # Формируем статус на сегодня
        status = ""
        if today_status and key in today_status:
            st = today_status[key]
            ok_n = len(st.get("ok", []))
            err_n = len(st.get("err", []))
            t = st.get("timestamp", "")
            if err_n == 0:
                status = f"  [OK] {ok_n}/{st['total']} ({t})"
            else:
                status = f"  [WARN] {ok_n}/{st['total']} err:{err_n} ({t})"
                
        # Метки
        batch = "  [батч по 5]" if proj["batch_size"] else ""
        scen = "  [сцен.]" if proj["scenarios"] else ""
        print(f"  {i}. {proj['name']:<22}{status}{batch}{scen}")
    print(f"{_hr()}")
    print(f"  Введите номера через запятую (1,3,5) или * для всех")
    print(f"{_hr()}")


def show_account_prompt(proj_key: str, proj: dict):
    """Показывает промпт выбора аккаунтов."""
    defaults = proj["default_accounts"]
    default_str = ", ".join(defaults)
    batch_note = f"  [WARN] Батчи по {proj['batch_size']} аккаунтов\n" if proj["batch_size"] else ""
    print(f"\n{'─'*52}")
    print(f"  [{proj['name']}] Аккаунты")
    print(f"  По умолчанию: {default_str}")
    if batch_note:
        print(batch_note, end="")
    print(f"  Форматы: 1-5 | 1,3,5 | * | *,-3,-7")
    print(f"  Enter = по умолчанию")
    print(f"{'─'*52}")


def show_scenario_menu(proj: dict):
    """Показывает меню сценариев."""
    scenarios = proj["scenarios"]
    print(f"\n{'─'*52}")
    print(f"  [{proj['name']}] Сценарий:")
    for i, (key, desc) in enumerate(scenarios.items(), 1):
        marker = " <-" if key == proj["default_scenario"] else ""
        print(f"  {i}. {key:<12} — {desc}{marker}")
    print(f"  Enter = {proj['default_scenario']}")
    print(f"{'─'*52}")


def select_scenario(proj: dict) -> str:
    """Запрашивает сценарий у пользователя."""
    scenarios = proj["scenarios"]
    show_scenario_menu(proj)
    raw = input("  Сценарий: ").strip()

    if not raw:
        return proj["default_scenario"]

    keys = list(scenarios.keys())
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(keys):
            return keys[idx]
    except ValueError:
        # Попробовать как текстовый ключ
        if raw in scenarios:
            return raw

    print(f"  [WARN] Неизвестный сценарий, используем: {proj['default_scenario']}")
    return proj["default_scenario"]


def show_confirmation(plan: list):
    """Показывает план перед запуском."""
    print(f"\n{_hr('═')}")
    print(f"  [PLAN] ПЛАН ЗАПУСКА")
    print(f"{_hr('═')}")
    for entry in plan:
        proj = PROJECTS[entry["project"]]
        accs = ", ".join(entry["accounts"])
        scen = f" ({entry['scenario']})" if entry["scenario"] else ""
        batch = f" [батч по {proj['batch_size']}]" if proj["batch_size"] else ""
        print(f"  -> {proj['name']}{scen}{batch}")
        print(f"    Аккаунты ({len(entry['accounts'])}): {accs}")
    print(f"{_hr('═')}")


# ═══════════════════════════════════════════════════════════════
#                    ЗАПУСК ПРОЕКТОВ
# ═══════════════════════════════════════════════════════════════

def _inject_delays(module):
    """Инжектирует общие задержки в модуль, если он поддерживает их."""
    mapping = {
        "MIN_DELAY_BETWEEN_ACTIONS": "min_action_delay",
        "MAX_DELAY_BETWEEN_ACTIONS": "max_action_delay",
        "MIN_STARTUP_DELAY": "min_startup_delay",
        "MAX_STARTUP_DELAY": "max_startup_delay",
    }
    for attr, key in mapping.items():
        if hasattr(module, attr):
            setattr(module, attr, HUMAN_DELAYS[key])


async def _run_adapter(adapter_func, playwright, accounts, scenario, max_concurrent):
    """Вызывает адаптер проекта."""
    kwargs = {"max_concurrent": max_concurrent}
    if scenario:
        # Nemesis: "swap+ls" → ["swap", "ls"]
        if "+" in scenario:
            kwargs["mode"] = scenario.split("+")
        else:
            kwargs["mode"] = scenario

    return await adapter_func(playwright, accounts, **kwargs)


async def run_project(playwright, proj_key: str, accounts: list, scenario: str | None):
    """Запускает один проект через его адаптер."""
    proj = PROJECTS[proj_key]
    max_c = proj["max_concurrent"]

    if proj_key == "nemesis":
        from Nemesis.nemesis_runner_adapter import (
            run_nemesis_with_runner as adapter,
        )
    else:
        logging.error(f"Неизвестный проект: {proj_key}")
        return {}

    # --- Батчевый запуск ---
    batch_size = proj["batch_size"]
    if batch_size and len(accounts) > batch_size:
        all_results = {}
        total_batches = (len(accounts) + batch_size - 1) // batch_size

        for batch_idx in range(0, len(accounts), batch_size):
            batch = accounts[batch_idx : batch_idx + batch_size]
            batch_num = batch_idx // batch_size + 1

            print(f"\n{'─'*52}")
            print(f"  [RETRY] [{proj['name']}] Батч {batch_num}/{total_batches}: {', '.join(batch)}")
            print(f"{'─'*52}")

            results = await _run_adapter(adapter, playwright, batch, scenario, max_c)
            all_results.update(results)

            # Если есть ещё батчи — ждём пользователя
            if batch_idx + batch_size < len(accounts):
                print(f"\n  [OK] Батч {batch_num} завершён.")
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    input,
                    "  [WAIT] Нажмите Enter для запуска следующего батча... ",
                )

        return all_results

    # --- Обычный запуск ---
    return await _run_adapter(adapter, playwright, accounts, scenario, max_c)


# ═══════════════════════════════════════════════════════════════
#           РАНДОМ-ПЛАНИРОВЩИК: ЮНИТ АККАУНТ×ПРОЕКТ
# ═══════════════════════════════════════════════════════════════

async def run_single_unit(playwright, proj_key: str, acc: str, scenario: str | None) -> dict:
    """
    Запускает один проект для ОДНОГО аккаунта (обёртка над run_project для
    рандом-планировщика). Батч-ветка run_project не сработает сама, т.к. len(accounts)==1.
    Всегда возвращает {acc: result}, даже при исключении.
    """
    try:
        result = await run_project(playwright, proj_key, [acc], scenario)
    except Exception as e:
        logging.error(f"[FAIL] [{acc}] {PROJECTS[proj_key]['name']} упал: {e}")
        return {acc: {"error": str(e)}}
    return result


def merge_result(old: dict, new: dict) -> None:
    """
    Смарт-мердж результата ретрая в накопленный результат (in-place):
    error — перезаписывается; bool True — побеждает; непустые значения — обновляются.
    """
    for k, v in new.items():
        if k == "error":
            old[k] = v
        elif isinstance(v, bool):
            if v is True:
                old[k] = True
        else:
            if v:
                old[k] = v


# ═══════════════════════════════════════════════════════════════
#                    ОПРЕДЕЛЕНИЕ УПАВШИХ АККАУНТОВ
# ═══════════════════════════════════════════════════════════════

def get_failed_accounts(proj_key: str, results: dict, original_scenario: str | None):
    """
    Возвращает список (account, scenario) для аккаунтов, которые упали.

    Для Nemesis: определяет конкретный упавший сценарий по результатам.
    """
    failed = []
    
    def _has_scen(s: str) -> bool:
        if not original_scenario or original_scenario == "all": return True
        if "+" in original_scenario: return s in original_scenario.split("+")
        return s == original_scenario

    for acc, res in results.items():
        if isinstance(res, dict) and res.get("skipped"):
            continue
        if isinstance(res, dict) and res.get("proxy_suspect") is True:
            logging.info(f"Skipping retry for {acc} in {proj_key} because the proxy is suspected to be dead (will be checked post-run).")
            continue

        if res.get("error"):
            # Полная ошибка — перезапускаем весь оригинальный сценарий
            failed.append((acc, original_scenario))
            continue

        if proj_key == "nemesis":
            # Определяем какие шаги провалились
            failed_steps = []
            if _has_scen("swap") and not res.get("swap_eth_dai") and not res.get("swap_dai_token"):
                failed_steps.append("swap")
            if _has_scen("ls") and res.get("long_short") is False:
                failed_steps.append("ls")
            if _has_scen("liq") and res.get("liquidity") is False:
                failed_steps.append("liq")

            if failed_steps:
                retry_scen = "+".join(failed_steps) if len(failed_steps) > 1 else failed_steps[0]
                failed.append((acc, retry_scen))

    return failed


# ═══════════════════════════════════════════════════════════════
#                    ФОРМАТИРОВАНИЕ ОТЧЁТОВ
# ═══════════════════════════════════════════════════════════════

def _icon(val):
    """Преобразует bool/None в иконку."""
    if val is True:
        return "[OK]"
    if val is False:
        return "[FAIL]"
    return "—"


def format_project_summary(
    proj_key: str, results: dict, scenario: str | None,
    retry_num: int = 0,
) -> str:
    """Форматирует отчёт по одному проекту."""
    proj = PROJECTS[proj_key]
    lines = []
    scen_str = f" ({scenario})" if scenario else ""
    retry_str = f" [retry {retry_num}]" if retry_num else ""
    lines.append(f"\n{'═'*52}")
    lines.append(f"   {proj['name']}{scen_str}{retry_str} — {len(results)} аккаунтов")
    lines.append(f"{'═'*52}")

    if not results:
        lines.append("  Нет результатов")
        return "\n".join(lines)

    success_count = 0
    error_count = 0

    for name in sorted(results.keys(), key=lambda x: int(x.split("_")[1])):
        res = results[name]
        err = res.get("error")
        parts = [f"  {name:<8}"]

        if proj_key == "nemesis":
            parts.append(f"wallet:{_icon(res.get('wallet'))}")
            parts.append(f"conn:{_icon(res.get('connected'))}")
            parts.append(f"ETH→DAI:{_icon(res.get('swap_eth_dai'))}")
            pair = res.get("pair_token", "?")
            parts.append(f"DAI→{pair}:{_icon(res.get('swap_dai_token'))}")
            parts.append(f"LS:{_icon(res.get('long_short'))}")
            parts.append(f"liq:{_icon(res.get('liquidity'))}")
        else:
            for k, v in res.items():
                if k != "error" and isinstance(v, bool):
                    parts.append(f"{k}:{_icon(v)}")

        if err:
            parts.append(f"[ERROR]{err[:40]}")
            error_count += 1
        else:
            success_count += 1

        lines.append(" | ".join(parts))

    lines.append(f"{'─'*52}")
    lines.append(f"  Итого: {success_count} [OK] / {error_count} [FAIL]")
    return "\n".join(lines)


def format_final_summary(all_summaries: list, elapsed: float, retry_count: int = 0):
    """Форматирует финальный отчёт по всем проектам."""
    mins = int(elapsed // 60)
    secs = int(elapsed % 60)

    print(f"\n{'═'*52}")
    print(f"  [FINISH] ФИНАЛЬНЫЙ ОТЧЁТ")
    print(f"{'═'*52}")

    total_ok = 0
    total_err = 0

    for summary in all_summaries:
        print(summary["formatted"])
        total_ok += summary["ok"]
        total_err += summary["err"]

    print(f"\n{'═'*52}")
    print(f"  Проектов: {len(all_summaries)}")
    print(f"  Аккаунтов: {total_ok + total_err} ({total_ok} [OK] / {total_err} [FAIL])")
    if retry_count > 0:
        print(f"  Ретраев: {retry_count}")
    print(f"  Время: {mins} мин {secs} сек")
    print(f"{'═'*52}\n")


# ═══════════════════════════════════════════════════════════════
#                    ЛОГИРОВАНИЕ
# ═══════════════════════════════════════════════════════════════

def setup_launcher_logger(stream: bool = True):
    """Настраивает логирование для лаунчера.

    Args:
        stream: добавить StreamHandler (вывод в консоль).
                При запуске через TUI передавать False — Textual владеет терминалом.
    """
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = log_dir / f"launcher_{timestamp}.log"

    handlers = [logging.FileHandler(log_file, encoding="utf-8")]
    if stream:
        handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.info(f" Лог: {log_file}")





# ═══════════════════════════════════════════════════════════════
#                    MAIN
# ═══════════════════════════════════════════════════════════════

async def main():
    setup_launcher_logger()

    # Автоочистка логов старше 7 дней
    try:
        from core.log_cleanup import cleanup_old_logs
        cleanup_old_logs()
    except Exception as e:
        logging.warning(f"[WARN] Ошибка при автоочистке логов: {e}")

    # Установка приоритета процесса (Windows BELOW_NORMAL_PRIORITY_CLASS)
    try:
        import os
        import psutil
        psutil.Process(os.getpid()).nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        logging.info("[WARN] Приоритет процесса лаунчера установлен в BELOW_NORMAL")
    except Exception as e:
        logging.debug(f"Не удалось установить приоритет процесса: {e}")





    # Загружаем историю
    history = load_history()
    today_status = get_today_status(history)

    # --- 1. Выбор проектов ---
    show_project_menu(history, today_status)
    raw_projects = input("  Проекты: ").strip()
    selected_keys = parse_projects(raw_projects)

    if not selected_keys:
        print("  [FAIL] Проекты не выбраны")
        return

    # --- 2. Для каждого проекта: аккаунты + сценарий ---
    plan = []
    for key in selected_keys:
        proj = PROJECTS[key]

        # Аккаунты
        show_account_prompt(key, proj)
        raw_accs = input("  Аккаунты: ").strip()
        accounts = parse_accounts(raw_accs, proj["default_accounts"])

        if not accounts:
            print(f"  [WARN] [{proj['name']}] Нет аккаунтов, пропускаю")
            continue

        # Сценарий
        scenario = None
        if proj["scenarios"]:
            scenario = select_scenario(proj)

        plan.append({
            "project": key,
            "accounts": accounts,
            "scenario": scenario,
        })

    if not plan:
        print("  [FAIL] Нечего запускать")
        return

    # --- 3. Подтверждение ---
    show_confirmation(plan)
    confirm = input("  Начать? [Y/n]: ").strip().lower()
    if confirm and confirm != "y":
        print("  [FAIL] Отменено")
        return

    # --- PROXY PRE-FLIGHT & RUN ---
    from core.run_settings import RunSettings
    settings = RunSettings(
        max_concurrent_browsers=GLOBAL_MAX_CONCURRENT,
        launch_stagger_min=getattr(config, "ACCOUNT_START_JITTER_MIN", 20.0),
        launch_stagger_max=getattr(config, "ACCOUNT_START_JITTER_MAX", 90.0),
        inter_account_delay_min=0.0,
        inter_account_delay_max=0.0,
        accounts_run_ratio=1.0,
        skip_probability=0.0,
        max_retries=MAX_RETRIES
    )
    await run_batch(plan, settings)


async def run_batch(plan: list[dict], settings, on_event=None) -> dict:
    """
    Запускает пакет проектов по заданному плану с переданными настройками RunSettings.
    """
    import config
    from core.run_settings import RunSettings

    # Сообщаем о старте всего прогона
    if on_event:
        on_event({"event_type": "run_start", "plan": plan})

    # --- Рандомизация доли аккаунтов (accounts_run_ratio) ---
    if settings.accounts_run_ratio < 1.0:
        all_unique_accounts = sorted(list({acc for entry in plan for acc in entry["accounts"]}))
        n_to_run = max(1, round(len(all_unique_accounts) * settings.accounts_run_ratio))
        run_accounts = set(random.sample(all_unique_accounts, n_to_run))
        excluded_accounts = sorted(list(set(all_unique_accounts) - run_accounts))
        logging.info(
            f" Фильтрация по accounts_run_ratio ({settings.accounts_run_ratio}): "
            f"запускаем {len(run_accounts)} из {len(all_unique_accounts)} аккаунтов. "
            f"Исключены: {excluded_accounts}"
        )
        filtered_plan = []
        for entry in plan:
            filtered_accs = [acc for acc in entry["accounts"] if acc in run_accounts]
            if filtered_accs:
                filtered_plan.append({
                    "project": entry["project"],
                    "accounts": filtered_accs,
                    "scenario": entry["scenario"]
                })
        plan = filtered_plan

    if not plan:
        logging.info("  [FAIL] Нечего запускать после фильтрации аккаунтов")
        if on_event:
            on_event({"event_type": "run_complete", "results": {}, "summaries": []})
        return {"results": {}, "summaries": []}

    # --- DB & GSheets init ---
    try:
        from core.db import init_db, log_execution
        init_db()
        _db_available = True
    except Exception as e:
        logging.warning(f"[WARN] DB unavailable: {e}")
        _db_available = False
        log_execution = None

    try:
        from core.sheets import get_gsheets_sync, update_gsheet_batch
        gs_sync = get_gsheets_sync()
        if gs_sync.enabled:
            project_info = [(p["name"], k) for k, p in PROJECTS.items()]
            gs_sync.init_all_tabs(project_info)
        _gs_available = True
    except Exception as e:
        logging.warning(f"[WARN] Google Sheets unavailable: {e}")
        _gs_available = False
        update_gsheet_batch = None

    session_id = str(uuid.uuid4())
    history = load_history()



    # --- 4. Запуск ---
    start_time = time.time()
    all_summaries = []
    all_results_by_project = {}

    random_plan = plan
    active_tasks = []

    async with async_playwright() as playwright:
        global_sem = asyncio.Semaphore(settings.max_concurrent_browsers)
        project_sems = {
            k: asyncio.Semaphore(1 if k in SERIAL_PROJECTS else PROJECTS[k]["max_concurrent"])
            for k in PROJECTS
        }
        gsheets_lock = asyncio.Lock()
        persist_lock = asyncio.Lock()
        project_remaining: dict = {}

        def _upsert_summary(proj_key: str, formatted: str, ok: int, err: int, results: dict):
            entry = {
                "project": proj_key,
                "formatted": formatted,
                "ok": ok,
                "err": err,
                "elapsed": 0,
                "results": results,
            }
            for idx, existing in enumerate(all_summaries):
                if existing["project"] == proj_key:
                    all_summaries[idx] = entry
                    return
            all_summaries.append(entry)

        async def on_project_complete(proj_key: str, retry_num: int = 0):
            data = all_results_by_project[proj_key]
            results = data["results"]
            scenario = data["scenario"]
            proj = PROJECTS[proj_key]

            async with persist_lock:
                formatted = format_project_summary(proj_key, results, scenario, retry_num=retry_num)
                print(formatted)

                ok_count = sum(1 for r in results.values() if not r.get("error"))
                err_count = sum(1 for r in results.values() if r.get("error"))
                _upsert_summary(proj_key, formatted, ok_count, err_count, results)

                logging.info(
                    f"[OK] {proj['name']} завершён (retry={retry_num}): "
                    f"{ok_count} ok / {err_count} err"
                )

                record_completion(history, proj_key, results, scenario)
                save_history(history)

                if _db_available:
                    for acc_name, res in results.items():
                        try:
                            await asyncio.to_thread(
                                log_execution,
                                account_name=acc_name,
                                project_key=proj_key,
                                result_data=res,
                                scenario=scenario,
                                session_id=session_id,
                                retry_round=retry_num,
                            )
                        except Exception as db_err:
                            logging.debug(f"DB log error for {acc_name}: {db_err}")

            if _gs_available:
                async with gsheets_lock:
                    try:
                        await asyncio.to_thread(update_gsheet_batch, proj_key, proj["name"], results)
                    except Exception as gs_err:
                        logging.warning(f"[WARN] GSheets batch error: {gs_err}")

        async def account_worker(acc: str, queue: list, retry_num: int = 0):
            if retry_num == 0:
                delay = random.uniform(settings.launch_stagger_min, settings.launch_stagger_max)
                logging.info(f"[{acc}] Джиттер старта аккаунта: пауза {delay:.1f}с перед первым юнитом")
                await asyncio.sleep(delay)

            for i, (proj_key, scenario) in enumerate(queue):
                # Пауза между проектами одного аккаунта
                if i > 0 and settings.inter_account_delay_max > 0:
                    delay = random.uniform(settings.inter_account_delay_min, settings.inter_account_delay_max)
                    logging.info(f"[{acc}] Пауза {delay:.1f}с перед запуском проекта {proj_key}")
                    await asyncio.sleep(delay)

                # Проверка skip_probability
                if proj_key not in MANUAL_PROJECTS and settings.skip_probability > 0:
                    if random.random() < settings.skip_probability:
                        logging.info(f" [{acc}] Проект {proj_key} пропущен по skip_probability ({settings.skip_probability:.2f})")
                        if on_event:
                            on_event({
                                "event_type": "unit_skipped",
                                "project": proj_key,
                                "account": acc,
                                "scenario": scenario,
                                "status": "skipped",
                                "retry_num": retry_num
                            })
                        bucket = all_results_by_project[proj_key]["results"]
                        bucket[acc] = {"skipped": True}
                        project_remaining[proj_key] -= 1
                        if project_remaining[proj_key] == 0:
                            await on_project_complete(proj_key, retry_num=retry_num)
                        continue

                if on_event:
                    on_event({
                        "event_type": "unit_start",
                        "project": proj_key,
                        "account": acc,
                        "scenario": scenario,
                        "retry_num": retry_num
                    })

                async with project_sems[proj_key]:
                    async with global_sem:
                        unit = await run_single_unit(playwright, proj_key, acc, scenario)

                unit_result = unit.get(acc, {"error": "Адаптер не вернул результат"})
                bucket = all_results_by_project[proj_key]["results"]
                if retry_num > 0 and acc in bucket:
                    merge_result(bucket[acc], unit_result)
                else:
                    bucket[acc] = unit_result

                is_err = bool(unit_result.get("error"))
                if on_event:
                    on_event({
                        "event_type": "unit_failed" if is_err else "unit_success",
                        "project": proj_key,
                        "account": acc,
                        "scenario": scenario,
                        "error": unit_result.get("error") if is_err else None,
                        "retry_num": retry_num
                    })

                project_remaining[proj_key] -= 1
                if project_remaining[proj_key] == 0:
                    await on_project_complete(proj_key, retry_num=retry_num)



        # --- 4b. Рандом-пул ---
        account_queues = {}
        for entry in random_plan:
            proj_key = entry["project"]
            accounts = entry["accounts"]
            all_results_by_project[proj_key] = {
                "results": {},
                "scenario": entry["scenario"],
            }
            project_remaining[proj_key] = len(accounts)
            for acc in accounts:
                account_queues.setdefault(acc, []).append((proj_key, entry["scenario"]))

        for acc, queue in account_queues.items():
            random.shuffle(queue)
            order = ", ".join(f"{pk}{f'({sc})' if sc else ''}" for pk, sc in queue)
            logging.info(f" [{acc}] Порядок выполнения: {order}")

        if account_queues:
            try:
                active_tasks = [
                    asyncio.create_task(account_worker(acc, queue))
                    for acc, queue in account_queues.items()
                ]
                await asyncio.gather(*active_tasks)
            except asyncio.CancelledError:
                logging.info("[STOP] Получен сигнал отмены в random-пуле. Отменяем активные задачи...")
                for t in active_tasks:
                    if not t.done():
                        t.cancel()
                await asyncio.shield(asyncio.gather(*active_tasks, return_exceptions=True))
                logging.info("[INFO] Все воркеры random-пула завершили работу.")
                raise



        # --- 5. Ретраи ---
        total_retries = 0
        for retry_round in range(1, settings.max_retries + 1):
            failed_units = [
                (pk, acc, scen)
                for pk, data in all_results_by_project.items()
                for acc, scen in get_failed_accounts(pk, data["results"], data["scenario"])
            ]

            if not failed_units:
                logging.info("[OK] Все аккаунты отработали успешно, retry не требуется")
                break

            total_retries += 1

            print(f"\n{'═'*52}")
            print(f"  [RETRY] RETRY {retry_round}/{settings.max_retries} — {len(failed_units)} упавших аккаунтов")
            print(f"{'═'*52}")
            for pk, acc, scen in failed_units:
                proj_name = PROJECTS[pk]["name"]
                sc_str = f" ({scen})" if scen else ""
                print(f"  -> {proj_name}{sc_str}: {acc}")
            print(f"{'─'*52}")

            # Строим очереди на аккаунт и пересчитываем project_remaining для этого раунда
            retry_queues = {}
            retry_counts = {}
            for pk, acc, scen in failed_units:
                retry_queues.setdefault(acc, []).append((pk, scen))
                retry_counts[pk] = retry_counts.get(pk, 0) + 1
            project_remaining.update(retry_counts)

            for acc, queue in retry_queues.items():
                random.shuffle(queue)
                order = ", ".join(f"{pk}{f'({sc})' if sc else ''}" for pk, sc in queue)
                logging.info(f" [RETRY {retry_round}] [{acc}] Порядок выполнения: {order}")
                for pk, scen in queue:
                    if on_event:
                        on_event({
                            "event_type": "unit_retry",
                            "project": pk,
                            "account": acc,
                            "scenario": scen,
                            "retry_num": retry_round
                        })

            try:
                active_tasks = [
                    asyncio.create_task(account_worker(acc, queue, retry_num=retry_round))
                    for acc, queue in retry_queues.items()
                ]
                await asyncio.gather(*active_tasks)
            except asyncio.CancelledError:
                logging.info(f"[STOP] Получен сигнал отмены во время RETRY {retry_round}. Отменяем задачи...")
                for t in active_tasks:
                    if not t.done():
                        t.cancel()
                await asyncio.shield(asyncio.gather(*active_tasks, return_exceptions=True))
                logging.info("[INFO] Все воркеры ретрая завершили работу.")
                raise

    elapsed = time.time() - start_time
    format_final_summary(all_summaries, elapsed, total_retries)

    if on_event:
        on_event({
            "event_type": "run_complete",
            "results": all_results_by_project,
            "summaries": all_summaries
        })

    return {"results": all_results_by_project, "summaries": all_summaries}


if __name__ == "__main__":
    asyncio.run(main())
