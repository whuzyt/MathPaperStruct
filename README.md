<p align="center">
  <img src="https://readme-typing-svg.demolab.com?font=Fira+Code&size=28&duration=3000&pause=500&color=3B82F6&center=true&vCenter=true&width=600&lines=Question+Bank+Pipeline;MinerU+%2B+DeepSeek+%E2%86%92+Structured+Math+Exam+Data" alt="Typing SVG" />
</p>

<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/English-3B82F6?style=for-the-badge&logo=readme&logoColor=white" alt="English" /></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/简体中文-EF4444?style=for-the-badge&logo=readme&logoColor=white" alt="简体中文" /></a>
  <a href="README.ja.md"><img src="https://img.shields.io/badge/日本語-8B5CF6?style=for-the-badge&logo=readme&logoColor=white" alt="日本語" /></a>
</p>

<p align="center">
  <a href="https://github.com/chengxudong2025/question-bank-pipeline/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=flat-square" alt="License" /></a>
  <a href="#"><img src="https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python&logoColor=white" alt="Python" /></a>
  <a href="#"><img src="https://img.shields.io/badge/tests-703%20passed-brightgreen?style=flat-square" alt="Tests" /></a>
  <a href="#"><img src="https://img.shields.io/badge/status-active-success?style=flat-square" alt="Status" /></a>
  <a href="#"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen?style=flat-square&logo=github" alt="PRs Welcome" /></a>
  <a href="#"><img src="https://img.shields.io/badge/DeepSeek-Powered-536DFE?style=flat-square&logo=openai&logoColor=white" alt="DeepSeek" /></a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/rainbow.png" alt="rainbow" />
</p>

---

# 📐 Question Bank Pipeline

> **MinerU + DeepSeek backend** — convert math exam PDFs into structured, reviewable question-bank data with deterministic enrichment and quality gating.

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

## ✨ Highlights

- 🧠 **PDF → Structured Questions** — MinerU parses layout; DeepSeek normalizes structure
- ✅ **Deterministic Fallbacks** — Choice parsing, answer enrichment, type inference without model inference
- 🔍 **Rule-Based Quality Gating** — 10+ checks for stems, choices, answers, LaTeX, analysis
- 📊 **Production Observability** — Manifest-driven batch runner, step-level timing, failure taxonomy
- 🖥️ **Web Console + Desktop GUI** — FastAPI dashboard and Tkinter desktop app
- 🐘 **PostgreSQL + MinIO** — Production-grade persistence and object storage
- 🔁 **Retry & Resume** — Automatic MinerU retry with exponential backoff, manifest-driven crash recovery

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

## 📋 Table of Contents

