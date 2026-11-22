"""SimplePS 命令行模式：便于批处理、脚本调用与自动化测试。"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from .core import (
    auto_remove_background,
    imitate_handwriting,
    rect_cutout,
    remove_by_color,
    render_text,
)


def _parse_color(value: str):
    """解析 'r,g,b[,a]' 或 '#RRGGBB[AA]'。"""
    value = value.strip()
    if value.startswith("#"):
        h = value[1:]
        if len(h) in (6, 8):
            return tuple(int(h[i:i + 2], 16) for i in range(0, len(h), 2))
    parts = [int(float(v)) for v in value.split(",")]
    if len(parts) not in (3, 4):
        raise argparse.ArgumentTypeError(f"颜色格式错误: {value}，应为 r,g,b[,a] 或 #RRGGBB")
    return tuple(parts)


def _parse_rect(value: str) -> tuple[int, int, int, int]:
    parts = [int(float(v)) for v in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(f"矩形格式错误: {value}，应为 x,y,w,h")
    return tuple(parts)


def _parse_samples(value: str):
    if not value:
        return None
    out = []
    for pair in value.split(";"):
        x, y = pair.split(":")
        out.append((int(x), int(y)))
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="SimplePS",
        description="SimplePS — 图片去背景 / 抠图 / 字体模仿",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  SimplePS -i photo.png -o cut.png --mode auto
  SimplePS -i photo.png -o cut.png --mode color --samples 0:0;639:0
  SimplePS -i photo.png -o cut.png --mode rect --rect 80,40,160,170
  SimplePS --mode text --text "你好 SimplePS" --font-name "NotoSansCJK Regular" -o text.png
  SimplePS --mode hand --text "Hello 世界" --size 72 --seed 8 -o hand.png
""",
    )
    p.add_argument("-i", "--input", help="输入图片路径")
    p.add_argument("-o", "--output", help="输出图片路径（默认 out.png）")
    p.add_argument("--mode", choices=["auto", "color", "rect", "text", "hand"], default="auto",
                   help="处理模式: auto=自动去背景, color=按颜色去背景, rect=矩形抠图, text=文字渲染, hand=手写模仿")
    p.add_argument("--rect", type=_parse_rect, help="抠图矩形 x,y,w,h（mode=rect）")
    p.add_argument("--samples", type=_parse_samples, help="背景采样点 x:y;x:y（mode=color）")
    p.add_argument("--text", help="要生成的文字（mode=text/hand）")
    p.add_argument("--font", help="字体文件路径")
    p.add_argument("--font-name", help="字体名称（可用 SimplePS --list-fonts 查看）")
    p.add_argument("--list-fonts", action="store_true", help="列出系统字体并退出")
    p.add_argument("--size", type=int, default=72, help="字号，默认 72")
    p.add_argument("--color", type=_parse_color, default=(255, 255, 255, 255), help="文字颜色")
    p.add_argument("--tolerance", type=float, default=42.0, help="背景颜色容差")
    p.add_argument("--softness", type=float, default=12.0, help="颜色过渡宽度")
    p.add_argument("--iterations", type=int, default=5, help="GrabCut 迭代次数")
    p.add_argument("--feather", type=float, default=1.0, help="边缘羽化半径")
    p.add_argument("--stroke", type=int, default=0, help="文字描边宽度")
    p.add_argument("--jitter", type=float, default=4.0, help="手写字抖动幅度")
    p.add_argument("--angle", type=float, default=8.0, help="手写旋转角度范围")
    p.add_argument("--seed", type=int, default=None, help="手写随机种子")
    p.add_argument("--gui", action="store_true", help="强制启动图形界面")
    return p


def run_cli(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_fonts:
        from .core.typography import discover_fonts
        for f in discover_fonts():
            print(f"{f['name']}\t{f['path']}")
        return 0

    if args.mode in ("text", "hand"):
        if not args.text:
            print("错误: 文字模式需要 --text 参数", flush=True)
            return 2
        kw = dict(font_path=args.font, font_name=args.font_name, size=args.size,
                  color=args.color, stroke_width=args.stroke)
        if args.mode == "text":
            result = render_text(args.text, **kw)
        else:
            result = imitate_handwriting(args.text, jitter=args.jitter,
                                         angle_range=args.angle, seed=args.seed, **kw)
    else:
        if not args.input:
            print("错误: 图片模式需要 -i/--input 参数", flush=True)
            return 2
        src = Path(args.input)
        if not src.is_file():
            print(f"错误: 找不到输入图片 {src}", flush=True)
            return 2
        image = Image.open(src)
        image.load()

        if args.mode == "auto":
            result = auto_remove_background(image, iterations=args.iterations,
                                            tolerance=args.tolerance, feather=args.feather)
        elif args.mode == "color":
            result = remove_by_color(image, samples=args.samples, tolerance=args.tolerance,
                                     softness=args.softness, feather=args.feather)
        else:
            if not args.rect:
                print("错误: rect 模式需要 --rect x,y,w,h", flush=True)
                return 2
            result = rect_cutout(image, rect=args.rect, iterations=args.iterations,
                                 feather=args.feather)

    out = Path(args.output or "out.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    result.convert("RGBA").save(out)
    print(f"已保存: {out.resolve()}  ({result.width}x{result.height})")
    return 0
