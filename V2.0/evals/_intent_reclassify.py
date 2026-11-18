# -*- coding: utf-8 -*-
"""新标准 JEV 全量重分类 → intent_cache_v3.jsonl，并对照 v2 缓存逐条 diff。"""
import json
import os
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent / "src"))
for line in open(BASE.parent / ".env", encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1)
        os.environ.setdefault(k, v)

from intent_node import classify  # noqa: E402

S2I = {"构成要件与归责": "elements_liability", "法条精准检索": "statute_lookup",
       "规则冲突与适用": "rule_conflict", "法律概念界定": "concept_definition",
       "off_topic": "irrelevant"}
old = {json.loads(l)["id"]: json.loads(l)
       for l in open(BASE / "intent_cache_v2.jsonl", encoding="utf-8")}

out = open(BASE / "intent_cache_v3.jsonl", "w", encoding="utf-8")
hits = flips = n_leg = 0
for l in open(BASE / "dataset_v2.jsonl", encoding="utf-8"):
    it = json.loads(l)
    i = it["id"]
    for attempt in range(4):
        try:
            ic = classify(it["query"])
            break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    rec = {"id": i, **{k: ic[k] for k in ("intent", "confidence", "probabilities",
                                          "false_premise", "jev_model", "jev_latency_ms",
                                          "jev_usage")}}
    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
    exp = S2I[it["scenario"]]
    if exp != "irrelevant":
        n_leg += 1
        hits += ic["intent"] == exp
    o = old.get(i, {}).get("intent")
    if o != ic["intent"]:
        flips += 1
        print(f"id{i}: {o} -> {ic['intent']} (exp={exp}, conf={ic['confidence']})")
    time.sleep(0.3)
out.close()
print(f"v3 准确率(legal): {hits}/{n_leg} = {hits / n_leg:.3f}; 标签翻转 {flips} 条")
