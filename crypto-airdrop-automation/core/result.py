from dataclasses import dataclass, field

@dataclass
class AccountResult:
    account: str
    ok: bool = False
    points: int | None = None
    error: str | None = None
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        res = {
            "error": self.error,
        }
        if self.points is not None:
            res["points"] = self.points
        res.update(self.extra)
        return res
