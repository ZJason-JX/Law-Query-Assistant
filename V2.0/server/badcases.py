# -*- coding: utf-8 -*-
"""Badcase 自动收集与归因（旁路能力，不进任何 prompt、不改核心链路）。

两条采集通道：
  live —— 在线，只有确定性信号（审计 ungrounded / intent conf / fp / 门控轮次 / 延迟）；
  eval —— 离线跑批，另含 judge 五维分与 gold 法条，可写「低得分环节」。
规则只用确定性判定，不新增任何模型调用；判定证据写进 triggered_rules。
"""
import json
import re
import time
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]

# ---------------- 规则与阈值（配置常量，不散落） ----------------

FP_CORRECT_TH = 0.5      # B4：false_premise 超过此值且答案未纠正 → S0
FP_VETO_TH = 0.9         # B2：极端错误前提（对抗 proxy）仍照答 → S1，P0
CONF_LOW_TH = 0.85       # B3：intent confidence 低于此值或路由落 other → S0
LATENCY_SLOW_MS = 45000  # B10：端到端延迟上限 → 性能
OPEN_ISSUE_N = 5         # 同环节 open 累计达此数 → 产出升级议题草稿

# 「纠正前提」措辞清单：答案出现任一即视为已做前提纠正
CORRECTION_MARKERS = ["前提", "不成立", "并非", "误传", "纠正", "误区",
                      "该说法", "需要指出", "并不存在", "不合法", "误解"]

RULES = {
    "B1":  {"channel": "live",   "stage": "S5", "severity": "P0",
            "desc": "outside_context > 0（引用脱离检索上下文）"},
    "B2":  {"channel": "live",   "stage": "S1", "severity": "P0",
            "desc": "对抗样本 veto FAIL（fp≥0.9 且未纠正仍照答）"},
    "B3":  {"channel": "live",   "stage": "S0", "severity": "P1",
            "desc": "intent confidence < 0.85 或路由落 other（非 off-topic）"},
    "B4":  {"channel": "live",   "stage": "S0", "severity": "P1",
            "desc": "false_premise > 0.5 且答案未含纠正前提措辞"},
    "B5":  {"channel": "live",   "stage": "S3", "severity": "P1",
            "desc": "追加轮用满且充分性仍不达标（目标法条仍不在候选的代理信号）"},
    "B6":  {"channel": "manual", "stage": "待归因", "severity": "P1",
            "desc": "用户点踩 / 人工标记"},
    "B7":  {"channel": "eval",   "stage": "按维度映射", "severity": "P1",
            "desc": "五维任一维 ≤3（1–5 制）"},
    "B8":  {"channel": "eval",   "stage": "S5", "severity": "P0",
            "desc": "安全性 < 5"},
    "B9":  {"channel": "eval",   "stage": "S1", "severity": "P1",
            "desc": "gold 法条不在 top-10"},
    "B10": {"channel": "live",   "stage": "性能", "severity": "P2",
            "desc": "端到端延迟 > 45s"},
}

# B7 低分维度 → 主责环节
DIM_STAGE = {"准确性": "S4", "相关性": "S4", "完整性": "S3",
             "简洁性": "S4", "安全性": "S5"}

SEV_ORDER = {"P0": 0, "P1": 1, "P2": 2}

# judge 冤判措辞：判词含「编造/虚构/伪造/杜撰/捏造」且未被否定词修饰；
# 需同时满足 安全性≤3（判了引用真实性）+ 审计零 outside_context（证据反驳）。
JUDGE_FAB_PAT = re.compile(
    r"(?<!未)(?<!不)(?<!无)(?<!非)(?<!并不)编造|(?<!未)(?<!不)(?<!无)(?<!非)虚构|伪造|杜撰|捏造")

STATUS_FLOW = {"open": ["triaged", "dismissed"],
               "triaged": ["linked", "open"],
               "linked": ["verified", "open"],
               "verified": ["closed"],
               "dismissed": ["open"],
               "closed": []}

STAGES = ["S0", "S1", "S2", "S3", "S4", "S5", "性能", "待归因"]


def _has_correction(answer: str) -> bool:
    return any(m in (answer or "") for m in CORRECTION_MARKERS)


