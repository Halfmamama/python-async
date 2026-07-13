# Конфигурация профилей и расширений (Пример)

# Пароль для автоматической разблокировки MetaMask
PASSWORD = "YOUR_METAMASK_PASSWORD_PLACEHOLDER"

# Пути к распакованным расширениям Chrome (CRX / папки)
EXTENSION_PATH_MM = "C:/path/to/extensions/metamask"
EXTENSION_PATH_RW = "C:/path/to/extensions/rabby"
EXTENSION_PATH_PH = "C:/path/to/extensions/phantom"
EXTENSION_PATH_SUB = "C:/path/to/extensions/sui"

# Включение Playwright Tracing (снимает скриншоты и DOM при сбоях)
TRACE = False

# Настройки окон браузера
AUTO_WINDOW_WIDTH = 1280
AUTO_WINDOW_HEIGHT = 720
SECONDARY_MONITOR_X = 0
SECONDARY_MONITOR_Y = 0

# База профилей аккаунтов. 
# Реальные прокси, адреса и настройки скрыты.
PROFILES = {
    "acc_1": {
        "proxy": {
            "server": "127.0.0.1:8000",
            "username": "dummy_proxy_user",
            "password": "dummy_proxy_password"
        },
        "wallet_address": "0x0000000000000000000000000000000000000000",
        "timezone": "Europe/London",
        "locale": "en-US",
        "accept_language": "en-US,en;q=0.9"
    },
    "acc_2": {
        "proxy": {
            "server": "127.0.0.1:8001",
            "username": "dummy_proxy_user",
            "password": "dummy_proxy_password"
        },
        "wallet_address": "0x0000000000000000000000000000000000000000",
        "timezone": "Europe/Paris",
        "locale": "fr-FR",
        "accept_language": "fr-FR,fr;q=0.9"
    }
}
