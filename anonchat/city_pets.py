"""MGN Capture: pet marketplace, death and server-authoritative GPS combat.

⭐ is the bot's existing users.xp (earned from messages), NOT paid Telegram Stars.
All writes to users.xp are tagged for the app's append-only XP ledger trigger.
Coordinates are used only for a request and are never persisted.
"""
import math
import sqlite3
import time

from .city_capture import FIX_MAX_AGE_S, MAX_ACCURACY_M

CAPTURE_STARS = 50
MAX_HP_MILLI = 100_000
MIN_HP_MILLI = 0
REGEN_HP_H = 8
CLAIM_MAX_SECONDS = 24 * 3600
PET_TYPES = {
    "cat":   {"name": "Кот",    "emoji": "🐈", "price": 100,  "stars_h": 1,  "hp_5m": 0.5},
    "bird":  {"name": "Птица",  "emoji": "🐤", "price": 500,  "stars_h": 3,  "hp_5m": 1},
    "pig":   {"name": "Свинка", "emoji": "🐷", "price": 1000, "stars_h": 6,  "hp_5m": 1.5},
    "snake": {"name": "Змея",   "emoji": "🐍", "price": 2500, "stars_h": 10, "hp_5m": 2.5},
    "lion":  {"name": "Лев",    "emoji": "🦁", "price": 5000, "stars_h": 18, "hp_5m": 4},
}


def catalog():
    return [{"kind": kind, **props} for kind, props in PET_TYPES.items()]


def init_db(db):
    # Run before BEGIN IMMEDIATE: SQLite executescript may commit open transactions.
    db.executescript("""
    CREATE TABLE IF NOT EXISTS city_pets (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      owner_id INTEGER NOT NULL,
      kind TEXT NOT NULL,
      zone_id INTEGER,
      purchased_at INTEGER NOT NULL,
      assigned_at INTEGER NOT NULL DEFAULT 0,
      income_tick_at INTEGER NOT NULL DEFAULT 0,
      income_fraction INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_city_pets_owner ON city_pets(owner_id);
    CREATE INDEX IF NOT EXISTS idx_city_pets_zone ON city_pets(zone_id);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_city_one_pet_per_zone
      ON city_pets(zone_id) WHERE zone_id IS NOT NULL;
    CREATE TABLE IF NOT EXISTS city_pet_orders (
      owner_id INTEGER NOT NULL,
      request_id TEXT NOT NULL,
      pet_id INTEGER NOT NULL,
      PRIMARY KEY(owner_id,request_id)
    );
    CREATE TABLE IF NOT EXISTS city_player_hp (
      user_id INTEGER PRIMARY KEY,
      hp_milli INTEGER NOT NULL DEFAULT 100000,
      last_tick INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS city_player_deaths (
      user_id INTEGER PRIMARY KEY,
      deaths INTEGER NOT NULL DEFAULT 0,
      died_at INTEGER NOT NULL DEFAULT 0,
      zones_lost INTEGER NOT NULL DEFAULT 0
    );
    """)


def _change_xp(db, user_id, amount, source, reason, ref_id):
    if not isinstance(amount, int) or abs(amount) > 100_000:
        raise ValueError("Некорректное количество звёзд")
    cursor = db.execute(
        """UPDATE users SET xp=xp+?, xp_source=?, xp_reason=?,
                  xp_reference_type='city_game', xp_reference_id=?
           WHERE user_id=? AND xp+?>=0""",
        (amount, source, reason, str(ref_id), user_id, amount),
    )
    if cursor.rowcount != 1:
        raise ValueError("Недостаточно звёзд ⭐")
    return db.execute("SELECT xp FROM users WHERE user_id=?", (user_id,)).fetchone()[0]


def on_capture(db, user_id, zone_id, timestamp):
    """Called WITHIN the same transaction as capture() ownership change."""
    db.execute(
        """UPDATE city_pets SET zone_id=NULL, assigned_at=0,
                  income_tick_at=0, income_fraction=0
           WHERE zone_id=? AND owner_id<>?""",
        (zone_id, user_id),
    )
    _change_xp(db, user_id, CAPTURE_STARS, "city_capture",
               "Захват игровой территории", zone_id)


def _begin(db):
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("BEGIN IMMEDIATE")


def _owner_has_zone(db, owner_id, zone_id):
    return db.execute(
        """SELECT 1 FROM city_ownership o JOIN city_zones z ON z.id=o.zone_id
           WHERE o.zone_id=? AND o.user_id=? AND z.enabled=1""",
        (zone_id, owner_id),
    ).fetchone() is not None


