# -*- coding: utf-8 -*-
"""引用溯源审计：逐 query 校验答案末尾结构化引用列表是否落在检索上下文内。

v1.1/v1.2 用落盘的 retrieved_ids；v1.0 未存 retrieved_ids，
用冻结扩展 + 冻结检索重算 top-10 近似（本地 BGE，确定性，结果标注为"重算"）。
输出 results/citation_audit/{per_query_citations.jsonl, ungrounded_rates.json, badcases.jsonl}
"""
import json
import re
import sys
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
PROJ = BASE.parent
sys.path.insert(0, str(PROJ / "src"))

for line in open(PROJ / ".env", encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1)
        os.environ.setdefault(k, v)

VERSIONS = ["v1_doubao_qwen", "v1.1", "v1.2_r1", "v1.2_r2",
            "v21_react_e2e", "v21_react_e2e_r2"]

CIT_RE = re.compile(r"\[\s*\{[^{}]*\"law\"[^{}]*\}\s*(?:,\s*\{[^{}]*\}\s*)*\]", re.S)
INLINE_RE = re.compile(r"《([^》]+)》\s*第([0-9一二三四五六七八九十百千零]+)条(?:（沿用第(\d+)轮）)?")
REUSE_RE = re.compile(r"《([^》]+)》\s*第([0-9一二三四五六七八九十百千零]+)条（沿用第(\d+)轮）")


def norm_law(s: str) -> str:
    return s.replace("《", "").replace("》", "").replace("中华人民共和国", "").strip()


_CN = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7,
       "八": 8, "九": 9, "十": 10, "百": 100, "千": 1000}


def _cn2num(s: str) -> int:
    if s.isdigit():
        return int(s)
    sec, num = 0, 0
    for ch in s:
        v = _CN.get(ch)
        if v is None:
            return -1
        if v >= 10:
            sec += (num or 1) * v
            num = 0
        else:
            num = v
    return sec + num


def norm_art(s: str) -> str:
    m = re.search(r"第(.+?)条", str(s))
    s = m.group(1) if m else re.sub(r"第|条|款|项|\s", "", str(s))
    n = _cn2num(s)
    return str(n) if n >= 0 else s


def norm_text(s: str) -> str:
    return re.sub(r'[\s，。；：、（）()"\'""''【】\[\].,;:…—-]', "", str(s))


def quote_ratio(quote: str, text: str) -> float:
    """quote 在原文中的保真度：匹配块字符数 / quote 长度（容忍摘编、截断、改序标点）。"""
    import difflib
    q, t = norm_text(quote), norm_text(text)
    if not q:
        return 0.0
    sm = difflib.SequenceMatcher(None, q, t, autojunk=False)
    matched = sum(b.size for b in sm.get_matching_blocks())
    return matched / len(q)


def extract_citations(answer: str) -> list:
    m = CIT_RE.search(answer)
    if m:
        try:
            arr = json.loads(m.group(0))
            return [c for c in arr if isinstance(c, dict)]
        except json.JSONDecodeError:
            pass
    # 无结构化列表时退化到《法名》第X条内联引用（v1.0 旧格式）
    seen = set()
    out = []
    for law, no, turn in INLINE_RE.findall(answer):
        k = (norm_law(law), norm_art(no))
        if k not in seen:
            seen.add(k)
            c = {"law": law, "article_no": "第" + no + "条", "quote": None}
            if turn:
                c["turn"] = int(turn)
            out.append(c)
    return out


