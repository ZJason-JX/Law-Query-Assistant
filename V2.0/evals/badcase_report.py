# -*- coding: utf-8 -*-
"""生成 Badcase 文档：对 results/<version>/ 中 MOS<4.0 的样本汇总 query/召回/混淆/回答/评分/理由。

用法: python evals/badcase_report.py --version v1_doubao_qwen [--threshold 4.0] [--out Badcase文档1.0.md]
"""
import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
PROJ = BASE.parent
sys.path.insert(0, str(PROJ / "src"))

LAW_SLUG = {"民法典": "civil-law", "公司法": "company-law",
            "反不正当竞争法": "anti-unfair-competition-law", "消费者权益保护法": "consumer-protection-law"}


def expected_groups(item):
    groups = []
    for a in item["expected_articles"]:
        no = int(a["article"][1:-1])
        slug = LAW_SLUG[a["law"]]
        ids = {f"{slug}-{no}", f"{slug}-2019-{no}"} if slug == "anti-unfair-competition-law" else {f"{slug}-{no}"}
        groups.append((f"{a['law']}{a['article']}", ids))
    return groups


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--threshold", type=float, default=4.0)
    ap.add_argument("--out", default="Badcase文档1.0.md")
    args = ap.parse_args()

    vdir = BASE / "results" / args.version
    answers = {json.loads(l)["id"]: json.loads(l)["answer"] for l in open(vdir / "answers.jsonl", encoding="utf-8")}
    scores = {json.loads(l)["id"]: json.loads(l) for l in open(vdir / "scores.jsonl", encoding="utf-8")}
    dataset = {json.loads(l)["id"]: json.loads(l) for l in open(BASE / "dataset.jsonl", encoding="utf-8")}

    bad_ids = [i for i, s in scores.items() if s["mos"] < args.threshold]
    bad_ids.sort()
    if not bad_ids:
        print(f"无需输出：无 MOS<{args.threshold} 样本")
        return 0

    from pipeline import retrieve
    lines = [
        f"# Badcase 文档 1.0（{args.version}）",
        "",
        f"阈值：MOS < {args.threshold}；badcase 数：{len(bad_ids)}；生成/裁判配置见 results/{args.version}/summary.json",
        "",
    ]
    for iid in bad_ids:
        item = dataset[iid]
        sc = scores[iid]
        dims = sc["dimensions"]

        # 召回与混淆矩阵
        retrieved = retrieve(item["query"], 10)
        retrieved_ids = [a["id"] for a in retrieved]
        groups = expected_groups(item)
        tp = [lbl for lbl, ids in groups if retrieved_ids and (set(retrieved_ids) & ids)]
        fn = [lbl for lbl, ids in groups if not (set(retrieved_ids) & ids)]
        exp_labels = {lbl for lbl, _ in groups}
        fp = [r for r in retrieved if f"《{r['law']}》{r['article_no']}" not in exp_labels
              and all(f"{r['law']}{r['article_no']}" != lbl for lbl in exp_labels)]

        lines += [
            "---",
            "",
            f"## id {iid}（{item['difficulty']} / {item['scenario']}）",
            "",
            f"**Query**：{item['query']}",
            "",
            "### 召回法条（top-10）",
            "",
        ]
        for idx, a in enumerate(retrieved, 1):
            mark = " ✅期望" if any(a["id"] in ids for _, ids in groups) else ""
            hist = "（历史版本）" if a["status"] != "现行有效" else ""
            lines.append(f"{idx}. 《{a['law']}》{a['article_no']}{hist}{mark}")
        lines += [
            "",
            "### 混淆矩阵（检索 vs 期望）",
            "",
            f"- TP（期望且召回）：{len(tp)}  →  {tp or '无'}",
            f"- FN（期望未召回）：{len(fn)}  →  {fn or '无'}",
            f"- FP（召回非期望）：{len(fp)}",
            f"- 期望总数：{len(groups)}；recall@10 = {len(tp)/len(groups):.2f}",
            "",
            "### 模型回答",
            "",
            answers[iid],
            "",
            "### MOS 打分",
            "",
            f"准确性 {dims['准确性']} / 相关性 {dims['相关性']} / 完整性 {dims['完整性']} / "
            f"简洁性 {dims['简洁性']} / 安全性 {dims['安全性']}  →  **MOS {sc['mos']:.1f}**",
            "",
            "### 打分依据（judge）",
            "",
            sc["reason"],
            "",
        ]

    out = BASE / args.out
    open(out, "w", encoding="utf-8").write("\n".join(lines))
    print(f"OK {len(bad_ids)} 个 badcase -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