- [Architecture](#-architecture)
- [Quick Start](#-quick-start)
- [PDF Ingestion](#-pdf-ingestion)
- [Question Splitting](#-question-splitting)
- [Quality Checks](#-quality-checks)
- [CLI Usage](#-cli-usage)
- [Database](#-database)
- [Desktop GUI](#-desktop-gui)
- [Configuration](#-configuration)
- [Development](#-development)
- [License](#-license)

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

## 🏗 Architecture

```text
┌──────────┐     ┌──────────────┐     ┌───────────────┐     ┌────────────┐
│ PDF file │ ──► │ MinerU Parse │ ──► │ Question      │ ──► │ DeepSeek   │
│          │     │ (layout)     │     │ Splitter      │     │ Structure  │
└──────────┘     └──────────────┘     └───────────────┘     └────────────┘
                                                                    │
                                                                    ▼
┌──────────┐     ┌──────────────┐     ┌───────────────┐     ┌────────────┐
│ Review   │ ◄── │ Quality      │ ◄── │ Type          │ ◄── │ Enrichment │
│ Queue    │     │ Gating       │     │ Inference     │     │ (choices,  │
│          │     │              │     │               │     │  answers)  │
└──────────┘     └──────────────┘     └───────────────┘     └────────────┘
```

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

## 🚀 Quick Start

### 1. Clone & Setup

```bash
git clone https://github.com/chengxudong2025/question-bank-pipeline.git
cd question-bank-pipeline

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your DeepSeek API key
```

### 3. Start Infrastructure

```bash
docker compose up -d postgres minio
question-bank db init
```

### 4. Run Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
# ✓ 703 tests passed
```

### 5. Ingest Your First PDF

```bash
question-bank ingest \
  --paper-id paper_001 \
  --pdf data/raw/paper_001.pdf \
  --output-dir data/mineru/paper_001 \
  --use-real-deepseek \
  --save-db
```

### 6. Launch Web Console

```bash
uvicorn question_bank.api.app:create_app --factory --reload
# Open http://127.0.0.1:8000/
```

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

## 📥 PDF Ingestion

The `PDFIngestionService` connects the full production path:

```text
PDF file → MinerU output.md → DeepSeek structure → quality gating → PostgreSQL
```

```python
from pathlib import Path
from question_bank.ingestion import PDFIngestionService
from question_bank.services.mineru import LocalMinerURunner

service = PDFIngestionService(
    mineru_runner=LocalMinerURunner(command="mineru"),
    deepseek_client=deepseek,
    repository=repository,
)

result = service.ingest_pdf(
    paper_id="paper_001",
    pdf_path=Path("data/raw/paper_001.pdf"),
    output_dir=Path("data/mineru/paper_001"),
)
```

### Reliability Features (ADR 021)

| Feature | Description |
|---------|-------------|
| 🔁 Auto Retry | MinerU transient failures retried up to 2× with exponential backoff (30s, 90s) |
| ✅ Resume Validation | Corrupt artifacts detected (empty md, unparseable JSON, zero elements) → auto re-run |
| 📋 Manifest Recovery | `batch-manifest.json` survives crashes; resume skips completed papers |
| ⏱ Step Timing | Per-step (MinerU, DeepSeek, crop…) aggregation for bottleneck analysis |

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

## ✂️ Question Splitting

Deterministic, review-friendly splitter with zero model inference:

| Feature | Support |
|---------|---------|
| Numbered questions | `1.`, `2、`, `第 6 题` |
| Chinese section headings | `一、选择题`, `二、填空题`, `三、解答` |
| Option labels | `A.`, `B.`, `C：`, `D．` (not treated as questions) |
| Answer sections | `参考答案`, `答案`, `解析`, `答案与解析` |
| Multi-line content | Preserved until next delimiter |

Answer enrichment is **deterministic**, not model inference:

```text
1. 答案：A 解析：代入可得。
   ──► answer_latex = "A", analysis_latex = "代入可得。"
```

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

## 🔍 Quality Checks

| Rule | Triggers When |
|------|--------------|
| `empty_stem` | Stem is empty or whitespace-only |
| `missing_answer` | No answer for choice/fill-blank/short-answer/proof |
| `single_choice_too_few_choices` | Single choice has < 2 options |
| `answer_not_in_choices` | Answer label not found in choice options |
| `asset_without_text_reference` | Stem references figure but has no attached asset |
| `no_analysis_for_proof` | Proof question missing analysis |
| `no_analysis_for_short_answer` | Short answer missing analysis |
| `unbalanced_latex_stem` | Mismatched `$` delimiters in stem |
| `unbalanced_latex_answer` | Mismatched `$` delimiters in answer |

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

## ⌨️ CLI Usage

```bash
# ── Ingestion ──────────────────────────────────────
# Dry-run from existing MinerU markdown
question-bank ingest --paper-id paper_001 \
  --from-markdown data/mineru/paper_001/output.md --dry-run

# Full pipeline: PDF → MinerU → DeepSeek → PostgreSQL
question-bank ingest --paper-id paper_001 \
  --pdf data/raw/paper_001.pdf --use-real-deepseek --save-db

# ── Review ─────────────────────────────────────────
# List questions needing review
question-bank review list --limit 50

# View question details
question-bank review show --question-id <id>

# ── Assets ─────────────────────────────────────────
# Compute perceptual hash for visual dedup
question-bank review asset phash --paper-id paper_001

# List visual duplicate candidates
question-bank review asset visual-candidates --max-distance 8

# ── Batch Production ───────────────────────────────
# Process all PDFs in a directory
python3 tools/batch_real_ingest.py --pdf-dir data/beta/pdf --limit 100

# Resume from crash
python3 tools/batch_real_ingest.py --pdf-dir data/beta/pdf --resume

# Re-run a single failed paper
python3 tools/batch_real_ingest.py --pdf-dir data/beta/pdf --only-index 12
```

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

## 🗄 Database

PostgreSQL with MinIO for object storage:

```bash
# Start infrastructure
docker compose up -d postgres minio

# Initialize schema
question-bank db init
```

**MinIO Console**: http://localhost:9001  
**User**: `questionbank` / **Password**: `questionbank123`

```python
from question_bank.repository import PostgresQuestionBankRepository
from question_bank.storage import LocalAssetUploader, MinIOObjectStorage

storage = MinIOObjectStorage(
    endpoint="http://localhost:9000",
    access_key="questionbank",
    secret_key="questionbank123",
    bucket="question-bank-assets",
)

uploader = LocalAssetUploader(storage=storage)
uploaded = uploader.upload_question_asset(
    paper_id="paper_001",
    question_id="q_001",
    file_path=Path("data/mineru/paper_001/images/figure.png"),
    asset_type="geometry",
    page=2,
)
```

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

## 🖥️ Desktop GUI

For non-technical users — select a PDF, run the full pipeline, export results:

```bash
./run_mathpaperstruct_gui.command
# or
question-bank-gui
```

The GUI produces structured JSON and Markdown under `data/gui_runs/<paper_id>/`.

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

## ⚙️ Configuration

```bash
# .env
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
MINERU_COMMAND=mineru
DATABASE_URL=postgresql://questionbank:questionbank123@localhost:5432/questionbank
```

DeepSeek output is validated before entering the pipeline:

| Field | Requirement |
|-------|-------------|
| `question_type` | One of: `single_choice`, `multiple_choice`, `fill_blank`, `short_answer`, `proof`, `unknown` |
| `choices` | Array of `{label, content_latex}` objects |
| `difficulty` | `null` or integer 1–5 |
| `confidence` | `structure`, `latex`, `answer`, `knowledge` each 0–1 |

> Missing source answers or analyses remain empty strings — the prompt explicitly forbids guessing.

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

## 🧪 Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
PYTHONPATH=src python3 -m unittest discover -s tests -v

# Run a specific test file
PYTHONPATH=src python3 -m unittest tests/test_mineru_retry.py -v

# Start API dev server
uvicorn question_bank.api.app:create_app --factory --reload
```

### API Endpoints

| Endpoint | Description |
|----------|-------------|
| `/` | Web console overview |
| `/ingest` | Ingest command builder |
| `/api/health` | Health check |
| `/api/runs` | Recent run-report.json summaries |
| `/api/evals` | Recent eval report summaries |

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

<p align="center">
  <sub>Built with ❤️ by the Question Bank Pipeline team</sub>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/rainbow.png" alt="rainbow" />
</p>
