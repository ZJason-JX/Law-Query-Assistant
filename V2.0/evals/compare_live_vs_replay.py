# -*- coding: utf-8 -*-
"""线上 ReAct 路径（v22_react_live）vs 复放路径（v21_react_e2e r1/r2）逐条对比文档。

落盘 results/v22_react_live/COMPARISON.md。纯读文件，不调用任何模型。
"""
import json
import statistics as st
from pathlib import Path

BASE = Path(__file__).resolve().parent
PROJ = BASE.parent
R = BASE / "results"
DIMS = ["准确性", "相关性", "完整性", "简洁性", "安全性"]
SLUG = {"民法典": "civil-law", "公司法": "company-law", "反不正当竞争法": "anti-unfair-competition-law",
        "消费者权益保护法": "consumer-protection-law", "劳动法": "labor-law", "劳动合同法": "labor-contract-law"}


def jl(fp):
    return [json.loads(l) for l in open(fp, encoding="utf-8")]


ds = {r["id"]: r for r in jl(BASE / "dataset_v2.jsonl")}
chunks = {r["id"]: r for r in jl(PROJ / "src" / "corpus" / "chunks" / "chunks.jsonl")}
trace = {r["query_id"]: r for r in jl(BASE / "query_expansion_trace.jsonl")}


def load(ver):
    a = {r["id"]: r for r in jl(R / ver / "answers.jsonl")}
    s = {r["id"]: r for r in jl(R / ver / "scores.jsonl")}
    return a, s


live_a, live_s = load("v22_react_live")
r1_a, r1_s = load("v21_react_e2e")
r2_a, r2_s = load("v21_react_e2e_r2")


def groups(arts):
    out = []
    for a in arts:
        no = int(a["article"][1:-1])
        g = {f"{SLUG[a['law']]}-{no}"}
        if a["law"] == "反不正当竞争法":
            g.add(f"anti-unfair-competition-law-2019-{no}")
        out.append(g)
    return out


def primary_recall(item, ids):
    prim = [a for a in item["expected_articles"] if a.get("level", "primary") == "primary"]
    g = groups(prim)
    return sum(1 for x in g if set(ids) & x) / len(g) if g else None


def trap_hit(item, ids):
    tp = item.get("trap_primary")
    return bool(set(ids) & groups([tp])[0]) if tp else None


def name(cid):
    c = chunks.get(cid, {})
    return f"{c.get('law', '?')}{c.get('article_no', '?')}"


legal = sorted(i for i in ds if ds[i]["difficulty"] != "off_topic")
rows, diffs = [], []
for i in legal:
    it = ds[i]
    la, ra = live_a[i], r1_a[i]
    lids, rids = la.get("retrieved_ids", []), ra.get("retrieved_ids", [])
    same_set, same_order = set(lids) == set(rids), lids == rids
    ov = len(set(lids) & set(rids))
    tr = trace[i]
    lg = la.get("react_gates") or []
    rg = tr["gates"]
    suff_l = lg[0]["sufficient"] if lg else None
    suff_r = rg[0]["sufficient"] if rg else None
    lrounds = la.get("react_rounds_log") or []
    qmatch = [lrounds[k]["new_query"] == tr["rounds"][k]["new_query"]
              for k in range(min(len(lrounds), len(tr["rounds"])))]
    pr_l, pr_r = primary_recall(it, lids), primary_recall(it, rids)
    mos_r1, mos_r2, mos_l = r1_s[i]["mos"], r2_s[i]["mos"], live_s[i]["mos"]
    rows.append(dict(id=i, diff=it["difficulty"], rounds_r=len(tr["rounds"]), rounds_l=la.get("react_rounds", 0),
                     stop_r=tr["stop_reason"], stop_l=la.get("react_stop"), suff_r=suff_r, suff_l=suff_l,
                     ov=ov, same_set=same_set, same_order=same_order, pr_r=pr_r, pr_l=pr_l,
                     th_r=trap_hit(it, rids), th_l=trap_hit(it, lids),
                     mos_r1=mos_r1, mos_r2=mos_r2, mos_l=mos_l, qmatch=qmatch,
                     lat_r=ra.get("gen_latency_ms"), lat_l=la.get("gen_latency_ms")))
    if not same_set:
        add = [name(x) for x in lids if x not in rids]
        rem = [name(x) for x in rids if x not in lids]
        diffs.append((i, add, rem, pr_r, pr_l, lg, lrounds, tr))


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else float("nan")


