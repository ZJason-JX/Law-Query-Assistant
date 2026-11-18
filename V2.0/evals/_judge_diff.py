# -*- coding: utf-8 -*-
import json

B = r"法律问答助手2.0\evals\results"

def load(d):
    return {json.loads(l)["id"]: json.loads(l)
            for l in open(B + "/" + d + "/scores.jsonl", encoding="utf-8")}

for old, new in [("v1_doubao_qwen", "v1.0_judge_fixed"), ("v1.1", "v1.1_judge_fixed")]:
    so, sn = load(old), load(new)
    print("=" * 15, old, "->", new)
    for i in sorted(so):
        d = sn[i]["mos"] - so[i]["mos"]
        mark = " <==" if abs(d) >= 1 else ""
        print(i, so[i]["mos"], "->", sn[i]["mos"],
              list(so[i]["dimensions"].values()), "->", list(sn[i]["dimensions"].values()), mark)
    mo = sum(s["mos"] for k, s in so.items() if k <= 20) / 20
    mn = sum(s["mos"] for k, s in sn.items() if k <= 20) / 20
    print("legal MOS %.2f -> %.2f" % (mo, mn))
