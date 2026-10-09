"""Verified, rolling SQLite backups; assumes BACKUP_DIR is a persistent volume.

A separate off-host copy is still needed for disaster recovery.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import time
from pathlib import Path

log = logging.getLogger(__name__)


def _check_integrity(path: Path) -> None:
    with sqlite3.connect(f"file:{path}?mode=ro",uri=True) as con:
        result = con.execute("PRAGMA integrity_check").fetchone()
        if not result or str(result[0]).lower() != "ok":
            raise RuntimeError("SQLite backup integrity check failed")


async def maybe_backup(db, mm, *, force: bool = False) -> str | None:
    last = int(await db.get_kv("backup_last_success_at","0") or 0)
    timestamp = int(time.time())
    if not force and timestamp-last < 24*3600:
        return None
    directory = Path(os.getenv("BACKUP_DIR") or (db.path.parent/"backups"))
    directory.mkdir(parents=True,exist_ok=True)
    final = directory / f"anonmgn-{timestamp}.sqlite"
    temporary = directory / f".anonmgn-{timestamp}.partial"
    try:
        await db.flush_matchmaker(mm)
        if temporary.exists():
            temporary.unlink()
        await db.backup_to(temporary)
        await asyncio.to_thread(_check_integrity, temporary)
        os.replace(temporary,final)
        await db.set_kv("backup_last_success_at",str(timestamp))
        await db.set_kv("backup_last_error","")
        keep = max(2,min(60,int(os.getenv("BACKUP_KEEP_COUNT","7"))))
        files=sorted(directory.glob("anonmgn-*.sqlite"),key=lambda f:f.stat().st_mtime,reverse=True)
        for old in files[keep:]:
            try:
                old.unlink()
            except OSError:
                log.exception("Unable to rotate backup: %s",old.name)
        return str(final)
    except Exception as exc:
        log.exception("SQLite backup failed")
        await db.set_kv("backup_last_error",type(exc).__name__)
        raise
    finally:
        temporary.unlink(missing_ok=True)
