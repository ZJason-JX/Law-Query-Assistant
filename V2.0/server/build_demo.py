# -*- coding: utf-8 -*-
"""生成 id29 五幕演示素材 server/demo_id29.json（一次性，确定性重放用）。
首轮检索用冻结变体确定性重算；门控/追加轮用 v20 trace；答案与评分取 v21 落盘结果。
运行：python server/build_demo.py"""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "src"))
sys.path.insert(0, str(BASE / "evals"))

import pipeline  # noqa: E402

ds = {json.loads(l)["id"]: json.loads(l) for l in open(BASE / "evals/dataset_v2.jsonl", encoding="utf-8")}
exp = {json.loads(l)["id"]: json.loads(l)["variants"] for l in open(BASE / "evals/query_expanded_v2.jsonl", encoding="utf-8")}
trace = {json.loads(l)["query_id"]: json.loads(l) for l in open(BASE / "evals/query_expansion_trace.jsonl", encoding="utf-8")}
ans = {json.loads(l)["id"]: json.loads(l) for l in open(BASE / "evals/results/v21_react_e2e/answers.jsonl", encoding="utf-8")}
scores = {json.loads(l)["id"]: json.loads(l) for l in open(BASE / "evals/results/v21_react_e2e/scores.jsonl", encoding="utf-8")}
chunk_map = {json.loads(l)["id"]: json.loads(l) for l in open(BASE / "src/corpus/chunks/chunks.jsonl", encoding="utf-8")}

item = ds[29]
q = item["query"]
ranked = pipeline._retrieve_pool(q, [q] + exp[29], pool={})
first = [{"id": e["payload"]["id"], "law": e["payload"]["law"],
          "article_no": e["payload"]["article_no"], "rrf": round(e["rrf"], 4),
          "dense_rank": e["dense"][1] if e["dense"] else None,
          "sparse_rank": e["sparse"][1] if e["sparse"] else None}
         for e in ranked[:10]]
t = trace[29]
a = ans[29]
final = [{"id": rid, "law": chunk_map[rid]["law"], "article_no": chunk_map[rid]["article_no"]}
         for rid in a["retrieved_ids"]]
demo = {
    "query": q, "trap_article": "labor-contract-law-21",
    "first_round_articles": first,
    "gates": t["gates"], "rounds": t["rounds"], "stop_reason": t["stop_reason"],
    "final_articles": final, "answer": a["answer"],
    "intent": a["intent"], "confidence": a["confidence"],
    "false_premise": a["false_premise"], "judge": scores[29],
    "subtitles": [
        "这是一个幻觉诱饵：『自动离职』在现行法里并不存在，试用期解除也必须满足法定情形。",
        "首轮检索召回了第39条等试用期条文，但 trap 主条《劳动合同法》第21条并不在 top-10。",
        "JEV 门控打出很高的 false_premise 分：问题前提不成立，触发纠错重查，而不是直接作答。",
        "追加轮围绕『试用期解除的法定条件』补检，把第21条拉回证据池。",
        "最终回答先纠正前提再引用法条，引用全部落在检索上下文内，judge 给出满分。",
    ],
}
out = BASE / "server" / "demo_id29.json"
json.dump(demo, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("written", out)
print("first round has trap?", any(x["id"] == "labor-contract-law-21" for x in first))
print("final has trap?", any(x["id"] == "labor-contract-law-21" for x in final))
print("judge:", scores[29]["mos"], "gates:", t["gates"])
