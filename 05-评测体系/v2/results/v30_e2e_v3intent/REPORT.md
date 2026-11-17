# v30_e2e_v3intent — ReAct v2.1 + 新标准意图缓存，端到端（live）

与 v29_e2e_live 的唯一差异：意图缓存从 `intent_cache_v2.jsonl`（旧 JEV 标签标准）
换成 `intent_cache_v3.jsonl`（新标准全量重分类）。11 条翻转题
（id3,4,5,6,10,12,13,15,17,26,30，全部 statute_lookup→elements_liability）
重新生成+重评；其余 22 条沿用 v29 产物（标签相同、prompt 相同，等价）。

## 结果

| 指标 | v30（v3 意图） | v29（v2 意图） |
|---|---|---|
| legal MOS | 4.660 | 4.693 |
| 意图准确率(legal) | **0.800** | 0.533 |
| 准确/相关/完整/简洁/安全 | 4.733/4.667/4.500/4.400/5.000 | 4.733/4.600/4.433/4.700/5.000 |
| 引用条数 | 67 | 62 |
| ungrounded / 越界 | 0 / 0 | 0 / 0 |
| verbatim/paraphrase/unmatched | 49/16/2 | 45/16/1 |
| off_topic 拒答 | 3/3 | 3/3 |
| 平均 ReAct 轮数 | 5.0 | 5.0 |

## 翻转题逐条（v29 → v30 MOS）

| id | MOS | id | MOS |
|---|---|---|---|
| 3 | 4.2→3.8 | 15 | 4.2→5.0 |
| 4 | 5.0→4.6 | 17 | 5.0→5.0 |
| 5 | 3.4→3.8 | 26 | 5.0→4.6 |
| 6 | 4.2→5.0 | 30 | 5.0→3.4 |
| 10 | 4.6→4.6 | 12 | 5.0→4.8 |
| 13 | 5.0→5.0 | | |

翻转题均值 4.509 vs 4.600，净 −0.09，在噪声量级内；id30 一条拉低 1.6
（elements 模板下漏引公司法第47/40条，属该次生成侧问题，检索未变）。
简洁性均分 4.7→4.4 是预期变化：elements_liability 模板是三段式长模板，
比 statute_lookup 直出模板长，评审对冗长扣分。

## 结论

- **意图口径已对齐**：管线 accuracy_legal=0.800 与中期报告一致。根因是
  `intent_cache_v2.jsonl` 冻结于旧标准，此前所有 e2e 的 0.533 都是缓存口径。
- 新标准路由（elements_liability）对生成质量影响中性：MOS 差在噪声内，
  引用安全不变（ungrounded 0、越界 0）。
- 遗留错分 6 条（id7/9/10/12/30 rule_conflict→elements_liability，id28
  elements→statute_lookup）属多法域单标签装不下的固有歧义，
  final report 照实披露即可，不建议再调标准——同集调参已经偏乐观。
- gen_latency 均值仍受前次 DeepSeek 故障重试污染，不采用。
