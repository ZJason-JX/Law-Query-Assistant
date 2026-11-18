# -*- coding: utf-8 -*-
"""v2 评测集候选生成：LLM 从语料反推 query，人筛后成集。

五类候选（共 ~51 条），每条附 basis_articles（出题依据法条）：
  labour      12  劳动法域口语题（解除/补偿/加班/竞业/工伤/试用期）
  multi_hop   12  双法域场景连接题（劳动×公司/劳动×反法/公司×民法典/反法×民法典）
  econ_new     8  经济新条款（反法2025数据权益·平台 / 公司法2023认缴·董监高）
  routine     15  常规题（民法典/公司法/反法/消保法，显性:隐性≈2:1）
  adversarial  4  劳动法/反法易误传前提题

用法: python evals/gen_queries_v2.py
输出: evals/dataset_v2_candidates.jsonl  {cid, category, query, basis_articles, suggested_scenario}
"""
import json
import os
import random
import re
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
PROJ = BASE.parent

for line in open(PROJ / ".env", encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.strip().split("=", 1)
        os.environ.setdefault(k, v)

random.seed(42)

CHUNKS = [json.loads(l) for l in open(PROJ / "src" / "corpus" / "chunks" / "chunks.jsonl", encoding="utf-8")]
BY_LAW = {}
for r in CHUNKS:
    BY_LAW.setdefault((r["law"], r["version"]), []).append(r)

LABOUR_KEYS = {
    "合同解除": ["解除劳动合同", "解除", "提前三十日", "过失性辞退"],
    "经济补偿": ["经济补偿", "补偿金"],
    "加班工时": ["加班", "延长工作时间", "休息日", "工作时间"],
    "竞业限制": ["竞业限制", "竞业"],
    "工伤社保": ["工伤", "社会保险", "工伤保险"],
    "试用期": ["试用期"],
}
NEW_ECON = {
    "anti-unfair-competition-law": ["数据", "平台", "网络"],
    "company-law": ["认缴", "出资期限", "董事", "监事", "高级管理"],
}


def pick(law_ver: tuple, keywords: list, n: int, exclude: set) -> list:
    cands = [r for r in BY_LAW[law_ver]
             if r["id"] not in exclude and any(k in r["text"] for k in keywords)]
    return cands[:n]


def call_llm(prompt: str, temperature: float = 0.7) -> str:
    body = json.dumps({"model": "deepseek-chat",
                       "messages": [{"role": "user", "content": prompt}],
                       "temperature": temperature}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions", data=body,
        headers={"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}",
                 "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"].strip()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def gen_query(arts: list, style: str, hint: str) -> str:
    arts_txt = "\n".join(f"《{a['law']}》（{a['version']}）{a['article_no']}：{a['text'][:260]}"
                         for a in arts)
    p = (f"你是法律评测出题人。依据下列法条，{hint}\n"
         f"要求：\n"
         f"1. query 用{style}问，不得出现条号\n"
         f"2. 答案可由所给法条直接回答\n"
         f"3. 只输出一行 query 文本，不要任何其他内容\n\n"
         f"{arts_txt}")
    q = call_llm(p).strip().strip('"“”').splitlines()[0].strip()
    return q


def basis(arts: list) -> list:
    return [{"law": a["law"], "article_no": a["article_no"], "version": a["version"],
             "chunk_id": a["id"]} for a in arts]


def main() -> int:
    out, used = [], set()
    cid = 0

    def emit(category, arts, scenario, **kw):
        nonlocal cid
        cid += 1
        q = gen_query(arts, **kw)
        for a in arts:
            used.add(a["id"])
        out.append({"cid": cid, "category": category, "query": q,
                    "basis_articles": basis(arts), "suggested_scenario": scenario})
        print(f"[{category}] cid{cid}: {q[:60]}")

    # ---- labour 12：每个主题抽 2 条 ----
    lcl, ll = ("劳动合同法", "2012修正版"), ("劳动法", "2018修正版")
    for i, (topic, kws) in enumerate(LABOUR_KEYS.items()):
        pool = pick(lcl, kws, 1, used) or pick(ll, kws, 1, used)
        pool2 = pick(ll, kws, 1, used) or pick(lcl, kws, 1, used)
        for arts in (pool, pool2):
            if arts:
                emit("labour", arts, "构成要件与归责",
                     style="非法律从业者的口语（打工者/HR 视角）",
                     hint=f"围绕「{topic}」生成一个打工人实际会问的口语问题。")

    # ---- multi_hop 12：四种组合各 3 ----
    combs = [(lcl, ("公司法", "2023修订版")), (ll, ("公司法", "2023修订版")),
             (lcl, ("反不正当竞争法", "2025修订版")), (ll, ("反不正当竞争法", "2025修订版")),
             (("公司法", "2023修订版"), ("民法典", "2021施行版")),
             (("反不正当竞争法", "2025修订版"), ("民法典", "2021施行版"))]
    for i, (a_lv, b_lv) in enumerate(combs):
        for _ in range(2):
            a = random.choice([r for r in BY_LAW[a_lv] if r["id"] not in used])
            b = random.choice([r for r in BY_LAW[b_lv] if r["id"] not in used])
            emit("multi_hop", [a, b], "规则冲突与适用",
                 style="当事人/经营者视角的自然场景描述",
                 hint="生成一个自然场景问题，使回答它必须同时用到这两条不同法律的条文（不要生硬拼接）。")

    # ---- econ_new 8 ----
    for slug_kws in NEW_ECON.items():
        lv = {"anti-unfair-competition-law": ("反不正当竞争法", "2025修订版"),
              "company-law": ("公司法", "2023修订版")}[slug_kws[0]]
        for r in pick(lv, slug_kws[1], 4, used):
            emit("econ_new", [r], "法律概念界定",
                 style="创业者/企业法务视角",
                 hint="围绕该条新增规则生成一个实务问题。")

    # ---- routine 15：四法显性10+隐性5 ----
    laws4 = [("民法典", "2021施行版"), ("公司法", "2023修订版"),
             ("反不正当竞争法", "2025修订版"), ("消费者权益保护法", "2013修正版")]
    for i in range(15):
        lv = laws4[i % 4]
        r = random.choice([x for x in BY_LAW[lv] if x["id"] not in used])
        style = "精准法条查询口吻（'法定标准/期限/规定是什么'式）" if i % 3 else \
                "口语化场景描述（隐去法律术语）"
        emit("routine", [r], "法条精准检索" if i % 3 else "构成要件与归责",
             style=style, hint="生成可由该条直接回答的问题。")

    # ---- adversarial 4 ----
    traps = [
        ("试用期最长可以约定一年", lcl, ["试用期"]),
        ("员工不辞而别就算自动离职、无需任何手续", lcl, ["解除", "劳动者提前"]),
        ("只要在网上用了别人的数据就一定构成不正当竞争", ("反不正当竞争法", "2025修订版"), ["数据"]),
        ("公司注册资本认缴就可以永远不实缴", ("公司法", "2023修订版"), ["认缴", "出资期限"]),
    ]
    for premise, lv, kws in traps:
        arts = pick(lv, kws, 1, used) or pick(lv, kws, 1, set())
        if not arts:
            continue
        emit("adversarial", arts, "对抗样本",
             style="用户以笃定口吻陈述一个错误前提",
             hint=f"生成一条隐含错误前提「{premise}」的问题，提问者以为该前提成立。")

    fp = BASE / "dataset_v2_candidates.jsonl"
    with open(fp, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nTOTAL {len(out)} -> {fp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
