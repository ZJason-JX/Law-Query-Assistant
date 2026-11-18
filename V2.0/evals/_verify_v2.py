# -*- coding: utf-8 -*-
import json
from collections import Counter

chunks = {}
for l in open(r"法律问答助手2.0\src\corpus\chunks\chunks.jsonl", encoding="utf-8"):
    r = json.loads(l)
    chunks[(r["law"], r["article_no"])] = r["id"]

rows = [json.loads(l) for l in open(r"法律问答助手2.0\evals\dataset_v2.jsonl", encoding="utf-8")]
print("total:", len(rows))
print("by category:", dict(Counter(r["category"] for r in rows)))
print("by difficulty:", dict(Counter(r["difficulty"] for r in rows)))
print("by scenario:", dict(Counter(r["scenario"] for r in rows)))
bad = []
for r in rows:
    for a in r["expected_articles"]:
        key = (a["law"], a["article"])
        if key not in chunks:
            bad.append((r["id"], key))
    if r["difficulty"] == "复合问题" and r.get("note") != "compound_query":
        bad.append((r["id"], "missing compound note"))
print("unresolved/malformed:", bad if bad else "none")
