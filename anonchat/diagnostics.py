"""Лёгкие runtime-метрики для админской диагностики."""
from __future__ import annotations

import os
import time
from pathlib import Path
from dataclasses import dataclass, field
from collections import deque

@dataclass(slots=True)
class RuntimeMetrics:
    started_at: float = field(default_factory=time.time)
    temp_errors: int = 0
    unavailable: int = 0
    janitor_removed_games: int = 0
    last_cleanup_at: int = 0
    last_matchmaker_save_at: int = 0
    recent_chat_relays: deque = field(default_factory=lambda: deque(maxlen=500))

    def note_chat_relay(self) -> None:
        """Small in-memory rolling sample; no per-message database queries."""
        self.recent_chat_relays.append(time.monotonic())

    def chat_relays_per_second(self) -> float:
        now_mono = time.monotonic()
        while self.recent_chat_relays and self.recent_chat_relays[0] < now_mono - 5:
            self.recent_chat_relays.popleft()
        return len(self.recent_chat_relays) / 5.0

    def uptime_seconds(self) -> int:
        return max(0, int(time.time() - self.started_at))

    @property
    def version(self) -> str:
        configured = (
            os.getenv("APP_VERSION")
            or os.getenv("GIT_COMMIT")
            or os.getenv("GITHUB_SHA")
        )
        if configured:
            return configured[:12]
        try:
            root = Path(__file__).resolve().parents[1]
            head = (root / ".git" / "HEAD").read_text(encoding="utf-8").strip()
            if head.startswith("ref: "):
                ref = root / ".git" / head[5:]
                return ref.read_text(encoding="utf-8").strip()[:12]
            if head:
                return head[:12]
        except OSError:
            pass
        return "не указан"

METRICS = RuntimeMetrics()