def buy(db, user_id, kind, now=None, request_id=""):
    if kind not in PET_TYPES:
        raise ValueError("Такого питомца нет")
    now = int(time.time() if now is None else now)
    request_id = str(request_id or "").strip()
    if request_id and (len(request_id) > 80 or not all(c.isalnum() or c in "-_" for c in request_id)):
        raise ValueError("Неверный ключ покупки")
    _begin(db)
    try:
        if request_id:
            old = db.execute(
                "SELECT pet_id FROM city_pet_orders WHERE owner_id=? AND request_id=?",
                (user_id, request_id),
            ).fetchone()
            if old:
                balance = db.execute("SELECT xp FROM users WHERE user_id=?", (user_id,)).fetchone()[0]
                db.commit()
                return {"pet_id": old[0], "balance": balance, "replayed": True}
        price = PET_TYPES[kind]["price"]
        balance = _change_xp(db, user_id, -price, "city_pet_purchase",
                             "Покупка питомца " + PET_TYPES[kind]["name"], kind)
        cursor = db.execute(
            """INSERT INTO city_pets(owner_id, kind, purchased_at)
               VALUES(?,?,?)""", (user_id, kind, now))
        if request_id:
            db.execute(
                "INSERT INTO city_pet_orders(owner_id,request_id,pet_id) VALUES(?,?,?)",
                (user_id, request_id, cursor.lastrowid),
            )
        db.commit()
        return {"pet_id": cursor.lastrowid, "balance": balance}
    except BaseException:
        db.rollback()
        raise


def place(db, user_id, pet_id, zone_id, now=None):
    now = int(time.time() if now is None else now)
    _begin(db)
    try:
        pet = db.execute(
            "SELECT id,zone_id FROM city_pets WHERE id=? AND owner_id=?",
            (pet_id, user_id),
        ).fetchone()
        if not pet:
            raise ValueError("Питомец не найден")
        if not _owner_has_zone(db, user_id, zone_id):
            raise ValueError("Сперва захвати эту территорию")
        occupant = db.execute(
            "SELECT id FROM city_pets WHERE zone_id=? AND id<>?",
            (zone_id, pet_id),
        ).fetchone()
        if occupant:
            raise ValueError("Здесь уже есть защитник — не больше одного на район")
        if pet[1] == zone_id:
            raise ValueError("Питомец уже на этом районе")
        db.execute(
            """UPDATE city_pets SET zone_id=?, assigned_at=?,
                      income_tick_at=?, income_fraction=0 WHERE id=?""",
            (zone_id, now, now, pet_id),
        )
        db.commit()
        return {"pet_id": pet_id, "zone_id": zone_id}
    except BaseException:
        db.rollback()
        raise


def recall(db, user_id, pet_id):
    _begin(db)
    try:
        result = db.execute(
            """UPDATE city_pets SET zone_id=NULL, assigned_at=0,
                      income_tick_at=0, income_fraction=0
               WHERE id=? AND owner_id=? AND zone_id IS NOT NULL""",
            (pet_id, user_id),
        )
        if result.rowcount != 1:
            raise ValueError("Питомец не установлен")
        db.commit()
        return {"pet_id": pet_id}
    except BaseException:
        db.rollback()
        raise


def pending_income(pet, now):
    """pet: (id, kind, zone_id, assigned_at, income_tick_at, fraction, is_owned)."""
    _id, kind, zone_id, _assigned, tick, fraction, owned = pet
    if zone_id is None or not owned or kind not in PET_TYPES:
        return 0, 0
    seconds = min(CLAIM_MAX_SECONDS, max(0, now - tick))
    total = seconds * PET_TYPES[kind]["stars_h"] + fraction
    return total // 3600, total % 3600


def _owned_pets(db, owner_id):
    return db.execute(
        """SELECT p.id,p.kind,p.zone_id,p.assigned_at,p.income_tick_at,
                  p.income_fraction,
                  (o.user_id=p.owner_id AND z.enabled=1) AS owned
           FROM city_pets p
           LEFT JOIN city_ownership o ON o.zone_id=p.zone_id
           LEFT JOIN city_zones z ON z.id=p.zone_id
           WHERE p.owner_id=? ORDER BY p.id""", (owner_id,),
    ).fetchall()


def claim(db, user_id, now=None):
    now = int(time.time() if now is None else now)
    _begin(db)
    try:
        earned = 0
        for pet in _owned_pets(db, user_id):
            if pet[2] is None or not pet[6]:
                continue
            stars, fraction = pending_income(pet, now)
            earned += stars
            db.execute(
                "UPDATE city_pets SET income_tick_at=?,income_fraction=? WHERE id=?",
                (now, fraction, pet[0]),
            )
        if earned:
            balance = _change_xp(db, user_id, earned, "city_pet_income",
                                 "Доход питомцев за защиту территорий", now)
        else:
            balance_row = db.execute("SELECT xp FROM users WHERE user_id=?", (user_id,)).fetchone()
            balance = balance_row[0] if balance_row else 0
        db.commit()
        return {"stars": earned, "balance": balance}
    except BaseException:
        db.rollback()
        raise


