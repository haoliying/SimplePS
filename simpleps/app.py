"""SimplePS v3 图形界面 — "极光"风格移动端图片编辑器。

设计语言：深空极光渐变 + 玻璃拟态卡片 + 悬浮胶囊工具栏 + 程序化矢量图标。
交互原则：无"应用"按钮，参数调节或标记完成后即时生效，撤销栈保护每一步。
无图片时点击画布任意位置即可选择图片。
"""

from __future__ import annotations

import os
import time
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox

import customtkinter as ctk
import numpy as np
from PIL import Image, ImageDraw, ImageTk

from . import __version__
from .core import (
    TextStyle,
    analyze_text_style,
    auto_remove_background,
    compose_styled_text,
    crop_image,
    flip_image,
    grabcut_with_marks,
    rect_cutout,
    remove_by_color,
    render_text,
    resize_image,
    rotate_90,
    rotate_image,
)
from .core.typography import default_font_path, discover_fonts
from . import theme

ctk.set_appearance_mode("dark")

FILE_TYPES = [
    ("PNG 图片", "*.png"), ("JPEG 图片", "*.jpg;*.jpeg"),
    ("BMP 图片", "*.bmp"), ("WebP 图片", "*.webp"), ("所有文件", "*.*"),
]

# (key, 图标, 标题)
TOOLS = [
    ("bg", "bg", "去背景"),
    ("cutout", "cutout", "抠图"),
    ("text", "text", "文字"),
    ("crop", "crop", "裁剪"),
    ("rotate", "rotate", "旋转"),
    ("transform", "transform", "变换"),
]


class SimplePSApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"SimplePS v{__version__} — 极光图片编辑器")
        self.geometry("1280x860")
        self.minsize(960, 660)
        self.configure(fg_color=theme.BG_BASE)

        self.image: Image.Image | None = None
        self.filename: str | None = None
        self.history: list[Image.Image] = []
        self.hidx = -1

        self.samples: list[tuple[int, int]] = []
        self.rect: tuple[int, int, int, int] | None = None
        self.place_point: tuple[int, int] | None = None
        self.tool = "none"
        self.tool_tab = "bg"
        self.brush_radius = 16
        self.fg_mask_img: Image.Image | None = None
        self.bg_mask_img: Image.Image | None = None
        self.fg_overlay: Image.Image | None = None
        self.bg_overlay: Image.Image | None = None
        self._drag_start = None
        self._last_point = None
        self._panning = False
        self._pan_start = None

        self._photo: ImageTk.PhotoImage | None = None
        self._view_origin = (0, 0)
        self._view_scale = 1.0
        self._zoom = 1.0
        self._pan = (0, 0)
        self._resize_job = None
        self._debounce_job: dict[str, str] = {}

        self.text_color = [30, 30, 30, 255]
        self.style: TextStyle | None = None
        self._init_style()

        self._icon_cache: dict[tuple[str, str, int], ctk.CTkImage] = {}
        self._build_ui()
        self._bind_keys()
        self.switch_tab("bg")
        self.set_status("点击图片区域选择照片，或点击下方工具开始编辑")

    # ------------------------------------------------------------ 样式/工具
    def _init_style(self) -> None:
        fonts = discover_fonts()
        self.font_names = [f["name"] for f in fonts]
        self.font_paths = {f["name"]: f["path"] for f in fonts}
        dp = default_font_path()
        self._default_font_name = next((n for n, p in self.font_paths.items() if p == dp),
                                       self.font_names[0] if self.font_names else "")

    def _ico(self, kind: str, color: str = theme.FG, size: int = 24) -> ctk.CTkImage:
        key = (kind, color, size)
        if key not in self._icon_cache:
            self._icon_cache[key] = ctk.CTkImage(
                light_image=theme.make_icon(kind, color, size),
                dark_image=theme.make_icon(kind, color, size),
                size=(size, size))
        return self._icon_cache[key]

    def _debounce(self, key: str, delay_ms: int, fn) -> None:
        """参数防抖：连续调节时只在停止 delay 后执行一次。"""
        old = self._debounce_job.pop(key, None)
        if old:
            try:
                self.after_cancel(old)
            except Exception:
                pass
        self._debounce_job[key] = self.after(delay_ms, fn)

    # -------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # ---------- 顶部标题栏（深空渐变） ----------
        top = ctk.CTkFrame(self, height=64, corner_radius=0, fg_color=theme.BG_DEEP)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_propagate(False)

        self._top_grad = ctk.CTkLabel(top, text="", fg_color="transparent")
        # 用 Canvas 铺渐变背景（customtkinter 控件叠加其上）
        grad_bg = tk.Canvas(top, highlightthickness=0, bd=0)
        grad_bg.place(x=0, y=0, relwidth=1, relheight=1)
        self._grad_bg = grad_bg
        self._grad_img_ref = None
        grad_bg.bind("<Configure>", lambda e: self._paint_top_gradient())

        # 品牌 logo：渐变圆点 + 文字
        brand = ctk.CTkFrame(top, fg_color="transparent")
        brand.place(x=22, y=0, relheight=1)
        logo = ctk.CTkLabel(brand, text="◈", font=ctk.CTkFont(size=28),
                            text_color=theme.CYAN, fg_color="transparent")
        logo.pack(side=tk.LEFT, padx=(0, 8))
        ctk.CTkLabel(brand, text="SimplePS", font=ctk.CTkFont(size=19, weight="bold"),
                     text_color=theme.FG, fg_color="transparent").pack(side=tk.LEFT)
        ctk.CTkLabel(brand, text="  极光编辑器", font=ctk.CTkFont(size=11),
                     text_color=theme.MUTED, fg_color="transparent").pack(side=tk.LEFT, pady=(6, 0))

        right = ctk.CTkFrame(top, fg_color="transparent")
        right.pack(side=tk.RIGHT, padx=16)
        self.btn_undo = ctk.CTkButton(right, image=self._ico("undo", size=20), text="",
                                      width=38, height=38, corner_radius=12,
                                      fg_color=theme.CARD_HI, hover_color=theme.BORDER,
                                      command=self.undo)
        self.btn_redo = ctk.CTkButton(right, image=self._ico("redo", size=20), text="",
                                      width=38, height=38, corner_radius=12,
                                      fg_color=theme.CARD_HI, hover_color=theme.BORDER,
                                      command=self.redo)
        self.btn_undo.pack(side=tk.LEFT, padx=3)
        self.btn_redo.pack(side=tk.LEFT, padx=3)
        # 保存主按钮（渐变描边感：亮色 fg）
        self.btn_save = ctk.CTkButton(right, image=self._ico("save", size=18), text="保存",
                                      width=92, height=38, corner_radius=12,
                                      fg_color=theme.PURPLE, hover_color="#7C3AED",
                                      font=ctk.CTkFont(size=13, weight="bold"),
                                      command=self.save_image)
        self.btn_save.pack(side=tk.LEFT, padx=(10, 0))

        # ---------- 中央画布 ----------
        stage = ctk.CTkFrame(self, fg_color=theme.BG_BASE, corner_radius=0)
        stage.grid(row=1, column=0, sticky="nsew")
        stage.columnconfigure(0, weight=1)
        stage.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(stage, bg=theme.BG_BASE, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self.canvas.bind("<ButtonPress-1>", self._on_canvas_press)
        self.canvas.bind("<B1-Motion>", self._on_canvas_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.canvas.bind("<ButtonPress-2>", self._on_pan_press)
        self.canvas.bind("<B2-Motion>", self._on_pan_move)
        self.canvas.bind("<ButtonRelease-2>", self._on_pan_release)
        self.canvas.bind("<Control-ButtonPress-1>", self._on_canvas_ctrl_click)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda e: self._zoom_by(1.12, e))
        self.canvas.bind("<Button-5>", lambda e: self._zoom_by(1 / 1.12, e))
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        # ---------- 工具选项面板（玻璃卡片） ----------
        self.options = ctk.CTkFrame(self, height=126, corner_radius=0, fg_color=theme.BG_DEEP)
        self.options.grid(row=2, column=0, sticky="ew")
        self.options.grid_propagate(False)
        self.options_inner = ctk.CTkFrame(self.options, fg_color="transparent")
        self.options_inner.pack(fill=tk.BOTH, expand=True, padx=20, pady=12)

        # ---------- 底部悬浮胶囊工具栏 ----------
        nav_wrap = ctk.CTkFrame(self, height=92, corner_radius=0, fg_color=theme.BG_DEEP)
        nav_wrap.grid(row=3, column=0, sticky="ew")
        nav_wrap.grid_propagate(False)
        nav = ctk.CTkFrame(nav_wrap, fg_color=theme.CARD, corner_radius=26, height=72)
        nav.pack(padx=24, pady=10, fill=tk.Y)
        self.nav_open = self._make_nav_item(nav, "open", "打开", self.open_image)
        self.nav_open.pack(side=tk.LEFT, padx=(14, 4), pady=6)
        sep = ctk.CTkFrame(nav, fg_color=theme.BORDER, width=2, height=40, corner_radius=1)
        sep.pack(side=tk.LEFT, padx=8, pady=16)
        self.tool_buttons: dict[str, ctk.CTkFrame] = {}
        for key, icon, label in TOOLS:
            item = self._make_nav_item(nav, icon, label, lambda k=key: self.switch_tab(k))
            item.pack(side=tk.LEFT, padx=4, pady=6)
            self.tool_buttons[key] = item

        # ---------- 状态栏 ----------
        status = ctk.CTkFrame(self, height=26, corner_radius=0, fg_color=theme.BG_DEEP)
        status.grid(row=4, column=0, sticky="ew")
        status.grid_propagate(False)
        self.status_var = tk.StringVar(value="")
        ctk.CTkLabel(status, textvariable=self.status_var, font=ctk.CTkFont(size=11),
                     text_color=theme.MUTED, fg_color="transparent", anchor="w").pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=20)
        self.info_var = tk.StringVar(value="")
        ctk.CTkLabel(status, textvariable=self.info_var, font=ctk.CTkFont(size=11),
                     text_color=theme.GREEN, fg_color="transparent", anchor="e").pack(
            side=tk.RIGHT, padx=20)

    def _paint_top_gradient(self) -> None:
        w = self._grad_bg.winfo_width()
        h = self._grad_bg.winfo_height()
        if w < 2 or h < 2:
            return
        grad = theme.linear_gradient((w, h), [
            (0.0, "#0C1330"), (0.5, "#161C40"), (1.0, "#241A45")], vertical=False)
        self._grad_img_ref = ImageTk.PhotoImage(grad)
        self._grad_bg.delete("all")
        self._grad_bg.create_image(0, 0, image=self._grad_img_ref, anchor="nw")

    def _make_nav_item(self, parent, icon: str, label: str, cmd) -> ctk.CTkFrame:
        """底部工具栏项：图标 + 文字，选中态青紫渐变胶囊 + 发光。"""
        frame = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=18,
                             width=76, height=60)
        frame.pack_propagate(False)
        icon_lbl = ctk.CTkLabel(frame, image=self._ico(icon, theme.MUTED, 24), text="",
                                fg_color="transparent")
        icon_lbl.pack(pady=(6, 0))
        text_lbl = ctk.CTkLabel(frame, text=label, font=ctk.CTkFont(size=10),
                                text_color=theme.MUTED, fg_color="transparent")
        text_lbl.pack()
        frame.icon_lbl = icon_lbl
        frame.text_lbl = text_lbl
        frame.icon_key = icon
        frame._cmd = cmd
        for w in (frame, icon_lbl, text_lbl):
            w.bind("<Button-1>", lambda e: cmd())
        frame._active = False
        return frame

    def _set_nav_active(self, frame: ctk.CTkFrame, active: bool) -> None:
        frame._active = active
        if active:
            frame.configure(fg_color=theme.CARD_HI)
            frame.icon_lbl.configure(image=self._ico(frame.icon_key, theme.CYAN, 24))
            frame.text_lbl.configure(text_color=theme.CYAN,
                                     font=ctk.CTkFont(size=10, weight="bold"))
        else:
            frame.configure(fg_color="transparent")
            frame.icon_lbl.configure(image=self._ico(frame.icon_key, theme.MUTED, 24))
            frame.text_lbl.configure(text_color=theme.MUTED,
                                     font=ctk.CTkFont(size=10))

    # ---------------------------------------------------------- 选项条控件
    def _clear_options(self) -> None:
        for w in self.options_inner.winfo_children():
            w.destroy()
        # 居中容器：让选项卡片整体水平居中，避免右侧留白
        self._opt_bar = ctk.CTkFrame(self.options_inner, fg_color="transparent")
        self._opt_bar.pack(anchor="center", fill=tk.Y)

    def _opt_col(self, title: str) -> ctk.CTkFrame:
        c = ctk.CTkFrame(self._opt_bar, fg_color=theme.CARD, corner_radius=14)
        c.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 14))
        head = ctk.CTkFrame(c, fg_color="transparent")
        head.pack(fill=tk.X, padx=14, pady=(8, 2))
        ctk.CTkLabel(head, text=title, font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=theme.CYAN, fg_color="transparent").pack(side=tk.LEFT)
        body = ctk.CTkFrame(c, fg_color="transparent")
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 8))
        c.body = body
        return c

    def _opt_scale(self, parent, label: str, from_, to, default, command,
                   length=190, on_release=None) -> ctk.DoubleVar:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill=tk.X, pady=3)
        ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=11),
                     text_color=theme.MUTED, fg_color="transparent",
                     width=74, anchor="w").pack(side=tk.LEFT)
        var = ctk.DoubleVar(value=default)
        val_lbl = ctk.CTkLabel(row, text=f"{default:.0f}", font=ctk.CTkFont(size=10),
                               text_color=theme.FG, fg_color="transparent", width=38)

        def _on_change(v):
            val_lbl.configure(text=f"{float(v):.0f}")
            if command:
                command(v)

        sl = ctk.CTkSlider(row, from_=from_, to=to, variable=var, width=length,
                           height=16, fg_color=theme.BORDER,
                           progress_color=theme.PURPLE, button_color=theme.CYAN,
                           button_hover_color=theme.CYAN, command=_on_change)
        sl.pack(side=tk.LEFT, padx=(4, 0))
        val_lbl.pack(side=tk.LEFT, padx=(6, 0))
        if on_release:
            sl.bind("<ButtonRelease-1>", lambda e: on_release())
        return var

    def _opt_button(self, parent, text: str, cmd, primary=False, icon=None, width=140) -> ctk.CTkButton:
        kwargs = dict(
            text=text, width=width, height=34, corner_radius=11, command=cmd,
            fg_color=theme.PURPLE if primary else theme.BORDER,
            hover_color="#7C3AED" if primary else theme.CARD_HI,
            text_color=theme.FG,
            font=ctk.CTkFont(size=12, weight="bold" if primary else "normal"))
        if icon:
            kwargs.update(image=self._ico(icon), compound=tk.LEFT)
        return ctk.CTkButton(parent, **kwargs)

    def _opt_radio(self, parent, text: str, variable, value, command=None) -> ctk.CTkRadioButton:
        return ctk.CTkRadioButton(
            parent, text=text, variable=variable, value=value, command=command,
            font=ctk.CTkFont(size=11), text_color=theme.FG,
            bg_color="transparent", fg_color=theme.CYAN,
            radiobutton_width=16, radiobutton_height=16,
            border_color=theme.BORDER, hover_color=theme.CARD_HI,
            border_width_unchecked=2, border_width_checked=5)

    # ---------------------------------------------------------- 工具面板
    def switch_tab(self, key: str) -> None:
        self.tool_tab = key
        for k, item in self.tool_buttons.items():
            self._set_nav_active(item, k == key)
        self._set_nav_active(self.nav_open, False)
        self.tool = "none"
        self.rect = None
        self.place_point = None
        self._clear_options()
        if key == "bg":
            self._options_bg()
        elif key == "cutout":
            self._options_cutout()
        elif key == "text":
            self._options_text()
        elif key == "crop":
            self._options_crop()
        elif key == "rotate":
            self._options_rotate()
        else:
            self._options_transform()
        self._redraw()

    def _options_bg(self) -> None:
        c1 = self._opt_col("去背景 · 智能")
        self.bg_tol = self._opt_scale(c1.body, "颜色容差", 10, 90, 42,
                                      lambda _: self._debounce("bg", 180, self.apply_auto_now))
        self.bg_iter = self._opt_scale(c1.body, "精细度", 1, 8, 4,
                                       lambda _: self._debounce("bg", 180, self.apply_auto_now))
        self.bg_feather = self._opt_scale(c1.body, "边缘羽化", 0, 40, 12,
                                          lambda _: self._debounce("bg", 180, self.apply_auto_now))
        c2 = self._opt_col("采样方式")
        self.sample_mode = tk.StringVar(value="corners")
        self._opt_radio(c2.body, "自动四边采样", self.sample_mode, "corners").pack(anchor="w", pady=2)
        self._opt_radio(c2.body, "Ctrl+点击手动采样", self.sample_mode, "manual").pack(anchor="w", pady=2)
        self.sample_label = ctk.CTkLabel(c2.body, text="采样点：0", font=ctk.CTkFont(size=11),
                                         text_color=theme.MUTED, fg_color="transparent")
        self.sample_label.pack(anchor="w", pady=4)
        self._opt_button(c2.body, "清除采样点", self.clear_samples, icon=None, width=130).pack(anchor="w")
        c3 = self._opt_col("一键处理")
        self._opt_button(c3.body, "✨ 自动去背景", self.apply_auto_now,
                         primary=True, width=160).pack(pady=3)
        self._opt_button(c3.body, "按采样色去背", self.apply_color_now, width=160).pack(pady=3)
        ctk.CTkLabel(c3.body, text="调节参数即实时生效\n可随时用顶部 ↶ 撤销",
                     font=ctk.CTkFont(size=10), text_color=theme.MUTED,
                     fg_color="transparent", justify="left").pack(anchor="w", pady=(6, 0))

    def _options_cutout(self) -> None:
        c1 = self._opt_col("抠图 · 工具")
        self.tool_var = tk.StringVar(value="rect")
        for txt, val in [("矩形框选", "rect"), ("前景笔刷（保留）", "fg"), ("背景笔刷（擦除）", "bg")]:
            self._opt_radio(c1.body, txt, self.tool_var, val,
                            self._on_tool_change).pack(anchor="w", pady=2)
        c2 = self._opt_col("参数（即时生效）")
        self.brush_var = self._opt_scale(c2.body, "笔刷半径", 3, 60, 16,
                                         lambda _: self._on_brush_change())
        self.cut_iter = self._opt_scale(c2.body, "精细度", 1, 8, 5, lambda _: None)
        self.cut_feather = self._opt_scale(c2.body, "边缘羽化", 0, 40, 10, lambda _: None)
        c3 = self._opt_col("执行")
        self._opt_button(c3.body, "✂ 开始抠图", self.apply_brush_now,
                         primary=True, width=150).pack(pady=3)
        self._opt_button(c3.body, "清除标记 / 重选", self.clear_marks, width=150).pack(pady=3)
        ctk.CTkLabel(c3.body, text="选工具后在画布标记，\n点「开始抠图」即生效",
                     font=ctk.CTkFont(size=10), text_color=theme.MUTED,
                     fg_color="transparent", justify="left").pack(anchor="w", pady=(6, 0))

    def _options_text(self) -> None:
        c1 = self._opt_col("① 采样参考样式")
        self._opt_button(c1.body, "▣ 框选参考文字", self._start_sample, width=160).pack(pady=2)
        self.ref_text_v = tk.StringVar(value="参考文字")
        ctk.CTkEntry(c1.body, textvariable=self.ref_text_v, height=32,
                     fg_color=theme.CARD_HI, border_color=theme.BORDER,
                     font=ctk.CTkFont(size=12)).pack(fill=tk.X, pady=2)
        self._opt_button(c1.body, "🔍 分析样式", self.analyze_style, width=160).pack(pady=2)
        c2 = self._opt_col("② 识别结果（可微调）")
        self.font_combo = ctk.CTkComboBox(c2.body, values=self.font_names, width=190,
                                          fg_color=theme.CARD_HI, border_color=theme.BORDER,
                                          dropdown_fg_color=theme.CARD,
                                          font=ctk.CTkFont(size=11))
        if self._default_font_name:
            self.font_combo.set(self._default_font_name)
        self.font_combo.pack(pady=2)
        row = ctk.CTkFrame(c2.body, fg_color="transparent")
        row.pack(fill=tk.X, pady=2)
        ctk.CTkLabel(row, text="字号", font=ctk.CTkFont(size=10), text_color=theme.MUTED,
                     fg_color="transparent").pack(side=tk.LEFT)
        self.font_size = tk.IntVar(value=48)
        ctk.CTkEntry(row, textvariable=self.font_size, width=60, height=28,
                     fg_color=theme.CARD_HI, border_color=theme.BORDER,
                     font=ctk.CTkFont(size=11)).pack(side=tk.LEFT, padx=4)
        ctk.CTkLabel(row, text="倾斜°", font=ctk.CTkFont(size=10), text_color=theme.MUTED,
                     fg_color="transparent").pack(side=tk.LEFT)
        self.font_angle = tk.DoubleVar(value=0)
        ctk.CTkEntry(row, textvariable=self.font_angle, width=56, height=28,
                     fg_color=theme.CARD_HI, border_color=theme.BORDER,
                     font=ctk.CTkFont(size=11)).pack(side=tk.LEFT, padx=4)
        self.style_info = ctk.CTkLabel(c2.body, text="尚未分析", font=ctk.CTkFont(size=10),
                                       text_color=theme.MUTED, fg_color="transparent",
                                       anchor="w", justify="left")
        self.style_info.pack(anchor="w", pady=2)
        c3 = self._opt_col("③ 输入并放置")
        self.text_box_v = tk.StringVar(value="新文字")
        ctk.CTkEntry(c3.body, textvariable=self.text_box_v, height=32,
                     fg_color=theme.CARD_HI, border_color=theme.BORDER,
                     font=ctk.CTkFont(size=12)).pack(fill=tk.X, pady=2)
        self._opt_button(c3.body, "◎ 点击图片选位置", self._start_place, width=150).pack(pady=2)
        self._opt_button(c3.body, "T 合成文字", self.generate_text, primary=True, width=150).pack(pady=2)

    def _options_crop(self) -> None:
        c1 = self._opt_col("裁剪")
        self._opt_button(c1.body, "▣ 框选裁剪区域", self._start_crop, width=170).pack(pady=4)
        ctk.CTkLabel(c1.body, text="在画布拖拽出矩形，\n松开鼠标即刻裁剪。",
                     font=ctk.CTkFont(size=11), text_color=theme.MUTED,
                     fg_color="transparent", justify="left").pack(anchor="w", pady=(4, 0))
        c2 = self._opt_col("快捷比例")
        row = ctk.CTkFrame(c2.body, fg_color="transparent")
        row.pack(pady=4)
        for txt, r in [("1:1", 1.0), ("4:3", 4 / 3), ("16:9", 16 / 9)]:
            self._opt_button(row, txt, lambda rr=r: self._crop_ratio(rr), width=56).pack(side=tk.LEFT, padx=3)

    def _options_rotate(self) -> None:
        c1 = self._opt_col("90° 旋转")
        row = ctk.CTkFrame(c1.body, fg_color="transparent")
        row.pack(pady=4)
        self._opt_button(row, "↶ 左转", lambda: self.apply_rotate90(-1), width=70).pack(side=tk.LEFT, padx=2)
        self._opt_button(row, "↷ 右转", lambda: self.apply_rotate90(1), width=70).pack(side=tk.LEFT, padx=2)
        c2 = self._opt_col("任意角度（即时）")
        self.rot_var = self._opt_scale(c2.body, "角度", -180, 180, 0,
                                       lambda _: self._debounce("rot", 220, self._rotate_live),
                                       on_release=self._rotate_commit)
        ctk.CTkLabel(c2.body, text="拖动滑块实时旋转，\n松开即定稿。",
                     font=ctk.CTkFont(size=10), text_color=theme.MUTED,
                     fg_color="transparent", justify="left").pack(anchor="w", pady=(4, 0))

    def _options_transform(self) -> None:
        c1 = self._opt_col("缩放（即时）")
        self.scale_var = self._opt_scale(c1.body, "比例 %", 10, 400, 100,
                                         lambda _: self._debounce("scale", 220, self._scale_live),
                                         on_release=self._scale_commit)
        ctk.CTkLabel(c1.body, text="拖动实时预览，松开定稿。",
                     font=ctk.CTkFont(size=10), text_color=theme.MUTED,
                     fg_color="transparent").pack(anchor="w", pady=(4, 0))
        c2 = self._opt_col("镜像翻转")
        row = ctk.CTkFrame(c2.body, fg_color="transparent")
        row.pack(pady=4)
        self._opt_button(row, "⇋ 水平", lambda: self.apply_flip("horizontal"), width=76).pack(side=tk.LEFT, padx=3)
        self._opt_button(row, "⇅ 垂直", lambda: self.apply_flip("vertical"), width=76).pack(side=tk.LEFT, padx=3)

    # ------------------------------------------------------------ 画布交互
    def _bind_keys(self) -> None:
        self.bind("<Control-o>", lambda e: self.open_image())
        self.bind("<Control-s>", lambda e: self.save_image())
        self.bind("<Control-z>", lambda e: self.undo())
        self.bind("<Control-y>", lambda e: self.redo())
        self.bind("<Control-Shift-Z>", lambda e: self.redo())

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _set_info(self) -> None:
        if self.image is None:
            self.info_var.set("")
        else:
            self.info_var.set(f"{self.image.width} × {self.image.height}  |  "
                              f"{os.path.basename(self.filename) if self.filename else '未保存'}")

    def push_history(self, image: Image.Image) -> None:
        self.history = self.history[:self.hidx + 1]
        self.history.append(image.copy())
        if len(self.history) > 40:
            self.history.pop(0)
        self.hidx = len(self.history) - 1
        self._update_nav_state()

    def _update_nav_state(self) -> None:
        self.btn_undo.configure(state="normal" if self.hidx > 0 else "disabled")
        self.btn_redo.configure(state="normal" if self.hidx < len(self.history) - 1 else "disabled")

    def _set_image(self, image: Image.Image, message: str, record: bool = True) -> None:
        self.image = image.convert("RGBA")
        if record:
            self.push_history(self.image)
        self._reset_marks()
        self._set_info()
        self._redraw()
        self.set_status(message)

    def undo(self) -> None:
        if self.hidx <= 0:
            return
        self.hidx -= 1
        self.image = self.history[self.hidx].copy()
        self._reset_marks()
        self._redraw()
        self._update_nav_state()
        self.set_status("已撤销")

    def redo(self) -> None:
        if self.hidx >= len(self.history) - 1:
            return
        self.hidx += 1
        self.image = self.history[self.hidx].copy()
        self._reset_marks()
        self._redraw()
        self._update_nav_state()
        self.set_status("已重做")

    def clear_samples(self) -> None:
        self.samples = []
        if hasattr(self, "sample_label"):
            self.sample_label.configure(text="采样点：0")
        self.set_status("已清除背景采样点")

    def clear_marks(self) -> None:
        self.rect = None
        self.place_point = None
        self._reset_marks()
        self._redraw()
        self.set_status("已清除标记与选框")

    def _reset_marks(self) -> None:
        if self.image is None:
            self.fg_mask_img = self.bg_mask_img = self.fg_overlay = self.bg_overlay = None
            return
        size = self.image.size
        self.fg_mask_img = Image.new("L", size, 0)
        self.bg_mask_img = Image.new("L", size, 0)
        self.fg_overlay = Image.new("RGBA", size, (0, 0, 0, 0))
        self.bg_overlay = Image.new("RGBA", size, (0, 0, 0, 0))

    def _on_tool_change(self) -> None:
        self.tool = self.tool_var.get()
        self.rect = None
        self._redraw()

    def _on_brush_change(self) -> None:
        self.brush_radius = int(self.brush_var.get()) if hasattr(self, "brush_var") else 16

    def _start_sample(self) -> None:
        if not self._require_image():
            return
        self.tool = "rect"
        self.set_status("在图片上拖拽框住参考文字，然后点「分析样式」")

    def _start_place(self) -> None:
        if not self._require_image():
            return
        self.tool = "place"
        self.set_status("在图片上点击选择文字放置位置")

    def _start_crop(self) -> None:
        if not self._require_image():
            return
        self.tool = "rect"
        self.set_status("在图片上拖拽出裁剪区域，松开鼠标即刻裁剪")

    def _on_canvas_resize(self, event) -> None:
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(50, self._redraw)

    def _canvas_to_image(self, cx: int, cy: int) -> tuple[int, int]:
        ox, oy = self._view_origin
        s = max(1e-6, self._view_scale)
        if self.image is None:
            return (0, 0)
        x = int(round((cx - ox) / s))
        y = int(round((cy - oy) / s))
        return (max(0, min(self.image.width - 1, x)), max(0, min(self.image.height - 1, y)))

    def _on_canvas_ctrl_click(self, event) -> None:
        if self.image is None:
            return
        if hasattr(self, "sample_mode") and self.sample_mode.get() != "manual":
            self.sample_mode.set("manual")
        p = self._canvas_to_image(event.x, event.y)
        self.samples.append(p)
        if hasattr(self, "sample_label"):
            self.sample_label.configure(text=f"采样点：{len(self.samples)}")
        self.set_status(f"已添加背景采样点 {p}")

    def _on_canvas_press(self, event) -> None:
        if self.image is None:
            self.open_image()
            return
        if self.tool == "place":
            self.place_point = self._canvas_to_image(event.x, event.y)
            self._redraw()
            self.set_status(f"放置位置：{self.place_point}，点「合成文字」完成")
            return
        p = self._canvas_to_image(event.x, event.y)
        self._drag_start = p
        self._last_point = p
        if self.tool == "rect":
            self.rect = (p[0], p[1], p[0], p[1])
            self._redraw()
        elif self.tool in ("fg", "bg"):
            self._paint(p, p)

    def _on_canvas_move(self, event) -> None:
        if self.image is None or self._drag_start is None:
            return
        p = self._canvas_to_image(event.x, event.y)
        if self.tool == "rect":
            x0, y0 = self._drag_start
            self.rect = (min(x0, p[0]), min(y0, p[1]), max(x0, p[0]), max(y0, p[1]))
            self._redraw()
        elif self.tool in ("fg", "bg"):
            self._paint(self._last_point or p, p)
            self._last_point = p

    def _on_canvas_release(self, event) -> None:
        rect = self.rect
        if rect is not None and rect[2] - rect[0] >= 4 and rect[3] - rect[1] >= 4:
            # 裁剪工具：松开即裁剪；其它工具保留选框待后续操作
            if self.tool_tab == "crop":
                self.apply_crop_now()
        self.rect = None if (rect is None or rect[2] - rect[0] < 4 or rect[3] - rect[1] < 4) else rect
        self._drag_start = None
        self._last_point = None
        self._redraw()

    def _on_pan_press(self, event) -> None:
        self._panning = True
        self._pan_start = (event.x, event.y)

    def _on_pan_move(self, event) -> None:
        if not self._panning or self._pan_start is None:
            return
        dx = event.x - self._pan_start[0]
        dy = event.y - self._pan_start[1]
        self._pan = (self._pan[0] + dx, self._pan[1] + dy)
        self._pan_start = (event.x, event.y)
        self._redraw()

    def _on_pan_release(self, event) -> None:
        self._panning = False
        self._pan_start = None

    def _on_wheel(self, event) -> None:
        self._zoom_by(1.12 if event.delta > 0 else 1 / 1.12, event)

    def _zoom_by(self, factor: float, event=None) -> None:
        old = self._zoom
        self._zoom = max(0.25, min(8.0, self._zoom * factor))
        if event is not None and self.image is not None:
            mx, my = event.x, event.y
            self._pan = (int(mx - (mx - self._pan[0]) * self._zoom / old),
                         int(my - (my - self._pan[1]) * self._zoom / old))
        self._redraw()

    def _paint(self, p0, p1) -> None:
        r = self.brush_radius
        is_fg = self.tool == "fg"
        mask_img = self.fg_mask_img if is_fg else self.bg_mask_img
        overlay = self.fg_overlay if is_fg else self.bg_overlay
        if mask_img is None or overlay is None:
            return
        color = (52, 211, 153, 110) if is_fg else (251, 113, 133, 110)
        md = ImageDraw.Draw(mask_img)
        od = ImageDraw.Draw(overlay)
        md.line([p0, p1], fill=255, width=r * 2)
        od.line([p0, p1], fill=color, width=r * 2)
        for x, y in (p0, p1):
            od.ellipse([x - r, y - r, x + r, y + r], fill=color)
        self._redraw()

    def _redraw(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        cw, ch = max(1, canvas.winfo_width()), max(1, canvas.winfo_height())
        if self.image is None:
            self._draw_empty_state(canvas, cw, ch)
            return

        disp = self.image.copy()
        if self.fg_overlay is not None:
            disp = Image.alpha_composite(disp, self.fg_overlay)
        if self.bg_overlay is not None:
            disp = Image.alpha_composite(disp, self.bg_overlay)

        pad = 40
        fit = min((cw - pad) / disp.width, (ch - pad) / disp.height)
        scale = max(0.05, fit * self._zoom)
        w, h = max(1, int(disp.width * scale)), max(1, int(disp.height * scale))
        ox, oy = (cw - w) // 2 + self._pan[0], (ch - h) // 2 + self._pan[1]
        self._view_origin = (ox, oy)
        self._view_scale = scale

        thumb = disp.resize((w, h), Image.Resampling.LANCZOS)
        cs = 14
        yy = (np.arange(h) // cs)[:, None]
        xx = (np.arange(w) // cs)[None, :]
        parity = ((yy + xx) % 2 == 0)
        bgpx = np.empty((h, w, 4), dtype=np.uint8)
        bgpx[:, :, :3] = np.where(parity[:, :, None], 38, 26).astype(np.uint8)
        bgpx[:, :, 3] = 255
        merged = Image.alpha_composite(Image.fromarray(bgpx, "RGBA"), thumb)
        self._photo = ImageTk.PhotoImage(merged)
        # 图片投影
        canvas.create_rectangle(ox - 2, oy - 2, ox + w + 2, oy + h + 2,
                                outline=theme.BORDER, width=1)
        canvas.create_image(ox, oy, image=self._photo, anchor="nw")

        if self.rect:
            x0, y0, x1, y1 = self.rect
            canvas.create_rectangle(ox + x0 * scale, oy + y0 * scale, ox + x1 * scale, oy + y1 * scale,
                                    outline=theme.CYAN, width=2, dash=(7, 4))
        if self.place_point:
            pxp, pyp = self.place_point
            cx, cy = ox + pxp * scale, oy + pyp * scale
            canvas.create_oval(cx - 8, cy - 8, cx + 8, cy + 8, outline=theme.PINK, width=2)
            canvas.create_line(cx - 13, cy, cx + 13, cy, fill=theme.PINK, width=1)
            canvas.create_line(cx, cy - 13, cx, cy + 13, fill=theme.PINK, width=1)

    def _draw_empty_state(self, canvas, cw: int, ch: int) -> None:
        """艺术化空状态：霓虹渐变圆环 + 加号 + 品牌提示。"""
        bw, bh = min(560, cw - 80), min(360, ch - 80)
        x0, y0 = (cw - bw) // 2, (ch - bh) // 2
        # 柔和光晕环
        cx, cy = cw // 2, y0 + bh // 2 - 24
        for r, col, wid in [(96, "#1C2A55", 1), (78, "#2A3B72", 1), (60, theme.PURPLE, 2)]:
            canvas.create_oval(cx - r, cy - r, cx + r, cy + r, outline=col, width=wid)
        # 加号（青紫）
        canvas.create_line(cx - 20, cy, cx + 20, cy, fill=theme.CYAN, width=5)
        canvas.create_line(cx, cy - 20, cx, cy + 20, fill=theme.CYAN, width=5)
        canvas.create_text(cw // 2, y0 + bh - 72, text="点击此处，开启创作",
                           fill=theme.FG, font=("Microsoft YaHei UI", 20, "bold"))
        canvas.create_text(cw // 2, y0 + bh - 38, text="拖入或直接点击选择图片 · 支持 PNG / JPG / BMP / WebP",
                           fill=theme.MUTED, font=("Microsoft YaHei UI", 10))

    # -------------------------------------------------------------- 文件
    def open_image(self) -> None:
        path = filedialog.askopenfilename(title="选择图片", filetypes=FILE_TYPES)
        if not path:
            return
        try:
            img = Image.open(path)
            img.load()
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc))
            return
        self.filename = path
        self.history, self.hidx = [], -1
        self.samples = []
        self._zoom, self._pan = 1.0, (0, 0)
        self._set_image(img, f"已打开：{os.path.basename(path)}")
        self._update_nav_state()

    def save_image(self) -> None:
        if self.image is None:
            messagebox.showinfo("提示", "请先打开或生成一张图片")
            return
        path = filedialog.asksaveasfilename(title="保存图片", filetypes=FILE_TYPES,
                                            defaultextension=".png", initialfile="SimplePS_output.png")
        if not path:
            return
        try:
            img = self.image
            if path.lower().endswith((".jpg", ".jpeg", ".bmp")):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.getchannel("A"))
                bg.save(path)
            else:
                img.convert("RGBA").save(path)
            self.filename = path
            self._set_info()
            self.set_status(f"已保存：{path}")
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))

    def _busy(self, fn, *args, **kwargs):
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            messagebox.showerror("处理失败", f"{type(exc).__name__}: {exc}")
            self.set_status(f"处理失败：{exc}")
            return None
        finally:
            self.configure(cursor="")

    def _require_image(self) -> bool:
        if self.image is None:
            messagebox.showinfo("提示", "请先点击画布选择一张图片")
            return False
        return True

    def _begin_live(self) -> None:
        """连续调节开始前的基线：用于滑块实时预览，避免污染撤销栈。"""
        if self.image is None:
            return
        if getattr(self, "_live_base", None) is None:
            self._live_base = self.image.copy()

    def _end_live(self, result: Image.Image, message: str) -> None:
        """连续调节定稿：记录一次撤销、清理基线。"""
        if result is not None:
            self._set_image(result, message, record=True)
        self._live_base = None

    # ------------------------------------------------------------ 去背景/抠图
    def apply_auto_now(self) -> None:
        if not self._require_image():
            return
        t0 = time.perf_counter()
        result = self._busy(auto_remove_background, self.image,
                            iterations=int(self.bg_iter.get()) if hasattr(self, "bg_iter") else 4,
                            tolerance=float(self.bg_tol.get()) if hasattr(self, "bg_tol") else 42)
        if result is not None:
            dt = time.perf_counter() - t0
            self._set_image(result, f"自动去背景完成 · {dt:.2f}s · 可撤销")

    def apply_color_now(self) -> None:
        if not self._require_image():
            return
        samples = self.samples if self.sample_mode.get() == "manual" and self.samples else None
        result = self._busy(remove_by_color, self.image, samples=samples,
                            tolerance=float(self.bg_tol.get()) if hasattr(self, "bg_tol") else 45,
                            softness=float(self.bg_soft.get()) if hasattr(self, "bg_soft") else 12)
        if result is not None:
            self._set_image(result, "按颜色去背景完成")

    def apply_brush_now(self) -> None:
        if not self._require_image():
            return
        fg = np.array(self.fg_mask_img) if self.fg_mask_img is not None else None
        bg = np.array(self.bg_mask_img) if self.bg_mask_img is not None else None
        if (fg is None or not fg.any()) and (bg is None or not bg.any()) and self.rect is None:
            messagebox.showinfo("提示", "请先用矩形框选，或用前景/背景笔刷标记")
            return
        result = self._busy(grabcut_with_marks, self.image, fg_mask=fg, bg_mask=bg,
                            rect=self.rect,
                            iterations=int(self.cut_iter.get()) if hasattr(self, "cut_iter") else 5,
                            feather=float(self.cut_feather.get()) / 10 if hasattr(self, "cut_feather") else 1.0)
        if result is not None:
            self._set_image(result, "抠图完成")

    # -------------------------------------------------------------- 字体模仿
    def _pick_color(self) -> None:
        rgb, _ = colorchooser.askcolor(color=self._hex(self.text_color), title="选择文字颜色")
        if rgb:
            self.text_color = [int(v) for v in rgb] + [255]

    @staticmethod
    def _hex(color) -> str:
        return "#{:02x}{:02x}{:02x}".format(*[int(v) for v in color[:3]])

    def analyze_style(self) -> None:
        if not self._require_image():
            return
        if self.rect is None:
            messagebox.showinfo("提示", "请先点「框选参考文字」并在图片上框住一行文字")
            return
        ref = self.ref_text_v.get().strip()
        self.set_status("正在分析字体样式，请稍候…")
        self.update_idletasks()

        def work(done, total, name):
            if done % 15 == 0:
                self.set_status(f"正在匹配字体 {done}/{total} · {name}")
                self.update_idletasks()

        style = self._busy(analyze_text_style, self.image, self.rect,
                           reference_text=ref or None, progress=work)
        if style is None:
            return
        self.style = style
        if style.font_name in self.font_paths:
            self.font_combo.set(style.font_name)
        self.font_size.set(int(style.size))
        self.font_angle.set(float(style.angle))
        self.text_color = list(style.color)
        self.style_info.configure(
            text=f"字体：{style.font_name}\n字号：{style.size} · 倾斜：{style.angle}°\n"
                 f"置信度：{style.confidence:.2f}")
        self.set_status("样式分析完成 · 输入新文字并选位置即可合成")

    def _current_style(self) -> TextStyle:
        style = self.style or TextStyle(font_path=self.font_paths.get(self.font_combo.get()),
                                        font_name=self.font_combo.get(), size=48, color=(30, 30, 30, 255))
        style.font_path = self.font_paths.get(self.font_combo.get(), style.font_path)
        style.font_name = self.font_combo.get()
        style.size = int(self.font_size.get())
        style.angle = float(self.font_angle.get())
        style.color = tuple(self.text_color)
        return style

    def generate_text(self) -> None:
        if not self._require_image():
            return
        text = self.text_box_v.get().strip()
        if not text:
            messagebox.showinfo("提示", "请先输入要生成的文字")
            return
        pos = self.place_point or (self.image.width // 2, self.image.height // 2)
        result = self._busy(compose_styled_text, self.image, text, self._current_style(), pos)
        if result is not None:
            self._set_image(result, f"文字已合成到 {pos} · 可撤销")

    # -------------------------------------------------------------- 图片变换
    def _rotate_live(self) -> None:
        if not self._require_image():
            return
        self._begin_live()
        base = self._live_base
        angle = float(self.rot_var.get())
        if abs(angle) < 0.5:
            if base is not None:
                self._set_image(base, "已复位", record=False)
            return
        result = self._busy(rotate_image, base if base is not None else self.image, angle)
        if result is not None:
            self._set_image(result, f"旋转 {angle:.0f}°", record=False)

    def _rotate_commit(self) -> None:
        if getattr(self, "_live_base", None) is not None and self.image is not None:
            self._end_live(self.image, f"旋转成功 · 已定稿")

    def _scale_live(self) -> None:
        if not self._require_image():
            return
        self._begin_live()
        base = self._live_base
        factor = self.scale_var.get() / 100.0
        if abs(factor - 1.0) < 0.01:
            if base is not None:
                self._set_image(base, "已复位", record=False)
            return
        result = self._busy(resize_image, base if base is not None else self.image, scale=factor)
        if result is not None:
            self._set_image(result, f"缩放 {factor:.2f}× → {result.width}×{result.height}", record=False)

    def _scale_commit(self) -> None:
        if getattr(self, "_live_base", None) is not None and self.image is not None:
            self._end_live(self.image, "缩放成功 · 已定稿")

    def apply_rotate90(self, times: int) -> None:
        if not self._require_image():
            return
        result = self._busy(rotate_90, self.image, times)
        if result is not None:
            self._set_image(result, f"旋转 {90 * times}° 完成")

    def apply_flip(self, direction: str) -> None:
        if not self._require_image():
            return
        result = self._busy(flip_image, self.image, direction)
        if result is not None:
            self._set_image(result, "镜像翻转完成")

    def _crop_ratio(self, ratio: float) -> None:
        if not self._require_image():
            return
        w, h = self.image.size
        if w / h > ratio:
            nw, nh = int(h * ratio), h
        else:
            nw, nh = w, int(w / ratio)
        x0, y0 = (w - nw) // 2, (h - nh) // 2
        result = self._busy(crop_image, self.image, (x0, y0, x0 + nw, y0 + nh))
        if result is not None:
            self._set_image(result, f"裁剪为 {ratio:.2f}:1 → {result.width}×{result.height}")

    def apply_crop_now(self) -> None:
        if not self._require_image() or self.rect is None:
            return
        rect = self.rect
        result = self._busy(crop_image, self.image, rect)
        if result is not None:
            self._set_image(result, f"裁剪完成 → {result.width}×{result.height}")


def run_gui() -> int:
    try:
        app = SimplePSApp()
    except Exception as exc:
        print(f"图形界面启动失败：{exc}")
        print("请使用命令行模式：SimplePS -i input.png -o output.png --mode auto")
        return 1
    app.mainloop()
    return 0
