# -*- coding: utf-8 -*-
# ---------------------------------------------------------------
# 【脚本用途】
# 这是“鼠标悬停看坐标”工具。
#
# 它的核心作用不是自动点击，也不是生成可执行 YAML。
# 它只帮你做两件事：
# 1. 在截图上肉眼找按钮时，实时看到当前位置的 0-1 坐标；
# 2. 如果 Poco 能识别该位置的节点，会顺手告诉你节点名称和文本。
#
# 当前项目执行时只使用 dump_current_screen.py 生成的 name + chain。
# 本工具保存的 coordinate_pos 只供人工核对，不建议复制到 config/*.yaml。
# ---------------------------------------------------------------
import cv2
import os
import sys
from datetime import datetime
from pathlib import Path

# 确保能搜到我们的工具包
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from airtest.core.api import auto_setup, connect_device, snapshot
from airtest_ai_runner.device_utils import build_android_device_uri, select_android_device_serial
from airtest_ai_runner.poco_utils import build_poco
from airtest_ai_runner.paths import get_coordinate_capture_dir, get_hover_inspector_dir


ADB_HOST = "127.0.0.1"
ADB_PORT = 5037

# 全局变量，用于存储采集到的数据
# poco_nodes: 当前页面所有已摊平的节点
# screen_img: 原始截图
# display_img: 预留给后续扩展的显示图缓存
poco_nodes = []
screen_img = None
display_img = None
captured_points = []
current_hover_info = None
selected_serial = ""
session_started_at = ""
hover_yaml_path = None
latest_hover_yaml_path = None


def get_node_at(x_norm, y_norm):
    """
    根据归一化坐标 (0-1) 找到层级最深的节点（通常是我们要找的按钮）。
    原理很简单：
    1. 遍历所有节点；
    2. 找出“当前鼠标位置落在它范围里”的节点；
    3. 如果多个节点都命中，就优先返回面积最小、也就是最精确的那个。
    """
    best_node = None
    min_size = float('inf')

    for node in poco_nodes:
        pos = node.get("pos")
        size = node.get("size")
        if not pos or not size:
            continue

        # 计算边界
        x_min = pos[0] - size[0] / 2
        x_max = pos[0] + size[0] / 2
        y_min = pos[1] - size[1] / 2
        y_max = pos[1] + size[1] / 2

        # 检查坐标是否在范围内
        if x_min <= x_norm <= x_max and y_min <= y_norm <= y_max:
            # 选面积最小的（即最精准的叶子节点）
            area = size[0] * size[1]
            if area < min_size:
                min_size = area
                best_node = node

    return best_node


def save_hover_coordinate_yaml() -> None:
    """
    把鼠标点击确认过的位置保存到项目内 YAML。

    注意：这里保存的是 `coordinate_pos`，只是辅助观察用。
    模块执行配置仍然应该使用 Poco selector，不应该使用这些坐标。
    """
    if hover_yaml_path is None or latest_hover_yaml_path is None:
        return
    lines = [
        f"# 运行时间: {session_started_at}",
        f"# 更新时间: {datetime.now().isoformat(timespec='seconds')}",
        f"# 连接设备: {selected_serial}",
        f"# 坐标数量: {len(captured_points)}",
        "",
    ]
    for point in captured_points:
        lines.append(f"# {point['index']:02d}. {point['captured_at']}")
        lines.append(point["yaml_line"])
        lines.append("")
    yaml_text = "\n".join(lines).rstrip() + "\n"
    _ = hover_yaml_path.write_text(yaml_text, encoding="utf-8")
    _ = latest_hover_yaml_path.write_text(yaml_text, encoding="utf-8")


