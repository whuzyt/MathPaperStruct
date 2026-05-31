# Question Bank Pipeline

MinerU + DeepSeek backend skeleton for converting math exam PDFs into structured, reviewable question-bank data.

## What This First Version Contains

- Domain models for papers, question blocks, questions, choices, assets, and quality reports.
- A deterministic question splitter for MinerU-style Markdown text.
- Rule-based quality checks for common math-question-bank errors.
- A DeepSeek adapter boundary with a fake client for local development and tests.
- A MinerU runner interface placeholder.
- A FastAPI web console for local run/evaluation visibility plus structure previews.

## Local Verification

The core tests use Python's standard `unittest`, so they can run before installing dev dependencies:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Configuration

Copy `.env.example` to `.env` and set at least:

```bash
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
MINERU_COMMAND=mineru
```

The production client posts to DeepSeek's chat completions API and asks the model to return strict JSON for each question block. Tests use a fake transport and do not call the network.

DeepSeek output is validated before it enters the pipeline. Required fields:

```text
question_type, stem_latex, choices, answer_latex, analysis_latex,
knowledge_points, difficulty, confidence, warnings
```

Important contract details:

- `question_type` must be one of `single_choice`, `multiple_choice`, `fill_blank`, `short_answer`, `proof`, `unknown`.
- `choices` must be an array of `{label, content_latex}` objects.
- `difficulty` must be `null` or an integer from 1 to 5.
- `confidence` must include `structure`, `latex`, `answer`, and `knowledge`, each from 0 to 1.
- `warnings` are persisted into `quality_reports.model_warnings` and force review.
- Missing source answers or analyses must remain empty strings; the prompt explicitly forbids guessing.

To run the API after installing dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn question_bank.api.app:create_app --factory --reload
```

Open the local console at:

```text
http://127.0.0.1:8000/
```

Useful endpoints:

```text
/                 Web console overview
/ingest           Ingest command builder
/api/health       Health check
/api/runs         Recent data/runs/*/run-report.json summaries
/api/evals        Recent docs/eval/*.md summaries
```

## Database

The first PostgreSQL schema lives in:

```text
db/001_initial_schema.sql
```

It creates the PRD core tables: `papers`, `parse_runs`, `question_blocks`, `questions`, `choices`, `question_assets`, and `quality_reports`.

Start local infrastructure:

```bash
docker compose up -d postgres minio
```

Initialize the database schema:

```bash
question-bank db init
```

MinIO runs at:

```text
API: http://localhost:9000
Console: http://localhost:9001
User: questionbank
Password: questionbank123
```

Asset uploads use stable object keys:

```text
papers/{paper_id}/{question_id}/{filename}
```

Example:

```python
from pathlib import Path

from question_bank.storage import LocalAssetUploader, MinIOObjectStorage, attach_uploaded_asset

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
attach_uploaded_asset(question, uploaded)
```

The repository layer accepts a DB-API style connection, so a psycopg connection can be passed in production:

```python
from question_bank.pipeline import ProcessingPipeline
from question_bank.repository import PostgresQuestionBankRepository
from question_bank.services.deepseek import DeepSeekHTTPClient

deepseek = DeepSeekHTTPClient(api_key="sk-...")
pipeline = ProcessingPipeline(deepseek_client=deepseek)
repository = PostgresQuestionBankRepository(connection)

result = pipeline.process_and_save_markdown("paper_001", mineru_markdown, repository)
```

## PDF Ingestion

`PDFIngestionService` connects the first production path:

```text
PDF file -> MinerU output.md -> DeepSeek structure pass -> quality report -> repository save
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

## Question Splitting

The first splitter is deterministic and review-friendly. It currently supports:

- Arabic numbered questions such as `1.`, `2、`, and `第 6 题`.
- Chinese section headings such as `一、选择题`, `二、填空题`, `三、解答`.
- Option labels like `A.` and `B.` without treating them as new questions.
- Stopping before answer sections such as `参考答案`, `答案`, `解析`, and `答案与解析`.

Ambiguous blocks should still be reviewed or reprocessed by the DeepSeek validation path; the splitter is the cheap first pass, not the final authority.

Answer sections are parsed separately by question number. When DeepSeek leaves `answer_latex` empty and a matching answer entry exists, the pipeline fills `answer_latex` from the parsed answer section before quality validation. This is deterministic enrichment, not model inference.

Answer entries with explicit labels are split before merge:

```text
1. 答案：A 解析：代入可得。
```

becomes `answer_latex = "A"` and `analysis_latex = "代入可得。"` when those fields are not already supplied by DeepSeek. Entries that only start with `解：` or `解析：` are treated as analysis. Plain entries like `B` or `$x=1$` are treated as answers.

Choice options are also parsed as a deterministic fallback. If DeepSeek returns no choices, the pipeline extracts option lines such as `A. ...`, `B、...`, `C：...`, and `D．...` from the raw question block. Multi-line option content is preserved until the next option label.

Question type is inferred after deterministic enrichment and before quality validation. The fallback rules correct `unknown` or generic `short_answer` outputs using:

- Parsed choices -> `single_choice`
- Blank markers like `____`, `（ ）`, or section title `填空题` -> `fill_blank`
- Section title or stem containing `证明` -> `proof`
- Section titles like `解答`, `计算`, `应用`, `综合`, `压轴` -> `short_answer`

Specific model outputs such as `single_choice` are not overwritten.

## Quality Checks

Rule-based validation currently flags:

- Empty stems.
- Missing answers for choice, fill-blank, short-answer, and proof questions.
- Single-choice questions with missing choices or fewer than 4 choices.
- Single-choice answers that do not match any option label.
- Stems that refer to a figure but have no attached asset.
- Proof and short-answer questions without analysis.
- Unbalanced LaTeX dollar delimiters in stem, answer, or analysis fields.

## CLI

After installing the package, use the `question-bank` command.

Dry-run an existing MinerU Markdown artifact without a database or real DeepSeek call:

```bash
question-bank ingest \
  --paper-id paper_001 \
  --from-markdown data/mineru/paper_001/output.md \
  --dry-run
```

Run MinerU on a PDF, using the fake DeepSeek client and no database save:

```bash
question-bank ingest \
  --paper-id paper_001 \
  --pdf data/raw/paper_001.pdf \
  --output-dir data/mineru/paper_001 \
  --dry-run
```

Use real DeepSeek:

```bash
DEEPSEEK_API_KEY=sk-... question-bank ingest \
  --paper-id paper_001 \
  --from-markdown data/mineru/paper_001/output.md \
  --use-real-deepseek \
  --dry-run
```

Persist to PostgreSQL:

```bash
question-bank ingest \
  --paper-id paper_001 \
  --from-markdown data/mineru/paper_001/output.md \
  --use-real-deepseek \
  --save-db
```

List questions that need review:

```bash
question-bank review list --limit 50
```

Each row includes question ID, type, quality score, rule error codes, model warnings, and a stem preview.

## Architecture

```text
PDF upload
 -> MinerU parsing
 -> question block splitting
 -> DeepSeek structure normalization
 -> rule and semantic quality checks
 -> human review queue
 -> production question bank
```

See `docs/prd-mineru-deepseek-question-bank.md` for the product requirements.