def state(db, user_id, now=None):
    now = int(time.time() if now is None else now)
    row = db.execute("SELECT xp FROM users WHERE user_id=?", (user_id,)).fetchone()
    hp = db.execute("SELECT hp_milli FROM city_player_hp WHERE user_id=?", (user_id,)).fetchone()
    death = db.execute(
        "SELECT deaths,died_at,zones_lost FROM city_player_deaths WHERE user_id=?",
        (user_id,),
    ).fetchone()
    pets = _owned_pets(db, user_id)
    pending = sum(pending_income(p, now)[0] for p in pets)
    return {
        "wallet": max(0, row[0]) if row else 0,
        "hp": round((hp[0] if hp else MAX_HP_MILLI) / 1000, 2),
        "max_hp": 100,
        "dead": bool(hp and hp[0] <= 0),
        "deaths": int(death[0]) if death else 0,
        "last_death_at": int(death[1]) if death else 0,
        "zones_lost": int(death[2]) if death else 0,
        "capture_stars": CAPTURE_STARS,
        "pending_stars": pending,
        "catalog": catalog(),
        "my_pets": [
            {"id": p[0], "kind": p[1], "zone_id": p[2], "active": bool(p[6]),
             "pending_stars": pending_income(p, now)[0]}
            for p in pets
        ],
        "guards": [
            {"zone_id": z[0], "kind": z[1], "mine": z[2] == user_id}
            for z in db.execute(
                """SELECT p.zone_id,p.kind,p.owner_id FROM city_pets p
                   JOIN city_ownership o ON p.zone_id=o.zone_id AND p.owner_id=o.user_id
                   JOIN city_zones z ON z.id=p.zone_id AND z.enabled=1
                   WHERE p.zone_id IS NOT NULL"""
            ).fetchall()
        ],
    }


def _contains(polygon, latitude, longitude):
    inside = False
    for i in range(len(polygon)):
        a = polygon[i]
        b = polygon[i - 1]
        if (a[0] > latitude) != (b[0] > latitude):
            x = (b[1] - a[1]) * (latitude - a[0]) / (b[0] - a[0]) + a[1]
            if longitude < x:
                inside = not inside
    return inside


def _boundary_distance_m(polygon, lat, lon):
    """Shortest distance to real road-block edge; uses a local metre projection."""
    scale = math.cos(math.radians(lat))
    x, y = lon * 111320 * scale, lat * 111320
    best = float("inf")
    for i in range(len(polygon)):
        p, q = polygon[i - 1], polygon[i]
        ax, ay = p[1] * 111320 * scale, p[0] * 111320
        bx, by = q[1] * 111320 * scale, q[0] * 111320
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        t = max(0, min(1, ((x-ax)*dx + (y-ay)*dy) / length)) if length else 0
        best = min(best, math.hypot(x - ax - t*dx, y - ay - t*dy))
    return best


