# -*- coding: utf-8 -*-
"""汇总 v3_batch：summary.json + 打印关键指标到 stdout（REPORT.md 素材）。"""
import json
import statistics as st
from pathlib import Path

OUT = Path(__file__).resolve().parent / "results" / "v3_batch"
runs = [json.loads(l) for l in open(OUT / "single_runs.jsonl", encoding="utf-8")]
mruns = [json.loads(l) for l in open(OUT / "multi_runs.jsonl", encoding="utf-8")]
sscores = {json.loads(l)["id"]: json.loads(l) for l in open(OUT / "single_scores.jsonl", encoding="utf-8")}
mscores = {(json.loads(l)["session"], json.loads(l)["turn_no"]): json.loads(l)
           for l in open(OUT / "multi_scores.jsonl", encoding="utf-8")}

# ---------- 单轮 ----------
legal = [r for r in runs if r["scenario"] != "off_topic"]
off = [r for r in runs if r["scenario"] == "off_topic"]
s_int_ok = [r for r in legal if r["intent"] == r["expected_intent"]]
s_int_bad = [(r["id"], r["scenario"], r["intent"], r["query"][:30]) for r in legal
             if r["intent"] != r["expected_intent"]]
s_hits = [r for r in legal if r["hit"]]
s_miss = [(r["id"], r["query"][:30]) for r in legal if r["hit"] is False]
s_ung = sum((r["s5"] or {}).get("ungrounded", 0) for r in runs)
s_cit = sum((r["s5"] or {}).get("n", 0) for r in runs)
s_mos = [sscores[r["id"]]["mos"] for r in legal if r["id"] in sscores]
o_mos = [sscores[r["id"]]["mos"] for r in off if r["id"] in sscores]
s_ref = sum(r["refused"] for r in off)
s_lat = sorted(r["latency_ms"] for r in runs if r.get("latency_ms"))
gates1 = [(r["id"], (r["gates"] or [{}])[0].get("sufficient")) for r in legal]

# ---------- 多轮 ----------
legal_m = [r for r in mruns if r["expected_intent"] != "irrelevant"]
m_int_bad = [(r["session"], r["turn_no"], r["expected_intent"], r["intent"], r["query"][:26])
             for r in legal_m if r["intent"] != r["expected_intent"]]
m_hits = [r for r in legal_m if r["hit"]]
m_miss = [(r["session"], r["turn_no"], r["query"][:26]) for r in legal_m if r["hit"] is False]
m_ung = sum(r.get("ungrounded") or 0 for r in mruns)
m_cit = sum(r.get("n_citations") or 0 for r in mruns)
m_used = [r for r in mruns if r.get("used_history")]
m_turn_cits = sum(1 for r in mruns for c in (r.get("citations") or []) if c.get("turn") is not None)
ref_checks = {("m09", 3): True, ("m10", 1): True}
m_ref_ok = sum(1 for (s, t), _ in ref_checks.items()
               if next((r for r in mruns if r["session"] == s and r["turn_no"] == t), {})["refused"])
m_mos = [v["mos"] for (k, v) in mscores.items()
         if next((r for r in mruns if r["session"] == k[0] and r["turn_no"] == k[1]
                  and r["expected_intent"] != "irrelevant"), None)]
m_mos_t1 = [mscores[k]["mos"] for k in mscores if k[1] == 1]
m_mos_follow = [mscores[k]["mos"] for k in mscores if k[1] > 1
                and (k[0], k[1]) in mscores
                and next((r for r in mruns if r["session"] == k[0] and r["turn_no"] == k[1]
                          and r["expected_intent"] != "irrelevant"), None)]

summary = {
    "version": "v3_batch",
    "single": {
        "n": len(runs), "legal_n": len(legal),
        "intent_acc": round(len(s_int_ok) / len(legal), 3),
        "intent_misses": s_int_bad,
        "retrieval_hit": round(len(s_hits) / len(legal), 3),
        "retrieval_misses": s_miss,
        "citations_total": s_cit, "ungrounded_total": s_ung,
        "mos_legal": round(st.mean(s_mos), 3), "mos_off_topic": round(st.mean(o_mos), 3),
        "off_topic_refused": f"{s_ref}/{len(off)}",
        "latency_p50_ms": int(st.median(s_lat)),
        "latency_p95_ms": int(s_lat[int(len(s_lat) * 0.95) - 1]),
    },
    "multi": {
        "sessions": 10, "turns": len(mruns),
        "intent_acc": round(1 - len(m_int_bad) / len(legal_m), 3),
        "intent_misses": m_int_bad,
        "retrieval_hit": round(len(m_hits) / len(legal_m), 3),
        "retrieval_misses": m_miss,
        "citations_total": m_cit, "ungrounded_total": m_ung,
        "turn_marked_citations": m_turn_cits,
        "turns_using_history": len(m_used),
        "refuse_checks_passed": f"{m_ref_ok}/{len(ref_checks)}",
        "mos_legal": round(st.mean(m_mos), 3),
        "mos_turn1": round(st.mean(m_mos_t1), 3),
        "mos_followup": round(st.mean(m_mos_follow), 3),
    },
}
json.dump(summary, open(OUT / "summary.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print(json.dumps(summary, ensure_ascii=False, indent=1))
