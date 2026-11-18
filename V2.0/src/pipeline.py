# -*- coding: utf-8 -*-
"""法律条文问答 pipeline v1.1：JEV 意图路由 → prompts/ 模板 → 冻结检索 → LLM 生成。

冻结配置见 retrieval_config.json；env：
  GEN_PROVIDER=deepseek|doubao   默认 deepseek（跑通后切 doubao）
  DEEPSEEK_API_KEY / DOUBAO_API_KEY / TYPESAFE_API_KEY 从项目根 .env 读取
用法: python src/pipeline.py "你的问题" [--provider doubao]
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tools"))
sys.path.insert(0, str(BASE.parent / "evals"))

PROMPT_DIR = BASE.parent / "prompts"

# ---- .env ----
for line in open(BASE.parent / ".env", encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1)
        os.environ.setdefault(k, v)

CONFIG = json.load(open(BASE / "retrieval_config.json", encoding="utf-8"))

PROVIDERS = {
    "deepseek": {"url": "https://api.deepseek.com/chat/completions", "key": "DEEPSEEK_API_KEY",
                 "model": "deepseek-chat"},
    # 火山方舟 OpenAI 兼容端点；model 值为接入点/模型名，错了会报 404，见报错信息自行改 MODEL 环境变量
    "doubao": {"url": "https://ark.cn-beijing.volces.com/api/v3/chat/completions", "key": "DOUBAO_API_KEY",
               "model": os.environ.get("DOUBAO_MODEL", "doubao-pro-32k-240828")},
}

def call_llm(provider: str, messages: list, temperature: float = 0.2) -> str:
    p = PROVIDERS[provider]
    body = json.dumps({"model": p["model"], "messages": messages, "temperature": temperature}).encode("utf-8")
    req = urllib.request.Request(p["url"], data=body, headers={
        "Authorization": f"Bearer {os.environ[p['key']]}", "Content-Type": "application/json"})
    last = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            last = f"[{provider}] HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}"
        except Exception as e:
            last = f"[{provider}] {type(e).__name__}: {e}"
        time.sleep(2 ** attempt)
    raise SystemExit(last)


def expand_query(query: str, history_str: str = "") -> list:
    from query_expand import PROMPT_TMPL, expand  # 复用评测侧同一份改写逻辑（红线同源）
    return expand(os.environ["DEEPSEEK_API_KEY"], query, history_str=history_str)


# 多轮注入规则段（节点 D 生成）：仅 history_str 非空时追加到 system prompt 末尾。
HIST_RULE_GEN = (
    "【历史对话变量】conversation_history 是当前对话框历史（历轮 query / 命中法条 / 回答），"
    "user_query 是本次要回答的问题。\n"
    "1. 用历史补全指代与省略，回答承接上文但不得把历史答案原样复述当新答案。\n"
    "2. 结论必须逐条落到法条：本轮检索到的法条，或历史已命中且你显式标注「沿用第N轮」的法条。"
    "不得引用历史里未重新命中、也未标注沿用的内容。\n"
    "3. 沿用历史法条时，答案末尾引用 JSON 增加 \"turn\": N（N = 对话中显示的轮次序号），"
    "正文上标写《法名》第X条（沿用第N轮）。turn 只是索引，合法性由引用审计回查数据库判定。\n"
    "4. history 中标 [拒答轮] 的轮次，不构成本轮拒答依据，不得据此拒答。\n"
    "5. 知识边界自白、选条通则、密度约束等 v1.2 既有规则全部继续生效，优先级高于本节。")


_bge = None
RRF_K = 60


def _emit(cb, stage: str, **data) -> None:
    """观测用事件回调（SSE 推送）；不传入时零开销，不改变任何链路行为。"""
    if cb:
        cb(stage, data)


def retrieve(query: str, topk: int = 10, queries: list = None) -> list:
    return [e["payload"] for e in _retrieve_pool(query, queries)[:topk]]


def retrieve_detail(query: str, queries: list, topk: int = 10) -> list:
    """观测面板用：同 retrieve 管线但返回每条的 dense/sparse/rrf 明细。"""
    return _retrieve_pool(query, queries)[:topk]


def _retrieve_pool(query: str, queries: list = None, pool: dict = None,
                   rrf_weight: float = 1.0, history_str: str = "") -> list:
    """queries 经 dense+sparse 两路 RRF 累加入 pool（外部传入则累积，ReAct 追加轮复用）。
    rrf_weight<1 用于追加轮降权，防止批量新条目挤掉首轮命中。
    返回按 rrf 降序的条目列表；调用方持有的 pool dict 会被原地填充。"""
    from FlagEmbedding import BGEM3FlagModel
    from qdrant_client import QdrantClient
    from qdrant_client.models import SparseVector

    global _bge
    if queries is None:
        queries = [query] + expand_query(query, history_str=history_str)
    if _bge is None:
        _bge = BGEM3FlagModel("BAAI/bge-m3", use_fp16=False)
    client = QdrantClient(path=str(BASE / "db" / "qdrant_storage"))
    if pool is None:
        pool = {}
    for qx in queries:
        emb = _bge.encode([qx], return_dense=True, return_sparse=True, return_colbert_vecs=False)
        lw = sorted(emb["lexical_weights"][0].items())
        sv = SparseVector(indices=[k for k, _ in lw], values=[v for _, v in lw])
        for lane, qq in (("dense", emb["dense_vecs"][0].tolist()), ("sparse", sv)):
            r = client.query_points(CONFIG["vector_store"]["collection"], query=qq, using=lane,
                                    limit=CONFIG["retrieval"]["lane_fetch"], with_payload=True)
            for rank, pt in enumerate(r.points, 1):
                rid = pt.payload["id"]
                ent = pool.setdefault(rid, {"payload": pt.payload, "rrf": 0.0,
                                            "dense": None, "sparse": None})
                ent["rrf"] += rrf_weight / (RRF_K + rank)
                if ent[lane] is None or ent[lane][1] > rank:
                    ent[lane] = (pt.score, rank)
    client.close()
    return sorted(pool.values(), key=lambda x: -x["rrf"])


REACT_MAX_ROUNDS = 5
SUFF_TH, FP_TH = 0.9, 0.5


def _gap_query(query: str, arts_summary: str, fp: float, covered: list,
               history_str: str = "") -> str:
    """S3 追加轮查询生成：只看 query+已召回清单，禁接触 expected。"""
    hint = "注意：该问题可能包含错误法律前提，请基于纠正后的前提生成检索查询。\n" \
        if fp > FP_TH else ""
    head = ""
    if history_str:
        from query_expand import HIST_RULE_E
        head = f"{history_str}\n\n{HIST_RULE_E}\n\n"
    txt = call_llm("deepseek", [{"role": "user", "content":
        head +
        f"用户问题：{query}\n已检索到的法条：\n{arts_summary}\n"
        f"已覆盖法律：{'、'.join(covered)}\n{hint}"
        "若问题涉及多部法律，优先生成针对尚未覆盖法律的检索查询；"
        "否则针对上述法条可能未覆盖的角度（其他法律关系、后果/救济、例外情形、被引用条款）。"
        "只输出一行查询文本。"}],
        temperature=0.0)
    return txt.strip().strip('"“”').splitlines()[0].strip()


def _react_loop(query: str, pool: dict, ranked: list, replay: dict = None,
                on_event=None, history_str: str = "") -> tuple:
    """S2 门控 + S3 追加轮（≤5）。suff≥0.9 退出，否则循环到上限。
    replay=trace 字典时复放 gate/new_query（评测确定性）。返回 (ranked, react_meta)。"""
    from intent_node import evidence_gate
    rounds_log, gates_log, n_extra, stop = [], [], 0, None
    while True:
        arts_sum = "\n".join(f"《{e['payload']['law']}》{e['payload']['article_no']}"
                             for e in ranked[:10])
        covered = list(dict.fromkeys(e["payload"]["law"] for e in ranked[:10]))
        if replay is not None:
            g = replay["gates"][min(n_extra, len(replay["gates"]) - 1)]
        else:
            g = evidence_gate(query, arts_sum, ask_fp=(n_extra == 0),
                              history_str=history_str)
            gates_log.append({"sufficient": g["sufficient"],
                              "false_premise": g["false_premise"]})
        suff, fp = g["sufficient"], g.get("false_premise") or 0.0
        _emit(on_event, "S2", round=n_extra, sufficient=suff, false_premise=fp,
              threshold=SUFF_TH, fp_threshold=FP_TH,
              decision="stop" if (suff >= SUFF_TH and fp <= FP_TH) else "loop")
        if suff >= SUFF_TH and fp <= FP_TH:
            stop = "sufficient"
            break
        if replay is not None and n_extra >= len(replay["rounds"]):
            stop = "trace_end"
            break
        if n_extra >= REACT_MAX_ROUNDS:
            stop = "max_rounds"
            break
        nq = replay["rounds"][n_extra]["new_query"] if replay is not None \
            else _gap_query(query, arts_sum, fp, covered, history_str=history_str)
        before = set(pool)
        ranked = _retrieve_pool(nq, [nq], pool=pool, rrf_weight=0.6)
        delta = len(set(pool) - before)
        _emit(on_event, "S3", round=n_extra + 1, new_query=nq, recalled_delta=delta,
              articles=[{"id": e["payload"]["id"], "law": e["payload"]["law"],
                         "article_no": e["payload"]["article_no"],
                         "rrf": round(e["rrf"], 4),
                         "dense_rank": e["dense"][1] if e["dense"] else None,
                         "sparse_rank": e["sparse"][1] if e["sparse"] else None}
                        for e in ranked[:10]])
        rounds_log.append({"round": n_extra + 1, "new_query": nq,
                           "recalled_delta": delta, "sufficient_score": suff, "fp_score": fp})
        n_extra += 1

    head, seen, skipped = [], {}, []
    for e in ranked:
        law = e["payload"]["law"]
        if len(head) < 10 and seen.get(law, 0) < 8:
            head.append(e)
            seen[law] = seen.get(law, 0) + 1
        else:
            skipped.append(e)
    ranked = head + skipped
    return ranked, {"react_rounds": n_extra, "react_stop": stop,
                    "react_gates": gates_log, "react_rounds_log": rounds_log}


def answer(query: str, provider: str = "deepseek", variants: list = None,
           intent: dict = None, temperature: float = 0.0,
           react: object = False, on_event=None, history_str: str = "") -> dict:
    """variants: 评测模式传入已落盘扩展变体（不含原 query）；None 则在线扩展。
    intent: 评测模式传入已落盘 JEV 分类结果；None 则在线调用。
    react: False 关闭；True 在线 ReAct；dict(trace) 复放 ReAct。
    history_str: 会话历史序列化块（server 层拼装）；空串时全链路 prompt 与旧版逐字节一致。"""
    from intent_node import classify, route, REFUSAL

    ic = intent or classify(query, history_str=history_str)
    stem = route(ic["intent"], ic["confidence"])
    _emit(on_event, "S0", intent=ic["intent"], confidence=ic["confidence"],
          false_premise=ic["false_premise"], prompt=stem)
    prompt_file = PROMPT_DIR / ("irrelevant.md" if stem == "refuse" else f"{stem}.md")
    meta = {
        **ic,
        "prompt_file": prompt_file.name,
        "prompt_file_hash": hashlib.sha256(prompt_file.read_bytes()).hexdigest()[:16],
    }
    if stem == "refuse":
        return {"answer": REFUSAL, "retrieved_ids": [], **meta}

    queries = None if variants is None else [query] + list(variants)
    pool = {}
    ranked = _retrieve_pool(query, queries, pool=pool, history_str=history_str)
    _emit(on_event, "S1", articles=[
        {"id": e["payload"]["id"], "law": e["payload"]["law"],
         "article_no": e["payload"]["article_no"], "rrf": round(e["rrf"], 4),
         "dense_rank": e["dense"][1] if e["dense"] else None,
         "sparse_rank": e["sparse"][1] if e["sparse"] else None}
        for e in ranked[:10]])
    if react:
        replay = react if isinstance(react, dict) else None
        ranked, react_meta = _react_loop(query, pool, ranked, replay=replay,
                                        on_event=on_event, history_str=history_str)
        meta.update(react_meta)
    arts = [e["payload"] for e in ranked[:CONFIG["retrieval"]["topk"]]]
    ctx = "\n\n".join(
        f"[{a['law']}{a['article_no']}]{a['text']}" + ("【历史版本】" if a["status"] != "现行有效" else "")
        for a in arts)
    print(f"检索到 {len(arts)} 条:")
    for a in arts:
        print(f"  - {a['law']} {a['article_no']}（{a['status']}）")
    print()

    user = f"用户问题：{query}\n\n检索到的相关法条：\n{ctx}"
    if ic["false_premise"] > 0.5:
        user = "注意：该问题可能隐含法律上不成立或误传的前提。请先指出前提不成立，再给出正确规定。\n\n" + user
    system = prompt_file.read_text(encoding="utf-8")
    if history_str:
        system = system + "\n\n" + HIST_RULE_GEN
        user = f"{history_str}\n\n" + user
    _emit(on_event, "S4", status="start", prompt_file=prompt_file.name)
    text = call_llm(provider, [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], temperature=temperature)
    return {"answer": text, "retrieved_ids": [a["id"] for a in arts], **meta}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--provider", default="deepseek", choices=list(PROVIDERS))
    args = ap.parse_args()
    print(answer(args.query, args.provider)["answer"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
