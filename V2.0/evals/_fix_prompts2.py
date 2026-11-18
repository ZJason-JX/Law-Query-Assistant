# -*- coding: utf-8 -*-
"""v1.2: 给全部生成模板追加信息密度硬约束（ statute_lookup 的选条通则单独 edit 过）。"""
import pathlib

d = pathlib.Path(__file__).parent.parent / "prompts"
DENSITY = ("6. 每段以要件或要点开头，一句话承载一个信息点；禁止过渡句、铺垫句；"
           "完整性不因简洁预算牺牲——三段结构中每个要件必须出现，用短句保密度，不用删内容换短。")
for p in d.glob("*.md"):
    if p.name == "irrelevant.md":
        continue
    t = p.read_text(encoding="utf-8")
    if "每段以要件或要点开头" in t:
        print("skip", p.name)
        continue
    t = t.rstrip() + "\n" + DENSITY + "\n"
    p.write_text(t, encoding="utf-8")
    print("updated", p.name)
