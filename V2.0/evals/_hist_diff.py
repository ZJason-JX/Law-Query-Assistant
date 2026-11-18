# -*- coding: utf-8 -*-
"""多轮历史功能离线自检（不触网：JEV/DeepSeek/生成全部 stub）。

覆盖验收6：
  a) 空历史：7 个调用点渲染 prompt 与改动前逐字节一致
  b) 有历史：各节点注入位置正确
  c) 引用审计白名单：turn 回查 / refused 轮不合法 / 越界轮次 / 缺 turn 标沿用
  d) 序列化截断（≤3 轮 ≤2000 字、丢最早轮重新编号）与 session 隔离
  e) CIT_RE 兼容 turn 字段；INLINE_RE 捕获「（沿用第N轮）」
  f) 10 轮写入后 prompt 不失控；failed 不占号不进白名单

运行: python -X utf8 evals/_hist_diff.py
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
PROJ = BASE.parent
for p in (str(PROJ), str(PROJ / "src"), str(PROJ / "server"), str(BASE)):
    if p not in sys.path:
        sys.path.insert(0, p)
for line in open(PROJ / ".env", encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1)
        os.environ.setdefault(k, v)

n_pass, n_fail = 0, 0


def check(name, cond, detail=""):
    global n_pass, n_fail
    if cond:
        n_pass += 1
        print(f"PASS {name}")
    else:
        n_fail += 1
        print(f"FAIL {name}  {detail}")


# ---------- fake JEV client ----------
class _CA:
    choice = "statute_lookup"
    confidence = 0.9
    probabilities = {"statute_lookup": 0.9}


class _Noul:
    noul = 0.1


class _Resp:
    model = "jev-1.13.0"
    choices = {"intent": _CA()}
    nouls = {"sufficient_evidence": _Noul(), "false_premise": _Noul()}

    class usage:
        input_tokens = 1
        output_tokens = 1


jev_calls = []


class _FakeClient:
    def system_one(self, inp, questions):
        jev_calls.append({
            "inp": inp,
            "instrs": {k: getattr(v, "instructions", "") for k, v in questions.items()}})
        return _Resp()


import intent_node  # noqa: E402
intent_node._client = _FakeClient()

Q = "公司超过一个月没跟我签劳动合同，能要双倍工资吗？"
H = ("=== 历史对话开始 ===\n[第1轮] 用户问：先前言\n        命中法条：（无）\n"
     "        回答：先答\n=== 历史对话结束 ===")

# ---------- a) classify 空历史逐字节 ----------
intent_node.classify(Q)
c = jev_calls[-1]
check("classify 空历史 input", c["inp"] == Q)
check("classify 空历史 intent instructions",
      c["instrs"]["intent"] == "判断该用户问题的类型")
check("classify 空历史 fp instructions",
      c["instrs"]["false_premise"] == "该问题是否隐含法律上不成立或常见误传的前提")

# ---------- b) classify 有历史 ----------
intent_node.classify(Q, history_str=H)
c = jev_calls[-1]
check("classify 注入历史块在头部", c["inp"] == f"{H}\n\n{Q}")
check("classify instructions 含节点A规则", "【历史对话变量】" in c["instrs"]["intent"]
      and "沿用上一轮" in c["instrs"]["intent"])
check("classify fp instructions 含拒答轮说明", "[拒答轮]" in c["instrs"]["false_premise"])

# ---------- c) evidence_gate 空/有历史 ----------
ARTS = "《劳动合同法》第82条\n《劳动合同法》第10条"
intent_node.evidence_gate(Q, ARTS)
c = jev_calls[-1]
check("gate 空历史 state", c["inp"] == f"用户问题：{Q}\n已检索到的法条：\n{ARTS}")
check("gate 空历史 suff instructions",
      c["instrs"]["sufficient_evidence"] == "依据当前已检索到的这些法条，已经足以完整回答这个问题了吗")
check("gate 空历史 fp instructions",
      c["instrs"]["false_premise"] == "该问题是否隐含法律上不成立或常见误传的前提")

intent_node.evidence_gate(Q, ARTS, history_str=H)
c = jev_calls[-1]
check("gate 注入历史块在 state 头部",
      c["inp"] == f"{H}\n\n用户问题：{Q}\n已检索到的法条：\n{ARTS}")
check("gate instructions 含节点B规则", "【该轮答案实际引用】" in c["instrs"]["sufficient_evidence"])

# ---------- d) expand（DeepSeek user 消息）----------
import query_expand  # noqa: E402

llm_bodies = []


class _HTTPResp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps({"choices": [{"message": {"content": "v1\nv2\nv3"}}]}).encode()


_orig_urlopen = urllib.request.urlopen


def _cap_urlopen(req, timeout=None):
    llm_bodies.append(json.loads(req.data.decode("utf-8")))
    return _HTTPResp()


urllib.request.urlopen = _cap_urlopen
query_expand.expand("K", Q)
check("expand 空历史逐字节",
      llm_bodies[-1]["messages"][0]["content"] == query_expand.PROMPT_TMPL.format(query=Q))
query_expand.expand("K", Q, history_str=H)
check("expand 注入历史+规则在头部",
      llm_bodies[-1]["messages"][0]["content"] ==
      f"{H}\n\n{query_expand.HIST_RULE_E}\n\n" + query_expand.PROMPT_TMPL.format(query=Q))
urllib.request.urlopen = _orig_urlopen

# ---------- e) _gap_query（pipeline.call_llm stub）----------
import pipeline  # noqa: E402

llm_msgs = []
_orig_call = pipeline.call_llm


def _cap_call(provider, messages, temperature=0.2):
    llm_msgs.append({"provider": provider, "messages": messages, "t": temperature})
    return "追加查询词"


pipeline.call_llm = _cap_call
pipeline._gap_query(Q, ARTS, 0.0, ["劳动合同法"])
gap_golden = (f"用户问题：{Q}\n已检索到的法条：\n{ARTS}\n"
              "已覆盖法律：劳动合同法\n"
              "若问题涉及多部法律，优先生成针对尚未覆盖法律的检索查询；"
              "否则针对上述法条可能未覆盖的角度（其他法律关系、后果/救济、例外情形、被引用条款）。"
              "只输出一行查询文本。")
check("_gap_query 空历史逐字节", llm_msgs[-1]["messages"][0]["content"] == gap_golden,
      llm_msgs[-1]["messages"][0]["content"][:80])
pipeline._gap_query(Q, ARTS, 0.0, ["劳动合同法"], history_str=H)
check("_gap_query 注入历史+规则在头部",
      llm_msgs[-1]["messages"][0]["content"] ==
      f"{H}\n\n{query_expand.HIST_RULE_E}\n\n" + gap_golden)

# ---------- f) 生成节点（answer 全链路 stub）----------
FAKE_ART = {"id": "labor-contract-law-82", "law": "劳动合同法", "article_no": "第82条",
            "text": "用人单位自用工之日起超过一个月不满一年未与劳动者订立书面劳动合同的，"
                    "应当向劳动者每月支付二倍的工资。", "status": "现行有效",
            "book": None, "chapter": None, "clause": None}
FAKE_RANKED = [{"payload": FAKE_ART, "rrf": 0.03, "dense": (0.9, 1), "sparse": (0.8, 2)}]


def _fake_pool(query, queries=None, pool=None, rrf_weight=1.0, history_str=""):
    if pool is not None:
        pool.update({FAKE_ART["id"]: FAKE_RANKED[0]})
    return list(FAKE_RANKED)


pipeline._retrieve_pool = _fake_pool
llm_msgs.clear()

pipeline.answer(Q, provider="doubao", react=False)
sys_prompt = (PROJ / "prompts" / "statute_lookup.md").read_text(encoding="utf-8")
ctx = f"[劳动合同法第82条]{FAKE_ART['text']}"
gen_golden_user = f"用户问题：{Q}\n\n检索到的相关法条：\n{ctx}"
gen = llm_msgs[-1]["messages"]
check("生成 空历史 system 逐字节", gen[0]["content"] == sys_prompt)
check("生成 空历史 user 逐字节", gen[1]["content"] == gen_golden_user, gen[1]["content"][:80])

pipeline.call_llm = _cap_call
pipeline.answer(Q, provider="doubao", react=False, history_str=H)
gen = llm_msgs[-1]["messages"]
check("生成 注入后 system=原文+D规则",
      gen[0]["content"] == sys_prompt + "\n\n" + pipeline.HIST_RULE_GEN)
check("生成 注入后 user=历史块头部",
      gen[1]["content"] == f"{H}\n\n" + gen_golden_user)
pipeline.call_llm = _orig_call

# ---------- g) 序列化 + 落库（真实 app.db，测试 session，事后清理）----------
from server import main as sm  # noqa: E402
from server import store  # noqa: E402

CID = "labor-contract-law-82"
chunk = store.get_chunk(CID)
check("测试 chunk 存在", chunk is not None)
if chunk is None:
    CID = store.chunks()[0]["id"]
    chunk = store.get_chunk(CID)

SID_A, SID_B = "t-hist-a", "t-hist-b"
res_stub = {"intent": "statute_lookup", "answer": "答A1", "prompt_file": "general.md"}
laws = [{"law": chunk["law"], "article_no": chunk["article_no"], "chunk_id": CID}]
audit_stub = {"citations": [{"law": chunk["law"], "article_no": chunk["article_no"],
                           "in_context": True, "band": "verbatim", "chunk_id": CID}],
              "n": 1, "ungrounded": 0, "used_history": []}
tn1 = store.save_turn(SID_A, "问A1", res_stub, laws, audit_stub, None, "ok")[0]
tn2 = store.save_turn(SID_A, "问A2拒答", {"intent": "irrelevant",
                    "answer": "本助手仅回答法律条文相关问题，请调整提问",
                    "prompt_file": "irrelevant.md"}, [], {"citations": [], "n": 0,
                    "ungrounded": 0, "used_history": []}, None, "refused")[0]
store.save_failed_turn(SID_A, "问A3挂了", "Timeout")
store.save_turn(SID_B, "问B1", res_stub, laws, audit_stub, None, "ok")
check("turn_no 顺序分配（failed 不占号）", (tn1, tn2) == (1, 2), f"{tn1},{tn2}")

s, canon = store.build_history(SID_A)
check("历史块边界", s.startswith("=== 历史对话开始 ===") and s.endswith("=== 历史对话结束 ==="))
check("failed 不进白名单", "问A3挂了" not in s and len(canon) == 2)
check("拒答轮标记", "[第2轮][拒答轮]" in s)
check("命中法条+已引用标记", f"（chunk_id={CID}）【该轮答案实际引用】" in s)
check("canonical 与序列化同一对象", len(canon) == 2 and canon[0]["user_query"] == "问A1")
sB, _ = store.build_history(SID_B)
check("session 隔离", "问A1" not in sB and "问B1" in sB)

# 10 轮 + 超长回答 → ≤3 轮、≤2000 字、重新编号
for i in range(8):
    store.save_turn(SID_A, f"长问{i}" + "字" * 300, {**res_stub, "answer": "答" * 800},
                    laws, audit_stub, None, "ok")
s2, canon2 = store.build_history(SID_A)
check("≤3 轮入变量", len(canon2) <= 3, str(len(canon2)))
check("总长≤2000", len(s2) <= 2000, str(len(s2)))
check("丢轮重编号从第1轮起", "[第1轮]" in s2)
check("省略标注", "已省略前" in s2 or len(canon2) == 3)

# ---------- h) 引用审计白名单 ----------
ans_ok = (f"答：《劳动合同法》第82条（沿用第1轮）…\n"
          f'[{{"law":"{chunk["law"]}","article_no":"{chunk["article_no"]}",'
          f'"quote":"{chunk["text"][:20]}","turn":1}}]')
a = sm._citation_audit(ans_ok, [], canon)
check("turn 引用回查合法", a["ungrounded"] == 0 and a["citations"][0]["in_context"],
      json.dumps(a["citations"], ensure_ascii=False)[:200])
check("used_history 回填", len(a["used_history"]) == 1 and a["used_history"][0]["from_turn"] == 1)

canon_refused = [dict(canon[0], status="refused")]
a = sm._citation_audit(ans_ok, [], canon_refused)
check("指向 refused 轮 → outside_context", a["ungrounded"] == 1)

ans_bad_turn = ans_ok.replace('"turn":1', '"turn":9')
a = sm._citation_audit(ans_bad_turn, [], canon)
check("越界轮次号 → outside_context", a["ungrounded"] == 1)

ans_no_turn = ans_ok.replace(',"turn":1', '')
a = sm._citation_audit(ans_no_turn, [], canon)
check("正文标沿用但缺 turn → outside_context", a["ungrounded"] == 1,
      json.dumps(a["citations"], ensure_ascii=False)[:200])

ans_fabricated = (f"答：《公司法》第999条（沿用第1轮）…\n"
                  f'[{{"law":"公司法","article_no":"第999条","quote":"编造","turn":1}}]')
a = sm._citation_audit(ans_fabricated, [], canon)
check("编造法条挂 turn → outside_context", a["ungrounded"] == 1)

a = sm._citation_audit(
    f'答：《{chunk["law"]}》{chunk["article_no"]}…\n'
    f'[{{"law":"{chunk["law"]}","article_no":"{chunk["article_no"]}","quote":"{chunk["text"][:20]}"}}]',
    [CID], canon)
check("本轮检索正常引用不受影响", a["ungrounded"] == 0)

# CIT_RE 兼容 turn 字段 + INLINE_RE 捕获标记
from verify_citations import extract_citations  # noqa: E402
cs = extract_citations('[{"law":"公司法","article_no":"第5条","quote":"q","turn":2}]')
check("CIT_RE 解析含 turn 的 JSON", cs and cs[0].get("turn") == 2)
cs = extract_citations("答：《劳动合同法》第82条（沿用第1轮）成立。")
check("INLINE_RE 捕获沿用标记", cs and cs[0].get("turn") == 1)
cs = extract_citations("答：《劳动合同法》第82条成立。")
check("INLINE_RE 无标记时无 turn 键（六版回归保护）", cs and "turn" not in cs[0])

# ---------- 清理测试 session ----------
with store._con() as con:
    con.execute("DELETE FROM turns WHERE session_id IN (?,?)", (SID_A, SID_B))
    con.execute("DELETE FROM sessions WHERE session_id IN (?,?)", (SID_A, SID_B))

print(f"\n{n_pass} PASS / {n_fail} FAIL")
sys.exit(1 if n_fail else 0)
