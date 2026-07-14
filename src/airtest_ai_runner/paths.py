from __future__ import annotations

"""
统一管理项目里各种“产物目录”的位置。

这里说的产物，主要指：
1. 执行日志；
2. 业务截图；
3. HTML/Markdown/JSON 报告；
4. dump_current_screen、poco_inspector 之类工具生成的辅助文件。

单独抽出这个文件的好处是：
以后如果你想把所有输出从下载目录改到别处，只需要改这一处。
"""

import os
import shutil
from datetime import datetime
from pathlib import Path

DEFAULT_ARTIFACTS_ROOT = Path("/Users/sunyi/Downloads/multilang_check_artifacts")


def get_artifacts_root() -> Path:
    """
    统一管理所有大体积产物的输出根目录。

    默认写到用户下载目录，避免把项目工作区塞满：
    /Users/sunyi/Downloads/multilang_check_artifacts

    如果以后想临时改地址，也可以通过环境变量 ARTIFACTS_ROOT 覆盖。
    """
    # 先看用户有没有通过环境变量手动指定产物目录。
    # 这一步优先级最高，适合临时切目录时使用。
    env_path = os.environ.get("ARTIFACTS_ROOT", "").strip()
    if env_path:
        return Path(env_path).expanduser().resolve()
    # 如果用户没传，就回退到项目默认下载目录。
    return DEFAULT_ARTIFACTS_ROOT.resolve()


def ensure_artifacts_root() -> Path:
    """
    确保产物根目录存在，不存在就自动创建。

    适合“我要往这里写文件，但不想关心目录是否存在”的场景。
    """
    root = get_artifacts_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def prompt_cleanup_artifacts_root() -> tuple[Path, list[Path]]:
    """
    在单模块脚本启动前，让用户手动选择要删除的旧产物。

    这样可以避免误删刚导出的 `current_dump`、旧报告或临时保留的截图。

    现在改成更适合新手的交互方式：
    1. 先列出产物目录下的第一层文件/文件夹；
    2. 用户输入要删除的编号，例如 `1,3,5-7`；
    3. 直接回车表示什么都不删；
    4. 输入 `all` 表示删除全部列出的内容。

    返回值：
    - 第一个值是产物根目录；
    - 第二个值是本次实际删除的路径列表，方便调用方打印提示。
    """
    root = ensure_artifacts_root()
    items = sorted(root.iterdir(), key=lambda item: item.name.lower())
    if not items:
        print(f"产物目录为空，无需清理: {root}")
        return root, []

    print("\n检测到产物目录已有以下内容：")
    print(f"目录: {root}")
    for index, item in enumerate(items, start=1):
        item_type = "目录" if item.is_dir() else "文件"
        print(f"  {index}. [{item_type}] {item.name}")
    print("请输入要删除的编号，例如 1,3,5-7；直接回车表示不删除；输入 all 删除全部。")

    try:
        raw_choice = input("请选择要清理的文件/目录: ").strip().lower()
    except EOFError:
        raw_choice = ""

    selected_indexes = _parse_cleanup_selection(raw_choice, len(items))
    if not selected_indexes:
        print("本次不删除旧产物。")
        return root, []

    deleted: list[Path] = []
    for index in selected_indexes:
        item = items[index - 1]
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
        deleted.append(item)

    print("已删除以下旧产物：")
    for item in deleted:
        print(f"  - {item}")
    return root, deleted


def _parse_cleanup_selection(raw_choice: str, item_count: int) -> list[int]:
    """解析用户输入的清理编号，支持 `all`、逗号和区间。"""
    if not raw_choice or raw_choice in {"n", "no", "none", "skip"}:
        return []
    if raw_choice in {"a", "all", "*"}:
        return list(range(1, item_count + 1))

    selected: set[int] = set()
    for part in raw_choice.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            if start_text.strip().isdigit() and end_text.strip().isdigit():
                start = int(start_text)
                end = int(end_text)
                if start > end:
                    start, end = end, start
                for value in range(start, end + 1):
                    if 1 <= value <= item_count:
                        selected.add(value)
            continue
        if part.isdigit():
            value = int(part)
            if 1 <= value <= item_count:
                selected.add(value)
    return sorted(selected)


def get_run_artifacts_dir() -> Path:
    """返回本次执行的日期目录，例如 `multilang_check_artifacts/2026-07-01`。"""
    run_dir = ensure_artifacts_root() / datetime.now().strftime("%Y-%m-%d")
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def get_module_log_dir(module_name: str) -> Path:
    """
    返回单模块脚本的日志目录，例如：
    /Users/sunyi/Downloads/multilang_check_artifacts/2026-07-01/_atw_test_work
    """
    # Airtest 运行中仍需要临时 logdir，执行结束后会清理，只保留截图、表格和报告。
    return get_run_artifacts_dir() / f"_{module_name}_work"


def get_current_dump_dir() -> Path:
    """返回当前页面手动导出数据的目录。"""
    return ensure_artifacts_root() / "current_dump"


def get_poco_inspect_dir() -> Path:
    """返回 Poco 控件树检查工具的默认输出目录。"""
    return ensure_artifacts_root() / "poco_inspect"


def get_hover_inspector_dir() -> Path:
    """返回鼠标悬停坐标检查工具的输出目录。"""
    return ensure_artifacts_root() / "hover_inspector"


def get_coordinate_capture_dir() -> Path:
    """
    返回悬停检查工具的人工坐标记录目录。

    这个目录只给 `poco_hover_inspector.py` 保存观察结果。
    当前自动化执行不读取这里的 YAML，也不会把这里的坐标当点击目标。
    """
    project_root = Path(__file__).resolve().parents[2]
    output_dir = project_root / "coordinate_captures"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir
