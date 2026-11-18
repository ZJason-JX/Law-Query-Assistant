# -*- coding: utf-8 -*-
"""扩库前后 top-10 对照：旧池（v1.2_r2 落盘 retrieved_ids）vs 新池重算。"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
BASE = Path(__file__).resolve().parent
PROJ = BASE.parent
sys.path.insert(0, str(PROJ / "src"))

from pipeline import retrieve  # noqa: E402

exps = {json.loads(l)["id"]: json.loads(l)["variants"]
        for l in open(BASE / "query_expanded_v0_3.jsonl", encoding="utf-8")}
old = {json.loads(l)["id"]: json.loads(l)
       for l in open(PROJ / "evals" / "results" / "v1.2_r2" / "answers.jsonl", encoding="utf-8")}
ds = {json.loads(l)["id"]: json.loads(l)
      for l in open(BASE / "dataset.jsonl", encoding="utf-8")}

changed = []
labour_hits = []
for iid in sorted(old):
    if iid not in exps or iid not in ds:
        continue
    q = ds[iid]["query"]
    new_ids = [a["id"] for a in retrieve(q, 10, queries=[q] + exps[iid])]
    old_ids = old[iid].get("retrieved_ids", [])
    if new_ids != old_ids:
        lost = [x for x in old_ids if x not in new_ids]
        gained = [x for x in new_ids if x not in old_ids]
        changed.append({"id": iid, "lost": lost, "gained": gained})
        for g in gained:
            if g.startswith(("labor-law", "labor-contract-law")):
                labour_hits.append({"id": iid, "gained": g})

print("top-10 变化的 query：", len(changed))
for c in changed:
    print(f"  id{c['id']}: -{c['lost']} +{c['gained']}")
print("挤入的劳动法条目：", labour_hits or "无")

out = {"changed": changed, "labour_hits": labour_hits}
with open(BASE / "results" / "corpus_v2_labour_law" / "topk_diff.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("saved ->", BASE / "results" / "corpus_v2_labour_law" / "topk_diff.json")
