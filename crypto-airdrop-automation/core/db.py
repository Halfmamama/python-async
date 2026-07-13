# Модуль-заглушка базы данных (без секретов и зависимостей)
import logging

logger = logging.getLogger(__name__)

def init_db():
    """No-op заглушка инициализации базы данных."""
    logger.debug("Database mock initialized (no-op).")

def log_execution(account, project, scenario, status, error=None, session_id=None):
    """No-op заглушка логирования выполнения задачи в базу данных."""
    logger.debug(f"Log execution mock (no-op): acc={account}, proj={project}, status={status}")
