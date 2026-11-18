# -*- coding: utf-8 -*-
"""富化嵌入文本构造（doc 侧与检索侧共享的唯一入口）。

设计约束（v0.1 门禁）：
- 编/章/节标题拼入条目前文；
- keywords 封顶 2 个，防止关键词过拟合；
- 该构造函数同时服务 encode 与任何下游检索时的文档重建，必须同源改动。
"""
import json
import re
from functools import lru_cache
from pathlib import Path

import docx

BASE = Path(__file__).resolve().parents[1]
DOCX_DIR = Path(r"F:\工作台\产品\法律知识问答助手V2.0\数据")
CIVIL_JSONL = BASE / "corpus" / "民法典.jsonl"

MAX_KEYWORDS = 2


def _clean_title(t: str) -> str:
    return re.sub(r"[　\s]+", "", t)

_CHAPTER_LINE = re.compile(r"^(第[一二三四五六七八九十百]+章)[　\s](.+)$")
_SECTION_LINE = re.compile(r"^(第[一二三四五六七八九十百]+节)[　\s](.*)$")
_DL_DIR = Path(r"F:\download")
_DOCX_BY_SLUG = {
    "labor-contract-law": _DL_DIR / "中华人民共和国劳动合同法_20121228.docx",
    "labor-law": _DL_DIR / "中华人民共和国劳动法_20181229.docx",
    "company-law": "中华人民共和国公司法_20231229.docx",
    "anti-unfair-competition-law": "中华人民共和国反不正当竞争法_20250627.docx",
    "anti-unfair-competition-law-2019": "中华人民共和国反不正当竞争法_20190423.docx",
    "consumer-protection-law": "中华人民共和国消费者权益保护法_20131025.docx",
}


@lru_cache(maxsize=1)
def _title_maps():
    """slug -> {'chapter': {第X章: 章名}, 'section': {(第X章, 第Y节): 节名}}"""
    maps = {}
    # 民法典：直接读已解析的 PDF 产物（含全称）
    ch, se = {}, {}
    for line in open(CIVIL_JSONL, encoding="utf-8"):
        r = json.loads(line)
        if r.get("chapter"):
            m = _CHAPTER_LINE.match(r["chapter"].strip("　 "))
            if m:
                ch[m.group(1)] = _clean_title(m.group(2))
        if r.get("section"):
            m = _SECTION_LINE.match(r["section"].strip("　 "))
            if m and r.get("chapter"):
                cm = _CHAPTER_LINE.match(r["chapter"].strip("　 "))
                if cm:
                    se[(cm.group(1), m.group(1))] = _clean_title(m.group(2))
    maps["civil-law"] = {"chapter": ch, "section": se}
    # 其余三部：扫 docx 标题行
    for slug, fn in _DOCX_BY_SLUG.items():
        ch, se, cur = {}, {}, None
        docx_path = fn if isinstance(fn, Path) else DOCX_DIR / fn
        for p in docx.Document(docx_path).paragraphs:
            t = p.text.strip()
            mc, ms = _CHAPTER_LINE.match(t), _SECTION_LINE.match(t)
            if mc:
                cur = mc.group(1)
                ch[cur] = _clean_title(mc.group(2))
            elif ms and cur:
                se[(cur, ms.group(1))] = _clean_title(ms.group(2))
        maps[slug] = {"chapter": ch, "section": se}
    return maps


BASE_CORPUS = BASE / "corpus" / "chunks"


@lru_cache(maxsize=1)
def _aliases_map():
    p = BASE_CORPUS / "aliases.jsonl"
    if not p.exists():
        return {}
    return {json.loads(l)["id"]: json.loads(l)["aliases"] for l in open(p, encoding="utf-8")}


def build_doc_text(chunk: dict) -> str:
    """chunk → 召回侧嵌入文本（book/chapter/clause 全称号 + 至多2个 keywords + 法理别名 + 正文）。"""
    tm = _title_maps().get(_slug_of(chunk), {"chapter": {}, "section": {}})
    parts = [f"《{chunk['law']}》{chunk['article_no']}"]
    if chunk.get("book"):
        parts.append(chunk["book"])
    if chunk.get("chapter"):
        title = tm["chapter"].get(chunk["chapter"])
        parts.append(f"{chunk['chapter']}·{title}" if title else chunk["chapter"])
    if chunk.get("clause"):
        title = tm["section"].get((chunk.get("chapter"), chunk["clause"]))
        parts.append(f"{chunk['clause']}·{title}" if title else chunk["clause"])
    parts.append(chunk["text"])
    kws = chunk.get("keywords") or []
    if kws:
        parts.append("关键词：" + "、".join(kws[:MAX_KEYWORDS]))
    aliases = _aliases_map().get(chunk["id"]) or []
    if aliases:
        parts.append("法理概念：" + "、".join(aliases[:3]))
    return "\n".join(parts)


def _slug_of(chunk: dict) -> str:
    rid = chunk["id"]
    return rid.rsplit("-", 1)[0]
