from __future__ import annotations
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportAny=false, reportUnusedCallResult=false

"""
Poco 页面采集小工具。

适合在“我先手动把页面切到目标界面，再导出节点和截图”的场景下使用。
它不负责执行业务流，只负责把当前页面的结构证据保存下来，
方便后续查控件名、坐标、文本内容和页面层级。
"""

import argparse
from pathlib import Path

from airtest.core.api import auto_setup, snapshot
from airtest.core.settings import Settings as ST

from .paths import get_poco_inspect_dir
from .poco_utils import build_android_poco, dump_visible_nodes, write_poco_nodes_field_guide
from .screenshot_utils import normalize_image_file_for_landscape


def main() -> int:
    """
    导出当前页面的 Poco 控件树和截图。
    这个工具不负责点击页面，只负责“采集证据”，方便后续分析按钮结构。
    """
    # 第 1 步：解析命令行参数。
    # 当前只支持一个常用参数：--output-dir
    # 不传时就走默认目录，传了就写到用户指定位置。
    parser = argparse.ArgumentParser(description="导出当前页面 Poco 控件树与截图")
    _ = parser.add_argument(
        "--output-dir",
        default=None,
        help="输出目录。若不传，则默认写入本次 Airtest 运行的日志目录。",
    )
    args = parser.parse_args()

    # 初始化 Airtest 运行环境，让截图和日志目录能正常工作。
    # 这个动作可以理解成“先把截图相机和日志系统打开”。
    auto_setup(__file__)

    if args.output_dir:
        # 用户手动指定了目录时，优先把结果放到用户给定的位置。
        output_dir = Path(args.output_dir).resolve()
    else:
        # 没传目录时，优先使用本次运行的日志目录。
        # 如果日志目录暂时为空，再退回到下载目录里的 artifacts/poco_inspect，
        # 避免采集图片和 JSON 堆在项目工作区。
        output_dir = Path(ST.LOG_DIR or get_poco_inspect_dir()).resolve()

    # 先创建输出目录，避免后面写文件时报“目录不存在”。
    output_dir.mkdir(parents=True, exist_ok=True)

    # 初始化 Poco，并把当前可见节点全部导出成 JSON。
    poco = build_android_poco()
    nodes_path = output_dir / "poco_nodes.json"
    _ = dump_visible_nodes(poco, nodes_path)
    guide_path = write_poco_nodes_field_guide(nodes_path)

    # 再补一张当前页面截图，方便你把 JSON 节点和真实界面对照查看。
    screen_path = output_dir / "screen.png"
    _ = snapshot(filename=str(screen_path), msg="当前页面截图")
    _ = normalize_image_file_for_landscape(screen_path)
    print(f"已导出 Poco 控件树：{nodes_path}")
    print(f"已导出字段说明：{guide_path}")
    print(f"已导出页面截图：{screen_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
