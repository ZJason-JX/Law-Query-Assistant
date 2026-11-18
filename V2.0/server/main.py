# -*- coding: utf-8 -*-
"""法律问答助手 2.0 后端：FastAPI 包装现有 pipeline（只加事件回调，不改核心逻辑）。
启动：python -m uvicorn server.main:app --port 8000
POST /api/chat 为 SSE 流（fetch POST 读取）；其余为普通 JSON REST。"""
import json
import os
import queue
import re
import sys
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "src"))
sys.path.insert(0, str(BASE / "evals"))

from server import store  # noqa: E402
from server.evals_data import dashboard  # noqa: E402

app = FastAPI(title="法律问答助手 2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
store.apply_settings(store.get_settings())

MOCK = os.environ.get("MOCK_MODE", "0") == "1"
DEMO_FP = BASE / "server" / "demo_id29.json"


def _chunk_map():
    return {r["id"]: r for r in store.chunks()}


def _citation_audit(answer_text: str, retrieved_ids: list, hist_turns: list = None) -> dict:
    """复用 evals/verify_citations 的确定性审计（S5）。
    hist_turns = build_history 的 canonical 列表：带 "turn" 的引用回查该轮 retrieved_law_ids，
    合法性由代码判定（模型只给索引）。缺 turn 但正文标「沿用」的同样记 outside_context。"""
    from verify_citations import (REUSE_RE, extract_citations, norm_art,
                                  norm_law, quote_ratio)
    cm = _chunk_map()
    ctx = [cm[r] for r in retrieved_ids if r in cm]
    keys = {(norm_law(x["law"]), norm_art(x["article_no"])) for x in ctx}
    hist_turns = hist_turns or []
    marked = {(norm_law(l), norm_art(n)) for l, n, _ in REUSE_RE.findall(answer_text)}
    rows, ungrounded, used_hist = [], 0, []
    for c in extract_citations(answer_text):
        key = (norm_law(c.get("law", "")), norm_art(c.get("article_no", "")))
        turn, art = c.get("turn"), None
        if turn is not None:
            i = turn - 1 if isinstance(turn, int) and not isinstance(turn, bool) else \
                (int(turn) - 1 if isinstance(turn, str) and turn.isdigit() else -1)
            if 0 <= i < len(hist_turns) and hist_turns[i]["status"] == "ok":
                ent = next((a for a in hist_turns[i]["retrieved_law_ids"]
                            if (norm_law(a["law"]), norm_art(a["article_no"])) == key), None)
                if ent:
                    art = cm.get(ent["chunk_id"])
                    if art:
                        used_hist.append({"law": ent["law"], "article_no": ent["article_no"],
                                          "chunk_id": ent["chunk_id"], "from_turn": i + 1})
            in_ctx = art is not None
        elif key in marked:
            in_ctx = False      # 正文写「沿用第N轮」但引用 JSON 缺 turn 字段
        else:
            in_ctx = key in keys
            art = next((x for x in ctx
                        if (norm_law(x["law"]), norm_art(x["article_no"])) == key), None)
        qr = round(quote_ratio(c["quote"], art["text"]), 3) if art and c.get("quote") else None
        band = ("outside_context" if not in_ctx else "no_quote" if qr is None else
                "verbatim" if qr >= 0.9 else "paraphrase" if qr >= 0.6 else "unmatched")
        ungrounded += 0 if in_ctx else 1
        cid = art["id"] if art else None
        row = {"law": c.get("law"), "article_no": c.get("article_no"),
               "quote": c.get("quote"), "in_context": in_ctx,
               "quote_ratio": qr, "band": band, "chunk_id": cid}
        if turn is not None:
            row["turn"] = turn
        rows.append(row)
    return {"citations": rows, "n": len(rows), "ungrounded": ungrounded,
            "used_history": used_hist}


def _sse(stage: str, data: dict) -> str:
    return f"event: {stage}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _demo_events():
    demo = json.load(open(DEMO_FP, encoding="utf-8"))
    subs = demo["subtitles"]
    yield _sse("subtitle", {"text": subs[0]})
    yield _sse("state", {"stage": "S0", "intent": demo["intent"],
                         "confidence": demo["confidence"],
                         "false_premise": demo["false_premise"]})
    time.sleep(1.4)
    yield _sse("subtitle", {"text": subs[1]})
    yield _sse("state", {"stage": "S1", "articles": demo["first_round_articles"],
                         "trap_missing": demo["trap_article"]})
    time.sleep(1.6)
    yield _sse("subtitle", {"text": subs[2]})
    for i, g in enumerate(demo["gates"]):
        yield _sse("state", {"stage": "S2", "round": i, "sufficient": g["sufficient"],
                             "false_premise": g.get("false_premise"), "decision": "loop"})
        if i < len(demo["rounds"]):
            r = demo["rounds"][i]
            yield _sse("state", {"stage": "S3", "round": r["round"], "new_query": r["new_query"],
                                 "recalled_delta": r["recalled_delta"], "articles": []})
        time.sleep(1.2)
    yield _sse("subtitle", {"text": subs[3]})
    yield _sse("state", {"stage": "S3", "round": len(demo["rounds"]),
                         "articles": demo["final_articles"], "final": True,
                         "trap_recovered": demo["trap_article"]})
    time.sleep(1.2)
    yield _sse("subtitle", {"text": subs[4]})
    yield _sse("state", {"stage": "S4", "status": "start"})
    audit = _citation_audit(demo["answer"], [a["id"] for a in demo["final_articles"]])
    yield _sse("state", {"stage": "S5", **audit})
    yield _sse("answer", {"answer": demo["answer"], "demo": True,
                          "retrieved_ids": [a["id"] for a in demo["final_articles"]],
                          "intent": demo["intent"], "confidence": demo["confidence"],
                          "judge": demo["judge"]})
    yield _sse("done", {})


# 多轮规则段（判断节点③ judge）：仅 judge_live 开启且 history 非空时追加到 judge system 末尾。
HIST_RULE_JUDGE = (
    "\n\n【历史对话变量】conversation_history 仅为对话语境，不参与评分对象。"
    "评分对象是本轮 user_query + answer + 本轮 current_retrieved。\n"
    "1. 每轮独立打分，不得把历史轮次得分或旧答案当作本轮评分锚点。\n"
    "2. 相关性 / 简洁性等维度只看本轮答案是否回答了补全后的当前 query；"
    "不因答案承接上文、出现「如上所述」「接着上一问」就扣分。\n"
    "3. 答案中标注「沿用第N轮」的引用，合法性由引用审计代码回查判定，本节点不重复判定，也不因此扣分。\n"
    "4. 输出沿用原 schema。")


def _live_events(query: str, provider: str, session_id: str = ""):
    import pipeline
    q = queue.Queue()
    holder = {}
    hist_str, hist_turns = ("", []) if (not session_id or MOCK) \
        else store.build_history(session_id)

    def on_event(stage, data):
        q.put((stage, data))

    def work():
        t0 = time.time()
        try:
            if MOCK:
                time.sleep(1.0)
                holder["res"] = {"answer": "【演示数据】这是 MOCK_MODE 下的占位回答，未调用真实模型。"
                                 "《中华人民共和国民法典》第571条规定，交付提存部门时提存成立。"
                                 "回答仅供参考，不构成法律意见。",
                                 "retrieved_ids": ["civil-law-571"], "intent": "statute_lookup",
                                 "confidence": 0.9, "false_premise": 0.0, "react_rounds": 0}
                on_event("S0", {"intent": "statute_lookup", "confidence": 0.9, "false_premise": 0.0})
                on_event("S1", {"articles": []})
                on_event("S4", {"status": "start"})
            else:
                holder["res"] = pipeline.answer(query, provider=provider, react=True,
                                                on_event=on_event, history_str=hist_str)
            holder["latency"] = round((time.time() - t0) * 1000)
        except BaseException as e:  # SystemExit（call_llm 重试耗尽）也要推给前端，而不是静默断流
            holder["error"] = f"{type(e).__name__}: {e}"
        finally:
            q.put(None)

    th = threading.Thread(target=work, daemon=True)
    th.start()
    while True:
        item = q.get()
        if item is None:
            break
        yield _sse("state", {"stage": item[0], **item[1]})
    if "error" in holder or "res" not in holder:
        if session_id and not MOCK:
            store.save_failed_turn(session_id, query, holder.get("error", "unknown"))
        yield _sse("error", {"message": holder.get("error", "未知错误：回答调用未返回")})
        return
    res = holder["res"]
    audit = _citation_audit(res["answer"], res.get("retrieved_ids", []), hist_turns)
    yield _sse("state", {"stage": "S5", **audit})
    judge = None
    if store.get_settings().get("judge_live") and not MOCK:
        try:
            from run_eval import judge as qwen_judge
            jp = (BASE / "evals" / "judge_prompt.md").read_text(encoding="utf-8")
            if hist_str:
                jp += HIST_RULE_JUDGE
            cm = _chunk_map()
            j = qwen_judge(jp, {"query": query, "expected_articles": []}, res["answer"],
                           retrieved=[cm[r] for r in res.get("retrieved_ids", []) if r in cm])
            from run_eval import DIMENSIONS
            judge = {"dimensions": {d: j[d] for d in DIMENSIONS},
                     "mos": sum(j[d] for d in DIMENSIONS) / 5, "reason": j.get("评分理由", "")}
        except Exception as e:
            judge = {"error": str(e)}
    request_id = store.record_request(query, res, holder["latency"],
                                      audit["n"], audit["ungrounded"], mock=MOCK)
    turn_no, turn_id = None, None
    if session_id and not MOCK:
        cm2 = _chunk_map()
        laws = [{"law": cm2[r]["law"], "article_no": cm2[r]["article_no"], "chunk_id": r}
                for r in res.get("retrieved_ids", []) if r in cm2]
        turn_no, turn_id = store.save_turn(
            session_id, query, res, laws, audit, judge,
            status="refused" if res.get("prompt_file") == "irrelevant.md" else "ok")
    # 旁路：确定性坏例判定（不进 prompt、不改 pipeline）。MOCK 与演示模式不采集。
    badcases = []
    if not MOCK:
        from server import badcases as bc
        badcases = [{"badcase_id": b["badcase_id"], "rules": [t["rule_id"] for t in b["triggered_rules"]],
                     "primary_stage": b["primary_stage"], "severity": b["severity"],
                     "triggered_rules": b["triggered_rules"], "status": b["status"]}
                    for b in bc.collect_live(query, res, audit, holder["latency"],
                                             session_id=session_id, turn_id=turn_id,
                                             request_id=request_id)]
    yield _sse("answer", {"answer": res["answer"], "retrieved_ids": res.get("retrieved_ids", []),
                          "intent": res.get("intent"), "confidence": res.get("confidence"),
                          "judge": judge, "mock": MOCK, "latency_ms": holder["latency"],
                          "turn_no": turn_no, "badcases": badcases})
    yield _sse("done", {})


class ChatReq(BaseModel):
    query: str
    demo_mode: bool = False
    provider: str = "doubao"
    session_id: str = ""


@app.post("/api/chat")
def chat(req: ChatReq):
    # 演示模式固定空历史、不查库、不写 turns：五幕序列与改动前一致
    gen = _demo_events() if req.demo_mode else _live_events(req.query, req.provider, req.session_id)
    return StreamingResponse(gen, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/sessions/{sid}/turns")
def session_turns(sid: str):
    return store.list_turns(sid)


@app.get("/api/settings")
def get_settings():
    return store.get_settings()


@app.put("/api/settings")
def put_settings(s: dict):
    return store.save_settings(s)


@app.get("/api/settings/keys")
def get_keys():
    return store.get_keys()


@app.put("/api/settings/keys")
def put_keys(body: dict):
    bad = [k for k in body if k not in store.ENV_KEYS]
    if bad:
        raise HTTPException(400, f"未知字段 {bad}")
    return store.save_keys(body)


@app.get("/api/laws")
def laws(law: str = "", search: str = "", page: int = 1, size: int = 20):
    return store.list_chunks(law, search, page, size)


@app.get("/api/laws/{cid}")
def law_detail(cid: str):
    r = store.get_chunk(cid)
    if not r:
        raise HTTPException(404, "not found")
    return r


@app.put("/api/chunks/{cid}")
def update_chunk(cid: str, patch: dict):
    try:
        return store.save_chunk(cid, patch)
    except KeyError:
        raise HTTPException(404, "not found")


@app.post("/api/chunks")
def create_chunk(r: dict):
    for k in ("id", "law", "article_no", "text"):
        if not r.get(k):
            raise HTTPException(400, f"缺少字段 {k}")
    try:
        return store.create_chunk(r)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/chunks/{cid}")
def delete_chunk(cid: str):
    try:
        store.delete_chunk(cid)
        return {"ok": True}
    except KeyError:
        raise HTTPException(404, "not found")


@app.get("/api/audit")
def audit():
    return store.audit_log()


@app.get("/api/evals")
def evals():
    return dashboard()


@app.get("/api/usage")
def usage():
    return store.usage()


# ---------------- Badcase 队列 ----------------

@app.get("/api/badcases")
def badcase_list(stage: str = "", severity: str = "", source: str = "",
                 status: str = "", limit: int = 200):
    return store.list_badcases(stage, severity, source, status, limit)


@app.get("/api/badcases/stats")
def badcase_stats():
    return store.badcase_stats()


@app.post("/api/badcases")
def badcase_create(body: dict):
    """手动通道（B6 用户点踩 / 人工标记）：可传 session_id+turn_no 或 turn_id 定位轮次。"""
    from server import badcases as bc
    turn_id = body.get("turn_id")
    if not turn_id and body.get("session_id") and body.get("turn_no"):
        turn_id = store.turn_id_of(body["session_id"], int(body["turn_no"]))
    row = bc.collect_manual(note=body.get("note", ""),
                            session_id=body.get("session_id", ""),
                            turn_id=turn_id, request_id=body.get("request_id"),
                            actor=body.get("actor", "user"))
    return store.get_badcase(row["badcase_id"])


@app.patch("/api/badcases/{bid}")
def badcase_patch(bid: str, body: dict):
    """状态流转 + 改判 primary_stage + 关联 case/议题，全部落 events。"""
    from server import badcases as bc
    try:
        fields = {}
        if body.get("primary_stage"):
            if body["primary_stage"] not in bc.STAGES:
                raise HTTPException(400, f"primary_stage 必须为 {bc.STAGES} 之一")
            fields["primary_stage"] = body["primary_stage"]
        for k in ("linked_case_id", "linked_issue_id"):
            if body.get(k) is not None:
                fields[k] = body[k]
        actor, note = body.get("actor", "admin"), body.get("note", "")
        if fields and not body.get("status"):
            store.update_badcase_fields(bid, **fields)
            store.add_badcase_event(bid, store.get_badcase(bid)["status"],
                                    store.get_badcase(bid)["status"], actor,
                                    note or f"字段更新 {list(fields)}")
            return store.get_badcase(bid)
        return bc.transition(bid, body.get("status", ""), actor, note, fields)
    except KeyError:
        raise HTTPException(404, "badcase not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/badcases/{bid}/events")
def badcase_event(bid: str, body: dict):
    """显式事件（如 dismissed/open 附 note、记录人工研判）。"""
    from server import badcases as bc
    try:
        to = body.get("to_status")
        if to:
            return bc.transition(bid, to, body.get("actor", "admin"),
                                 body.get("note", ""), body.get("fields"))
        row = store.get_badcase(bid)
        if not row:
            raise KeyError(bid)
        store.add_badcase_event(bid, row["status"], row["status"],
                                body.get("actor", "admin"), body.get("note", ""))
        return {"ok": True}
    except KeyError:
        raise HTTPException(404, "badcase not found")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/badcases/{bid}/verify")
def badcase_verify(bid: str):
    """回填验证（闭环终点）：回查 query 重跑链路，规则全不触发才置 verified。"""
    from server import badcases as bc
    row = store.get_badcase(bid)
    if not row:
        raise HTTPException(404, "badcase not found")
    if row["status"] != "linked":
        raise HTTPException(400, f"仅 linked 状态可验证（当前 {row['status']}）")
    query = bc.resolve_query(row)
    if not query:
        raise HTTPException(400, "无法回查 query（turns/requests/dataset 均无）")
    import pipeline
    t0 = time.time()
    res = pipeline.answer(query, provider="doubao", react=True)
    lat = round((time.time() - t0) * 1000)
    audit = _citation_audit(res["answer"], res.get("retrieved_ids", []))
    after = bc.collect_live(query, res, audit, lat,
                            session_id=row.get("session_id") or "")
    before_rules = [t["rule_id"] for t in row["triggered_rules"]]
    after_rules = [t["rule_id"] for a in after for t in a["triggered_rules"]]
    note = json.dumps({"before": {"triggered_rules": before_rules,
                                  "scores": row.get("scores")},
                       "after": {"triggered_rules": after_rules},
                       "verify_pass": not after_rules}, ensure_ascii=False)
    if after_rules:
        store.update_badcase_fields(bid, status="open")
        store.add_badcase_event(bid, "linked", "open", "verify",
                                f"重跑仍触发 {after_rules}，保留 open。{note}")
        return {"verified": False, "after_rules": after_rules}
    store.update_badcase_fields(bid, status="verified")
    store.add_badcase_event(bid, "linked", "verified", "verify", f"重跑全部规则不再触发。{note}")
    return {"verified": True, "after_rules": []}


# ---------------- 前端静态托管（SPA fallback，必须最后注册） ----------------
DIST = BASE / "web" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        fp = DIST / full_path
        return FileResponse(fp if full_path and fp.is_file() else DIST / "index.html")
