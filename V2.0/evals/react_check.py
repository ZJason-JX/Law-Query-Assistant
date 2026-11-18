# -*- coding: utf-8 -*-
"""v2.0-retrieval-agent：ReAct 循环检索评测。

状态机（本脚本实现 S1-S3，S0/S4/S5 不动）：
  S1 首轮检索（离线固化变体 × dense+sparse 八路 RRF，与基线同管线）
  S2 证据充分性门控（JEV：sufficient_evidence Noul，首轮加问 false_premise）
  S3 追加轮（≤5 轮）：DeepSeek 针对缺口生成新查询（含法域覆盖提示）→ 同管线 RRF 入池去重
终止：sufficient≥0.9 | 轮数=5 | trace 复放耗尽

确定性：--trace 落盘每轮 JEV 分数 + 生成的新查询；--replay 跳过 LLM/JEV，
  按 trace 复放检索动作 → 双跑逐条一致。
用法:
  python evals/react_check.py --dataset evals/dataset_v2.jsonl \
      --expand-file evals/query_expanded_v2.jsonl --collection law_articles_v0_5 \
      --save v20_react --trace evals/query_expansion_trace.jsonl [--replay]
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from FlagEmbedding import BGEM3FlagModel
from qdrant_client import QdrantClient
from qdrant_client.models import (FieldCondition, Filter, MatchValue, SparseVector)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recall_check import LAW_SLUG, art_groups  # noqa: E402

BASE = Path(__file__).resolve().parents[1]
STORAGE = BASE / "src" / "db" / "qdrant_storage"

for line in open(BASE / ".env", encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1)
        os.environ.setdefault(k, v)

MAX_ROUNDS = 5
SUFF_TH, FP_TH = 0.9, 0.5


def call_ds(prompt: str) -> dict:
    body = json.dumps({"model": "deepseek-chat",
                       "messages": [{"role": "user", "content": prompt}],
                       "temperature": 0}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions", data=body,
        headers={"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}",
                 "Content-Type": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.loads(r.read().decode("utf-8"))
            msg = d["choices"][0]["message"]["content"].strip()
            return {"text": msg, "usage": d.get("usage", {})}
        except Exception:
            if attempt == 5:
                raise
            time.sleep(2 ** attempt)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topk", type=int, default=10)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--expand-file", required=True)
    ap.add_argument("--collection", default="law_articles")
    ap.add_argument("--save", metavar="VERSION_DIR")
    ap.add_argument("--trace", metavar="JSONL", help="落盘轮次 trace（JEV分数+新查询）")
    ap.add_argument("--replay", metavar="JSONL", help="按已有 trace 复放，不调 JEV/DeepSeek")
    ap.add_argument("--current-only", action="store_true")
    args = ap.parse_args()

    replay = {}
    if args.replay:
        for l in open(args.replay, encoding="utf-8"):
            r = json.loads(l)
            replay[r["query_id"]] = r

    expansions = {}
    for l in open(args.expand_file, encoding="utf-8"):
        r = json.loads(l)
        expansions[r["id"]] = r["variants"]

    evals = [json.loads(l) for l in open(args.dataset, encoding="utf-8")]
    model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=False)
    client = QdrantClient(path=str(STORAGE))
    filt = Filter(must=[FieldCondition(key="status", match=MatchValue(value="现行有效"))]) \
        if args.current_only else None

    def lane_lists(query: str, limit: int) -> dict:
        emb = model.encode([query], return_dense=True, return_sparse=True)
        lw = sorted(emb["lexical_weights"][0].items())
        sv = SparseVector(indices=[k for k, _ in lw], values=[v for _, v in lw])
        out = {}
        for name, qq in (("dense", emb["dense_vecs"][0].tolist()), ("sparse", sv)):
            r = client.query_points(args.collection, query=qq, using=name, limit=limit,
                                    query_filter=filt, with_payload=True)
            out[name] = r.points
        return out

    def rrf_into(pool: dict, queries: list, lane_n: int = 20, weight: float = 1.0) -> int:
        """多 query × dense+sparse RRF 累加入池，返回新增条数。
        weight<1 用于追加轮降权，防止批量新条目挤掉首轮命中。"""
        before = set(pool)
        for qx in queries:
            for lane, pts in lane_lists(qx, lane_n).items():
                for rank, p in enumerate(pts, 1):
                    ent = pool.setdefault(p.payload["id"], [p, 0.0])
                    ent[1] += weight / (60 + rank)
        return len(set(pool) - before)

    def arts_summary(pool_ranked: list) -> str:
        return "\n".join(f"《{p.payload['law']}》{p.payload['article_no']}"
                         for p, _ in pool_ranked[:10])

    sys.path.insert(0, str(BASE / "src"))
    from intent_node import evidence_gate  # noqa: E402

    per_query, trace_rows, cost = [], [], []
    print(f"{'id':>3} {'difficulty':<6} {'recall':>7} {'rounds':>6}  miss")
    for item in evals:
        if not item.get("expected_articles"):
            continue
        rp = replay.get(item["id"])
        q = item["query"]
        t_q0 = time.time()
        tok = {"jev_in": 0, "jev_out": 0, "ds_in": 0, "ds_out": 0}

        # S1 首轮：原 query + 离线变体，八路 RRF（与基线同）
        pool = {}
        rrf_into(pool, [q] + expansions.get(item["id"], []))
        rounds_log, gates_log, stop, n_extra = [], [], None, 0

        while True:
            # S2 门控
            if rp:
                g = rp["gates"][n_extra] if n_extra < len(rp["gates"]) else rp["gates"][-1]
            else:
                g = evidence_gate(q, arts_summary(sorted(pool.values(), key=lambda x: -x[1])),
                                  ask_fp=(n_extra == 0))
                gates_log.append({"sufficient": g["sufficient"],
                                  "false_premise": g["false_premise"]})
                tok["jev_in"] += g["jev_usage"]["input_tokens"]
                tok["jev_out"] += g["jev_usage"]["output_tokens"]
            suff, fp = g["sufficient"], g.get("false_premise") or 0.0
            need_more = (suff < SUFF_TH) or (fp > FP_TH)
            if not need_more:
                stop = "sufficient"
                break
            if rp and n_extra >= len(rp["rounds"]):
                stop = "trace_end"
                break
            if n_extra >= MAX_ROUNDS:
                stop = "max_rounds"
                break
            # S3 追加轮
            if rp:
                nq = rp["rounds"][n_extra]["new_query"]
            else:
                ranked_now = sorted(pool.values(), key=lambda x: -x[1])
                covered = "、".join(dict.fromkeys(p.payload["law"] for p, _ in ranked_now[:10]))
                hint = "注意：该问题可能包含错误法律前提，请基于纠正后的前提生成检索查询。\n" \
                    if fp > FP_TH else ""
                prompt = (f"用户问题：{q}\n"
                          f"已检索到的法条：\n{arts_summary(ranked_now)}\n"
                          f"已覆盖法律：{covered}\n"
                          f"{hint}若问题涉及多部法律，优先生成针对尚未覆盖法律的检索查询；"
                          f"否则针对上述法条可能未覆盖的角度"
                          f"（其他法律关系、后果/救济、例外情形、被引用条款）。"
                          f"只输出一行查询文本。")
                d = call_ds(prompt)
                nq = d["text"].strip().strip('"“”').splitlines()[0].strip()
                tok["ds_in"] += d["usage"].get("prompt_tokens", 0)
                tok["ds_out"] += d["usage"].get("completion_tokens", 0)
            delta = rrf_into(pool, [nq], weight=0.6)
            rounds_log.append({"round": n_extra + 1, "new_query": nq,
                               "recalled_delta": delta, "sufficient_score": suff,
                               "fp_score": fp})
            n_extra += 1

        ranked = sorted(pool.values(), key=lambda x: -x[1])
        head, seen, skipped = [], {}, []
        for ent in ranked:
            law = ent[0].payload["law"]
            if len(head) < args.topk and seen.get(law, 0) < 8:
                head.append(ent)
                seen[law] = seen.get(law, 0) + 1
            else:
                skipped.append(ent)
        ranked = head + skipped
        res_points = [p for p, _ in ranked[:args.topk]]
        got = {p.payload["id"] for p in res_points}
        prim = [a for a in item["expected_articles"] if a.get("level", "primary") == "primary"]
        sec = [a for a in item["expected_articles"] if a.get("level", "primary") == "secondary"]
        need, sec_g = art_groups(prim), art_groups(sec)
        hit = sum(1 for g in need if got & g)
        recall = hit / len(need) if need else 0.0
        miss = sorted(m for g in need if not (got & g) for m in g)
        rec = {"id": item["id"], "difficulty": item["difficulty"],
               "recall": recall, "expected": [m for g in need for m in g],
               "hit": hit, "total": len(need), "miss": miss,
               "secondary_hit": sum(1 for g in sec_g if got & g),
               "secondary_total": len(sec_g),
               "rounds": n_extra, "stop_reason": stop,
               "latency_ms": round((time.time() - t_q0) * 1000),
               "tokens": tok}
        if item.get("trap_primary"):
            tp = art_groups([item["trap_primary"]])[0]
            rec["trap_primary_hit"] = bool(got & tp)
            rec["trap_primary"] = sorted(tp)
        trace_rows.append({"query_id": item["id"], "gates": gates_log,
                           "rounds": rounds_log, "stop_reason": stop})
        cost.append(rec)
        per_query.append(rec)
        print(f"{item['id']:>3} {item['difficulty']:<6} {recall:>7.2f} {n_extra:>6}  "
              f"{'、'.join(miss) if miss else '-'} [{stop}]")

    # ---- 切片 ----
    print("=" * 60)
    THRESHOLDS = {"显性事实": 0.90, "隐性事实": 0.70}
    slices = {}
    for diff in ("显性事实", "隐性事实", "可解释推理", "对抗样本", "复合问题"):
        sub = [q for q in per_query if q["difficulty"] == diff]
        if not sub:
            continue
        mean = sum(q["recall"] for q in sub) / len(sub)
        th = THRESHOLDS.get(diff)
        slices[diff] = {"n": len(sub), "mean_recall": round(mean, 4), "threshold": th,
                        "pass": (mean >= th) if th is not None else None}
        verdict = f"{'PASS' if slices[diff]['pass'] else 'FAIL'} (线 ≥{th})" if th is not None else "(无阈值)"
        print(f"{diff:<8} n={len(sub):>2}  mean recall={mean:.2f}  {verdict}")

    adv = [q for q in per_query if q["difficulty"] == "对抗样本"]
    adv_ok = all(q.get("trap_primary_hit", q["recall"] == 1.0) for q in adv) if adv else False
    for q in adv:
        print(f"对抗样本一票否决检查: id={q['id']} trap_hit={q.get('trap_primary_hit')} -> "
              f"{'PASS' if q.get('trap_primary_hit', q['recall'] == 1.0) else 'FAIL'}")

    # ---- 循环开销 ----
    mean_all = sum(q["recall"] for q in per_query) / len(per_query)
    looped = [q for q in cost if q["rounds"] > 0]
    deltas = [r["recalled_delta"] for t in trace_rows for r in t["rounds"]]
    stats = {
        "avg_rounds": round(sum(q["rounds"] for q in cost) / len(cost), 3),
        "loop_ratio": round(len(looped) / len(cost), 3),
        "delta_dist": {str(d): deltas.count(d) for d in sorted(set(deltas))},
        "avg_latency_ms": round(sum(q["latency_ms"] for q in cost) / len(cost)),
        "tokens_per_query": {
            k: round(sum(q["tokens"][k] for q in cost) / len(cost)) for k in
            ("jev_in", "jev_out", "ds_in", "ds_out")},
    }
    sec_items = [q for q in per_query if q["secondary_total"]]
    sec_cov = sum(q["secondary_hit"] for q in sec_items) / \
        sum(q["secondary_total"] for q in sec_items) if sec_items else None
    print("-" * 60)
    print(f"循环统计: {json.dumps(stats, ensure_ascii=False)}")
    print(f"secondary_coverage={sec_cov:.3f}" if sec_cov is not None else "")
    print(f"总体 mean recall@{args.topk} = {mean_all:.3f} (primary 口径)")

    if args.trace and not args.replay:
        with open(args.trace, "w", encoding="utf-8") as f:
            for r in trace_rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"trace -> {args.trace}")

    if args.save:
        out_dir = BASE / "evals" / "results" / args.save
        out_dir.mkdir(parents=True, exist_ok=True)
        json.dump({"version": args.save, "time": datetime.now().isoformat(timespec="seconds"),
                   "replay": bool(args.replay), "slices": slices,
                   "adversarial_veto": {"ok": adv_ok,
                                      "trap_primary_hits": {q["id"]: q.get("trap_primary_hit") for q in adv}},
                   "secondary_coverage": round(sec_cov, 4) if sec_cov is not None else None,
                   "loop_stats": stats,
                   "mean_recall": round(mean_all, 4), "per_query": per_query},
                  open(out_dir / "recall_report.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"saved -> {out_dir / 'recall_report.json'}")
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
