"""End-to-end authorization and smoke tests for Mini App administration."""
from __future__ import annotations
import asyncio
import hashlib
import hmac
import json
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

from aiohttp.test_utils import TestClient, TestServer

from anonchat.db import Database
from anonchat.matching import Matchmaker
from anonchat.miniapp_api import MiniAppServer


def signed(uid: int) -> str:
    token = "123456:ADMIN_TEST"
    params = {
        "auth_date": str(int(time.time())),
        "query_id": "miniapp-admin-tests",
        "user": json.dumps({"id":uid,"first_name":"Test","username":f"user{uid}"},
                           ensure_ascii=False,separators=(",",":")),
    }
    check = "\n".join(f"{k}={v}" for k,v in sorted(params.items()))
    secret = hmac.new(b"WebAppData",token.encode(),hashlib.sha256).digest()
    params["hash"] = hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
    return urlencode(params)


def test_admin_miniapp_endpoints() -> None:
    async def scenario():
        path=Path(tempfile.mkdtemp())/"admin-api.db"
        db=await Database(path).start()
        cfg=SimpleNamespace(
            bot_token="123456:ADMIN_TEST",miniapp_url="",admin_ids=(1001,),
            menu_rate_limit=30, inchat_rate_limit=30,
        )
        mm=Matchmaker()
        server=MiniAppServer(None,cfg,db,mm,None)
        client=TestClient(TestServer(server.create_app()))
        await client.start_server()
        headers=lambda uid:{"X-Telegram-Init-Data":signed(uid)}
        try:
            home=await client.get("/")
            assert home.status==200
            home_html=await home.text()
            assert "admin.js?v=1" in home_html and "admin.css?v=1" in home_html
            assert 'data-game="numbers"' not in home_html
            assert "500 ⭐ в день" in home_html
            admin_bundle=await client.get("/admin.js")
            assert admin_bundle.status==200
            assert "api('/bootstrap')" in await admin_bundle.text()
            css=await client.get("/admin.css")
            assert css.status==200 and ".admin-center" in await css.text()
            for uid in (1001,1002,1003):
                await db.ensure_user(uid,f"user{uid}",f"User {uid}")
            retired=await client.post("/api/miniapp/games/numbers/invite",
                   headers=headers(1002),json={"range_max":10})
            assert retired.status==409
            assert "удалена" in (await retired.json())["message"]
            await db.award_xp(1002,50,source="message")
            no_auth=await client.get("/api/miniapp/admin/bootstrap")
            assert no_auth.status==401
            user=await client.get("/api/miniapp/admin/bootstrap",headers=headers(1002))
            assert user.status==403
            user_denial=await client.get("/api/miniapp/admin/users/1001",headers=headers(1002))
            assert user_denial.status==403
            fake=await client.get("/api/miniapp/admin/bootstrap",
                 headers={"X-Telegram-Init-Data":signed(1001)+"invalid"})
            assert fake.status==401
            await db.set_admin(1003,{"users"},1001)
            users_only=await client.get("/api/miniapp/admin/users",headers=headers(1003))
            assert users_only.status==200
            no_ledger=await client.get("/api/miniapp/admin/transactions",headers=headers(1003))
            assert no_ledger.status==403
            no_adjust=await client.post("/api/miniapp/admin/adjust",headers=headers(1003),
                                        json={"user_id":1002,"amount":50,"reason":"test",
                                              "key":"already-long-confirm-token"})
            assert no_adjust.status==403
            owner=await client.get("/api/miniapp/admin/bootstrap",headers=headers(1001))
            assert owner.status==200
            data=await owner.json()
            assert data["owner"] and "points" in data["permissions"]
            profile=await client.get("/api/miniapp/admin/users/1002",headers=headers(1001))
            assert (await profile.json())["user"]["xp"]==50
            key="test-protected-operation-01"
            args={"user_id":1002,"amount":70,"reason":"компенсация","key":key}
            plus=await client.post("/api/miniapp/admin/adjust",json=args,headers=headers(1001))
            assert plus.status==200 and (await plus.json())["balance"]==120
            repeat=await client.post("/api/miniapp/admin/adjust",json=args,headers=headers(1001))
            assert repeat.status==200 and (await repeat.json())["applied"] is False
            assert int((await db.get_user(1002))["xp"])==120
            bad=await client.post("/api/miniapp/admin/adjust",headers=headers(1001),
                json={"user_id":1002,"amount":-500,"reason":"too much",
                      "key":"test-negative-protected-02"})
            assert bad.status==400
            reason=await client.post("/api/miniapp/admin/adjust",headers=headers(1001),
                json={"user_id":1002,"amount":20,"reason":"",
                      "key":"test-without-reason-0003"})
            assert reason.status==400
            ledger=await client.get("/api/miniapp/admin/transactions?user_id=1002&period=today",
                                    headers=headers(1001))
            assert ledger.status==200
            items=(await ledger.json())["items"]
            assert any(t["source"]=="admin_award" and t["actor_id"]==1001
                       and t["reason"]=="компенсация" for t in items)
            assert any(t["source"]=="message" for t in items)
            rankings=await client.get("/api/miniapp/admin/rankings?period=week",
                                      headers=headers(1001))
            assert rankings.status==200 and (await rankings.json())["items"]
            report_id,_=await db.add_report(1003,1002,"spam","Пример")
            moderation={"action":"report_mute","report_id":report_id,"user_id":1002,
                        "minutes":60,"reason":"подтверждённое нарушение",
                        "key":"test-approved-report-001"}
            mod=await client.post("/api/miniapp/admin/moderate",json=moderation,
                                  headers=headers(1001))
            assert mod.status==200 and (await mod.json())["applied"] is True
            repeatmod=await client.post("/api/miniapp/admin/moderate",json=moderation,
                                        headers=headers(1001))
            assert repeatmod.status==200 and (await repeatmod.json())["applied"] is False
            assert (await db.get_report(report_id))["status"]=="done"
            assert (await db.get_user(1002))["mute_until"]>time.time()
            logs=await client.get("/api/miniapp/admin/actions",headers=headers(1001))
            assert logs.status==200 and (await logs.json())["items"]
            for route in ("/api/miniapp/admin/analytics","/api/miniapp/admin/games",
                          "/api/miniapp/admin/chats","/api/miniapp/admin/admins",
                          "/api/miniapp/admin/diagnostics","/api/miniapp/admin/sources"):
                response=await client.get(route,headers=headers(1001))
                assert response.status==200,(route,await response.text())
            # New admin-only monitors and owner-managed polls.
            mm.connect(1002)
            queue=await client.get("/api/miniapp/admin/queue",headers=headers(1001))
            assert queue.status==200
            assert any(int(x["user_id"])==1002 for x in (await queue.json())["items"])
            poll_input={"action":"create","question":"Как дела?",
                        "option_a":"Отлично","option_b":"Нормально",
                        "key":"integration-new-poll-001"}
            poll_post=await client.post("/api/miniapp/admin/polls",
                                        headers=headers(1001),json=poll_input)
            assert poll_post.status==200 and (await poll_post.json())["applied"]
            poll_view=await client.get("/api/miniapp/admin/polls",headers=headers(1001))
            assert (await poll_view.json())["active"]["question"]=="Как дела?"
            poll_close=await client.post("/api/miniapp/admin/polls",
                         headers=headers(1001),json={"action":"close",
                                                      "key":"integration-close-poll-002"})
            assert poll_close.status==200
            export=await client.get(
                "/api/miniapp/admin/transactions/export?user_id=1002&period=today",
                headers=headers(1001),
            )
            assert export.status==200
            csvbody=await export.read()
            assert csvbody.startswith(bytes((239,187,191)))
            assert b"admin_award" in csvbody and b"balance_after" in csvbody
            non_admin_export=await client.get(
                "/api/miniapp/admin/transactions/export",
                headers=headers(1002),
            )
            assert non_admin_export.status==403
            insecure=await client.post("/api/miniapp/admin/moderate",headers=headers(1002),
                                      json=moderation)
            assert insecure.status==403
        finally:
            await client.close()
            await db.close()
    asyncio.run(scenario())


if __name__=="__main__":
    test_admin_miniapp_endpoints()
    print("ok miniapp admin auth, XP, moderation, permissions and listings")