def slice_rows(rs, d):
    return [r for r in rs if r["diff"] == d]


n = len(rows)
out = []
w = out.append
w("# 线上 ReAct 路径 vs 复放路径：逐条对比\n")
w("对象：`pipeline.answer(react=True)` 实时跑 JEV 门控 + DeepSeek 缺口查询（`v22_react_live`），"
  "对照 `v21_react_e2e` 用 trace 复放的两次运行（r1/r2）。\n")
w("## 0. 对比口径与混杂因素\n")
w("- **相同**：评测集 dataset_v2（30 法律题）、离线固化的扩展变体、意图缓存 `intent_cache_v2.jsonl`、"
  "检索与 RRF 参数、生成模型 Doubao（temperature 0）、Qwen 评审与评审 prompt。")
w("- **唯一的设计差异**：ReAct 的门控分数与缺口查询，复放组读 trace，线上组实时调用。")
w("- **混杂因素 1（非设计）**：线上组跑在免责声明加入 prompt 之后，答案末尾多一行固定提示，"
  "可能小幅影响简洁性与 MOS；v21 两次运行没有这一行。")
w("- **混杂因素 2**：Doubao 在 temperature 0 下本身有措辞级抖动（r1 与 r2 的 MOS 差即噪声底，见 §3）。\n")

w("## 1. 路径等价性（检索层）\n")
w("| 指标 | 数值 |\n|---|---|")
w(f"| top-10 条文集合完全一致 | {sum(r['same_set'] for r in rows)}/{n} |")
w(f"| top-10 集合与顺序完全一致 | {sum(r['same_order'] for r in rows)}/{n} |")
w(f"| 平均 top-10 重合条数 | {mean([r['ov'] for r in rows]):.2f}/10 |")
w(f"| 追加轮数完全一致 | {sum(r['rounds_r'] == r['rounds_l'] for r in rows)}/{n} |")
w(f"| 终止原因完全一致 | {sum(r['stop_r'] == r['stop_l'] for r in rows)}/{n} |")
allq = [m for r in rows for m in r["qmatch"]]
w(f"| 缺口查询文本逐字一致（可比较轮次中） | {sum(allq)}/{len(allq)} |")
sd = [abs(r["suff_l"] - r["suff_r"]) for r in rows if r["suff_l"] is not None and r["suff_r"] is not None]
w(f"| 首轮 sufficient 分数平均漂移 | {mean(sd):.3f}（最大 {max(sd):.2f}） |")
w(f"| 首轮 sufficient 与 0.5 阈值同侧 | {sum((r['suff_l'] < 0.5) == (r['suff_r'] < 0.5) for r in rows if r['suff_l'] is not None)}/{n} |\n")

w("## 2. 召回（primary 口径）与对抗否决\n")
w("| 切片 | n | 复放 recall | 线上 recall |\n|---|---|---|---|")
for d in ["显性事实", "隐性事实", "可解释推理", "对抗样本", "复合问题"]:
    sr = slice_rows(rows, d)
    w(f"| {d} | {len(sr)} | {mean([r['pr_r'] for r in sr]):.3f} | {mean([r['pr_l'] for r in sr]):.3f} |")
