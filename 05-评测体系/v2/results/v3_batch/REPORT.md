# v3 批量评测报告 — 多轮历史功能上线后首次全量评测

- 日期：2026-11-17
- 链路：`POST /api/chat` 真链路（session 持久化 + 历史注入 + ReAct v2.1 + S5 引用审计白名单）
- 生成 provider：doubao（`ep-m-20260830212522-x7fqr`，temp=0）；judge：qwen-plus + judge_prompt.md（多轮轮次追加 HIST_RULE_JUDGE）
- 数据集：`evals/dataset_v3_single.jsonl`（20 条，镜像 V1 分布：构成要件7/法条检索5/规则冲突3/概念界定2/off_topic3）＋ `evals/dataset_v3_multi.jsonl`（10 会话×3 轮）

## 一、总体指标

### 单轮 20 条（legal 17 + off_topic 3）

| 指标 | 值 | 备注 |
|---|---|---|
| 意图准确率（legal） | **0.824**（14/17） | V1 基线 0.800，同区间 |
| 检索命中率（expected∈top10） | **1.000**（17/17） | 全部命中 |
| 引用审计 ungrounded | **0 / 39** | 零误报 |
| judge MOS（legal） | **4.741** | 基线 v30=4.660，同区间 |
| off_topic 拒答 | 2/3 | 见 badcase-A |
| 延迟 p50 / p95 | 40.0s / 45.2s | ReAct 五轮全跑 |

### 多轮 10 会话 × 3 轮 = 30 轮

| 指标 | 值 | 备注 |
|---|---|---|
| 意图准确率 | **0.821**（23/28，排除 2 条应拒答轮） | |
| 检索命中率 | **0.964**（27/28） | 唯一 miss 见 badcase-D |
| 引用审计 ungrounded | **0 / 69** | 含 3 条 turn 标记引用，全部回查通过 |
| 沿用标记引用（turn:N） | 3 条 / 3 轮 | m01t3、m06t3、m10t3 |
| 拒答边界 | **2/2** | m09t3 法律史→闲聊正确拒答；m10t1 闲聊拒答；m10t2 拒答轮后正常作答 |
| judge MOS（legal） | **4.664** | |
| 首问 MOS / 追问 MOS | 4.44 / **4.65** | 历史注入无质量衰减 |

## 二、多轮专项结论（本轮功能验收口径）

- 指代补全正常：m01t2「那超过一年没签呢」、m04t2「如果是定做的窗帘呢」等均正确承接并补出目标法条（劳合法14、消法25）。
- 沿用机制生效：3 轮答案自发标注「沿用第N轮」+ `turn:N` 字段，审计按 canonical 下标回查 DB 全部合法；`used_history` 正确回填。
- 历史不带偏：m02t3（流浪狗）、m09t2 按当前 query 判；m09t3 有法律史时闲聊仍拒答；m10t2 拒答轮不构成拒答依据，正常作答。
- 会话隔离/落库/恢复：turns 表按 session 严格隔离，failed 不占号不进白名单（`_hist_diff.py` 41 PASS）。

## 三、Badcase 清单

| # | 位置 | 现象 | 定性 |
|---|---|---|---|
| A | single id20「感情还应该继续吗」 | intent=irrelevant conf **0.88** <0.90 → 走 general 模板输出边界化法律回答，judge 5.0 | 非故障：阈值边界上的有界回答，可接受；但 off_topic 拒答率 2/3 需在报告中说明 |
| B | m03t2「查账被公司拒绝了怎么办」 | intent=**other**(conf 0.41)，期望 elements_liability；答案本身正常 | **节点A规则2未救回**：短追问、无法条名词时被 JEV 判 other |
| C | m09t1「公司拖欠工资怎么维权」 | intent=**other**(conf 0.66) | 同上，首问即错（与历史无关） |
| D | m07t3「离职后追讨加班费」 | expected 劳动法77 未命中 → hit=False | 部分数据集标定偏严：答案实际引用了劳动法82（仲裁时效60日，更贴题）+劳合法85；真实漏检待复核 |
| E | m10t3「能要多少补偿」 | intent=statute_lookup（期望 elements）；答案引用里「第100条（沿用第2轮）」仅出现在正文、**未进 JSON 引用列表** → 逃逸审计 | ①数量词误判（同 id4/7/14 模式）②**审计盲区**：正文标沿用但 JSON 无该条 → 不形成引用行，无法判 outside_context |

## 四、意图误判模式（8 条 miss 的归因）

| 模式 | 出现次数 | 例 |
|---|---|---|
| 数量词疑问拉向 statute_lookup | 5 | id4「多少倍」id7「这种说法对吗」id14「哪种保证」m10t3「多少补偿」m06t2「订金呢」→概念类边界 |
| 短追问/无显性法条名词 → other | 2 | m03t2「怎么办」m09t1「怎么维权」 |
| rule_conflict→elements | 1 | m08t3「银行能直接找我要钱吗」 |

## 五、优化方向（按性价比排序）

1. **数量词↔归责边界**：构成要件/规则冲突中含「多少倍/多少天/哪种/对不对」的疑问句被系统性拉向 statute_lookup。这是 V1 起就存在的老边界（v3 criteria 修到 0.800 后的残留），建议再收窄 statute_lookup criteria——「能/否+数额」混合问句应先按归责意图路由。影响仅是模板选择（general 兜底答案质量没掉），不急于动核心。
2. **追问判 other 的兜底**：HIST_RULE_INTENT 规则2对 JEV 约束力不足（m03t2 conf 0.41）。可在 classify 层加确定性后处理：history 非空且 intent=other/conf<0.6 → 继承上一轮主意图（一行规则，不动 JEV）。
3. **审计盲区补口**：正文出现「（沿用第N轮）」标记但 JSON 引用列表无对应条目 → 现逃逸。`marked - cited` 差集应计 outside_context（几行代码，`marked` 集合已有）。
4. **拒答边界 0.88/0.90**：id20 这类软 off_topic 走 general 出有界回答是更优行为，但指标口径上「off_topic 拒答率 2/3」需写明——按 judge 口径它反而是满分。
5. **数据集标定**：m07t3 的 expected 劳动法77 不如答案自选劳动法82（60日仲裁时效）贴题——expected_articles 需复核而非判系统 miss。

## 六、产物清单

`evals/results/v3_batch/`：`single_runs.jsonl`（20 轮全事件）、`multi_runs.jsonl`（30 轮）、`single_scores.jsonl` / `multi_scores.jsonl`（judge 五维）、`summary.json`、`run.log`、本报告。
数据集：`evals/dataset_v3_single.jsonl`、`evals/dataset_v3_multi.jsonl`。
自检：`evals/_hist_diff.py`（41 PASS）、`_badcase_v3.py`、`_rejudge_v3.py`、`_summary_v3.py`。
