"""Лёгкие runtime-метрики для админской диагностики."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

@dataclass(slots=True)
class RuntimeMetrics:
    started_at: float = field(default_factory=time.time)
    temp_errors: int = 0
    unavailable: int = 0
    janitor_removed_games: int = 0
    last_cleanup_at: int = 0
    last_matchmaker_save_at: int = 0

    def uptime_seconds(self) -> int:
        return max(0, int(time.time() - self.started_at))

    @property
    def version(self) -> str:
        return (
            os.getenv("APP_VERSION")
            or os.getenv("GIT_COMMIT")
            or os.getenv("GITHUB_SHA")
            or "не указан"
        )[:12]

METRICS = RuntimeMetrics()
