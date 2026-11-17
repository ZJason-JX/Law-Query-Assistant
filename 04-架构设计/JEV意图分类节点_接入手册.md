# JEV 意图分类节点 · 接入手册（v1.1）

> 用途：法律问答助手 2.0 · pipeline v1.1 意图识别节点
> 适用对象：Devin（实现）/ 张（验收）
> 信息核验时间：2026-10-04

---

## 1. JEV 是什么，为什么用它

TypeSafe AI（前 OpenAI 研究员 Diogo Almeida 创办，RLHF 共同发明人）2026-09/10 发布的**决策专用模型**（"System One"范式）：不生成文本，直接输出带校准置信度的结构化判定。

| 特性 | 数值 | 对我们的意义 |
|---|---|---|
| 输入价格 | $0.042 / 百万 token，**输出免费** | 20 条评测跑批成本 ≈ $0.0002，忽略不计 |
| 延迟 | 70–500ms（中位 216ms） | 前置于检索，用户无感 |
| 结构化错误率 | 0%（按构造，答错也是"允许值里的错"） | 不需要 JSON 解析容错代码 |
| 置信度 | RLCD 训练的校准值 | fallback 门控的可靠依据 |

**选型叙事**（写进架构文档）：生成用 LLM（豆包）、查询改写用 LLM（DeepSeek）、意图分类用决策模型（JEV）——按任务类型选原语，不是无脑全上 LLM。

## 2. 接入步骤

1. **拿 key**：console.typesafe.ai/settings/keys（early access 可能排队），或走 Vercel AI Gateway
2. **配环境变量**：`TYPESAFE_API_KEY`，写 `.env`，**不进代码库/聊天/git**（与 DEEPSEEK_API_KEY 同一纪律）
3. **装 SDK**：`pip install typesafe-sdk`（Python 3.10+）
4. **模型版本 pin 死 `jev-1.13.0`**，不用 `jev-latest` 浮动别名（官方明确建议，评测可复现性要求）

## 3. 我们的调用设计

**节点位置**：链路最前端（query → JEV 意图分类 → 选回答模板 → 检索 → 生成）。**只接生成侧，不碰检索**。

**一次调用、两个问题**（共享 state，省 12 倍成本，这是官方推荐的批处理模式）：

- **Q1（核心）：意图分类** —— Choice 类型
- **Q2（加防坑检测）：错误法律前提识别** —— Noul 类型

### 代码骨架（Devin 参照集成，非直接照抄）

```python
from typesafe_sdk import Choice, Noul, TypeSafeClient

INTENT_TEMPLATES = {
    "elements_liability": "要件清单模板",   # 构成要件与归责
    "statute_lookup":     "单段直出模板",   # 法条精准检索（最短）
    "rule_conflict":      "顺位分析模板",   # 规则冲突与适用
    "concept_definition": "辨析模板",       # 法律概念界定
    "other":              "通用三段式",     # 兜底
}

with TypeSafeClient() as client:
    resp = client.system_one(
        state={"query": user_query},
        questions={
            "intent": Choice(
                instructions=(
                    "判断这条法律咨询问题属于哪类提问意图。"
                    "只依据问题本身的表述判断。"
                ),
                criteria={
                    "elements_liability": (
                        "构成要件与归责：询问某行为/事实的法律责任是否成立、"
                        "归责原则、侵权或违约责任构成要件（如'XX是否要担责'）"
                    ),
                    "statute_lookup": (
                        "法条精准检索：直接询问某事项的法定标准、期限、"
                        "具体条文规定（如'法定标准是什么''规定在第几条'）"
                    ),
                    "rule_conflict": (
                        "规则冲突与适用：一般法与特别法、原则与例外的"
                        "适用顺位（如'优先适用哪一条'）"
                    ),
                    "concept_definition": (
                        "法律概念界定：某术语的内涵外延、与相似概念的"
                        "区分（如'XX与YY有什么区别'）"
                    ),
                    "other": "以上都不符合",
                },
            ),
            "false_premise": Noul(
                instructions="这个问题隐含了一个法律上不成立或常见误传的前提（如把不存在的法律规定当作已存在）"
            ),
        },
    )

ans = resp.answers["intent"]
intent = ans.choice if ans.confidence >= 0.85 else "other"
# false_premise.noul > 0.5 时，生成 prompt 追加"先纠正前提"指令
template = INTENT_TEMPLATES[intent]
```

