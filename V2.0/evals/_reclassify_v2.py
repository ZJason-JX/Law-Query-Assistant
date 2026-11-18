# -*- coding: utf-8 -*-
"""v2 意图重分类：criteria 修订后全量 JEV 重跑，新旧混淆矩阵对照。
落盘 intent_cache_v2b.jsonl（新分类，不覆盖旧缓存）。"""
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
PROJ = BASE.parent
sys.path.insert(0, str(PROJ / "src"))

for line in open(PROJ / ".env", encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1)
        os_k, os_v = k, v
        import os
        os.environ.setdefault(os_k, os_v)

from intent_node import classify  # noqa: E402

SCENARIO2INTENT = {"构成要件与归责": "elements_liability", "法条精准检索": "statute_lookup",
                   "规则冲突与适用": "rule_conflict", "法律概念界定": "concept_definition",
                   "off_topic": "irrelevant"}

items = [json.loads(l) for l in open(BASE / "dataset_v2.jsonl", encoding="utf-8")]
old = {json.loads(l)["id"]: json.loads(l)
       for l in open(BASE / "intent_cache_v2.jsonl", encoding="utf-8")}

new = {}
out_fp = open(BASE / "intent_cache_v2b.jsonl", "w", encoding="utf-8")
for it in items:
    r = classify(it["query"])
    new[it["id"]] = {"id": it["id"], **r}
    out_fp.write(json.dumps(new[it["id"]], ensure_ascii=False) + "\n")
    time.sleep(0.3)
out_fp.close()

for tag, cache in (("旧", old), ("新", new)):
    matrix, errs, confs = {}, [], []
    for it in items:
        exp = SCENARIO2INTENT.get(it["scenario"])
        got = cache[it["id"]]["intent"]
        conf = cache[it["id"]]["confidence"]
        matrix[f"{exp}->{got}"] = matrix.get(f"{exp}->{got}", 0) + 1
        confs.append(conf)
        if got != exp:
            errs.append((it["id"], exp, got, conf))
    legal_errs = [e for e in errs if e[1] != "irrelevant"]
    n_legal = len(items) - 3
    acc = (n_legal - len(legal_errs)) / n_legal
    print(f"\n===== {tag} criteria =====")
    print(f"legal 准确率: {acc:.3f}  混淆矩阵: {matrix}")
    for e in legal_errs:
        print(f"  错例 id{e[0]}: {e[1]} -> {e[2]} (conf={e[3]})")
    import statistics
    print(f"  conf 分布: min={min(confs):.2f} median={statistics.median(confs):.2f} "
          f"<0.85: {sum(1 for c in confs if c < 0.85)}/{len(confs)}")