w(f"| **总体** | {n} | **{mean([r['pr_r'] for r in rows]):.3f}** | **{mean([r['pr_l'] for r in rows]):.3f}** |")
adv = slice_rows(rows, "对抗样本")
w(f"\n对抗否决（trap_primary 命中）：复放 {sum(bool(r['th_r']) for r in adv)}/{len(adv)}，线上 {sum(bool(r['th_l']) for r in adv)}/{len(adv)}。\n")

w("## 3. 生成质量（Qwen 评审，五维）\n")
w("| 指标 | v21 r1 | v21 r2 | 复放均值 | 线上 |\n|---|---|---|---|---|")
w(f"| MOS | {mean([r['mos_r1'] for r in rows]):.3f} | {mean([r['mos_r2'] for r in rows]):.3f} | "
  f"{(mean([r['mos_r1'] for r in rows]) + mean([r['mos_r2'] for r in rows])) / 2:.3f} | {mean([r['mos_l'] for r in rows]):.3f} |")
for dname in DIMS:
    a1 = mean([r1_s[i]["dimensions"][dname] for i in legal])
    a2 = mean([r2_s[i]["dimensions"][dname] for i in legal])
    al = mean([live_s[i]["dimensions"][dname] for i in legal])
    w(f"| {dname} | {a1:.2f} | {a2:.2f} | {(a1 + a2) / 2:.2f} | {al:.2f} |")
noise = mean([abs(r["mos_r1"] - r["mos_r2"]) for r in rows])
drift = mean([abs(r["mos_l"] - (r["mos_r1"] + r["mos_r2"]) / 2) for r in rows])
w(f"\n- **噪声底**：同一路径两次运行逐题 MOS 平均绝对差 = {noise:.3f}。")
w(f"- **线上 vs 复放均值**：逐题 MOS 平均绝对差 = {drift:.3f}。若与噪声底相当，则差异不能归因于路径。\n")

w("## 4. 引用审计与延迟\n")
cr = {k: json.load(open(R / v / "citation_report.json", encoding="utf-8")) for k, v in
      [("r1", "v21_react_e2e"), ("r2", "v21_react_e2e_r2"), ("live", "v22_react_live")]}
w("| 版本 | 引用数 | verbatim | paraphrase | unmatched | 出 context | ungrounded 率 |\n|---|---|---|---|---|---|---|")
for k, lab in [("r1", "v21 r1"), ("r2", "v21 r2"), ("live", "v22 线上")]:
    c = cr[k]
    b = c["quote_bands"]
    w(f"| {lab} | {c['n_citations']} | {b['verbatim']} | {b['paraphrase']} | {b['unmatched']} | "
      f"{b['outside_context']} | {c['ungrounded_rate']} |")
lat_r = mean([r["lat_r"] for r in rows])
lat_l = mean([r["lat_l"] for r in rows])
dl = [r["lat_l"] - r["lat_r"] for r in rows]
w(f"\n- 生成段平均耗时：复放 {lat_r / 1000:.1f}s，线上 {lat_l / 1000:.1f}s；逐题配对差均值 {mean(dl) / 1000:+.1f}s，"
  f"标准差 {st.stdev(dl) / 1000:.1f}s（范围 {min(dl) / 1000:+.1f}s 到 {max(dl) / 1000:+.1f}s）。")
w("  该差值被 Doubao 生成耗时的波动淹没，**不能用来估计 ReAct 实时调用的开销**；"
  "检索阶段的开销以 `react_check.py` 隔离测量为准（线上约 3.5s/题，复放约 1.35s/题，即实时调用约 +2.2s/题）。\n")

kw = ["仅供参考", "免责", "不构成法律意见"]
n_live_kw = sum(any(k in live_s[i]["reason"] for k in kw) for i in legal)
n_r1_kw = sum(any(k in r1_s[i]["reason"] for k in kw) for i in legal)
n_disc = sum("回答仅供参考" in live_a[i]["answer"][-30:] for i in legal)
w("## 4b. 免责声明的影响（混杂因素 1 的核查）\n")
w(f"- 线上 30 条答案末尾均带免责标识：{n_disc}/30。")
w(f"- 评审理由中提到免责/不构成法律意见的题数：线上 {n_live_kw}/30，v21 r1 {n_r1_kw}/30；"
  "提及处均出现在**安全性**一项的正面说明里，未见因此扣分。")
