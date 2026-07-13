from dataclasses import dataclass, field
from typing import Any, Dict, Optional

@dataclass
class TaskResult:
    """
    A generic carrier class for tasks or network requests execution results.
    """
    name: str
    ok: bool = False
    error: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        """
        Serializes the result instance into a dictionary format.
        """
        res = {
            "name": self.name,
            "ok": self.ok,
            "error": self.error,
        }
        res.update(self.data)
        return res
