"""SimplePS 核心功能单元测试。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simpleps.core import (  # noqa: E402
    auto_remove_background,
    imitate_handwriting,
    rect_cutout,
    remove_by_color,
    render_text,
)
from simpleps.cli import run_cli  # noqa: E402


def make_sample() -> Image.Image:
    img = Image.new("RGB", (240, 180), (250, 250, 250))
    d = ImageDraw.Draw(img)
    d.ellipse((60, 30, 180, 150), fill=(30, 120, 220))
    return img


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.img = make_sample()

    def assert_transparent_result(self, result: Image.Image) -> None:
        self.assertEqual(result.mode, "RGBA")
        alpha = np.array(result)[:, :, 3]
        self.assertGreater(int((alpha > 0).sum()), 1000)
        self.assertLess(int((alpha == 255).sum()), 240 * 180)

    def test_auto_remove(self):
        self.assert_transparent_result(auto_remove_background(self.img, iterations=3))

    def test_color_remove(self):
        self.assert_transparent_result(remove_by_color(self.img, tolerance=40))

    def test_rect_cutout(self):
        self.assert_transparent_result(rect_cutout(self.img, (50, 20, 140, 140), iterations=3))


class TypographyTests(unittest.TestCase):
    def test_render_text(self):
        out = render_text("你好 SimplePS", size=36)
        self.assertEqual(out.mode, "RGBA")
        self.assertGreater(out.width, 50)
        self.assertGreater(out.height, 20)

    def test_gradient_text(self):
        out = render_text("渐变", size=36, gradient_colors=[(255, 0, 0), (0, 0, 255)])
        alpha = np.array(out)[:, :, 3]
        self.assertGreater(int((alpha > 0).sum()), 50)

    def test_handwriting_deterministic(self):
        a = imitate_handwriting("手写 Test", size=32, seed=42)
        b = imitate_handwriting("手写 Test", size=32, seed=42)
        self.assertEqual(a.tobytes(), b.tobytes())


class CliTests(unittest.TestCase):
    def test_cli_text(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "text.png"
            code = run_cli(["--mode", "text", "--text", "CLI 测试", "-o", str(out)])
            self.assertEqual(code, 0)
            self.assertTrue(out.exists())
            with Image.open(out) as saved:
                self.assertEqual(saved.mode, "RGBA")


if __name__ == "__main__":
    unittest.main()
