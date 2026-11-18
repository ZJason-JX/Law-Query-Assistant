# -*- coding: utf-8 -*-
"""回溯重判：用当前 judge_prompt 对已有版本的 answers.jsonl 重新打分（不重新生成）。

用法: python evals/rejudge.py --src v1_doubao_qwen --dst v1.0_judge_fixed
产物: results/<dst>/scores.jsonl + summary.json（answers 复制软链接式引用，只复制文件）
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
PROJ = BASE.parent
sys.path.insert(0, str(PROJ / "src"))
sys.path.insert(0, str(BASE))

for line in open(PROJ / ".env", encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1)
        os.environ.setdefault(k, v)

from run_eval import judge, DIMENSIONS, JUDGE_MODEL


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    args = ap.parse_args()

    src_dir, dst_dir = BASE / "results" / args.src, BASE / "results" / args.dst
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_dir / "answers.jsonl", dst_dir / "answers.jsonl")
    ir = src_dir / "intent_report.json"
    if ir.exists():
        shutil.copy2(ir, dst_dir / "intent_report.json")

    judge_prompt = (BASE / "judge_prompt.md").read_text(encoding="utf-8")
    items = {json.loads(l)["id"]: json.loads(l)
             for l in open(BASE / "dataset.jsonl", encoding="utf-8")}
    answers = [json.loads(l) for l in open(dst_dir / "answers.jsonl", encoding="utf-8")]
    chunk_map = {json.loads(l)["id"]: json.loads(l)
                 for l in open(PROJ / "src" / "corpus" / "chunks" / "chunks.jsonl", encoding="utf-8")}

    with open(dst_dir / "scores.jsonl", "w", encoding="utf-8") as fs:
        for a in answers:
            rids = a.get("retrieved_ids")
            retrieved = [chunk_map[r] for r in rids if r in chunk_map] if rids else None
            j = judge(judge_prompt, items[a["id"]], a["answer"], retrieved=retrieved)
            mos = sum(j[d] for d in DIMENSIONS) / 5
            fs.write(json.dumps({"id": a["id"], "dimensions": {d: j[d] for d in DIMENSIONS},
                                 "mos": mos, "reason": j.get("评分理由", "")},
                                ensure_ascii=False) + "\n")
            fs.flush()
            print(f"id={a['id']} -> MOS {mos:.1f}  {[j[d] for d in DIMENSIONS]}")

    scores = [json.loads(l) for l in open(dst_dir / "scores.jsonl", encoding="utf-8")]
    legal = [s for s in scores if items[s["id"]]["difficulty"] != "off_topic"]
    off = [s for s in scores if items[s["id"]]["difficulty"] == "off_topic"]

    def agg(rows):
        if not rows:
            return {"n": 0}
        return {"n": len(rows), "mos": round(sum(s["mos"] for s in rows) / len(rows), 3),
                "dim_avg": {d: round(sum(s["dimensions"][d] for s in rows) / len(rows), 3)
                            for d in DIMENSIONS}}

    summary = {"version": args.dst, "rejudged_from": args.src, "judge_model": JUDGE_MODEL,
               "judge_prompt": "fixed_corpus_aware", "legal_slice": agg(legal),
               "off_topic_slice": agg(off)}
    json.dump(summary, open(dst_dir / "summary.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n{args.dst}: legal MOS={summary['legal_slice'].get('mos')}")
    print("维度均值:", summary["legal_slice"].get("dim_avg"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
