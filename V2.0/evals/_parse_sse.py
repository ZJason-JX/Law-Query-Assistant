# -*- coding: utf-8 -*-
import json
import re
import sys

for fp in sys.argv[1:]:
    sse = open(fp, encoding="utf-8").read()
    evs = []
    for m in re.finditer(r"event: (\w+)\ndata: (.*?)(?=\n\nevent:|\Z)", sse, re.S):
        evs.append((m.group(1), json.loads(m.group(2))))
    s0 = next((d for e, d in evs if e == "state" and d.get("stage") == "S0"), None)
    gates = [d for e, d in evs if e == "state" and d.get("stage") == "S2"]
    s3n = len([d for e, d in evs if e == "state" and d.get("stage") == "S3"])
    s5 = next((d for e, d in evs if e == "state" and d.get("stage") == "S5"), None)
    ans = next((d for e, d in evs if e == "answer"), None)
    err = next((d for e, d in evs if e == "error"), None)
    print(f"--- {fp} ---")
    if err:
        print("ERROR:", err)
        continue
    if s0:
        print("S0 intent:", s0.get("intent"), s0.get("confidence"), "fp:", s0.get("false_premise"))
    print("S2 gates:", [(g.get("round"), round(g.get("sufficient", 0), 3), g.get("decision")) for g in gates],
          "| S3 追加轮:", s3n)
    if s5:
        print(f"S5: n_citations={s5['n']} ungrounded={s5['ungrounded']} used_history={s5.get('used_history')}")
        for c in s5["citations"]:
            print("   cite:", c["law"], c["article_no"], c["band"], "turn=", c.get("turn"))
    if ans:
        print("turn_no:", ans.get("turn_no"), "| retrieved:", ",".join(ans["retrieved_ids"][:6]))
        print("answer:", ans["answer"][:200].replace("\n", " / "))
    print()
