from __future__ import annotations

"""
统一管理项目里各种“产物目录”的位置。

这里说的产物，主要指：
1. 执行日志；
2. 业务截图；
3. HTML/Markdown/JSON 报告；
4. quick_click、poco_inspector 之类工具生成的辅助文件。

单独抽出这个文件的好处是：
以后如果你想把所有输出从下载目录改到别处，只需要改这一处。
"""

import os
import shutil
from pathlib import Path


def get_artifacts_root() -> Path:
    """
    统一管理所有大体积产物的输出根目录。

    默认写到用户下载目录，避免把项目工作区塞满：
    /Users/sunyi/Downloads/artifacts

    如果以后想临时改地址，也可以通过环境变量 ARTIFACTS_ROOT 覆盖。
    """
    # 先看用户有没有通过环境变量手动指定产物目录。
    # 这一步优先级最高，适合临时切目录时使用。
    env_path = os.environ.get("ARTIFACTS_ROOT", "").strip()
    if env_path:
        return Path(env_path).expanduser().resolve()
    # 如果用户没传，就回退到项目默认下载目录。
    return Path("/Users/sunyi/Downloads/artifacts").resolve()


def ensure_artifacts_root() -> Path:
    """
    确保产物根目录存在，不存在就自动创建。

    适合“我要往这里写文件，但不想关心目录是否存在”的场景。
    """
    root = get_artifacts_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def clear_artifacts_root() -> Path:
    """
    在单模块脚本启动前清空整个产物目录。

    这样每次手动运行 `stamp_test.py`、`byd_test.py`、`atw_test.py` 时，
    下载目录里只保留本次最新执行生成的截图、日志和报告。
    """
    root = get_artifacts_root()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_module_log_dir(module_name: str) -> Path:
    """
    返回单模块脚本的日志目录，例如：
    /Users/sunyi/Downloads/artifacts/atw_test_logs
    """
    # 每个模块一个独立日志目录，避免不同模块的截图和报告混在一起。
    return ensure_artifacts_root() / f"{module_name}_logs"


def get_quick_click_dir() -> Path:
    """返回 quick_click.py 的输出目录。"""
    return ensure_artifacts_root() / "quick_click"


def get_current_dump_dir() -> Path:
    """返回当前页面手动导出数据的目录。"""
    return ensure_artifacts_root() / "current_dump"


def get_poco_inspect_dir() -> Path:
    """返回 Poco 控件树检查工具的默认输出目录。"""
    return ensure_artifacts_root() / "poco_inspect"


def get_hover_inspector_dir() -> Path:
    """返回鼠标悬停坐标检查工具的输出目录。"""
    return ensure_artifacts_root() / "hover_inspector"
