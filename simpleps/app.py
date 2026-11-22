"""SimplePS 图形界面 — 现代化深色图像编辑器。

布局仿移动端图像软件：顶部操作栏 + 中央画布 + 底部工具 Tab + 工具属性面板。
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

# 深色主题配色
BG = "#1b1d23"
PANEL = "#23262e"
PANEL2 = "#2b2f39"
CARD = "#313642"
FG = "#e8ebf2"
MUTED = "#9aa3b2"
ACCENT = "#4f8cff"
ACCENT2 = "#22c3a6"
LINE = "#3a4050"


class SimplePSApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"SimplePS v{__version__} — 去背景 · 抠图 · 字体模仿 · 图片编辑")
        self.geometry("1280x840")
        self.minsize(1000, 680)
        self.configure(bg=BG)

        self.image: Image.Image | None = None
        self.filename: str | None = None
        self.history: list[Image.Image] = []
        self.hidx = -1

        self.samples: list[tuple[int, int]] = []
        self.rect: tuple[int, int, int, int] | None = None
        self.place_point: tuple[int, int] | None = None
        self.tool = "none"       # none / rect / fg / bg / place
        self.tool_tab = "bg"     # bg / cutout / text / transform
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
        self.set_status("准备就绪 · 打开图片或选择下方工具开始")

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
        s.configure("TFrame", background=BG)
        s.configure("Panel.TFrame", background=PANEL)
        s.configure("Card.TFrame", background=CARD)
        s.configure("TLabel", background=BG, foreground=FG, font=("Microsoft YaHei UI", 10))
        s.configure("Panel.TLabel", background=PANEL, foreground=FG)
        s.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=("Microsoft YaHei UI", 9))
        s.configure("Title.TLabel", background=BG, foreground=FG, font=("Microsoft YaHei UI", 15, "bold"))
        s.configure("Card.TLabel", background=CARD, foreground=FG)
        s.configure("TButton", font=("Microsoft YaHei UI", 10), padding=5)
        s.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                    borderwidth=0, focusthickness=0, padding=6)
        s.map("Accent.TButton", background=[("active", "#3d78e8")])
        s.configure("Tool.TButton", font=("Microsoft YaHei UI", 10), padding=(10, 6))
        s.configure("ActiveTool.TButton", background=ACCENT, foreground="#ffffff",
                    font=("Microsoft YaHei UI", 10, "bold"), padding=(10, 6))
        s.configure("TCheckbutton", background=PANEL, foreground=FG)
        s.configure("TRadiobutton", background=PANEL, foreground=FG)
        s.configure("TScale", background=PANEL, troughcolor=PANEL2)
        s.configure("TNotebook", background=PANEL, borderwidth=0)
        s.configure("TNotebook.Tab", background=PANEL2, foreground=MUTED, padding=(12, 6))
        s.map("TNotebook.Tab", background=[("selected", CARD)], foreground=[("selected", FG)])

    # -------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # ---------- 顶部操作栏 ----------
        top = tk.Frame(self, bg=BG, height=58)
        top.grid(row=0, column=0, sticky="ew", padx=14, pady=(8, 4))
        tk.Label(top, text="SimplePS", bg=BG, fg=FG,
                 font=("Microsoft YaHei UI", 17, "bold")).pack(side=tk.LEFT)
        tk.Label(top, text="  图像工作室", bg=BG, fg=MUTED,
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
        tk.Frame(top, bg=BG, width=24).pack(side=tk.LEFT)
        for text, cmd in [("打开", self.open_image), ("保存", self.save_image),
                          ("撤销", self.undo), ("重做", self.redo)]:
            tk.Button(top, text=text, command=cmd, bg=PANEL2, fg=FG,
                      activebackground=CARD, activeforeground=FG, relief=tk.FLAT,
                      font=("Microsoft YaHei UI", 10), padx=14, pady=5).pack(side=tk.LEFT, padx=3)
        tk.Button(top, text="帮助", command=self._show_help_dialog, bg=PANEL2, fg=MUTED,
                  activebackground=CARD, relief=tk.FLAT, font=("Microsoft YaHei UI", 10),
                  padx=12, pady=5).pack(side=tk.RIGHT, padx=3)

        # ---------- 主体：画布 + 属性面板 ----------
        main = ttk.Frame(self)
        main.grid(row=1, column=0, sticky="nsew", padx=14)
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=0)
        main.rowconfigure(0, weight=1)

        self._build_canvas(main)

        props = ttk.Frame(main, style="Panel.TFrame", width=330)
        props.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=(0, 4))
        props.grid_propagate(False)
        self.props = props

        # ---------- 底部工具 Tab ----------
        bottom = tk.Frame(self, bg=PANEL, height=70)
        bottom.grid(row=2, column=0, sticky="ew", padx=14, pady=(6, 8))
        self.tool_buttons: dict[str, tk.Button] = {}
        for key, icon, label in [("bg", "◐", "去背景"), ("cutout", "✂", "抠图"),
                                 ("text", "T", "字体模仿"), ("transform", "⤢", "变换")]:
            btn = tk.Button(bottom, text=f"{icon}\n{label}", command=lambda k=key: self.switch_tab(k),
                            bg=PANEL2, fg=MUTED, activebackground=CARD, activeforeground=FG,
                            relief=tk.FLAT, font=("Microsoft YaHei UI", 11), width=9, height=2)
            btn.pack(side=tk.LEFT, padx=5, pady=6)
            self.tool_buttons[key] = btn
        tk.Label(bottom, text="滚轮缩放 · 中键拖拽平移 · Ctrl+Z 撤销", bg=PANEL, fg=MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(side=tk.RIGHT, padx=12)

        # ---------- 状态栏 ----------
        status = tk.Frame(self, bg=BG, height=24)
        status.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 6))
        self.status_var = tk.StringVar(value="")
        tk.Label(status, textvariable=self.status_var, bg=BG, fg=MUTED, anchor="w",
                 font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.info_var = tk.StringVar(value="")
        tk.Label(status, textvariable=self.info_var, bg=BG, fg=ACCENT2, anchor="e",
                 font=("Consolas", 9)).pack(side=tk.RIGHT)

        self.switch_tab("bg")

    def _build_canvas(self, parent: ttk.Frame) -> None:
        wrap = tk.Frame(parent, bg="#12141a")
        wrap.grid(row=0, column=0, sticky="nsew")
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(wrap, bg="#12141a", highlightthickness=0)
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

    # ---------------------------------------------------------- 属性面板
    def _clear_props(self) -> None:
        for w in self.props.winfo_children():
            w.destroy()

    def _card(self, title: str) -> ttk.Frame:
        f = ttk.Frame(self.props, style="Card.TFrame")
        f.pack(fill=tk.X, pady=(0, 10), padx=2)
        tk.Label(f, text=title, bg=CARD, fg=FG,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=12, pady=(10, 4))
        return f

    def _prop_scale(self, parent, label: str, from_, to, default, resolution,
                    command=None) -> tk.DoubleVar:
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill=tk.X, padx=12, pady=2)
        var = tk.DoubleVar(value=default)
        tk.Label(row, text=label, bg=CARD, fg=MUTED,
                 font=("Microsoft YaHei UI", 9), width=14, anchor="w").pack(side=tk.LEFT)
        tk.Scale(row, from_=from_, to=to, resolution=resolution, orient=tk.HORIZONTAL,
                 variable=var, length=180, showvalue=True, bg=CARD, fg=FG,
                 troughcolor=PANEL2, highlightthickness=0,
                 command=command if command else lambda _: None).pack(side=tk.LEFT)
        return var

    def switch_tab(self, key: str) -> None:
        self.tool_tab = key
        for k, btn in self.tool_buttons.items():
            if k == key:
                btn.configure(bg=ACCENT, fg="#ffffff",
                              font=("Microsoft YaHei UI", 11, "bold"))
            else:
                btn.configure(bg=PANEL2, fg=MUTED,
                              font=("Microsoft YaHei UI", 11))
        self.tool = "none"
        self.rect = None
        self.place_point = None
        self._clear_props()
        if key == "bg":
            self._props_bg()
        elif key == "cutout":
            self._props_cutout()
        elif key == "text":
            self._props_text()
        else:
            self._props_transform()
        self._redraw()

    def _props_bg(self) -> None:
        c = self._card("背景去除")
        self.bg_tol = self._prop_scale(c, "颜色容差", 10, 90, 42, 1)
        self.bg_soft = self._prop_scale(c, "边缘柔和", 0, 40, 12, 1)
        self.bg_iter = self._prop_scale(c, "GrabCut 迭代", 1, 10, 5, 1)
        self.bg_feather = self._prop_scale(c, "羽化半径", 0, 4, 1.0, 0.1)
        self.sample_mode = tk.StringVar(value="corners")
        tk.Radiobutton(c, text="自动四边采样", variable=self.sample_mode, value="corners",
                       bg=CARD, fg=FG, selectcolor=PANEL2,
                       font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=12)
        tk.Radiobutton(c, text="手动（Ctrl+点击加采样点）", variable=self.sample_mode, value="manual",
                       bg=CARD, fg=FG, selectcolor=PANEL2,
                       font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=12)
        self.sample_label = ttk.Label(c, text="采样点：0", style="Muted.TLabel")
        self.sample_label.pack(anchor="w", padx=12, pady=2)
        ttk.Button(c, text="清除采样点", command=self.clear_samples).pack(fill=tk.X, padx=12, pady=4)
        ttk.Button(c, text="✨ 自动去背景", style="Accent.TButton",
                   command=self.apply_auto).pack(fill=tk.X, padx=12, pady=(8, 4))
        ttk.Button(c, text="按颜色去背景", command=self.apply_color).pack(fill=tk.X, padx=12, pady=4)
        ttk.Label(c, text="提示：纯色背景用「按颜色」；\n复杂背景用「自动」再到抠图页修正。",
                  style="Muted.TLabel", wraplength=290).pack(anchor="w", padx=12, pady=(6, 10))

    def _props_cutout(self) -> None:
        c = self._card("智能抠图")
        self.tool_var = tk.StringVar(value="rect")
        for txt, val in [("矩形框选", "rect"), ("前景笔刷（保留）", "fg"), ("背景笔刷（擦除）", "bg")]:
            tk.Radiobutton(c, text=txt, variable=self.tool_var, value=val,
                           command=self._on_tool_change, bg=CARD, fg=FG, selectcolor=PANEL2,
                           font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=12, pady=1)
        self.brush_var = tk.IntVar(value=16)
        self._prop_scale(c, "笔刷半径", 3, 60, 16, 1, lambda _: self._on_brush_change())
        self.cut_iter = self._prop_scale(c, "GrabCut 迭代", 1, 10, 6, 1)
        self.cut_feather = self._prop_scale(c, "羽化半径", 0, 4, 1.0, 0.1)
        ttk.Button(c, text="✂ 应用抠图", style="Accent.TButton",
                   command=self.apply_brush).pack(fill=tk.X, padx=12, pady=(10, 4))
        ttk.Button(c, text="清除标记 / 重选", command=self.clear_marks).pack(fill=tk.X, padx=12, pady=4)
        ttk.Label(c, text="拖拽矩形框住主体，或用绿/红笔刷标记后应用。",
                  style="Muted.TLabel", wraplength=290).pack(anchor="w", padx=12, pady=(6, 10))

    def _props_text(self) -> None:
        c = self._card("字体模仿 · 从图片采样")
        ttk.Label(c, text="① 框选图中文字，输入它的内容，点「分析样式」",
                  style="Muted.TLabel", wraplength=290).pack(anchor="w", padx=12, pady=(2, 4))
        tk.Button(c, text="▣ 框选参考文字区域", command=self._start_sample,
                  bg=PANEL2, fg=FG, relief=tk.FLAT, font=("Microsoft YaHei UI", 10),
                  padx=10, pady=5).pack(fill=tk.X, padx=12, pady=3)
        self.ref_text = tk.Text(c, height=2, font=("Microsoft YaHei UI", 10), bg=PANEL2, fg=FG,
                                insertbackground=FG, relief=tk.FLAT)
        self.ref_text.insert("1.0", "参考文字")
        self.ref_text.pack(fill=tk.X, padx=12, pady=3)
        ttk.Button(c, text="🔍 分析样式", command=self.analyze_style).pack(fill=tk.X, padx=12, pady=4)

        info = self._card("识别结果（可手动调整）")
        self.font_combo = ttk.Combobox(info, values=self.font_names, state="readonly")
        self.font_combo.set(self._default_font_name)
        self.font_combo.pack(fill=tk.X, padx=12, pady=3)
        row = tk.Frame(info, bg=CARD)
        row.pack(fill=tk.X, padx=12, pady=3)
        tk.Label(row, text="字号", bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        self.font_size = tk.IntVar(value=48)
        tk.Spinbox(row, from_=8, to=400, textvariable=self.font_size, width=7,
                   bg=PANEL2, fg=FG).pack(side=tk.LEFT, padx=6)
        tk.Label(row, text="倾斜°", bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        self.font_angle = tk.DoubleVar(value=0)
        tk.Spinbox(row, from_=-45, to=45, textvariable=self.font_angle, width=6,
                   bg=PANEL2, fg=FG).pack(side=tk.LEFT, padx=6)
        self.color_btn = tk.Button(info, text="文字颜色", command=self._pick_color,
                                   bg="#1e1e1e", fg="#ffffff", relief=tk.FLAT,
                                   font=("Microsoft YaHei UI", 9), pady=4)
        self.color_btn.pack(fill=tk.X, padx=12, pady=3)
        self.style_info = ttk.Label(info, text="尚未分析", style="Muted.TLabel")
        self.style_info.pack(anchor="w", padx=12, pady=(4, 2))

        c2 = self._card("② 输入新文字并放置")
        self.text_box = tk.Text(c2, height=2, font=("Microsoft YaHei UI", 10), bg=PANEL2, fg=FG,
                                insertbackground=FG, relief=tk.FLAT)
        self.text_box.insert("1.0", "新文字")
        self.text_box.pack(fill=tk.X, padx=12, pady=3)
        tk.Button(c2, text="◎ 在图片上点击选择位置", command=self._start_place,
                  bg=PANEL2, fg=FG, relief=tk.FLAT, font=("Microsoft YaHei UI", 10),
                  padx=10, pady=5).pack(fill=tk.X, padx=12, pady=3)
        ttk.Button(c2, text="T 合成到图片", style="Accent.TButton",
                   command=self.generate_text).pack(fill=tk.X, padx=12, pady=4)
        ttk.Button(c2, text="导出文字为 PNG", command=self.export_text).pack(fill=tk.X, padx=12, pady=4)

    def _props_transform(self) -> None:
        c = self._card("图片变换")
        ttk.Label(c, text="缩放", style="Muted.TLabel").pack(anchor="w", padx=12, pady=(4, 0))
        self.scale_var = tk.DoubleVar(value=100)
        self._prop_scale(c, "比例 %", 10, 400, 100, 5)
        row = tk.Frame(c, bg=CARD)
        row.pack(fill=tk.X, padx=12, pady=3)
        tk.Button(row, text="缩小 50%", command=lambda: self.apply_scale(0.5),
                  bg=PANEL2, fg=FG, relief=tk.FLAT, font=("Microsoft YaHei UI", 9), padx=8).pack(side=tk.LEFT, padx=2)
        tk.Button(row, text="放大 2×", command=lambda: self.apply_scale(2.0),
                  bg=PANEL2, fg=FG, relief=tk.FLAT, font=("Microsoft YaHei UI", 9), padx=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(c, text="按比例应用缩放", command=lambda: self.apply_scale(self.scale_var.get() / 100.0)).pack(
            fill=tk.X, padx=12, pady=4)

        c2 = self._card("旋转 / 翻转")
        row2 = tk.Frame(c2, bg=CARD)
        row2.pack(fill=tk.X, padx=12, pady=3)
        tk.Button(row2, text="↶ 90°", command=lambda: self.apply_rotate90(-1),
                  bg=PANEL2, fg=FG, relief=tk.FLAT, font=("Microsoft YaHei UI", 9), padx=8).pack(side=tk.LEFT, padx=2)
        tk.Button(row2, text="↷ 90°", command=lambda: self.apply_rotate90(1),
                  bg=PANEL2, fg=FG, relief=tk.FLAT, font=("Microsoft YaHei UI", 9), padx=8).pack(side=tk.LEFT, padx=2)
        tk.Button(row2, text="⇋ 水平", command=lambda: self.apply_flip("horizontal"),
                  bg=PANEL2, fg=FG, relief=tk.FLAT, font=("Microsoft YaHei UI", 9), padx=8).pack(side=tk.LEFT, padx=2)
        tk.Button(row2, text="⇅ 垂直", command=lambda: self.apply_flip("vertical"),
                  bg=PANEL2, fg=FG, relief=tk.FLAT, font=("Microsoft YaHei UI", 9), padx=8).pack(side=tk.LEFT, padx=2)
        self.rot_var = tk.DoubleVar(value=0)
        self._prop_scale(c2, "任意角度", -180, 180, 0, 1)
        ttk.Button(c2, text="应用旋转", command=lambda: self.apply_rotate(self.rot_var.get())).pack(
            fill=tk.X, padx=12, pady=4)

        c3 = self._card("裁剪")
        tk.Button(c3, text="▣ 框选裁剪区域", command=self._start_crop,
                  bg=PANEL2, fg=FG, relief=tk.FLAT, font=("Microsoft YaHei UI", 10),
                  padx=10, pady=5).pack(fill=tk.X, padx=12, pady=3)
        ttk.Button(c3, text="✂ 应用裁剪", style="Accent.TButton",
                   command=self.apply_crop).pack(fill=tk.X, padx=12, pady=4)
        ttk.Label(c3, text="在画布上拖拽出矩形后应用，可撤销返回。",
                  style="Muted.TLabel", wraplength=290).pack(anchor="w", padx=12, pady=(4, 10))

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
        self.brush_radius = int(self.brush_var.get())

    def _start_sample(self) -> None:
        self.tool = "rect"
        self.set_status("在图片上拖拽框住参考文字，然后点「分析样式」")

    def _start_place(self) -> None:
        self.tool = "place"
        self.set_status("在图片上点击选择文字放置位置")

    def _start_crop(self) -> None:
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
        if self.image is None:
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
        """Windows 滚轮：event.delta 为 120 的整数倍。"""
        factor = 1.12 if event.delta > 0 else 1 / 1.12
        self._zoom_by(factor, event)

    def _zoom_by(self, factor: float, event=None) -> None:
        old = self._zoom
        self._zoom = max(0.25, min(8.0, self._zoom * factor))
        if event is not None and self.image is not None:
            # 以鼠标位置为中心缩放
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
            canvas.create_text(cw // 2, ch // 2,
                               text="打开一张图片开始编辑\n或使用下方工具",
                               fill=MUTED, font=("Microsoft YaHei UI", 16), justify=tk.CENTER)
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
        # 向量化生成棋盘格底图，表示透明背景
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
        path = filedialog.askopenfilename(title="打开图片", filetypes=FILE_TYPES)
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
            messagebox.showinfo("提示", "请先打开一张图片")
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
            self._set_image(result, "自动去背景完成 · 可用撤销返回")

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
            messagebox.showinfo("提示", "请先点「框选参考文字区域」并在图片上框住一行文字")
            return
        ref = self.ref_text.get("1.0", tk.END).strip()
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
                 f"匹配置信度：{style.confidence:.2f}")
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
        text = self.text_box.get("1.0", tk.END).strip()
        if not text:
            messagebox.showinfo("提示", "请先输入要生成的文字")
            return
        pos = self.place_point or (self.image.width // 2, self.image.height // 2)
        result = self._busy(compose_styled_text, self.image, text, self._current_style(), pos)
        if result is not None:
            self._set_image(result, f"文字已合成到 {pos} · 可撤销返回")

    def export_text(self) -> None:
        text = self.text_box.get("1.0", tk.END).strip()
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

    def _show_help_dialog(self) -> None:
        messagebox.showinfo("SimplePS 使用说明",
            "1. 打开图片后，从底部选择工具。\n\n"
            "2. 去背景：纯色用「按颜色」，复杂背景用「自动去背景」。\n\n"
            "3. 抠图：拖拽矩形框住主体，或用绿/红笔刷标记后应用。\n\n"
            "4. 字体模仿：\n"
            "   · 点「框选参考文字区域」在图片上框住一行字；\n"
            "   · 输入图中文字内容，点「分析样式」识别字体/字号/倾斜/颜色；\n"
            "   · 输入新文字，点图片选位置，再点「合成到图片」。\n\n"
            "5. 变换：缩放、旋转、裁剪、翻转，均可 Ctrl+Z 撤销。\n\n"
            "6. 滚轮缩放画布，中键拖拽平移；Ctrl+O/S 打开/保存。")


def run_gui() -> int:
    try:
        app = SimplePSApp()
    except Exception as exc:
        print(f"图形界面启动失败：{exc}")
        print("请使用命令行模式：SimplePS -i input.png -o output.png --mode auto")
        return 1
    app.mainloop()
    return 0
