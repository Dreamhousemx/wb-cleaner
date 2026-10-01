#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""在桌面创建一个带图标的应用快捷方式（可选工具，需要时自己执行）。

  python tools/make_shortcut.py                # 创建/更新桌面的「扫尘」快捷方式
  python tools/make_shortcut.py --name 净匣     # 换个显示名
  python tools/make_shortcut.py --remove       # 删除该快捷方式

说明：
  * 只在桌面新增一个 .lnk，不改动其它任何东西；已存在同名快捷方式会覆盖。
  * 中文全部由 Python 打印，.bat 保持纯 ASCII，避免批处理编码问题。
  * 它就是替代「右键快捷方式 → 属性 → 更改图标」的手工步骤。
"""

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_NAME = "扫尘"


def ps_quote(s):
    """PowerShell 单引号字符串：内部单引号翻倍。"""
    return "'" + str(s).replace("'", "''") + "'"


def run_ps(script):
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        return False, err or ("返回码 %d" % proc.returncode)
    return True, ""


def desktop_dir():
    candidate = os.path.join(os.path.expanduser("~"), "Desktop")
    if os.path.isdir(candidate):
        return candidate
    # 中文系统的桌面目录名可能被重定向
    for name in ("桌面", "OneDrive\\Desktop", "OneDrive\\桌面"):
        p = os.path.join(os.path.expanduser("~"), name)
        if os.path.isdir(p):
            return p
    return candidate


def main(argv=None):
    ap = argparse.ArgumentParser(description="创建带图标的桌面快捷方式")
    ap.add_argument("--name", default=DEFAULT_NAME, help="快捷方式显示名（默认：%s）" % DEFAULT_NAME)
    ap.add_argument("--remove", action="store_true", help="删除该快捷方式")
    args = ap.parse_args(argv)

    target = os.path.join(ROOT, "ui.bat")
    icon = os.path.join(ROOT, "icon", "app-icon.ico")
    lnk = os.path.join(desktop_dir(), "%s.lnk" % args.name)

    print("目标程序：%s" % target)
    print("图标文件：%s" % icon)
    print("快捷方式：%s" % lnk)

    if not os.path.isfile(target):
        print("✗ 找不到 %s" % target)
        return 1
    if not os.path.isfile(icon):
        print("✗ 找不到图标文件，请先运行： python icon/make_icon.py")
        return 1

    if args.remove:
        if os.path.isfile(lnk):
            os.remove(lnk)
            print("✓ 已删除快捷方式")
        else:
            print("· 该快捷方式不存在，无需删除")
        return 0

    script = (
        "$w = New-Object -ComObject WScript.Shell; "
        "$s = $w.CreateShortcut({lnk}); "
        "$s.TargetPath = {target}; "
        "$s.Arguments = ''; "
        "$s.WorkingDirectory = {wd}; "
        "$s.IconLocation = {icon}; "
        "$s.Description = {desc}; "
        "$s.WindowStyle = 1; "
        "$s.Save()"
    ).format(lnk=ps_quote(lnk), target=ps_quote(target), wd=ps_quote(ROOT),
             icon=ps_quote(icon + ",0"), desc=ps_quote("扫尘 — 清缓存、腾空间"))

    ok, err = run_ps(script)
    if ok and os.path.isfile(lnk):
        print("✓ 已在桌面创建「%s」，图标已设置" % args.name)
        return 0
    print("✗ 创建失败：%s" % (err or "快捷方式未生成"))
    print("  可以手工创建：右键 ui.bat → 发送到 → 桌面快捷方式，"
          "再右键属性 → 更改图标 → 选择 icon\\app-icon.ico")
    return 1


if __name__ == "__main__":
    sys.exit(main())