def _ev(rule_id: str, threshold, observed, evidence: str) -> dict:
    return {"rule_id": rule_id, "threshold": threshold,
            "observed": observed, "evidence": evidence}


def _new_badcase(source, trig, scores, fk):
    """severity 取最高；primary_stage 取最高严重度规则对应环节（P0 优先）。"""
    from server import store
    sev = min((RULES[t["rule_id"]]["severity"] for t in trig), key=lambda s: SEV_ORDER[s])
    top = next(t for t in trig if RULES[t["rule_id"]]["severity"] == sev)
    stages = [RULES[t["rule_id"]]["stage"] for t in trig
              if RULES[t["rule_id"]]["stage"] != "按维度映射"]
    primary = RULES[top["rule_id"]]["stage"]
    if primary == "按维度映射":
        primary = top.get("mapped_stage") or "待归因"
    secondary = [s for s in dict.fromkeys(stages) if s != primary]
    row = {
        "badcase_id": f"bc-{source}-{uuid.uuid4().hex[:12]}",
        "source": source, "triggered_rules": trig,
        "primary_stage": primary, "secondary_stages": secondary,
        "severity": sev, "scores": scores, "status": "open",
        **fk,
    }
    store.insert_badcase(row)
    return row


# ---------------- live 通道（确定性信号，无 judge 分） ----------------

def collect_live(query: str, res: dict, audit: dict, latency_ms: int,
                 session_id: str = "", turn_id=None, request_id=None) -> list:
    """S5 审计完成后旁路调用。返回本次新建的 badcase 摘要（给 SSE answer 角标）。
    demo/failed 轮不进入本函数（调用方保证）。"""
    refused = res.get("prompt_file") == "irrelevant.md"
    trig = []

    if audit.get("ungrounded", 0) > 0:
        trig.append(_ev("B1", "outside_context>0", audit["ungrounded"],
                        f"S5 审计 {audit['n']} 条引用中 {audit['ungrounded']} 条 out-of-context"))

    fp = res.get("false_premise") or 0.0
    corrected = _has_correction(res.get("answer", ""))
    if fp >= FP_VETO_TH and not corrected and not refused:
        trig.append(_ev("B2", f"fp>={FP_VETO_TH} 且未纠正", fp,
                        "极端错误前提未触发纠错/拒答（对抗 veto 的 live 代理信号）"))
    if fp > FP_CORRECT_TH and not corrected and not refused:
        trig.append(_ev("B4", f"fp>{FP_CORRECT_TH} 且未纠正", fp,
                        "false_premise 超过阈值但答案无纠正前提措辞"))

    conf = res.get("confidence")
    if (conf is not None and conf < CONF_LOW_TH) or res.get("intent") == "other":
        trig.append(_ev("B3", f"confidence<{CONF_LOW_TH} 或 intent=other",
                        {"confidence": conf, "intent": res.get("intent")},
                        "意图路由低置信或落入 other 兜底"))

    gates = res.get("react_gates") or []
    if res.get("react_stop") == "max_rounds" and gates:
        last_suff = gates[-1].get("sufficient")
        trig.append(_ev("B5", "react_stop=max_rounds 且最后一轮 sufficient 未达标",
                        {"rounds": res.get("react_rounds"), "last_sufficient": last_suff},
                        "追加轮用满后充分性仍低于门控阈值，目标证据大概率未进候选"))

    if latency_ms and latency_ms > LATENCY_SLOW_MS:
        trig.append(_ev("B10", f"latency>{LATENCY_SLOW_MS}ms", latency_ms,
                        "端到端延迟超上限"))

    if not trig:
        return []
    row = _new_badcase("live", trig, None,
                       {"session_id": session_id, "turn_id": turn_id,
                        "request_id": request_id})
    return [row]


# ---------------- eval 通道（五维分 + gold） ----------------

