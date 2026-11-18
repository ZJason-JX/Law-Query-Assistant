# -*- coding: utf-8 -*-
"""v0.3 检索侧实验：LLM 离线改写 20 条评测 query。

红线：
1. 改写 prompt 只含 query 原文，绝不接触 expected_articles / 备注 / 任何答案信息。
2. 原 query 与改写变体双留档 -> evals/query_expanded_v0_3.jsonl

用法: python evals/query_expand.py
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATASET = BASE / "dataset.jsonl"
OUT = BASE / "query_expanded_v0_3.jsonl"
ENV_FILE = BASE.parent / ".env"

PROMPT_TMPL = (
    "你是中国法律检索专家。用户提问以口语表述，请将其改写为 3 个适合在法条库中检索的查询变体，"
    "要求：使用规范法律术语（如合同相对性、侵权责任、不正当竞争等）、覆盖问题涉及的核心法律关系、"
    "每个变体侧重不同角度。只输出 3 个变体，每行一个，不要编号、不要解释。\n\n"
    "用户提问：{query}"
)

# 多轮注入规则段：expand / _gap_query 两个检索词节点共用；仅 history_str 非空时拼到 user 头部。
HIST_RULE_E = (
    "【历史对话变量】conversation_history 仅用于把 user_query 补全成独立完整的检索语义。\n"
    "1. 先补全指代与省略，再基于补全后的语义生成扩展词 / 缺口查询，不要直接拿原始省略句去扩写。\n"
    "2. 扩展词只输出法条检索关键词（法名、主体、行为、构成要件），"
    "不得照抄历史答案、历史法条全文、历史 query 原句。\n"
    "3. 补全后语义若与上一轮相同，换角度扩展（主体 / 情形 / 法名），不得复述上一轮 query。\n"
    "4. 输出格式沿用原样，不新增字段。")


def load_key() -> str:
    for line in open(ENV_FILE, encoding="utf-8"):
        if line.strip().startswith("DEEPSEEK_API_KEY="):
            return line.strip().split("=", 1)[1]
    return os.environ["DEEPSEEK_API_KEY"]


def expand(api_key: str, query: str, max_retry: int = 3, history_str: str = "") -> list:
    prompt = PROMPT_TMPL.format(query=query)
    if history_str:
        prompt = f"{history_str}\n\n{HIST_RULE_E}\n\n{prompt}"
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions", data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    for attempt in range(max_retry):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.loads(r.read().decode("utf-8"))
            text = d["choices"][0]["message"]["content"]
            variants = [ln.strip("123．.、 \t") for ln in text.splitlines() if ln.strip()]
            variants = [v for v in variants if v and v != query]
            return variants[:3]
        except Exception as e:
            if attempt == max_retry - 1:
                raise
            time.sleep(2 ** attempt)
    return []


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(DATASET))
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    api_key = load_key()
    rows = [json.loads(l) for l in open(args.dataset, encoding="utf-8")]
    out = []
    for item in rows:
        # 红线：只取 id 与 query，expected_articles 等一律不出现在请求里
        variants = expand(api_key, item["query"])
        out.append({"id": item["id"], "query": item["query"], "variants": variants})
        print(f"id={item['id']:>2} 变体{len(variants)} 个")
        for v in variants:
            print(f"    - {v}")
        time.sleep(0.5)
    out_path = Path(args.out)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"OK {len(out)} 条 -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
