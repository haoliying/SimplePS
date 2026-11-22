#!/usr/bin/env python3
"""SimplePS 入口：无参数启动图形界面，带参数进入命令行模式。"""

from __future__ import annotations

import sys


def main() -> int:
    argv = list(sys.argv[1:])

    if "--gui" in argv:
        argv.remove("--gui")
        show_gui = True
    else:
        show_gui = not argv  # 不带任何参数时启动 GUI

    if show_gui:
        from simpleps.app import run_gui
        return run_gui()

    from simpleps.cli import run_cli
    return run_cli(argv)


if __name__ == "__main__":
    raise SystemExit(main())
