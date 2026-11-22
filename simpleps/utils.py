"""通用辅助函数：PIL / NumPy / OpenCV 之间的转换。"""

from __future__ import annotations

import numpy as np
from PIL import Image

try:
    import cv2
except ImportError:  # pragma: no cover - 仅在缺少 OpenCV 时触发
    cv2 = None


def require_cv2() -> None:
    if cv2 is None:
        raise RuntimeError("需要 OpenCV，请先执行: pip install opencv-python")


def to_bgr(image: Image.Image) -> np.ndarray:
    """PIL Image -> OpenCV BGR ndarray（丢弃 alpha）。"""
    arr = np.array(image.convert("RGB"))
    return arr[:, :, ::-1].copy()


def to_rgba(image: Image.Image) -> Image.Image:
    """确保图片为 RGBA 模式。"""
    return image.convert("RGBA")


def bgr_to_rgba(bgr: np.ndarray, alpha: np.ndarray | None = None) -> Image.Image:
    """BGR ndarray + 可选 alpha(0-255) -> RGBA PIL Image。"""
    rgb = bgr[:, :, ::-1]
    if alpha is None:
        alpha = np.full(bgr.shape[:2], 255, dtype=np.uint8)
    alpha = np.clip(alpha, 0, 255).astype(np.uint8)
    rgba = np.dstack([rgb, alpha])
    return Image.fromarray(rgba, "RGBA")


def pil_to_bgr(image: Image.Image) -> np.ndarray:
    return to_bgr(image)


def fit_image_size(image_size, box_size, padding: int = 12):
    """按比例缩放图片以适配显示框，返回 (w, h)。"""
    iw, ih = image_size
    bw, bh = max(1, box_size[0] - padding), max(1, box_size[1] - padding)
    if iw <= 0 or ih <= 0:
        return (1, 1)
    scale = min(bw / iw, bh / ih, 1.0)
    return (max(1, int(iw * scale)), max(1, int(ih * scale)))
