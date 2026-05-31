# Frontend Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal browser-based control console for the existing question-bank pipeline.

**Architecture:** Extend the existing FastAPI app with server-rendered HTML and small JSON endpoints. Keep it dependency-free beyond FastAPI already present in the project, and read local run/eval artifacts without starting background jobs in v1.

**Tech Stack:** Python 3.11, FastAPI, standard-library HTML generation, unittest.

---

### Task 1: Web Console Endpoints

**Files:**
- Modify: `src/question_bank/api/app.py`
- Create: `tests/test_api_app.py`

- [ ] Add tests for `/`, `/api/health`, `/api/runs`, `/api/evals`, and `/ingest`.
- [ ] Implement local artifact readers for `data/runs` and `docs/eval`.
- [ ] Implement a restrained server-rendered HTML console.
- [ ] Verify with `PYTHONPATH=src:. .venv/bin/python -m unittest tests.test_api_app -v`.
- [ ] Verify full suite with `PYTHONPATH=src:. .venv/bin/python -m unittest discover -s tests -v`.

### Task 2: Local Startup Check

**Files:**
- Modify: `README.md`

- [ ] Document `uvicorn question_bank.api.app:create_app --factory --reload`.
- [ ] Start the server locally.
- [ ] Open `http://127.0.0.1:8000/` and confirm the page renders.
