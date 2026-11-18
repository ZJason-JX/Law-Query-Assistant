# -*- coding: utf-8 -*-
"""增量编码：只为 chunks.jsonl 中不在 vectors_bgem3_<tag>.npz 里的新 id 编码，
结果合并回原 npz（逐文档独立编码，与全量编码产物等价）。"""
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
BATCH = 32


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--rich", action="store_true")
    args = ap.parse_args()
    npz_path = BASE / "corpus" / "chunks" / f"vectors_bgem3_{args.tag}.npz"

    rows = [json.loads(l) for l in open(CHUNKS, encoding="utf-8")]
    old = np.load(npz_path, allow_pickle=True)
    have = set(old["ids"].tolist())
    todo = [r for r in rows if r["id"] not in have]
    print(f"已有 {len(have)}，待编码 {len(todo)}")
    if not todo:
        return 0

    model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=False)
    texts = [build_doc_text(r) if args.rich else r["text"] for r in todo]
    t0 = time.time()
    dense_new, sidx_new, sval_new = [], [], []
    for i in range(0, len(texts), BATCH):
        embs = model.encode(texts[i:i + BATCH], return_dense=True, return_sparse=True,
                            return_colbert_vecs=False, batch_size=BATCH)
        dense_new.append(embs["dense_vecs"])
        for lw in embs["lexical_weights"]:
            items = sorted(lw.items())
            sidx_new.append(np.array([k for k, _ in items], dtype=np.int32))
            sval_new.append(np.array([v for _, v in items], dtype=np.float32))
        print(f"  {min(i + BATCH, len(texts))}/{len(texts)}")

    ids = old["ids"].tolist() + [r["id"] for r in todo]
    dense = np.concatenate([old["dense"]] + dense_new).astype(np.float16)
    sidx = np.concatenate([old["sparse_indices"], np.array(sidx_new, dtype=object)])
    sval = np.concatenate([old["sparse_values"], np.array(sval_new, dtype=object)])
    np.savez_compressed(npz_path, ids=np.array(ids), dense=dense,
                        sparse_indices=sidx, sparse_values=sval)
    print(f"OK -> {npz_path}  {len(ids)} 条  耗时 {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
