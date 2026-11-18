# -*- coding: utf-8 -*-
"""把四部法律转换为统一 chunk schema 的 jsonl。

输入：民法典走已解析的 src/corpus/民法典.jsonl（PDF 产物），
     公司法/反不正当竞争法(2025/2019)/消保法走 docx。
输出：src/corpus/chunks/<slug>.jsonl + 汇总 chunks.jsonl
"""
import json
import re
import sys
from pathlib import Path

import docx
import jieba.analyse

BASE = Path(__file__).resolve().parents[1]
DOCX_DIR = Path(r"F:\工作台\产品\法律知识问答助手V2.0\数据")
CIVIL_JSONL = BASE / "corpus" / "民法典.jsonl"
OUT_DIR = BASE / "corpus" / "chunks"

CN_DIGITS = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
UNITS = {"十": 10, "百": 100, "千": 1000}


def cn2int(s: str) -> int:
    total, num = 0, 0
    for ch in s:
        if ch in CN_DIGITS:
            num = CN_DIGITS[ch]
        elif ch in UNITS:
            total += (num or 1) * UNITS[ch]
            num = 0
        else:
            raise ValueError(s)
    return total + num


ARTICLE_RE = re.compile(r"^第([零一二三四五六七八九十百千]+)条[　\s]*(.*)$")
CHAPTER_RE = re.compile(r"^(第[一二三四五六七八九十百]+)章")
SECTION_RE = re.compile(r"^(第[一二三四五六七八九十百]+)节")


def make_keywords(text: str, limit: int = 4) -> list:
    """条号引注词 + TextRank 实义词，取前 limit 个。"""
    kws = re.findall(r"[“\"]([^“”\"]{2,10})[”\"]", text)
    kws += jieba.analyse.textrank(text, topK=limit * 2, allowPOS=("n", "nz", "vn"))
    seen, out = set(), []
    for k in kws:
        k = k.strip("，。；：、　 ")
        if k and k not in seen and len(k) >= 2 and not k.startswith("本法"):
            seen.add(k)
            out.append(k)
        if len(out) >= limit:
            break
    return out


def parse_docx(path: Path, meta: dict, expected: int) -> list:
    paras = [p.text.strip() for p in docx.Document(path).paragraphs if p.text.strip()]
    records, cur, chapter, section = [], None, None, None
    expected_no = 1
    for ln in paras:
        m = ARTICLE_RE.match(ln)
        if m and cn2int(m.group(1)) != expected_no:
            m = None  # 目录/断行伪条头
        if m:
            if cur:
                cur["text"] = cur["text"].strip()
                records.append(cur)
            no = cn2int(m.group(1))
            cur = {
                "id": f"{meta['slug']}-{no}",
                "law": meta["law"],
                "article_no": f"第{no}条",
                "book": None,
                "chapter": chapter,
                "clause": section,
                "text": m.group(2).strip(),
                "version": meta["version"],
                "effective_date": meta["effective_date"],
                "status": meta["status"],
            }
            expected_no += 1
            continue
        if cur is None:
            continue  # 题注/目录区
        mc, ms = CHAPTER_RE.match(ln), SECTION_RE.match(ln)
        if mc and "节" not in ln:
            chapter, section = mc.group(1) + "章", None
        elif ms:
            section = ms.group(1) + "节"
        else:
            cur["text"] += ln
    if cur:
        cur["text"] = cur["text"].strip()
        records.append(cur)
    assert len(records) == expected, f"{meta['law']}({meta['version']}) 应 {expected} 条，实得 {len(records)}"
    nos = [int(r["article_no"][1:-1]) for r in records]
    assert nos == list(range(1, expected + 1)), f"{meta['law']} 条号不连续"
    for r in records:
        assert r["text"], f"{meta['law']} {r['article_no']} 文本为空"
        r["keywords"] = make_keywords(r["text"])
    return records


def civil_from_pdf_jsonl() -> list:
    out = []
    for line in open(CIVIL_JSONL, encoding="utf-8"):
        r = json.loads(line)
        part = (r["part"] or "").strip("　 ")
        if not part:
            book = None
        elif part == "附则":
            book = "附则"
        else:
            book = re.sub(r"^第[一二三四五六七]编[　\s]*", "", part) + "编"
        chapter = r["chapter"] or ""
        ch_m = CHAPTER_RE.match(chapter.strip("　 "))
        cl_m = SECTION_RE.match((r["section"] or "").strip("　 "))
        rec = {
            "id": f"civil-law-{r['article_no']}",
            "law": "民法典",
            "article_no": f"第{r['article_no']}条",
            "book": book or None,
            "chapter": (ch_m.group(1) + "章") if ch_m else (chapter or None),
            "clause": (cl_m.group(1) + "节") if cl_m else None,
            "text": r["text"],
            "version": "2021施行版",
            "effective_date": "2021-01-01",
            "status": "现行有效",
        }
        rec["keywords"] = make_keywords(rec["text"])
        out.append(rec)
    assert len(out) == 1260, f"民法典应 1260 条，实得 {len(out)}"
    return out


DL_DIR = Path(r"F:\download")

SOURCES = [
    (DL_DIR / "中华人民共和国劳动合同法_20121228.docx",
     {"slug": "labor-contract-law", "law": "劳动合同法", "version": "2012修正版",
      "effective_date": "2013-07-01", "status": "现行有效"}, 98),
    (DL_DIR / "中华人民共和国劳动法_20181229.docx",
     {"slug": "labor-law", "law": "劳动法", "version": "2018修正版",
      "effective_date": "2018-12-29", "status": "现行有效"}, 107),
    ("中华人民共和国公司法_20231229.docx",
     {"slug": "company-law", "law": "公司法", "version": "2023修订版",
      "effective_date": "2024-07-01", "status": "现行有效"}, 266),
    ("中华人民共和国反不正当竞争法_20250627.docx",
     {"slug": "anti-unfair-competition-law", "law": "反不正当竞争法", "version": "2025修订版",
      "effective_date": "2025-10-15", "status": "现行有效"}, 41),
    ("中华人民共和国反不正当竞争法_20190423.docx",
     {"slug": "anti-unfair-competition-law-2019", "law": "反不正当竞争法", "version": "2019修正版",
      "effective_date": "2019-04-23", "status": "历史版本"}, 33),
    ("中华人民共和国消费者权益保护法_20131025.docx",
     {"slug": "consumer-protection-law", "law": "消费者权益保护法", "version": "2013修正版",
      "effective_date": "2014-03-15", "status": "现行有效"}, 63),
]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_chunks = []

    civil = civil_from_pdf_jsonl()
    all_chunks += civil
    with open(OUT_DIR / "civil-law.jsonl", "w", encoding="utf-8") as f:
        for r in civil:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"OK 民法典 {len(civil)} 条")

    for fn, meta, expected in SOURCES:
        path = Path(fn) if Path(fn).is_absolute() else DOCX_DIR / fn
        recs = parse_docx(path, meta, expected)
        all_chunks += recs
        with open(OUT_DIR / f"{meta['slug']}.jsonl", "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"OK {meta['law']}({meta['version']}) {len(recs)} 条")

    ids = [r["id"] for r in all_chunks]
    assert len(ids) == len(set(ids)), "存在重复 id"
    with open(OUT_DIR / "chunks.jsonl", "w", encoding="utf-8") as f:
        for r in all_chunks:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"TOTAL {len(all_chunks)} 条 -> {OUT_DIR / 'chunks.jsonl'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
