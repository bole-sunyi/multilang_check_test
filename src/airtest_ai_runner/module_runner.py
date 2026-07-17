from __future__ import annotations

"""
单模块多语言截图执行器。

stamp、byd、atw 仍然保持各自独立入口，但启动 App、初始化 Poco、执行 YAML、
截图、生成钉钉 MCP 待同步数据或本地表格、生成报告这些通用流程统一放在这里维护。
"""

import os
import shutil
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from airtest.core.api import auto_setup, device, home, sleep, start_app, stop_app
except ImportError:
    import site
    import sys

    user_site = site.getusersitepackages()
    if user_site not in sys.path:
        sys.path.insert(0, user_site)
    from airtest.core.api import auto_setup, device, home, sleep, start_app, stop_app

from airtest.core.settings import Settings as ST

from .device_utils import build_android_device_uri, resolve_airtest_devices, select_android_device_serial
from .dingtalk_export import export_module_screenshots_to_dingtalk
from .excel_export import export_module_screenshots_to_excel
from .log_utils import sanitize_airtest_log
from .paths import get_module_log_dir, get_run_artifacts_dir, prompt_cleanup_artifacts_root
from .poco_utils import build_poco, dump_poco_hierarchy, dump_visible_nodes, execute_steps, load_steps
from .single_run_report import write_single_case_reports

DEFAULT_ADB_HOST = "127.0.0.1"
DEFAULT_ADB_PORT = 5037
DEFAULT_PACKAGE_NAME = "slots.pcg.casino.games.free.android"


def run_module(
    *,
    module_name: str,
    entry_file: str | Path,
    project_root: Path,
) -> int:
    """
    执行一个独立多语言截图模块。

    新手可以把它理解成一条固定流水线：
    1. 列出旧产物，让用户选择要删除哪些文件/目录；
    2. 连接 Android 设备或模拟器；
    3. 读取 `config/{module_name}.yaml`；
    4. 启动游戏并等待页面稳定；
    5. 初始化 Poco，并确认能读取游戏节点树；
    6. 按 YAML 的 steps 一步步执行；
    7. 生成钉钉 MCP 待同步数据；如果未开启钉钉导出，则写入本地 Excel；
    8. 生成 HTML 报告。

    如果你只是想改“点哪里、截哪里”，请改 YAML，不要改这个函数。
    """
    started_at = datetime.now().isoformat(timespec="seconds")
    log_dir: Path | None = None
    status = "failed"
    return_code = 1
    error_text = ""
    table_output: str | None = None
    snapshot_records: list[dict[str, Any]] = []

    adb_host = os.environ.get("ADB_HOST", DEFAULT_ADB_HOST).strip()
    adb_port = int(os.environ.get("ADB_PORT", str(DEFAULT_ADB_PORT)).strip())
    flow_config_path = project_root / "config" / f"{module_name}.yaml"
    device_serial = ""

    try:
        print(f"--- 开始执行模块: {module_name} ---")

        # 单模块运行前先让用户选择要删除哪些旧产物。
        # 这样可以保留刚导出的 current_dump，也可以保留历史报告或截图。
        artifacts_root, deleted_items = prompt_cleanup_artifacts_root()
        print(f"产物根目录: {artifacts_root}")
        if deleted_items:
            print(f"本次已清理 {len(deleted_items)} 个旧产物。")
        else:
            print("本次未清理旧产物。")
        log_dir = get_module_log_dir(module_name)
        log_dir.mkdir(parents=True, exist_ok=True)

        device_serial = select_android_device_serial(adb_host=adb_host)
        device_uri = build_android_device_uri(adb_host, adb_port, device_serial)
        auto_setup(
            str(entry_file),
            devices=resolve_airtest_devices(device_uri),
            logdir=str(log_dir),
        )
        setattr(ST, "SAVE_IMAGE", False)

        if not flow_config_path.exists():
            raise FileNotFoundError(f"【找不到配置文件】请先检查是否存在: {flow_config_path.resolve()}")

        # 读取并校验 YAML。配置错误会在这里尽早抛出，
        # 避免脚本跑到一半才因为 selector 或缩进问题失败。
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
        dingtalk_export_config = flow.get("dingtalk_export")
        use_dingtalk_export = _is_dingtalk_export_enabled(dingtalk_export_config)

        log_dir = Path(ST.LOG_DIR or get_module_log_dir(module_name))
        log_dir.mkdir(parents=True, exist_ok=True)

        print("正在回到手机桌面并重新启动 App...")
        home()
        start_app(package_name)
        print(f"App 已启动，先等待 {startup_wait_seconds} 秒，让游戏加载稳定。")
        sleep(startup_wait_seconds)

        print("正在初始化 Poco 控件引擎...")
        poco = build_poco(device())
        _verify_poco_connection(poco)
        snapshot_dir = get_run_artifacts_dir() / f"{_module_short_name(module_name)}_screen"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        if dump_poco_tree:
            poco_nodes_file = log_dir / "poco_nodes.json"
            print(f"正在导出当前页面 Poco 节点树: {poco_nodes_file}")
            # 运行开始前导出一份节点树，主要用于排查：
            # 如果某一步点不到，可以回头看启动后的页面节点是否和预期一致。
            dump_visible_nodes(poco, poco_nodes_file)
            print(f"已同步生成可执行 YAML 片段: {poco_nodes_file.with_name('poco_nodes_steps.yaml')}")

        print(f"即将开始执行业务流，共 {len(steps)} 个步骤。")
        snapshot_records = execute_steps(
            poco=poco,
            steps=steps,
            snapshot_dir=snapshot_dir,
            module_name=module_name,
        )

        if use_dingtalk_export:
            # 方案 2 的 MCP 版本：
            # 本地脚本不直接调钉钉开放 API，只生成待同步 JSON。
            # 后续由 Cursor 里的钉钉 MCP 读取这个 JSON 并写入在线表格。
            if not isinstance(dingtalk_export_config, dict):
                raise ValueError("dingtalk_export 必须是 YAML 字典结构。")
            table_output = export_module_screenshots_to_dingtalk(
                snapshot_records,
                module_name=module_name,
                config=dingtalk_export_config,
                finished_at=datetime.now().isoformat(timespec="seconds"),
            )
            print(f"已生成钉钉 MCP 待同步文件: {table_output}")
            print("下一步：在 Cursor 对话里说“把最新 dingtalk_pending 写入钉钉表格”。")
        else:
            workbook_path = export_module_screenshots_to_excel(
                snapshot_records,
                sheet_name=excel_sheet_name,
            )
            workbook_path = _prompt_rename_file(
                workbook_path,
                prompt="请输入表格新名称（直接回车保留 多语测试模板.xlsx）: ",
                suffix=".xlsx",
            )
            table_output = str(workbook_path)
            print(f"本地多语截图表格已写入: {workbook_path} / sheet={excel_sheet_name}")

        if stop_app_after_run:
            stop_app(package_name)
            print("模块执行完成，已按配置自动关闭 App。")
        else:
            print("模块执行完成，按配置保留 App 当前界面，方便手动检查。")

        print(f"截图目录: {snapshot_dir.resolve()}")
        print(f"临时工作目录: {log_dir.resolve()}（执行结束会自动清理）")
        print(f"--- 模块执行结束: {module_name} ---")
        status = "passed"
        return_code = 0
    except Exception:
        error_text = traceback.format_exc()
        raise
    finally:
        if log_dir is None:
            log_dir = get_module_log_dir(module_name)
        finished_at = datetime.now().isoformat(timespec="seconds")
        sanitize_airtest_log(log_dir / "log.txt")
        report_json, report_md, report_html = write_single_case_reports(
            module_name=module_name,
            device_name=device_serial or "unknown",
            log_dir=log_dir,
            status=status,
            return_code=return_code,
            started_at=started_at,
            finished_at=finished_at,
            error_text=error_text,
            excel_path=table_output,
            snapshot_records=snapshot_records,
        )
        report_html = _move_report_to_artifacts_root(
            report_json,
            report_md,
            report_html,
            module_name=module_name,
        )
        print(f"最终报告 HTML: {report_html.resolve()}")
        _remove_temporary_work_dir(log_dir)

    return return_code


