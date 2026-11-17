# 🚀 V2.0 · 当前主线（目录占位说明）

> 本目录是 2.0 代码与资产的**迁入位置**。截至 2026-11-17，代码仍在开发工作区，尚未迁入本仓库。
> 本文件先占位并约定目录职责，避免迁入时结构漂移。**产品全链路说明见仓库根 [`README.md`](../README.md)**。

---

## 1. 当前状态（诚实标注）

| 模块 | 状态 | 说明 |
|---|---|---|
| 检索链路（v0.6-RRF 冻结） | ✅ 已完成 | 九版消融、门禁前置、负结果留档 |
| 生成链路（v1.2 冻结） | ✅ 已完成 | 三版迭代、6 套按意图分发 prompt |
| 评测流水线 | ✅ 已完成 | 五分制五维 + LLM-as-judge + 校准 + 回归脚本 |
| 引用审计 | ✅ 已完成 | 六版零 `outside_context` |
| ReAct 循环检索 | ✅ 已完成 | S0–S5 状态机，追加轮 ≤2 |
| 双页前端 | 🟡 已验收，待迁入 | 对话页 + 管理后台四 Tab |
| 多轮对话 | 🟡 实现中 | 会话持久化 + 7 调用点注入 + 引用防绕过，验收用例 6 组 |
| 架构与迭代白皮书 | 📄 已成稿，待迁入 | 迁入到 `docs/` 后按最终页面定稿 |
| 线上可访问版本 | ⬜ 未启动 | 建议：本地全功能 + 静态展示层，见根 README 第 6.4 节 |

> 状态以开发工作区实际进度为准，迁入时由维护者更新本表。**不要把「占位目录」当成「已交付代码」**。

---

## 2. 目录职责约定

| 目录 / 文件 | 放什么 | 不该放什么 |
|---|---|---|
| `src/` | 核心链路：`pipeline.py`、`intent_node.py`、`retrieval_config.json`（含版本 changelog） | 服务层、评测脚本 |
| `server/` | FastAPI + SSE 服务 `main.py`、SQLite 存储 `store.py`（`app.db`） | 前端资源 |
| `evals/` | 评测集、`query_expand.py`、`verify_citations.py`、`run_eval.py`、`judge_prompt.md`、`results/FREEZE.md`、`results/GENERATION_FREEZE_v1.2.md`、`query_expansion_trace.jsonl`、`citation_audit/` | 生产配置 |
| `prompts/` | 6 套按意图分发的生成 prompt（每路一个 `.md`，hash 入评测报告） | 运行时拼接的模板片段 |
| `web/` | React + Vite + TS 前端：`src/api.ts`、对话页、管理后台 | 后端代码 |
| `chunks/` | 法条级语料 `chunks.jsonl`、法理别名表 | 原始 PDF / docx（放 `V1.0/`） |
| `docs/` | 架构与迭代白皮书、架构图 | 评测原始结果（放 `evals/`） |
| `app.py` | Streamlit 观测面板（旧链路，只读保留） | 新功能开发 |
| `.env.example` | 变量名清单（**不含任何真实值**） | `TYPESAFE_API_KEY` 等真实密钥 |

**铁律**：`.env`、`app.db`、任何含密钥的文件不得入库；`.gitignore` 需覆盖 `.env`、`*.db`、`__pycache__/`、`node_modules/`、`dist/`。

---

## 3. 迁入清单（逐项打勾）

```
[ ] src/          核心链路 + 冻结配置
[ ] server/       FastAPI 服务 + SQLite 存储
[ ] evals/        评测集 / judge / 冻结决议 / 引用审计六版结果 / ReAct trace
[ ] prompts/      6 套生成 prompt
[ ] web/          双页前端
[ ] chunks/       法条级语料与别名表
[ ] docs/         架构与迭代白皮书 + 架构图
[ ] app.py        Streamlit 观测面板
[ ] .env.example  变量名清单
[ ] .gitignore
[ ] requirements.txt / pyproject.toml + 前端 package.json
[ ] 根 README 第 6.1 节：补齐精确启动命令、依赖清单、端口
```

迁入后**必须重跑**根 README 第 7.3 节的 6 组验收用例，并把实测输出贴进 PR / commit message；空历史逐字节 diff 证据随迁入一起提交。

---

## 4. 冻结项（迁入后不得随意改动）

| 项 | 冻结值 | 改动条件 |
|---|---|---|
| 检索配置 | `v0.6-rrf-alias`，RRF k=60 | 需新评测集 + 预注册门禁 + 全量回归 |
| 生成版本 | `v1.2`，6 套 prompt | 同上；prompt 文件 hash 需记入评测报告 |
| JEV 模型版本 | `jev-1.13.0`（不浮动） | 换版需重跑意图分类校准 |
| judge 口径 | qwen-plus 校准后五分制 | 换模型需重新过 ±1 一致率门禁 |
| 引用审计 | 合法来源 = 本轮检索 ∪ 显式标注 `turn` 的历史法条 | 防绕过校验不可关闭 |

---

## 5. 已知缺陷与 v3 存货

已知缺陷 6 条见根 README 第 7.4 节（含 id7 多跳弱信号、生成选条上限、意图 0.800 未达 0.85、生成非确定性、循环隐性代价、门控偏松）。

**v3 存货（暂不实施）**：门控 state 改造（补条文内容而非只给条号清单）、引用 verbatim prompt 约束、意图 `compound_parts` 多标签。

---

<sub>占位建立：2026-11-17 · 状态更新责任：仓库维护者 · 产品定义与验收口径见根 README</sub>
