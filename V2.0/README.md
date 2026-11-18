# V2.0 · 法律问答助手（可运行代码）

> 本目录是 2.0 的**完整可运行版本**：FastAPI 后端 + React 前端 + 五节点链路 + 评测流水线 + 法条向量库。
> 下载 ZIP 解压后按第 1 节操作即可跑起来；只需自备模型密钥（见第 2 节），数据已随仓库带入。
> **产品全链路说明见仓库根 [`README.md`](../README.md)**。

---

## 1. 启用步骤（新电脑，约 5 分钟 + 首次模型下载）

```bash
cd V2.0

# 1) 装依赖（建议虚拟环境；Python 3.10+）
python -m venv .venv
.venv\Scripts\activate          # Windows；Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt

# 2) 配密钥：二选一
#    a. 命令行：复制 .env.example 为 .env，填入 4 个 key
#    b. 图形界面：直接启动，进「管理后台 → 设置 → API 密钥」粘贴（推荐，见第 2 节）

# 3) 起后端（前端静态页由后端托管）
python -m uvicorn server.main:app --port 8000

# 4) 打开浏览器
#    http://localhost:8000            → 对话页（勾选「演示模式」可不看 key 先跑通五幕演示）
#    http://localhost:8000 → 管理后台  → 设置/评测/知识库/坏例/链路架构 五个页签
```

前端改代码才需要另起 dev server：`cd web && npm install && npm run dev`（端口 5173，代理到 8000）。

**首次真实提问**会自动下载 BGE-M3 向量模型（约 2 GB，代码已配 hf-mirror 镜像）；之后的提问直接走本地。
向量索引 `src/db/qdrant_storage/`（约 22 MB）与语料 `src/corpus/`（13 MB，1868 个法条切片）已在仓库内，无需重建。

---

## 2. 配置 API 密钥

系统需要 4 个密钥，全部可空着启动——哪个没配，对应环节调用时才会报错：

| Key | 用在哪 | 不填的后果 |
|---|---|---|
| `DOUBAO_API_KEY` | 生成主链：S3 门控 / S4 生成 / 拒答 | 无法正常回答 |
| `TYPESAFE_API_KEY` | S0 意图分类（JEV） | 意图判断失败 |
| `DEEPSEEK_API_KEY` | S3 查询扩展 | 追加检索失败 |
| `QWEN_API_KEY` | judge 评审（评测跑批 / 实时评分） | 不评测就不影响问答 |

**三种配法（等价，都会落到本机 `.env`）：**

1. **界面配（推荐）**：启动后 → 管理后台 → 设置 → 「API 密钥」卡片，密码框粘贴 → 保存即生效，只显示末 4 位。
2. **文件配**：复制 `.env.example` 为 `.env` 填值，重启后端。
3. **环境变量**：系统级 `setx` / `export`，`.env` 不覆盖已有环境变量。

生成模型的方舟接入点（`DOUBAO_MODEL`，`ep-` 开头）在管理后台「生成模型」下拉里改，同样写进 `.env`。

**密钥安全**：`.env` 已在 `.gitignore`，密钥永不入库；接口只回传末 4 位掩码，不回传明文。

---

## 3. 目录结构

```
V2.0/
├── app.py                # Streamlit 观测面板（旧链路，只读保留）
├── src/                  # 核心链路
│   ├── pipeline.py       # S0–S5 主链：意图→检索→门控→ReAct→生成→审计
│   ├── intent_node.py    # S0 意图分类
│   ├── retrieval_config.json  # v0.6-RRF 冻结配置 + 版本 changelog
│   ├── corpus/           # chunks.jsonl（1868 法条切片）+ 分法源文件 + 别名表
│   ├── db/               # qdrant_storage（向量索引 v0.5）+ law_articles.db（SQLite）
│   └── tools/            # 建库脚本（docx/pdf→chunks、编码、灌库）
├── server/
│   ├── main.py           # FastAPI + SSE（/api/chat 流式 + 全部 REST）
│   ├── store.py          # SQLite 存储层：会话/请求/审计/坏例 + .env 密钥读写
│   ├── badcases.py       # B1–B10 确定性坏例规则 + 归因 + 状态机
│   ├── evals_data.py     # 管理后台评测看板数据
│   └── demo_id29.json    # 演示模式剧本（id29 五幕案例）
├── evals/                # 评测集（v1/v2/v3 单轮+多轮）+ run_eval 跑批器
│                         + verify_citations 引用审计 + judge_prompt + 判定/校准脚本
├── prompts/              # 6 套按意图分发的生成 prompt（hash 入评测报告）
└── web/                  # React + Vite + TS：对话页 + 管理后台 5 页签
```

运行时产物不入库：`server/data/`（app.db、settings.json）与 `.env` 启动时自动生成。

---

## 4. 跑评测（可选）

```bash
cd V2.0
# v3 多轮评测（10 会话×3 轮；需 DOUBAO + QWEN key，真实调用，逐条落盘防断）
python evals\run_eval_v3.py dataset evals\dataset_v3_multi.jsonl --out evals\results\run --n 1 --sleep 2

# 单轮评测
python evals\run_eval.py --dataset evals\dataset.jsonl --out evals\results\single --n 1 --sleep 2
```

结果解读与冻结门禁见 [`../05-评测体系/v2/FREEZE.md`](../05-评测体系/v2/FREEZE.md)。

---

## 5. 冻结项（改动需新评测集 + 预注册门禁 + 全量回归）

| 项 | 冻结值 |
|---|---|
| 检索配置 | `v0.6-rrf-alias`，RRF k=60，top-10，lane 20 |
| 生成版本 | `v1.2`，6 套 prompt |
| JEV 模型版本 | `jev-1.13.0`（不浮动） |
| judge 口径 | qwen-plus 校准后五分制 |
| 引用审计 | 合法来源 = 本轮检索 ∪ 显式标注 `turn` 的历史法条，防绕过不可关 |

---

## 6. 已知缺陷与 v3 存货

已知缺陷 6 条见根 README『已知缺陷』一节（id7 多跳弱信号、生成选条上限、意图 0.800、生成非确定性、循环隐性代价、门控偏松）。

**v3 存货（暂不实施）**：门控 state 改造（给条文内容而非条号清单）、引用 verbatim 约束、意图 `compound_parts` 多标签。

---

<sub>迁入完成：2026-11-18 · 代码 = 开发工作区快照（含坏例闭环与密钥管理） · 状态更新责任：仓库维护者</sub>
