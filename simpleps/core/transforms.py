"""常见图片变换：缩放、旋转、裁剪、翻转。全部返回新的 RGBA 图片。"""

from __future__ import annotations

from PIL import Image


def resize_image(image: Image.Image, width: int | None = None, height: int | None = None,
                 scale: float | None = None, keep_aspect: bool = True) -> Image.Image:
    """缩放图片。

    - ``scale`` 优先：按比例缩放。
    - 否则用 width/height；``keep_aspect=True`` 时以较大约束为准保持比例。
    """
    img = image.convert("RGBA")
    w, h = img.size
    if scale is not None:
        scale = float(scale)
        if scale <= 0:
            raise ValueError("缩放比例必须大于 0")
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    else:
        if width is None and height is None:
            return img
        if width is None:
            width = max(1, int(round(w * height / h)))  # type: ignore[operator]
        if height is None:
            height = max(1, int(round(h * width / w)))  # type: ignore[operator]
        width, height = max(1, int(width)), max(1, int(height))
        if keep_aspect:
            if abs(width / w - 1) < abs(height / h - 1):
                height = max(1, int(round(h * width / w)))
            else:
                width = max(1, int(round(w * height / h)))
        nw, nh = width, height
    return img.resize((nw, nh), Image.Resampling.LANCZOS)


def rotate_image(image: Image.Image, angle: float, expand: bool = True,
                 fill=(0, 0, 0, 0)) -> Image.Image:
    """任意角度旋转（逆时针为正）。"""
    return image.convert("RGBA").rotate(float(angle), resample=Image.Resampling.BICUBIC,
                                        expand=expand, fillcolor=fill)


def rotate_90(image: Image.Image, times: int = 1) -> Image.Image:
    """按 90 度步进旋转，times 可为负（顺时针）。"""
    return image.convert("RGBA").rotate(90.0 * times, expand=True, fillcolor=(0, 0, 0, 0))


def crop_image(image: Image.Image, rect: tuple[int, int, int, int]) -> Image.Image:
    """按矩形裁剪，rect=(left, top, right, bottom)。"""
    l, t, r, b = [int(v) for v in rect]
    l, t = max(0, l), max(0, t)
    r, b = min(image.width, r), min(image.height, b)
    if r - l < 1 or b - t < 1:
        raise ValueError("裁剪区域无效")
    return image.convert("RGBA").crop((l, t, r, b))


def flip_image(image: Image.Image, direction: str = "horizontal") -> Image.Image:
    """水平 / 垂直镜像翻转。"""
    img = image.convert("RGBA")
    if direction == "horizontal":
        return img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if direction == "vertical":
        return img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    raise ValueError("direction 必须是 horizontal 或 vertical")
