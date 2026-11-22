"""核心图像处理算法。"""

from .background import auto_remove_background, remove_by_color
from .cutout import grabcut_with_marks, rect_cutout, clean_alpha
from .typography import discover_fonts, render_text, imitate_handwriting
from .text_style import TextStyle, analyze_text_style, render_styled_text, compose_styled_text
from .transforms import resize_image, rotate_image, rotate_90, crop_image, flip_image

__all__ = [
    "auto_remove_background",
    "remove_by_color",
    "grabcut_with_marks",
    "rect_cutout",
    "clean_alpha",
    "discover_fonts",
    "render_text",
    "imitate_handwriting",
    "TextStyle",
    "analyze_text_style",
    "render_styled_text",
    "compose_styled_text",
    "resize_image",
    "rotate_image",
    "rotate_90",
    "crop_image",
    "flip_image",
]
