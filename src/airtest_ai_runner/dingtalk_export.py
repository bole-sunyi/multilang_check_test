from __future__ import annotations

"""
生成给 Cursor MCP 写入钉钉表格的待同步数据。

这里特意不调用钉钉开放平台 API，也不读取 appKey、appSecret、accessToken。
原因是用户希望完全复用 Cursor 里的钉钉 MCP 授权。

本地 Python 脚本不能直接调用 Cursor MCP，所以模块执行结束后先把要写入的行数据
保存成 JSON 文件。之后在 Cursor 对话里让智能体读取这个 JSON，并用已授权的
`user-dingtalk-sheets` MCP 工具写入在线表格。
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
import json
from pathlib import Path

from .paths import get_run_artifacts_dir

DEFAULT_COLUMNS = 7
DINGTALK_RESULT_SHEET_URL = "https://alidocs.dingtalk.com/i/nodes/dpYLaezmVNLd17qQSPXQzPAq8rMqPxX6?utm_scene=team_space"
DINGTALK_RESULT_SHEET_ID = "kgqie6hm"


def export_module_screenshots_to_dingtalk(
    snapshot_records: Sequence[Mapping[str, object]],
    *,
    module_name: str,
    config: Mapping[str, object] | None = None,
    finished_at: str | None = None,
) -> str:
    """
    生成一份待同步到钉钉表格的 JSON 文件。

    返回值会写进报告中，指向这份 pending JSON，而不是声称已经写入钉钉。
    """
    settings = config or {}
    workbook_id = _read_text_config(settings, "workbook_id", DINGTALK_RESULT_SHEET_URL)
    sheet_id = _read_text_config(settings, "sheet_id", DINGTALK_RESULT_SHEET_ID)
    rows = [
        _build_result_row(record, module_name=module_name, finished_at=finished_at)
        for record in snapshot_records
    ]
    pending_file = _write_pending_file(
        module_name=module_name,
        workbook_id=workbook_id,
        sheet_id=sheet_id,
        rows=rows,
    )
    return str(pending_file)


def _write_pending_file(
    *,
    module_name: str,
    workbook_id: str,
    sheet_id: str,
    rows: Sequence[Sequence[str]],
) -> Path:
    output_dir = get_run_artifacts_dir() / "dingtalk_pending"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"{timestamp}_{module_name}.json"
    payload = {
        "description": "Cursor MCP 待写入钉钉表格数据。本地脚本只生成此文件，不直接调用钉钉 API。",
        "write_mode": "name_and_real_screenshot",
        "workbook_id": workbook_id,
        "sheet_id": sheet_id,
        "start_row": 3,
        "columns": ["描述", "截图"],
        "rows": rows,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path.resolve()


def _build_result_row(
    record: Mapping[str, object],
    *,
    module_name: str,
    finished_at: str | None,
) -> list[str]:
    step_name = str(record.get("step_name") or record.get("image_name") or "")
    image_path = str(record.get("image_path") or "")
    return [
        step_name,
        _normalize_path_text(image_path),
    ]


def _read_text_config(config: Mapping[str, object] | None, key: str, default: str) -> str:
    if not config:
        return default
    value = config.get(key)
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _normalize_path_text(value: str) -> str:
    if not value:
        return ""
    path = Path(value).expanduser()
    try:
        return str(path.resolve())
    except OSError:
        return value