def presence(db, user_id, lat, lon, accuracy_m, timestamp_s, polygons, now=None):
    """Applies HP only inside real OSM road cells. No coordinate history stored.

    No damage on first location report. Delayed requests cannot stack hours of
    damage; each request processes at most 60 seconds of server elapsed time.
    On reaching zero HP, ownership and defenders are released atomically.
    A dead player must explicitly respawn; repeated GPS reports cannot kill twice.
    """
    # Check fractional GPS timestamps against fractional server time.
    # Comparing them to int(time.time()) rejected valid fixes in the
    # same second (e.g. timestamp 12:00:00.800 > server 12:00:00).
    now_wall = float(time.time() if now is None else now)
    now = int(now_wall)
    vals = (lat, lon, accuracy_m, timestamp_s)
    if not all(isinstance(v, (float, int)) and math.isfinite(v) for v in vals):
        raise ValueError("Неверные координаты")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or not (0 <= accuracy_m <= MAX_ACCURACY_M):
        raise ValueError("Низкая точность GPS")
    if not (-2 <= now_wall - timestamp_s <= FIX_MAX_AGE_S):
        raise ValueError("Устаревшее положение")
    _begin(db)
    try:
        previous = db.execute(
            "SELECT hp_milli,last_tick FROM city_player_hp WHERE user_id=?", (user_id,)
        ).fetchone()
        hp = previous[0] if previous else MAX_HP_MILLI
        elapsed = max(0, min(60, now - previous[1])) if previous else 0
        if hp <= 0:
            details = db.execute(
                "SELECT deaths,zones_lost FROM city_player_deaths WHERE user_id=?",
                (user_id,),
            ).fetchone()
            db.commit()
            return {"hp": 0, "max_hp": 100, "dead": True, "died": False,
                    "deaths": details[0] if details else 0,
                    "zones_lost": details[1] if details else 0,
                    "zone_id": None, "attacked_by": None}
        hit_kind = None
        hit_zone = None
        # Protect user with accuracy: entire GPS uncertainty must fit the road cell.
        # On unreliable fixes, don't apply damage. No guard = healing only.
        if accuracy_m <= 35:
            for zone_id, kind, owner_id in db.execute(
                """SELECT p.zone_id,p.kind,p.owner_id FROM city_pets p
                   JOIN city_ownership o ON o.zone_id=p.zone_id AND o.user_id=p.owner_id
                   JOIN city_zones z ON z.id=p.zone_id AND z.enabled=1
                   WHERE p.zone_id IS NOT NULL AND p.owner_id<>?""",
                (user_id,),
            ).fetchall():
                shape = polygons.get(str(zone_id))
                if not shape or len(shape) < 3 or not _contains(shape, lat, lon):
                    continue
                if _boundary_distance_m(shape, lat, lon) < accuracy_m + 2:
                    continue
                hit_kind, hit_zone = kind, zone_id
                break
        if hit_kind in PET_TYPES:
            # Damage numbers are HP lost per 5 MINUTES, not per hour.
            # Real server elapsed time; no offline damage spikes.
            damage = int(elapsed * PET_TYPES[hit_kind]["hp_5m"] * 1000 / 300)
            hp = max(MIN_HP_MILLI, hp - damage)
        else:
            hp = min(MAX_HP_MILLI, hp + int(elapsed * REGEN_HP_H * 1000 / 3600))
        died = hp <= 0
        lost_zones = 0
        if died:
            # This runs under the SAME IMMEDIATE SQLite transaction as HP=0.
            # Other players will see all former zones free after this commit.
            lost_zones = db.execute(
                "SELECT COUNT(*) FROM city_ownership WHERE user_id=?",
                (user_id,),
            ).fetchone()[0]
            db.execute("DELETE FROM city_ownership WHERE user_id=?", (user_id,))
            # Pets are not destroyed or sold: they return to the inventory.
            # No abandoned guards can hurt players or generate star income.
            db.execute(
                """UPDATE city_pets SET zone_id=NULL,assigned_at=0,
                          income_tick_at=0,income_fraction=0
                   WHERE owner_id=? AND zone_id IS NOT NULL""",
                (user_id,),
            )
            db.execute(
                """INSERT INTO city_player_deaths(user_id,deaths,died_at,zones_lost)
                   VALUES(?,1,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     deaths=deaths+1,died_at=excluded.died_at,
                     zones_lost=excluded.zones_lost""",
                (user_id, now, lost_zones),
            )
        db.execute(
            """INSERT INTO city_player_hp(user_id,hp_milli,last_tick) VALUES(?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET hp_milli=excluded.hp_milli,
               last_tick=excluded.last_tick""",
            (user_id, hp, now),
        )
        deaths = db.execute(
            "SELECT deaths FROM city_player_deaths WHERE user_id=?",
            (user_id,),
        ).fetchone()
        db.commit()
        return {"hp": round(hp / 1000, 2), "max_hp": 100,
                "dead": died, "died": died, "deaths": deaths[0] if deaths else 0,
                "zones_lost": lost_zones, "zone_id": hit_zone,
                "attacked_by": hit_kind, "safe": not died}
    except BaseException:
        db.rollback()
        raise


def respawn(db, user_id, now=None):
    """Explicit respawn after death. Health resets; lost zones stay free."""
    now = int(time.time() if now is None else now)
    _begin(db)
    try:
        old = db.execute(
            "SELECT hp_milli FROM city_player_hp WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if old is None or old[0] > 0:
            raise ValueError("Возрождение доступно только после гибели")
        db.execute(
            "UPDATE city_player_hp SET hp_milli=?,last_tick=? WHERE user_id=?",
            (MAX_HP_MILLI, now, user_id),
        )
        info = db.execute(
            "SELECT deaths,zones_lost FROM city_player_deaths WHERE user_id=?",
            (user_id,),
        ).fetchone()
        db.commit()
        return {"hp": 100, "max_hp": 100, "dead": False,
                "deaths": info[0] if info else 0,
                "zones_lost": info[1] if info else 0}
    except BaseException:
        db.rollback()
        raise
