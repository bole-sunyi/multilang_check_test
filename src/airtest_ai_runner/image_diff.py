from __future__ import annotations

"""
截图基线比对工具。

这个模块主要做 3 件事：
1. 扫描当前截图目录和基线目录；
2. 对同名 PNG 做像素级差异比较；
3. 在需要时生成带红框的差异标记图，供人工排查。

它服务的核心场景是“界面回归”，也就是判断这次运行出来的画面，
和上一版确认过的基线图相比有没有明显变化。
"""

import os
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, asdict
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageChops


@dataclass
class DiffResult:
    """描述一张截图的比对结果，便于后续统一写进 JSON/报告。"""
    baseline: str
    current: str
    marked: str
    diff_ratio: float
    different_pixels: int
    width: int
    height: int
    passed: bool
    status: str
    message: str = ""

    def to_dict(self) -> dict[str, object]:
        """把 dataclass 转成普通字典，方便 JSON 序列化。"""
        return asdict(self)


def _should_save_marked_image() -> bool:
    """
    是否保存带红框的差异标记图。

    默认关闭：
    1. 业务方平时更关注原始截图，不希望产物目录里混入额外的“框选版”图片；
    2. 差异率、通过状态本身已经足够用于回归判断；
    3. 如果以后确实需要排查某次差异来源，再手工打开环境变量即可。
    """
    raw_value = os.getenv("DIFF_SAVE_MARKED_IMAGES", "").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def _iter_png_files(path: Path) -> Iterable[Path]:
    """递归列出目录下所有 PNG 文件，并按文件名排序保证结果稳定。"""
    if not path.exists():
        return []
    return sorted([item for item in path.rglob("*.png") if item.is_file()])


def compare_directories(
    baseline_dir: Path,
    current_dir: Path,
    output_dir: Path,
    threshold: float = 0.01,
) -> list[DiffResult]:
    """
    对两个目录做“同名 PNG 批量比对”。

    返回结果里既会包含正常参与比对的图片，
    也会包含“缺基线图”或“本次未产出当前图”的异常项。
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    baseline_files = {file.name: file for file in _iter_png_files(baseline_dir)}
    current_files = {file.name: file for file in _iter_png_files(current_dir)}
    common_names = sorted(set(baseline_files) & set(current_files))
    missing_baselines = sorted(set(current_files) - set(baseline_files))
    missing_currents = sorted(set(baseline_files) - set(current_files))

    results: list[DiffResult] = []
    for file_name in common_names:
        # 只有两边都存在的同名图片，才进入真正的像素级比较。
        result = compare_images(
            baseline_files[file_name],
            current_files[file_name],
            output_dir / f"diff_{file_name}",
            threshold=threshold,
        )
        results.append(result)

    for file_name in missing_baselines:
        current_path = current_files[file_name]
        # 当前截图有，但基线图没有，说明这张图还没被纳入基线体系。
        results.append(
            DiffResult(
                baseline="",
                current=str(current_path),
                marked="",
                diff_ratio=1.0,
                different_pixels=0,
                width=0,
                height=0,
                passed=False,
                status="missing_baseline",
                message="当前截图存在，但缺少基线图。",
            )
        )

    for file_name in missing_currents:
        baseline_path = baseline_files[file_name]
        # 基线图存在，但这次没生成当前图，通常意味着业务步骤没走到或截图丢了。
        results.append(
            DiffResult(
                baseline=str(baseline_path),
                current="",
                marked="",
                diff_ratio=1.0,
                different_pixels=0,
                width=0,
                height=0,
                passed=False,
                status="missing_current",
                message="基线图存在，但本次执行未生成对应截图。",
            )
        )
    return results


def refresh_baseline_from_current(current_dir: Path, baseline_dir: Path) -> list[str]:
    """用当前目录里的截图覆盖刷新基线图目录。"""
    baseline_dir.mkdir(parents=True, exist_ok=True)
    copied_files: list[str] = []
    for current_file in _iter_png_files(current_dir):
        target_path = baseline_dir / current_file.name
        _ = shutil.copy2(current_file, target_path)
        copied_files.append(str(target_path))
    return copied_files


def compare_images(
    baseline_path: Path,
    current_path: Path,
    marked_output_path: Path,
    threshold: float = 0.01,
) -> DiffResult:
    """
    比较两张图片的像素差异，并返回结构化结果。

    如果尺寸不一致，会先把当前图缩放到基线图尺寸，
    这样可以避免因为截图设备尺寸不同而直接无法比较。
    """
    baseline_image = Image.open(baseline_path).convert("RGBA")
    current_image = Image.open(current_path).convert("RGBA")

    if baseline_image.size != current_image.size:
        # 某些设备分辨率不同，但我们仍然希望先看“内容是否大体一致”。
        current_image = current_image.resize(baseline_image.size)

    diff = ImageChops.difference(baseline_image, current_image)
    diff_array = np.array(diff)
    # 只要 RGB 任一通道变化明显，就把这个像素点视为“有差异”。
    active_mask: NDArray[np.uint8] = np.any(diff_array[:, :, :3] > 10, axis=2).astype(np.uint8) * 255

    different_pixels = int(np.count_nonzero(active_mask))
    width, height = baseline_image.size
    total_pixels = max(width * height, 1)
    diff_ratio = different_pixels / total_pixels

    marked_path = ""
    if diff_ratio > threshold and _should_save_marked_image():
        # 只有在真的超阈值时，才额外画红框。
        # 这样平时不会生成大量不必要的辅助图片。
        marked_image = cv2.cvtColor(np.array(current_image), cv2.COLOR_RGBA2BGRA)
        contours, _hierarchy = cv2.findContours(active_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w * h < 64:
                continue
            _ = cv2.rectangle(marked_image, (x, y), (x + w, y + h), (0, 0, 255, 255), 2)

        _ = cv2.imwrite(str(marked_output_path), marked_image)
        marked_path = str(marked_output_path)

    return DiffResult(
        baseline=str(baseline_path),
        current=str(current_path),
        marked=marked_path,
        diff_ratio=round(diff_ratio, 6),
        different_pixels=different_pixels,
        width=width,
        height=height,
        passed=diff_ratio <= threshold,
        status="matched" if diff_ratio <= threshold else "different",
        message="",
    )
