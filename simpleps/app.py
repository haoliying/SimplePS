"""SimplePS 图形界面（tkinter）。"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageDraw, ImageTk

from . import __version__
from .core import (
    auto_remove_background,
    grabcut_with_marks,
    imitate_handwriting,
    rect_cutout,
    remove_by_color,
    render_text,
)
from .core.typography import default_font_path, discover_fonts
from .utils import fit_image_size

FILE_TYPES = [
    ("PNG 图片", "*.png"),
    ("JPEG 图片", "*.jpg;*.jpeg"),
    ("BMP 图片", "*.bmp"),
    ("WebP 图片", "*.webp"),
    ("所有文件", "*.*"),
]


class SimplePSApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"SimplePS v{__version__} — 去背景 / 抠图 / 字体模仿")
        self.geometry("1220x800")
        self.minsize(940, 640)

        self.image: Image.Image | None = None
        self.filename: str | None = None
        self.history: list[Image.Image] = []
        self.hidx = -1

        self.samples: list[tuple[int, int]] = []
        self.rect: tuple[int, int, int, int] | None = None
        self.tool = "none"          # none / rect / fg / bg
        self.brush_radius = 12
        self.fg_mask_img: Image.Image | None = None
        self.bg_mask_img: Image.Image | None = None
        self.fg_overlay: Image.Image | None = None
        self.bg_overlay: Image.Image | None = None
        self._drag_start = None
        self._last_point = None

        self._photo: ImageTk.PhotoImage | None = None
        self._view_origin = (0, 0)
        self._view_scale = 1.0
        self._resize_job = None

        self.text_color = [255, 255, 255, 255]
        self.grad_color = [70, 120, 255, 255]

        self._build_ui()
        self._bind_keys()
        self.set_status("准备就绪。打开一张图片开始，或在左侧切换功能。")

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="打开...            Ctrl+O", command=self.open_image)
        file_menu.add_command(label="保存为...          Ctrl+S", command=self.save_image)
        file_menu.add_separator()
        file_menu.add_command(label="撤销               Ctrl+Z", command=self.undo)
        file_menu.add_command(label="重做               Ctrl+Y", command=self.redo)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.destroy)
        menubar.add_cascade(label="文件", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="自动去背景", command=self.apply_auto)
        edit_menu.add_command(label="按颜色去背景", command=self.apply_color)
        edit_menu.add_separator()
        edit_menu.add_command(label="矩形抠图", command=self.apply_rect)
        edit_menu.add_command(label="笔刷抠图", command=self.apply_brush)
        edit_menu.add_separator()
        edit_menu.add_command(label="清除标记", command=self.clear_marks)
        menubar.add_cascade(label="编辑", menu=edit_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="使用说明", command=self._show_help_dialog)
        help_menu.add_command(label="关于 SimplePS", command=self._show_about)
        menubar.add_cascade(label="帮助", menu=help_menu)
        self.config(menu=menubar)

        toolbar = ttk.Frame(self, padding=(6, 5))
        toolbar.grid(row=0, column=0, sticky="ew")
        for i, (label, cmd) in enumerate([
            ("打开", self.open_image), ("保存", self.save_image),
            ("撤销", self.undo), ("重做", self.redo),
        ]):
            ttk.Button(toolbar, text=label, command=cmd).grid(row=0, column=i, padx=3)
        ttk.Separator(toolbar, orient=tk.VERTICAL).grid(row=0, column=4, sticky="ns", padx=8)
        for i, (label, cmd) in enumerate([
            ("自动去背景", self.apply_auto), ("颜色去背景", self.apply_color),
            ("矩形抠图", self.apply_rect), ("笔刷抠图", self.apply_brush),
            ("字体模仿", self.generate_text),
        ]):
            ttk.Button(toolbar, text=label, command=cmd).grid(row=0, column=5 + i, padx=3)

        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.grid(row=1, column=0, sticky="nsew")

        left = ttk.Frame(pane, width=340)
        pane.add(left, weight=0)
        right = ttk.Frame(pane)
        pane.add(right, weight=1)

        self._build_left(left)
        self._build_canvas(right)

        status = ttk.Frame(self, padding=(6, 4))
        status.grid(row=2, column=0, sticky="ew")
        self.status_var = tk.StringVar(value="")
        ttk.Label(status, textvariable=self.status_var, anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.info_var = tk.StringVar(value="")
        ttk.Label(status, textvariable=self.info_var, anchor="e").pack(side=tk.RIGHT)

    def _build_left(self, parent: ttk.Frame) -> None:
        nb = ttk.Notebook(parent)
        nb.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ---------------- 去背景 ----------------
        bg = ttk.Frame(nb, padding=10)
        nb.add(bg, text="去背景")
        self.bg_tol = self._scale(bg, "颜色容差", 10, 90, 42, 1, 0)
        self.bg_soft = self._scale(bg, "边缘柔和度", 0, 40, 12, 1, 1)
        self.bg_iter = self._scale(bg, "GrabCut 迭代", 1, 10, 5, 1, 2)
        self.bg_feather = self._scale(bg, "羽化半径", 0, 4, 1.0, 0.1, 3)

        ttk.Label(bg, text="采样方式：", font=("Microsoft YaHei", 10, "bold")).grid(
            row=4, column=0, sticky="w", pady=(12, 4))
        self.sample_mode = tk.StringVar(value="corners")
        ttk.Radiobutton(bg, text="自动（四边采样）", variable=self.sample_mode,
                        value="corners").grid(row=5, column=0, sticky="w")
        ttk.Radiobutton(bg, text="手动：按住 Ctrl 点击图片添加采样点", variable=self.sample_mode,
                        value="manual").grid(row=6, column=0, sticky="w")
        self.sample_label = ttk.Label(bg, text="当前采样点：0 个", foreground="#666")
        self.sample_label.grid(row=7, column=0, sticky="w", pady=(4, 2))
        ttk.Button(bg, text="清除采样点", command=self.clear_samples).grid(row=8, column=0, sticky="w")

        ttk.Button(bg, text="自动去背景", command=self.apply_auto).grid(row=9, column=0, sticky="ew", pady=(14, 4))
        ttk.Button(bg, text="按颜色去背景", command=self.apply_color).grid(row=10, column=0, sticky="ew")
        ttk.Label(bg, text="提示：纯色背景优先用「按颜色」；\n复杂背景用「自动」并在抠图页微调。",
                  foreground="#777", wraplength=290, justify=tk.LEFT).grid(row=11, column=0, sticky="w", pady=(10, 0))

        # ---------------- 抠图 ----------------
        cut = ttk.Frame(nb, padding=10)
        nb.add(cut, text="抠图")
        ttk.Label(cut, text="工具：", font=("Microsoft YaHei", 10, "bold")).grid(row=0, column=0, sticky="w")
        self.tool_var = tk.StringVar(value="rect")
        for i, (txt, val) in enumerate([
            ("矩形框选", "rect"), ("前景笔刷（保留）", "fg"), ("背景笔刷（擦除）", "bg")
        ]):
            ttk.Radiobutton(cut, text=txt, variable=self.tool_var, value=val,
                            command=self._on_tool_change).grid(row=1 + i, column=0, sticky="w")
        ttk.Label(cut, text="笔刷半径：").grid(row=4, column=0, sticky="w", pady=(6, 0))
        self.brush_var = tk.IntVar(value=12)
        tk.Scale(cut, from_=3, to=60, orient=tk.HORIZONTAL, variable=self.brush_var,
                 length=280, showvalue=True, command=lambda _: self._on_brush_change()).grid(row=5, column=0, sticky="ew")
        self.cut_iter = self._scale(cut, "GrabCut 迭代", 1, 10, 6, 1, 6)
        self.cut_feather = self._scale(cut, "羽化半径", 0, 4, 1.0, 0.1, 7)
        ttk.Button(cut, text="应用抠图", command=self.apply_brush).grid(row=8, column=0, sticky="ew", pady=(14, 4))
        ttk.Button(cut, text="清除标记 / 重选", command=self.clear_marks).grid(row=9, column=0, sticky="ew")
        ttk.Label(cut, text="操作：选「矩形框选」后在图上拖拽框住主体；\n或用笔刷涂抹绿色=保留、红色=擦除，再点应用。",
                  foreground="#777", wraplength=290, justify=tk.LEFT).grid(row=10, column=0, sticky="w", pady=(10, 0))

        # ---------------- 字体模仿 ----------------
        tx = ttk.Frame(nb, padding=10)
        nb.add(tx, text="字体模仿")
        ttk.Label(tx, text="输入文字：", font=("Microsoft YaHei", 10, "bold")).grid(row=0, column=0, sticky="w")
        self.text_box = tk.Text(tx, height=4, width=38, font=("Microsoft YaHei", 10))
        self.text_box.insert("1.0", "SimplePS 你好")
        self.text_box.grid(row=1, column=0, sticky="ew", pady=(2, 6))

        ttk.Label(tx, text="字体：").grid(row=2, column=0, sticky="w")
        fonts = discover_fonts()
        self.font_names = [f["name"] for f in fonts]
        self.font_paths = {f["name"]: f["path"] for f in fonts}
        self.font_combo = ttk.Combobox(tx, values=self.font_names, state="readonly", width=34)
        default_path = default_font_path()
        default_name = next((n for n, p in self.font_paths.items() if p == default_path),
                            self.font_names[0] if self.font_names else "")
        self.font_combo.set(default_name)
        self.font_combo.grid(row=3, column=0, sticky="ew")

        self.font_size = tk.IntVar(value=72)
        ttk.Label(tx, text="字号：").grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Spinbox(tx, from_=12, to=300, textvariable=self.font_size, width=10).grid(row=5, column=0, sticky="w")

        self.text_style = tk.StringVar(value="hand")
        ttk.Label(tx, text="风格：", font=("Microsoft YaHei", 10, "bold")).grid(row=6, column=0, sticky="w", pady=(8, 2))
        ttk.Radiobutton(tx, text="标准排版（支持渐变/描边/阴影）", variable=self.text_style,
                        value="normal").grid(row=7, column=0, sticky="w")
        ttk.Radiobutton(tx, text="手写模仿（逐字旋转抖动）", variable=self.text_style,
                        value="hand").grid(row=8, column=0, sticky="w")

        self.jitter = self._scale(tx, "手写抖动", 0, 14, 4, 1, 9)
        self.angle = self._scale(tx, "旋转范围", 0, 25, 8, 1, 10)
        self.stroke = self._scale(tx, "描边宽度", 0, 10, 0, 1, 11)

        self.grad_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(tx, text="启用渐变（主色 -> 渐变色）", variable=self.grad_on).grid(
            row=12, column=0, sticky="w", pady=(8, 2))

        color_row = ttk.Frame(tx)
        color_row.grid(row=13, column=0, sticky="ew", pady=4)
        self.color_btn = tk.Button(color_row, text="主色", command=self._pick_main_color,
                                   bg="#FFFFFF", relief=tk.RAISED, width=8)
        self.color_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.grad_btn = tk.Button(color_row, text="渐变色", command=self._pick_grad_color,
                                  bg="#4678FF", fg="white", relief=tk.RAISED, width=8)
        self.grad_btn.pack(side=tk.LEFT)

        ttk.Button(tx, text="生成到画布", command=self.generate_text).grid(row=14, column=0, sticky="ew", pady=(12, 3))
        ttk.Button(tx, text="导出为 PNG", command=self.export_text).grid(row=15, column=0, sticky="ew")

        # ---------------- 帮助 ----------------
        hp = ttk.Frame(nb, padding=12)
        nb.add(hp, text="帮助")
        help_text = (
            "SimplePS 使用说明\n"
            "========================\n\n"
            "1. 打开图片后，左侧选择功能。\n\n"
            "2. 去背景\n   · 纯色背景：采样四角，点「按颜色去背景」。\n   · 复杂背景：点「自动去背景」，\n     再到抠图页用笔刷修正。\n\n"
            "3. 抠图\n   · 矩形：在图片上拖拽框住主体。\n   · 前景笔刷（绿）：涂抹需要保留的区域。\n   · 背景笔刷（红）：涂抹需要删除的区域。\n   · 点「应用抠图」生成透明 PNG。\n\n"
            "4. 字体模仿\n   · 输入文字，选择字体和风格。\n   · 「生成到画布」替换当前图片；\n     「导出为 PNG」直接保存文字图层。\n\n"
            "5. 按住 Ctrl 在图片上点击可添加背景采样点。\n\n"
            "所有结果均保留透明通道，建议保存为 PNG。\n"
        )
        tk.Label(hp, text=help_text, justify=tk.LEFT, anchor="nw", font=("Microsoft YaHei", 10),
                 foreground="#333").pack(fill=tk.BOTH, expand=True)

    def _scale(self, parent, label: str, from_, to, default, resolution, row: int) -> tk.DoubleVar:
        var = tk.DoubleVar(value=default)
        ttk.Label(parent, text=f"{label}：").grid(row=row, column=0, sticky="w", pady=(6, 0))
        tk.Scale(parent, from_=from_, to=to, resolution=resolution, orient=tk.HORIZONTAL,
                 variable=var, length=280, showvalue=True).grid(row=row + 1, column=0, sticky="ew")
        return var

    def _build_canvas(self, parent: ttk.Frame) -> None:
        wrap = ttk.Frame(parent)
        wrap.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        hscroll = ttk.Scrollbar(wrap, orient=tk.HORIZONTAL)
        vscroll = ttk.Scrollbar(wrap, orient=tk.VERTICAL)
        self.canvas = tk.Canvas(wrap, bg="#20242b", highlightthickness=0,
                                xscrollcommand=hscroll.set, yscrollcommand=vscroll.set)
        hscroll.pack(side=tk.BOTTOM, fill=tk.X)
        vscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>", self._on_canvas_press)
        self.canvas.bind("<B1-Motion>", self._on_canvas_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.canvas.bind("<Control-ButtonPress-1>", self._on_canvas_ctrl_click)
        self.canvas.bind("<Configure>", self._on_canvas_resize)

    def _bind_keys(self) -> None:
        self.bind("<Control-o>", lambda e: self.open_image())
        self.bind("<Control-s>", lambda e: self.save_image())
        self.bind("<Control-z>", lambda e: self.undo())
        self.bind("<Control-y>", lambda e: self.redo())
        self.bind("<Control-Shift-Z>", lambda e: self.redo())

    # -------------------------------------------------------------- 状态
    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _set_info(self) -> None:
        if self.image is None:
            self.info_var.set("")
        else:
            self.info_var.set(f"{self.image.width} x {self.image.height}  |  "
                              f"{os.path.basename(self.filename) if self.filename else '未保存'}")

    def push_history(self, image: Image.Image) -> None:
        self.history = self.history[:self.hidx + 1]
        self.history.append(image.copy())
        if len(self.history) > 25:
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

    def _on_tool_change(self) -> None:
        self.tool = self.tool_var.get()
        if self.tool != "rect":
            self.rect = None
        self._redraw()

    def _on_brush_change(self) -> None:
        self.brush_radius = int(self.brush_var.get())

    def clear_samples(self) -> None:
        self.samples = []
        self.sample_label.config(text="当前采样点：0 个")
        self.set_status("已清除背景采样点")

    def clear_marks(self) -> None:
        self.rect = None
        self._reset_marks()
        self._redraw()
        self.set_status("已清除抠图标记与选框")

    def _reset_marks(self) -> None:
        if self.image is None:
            self.fg_mask_img = self.bg_mask_img = self.fg_overlay = self.bg_overlay = None
            return
        size = self.image.size
        self.fg_mask_img = Image.new("L", size, 0)
        self.bg_mask_img = Image.new("L", size, 0)
        self.fg_overlay = Image.new("RGBA", size, (0, 0, 0, 0))
        self.bg_overlay = Image.new("RGBA", size, (0, 0, 0, 0))

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
        self.sample_label.config(text="当前采样点：0 个")
        self._set_image(img, f"已打开：{os.path.basename(path)}")

    def save_image(self) -> None:
        if self.image is None:
            messagebox.showinfo("提示", "请先打开或生成一张图片")
            return
        path = filedialog.asksaveasfilename(title="保存图片", filetypes=FILE_TYPES,
                                            defaultextension=".png",
                                            initialfile="SimplePS_output.png")
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

    # ------------------------------------------------------------ 画布交互
    def _on_canvas_resize(self, event) -> None:
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(80, self._redraw)

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
        if self.sample_mode.get() != "manual":
            self.sample_mode.set("manual")
        p = self._canvas_to_image(event.x, event.y)
        self.samples.append(p)
        self.sample_label.config(text=f"当前采样点：{len(self.samples)} 个")
        self.set_status(f"已添加背景采样点 {p}")

    def _on_canvas_press(self, event) -> None:
        if self.image is None:
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

    def _paint(self, p0: tuple[int, int], p1: tuple[int, int]) -> None:
        r = self.brush_radius
        is_fg = self.tool == "fg"
        mask_img = self.fg_mask_img if is_fg else self.bg_mask_img
        overlay = self.fg_overlay if is_fg else self.bg_overlay
        if mask_img is None or overlay is None:
            return
        color = (0, 235, 140, 95) if is_fg else (255, 70, 70, 95)
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
        if self.image is None:
            canvas.create_text(canvas.winfo_width() // 2, canvas.winfo_height() // 2,
                               text="请点击「打开」载入图片\n或在左侧使用「字体模仿」生成文字",
                               fill="#8d96a6", font=("Microsoft YaHei", 15), justify=tk.CENTER)
            return
        cw, ch = max(1, canvas.winfo_width()), max(1, canvas.winfo_height())
        disp = self.image.copy()
        if self.fg_overlay is not None:
            disp = Image.alpha_composite(disp, self.fg_overlay)
        if self.bg_overlay is not None:
            disp = Image.alpha_composite(disp, self.bg_overlay)

        w, h = fit_image_size(disp.size, (cw, ch), padding=16)
        scaled = disp.resize((w, h), Image.Resampling.LANCZOS)
        self._photo = ImageTk.PhotoImage(scaled)
        ox, oy = max(0, (cw - w) // 2), max(0, (ch - h) // 2)
        self._view_origin = (ox, oy)
        self._view_scale = w / max(1, self.image.width)
        canvas.create_image(ox, oy, image=self._photo, anchor="nw")

        if self.rect:
            x0, y0, x1, y1 = self.rect
            s = self._view_scale
            canvas.create_rectangle(ox + x0 * s, oy + y0 * s, ox + x1 * s, oy + y1 * s,
                                    outline="#00e5ff", width=2, dash=(7, 4))
        # 棋盘格背景角落标记，提示透明通道
        canvas.create_text(cw - 12, ch - 12, text="透明背景以棋盘格显示（导出 PNG 保留）",
                           fill="#6b7480", anchor="se", font=("Microsoft YaHei", 9))

    # ------------------------------------------------------------ 功能调用
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

    def apply_auto(self) -> None:
        if not self._require_image():
            return
        result = self._busy(auto_remove_background, self.image,
                            iterations=int(self.bg_iter.get()),
                            tolerance=float(self.bg_tol.get()),
                            feather=float(self.bg_feather.get()))
        if result is not None:
            self._set_image(result, "自动去背景完成，可用撤销返回，或用笔刷继续修正")

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
            messagebox.showinfo("提示", "请先在左侧选「矩形框选」，然后在图片上拖拽框住主体")
            return
        result = self._busy(rect_cutout, self.image, rect=self.rect,
                            iterations=int(self.cut_iter.get()),
                            feather=float(self.cut_feather.get()))
        if result is not None:
            self._set_image(result, "矩形抠图完成")

    def apply_brush(self) -> None:
        if not self._require_image():
            return
        fg = np.array(self.fg_mask_img) if self.fg_mask_img is not None else None
        bg = np.array(self.bg_mask_img) if self.bg_mask_img is not None else None
        if fg is not None and not fg.any() and bg is not None and not bg.any() and self.rect is None:
            messagebox.showinfo("提示", "请先用矩形框选，或用前景/背景笔刷涂抹标记")
            return
        result = self._busy(grabcut_with_marks, self.image, fg_mask=fg, bg_mask=bg,
                            rect=self.rect, iterations=int(self.cut_iter.get()),
                            feather=float(self.cut_feather.get()))
        if result is not None:
            self._set_image(result, "笔刷抠图完成")

    # -------------------------------------------------------------- 文字
    def _get_text_args(self):
        text = self.text_box.get("1.0", tk.END).strip()
        if not text:
            messagebox.showinfo("提示", "请先输入要生成的文字")
            return None
        font_name = self.font_combo.get()
        font_path = self.font_paths.get(font_name)
        base = dict(text=text, font_path=font_path, size=int(self.font_size.get()),
                    color=tuple(self.text_color), stroke_width=int(self.stroke.get()))
        return base

    def _render_text_image(self):
        args = self._get_text_args()
        if args is None:
            return None
        if self.text_style.get() == "hand":
            return self._busy(imitate_handwriting, jitter=float(self.jitter.get()),
                              angle_range=float(self.angle.get()), **args)
        if self.grad_on.get():
            return self._busy(render_text, gradient_colors=[tuple(self.text_color),
                                                            tuple(self.grad_color)], **args)
        return self._busy(render_text, **args)

    def generate_text(self) -> None:
        result = self._render_text_image()
        if result is not None:
            self._set_image(result, "文字生成完成，可在左侧调整参数后重试")

    def export_text(self) -> None:
        result = self._render_text_image()
        if result is None:
            return
        path = filedialog.asksaveasfilename(title="导出文字图层", filetypes=FILE_TYPES,
                                            defaultextension=".png", initialfile="SimplePS_text.png")
        if not path:
            return
        try:
            result.convert("RGBA").save(path)
            self.set_status(f"文字图层已导出：{path}")
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))

    def _pick_main_color(self) -> None:
        rgb, hexcode = colorchooser.askcolor(color=self._hex(self.text_color), title="选择主色")
        if rgb:
            self.text_color = [int(v) for v in rgb] + [255]
            self.color_btn.config(bg=hexcode, fg="#000" if sum(rgb) > 380 else "#fff")

    def _pick_grad_color(self) -> None:
        rgb, hexcode = colorchooser.askcolor(color=self._hex(self.grad_color), title="选择渐变色")
        if rgb:
            self.grad_color = [int(v) for v in rgb] + [255]
            self.grad_btn.config(bg=hexcode, fg="#000" if sum(rgb) > 380 else "#fff")
            self.grad_on.set(True)

    @staticmethod
    def _hex(color) -> str:
        return "#{:02x}{:02x}{:02x}".format(*[int(v) for v in color[:3]])

    def _show_help_dialog(self) -> None:
        messagebox.showinfo("使用说明",
            "1. 打开图片后选择左侧功能。\n"
            "2. 去背景：纯色用「按颜色」，复杂背景用「自动」。\n"
            "3. 抠图：拖拽矩形框选主体，或用绿/红笔刷标记后应用。\n"
            "4. 字体模仿：输入文字，选择字体与风格，生成或导出 PNG。\n"
            "5. Ctrl+点击图片可添加背景采样点。\n"
            "6. Ctrl+Z 撤销，Ctrl+S 保存。")

    def _show_about(self) -> None:
        messagebox.showinfo("关于 SimplePS",
            f"SimplePS v{__version__}\n\n"
            "轻量级图像处理工具：去背景 / 抠图 / 字体模仿。\n"
            "基于 Python + OpenCV + Pillow，完全离线运行。")


def run_gui() -> int:
    try:
        app = SimplePSApp()
    except Exception as exc:
        print(f"图形界面启动失败：{exc}")
        print("请使用命令行模式：SimplePS -i input.png -o output.png --mode auto")
        return 1
    app.mainloop()
    return 0
