"""Уровни общения («Прокачка собеседника») — растём от Гостя МГН до Голоса города."""

from __future__ import annotations

from dataclasses import dataclass

# (порог XP, звание)
LEVELS: tuple[tuple[int, str], ...] = (
    (0, "Гость МГН"),
    (60, "Новичок у Вокзала"),
    (140, "Собеседник с Зелёного Лога"),
    (260, "Гуляка по набережной"),
    (420, "Житель Левобережки"),
    (620, "Собеседник с ГЗ"),
    (880, "Магнитогорец со стажем"),
    (1200, "Металл души"),
    (1600, "Сплав доверия"),
    (2100, "Искра Пролетарки"),
    (2700, "Легенда Анончата"),
    (3500, "Голос МГН"),
)


@dataclass(slots=True)
class LevelInfo:
    level: int
    title: str
    xp: int
    next_xp: int | None
    next_title: str | None
    progress: float  # 0..1 внутри текущего уровня

    @property
    def bar(self, width: int = 10) -> str:
        filled = max(0, min(width, round(self.progress * width)))
        return "▓" * filled + "░" * (width - filled)

    @property
    def to_next(self) -> int | None:
        if self.next_xp is None:
            return None
        return max(0, self.next_xp - self.xp)


def level_for(xp: int) -> LevelInfo:
    xp = max(0, int(xp))
    idx = 0
    for i, (need, _) in enumerate(LEVELS):
        if xp >= need:
            idx = i
        else:
            break
    cur_need, title = LEVELS[idx]
    if idx + 1 < len(LEVELS):
        nxt_need, nxt_title = LEVELS[idx + 1]
        span = max(1, nxt_need - cur_need)
        progress = (xp - cur_need) / span
        return LevelInfo(idx + 1, title, xp, nxt_need, nxt_title, min(1.0, max(0.0, progress)))
    return LevelInfo(idx + 1, title, xp, None, None, 1.0)
