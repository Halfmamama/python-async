# Модуль-заглушка Google Sheets (без секретов и зависимостей)
import logging

logger = logging.getLogger(__name__)

class GoogleSheetsSyncMock:
    @property
    def enabled(self) -> bool:
        return False

    def init_all_tabs(self, project_info) -> None:
        pass

def get_gsheets_sync() -> GoogleSheetsSyncMock:
    """Возвращает no-op заглушку клиента Google Sheets."""
    return GoogleSheetsSyncMock()

def update_gsheet_batch(gs_sync, results_batch, session_id) -> None:
    """No-op заглушка отправки результатов в Google Таблицы."""
    pass
