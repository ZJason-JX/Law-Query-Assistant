# -*- coding: utf-8 -*-
"""后端存储层：设置持久化、用量统计、知识库 CRUD（chunks.jsonl + SQLite + Qdrant 三处同步 + 审计）。
不改动检索/生成核心逻辑；设置通过 pipeline 的模块级常量生效。"""
import json
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]          # 法律问答助手2.0/
sys.path.insert(0, str(BASE / "src"))
sys.path.insert(0, str(BASE / "evals"))

_env_fp = BASE / ".env"
if not _env_fp.exists() and (BASE / ".env.example").exists():
    import shutil
    shutil.copyfile(BASE / ".env.example", _env_fp)  # 首次运行：占位值示例文件拷成 .env
if _env_fp.exists():
    for line in open(_env_fp, encoding="utf-8"):
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            import os
            os.environ.setdefault(k, v)

CHUNKS = BASE / "src" / "corpus" / "chunks" / "chunks.jsonl"
SQLITE = BASE / "src" / "db" / "law_articles.db"
QDRANT = BASE / "src" / "db" / "qdrant_storage"
DATA = BASE / "server" / "data"
DATA.mkdir(exist_ok=True)
DB = DATA / "app.db"

DEFAULT_SETTINGS = {
    "models": {"intent": "jev-1.13.0",
               "generation": os.environ.get("DOUBAO_MODEL", "doubao-pro-32k-240828"),
               "judge": "qwen-plus"},
    "retrieval": {"topk": 10, "lane_fetch": 20, "rrf_k": 60,
                  "react_max_rounds": 5, "suff_th": 0.9, "fp_th": 0.5,
                  "veto_enabled": True},
    "judge_live": False,
}

