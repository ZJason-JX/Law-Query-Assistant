# -*- coding: utf-8 -*-
"""v3 批量评测：单轮 20 + 多轮 10 会话×3 轮，走 HTTP /api/chat 真链路（SSE 全事件落盘）。

用法: python -X utf8 evals/run_eval_v3.py [--only single|multi] [--no-judge]
产物 evals/results/v3_batch/:
  single_runs.jsonl / multi_runs.jsonl   每轮 {id/session,turn_no,query,S0,gates,S3,S5,answer,retrieved_ids,latency}
  single_scores.jsonl / multi_scores.jsonl  judge 五维
  summary.json
断点续跑：已落盘的 id/session+turn 自动跳过。
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
PROJ = BASE.parent
for p in (str(PROJ), str(PROJ / "src"), str(BASE)):
    sys.path.insert(0, p)
for line in open(PROJ / ".env", encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1)
        __import__("os").environ.setdefault(k, v)

OUT = BASE / "results" / "v3_batch"
OUT.mkdir(parents=True, exist_ok=True)
API = "http://localhost:8000/api/chat"
SCENARIO2INTENT = {"构成要件与归责": "elements_liability", "法条精准检索": "statute_lookup",
                   "规则冲突与适用": "rule_conflict", "法律概念界定": "concept_definition",
                   "off_topic": "irrelevant"}
EV_RE = re.compile(r"event: (\w+)\ndata: (.*?)(?=\n\nevent:|\Z)", re.S)


def post_chat(query, session_id, timeout=300):
    body = json.dumps({"query": query, "session_id": session_id, "demo_mode": False,
                       "provider": "doubao"}).encode("utf-8")
    req = urllib.request.Request(API, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        sse = r.read().decode("utf-8")
    evs = [(m.group(1), json.loads(m.group(2))) for m in EV_RE.finditer(sse)]
    rec = {"raw_events": evs}
    rec["s0"] = next((d for e, d in evs if e == "state" and d.get("stage") == "S0"), None)
    rec["gates"] = [{"round": g.get("round"), "sufficient": g.get("sufficient"),
                     "fp": g.get("false_premise")}
                    for e, d in evs if e == "state" and d.get("stage") == "S2"
                    for g in [d]]
    rec["s3"] = [{"round": d.get("round"), "new_query": d.get("new_query"),
                  "delta": d.get("recalled_delta")}
                 for e, d in evs if e == "state" and d.get("stage") == "S3" and d.get("new_query")]
    rec["s5"] = next((d for e, d in evs if e == "state" and d.get("stage") == "S5"), None)
    rec["answer_ev"] = next((d for e, d in evs if e == "answer"), None)
    rec["error"] = next((d for e, d in evs if e == "error"), None)
    return rec


def expected_hit(expected, retrieved_ids, cmap):
    """expected_articles 是否落在本轮 retrieved top10（norm_law+norm_art 口径）。"""
    from verify_citations import norm_art, norm_law
    got = {(norm_law(cmap[r]["law"]), norm_art(cmap[r]["article_no"]))
           for r in retrieved_ids if r in cmap}
    return [all((norm_law(a["law"]), norm_art(a["article"])) in got
                for a in expected)] if expected else [None]


def judge_one(jp, item, answer, retrieved):
    from run_eval import judge as qwen_judge, DIMENSIONS
    item = dict(item, expected_articles=[{**a, "note": a.get("note", "")}
                                         for a in item["expected_articles"]])
    j = qwen_judge(jp, item, answer, retrieved=retrieved)
    return {"dimensions": {d: j[d] for d in DIMENSIONS},
            "mos": round(sum(j[d] for d in DIMENSIONS) / 5, 3),
            "reason": j.get("评分理由", "")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["single", "multi"], default=None)
    ap.add_argument("--no-judge", action="store_true")
    args = ap.parse_args()

    cmap = {r["id"]: r for r in
            (json.loads(l) for l in open(PROJ / "src/corpus/chunks/chunks.jsonl", encoding="utf-8"))}
    jp = (BASE / "judge_prompt.md").read_text(encoding="utf-8")
    from server.main import HIST_RULE_JUDGE  # 多轮轮次追加段，与线上口径一致

    done = set()
    for fn in ("single_runs.jsonl", "multi_runs.jsonl"):
        fp = OUT / fn
        if fp.exists():
            for l in open(fp, encoding="utf-8"):
                r = json.loads(l)
                done.add((fn, r.get("id") or r.get("session"), r.get("turn_no", 0)))

    # ---------- 单轮 20 ----------
    if args.only in (None, "single"):
        items = [json.loads(l) for l in open(BASE / "dataset_v3_single.jsonl", encoding="utf-8")]
        fa = open(OUT / "single_runs.jsonl", "a", encoding="utf-8")
        fs = open(OUT / "single_scores.jsonl", "a", encoding="utf-8")
        for it in items:
            iid = it["id"]
            if ("single_runs.jsonl", iid, 0) in done:
                print(f"single id={iid} 已有，跳过")
                continue
            sid = f"v3s-{iid:02d}"
            print(f"single id={iid} [{it['scenario']}] {it['query'][:30]}…", flush=True)
            t0 = time.time()
            try:
                rec = post_chat(it["query"], sid)
            except Exception as e:
                rec = {"error": {"message": f"{type(e).__name__}: {e}"}}
            lat = round((time.time() - t0) * 1000)
            ans = (rec.get("answer_ev") or {})
            rids = ans.get("retrieved_ids", [])
            row = {"id": iid, "query": it["query"], "scenario": it["scenario"],
                   "difficulty": it["difficulty"], "expected_intent": SCENARIO2INTENT[it["scenario"]],
                   "intent": (rec.get("s0") or {}).get("intent"),
                   "confidence": (rec.get("s0") or {}).get("confidence"),
                   "fp": (rec.get("s0") or {}).get("false_premise"),
                   "gates": rec.get("gates"), "s3": rec.get("s3"),
                   "s5": rec.get("s5"), "answer": ans.get("answer"),
                   "retrieved_ids": rids, "turn_no": ans.get("turn_no"),
                   "latency_ms": ans.get("latency_ms") or lat,
                   "hit": expected_hit(it["expected_articles"], rids, cmap)[0],
                   "refused": (ans.get("answer") == "本助手仅回答法律条文相关问题，请调整提问"),
                   "error": rec.get("error")}
            fa.write(json.dumps(row, ensure_ascii=False) + "\n")
            fa.flush()
            if not args.no_judge and ans.get("answer"):
                try:
                    retr = [cmap[r] for r in rids if r in cmap]
                    jrow = judge_one(jp, {"query": it["query"],
                                          "expected_articles": it["expected_articles"],
                                          "adversarial_trap": it.get("adversarial_trap")},
                                     ans["answer"], retr)
                    jrow["id"] = iid
                    fs.write(json.dumps(jrow, ensure_ascii=False) + "\n")
                    fs.flush()
                    print(f"  MOS={jrow['mos']} intent={row['intent']} hit={row['hit']}", flush=True)
                except Exception as e:
                    print(f"  judge 失败: {e}", flush=True)
        fa.close()
        fs.close()

    # ---------- 多轮 10 会话 ----------
    if args.only in (None, "multi"):
        # 文件为多个跨行 pretty JSON 顺序拼接，用 raw_decode 逐个解析
        _txt = open(BASE / "dataset_v3_multi.jsonl", encoding="utf-8").read()
        sessions, _idx = [], 0
        _dec = json.JSONDecoder()
        while True:
            while _idx < len(_txt) and _txt[_idx] in " \n\r\t":
                _idx += 1
            if _idx >= len(_txt):
                break
            _obj, _idx = _dec.raw_decode(_txt, _idx)
            sessions.append(_obj)
        fa = open(OUT / "multi_runs.jsonl", "a", encoding="utf-8")
        fs = open(OUT / "multi_scores.jsonl", "a", encoding="utf-8")
        for sess in sessions:
            sid = f"v3m-{sess['session']}"
            for ti, t in enumerate(sess["turns"], 1):
                if ("multi_runs.jsonl", sess["session"], ti) in done:
                    continue
                print(f"{sess['session']} turn{ti} [{t['check']}] {t['query'][:30]}…", flush=True)
                t0 = time.time()
                try:
                    rec = post_chat(t["query"], sid)
                except Exception as e:
                    rec = {"error": {"message": f"{type(e).__name__}: {e}"}}
                lat = round((time.time() - t0) * 1000)
                ans = (rec.get("answer_ev") or {})
                rids = ans.get("retrieved_ids", [])
                s5 = rec.get("s5") or {}
                row = {"session": sess["session"], "turn_no": ti, "query": t["query"],
                       "check": t["check"], "expected_intent": t["expected_intent"],
                       "intent": (rec.get("s0") or {}).get("intent"),
                       "confidence": (rec.get("s0") or {}).get("confidence"),
                       "fp": (rec.get("s0") or {}).get("false_premise"),
                       "gates": rec.get("gates"), "s3": rec.get("s3"),
                       "n_citations": s5.get("n"), "ungrounded": s5.get("ungrounded"),
                       "used_history": s5.get("used_history"),
                       "citations": s5.get("citations"), "answer": ans.get("answer"),
                       "retrieved_ids": rids, "latency_ms": ans.get("latency_ms") or lat,
                       "hit": expected_hit(t["expected_articles"], rids, cmap)[0],
                       "refused": (ans.get("answer") == "本助手仅回答法律条文相关问题，请调整提问"),
                       "error": rec.get("error")}
                fa.write(json.dumps(row, ensure_ascii=False) + "\n")
                fa.flush()
                if not args.no_judge and ans.get("answer"):
                    try:
                        retr = [cmap[r] for r in rids if r in cmap]
                        jx = jp + (HIST_RULE_JUDGE if ti > 1 else "")
                        jrow = judge_one(jx, {"query": t["query"],
                                              "expected_articles": t["expected_articles"]},
                                         ans["answer"], retr)
                        jrow.update(session=sess["session"], turn_no=ti)
                        fs.write(json.dumps(jrow, ensure_ascii=False) + "\n")
                        fs.flush()
                        print(f"  MOS={jrow['mos']} intent={row['intent']} "
                              f"ungrounded={row['ungrounded']} hit={row['hit']}", flush=True)
                    except Exception as e:
                        print(f"  judge 失败: {e}", flush=True)
        fa.close()
        fs.close()


if __name__ == "__main__":
    main()
