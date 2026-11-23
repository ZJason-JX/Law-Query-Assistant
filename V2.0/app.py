# -*- coding: utf-8 -*-
"""法律问答助手 2.0 观测面板：链路可视化 / 评测结果 / 法条库浏览。

用法: streamlit run app.py
全部数据来自落盘文件；链路页对自由输入 query 做实时链路演示（JEV+检索+生成）。
"""
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

import streamlit as st

BASE = Path(__file__).resolve().parent          # 法律问答助手2.0/
EVAL = BASE / "evals"
RES = EVAL / "results"
sys.path.insert(0, str(BASE / "src"))
sys.path.insert(0, str(EVAL))

_env = BASE / ".env"
if not _env.exists() and (BASE / ".env.example").exists():
    import shutil
    shutil.copyfile(BASE / ".env.example", _env)
if _env.exists():
    for line in open(_env, encoding="utf-8"):
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            import os
            os.environ.setdefault(k, v)

st.set_page_config(page_title="法律问答助手2.0 观测面板", layout="wide")


@st.cache_data
def load_jsonl(fp):
    return [json.loads(l) for l in open(fp, encoding="utf-8")] if Path(fp).exists() else []


@st.cache_data
def dataset():
    return {r["id"]: r for r in load_jsonl(EVAL / "dataset.jsonl")}


@st.cache_data
def dataset_v2():
    return {r["id"]: r for r in load_jsonl(EVAL / "dataset_v2.jsonl")}


@st.cache_data
def chunks_map():
    return {r["id"]: r for r in load_jsonl(BASE / "src" / "corpus" / "chunks" / "chunks.jsonl")}


@st.cache_data
def versions_summary():
    """扫 results/ 下所有版本目录，聚合可展示的指标行。"""
    rows = []
    for d in sorted(RES.iterdir()):
        if not d.is_dir():
            continue
        rec = {"version": d.name}
        rp = d / "recall_report.json"
        if rp.exists():
            r = json.load(open(rp, encoding="utf-8"))
            rec["类型"] = "检索"
            rec["显性"] = r["slices"].get("显性事实", {}).get("mean_recall")
            rec["隐性"] = r["slices"].get("隐性事实", {}).get("mean_recall")
            rec["对抗"] = r["slices"].get("对抗样本", {}).get("mean_recall")
            rec["verdict"] = r.get("verdict")
            rows.append(rec)
            continue
        sp = d / "summary.json"
        if sp.exists():
            s = json.load(open(sp, encoding="utf-8"))
            sl = s.get("legal_slice", s)
            rec["类型"] = "生成"
            rec["MOS"] = sl.get("mos")
            for k, v in sl.get("dim_avg", {}).items():
                rec[k] = v
            if "intent" in s:
                rec["意图acc"] = s["intent"].get("accuracy_legal20")
            rows.append(rec)
    return rows


def citation_check(answer: str, ctx_ids: list):
    """返回每条引用的分级：not_in_context / paraphrase(<0.9) / verbatim(>=0.9)。"""
    from verify_citations import extract_citations, norm_law, norm_art, quote_ratio
    ctx = [chunks_map()[i] for i in ctx_ids if i in chunks_map()]
    ctx_keys = {(norm_law(a["law"]), norm_art(a["article_no"])) for a in ctx}
    out = []
    for c in extract_citations(answer):
        key = (norm_law(c.get("law", "")), norm_art(c.get("article_no", "")))
        art = next((a for a in ctx if (norm_law(a["law"]), norm_art(a["article_no"])) == key), None)
        qr = round(quote_ratio(c["quote"], art["text"]), 2) if art is not None and c.get("quote") else None
        if key not in ctx_keys:
            grade = "not_in_context"
        elif qr is None:
            grade = "verbatim"      # 无 quote 字段的引用只能校验条号
        elif qr >= 0.9:
            grade = "verbatim"
        elif qr >= 0.6:
            grade = "paraphrase"
        else:
            grade = "miss"
        out.append({"law": c.get("law"), "article_no": c.get("article_no"),
                    "in_context": key in ctx_keys, "grade": grade, "quote_ratio": qr})
    return out


