"""MGN ZAHVAT: isolated GPS-gated territory capture engine."""
import math
import sqlite3
import time

RADIUS_M = 100
MAX_ACCURACY_M = 75
FIX_MAX_AGE_S = 30
COOLDOWN_S = 1800

def distance_m(a, b, c, d):
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = p2-p1, math.radians(d-b)
    h = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 12742000 * math.asin(min(1, math.sqrt(h)))

def init_db(db: sqlite3.Connection):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS city_zones(
      id INTEGER PRIMARY KEY, name TEXT NOT NULL,
      lat REAL NOT NULL, lon REAL NOT NULL, enabled INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS city_ownership(
      zone_id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, captured_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS city_capture_events(
      id INTEGER PRIMARY KEY, zone_id INTEGER NOT NULL,
      user_id INTEGER NOT NULL, captured_at INTEGER NOT NULL);
    CREATE INDEX IF NOT EXISTS city_events_user_time
      ON city_capture_events(user_id,captured_at);
    """)

def capture(db, user_id, zone_id, lat, lon, accuracy_m, fix_timestamp, now=None):
    """Caller must authenticate user_id from Telegram initData. GPS can be spoofed."""
    now = time.time() if now is None else now
    vals = (lat, lon, accuracy_m, fix_timestamp)
    if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in vals):
        raise ValueError("Invalid location")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Invalid coordinates")
    if not (0 <= accuracy_m <= MAX_ACCURACY_M):
        raise ValueError("Location accuracy insufficient")
    if not (0 <= now-fix_timestamp <= FIX_MAX_AGE_S):
        raise ValueError("Stale location")
    if not isinstance(user_id,int) or user_id <= 0:
        raise ValueError("Invalid user")
    db.execute("BEGIN IMMEDIATE")
    try:
        zone = db.execute(
          "SELECT name,lat,lon FROM city_zones WHERE id=? AND enabled=1",
          (zone_id,)).fetchone()
        if not zone:
            raise ValueError("Zone unavailable")
        # Dead players cannot capture zones by calling the endpoint directly.
        # In production city_pets.init_db() is run before a capture transaction.
        hp_table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='city_player_hp'"
        ).fetchone()
        if hp_table:
            health = db.execute(
                "SELECT hp_milli FROM city_player_hp WHERE user_id=?", (user_id,)
            ).fetchone()
            if health is not None and health[0] <= 0:
                raise ValueError("Сначала возродись, затем захватывай территории")
        if distance_m(lat,lon,zone[1],zone[2])+accuracy_m > RADIUS_M:
            raise ValueError("Outside capture radius")
        last = db.execute(
          "SELECT MAX(captured_at) FROM city_capture_events WHERE user_id=?",
          (user_id,)).fetchone()[0]
        if last is not None and now-last < COOLDOWN_S:
            raise ValueError("Capture cooldown")
        owner = db.execute(
          "SELECT user_id FROM city_ownership WHERE zone_id=?",
          (zone_id,)).fetchone()
        if owner and owner[0] == user_id:
            raise ValueError("Already owned")
        db.execute(
          "INSERT INTO city_ownership VALUES(?,?,?) ON CONFLICT(zone_id) DO UPDATE SET "
          "user_id=excluded.user_id,captured_at=excluded.captured_at",
          (zone_id,user_id,int(now)))
        db.execute(
          "INSERT INTO city_capture_events(zone_id,user_id,captured_at) VALUES(?,?,?)",
          (zone_id,user_id,int(now)))
        # Atomic with ownership: reward existing ⭐/XP balance and remove
        # an old owner's guard. If reward fails, capture itself rolls back.
        from .city_pets import on_capture
        on_capture(db, user_id, zone_id, int(now))
        db.commit()
        return {"zone_id":zone_id,"name":zone[0],"owner_user_id":user_id}
    except BaseException:
        db.rollback()
        raise
