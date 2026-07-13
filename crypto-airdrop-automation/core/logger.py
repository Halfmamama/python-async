import logging
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"

LOG_DIR.mkdir(exist_ok=True)

# Глобальный флаг для отслеживания инициализации
_configured = False

class SecretMaskerFilter(logging.Filter):
    def __init__(self, secrets_to_mask=None):
        super().__init__()
        self.secrets = set()
        if secrets_to_mask:
            for s in secrets_to_mask:
                if s and isinstance(s, str) and len(s) > 3:
                    self.secrets.add(s)

    def filter(self, record):
        if isinstance(record.msg, str) and self.secrets:
            msg = record.msg
            for secret in self.secrets:
                msg = msg.replace(secret, "[REDACTED]")
            record.msg = msg
        return True

def setup_logger(run_id=None):
    global _configured
    root_logger = logging.getLogger()

    # Проверяем, не настроен ли уже логгер.
    has_file_handler = any(isinstance(h, logging.FileHandler) for h in root_logger.handlers)
    
    if not _configured and not has_file_handler:
        # Настраиваем один root-логгер
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_file = LOG_DIR / f"run_{timestamp}.log"
        
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        
        # Получаем список секретов для маскирования
        secrets_to_mask = []
        try:
            import config
            if hasattr(config, "PASSWORD"):
                secrets_to_mask.append(config.PASSWORD)
            if hasattr(config, "PROFILES"):
                for profile in config.PROFILES.values():
                    proxy = profile.get("proxy", {})
                    if proxy.get("username"):
                        secrets_to_mask.append(proxy["username"])
                    if proxy.get("password"):
                        secrets_to_mask.append(proxy["password"])
            if hasattr(config, "BOT_TOKENS"):
                for tok in config.BOT_TOKENS.values():
                    secrets_to_mask.append(tok)
        except Exception:
            pass

        masker = SecretMaskerFilter(secrets_to_mask)
        file_handler.addFilter(masker)
        stream_handler.addFilter(masker)
        
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(file_handler)
        root_logger.addHandler(stream_handler)
        
        _configured = True
        
    return root_logger, root_logger
