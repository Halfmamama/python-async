import logging
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple

class SecretMaskerFilter(logging.Filter):
    """
    A logging filter that intercepts log messages and redacts sensitive strings.
    """
    def __init__(self, secrets_to_mask: Optional[List[str]] = None):
        super().__init__()
        self.secrets = set()
        if secrets_to_mask:
            for s in secrets_to_mask:
                if s and isinstance(s, str) and len(s) > 3:
                    self.secrets.add(s)

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str) and self.secrets:
            msg = record.msg
            for secret in self.secrets:
                msg = msg.replace(secret, "[REDACTED]")
            record.msg = msg
        return True


def setup_logger(
    log_name: Optional[str] = None,
    log_dir: str = "logs",
    secrets_to_mask: Optional[List[str]] = None
) -> Tuple[logging.Logger, Path]:
    """
    Configures a root/named logger with both File and Console handlers.
    Applies secret masking if secrets are provided.
    
    :param log_name: Name of the log file, defaults to datetime stamp if None.
    :param log_dir: Target directory for storing log files.
    :param secrets_to_mask: List of strings (passwords, tokens) to redact.
    :return: A tuple of (Logger instance, Path to log file).
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Avoid duplicate handlers if already configured
    if not root_logger.handlers:
        target_dir = Path(log_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        
        if not log_name:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            log_name = f"run_{timestamp}.log"
            
        log_file = target_dir / log_name
        
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        
        # File handler
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        
        # Console handler
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        
        # Apply Secret Masking Filter
        masker = SecretMaskerFilter(secrets_to_mask)
        file_handler.addFilter(masker)
        stream_handler.addFilter(masker)
        
        root_logger.addHandler(file_handler)
        root_logger.addHandler(stream_handler)
        
        return root_logger, log_file
    else:
        # Return existing logger and locate the first FileHandler's file path if possible
        log_file = Path(log_dir)
        for h in root_logger.handlers:
            if isinstance(h, logging.FileHandler):
                log_file = Path(h.baseFilename)
                break
        return root_logger, log_file
