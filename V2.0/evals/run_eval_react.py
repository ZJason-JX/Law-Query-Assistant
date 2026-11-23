# -*- coding: utf-8 -*-
"""v2.1 ReAct 端到端跑批：ReAct 检索 → Doubao 生成 → Qwen judge → 引用审计。

复用：pipeline.answer(react=trace) / run_eval.judge / verify_citations.{extract,quote_ratio}
确定性：intent 落盘 intent_cache_v2.jsonl；react 轮次复放 query_expansion_trace.jsonl；
        生成/评分 temperature=0 → 双跑逐条一致。
用法:
  python evals/run_eval_react.py --version v21_react_e2e [--limit N]
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent          # evals/
PROJ = BASE.parent                              # 法律问答助手2.0/
sys.path.insert(0, str(PROJ / "src"))
sys.path.insert(0, str(BASE))

_env = PROJ / ".env"
if not _env.exists() and (PROJ / ".env.example").exists():
    import shutil
    shutil.copyfile(PROJ / ".env.example", _env)
if _env.exists():
    for line in open(_env, encoding="utf-8"):
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            os.environ.setdefault(k, v)

from run_eval import DIMENSIONS, judge  # noqa: E402
from verify_citations import extract_citations, norm_art, norm_law, quote_ratio  # noqa: E402

DATASET = BASE / "dataset_v2.jsonl"
EXPAND = BASE / "query_expanded_v2.jsonl"
INTENT_CACHE = BASE / "intent_cache_v2.jsonl"
REACT_TRACE = BASE / "query_expansion_trace.jsonl"

SCENARIO2INTENT = {"构成要件与归责": "elements_liability", "法条精准检索": "statute_lookup",
                   "规则冲突与适用": "rule_conflict", "法律概念界定": "concept_definition",
                   "off_topic": "irrelevant"}


def quote_band(qr, in_ctx):
    if not in_ctx:
        return "outside_context"
    if qr is None:
        return "no_quote"
    return "verbatim" if qr >= 0.9 else ("paraphrase" if qr >= 0.6 else "unmatched")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--gen-provider", default="doubao")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--live-react", action="store_true",
                    help="线上路径：门控与追加轮实时调用 JEV/DeepSeek，不读 trace 复放")
    ap.add_argument("--intent-cache", default=str(INTENT_CACHE),
                    help="JEV 意图缓存 jsonl（默认 intent_cache_v2.jsonl）")
    args = ap.parse_args()

    out_dir = BASE / "results" / args.version
    out_dir.mkdir(parents=True, exist_ok=True)
    judge_prompt = (BASE / "judge_prompt.md").read_text(encoding="utf-8")

    items = [json.loads(l) for l in open(DATASET, encoding="utf-8")]
    if args.limit:
        items = items[:args.limit]
    item_by_id = {it["id"]: it for it in items}

    expansions = {json.loads(l)["id"]: json.loads(l)["variants"]
                  for l in open(EXPAND, encoding="utf-8")}
    react_traces = {json.loads(l)["query_id"]: json.loads(l)
                    for l in open(REACT_TRACE, encoding="utf-8")}
    intent_fp = Path(args.intent_cache)
    intents = {}
    if intent_fp.exists():
        for l in open(intent_fp, encoding="utf-8"):
            r = json.loads(l)
            intents[r["id"]] = r

    done_ans, done_scores = {}, {}
    ans_fp, score_fp = out_dir / "answers.jsonl", out_dir / "scores.jsonl"
    for fp, store in ((ans_fp, done_ans), (score_fp, done_scores)):
        if fp.exists():
            for l in open(fp, encoding="utf-8"):
                r = json.loads(l)
                store[r["id"]] = r

    from pipeline import answer as gen_answer
    chunk_map = {json.loads(l)["id"]: json.loads(l)
                 for l in open(PROJ / "src" / "corpus" / "chunks" / "chunks.jsonl", encoding="utf-8")}

    with open(ans_fp, "a", encoding="utf-8") as fa, open(score_fp, "a", encoding="utf-8") as fs:
        for item in items:
            iid = item["id"]
            if iid in done_scores:
                print(f"id={iid} 已有评分，跳过")
                continue
            rec = done_ans.get(iid, {})
            ans = rec.get("answer")
            if not ans:
                print(f"id={iid} 生成中...")
                t0 = time.time()
                res = gen_answer(item["query"], args.gen_provider,
                                 variants=expansions.get(iid, []),
                                 intent=intents.get(iid),
                                 react=True if args.live_react else react_traces.get(iid, True))
                gen_ms = round((time.time() - t0) * 1000)
                if iid not in intents:
                    ic = {k: res[k] for k in ("intent", "confidence", "probabilities",
                                              "false_premise", "jev_model", "jev_latency_ms",
                                              "jev_usage") if k in res}
                    intents[iid] = {"id": iid, **ic}
                    with open(intent_fp, "a", encoding="utf-8") as fi:
                        fi.write(json.dumps(intents[iid], ensure_ascii=False) + "\n")
                ans = res.pop("answer")
                rec = {"id": iid, "query": item["query"], "answer": ans,
                       "gen_latency_ms": gen_ms, **res}
                fa.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fa.flush()
            print(f"id={iid} 评判中...")
            retrieved = None
            rids = rec.get("retrieved_ids")
            if rids:
                retrieved = [chunk_map[r] for r in rids if r in chunk_map]
            j = judge(judge_prompt, item, ans, retrieved=retrieved)
            mos = sum(j[d] for d in DIMENSIONS) / 5
            fs.write(json.dumps({"id": iid, "dimensions": {d: j[d] for d in DIMENSIONS},
                                 "mos": mos, "reason": j.get("评分理由", "")},
                                ensure_ascii=False) + "\n")
            fs.flush()
            print(f"  -> MOS {mos:.1f}  {[j[d] for d in DIMENSIONS]}")

    # ---------- 汇总 ----------
    scores = [json.loads(l) for l in open(score_fp, encoding="utf-8")]
    answers = {json.loads(l)["id"]: json.loads(l) for l in open(ans_fp, encoding="utf-8")}

    def slice_stats(rows):
        if not rows:
            return {"n": 0}
        return {"n": len(rows), "mos": round(sum(s["mos"] for s in rows) / len(rows), 3),
                "dim_avg": {d: round(sum(s["dimensions"][d] for s in rows) / len(rows), 3)
                            for d in DIMENSIONS}}

    legal = [s for s in scores if item_by_id[s["id"]]["difficulty"] != "off_topic"]
    off = [s for s in scores if item_by_id[s["id"]]["difficulty"] == "off_topic"]

    # 意图混淆 + off_topic 拒答
    matrix, intent_detail = {}, []
    for iid, a in sorted(answers.items()):
        it = item_by_id.get(iid)
        if it is None:
            continue
        exp_int = SCENARIO2INTENT.get(it["scenario"])
        got = a.get("intent")
        matrix[f"{exp_int}->{got}"] = matrix.get(f"{exp_int}->{got}", 0) + 1
        intent_detail.append({"id": iid, "expected": exp_int, "intent": got,
                              "confidence": a.get("confidence"),
                              "false_premise": a.get("false_premise"),
                              "ok": got == exp_int})
    legal_int = [d for d in intent_detail if d["expected"] != "irrelevant"]
    intent_acc = sum(d["ok"] for d in legal_int) / len(legal_int) if legal_int else 0
    refused = [d["id"] for d in intent_detail
               if d["expected"] == "irrelevant" and "本助手仅回答" in answers[d["id"]]["answer"]]

    # ---------- 引用审计（quote_ratio 分级） ----------
    bands = {"verbatim": 0, "paraphrase": 0, "unmatched": 0,
             "outside_context": 0, "no_quote": 0}
    n_cit, ungrounded = 0, 0
    cit_detail = []
    for iid, a in sorted(answers.items()):
        if item_by_id[iid]["difficulty"] == "off_topic":
            continue
        ctx = [chunk_map[r] for r in a.get("retrieved_ids", []) if r in chunk_map]
        ctx_keys = {(norm_law(x["law"]), norm_art(x["article_no"])) for x in ctx}
        rows = []
        for c in extract_citations(a["answer"]):
            key = (norm_law(c.get("law", "")), norm_art(c.get("article_no", "")))
            in_ctx = key in ctx_keys
            art = next((x for x in ctx if (norm_law(x["law"]), norm_art(x["article_no"])) == key), None)
            qr = round(quote_ratio(c["quote"], art["text"]), 3) if art and c.get("quote") else None
            band = quote_band(qr, in_ctx)
            bands[band] += 1
            n_cit += 1
            ungrounded += 0 if in_ctx else 1
            rows.append({"cit": f"{c.get('law')}{c.get('article_no')}", "band": band, "qr": qr})
        cit_detail.append({"id": iid, "n": len(rows), "citations": rows})
    cit_report = {"n_citations": n_cit, "ungrounded": ungrounded,
                  "ungrounded_rate": round(ungrounded / n_cit, 3) if n_cit else None,
                  "quote_bands": bands, "detail": cit_detail}

    # 循环开销（answer 元数据）
    looped = [a for a in answers.values() if a.get("react_rounds")]
    cost = {"avg_react_rounds": round(sum(a.get("react_rounds", 0) for a in answers.values()
                                          if item_by_id[a["id"]]["difficulty"] != "off_topic") /
                                    max(1, len(legal)), 3),
            "avg_gen_latency_ms": round(sum(a.get("gen_latency_ms", 0) for a in answers.values())
                                        / max(1, len(answers))),
            "stop_reasons": {}}
    for a in answers.values():
        if a.get("react_stop"):
            cost["stop_reasons"][a["react_stop"]] = cost["stop_reasons"].get(a["react_stop"], 0) + 1

    summary = {
        "version": args.version, "gen_provider": args.gen_provider,
        "legal_slice": slice_stats(legal), "off_topic_slice": slice_stats(off),
        "intent": {"accuracy_legal": round(intent_acc, 3),
                   "off_topic_refused": refused},
        "citation_audit": {k: v for k, v in cit_report.items() if k != "detail"},
        "react_cost": cost,
    }
    json.dump(summary, open(out_dir / "summary.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump({"confusion": matrix, "detail": intent_detail},
              open(out_dir / "intent_report.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(cit_report, open(out_dir / "citation_report.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print(f"\n{args.version}: legal n={len(legal)} MOS={summary['legal_slice'].get('mos')}")
    print("维度均值:", summary["legal_slice"].get("dim_avg"))
    print(f"意图准确率={intent_acc:.3f} off_topic拒答={refused}")
    print(f"引用: {cit_report['n_citations']}条 ungrounded={cit_report['ungrounded']} bands={bands}")
    print(f"react成本: {cost}")
    print(f"saved -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
