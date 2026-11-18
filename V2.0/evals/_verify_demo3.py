# -*- coding: utf-8 -*-
"""verified 正路径 v2：off-topic 拒答轮（重跑可预期干净）→ manual → 全链路到 closed。"""
import json, sqlite3, urllib.request, uuid

API = "http://localhost:8000"
DB = "server/data/app.db"

def req(path, method="GET", body=None, timeout=300):
    r = urllib.request.Request(API + path, method=method,
                               data=json.dumps(body).encode() if body is not None else None,
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=timeout).read())

sid = "bc-ot-" + uuid.uuid4().hex[:8]
q = "今天北京天气怎么样，适合出门吗？"
print("跑 off-topic query（预期拒答、重跑干净）...")
body = json.dumps({"query": q, "session_id": sid, "demo_mode": False,
                   "provider": "doubao"}).encode()
r = urllib.request.Request(API + "/api/chat", data=body,
                           headers={"Content-Type": "application/json"})
raw = urllib.request.urlopen(r, timeout=300).read().decode("utf-8")
ans = None
for b in raw.split("\n\n"):
    if b.startswith("event: answer"):
        ans = json.loads([l[6:] for l in b.splitlines() if l.startswith("data: ")][0])
print("badcases:", ans.get("badcases"), "| intent:", ans.get("intent"),
      "| conf:", ans.get("confidence"), "| latency:", ans.get("latency_ms"),
      "| turn:", ans.get("turn_no"))

m = req("/api/badcases", "POST", {"session_id": sid, "turn_no": ans["turn_no"],
                                  "note": "人工标记（验收正路径）", "actor": "tester"})
bid = m["badcase_id"]
print("manual:", bid, m["primary_stage"], m["severity"])

for st in ("triaged", "linked"):
    body = {"status": st, "actor": "qa"}
    if st == "linked":
        body.update({"linked_issue_id": "v3-offtopic", "note": "关联议题（验收）"})
    r = req(f"/api/badcases/{bid}", "PATCH", body)
    print(f"→ {st}: {r['status']}")

v = req(f"/api/badcases/{bid}/verify", "POST", {})
print("verify:", v)
if v.get("verified"):
    r = req(f"/api/badcases/{bid}", "PATCH", {"status": "closed", "actor": "qa", "note": "闭环验收"})
    print("→ closed:", r["status"])

con = sqlite3.connect(DB)
print("\nbadcase_events 流转记录:")
for e in con.execute(
        "SELECT from_status,to_status,actor,substr(note,1,120) FROM badcase_events WHERE badcase_id=? ORDER BY id",
        (bid,)):
    print("  ", e)
con.close()
