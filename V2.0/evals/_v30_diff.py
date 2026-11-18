# -*- coding: utf-8 -*-
import json
import statistics as st

flip = {3, 4, 5, 6, 10, 12, 13, 15, 17, 26, 30}
o = {json.loads(l)["id"]: json.loads(l)
     for l in open("evals/results/v29_e2e_live/scores.jsonl", encoding="utf-8")}
n = {json.loads(l)["id"]: json.loads(l)
     for l in open("evals/results/v30_e2e_v3intent/scores.jsonl", encoding="utf-8")}
for i in sorted(flip):
    d = n[i]["mos"] - o[i]["mos"]
    print(f"id{i}: {o[i]['mos']:.1f} -> {n[i]['mos']:.1f} ({d:+.1f})  {n[i]['reason'][:60]}")
print("flipped mean:", round(st.mean(n[i]["mos"] for i in flip), 3),
      "vs old", round(st.mean(o[i]["mos"] for i in flip), 3))
