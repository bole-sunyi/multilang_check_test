from __future__ import annotations

"""
截图后处理工具。

主要解决两类问题：
1. 某些设备/截图方案保存出来的 PNG 实际是竖版，需要统一转成横版；
2. 写入 Excel 前，需要按目标尺寸缩放并输出成 openpyxl 兼容更好的 PNG 数据。
"""

from io import BytesIO
from pathlib import Path
from typing import Literal

from PIL import Image, ImageOps

RotateDirection = Literal["cw", "ccw"]


def normalize_image_file_for_landscape(
    image_path: Path,
    rotate_direction: RotateDirection = "ccw",
) -> tuple[int, int]:
    """
    把落盘后的截图统一整理成横版 PNG。

    返回值是处理后的 `(width, height)`，方便调用方做日志或后续布局。
    """
    with Image.open(image_path) as image:
        normalized = _prepare_image(image, prefer_landscape=True, rotate_direction=rotate_direction)
        normalized.save(image_path, format="PNG")
        return normalized.size


def build_resized_png_buffer(
    image_path: Path,
    *,
    max_width_px: int,
    max_height_px: int,
    prefer_landscape: bool = False,
    rotate_direction: RotateDirection = "ccw",
) -> tuple[BytesIO, int, int]:
    """读取图片、按需要修正方向并缩放，返回内存 PNG 数据和缩放后尺寸。"""
    with Image.open(image_path) as image:
        normalized = _prepare_image(
            image,
            prefer_landscape=prefer_landscape,
            rotate_direction=rotate_direction,
        )
        resized = normalized.copy()
        resized.thumbnail((max_width_px, max_height_px), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        resized.save(buffer, format="PNG")
        width, height = resized.size

    _ = buffer.seek(0)
    return buffer, width, height


def _prepare_image(
    image: Image.Image,
    *,
    prefer_landscape: bool,
    rotate_direction: RotateDirection,
) -> Image.Image:
    """统一处理 EXIF 方向并在需要时旋转为横版。"""
    normalized = ImageOps.exif_transpose(image).convert("RGB")
    if prefer_landscape and normalized.width < normalized.height:
        rotation_angle = 90 if rotate_direction == "ccw" else -90
        normalized = normalized.rotate(rotation_angle, expand=True)
    return normalized