def _audit_plain(answer: str, retrieved_ids: list, cmap: dict) -> dict:
    """离线确定性审计（无历史轮）：与 server.main._citation_audit 同规则。"""
    from verify_citations import (REUSE_RE, extract_citations, norm_art,
                                  norm_law, quote_ratio)
    ctx = [cmap[r] for r in retrieved_ids if r in cmap]
    keys = {(norm_law(x["law"]), norm_art(x["article_no"])) for x in ctx}
    marked = {(norm_law(l), norm_art(n)) for l, n, _ in REUSE_RE.findall(answer)}
    rows, ung = [], 0
    for c in extract_citations(answer):
        key = (norm_law(c.get("law", "")), norm_art(c.get("article_no", "")))
        in_ctx = False if key in marked else key in keys
        art = next((x for x in ctx
                    if (norm_law(x["law"]), norm_art(x["article_no"])) == key), None)
        qr = round(quote_ratio(c["quote"], art["text"]), 3) if art and c.get("quote") else None
        band = ("outside_context" if not in_ctx else "no_quote" if qr is None else
                "verbatim" if qr >= 0.9 else "paraphrase" if qr >= 0.6 else "unmatched")
        ung += 0 if in_ctx else 1
        rows.append({"law": c.get("law"), "article_no": c.get("article_no"),
                     "in_context": in_ctx, "quote_ratio": qr, "band": band,
                     "turn": c.get("turn")})
    cited_keys = {(norm_law(r["law"]), norm_art(r["article_no"])) for r in rows if r["in_context"]}
    return {"citations": rows, "n": len(rows), "ungrounded": ung, "cited_keys": cited_keys}


def collect_eval(item: dict, rec: dict, dims: dict, mos: float,
                 judge_reason: str, cmap: dict, version: str = "") -> list:
    """run_eval 每条判完分后调用。item=评测集行（含 expected_articles）；
    rec=answers.jsonl 行（含 res 字段 + answer + retrieved_ids）。"""
    from verify_citations import norm_art, norm_law
    trig, tags = [], []
    audit = _audit_plain(rec.get("answer", ""), rec.get("retrieved_ids", []), cmap)

    low = {d: v for d, v in dims.items() if isinstance(v, (int, float)) and v <= 3}
    if low:
        worst = min(low, key=lambda d: (low[d],))
        trig.append({**_ev("B7", "任一维<=3", low,
                           f"低分维度 {worst}={low[worst]}"),
                     "mapped_stage": DIM_STAGE.get(worst, "待归因")})
    if dims.get("安全性") is not None and dims["安全性"] < 5:
        trig.append(_ev("B8", "安全性<5", dims["安全性"], "安全性维度未满分"))

    gold = [(norm_law(a["law"]), norm_art(a["article"])) for a in item.get("expected_articles", [])]
    top10 = {(norm_law(cmap[r]["law"]), norm_art(cmap[r]["article_no"]))
             for r in rec.get("retrieved_ids", []) if r in cmap}
    gold_missing = [g for g in gold if g not in top10]
    gold_in_top = [g for g in gold if g in top10]
    if gold_missing:
        trig.append(_ev("B9", "gold∉top-10", gold_missing,
                        f"{len(gold_missing)}/{len(gold)} 个 gold 法条未进候选（检索）"))

    # ---- 归因覆盖（按证据，可并存：上游缺失为主责，下游未引记次要） ----
    stage_override, extra_ev = None, []
    if gold_missing:
        stage_override = "S1"          # gold 不在 top-10 → 检索
    uncited = [g for g in gold_in_top if g not in audit["cited_keys"]]
    if uncited:
        if not stage_override:
            stage_override = "S4"      # gold 在 top-10 但答案未引用 → 生成选条
        extra_ev.append(_ev("A-S4", "gold∈top10 且未被引用", uncited,
                            "对应已知缺陷 id2/id10：生成选条失败"))
    if dims.get("准确性") is not None and dims["准确性"] <= 3 and audit["ungrounded"] > 0:
        stage_override = "S5"
        extra_ev.append(_ev("A-S5", "准确性≤3 且 outside_context>0",
                            audit["ungrounded"], "低准确性伴随引用脱离上下文"))
    if (dims.get("完整性") is not None and dims["完整性"] <= 3
            and rec.get("react_stop") == "max_rounds"):
        stage_override = "S3"
        extra_ev.append(_ev("A-S3", "完整性≤3 且追加轮用满",
                            rec.get("react_rounds"), "证据不完整与追加轮耗尽共现"))
    # judge 冤判：判了编造/虚构类且安全性扣分，但确定性审计零 outside_context 且引用条目语料存在
    fab = (dims.get("安全性") is not None and dims["安全性"] <= 3
           and JUDGE_FAB_PAT.search(judge_reason or ""))
    if fab and audit["ungrounded"] == 0 and audit["n"] > 0:
        stage_override = "S5"
        tags.append("测量仪器缺陷")
        extra_ev.append(_ev("A-INSTR", "judge 判编造但审计零 outside_context",
                            {"安全性": dims.get("安全性")},
                            "对应已知缺陷 id16：judge 知识边界冤判"))

    if not trig and not stage_override:
        return []
    if not trig:      # 只有归因证据没命中规则时不建例（规则是入口，归因是覆盖）
        return []
    row = _new_badcase("eval", trig,
                       {"dimensions": dims, "mos": mos, "reason": judge_reason,
                        "item_id": item.get("id"), "version": version},
                       {"session_id": None, "turn_id": None, "request_id": None})
    if stage_override:
        from server import store
        row["primary_stage"] = stage_override
        row["triggered_rules"] = row["triggered_rules"] + extra_ev
        row["instrument_defect"] = "测量仪器缺陷" in tags
        sec = [s for s in ([stage_override] + [RULES[t["rule_id"]]["stage"]
               for t in row["triggered_rules"] if t["rule_id"] in RULES])
               if s != "按维度映射"]
        secondary = [s for s in dict.fromkeys(sec) if s != stage_override]
        store.update_badcase_fields(row["badcase_id"],
                                    primary_stage=stage_override,
                                    secondary_stages=secondary,
                                    triggered_rules=row["triggered_rules"])
        row["secondary_stages"] = secondary
    return [row]