# ============================================================ Tab1 链路
def tab_pipeline():
    st.header("链路可视化")
    col1, col2 = st.columns([1, 2])
    with col1:
        mode = st.radio("输入来源", ["选 dataset 样例", "自由输入", "演示模式"], horizontal=True)
    demo = mode == "演示模式"
    if mode == "选 dataset 样例" or demo:
        ver = "v2" if demo else st.selectbox("数据集", ["v1", "v2"], index=0)
        ds = dataset_v2() if ver == "v2" else dataset()
        replay_dir = "v21_react_e2e" if ver == "v2" else "v1.2_r2"
        exp_file = "query_expanded_v2.jsonl" if ver == "v2" else "query_expanded_v0_3.jsonl"
        default_idx = sorted(ds).index(29) if (demo and 29 in ds) else 0
        qid = st.selectbox("dataset id", sorted(ds), index=default_idx,
                           format_func=lambda i: f"id{i} | {ds[i].get('difficulty', ds[i]['scenario'])} | {ds[i]['query'][:40]}")
        query = ds[qid]["query"]
        item = ds[qid]
    else:
        query = st.text_input("query", "营业场所对顾客的安全保障义务的法定标准是什么？")
        qid, item, replay_dir = None, None, None
        exp_file = "query_expanded_v0_3.jsonl"

    run = st.button("跑链路", type="primary")
    if not run or demo:
        # 离线回放：落盘 answers 直接展示（v1→v1.2_r2, v2→v21_react_e2e）
        if demo:
            st.info("演示模式：id29 对抗题 · ReAct 循环与引用校验已展开")
        ans_rows = {r["id"]: r for r in load_jsonl(RES / replay_dir / "answers.jsonl")} \
            if replay_dir else {}
        if qid and qid in ans_rows:
            r = ans_rows[qid]
            show_chain(r, item, stored=True, demo=demo)
        return

    with st.spinner("意图分类（JEV）..."):
        from intent_node import classify, route, REFUSAL
        ic = classify(query)
        stem = route(ic["intent"], ic["confidence"])
        pf = BASE / "prompts" / ("irrelevant.md" if stem == "refuse" else f"{stem}.md")
        ic.update(prompt_file=pf.name,
                  prompt_file_hash=hashlib.sha256(pf.read_bytes()).hexdigest()[:16],
                  route=stem)

    expansions = {r["id"]: r["variants"] for r in load_jsonl(EVAL / exp_file)}
    variants = expansions.get(qid)
    if stem == "refuse":
        show_intent(ic, st)
        st.warning(f"拒答输出：{REFUSAL}")
        return
    if variants is None:
        from pipeline import expand_query
        variants = expand_query(query)
        st.caption("（自由输入：在线 DeepSeek 扩展）")

    with st.spinner("检索 top-10（dense+sparse×4 query → RRF）..."):
        from pipeline import retrieve_detail
        details = retrieve_detail(query, [query] + variants)

    with st.spinner("生成（doubao）..."):
        from pipeline import call_llm
        ctx = "\n\n".join(f"[{e['payload']['law']}{e['payload']['article_no']}]{e['payload']['text']}"
                          + ("【历史版本】" if e["payload"]["status"] != "现行有效" else "")
                          for e in details)
        user = f"用户问题：{query}\n\n检索到的相关法条：\n{ctx}"
        if ic["false_premise"] > 0.5:
            user = "注意：该问题可能隐含法律上不成立或误传的前提。请先指出前提不成立，再给出正确规定。\n\n" + user
        ans = call_llm("doubao", [{"role": "system", "content": pf.read_text(encoding="utf-8")},
                                  {"role": "user", "content": user}], temperature=0.0)
        r = {"id": qid or "-", "query": query, "answer": ans,
             "retrieved_ids": [e["payload"]["id"] for e in details], **ic}
        r["_details"] = details
        r["_variants"] = variants
        show_chain(r, item, stored=False)


