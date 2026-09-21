"""Правила игры «Числа»."""

NUMBER_ROUNDS = 3
NUMBER_REWARDS: dict[int, int] = {
    10: 25,
    100: 50,
    1000: 100,
}


def number_reward(range_max: int, first: int, second: int) -> int:
    """Награда каждому игроку за один раунд."""
    base = NUMBER_REWARDS.get(int(range_max), 0)
    if base <= 0:
        return 0
    diff = abs(int(first) - int(second))
    if diff == 0:
        return base
    if diff == 1:
        return base // 2
    return 0
