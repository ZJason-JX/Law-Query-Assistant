# -*- coding: utf-8 -*-
"""把 chunks.jsonl 全量写入 SQLite 法条表（向量库的 payload 源/审计副本）。"""
import json
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
CHUNKS = BASE / "corpus" / "chunks" / "chunks.jsonl"
DB = BASE / "db" / "law_articles.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id             TEXT PRIMARY KEY,
    law            TEXT NOT NULL,
    article_no     TEXT NOT NULL,
    book           TEXT,
    chapter        TEXT,
    clause         TEXT,
    text           TEXT NOT NULL,
    version        TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    status         TEXT NOT NULL,
    keywords       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_law_status ON articles(law, status);
CREATE INDEX IF NOT EXISTS idx_law_article ON articles(law, article_no);
"""


def main() -> int:
    DB.parent.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(l) for l in open(CHUNKS, encoding="utf-8")]
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.executescript("DROP TABLE IF EXISTS articles;" + SCHEMA)
    cur.executemany(
        "INSERT INTO articles VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(r["id"], r["law"], r["article_no"], r.get("book"), r.get("chapter"), r.get("clause"),
          r["text"], r["version"], r["effective_date"], r["status"],
          json.dumps(r.get("keywords", []), ensure_ascii=False)) for r in rows],
    )
    con.commit()

    n = cur.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    by_law = cur.execute(
        "SELECT law, version, status, COUNT(*) FROM articles GROUP BY law, version"
    ).fetchall()
    con.close()
    assert n == len(rows), f"写入条数不符: {n} != {len(rows)}"
    print(f"OK {n} 条 -> {DB}")
    for law, ver, st, c in by_law:
        print(f"  {law} | {ver} | {st} | {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
