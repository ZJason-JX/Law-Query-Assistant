# -*- coding: utf-8 -*-
"""跑批脚本：dataset.jsonl 20 条 → 生成（豆包/deepseek）→ judge（qwen）→ 按版本落盘 results/<version>/。

用法: python evals/run_eval.py --version v1_doubao_qwen [--gen-provider doubao] [--limit N]
产物:
  results/<version>/answers.jsonl   每条 {id, query, answer}
  results/<version>/scores.jsonl    每条 {id, 五维分, 理由}
  results/<version>/summary.json    汇总 MOS + 维度均值
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent          # evals/
PROJ = BASE.parent                              # 法律问答助手2.0/
sys.path.insert(0, str(PROJ / "src"))

# ---- .env ----
for line in open(PROJ / ".env", encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1)
        os.environ.setdefault(k, v)

DIMENSIONS = ["准确性", "相关性", "完整性", "简洁性", "安全性"]
JUDGE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
JUDGE_MODEL = os.environ.get("QWEN_MODEL", "qwen-plus")


def call_json(url: str, key_env: str, model: str, messages: list, temperature: float = 0.0) -> dict:
    body = json.dumps({"model": model, "messages": messages, "temperature": temperature,
                       "response_format": {"type": "json_object"}}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {os.environ[key_env]}", "Content-Type": "application/json"})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"LLM 调用失败: {last}")


def judge(judge_prompt: str, item: dict, answer: str, retrieved: list = None) -> dict:
    arts = [f"{a['law']}{a['article']}（{a['note']}）" for a in item["expected_articles"]]
    user = (f"query：{item['query']}\n\n"
            f"expected_articles：\n" + "\n".join(arts) + "\n\n")
    if retrieved:
        ctx = [f"[{a['law']}{a['article_no']}]{'【历史版本】' if a['status'] != '现行有效' else ''}{a['text']}"
               for a in retrieved]
        user += "检索上下文（被评答案实际拿到的法条）：\n" + "\n\n".join(ctx) + "\n\n"
    if item.get("adversarial_trap"):
        user += f"adversarial_trap：{item['adversarial_trap']}\n\n"
    user += f"answer：{answer}"
    d = call_json(JUDGE_URL, "QWEN_API_KEY", JUDGE_MODEL,
                  [{"role": "system", "content": judge_prompt},
                   {"role": "user", "content": user}])
    return json.loads(d["choices"][0]["message"]["content"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="结果版本目录名，如 v1_doubao_qwen")
    ap.add_argument("--gen-provider", default="doubao", choices=["doubao", "deepseek"])
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（调试用）")
    args = ap.parse_args()

    out_dir = BASE / "results" / args.version
    out_dir.mkdir(parents=True, exist_ok=True)

    judge_prompt = (BASE / "judge_prompt.md").read_text(encoding="utf-8")
    items = [json.loads(l) for l in open(BASE / "dataset.jsonl", encoding="utf-8")]
    if args.limit:
        items = items[:args.limit]

    # 评测模式：扩展变体与 JEV 意图均离线落盘复用，保证两轮跑批确定性
    expansions = {}
    exp_fp = BASE / "query_expanded_v0_3.jsonl"
    if exp_fp.exists():
        for l in open(exp_fp, encoding="utf-8"):
            r = json.loads(l)
            expansions[r["id"]] = r["variants"]
    intents = {}
    int_fp = BASE / "intent_cache.jsonl"
    if int_fp.exists():
        for l in open(int_fp, encoding="utf-8"):
            r = json.loads(l)
            intents[r["id"]] = r

    # 断点续跑
    done_ans, done_scores = {}, {}
    ans_fp = out_dir / "answers.jsonl"
    score_fp = out_dir / "scores.jsonl"
    for fp, store in ((ans_fp, done_ans), (score_fp, done_scores)):
        if fp.exists():
            for l in open(fp, encoding="utf-8"):
                r = json.loads(l)
                store[r["id"]] = r

    from pipeline import answer as gen_answer  # 延迟导入：加载 BGE-M3 较重

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
                res = gen_answer(item["query"], args.gen_provider,
                                 variants=expansions.get(iid, []),
                                 intent=intents.get(iid))
                if iid not in intents:
                    ic = {k: res[k] for k in ("intent", "confidence", "probabilities",
                                              "false_premise", "jev_model", "jev_latency_ms",
                                              "jev_usage") if k in res}
                    intents[iid] = {"id": iid, **ic}
                    with open(int_fp, "a", encoding="utf-8") as fi:
                        fi.write(json.dumps(intents[iid], ensure_ascii=False) + "\n")
                ans = res.pop("answer")
                rec = {"id": iid, "query": item["query"], "answer": ans, **res}
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
            try:
                sys.path.insert(0, str(PROJ))
                from server import badcases as _bc
                n_bc = len(_bc.collect_eval(
                    item, {**rec, "answer": ans}, {d: j[d] for d in DIMENSIONS},
                    mos, j.get("评分理由", ""), chunk_map, version=args.version))
                if n_bc:
                    print(f"  -> badcase +{n_bc}")
            except Exception as e:
                print(f"  -> badcase 采集异常（不影响跑批）: {e}")
            print(f"  -> MOS {mos:.1f}  {[j[d] for d in DIMENSIONS]}")

    # 汇总：off_topic 单独切片，不并入原 20 条口径
    SCENARIO2INTENT = {"构成要件与归责": "elements_liability", "法条精准检索": "statute_lookup",
                       "规则冲突与适用": "rule_conflict", "法律概念界定": "concept_definition",
                       "off_topic": "irrelevant"}
    scores = [json.loads(l) for l in open(score_fp, encoding="utf-8")]
    answers = {json.loads(l)["id"]: json.loads(l) for l in open(ans_fp, encoding="utf-8")}
    item_by_id = {it["id"]: it for it in items}

    def slice_stats(rows):
        if not rows:
            return {"n": 0}
        return {"n": len(rows), "mos": round(sum(s["mos"] for s in rows) / len(rows), 3),
                "dim_avg": {d: round(sum(s["dimensions"][d] for s in rows) / len(rows), 3)
                            for d in DIMENSIONS}}

    legal = [s for s in scores if item_by_id[s["id"]]["difficulty"] != "off_topic"]
    off = [s for s in scores if item_by_id[s["id"]]["difficulty"] == "off_topic"]

    # 意图混淆矩阵 + confidence 直方图
    matrix, histogram = {}, [0] * 10
    intent_detail = []
    for iid, a in sorted(answers.items()):
        it = item_by_id.get(iid)
        if it is None:
            continue
        exp_int = SCENARIO2INTENT.get(it["scenario"])
        got = a.get("intent")
        conf = a.get("confidence")
        key = f"{exp_int}->{got}"
        matrix[key] = matrix.get(key, 0) + 1
        if conf is not None:
            histogram[min(9, int(conf * 10))] += 1
        intent_detail.append({"id": iid, "expected": exp_int, "intent": got,
                              "confidence": conf, "false_premise": a.get("false_premise"),
                              "ok": got == exp_int})
    legal_int = [d for d in intent_detail if d["expected"] != "irrelevant"]
    intent_acc = sum(d["ok"] for d in legal_int) / len(legal_int) if legal_int else 0
    id20 = next((d for d in intent_detail if d["id"] == 20), {})
    refused = [d["id"] for d in intent_detail if d["expected"] == "irrelevant"
               and answers[d["id"]].get("prompt_file") == "irrelevant.md"]
    mis_irrelevant = [d["id"] for d in legal_int if d["intent"] == "irrelevant"]

    summary = {
        "version": args.version,
        "gen_provider": args.gen_provider,
        "judge_model": JUDGE_MODEL,
        "legal_slice": slice_stats(legal),
        "off_topic_slice": slice_stats(off),
        "intent": {
            "accuracy_legal20": round(intent_acc, 3),
            "id20": {"intent": id20.get("intent"), "false_premise": id20.get("false_premise")},
            "off_topic_refused": refused,
            "legal_misclassified_irrelevant": mis_irrelevant,
        },
        "config": json.load(open(PROJ / "src" / "retrieval_config.json", encoding="utf-8")),
    }
    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    with open(out_dir / "intent_report.json", "w", encoding="utf-8") as f:
        json.dump({"confusion": matrix,
                   "confidence_histogram_0_1": histogram,
                   "detail": intent_detail}, f, ensure_ascii=False, indent=1)

    print(f"\n{args.version}: legal n={len(legal)} MOS={summary['legal_slice'].get('mos')}")
    print("维度均值:", summary["legal_slice"].get("dim_avg"))
    print(f"意图准确率(legal)={summary['intent']['accuracy_legal20']} "
          f"id20={summary['intent']['id20']} off_topic拒答={refused} 误判irrelevant={mis_irrelevant}")
    print(f"saved -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
