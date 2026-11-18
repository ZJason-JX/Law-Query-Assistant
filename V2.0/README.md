# V2.0 · 法律问答助手（可运行代码）

> 本目录是 2.0 的**完整可运行版本**：FastAPI 后端 + React 前端 + 五节点链路 + 评测流水线 + 法条向量库。
> 下载 ZIP 解压后按第 1 节操作即可跑起来；只需自备模型密钥（见第 2 节），数据已随仓库带入。
> **产品全链路说明见仓库根 [`README.md`](../README.md)**。

---

## 1. 启用步骤（从零开始，约 10 分钟 + 首次模型下载）

> 目标读者：一台只有浏览器的电脑。每步一行命令 + 一句说明。

### 第 0 步 · 装环境（每台电脑只装一次）

**版本要求**：Python **≥3.10**（代码用到 `dict | None` 语法；实测环境 Python 3.14.2 / Windows，`requirements.txt` 已锁到实测版本）；Git（可省，用 ZIP）；Node **≥18** 仅改前端时需要（实测 v24.13）。

```bash
# Windows：python.org 下载 Python 3.10+，安装时勾选 Add to PATH
#          git-scm.com 装 Git（用 Download ZIP 拿代码可以不装）

# Mac：终端跑这一行，git 与编译工具一次装好；Python3 系统自带
xcode-select --install
```

### 第 1 步 · 进入 V2.0 目录

```bash
cd Law-Query-Assistant/V2.0     # git 克隆的路径；ZIP 解压则 cd 到解压出的 V2.0 文件夹
```

### 第 2 步 · 建虚拟环境（隔离依赖，必做）

```bash
# 创建虚拟环境文件夹 .venv
python -m venv .venv          # Mac 用 python3 -m venv .venv

# 激活（每次新开终端都要激活一次）
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Mac / Linux
# 成功标志：提示符最前面出现 (.venv)
```

### 第 3 步 · 装依赖

```bash
# 一次性装好全部库（FastAPI / Qdrant / 向量模型库等，约 3 GB 含 torch）
pip install -r requirements.txt
```

### 第 4 步 · 配密钥（可跳过——演示模式不需要）

```bash
# 方式 a（推荐）：先启动，进管理后台 → 设置 → API 密钥 粘贴（见第 2 节）
# 方式 b：复制模板手填
copy .env.example .env        # Windows；Mac 用 cp .env.example .env
```

### 第 5 步 · 启动

```bash
# 起服务：API + 前端页面都在这一个端口（web/dist 已由后端托管，无需 Node）
python -m uvicorn server.main:app --port 8000

# 浏览器打开 http://localhost:8000   → 对话页（勾选「演示模式」先看五幕重放）
#                  /admin          → 管理后台（设置/评测/知识库/坏例/链路架构）
```

### 排错

| 症状 | 处理 |
|---|---|
| `Errno 10048` 端口被占 | Windows `Get-Process python \| Stop-Process -Force`；Mac `kill $(lsof -ti:8000)` |
| 首次真实提问很慢 | 正常：自动下载 BGE-M3 向量模型约 2 GB（已配 hf-mirror 国内镜像），只下一次 |
| `externally-managed-environment` | Mac 提示：说明没激活 venv，回到第 2 步 |
| 想改前端代码 | `cd web && npm install && npm run dev`（5173 代理 8000，需自行装 Node） |

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
