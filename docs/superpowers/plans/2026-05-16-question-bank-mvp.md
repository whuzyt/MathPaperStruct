# Question Bank MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first runnable backend skeleton for a MinerU + DeepSeek math-question-bank production pipeline.

**Architecture:** Start with a Python package that separates domain schemas, question splitting, quality validation, LLM adaptation, MinerU orchestration, and API wiring. The first milestone uses in-memory/service abstractions so the core behavior is testable before database and worker infrastructure are added.

**Tech Stack:** Python 3.11, standard-library unittest for zero-install verification, FastAPI/Pydantic planned for API and schemas, PostgreSQL/MinIO/Celery planned after the core MVP skeleton.

---

## File Structure

- `pyproject.toml`: project metadata, dependencies, package configuration.
- `README.md`: setup, architecture, and first-run instructions.
- `.env.example`: DeepSeek and pipeline configuration template.
- `src/question_bank/domain/models.py`: dataclasses and enums for papers, question blocks, questions, assets, and quality reports.
- `src/question_bank/domain/schemas.py`: JSON schema constants for DeepSeek structured output.
- `src/question_bank/services/question_splitter.py`: deterministic question-block splitting from MinerU Markdown-style text.
- `src/question_bank/services/quality.py`: rule-based quality validation.
- `src/question_bank/services/deepseek.py`: DeepSeek client abstraction and deterministic fake client for tests/local development.
- `src/question_bank/services/mineru.py`: MinerU runner interface and local command wrapper placeholder.
- `src/question_bank/api/app.py`: FastAPI application factory with health and structure endpoints.
- `tests/test_question_splitter.py`: splitting behavior tests.
- `tests/test_quality.py`: rule validation behavior tests.
- `tests/test_deepseek.py`: DeepSeek adapter behavior tests.

## Task 1: Project Metadata and Package Layout

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `.env.example`
- Create: `src/question_bank/__init__.py`
- Create: `src/question_bank/domain/__init__.py`
- Create: `src/question_bank/services/__init__.py`
- Create: `src/question_bank/api/__init__.py`

- [ ] **Step 1: Create metadata and empty package files**

Add project metadata, runtime dependencies, and importable package directories.

- [ ] **Step 2: Verify imports**

Run: `python3 -m unittest discover -s tests`

Expected: initially no tests are discovered or tests fail only because test files have not been added yet.

## Task 2: Domain Models

**Files:**
- Create: `src/question_bank/domain/models.py`
- Test: `tests/test_quality.py`

- [ ] **Step 1: Write tests that construct a question and run quality validation**

The test should create single-choice questions with complete and incomplete fields.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_quality -v`

Expected: FAIL because `question_bank.domain.models` and `question_bank.services.quality` do not exist.

- [ ] **Step 3: Implement dataclasses and enums**

Define `QuestionType`, `AssetType`, `ReviewStatus`, `Choice`, `QuestionAsset`, `Question`, `QualityIssue`, and `QualityReport`.

- [ ] **Step 4: Run the test**

Run: `python3 -m unittest tests.test_quality -v`

Expected: tests pass after quality rules are implemented in Task 4.

## Task 3: Question Splitter

**Files:**
- Create: `tests/test_question_splitter.py`
- Create: `src/question_bank/services/question_splitter.py`

- [ ] **Step 1: Write failing tests**

Cover numbered questions, Chinese comma numbering, section headings, and content that contains formulas.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_question_splitter -v`

Expected: FAIL because splitter does not exist.

- [ ] **Step 3: Implement minimal splitter**

Implement `split_markdown_into_blocks(paper_id: str, markdown: str) -> list[QuestionBlock]`.

- [ ] **Step 4: Run the test**

Run: `python3 -m unittest tests.test_question_splitter -v`

Expected: PASS.

## Task 4: Quality Rules

**Files:**
- Create: `src/question_bank/services/quality.py`
- Modify: `tests/test_quality.py`

- [ ] **Step 1: Write failing tests**

Cover missing stem, missing choices, answer not in choices, missing image when stem says "如图", and valid single-choice question.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_quality -v`

Expected: FAIL because quality validator does not exist.

- [ ] **Step 3: Implement validator**

Implement `validate_question(question: Question) -> QualityReport`.

- [ ] **Step 4: Run the test**

Run: `python3 -m unittest tests.test_quality -v`

Expected: PASS.

## Task 5: DeepSeek Adapter

**Files:**
- Create: `tests/test_deepseek.py`
- Create: `src/question_bank/domain/schemas.py`
- Create: `src/question_bank/services/deepseek.py`

- [ ] **Step 1: Write failing tests**

Cover fake client returning strict JSON and malformed JSON raising a structured error.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_deepseek -v`

Expected: FAIL because adapter does not exist.

- [ ] **Step 3: Implement adapter**

Implement `DeepSeekClientProtocol`, `FakeDeepSeekClient`, `parse_deepseek_question_response`, and `DeepSeekResponseError`.

- [ ] **Step 4: Run the test**

Run: `python3 -m unittest tests.test_deepseek -v`

Expected: PASS.

## Task 6: MinerU Runner Interface

**Files:**
- Create: `src/question_bank/services/mineru.py`

- [ ] **Step 1: Implement runner interface**

Define `MinerUResult`, `MinerURunnerProtocol`, and `LocalMinerURunner` that builds a command but does not require MinerU to be installed during unit tests.

- [ ] **Step 2: Verify imports**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests -v`

Expected: PASS.

## Task 7: API Skeleton

**Files:**
- Create: `src/question_bank/api/app.py`

- [ ] **Step 1: Implement app factory**

Create `create_app()` with `/health` and `/v1/questions/structure-preview` endpoints. The endpoint should use the fake DeepSeek client by default unless configured otherwise.

- [ ] **Step 2: Verify core tests still pass**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests -v`

Expected: PASS.

## Task 8: Final Verification

**Files:**
- All created files.

- [ ] **Step 1: Run all unit tests**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests -v`

Expected: all tests pass.

- [ ] **Step 2: Inspect git status**

Run: `git status --short`

Expected: created project files and PRD/plan docs are visible.

