"""从图片中的参考文字分析样式（字体 / 字号 / 倾斜角 / 颜色），
并把新文字按该样式合成到图片的指定位置。

流程::

    style = analyze_text_style(image, rect, reference_text="示例文字")
    result = compose_styled_text(image, "新的文字", style, position=(x, y))

字体匹配采用「渲染候选字体 -> 与参考文字二值蒙版求 IoU」的方式，
无需 OCR；若提供 reference_text（图片中那句话的内容），匹配更准确。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
from PIL import Image, ImageFont

from .typography import discover_fonts, render_text


def _mask_sig(font, ch: str):
    m = np.asarray(font.getmask(ch), dtype=np.uint8)
    return m.tobytes(), font.getbbox(ch)


def _font_has_chars(path: str, text: str) -> bool:
    """检测字体是否包含 text 中非空白字符的字形（避免中文被渲染成方框）。

    判据：若多个不同汉字渲染结果完全相同，说明该字体用同一个 .notdef
    字形代替，视为不支持。
    """
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return True
    cjk = [c for c in chars if "\u4e00" <= c <= "\u9fff"]
    try:
        font = ImageFont.truetype(path, 32)
    except Exception:
        return False
    if len(cjk) >= 2:
        a, b = _mask_sig(font, cjk[0]), _mask_sig(font, cjk[1])
        if cjk[0] != cjk[1] and a == b:
            return False
    if cjk:
        missing = _mask_sig(font, "\U0010ffff")
        if _mask_sig(font, cjk[0]) == missing:
            return False
    return True


@dataclass
class TextStyle:
    font_path: str = ""
    font_name: str = ""
    size: int = 48
    color: tuple = (30, 30, 30, 255)
    angle: float = 0.0          # 文字基线相对水平的旋转角（度）
    bold: bool = False
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- 内部工具
def _border_color(arr: np.ndarray) -> np.ndarray:
    """取四边像素中出现最多的量化颜色作为背景色估计。"""
    h, w = arr.shape[:2]
    border = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]], axis=0)
    q = (border // 16 * 16).astype(np.int32)
    vals, counts = np.unique(q, axis=0, return_counts=True)
    if len(vals) == 0:
        return np.array([255, 255, 255], dtype=float)
    return vals[counts.argmax()].astype(float)


def _tight(mask: np.ndarray) -> np.ndarray:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return mask
    return mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _resize_mask(mask: np.ndarray, size: int = 72) -> np.ndarray:
    img = Image.fromarray((mask.astype(np.uint8) * 255), "L")
    img = img.resize((size, size), Image.Resampling.BILINEAR)
    return np.array(img) > 96


def _estimate_angle(mask: np.ndarray) -> float:
    """用前景像素主成分估计文字基线倾斜角，超过 ±35° 视为竖排/不可靠返回 0。"""
    ys, xs = np.where(mask)
    n = len(xs)
    if n < 12:
        return 0.0
    if n > 6000:
        idx = np.linspace(0, n - 1, 6000).astype(int)
        xs, ys = xs[idx], ys[idx]
    pts = np.column_stack([xs.astype(float), ys.astype(float)])
    pts -= pts.mean(axis=0)
    cov = pts.T @ pts / max(1, len(pts))
    vals, vecs = np.linalg.eigh(cov)
    v = vecs[:, vals.argmax()]
    ang = float(np.degrees(np.arctan2(v[1], v[0])))
    # 归一化到 [-90, 90)
    while ang >= 90:
        ang -= 180
    while ang < -90:
        ang += 180
    if abs(ang) > 35:
        return 0.0
    return round(ang, 1)


def _font_size_from_mask(mask: np.ndarray, image_size: tuple[int, int]) -> int:
    """用文字行高估算字号（CJK 字面高度约为字号的 0.9）。"""
    ys, xs = np.where(mask)
    if len(ys) == 0:
        return 48
    row_counts = np.bincount(ys, minlength=mask.shape[0])
    active = row_counts > max(1, 0.04 * len(xs) / max(1, mask.shape[0]))
    idx = np.where(active)[0]
    if len(idx) == 0:
        h = ys.max() - ys.min() + 1
    else:
        # 取最长的连续活跃行段作为一行文字高度
        best = cur = 0
        start = prev = int(idx[0])
        best_start = start
        for i in idx[1:]:
            i = int(i)
            if i == prev + 1:
                cur += 1
            else:
                if cur > best:
                    best, best_start = cur, start
                cur, start = 0, i
            prev = i
        if cur > best:
            best, best_start = cur, start
        h = max(1, best + 1)
    size = int(round(h / 0.9))
    return max(8, min(image_size[0], size))


def _text_mask(arr: np.ndarray, bg: np.ndarray, tol: float) -> np.ndarray:
    d = np.linalg.norm(arr.astype(float) - bg[None, None, :], axis=2)
    return d > tol


# ---------------------------------------------------------------- 公开 API
def analyze_text_style(
    image: Image.Image,
    rect: tuple[int, int, int, int],
    reference_text: str | None = None,
    max_fonts: int = 140,
    progress=None,
) -> TextStyle:
    """分析 rect 框选的参考文字，返回识别出的样式。

    Args:
        image: 原图（RGB/RGBA）。
        rect: (left, top, right, bottom) 框选的文字区域。
        reference_text: 图中文字的内容；提供后字体匹配的准确度明显提升。
        max_fonts: 参与匹配的候选字体上限（越多越准但越慢）。
        progress: 可选回调 ``(done, total, name)`` 用于显示进度。
    """
    img = image.convert("RGBA")
    W, H = img.size
    l, t, r, b = [int(v) for v in rect]
    l, t = max(0, l), max(0, t)
    r, b = min(W, r), min(H, b)
    if r - l < 6 or b - t < 6:
        raise ValueError("参考文字区域太小，请在图片上框住一行文字")

    crop = img.crop((l, t, r, b))
    arr = np.array(crop)[:, :, :3].astype(float)

    # 前景 / 背景分离
    bg = _border_color(arr)
    # 自适应容差：用像素与背景色距离的分布决定
    dist = np.linalg.norm(arr - bg[None, None, :], axis=2)
    tol = max(18.0, float(np.percentile(dist, 88)))
    mask = _text_mask(arr, bg, tol)

    # 去掉孤立噪点：行列投影过滤
    row_counts = np.bincount(np.where(mask)[0], minlength=mask.shape[0]) if mask.any() else np.array([])
    col_counts = np.bincount(np.where(mask)[1], minlength=mask.shape[1]) if mask.any() else np.array([])
    if len(row_counts):
        rth = max(1.0, row_counts.max() * 0.06)
        cth = max(1.0, col_counts.max() * 0.06)
        mask[row_counts < rth, :] = False
        mask[:, col_counts < cth] = False
    if not mask.any():
        mask = dist > max(12.0, float(np.percentile(dist, 96)))

    # 文字颜色（前景像素颜色中位数）
    fg_pixels = arr[mask]
    if len(fg_pixels):
        rgb = np.median(fg_pixels, axis=0).astype(int)
    else:
        rgb = np.array([30, 30, 30])
    color = tuple(int(v) for v in rgb) + (255,)

    size = _font_size_from_mask(mask, (W, H))
    angle = _estimate_angle(mask)

    target = _resize_mask(_tight(mask))

    # 字体匹配
    fonts = discover_fonts()
    best_path, best_name, best_score = "", "", -1.0
    text_for_match = (reference_text or "").strip() or None

    if text_for_match:
        # 只保留能渲染参考文字字形的候选字体，避免中文被匹配成方框字体
        candidates = [f for f in fonts if _font_has_chars(f["path"], text_for_match)][:max_fonts]
        if not candidates:
            candidates = fonts[:max_fonts]
        for i, f in enumerate(candidates):
            if progress:
                progress(i + 1, len(candidates), f["name"])
            try:
                layer = render_text(text_for_match, font_path=f["path"], size=64,
                                    color=(0, 0, 0, 255), padding=6)
                m = np.array(layer)[:, :, 3] > 100
                if not m.any():
                    continue
                cand = _resize_mask(_tight(m))
                inter = np.logical_and(cand, target).sum()
                union = np.logical_or(cand, target).sum()
                iou = inter / max(1, union)
                # 轻微奖励笔画密度接近者
                density = min(cand.mean(), target.mean()) / max(1e-6, max(cand.mean(), target.mean()))
                score = iou * 0.85 + density * 0.15
                if score > best_score:
                    best_score, best_path, best_name = score, f["path"], f["name"]
            except Exception:
                continue

    if not best_path:
        # 无参考文字时按尺寸挑一个中文字体作为合理默认
        from .typography import default_font_path
        best_path = default_font_path()
        best_name = next((f["name"] for f in fonts if f["path"] == best_path), "默认字体")
        best_score = 0.0

    bold = bool(row_counts.max() > 0 and (mask.sum() / max(1, mask.shape[0])) > 0.5)

    return TextStyle(
        font_path=best_path,
        font_name=best_name,
        size=size,
        color=color,
        angle=angle,
        bold=bold,
        confidence=round(float(max(0.0, best_score)), 3),
    )


def render_styled_text(text: str, style: TextStyle) -> Image.Image:
    """按样式渲染文字为透明图（已应用倾斜角）。"""
    layer = render_text(
        text,
        font_path=style.font_path,
        size=int(style.size),
        color=tuple(style.color),
        stroke_width=1 if style.bold else 0,
        stroke_color=tuple(style.color),
        padding=10,
    )
    if abs(style.angle) > 0.01:
        layer = layer.rotate(style.angle, resample=Image.Resampling.BICUBIC, expand=True,
                             fillcolor=(0, 0, 0, 0))
    return layer


def compose_styled_text(
    image: Image.Image,
    text: str,
    style: TextStyle,
    position: tuple[int, int] = (0, 0),
    anchor: str = "center",
) -> Image.Image:
    """把文字按样式合成到图片指定位置，返回新的 RGBA 图片。

    Args:
        position: 放置点（图片像素坐标）。
        anchor: ``center`` / ``topleft``，表示 position 对应文字的哪个点。
    """
    base = image.convert("RGBA")
    layer = render_styled_text(text, style)
    px, py = int(position[0]), int(position[1])
    if anchor == "center":
        x = px - layer.width // 2
        y = py - layer.height // 2
    elif anchor == "topleft":
        x, y = px, py
    else:
        raise ValueError("anchor 必须是 center 或 topleft")
    canvas = Image.new("RGBA", base.size, (0, 0, 0, 0))
    canvas.alpha_composite(layer, (x, y))
    return Image.alpha_composite(base, canvas)
