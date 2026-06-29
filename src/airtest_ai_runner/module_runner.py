from __future__ import annotations

"""
单模块多语言截图执行器。

stamp、byd、atw 仍然保持各自独立入口，但启动 App、初始化 Poco、执行 YAML、
截图、写 Excel、生成报告这些通用流程统一放在这里维护。
"""

import os
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from airtest.core.api import auto_setup, home, sleep, start_app, stop_app
except ImportError:
    import site
    import sys

    user_site = site.getusersitepackages()
    if user_site not in sys.path:
        sys.path.insert(0, user_site)
    from airtest.core.api import auto_setup, home, sleep, start_app, stop_app

from airtest.core.settings import Settings as ST

from .device_utils import build_android_device_uri, resolve_airtest_devices
from .excel_export import export_module_screenshots_to_excel
from .log_utils import sanitize_airtest_log
from .paths import clear_artifacts_root, get_module_log_dir
from .poco_utils import build_android_poco, dump_visible_nodes, execute_steps, load_steps
from .single_run_report import write_single_case_reports

DEFAULT_ADB_HOST = "127.0.0.1"
DEFAULT_ADB_PORT = 5037
DEFAULT_DEVICE_SERIAL = "127.0.0.1:16448"
DEFAULT_PACKAGE_NAME = "slots.pcg.casino.games.free.android"


def run_module(
    *,
    module_name: str,
    entry_file: str | Path,
    project_root: Path,
) -> int:
    """执行一个独立多语言截图模块。"""
    started_at = datetime.now().isoformat(timespec="seconds")
    log_dir = get_module_log_dir(module_name)
    log_dir.mkdir(parents=True, exist_ok=True)
    status = "failed"
    return_code = 1
    error_text = ""
    excel_output: Path | None = None
    snapshot_records: list[dict[str, Any]] = []

    device_serial = os.environ.get("DEVICE_SERIAL", DEFAULT_DEVICE_SERIAL).strip()
    adb_host = os.environ.get("ADB_HOST", DEFAULT_ADB_HOST).strip()
    adb_port = int(os.environ.get("ADB_PORT", str(DEFAULT_ADB_PORT)).strip())
    device_uri = build_android_device_uri(adb_host, adb_port, device_serial)
    flow_config_path = project_root / "config" / f"{module_name}.yaml"

    try:
        print(f"--- 开始执行模块: {module_name} ---")

        if _env_flag("CLEAR_ARTIFACTS_BEFORE_MODULE", default=True):
            artifacts_root = clear_artifacts_root()
            print(f"已清空旧产物目录: {artifacts_root}")
            log_dir = get_module_log_dir(module_name)
            log_dir.mkdir(parents=True, exist_ok=True)

        auto_setup(
            str(entry_file),
            devices=resolve_airtest_devices(device_uri),
            logdir=str(log_dir),
        )
        setattr(ST, "SAVE_IMAGE", False)

        if not flow_config_path.exists():
            raise FileNotFoundError(f"【找不到配置文件】请先检查是否存在: {flow_config_path.resolve()}")

        flow = load_steps(flow_config_path)
        steps = flow.get("steps", [])
        if not isinstance(steps, list) or not steps:
            raise ValueError(f"【配置为空】{flow_config_path.resolve()} 里没有可执行 steps。")

        package_env_name = str(flow.get("package_name_env") or "APP_PACKAGE_NAME")
        package_name = os.environ.get(package_env_name, DEFAULT_PACKAGE_NAME).strip()
        startup_wait_seconds = float(flow.get("startup_wait_seconds", 20))
        stop_app_after_run = bool(flow.get("stop_app_after_run", False))
        dump_poco_tree = bool(flow.get("dump_poco_tree", True))
        excel_sheet_name = str(flow.get("excel_sheet_name") or _default_sheet_name(module_name))

        log_dir = Path(ST.LOG_DIR or get_module_log_dir(module_name))
        log_dir.mkdir(parents=True, exist_ok=True)

        print("正在回到手机桌面并重新启动 App...")
        home()
        start_app(package_name)
        print(f"App 已启动，先等待 {startup_wait_seconds} 秒，让游戏加载稳定。")
        sleep(startup_wait_seconds)

        print("正在初始化 Poco 控件引擎...")
        poco = build_android_poco()
        snapshot_dir = log_dir / f"{_module_short_name(module_name)}_screen"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        if dump_poco_tree:
            poco_nodes_file = log_dir / "poco_nodes.json"
            print(f"正在导出当前页面 Poco 节点树: {poco_nodes_file}")
            dump_visible_nodes(poco, poco_nodes_file)

        print(f"即将开始执行业务流，共 {len(steps)} 个步骤。")
        snapshot_records = execute_steps(
            poco=poco,
            steps=steps,
            snapshot_dir=snapshot_dir,
            module_name=module_name,
        )

        excel_output = export_module_screenshots_to_excel(
            snapshot_records,
            sheet_name=excel_sheet_name,
        )
        print(f"多语测试 Excel 已更新: {excel_output} / sheet={excel_sheet_name}")

        if stop_app_after_run:
            stop_app(package_name)
            print("模块执行完成，已按配置自动关闭 App。")
        else:
            print("模块执行完成，按配置保留 App 当前界面，方便手动检查。")

        print(f"截图目录: {snapshot_dir.resolve()}")
        print(f"日志目录: {log_dir.resolve()}")
        print(f"--- 模块执行结束: {module_name} ---")
        status = "passed"
        return_code = 0
    except Exception:
        error_text = traceback.format_exc()
        raise
    finally:
        finished_at = datetime.now().isoformat(timespec="seconds")
        sanitize_airtest_log(log_dir / "log.txt")
        report_json, report_md, report_html = write_single_case_reports(
            module_name=module_name,
            device_name=device_serial,
            log_dir=log_dir,
            status=status,
            return_code=return_code,
            started_at=started_at,
            finished_at=finished_at,
            error_text=error_text,
            excel_path=excel_output,
            snapshot_records=snapshot_records,
        )
        print(f"模块报告 JSON: {report_json.resolve()}")
        print(f"模块报告 Markdown: {report_md.resolve()}")
        print(f"模块报告 HTML: {report_html.resolve()}")

    return return_code


def _default_sheet_name(module_name: str) -> str:
    return _module_short_name(module_name)


def _module_short_name(module_name: str) -> str:
    return module_name.removesuffix("_test")


def _env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    return raw_value.lower() in {"1", "true", "yes", "on"}
