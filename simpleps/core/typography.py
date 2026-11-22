"""字体渲染与"字体模仿"。

- ``discover_fonts`` 扫描系统字体目录，返回可直接用于渲染的字体列表。
- ``render_text`` 支持描边、阴影、渐变、多色、多行文本。
- ``imitate_handwriting`` 通过逐字旋转 / 抖动 / 缩放模拟手写风格。
"""

from __future__ import annotations

import os
import random
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

_FONT_EXTS = {".ttf", ".otf", ".ttc"}

# 常见字体的友好显示名
_FRIENDLY = {
    "simhei": "黑体 SimHei",
    "simsun": "宋体 SimSun",
    "simkai": "楷体 SimKai",
    "simfang": "仿宋 SimFang",
    "msyh": "微软雅黑 Microsoft YaHei",
    "msyhbd": "微软雅黑粗体",
    "arial": "Arial",
    "arialbd": "Arial Bold",
    "times": "Times New Roman",
    "calibri": "Calibri",
    "dejavusans": "DejaVu Sans",
    "dejavuserif": "DejaVu Serif",
    "notosanscjk": "Noto Sans CJK",
    "notosans": "Noto Sans",
    "notoserif": "Noto Serif",
}

# 仅使用明确的中文字体关键字，避免 "Canadian" 中的 "sc" 之类误匹配
_CN_HINTS = (
    "cjk", "simhei", "simsun", "simkai", "simfang", "yahei", "wqy",
    "sourcehan", "pingfang", "heiti", "songti", "kaiti", "fangsong",
    "chinese", "hans", "noto sans sc", "noto serif sc", "dengxian", "microsoft yahei",
)


