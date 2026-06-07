<p align="center">
  <img src="https://readme-typing-svg.demolab.com?font=Fira+Code&size=28&duration=3000&pause=500&color=3B82F6&center=true&vCenter=true&width=600&lines=Question+Bank+Pipeline;MinerU+%2B+DeepSeek+%E2%86%92+结构化数学题库数据" alt="Typing SVG" />
</p>

<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/English-3B82F6?style=for-the-badge&logo=readme&logoColor=white" alt="English" /></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/简体中文-EF4444?style=for-the-badge&logo=readme&logoColor=white" alt="简体中文" /></a>
  <a href="README.ja.md"><img src="https://img.shields.io/badge/日本語-8B5CF6?style=for-the-badge&logo=readme&logoColor=white" alt="日本語" /></a>
</p>

<p align="center">
  <a href="https://github.com/chengxudong2025/question-bank-pipeline/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=flat-square" alt="License" /></a>
  <a href="#"><img src="https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python&logoColor=white" alt="Python" /></a>
  <a href="#"><img src="https://img.shields.io/badge/测试-703%20通过-brightgreen?style=flat-square" alt="Tests" /></a>
  <a href="#"><img src="https://img.shields.io/badge/状态-活跃-success?style=flat-square" alt="Status" /></a>
  <a href="#"><img src="https://img.shields.io/badge/欢迎PR-brightgreen?style=flat-square&logo=github" alt="PRs Welcome" /></a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/rainbow.png" alt="rainbow" />
</p>

---

# 📐 Question Bank Pipeline

> **MinerU + DeepSeek 后端** — 将数学试卷 PDF 转化为结构化、可审核的题库数据。

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

## ✨ 亮点

- 🧠 **PDF → 结构化题目** — MinerU 解析版面，DeepSeek 规范化结构
- ✅ **确定性回退** — 选项解析、答案补充、题型推断均不依赖模型推理
- 🔍 **规则质量把关** — 10+ 项检查：题干、选项、答案、LaTeX、解析
- 📊 **生产可观测** — Manifest 驱动的批量运行、步骤级耗时、故障分类
- 🖥️ **Web 控制台 + 桌面应用** — FastAPI 仪表盘和 Tkinter 桌面 GUI
- 🐘 **PostgreSQL + MinIO** — 生产级持久化与对象存储
- 🔁 **重试与断点续跑** — MinerU 自动重试（指数退避），Manifest 驱动崩溃恢复

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

## 🚀 快速开始

### 1. 克隆项目并安装

```bash
git clone https://github.com/chengxudong2025/question-bank-pipeline.git
cd question-bank-pipeline

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env 填入 DeepSeek API 密钥
```

### 3. 启动基础设施

```bash
docker compose up -d postgres minio
question-bank db init
```

### 4. 运行测试

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
# ✓ 703 tests passed
```

### 5. 摄入第一篇 PDF

```bash
question-bank ingest \
  --paper-id paper_001 \
  --pdf data/raw/paper_001.pdf \
  --output-dir data/mineru/paper_001 \
  --use-real-deepseek \
  --save-db
```

### 6. 启动 Web 控制台

```bash
uvicorn question_bank.api.app:create_app --factory --reload
# 打开 http://127.0.0.1:8000/
```

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

## 🏗 架构

```text
┌──────────┐     ┌──────────────┐     ┌───────────────┐     ┌────────────┐
│ PDF 文件 │ ──► │ MinerU 解析  │ ──► │ 题目分割器    │ ──► │ DeepSeek   │
│          │     │ (版面)       │     │               │     │ 结构化     │
└──────────┘     └──────────────┘     └───────────────┘     └────────────┘
                                                                    │
                                                                    ▼
┌──────────┐     ┌──────────────┐     ┌───────────────┐     ┌────────────┐
│ 审核队列 │ ◄── │ 质量把关     │ ◄── │ 题型推断      │ ◄── │ 补充增强   │
│          │     │              │     │               │     │ (选项、    │
│          │     │              │     │               │     │  答案)     │
└──────────┘     └──────────────┘     └───────────────┘     └────────────┘
```

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

## ⌨️ 命令行使用

```bash
# ── 摄入 ──────────────────────────────────────────
# 从已有 MinerU Markdown 干跑
question-bank ingest --paper-id paper_001 \
  --from-markdown data/mineru/paper_001/output.md --dry-run

# 完整流水线：PDF → MinerU → DeepSeek → PostgreSQL
question-bank ingest --paper-id paper_001 \
  --pdf data/raw/paper_001.pdf --use-real-deepseek --save-db

# ── 审核 ──────────────────────────────────────────
question-bank review list --limit 50

# ── 批量生产 ──────────────────────────────────────
python3 tools/batch_real_ingest.py --pdf-dir data/beta/pdf --limit 100
python3 tools/batch_real_ingest.py --pdf-dir data/beta/pdf --resume
python3 tools/batch_real_ingest.py --pdf-dir data/beta/pdf --only-index 12
```

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

## 📄 许可证

本项目使用 **MIT 许可证** — 详见 [LICENSE](LICENSE) 文件。

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

<p align="center">
  <sub>用 ❤️ 构建</sub>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/rainbow.png" alt="rainbow" />
</p>
