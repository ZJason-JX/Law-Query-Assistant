# -*- coding: utf-8 -*-
"""ReAct 线上检索多次采样方差：v20_react + v22_react_live + v23_react_live_r1..r3。
逐题 5 次采样的 primary recall 分布 → evals/results/v23_react_variance.md"""
import json
import statistics as st
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from recall_check import art_groups  # noqa: E402

R = BASE / "results"
ds = {int(r["id"]): r for r in (json.loads(l) for l in open(BASE / "dataset_v2.jsonl", encoding="utf-8"))}
legal = [i for i in ds if ds[i].get("expected_articles")]


def from_report(ver):
    rep = json.load(open(R / ver / "recall_report.json", encoding="utf-8"))
    return {int(q["id"]): {"recall": q["recall"], "rounds": q["rounds"],
                           "trap": q.get("trap_primary_hit")} for q in rep["per_query"]}


def from_answers(ver):
    out = {}
    for l in open(R / ver / "answers.jsonl", encoding="utf-8"):
        r = json.loads(l)
        i = int(r["id"])
        if i not in legal:
            continue
        got = set(r["retrieved_ids"])
        prim = [a for a in ds[i]["expected_articles"] if a.get("level", "primary") == "primary"]
        need = art_groups(prim)
        rec = sum(1 for g in need if got & g) / len(need)
        trap = bool(got & art_groups([ds[i]["trap_primary"]])[0]) if ds[i].get("trap_primary") else None
        out[i] = {"recall": rec, "rounds": int(r["react_rounds"]), "trap": trap}
    return out


samples = {"v20": from_report("v20_react"), "v22": from_answers("v22_react_live")}
for k in (1, 2, 3):
    d = R / f"v23_react_live_r{k}" / "recall_report.json"
    if d.exists():
        samples[f"r{k}"] = from_report(f"v23_react_live_r{k}")

names = list(samples)
w = open(R / "v23_react_variance.md", "w", encoding="utf-8")
w.write(f"# ReAct 线上检索多次采样方差\n\n样本：{len(names)} 次独立线上运行（{', '.join(names)}），"
        "每次 JEV 门控 + DeepSeek 缺口查询实时调用。\n\n")

w.write("## 总体\n\n| 样本 | mean primary recall | 平均轮数 |\n|---|---|---|\n")
per_sample_mean = {}
for n in names:
    m = st.mean(samples[n][i]["recall"] for i in legal)
    rd = st.mean(samples[n][i]["rounds"] for i in legal)
    per_sample_mean[n] = m
    w.write(f"| {n} | {m:.3f} | {rd:.2f} |\n")
w.write(f"\n5 次采样均值 {st.mean(per_sample_mean.values()):.3f}，"
        f"标准差 {st.stdev(per_sample_mean.values()):.3f}，"
        f"范围 [{min(per_sample_mean.values()):.3f}, {max(per_sample_mean.values()):.3f}]。\n")

w.write("\n## 逐题\n\n| id | 难度 | " + " | ".join(names) + " | 均值 | 范围 |\n|---|---|" + "---|" * (len(names) + 2) + "\n")
unstable = []
for i in legal:
    rs = [samples[n][i]["recall"] for n in names]
    rng = max(rs) - min(rs)
    if rng > 0:
        unstable.append(i)
    w.write(f"| {i} | {ds[i]['difficulty']} | " + " | ".join(f"{x:.2f}" for x in rs) +
            f" | {st.mean(rs):.2f} | {rng:.2f} |\n")
w.write(f"\n跨样本 recall 有波动的题：{len(unstable)}/30（{['id%d' % i for i in unstable]}）。\n")

w.write("\n## 切片（每次采样的切片均值）\n\n| 难度 | " + " | ".join(names) + " | 均值±sd |\n|---|---|" + "---|" * (len(names) + 1) + "\n")
for diff in ("显性事实", "隐性事实", "可解释推理", "对抗样本", "复合问题"):
    sub = [i for i in legal if ds[i]["difficulty"] == diff]
    if not sub:
        continue
    ms = [st.mean(samples[n][i]["recall"] for i in sub) for n in names]
    w.write(f"| {diff} (n={len(sub)}) | " + " | ".join(f"{m:.3f}" for m in ms) +
            f" | {st.mean(ms):.3f}±{st.stdev(ms):.3f} |\n")

w.write("\n## 对抗否决与轮数\n\n- trap_primary 命中（每次采样）：")
adv = [i for i in legal if ds[i].get("trap_primary")]
for i in adv:
    w.write(f"\n  - id{i}: " + ", ".join(f"{n}={'✓' if samples[n][i]['trap'] else '✗'}" for n in names))
w.write("\n\n- 各题轮数跨样本分布：")
for i in legal:
    rs = [samples[n][i]["rounds"] for n in names]
    if len(set(rs)) > 1:
        w.write(f"\n  - id{i}: {rs}")
w.write("\n")
w.close()
print("samples:", names)
print("per-sample mean:", {n: round(per_sample_mean[n], 3) for n in names})
print(f"mean {st.mean(per_sample_mean.values()):.3f} sd {st.stdev(per_sample_mean.values()):.3f}")
print("unstable:", unstable)
print("-> evals/results/v23_react_variance.md")
