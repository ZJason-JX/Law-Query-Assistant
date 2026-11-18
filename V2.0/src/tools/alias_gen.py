# -*- coding: utf-8 -*-
"""用 DeepSeek 为全语料生成法理概念别名（每条约 3 个）。

输入只含条文文本（语料侧增强，与评测集无任何接触）。
输出 src/corpus/chunks/aliases.jsonl：{"id":..., "aliases":[...]}
断点续跑：已生成的 id 自动跳过。
"""
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
CHUNKS = BASE / "corpus" / "chunks" / "chunks.jsonl"
OUT = BASE / "corpus" / "chunks" / "aliases.jsonl"
ENV_FILE = BASE.parent / ".env"
WORKERS = 6

PROMPT = (
    '你是中国法律专家。请为以下法律条文提炼 3 个检索用的"法理概念别名"：'
    '法学界/实务界谈到这条规则时的惯用语（如“合同相对性”“定金罚则”“人身安全保护令”），'
    '偏法理概念而非原文重复。只输出一个 JSON 数组，如 ["甲","乙","丙"]，不要任何其他文字。\n\n'
    '《{law}》{article_no}：{text}'
)


def load_key() -> str:
    for line in open(ENV_FILE, encoding="utf-8"):
        if line.strip().startswith("DEEPSEEK_API_KEY="):
            return line.strip().split("=", 1)[1]
    return os.environ["DEEPSEEK_API_KEY"]


def gen_aliases(api_key: str, chunk: dict, max_retry: int = 3) -> list:
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": PROMPT.format(
            law=chunk["law"], article_no=chunk["article_no"], text=chunk["text"][:800])}],
        "temperature": 0.1,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions", data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    for attempt in range(max_retry):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.loads(r.read().decode("utf-8"))
            text = d["choices"][0]["message"]["content"].strip()
            s, e = text.find("["), text.rfind("]")
            arr = json.loads(text[s:e + 1])
            out = [str(x).strip() for x in arr if str(x).strip()][:3]
            return out
        except Exception:
            if attempt == max_retry - 1:
                return []
            time.sleep(2 ** attempt)
    return []


def main() -> int:
    api_key = load_key()
    rows = [json.loads(l) for l in open(CHUNKS, encoding="utf-8")]

    done = {}
    if OUT.exists():
        for l in open(OUT, encoding="utf-8"):
            r = json.loads(l)
            done[r["id"]] = r["aliases"]
    todo = [r for r in rows if r["id"] not in done]
    print(f"已完成 {len(done)}，待生成 {len(todo)}")

    lock = __import__("threading").Lock()
    f = open(OUT, "a", encoding="utf-8")
    t0 = time.time()
    finished = [0]

    def work(chunk):
        aliases = gen_aliases(api_key, chunk)
        with lock:
            f.write(json.dumps({"id": chunk["id"], "aliases": aliases}, ensure_ascii=False) + "\n")
            f.flush()
            finished[0] += 1
            if finished[0] % 50 == 0:
                rate = finished[0] / (time.time() - t0)
                eta = (len(todo) - finished[0]) / rate
                print(f"  {finished[0]}/{len(todo)}  ETA {eta/60:.1f}min")
        return aliases

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(ex.map(work, todo))
    f.close()
    empty = sum(1 for r in rows if not done.get(r["id"]) and r["id"] in done)
    print(f"OK -> {OUT}（空别名 {empty} 条，可用重跑补齐）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
