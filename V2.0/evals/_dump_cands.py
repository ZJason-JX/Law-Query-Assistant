# -*- coding: utf-8 -*-
import json
for l in open(r"法律问答助手2.0\evals\dataset_v2_candidates.jsonl", encoding="utf-8"):
    r = json.loads(l)
    print(f"cid{r['cid']} [{r['category']}] {r['suggested_scenario']}")
    print("  Q:", r["query"])
    print("  basis:", [a["law"] + a["article_no"] + "(" + a["version"] + ")" for a in r["basis_articles"]])
