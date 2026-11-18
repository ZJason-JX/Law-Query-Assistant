# -*- coding: utf-8 -*-
"""dataset_v2 expected 分级 + trap_primary + compound_parts 落盘。

level 规则（自动初标，映射表显式列出供复核）：
- 显性题：全部 expected = primary
- 隐性/推理/compound：每条标注 primary(主依据) / secondary(补全·后果·救济·指引)
- 对抗题：primary = 纠错主条，并同步写入 item.trap_primary
- compound 题：写入 compound_parts = [{sub_query, expected:[...]}]
"""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
fp = BASE / "dataset_v2.jsonl"
rows = [json.loads(l) for l in open(fp, encoding="utf-8")]

# (id, law, article) -> level；未列出的多法条题全部 secondary
PRIMARY = {
    # 隐性题主依据
    (1, "劳动合同法", "第2条"): "直接回答适用范围",
    (2, "劳动合同法", "第46条"): "经济补偿情形清单，主依据",
    (3, "劳动合同法", "第4条"): "民主程序违法是核心争点",
    (4, "劳动合同法", "第24条"): "人员范围限定是争点",
    (5, "劳动法", "第72条"): "强制参保缴费义务，直接依据",
    (6, "劳动合同法", "第19条"): "试用期分档上限，决定性依据",
    (17, "公司法", "第15条"): "关联担保决议规则，唯一直接依据",
    # 隐性题单条 = 主依据
    (25, "民法典", "第861条"): "唯一依据",
    (26, "公司法", "第189条"): "唯一依据",
    (27, "民法典", "第573条"): "唯一依据",
    # 多跳/复合：每个法域的主条各算 primary
    (7, "劳动法", "第19条"): "合同必备条款半边的依据",
    (7, "公司法", "第53条"): "抽逃出资半边的依据",
    (8, "反不正当竞争法", "第39条"): "举证责任分配是核心问",
    (9, "公司法", "第264条"): "刑责半边的依据",
    (9, "民法典", "第1234条"): "修复代履行半边的依据",
    (10, "公司法", "第116条"): "表决权半边的依据",
    (10, "劳动法", "第37条"): "计件定额半边的依据",
    (11, "反不正当竞争法", "第35条"): "阻碍调查处罚半边",
    (11, "劳动合同法", "第95条"): "监察渎职责任半边",
    (12, "公司法", "第114条"): "自行召集半边",
    (12, "民法典", "第477条"): "撤销要约到达时点，核心规则",
    # 对抗题纠错主条
    (28, "劳动合同法", "第19条"): "纠错：试用期上限六个月",
    (29, "劳动合同法", "第21条"): "纠错：试用期解除受限+说明理由",
    (30, "公司法", "第47条"): "纠错：五年缴足期限",
}

COMPOUND = {
    11: [
        {"sub_query": "阻碍市场监管部门对涉嫌不正当竞争行为的调查，负责人和公司会面临什么处罚？",
         "expected": [{"law": "反不正当竞争法", "article": "第35条"}]},
        {"sub_query": "劳动监察部门工作人员玩忽职守给用人单位造成损害的，要不要承担赔偿责任？",
         "expected": [{"law": "劳动合同法", "article": "第95条"}]},
    ],
    12: [
        {"sub_query": "持股百分之十以上且连续持股九十日以上的股东，在董事会监事会都不召集临时股东会时，能否自行召集和主持？",
         "expected": [{"law": "公司法", "article": "第114条"}]},
        {"sub_query": "撤销要约的通知在受要约人作出承诺之后才到达，该撤销是否有效？",
         "expected": [{"law": "民法典", "article": "第476条"},
                      {"law": "民法典", "article": "第477条"}]},
    ],
}

report = []
for row in rows:
    is_adv = row["difficulty"] == "对抗样本"
    is_exp = row["difficulty"] == "显性事实"
    for a in row["expected_articles"]:
        if is_exp:
            a["level"] = "primary"
            why = "显性题全部 expected"
        elif (row["id"], a["law"], a["article"]) in PRIMARY:
            a["level"] = "primary"
            why = PRIMARY[(row["id"], a["law"], a["article"])]
        else:
            a["level"] = "secondary"
            why = "补全/后果/救济/指引"
        report.append((row["id"], f"{a['law']}{a['article']}", a["level"], why))
    if is_adv:
        prim = [a for a in row["expected_articles"] if a["level"] == "primary"]
        row["trap_primary"] = {"law": prim[0]["law"], "article": prim[0]["article"]}
    if row["id"] in COMPOUND:
        row["compound_parts"] = COMPOUND[row["id"]]

with open(fp, "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

print(f"{'id':>3} {'article':<22} {'level':<10} 判定依据")
for rid, art, lv, why in report:
    print(f"{rid:>3} {art:<22} {lv:<10} {why}")
n_p = sum(1 for r in report if r[2] == "primary")
n_s = sum(1 for r in report if r[2] == "secondary")
print(f"\nprimary={n_p} secondary={n_s}")
