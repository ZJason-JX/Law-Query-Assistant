# -*- coding: utf-8 -*-
import pathlib
d = pathlib.Path(__file__).parent.parent / "prompts"
for p in d.glob("*.md"):
    if p.name == "irrelevant.md":
        continue
    t = p.read_text(encoding="utf-8")
    t = t.replace("2. 输出末尾附结构化引用列表",
                  "2. 先判断哪条法条最直接回答问题，首句必须亮出它；其余法条仅作补充。\n3. 输出末尾附结构化引用列表")
    t = t.replace(' [{"law","article_no","quote"}]。',
                  ' [{"law","article_no","quote"}]，仅列实际援引且与答案直接相关的法条，至多3条，quote 截取关键句不超过50字。')
    t = t.replace("3. 涉及上下文未覆盖", "4. 涉及上下文未覆盖")
    t = t.replace("4. 每段≤150字", "5. 每段≤150字")
    p.write_text(t, encoding="utf-8")
    print("updated", p.name)