_lock = threading.RLock()  # save_chunk 持锁后还要进 _audit，必须可重入


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(DB, check_same_thread=False)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS requests (
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, query TEXT, intent TEXT,
      rounds INTEGER, stop_reason TEXT, first_suff REAL, latency_ms INTEGER,
      n_citations INTEGER, ungrounded INTEGER, mock INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS audit (
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, action TEXT,
      chunk_id TEXT, old_value TEXT, new_value TEXT, operator TEXT DEFAULT 'admin');
    CREATE TABLE IF NOT EXISTS sessions (
      session_id TEXT PRIMARY KEY, title TEXT, created_at REAL, status TEXT);
    CREATE TABLE IF NOT EXISTS turns (
      turn_id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, turn_no INTEGER,
      user_query TEXT, intent_label TEXT, retrieved_law_ids TEXT,
      answer TEXT, citations TEXT, judge_scores TEXT,
      used_history_article_ids TEXT, error_code TEXT,
      created_at REAL, status TEXT);
    CREATE TABLE IF NOT EXISTS badcases (
      badcase_id TEXT PRIMARY KEY, session_id TEXT, turn_id INTEGER, request_id INTEGER,
      source TEXT, triggered_rules TEXT, primary_stage TEXT, secondary_stages TEXT,
      severity TEXT, scores TEXT, status TEXT, linked_case_id TEXT, linked_issue_id TEXT,
      created_at REAL, updated_at REAL);
    CREATE TABLE IF NOT EXISTS badcase_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT, badcase_id TEXT, from_status TEXT,
      to_status TEXT, actor TEXT, note TEXT, created_at REAL);
    """)
    return con


# ---------------- 设置 ----------------

def get_settings() -> dict:
    fp = DATA / "settings.json"
    s = json.loads(json.dumps(DEFAULT_SETTINGS))
    if fp.exists():
        saved = json.load(open(fp, encoding="utf-8"))
        for k, v in saved.items():
            if isinstance(v, dict) and k in s:
                s[k].update(v)
            else:
                s[k] = v
    return s


def save_settings(s: dict) -> dict:
    with _lock:
        json.dump(s, open(DATA / "settings.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        apply_settings(s)
    return s


def apply_settings(s: dict) -> None:
    import pipeline
    r = s["retrieval"]
    pipeline.CONFIG["retrieval"]["topk"] = r["topk"]
    pipeline.CONFIG["retrieval"]["lane_fetch"] = r["lane_fetch"]
    pipeline.RRF_K = r["rrf_k"]
    pipeline.REACT_MAX_ROUNDS = r["react_max_rounds"]
    pipeline.SUFF_TH = r["suff_th"]
    pipeline.FP_TH = r["fp_th"]
    pipeline.PROVIDERS["doubao"]["model"] = s["models"]["generation"]


# ---------------- API 密钥（落盘 .env + 注入 os.environ，不回传明文） ----------------
ENV_KEYS = ("TYPESAFE_API_KEY", "DEEPSEEK_API_KEY", "DOUBAO_API_KEY", "QWEN_API_KEY")


def get_keys() -> dict:
    out = {}
    for k in ENV_KEYS:
        v = os.environ.get(k, "")
        real = bool(v) and v != "apikey_123123"   # 示例占位值不算已设置
        out[k] = {"set": real, "tail": v[-4:] if real else ""}
    return out


def save_keys(patch: dict) -> dict:
    fp = BASE / ".env"
    lines = fp.read_text(encoding="utf-8").splitlines() if fp.exists() else []
    with _lock:
        for k in ENV_KEYS:
            v = (patch.get(k) or "").strip()
            if not v:
                continue
            os.environ[k] = v
            for i, l in enumerate(lines):
                if l.startswith(k + "="):
                    lines[i] = f"{k}={v}"
                    break
            else:
                lines.append(f"{k}={v}")
        fp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return get_keys()


# ---------------- 用量 ----------------

def record_request(query: str, res: dict, latency_ms: int,
                   n_citations: int, ungrounded: int, mock: bool = False) -> int:
    rounds = res.get("react_rounds", 0)
    gates = res.get("react_gates") or []
    with _lock, _con() as con:
        cur = con.execute(
            "INSERT INTO requests (ts,query,intent,rounds,stop_reason,first_suff,"
            "latency_ms,n_citations,ungrounded,mock) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (time.time(), query, res.get("intent"), rounds, res.get("react_stop"),
             gates[0]["sufficient"] if gates else None, latency_ms,
             n_citations, ungrounded, int(mock)))
        return cur.lastrowid


def usage() -> dict:
    with _con() as con:
        rows = con.execute(
            "SELECT ts,intent,rounds,latency_ms,n_citations,ungrounded,mock FROM requests").fetchall()
    real = [r for r in rows if not r[6]]
    out = {"total": len(real), "mock_only": bool(rows) and not real,
           "per_day": [], "intents": {}, "gate": {}, "latency": {}, "citations": {}}
    if not real:
        return out
    import statistics as st
    days = {}
    for ts, intent, *_ in real:
        day = time.strftime("%m-%d", time.localtime(ts))
        days[day] = days.get(day, 0) + 1
        out["intents"][intent or "unknown"] = out["intents"].get(intent or "unknown", 0) + 1
    out["per_day"] = [{"day": d, "n": n} for d, n in sorted(days.items())][-14:]
    rounds = [r[2] or 0 for r in real]
    lat = sorted(r[3] for r in real if r[3] is not None)
    out["gate"] = {"trigger_rate": round(sum(x > 0 for x in rounds) / len(rounds), 3),
                   "avg_rounds": round(sum(rounds) / len(rounds), 2)}
    out["latency"] = {"p50_ms": int(st.median(lat)),
                      "p95_ms": int(lat[min(len(lat) - 1, int(len(lat) * 0.95))])}
    out["citations"] = {"total": sum(r[4] or 0 for r in real),
                        "ungrounded": sum(r[5] or 0 for r in real)}
    return out


def audit_log(limit: int = 200) -> list:
    with _con() as con:
        rows = con.execute(
            "SELECT ts,action,chunk_id,old_value,new_value FROM audit ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
    return [{"ts": t, "action": a, "chunk_id": c,
             "old_value": json.loads(o) if o else None,
             "new_value": json.loads(n) if n else None} for t, a, c, o, n in rows]


# ---------------- 会话历史 ----------------
# 规则：只读注入；failed 行不占 turn_no 不进白名单；canonical index = 注入列表下标(1-based)。

HIST_MAX_TURNS, HIST_MAX_LEN = 3, 2000


def _ensure_session(con, session_id: str, title: str = "") -> None:
    con.execute(
        "INSERT OR IGNORE INTO sessions (session_id,title,created_at,status) VALUES (?,?,?,?)",
        (session_id, title, time.time(), "active"))


def save_turn(session_id: str, query: str, res: dict, laws: list, audit: dict,
              judge: dict | None, status: str) -> tuple:
    """一轮完整结束（含拒答）后调用；返回 (turn_no, turn_id)。"""
    with _lock, _con() as con:
        _ensure_session(con, session_id, query[:30])
        turn_no = (con.execute(
            "SELECT MAX(turn_no) FROM turns WHERE session_id=?", (session_id,)).fetchone()[0] or 0) + 1
        cur = con.execute(
            "INSERT INTO turns (session_id,turn_no,user_query,intent_label,retrieved_law_ids,"
            "answer,citations,judge_scores,used_history_article_ids,created_at,status)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (session_id, turn_no, query, res.get("intent"),
             json.dumps(laws, ensure_ascii=False), res.get("answer"),
             json.dumps(audit.get("citations", []), ensure_ascii=False),
             json.dumps(judge, ensure_ascii=False) if judge else None,
             json.dumps(audit.get("used_history", []), ensure_ascii=False),
             time.time(), status))
        return turn_no, cur.lastrowid


def save_failed_turn(session_id: str, query: str, error_code: str) -> None:
    """错误/中断轮：只存 query+error_code，turn_no 留空，不进注入白名单。"""
    with _lock, _con() as con:
        _ensure_session(con, session_id, query[:30])
        con.execute(
            "INSERT INTO turns (session_id,turn_no,user_query,created_at,status,error_code)"
            " VALUES (?,?,?,?,?,?)",
            (session_id, None, query, time.time(), "failed", error_code[:300]))


def _hist_rows(session_id: str) -> list:
    """注入白名单：最近 HIST_MAX_TURNS 条 ok/refused，按时间正序。"""
    with _con() as con:
        rows = con.execute(
            "SELECT turn_id,turn_no,user_query,intent_label,retrieved_law_ids,answer,"
            "citations,status FROM turns WHERE session_id=? AND status IN ('ok','refused')"
            " ORDER BY turn_id DESC LIMIT ?", (session_id, HIST_MAX_TURNS)).fetchall()
    out = []
    for r in reversed(rows):
        out.append({"turn_id": r[0], "turn_no": r[1], "user_query": r[2],
                    "intent_label": r[3], "retrieved_law_ids": json.loads(r[4] or "[]"),
                    "answer": r[5], "citations": json.loads(r[6] or "[]"), "status": r[7]})
    return out


def _render_hist(turns: list, dropped: int) -> str:
    """序列化为 === 历史对话 === 块；[第N轮] N 为列表下标(1-based)，与引用审计共用。"""
    from verify_citations import CIT_RE, norm_art, norm_law
    blocks = []
    for i, t in enumerate(turns, 1):
        cited = {(norm_law(c.get("law", "")), norm_art(c.get("article_no", "")))
                 for c in t["citations"]}
        arts = "；".join(
            f"《{a['law']}》{a['article_no']}（chunk_id={a['chunk_id']}）"
            + ("【该轮答案实际引用】" if (norm_law(a["law"]), norm_art(a["article_no"])) in cited else "")
            + f"｜摘要：{(get_chunk(a['chunk_id']) or {}).get('text', '（条目已删除）')[:60]}"
            for a in t["retrieved_law_ids"][:5]) or "（无）"
        tag = "[拒答轮]" if t["status"] == "refused" else ""
        ans_txt = CIT_RE.sub("", t["answer"] or "").strip()  # 末尾引用 JSON 是机器字段，进变量前先剥掉
        blocks.append(f"[第{i}轮]{tag} 用户问：{t['user_query'][:200]}\n"
                      f"        命中法条：{arts}\n"
                      f"        回答：{ans_txt[:600]}")
    body = "\n".join(blocks)
    if dropped:
        body += f"\n（已省略前 {dropped} 轮）"
    return f"=== 历史对话开始 ===\n{body}\n=== 历史对话结束 ==="


def build_history(session_id: str) -> tuple:
    """→ (history_str, canonical_turns)。canon 为截断后实际入变量的轮次列表，
    引用审计用它把「沿用第N轮」的 N 解析回具体 turns 行；空会话返回 ('', [])。"""
    rows = _hist_rows(session_id)
    dropped = 0
    while rows:
        s = _render_hist(rows, dropped)
        if len(s) <= HIST_MAX_LEN:
            return s, rows
        rows, dropped = rows[1:], dropped + 1
    return "", []


# ---------------- Badcase ----------------
# 不重复存正文：只存外键 + 结构化判定字段，query/answer 回查 turns/requests。

def _bc_row(r) -> dict:
    return {"badcase_id": r[0], "session_id": r[1], "turn_id": r[2], "request_id": r[3],
            "source": r[4], "triggered_rules": json.loads(r[5] or "[]"),
            "primary_stage": r[6], "secondary_stages": json.loads(r[7] or "[]"),
            "severity": r[8], "scores": json.loads(r[9]) if r[9] else None,
            "status": r[10], "linked_case_id": r[11], "linked_issue_id": r[12],
            "created_at": r[13], "updated_at": r[14]}


_BC_COLS = ("badcase_id,session_id,turn_id,request_id,source,triggered_rules,"
            "primary_stage,secondary_stages,severity,scores,status,"
            "linked_case_id,linked_issue_id,created_at,updated_at")


def insert_badcase(row: dict) -> None:
    now = time.time()
    with _lock, _con() as con:
        con.execute(
            "INSERT INTO badcases (badcase_id,session_id,turn_id,request_id,source,"
            "triggered_rules,primary_stage,secondary_stages,severity,scores,status,"
            "linked_case_id,linked_issue_id,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["badcase_id"], row.get("session_id"), row.get("turn_id"),
             row.get("request_id"), row["source"],
             json.dumps(row["triggered_rules"], ensure_ascii=False),
             row["primary_stage"], json.dumps(row.get("secondary_stages", []), ensure_ascii=False),
             row["severity"],
             json.dumps(row["scores"], ensure_ascii=False) if row.get("scores") else None,
             row.get("status", "open"), row.get("linked_case_id"),
             row.get("linked_issue_id"), now, now))


def get_badcase(badcase_id: str) -> dict | None:
    with _con() as con:
        r = con.execute(f"SELECT {_BC_COLS} FROM badcases WHERE badcase_id=?",
                        (badcase_id,)).fetchone()
    return _bc_row(r) if r else None


def update_badcase_fields(badcase_id: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    sets, vals = [], []
    for k, v in fields.items():
        sets.append(f"{k}=?")
        vals.append(json.dumps(v, ensure_ascii=False)
                    if k in ("triggered_rules", "secondary_stages", "scores") else v)
    vals.append(badcase_id)
    with _lock, _con() as con:
        con.execute(f"UPDATE badcases SET {','.join(sets)} WHERE badcase_id=?", vals)


def add_badcase_event(badcase_id: str, frm: str, to: str,
                      actor: str, note: str) -> None:
    with _lock, _con() as con:
        con.execute(
            "INSERT INTO badcase_events (badcase_id,from_status,to_status,actor,note,created_at)"
            " VALUES (?,?,?,?,?,?)",
            (badcase_id, frm, to, actor, note, time.time()))


def list_badcases(stage: str = "", severity: str = "", source: str = "",
                  status: str = "", limit: int = 200) -> list:
    sql, vals = f"SELECT {_BC_COLS} FROM badcases", []
    conds = []
    for col, v in (("primary_stage", stage), ("severity", severity),
                   ("source", source), ("status", status)):
        if v:
            conds.append(f"{col}=?")
            vals.append(v)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY created_at DESC LIMIT ?"
    vals.append(limit)
    with _con() as con:
        rows = con.execute(sql, vals).fetchall()
    out = []
    for r in rows:
        row = _bc_row(r)
        q = turn_query(row["turn_id"]) if row["turn_id"] else \
            (request_query(row["request_id"]) if row["request_id"] else "")
        row["query_preview"] = (q or "")[:80]
        out.append(row)
    return out


def badcase_stats() -> dict:
    with _con() as con:
        rows = con.execute(
            "SELECT triggered_rules,primary_stage,severity,status FROM badcases").fetchall()
    by_stage, by_rule, by_sev, by_status, open_by_stage = {}, {}, {}, {}, {}
    for trig, stage, sev, status in rows:
        by_stage[stage or "待归因"] = by_stage.get(stage or "待归因", 0) + 1
        by_sev[sev] = by_sev.get(sev, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1
        for t in (json.loads(trig) if trig else []):
            rid = t.get("rule_id")
            if rid:
                by_rule[rid] = by_rule.get(rid, 0) + 1
        if status == "open":
            open_by_stage[stage or "待归因"] = open_by_stage.get(stage or "待归因", 0) + 1
    drafts = [{"stage": s, "open_n": n,
               "draft": (f"v3 升级议题草稿：环节 {s} 累计 {n} 条 open badcase，"
                         "建议立项评审触发规则与归因证据后升级对应模块。"
                         "本草稿为建议文本，不改任何配置。")}
              for s, n in sorted(open_by_stage.items()) if n >= 5]
    return {"total": len(rows), "by_stage": by_stage, "by_rule": by_rule,
            "by_severity": by_sev, "by_status": by_status,
            "open_by_stage": open_by_stage, "issue_drafts": drafts}


def badcase_events(badcase_id: str) -> list:
    with _con() as con:
        rows = con.execute(
            "SELECT from_status,to_status,actor,note,created_at FROM badcase_events"
            " WHERE badcase_id=? ORDER BY id", (badcase_id,)).fetchall()
    return [{"from_status": a, "to_status": b, "actor": c, "note": d, "created_at": e}
            for a, b, c, d, e in rows]


def turn_query(turn_id) -> str:
    if not turn_id:
        return ""
    with _con() as con:
        r = con.execute("SELECT user_query FROM turns WHERE turn_id=?",
                        (turn_id,)).fetchone()
    return r[0] if r else ""


def request_query(request_id) -> str:
    if not request_id:
        return ""
    with _con() as con:
        r = con.execute("SELECT query FROM requests WHERE id=?",
                        (request_id,)).fetchone()
    return r[0] if r else ""


def turn_id_of(session_id: str, turn_no: int) -> int | None:
    with _con() as con:
        r = con.execute("SELECT turn_id FROM turns WHERE session_id=? AND turn_no=?",
                        (session_id, turn_no)).fetchone()
    return r[0] if r else None


def list_turns(session_id: str) -> list:
    """前端刷新恢复用：该会话全部可展示轮（ok+refused），按时间正序。"""
    with _con() as con:
        rows = con.execute(
            "SELECT turn_no,user_query,intent_label,retrieved_law_ids,answer,citations,"
            "judge_scores,status,used_history_article_ids FROM turns"
            " WHERE session_id=? AND status IN ('ok','refused') ORDER BY turn_id",
            (session_id,)).fetchall()
    return [{"turn_no": r[0], "user_query": r[1], "intent_label": r[2],
             "retrieved_law_ids": json.loads(r[3] or "[]"), "answer": r[4],
             "citations": json.loads(r[5] or "[]"), "judge_scores": json.loads(r[6]) if r[6] else None,
             "status": r[7], "used_history_article_ids": json.loads(r[8] or "[]")}
            for r in rows]


# ---------------- 知识库 ----------------

_chunks_cache = {"mtime": 0, "rows": []}


def chunks() -> list:
    m = CHUNKS.stat().st_mtime
    if m != _chunks_cache["mtime"]:
        _chunks_cache["rows"] = [json.loads(l) for l in open(CHUNKS, encoding="utf-8")]
        _chunks_cache["mtime"] = m
    return _chunks_cache["rows"]


def get_chunk(cid: str) -> dict | None:
    return next((r for r in chunks() if r["id"] == cid), None)


def list_chunks(law: str = "", search: str = "", page: int = 1, size: int = 20) -> dict:
    rows = chunks()
    if law:
        rows = [r for r in rows if r["law"] == law]
    if search:
        s = search.strip()
        rows = [r for r in rows if s in r["text"] or s in r["article_no"] or s in r["id"]]
    total = len(rows)
    return {"total": total, "page": page, "size": size,
            "items": [{**r, "text": r["text"][:120]} for r in rows[(page - 1) * size: page * size]]}


def _write_chunks(rows: list) -> None:
    with open(CHUNKS, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    _chunks_cache["mtime"] = 0


def _sqlite_upsert(r: dict, delete: bool = False) -> None:
    con = sqlite3.connect(SQLITE)
    if delete:
        con.execute("DELETE FROM articles WHERE id=?", (r["id"],))
    else:
        con.execute(
            "INSERT OR REPLACE INTO articles VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (r["id"], r["law"], r["article_no"], r.get("book"), r.get("chapter"),
             r.get("clause"), r["text"], r.get("version", ""), r.get("effective_date", ""),
             r.get("status", "现行有效"), json.dumps(r.get("keywords", []), ensure_ascii=False)))
    con.commit()
    con.close()


_bge_model = None


def _embed(text: str):
    global _bge_model
    if _bge_model is None:
        from FlagEmbedding import BGEM3FlagModel
        _bge_model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=False)
    return _bge_model.encode([text], return_dense=True, return_sparse=True)


def _qdrant_sync(r: dict, delete: bool = False) -> None:
    """按 payload.id 定位整型 point id，做向量/载荷同步。编辑后重新嵌入正文。"""
    from qdrant_client import QdrantClient
    from qdrant_client.models import (FieldCondition, Filter, MatchValue, PointStruct,
                                      SparseVector)
    client = QdrantClient(path=str(QDRANT))
    col = "law_articles_v0_5"
    filt = Filter(must=[FieldCondition(key="id", match=MatchValue(value=r["id"]))])
    found = client.scroll(col, scroll_filter=filt, limit=1, with_payload=False)[0]
    if delete:
        if found:
            client.delete(col, points_selector=[p.id for p in found])
        client.close()
        return
    # 与建库一致的 rich 嵌入文本（条号+章+正文）；aliases 不重生成，见交付说明
    emb_text = f"《{r['law']}》{r['article_no']}\n{r.get('chapter') or ''}\n{r['text']}"
    emb = _embed(emb_text)
    lw = sorted(emb["lexical_weights"][0].items())
    vec = {"dense": emb["dense_vecs"][0].tolist(),
           "sparse": SparseVector(indices=[k for k, _ in lw], values=[v for _, v in lw])}
    if found:
        pid = found[0].id
        client.update_vectors(col, points=[PointStruct(id=pid, vector=vec)])
        client.set_payload(col, payload=r, points=[pid])
    else:
        nxt = (client.get_collection(col).points_count or 0) + 10000
        client.upsert(col, points=[PointStruct(id=nxt, vector=vec, payload=r)])
    client.close()


def _audit(action: str, cid: str, old: dict | None, new: dict | None) -> None:
    with _lock, _con() as con:
        con.execute("INSERT INTO audit (ts,action,chunk_id,old_value,new_value) VALUES (?,?,?,?,?)",
                    (time.time(), action, cid,
                     json.dumps(old, ensure_ascii=False) if old else None,
                     json.dumps(new, ensure_ascii=False) if new else None))


def save_chunk(cid: str, patch: dict) -> dict:
    with _lock:
        rows = chunks()
        old = next((r for r in rows if r["id"] == cid), None)
        if old is None:
            raise KeyError(cid)
        new = {**old, **{k: v for k, v in patch.items() if k in
                         ("text", "article_no", "chapter", "status", "book", "clause")}}
        _write_chunks([new if r["id"] == cid else r for r in rows])
        _sqlite_upsert(new)
        _qdrant_sync(new)
        _audit("update", cid, old, new)
        return new


def create_chunk(r: dict) -> dict:
    with _lock:
        rows = chunks()
        if any(x["id"] == r["id"] for x in rows):
            raise ValueError("id 已存在")
        r.setdefault("version", "手工新增")
        r.setdefault("effective_date", "")
        r.setdefault("status", "现行有效")
        r.setdefault("keywords", [])
        _write_chunks(rows + [r])
        _sqlite_upsert(r)
        _qdrant_sync(r)
        _audit("create", r["id"], None, r)
        return r


def delete_chunk(cid: str) -> None:
    with _lock:
        rows = chunks()
        old = next((r for r in rows if r["id"] == cid), None)
        if old is None:
            raise KeyError(cid)
        _write_chunks([r for r in rows if r["id"] != cid])
        _sqlite_upsert(old, delete=True)
        _qdrant_sync(old, delete=True)
        _audit("delete", cid, old, None)
