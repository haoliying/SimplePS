# SimplePS

> 轻量级图像处理桌面工具：**去背景 / 抠图 / 字体模仿**，完全离线运行。

基于 Python + OpenCV + Pillow + tkinter。提供 Windows 单文件 EXE（无需安装 Python），也可作为命令行工具批处理。

---

## 功能

| 功能 | 说明 |
|---|---|
| 自动去背景 | 自动采样画面边缘颜色并用 GrabCut 精修，适合绝大多数主体/背景有色差的图片 |
| 按颜色去背景 | 取四角或手动采样点，按 Lab 颜色距离抠除纯色/渐变背景，边缘带羽化 |
| 矩形抠图 | 在图片上拖拽框住主体，GrabCut 自动分割 |
| 笔刷抠图 | 绿色笔刷标记保留区域、红色笔刷标记擦除区域，精细修正 |
| 字体模仿 | 扫描系统字体，支持描边、阴影、渐变、多行排版，以及逐字旋转抖动的**手写模仿** |
| 通用 | 打开/保存、PNG 透明通道、撤销/重做、Ctrl+O / Ctrl+S / Ctrl+Z 快捷键 |

---

## 下载 Windows EXE

- 仓库地址：<https://github.com/haoliying/SimplePS>
- 已构建好的 EXE：<https://github.com/haoliying/SimplePS/releases/tag/v1.0.0>（`SimplePS.exe` 与 `SimplePS-cli.exe`）

也可以进入仓库 **Actions** → **Build Windows EXE** → 点击最新一次成功运行，在 **Artifacts** 中下载 `SimplePS-Windows.zip`。

也可以给仓库打一个 `v*` 标签（例如 `v1.0.0`），CI 会自动构建并把 EXE 发布到 Releases：

```bash
git tag v1.0.0 && git push origin v1.0.0
```

解压后可得到：

- `SimplePS.exe` —— 图形界面版
- `SimplePS-cli.exe` —— 命令行版

---

## 本地运行

```bash
python -m pip install -r requirements.txt
python main.py                 # 启动图形界面
```

命令行模式：

```bash
# 自动去背景
python main.py -i examples/sample.png -o out.png --mode auto

# 按颜色去背景（自定义采样点）
python main.py -i photo.jpg -o cut.png --mode color --samples 0:0;639:0

# 矩形抠图
python main.py -i photo.jpg -o cut.png --mode rect --rect 80,40,160,170

# 文字渲染 / 手写模仿
python main.py --mode text --text "你好 SimplePS" --size 72 -o text.png
python main.py --mode hand --text "Hello 世界" --seed 8 -o hand.png

# 查看系统字体
python main.py --list-fonts
```

常用参数：`--tolerance`（颜色容差）、`--iterations`（GrabCut 迭代）、`--feather`（羽化）、`--font`（字体文件）、`--font-name`（字体名）、`--color`（颜色，如 `255,0,0,255`）、`--jitter` / `--angle`（手写抖动）。

---

## 自己打包 EXE

在 Windows 上执行：

```bat
build_windows.bat
```

脚本会安装依赖并生成 `dist\SimplePS.exe` 与 `dist\SimplePS-cli.exe`。等价于：

```bat
pyinstaller --clean --noconfirm SimplePS.spec
pyinstaller --clean --noconfirm SimplePS_CLI.spec
```

---

## 项目结构

```
SimplePS/
├── main.py                  # 入口（无参数 = GUI，有参数 = CLI）
├── simpleps/
│   ├── app.py               # tkinter 图形界面
│   ├── cli.py               # 命令行参数与流程
│   ├── utils.py             # PIL / NumPy / OpenCV 转换
│   └── core/
│       ├── background.py    # 去背景
│       ├── cutout.py        # 抠图
│       └── typography.py    # 字体渲染与手写模仿
├── tests/                   # 单元测试
├── assets/                  # 图标
├── examples/sample.png      # 示例图片
├── SimplePS.spec            # GUI EXE 打包配置
├── SimplePS_CLI.spec        # CLI EXE 打包配置
└── .github/workflows/       # 自动构建与发布
```

---

## 说明

- 去背景/抠图基于传统视觉算法，**无需下载模型**，离线可用；对边缘复杂（毛发、透明物体）的图片建议配合笔刷微调。
- 导出请优先使用 **PNG** 以保留透明通道；JPEG/BMP 会自动合成白色背景。
- 中文字体优先使用系统自带的 Noto CJK / 微软雅黑 / 黑体等，可在「字体模仿」页下拉选择。

## License

MIT
