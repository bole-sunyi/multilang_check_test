from __future__ import annotations

"""
单模块运行报告适配层。

批量回归走的是 `cli.py -> report.py` 这条链路，
而直接执行 `atw_test.py` / `stamp_test.py` 这类单模块脚本时，
也希望产出同风格报告，所以这里负责把“单次模块执行结果”
包装成 `report.py` 能识别的统一结构。
"""

from datetime import datetime
from pathlib import Path
from typing import Any, cast

from .report import CaseResult, RuntimeOptions, generate_reports


def write_single_case_reports(
    *,
    module_name: str,
    device_name: str,
    log_dir: Path,
    status: str,
    return_code: int,
    started_at: str,
    finished_at: str,
    error_text: str = "",
    excel_path: Path | str | None = None,
    snapshot_records: list[dict[str, Any]] | None = None,
) -> tuple[Path, Path, Path]:
    """
    为“直接运行单个模块脚本”的场景生成独立报告文件。

    说明：
    1. 这里复用现有的 report.py，不重新发明一套报告格式；
    2. 报告会直接落到模块自己的日志目录里；
    3. 如果本次执行失败，会额外写一份 module_error.log，方便报告里挂链接。
    """
    # 先确保模块日志目录一定存在。
    # 这样就算本次脚本中途报错，后面也仍然有地方写错误日志和报告文件。
    log_dir.mkdir(parents=True, exist_ok=True)

    # 如果本次执行失败，把完整错误堆栈单独写进一个文件。
    # 这样 report.html / report.md 里就能挂上错误文件路径，排查更直接。
    stderr_file = ""
    if error_text:
        error_file = log_dir / "module_error.log"
        _ = error_file.write_text(error_text, encoding="utf-8")
        stderr_file = str(error_file)

    # 这里手工拼装一个“最小可用结果对象”。
    # 目的不是重新发明报告格式，而是把“单模块直接运行”的结果包装成
    # report.py 能看懂的统一结构。
    result = cast(
        CaseResult,
        cast(
            object,
            {
        "device_name": device_name,
        "serial": device_name,
        "platform": "android",
        "case_name": module_name,
        "case_path": "",
        "status": status,
        "return_code": return_code,
        "attempt_number": 1,
        "started_at": started_at,
        "finished_at": finished_at,
        "stdout_file": "",
        "stderr_file": stderr_file,
        "log_dir": str(log_dir),
        "attempt_dir": str(log_dir),
        "image_diffs": [],
        "excel_path": _excel_output_to_text(excel_path),
        "snapshot_records": snapshot_records or [],
        "baseline_action": "skipped",
        "baseline_files": [],
        "attempt_count": 1,
        "retried": False,
        "attempts": [
            {
                "attempt_number": 1,
                "status": status,
                "return_code": return_code,
                "started_at": started_at,
                "finished_at": finished_at,
                "stdout_file": "",
                "stderr_file": stderr_file,
                "log_dir": str(log_dir),
            }
        ],
            },
        ),
    )

    # runtime_options 主要是给报告头部用，告诉后续读报告的人：
    # 这份报告不是批量回归出来的，而是单模块脚本直接生成的。
    runtime_options: RuntimeOptions = {
        "run_mode": "single_module_run",
        "generated_by": "single_run_report",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    return generate_reports([result], log_dir, runtime_options=runtime_options)


def _excel_output_to_text(excel_path: Path | str | None) -> str:
    if excel_path is None:
        return ""
    if isinstance(excel_path, Path):
        return str(excel_path.resolve())
    return excel_path
