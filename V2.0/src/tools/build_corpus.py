# -*- coding: utf-8 -*-
"""将民法典 PDF 解析为结构化 jsonl 语料。

输出字段：law / article_no / article（中文条号）/ part（编）/ chapter（章）/ section（节，可无）/ text
跑一次即可复现，PDF 变动后重跑覆盖。
"""
import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader

PDF_PATH = Path(r"F:\工作台\产品\法律知识问答助手\中华人民共和国民法典.pdf")
OUT_PATH = Path(__file__).resolve().parents[1] / "corpus" / "民法典.jsonl"

CN_DIGITS = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def cn2int(s: str) -> int:
    """中文数字转阿拉伯数字，上限支持 9999（民法典最大条号 1260）。"""
    total, section_num = 0, 0
    units = {"十": 10, "百": 100, "千": 1000}
    for ch in s:
        if ch in CN_DIGITS:
            section_num = CN_DIGITS[ch]
        elif ch in units:
            u = units[ch]
            section_num = section_num if section_num else 1  # “十二条”式省略
            total += section_num * u
            section_num = 0
        else:
            raise ValueError(f"无法解析中文数字: {s}")
    return total + section_num


ARTICLE_RE = re.compile(r"^(第[零一二三四五六七八九十百千]+条)[　\s]*(.*)$")
PART_RE = re.compile(r"^第[一二三四五六七]编[　\s]")
CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百]+章[　\s]")
SECTION_RE = re.compile(r"^第[一二三四五六七八九十]+节[　\s]")
NONCONTENT_PREFIXES = ("目　　录", "目录")


def main() -> int:
    reader = PdfReader(str(PDF_PATH))
    pages = [p.extract_text() or "" for p in reader.pages]
    full = "\n".join(pages)
    lines = [ln.strip("　 ") for ln in full.splitlines() if ln.strip("　 ")]

    records = []
    part = chapter = section = None
    cur = None  # 正在累积的条文 dict

    def flush():
        if cur:
            cur["text"] = cur["text"].strip()
            records.append(cur)

    # 条文号必须严格递增（1..1260）。跨行断句可能在行首出现引用条号
    # （如“第五百一十条的规定仍不能确定”），用序号连续性过滤误切分。
    expected_no = 1
    in_body = False  # 跳过开头目录页
    for ln in lines:
        m = ARTICLE_RE.match(ln)
        if m and in_body:
            try:
                if cn2int(m.group(1)[1:-1]) != expected_no:
                    m = None  # 伪条头，按正文续行处理
            except ValueError:
                m = None
        if m:
            in_body = True
            flush()
            article_cn = m.group(1)
            cur = {
                "law": "中华人民共和国民法典",
                "article_no": cn2int(article_cn[1:-1]),
                "article": article_cn,
                "part": part,
                "chapter": chapter,
                "section": section,
                "text": m.group(2).strip(),
            }
            expected_no += 1
            continue
        if not in_body:
            continue  # 目录区
        if PART_RE.match(ln):
            part, chapter, section = ln, None, None
            continue
        if CHAPTER_RE.match(ln):
            chapter, section = ln, None
            continue
        if SECTION_RE.match(ln):
            section = ln
            continue
        if ln == "附则":
            part, chapter, section = "附则", None, None
            continue
        if cur is not None:
            cur["text"] += ln  # 条文内换行拼接

    flush()

    # 完整性校验
    assert len(records) == 1260, f"条文数应为 1260，实得 {len(records)}"
    nos = [r["article_no"] for r in records]
    assert nos == sorted(nos) and len(set(nos)) == 1260, "条号不连续或有重复"
    for r in records:
        assert r["text"], f"{r['article']} 文本为空"

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"OK: {len(records)} 条 -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
