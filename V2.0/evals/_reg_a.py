# -*- coding: utf-8 -*-
import json
import re


def ans_of(fp):
    sse = open(fp, encoding="utf-8").read()
    m = re.search(r"event: answer\ndata: (.*?)(?=\n\nevent:|\Z)", sse, re.S)
    return json.loads(m.group(1))


old = ans_of("evals/_baseline_turn1.sse")
new = ans_of("evals/_live_regA.sse")
print("retrieved_ids 相同:", old["retrieved_ids"] == new["retrieved_ids"])
print("  old:", old["retrieved_ids"])
print("  new:", new["retrieved_ids"])
print("intent/conf 相同:", (old["intent"], old["confidence"]) == (new["intent"], new["confidence"]),
      old["intent"], old["confidence"], "vs", new["intent"], new["confidence"])
print("answer 逐字节相同:", old["answer"] == new["answer"], f"({len(old['answer'])} vs {len(new['answer'])} 字)")
if old["answer"] != new["answer"]:
    for i, (a, b) in enumerate(zip(old["answer"], new["answer"])):
        if a != b:
            print(f"  首个差异@{i}: {a!r} vs {b!r}")
            break
