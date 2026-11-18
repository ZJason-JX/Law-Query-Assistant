# -*- coding: utf-8 -*-
"""建 Qdrant 集合（dense + sparse 双向量 + 全量 payload）并灌库。

使用本地嵌入式存储（无需 Docker），目录 src/db/qdrant_storage/。
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import (Distance, PointStruct, SparseVector,
                                  SparseVectorParams, VectorParams)

BASE = Path(__file__).resolve().parents[1]
CHUNKS = BASE / "corpus" / "chunks" / "chunks.jsonl"
STORAGE = BASE / "db" / "qdrant_storage"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--collection", default="law_articles")
    ap.add_argument("--tag", default="", help="向量文件 tag，对应 vectors_bgem3_<tag>.npz")
    args = ap.parse_args()
    vectors = BASE / "corpus" / "chunks" / f"vectors_bgem3{('_' + args.tag) if args.tag else ''}.npz"

    chunks = {r["id"]: r for r in (json.loads(l) for l in open(CHUNKS, encoding="utf-8"))}
    npz = np.load(vectors, allow_pickle=True)
    ids = npz["ids"].tolist()
    dense = npz["dense"].astype(np.float32)
    sidx = npz["sparse_indices"]
    sval = npz["sparse_values"]

    client = QdrantClient(path=str(STORAGE))
    if client.collection_exists(args.collection):
        client.delete_collection(args.collection)
    client.create_collection(
        collection_name=args.collection,
        vectors_config={"dense": VectorParams(size=1024, distance=Distance.COSINE)},
        sparse_vectors_config={"sparse": SparseVectorParams()},
    )

    points = []
    for i, rid in enumerate(ids):
        points.append(PointStruct(
            id=i,
            vector={
                "dense": dense[i].tolist(),
                "sparse": SparseVector(indices=sidx[i].tolist(), values=sval[i].tolist()),
            },
            payload=chunks[rid],
        ))
    for i in range(0, len(points), 256):
        client.upsert(args.collection, points[i:i + 256])
        print(f"  upsert {min(i+256, len(points))}/{len(points)}")

    info = client.get_collection(args.collection)
    print(f"OK collection={args.collection} points={info.points_count}")
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
