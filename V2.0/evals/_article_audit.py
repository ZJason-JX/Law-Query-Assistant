# -*- coding: utf-8 -*-
"""dataset_v2 条号补全 + 一致性校验（两步合一）。

Step1: 扫每条 expected 的 note，提取 "第X条"/"X条" 引用；
       引用了但未成独立 expected 记录的同法条号 -> 拆分补录（note 标 [拆分补录]）。
       article 字段本已全填，空缺的才标 TODO_MANUAL。
Step2: DeepSeek 逐条校验 note 描述与 chunks 原文语义一致性 -> 一致/存疑/不一致。

输出: dataset_v2.jsonl（补全）+ dataset_v2_extraction_report.md
"""
import json
import os
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

CN2NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8,
          "九": 9, "十": 10, "百": 100, "千": 1000, "零": 0}


def cn_num(s: str) -> int:
    """中文数词 -> int（支持 一百二十三 / 二十三 / 十 / 百零五 等）"""
    if s.isdigit():
        return int(s)
    total, section = 0, 0
    for ch in s:
        if ch not in CN2NUM:
            return -1
        v = CN2NUM[ch]
        if v >= 10:
            section = (section or 1) * v
            total += section
            section = 0
        else:
            section = section * 10 + v if section else v
    return total + section


ART_RE = re.compile(r"(?:第([0-9]+|[一二三四五六七八九十百零]+)条|([0-9]+)条)")

CHUNKS = {}
for l in open(PROJ / "src" / "corpus" / "chunks" / "chunks.jsonl", encoding="utf-8"):
    r = json.loads(l)
    key = (r["law"], r["article_no"])
    # 同法多版本（反法 2025/2019）：expected 默认指向现行有效版本
    if key not in CHUNKS or r["status"] == "现行有效":
        CHUNKS[key] = r

rows = [json.loads(l) for l in open(BASE / "dataset_v2.jsonl", encoding="utf-8")]

# ---------- Step 1: 提取 ----------
extract_rows = []   # 报告用
added = []
for row in rows:
    have = {(a["law"], a["article"]) for a in row["expected_articles"]}
    for a in row["expected_articles"]:
        refs = set()
        for m in ART_RE.finditer(a["note"]):
            n = cn_num(m.group(1) or m.group(2))
            if n > 0:
                refs.add(f"第{n}条")
        refs.discard(a["article"])           # 自身条号不算
        for ref in sorted(refs, key=lambda s: int(s[1:-1])):
            key = (a["law"], ref)
            status = "已存在" if key in have else ("语料缺失" if key not in CHUNKS else "拆分补录")
            extract_rows.append((row["id"], a["law"], a["article"], ref, a["note"], status))
            if status == "拆分补录":
                row["expected_articles"].append({
                    "law": a["law"], "article": ref,
                    "note": f"[拆分补录] 原note引用于「{a['law']}{a['article']}」的note中，待人工确认是否必要"})
                have.add(key)
                added.append((row["id"], a["law"], ref))

# TODO_MANUAL: article 为空或不可解析
for row in rows:
    for a in row["expected_articles"]:
        if not a.get("article") or not re.fullmatch(r"第[0-9]+条", a["article"]):
            a["article"] = "TODO_MANUAL"

# ---------- Step 2: LLM 一致性校验 ----------

def call_llm(prompt: str) -> str:
    body = json.dumps({"model": "deepseek-chat",
                       "messages": [{"role": "user", "content": prompt}],
                       "temperature": 0}).encode("utf-8")
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


verdicts = []   # (id, law, article, verdict, reason)
for row in rows:
    pairs = []
    for i, a in enumerate(row["expected_articles"]):
        if a["article"] == "TODO_MANUAL":
            verdicts.append((row["id"], a["law"], "TODO_MANUAL", "存疑", "article 待人工填写"))
            continue
        chunk = CHUNKS.get((a["law"], a["article"]))
        if not chunk:
            verdicts.append((row["id"], a["law"], a["article"], "不一致", "语料中无此法条"))
            continue
        pairs.append((i, a, chunk["text"]))
    if not pairs:
        continue
    items = "\n\n".join(
        f"[{i}] {a['law']}{a['article']}\nnote描述：{a['note']}\n条文原文：{txt}"
        for i, a, txt in pairs)
    p = ("你是法律语料质检员。逐条判断 note描述 与 条文原文 是否语义一致"
         "（note 是对该条文规则要点的概括，允许缩写但不要求逐字对应）。\n"
         "判定三档：一致 / 存疑（部分对应或表述有偏差）/ 不一致（规则要点对不上）。\n"
         "只输出 JSON 数组，每元素形如 "
         '{"i":0,"verdict":"一致","reason":"一句话"}，不要其他内容。\n\n' + items)
    try:
        res = json.loads(call_llm(p).strip().strip("`").removeprefix("json").strip())
        m = {x["i"]: x for x in res}
        for i, a, _ in pairs:
            v = m.get(i, {})
            verdicts.append((row["id"], a["law"], a["article"],
                             v.get("verdict", "存疑"), v.get("reason", "解析失败")))
    except Exception as e:
        for i, a, _ in pairs:
            verdicts.append((row["id"], a["law"], a["article"], "存疑", f"LLM调用失败:{e}"))
    print(f"id{row['id']} checked {len(pairs)}")

# ---------- 报告 ----------
total_exp = sum(len(r["expected_articles"]) for r in rows)
n_todo = sum(1 for r in rows for a in r["expected_articles"] if a["article"] == "TODO_MANUAL")
fix = [v for v in verdicts if v[3] != "一致"]

lines = ["# dataset_v2 条号提取 + 一致性校验报告\n",
         f"- expected 记录总数：{total_exp}（含拆分补录 {len(added)} 条）",
         f"- article 空缺待人工（TODO_MANUAL）：{n_todo}",
         f"- 一致性：一致 {sum(1 for v in verdicts if v[3]=='一致')} / "
         f"存疑 {sum(1 for v in verdicts if v[3]=='存疑')} / "
         f"不一致 {sum(1 for v in verdicts if v[3]=='不一致')}\n",
         "## 一、note 条号提取对照表\n",
         "| id | 所在expected | 提取条号 | 处置 | note 原文 |", "|---|---|---|---|---|"]
for rid, law, art, ref, note, st in extract_rows:
    lines.append(f"| {rid} | {law}{art} | {law}{ref} | {st} | {note} |")
if not extract_rows:
    lines.append("| - | （note 中无额外条号引用） | | | |")

lines += ["\n## 二、逐条一致性校验\n",
          "| id | 法条 | 判定 | 理由 |", "|---|---|---|---|"]
for rid, law, art, vd, reason in verdicts:
    lines.append(f"| {rid} | {law}{art} | {vd} | {reason} |")

lines += ["\n## 三、fix_list（存疑+不一致，待人工裁决）\n",
          "| id | 法条 | 判定 | 理由 | 建议 |", "|---|---|---|---|---|"]
for rid, law, art, vd, reason in fix:
    sug = "复核 note 表述或改挂其他条号"
    if art == "TODO_MANUAL":
        sug = "人工补 article_no"
    lines.append(f"| {rid} | {law}{art} | {vd} | {reason} | {sug} |")
if not fix:
    lines.append("| - | 无 | | | |")

with open(BASE / "dataset_v2.jsonl", "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

rp = BASE / "dataset_v2_extraction_report.md"
rp.write_text("\n".join(lines), encoding="utf-8")
print(f"added={added}\ntodo={n_todo} fix={len(fix)} -> {rp}")
