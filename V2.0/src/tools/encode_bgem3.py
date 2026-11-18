# -*- coding: utf-8 -*-
"""用 BGE-M3 对全部 chunk 编码（稠密 + 稀疏双路），结果落盘 npz。

首次运行会从 Hugging Face 拉取模型（约 2.2GB）；
网络不通时可设置 HF_ENDPOINT=https://hf-mirror.com。
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import numpy as np
from FlagEmbedding import BGEM3FlagModel

sys.path.insert(0, str(Path(__file__).resolve().parent))
from embed_text import build_doc_text  # noqa: E402

BASE = Path(__file__).resolve().parents[1]
CHUNKS = BASE / "corpus" / "chunks" / "chunks.jsonl"
MODEL = "BAAI/bge-m3"
BATCH = 32


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rich", action="store_true", help="拼入法名/编章节标题/至多2个关键词")
    ap.add_argument("--tag", default="", help="输出文件 tag，如 v0_1 → vectors_bgem3_v0_1.npz")
    args = ap.parse_args()
    out = BASE / "corpus" / "chunks" / f"vectors_bgem3{('_' + args.tag) if args.tag else ''}.npz"

    rows = [json.loads(l) for l in open(CHUNKS, encoding="utf-8")]
    texts = [build_doc_text(r) if args.rich else r["text"] for r in rows]
    ids = [r["id"] for r in rows]
    print(f"加载模型 {MODEL} ...")
    model = BGEM3FlagModel(MODEL, use_fp16=False)  # CPU 上 fp16 反而慢/不稳
    print(f"编码 {len(texts)} 条 ...")
    t0 = time.time()
    sparse_idx, sparse_val = [], []
    dense_all = []
    for i in range(0, len(texts), BATCH):
        batch = texts[i:i + BATCH]
        embs = model.encode(batch, return_dense=True, return_sparse=True,
                            return_colbert_vecs=False, batch_size=BATCH)
        dense_all.append(embs["dense_vecs"])
        for lw in embs["lexical_weights"]:
            items = sorted(lw.items())
            sparse_idx.append(np.array([k for k, _ in items], dtype=np.int32))
            sparse_val.append(np.array([v for _, v in items], dtype=np.float32))
        done = min(i + BATCH, len(texts))
        print(f"  {done}/{len(texts)}  ({(time.time()-t0)/done:.2f}s/条)")
    dense = np.concatenate(dense_all).astype(np.float16)
    np.savez_compressed(out, ids=np.array(ids), dense=dense,
                        sparse_indices=np.array(sparse_idx, dtype=object),
                        sparse_values=np.array(sparse_val, dtype=object))
    print(f"OK -> {out}  耗时 {time.time()-t0:.0f}s  dense{tuple(dense.shape)}  rich={args.rich}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
