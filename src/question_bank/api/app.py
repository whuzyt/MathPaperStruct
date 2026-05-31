from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    from pydantic import BaseModel
except ImportError:  # pragma: no cover - lets core unit tests run before dependency install.
    FastAPI = None  # type: ignore[assignment]
    HTMLResponse = None  # type: ignore[assignment]
    BaseModel = object  # type: ignore[assignment,misc]

from question_bank.services.deepseek import FakeDeepSeekClient


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MAX_ITEMS = 20


if FastAPI is not None:

    class StructurePreviewRequest(BaseModel):
        raw_markdown: str

else:

    class StructurePreviewRequest:  # type: ignore[no-redef]
        def __init__(self, raw_markdown: str):
            self.raw_markdown = raw_markdown


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _first_heading(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip() or path.name
    except Exception:
        pass
    return path.name


def _recent_runs(limit: int = MAX_ITEMS) -> list[dict[str, Any]]:
    runs_root = PROJECT_ROOT / "data" / "runs"
    if not runs_root.exists():
        return []

    reports = sorted(
        runs_root.rglob("run-report.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    runs: list[dict[str, Any]] = []
    for report_path in reports[:limit]:
        data = _read_json(report_path)
        counts = data.get("counts") if isinstance(data.get("counts"), dict) else {}
        runs.append({
            "paper_id": data.get("paper_id") or report_path.parent.name,
            "status": data.get("status", "unknown"),
            "questions_passed": data.get("questions_passed", 0),
            "questions_warning": data.get("questions_warning", 0),
            "questions_failed": data.get("questions_failed", 0),
            "layout_ownership": counts.get("layout_ownership", 0),
            "deepseek_structure": counts.get("deepseek_structure", 0),
            "quality_warning_counts": data.get("quality_warning_counts", {}),
            "path": str(report_path.relative_to(PROJECT_ROOT)),
        })
    return runs


def _recent_evals(limit: int = MAX_ITEMS) -> list[dict[str, Any]]:
    eval_root = PROJECT_ROOT / "docs" / "eval"
    if not eval_root.exists():
        return []

    reports = sorted(
        eval_root.glob("*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return [
        {
            "name": path.name,
            "title": _first_heading(path),
            "path": str(path.relative_to(PROJECT_ROOT)),
            "updated_at": int(path.stat().st_mtime),
        }
        for path in reports[:limit]
    ]


def _render_layout(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --ink: #1f2933;
      --muted: #657181;
      --line: #d9dee7;
      --panel: #ffffff;
      --accent: #0f766e;
      --warn: #b45309;
      --fail: #b91c1c;
      --pass: #166534;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}
    .bar {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 16px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }}
    .brand {{ font-size: 18px; font-weight: 700; }}
    nav a {{
      color: var(--muted);
      text-decoration: none;
      margin-left: 14px;
      font-weight: 600;
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 22px 20px 42px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.3fr) minmax(280px, .7fr);
      gap: 18px;
      align-items: start;
    }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
    h1, h2 {{ margin: 0 0 12px; line-height: 1.2; }}
    h1 {{ font-size: 22px; }}
    h2 {{ font-size: 15px; }}
    .muted {{ color: var(--muted); }}
    table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 9px 7px;
      text-align: left;
      vertical-align: top;
      word-break: break-word;
    }}
    th {{ color: var(--muted); font-size: 12px; }}
    .status-completed {{ color: var(--pass); font-weight: 700; }}
    .status-partial, .status-warning {{ color: var(--warn); font-weight: 700; }}
    .status-failed, .status-crashed {{ color: var(--fail); font-weight: 700; }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin: 12px 0 0;
    }}
    .button {{
      display: inline-flex;
      align-items: center;
      min-height: 36px;
      border: 1px solid var(--accent);
      border-radius: 6px;
      padding: 0 12px;
      background: var(--accent);
      color: #fff;
      text-decoration: none;
      font-weight: 700;
    }}
    label {{ display: block; margin: 10px 0 5px; font-weight: 700; }}
    input {{
      width: 100%;
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 7px 9px;
      font: inherit;
    }}
    .checks {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin-top: 10px;
    }}
    .checks label {{
      display: flex;
      align-items: center;
      gap: 6px;
      margin: 0;
      font-weight: 600;
    }}
    .checks input {{ width: auto; min-height: auto; }}
    @media (max-width: 820px) {{
      .bar {{ align-items: flex-start; flex-direction: column; }}
      nav a {{ margin: 0 12px 0 0; }}
      .grid {{ grid-template-columns: 1fr; }}
      .checks {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="bar">
      <div class="brand">MathPaperStruct Console</div>
      <nav>
        <a href="/">Overview</a>
        <a href="/ingest">Ingest</a>
        <a href="/api/runs">Runs API</a>
        <a href="/api/evals">Evals API</a>
      </nav>
    </div>
  </header>
  <main>{body}</main>
</body>
</html>"""


def _runs_table(runs: list[dict[str, Any]]) -> str:
    if not runs:
        return '<p class="muted">No run reports found.</p>'
    rows = []
    for run in runs:
        status = html.escape(str(run["status"]))
        warnings = run.get("quality_warning_counts") or {}
        warning_text = ", ".join(f"{k}: {v}" for k, v in warnings.items()) or "-"
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(run['paper_id']))}</td>"
            f"<td class=\"status-{status}\">{status}</td>"
            f"<td>{run['questions_passed']} / {run['questions_warning']} / {run['questions_failed']}</td>"
            f"<td>{html.escape(warning_text)}</td>"
            f"<td>{html.escape(str(run['path']))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>Paper</th><th>Status</th><th>Pass/Warn/Fail</th><th>Warnings</th><th>Report</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _evals_table(evals: list[dict[str, Any]]) -> str:
    if not evals:
        return '<p class="muted">No evaluation reports found.</p>'
    rows = [
        "<tr>"
        f"<td>{html.escape(str(item['name']))}</td>"
        f"<td>{html.escape(str(item['title']))}</td>"
        f"<td>{html.escape(str(item['path']))}</td>"
        "</tr>"
        for item in evals
    ]
    return (
        "<table><thead><tr><th>File</th><th>Title</th><th>Path</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _overview_html() -> str:
    runs = _recent_runs()
    evals = _recent_evals()
    completed = sum(1 for run in runs if run.get("status") == "completed")
    total_warn = sum(int(run.get("questions_warning") or 0) for run in runs)
    body = f"""
      <h1>Pipeline Overview</h1>
      <p class="muted">Local control surface for PDF ingestion runs and evaluation reports.</p>
      <div class="grid">
        <section>
          <h2>Recent Runs</h2>
          {_runs_table(runs)}
        </section>
        <div>
          <section>
            <h2>Status</h2>
            <table>
              <tbody>
                <tr><th>Run reports</th><td>{len(runs)}</td></tr>
                <tr><th>Completed</th><td>{completed}</td></tr>
                <tr><th>Warning questions</th><td>{total_warn}</td></tr>
                <tr><th>Project root</th><td>{html.escape(str(PROJECT_ROOT))}</td></tr>
              </tbody>
            </table>
            <div class="actions"><a class="button" href="/ingest">Start Ingest</a></div>
          </section>
          <section style="margin-top:18px">
            <h2>Recent Evaluations</h2>
            {_evals_table(evals[:8])}
          </section>
        </div>
      </div>
    """
    return _render_layout("MathPaperStruct Console", body)


def _ingest_html() -> str:
    body = """
      <h1>Start Ingest</h1>
      <p class="muted">Use this form as a launch checklist. Execution is still handled by the CLI in v1.</p>
      <section>
        <form method="get" action="/api/ingest-command">
          <label for="paper_id">Paper ID</label>
          <input id="paper_id" name="paper_id" placeholder="paper_001">
          <label for="pdf_path">PDF Path</label>
          <input id="pdf_path" name="pdf_path" placeholder="data/beta/pdf/paper_0001.pdf">
          <label for="work_dir">Work Dir</label>
          <input id="work_dir" name="work_dir" placeholder="data/runs/paper_001">
          <div class="checks">
            <label><input type="checkbox" name="dry_run" value="1" checked> dry-run</label>
            <label><input type="checkbox" name="resume" value="1" checked> resume</label>
            <label><input type="checkbox" name="real_deepseek" value="1"> real DeepSeek</label>
          </div>
          <div class="actions"><button class="button" type="submit">Build Command</button></div>
        </form>
      </section>
    """
    return _render_layout("Start Ingest", body)


def create_app() -> Any:
    if FastAPI is None:
        raise RuntimeError("FastAPI is not installed. Run `pip install -e .` before starting the API.")

    app = FastAPI(title="Question Bank Pipeline", version="0.1.0")
    deepseek_client = FakeDeepSeekClient()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/health")
    def api_health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def console_home() -> str:
        return _overview_html()

    @app.get("/ingest", response_class=HTMLResponse)
    def ingest_page() -> str:
        return _ingest_html()

    @app.get("/api/runs")
    def runs() -> dict[str, Any]:
        items = _recent_runs()
        return {"count": len(items), "runs": items}

    @app.get("/api/evals")
    def evals() -> dict[str, Any]:
        items = _recent_evals()
        return {"count": len(items), "evals": items}

    @app.get("/api/ingest-command")
    def ingest_command(
        paper_id: str = "paper_001",
        pdf_path: str = "data/beta/pdf/paper_0001.pdf",
        work_dir: str = "data/runs/paper_001",
        dry_run: bool = True,
        resume: bool = True,
        real_deepseek: bool = False,
    ) -> dict[str, Any]:
        command = [
            "PYTHONPATH=src:.",
            ".venv/bin/python",
            "-m",
            "question_bank.cli",
            "paper",
            "ingest-full",
            "--paper-id",
            paper_id,
            "--pdf",
            pdf_path,
            "--work-dir",
            work_dir,
            "--asset-dir",
            "data/assets",
        ]
        if dry_run:
            command.append("--dry-run")
        if resume:
            command.append("--resume")
        if real_deepseek:
            command.append("--use-real-deepseek")
        return {"command": command, "shell": " ".join(command)}

    @app.post("/v1/questions/structure-preview")
    def structure_preview(request: StructurePreviewRequest) -> dict[str, Any]:
        return deepseek_client.structure_question(request.raw_markdown)

    return app