def show_intent(ic, st_):
    st_.subheader("1 · JEV 意图")
    c1, c2, c3, c4 = st_.columns(4)
    c1.metric("intent", ic["intent"])
    c2.metric("confidence", ic["confidence"])
    c3.metric("false_premise", ic["false_premise"])
    c4.metric("route", ic.get("route") or ic.get("prompt_file", "?"))
    st_.caption(f"prompt_file={ic.get('prompt_file')}  sha256={ic.get('prompt_file_hash')}  "
                f"jev={ic.get('jev_model')}  {ic.get('jev_latency_ms')}ms  usage={ic.get('jev_usage')}")


@st.cache_data(show_spinner=False)
def react_round_items(query: str, variants: tuple, new_queries: tuple):
    """复放 ReAct 轮次：首轮池 + 逐轮追加，返回每轮新增 id 列表与最终 top-10。"""
    from pipeline import _retrieve_pool
    pool = {}
    _retrieve_pool(query, [query] + list(variants), pool=pool)
    rounds, ranked = [], None
    for nq in new_queries:
        before = set(pool)
        ranked = _retrieve_pool(nq, [nq], pool=pool)
        rounds.append(sorted(set(pool) - before))
    final_top10 = {e["payload"]["id"] for e in (ranked or [])[:10]} if ranked else set()
    return rounds, final_top10


def _variants_for(qid):
    for fp in ("query_expanded_v2.jsonl", "query_expanded_v0_3.jsonl"):
        exps = {x["id"]: x["variants"] for x in load_jsonl(EVAL / fp)}
        if qid in exps:
            return exps[qid]
    return []


