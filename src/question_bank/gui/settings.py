from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


GUI_SETTINGS_PATH = Path.home() / ".mathpaperstruct" / "gui_settings.json"


@dataclass(slots=True)
class GuiSettings:
    output_dir: str = ""
    mineru_command: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = ""
    deepseek_model: str = ""
    use_real_deepseek: bool | None = None
    resume: bool | None = None


def load_gui_settings(path: Path = GUI_SETTINGS_PATH) -> GuiSettings:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return GuiSettings()
    if not isinstance(data, dict):
        return GuiSettings()
    return GuiSettings(
        output_dir=_str_value(data.get("output_dir")),
        mineru_command=_str_value(data.get("mineru_command")),
        deepseek_api_key=_str_value(data.get("deepseek_api_key")),
        deepseek_base_url=_str_value(data.get("deepseek_base_url")),
        deepseek_model=_str_value(data.get("deepseek_model")),
        use_real_deepseek=_bool_or_none(data.get("use_real_deepseek")),
        resume=_bool_or_none(data.get("resume")),
    )


def save_gui_settings(settings: GuiSettings, path: Path = GUI_SETTINGS_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(tmp_path, 0o600)
    except OSError:
        pass
    os.replace(tmp_path, path)
    return path


def _str_value(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None
