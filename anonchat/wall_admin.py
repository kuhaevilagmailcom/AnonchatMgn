"""Wall moderation dashboard: staff with reports permission only.

No public endpoint exposes Telegram IDs or admin audit records.
"""
from __future__ import annotations
import time
from aiohttp import web


def err(code, msg):
    from .wall import _error
    _error(code,msg)


def integer(value, low=0, high=1_000_000):
    try:
        n=int(value)
    except (ValueError,TypeError):
        err(400,"Некорректное число")
    if n<low or n>high:
        err(400,"Некорректное число")
    return n


class WallAdmin:
    def __init__(self, wall):
        self.wall=wall
        self.db=wall.db

    async def access(self, request):
        uid=await self.wall._user(request)
        if not await self.wall._admin(uid):
            err(403,"Недостаточно прав для модерации стены")
        return uid

    async def overview(self, request):
        await self.access(request)
        now=int(time.time())
        day=now-now%86400
        stats=await self.db._fetchone("""
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN created_at>=? THEN 1 ELSE 0 END) AS today,
                   SUM(CASE WHEN hidden<>0 THEN 1 ELSE 0 END) AS hidden,
                   COUNT(DISTINCT author_id) AS authors
              FROM wall_posts
        """,(day,))
        comments=await self.db._fetchone("SELECT COUNT(*) AS n FROM wall_comments")
        reports=await self.db._fetchone(
            "SELECT COUNT(*) AS n FROM wall_reports WHERE resolved_at IS NULL"
        )
        return web.json_response({"total":int(stats["total"] or 0),"today":int(stats["today"] or 0),
          "hidden":int(stats["hidden"] or 0),"authors":int(stats["authors"] or 0),
          "comments":int(comments["n"] or 0),"reports":int(reports["n"] or 0)})

    def _post_sql(self, where):
        return f"""SELECT p.id,p.author_id,p.body,p.hidden,p.created_at,p.updated_at,
                   u.nickname,u.username,u.first_name,u.support_stars,
                   (SELECT COUNT(*) FROM wall_likes l WHERE l.post_id=p.id) AS likes,
                   (SELECT COUNT(*) FROM wall_comments c WHERE c.post_id=p.id AND c.hidden=0) AS comments
                 FROM wall_posts p JOIN users u ON u.user_id=p.author_id
                 WHERE {where}"""

    def _post(self,row):
        return {
            "id":int(row["id"]),"author_id":int(row["author_id"]),
            "username":row["username"] or "", "first_name":row["first_name"] or "",
            "nick": __import__("anonchat.nick",fromlist=["display"]).display(
                row["nickname"],int(row["author_id"]),int(row["support_stars"] or 0)
            ),
            "body":row["body"],"hidden":int(row["hidden"]),
            "likes":int(row["likes"]),"comments":int(row["comments"]),
            "created_at":int(row["created_at"]), "updated_at":int(row["updated_at"]),
        }

    async def posts(self, request):
        await self.access(request)
        state=request.query.get("filter","all")
        if state not in ("all","active","hidden","reports"):
            err(400,"Неверный фильтр")
        q=request.query.get("q","").strip()[:100]
        page=integer(request.query.get("page","0"),0,100_000)
        where="1=1"
        values=[]
        if state=="active":
            where+=" AND p.hidden=0"
        elif state=="hidden":
            where+=" AND p.hidden<>0"
        elif state=="reports":
            where+=" AND EXISTS (SELECT 1 FROM wall_reports r WHERE r.resolved_at IS NULL AND ((r.target_type='post' AND r.target_id=p.id) OR (r.target_type='comment' AND r.target_id IN (SELECT id FROM wall_comments WHERE post_id=p.id))))"
        if q:
            where+=" AND (CAST(p.id AS TEXT)=? OR CAST(p.author_id AS TEXT)=? OR LOWER(COALESCE(u.username,'')) LIKE ? OR LOWER(COALESCE(u.nickname,'')) LIKE ? OR LOWER(p.body) LIKE ?)"
            values.extend([q.lstrip("#"),q.lstrip("#"),"%"+q.lower().lstrip("@")+"%","%"+q.lower()+"%","%"+q.lower()+"%"])
        rows=await self.db._fetchall(
            self._post_sql(where)+" ORDER BY p.created_at DESC,p.id DESC LIMIT 21 OFFSET ?",
            (*values,page*20),
        )
        items=[self._post(r) for r in rows[:20]]
        medias=await self.wall.media.for_posts([p["id"] for p in items])
        for p in items:
            p["media"]=medias.get(p["id"],[])
        return web.json_response({"items":items,"page":page,"has_more":len(rows)>20})

    async def post(self, request):
        await self.access(request)
        pid=integer(request.match_info["post_id"],1)
        r=await self.db._fetchone(self._post_sql("p.id=?"),(pid,))
        if not r:
            err(404,"Публикация не найдена")
        comments=await self.db._fetchall(
            """SELECT c.id,c.post_id,c.parent_id,c.author_id,c.body,c.hidden,c.created_at,
                      u.nickname,u.username,u.support_stars
                 FROM wall_comments c JOIN users u ON u.user_id=c.author_id
                 WHERE c.post_id=? ORDER BY c.created_at ASC,c.id ASC LIMIT 501""",
            (pid,),
        )
        from .nick import display
        return web.json_response({
            "post":{**self._post(r),"media":await self.wall.media.for_post(pid)},
            "comments":[{
                "id":int(c["id"]),"parent_id":c["parent_id"],"author_id":int(c["author_id"]),
                "username":c["username"] or "", "nick":display(
                    c["nickname"],int(c["author_id"]),int(c["support_stars"] or 0)
                ),
                "body":c["body"],"hidden":int(c["hidden"]),"created_at":int(c["created_at"])
            } for c in comments[:500]],
            "truncated":len(comments)>500,
        })

    async def reports(self, request):
        await self.access(request)
        rows=await self.db._fetchall(
            """SELECT r.*, reporter.username AS reporter_username,
                    CASE WHEN r.target_type='post' THEN p.author_id
                         ELSE c.author_id END AS author_id,
                    CASE WHEN r.target_type='post' THEN p.body ELSE c.body END AS body,
                    CASE WHEN r.target_type='post' THEN p.id ELSE c.post_id END AS post_id
               FROM wall_reports r LEFT JOIN users reporter ON reporter.user_id=r.reporter_id
               LEFT JOIN wall_posts p ON r.target_type='post' AND r.target_id=p.id
               LEFT JOIN wall_comments c ON r.target_type='comment' AND r.target_id=c.id
               WHERE r.resolved_at IS NULL ORDER BY r.created_at ASC,r.id ASC LIMIT 100"""
        )
        return web.json_response({"items":[{
            "id":int(r["id"]),"type":r["target_type"],"target_id":int(r["target_id"]),
            "post_id":r["post_id"],"body":r["body"] or "","author_id":r["author_id"],
            "reporter_id":int(r["reporter_id"]),"reporter_username":r["reporter_username"] or "",
            "reason":r["reason"],"created_at":int(r["created_at"]),
        } for r in rows]})

    async def action(self, request):
        uid=await self.access(request)
        data=await request.json()
        typ=data.get("type")
        action=data.get("action")
        if typ not in ("post","comment") or action not in ("hide","restore","delete","dismiss"):
            err(400,"Неизвестная операция")
        target=integer(data.get("id"),1)
        table="wall_posts" if typ=="post" else "wall_comments"
        record=await self.db._fetchone(f"SELECT id,hidden FROM {table} WHERE id=?",(target,))
        if not record:
            err(404,"Материал не найден")
        status={"hide":1,"restore":0,"delete":2}.get(action)
        if status is not None:
            await self.db.db.execute(f"UPDATE {table} SET hidden=? WHERE id=?",(status,target))
        await self.db.db.execute(
            "UPDATE wall_reports SET resolved_at=? WHERE target_type=? AND target_id=? AND resolved_at IS NULL",
            (int(time.time()),typ,target),
        )
        await self.db.db.execute(
            """INSERT INTO wall_admin_log(actor_id,target_type,target_id,action,note,created_at)
               VALUES(?,?,?,?,?,?)""",
            (uid,typ,target,action,str(data.get("note") or "")[:200],int(time.time())),
        )
        return web.json_response({"ok":True})

    async def audit(self,request):
        await self.access(request)
        page=integer(request.query.get("page","0"),0,100000)
        rows=await self.db._fetchall(
            """SELECT actor_id,target_type,target_id,action,note,created_at
               FROM wall_admin_log ORDER BY id DESC LIMIT 50 OFFSET ?""",(page*50,),
        )
        return web.json_response({"items":[dict(r) for r in rows],"page":page})


def install_wall_admin_routes(app,wall):
    admin=WallAdmin(wall)
    prefix="/api/miniapp/wall/admin"
    app.router.add_get(prefix+"/overview",admin.overview)
    app.router.add_get(prefix+"/posts",admin.posts)
    app.router.add_get(prefix+"/posts/{post_id}",admin.post)
    app.router.add_get(prefix+"/reports",admin.reports)
    app.router.add_get(prefix+"/audit",admin.audit)
    app.router.add_post(prefix+"/action",admin.action)
