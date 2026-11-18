# -*- coding: utf-8 -*-
import json

OUT = "evals/results/v3_batch/"
runs = [json.loads(l) for l in open(OUT + "single_runs.jsonl", encoding="utf-8")]
r20 = next(r for r in runs if r["id"] == 20)
print("id20 conf:", r20["confidence"], "refused:", r20["refused"])
print("id20 answer:", (r20["answer"] or "")[:300])
r18 = next(r for r in runs if r["id"] == 18)
print("\nid18 conf:", r18["confidence"], "refused:", r18["refused"])
print()
mruns = [json.loads(l) for l in open(OUT + "multi_runs.jsonl", encoding="utf-8")]
for r in mruns:
    if r.get("used_history"):
        print(r["session"], "t" + str(r["turn_no"]), "used:", r["used_history"])
        for c in r["citations"]:
            print("   cite:", c["law"], c["article_no"], c["band"], "turn=", c.get("turn"))
for s, t in [("m09", 1), ("m03", 2), ("m10", 3), ("m07", 3)]:
    r = next(x for x in mruns if x["session"] == s and x["turn_no"] == t)
    a = (r["answer"] or "")[:160].replace("\n", " / ")
    print(s + "t" + str(t), "conf=", r["confidence"], "intent=", r["intent"], "|", a)