# ---------------- 手动通道 ----------------

def collect_manual(note: str = "", session_id: str = "",
                   turn_id=None, request_id=None, actor: str = "user") -> dict:
    trig = [_ev("B6", "人工标记", note, "用户点踩 / 人工标记")]
    return _new_badcase("manual", trig, None,
                        {"session_id": session_id, "turn_id": turn_id,
                         "request_id": request_id})


# ---------------- 状态机 ----------------

def transition(badcase_id: str, to_status: str, actor: str = "admin",
               note: str = "", fields: dict = None) -> dict:
    from server import store
    row = store.get_badcase(badcase_id)
    if not row:
        raise KeyError(badcase_id)
    frm = row["status"]
    if to_status not in STATUS_FLOW.get(frm, []):
        raise ValueError(f"非法状态流转 {frm} → {to_status}（允许：{STATUS_FLOW.get(frm)}）")
    if to_status == "dismissed" and not note:
        raise ValueError("dismissed 必须填写 note（误报原因）")
    if to_status == "verified":
        raise ValueError("verified 只能经 POST /api/badcases/{id}/verify 回填验证后置位")
    upd = {"status": to_status}
    if fields:
        for k in ("primary_stage", "linked_case_id", "linked_issue_id"):
            if fields.get(k) is not None:
                upd[k] = fields[k]
    store.update_badcase_fields(badcase_id, **upd)
    store.add_badcase_event(badcase_id, frm, to_status, actor, note)
    return store.get_badcase(badcase_id)


def resolve_query(row: dict) -> str:
    """回查 query 正文（不存副本）：turns → requests → 评测集 item_id。"""
    from server import store
    if row.get("turn_id"):
        q = store.turn_query(row["turn_id"])
        if q:
            return q
    if row.get("request_id"):
        q = store.request_query(row["request_id"])
        if q:
            return q
    scores = row.get("scores") or {}
    iid, ver = scores.get("item_id"), scores.get("version")
    if iid:
        for ds in ("dataset.jsonl", "dataset_v2.jsonl",
                   "dataset_v3_single.jsonl", "dataset_v3_multi.jsonl"):
            fp = BASE / "evals" / ds
            if not fp.exists():
                continue
            txt = open(fp, encoding="utf-8").read()
            dec, idx = json.JSONDecoder(), 0
            while idx < len(txt):
                while idx < len(txt) and txt[idx] in " \n\r\t":
                    idx += 1
                if idx >= len(txt):
                    break
                obj, idx = dec.raw_decode(txt, idx)
                if obj.get("id") == iid and obj.get("query"):
                    return obj["query"]
    return ""
