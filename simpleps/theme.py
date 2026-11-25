"""SimplePS v3 "极光" 视觉主题。

提供统一配色、渐变位图与自绘线性图标，供 customtkinter 界面使用。
所有图标均为程序化绘制，无外部图片依赖，打包体积小、任意分辨率清晰。
"""

from __future__ import annotations

from PIL import Image, ImageDraw

# ---------------------------------------------------------------- 配色
BG_DEEP = "#0A0F22"
BG_BASE = "#0D1329"
CARD = "#182142"
CARD_HI = "#222E57"
BORDER = "#2C3B6B"
FG = "#EEF2FF"
MUTED = "#9AA6CE"
CYAN = "#22D3EE"
PURPLE = "#8B5CF6"
PINK = "#F472B6"
GREEN = "#34D399"
RED = "#FB7185"
AMBER = "#FBBF24"

CYAN_RGB = (34, 211, 238)
PURPLE_RGB = (139, 92, 246)
PINK_RGB = (244, 114, 182)


def _hx(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


# ---------------------------------------------------------------- 渐变位图
def linear_gradient(size: tuple[int, int], stops: list[tuple[float, str]],
                    vertical: bool = True) -> Image.Image:
    """生成线性渐变图。stops: [(位置0-1, 颜色hex), ...]。"""
    w, h = size
    length = h if vertical else w
    strip = Image.new("RGB", (1, length))
    px = strip.load()
    stops = sorted(stops)
    for i in range(length):
        t = i / max(1, length - 1)
        # 找到所在区间
        c = _hx(stops[-1][1])
        for j in range(len(stops) - 1):
            p0, col0 = stops[j]
            p1, col1 = stops[j + 1]
            if p0 <= t <= p1:
                r0, g0, b0 = _hx(col0)
                r1, g1, b1 = _hx(col1)
                f = (t - p0) / max(1e-6, p1 - p0)
                c = (int(r0 + (r1 - r0) * f),
                     int(g0 + (g1 - g0) * f),
                     int(b0 + (b1 - b0) * f))
                break
        px[0, i] = c
    grad = strip.resize((w, h), Image.Resampling.BILINEAR)
    return grad


def aurora_gradient(size: tuple[int, int]) -> Image.Image:
    """极光渐变：深蓝 -> 靛紫 -> 暗紫，带一点青色辉光。"""
    return linear_gradient(size, [
        (0.0, "#0A0F24"),
        (0.45, "#141C3E"),
        (0.8, "#1B1740"),
        (1.0, "#241640"),
    ], vertical=True)


def accent_gradient(size: tuple[int, int]) -> Image.Image:
    """强调渐变：青 -> 紫 -> 粉，用于主按钮/选中态。"""
    return linear_gradient(size, [
        (0.0, CYAN),
        (0.55, PURPLE),
        (1.0, PINK),
    ], vertical=False)


# ---------------------------------------------------------------- 图标
def make_icon(kind: str, color: str = FG, size: int = 24, glow: bool = False) -> Image.Image:
    """程序化绘制线性图标，返回 RGBA 图。kind 见 ICONS。"""
    S = 96
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = _hx(color) + (255,)
    w = 7

    def line(points, width=w):
        d.line(points, fill=c, width=width, joint="curve")

    def arc(box, start, end, width=w):
        d.arc(box, start, end, fill=c, width=width)

    if kind == "open":  # 相框 + 加号
        d.rounded_rectangle([10, 24, 62, 72], radius=9, outline=c, width=w)
        d.ellipse([20, 34, 32, 46], fill=c)
        line([(12, 68), (34, 50), (46, 60), (58, 50), (61, 54)])
        d.ellipse([62, 8, 90, 36], fill=_hx(BG_BASE) + (255,), outline=c, width=w)
        line([(76, 16), (76, 28)], 6)
        line([(70, 22), (82, 22)], 6)
    elif kind == "bg":  # 圆被竖线分为前景/背景
        d.ellipse([12, 12, 84, 84], outline=c, width=w)
        line([(48, 12), (48, 84)], 5)
        for x, y in [(26, 30), (34, 42), (24, 54), (36, 64), (30, 74)]:
            d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=c)
    elif kind == "cutout":  # 剪刀
        d.ellipse([10, 62, 30, 82], outline=c, width=w)
        d.ellipse([10, 10, 30, 30], outline=c, width=w)
        line([(24, 74), (82, 22)])
        line([(24, 22), (50, 48), (82, 74)])
        d.ellipse([46, 44, 54, 52], fill=_hx(BG_BASE) + (255,), outline=c, width=4)
    elif kind == "text":  # T
        line([(16, 20), (80, 20)], 9)
        line([(48, 20), (48, 82)], 9)
        line([(34, 80), (62, 80)], 5)
    elif kind == "crop":  # 裁剪角标
        line([(20, 36), (20, 20), (36, 20)])
        line([(60, 20), (76, 20), (76, 36)])
        line([(76, 60), (76, 76), (60, 76)])
        line([(36, 76), (20, 76), (20, 60)])
        line([(12, 48), (84, 48)], 4)
    elif kind == "rotate":  # 旋转箭头
        arc([18, 18, 78, 78], 300, 200, w)
        # 箭头头
        line([(58, 20), (76, 26), (70, 42)])
    elif kind == "transform":  # 对角双向缩放箭头
        line([(20, 76), (76, 20)])
        line([(52, 20), (78, 20), (78, 46)])
        line([(18, 50), (18, 78), (46, 78)])
        d.ellipse([14, 72, 26, 84], fill=c)
    elif kind == "undo":
        arc([20, 20, 80, 80], 200, 500, w)
        line([(20, 44), (20, 66), (42, 66)])
    elif kind == "redo":
        arc([16, 20, 76, 80], 40, 340, w)
        line([(76, 44), (76, 66), (54, 66)])
    elif kind == "save":  # 下载到托盘
        line([(48, 14), (48, 58)])
        line([(32, 44), (48, 60), (64, 44)])
        line([(18, 72), (78, 72)])
        line([(18, 72), (18, 84), (78, 84), (78, 72)])
    elif kind == "check":
        line([(18, 50), (40, 72), (80, 26)], 10)
    elif kind == "sparkles":
        d.polygon([(48, 10), (56, 38), (84, 46), (56, 54), (48, 82), (40, 54), (12, 46), (40, 38)], fill=c)
    else:
        d.ellipse([24, 24, 72, 72], outline=c, width=w)

    if glow:
        # 简易外发光
        import PIL.ImageFilter as F
        glow_layer = img.filter(F.GaussianBlur(6))
        glow_layer.putalpha(glow_layer.getchannel("A").point(lambda a: int(a * 0.5)))
        out = Image.alpha_composite(glow_layer, img)
    else:
        out = img
    return out.resize((size, size), Image.Resampling.LANCZOS)


ICON_KINDS = ["open", "bg", "cutout", "text", "crop", "rotate", "transform"]
