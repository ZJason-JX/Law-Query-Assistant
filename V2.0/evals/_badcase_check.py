# -*- coding: utf-8 -*-
"""badcase 系统验收（离线部分）：
A. collect_live 合成信号单测（B1/B2/B3/B4/B5/B10 → 环节与严重度）
B. collect_eval 用 v30_e2e_v3intent 真实跑批数据回放（id7/id2/id10/id16 归因）
运行: python evals/_badcase_check.py
"""
import json, sqlite3, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
PROJ = BASE.parent
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(PROJ / "src"))
sys.path.insert(0, str(BASE))

from server import badcases as bc, store  # noqa: E402

# ---------- A. 合成信号单测 ----------
def mkres(**kw):
    r = {"answer": "普通回答", "retrieved_ids": ["civil-law-571"],
         "intent": "statute_lookup", "confidence": 0.95, "false_premise": 0.0,
         "prompt_file": "statute_lookup.md", "react_rounds": 0, "react_gates": []}
    r.update(kw)
    return r

A = []
A.append(("B1 outside_context", bc.collect_live("q", mkres(),
        {"ungrounded": 2, "n": 3, "citations": []}, 30000)))
A.append(("B2 对抗veto", bc.collect_live("q", mkres(false_premise=0.94),
        {"ungrounded": 0, "n": 1, "citations": []}, 30000)))
A.append(("B3 低conf", bc.collect_live("q", mkres(confidence=0.6),
        {"ungrounded": 0, "n": 1, "citations": []}, 30000)))
A.append(("B4 fp未纠正", bc.collect_live("q", mkres(false_premise=0.6),
        {"ungrounded": 0, "n": 1, "citations": []}, 30000)))
A.append(("B5 轮满不充分", bc.collect_live("q", mkres(react_stop="max_rounds",
        react_rounds=5, react_gates=[{"sufficient": 0.4}]),
        {"ungrounded": 0, "n": 1, "citations": []}, 30000)))
A.append(("B10 慢", bc.collect_live("q", mkres(),
        {"ungrounded": 0, "n": 1, "citations": []}, 50000)))
A.append(("干净不误报", bc.collect_live("q", mkres(),
        {"ungrounded": 0, "n": 1, "citations": []}, 30000)))

print("=== A. collect_live 单测 ===")
for name, rows in A:
    if not rows:
        print(f"  {name}: 未触发")
        continue
    r = rows[0]
    print(f"  {name}: rules={[t['rule_id'] for t in r['triggered_rules']]} "
          f"→ {r['primary_stage']} {r['severity']}")

# ---------- B. v30 真实数据回放 ----------
ver = "v22_react_live"
rd = BASE / "results" / ver
items = {json.loads(l)["id"]: json.loads(l)
         for l in open(BASE / "dataset_v2.jsonl", encoding='utf-8')}
answers = {json.loads(l)["id"]: json.loads(l)
           for l in open(rd / "answers.jsonl", encoding="utf-8")}
scores = {json.loads(l)["id"]: json.loads(l)
          for l in open(rd / "scores.jsonl", encoding="utf-8")}
cmap = {json.loads(l)["id"]: json.loads(l)
        for l in open(PROJ / "src" / "corpus" / "chunks" / "chunks.jsonl", encoding="utf-8")}

print("\n=== B. eval 通道回放 v22_react_live（真实跑批，无新模型调用） ===")
picked = {}
for iid, s in sorted(scores.items()):
    if iid not in items or iid not in answers:
        continue
    got = bc.collect_eval(items[iid], answers[iid], s["dimensions"], s["mos"],
                          s.get("reason", ""), cmap, version=f"replay-{ver}")
    if got:
        r = got[0]
        picked[iid] = r
        tag = " ⚑测量仪器" if r.get("instrument_defect") else ""
        sec = f" 次:{','.join(r['secondary_stages'])}" if r["secondary_stages"] else ""
        print(f"  id{iid}: rules={[t['rule_id'] for t in r['triggered_rules']]} "
              f"→ {r['primary_stage']} {r['severity']}{sec}{tag}")

print("\n=== C. 已知缺陷对照（验收1） ===")
for iid, expect in ((7, "S1/S3"), (2, "S4"), (10, "S4"), (16, "S5")):
    r = picked.get(iid)
    print(f"  id{iid} 期望 {expect} → 实际 "
          f"{(r['primary_stage'] + ' ' + r['severity']) if r else '未触发'}"
          + (f"（次要:{','.join(r['secondary_stages'])}）" if r and r["secondary_stages"] else ""))

print("\n=== D. 测量仪器缺陷（真实答案 + 构造 judge 判词注入） ===")
# 真实答案 id16/v1.0 的引用在上下文内时，judge 若仍判「编造」→ 应命中 A-INSTR
ans10 = {json.loads(l)["id"]: json.loads(l)
         for l in open(BASE / "results" / "v22_react_live" / "answers.jsonl", encoding='utf-8')}
a = ans10[13]  # 反法2025题，真实答案
audit = bc._audit_plain(a.get("answer", ""), a.get("retrieved_ids", []), cmap)
print(f"  预检 id13 审计: n={audit['n']} ungrounded={audit['ungrounded']}")
if audit["ungrounded"] == 0 and audit["n"] > 0:
    got = bc.collect_eval(items[13], a,
                          {"准确性": 5, "相关性": 5, "完整性": 5, "简洁性": 5, "安全性": 1},
                          4.2, "答案编造法条，引用了不存在的条文（注入测试判词）",
                          cmap, version="inject-judge-defect")
    r = got[0] if got else None
    print(f"  注入后: rules={[t['rule_id'] for t in r['triggered_rules']]} "
          f"→ {r['primary_stage']} {r['severity']} 仪器:{r.get('instrument_defect')}")

print("\n=== E. 意图错例 → S0（v30 intent_report 真实 conf 回放 live 规则） ===")
rep = json.load(open(BASE / "results" / "v30_e2e_v3intent" / "intent_report.json",
                     encoding="utf-8"))
for d in rep["detail"]:
    if d.get("ok") is False and d.get("expected") != "irrelevant":
        fake = {"answer": "x", "retrieved_ids": [], "intent": d.get("intent"),
                "confidence": d.get("confidence"), "false_premise": 0.0,
                "prompt_file": "x.md", "react_gates": []}
        got = bc.collect_live("q", fake, {"ungrounded": 0, "n": 0, "citations": []}, 10000)
        print(f"  id{d['id']} expected={d['expected']} got={d['intent']} conf={d['confidence']}"
              f" → {([t['rule_id'] for t in got[0]['triggered_rules']], got[0]['primary_stage']) if got else '不触发'}")

# ---------- 表内无正文副本 ----------
con = sqlite3.connect(store.DB)
cols = [c[1] for c in con.execute("PRAGMA table_info(badcases)")]
print("\nbadcases 列:", cols)
assert not any(c in ("query", "answer", "user_query", "text") for c in cols), "存在正文字段！"
print("无 query/answer/法条正文字段 ✓")
con.close()
