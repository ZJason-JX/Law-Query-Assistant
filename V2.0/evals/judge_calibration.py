# -*- coding: utf-8 -*-
"""Judge 校准（A 环节，不动产线代码）：

V2.0 xlsx Sheet2 的 5 条 query × 3 个模型回答（带五维人工分）
→ 用 judge_prompt.md + dataset 的 expected_articles 让 qwen-plus 重评
→ 对比：逐维 exact-match / ±1 一致率、mean |Δ|、Mos 的 Pear 相关。

用法: python evals/judge_calibration.py
"""
import json
import os
import sys
from pathlib import Path

import openpyxl

BASE = Path(__file__).resolve().parent
PROJ = BASE.parent
sys.path.insert(0, str(BASE))

for line in open(PROJ / ".env", encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1)
        os.environ.setdefault(k, v)

from run_eval import judge, DIMENSIONS  # noqa: E402  复用产线 judge 调用

XLSX = Path(r"F:\工作台\产品\法律知识问答助手V2.0\模型回答对比（模型参考打分）.xlsx")
DIMS_COLS = {  # 每模型五个维度分数列
    "DP": 5, "doubao-lite": 12, "doubao-pro": 19,
}
ANSWER_COL = {"DP": 4, "doubao-lite": 11, "doubao-pro": 18}


def main() -> int:
    dataset = [json.loads(l) for l in open(BASE / "dataset.jsonl", encoding="utf-8")]
    by_query = {i["query"].strip(): i for i in dataset}
    judge_prompt = (BASE / "judge_prompt.md").read_text(encoding="utf-8")

    ws = openpyxl.load_workbook(XLSX, data_only=True)["Sheet2"]
    cases = []
    for r in range(1, 6):
        q = ws.cell(row=r, column=1).value.strip()
        item = by_query[q]
        for m in ("DP", "doubao-lite", "doubao-pro"):
            ans = ws.cell(row=r, column=ANSWER_COL[m]).value
            human = [ws.cell(row=r, column=DIMS_COLS[m] + i).value for i in range(5)]
            cases.append({"id": item["id"], "model": m, "item": item,
                          "answer": str(ans), "human": human})

    rows = []
    print(f"{'case':<28} {'人工五维':<22} {'judge五维':<22} Δ")
    for c in cases:
        j = judge(judge_prompt, c["item"], c["answer"])
        jdims = [j[d] for d in DIMENSIONS]
        delta = sum(abs(a - b) for a, b in zip(jdims, c["human"]))
        rows.append({"eval_id": c["id"], "model": c["model"],
                     "human": c["human"], "judge": jdims, "reason": j.get("评分理由", "")})
        print(f"id{c['id']}/{c['model']:<14} {str(c['human']):<22} {str(jdims):<22} {delta}")

    exact = sum(sum(1 for a, b in zip(r["judge"], r["human"]) if a == b) for r in rows) / (len(rows) * 5)
    within1 = sum(sum(1 for a, b in zip(r["judge"], r["human"]) if abs(a - b) <= 1) for r in rows) / (len(rows) * 5)
    mad = sum(sum(abs(a - b) for a, b in zip(r["judge"], r["human"])) for r in rows) / (len(rows) * 5)
    hm = [sum(r["human"]) / 5 for r in rows]
    jm = [sum(r["judge"]) / 5 for r in rows]
    n = len(rows)
    mh, mj = sum(hm) / n, sum(jm) / n
    pearson = sum((a - mh) * (b - mj) for a, b in zip(hm, jm)) / (
        (sum((a - mh) ** 2 for a in hm) * sum((b - mj) ** 2 for b in jm)) ** 0.5)

    out = {
        "n_cases": len(rows),
        "per_dim_exact_match": round(exact, 3),
        "per_dim_within_one": round(within1, 3),
        "mean_abs_diff": round(mad, 3),
        "mos_pearson": round(pearson, 3),
        "judge_model": os.environ.get("QWEN_MODEL", "qwen-plus"),
        "rows": rows,
    }
    odir = BASE / "results" / "judge_calibration"
    odir.mkdir(parents=True, exist_ok=True)
    out_name = "calibration_fixed.json" if "语料清单" in judge_prompt else "calibration.json"
    with open(odir / out_name, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\nexact={exact:.1%}  ±1 一致率={within1:.1%}  mean|Δ|={mad:.2f}  MOS Pearson={pearson:.3f}")
    print(f"saved -> {odir / out_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
