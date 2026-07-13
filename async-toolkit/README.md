# Async Networking & Automation Toolkit

A collection of lightweight, production-ready helper modules designed to enhance the stability, resilience, and debugging capabilities of asynchronous Python programs and Playwright automations.

All modules are completely self-contained and free from any hardcoded environment credentials or third-party crypto-centric libraries.

---

## Module Overview

### 1. `proxy_health.py`
Provides tools for asynchronous proxy diagnostic checks:
- **`confirm_proxy_dead(proxy, retries)`**: Escalates query timeouts to verify proxy health.
- Distinguishes physical network connection issues (e.g. proxy server down) from website specific lags/timeouts, preventing false positives.
- Purely async (powered by offloading blocking `requests` calls to `asyncio.to_thread`).

### 2. `resilience.py`
A resilience overlay for Playwright:
- **`dump_failure(page, name, action)`**: Atomically captures and persists the current browser screen layout (full-page screenshot) and raw HTML source during exceptions to facilitate automated debugging.
- **`click_if_visible(locator, name, label)`**: Safely triggers interactions on volatile or slow-loading SPA pages without crashing when elements are unattached or hidden.
- Tracing helper function to dynamically record and save Playwright event ZIP traces under error states.

### 3. `logger.py`
A unified logging engine:
- Directs structured console outputs and rotating file outputs simultaneously.
- **`SecretMaskerFilter`**: Intercepts active logging buffers to systematically mask passwords, telegram bot keys, and proxy tokens with a generic `[REDACTED]` label before writing to disk.

### 4. `result.py`
A lightweight, typed dataclass interface (`TaskResult`) representing task operations, facilitating clean serialization across async workers.

---

## How to Run Examples

### 1. Install Dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Proxy Checker Example
Runs the proxy verifier against a simulated dead server configuration. Demonstrates retry policies and log mask filters:
```bash
python examples/check_proxy.py
```

### 3. Playwright Resilience Example
Launches a headless Chromium instance, spawns a mock HTML test page, runs safe click operations, and creates a diagnostic failure output:
```bash
python examples/resilient_click.py
```

---

# Набор Асинхронных Сетевых Утилит

Коллекция переиспользуемых модулей для повышения отказоустойчивости сетевых скриптов и автоматизации браузеров на Playwright.

---

## Содержимое пакета

1. **`proxy_health.py`** — асинхронный чекер прокси, отличающий сетевые падения от медленной загрузки сайтов.
2. **`resilience.py`** — инструменты выживания Playwright: автодамп скриншота + HTML при ошибках, безопасные клики, сохранение архива трассировки событий (Playwright trace).
3. **`logger.py`** — универсальный логгер с фильтром маскирования секретов (паролей, токенов).
4. **`result.py`** — типизированный контейнер результатов выполнения задач (`TaskResult`).
