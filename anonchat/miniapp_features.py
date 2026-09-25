"""Доменные helpers Mini App.

Вынесены из HTTP-слоя, чтобы miniapp_api.py не превращался в набор бизнес-правил.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .db import referral_day_start
from .engagement import ACHIEVEMENTS, progress_value, quests_for


REPORT_REASONS: dict[str, str] = {
    "spam": "Спам / реклама",
    "insult": "Оскорбления",
    "sexual": "Неподходящий контент",
    "threat": "Угрозы",
    "personal": "Личные данные",
    "other": "Другое",
}


async def quest_items(db, user_id: int) -> list[dict[str, Any]]:
    day = referral_day_start()
    activity = await db.activity_totals(user_id, 1)
    claimed = await db.daily_quest_claimed(user_id, day)
    items: list[dict[str, Any]] = []
    for quest in quests_for(user_id, day):
        current = min(progress_value(activity, quest), quest.target)
        items.append(
            {
                "key": quest.key,
                "title": quest.title,
                "current": current,
                "target": quest.target,
                "reward": quest.reward,
                "done": current >= quest.target,
                "claimed": quest.key in claimed,
            }
        )
    return items


async def achievement_items(db, user_id: int) -> list[dict[str, Any]]:
    user = await db.get_user(user_id)
    engagement = await db.engagement_state(user_id)
    try:
        unlocked = set(json.loads(str(engagement["achievements"] or "[]")))
    except (TypeError, json.JSONDecodeError):
        unlocked = set()

    totals = {
        "dialogs": int(engagement["dialogs_total"] or 0),
        "messages": int(user["messages"] or 0) if user is not None else 0,
        "good_ratings": int(user["good_ratings"] or 0) if user is not None else 0,
        "games_total": int(engagement["games_total"] or 0),
        "battle_perfect_5": int(engagement["battle_perfect_5"] or 0),
        "battle_perfect_10": int(engagement["battle_perfect_10"] or 0),
        "number_exact_1000": int(engagement["number_exact_1000"] or 0),
        "current_streak": int(engagement["current_streak"] or 0),
    }
    return [
        {
            "key": key,
            "title": title,
            "current": min(int(totals.get(field, 0)), int(target)),
            "target": int(target),
            "reward": int(reward),
            "unlocked": key in unlocked,
        }
        for key, title, field, target, reward in ACHIEVEMENTS
    ]


async def poll_payload(db, user_id: int) -> dict[str, Any] | None:
    poll = await db.active_poll()
    if poll is None:
        return None
    poll_id = int(poll["id"])
    selected = await db.poll_vote_for(poll_id, user_id)
    results = await db.poll_results(poll_id)
    return {
        "id": poll_id,
        "question": str(poll["question"]),
        "options": [str(poll["option_a"]), str(poll["option_b"])],
        "selected": selected,
        "total": int(results["total"]),
        "percentages": [int(results["pct_a"]), int(results["pct_b"])],
    }


def event_payload(row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "type": str(row["type"] or "system"),
        "icon": str(row["icon"] or "bell"),
        "title": str(row["title"] or ""),
        "text": str(row["text"] or ""),
        "action": str(row["action"] or ""),
        "created_at": int(row["created_at"] or 0),
        "unread": row["read_at"] is None,
    }


def dialog_result_payload(row) -> dict[str, Any] | None:
    if row is None:
        return None
    try:
        games = json.loads(str(row["games"] or "[]"))
    except (TypeError, json.JSONDecodeError):
        games = []
    return {
        "match_id": int(row["match_id"]),
        "created_at": int(row["created_at"]),
        "started_at": int(row["started_at"]),
        "duration": int(row["duration"] or 0),
        "sent": int(row["sent"] or 0),
        "received": int(row["received"] or 0),
        "earned": int(row["earned"] or 0),
        "games": games if isinstance(games, list) else [],
        "rated": bool(int(row["rated"] or 0)),
    }


def period_deadline(period: str) -> int | None:
    """Unix timestamp конца текущего UTC+5 периода для UI."""
    tz = timezone(timedelta(hours=5))
    now_dt = datetime.now(tz)
    if period == "week":
        end = (now_dt + timedelta(days=7 - now_dt.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif period == "month":
        if now_dt.month == 12:
            end = now_dt.replace(
                year=now_dt.year + 1, month=1, day=1, hour=0, minute=0,
                second=0, microsecond=0
            )
        else:
            end = now_dt.replace(
                month=now_dt.month + 1, day=1, hour=0, minute=0,
                second=0, microsecond=0
            )
    else:
        return None
    return int(end.timestamp())