def show_chain(r, item, stored: bool, demo: bool = False):
    st.caption("存储回放" if stored else "实时链路")
    show_intent(r, st)
    st.subheader("2 · 查询扩展")
    variants = r.get("_variants") or _variants_for(r["id"])
    st.write([r["query"]] + list(variants))

    st.subheader("3 · 检索 top-10")
    details = r.get("_details")
    if details is None and r.get("retrieved_ids"):
        # 回放路径：lane 分没落盘，用冻结扩展重算（确定性等价于跑批时的检索）
        exps = _variants_for(r["id"])
        if exps:
            with st.spinner("重算 lane 分（BGE-M3 首次加载约 20s）..."):
                from pipeline import retrieve_detail
                details = retrieve_detail(r["query"], [r["query"]] + exps)
        else:
            details = [{"payload": chunks_map()[i], "rrf": None, "dense": None, "sparse": None}
                       for i in r["retrieved_ids"] if i in chunks_map()]
    expected = set()
    if item:
        for a in item["expected_articles"]:
            expected.add((a["law"], re.sub(r"第|条", "", a["article"])))
    tbl = []
    for rank, e in enumerate(details, 1):
        p = e["payload"]
        hit = (p["law"], re.sub(r"第|条", "", p["article_no"])) in expected
        tbl.append({"rank": rank, "命中期望": "★" if hit else "", "law": p["law"],
                    "article_no": p["article_no"], "book": p.get("book"), "chapter": p.get("chapter"),
                    "dense": f"{e['dense'][0]:.4f}@{e['dense'][1]}" if e.get("dense") else "-",
                    "sparse": f"{e['sparse'][0]:.3f}@{e['sparse'][1]}" if e.get("sparse") else "-",
                    "rrf": f"{e['rrf']:.5f}" if e.get("rrf") else "-", "status": p["status"]})
    st.dataframe(tbl, use_container_width=True)

    # ---- 3.5 ReAct 循环（默认折叠；演示模式自动展开） ----
    rounds_log = r.get("react_rounds_log") or []
    if not rounds_log:
        tr = {x["query_id"]: x for x in load_jsonl(EVAL / "query_expansion_trace.jsonl")}.get(r["id"])
        if tr:
            rounds_log = tr["rounds"]
            r.setdefault("react_gates", tr["gates"])
            r.setdefault("react_stop", tr["stop_reason"])
    gates = r.get("react_gates") or []
    stop = r.get("react_stop")
    STOP_LABEL = {"sufficient": "证据充分 (sufficient≥0.5)",
                  "max_rounds": "轮数上限 (2 轮)",
                  "no_delta": "本轮无增量 (delta=0)"}
    with st.expander(f"3.5 · ReAct 循环 — {len(rounds_log)} 轮 · 终止: "
                     f"{STOP_LABEL.get(stop, stop or '单轮未触发')}", expanded=demo):
        if not rounds_log:
            st.caption("该 query 未进入循环（门控首轮判 sufficient 或无 trace）")
        else:
            new_per_round, final_ids = None, set()
            if st.checkbox("展开逐轮新增条目（本地重算检索，确定性复放，首次约20s）",
                           value=demo, key=f"reactdet_{r['id']}"):
                with st.spinner("复放轮次..."):
                    new_per_round, final_ids = react_round_items(
                        r["query"], tuple(variants),
                        tuple(x["new_query"] for x in rounds_log))
            for i, rd in enumerate(rounds_log):
                g = gates[i] if i < len(gates) else {}
                st.markdown(f"**第 {rd['round']} 轮** · 本轮新增 **{rd['recalled_delta']}** 条")
                st.code(rd["new_query"], language=None)
                c1, c2, c3 = st.columns(3)
                c1.metric("sufficient_evidence", g.get("sufficient", rd.get("sufficient_score")))
                c2.metric("false_premise", g.get("false_premise", rd.get("fp_score")))
                c3.metric("recalled_delta", rd["recalled_delta"])
                if new_per_round is not None:
                    cm = chunks_map()
                    marks = []
                    for rid in new_per_round[i]:
                        p = cm.get(rid, {})
                        in_final = " ★入top10" if rid in final_ids else ""
                        marks.append(f"🟢 《{p.get('law','?')}》{p.get('article_no','?')}{in_final}")
                    st.write("　".join(marks) if marks else "（无新增条）")
            st.caption(f"终止原因：{STOP_LABEL.get(stop, stop)}")

    st.subheader("4 · 生成答案")
    st.markdown(r["answer"])

    # ---- 5 引用校验（三档着色 + in_context 标记 + 六版对比） ----
    st.subheader("5 · 引用校验")
    cits = citation_check(r["answer"], r.get("retrieved_ids", []))
    if not cits:
        st.info("无结构化引用列表（或为拒答）")
    else:
        BADGE = {"verbatim": ("🟢", "原文引用 ≥0.9"), "paraphrase": ("🟡", "改写引用 0.6-0.9"),
                 "miss": ("🔴", "未命中原文 <0.6"), "not_in_context": ("❌", "不在上下文")}
        for c in cits:
            mark, label = BADGE[c["grade"]]
            ctx_mark = "in_context✓" if c["in_context"] else "in_context✗"
            extra = f"quote_ratio={c['quote_ratio']}" if c["quote_ratio"] is not None else "无quote"
            st.write(f"{mark} 《{c['law']}》{c['article_no']} — {label} · {extra} · {ctx_mark}")
    with st.expander("六版引用审计对比（citation_audit）", expanded=demo):
        rates_fp = EVAL / "results" / "citation_audit" / "ungrounded_rates.json"
        if rates_fp.exists():
            rates = json.load(open(rates_fp, encoding="utf-8"))
            tbl2 = [{"版本": v, "引用数": s["n_citations"],
                     "verbatim率": s.get("verbatim_rate"),
                     "unmatched<0.6": s.get("unmatched"),
                     "出context": s.get("outside_context"),
                     "ungrounded率": s.get("ungrounded_rate")}
                    for v, s in rates.items()]
            st.dataframe(tbl2, use_container_width=True)
            st.caption("ungrounded = 条不在 context 或 quote_ratio<0.6；六版全部零出界引用")
        else:
            st.info("未找到 ungrounded_rates.json（先跑 evals/verify_citations.py）")


