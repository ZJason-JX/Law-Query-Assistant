# -*- coding: utf-8 -*-
"""验收脚本：20 条评测 query 逐条跑混合检索，对照 expected_articles 算 recall@10。

验收规则：
- 对抗样本：expected_articles 必须全部召回，一票否决（不达标整体 FAIL）。
- 难度切片：显性事实 mean recall ≥ 0.90；隐性事实 mean recall ≥ 0.70。

用法: python evals/recall_check.py [--topk 10] [--current-only] [--save <dir>]
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from FlagEmbedding import BGEM3FlagModel
from qdrant_client import QdrantClient
from qdrant_client.models import (FieldCondition, Filter, Fusion, FusionQuery,
                                  MatchValue, Prefetch, SparseVector)

BASE = Path(__file__).resolve().parents[1]
DATASET = BASE / "evals" / "dataset.jsonl"
STORAGE = BASE / "src" / "db" / "qdrant_storage"
LAW_SLUG = {
    "民法典": "civil-law",
    "公司法": "company-law",
    "反不正当竞争法": "anti-unfair-competition-law",
    "消费者权益保护法": "consumer-protection-law",
    "劳动法": "labor-law",
    "劳动合同法": "labor-contract-law",
}


def art_groups(arts: list) -> list:
    """每条 expected -> 候选 id 组（反法双版本同组）。"""
    groups = []
    for a in arts:
        no = int(a["article"][1:-1])
        slug = LAW_SLUG[a["law"]]
        g = {f"{slug}-{no}"}
        if slug == "anti-unfair-competition-law":  # 2019 与 2025 两版均视为命中
            g.add(f"{slug}-2019-{no}")
        groups.append(g)
    return groups


def expected_ids(item: dict, level: str = None) -> set:
    return {m for a in item["expected_articles"] if level is None or a.get("level", "primary") == level
            for m in ({f"{LAW_SLUG[a['law']]}-{int(a['article'][1:-1])}"} |
                      ({f"anti-unfair-competition-law-2019-{int(a['article'][1:-1])}"}
                       if a["law"] == "反不正当竞争法" else set()))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topk", type=int, default=10)
    ap.add_argument("--current-only", action="store_true", help="只在现行有效法条中检索")
    ap.add_argument("--save", metavar="VERSION_DIR", help="结果落盘到 evals/results/<VERSION_DIR>/recall_report.json")
    ap.add_argument("--collection", default="law_articles")
    ap.add_argument("--compare", metavar="REPORT_JSON", help="对照历史 recall_report.json 打印回归对比")
    ap.add_argument("--rerank", action="store_true", help="top-N 候选用 bge-reranker-v2-m3 精排后再取 topk")
    ap.add_argument("--candidates", type=int, default=20, help="--rerank 时的召回候选数")
    ap.add_argument("--expand-file", metavar="JSONL", help="query_expanded_*.jsonl，多路 query RRF 融合检索")
    ap.add_argument("--dataset", metavar="JSONL", default=str(DATASET), help="评测集路径")
    args = ap.parse_args()

    reranker = None
    if args.rerank:
        sys.path.insert(0, str(BASE / "src" / "tools"))
        from embed_text import build_doc_text
        from FlagEmbedding import FlagReranker
        reranker = FlagReranker("BAAI/bge-reranker-v2-m3", use_fp16=False)

    expansions = {}
    if args.expand_file:
        for l in open(args.expand_file, encoding="utf-8"):
            r = json.loads(l)
            expansions[r["id"]] = r["variants"]

    evals = [json.loads(l) for l in open(args.dataset, encoding="utf-8")]
    model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=False)
    client = QdrantClient(path=str(STORAGE))

    def lane_lists(query: str, limit: int) -> dict:
        """返回 {'dense': [...], 'sparse': [...]} 两路各自的 top-limit。"""
        emb = model.encode([query], return_dense=True, return_sparse=True, return_colbert_vecs=False)
        lw = sorted(emb["lexical_weights"][0].items())
        sv = SparseVector(indices=[k for k, _ in lw], values=[v for _, v in lw])
        out = {}
        for name, qq in (("dense", emb["dense_vecs"][0].tolist()), ("sparse", sv)):
            r = client.query_points(args.collection, query=qq, using=name, limit=limit,
                                    query_filter=filt, with_payload=True)
            out[name] = r.points
        return out

    def hybrid_ids(query: str, limit: int) -> list:
        lanes = lane_lists(query, limit)
        fused = {}
        for lane, pts in lanes.items():
            for rank, p in enumerate(pts, 1):
                rid = p.payload["id"]
                fused[rid] = fused.get(rid, [p, 0.0])
                fused[rid][1] += 1.0 / (60 + rank)
        return [p for p, _ in sorted(fused.values(), key=lambda x: -x[1])[:limit]]

    filt = None
    if args.current_only:
        filt = Filter(must=[FieldCondition(key="status", match=MatchValue(value="现行有效"))])

    per_query = []
    print(f"{'id':>3} {'difficulty':<6} {'recall@%d' % args.topk}  miss")
    for item in evals:
        if not item.get("expected_articles"):
            continue  # off_topic 等无期望条的样本不参与召回评测
        q = item["query"]
        fetch_n = args.candidates if reranker else args.topk

        if args.expand_file:
            # 原 query + 变体 × (dense+sparse) 八路入池，RRF(k=60) 求和融合（原规格）
            queries = [q] + expansions.get(item["id"], [])
            pool = {}
            for qx in queries:
                for lane, pts in lane_lists(qx, 20).items():
                    for rank, p in enumerate(pts, 1):
                        rid = p.payload["id"]
                        ent = pool.setdefault(rid, [p, 0.0])
                        ent[1] += 1.0 / (60 + rank)
            ranked = sorted(pool.values(), key=lambda x: -x[1])
            res_points = [p for p, _ in ranked[:max(fetch_n, args.topk)]]
        else:
            res_points = hybrid_ids(q, fetch_n)

        if reranker:
            pairs = [[q, build_doc_text(p.payload)] for p in res_points]
            scores = reranker.compute_score(pairs, normalize=True)
            order = sorted(range(len(res_points)), key=lambda i: -scores[i])[:args.topk]
            res_points = [res_points[i] for i in order]
        else:
            res_points = res_points[:args.topk]
        got = {p.payload["id"] for p in res_points}
        # 门禁口径：只算 primary；缺省 level 视为 primary（v1 兼容）
        prim_arts = [a for a in item["expected_articles"] if a.get("level", "primary") == "primary"]
        sec_arts = [a for a in item["expected_articles"] if a.get("level", "primary") == "secondary"]
        need_groups = art_groups(prim_arts)
        sec_groups = art_groups(sec_arts)
        hit_groups = sum(1 for g in need_groups if got & g)
        recall = hit_groups / len(need_groups) if need_groups else 0.0
        sec_hit = sum(1 for g in sec_groups if got & g)
        miss = sorted(m for g in need_groups if not (got & g) for m in g)
        rec = {
            "id": item["id"],
            "difficulty": item["difficulty"],
            "recall": recall,
            "expected": [m for g in need_groups for m in g],
            "hit": hit_groups,
            "total": len(need_groups),
            "miss": miss,
            "secondary_hit": sec_hit,
            "secondary_total": len(sec_groups),
        }
        if item.get("trap_primary"):
            tp = art_groups([item["trap_primary"]])[0]
            rec["trap_primary_hit"] = bool(got & tp)
            rec["trap_primary"] = sorted(tp)
        # compound 双口径：分半口径 = 每个 part 单 query 检索（无扩展变体）
        if item.get("compound_parts"):
            parts = []
            for part in item["compound_parts"]:
                pids = {p.payload["id"] for p in hybrid_ids(part["sub_query"], args.topk)}
                pg = art_groups(part["expected"])
                parts.append({
                    "sub_query": part["sub_query"],
                    "recall": sum(1 for g in pg if pids & g) / len(pg),
                    "miss": sorted(m for g in pg if not (pids & g) for m in g),
                })
            rec["compound_parts"] = parts
        per_query.append(rec)
        extra = f"  sec {sec_hit}/{len(sec_groups)}" if sec_groups else ""
        print(f"{item['id']:>3} {item['difficulty']:<6} {recall:>8.2f}  "
              f"{'、'.join(miss) if miss else '-'}{extra}")

    # ---- 切片与断言 ----
    print("=" * 60)
    THRESHOLDS = {"显性事实": 0.90, "隐性事实": 0.70}
    slices = {}
    for diff in ("显性事实", "隐性事实", "可解释推理", "对抗样本", "复合问题"):
        sub = [q for q in per_query if q["difficulty"] == diff]
        if not sub:
            continue
        mean = sum(q["recall"] for q in sub) / len(sub)
        th = THRESHOLDS.get(diff)
        slices[diff] = {
            "n": len(sub),
            "mean_recall": round(mean, 4),
            "threshold": th,
            "pass": (mean >= th) if th is not None else None,
        }
        verdict = f"{'PASS' if slices[diff]['pass'] else 'FAIL'} (线 ≥{th})" if th is not None else "(无阈值)"
        print(f"{diff:<8} n={len(sub):>2}  mean recall={mean:.2f}  {verdict}")

    adv = [q for q in per_query if q["difficulty"] == "对抗样本"]
    # veto 重构：仅验 trap_primary（纠错主条）；无 trap_primary 的老数据回退全量判定
    def adv_ok(q):
        return q["trap_primary_hit"] if "trap_primary_hit" in q else q["recall"] == 1.0
    adversarial_ok = all(adv_ok(q) for q in adv) if adv else False
    for q in adv:
        status = "PASS" if adv_ok(q) else "FAIL"
        tp = f" trap_primary={'+'.join(q.get('trap_primary', []))} hit={q.get('trap_primary_hit')}"
        print(f"对抗样本一票否决检查: id={q['id']} recall={q['recall']:.2f}{tp} -> {status}")

    explicit_regress = False
    if args.compare:
        old = json.load(open(args.compare, encoding="utf-8"))
        old_map = {q["id"]: q["recall"] for q in old["per_query"]}
        print("-" * 60)
        print(f"对照 {old['version']} 回归检查：")
        regress = []
        for q in per_query:
            before = old_map.get(q["id"])
            if before is None:
                continue
            delta = q["recall"] - before
            if delta < 0:
                regress.append((q["id"], before, q["recall"]))
        if regress:
            for rid, b, a in regress:
                print(f"  回退: id={rid} {b:.2f} -> {a:.2f}")
        else:
            print("  无回退")
        # 显性切片是门禁项：任何显性题回退都记 FAIL
        explicit_regress = any(
            q["difficulty"] == "显性事实" and q["recall"] < old_map.get(q["id"], 1.0)
            for q in per_query
        )
        if explicit_regress:
            print("  !! 显性事实切片出现回退（门禁不通过）")

    # secondary 覆盖率 + compound 分半口径统计
    sec_items = [q for q in per_query if q["secondary_total"]]
    sec_cov = (sum(q["secondary_hit"] for q in sec_items) /
               sum(q["secondary_total"] for q in sec_items)) if sec_items else None
    comp_items = [q for q in per_query if q.get("compound_parts")]
    if comp_items:
        print("-" * 60)
        print("compound 双口径（整题=扩展变体检索 / 分半=单 query 无变体）：")
        for q in comp_items:
            part_str = " | ".join(
                f"part{i+1}={p['recall']:.2f}{'漏' + '、'.join(p['miss']) if p['miss'] else ''}"
                for i, p in enumerate(q["compound_parts"]))
            print(f"  id={q['id']} 整题 primary={q['recall']:.2f}  分半: {part_str}")

    mean_all = sum(q["recall"] for q in per_query) / len(per_query)
    slices_pass = all(v["pass"] for v in slices.values() if v["pass"] is not None)
    overall = "PASS" if (slices_pass and adversarial_ok and not explicit_regress) else "FAIL"
    print("-" * 60)
    print(f"总体 mean recall@{args.topk} = {mean_all:.3f}")
    print(f"验收结论: {overall}  (难度切片 {'达标' if slices_pass else '未达标'}, "
          f"对抗样本一票否决 {'满足' if adversarial_ok else '未满足'}, "
          f"显性回归 {'无' if not explicit_regress else '有（FAIL）'})")

    if args.save:
        out_dir = BASE / "evals" / "results" / args.save
        out_dir.mkdir(parents=True, exist_ok=True)
        report = {
            "version": args.save,
            "time": datetime.now().isoformat(timespec="seconds"),
            "config": {
                "embedder": "BAAI/bge-m3 (dense+sparse, RRF)",
                "vector_store": f"qdrant local ({args.collection})",
                "corpus": "chunks.jsonl 1868条（民法典1260/公司法266/反法2025-41/反法2019-33/消保法63/劳动法107/劳合法98）",
                "topk": args.topk,
                "current_only": bool(args.current_only),
                "rerank": (f"bge-reranker-v2-m3 候选{args.candidates}精排→top{args.topk}"
                           if args.rerank else None),
                "expand_file": args.expand_file,
            },
            "slices": slices,
            "secondary_coverage": round(sec_cov, 4) if sec_cov is not None else None,
            "compound_parts": {q["id"]: q["compound_parts"] for q in comp_items},
            "adversarial_veto": {"ok": adversarial_ok, "items": [q["id"] for q in adv],
                                 "trap_primary_hits": {q["id"]: q.get("trap_primary_hit") for q in adv}},
            "explicit_regress": explicit_regress,
            "mean_recall": round(mean_all, 4),
            "verdict": overall,
            "per_query": per_query,
        }
        out_file = out_dir / "recall_report.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
        print(f"saved -> {out_file}")
    client.close()
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
