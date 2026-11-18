# -*- coding: utf-8 -*-
import json, sys

want = sys.argv[1:]
cm = {json.loads(l)["id"]: json.loads(l)
      for l in open(r"法律问答助手2.0\src\corpus\chunks\chunks.jsonl", encoding="utf-8")}
for rid in want:
    r = cm.get(rid)
    if r:
        print(f"== {rid} {r['law']}{r['article_no']}({r['version']})")
        print(r["text"][:400]); print()
    else:
        print("MISS", rid)
