"""核心图像处理算法。"""

from .background import auto_remove_background, remove_by_color
from .cutout import grabcut_with_marks, rect_cutout, clean_alpha
from .typography import discover_fonts, render_text, imitate_handwriting

__all__ = [
    "auto_remove_background",
    "remove_by_color",
    "grabcut_with_marks",
    "rect_cutout",
    "clean_alpha",
    "discover_fonts",
    "render_text",
    "imitate_handwriting",
]
