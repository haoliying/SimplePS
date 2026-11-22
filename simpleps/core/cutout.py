"""交互式抠图：矩形框选 + 前景/背景笔刷（基于 GrabCut）。"""

from __future__ import annotations

import numpy as np
from PIL import Image

from ..utils import require_cv2, to_bgr, bgr_to_rgba


def clean_alpha(alpha: np.ndarray, kernel_size: int = 3, close: int = 1, open_: int = 1) -> np.ndarray:
    """形态学清理 alpha：去小噪点、填补细小空洞。"""
    import cv2
    k = max(1, int(kernel_size) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    out = alpha.copy()
    if close > 0:
        out = cv2.morphologyEx(out, cv2.MORPH_CLOSE, kernel, iterations=close)
    if open_ > 0:
        out = cv2.morphologyEx(out, cv2.MORPH_OPEN, kernel, iterations=open_)
    return out


def _feather(alpha: np.ndarray, radius: float) -> np.ndarray:
    import cv2
    if radius <= 0:
        return alpha
    k = max(3, int(round(radius * 2 + 1)) | 1)
    return cv2.GaussianBlur(alpha, (k, k), radius)


def rect_cutout(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    iterations: int = 6,
    feather: float = 1.0,
    cleanup: bool = True,
) -> Image.Image:
    """用矩形框做抠图。

    Args:
        rect: ``(x, y, width, height)``，框住需要保留的主体。
    """
    require_cv2()
    import cv2

    bgr = to_bgr(image)
    h, w = bgr.shape[:2]
    x, y, rw, rh = [int(v) for v in rect]
    rw, rh = max(1, rw), max(1, rh)
    x = int(np.clip(x, 0, w - 1))
    y = int(np.clip(y, 0, h - 1))
    rw = int(np.clip(rw, 1, w - x))
    rh = int(np.clip(rh, 1, h - y))

    mask = np.zeros((h, w), dtype=np.uint8)
    bgd = np.zeros((1, 65), dtype=np.float64)
    fgd = np.zeros((1, 65), dtype=np.float64)
    cv2.grabCut(
        bgr, mask, (x, y, rw, rh), bgd, fgd,
        max(1, int(iterations)), cv2.GC_INIT_WITH_RECT,
    )
    alpha = np.where((mask == cv2.GC_BGD) | (mask == cv2.GC_PR_BGD), 0, 255).astype(np.uint8)
    if cleanup:
        alpha = clean_alpha(alpha)
    return bgr_to_rgba(bgr, _feather(alpha, feather))


def grabcut_with_marks(
    image: Image.Image,
    fg_mask: np.ndarray | None = None,
    bg_mask: np.ndarray | None = None,
    rect: tuple[int, int, int, int] | None = None,
    iterations: int = 6,
    feather: float = 1.0,
    cleanup: bool = True,
) -> Image.Image:
    """结合笔刷标记做精细抠图。

    Args:
        fg_mask: 与图片同尺寸的 uint8 掩码，>0 处标记为"确定前景"。
        bg_mask: 与图片同尺寸的 uint8 掩码，>0 处标记为"确定背景"。
        rect: 可选初始矩形 ``(x, y, w, h)``。
    """
    require_cv2()
    import cv2

    bgr = to_bgr(image)
    h, w = bgr.shape[:2]

    if fg_mask is None and bg_mask is None and rect is None:
        raise ValueError("请至少提供矩形框或前景/背景笔刷标记")

    bgd = np.zeros((1, 65), dtype=np.float64)
    fgd = np.zeros((1, 65), dtype=np.float64)

    if rect is not None:
        mask = np.zeros((h, w), dtype=np.uint8)
        x, y, rw, rh = [int(v) for v in rect]
        x = int(np.clip(x, 0, w - 1))
        y = int(np.clip(y, 0, h - 1))
        rw = int(np.clip(rw, 1, w - x))
        rh = int(np.clip(rh, 1, h - y))
        cv2.grabCut(
            bgr, mask, (x, y, rw, rh), bgd, fgd,
            max(1, int(iterations // 2)), cv2.GC_INIT_WITH_RECT,
        )
    else:
        mask = np.full((h, w), cv2.GC_PR_FGD, dtype=np.uint8)

    if bg_mask is not None:
        bm = np.asarray(bg_mask)
        if bm.shape != (h, w):
            raise ValueError("背景笔刷掩码尺寸与图片不一致")
        mask[bm > 0] = cv2.GC_BGD

    if fg_mask is not None:
        fm = np.asarray(fg_mask)
        if fm.shape != (h, w):
            raise ValueError("前景笔刷掩码尺寸与图片不一致")
        mask[fm > 0] = cv2.GC_FGD

    cv2.grabCut(
        bgr, mask, None, bgd, fgd,
        max(1, int(iterations)), cv2.GC_INIT_WITH_MASK,
    )

    alpha = np.where((mask == cv2.GC_BGD) | (mask == cv2.GC_PR_BGD), 0, 255).astype(np.uint8)
    if cleanup:
        alpha = clean_alpha(alpha)
    return bgr_to_rgba(bgr, _feather(alpha, feather))
