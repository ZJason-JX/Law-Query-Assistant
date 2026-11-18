# -*- coding: utf-8 -*-
"""live 验收：POST /api/chat 真实问答 → badcases 角标/DB 行；demo/failed 不采集；状态机全链路。"""
import json, sqlite3, sys, urllib.request

API = "http://localhost:8000"
DB = "server/data/app.db"

def post(path, body=None, timeout=300):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())

def get(path):
    return json.loads(urllib.request.urlopen(API + path, timeout=60).read())

def patch(path, body):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="PATCH")
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

def count():
    con = sqlite3.connect(DB)
    n = con.execute("SELECT COUNT(*) FROM badcases").fetchone()[0]
    con.close()
    return n

def sse_chat(query, session_id="", demo=False, provider="doubao"):
    body = json.dumps({"query": query, "session_id": session_id,
                       "demo_mode": demo, "provider": provider}).encode()
    req = urllib.request.Request(API + "/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    raw = urllib.request.urlopen(req, timeout=300).read().decode("utf-8")
    evs = {}
    for block in raw.split("\n\n"):
        ev = [l for l in block.splitlines() if l.startswith("event: ")]
        dt = [l for l in block.splitlines() if l.startswith("data: ")]
        if ev and dt:
            evs.setdefault(ev[0][7:], []).append(dt[0][6:])
    return {k: [json.loads(x) for x in v] for k, v in evs.items()}

sid = "bc-check-" + __import__("uuid").uuid4().hex[:8]

print("== 1. live 正常问答（id29 对抗题，应被正确纠正 → 无 P0）")
n0 = count()
ev = sse_chat("员工不辞而别就算自动离职、无需任何手续，那公司在试用期直接让他走并说明理由总没问题吧？", sid)
ans = ev["answer"][0]
print("   badcases 字段:", ans.get("badcases"))
print("   DB 增量:", count() - n0)

print("== 2. demo_mode 重放（应零新增、无角标）")
n0 = count()
ev = sse_chat("x", demo=True)
print("   answer.badcases:", ev["answer"][0].get("badcases"), "| demo:", ev["answer"][0].get("demo"))
print("   DB 增量:", count() - n0)

print("== 3. failed 轮（provider=bogus → error 路径，应零新增）")
n0 = count()
ev = sse_chat("测试失败轮", sid, provider="bogus-provider")
print("   error:", ev.get("error"))
con = sqlite3.connect(DB)
ft = con.execute("SELECT status,error_code FROM turns WHERE session_id=? ORDER BY turn_id DESC LIMIT 1", (sid,)).fetchone()
con.close()
print("   末轮 status:", ft)
print("   DB 增量:", count() - n0)

print("== 4. 低质问答触发型（问一个跨法域冷僻题，看 B3/B5 是否触发）")
n0 = count()
ev = sse_chat("公司在没跟我签竞业协议的情况下能不能直接起诉我侵犯商业秘密？反不正当竞争法里平台二选一怎么算？", sid)
ans2 = ev["answer"][0]
print("   badcases 字段:", json.dumps(ans2.get("badcases"), ensure_ascii=False)[:400])
print("   DB 增量:", count() - n0)

print("== 5. 手动通道 + 状态机全链路 open→triaged→linked→verify→closed")
rows = get("/api/badcases?source=live&limit=5")
print("   live badcases:", [(r["badcase_id"][:22], r["primary_stage"], r["severity"]) for r in rows])
m = post("/api/badcases", {"session_id": sid, "turn_no": 1, "note": "验收人工标记", "actor": "tester"})
bid = m["badcase_id"]
print("   manual:", bid, m["primary_stage"], m["severity"], "turn_id:", m["turn_id"])
for st in ("triaged", "linked"):
    r = patch(f"/api/badcases/{bid}", {"status": st, "actor": "qa",
              "note": f"流转到 {st}", "linked_case_id": "case-99-验收"} if st == "linked" else {"status": st, "actor": "qa"})
    print(f"   → {st}: {r['status']}")
v = post(f"/api/badcases/{bid}/verify", {}, timeout=300)
print("   verify:", v)
r = patch(f"/api/badcases/{bid}", {"status": "closed", "actor": "qa", "note": "闭环验收"})
print("   → closed:", r["status"])
evs = get(f"/api/badcases/{bid}/events") if False else None
con = sqlite3.connect(DB)
for e in con.execute("SELECT from_status,to_status,actor,substr(note,1,60) FROM badcase_events WHERE badcase_id=? ORDER BY id", (bid,)):
    print("   event:", e)
con.close()

print("== 6. stats")
d = get("/api/badcases/stats")
print("   total:", d["total"], "| by_stage:", d["by_stage"], "| by_status:", d["by_status"])
print("   drafts:", [x["draft"][:60] for x in d["issue_drafts"]])