# ============================================================ Tab2 评测
def tab_eval():
    st.header("评测结果")
    rows = versions_summary()
    st.subheader("消融链总表")
    st.dataframe(rows, use_container_width=True)

    st.subheader("judge 修正前后对照")
    pairs = [("v1_doubao_qwen", "v1.0_judge_fixed"), ("v1.1", "v1.1_judge_fixed")]
    diff = []
    for old, new in pairs:
        so = {r["id"]: r for r in load_jsonl(RES / old / "scores.jsonl")}
        sn = {r["id"]: r for r in load_jsonl(RES / new / "scores.jsonl")}
        for i in sorted(so):
            if i in sn:
                diff.append({"base": old, "id": i, "旧MOS": so[i]["mos"], "新MOS": sn[i]["mos"],
                             "Δ": round(sn[i]["mos"] - so[i]["mos"], 2)})
    st.dataframe(diff, use_container_width=True)

    st.subheader("逐 query 得分明细")
    ver = st.selectbox("版本", sorted(d.name for d in RES.iterdir() if (d / "scores.jsonl").exists()),
                       index=None, placeholder="选版本")
    if ver:
        for r in load_jsonl(RES / ver / "scores.jsonl"):
            with st.expander(f"id{r['id']}  MOS {r['mos']}  {list(r['dimensions'].items())}"):
                st.write(r["reason"])

    st.subheader("意图混淆矩阵 + confidence 直方图")
    ir = RES / "v1.2_r1" / "intent_report.json"
    if ir.exists():
        rep = json.load(open(ir, encoding="utf-8"))
        c1, c2 = st.columns(2)
        c1.write("expected→predicted 计数")
        c1.json(rep["confusion"])
        c2.write("confidence 桶（0.0-1.0 十等分）")
        c2.bar_chart({"count": rep["confidence_histogram_0_1"]})


# ============================================================ Tab3 法条库
def tab_corpus():
    st.header("法条库浏览")
    db = sqlite3.connect(BASE / "src" / "db" / "law_articles.db", check_same_thread=False)
    laws = [r[0] for r in db.execute("select distinct law from articles")]
    ver_s = st.selectbox("版本/状态过滤", ["全部", "现行有效", "历史版本"])

    c1, c2, c3 = st.columns([1, 1, 2])
    law = c1.selectbox("法名", ["全部"] + laws)
    art = c2.text_input("条号跳转（如 1079）", "")
    kw = c3.text_input("全文关键词", "")
    sql, params = "select * from articles where 1=1", []
    if law != "全部":
        sql += " and law=?"; params.append(law)
    if ver_s == "现行有效":
        sql += " and status='现行有效'"
    elif ver_s == "历史版本":
        sql += " and status!='现行有效'"
    if art:
        sql += " and article_no like ?"; params.append(f"%{art}%")
    if kw:
        sql += " and text like ?"; params.append(f"%{kw}%")
    rows = db.execute(sql + " limit 200", params).fetchall()
    st.write(f"{len(rows)} 条")
    for r in rows:
        st.markdown(f"**{r[1]} {r[2]}**（{r[7]}/{r[8]}） {r[6]}")

    st.subheader("反法 2019 / 2025 并排对照")
    a19 = db.execute("select * from articles where law='反不正当竞争法' and version like '%2019%'").fetchall()
    a25 = db.execute("select * from articles where law='反不正当竞争法' and version not like '%2019%'").fetchall()
    cc1, cc2 = st.columns(2)
    for col, rs, tag in ((cc1, a19, "2019历史版"), (cc2, a25, "2025修订版")):
        col.markdown(f"**{tag}（{len(rs)}条）**")
        sel = col.selectbox(f"{tag}条号", [f"{r[2]} {r[6][:20]}" for r in rs])
        if sel:
            r = rs[[f"{x[2]} {x[6][:20]}" for x in rs].index(sel)]
            col.info(f"{r[1]}{r[2]}（{r[8]}）\n\n{r[6]}")


t1, t2, t3 = st.tabs(["链路可视化", "评测结果", "法条库浏览"])
with t1:
    tab_pipeline()
with t2:
    tab_eval()
with t3:
    tab_corpus()
