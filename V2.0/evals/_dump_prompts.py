# -*- coding: utf-8 -*-
"""用真实 session(t-live-3turn)的历史块，渲染 7 个调用点注入后的 prompt 全文（不触网）。"""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
PROJ = BASE.parent
for p in (str(PROJ), str(PROJ / "src"), str(PROJ / "server"), str(BASE)):
    sys.path.insert(0, p)
for line in open(PROJ / ".env", encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1)
        __import__("os").environ.setdefault(k, v)

from server import store  # noqa: E402

H, canon = store.build_history("t-live-3turn")
Q = "换成个体户雇人算不算？"
ARTS = "《劳动合同法》第2条\n《劳动合同法》第10条"

print("=" * 70)
print("【注入变量 history_str】(canonical %d 轮)" % len(canon))
print("=" * 70)
print(H)

import intent_node


class _C:
    def system_one(self, inp, questions):
        return type("R", (), {"choices": {"intent": type("X", (), {
            "choice": "elements_liability", "confidence": 0.9,
            "probabilities": {}})()},
            "nouls": {"sufficient_evidence": type("Y", (), {"noul": 0.1})(),
                      "false_premise": type("Y", (), {"noul": 0.1})()},
            "model": "jev", "usage": type("U", (), {"input_tokens": 0,
                      "output_tokens": 0})()})


intent_node._client = _C()

# ① A: classify —— input + intent/fp instructions
print("\n" + "=" * 70)
print("【节点① A|S0 classify】system_one 输入 inp：")
print("-" * 70)
intent_node.classify(Q, history_str=H)
# re-derive what was passed
import inspect  # noqa: E402
print(f"{H}\n\n{Q}")
print("-" * 70)
print("intent instructions =")
print("判断该用户问题的类型" + intent_node.HIST_RULE_INTENT)
print("-" * 70)
print("false_premise instructions =")
print("该问题是否隐含法律上不成立或常见误传的前提" + intent_node.HIST_RULE_FP)

# ② B: evidence_gate —— state + instructions
print("\n" + "=" * 70)
print("【节点② B|S2 evidence_gate】state：")
print("-" * 70)
print(f"{H}\n\n用户问题：{Q}\n已检索到的法条：\n{ARTS}")
print("-" * 70)
print("sufficient_evidence instructions =")
print("依据当前已检索到的这些法条，已经足以完整回答这个问题了吗" + intent_node.HIST_RULE_GATE)
print("-" * 70)
print("false_premise instructions = 同上 fp 段")

# ③ E×2: expand & _gap_query user 消息
import query_expand  # noqa: E402
print("\n" + "=" * 70)
print("【节点③ E|expand_query】user content：")
print("-" * 70)
print(f"{H}\n\n{query_expand.HIST_RULE_E}\n\n" + query_expand.PROMPT_TMPL.format(query=Q))

print("\n" + "=" * 70)
print("【节点③ E|_gap_query】user content：")
print("-" * 70)
gap_body = (f"用户问题：{Q}\n已检索到的法条：\n{ARTS}\n"
            "已覆盖法律：劳动合同法\n"
            "若问题涉及多部法律，优先生成针对尚未覆盖法律的检索查询；"
            "否则针对上述法条可能未覆盖的角度（其他法律关系、后果/救济、例外情形、被引用条款）。"
            "只输出一行查询文本。")
print(f"{H}\n\n{query_expand.HIST_RULE_E}\n\n" + gap_body)

# ④ D: 生成 system + user
import pipeline  # noqa: E402
sys_prompt = (PROJ / "prompts" / "elements_liability.md").read_text(encoding="utf-8")
print("\n" + "=" * 70)
print("【节点④ D|S4 生成】system = prompts/elements_liability.md 原文 + 追加：")
print("-" * 70)
print(sys_prompt)
print("[追加段]")
print(pipeline.HIST_RULE_GEN)
print("-" * 70)
print("user =")
print(f"{H}\n\n用户问题：{Q}\n\n检索到的相关法条：\n<ctx top-10 法条全文>")

# ⑤ C: judge 追加段 + S5 代码层说明
from server import main as sm  # noqa: E402
print("\n" + "=" * 70)
print("【节点⑤ C|S5+judge】judge_prompt.md 追加段（仅 judge_live 且 history 非空）：")
print(sm.HIST_RULE_JUDGE)
print("-" * 70)
print("S5 _citation_audit 代码层：turn→canonical 回查（见 main.py），不走 prompt。")