### 两个设计说明

1. **criteria 写的是"判断边界"而非"选项名"**——官方文档明确：question ID 不发给模型，模型只看 instructions 和 criteria 描述。选项描述写得越像判定规则，分类越准。
2. **Q2（Noul 防坑）是加分项**：id20"分居满两年自动离婚"就是错误前提型 query。noul > 0.5 时在生成 prompt 里注入"先指出前提不存在，再给出正确规定"——对抗样本的处置从"碰运气"变成"有检测器"。

## 4. 验收标准

| 项 | 门禁 |
|---|---|
| 意图分类准确率 | ≥85%（17/20，ground truth = dataset 的 scenario 字段） |
| 对抗样本 id20 | 必须分入 statute_lookup **且** false_premise.noul > 0.5 |
| 置信度分布 | 报告 20 条的 confidence 直方图（校准质量的人工检查点） |
| 延迟 | 计入 pipeline 延迟统计（观测面板加一行） |
| 成本 | 记录实际 usage（返回值里有 token 计数），对账官方价格 |

## 5. 已知的坑（官方文档警告 + 实操注意）

| 坑 | 说明 |
|---|---|
| **confidence ≠ 选中项概率** | 它是从答案分布派生的校准值，0.85 这个阈值要用我们自己的 20 条标注数据复核，不是拍脑袋定死 |
| 不要让 JEV 做算术/日期比较/大状态计数 | 官方明确警告——我们只做分类，天然避开 |
| 必须带 `other` 兜底选项 | JEV 强制选择，没有 other 时它会硬挑最接近的错项 |
| 版本浮动 | pin `jev-1.13.0`；报告中记录返回的 model version 字段 |
| 问题间相互独立 | 同一调用里的 Q1/Q2 不共享结论，依赖逻辑要写在应用代码里 |

## 5.5 架构更新（2026-10-05）：路由分发制（用户定案）

原设计的"模板 dict 注入"升级为**路由分发**（延续 1.0 的平行生成架构思路）：

- JEV 输出 5+1 路：`0=法律无关`（直接输出固定拒答文案，不走生成模型）/ `1-4=四类理想态`（各走独立 prompt 文件）/ `other+低置信=通用三段式`
- **每路一个独立 prompt 文件**（`prompts/` 目录），不把四套模板塞进同一个 system prompt——防长文本指令稀释，且各模板可独立版本化迭代
- **0 类（拒答）阈值不对称**：误把法律 query 拒答的代价 >> 误把无关 query 硬答，所以 0 类要求 confidence ≥0.90 才拒答，否则降级通用模板
- **prompt 文件 hash 记入评测报告**（与扩展变体离线固化同一逻辑：一切影响输出的输入都要可追溯可复现）
- **off-topic 样本单独切片**：新增 id21-23（天气/写诗/闲聊类）只验 0 类路由，不并入原 20 条对比口径（保 v1.0 基线可比性）

## 6. 边界：JEV 不能替代 judge

JEV 有 Score 题型（有序等级打分），理论上能打五维分——**不要用**。两个理由：
1. **无 rationale**：我们的 scores.jsonl 需要 judge 理由作为 bad case 归因依据，JEV 只给数字不给理由，评测失去可解释性；
2. **judge 换型要重新过校准门禁**：qwen-plus 的 ±1 一致率校准做了才能用，换 JEV 就重来一遍，收益只是省钱几毛钱。

（唯一例外留个口子：**引用溯源校验**里的"引用条文与上下文条文是否同一"这类确定性比对，用代码字符串匹配更可靠，也别用 JEV。）

## 7. 落地清单

- [ ] 申请 key → `.env` 加 `TYPESAFE_API_KEY`
- [ ] `pip install typesafe-sdk`，模型 pin `jev-1.13.0`
- [ ] `intent_node.py`：上述骨架 + 置信度 fallback + Noul 前提检测
- [ ] 离线评测：20 条 query 的分类混淆矩阵 + confidence 直方图
- [ ] 并入 pipeline v1.1（与 prompt 收紧、知识边界自白同一次迭代）
- [ ] v1.1 跑批报告新增字段：intent、confidence、false_premise、jev_latency、jev_usage
