# Steam Market Monitor

A lightweight, robust background application for real-time monitoring of Steam Community Market listings. 

This utility runs as a windowless background task on Windows, polling specified market searches, parsing search results, performing automatic currency conversions, filtering duplicates, and routing notifications straight to your Telegram channel or chat.

---

## Technical Features & Engineering Challenges

1. **Reverse-Engineering Steam's Search Protocol**  
   Rather than using browser-based scrapers (like Selenium/Playwright) which are resource-heavy, this project reverse-engineers the internal Steam search endpoints using direct HTTP requests. It simulates search requests mimicking native browser payloads, extracting structured HTML page lists.

2. **Resilience Against Aggressive Rate-Limiting & Backoff**  
   Steam is well-known for returning `HTTP 429 Too Many Requests` very quickly. To combat this, the monitor employs:
   - Configurable randomized delays (`request_delay_seconds` + `request_delay_jitter_seconds`).
   - An active exponential backoff sleep multiplier when encountering HTTP 429 or network errors, scaling wait times before retrying.

3. **In-Memory and Local State Deduplication**  
   Avoids sending duplicate Telegram alerts for the same listing. Items are tracked by unique IDs, price, and timestamp, maintaining local persistence (`state.json`) between application restarts.

4. **Multi-Currency Support & Automated FX Conversions**  
   Retrieves actual currency exchange rates and automatically normalizes diverse foreign currency values (USD, EUR, CNY, etc.) into Russian Rubles (`₽`), including custom currency symbol mapping.

5. **Standalone Windows Executable Assembly**  
   Bundled via PyInstaller in `--noconsole` mode. To avoid crashes caused by print/write operations when `sys.stdout` and `sys.stderr` are absent under Windows windowless mode, standard output streams are safely redirected to `os.devnull` before logging initialization.

---

## Configuration & Usage

### 1. Requirements
Install dependencies using pip:
```bash
pip install -r requirements.txt
```

### 2. Setting Up Configuration
1. Copy `config.example.json` to `config.json`.
2. Generate a Telegram Bot token through [@BotFather](https://t.me/BotFather) and paste it into `"telegram_token"`.
3. Leave `"chat_id"` as `null`. Send a message (e.g. `/start`) to your Telegram bot. When you run the monitor, it will automatically query `getUpdates`, fetch your `chat_id`, and save it back to `config.json`.
4. Customize the `"searches"` list with your Steam Market urls and search configurations.

### 3. Launching
Run the Python script:
```bash
python monitor.py
```
Or use the `build.bat` script to package it as a standalone executable (`dist/steam_market_monitor.exe`).

---

# Монитор Торговой Площадки Steam

Легковесное и отказоустойчивое фоновое приложение для отслеживания лотов на торговой площадке Steam в реальном времени.

Программа работает как фоновый процесс для Windows без консольного окна, опрашивает заданные поисковые ссылки, парсит результаты, конвертирует зарубежные валюты в рубли, отсекает дубликаты и отправляет уведомления в Telegram.

---

## Технические особенности и вызовы

1. **Реверс-инжиниринг протокола поиска Steam**  
   Вместо тяжелых браузерных библиотек (Playwright/Selenium), монитор напрямую общается с внутренними эндпоинтами поиска Steam, имитируя запросы браузера и экономя системные ресурсы.

2. **Преодоление Rate-Limit ограничений Steam**  
   Steam жестко ограничивает частые запросы (HTTP 429). В приложении реализована логика задержек с джиттером (случайным отклонением) и алгоритм экспоненциального ожидания (exponential backoff) при обнаружении блокировки или сетевых сбоев.

3. **Дедупликация и хранение состояния**  
   Для предотвращения спама одинаковыми лотами используется локальная база состояния (`state.json`). Лот повторно не отправляется, если не изменилась его цена или состояние.

4. **Мультивалютная конвертация**  
   Цены лотов, выставленных в долларах, евро или других валютах, автоматически приводятся к общему знаменателю (рубли) по актуальному курсу обмена.

5. **Сборка в EXE для Windows без консоли**  
   Приложение собирается через PyInstaller с флагом `--noconsole`. Во избежание падений при выводе в отсутствующие потоки `sys.stdout`/`sys.stderr`, все стандартные потоки безопасно перенаправляются в `os.devnull` при старте.