def _default_sheet_name(module_name: str) -> str:
    return _module_short_name(module_name)


def _is_dingtalk_export_enabled(config: object) -> bool:
    if not isinstance(config, dict):
        return False
    return bool(config.get("enabled", False))


def _verify_poco_connection(poco: Any) -> None:
    """运行前快速确认游戏 Poco 树可读取，失败时给出明确排查方向。"""
    hierarchy = dump_poco_hierarchy(poco)

    root_name = ""
    if isinstance(hierarchy, dict):
        payload = hierarchy.get("payload") or {}
        root_name = str(payload.get("name") or hierarchy.get("name") or "")
    print(f"Poco 控件树读取成功：root={root_name or 'unknown'}")


def _module_short_name(module_name: str) -> str:
    return module_name.removesuffix("_test")


def _move_report_to_artifacts_root(
    report_json: Path,
    report_md: Path,
    report_html: Path,
    *,
    module_name: str,
) -> Path:
    output_root = get_run_artifacts_dir()
    default_base = f"{datetime.now().strftime('%Y-%m-%d')}_{module_name}_执行报告"
    report_base = _prompt_output_base_name(
        prompt=f"请输入报告新名称（直接回车使用 {default_base}）: ",
        default_base=default_base,
    )
    final_html = output_root / f"{report_base}.html"
    _delete_if_exists(report_json)
    _delete_if_exists(report_md)
    _replace_move(report_html, final_html)
    return final_html


def _prompt_rename_file(path: Path, *, prompt: str, suffix: str) -> Path:
    try:
        raw_name = input(prompt).strip()
    except EOFError:
        raw_name = ""
    if not raw_name:
        return path
    file_name = _sanitize_local_file_name(raw_name)
    if not file_name.lower().endswith(suffix):
        file_name = f"{file_name}{suffix}"
    target = path.with_name(file_name)
    if target == path:
        return path
    _replace_move(path, target)
    return target


def _prompt_output_base_name(*, prompt: str, default_base: str) -> str:
    try:
        raw_name = input(prompt).strip()
    except EOFError:
        raw_name = ""
    value = raw_name or default_base
    return Path(_sanitize_local_file_name(value)).stem


def _sanitize_local_file_name(name: str) -> str:
    sanitized = "".join("_" if char in '/\\:\t*"<>|' else char for char in name).strip()
    return sanitized.rstrip(".") or "output"


def _replace_move(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    shutil.move(str(source), str(target))


def _delete_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()


def _remove_temporary_work_dir(log_dir: Path) -> None:
    if log_dir.exists():
        shutil.rmtree(log_dir)
