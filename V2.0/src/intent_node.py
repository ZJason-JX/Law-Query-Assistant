# -*- coding: utf-8 -*-
"""JEV 意图路由节点：一次 system_one 调用同时拿 intent(Choice) 与 false_premise(Noul)。

模型 pin jev-1.13.0；key 从环境变量 TYPESAFE_API_KEY 读取（项目 .env 由调用方加载）。
路由规则见 route()；置信度不足一律降级 general 三段式。
"""
import os
import time
from pathlib import Path

MODEL = "jev-1.13.0"
REFUSAL = "本助手仅回答法律条文相关问题，请调整提问"

INTENT_OPTIONS = {
    "irrelevant": "与法律/法条完全无关的闲聊、写作、天气等请求",
    "elements_liability": "构成要件与归责：侵权/合同等法律责任是否成立、由谁承担、归责原则，责任或赔偿（含精神损害赔偿、雇主责任）的构成要件与法律依据，义务的法定标准；问'合法吗/行不行/能不能/有效吗'的问句，需要先拆解法定要件才能作答的，归此类——不要因为措辞简短就判为检索型",
    "statute_lookup": "法条精准检索：问某条文的明文规定、期限、数额、程序，或某权利是否有法定依据等可直接查表的法定标准；仅限直接询问法定标准、期限、数额、条号的问句，需要判断某行为是否合法的，不归此类",
    "rule_conflict": "规则冲突与适用：一般法与特别法、原则与例外、责任主体顺位、多项费用/请求权相互返还或抵扣时如何适用法律",
    "concept_definition": "法律概念界定：法律术语、某项权利或制度的性质、内涵外延、设立形式与生效要件、归属界定、与相似概念的区分",
    "other": "以上都不符合",
}
LEGAL_INTENTS = {"elements_liability", "statute_lookup", "rule_conflict", "concept_definition"}

_client = None


def _get_client():
    global _client
    if _client is None:
        if not os.environ.get("TYPESAFE_API_KEY"):
            raise SystemExit("缺少 TYPESAFE_API_KEY：请在 .env 中配置后再跑（JEV 意图节点必需）")
        import typesafe_sdk as ts
        _client = ts.TypeSafeClient(model=MODEL)
    return _client


# 多轮注入规则段：仅 history_str 非空时追加到对应 question 的 instructions（空历史逐字节不变）。
HIST_RULE_INTENT = (
    "\n【历史对话变量】本次请求含 conversation_history 块，它是当前对话框的历史记录"
    "（历轮 用户query / 命中法条 / 回答），不是本次分类对象。本次分类对象只有 user_query。\n"
    "1. 只用历史解析 user_query 中的指代与省略（「它」「这条」「那刚才那个」「如果是个人呢」），"
    "补全语义后再判意图。\n"
    "2. 纯追问 / 澄清 / 条件变体，主意图沿用上一轮，不要判成新类别或「其他」。\n"
    "3. 不要因为历史里出现过某类法条，就把当前 query 归到该类。\n"
    "4. history 中标 [拒答轮] 的轮次，不构成本轮拒答依据，也不影响分类。\n"
    "5. 输出沿用原 JSON schema，不新增字段，不把历史内容写进结果。")
HIST_RULE_FP = ("\n历史对话块仅为语境，false_premise 只针对当前 user_query 判定，"
                "标 [拒答轮] 的历史轮不构成拒答依据。")
HIST_RULE_GATE = (
    "\n【历史对话变量】conversation_history 是当前对话框历史"
    "（含历轮已命中法条，标【该轮答案实际引用】的为被该轮答案实际引用过的法条）；"
    "本轮「已检索到的法条」才是新证据。\n"
    "1. 判断「回答当前 query 所需证据是否充分」时，可把历史轮次中标【该轮答案实际引用】的法条"
    "计入已有证据；只命中但未被引用（检索噪声）不计入，与当前 query 无关的也不计入。\n"
    "2. 指代性追问在历史法条已覆盖时应判 sufficient，不要因为本轮检索条数少就触发追加轮。\n"
    "3. suff 只反映当前 query 的证据缺口，不因历史轮次多、话题复杂而压低。\n"
    "4. 触发追加轮时，追加检索词必须来自检索词节点补全后的语义，不得原样重复上一轮 query。\n"
    "5. 标 [拒答轮] 的历史轮不计入已有证据，不构成本轮拒答依据。\n"
    "6. 输出沿用原 schema。")


def classify(query: str, history_str: str = "") -> dict:
    """一次 JEV 调用，返回 intent/confidence/false_premise 及延迟、用量、模型版本。"""
    import typesafe_sdk as ts
    t0 = time.time()
    intent_instr = "判断该用户问题的类型"
    fp_instr = "该问题是否隐含法律上不成立或常见误传的前提"
    inp = query
    if history_str:
        inp = f"{history_str}\n\n{query}"
        intent_instr += HIST_RULE_INTENT
        fp_instr += HIST_RULE_FP
    r = _get_client().system_one(
        inp,
        questions={
            "intent": ts.Choice(
                instructions=intent_instr,
                criteria=INTENT_OPTIONS),
            "false_premise": ts.Noul(
                instructions=fp_instr),
        })
    ca, na = r.choices["intent"], r.nouls["false_premise"]
    return {
        "intent": ca.choice,
        "confidence": round(ca.confidence, 4),
        "probabilities": {k: round(v, 4) for k, v in ca.probabilities.items()},
        "false_premise": round(na.noul, 4),
        "jev_model": r.model,
        "jev_latency_ms": round((time.time() - t0) * 1000),
        "jev_usage": {"input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens},
    }


def evidence_gate(query: str, articles_summary: str, ask_fp: bool = True,
                  history_str: str = "") -> dict:
    """S2 证据充分性门控：一次 JEV 调用拿 sufficient_evidence(+false_premise) 两个 Noul。

    state = 用户问题 + 已召回法条清单；false_premise 只在首轮需要（它是问题本身的属性）。
    history_str 非空时拼进 state 头部并给 instructions 追加多轮规则。
    返回 {"sufficient": float, "false_premise": float|None, "jev_usage": {...},
          "jev_latency_ms": int}
    """
    import typesafe_sdk as ts
    state = f"用户问题：{query}\n已检索到的法条：\n{articles_summary}"
    suff_instr = "依据当前已检索到的这些法条，已经足以完整回答这个问题了吗"
    fp_instr = "该问题是否隐含法律上不成立或常见误传的前提"
    if history_str:
        state = f"{history_str}\n\n{state}"
        suff_instr += HIST_RULE_GATE
        fp_instr += HIST_RULE_FP
    qs = {"sufficient_evidence": ts.Noul(instructions=suff_instr)}
    if ask_fp:
        qs["false_premise"] = ts.Noul(instructions=fp_instr)
    t0 = time.time()
    r = _get_client().system_one(state, questions=qs)
    return {
        "sufficient": round(r.nouls["sufficient_evidence"].noul, 4),
        "false_premise": (round(r.nouls["false_premise"].noul, 4) if ask_fp else None),
        "jev_model": r.model,
        "jev_latency_ms": round((time.time() - t0) * 1000),
        "jev_usage": {"input_tokens": r.usage.input_tokens,
                      "output_tokens": r.usage.output_tokens},
    }


def route(intent: str, confidence: float) -> str:
    """返回 prompts/ 下的模板名；"refuse" 表示固定拒答、不走生成。"""
    if intent == "irrelevant":
        return "refuse" if confidence >= 0.90 else "general"
    if intent in LEGAL_INTENTS and confidence >= 0.85:
        return intent
    return "general"
