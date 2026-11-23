"""SimplePS 图形界面 — 华为相册风格图片编辑器。

布局：顶部简洁操作栏 + 全屏深色画布 + 工具选项条 + 底部图标工具栏。
无图片时点击画布任意位置即可选择图片。
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageDraw, ImageTk

from . import __version__
from .core import (
    TextStyle,
    analyze_text_style,
    auto_remove_background,
    clean_alpha,
    compose_styled_text,
    crop_image,
    flip_image,
    grabcut_with_marks,
    imitate_handwriting,
    rect_cutout,
    remove_by_color,
    render_text,
    resize_image,
    rotate_90,
    rotate_image,
)
from .core.typography import default_font_path, discover_fonts

FILE_TYPES = [
    ("PNG 图片", "*.png"), ("JPEG 图片", "*.jpg;*.jpeg"),
    ("BMP 图片", "*.bmp"), ("WebP 图片", "*.webp"), ("所有文件", "*.*"),
]

# 深色主题配色（华为相册风格）
BG = "#000000"
BAR = "#141414"
PANEL = "#1c1c1e"
PANEL2 = "#2c2c2e"
CARD = "#242426"
FG = "#f2f2f7"
MUTED = "#98989f"
ACCENT = "#0a84ff"
ACCENT2 = "#30d158"
LINE = "#3a3a3c"

# (key, 图标, 标题)
TOOLS = [
    ("bg", "◐", "去背景"),
    ("cutout", "✂", "抠图"),
    ("text", "T", "文字"),
    ("crop", "▢", "裁剪"),
    ("rotate", "⟳", "旋转"),
    ("transform", "⤢", "变换"),
]


class SimplePSApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"SimplePS v{__version__} — 图片编辑器")
        self.geometry("1280x820")
        self.minsize(940, 620)
        self.configure(bg=BG)

        self.image: Image.Image | None = None
        self.filename: str | None = None
        self.history: list[Image.Image] = []
        self.hidx = -1

        self.samples: list[tuple[int, int]] = []
        self.rect: tuple[int, int, int, int] | None = None
        self.place_point: tuple[int, int] | None = None
        self.tool = "none"       # none / rect / fg / bg / place
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

        self.text_color = [30, 30, 30, 255]
        self.style: TextStyle | None = None
        self._init_style()

        self._build_style()
        self._build_ui()
        self._bind_keys()
        self.set_status("点击图片区域选择照片，或点击下方工具开始编辑")

    # ------------------------------------------------------------ 样式
    def _init_style(self) -> None:
        fonts = discover_fonts()
        self.font_names = [f["name"] for f in fonts]
        self.font_paths = {f["name"]: f["path"] for f in fonts}
        dp = default_font_path()
        self._default_font_name = next((n for n, p in self.font_paths.items() if p == dp),
                                       self.font_names[0] if self.font_names else "")

    def _build_style(self) -> None:
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure("TFrame", background=PANEL)
        s.configure("TLabel", background=PANEL, foreground=FG,
                    font=("Microsoft YaHei UI", 10))
        s.configure("Muted.TLabel", background=PANEL, foreground=MUTED,
                    font=("Microsoft YaHei UI", 9))
        s.configure("TButton", font=("Microsoft YaHei UI", 10), padding=5)
        s.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                    borderwidth=0, focusthickness=0, padding=6)
        s.map("Accent.TButton", background=[("active", "#0070e0")])
        s.configure("TScale", background=PANEL, troughcolor=PANEL2)
        s.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2,
                    foreground=FG, selectbackground=ACCENT)

    # -------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # ---------- 顶部操作栏 ----------
        top = tk.Frame(self, bg=BAR, height=52)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_propagate(False)
        tk.Label(top, text="‹", bg=BAR, fg=MUTED,
                 font=("Microsoft YaHei UI", 22)).pack(side=tk.LEFT, padx=(14, 2))
        tk.Label(top, text="SimplePS", bg=BAR, fg=FG,
                 font=("Microsoft YaHei UI", 15, "bold")).pack(side=tk.LEFT, padx=(4, 2))
        tk.Label(top, text="  图片编辑", bg=BAR, fg=MUTED,
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
        right = tk.Frame(top, bg=BAR)
        right.pack(side=tk.RIGHT, padx=12)
        for text, cmd in [("↶", self.undo), ("↷", self.redo)]:
            tk.Button(right, text=text, command=cmd, bg=BAR, fg=FG,
                      activebackground=PANEL2, activeforeground=FG, relief=tk.FLAT,
                      font=("Microsoft YaHei UI", 17), width=3, bd=0).pack(side=tk.LEFT, padx=2)
        tk.Button(right, text="保存", command=self.save_image, bg=ACCENT, fg="#ffffff",
                  activebackground="#0070e0", activeforeground="#ffffff", relief=tk.FLAT,
                  font=("Microsoft YaHei UI", 11, "bold"), padx=16, pady=5, bd=0).pack(
            side=tk.LEFT, padx=(10, 2))

        # ---------- 中央画布（全屏，无右侧面板） ----------
        stage = tk.Frame(self, bg=BG)
        stage.grid(row=1, column=0, sticky="nsew")
        stage.columnconfigure(0, weight=1)
        stage.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(stage, bg=BG, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
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

        # ---------- 工具选项条（随工具切换） ----------
        self.options = tk.Frame(self, bg=PANEL, height=104)
        self.options.grid(row=2, column=0, sticky="ew")
        self.options.grid_propagate(False)
        self.options_inner = tk.Frame(self.options, bg=PANEL)
        self.options_inner.pack(fill=tk.BOTH, expand=True, padx=14, pady=8)

        # ---------- 底部图标工具栏 ----------
        nav = tk.Frame(self, bg=BAR, height=72)
        nav.grid(row=3, column=0, sticky="ew")
        nav.grid_propagate(False)
        # 打开按钮固定在最左
        self.nav_open = self._make_nav_item(nav, "⊕", "打开", self.open_image)
        self.nav_open.pack(side=tk.LEFT, padx=(18, 6), pady=6)
        sep = tk.Frame(nav, bg=LINE, width=1, height=40)
        sep.pack(side=tk.LEFT, pady=16, padx=4)
        self.tool_buttons: dict[str, tk.Frame] = {}
        for key, icon, label in TOOLS:
            item = self._make_nav_item(nav, icon, label, lambda k=key: self.switch_tab(k))
            item.pack(side=tk.LEFT, padx=6, pady=6)
            self.tool_buttons[key] = item

        # ---------- 状态栏 ----------
        status = tk.Frame(self, bg=BAR, height=22)
        status.grid(row=4, column=0, sticky="ew")
        status.grid_propagate(False)
        self.status_var = tk.StringVar(value="")
        tk.Label(status, textvariable=self.status_var, bg=BAR, fg=MUTED, anchor="w",
                 font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=14)
        self.info_var = tk.StringVar(value="")
        tk.Label(status, textvariable=self.info_var, bg=BAR, fg=ACCENT2, anchor="e",
                 font=("Consolas", 9)).pack(side=tk.RIGHT, padx=14)

        self.switch_tab("bg")

    def _make_nav_item(self, parent, icon: str, label: str, cmd) -> tk.Frame:
        """华为相册风格的底部图标按钮：图标 + 文字，选中态高亮。"""
        frame = tk.Frame(parent, bg=BAR, cursor="hand2", width=64, height=58)
        frame.pack_propagate(False)
        icon_lbl = tk.Label(frame, text=icon, bg=BAR, fg=MUTED,
                            font=("Segoe UI Symbol", 21))
        icon_lbl.pack(expand=True)
        text_lbl = tk.Label(frame, text=label, bg=BAR, fg=MUTED,
                            font=("Microsoft YaHei UI", 9))
        text_lbl.pack()
        frame.configure(icon_lbl=icon_lbl, text_lbl=text_lbl) if False else None
        frame.icon_lbl = icon_lbl
        frame.text_lbl = text_lbl
        for w in (frame, icon_lbl, text_lbl):
            w.bind("<Button-1>", lambda e: cmd())
        frame._active = False
        return frame

    def _set_nav_active(self, frame: tk.Frame, active: bool) -> None:
        frame._active = active
        color = ACCENT if active else MUTED
        bg = BAR
        frame.configure(bg=bg)
        frame.icon_lbl.configure(fg=color, bg=bg)
        frame.text_lbl.configure(fg=color, bg=bg,
                                 font=("Microsoft YaHei UI", 9, "bold" if active else "normal"))

    # ---------------------------------------------------------- 选项条控件
    def _clear_options(self) -> None:
        for w in self.options_inner.winfo_children():
            w.destroy()

    def _opt_col(self) -> tk.Frame:
        """选项条中的一列（竖直分区）。"""
        c = tk.Frame(self.options_inner, bg=PANEL)
        c.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 18))
        return c

    def _opt_title(self, parent, text: str) -> None:
        tk.Label(parent, text=text, bg=PANEL, fg=ACCENT,
                 font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", pady=(0, 4))

    def _opt_scale(self, parent, label: str, from_, to, default, resolution,
                   command=None, length=150) -> tk.DoubleVar:
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill=tk.X, pady=2)
        tk.Label(row, text=label, bg=PANEL, fg=MUTED,
                 font=("Microsoft YaHei UI", 9), width=11, anchor="w").pack(side=tk.LEFT)
        var = tk.DoubleVar(value=default)
        tk.Scale(row, from_=from_, to=to, resolution=resolution, orient=tk.HORIZONTAL,
                 variable=var, length=length, showvalue=True, bg=PANEL, fg=FG,
                 troughcolor=PANEL2, highlightthickness=0,
                 command=command if command else lambda _: None).pack(side=tk.LEFT)
        return var

    def _opt_button(self, parent, text: str, cmd, primary=False, width=13) -> tk.Widget:
        if primary:
            return ttk.Button(parent, text=text, command=cmd, style="Accent.TButton", width=width)
        return tk.Button(parent, text=text, command=cmd, bg=PANEL2, fg=FG,
                         activebackground=CARD, activeforeground=FG, relief=tk.FLAT,
                         font=("Microsoft YaHei UI", 10), padx=8, pady=4, bd=0, width=width)

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
        c1 = self._opt_col()
        self._opt_title(c1, "去背景 · 参数")
        self.bg_tol = self._opt_scale(c1, "颜色容差", 10, 90, 42, 1)
        self.bg_soft = self._opt_scale(c1, "边缘柔和", 0, 40, 12, 1)
        self.bg_iter = self._opt_scale(c1, "GrabCut 迭代", 1, 10, 5, 1)
        self.bg_feather = self._opt_scale(c1, "羽化半径", 0, 4, 1.0, 0.1)
        c2 = self._opt_col()
        self._opt_title(c2, "采样方式")
        self.sample_mode = tk.StringVar(value="corners")
        tk.Radiobutton(c2, text="自动四边采样", variable=self.sample_mode, value="corners",
                       bg=PANEL, fg=FG, selectcolor=PANEL2, activebackground=PANEL,
                       font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=1)
        tk.Radiobutton(c2, text="手动 Ctrl+点击加采样点", variable=self.sample_mode, value="manual",
                       bg=PANEL, fg=FG, selectcolor=PANEL2, activebackground=PANEL,
                       font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=1)
        self.sample_label = tk.Label(c2, text="采样点：0", bg=PANEL, fg=MUTED,
                                     font=("Microsoft YaHei UI", 9))
        self.sample_label.pack(anchor="w", pady=2)
        self._opt_button(c2, "清除采样点", self.clear_samples, width=18).pack(anchor="w", pady=2)
        c3 = self._opt_col()
        self._opt_title(c3, "执行")
        self._opt_button(c3, "✨ 自动去背景", self.apply_auto, primary=True, width=17).pack(pady=3)
        self._opt_button(c3, "按颜色去背景", self.apply_color, width=17).pack(pady=3)

    def _options_cutout(self) -> None:
        c1 = self._opt_col()
        self._opt_title(c1, "抠图 · 工具")
        self.tool_var = tk.StringVar(value="rect")
        for txt, val in [("矩形框选", "rect"), ("前景笔刷（保留）", "fg"), ("背景笔刷（擦除）", "bg")]:
            tk.Radiobutton(c1, text=txt, variable=self.tool_var, value=val,
                           command=self._on_tool_change, bg=PANEL, fg=FG, selectcolor=PANEL2,
                           activebackground=PANEL, font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=1)
        c2 = self._opt_col()
        self._opt_title(c2, "参数")
        self.brush_var = self._opt_scale(c2, "笔刷半径", 3, 60, 16, 1, lambda _: self._on_brush_change())
        self.cut_iter = self._opt_scale(c2, "GrabCut 迭代", 1, 10, 6, 1)
        self.cut_feather = self._opt_scale(c2, "羽化半径", 0, 4, 1.0, 0.1)
        c3 = self._opt_col()
        self._opt_title(c3, "执行")
        self._opt_button(c3, "✂ 应用抠图", self.apply_brush, primary=True, width=16).pack(pady=3)
        self._opt_button(c3, "清除标记 / 重选", self.clear_marks, width=16).pack(pady=3)

    def _options_text(self) -> None:
        c1 = self._opt_col()
        self._opt_title(c1, "① 从图片采样样式")
        self._opt_button(c1, "▣ 框选参考文字", self._start_sample, width=17).pack(pady=2)
        self.ref_text_v = tk.StringVar(value="参考文字")
        tk.Entry(c1, textvariable=self.ref_text_v, bg=PANEL2, fg=FG, insertbackground=FG,
                 relief=tk.FLAT, font=("Microsoft YaHei UI", 10), width=20).pack(pady=2)
        self._opt_button(c1, "🔍 分析样式", self.analyze_style, primary=True, width=17).pack(pady=2)
        c2 = self._opt_col()
        self._opt_title(c2, "识别结果（可微调）")
        self.font_combo = ttk.Combobox(c2, values=self.font_names, state="readonly", width=20)
        self.font_combo.set(self._default_font_name)
        self.font_combo.pack(pady=2)
        row = tk.Frame(c2, bg=PANEL)
        row.pack(fill=tk.X, pady=2)
        tk.Label(row, text="字号", bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        self.font_size = tk.IntVar(value=48)
        tk.Spinbox(row, from_=8, to=400, textvariable=self.font_size, width=6,
                   bg=PANEL2, fg=FG).pack(side=tk.LEFT, padx=4)
        tk.Label(row, text="倾斜°", bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        self.font_angle = tk.DoubleVar(value=0)
        tk.Spinbox(row, from_=-45, to=45, textvariable=self.font_angle, width=5,
                   bg=PANEL2, fg=FG).pack(side=tk.LEFT, padx=4)
        self.color_btn = tk.Button(c2, text="文字颜色", command=self._pick_color,
                                   bg="#1e1e1e", fg="#ffffff", relief=tk.FLAT,
                                   font=("Microsoft YaHei UI", 9), pady=3, bd=0, width=20)
        self.color_btn.pack(pady=2)
        self.style_info = tk.Label(c2, text="尚未分析", bg=PANEL, fg=MUTED,
                                   font=("Microsoft YaHei UI", 9), anchor="w", justify="left")
        self.style_info.pack(anchor="w", pady=2)
        c3 = self._opt_col()
        self._opt_title(c3, "② 输入新文字并放置")
        self.text_box_v = tk.StringVar(value="新文字")
        tk.Entry(c3, textvariable=self.text_box_v, bg=PANEL2, fg=FG, insertbackground=FG,
                 relief=tk.FLAT, font=("Microsoft YaHei UI", 10), width=20).pack(pady=2)
        self._opt_button(c3, "◎ 点击图片选位置", self._start_place, width=18).pack(pady=2)
        self._opt_button(c3, "T 合成到图片", self.generate_text, primary=True, width=18).pack(pady=2)
        self._opt_button(c3, "导出文字 PNG", self.export_text, width=18).pack(pady=2)

    def _options_crop(self) -> None:
        c1 = self._opt_col()
        self._opt_title(c1, "裁剪")
        self._opt_button(c1, "▣ 框选裁剪区域", self._start_crop, width=17).pack(pady=3)
        self._opt_button(c1, "✂ 应用裁剪", self.apply_crop, primary=True, width=17).pack(pady=3)
        c2 = self._opt_col()
        self._opt_title(c2, "说明")
        tk.Label(c2, text="在画布上拖拽出矩形后点「应用裁剪」，\n可随时用顶部 ↶ 撤销返回。",
                 bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9),
                 justify="left").pack(anchor="w")

    def _options_rotate(self) -> None:
        c1 = self._opt_col()
        self._opt_title(c1, "90° 旋转")
        row = tk.Frame(c1, bg=PANEL)
        row.pack(pady=3)
        self._opt_button(row, "↶ 左转 90°", lambda: self.apply_rotate90(-1), width=12).pack(side=tk.LEFT, padx=2)
        self._opt_button(row, "↷ 右转 90°", lambda: self.apply_rotate90(1), width=12).pack(side=tk.LEFT, padx=2)
        self._opt_title(c1, "任意角度")
        self.rot_var = self._opt_scale(c1, "角度", -180, 180, 0, 1)
        self._opt_button(c1, "应用旋转", lambda: self.apply_rotate(self.rot_var.get()),
                         primary=True, width=16).pack(pady=3)

    def _options_transform(self) -> None:
        c1 = self._opt_col()
        self._opt_title(c1, "缩放")
        self.scale_var = self._opt_scale(c1, "比例 %", 10, 400, 100, 5)
        row = tk.Frame(c1, bg=PANEL)
        row.pack(pady=3)
        self._opt_button(row, "缩小 50%", lambda: self.apply_scale(0.5), width=10).pack(side=tk.LEFT, padx=2)
        self._opt_button(row, "放大 2×", lambda: self.apply_scale(2.0), width=10).pack(side=tk.LEFT, padx=2)
        self._opt_button(c1, "按比例应用缩放",
                         lambda: self.apply_scale(self.scale_var.get() / 100.0),
                         primary=True, width=16).pack(pady=3)
        c2 = self._opt_col()
        self._opt_title(c2, "镜像翻转")
        row2 = tk.Frame(c2, bg=PANEL)
        row2.pack(pady=3)
        self._opt_button(row2, "⇋ 水平", lambda: self.apply_flip("horizontal"), width=11).pack(side=tk.LEFT, padx=2)
        self._opt_button(row2, "⇅ 垂直", lambda: self.apply_flip("vertical"), width=11).pack(side=tk.LEFT, padx=2)

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
        if len(self.history) > 30:
            self.history.pop(0)
        self.hidx = len(self.history) - 1

    def _set_image(self, image: Image.Image, message: str) -> None:
        self.image = image.convert("RGBA")
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
        self.set_status("已撤销")

    def redo(self) -> None:
        if self.hidx >= len(self.history) - 1:
            return
        self.hidx += 1
        self.image = self.history[self.hidx].copy()
        self._reset_marks()
        self._redraw()
        self.set_status("已重做")

    def clear_samples(self) -> None:
        self.samples = []
        if hasattr(self, "sample_label"):
            self.sample_label.config(text="采样点：0")
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
        self.set_status("在图片上拖拽出裁剪区域，然后点「应用裁剪」")

    def _on_canvas_resize(self, event) -> None:
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(60, self._redraw)

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
            self.sample_label.config(text=f"采样点：{len(self.samples)}")
        self.set_status(f"已添加背景采样点 {p}")

    def _on_canvas_press(self, event) -> None:
        # 无图片：点击画布任意位置直接选择图片
        if self.image is None:
            self.open_image()
            return
        if self.tool == "place":
            self.place_point = self._canvas_to_image(event.x, event.y)
            self._redraw()
            self.set_status(f"放置位置：{self.place_point}，点「合成到图片」完成")
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
        if self.rect is not None:
            x0, y0, x1, y1 = self.rect
            if x1 - x0 < 4 or y1 - y0 < 4:
                self.rect = None
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
        factor = 1.12 if event.delta > 0 else 1 / 1.12
        self._zoom_by(factor, event)

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
        color = (0, 235, 140, 100) if is_fg else (255, 70, 70, 100)
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
            # 华为相册风格空状态：虚线框 + 加号 + 提示
            bw, bh = min(420, cw - 60), min(260, ch - 60)
            x0, y0 = (cw - bw) // 2, (ch - bh) // 2
            x1, y1 = x0 + bw, y0 + bh
            canvas.create_rectangle(x0, y0, x1, y1, outline="#3a3a3c", width=2, dash=(8, 6))
            cx, cy = cw // 2, y0 + bh // 2 - 18
            canvas.create_oval(cx - 30, cy - 30, cx + 30, cy + 30, outline=ACCENT, width=3)
            canvas.create_line(cx - 14, cy, cx + 14, cy, fill=ACCENT, width=3)
            canvas.create_line(cx, cy - 14, cx, cy + 14, fill=ACCENT, width=3)
            canvas.create_text(cw // 2, y0 + bh - 56, text="点击此处选择图片",
                               fill=FG, font=("Microsoft YaHei UI", 15, "bold"))
            canvas.create_text(cw // 2, y0 + bh - 30, text="支持 PNG / JPG / BMP / WebP",
                               fill=MUTED, font=("Microsoft YaHei UI", 10))
            return

        disp = self.image.copy()
        if self.fg_overlay is not None:
            disp = Image.alpha_composite(disp, self.fg_overlay)
        if self.bg_overlay is not None:
            disp = Image.alpha_composite(disp, self.bg_overlay)

        pad = 36
        fit = min((cw - pad) / disp.width, (ch - pad) / disp.height)
        scale = max(0.05, fit * self._zoom)
        w, h = max(1, int(disp.width * scale)), max(1, int(disp.height * scale))
        ox, oy = (cw - w) // 2 + self._pan[0], (ch - h) // 2 + self._pan[1]
        self._view_origin = (ox, oy)
        self._view_scale = scale

        thumb = disp.resize((w, h), Image.Resampling.LANCZOS)
        cs = 12
        yy = (np.arange(h) // cs)[:, None]
        xx = (np.arange(w) // cs)[None, :]
        parity = ((yy + xx) % 2 == 0)
        bgpx = np.empty((h, w, 4), dtype=np.uint8)
        bgpx[:, :, :3] = np.where(parity[:, :, None], 42, 30).astype(np.uint8)
        bgpx[:, :, 3] = 255
        merged = Image.alpha_composite(Image.fromarray(bgpx, "RGBA"), thumb)
        self._photo = ImageTk.PhotoImage(merged)
        canvas.create_image(ox, oy, image=self._photo, anchor="nw")

        if self.rect:
            x0, y0, x1, y1 = self.rect
            canvas.create_rectangle(ox + x0 * scale, oy + y0 * scale, ox + x1 * scale, oy + y1 * scale,
                                    outline=ACCENT2, width=2, dash=(7, 4))
        if self.place_point:
            pxp, pyp = self.place_point
            cx, cy = ox + pxp * scale, oy + pyp * scale
            canvas.create_oval(cx - 7, cy - 7, cx + 7, cy + 7, outline=ACCENT, width=2)
            canvas.create_line(cx - 12, cy, cx + 12, cy, fill=ACCENT, width=1)
            canvas.create_line(cx, cy - 12, cx, cy + 12, fill=ACCENT, width=1)

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
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            messagebox.showerror("处理失败", f"{type(exc).__name__}: {exc}")
            self.set_status(f"处理失败：{exc}")
            return None
        finally:
            self.config(cursor="")

    def _require_image(self) -> bool:
        if self.image is None:
            messagebox.showinfo("提示", "请先点击画布选择一张图片")
            return False
        return True

    # ------------------------------------------------------------ 去背景/抠图
    def apply_auto(self) -> None:
        if not self._require_image():
            return
        result = self._busy(auto_remove_background, self.image,
                            iterations=int(self.bg_iter.get()),
                            tolerance=float(self.bg_tol.get()),
                            feather=float(self.bg_feather.get()))
        if result is not None:
            self._set_image(result, "自动去背景完成 · 可用 ↶ 撤销返回")

    def apply_color(self) -> None:
        if not self._require_image():
            return
        samples = self.samples if self.sample_mode.get() == "manual" and self.samples else None
        result = self._busy(remove_by_color, self.image, samples=samples,
                            tolerance=float(self.bg_tol.get()),
                            softness=float(self.bg_soft.get()),
                            feather=float(self.bg_feather.get()))
        if result is not None:
            self._set_image(result, "按颜色去背景完成")

    def apply_rect(self) -> None:
        if not self._require_image():
            return
        if self.rect is None:
            messagebox.showinfo("提示", "请先框住主体")
            return
        result = self._busy(rect_cutout, self.image, rect=self.rect,
                            iterations=int(self.cut_iter.get()), feather=float(self.cut_feather.get()))
        if result is not None:
            self._set_image(result, "矩形抠图完成")

    def apply_brush(self) -> None:
        if not self._require_image():
            return
        fg = np.array(self.fg_mask_img) if self.fg_mask_img is not None else None
        bg = np.array(self.bg_mask_img) if self.bg_mask_img is not None else None
        if (fg is None or not fg.any()) and (bg is None or not bg.any()) and self.rect is None:
            messagebox.showinfo("提示", "请先用矩形框选，或用前景/背景笔刷标记")
            return
        result = self._busy(grabcut_with_marks, self.image, fg_mask=fg, bg_mask=bg,
                            rect=self.rect, iterations=int(self.cut_iter.get()),
                            feather=float(self.cut_feather.get()))
        if result is not None:
            self._set_image(result, "抠图完成")

    # -------------------------------------------------------------- 字体模仿
    def _pick_color(self) -> None:
        rgb, _ = colorchooser.askcolor(color=self._hex(self.text_color), title="选择文字颜色")
        if rgb:
            self.text_color = [int(v) for v in rgb] + [255]
            self.color_btn.config(bg=self._hex(self.text_color),
                                  fg="#000" if sum(rgb) > 380 else "#fff")

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
        self.color_btn.config(bg=self._hex(self.text_color),
                              fg="#000" if sum(self.text_color[:3]) > 380 else "#fff")
        self.style_info.config(
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
            self._set_image(result, f"文字已合成到 {pos} · 可撤销返回")

    def export_text(self) -> None:
        text = self.text_box_v.get().strip()
        if not text:
            messagebox.showinfo("提示", "请先输入文字")
            return
        from .core.text_style import render_styled_text
        layer = self._busy(render_styled_text, text, self._current_style())
        if layer is None:
            return
        path = filedialog.asksaveasfilename(title="导出文字图层", filetypes=FILE_TYPES,
                                            defaultextension=".png", initialfile="SimplePS_text.png")
        if not path:
            return
        try:
            layer.save(path)
            self.set_status(f"文字图层已导出：{path}")
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))

    # -------------------------------------------------------------- 图片变换
    def apply_scale(self, factor: float) -> None:
        if not self._require_image():
            return
        result = self._busy(resize_image, self.image, scale=factor)
        if result is not None:
            self._set_image(result, f"缩放 {factor:.2f}× → {result.width}×{result.height}")

    def apply_rotate90(self, times: int) -> None:
        if not self._require_image():
            return
        result = self._busy(rotate_90, self.image, times)
        if result is not None:
            self._set_image(result, f"旋转 {90 * times}° 完成")

    def apply_rotate(self, angle: float) -> None:
        if not self._require_image():
            return
        result = self._busy(rotate_image, self.image, angle)
        if result is not None:
            self._set_image(result, f"旋转 {angle}° 完成")

    def apply_flip(self, direction: str) -> None:
        if not self._require_image():
            return
        result = self._busy(flip_image, self.image, direction)
        if result is not None:
            self._set_image(result, "镜像翻转完成")

    def apply_crop(self) -> None:
        if not self._require_image():
            return
        if self.rect is None:
            messagebox.showinfo("提示", "请先框选裁剪区域")
            return
        result = self._busy(crop_image, self.image, self.rect)
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