@lru_cache(maxsize=1)
def discover_fonts() -> list[dict[str, str]]:
    """扫描系统字体，返回 ``[{"name": ..., "path": ...}, ...]``。"""
    system = os.name
    roots: list[Path] = []
    if system == "nt":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        roots += [Path(windir) / "Fonts", Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"]
    elif system == "darwin":
        roots += [Path("/System/Library/Fonts"), Path("/Library/Fonts"), Path.home() / "Library" / "Fonts"]
    else:
        roots += [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
                  Path.home() / ".fonts", Path.home() / ".local" / "share" / "fonts"]

    found: dict[str, str] = {}
    for root in roots:
        if not root or not root.exists():
            continue
        try:
            for dirpath, _, files in os.walk(root):
                for fn in files:
                    if Path(fn).suffix.lower() not in _FONT_EXTS:
                        continue
                    full = Path(dirpath) / fn
                    stem = Path(fn).stem
                    name = _FRIENDLY.get(stem.lower(), stem.replace("_", " ").replace("-", " "))
                    found.setdefault(name, str(full))
        except (OSError, PermissionError):
            continue

    items = [{"name": n, "path": p} for n, p in found.items()]
    items.sort(key=lambda d: d["name"].lower())
    if not items:
        raise RuntimeError("未找到任何系统字体，请安装字体后重试")
    return items


def default_font_path() -> str:
    """优先返回中文字体（按名称关键字识别），否则返回第一个可用字体。"""
    fonts = discover_fonts()
    for f in fonts:
        if any(h in f["name"].lower() for h in _CN_HINTS):
            return f["path"]
    return fonts[0]["path"]


def resolve_font_path(font_path: str | None = None, font_name: str | None = None) -> str:
    if font_path and os.path.isfile(font_path):
        return font_path
    if font_name:
        for f in discover_fonts():
            if f["name"] == font_name or f["name"].lower() == font_name.lower():
                return f["path"]
    return default_font_path()


def _get_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    size = max(6, int(size))
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default(size=size)


def _as_rgba(color, default=(255, 255, 255, 255)) -> tuple[int, int, int, int]:
    if color is None:
        return default
    if isinstance(color, (tuple, list)):
        c = list(color[:4])
        while len(c) < 4:
            c.append(255)
        return tuple(int(max(0, min(255, v))) for v in c)
    return default


def _gradient_rgb(colors, width: int) -> np.ndarray:
    """在 width 上插值渐变色，返回 (width, 3) uint8。"""
    cols = [_as_rgba(c)[:3] for c in colors]
    if len(cols) == 1:
        return np.tile(np.array(cols[0], dtype=np.uint8), (width, 1))
    x = np.linspace(0, len(cols) - 1, width)
    out = np.zeros((width, 3), dtype=np.float32)
    for i in range(3):
        out[:, i] = np.interp(x, np.arange(len(cols)), [c[i] for c in cols])
    return np.clip(out, 0, 255).astype(np.uint8)


def render_text(
    text: str,
    font_path: str | None = None,
    font_name: str | None = None,
    size: int = 64,
    color=(255, 255, 255, 255),
    stroke_width: int = 0,
    stroke_color=(0, 0, 0, 255),
    shadow_color=None,
    shadow_offset: tuple[int, int] = (3, 3),
    gradient_colors=None,
    line_spacing: float = 1.25,
    align: str = "left",
    padding: int = 12,
) -> Image.Image:
    """渲染文本为透明背景 RGBA 图片。

    Args:
        text: 支持 ``\\n`` 多行。
        gradient_colors: 颜色列表，如 ``[(255,0,0), (0,0,255)]``，设置后忽略 color。
        align: ``left`` / ``center`` / ``right``。
    """
    if not text:
        raise ValueError("文本不能为空")

    path = resolve_font_path(font_path, font_name)
    font = _get_font(path, size)
    color = _as_rgba(color)
    stroke_color = _as_rgba(stroke_color, (0, 0, 0, 255))

    lines = text.split("\n")
    probe = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    draw = ImageDraw.Draw(probe)
    boxes = [draw.textbbox((0, 0), line or " ", font=font, stroke_width=stroke_width) for line in lines]
    widths = [max(1, b[2] - b[0]) for b in boxes]
    heights = [max(1, b[3] - b[1]) for b in boxes]
    line_h = max(heights) * line_spacing

    canvas_w = int(max(widths) + padding * 2 + abs(shadow_offset[0]))
    canvas_h = int(line_h * len(lines) + padding * 2 + abs(shadow_offset[1]))
    canvas = Image.new("RGBA", (max(1, canvas_w), max(1, canvas_h)), (0, 0, 0, 0))

    def draw_lines(dr: ImageDraw.ImageDraw, fill, offset=(0, 0)) -> None:
        ox, oy = offset
        for i, line in enumerate(lines):
            lw = widths[i]
            if align == "center":
                x = (canvas_w - lw) / 2
            elif align == "right":
                x = canvas_w - padding - lw
            else:
                x = padding
            x += ox
            y = padding + i * line_h + oy
            dr.text((x, y), line, font=font, fill=fill,
                    stroke_width=stroke_width,
                    stroke_fill=stroke_color if shadow_color is None else fill)

    if shadow_color is not None:
        shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines(ImageDraw.Draw(shadow), _as_rgba(shadow_color, (0, 0, 0, 160)), shadow_offset)
        canvas = Image.alpha_composite(canvas, shadow)

    if gradient_colors:
        mask_img = Image.new("L", canvas.size, 0)
        md = ImageDraw.Draw(mask_img)
        for i, line in enumerate(lines):
            lw = widths[i]
            if align == "center":
                x = (canvas_w - lw) / 2
            elif align == "right":
                x = canvas_w - padding - lw
            else:
                x = padding
            y = padding + i * line_h
            md.text((x, y), line, font=font, fill=255, stroke_width=stroke_width, stroke_fill=255)
        grad = _gradient_rgb(gradient_colors, canvas.width)
        rgba = np.zeros((canvas.height, canvas.width, 4), dtype=np.uint8)
        rgba[:, :, :3] = grad[None, :, :]
        rgba[:, :, 3] = np.array(mask_img)
        layer = Image.fromarray(rgba, "RGBA")
    else:
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw_lines(ImageDraw.Draw(layer), color)

    return Image.alpha_composite(canvas, layer)


def imitate_handwriting(
    text: str,
    font_path: str | None = None,
    font_name: str | None = None,
    size: int = 64,
    color=(30, 30, 30, 255),
    jitter: float = 4.0,
    angle_range: float = 8.0,
    scale_jitter: float = 0.12,
    spacing: float = 1.05,
    seed: int | None = None,
    stroke_width: int = 0,
) -> Image.Image:
    """模拟手写风格：逐字旋转、上下抖动、轻微缩放，组合成图片。"""
    if not text:
        raise ValueError("文本不能为空")

    rng = random.Random(seed)
    path = resolve_font_path(font_path, font_name)
    font = _get_font(path, size)
    color = _as_rgba(color, (30, 30, 30, 255))

    pad = max(4, int(size * 0.18))
    lines = text.split("\n")
    line_h = int(size * 1.5)

    # 先测量每行宽度，用于居中/画布尺寸
    probe = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(probe)
    line_widths = [
        sum(d.textlength(ch, font=font) for ch in line if not ch.isspace()) * spacing
        for line in lines
    ]
    canvas_w = int(max(line_widths, default=size) + pad * 4)
    canvas_h = int(line_h * len(lines) + pad * 3)
    canvas = Image.new("RGBA", (max(canvas_w, 1), max(canvas_h, 1)), (0, 0, 0, 0))

    y_base = pad
    for line, total_w in zip(lines, line_widths):
        x = pad * 2
        for ch in line:
            if ch.isspace():
                x += d.textlength(ch, font=font) * spacing
                continue
            bbox = d.textbbox((0, 0), ch, font=font, stroke_width=stroke_width)
            cw = max(1, bbox[2] - bbox[0] + stroke_width * 2)
            chh = max(1, bbox[3] - bbox[1] + stroke_width * 2)
            char_img = Image.new("RGBA", (cw + pad * 2, chh + pad * 2), (0, 0, 0, 0))
            cd = ImageDraw.Draw(char_img)
            cd.text((pad - bbox[0], pad - bbox[1]), ch, font=font, fill=color,
                    stroke_width=stroke_width, stroke_fill=(0, 0, 0, 255))

            angle = rng.uniform(-angle_range, angle_range)
            scale = 1.0 + rng.uniform(-scale_jitter, scale_jitter)
            if angle or scale != 1.0:
                char_img = char_img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(0, 0, 0, 0))
                if scale != 1.0:
                    nw = max(1, int(char_img.width * scale))
                    nh = max(1, int(char_img.height * scale))
                    char_img = char_img.resize((nw, nh), Image.Resampling.LANCZOS)

            dy = int(rng.uniform(-jitter, jitter))
            canvas.alpha_composite(char_img, (int(x), int(y_base + dy)))
            x += d.textlength(ch, font=font) * spacing

        y_base += line_h

    return canvas