w(f"- 安全性均分：v21 r1 {mean([r1_s[i]['dimensions']['安全性'] for i in legal]):.2f}，"
  f"线上 {mean([live_s[i]['dimensions']['安全性'] for i in legal]):.2f}（均为满分，免责声明没有拉高也没有拉低）。")
w(f"- 答案平均字数：v21 r1 {mean([len(r1_a[i]['answer']) for i in legal]):.0f}，"
  f"线上 {mean([len(live_a[i]['answer']) for i in legal]):.0f}（+1 行免责约 15 字）。\n")

w("### 相关性下降的题（线上 < min(r1, r2)）\n")
for i in legal:
    a = live_s[i]["dimensions"]["相关性"]
    b = min(r1_s[i]["dimensions"]["相关性"], r2_s[i]["dimensions"]["相关性"])
    if a < b:
        w(f"- id{i}（{ds[i]['difficulty']}）：线上 {a} / r1,r2 = {r1_s[i]['dimensions']['相关性']},{r2_s[i]['dimensions']['相关性']}；"
          f"评审：{live_s[i]['reason'][:110]}…")
w("")

w("## 5. 逐条对照\n")
w("| id | 难度 | 轮数 复放→线上 | 终止 复放→线上 | suff₀ 复放→线上 | top10 重合 | primary 复放→线上 | MOS r1/r2→线上 |\n|---|---|---|---|---|---|---|---|")
for r in rows:
    flag = "" if r["same_set"] else " ⚠"
    pr = lambda x: "-" if x is None else f"{x:.2f}"
    w(f"| {r['id']} | {r['diff']} | {r['rounds_r']}→{r['rounds_l']} | {r['stop_r']}→{r['stop_l']} | "
      f"{r['suff_r']}→{r['suff_l']} | {r['ov']}/10{flag} | {pr(r['pr_r'])}→{pr(r['pr_l'])} | "
      f"{r['mos_r1']:.1f}/{r['mos_r2']:.1f}→{r['mos_l']:.1f} |")

w("\n## 6. 检索结果不一致的题（⚠）明细\n")
if not diffs:
    w("无：30 题 top-10 集合全部一致。")
for i, add, rem, prr, prl, lg, lr, tr in diffs:
    w(f"### id{i}（{ds[i]['difficulty']}）  primary {prr}→{prl}")
    w(f"- 线上多出：{', '.join(add) or '无'}")
    w(f"- 线上缺少：{', '.join(rem) or '无'}")
    w(f"- 线上门控：{[(g['sufficient'], g['false_premise']) for g in lg]}  复放门控：{[(g['sufficient'], g['false_premise']) for g in tr['gates']]}")
    for k, x in enumerate(lr):
        t = tr["rounds"][k]["new_query"] if k < len(tr["rounds"]) else "（复放无此轮）"
        same = "一致" if x["new_query"] == t else "不同"
        w(f"- 第{x['round']}轮缺口查询（{same}）：线上「{x['new_query']}」 / 复放「{t}」")
    w("")

pr_all_r, pr_all_l = mean([r["pr_r"] for r in rows]), mean([r["pr_l"] for r in rows])
rs_r = mean([r["pr_r"] for r in slice_rows(rows, "可解释推理")])
rs_l = mean([r["pr_l"] for r in slice_rows(rows, "可解释推理")])
lost = [r["id"] for r in rows if r["pr_l"] < r["pr_r"]]
gain = [r["id"] for r in rows if r["pr_l"] > r["pr_r"]]
w("## 7. 结论\n")
w("**1. 线上路径可用且与评测路径行为一致。** 33 条（含 3 条拒答）全部跑通，ReAct 元数据完整落盘。"
  f"门控非常稳定：首轮 sufficient 平均漂移 {mean(sd):.3f}，30/30 与 0.5 阈值同侧；追加轮数 "
  f"{sum(r['rounds_r'] == r['rounds_l'] for r in rows)}/30 一致。\n")
