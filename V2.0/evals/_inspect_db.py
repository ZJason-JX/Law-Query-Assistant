# -*- coding: utf-8 -*-
import sqlite3
c = sqlite3.connect(r"法律问答助手2.0\src\db\law_articles.db")
print([r[0] for r in c.execute("select name from sqlite_master")])
for name in [r[0] for r in c.execute("select name from sqlite_master")]:
    print("==", name, c.execute(f"select count(*) from {name}").fetchone())
    print([d[1] for d in c.execute(f"pragma table_info({name})")])
    print(c.execute(f"select * from {name} limit 1").fetchone())
