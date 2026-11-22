"""背景去除算法。

提供两种无需深度学习模型、可离线运行的方案：

1. ``remove_by_color`` —— 基于颜色距离，适合纯色 / 渐变背景（证件照、产品图）。
2. ``auto_remove_background`` —— 自动采样画面边缘颜色作为背景种子，再用
   OpenCV GrabCut 精修，适合主体与背景有色差的大多数图片。
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from ..utils import require_cv2, to_bgr, bgr_to_rgba


def _lab(image_bgr: np.ndarray) -> np.ndarray:
    import cv2
    return cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)


def _feather_alpha(alpha: np.ndarray, radius: float) -> np.ndarray:
    """对 alpha 做轻微羽化，让边缘更自然。"""
    if radius <= 0:
        return alpha
    import cv2
    k = int(max(1, round(radius * 2 + 1)))
    k += (k + 1) % 2  # 保证奇数核
    return cv2.GaussianBlur(alpha, (k, k), radius)


def _alpha_from_distance(dist: np.ndarray, tolerance: float, softness: float) -> np.ndarray:
    """距离 -> alpha，带平滑过渡带。"""
    softness = max(1e-3, float(softness))
    lo = max(0.0, tolerance - softness)
    hi = tolerance + softness
    t = np.clip((dist - lo) / (hi - lo), 0.0, 1.0)
    # smoothstep 让过渡更柔和
    t = t * t * (3.0 - 2.0 * t)
    return (t * 255.0).astype(np.uint8)


def remove_by_color(
    image: Image.Image,
    samples: list[tuple[int, int]] | None = None,
    tolerance: float = 45.0,
    softness: float = 12.0,
    feather: float = 0.8,
) -> Image.Image:
    """按采样颜色去除背景。

    Args:
        image: 输入图片。
        samples: 背景采样点列表 ``[(x, y), ...]``；为 None 时自动取四角与四边中点。
        tolerance: 颜色距离阈值（Lab 空间），越大去除范围越广。
        softness: 过渡带宽度，越大边缘越柔和。
        feather: 边缘羽化高斯半径，0 表示不羽化。
    """
    require_cv2()
    import cv2

    bgr = to_bgr(image)
    h, w = bgr.shape[:2]
    lab = _lab(bgr)

    if samples is None:
        m = 3
        samples = [
            (m, m), (w - 1 - m, m), (m, h - 1 - m), (w - 1 - m, h - 1 - m),
            (w // 2, m), (w // 2, h - 1 - m), (m, h // 2), (w - 1 - m, h // 2),
        ]

    seeds = []
    for x, y in samples:
        x, y = int(np.clip(x, 0, w - 1)), int(np.clip(y, 0, h - 1))
        seeds.append(lab[y, x])

    if not seeds:
        raise ValueError("至少需要一个背景采样点")

    seeds_arr = np.stack(seeds).astype(np.float32)  # (N, 3)
    # 计算每个像素到最近种子颜色的距离
    dist = np.full((h, w), np.inf, dtype=np.float32)
    for seed in seeds_arr:
        d = np.linalg.norm(lab - seed.reshape(1, 1, 3), axis=2)
        dist = np.minimum(dist, d)

    alpha = _alpha_from_distance(dist, tolerance, softness)
    alpha = _feather_alpha(alpha, feather)
    return bgr_to_rgba(bgr, alpha)


def auto_remove_background(
    image: Image.Image,
    iterations: int = 5,
    tolerance: float = 42.0,
    feather: float = 1.0,
    cleanup: bool = True,
) -> Image.Image:
    """自动去背景：边缘颜色聚类 + GrabCut 精修。

    Args:
        image: 输入图片。
        iterations: GrabCut 迭代次数，越多越精细（推荐 3-8）。
        tolerance: 背景种子颜色距离阈值。
        feather: 边缘羽化半径。
        cleanup: 是否做形态学清理（去小噪点、填小洞）。
    """
    require_cv2()
    import cv2

    bgr = to_bgr(image)
    h, w = bgr.shape[:2]
    if h < 8 or w < 8:
        raise ValueError("图片尺寸过小，无法自动去背景")

    lab = _lab(bgr)
    strip = max(2, min(h, w) // 60)

    border = np.concatenate([
        lab[:strip, :, :].reshape(-1, 3),
        lab[-strip:, :, :].reshape(-1, 3),
        lab[:, :strip, :].reshape(-1, 3),
        lab[:, -strip:, :].reshape(-1, 3),
    ], axis=0).astype(np.float32)

    # 限制 kmeans 样本量以加快速度
    if len(border) > 6000:
        idx = np.linspace(0, len(border) - 1, 6000).astype(int)
        border = border[idx]

    k = int(min(4, max(1, len(border))))
    criteria = (
        cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
        12,
        0.5,
    )
    _, labels, centers = cv2.kmeans(
        border, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS
    )
    counts = np.bincount(labels.ravel(), minlength=k).astype(np.float32)
    weights = counts / counts.sum()

    # 初始：全部可能是前景
    mask = np.full((h, w), cv2.GC_PR_FGD, dtype=np.uint8)

    for center, weight in zip(centers, weights):
        if weight < 0.06:
            continue
        d = np.linalg.norm(lab - center.reshape(1, 1, 3), axis=2)
        mask[d < tolerance] = cv2.GC_BGD
        mid = (mask == cv2.GC_PR_FGD) & (d < tolerance * 1.45)
        mask[mid] = cv2.GC_PR_BGD

    # 中心区域强制为前景，避免主体被误删
    cx0, cy0 = int(w * 0.28), int(h * 0.28)
    cx1, cy1 = int(w * 0.72), int(h * 0.72)
    center_region = mask[cy0:cy1, cx0:cx1]
    center_region[center_region == cv2.GC_PR_BGD] = cv2.GC_PR_FGD

    bgd_model = np.zeros((1, 65), dtype=np.float64)
    fgd_model = np.zeros((1, 65), dtype=np.float64)

    try:
        cv2.grabCut(
            bgr, mask, None, bgd_model, fgd_model,
            max(1, int(iterations)), cv2.GC_INIT_WITH_MASK,
        )
    except cv2.error:
        # 极端图片退化：直接按颜色阈值输出
        dist = np.min(
            [np.linalg.norm(lab - c.reshape(1, 1, 3), axis=2)
             for c, wt in zip(centers, weights) if wt >= 0.06]
            or [np.zeros((h, w), dtype=np.float32)],
            axis=0,
        )
        return bgr_to_rgba(bgr, _alpha_from_distance(dist, tolerance, 15.0))

    alpha = np.where(
        (mask == cv2.GC_BGD) | (mask == cv2.GC_PR_BGD), 0, 255
    ).astype(np.uint8)

    if cleanup:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        alpha = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, kernel, iterations=1)
        alpha = cv2.morphologyEx(alpha, cv2.MORPH_OPEN, kernel, iterations=1)

    alpha = _feather_alpha(alpha, feather)
    return bgr_to_rgba(bgr, alpha)
