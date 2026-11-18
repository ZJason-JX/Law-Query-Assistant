# -*- coding: utf-8 -*-
"""补判 multi_runs 中缺 score 的轮次（note 字段修复前跑完的那批）。"""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
PROJ = BASE.parent
for p in (str(PROJ), str(PROJ / "src"), str(BASE)):
    sys.path.insert(0, p)
for line in open(PROJ / ".env", encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1)
        __import__("os").environ.setdefault(k, v)

OUT = BASE / "results" / "v3_batch"
runs = [json.loads(l) for l in open(OUT / "multi_runs.jsonl", encoding="utf-8")]
scores = {(json.loads(l)["session"], json.loads(l)["turn_no"])
          for l in open(OUT / "multi_scores.jsonl", encoding="utf-8")}

cmap = {r["id"]: r for r in
        (json.loads(l) for l in open(PROJ / "src/corpus/chunks/chunks.jsonl", encoding="utf-8"))}
jp = (BASE / "judge_prompt.md").read_text(encoding="utf-8")
from server.main import HIST_RULE_JUDGE  # noqa: E402

# 数据集里 expected_articles 按 session+turn 取回
dec = json.JSONDecoder()
txt = open(BASE / "dataset_v3_multi.jsonl", encoding="utf-8").read()
sessions, idx = [], 0
while True:
    while idx < len(txt) and txt[idx] in " \n\r\t":
        idx += 1
    if idx >= len(txt):
        break
    o, idx = dec.raw_decode(txt, idx)
    sessions.append(o)
exp = {}
for s in sessions:
    for i, t in enumerate(s["turns"], 1):
        exp[(s["session"], i)] = t["expected_articles"]

from run_eval import judge as qj, DIMENSIONS  # noqa: E402

with open(OUT / "multi_scores.jsonl", "a", encoding="utf-8") as f:
    for r in runs:
        key = (r["session"], r["turn_no"])
        if key in scores or not r.get("answer"):
            continue
        item = {"query": r["query"],
                "expected_articles": [{**a, "note": a.get("note", "")}
                                      for a in exp.get(key, [])]}
        jp2 = jp + (HIST_RULE_JUDGE if r["turn_no"] > 1 else "")
        retr = [cmap[x] for x in r["retrieved_ids"] if x in cmap]
        j = qj(jp2, item, r["answer"], retrieved=retr)
        row = {"session": key[0], "turn_no": key[1],
               "dimensions": {d: j[d] for d in DIMENSIONS},
               "mos": round(sum(j[d] for d in DIMENSIONS) / 5, 3),
               "reason": j.get("评分理由", "")}
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()
        print(key, "MOS=", row["mos"], flush=True)
print("done")
