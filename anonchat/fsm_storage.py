"""Persistent aiogram FSM storage backed by the bot's existing SQLite database."""
from __future__ import annotations

import json
import time
from typing import Any

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey


class SQLiteFSMStorage(BaseStorage):
    """SQLite-backed FSM for interrupted administrative and user conversations.

    Owns no connection: Database.start()/close() manage the shared SQLite handle.
    """

    def __init__(self, db) -> None:
        self.db = db

    @staticmethod
    def _key(key: StorageKey) -> str:
        return json.dumps(
            [
                key.bot_id,key.chat_id,key.user_id,
                getattr(key,"thread_id",None),
                getattr(key,"business_connection_id",None),
                getattr(key,"destiny","default"),
            ],
            separators=(",",":"),
        )

    async def set_state(self, key: StorageKey, state: State | str | None = None) -> None:
        value = state.state if isinstance(state,State) else str(state) if state is not None else None
        await self.db.db.execute(
            """INSERT INTO fsm_storage(storage_key,state,data,updated_at)
               VALUES(?,?, '{}',?)
               ON CONFLICT(storage_key) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at""",
            (self._key(key),value,int(time.time())),
        )

    async def get_state(self, key: StorageKey) -> str | None:
        row = await self.db._fetchone(
            "SELECT state FROM fsm_storage WHERE storage_key=?",(self._key(key),)
        )
        return str(row["state"]) if row and row["state"] is not None else None

    async def set_data(self, key: StorageKey, data: dict[str, Any]) -> None:
        if not isinstance(data,dict):
            raise ValueError("FSM data must be a dict")
        payload=json.dumps(data,ensure_ascii=False,separators=(",",":"))
        if len(payload)>200_000:
            raise ValueError("FSM data too large")
        await self.db.db.execute(
            """INSERT INTO fsm_storage(storage_key,state,data,updated_at)
               VALUES(?,NULL,?,?)
               ON CONFLICT(storage_key) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at""",
            (self._key(key),payload,int(time.time())),
        )

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        row=await self.db._fetchone(
            "SELECT data FROM fsm_storage WHERE storage_key=?",(self._key(key),)
        )
        try:
            data=json.loads(row["data"]) if row else {}
        except (ValueError,TypeError):
            return {}
        return dict(data) if isinstance(data,dict) else {}

    async def close(self) -> None:
        # The parent Database object closes the shared connection on shutdown.
        return None
