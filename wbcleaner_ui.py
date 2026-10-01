#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""WBCleaner 可视化界面 —— 启动本地服务并打开应用窗口。

用法
  python wbcleaner_ui.py                 启动界面（自动用 Edge/Chrome 应用窗口打开）
  python wbcleaner_ui.py --port 8791     指定端口
  python wbcleaner_ui.py --browser       用默认浏览器打开（不用应用窗口模式）
  python wbcleaner_ui.py --no-browser    只起服务，不自动打开

界面功能与命令行完全一致，只是把操作搬到了窗口里：
  扫描 / 分组勾选清理 / 预览 / 执行（隔离区或永久删除）/ 隔离区还原 / WinSxS(DISM) / 报告导出
"""

import argparse
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wbc import __version__, util, webui  # noqa: E402

APP_NAME = "扫尘"


def pick_port(start, span=25):
    for port in range(start, start + span):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
        finally:
            s.close()
    return start


def main(argv=None):
    ap = argparse.ArgumentParser(description="WBCleaner 可视化界面")
    ap.add_argument("--port", type=int, default=8791, help="监听端口（被占用时自动顺延）")
    ap.add_argument("--browser", action="store_true", help="用默认浏览器打开，而非应用窗口")
    ap.add_argument("--no-browser", action="store_true", help="只启动服务")
    ap.add_argument("--version", action="version", version="WBCleaner UI %s" % __version__)
    args = ap.parse_args(argv)

    port = pick_port(args.port)
    print("=" * 66)
    print("  %s  —— WorkBuddy / Codex / C盘 清理" % APP_NAME)
    print("  (Sweep) v%s    WinSxS 走 DISM，清理先入隔离区可还原" % __version__)
    print("  权限：%s" % ("管理员" if util.is_admin() else
                          "普通用户（系统级清理可在界面里一键提权重启）"))
    print("=" * 66)
    return webui.serve(port, open_browser=not args.no_browser,
                       app_window=not args.browser)


if __name__ == "__main__":
    sys.exit(main())