def update_hover_info(x, y):
    """刷新当前位置预览，并返回当前点位信息。"""
    global display_img, current_hover_info
    if screen_img is None:
        return None
    h, w = screen_img.shape[:2]
    # 计算归一化坐标 (Poco 使用的 0-1 坐标)
    x_norm = x / w
    y_norm = y / h

    # 查找该位置的节点
    node = get_node_at(x_norm, y_norm)

    # 刷新显示图
    # 每次鼠标一移动，都从原图重新复制一份，避免十字线和框越画越多。
    temp_img = screen_img.copy()

    # 绘制十字线
    cv2.line(temp_img, (0, y), (w, y), (0, 255, 0), 1)
    cv2.line(temp_img, (x, 0), (x, h), (0, 255, 0), 1)

    coordinate_pos = [round(x_norm, 3), round(y_norm, 3)]
    current_hover_info = {
        "coordinate_pos": coordinate_pos,
        "coordinate_pos_text": f"[{coordinate_pos[0]}, {coordinate_pos[1]}]",
        "yaml_line": f"coordinate_pos: [{coordinate_pos[0]}, {coordinate_pos[1]}]",
        "pixel": [int(x), int(y)],
        "node": None,
    }

    if node:
        # 提取节点信息
        name = node.get("name", "Unknown")
        text = node.get("text", "")
        info = f"Pos: [{x_norm:.3f}, {y_norm:.3f}] | Name: {name} | Text: {text}"
        current_hover_info["node"] = {"name": name, "text": text}

        # 在窗口左上角显示信息
        cv2.putText(temp_img, info, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        # 绘制节点边框
        pos = node["pos"]
        size = node["size"]
        nx, ny = int((pos[0] - size[0]/2) * w), int((pos[1] - size[1]/2) * h)
        nw, nh = int(size[0] * w), int(size[1] * h)
        cv2.rectangle(temp_img, (nx, ny), (nx + nw, ny + nh), (0, 0, 255), 2)
    else:
        info = f"Pos: [{x_norm:.3f}, {y_norm:.3f}] | No Poco node"
        cv2.putText(temp_img, info, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

    display_img = temp_img
    cv2.imshow("Poco Hover Inspector (Press ESC to Quit)", temp_img)
    return current_hover_info

def on_mouse_move(event, x, y, _flags, _param):
    """
    鼠标移动回调函数。
    只要鼠标在图片窗口里移动一次，这个函数就会自动触发一次。
    """
    _ = (_flags, _param)
    if event not in (cv2.EVENT_MOUSEMOVE, cv2.EVENT_LBUTTONDOWN):
        return

    hover_info = update_hover_info(x, y)
    if event != cv2.EVENT_LBUTTONDOWN or hover_info is None:
        return

    record = dict(hover_info)
    record["index"] = len(captured_points) + 1
    record["captured_at"] = datetime.now().isoformat(timespec="seconds")
    captured_points.append(record)
    save_hover_coordinate_yaml()
    print(f"\n>>> 已记录第 {record['index']} 个坐标: {record['yaml_line']}")
    print(f">>> 坐标 YAML: {hover_yaml_path}")


def start_inspector():
    global poco_nodes, screen_img, selected_serial, session_started_at, hover_yaml_path, latest_hover_yaml_path

    print("="*60)
    print("【Poco 鼠标悬停查询工具】")
    print("用法: 鼠标移动可预览坐标，左键点击会把当前坐标记录到 YAML。")
    print("="*60)

    # 1. 连接设备
    # 这里先连接模拟器，再初始化 Airtest，确保后续截图和 Poco 读取都能正常工作。
    print("正在连接设备并截取当前画面...")
    # 和 dump_current_screen.py 保持一致：
    # - 如果用户传了 DEVICE_SERIAL，就优先使用指定设备；
    # - 如果命令行第一个参数是设备号，也优先使用；
    # - 都没传时，再自动发现设备并在多设备时让用户选择。
    preferred_serial = os.environ.get("DEVICE_SERIAL", sys.argv[1] if len(sys.argv) > 1 else "").strip()
    selected_serial = select_android_device_serial(adb_host=ADB_HOST, preferred_serial=preferred_serial)
    device_uri = build_android_device_uri(ADB_HOST, ADB_PORT, selected_serial)
    dev = connect_device(device_uri)
    auto_setup(__file__, devices=[device_uri])

    session_started_at = datetime.now().isoformat(timespec="seconds")
    coordinate_dir = get_coordinate_capture_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    hover_yaml_path = coordinate_dir / f"hover_inspector_{timestamp}.yaml"
    latest_hover_yaml_path = coordinate_dir / "latest_hover_inspector.yaml"
    save_hover_coordinate_yaml()

    # 2. 采集数据
    # 这里直接读取 Poco 的原始层级树，再手工摊平成一维列表。
    # 这样鼠标每移动一次时，只需要在列表里查，不需要反复递归整棵树。
    poco = build_poco(dev)
    # 递归采集所有节点
    raw_dump = poco.agent.hierarchy.dump()

    def flatten(node):
        """
        把树状节点摊平成一维列表。
        这样后面鼠标移动时，就不用每次都递归整棵树，查找会更直接。
        """
        res = []
        payload = node.get("payload", {})
        if payload:
            res.append(payload)
        for child in node.get("children", []):
            res.extend(flatten(child))
        return res

    poco_nodes = flatten(raw_dump)

    # 3. 获取截图
    # 这里先临时生成一张截图，给 OpenCV 当作可视化底图使用。
    output_dir = get_hover_inspector_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    screen_file = output_dir / "temp_inspector_screen.png"
    snapshot(filename=str(screen_file))
    screen_img = cv2.imread(str(screen_file))
    if screen_img is None:
        print("错误: 无法获取截图，请检查模拟器连接。")
        return

    # 4. 创建交互窗口
    cv2.namedWindow("Poco Hover Inspector (Press ESC to Quit)", cv2.WINDOW_NORMAL)
    # 窗口大小调整为截图的一半，防止太大
    h, w = screen_img.shape[:2]
    cv2.resizeWindow("Poco Hover Inspector (Press ESC to Quit)", w // 2, h // 2)

    cv2.setMouseCallback("Poco Hover Inspector (Press ESC to Quit)", on_mouse_move)

    print("\n工具已启动！请在弹出的图片窗口上移动鼠标。")
    print("找到满意的按钮后，左键点击该位置，坐标会写入项目内 YAML。")
    print(f"本次坐标 YAML: {hover_yaml_path}")

    cv2.imshow("Poco Hover Inspector (Press ESC to Quit)", screen_img)

    while True:
        # 按 ESC 键退出
        if cv2.waitKey(1) & 0xFF == 27:
            break

    # 收尾：关闭窗口，删除临时截图文件，避免项目目录残留垃圾文件。
    cv2.destroyAllWindows()
    if screen_file.exists():
        screen_file.unlink()
    print(f"\n工具已关闭，共记录 {len(captured_points)} 个坐标。")
    print(f"坐标 YAML: {hover_yaml_path}")

if __name__ == "__main__":
    start_inspector()
