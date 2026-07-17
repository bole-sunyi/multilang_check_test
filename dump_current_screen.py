# -*- coding: utf-8 -*-
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportAny=false, reportUnusedCallResult=false
# ---------------------------------------------------------------
# 【脚本用途】
# 这是“当前页面即时采集工具”。
#
# 适合场景：
# 1. 你已经手动把游戏切到某个目标页面；
# 2. 你不想执行任何点击，只想把当前页面截图和节点树导出来；
# 3. 你想对照 screen.png 和 nodes.json 判断 Poco 看到了什么；
# 4. 你想直接拿到可复制进 config/*.yaml 的 nodes_steps.yaml。
#
# 新手优先看 nodes_steps.yaml：
# - nodes.json 是完整原始数据，适合排查，但内容很多；
# - nodes_steps.yaml 已经帮你整理成 `name + chain` 点击步骤；
# - 复制 nodes_steps.yaml 里的步骤到模块 YAML 后，通常只需要改 name。
# ---------------------------------------------------------------
import sys
import os
from pathlib import Path

# 将 src 目录加入 Python 路径，确保能搜到我们的工具包
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from airtest.core.api import auto_setup, device, snapshot
from airtest_ai_runner.device_utils import build_android_device_uri, select_android_device_serial
from airtest_ai_runner.poco_utils import PocoHierarchyDumpError, build_poco, dump_visible_nodes
from airtest_ai_runner.paths import get_current_dump_dir
from airtest_ai_runner.screenshot_utils import normalize_image_file_for_landscape


ADB_HOST = "127.0.0.1"
ADB_PORT = 5037


def dump_now():
    """
    【即时采集工具】
    当你手动把游戏翻到某个界面，想看这个界面的 Poco 节点时，运行这个脚本。
    它会直接采集当前屏幕，不进行任何点击或跳转。
    """

    # 1. 连接设备（MuMu 模拟器）
    # 启动时自动发现可连接设备，避免每次手工维护固定模拟器端口。
    print("正在连接设备...")
    preferred_serial = os.environ.get("DEVICE_SERIAL", sys.argv[1] if len(sys.argv) > 1 else "").strip()
    device_serial = select_android_device_serial(adb_host=ADB_HOST, preferred_serial=preferred_serial)
    device_uri = build_android_device_uri(ADB_HOST, ADB_PORT, device_serial)
    auto_setup(__file__, devices=[device_uri])

    # 2. 初始化 Poco 引擎
    # Poco 负责读取页面上的控件结构，相当于“把屏幕翻译成可分析的数据”。
    print("正在初始化 Poco 引擎...")
    poco = build_poco(device())

    # 3. 设置输出目录
    # 采集结果会放在下载目录的 artifacts/current_dump/ 文件夹下，
    # 避免大图和 JSON 一直堆在项目目录里。
    output_dir = get_current_dump_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    # 4. 先截一张图，方便对照。
    # Poco socket 偶发断开时，至少能保留当前页面截图用于排查。
    img_path = output_dir / "screen.png"
    _ = snapshot(filename=str(img_path), msg="手动即时采集")
    _ = normalize_image_file_for_landscape(img_path)

    # 5. 采集节点树。
    # dump_visible_nodes 会一次生成 3 类文件：
    # - nodes.json：完整节点清单，适合搜索和排查；
    # - nodes字段说明.md：解释 JSON 每个字段什么意思；
    # - nodes_steps.yaml：把节点路径转换成可复制执行的 name + chain 步骤。
    print("正在抓取当前页面控件树 (Poco Tree)...")
    json_path = output_dir / "nodes.json"
    try:
        _ = dump_visible_nodes(poco, json_path)
    except PocoHierarchyDumpError as exc:
        error_path = output_dir / "poco_dump_error.txt"
        error_path.write_text(str(exc), encoding="utf-8")
        print("\n" + "="*50)
        print("【Poco 节点采集失败】")
        print(f"当前截图已保存: {img_path.absolute()}")
        print(f"错误说明已保存: {error_path.absolute()}")
        print(str(exc))
        print("="*50)
        raise SystemExit(1) from exc
    guide_path = json_path.with_name(f"{json_path.stem}字段说明.md")
    yaml_path = json_path.with_name(f"{json_path.stem}_steps.yaml")

    # 建议新手同时打开 screen.png 和 nodes_steps.yaml：
    # - screen.png 用来确认当前页面是不是你想采集的页面；
    # - nodes_steps.yaml 用来挑选要复制的 Poco selector。
    print("\n" + "="*50)
    print("【采集成功！】")
    print(f"1. 节点清单 (JSON): {json_path.absolute()}")
    print(f"2. 字段说明 (MD):   {guide_path.absolute()}")
    print(f"3. 可执行片段 (YAML): {yaml_path.absolute()}")
    print(f"4. 当前截图 (PNG):  {img_path.absolute()}")
    print("="*50)
    print("提示：优先打开 nodes_steps.yaml，挑选目标节点后复制到模块配置的 steps 下。")
    print("提示：模块执行前会让你选择清理旧产物；如果你删除了 current_dump，需要重新运行本工具。")


if __name__ == "__main__":
    dump_now()