def main() -> int:
    chunk_map = {json.loads(l)["id"]: json.loads(l)
                 for l in open(PROJ / "src" / "corpus" / "chunks" / "chunks.jsonl", encoding="utf-8")}

    # v1.0 重算上下文（冻结扩展 + 冻结检索，确定性）
    recomputed = {}
    exp_fp = BASE / "query_expanded_v0_3.jsonl"
    v0_needs = [json.loads(l) for l in
                open(BASE / "results" / "v1_doubao_qwen" / "answers.jsonl", encoding="utf-8")]
    if all("retrieved_ids" not in r for r in v0_needs):
        print("v1.0 无 retrieved_ids，用冻结扩展重算检索上下文...")
        from pipeline import retrieve
        exps = {json.loads(l)["id"]: json.loads(l)["variants"]
                for l in open(exp_fp, encoding="utf-8")}
        for r in v0_needs:
            arts = retrieve(r["query"], 10, queries=[r["query"]] + exps.get(r["id"], []))
            recomputed[r["id"]] = arts

    out_dir = BASE / "results" / "citation_audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    detail_fp = open(out_dir / "per_query_citations.jsonl", "w", encoding="utf-8")
    bad_fp = open(out_dir / "badcases.jsonl", "w", encoding="utf-8")

    rates = {}
    for ver in VERSIONS:
        fp = BASE / "results" / ver / "answers.jsonl"
        if not fp.exists():
            continue
        total, miss = 0, 0
        bands = {"verbatim": 0, "paraphrase": 0, "unmatched": 0,
                 "outside_context": 0, "no_quote": 0}
        for l in open(fp, encoding="utf-8"):
            r = json.loads(l)
            if r.get("intent") == "irrelevant" or "本助手仅回答" in r["answer"]:
                continue
            if "retrieved_ids" in r:
                ctx = [chunk_map[i] for i in r["retrieved_ids"] if i in chunk_map]
                ctx_src = "stored"
            else:
                ctx = recomputed.get(r["id"], [])
                ctx_src = "recomputed"
            ctx_keys = {(norm_law(a["law"]), norm_art(a["article_no"])) for a in ctx}
            cits = extract_citations(r["answer"])
            rows = []
            for c in cits:
                key = (norm_law(c.get("law", "")), norm_art(c.get("article_no", "")))
                in_ctx = key in ctx_keys
                art = next((a for a in ctx
                            if (norm_law(a["law"]), norm_art(a["article_no"])) == key), None)
                quote_ok = None
                qr = None
                if art is not None and c.get("quote"):
                    qr = round(quote_ratio(c["quote"], art["text"]), 3)
                    quote_ok = qr >= 0.8
                if not in_ctx:
                    band = "outside_context"
                elif qr is None:
                    band = "no_quote"
                else:
                    band = "verbatim" if qr >= 0.9 else ("paraphrase" if qr >= 0.6 else "unmatched")
                bands[band] += 1
                rows.append({"law": c.get("law"), "article_no": c.get("article_no"),
                             "in_context": in_ctx, "quote_verbatim": quote_ok,
                             "quote_ratio": qr, "band": band})
                total += 1
                # ungrounded 口径：条不在 context 或 quote_ratio<0.6
                if not in_ctx or (qr is not None and qr < 0.6):
                    miss += 1
            rec = {"version": ver, "id": r["id"], "query": r["query"],
                   "ctx_source": ctx_src, "n_citations": len(cits), "citations": rows}
            detail_fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
            bad = [x for x in rows if not x["in_context"] or x["band"] == "unmatched"]
            if bad:
                bad_fp.write(json.dumps({**rec, "bad": bad,
                                         "answer": r["answer"][-1200:]},
                                        ensure_ascii=False) + "\n")
        rates[ver] = {"n_citations": total,
                      "verbatim": bands["verbatim"],
                      "paraphrase": bands["paraphrase"],
                      "unmatched": bands["unmatched"],
                      "outside_context": bands["outside_context"],
                      "no_quote": bands["no_quote"],
                      "verbatim_rate": round(bands["verbatim"] / total, 3) if total else None,
                      "ungrounded": miss,
                      "ungrounded_rate": round(miss / total, 3) if total else None}
        print(ver, rates[ver])

    detail_fp.close(); bad_fp.close()
    json.dump(rates, open(out_dir / "ungrounded_rates.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("saved ->", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
