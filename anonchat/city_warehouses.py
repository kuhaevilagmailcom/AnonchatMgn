"""РАЙОНЫ — player warehouses, invitations and shared achievements."""
import re
import sqlite3
import time
from .city_progression import stats

CAPACITY = 10
INVITE_TTL = 2*86400
COOLDOWN = 90

def init_db(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS city_warehouses(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      owner_id INTEGER NOT NULL UNIQUE,
      name TEXT NOT NULL,
      emoji TEXT NOT NULL DEFAULT '📦',
      description TEXT NOT NULL DEFAULT '',
      created_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS city_warehouse_members(
      user_id INTEGER PRIMARY KEY, warehouse_id INTEGER NOT NULL,
      role TEXT NOT NULL DEFAULT 'member', joined_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_city_warehouse_members ON city_warehouse_members(warehouse_id);
    CREATE TABLE IF NOT EXISTS city_warehouse_invites(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      warehouse_id INTEGER NOT NULL, inviter_id INTEGER NOT NULL,
      invitee_id INTEGER NOT NULL, created_at INTEGER NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending'
    );
    CREATE INDEX IF NOT EXISTS idx_city_invitee ON city_warehouse_invites(invitee_id, status);
    CREATE TABLE IF NOT EXISTS city_warehouse_mission_claims (
      warehouse_id INTEGER NOT NULL,
      user_id INTEGER NOT NULL,
      day INTEGER NOT NULL,
      tier INTEGER NOT NULL,
      claimed_at INTEGER NOT NULL,
      PRIMARY KEY(warehouse_id,user_id,day,tier)
    );
    """)

def _begin(db):
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("BEGIN IMMEDIATE")

def my_warehouse(db,uid):
    row=db.execute("""SELECT w.id,w.owner_id,w.name,w.emoji,w.description,w.created_at
      FROM city_warehouses w JOIN city_warehouse_members m ON m.warehouse_id=w.id
      WHERE m.user_id=?""",(uid,)).fetchone()
    if row is None:
        return {"warehouse":None,"invitations":invitations(db,uid)}
    members=db.execute("""SELECT m.user_id,u.nickname,m.role,COUNT(o.zone_id)
      FROM city_warehouse_members m LEFT JOIN users u ON u.user_id=m.user_id
      LEFT JOIN city_ownership o ON o.user_id=m.user_id
      WHERE m.warehouse_id=? GROUP BY m.user_id
      ORDER BY CASE WHEN m.role='owner' THEN 0 ELSE 1 END,u.nickname""",(row[0],)).fetchall()
    total=sum(m[3] for m in members)
    return {"warehouse":{
      "id":row[0],"owner_id":row[1],"mine":row[1]==uid,
      "name":row[2],"emoji":row[3],"description":row[4],
      "members":[{"id":m[0],"nickname":m[1] or "Аноним","role":m[2],
                  "zones":m[3]} for m in members],
      "zones":total,"level":1+total//10,
      "income_h":round(sum(
        stats(pet[0],pet[1])["stars_h"]
        for pet in db.execute(
           """SELECT p.kind,p.level FROM city_pets p
              JOIN city_warehouse_members m ON m.user_id=p.owner_id
              JOIN city_ownership o ON o.zone_id=p.zone_id AND o.user_id=p.owner_id
              WHERE m.warehouse_id=?""",(row[0],))
      ),2),
      "missions":missions(db,uid,row[0]),
      "achievements":[
        {"name":"Первая территория","done":total>=1},
        {"name":"Десять районов","done":total>=10},
        {"name":"Полный склад","done":len(members)>=CAPACITY}
      ]
    },"invitations":invitations(db,uid)}

def invitations(db,uid,now=None):
    now=int(time.time() if now is None else now)
    return [{"id":r[0],"warehouse":r[1],"emoji":r[2],"inviter":r[3],
             "expires_at":r[4]+INVITE_TTL}
      for r in db.execute("""SELECT i.id,w.name,w.emoji,COALESCE(u.nickname,'Аноним'),
                                  i.created_at
       FROM city_warehouse_invites i
       JOIN city_warehouses w ON w.id=i.warehouse_id
       LEFT JOIN users u ON u.user_id=i.inviter_id
       WHERE i.invitee_id=? AND i.status='pending' AND i.created_at>?
       ORDER BY i.id DESC LIMIT 15""",(uid,now-INVITE_TTL))]

def create(db,uid,name,emoji="📦",description="",now=None):
    now=int(time.time() if now is None else now)
    name=str(name).strip();description=str(description).strip()
    if not 3<=len(name)<=28 or not re.fullmatch(r"[\w\s\-«»№.]+",name,re.UNICODE):
        raise ValueError("Название: 3–28 символов, без ссылок и HTML")
    if len(description)>140: raise ValueError("Описание слишком длинное")
    if emoji not in ("📦","🏚️","🏠","🏭","🛡️","🏴","👑","⚡"):
        raise ValueError("Выбери эмодзи склада")
    _begin(db)
    try:
        if db.execute("SELECT 1 FROM city_warehouse_members WHERE user_id=?",(uid,)).fetchone():
            raise ValueError("Ты уже на складе")
        cur=db.execute("INSERT INTO city_warehouses(owner_id,name,emoji,description,created_at) VALUES(?,?,?,?,?)",
                       (uid,name,emoji,description,now))
        db.execute("INSERT INTO city_warehouse_members(user_id,warehouse_id,role,joined_at) VALUES(?,?,'owner',?)",
                   (uid,cur.lastrowid,now))
        db.commit();return {"warehouse_id":cur.lastrowid}
    except BaseException:db.rollback();raise

def invite(db,uid,nickname,now=None):
    now=int(time.time() if now is None else now)
    nickname=str(nickname).strip().lstrip("@")
    if not 2<=len(nickname)<=40:raise ValueError("Неверный ник")
    _begin(db)
    try:
        row=db.execute("""SELECT w.id,w.name,w.emoji FROM city_warehouses w
             JOIN city_warehouse_members m ON m.warehouse_id=w.id
             WHERE m.user_id=? AND m.role IN ('owner','moderator')""",(uid,)).fetchone()
        if row is None:raise ValueError("Приглашать может владелец склада")
        # nick_key is created with Python .casefold(), unlike SQLite LOWER
        # which cannot compare Cyrillic uppercase and lowercase reliably.
        target=db.execute("""SELECT user_id,COALESCE(nickname,'') FROM users
              WHERE nick_key=? OR lower(username)=?""",
              (nickname.casefold(),nickname.lower())).fetchone()
        if not target:raise ValueError("Пользователь с таким ником не найден")
        if target[0]==uid:raise ValueError("Нельзя пригласить себя")
        if db.execute("SELECT 1 FROM city_warehouse_members WHERE user_id=?",(target[0],)).fetchone():
            raise ValueError("Игрок уже состоит на складе")
        if db.execute("SELECT COUNT(*) FROM city_warehouse_members WHERE warehouse_id=?",(row[0],)).fetchone()[0]>=CAPACITY:
            raise ValueError("Склад заполнен")
        recent=db.execute("""SELECT MAX(created_at) FROM city_warehouse_invites
               WHERE inviter_id=? AND invitee_id=?""",(uid,target[0])).fetchone()[0]
        if recent and now-recent<COOLDOWN:raise ValueError("Подожди перед следующим приглашением")
        cur=db.execute("INSERT INTO city_warehouse_invites(warehouse_id,inviter_id,invitee_id,created_at) VALUES(?,?,?,?)",
                       (row[0],uid,target[0],now))
        db.commit()
        return {"id":cur.lastrowid,"recipient_id":target[0],"warehouse":row[1],
                "emoji":row[2]}
    except BaseException:db.rollback();raise

def respond(db,uid,invite_id,accept,now=None):
    now=int(time.time() if now is None else now)
    _begin(db)
    try:
        row=db.execute("""SELECT warehouse_id,created_at,status FROM city_warehouse_invites
                         WHERE id=? AND invitee_id=?""",(invite_id,uid)).fetchone()
        if not row or row[2]!="pending":raise ValueError("Приглашение недоступно")
        if now-row[1]>INVITE_TTL:raise ValueError("Приглашение истекло")
        if accept:
            if db.execute("SELECT 1 FROM city_warehouse_members WHERE user_id=?",(uid,)).fetchone():
                raise ValueError("Ты уже на складе")
            if db.execute("SELECT COUNT(*) FROM city_warehouse_members WHERE warehouse_id=?",(row[0],)).fetchone()[0]>=CAPACITY:
                raise ValueError("Склад заполнен")
            db.execute("INSERT INTO city_warehouse_members(user_id,warehouse_id,role,joined_at) VALUES(?,?,'member',?)",
                       (uid,row[0],now))
        db.execute("UPDATE city_warehouse_invites SET status=? WHERE id=?",
                   ("accepted" if accept else "declined",invite_id))
        db.commit();return {"accepted":bool(accept),"warehouse_id":row[0]}
    except BaseException:db.rollback();raise

def leave(db,uid):
    _begin(db)
    try:
        row=db.execute("SELECT warehouse_id,role FROM city_warehouse_members WHERE user_id=?",(uid,)).fetchone()
        if not row:raise ValueError("Ты не на складе")
        if row[1]=="owner":raise ValueError("Владелец должен удалить склад или передать управление")
        db.execute("DELETE FROM city_warehouse_members WHERE user_id=?",(uid,))
        db.commit()
        return {"left":True}
    except BaseException:db.rollback();raise

def kick(db,uid,target_id):
    _begin(db)
    try:
        row=db.execute("SELECT warehouse_id FROM city_warehouse_members WHERE user_id=? AND role='owner'",(uid,)).fetchone()
        if not row:raise ValueError("Только владелец может исключать")
        res=db.execute("DELETE FROM city_warehouse_members WHERE warehouse_id=? AND user_id=? AND role<>'owner'",
                       (row[0],target_id))
        if res.rowcount!=1:raise ValueError("Участник не найден")
        db.commit();return {"removed":True}
    except BaseException:db.rollback();raise

def disband(db,uid,confirm):
    if confirm!="УДАЛИТЬ СКЛАД":raise ValueError("Нужно явное подтверждение удаления")
    _begin(db)
    try:
        row=db.execute("SELECT id FROM city_warehouses WHERE owner_id=?",(uid,)).fetchone()
        if not row:raise ValueError("Ты не владелец склада")
        db.execute("DELETE FROM city_warehouse_invites WHERE warehouse_id=?",(row[0],))
        db.execute("DELETE FROM city_warehouse_members WHERE warehouse_id=?",(row[0],))
        db.execute("DELETE FROM city_warehouses WHERE id=?",(row[0],))
        db.commit();return {"deleted":True}
    except BaseException:db.rollback();raise


MISSION_REWARDS = ((3,25),(10,100))

def missions(db,uid,warehouse_id,now=None):
    now=int(time.time() if now is None else now)
    day=now//86400
    captures=db.execute("""SELECT COUNT(*) FROM city_capture_events c
       JOIN city_warehouse_members m ON m.user_id=c.user_id
       WHERE m.warehouse_id=? AND c.captured_at>=? AND c.captured_at<?""",
       (warehouse_id,day*86400,(day+1)*86400)).fetchone()[0]
    claimed={r[0] for r in db.execute("""SELECT tier FROM city_warehouse_mission_claims
       WHERE warehouse_id=? AND user_id=? AND day=?""",(warehouse_id,uid,day))}
    return [
        {"tier":tier,"label":f"Захватить {tier} районов за день",
         "progress":min(captures,tier),"target":tier,"reward":amount,
         "claimed":tier in claimed,"claimable":captures>=tier and tier not in claimed}
        for tier,amount in MISSION_REWARDS
    ]

def claim_mission(db,uid,tier,now=None):
    """Shared capture progress; each warehouse member claims once per UTC day."""
    from .city_pets import _change_xp
    now=int(time.time() if now is None else now)
    _begin(db)
    try:
        found=db.execute(
          "SELECT warehouse_id FROM city_warehouse_members WHERE user_id=?",(uid,)
        ).fetchone()
        if not found:raise ValueError("Ты не состоишь на складе")
        wh_id=found[0]
        quest=next((q for q in missions(db,uid,wh_id,now) if q["tier"]==tier),None)
        if not quest or not quest["claimable"]:
            raise ValueError("Задание ещё не выполнено или награда уже получена")
        db.execute("""INSERT INTO city_warehouse_mission_claims(
           warehouse_id,user_id,day,tier,claimed_at) VALUES(?,?,?,?,?)""",
           (wh_id,uid,now//86400,tier,now))
        balance=_change_xp(db,uid,quest["reward"],"city_warehouse_mission",
                           "Совместное задание склада",f"{wh_id}:{now//86400}:{tier}")
        db.commit()
        return {"reward":quest["reward"],"balance":balance}
    except BaseException:
        db.rollback();raise