w(f"**2. 不稳定的是缺口查询的生成。** DeepSeek 在 temperature 0 下，缺口查询文本逐字一致仅 {sum(allq)}/{len(allq)}，"
  f"导致 top-10 集合一致仅 {sum(r['same_set'] for r in rows)}/30（平均重合 {mean([r['ov'] for r in rows]):.1f}/10）。"
  "ReAct 的检索结果因此是一个随机变量，之前的“双跑一致”只验证了复放。\n")
w(f"**3. 召回的两次采样：{pr_all_r:.3f}（trace 那次）与 {pr_all_l:.3f}（本次线上）。** 差异只来自一道题："
  f"回退 {['id%d' % x for x in lost]}，提升 {['id%d' % x for x in gain] or '无'}。"
  "id9 的公司法第 264 条未进线上 top-10，primary 1.0→0.5。"
  f"两个样本都高于 v2 基线 0.933 和预注册线 0.96，但对 0.96 的余量只有 {pr_all_l - 0.96:+.3f}。"
  "**按预注册的“其余切片不回退”，线上这次的可解释推理切片 "
  f"{rs_r:.3f}→{rs_l:.3f} 严格说已回退一格（id9 一道题）。**\n")
w("**4. 对抗否决与复合切片稳定。** trap_primary 3/3 命中（含 id29 劳合法第 21 条），复合切片 1.00，两次一致。\n")
w(f"**5. 生成质量差异在噪声量级。** MOS {mean([r['mos_l'] for r in rows]):.3f} 对复放均值 "
  f"{(mean([r['mos_r1'] for r in rows]) + mean([r['mos_r2'] for r in rows])) / 2:.3f}；逐题 MOS 平均绝对差 {drift:.3f}，"
  f"与同路径两次运行的噪声底 {noise:.3f} 相当。相关性均分下降最多（4 道题由 5 降到 3），评审理由分两类："
  "id16/18/21 是“未按三段式展开”，而这三题走的是单段直出的 statute_lookup 模板，属评审口径波动；"
  "id7 是“漏了劳动法第 19 条”，但该漏召回在复放组里同样存在、当时却给了 5 分，也是评审波动。"
  "四题都无法归因到线上路径本身。免责声明只在安全性里被正面提及，未见扣分。\n")
w("**6. 引用安全兜底未退化。** ungrounded 率 0%，零越界引用；unmatched 占比 3/61，介于 v21 两次（4/63、1/59）之间。\n")
w("**7. 对后续工作的含义。** (a) ReAct 召回应以多次采样的均值±区间报告，而不是单次数字；"
  "(b) 低成本的下一步是只重复跑检索阶段 k=3 次量化方差（约 3.5s×30×k）；"
  "(c) 若要线上可复现，需要缓存缺口查询或对其采样取并集，这是设计选择而不是 bug。")
fp = R / "v22_react_live" / "COMPARISON.md"
fp.write_text("\n".join(out), encoding="utf-8")
print(f"written {fp}  n={n}")
print("same_set", sum(r['same_set'] for r in rows), "same_order", sum(r['same_order'] for r in rows),
      "recall replay/live", round(mean([r['pr_r'] for r in rows]), 3), round(mean([r['pr_l'] for r in rows]), 3),
      "MOS", round(mean([r['mos_r1'] for r in rows]), 3), round(mean([r['mos_r2'] for r in rows]), 3), round(mean([r['mos_l'] for r in rows]), 3))
