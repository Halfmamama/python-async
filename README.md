# Python Async Showcase Portfolio

Welcome to my public portfolio showcase, demonstrating production-grade asynchronous Python engineering, automated web scraping, and resilience toolkits.

This repository highlights my expertise in building high-performance, asynchronous networking applications and test-resilient automation tools. The stack includes **Python 3.11+**, **asyncio** (for concurrency), **Playwright** (for headful/headless browser automation), **Requests & BeautifulSoup4** (for parsing and reverse-engineered API integrations), and **PyInstaller** (for distributing standalone Windows executables).

---

## Projects Overview

1. **[Steam Market Monitor](./steam-market-monitor/)**  
   An offline Windows background daemon that monitors Steam Community Market listings in real-time, reverse-engineers internal Steam POST endpoints, handles rate limits with exponential backoff, filters duplicates, and sends Telegram alerts with automatic currency conversion (to RUB).
   
2. **[Async Networking & Automation Toolkit](./async-toolkit/)**  
   A set of reusable, production-ready core modules designed for browser automation and networking resilience. Includes an advanced proxy health checker distinguishing connection drops from website-level errors, a Playwright-resilience module for UI interaction logs, custom traceback dumping (HTML + screenshots), and a secret-masking logger.

---

# Портфолио Python Async Showcase

Добро пожаловать в моё публичное портфолио, демонстрирующее примеры асинхронной разработки на Python, веб-парсинга и отказоустойчивых инструментов автоматизации.

Репозиторий демонстрирует навыки проектирования высокопроизводительных сетевых приложений и автоматизации браузеров. Стек технологий: **Python 3.11+**, **asyncio** (конкурентность), **Playwright** (автоматизация браузера), **Requests + BeautifulSoup4** (парсинг и интеграция с внутренними эндпоинтами) и **PyInstaller** (сборка standalone-приложений для Windows).

---

## Обзор проектов

1. **[Steam Market Monitor](./steam-market-monitor/)**  
   Фоновый демон для Windows, отслеживающий лоты на торговой площадке Steam в реальном времени. Реверсит внутренние эндпоинты, обрабатывает лимиты Steam (rate limits + backoff), дедуплицирует события и шлет уведомления в Telegram с конвертацией валют.
   
2. **[Async Networking & Automation Toolkit](./async-toolkit/)**  
   Набор переиспользуемых модулей для повышения стабильности сетевых запросов и браузерной автоматизации. Включает продвинутый чекер прокси, модуль отказоустойчивости Playwright (с дампом HTML+скриншотов и безопасными кликами), универсальный логгер с маскированием паролей и токенов.
