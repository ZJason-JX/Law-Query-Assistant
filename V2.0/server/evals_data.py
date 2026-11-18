# -*- coding: utf-8 -*-
"""评测看板静态数据：只读 evals/results 落盘结果，不重跑任何评测。"""
import json
from pathlib import Path

RES = Path(__file__).resolve().parents[1] / "evals" / "results"


def _j(p: Path):
    return json.load(open(p, encoding="utf-8")) if p.exists() else None


def _recall(ver: str) -> dict | None:
    r = _j(RES / ver / "recall_report.json")
    if not r:
        return None
    sl = r["slices"]
    return {"version": ver,
            "explicit": sl.get("显性事实", {}).get("mean_recall"),
            "implicit": sl.get("隐性事实", {}).get("mean_recall"),
            "overall": r.get("mean_recall")}


def _gen(ver: str) -> dict | None:
    s = _j(RES / ver / "summary.json")
    if not s:
        return None
    sl = s.get("legal_slice", s)
    if "mos" not in sl:
        return None
    return {"version": ver, "mos": sl.get("mos"), **sl.get("dim_avg", {})}


def _old_citations() -> list:
    """老六版引用审计：以逐条 per_query_citations.jsonl 为准。
    ungrounded_rates.json 是归一化修复前的旧口径，不采用。"""
    fp = RES / "citation_audit" / "per_query_citations.jsonl"
    if not fp.exists():
        return []
    from collections import defaultdict
    agg = defaultdict(lambda: {"n": 0, "ungrounded": 0, "bands": defaultdict(int)})
    for l in open(fp, encoding="utf-8"):
        r = json.loads(l)
        a = agg[r["version"]]
        for c in r["citations"]:
            a["n"] += 1
            if not c.get("in_context", True):
                a["ungrounded"] += 1
            a["bands"][c.get("band", "?")] += 1
    order = ["v1_doubao_qwen", "v1.1", "v1.2_r1", "v1.2_r2", "v21_react_e2e", "v21_react_e2e_r2"]
    return [{"version": v, **agg[v]} for v in order if v in agg]


def dashboard() -> dict:
    ablation = [x for x in (_recall(v) for v in
                ["v0_rag_baseline", "v0.1_embed_rich", "v0.2_rerank", "v0.3_query_exp",
                 "v0.4_expand_rerank", "v0.5_alias", "v0.6_rrf", "v0.6_rrf_alias"]) if x]
    react = [x for x in (_recall(v) for v in
             ["dataset_v2_baseline_primary", "v20_react", "v25_react_5r_w",
              "v27_react_cap", "v28_react_cap_w6"]) if x]
    generation = [x for x in (_gen(v) for v in
                  ["v1_doubao_qwen", "v1.1", "v1.2_r1", "v1.2_r2"]) if x]
    react_e2e = [x for x in (_gen(v) for v in
                 ["v21_react_e2e", "v22_react_live", "v29_e2e_live", "v30_e2e_v3intent"]) if x]
    intent = []
    for ver, label in (("v29_e2e_live", "旧标签标准（缓存口径）"),
                       ("v30_e2e_v3intent", "新标签标准（当前）")):
        s = _j(RES / ver / "summary.json")
        if s:
            intent.append({"label": label, "accuracy": s["intent"]["accuracy_legal"]})
    citations = _old_citations()
    for ver in ["v22_react_live", "v29_e2e_live", "v30_e2e_v3intent"]:
        c = _j(RES / ver / "citation_report.json")
        if c:
            citations.append({"version": ver, "n": c["n_citations"],
                              "ungrounded": c["ungrounded"],
                              "bands": c.get("quote_bands", {})})
    return {"retrieval_ablation": ablation, "react_recall": react,
            "generation": generation, "react_e2e": react_e2e,
            "intent": intent, "citations": citations}
