# -*- coding: utf-8 -*-
"""S2 门控诊断：trace + v20_react 报告 + v2 primary 基线对照，纯分析不重跑。"""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent

trace = {json.loads(l)["query_id"]: json.loads(l)
         for l in open(BASE / "query_expansion_trace.jsonl", encoding="utf-8")}
react = {q["id"]: q for q in
         json.load(open(BASE / "results" / "v20_react" / "recall_report.json", encoding="utf-8"))["per_query"]}
base = {q["id"]: q for q in
        json.load(open(BASE / "results" / "dataset_v2_baseline_primary" / "recall_report.json", encoding="utf-8"))["per_query"]}

# ---------- A1 suff 首轮分数直方图 ----------
first_suff = {qid: t["gates"][0]["sufficient"] for qid, t in trace.items()}
bins = {"0.0-0.2": [], "0.2-0.4": [], "0.4-0.5": [], "0.5-0.7": [], "0.7-1.0": []}
for qid, s in first_suff.items():
    k = ("0.0-0.2" if s < 0.2 else "0.2-0.4" if s < 0.4 else
         "0.4-0.5" if s < 0.5 else "0.5-0.7" if s < 0.7 else "0.7-1.0")
    bins[k].append((qid, s))
print("A1 首轮 suff_evidence 分布（阈值线 0.5）")
for k, v in bins.items():
    mark = "  <== 阈值 0.5 在此桶上沿" if k == "0.4-0.5" else ("  <== 阈值以下全部进循环" if k in ("0.0-0.2", "0.2-0.4") else "")
    ids = ",".join(str(i) for i, _ in v)
    print(f"  {k}: n={len(v):>2} [{ids}]{mark}")

# ---------- A2 分桶收益 ----------
groups = {"suff<0.3": [], "0.3-0.5": [], ">=0.5": []}
for qid, s in first_suff.items():
    k = "suff<0.3" if s < 0.3 else ("0.3-0.5" if s < 0.5 else ">=0.5")
    groups[k].append(qid)
print("\nA2 分桶收益（增量=各轮 recalled_delta 之和；提升=react recall - baseline recall）")
print(f"{'桶':<10} {'题数':>4} {'平均增量':>8} {'recall提升':>10} {'平均轮次':>8}")
for k, ids in groups.items():
    if not ids:
        continue
    deltas, ups, rds = [], [], []
    for qid in ids:
        t = trace[qid]
        deltas.append(sum(r["recalled_delta"] for r in t["rounds"]))
        ups.append(react[qid]["recall"] - base[qid]["recall"])
        rds.append(len(t["rounds"]))
    print(f"{k:<10} {len(ids):>4} {sum(deltas)/len(deltas):>8.2f} {sum(ups)/len(ups):>10.3f} {sum(rds)/len(rds):>8.2f}")

# ---------- A4 白跑规模 ----------
wasted = []
for qid, t in trace.items():
    if not t["rounds"]:
        continue
    total_delta = sum(r["recalled_delta"] for r in t["rounds"])
    if total_delta == 0 and react[qid]["recall"] == base[qid]["recall"]:
        wasted.append(qid)
    # 也记"有增量但 recall 没变"（进池但没进 top10 / 进的不是期望条）
print(f"\nA4 纯白跑（总增量=0 且 recall 不变）: {wasted}")
dil = [qid for qid, t in trace.items()
       if t["rounds"] and sum(r["recalled_delta"] for r in t["rounds"]) > 0
       and react[qid]["recall"] == base[qid]["recall"]]
print(f"A4' 有增量但 recall 无变化（稀释/非期望条进池）: {dil}")
